"""Google Text-to-Speech Integration — Dual-Provider.

Zwei Pfade die wahlweise pro User aktiviert werden:

1. **Cloud TTS** (`provider="cloud_tts"`): Über die offizielle
   `google-cloud-texttospeech`-Library + Service-Account-JSON unter
   `data/google_tts_credentials.json`. Audio wird als MP3-Bytes zurückgegeben.
   Billing läuft direkt über das Cloud-Billing-Konto — kein AI-Studio-Hard-Cap.

2. **Gemini API direkt** (`provider="gemini_api"`): REST gegen
   `generativelanguage.googleapis.com` mit dem AI-Studio-API-Key (derselbe
   den `image_engine.py` für Image-Gen nutzt). Audio kommt als raw 16-bit
   signed PCM mono @ 24kHz; wir wrappen das beim Streaming in einen WAV-
   Header. Billing läuft über AI-Studio → der monatliche 8-€-Cap greift
   automatisch — d.h. dieser Pfad ist der "sichere" Default.

Bei Gemini-Voices ist die Generierung deutlich langsamer als bei Cloud-TTS-
Classic, und die API unterstützt kein natives Streaming für Gemini-Modelle.
Workaround: `synthesize_chunked` splittet den Text an Satzgrenzen, stößt alle
Stücke parallel an und streamt die Audio-Bytes in Reihenfolge an die App.
Das funktioniert für beide Provider — Input-Chunking ist API-unabhängig.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import random
import re
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Awaitable, Callable, Optional

import httpx

from pocket_claude.config import settings

log = logging.getLogger(__name__)


CREDENTIALS_FILENAME = "google_tts_credentials.json"


class TtsQuotaExceededError(RuntimeError):
    """Wird vom Gemini-API-Pfad geworfen wenn Google 429 RESOURCE_EXHAUSTED
    zurückgibt. Trägt den auslösenden API-Key + Retry-Hinweis, damit der
    Caller (server.py) den Key burnen + auf einen anderen ausweichen kann.
    """
    def __init__(self, api_key: str, retry_delay_sec: float, quota_id: str, message: str):
        super().__init__(message)
        self.api_key = api_key
        self.retry_delay_sec = retry_delay_sec
        self.quota_id = quota_id


class TtsTransientError(RuntimeError):
    """Transienter Fehler (Timeout, 5xx von Google, Safety-Block). NICHT
    Key-spezifisch — derselbe oder ein anderer Key kann beim Retry klappen.
    Caller sollte einfach erneut versuchen (anderer Key bevorzugt, weil
    bei einem überlasteten Key vielleicht ein frischer schneller ist).
    """
    def __init__(self, api_key: str, message: str, kind: str = "transient"):
        super().__init__(message)
        self.api_key = api_key
        self.kind = kind  # "timeout" | "5xx" | "safety_block" | "transient"


class TtsPoolExhaustedError(RuntimeError):
    """Wird geworfen wenn ALLE Keys im Multi-Key-Pool burned/aufgebraucht sind
    und kein neuer Key picked werden kann. Retry sinnlos — Stream sollte
    sofort graceful enden."""
    pass


class TtsCloudTtsUnavailableError(RuntimeError):
    """Cloud-TTS-Dauer-Fehler (Billing disabled, API nicht aktiviert,
    Permission denied). Retry sinnlos — Stream sollte sofort graceful
    enden, App-User braucht einen Hinweis Provider zu wechseln.

    Unterscheidet sich von TtsTransientError, weil ein zweiter Versuch
    deterministisch wieder failed."""
    pass

class TtsSessionExpiredError(RuntimeError):
    """Die Google-Sitzung des Vorlese-Dienstes traegt nicht mehr.

    Bewusst eine eigene Klasse und nicht TtsCloudTtsUnavailableError: die setzt
    im Stream-Endpunkt eine serverweite Sperre fuer Cloud-TTS. Ein abgelaufener
    Gemini-Web-Login wuerde damit ausgerechnet den Anbieter lahmlegen, auf den
    die Fehlermeldung zum Ausweichen verweist.

    Erneut versuchen ist sinnlos, es hilft nur eine neue Anmeldung auf dem
    Server."""


# Provider-Konstanten
PROVIDER_CLOUD_TTS = "cloud_tts"
PROVIDER_GEMINI_API = "gemini_api"
# Edge-TTS: nutzt Microsoft Edge's "Read Aloud"-Endpoint via `edge-tts`-Library.
# KOSTENLOS, OHNE Setup (kein Service-Account, kein API-Key). Klangqualität
# deutlich schwächer als Gemini/Studio/Chirp, dafür Zero-Effort-Default für
# User die TTS einfach mal ausprobieren wollen.
PROVIDER_EDGE_TTS = "edge_tts"
# Gemini-Web: die Vorlesefunktion von gemini.google.com. Das ist ein eigener
# Aufruf, der beliebigen Text annimmt — kein Chat, kein Modell, keine
# Oberfläche. Ein kleiner Dienst auf demselben Rechner hält die angemeldete
# Google-Sitzung und liefert Ogg/Opus zurück (siehe GEMINI_WEB_TTS_URL).
#
# Warum das der beste Default ist: kostenlos, keine Einrichtung in der App,
# keine Rate-Limit-Fallen, und rund 40-mal schneller als Echtzeit (gemessen:
# 1140 Zeichen ergaben 70 s Audio in 1,5 s). Nachteil: die Stimme ist nicht
# wählbar, und die Sprechgeschwindigkeit kann der Dienst nicht ändern — die
# stellt der Client beim Abspielen ein.
PROVIDER_GEMINI_WEB = "gemini_web"
VALID_PROVIDERS = {PROVIDER_CLOUD_TTS, PROVIDER_GEMINI_API, PROVIDER_EDGE_TTS,
                   PROVIDER_GEMINI_WEB}

# Adresse des Vorlese-Dienstes. Läuft er nicht (etwa auf einem Server ohne
# angemeldete Sitzung), verhält sich alles wie vorher: der Provider taucht
# nicht als verfügbar auf und niemand wird darauf umgestellt.
GEMINI_WEB_TTS_URL = os.environ.get("GEMINI_WEB_TTS_URL", "http://127.0.0.1:8811").rstrip("/")
# Der Dienst deckelt selbst bei 20.000 Zeichen; hier etwas darunter bleiben,
# damit die Fehlermeldung bei uns entsteht und nicht dort.
GEMINI_WEB_MAX_CHARS = 18000
# Default ist Cloud-TTS (Service-Account-Pfad). Grund: das ist der einzige
# Pfad mit großzügigem Free-Contingent und ohne harte Rate-Limit-Stolperfallen
# für eine Chat-App.
#
# Live-Test Mai 2026 ergab: Gemini 3.1 Flash TTS Preview hat im AI-Studio-
# Free-Tier nur **10 Requests pro Tag** (QuotaId: GenerateRequestsPerDayPer-
# ProjectPerModel-FreeTier, value=10). Bei Chunking mit 5-8 Chunks pro
# Antwort ist das Tageskontingent in 1-2 Nachrichten weg.
#
# Gemini 2.5 Flash TTS Preview ist im Free-Tier nutzbarer (3 RPM rolling),
# aber für sinnvolles Chunking auch grenzwertig.
#
# Cloud-TTS dagegen: 1 Mio Zeichen/Monat free pro Voice-Tier (Studio,
# Neural2, Wavenet, Standard, sowie ein eigenes Free-Contingent für die
# Gemini-Voices die über Cloud-TTS geroutet werden). Keine RPM-Begrenzung
# in der Praxis. Datenschutz: kein Daten-Training.
#
# User der Cloud-TTS nicht eingerichtet hat, kann jederzeit auf Gemini API
# switchen (in den App-Einstellungen) und einen oder mehrere AI-Studio-
# Free-Tier-Keys eintragen — der Server verteilt Requests dann via
# Round-Robin + Rate-Limiter auf die Keys.
DEFAULT_PROVIDER = PROVIDER_GEMINI_WEB

# Modell-Name für Gemini-TTS via Cloud-TTS-API (ab google-cloud-texttospeech 2.31.0).
# Voice-IDs mit Prefix "gemini-" routen automatisch über dieses Modell.
# WICHTIG: das ist der Default-Fallback wenn der User kein anderes Modell
# konfiguriert hat. Per-User-Override via KV `tts_model` (siehe server.py).
#
# Stand 2026-05 (offizielle Cloud-TTS-Doku):
#   - `gemini-2.5-flash-tts`              ← GA (kein "-preview-" mehr im Namen)
#   - `gemini-2.5-pro-tts`                ← GA
#   - `gemini-3.1-flash-tts-preview`      ← Preview
#   - `gemini-2.5-flash-lite-preview-tts` ← Preview, single-speaker only
# Quelle: docs.cloud.google.com/text-to-speech/docs/gemini-tts (Mai 2026)
GEMINI_TTS_MODEL = "gemini-2.5-flash-tts"
GEMINI_VOICE_PREFIX = "gemini-"

# Modell-Aliasing: Cloud-TTS-Doku verwendet GA-Namen ("gemini-2.5-flash-tts"),
# die ältere Generativelanguage-API-Doku verwendete "...-preview-tts". Wir
# akzeptieren beide IDs in Settings (kein Daten-Migration nötig) und mappen
# beim Cloud-TTS-Call auf den GA-Namen, sonst antwortet Google mit 500.
_CLOUD_TTS_MODEL_ALIAS: dict[str, str] = {
    "gemini-2.5-flash-preview-tts": "gemini-2.5-flash-tts",
    "gemini-2.5-pro-preview-tts": "gemini-2.5-pro-tts",
    # Folgende sind bereits unter ihrem kanonischen Cloud-TTS-Namen gültig:
    "gemini-2.5-flash-tts": "gemini-2.5-flash-tts",
    "gemini-2.5-pro-tts": "gemini-2.5-pro-tts",
    "gemini-3.1-flash-tts-preview": "gemini-3.1-flash-tts-preview",
    "gemini-2.5-flash-lite-preview-tts": "gemini-2.5-flash-lite-preview-tts",
}


def _cloud_tts_model_name(model_id: str | None) -> str:
    """Map our model-ID auf den exakten Cloud-TTS-Modellnamen.
    Unbekannte IDs werden auf den GA-Default geroutet."""
    if not model_id:
        return GEMINI_TTS_MODEL
    return _CLOUD_TTS_MODEL_ALIAS.get(model_id, GEMINI_TTS_MODEL)


# Genau das umgekehrte Mapping: die Gemini-Direct-API
# (`generativelanguage.googleapis.com`) verwendet die `-preview-tts`-Namen,
# **nicht** die Cloud-TTS-GA-Namen. Wenn ein User die Settings auf
# `gemini-2.5-flash-tts` (Cloud-TTS-GA) gesetzt hat und dann auf Provider
# `gemini_api` umstellt, antwortet die Direct-API mit 404, weil sie diesen
# Modellnamen nicht kennt. Daher: separate Tabelle für Direct-API-Routing.
_GEMINI_API_MODEL_ALIAS: dict[str, str] = {
    # Cloud-TTS-GA-Namen → Direct-API-Preview-Namen
    "gemini-2.5-flash-tts": "gemini-2.5-flash-preview-tts",
    "gemini-2.5-pro-tts": "gemini-2.5-pro-preview-tts",
    # Direct-API-eigene Namen bleiben unverändert
    "gemini-2.5-flash-preview-tts": "gemini-2.5-flash-preview-tts",
    "gemini-2.5-pro-preview-tts": "gemini-2.5-pro-preview-tts",
    "gemini-3.1-flash-tts-preview": "gemini-3.1-flash-tts-preview",
    "gemini-2.5-flash-lite-preview-tts": "gemini-2.5-flash-lite-preview-tts",
}


def _gemini_api_model_name(model_id: str | None) -> str:
    """Map our model-ID auf den exakten Direct-API-Modellnamen
    (`generativelanguage.googleapis.com`). Unbekannte IDs → Direct-API-Default."""
    if not model_id:
        return GEMINI_API_TTS_MODEL
    return _GEMINI_API_MODEL_ALIAS.get(model_id, GEMINI_API_TTS_MODEL)


# Liste der wählbaren Gemini-TTS-Modelle. Stand Mai 2026.
# Preise (jeweils Input / Audio-Output pro 1M Tokens, Paid Tier):
#   2.5-flash-tts:  $0.50 / $10     — günstigste Option, GA-Modell
#   3.1-flash-tts:  $1.00 / $20     — neueste Generation, Preview
#   2.5-pro-tts:    $1.00 / $20     — Pro-Modell, GA
# Voice-IDs (Algenib, Charon, Zephyr usw.) sind modellunabhängig — derselbe
# Sprecher klingt zwischen Modellen nur leicht unterschiedlich.
AVAILABLE_GEMINI_TTS_MODELS: list[dict] = [
    {
        "id": "gemini-2.5-flash-tts",
        "label": "Gemini 2.5 Flash TTS",
        "tier": "flash",
        "price_hint": "$0.50/M Input + $10/M Audio-Output",
        "default": True,
    },
    {
        "id": "gemini-3.1-flash-tts-preview",
        "label": "Gemini 3.1 Flash TTS (Preview)",
        "tier": "flash",
        "price_hint": "$1/M Input + $20/M Audio-Output (neuere Generation)",
        "default": False,
    },
    {
        "id": "gemini-2.5-pro-tts",
        "label": "Gemini 2.5 Pro TTS",
        "tier": "pro",
        "price_hint": "$1/M Input + $20/M Audio-Output (Pro-Modell)",
        "default": False,
    },
]


def is_valid_gemini_model(model_id: str | None) -> bool:
    """True wenn die Modell-ID in der wählbaren Liste ODER ein bekannter
    Alias ist (alte Settings, die noch auf -preview-tts zeigen, sollen
    weiter funktionieren statt nach Default zu fallen)."""
    if not model_id:
        return False
    if model_id in _CLOUD_TTS_MODEL_ALIAS:
        return True
    return any(m["id"] == model_id for m in AVAILABLE_GEMINI_TTS_MODELS)


def default_gemini_model_id() -> str:
    return next(
        (m["id"] for m in AVAILABLE_GEMINI_TTS_MODELS if m.get("default")),
        AVAILABLE_GEMINI_TTS_MODELS[0]["id"],
    )

# === Gemini-API direkt (REST) ===
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
# Default-Modell für den direkten Gemini-API-Pfad. User kann per Setting via
# `tts_model`-KV-Key auf ein anderes Modell switchen (3.1-flash, 2.5-pro).
# Default ist 2.5-flash weil:
#   - günstigster Preis-Tier ($0.50/M Input + $10/M Audio-Output)
#   - ausgereiftes, stabiles Modell
#   - Free-Tier: 3 RPM (rolling) + 10 RPD pro Projekt — mit Multi-Key-Pool nutzbar
#   - 3.1-flash hat Free-Tier nur 10 RPD (kein RPM-Limit) — viel restriktiver
GEMINI_API_TTS_MODEL = "gemini-2.5-flash-preview-tts"
# Gemini-TTS liefert IMMER 16-bit signed-LE PCM mono @ 24kHz zurück.
GEMINI_API_SAMPLE_RATE = 24000
GEMINI_API_CHANNELS = 1
GEMINI_API_BITS = 16
GEMINI_API_BYTES_PER_SEC = (
    GEMINI_API_SAMPLE_RATE * GEMINI_API_CHANNELS * GEMINI_API_BITS // 8
)

# Temperature für Gemini TTS: laut Google-Cookbook beeinflusst der Wert die
# „Style und Charakteristik des Audios" — nicht den Wortlaut. Ohne explizite
# Temperature samplet das Modell mit dem Default-Wert (≥0.5), was zu
# hörbarem Voice-Drift zwischen aufeinanderfolgenden Chunks führt (anderer
# Pitch / Timbre / Pacing pro Call). 0.3 ist ein Kompromiss: niedrig genug
# für konsistente Voice-Charakteristik über alle Chunks einer Antwort,
# hoch genug damit die Stimme nicht monoton-mechanisch klingt.
GEMINI_API_TTS_TEMPERATURE = 0.3

# Media-Types die wir an die Clients zurückgeben.
MEDIA_TYPE_MP3 = "audio/mpeg"
MEDIA_TYPE_WAV = "audio/wav"
MEDIA_TYPE_OGG = "audio/ogg"


def media_type_for(provider: str) -> str:
    # Edge-TTS + Cloud-TTS liefern MP3, Gemini-Direct-API liefert PCM/WAV,
    # Gemini-Web liefert Ogg/Opus.
    if provider == PROVIDER_GEMINI_API:
        return MEDIA_TYPE_WAV
    if provider == PROVIDER_GEMINI_WEB:
        return MEDIA_TYPE_OGG
    return MEDIA_TYPE_MP3


# ===== Edge-TTS — Microsoft Edge's "Read Aloud" via edge-tts-Library =====
# Voice-Prefix für die internen Voice-IDs (analog zu `gemini-` und `chirp3hd-`).
# Auf der edge-tts-Library wird der Voice-Name OHNE Prefix verwendet
# (z.B. "de-DE-KatjaNeural").
EDGE_VOICE_PREFIX = "edge-"

# Kuratierte deutsche Edge-Voices (alphabetisch). Quelle: `edge-tts --list-voices`
# Stand 2026-05. Klangqualität: solide-aber-mechanisch — perfekt als Zero-Setup
# Default damit ein neuer User direkt vorlesen lassen kann, bevor er sich um
# Cloud-TTS-Service-Account oder Gemini-API-Key kümmert.
EDGE_VOICES_DE: list[dict] = [
    {"voice": "de-DE-KatjaNeural", "gender": "FEMALE", "label": "Katja"},
    {"voice": "de-DE-AmalaNeural", "gender": "FEMALE", "label": "Amala"},
    {"voice": "de-DE-ConradNeural", "gender": "MALE", "label": "Conrad"},
    {"voice": "de-DE-KillianNeural", "gender": "MALE", "label": "Killian"},
    {"voice": "de-DE-FlorianMultilingualNeural", "gender": "MALE", "label": "Florian (multilingual)"},
    {"voice": "de-DE-SeraphinaMultilingualNeural", "gender": "FEMALE", "label": "Seraphina (multilingual)"},
]
EDGE_VOICES: set[str] = {f"{EDGE_VOICE_PREFIX}{v['voice']}" for v in EDGE_VOICES_DE}

# Voice-Prefix für Chirp 3: HD-Voices (separater Cloud-TTS-Pfad, keine
# Modell-Inferenz, dafür Streaming-fähig und mit 1 Mio Free-Tier-Zeichen/Monat).
# Voice-Namen sind identisch zu Gemini-TTS (Algenib, Charon, Zephyr, …) —
# Routing entscheidet welche Pipeline. Format intern `chirp3hd-VoiceName`,
# auf der API dann `de-DE-Chirp3-HD-VoiceName` (siehe `_synthesize_cloud_tts`).
CHIRP3HD_VOICE_PREFIX = "chirp3hd-"

# Kuratierte Liste guter deutscher Stimmen (alphabetisch nach Display-Name).
# Sortiert nach Qualität: Gemini > Chirp3-HD > Studio > Neural2 > Wavenet > Standard.
# Provider-Kompatibilität:
#   _ALL_CLOUD = Cloud-TTS-API + Gemini-Direct-API → für `gemini-*`-Voices
#   _CTTS_ONLY = nur Cloud-TTS-API → für Studio/Neural2/Wavenet/Standard/Chirp3HD
#   _EDGE_ONLY = nur Edge-TTS → für `edge-*`-Voices
_ALL_CLOUD = ["cloud_tts", "gemini_api"]
_CTTS_ONLY = ["cloud_tts"]
_EDGE_ONLY = ["edge_tts"]
_WEB_ONLY = ["gemini_web"]
# Legacy-Alias (vor Edge-TTS existierte nur _ALL_PROVIDERS)
_ALL_PROVIDERS = _ALL_CLOUD

CURATED_VOICES = [
    # Gemini-Web — eine einzige Stimme, die Google für das Vorlesen benutzt.
    # Sie ist bewusst als Eintrag geführt, obwohl es nichts zu wählen gibt:
    # sonst stünde die Stimmenliste leer da, sobald dieser Provider aktiv ist.
    {"id": "geminiweb-standard", "label": "Gemini (Standard, keine Auswahl)", "gender": "FEMALE", "tier": "geminiweb", "compatible_providers": _WEB_ONLY},
    # Edge-TTS — Microsoft Edge's "Read Aloud". KOSTENLOS, OHNE Setup.
    # Klangqualität schwächer als Gemini/Chirp, dafür Zero-Effort-Default.
    {"id": "edge-de-DE-KatjaNeural", "label": "Edge Katja — weiblich (gratis)", "gender": "FEMALE", "tier": "edge", "compatible_providers": _EDGE_ONLY},
    {"id": "edge-de-DE-ConradNeural", "label": "Edge Conrad — männlich (gratis)", "gender": "MALE", "tier": "edge", "compatible_providers": _EDGE_ONLY},
    {"id": "edge-de-DE-AmalaNeural", "label": "Edge Amala — weiblich (gratis)", "gender": "FEMALE", "tier": "edge", "compatible_providers": _EDGE_ONLY},
    {"id": "edge-de-DE-KillianNeural", "label": "Edge Killian — männlich (gratis)", "gender": "MALE", "tier": "edge", "compatible_providers": _EDGE_ONLY},
    {"id": "edge-de-DE-FlorianMultilingualNeural", "label": "Edge Florian — männlich, multilingual (gratis)", "gender": "MALE", "tier": "edge", "compatible_providers": _EDGE_ONLY},
    {"id": "edge-de-DE-SeraphinaMultilingualNeural", "label": "Edge Seraphina — weiblich, multilingual (gratis)", "gender": "FEMALE", "tier": "edge", "compatible_providers": _EDGE_ONLY},
    # Gemini-TTS — Modell-Inferenz mit Prompt-Style-Control, kein Free-Tier.
    # Voice-Namen sind Sternennamen, Sprache wird per language_code mitgegeben.
    # Diese Voices funktionieren auf BEIDEN APIs (Cloud-TTS + Direct-API).
    {"id": "gemini-Algenib", "label": "Gemini Algenib — männlich", "gender": "MALE", "tier": "gemini", "compatible_providers": _ALL_PROVIDERS},
    {"id": "gemini-Algieba", "label": "Gemini Algieba — männlich", "gender": "MALE", "tier": "gemini", "compatible_providers": _ALL_PROVIDERS},
    {"id": "gemini-Charon", "label": "Gemini Charon — männlich", "gender": "MALE", "tier": "gemini", "compatible_providers": _ALL_PROVIDERS},
    {"id": "gemini-Zephyr", "label": "Gemini Zephyr — weiblich", "gender": "FEMALE", "tier": "gemini", "compatible_providers": _ALL_PROVIDERS},
    {"id": "gemini-Pulcherrima", "label": "Gemini Pulcherrima — weiblich", "gender": "FEMALE", "tier": "gemini", "compatible_providers": _ALL_PROVIDERS},
    {"id": "gemini-Callirrhoe", "label": "Gemini Callirrhoe — weiblich", "gender": "FEMALE", "tier": "gemini", "compatible_providers": _ALL_PROVIDERS},
    # Chirp 3: HD — gleiche Sternen-Voices wie Gemini, aber Standard-TTS-Pfad
    # (kein Modell-Inferencing). 1 Mio Zeichen/Monat KOSTENLOS, danach $30/M.
    # Nur via Cloud-TTS-API verfügbar (kein Direct-API-Pendant).
    {"id": "chirp3hd-Algenib", "label": "Chirp 3 HD Algenib — männlich", "gender": "MALE", "tier": "chirp3hd", "compatible_providers": _CTTS_ONLY},
    {"id": "chirp3hd-Algieba", "label": "Chirp 3 HD Algieba — männlich", "gender": "MALE", "tier": "chirp3hd", "compatible_providers": _CTTS_ONLY},
    {"id": "chirp3hd-Charon", "label": "Chirp 3 HD Charon — männlich", "gender": "MALE", "tier": "chirp3hd", "compatible_providers": _CTTS_ONLY},
    {"id": "chirp3hd-Schedar", "label": "Chirp 3 HD Schedar — männlich", "gender": "MALE", "tier": "chirp3hd", "compatible_providers": _CTTS_ONLY},
    {"id": "chirp3hd-Zephyr", "label": "Chirp 3 HD Zephyr — weiblich", "gender": "FEMALE", "tier": "chirp3hd", "compatible_providers": _CTTS_ONLY},
    {"id": "chirp3hd-Aoede", "label": "Chirp 3 HD Aoede — weiblich", "gender": "FEMALE", "tier": "chirp3hd", "compatible_providers": _CTTS_ONLY},
    {"id": "chirp3hd-Callirrhoe", "label": "Chirp 3 HD Callirrhoe — weiblich", "gender": "FEMALE", "tier": "chirp3hd", "compatible_providers": _CTTS_ONLY},
    {"id": "chirp3hd-Pulcherrima", "label": "Chirp 3 HD Pulcherrima — weiblich", "gender": "FEMALE", "tier": "chirp3hd", "compatible_providers": _CTTS_ONLY},
    # Studio (Premium-Qualität, teuer)
    {"id": "de-DE-Studio-B", "label": "Studio B — männlich (Premium)", "gender": "MALE", "tier": "studio", "compatible_providers": _CTTS_ONLY},
    {"id": "de-DE-Studio-C", "label": "Studio C — weiblich (Premium)", "gender": "FEMALE", "tier": "studio", "compatible_providers": _CTTS_ONLY},
    # Neural2
    {"id": "de-DE-Neural2-B", "label": "Neural2 B — männlich", "gender": "MALE", "tier": "neural2", "compatible_providers": _CTTS_ONLY},
    {"id": "de-DE-Neural2-C", "label": "Neural2 C — weiblich", "gender": "FEMALE", "tier": "neural2", "compatible_providers": _CTTS_ONLY},
    {"id": "de-DE-Neural2-D", "label": "Neural2 D — männlich", "gender": "MALE", "tier": "neural2", "compatible_providers": _CTTS_ONLY},
    {"id": "de-DE-Neural2-F", "label": "Neural2 F — weiblich", "gender": "FEMALE", "tier": "neural2", "compatible_providers": _CTTS_ONLY},
    # Wavenet (gutes Preis-Leistungs-Verhältnis)
    {"id": "de-DE-Wavenet-B", "label": "Wavenet B — männlich", "gender": "MALE", "tier": "wavenet", "compatible_providers": _CTTS_ONLY},
    {"id": "de-DE-Wavenet-C", "label": "Wavenet C — weiblich", "gender": "FEMALE", "tier": "wavenet", "compatible_providers": _CTTS_ONLY},
    {"id": "de-DE-Wavenet-F", "label": "Wavenet F — weiblich", "gender": "FEMALE", "tier": "wavenet", "compatible_providers": _CTTS_ONLY},
    # Standard (günstig, etwas mechanischer)
    {"id": "de-DE-Standard-A", "label": "Standard A — weiblich", "gender": "FEMALE", "tier": "standard", "compatible_providers": _CTTS_ONLY},
    {"id": "de-DE-Standard-B", "label": "Standard B — männlich", "gender": "MALE", "tier": "standard", "compatible_providers": _CTTS_ONLY},
]

# Default-Stimmen pro Provider — die App holt sich beim Setup den richtigen
# Default ab, je nachdem ob der User Cloud-TTS oder Gemini-Direct-API gewählt hat.
#
# - Cloud-TTS:    Chirp 3 HD Algenib (männlich, deutsch).
#     · 1 Mio Zeichen/Monat KOSTENLOS = ~20 h Audio/Monat
#     · danach $30 / 1 Mio Zeichen (~$1.50/h)
#     · Sternennamen-Voice mit guter Prosodie, kein Modell-Inferencing
#     · perfekter „erster Eindruck" für User mit Service-Account-Setup
#
# - Gemini-Direct-API: gemini-Algenib (gleiche Voice, anderer Pfad).
#     · Free Tier der Direct-API (10 RPD pro Key, mit Multi-Key-Pool nutzbar)
#     · klanglich praktisch identisch zur Cloud-TTS-Chirp-Variante
DEFAULT_VOICE_CLOUD_TTS = "chirp3hd-Algenib"
DEFAULT_VOICE_GEMINI_API = "gemini-Algenib"
DEFAULT_VOICE_EDGE_TTS = "edge-de-DE-KatjaNeural"
# Gemini-Web kennt keine Stimmauswahl (geprüft: der Aufruf hat schlicht keinen
# Parameter dafür). Die ID ist trotzdem nötig, damit Cache-Schlüssel und
# Stimmenliste einen stabilen Wert haben.
DEFAULT_VOICE_GEMINI_WEB = "geminiweb-standard"

# Globaler Fallback (für Call-Sites die keinen Provider kennen). Wir nehmen
# Edge-TTS-Variante weil das der UNIVERSAL-Pfad ist — funktioniert für jeden
# User ohne Setup.
DEFAULT_VOICE = DEFAULT_VOICE_EDGE_TTS


def default_voice_for(provider: str | None) -> str:
    """Liefert die Default-Voice passend zum aktiven TTS-Provider.

    Wird bei /tts/status und beim Stream-Resolve genutzt, damit User die noch
    keine Voice gesetzt haben automatisch die provider-kompatible Default-Voice
    bekommen."""
    if provider == PROVIDER_GEMINI_API:
        return DEFAULT_VOICE_GEMINI_API
    if provider == PROVIDER_EDGE_TTS:
        return DEFAULT_VOICE_EDGE_TTS
    if provider == PROVIDER_GEMINI_WEB:
        return DEFAULT_VOICE_GEMINI_WEB
    return DEFAULT_VOICE_CLOUD_TTS


def chunking_default_for(provider: str | None) -> bool:
    """Default-Wert für Chunking, abhängig vom Provider.

    - cloud_tts: TRUE — kein nennenswertes Rate-Limit-Risiko, Latency-Gewinn
      durch parallele Chunks. Chirp 3 HD = 1M Zeichen/Monat free, Voice-Quality
      ist konsistent zwischen Chunks.
    - gemini_api: FALSE — Free-Tier hat 10 RPD pro Key, eine gechunkte Antwort
      mit 12 Chunks verbraucht das Tageskontingent in einer einzigen Nachricht.
      Bei Multi-Key-Pool kann der User das manuell wieder einschalten.
    - edge_tts: FALSE — Edge-TTS macht single-WebSocket-Session pro Request,
      Chunking erzeugt unnötig viele Connections ohne Latency-Vorteil.
    - gemini_web: FALSE — und das ist hier keine Abwägung, sondern Pflicht:
      der Dienst liefert Ogg/Opus, und Ogg-Ströme lassen sich nicht einfach
      aneinanderhängen (jeder bringt eigene Kopfdaten und eine eigene Kennung
      mit). Gechunkt käme beim Abspielen nur der erste Teil an. Nötig ist es
      ohnehin nicht: 1140 Zeichen ergaben gemessen 70 s Audio in 1,5 s.
    """
    if provider == PROVIDER_CLOUD_TTS:
        return True
    return False

# Fallback-Voice für den Gemini-API-Pfad: wenn ein User noch eine Cloud-TTS-Voice
# (z.B. `de-DE-Neural2-F`) konfiguriert hat, der Server aber auf Provider
# `gemini_api` läuft, muss der Voice-Name auf einen gültigen Gemini-Voice-Namen
# gemapped werden. Zephyr is a warm female voice — a good default fallback.
DEFAULT_GEMINI_API_VOICE = "Zephyr"

# Bekannte Gemini-TTS-Voice-Namen (Stand 2026-05). Quelle:
# https://ai.google.dev/gemini-api/docs/speech-generation
# Wird nur fürs Voice-Mapping benutzt — wenn Google eine neue Voice ergänzt und
# der User die wählt, wird sie über DEFAULT_GEMINI_API_VOICE „aufgefangen", aber
# nicht hart abgelehnt. Wir loggen einen Hinweis und probieren die Voice trotzdem
# an die API zu schicken — die API entscheidet final.
KNOWN_GEMINI_VOICES: set[str] = {
    "Zephyr", "Puck", "Charon", "Kore", "Fenrir", "Leda", "Orus", "Aoede",
    "Callirrhoe", "Autonoe", "Enceladus", "Iapetus", "Umbriel", "Algieba",
    "Despina", "Erinome", "Algenib", "Rasalgethi", "Laomedeia", "Achernar",
    "Alnilam", "Schedar", "Gacrux", "Pulcherrima", "Achird", "Zubenelgenubi",
    "Vindemiatrix", "Sadachbia", "Sadaltager", "Sulafat",
}

# Speed-Bounds (Google-TTS speaking_rate-Range ist 0.25..4.0)
MIN_SPEED = 0.25
MAX_SPEED = 2.0
DEFAULT_SPEED = 1.0


@dataclass
class TtsConfig:
    project_id: str
    client_email: str
    voice: str = DEFAULT_VOICE


def _credentials_path() -> Path:
    return settings.data_dir / CREDENTIALS_FILENAME


def is_configured() -> bool:
    return _credentials_path().exists()


def save_credentials(json_str: str) -> TtsConfig:
    """Speichert Service-Account-JSON. Validiert grob, dass es eins ist."""
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise ValueError(f"Ungültiges JSON: {e}") from e

    if data.get("type") != "service_account":
        raise ValueError(
            f"Erwarte type='service_account', habe '{data.get('type')}'. "
            f"Das sieht nicht nach Google-Cloud-Service-Account aus."
        )
    if "private_key" not in data or "client_email" not in data:
        raise ValueError("JSON enthält keine private_key/client_email.")

    path = _credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))
    try:
        path.chmod(0o600)
    except Exception:  # noqa: BLE001
        pass

    log.info("Google-TTS-Credentials gespeichert (%s)", data.get("client_email"))
    return TtsConfig(
        project_id=data.get("project_id", ""),
        client_email=data.get("client_email", ""),
    )


def delete_credentials() -> bool:
    path = _credentials_path()
    if path.exists():
        path.unlink()
        log.info("Google-TTS-Credentials gelöscht.")
        return True
    return False


def get_config() -> Optional[TtsConfig]:
    path = _credentials_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return TtsConfig(
            project_id=data.get("project_id", ""),
            client_email=data.get("client_email", ""),
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("Credentials-Datei nicht lesbar: %s", exc)
        return None


_client = None


def _client_lazy():
    """Initialisiert den Google-TTS-Client beim ersten Zugriff."""
    global _client
    if _client is not None:
        return _client
    path = _credentials_path()
    if not path.exists():
        raise RuntimeError("TTS-Credentials nicht konfiguriert.")
    # Lazy-Import — wir wollen den Server auch starten können, wenn die
    # google-cloud-texttospeech Library noch nicht installiert ist.
    from google.cloud import texttospeech
    from google.oauth2 import service_account

    creds = service_account.Credentials.from_service_account_file(str(path))
    _client = texttospeech.TextToSpeechClient(credentials=creds)
    return _client


def reset_client() -> None:
    """Nach Credentials-Wechsel: Client neu initialisieren. Public API für
    Caller aus anderen Modulen."""
    global _client
    _client = None


# Backward-Compat: alter privater Name. Caller migrieren auf reset_client().
_reset_client = reset_client


# Emoji-Ranges — fast vollständige Abdeckung. Wenn diese drin sind, würde Google-TTS
# sie als ihren Unicode-Namen vorlesen ("waving hand" für 👋 etc), das wollen wir nicht.
_EMOJI_PATTERN = re.compile(
    "["
    "\U0001F1E0-\U0001F1FF"  # Flaggen
    "\U0001F300-\U0001F5FF"  # Symbole & Piktogramme
    "\U0001F600-\U0001F64F"  # Emoticons
    "\U0001F680-\U0001F6FF"  # Transport & Karten
    "\U0001F700-\U0001F77F"  # Alchemie
    "\U0001F780-\U0001F7FF"  # geometrische Formen
    "\U0001F800-\U0001F8FF"  # Ergänzende Pfeile
    "\U0001F900-\U0001F9FF"  # Ergänzende Symbole & Piktogramme
    "\U0001FA00-\U0001FA6F"  # Schach-Symbole
    "\U0001FA70-\U0001FAFF"  # Symbols & Pictographs Extended
    "\U00002600-\U000026FF"  # Misc. Symbols (☀️, ☎️, ⚽…)
    "\U00002700-\U000027BF"  # Dingbats (✂️, ✈️, …)
    "\U0001F004-\U0001F0CF"  # Mahjong/Spielkarten
    "\U0000FE0E-\U0000FE0F"  # Variation Selectors (für Emoji-Style)
    "\U0001F018-\U0001F270"  # Verschiedenes
    "\U0000200D"               # Zero-Width-Joiner (Emoji-Sequenzen)
    "\U000020E3"               # Combining Enclosing Keycap
    "]",
    flags=re.UNICODE,
)


def _strip_for_tts(text: str) -> str:
    """Bereitet Markdown-haltigen Text für TTS auf."""
    if not text:
        return ""
    # Code-Blöcke entfernen (werden sonst als endlose Zeichenfolge vorgelesen)
    text = re.sub(r"```[\s\S]*?```", " ", text)
    # Inline-Code
    text = re.sub(r"`([^`]+)`", r"\1", text)
    # Bold/Italic-Marker
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"__([^_]+)__", r"\1", text)
    text = re.sub(r"\*([^*\n]+)\*", r"\1", text)
    text = re.sub(r"(?<!\w)_([^_\n]+)_(?!\w)", r"\1", text)
    # Header-Marker
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    # Listen-Marker
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\d+\.\s+", "", text, flags=re.MULTILINE)
    # URLs in Markdown-Links: [Text](url) → Text
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    # Bilder-Marker
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", text)
    # Bare URLs
    text = re.sub(r"https?://\S+", " ", text)
    # Emojis komplett raus
    text = _EMOJI_PATTERN.sub("", text)
    # Mehrfache Leerzeichen / Newlines
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


# Pro-Request-Limit der Cloud-TTS-API ist 5000 Bytes. Da wir aber chunken
# (jeder Chunk ≤ 150 Zeichen, weit unter dem API-Limit), gilt für den
# Gesamttext keine harte Grenze mehr. Wir setzen trotzdem eine sehr hohe
# Sicherheitsgrenze, damit ein versehentlich riesiger Text nicht 1000
# parallele Synthese-Calls auslöst.
MAX_TOTAL_CHARS = 100_000

# Legacy-Alias: das alte Single-Call-Limit von 4800. Wird aktuell nur noch
# vom direkten `synthesize`-Pfad genutzt (Kurztexte unter CHUNKING_MIN_TOTAL_CHARS
# oder klassische Cloud-TTS-Voices); dort ist 4800 ≈ Google-API-Limit.
MAX_SYNTH_CHARS = 4800


def _clamp_speed(speed: float | None) -> float:
    """Begrenzt den Speed auf [MIN_SPEED, MAX_SPEED]. None → DEFAULT_SPEED."""
    if speed is None:
        return DEFAULT_SPEED
    try:
        s = float(speed)
    except (TypeError, ValueError):
        return DEFAULT_SPEED
    if s < MIN_SPEED:
        return MIN_SPEED
    if s > MAX_SPEED:
        return MAX_SPEED
    return s


def wav_header(pcm_size: int,
               sample_rate: int = GEMINI_API_SAMPLE_RATE,
               channels: int = GEMINI_API_CHANNELS,
               bits: int = GEMINI_API_BITS) -> bytes:
    """RIFF/WAV-Header für PCM-Audio. `pcm_size` = Anzahl Bytes der PCM-Daten."""
    byte_rate = sample_rate * channels * bits // 8
    block_align = channels * bits // 8
    riff_size = 36 + pcm_size
    return (
        b"RIFF" + struct.pack("<I", riff_size) +
        b"WAVE" +
        b"fmt " + struct.pack("<IHHIIHH", 16, 1, channels, sample_rate,
                              byte_rate, block_align, bits) +
        b"data" + struct.pack("<I", pcm_size)
    )


def streaming_wav_header() -> bytes:
    """WAV-Header mit fake-Maximum-Länge für Streaming.

    Spec-konform sind die Length-Felder unsigned-32-bit. Wir setzen sie auf
    `0xFFFFFFFF` (≈ 24h Audio bei 24kHz mono 16-bit), das interpretieren
    Browser + Android-MediaPlayer als "open-ended" — sie streamen Bytes
    durch bis die HTTP-Verbindung schließt, dann ist das Audio fertig.

    Die "wrong duration" Anzeige während des Streams ist Inkauf zu nehmen;
    für den Cache schreiben wir den korrekten Header nachträglich neu
    (`fix_wav_header_length`).
    """
    huge = 0xFFFFFFFF - 36
    return wav_header(pcm_size=huge)


def fix_wav_header_length(wav_with_fake_header: bytes) -> bytes:
    """Schreibt die echten Length-Felder in einen WAV-Stream der mit
    `streaming_wav_header()` begonnen hat. Wird für den Cache gebraucht,
    damit gecachte Audios eine korrekte Dauer melden."""
    if len(wav_with_fake_header) < 44:
        return wav_with_fake_header
    pcm_size = len(wav_with_fake_header) - 44
    new_header = wav_header(pcm_size)
    return new_header + wav_with_fake_header[44:]


def rebuild_wav(pcm_bytes: bytes) -> bytes:
    """Baut ein komplettes WAV-File aus rohen PCM-Bytes mit korrekter Länge."""
    return wav_header(len(pcm_bytes)) + pcm_bytes


def _strip_gemini_prefix(voice: str) -> str:
    """'gemini-Algenib' → 'Algenib'. Andere Voice-Namen unverändert."""
    if voice.startswith(GEMINI_VOICE_PREFIX):
        return voice[len(GEMINI_VOICE_PREFIX):]
    return voice


def _normalize_voice_for_gemini_api(voice: str) -> str:
    """Mappt einen beliebigen Voice-String auf einen gültigen Gemini-API-Voice-
    Namen.

    Hintergrund: User können auf eine Cloud-TTS-Voice (z.B. `de-DE-Neural2-F`)
    konfiguriert sein, während der Server mit Provider `gemini_api` läuft.
    Die Gemini-API kennt nur Sternennamen (Zephyr, Algenib …); Cloud-TTS-
    Voice-IDs würden zu HTTP 400 führen.

    Regeln:
    - `gemini-Algenib` → `Algenib` (Prefix strippen)
    - `Algenib`       → `Algenib` (schon ok)
    - `de-DE-Neural2-F` (oder irgendwas anderes) → DEFAULT_GEMINI_API_VOICE,
      mit Warn-Log damit man's in den Logs sieht.

    Unbekannte Namen, die plausibel wie Gemini-Voices aussehen (keine `-`-im-
    Namen, beginnen mit Großbuchstaben), werden durchgelassen — Google
    erweitert die Voice-Liste regelmäßig, wir wollen nicht alles hart
    sperren.
    """
    stripped = _strip_gemini_prefix(voice or "").strip()
    if not stripped:
        return DEFAULT_GEMINI_API_VOICE
    if stripped in KNOWN_GEMINI_VOICES:
        return stripped
    # Heuristik: enthält `-` (z.B. `de-DE-Neural2-F`) → ist sicher KEINE Gemini-
    # Voice. Auf Default mappen.
    if "-" in stripped or stripped[:1].islower():
        log.warning(
            "Voice %r ist nicht Gemini-kompatibel — fallback auf %r. "
            "User sollte in den TTS-Einstellungen eine Gemini-Voice wählen.",
            voice, DEFAULT_GEMINI_API_VOICE,
        )
        return DEFAULT_GEMINI_API_VOICE
    # Sieht aus wie eine Gemini-Voice die wir noch nicht kennen — probieren.
    log.info(
        "Voice %r ist nicht in der bekannten Liste, schicke trotzdem an die API.",
        stripped,
    )
    return stripped


def _normalize_voice_for_edge_tts(voice: str) -> str:
    """Mappt einen beliebigen Voice-String auf einen gültigen Edge-TTS-
    Voice-Namen.

    Edge-TTS-Voices haben unser internes Format `edge-<api-name>`, wobei
    `api-name` z.B. `de-DE-KatjaNeural` ist. Wenn ein User auf eine fremde
    Voice (`gemini-Algenib`, `chirp3hd-Charon`, `de-DE-Neural2-F`)
    konfiguriert ist und auf Edge-Provider wechselt, würde das hier
    1:1 an Edge geschickt → WebSocket-Fehler.

    Regeln:
    - `edge-de-DE-KatjaNeural` → passthrough (schon korrekt)
    - jede andere Voice          → DEFAULT_VOICE_EDGE_TTS, mit Warn-Log
    """
    if voice and voice.startswith(EDGE_VOICE_PREFIX):
        api_name = voice[len(EDGE_VOICE_PREFIX):]
        # Bekannte Edge-Voices durchlassen, sonst auf Default zurück
        known_api_names = {v["voice"] for v in EDGE_VOICES_DE}
        if api_name in known_api_names:
            return voice
    log.warning(
        "Voice %r ist nicht Edge-TTS-kompatibel — fallback auf %r. "
        "User sollte in den TTS-Einstellungen eine Edge-Voice wählen.",
        voice, DEFAULT_VOICE_EDGE_TTS,
    )
    return DEFAULT_VOICE_EDGE_TTS


def _synthesize_gemini_api(
    text: str,
    voice: str,
    speaking_rate: float,
    api_key: str,
    timeout: float = 30.0,
    model_id: str | None = None,
) -> bytes:
    """Synthese via Gemini-API (REST). Returnt rohe PCM-Bytes
    (16-bit signed-LE, mono, 24kHz). Caller wrappt sie in WAV oder
    streamt sie als raw-PCM hinter einem vorab geschickten WAV-Header.

    `speaking_rate` wird vom aktuellen Gemini-TTS-Preview noch nicht direkt
    unterstützt — wir loggen den gewünschten Wert. Stimmen reagieren auf
    Inline-Steuerung im Prompt-Text (z.B. "[langsam und ruhig]"), aber das
    machen wir hier nicht automatisch — wäre ein eigenes Feature.
    """
    if not api_key or not api_key.strip():
        raise RuntimeError(
            "Provider=gemini_api: kein API-Key gesetzt. Trage deinen "
            "AI-Studio-API-Key in den Einstellungen ein."
        )

    # Voice-Mapping: gemini-Algenib → Algenib; de-DE-Neural2-F → Zephyr (Default).
    # Verhindert HTTP 400 wenn der User noch auf eine Cloud-TTS-Voice steht und
    # der Server (neu seit Mai 2026) per Default auf gemini_api läuft.
    voice_name = _normalize_voice_for_gemini_api(voice)

    body = {
        "contents": [{"parts": [{"text": text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            # Niedrige Temperature für Voice-Konsistenz zwischen Chunks.
            # Default-Temperature des Modells ist hörbar zu hoch (verschiedene
            # Pitch/Timbre/Pacing zwischen parallelen Chunk-Calls).
            "temperature": GEMINI_API_TTS_TEMPERATURE,
            "speechConfig": {
                "voiceConfig": {
                    "prebuiltVoiceConfig": {"voiceName": voice_name},
                },
            },
        },
    }

    # WICHTIG: Die Direct-API kennt NICHT die Cloud-TTS-GA-Namen ("gemini-2.5-flash-tts"),
    # sondern nur die Preview-Namen ("gemini-2.5-flash-preview-tts"). Mappen.
    effective_model = _gemini_api_model_name(
        model_id if is_valid_gemini_model(model_id) else GEMINI_API_TTS_MODEL
    )
    url = f"{GEMINI_API_BASE}/models/{effective_model}:generateContent"
    log.info(
        "gemini-tts API: model=%s voice=%s chars=%d rate=%.2f (rate gets ignored by current preview)",
        effective_model, voice_name, len(text), speaking_rate,
    )

    try:
        with httpx.Client(timeout=timeout) as cli:
            r = cli.post(
                url,
                params={"key": api_key},
                headers={"Content-Type": "application/json"},
                json=body,
            )
    except httpx.TimeoutException as e:
        # Transient: Caller soll mit anderem Key retrien
        raise TtsTransientError(
            api_key=api_key, kind="timeout",
            message=f"Gemini-TTS: Timeout nach {timeout:.0f}s (Key …{api_key[-6:]}).",
        ) from e
    except httpx.RequestError as e:
        raise TtsTransientError(
            api_key=api_key, kind="transient",
            message=f"Gemini-TTS: Netzwerk-Fehler ({type(e).__name__}): {str(e)[:120]}",
        ) from e

    if r.status_code >= 400:
        msg = r.text[:400]
        status_code_str = ""
        retry_delay_sec: float = 0.0
        quota_id = ""
        try:
            err = (r.json() or {}).get("error") or {}
            msg = err.get("message") or msg
            status_code_str = err.get("status") or ""
            # Google packt retryDelay und quotaId in SEPARATE Detail-Objekte:
            # `google.rpc.RetryInfo` trägt retryDelay, `google.rpc.QuotaFailure`
            # trägt die violations[].quotaId. Wir parsen typ-bewusst und nehmen
            # den ERSTEN konkreten quotaId (statt den letzten zu überschreiben),
            # damit RPD-vs-RPM-Burn korrekt klassifiziert wird.
            for d in err.get("details", []) or []:
                if not isinstance(d, dict):
                    continue
                dtype = d.get("@type") or ""
                if "retryDelay" in d and isinstance(d["retryDelay"], str):
                    # Format wie "23s" oder "23.5s"
                    raw = d["retryDelay"].rstrip("s")
                    try:
                        retry_delay_sec = float(raw)
                    except ValueError:
                        pass
                if not quota_id:
                    for v in d.get("violations", []) or []:
                        qi = v.get("quotaId") if isinstance(v, dict) else ""
                        if qi:
                            quota_id = qi
                            break
                if not quota_id and "QuotaFailure" not in dtype:
                    # quotaId taucht bei manchen Antworten in metadata auf
                    meta = d.get("metadata")
                    if isinstance(meta, dict) and meta.get("quota_metric"):
                        quota_id = meta["quota_metric"]
        except Exception:  # noqa: BLE001
            pass
        prefix = f"[{status_code_str}] " if status_code_str else ""
        if r.status_code == 429:
            # Spezielle Exception → server.py kann darauf mit Key-Burn + Retry
            # reagieren statt den ganzen Stream abzubrechen.
            raise TtsQuotaExceededError(
                api_key=api_key,
                retry_delay_sec=retry_delay_sec or 60.0,
                quota_id=quota_id,
                message=f"Gemini-TTS Quota erschöpft: {prefix}{msg}",
            )
        if r.status_code >= 500:
            # Server-side Google-Glitch — Retry mit beliebigem Key kann
            # klappen. Nicht den ganzen Stream killen.
            raise TtsTransientError(
                api_key=api_key, kind="5xx",
                message=f"Gemini-TTS Server-Fehler (HTTP {r.status_code}): {prefix}{msg[:140]}",
            )
        raise RuntimeError(
            f"Gemini-TTS API-Fehler (HTTP {r.status_code}): {prefix}{msg}"
        )

    try:
        data = r.json()
    except Exception as e:
        raise RuntimeError(f"Gemini-TTS: Response nicht parsebar: {e}") from e

    candidates = data.get("candidates") or []
    if not candidates:
        raise RuntimeError(
            f"Gemini-TTS: Keine candidates in Response. payload={str(data)[:200]}"
        )

    parts = (candidates[0].get("content") or {}).get("parts") or []
    for part in parts:
        inline = part.get("inlineData") or part.get("inline_data")
        if inline and inline.get("data"):
            try:
                pcm = base64.b64decode(inline["data"])
            except Exception as e:
                raise RuntimeError(f"Gemini-TTS: base64-decode fehlgeschlagen: {e}") from e
            duration = len(pcm) / GEMINI_API_BYTES_PER_SEC
            log.info(
                "gemini-tts API: %d PCM bytes (%.2fs audio @ %dHz)",
                len(pcm), duration, GEMINI_API_SAMPLE_RATE,
            )
            return pcm

    finish_reason = candidates[0].get("finishReason", "unbekannt")
    # Als transient klassifizieren — auch wenn's „SAFETY"/OTHER ist:
    # - manchmal hilft ein Retry-Call (Sampling)
    # - falls's wirklich blockt, gibt der Stream-Wrapper am Ende auf
    # - aber: nicht den ganzen Stream killen
    raise TtsTransientError(
        api_key=api_key, kind="safety_block",
        message=(
            f"Gemini-TTS: Keine Audio-Daten (finishReason={finish_reason}). "
            "Wahrscheinlich Safety-Block oder Mini-Glitch — Retry möglich."
        ),
    )


def _synthesize_cloud_tts(
    text: str,
    voice: str,
    speaking_rate: float,
    model_id: str | None = None,
) -> bytes:
    """Synthese via Cloud-TTS-API + Service-Account. Returnt MP3-Bytes.
    Voice-IDs mit Prefix "gemini-" routen über das Gemini-3.1-Flash-TTS-Modell
    der Cloud-TTS-API (anderer Bezahlpfad als der direkte Gemini-API-Pfad!).
    """
    if not is_configured():
        raise RuntimeError(
            "Cloud-TTS ist nicht konfiguriert. Lade dein Service-Account-JSON "
            "via PUT /tts/credentials hoch — ODER nutze Provider=gemini_api."
        )

    from google.cloud import texttospeech as gtts

    client = _client_lazy()
    synthesis_input = gtts.SynthesisInput(text=text)

    is_gemini = voice.startswith(GEMINI_VOICE_PREFIX)
    is_chirp3hd = voice.startswith(CHIRP3HD_VOICE_PREFIX)
    if is_gemini:
        api_voice_name = voice[len(GEMINI_VOICE_PREFIX):]
        # WICHTIG: Cloud-TTS will den GA-Modellnamen ("gemini-2.5-flash-tts"),
        # NICHT den Generativelanguage-API-Namen ("...-preview-tts"). Sonst 500.
        effective_model = _cloud_tts_model_name(
            model_id if is_valid_gemini_model(model_id) else GEMINI_TTS_MODEL
        )
        voice_params = gtts.VoiceSelectionParams(
            language_code="de-DE",
            name=api_voice_name,
            model_name=effective_model,
        )
    elif is_chirp3hd:
        # Chirp 3: HD — Standard-TTS-Pfad, kein Modell-Inferencing.
        # API-Voice-Name-Format: `<locale>-Chirp3-HD-<VoiceName>`, KEIN model_name.
        # Voice-Namen sind kapitalisiert (Algenib, Charon, …) wie bei Gemini.
        star_name = voice[len(CHIRP3HD_VOICE_PREFIX):]
        api_voice_name = f"de-DE-Chirp3-HD-{star_name}"
        voice_params = gtts.VoiceSelectionParams(
            language_code="de-DE",
            name=api_voice_name,
        )
    else:
        lang_code = "-".join(voice.split("-")[:2]) if voice else "de-DE"
        voice_params = gtts.VoiceSelectionParams(
            language_code=lang_code,
            name=voice,
        )

    audio_config = gtts.AudioConfig(
        audio_encoding=gtts.AudioEncoding.MP3,
        speaking_rate=speaking_rate,
    )
    log.info(
        "cloud-tts: synthesizing %d chars voice=%s rate=%.2f (gemini-voice=%s, model=%s)",
        len(text), voice, speaking_rate, is_gemini,
        (model_id if is_gemini else "n/a"),
    )
    try:
        response = client.synthesize_speech(
            input=synthesis_input,
            voice=voice_params,
            audio_config=audio_config,
        )
        return response.audio_content
    except Exception as exc:  # noqa: BLE001
        # Google-Cloud-Exceptions kürzen + häufige Ursachen mit hilfreichen
        # Hinweisen versehen (statt 30-Zeilen-Proto-Dump im Stream-Error).
        # Bei "Dauer"-Fehlern (Billing, API nicht aktiviert, Permission)
        # werfen wir TtsCloudTtsUnavailableError → Stream beendet graceful,
        # weiterer Retry sinnlos.
        full = str(exc)
        # Erste 2 Zeilen der Google-Antwort fürs Debugging mitloggen — die
        # Klassifizierung weiter unten ist nur eine Heuristik, der echte
        # Wortlaut liegt hier.
        first_lines = " | ".join(full.splitlines()[:2])[:400]
        log.warning("cloud-tts raw error: %s (type=%s)",
                    first_lines, type(exc).__name__)
        if "BILLING_DISABLED" in full or "requires billing" in full:
            # WICHTIG: NICHT vorschlagen auf Gemini-API zu wechseln — das
            # $10-AI-Pro-Kontingent wird NUR via Cloud-TTS abgebucht.
            # Korrekter Fix ist Billing aktivieren / Projekt mit Billing-
            # Account verknüpfen.
            raise TtsCloudTtsUnavailableError(
                "Cloud TTS API: Das Cloud-Projekt des hochgeladenen Service-"
                "Account-JSON hat kein aktives Billing. Geh in der Google Cloud "
                "Console auf Billing → My Projects, find das Projekt aus dem "
                "Service-Account, und verknüpfe es mit deinem Billing-Konto. "
                "(Hinweis: nur Cloud-TTS bucht aufs AI-Pro-Kontingent — die "
                "Gemini-Direct-API tut das NICHT.)"
            ) from exc
        # Spezialfall: Gemini-Voices auf Cloud-TTS routen intern über
        # Vertex AI / Agent Platform — die braucht eine SEPARATE API-
        # Aktivierung (aiplatform.googleapis.com), zusätzlich zur Cloud-TTS-API.
        if "aiplatform.googleapis.com" in full or "Agent Platform API" in full:
            raise TtsCloudTtsUnavailableError(
                "Cloud TTS API: Gemini-Voices erfordern die separat zu "
                "aktivierende Vertex AI / Agent Platform API "
                "(aiplatform.googleapis.com). Cloud Console → APIs & Services "
                "→ Library → 'Vertex AI API' bzw. 'Agent Platform API' suchen "
                "+ aktivieren."
            ) from exc
        if "API has not been used" in full or "SERVICE_DISABLED" in full:
            # Aus dem Original den Service-Namen extrahieren wenn möglich.
            import re as _re
            m = _re.search(r"([A-Z][\w ]+API)\s+has not been used", full)
            api_name = m.group(1) if m else "Eine benötigte Google-API"
            raise TtsCloudTtsUnavailableError(
                f"Cloud TTS-Aufruf scheitert weil {api_name} im "
                "Cloud-Projekt nicht aktiviert ist. Cloud Console → APIs & "
                "Services → Library → API-Name suchen + aktivieren."
            ) from exc
        if "PERMISSION_DENIED" in full:
            raise TtsCloudTtsUnavailableError(
                "Cloud TTS API: Permission denied. Das Service-Account-JSON hat "
                "wahrscheinlich nicht die Rolle 'Cloud Text-to-Speech User' oder "
                "die TTS-API ist im Projekt nicht aktiviert. Cloud Console → IAM "
                "+ APIs & Services prüfen."
            ) from exc
        # Server-side Glitch von Google (Gemini-TTS-Preview-Modelle haben das
        # öfter: "500 Unable to generate audio"). Transient — Retry kann
        # klappen. Cloud-TTS hat kein Key-Konzept, daher api_key="".
        #
        # Bevorzugt über den Exception-TYP klassifizieren statt über
        # Substrings im str(exc) — das ist robust gegen Message-Bodies die
        # zufällig "500"/"INTERNAL" enthalten ohne ein echtes 5xx zu sein.
        is_transient_5xx = False
        try:
            from google.api_core import exceptions as _gexc  # type: ignore
            is_transient_5xx = isinstance(
                exc, (_gexc.InternalServerError, _gexc.ServiceUnavailable)
            )
        except Exception:  # noqa: BLE001 — google-api-core evtl. nicht da
            pass
        exc_name = type(exc).__name__
        if (
            is_transient_5xx
            or "Unable to generate audio" in full
            or exc_name in ("InternalServerError", "ServiceUnavailable")
        ):
            raise TtsTransientError(
                api_key="",
                message=f"Cloud-TTS 5xx (server-side glitch): {full.splitlines()[0][:200]}",
                kind="5xx",
            ) from exc
        # Generischer Fall — wir kürzen die Message statt komplett zu propagieren
        short = full.splitlines()[0][:240]
        raise RuntimeError(f"Cloud-TTS-Fehler: {short}") from exc


def _synthesize_edge_tts(
    text: str,
    voice: str,
    speaking_rate: float,
) -> bytes:
    """Synthese via Microsoft Edge's "Read Aloud"-Endpoint (edge-tts-Library).

    Voice-Name auf Library-Ebene: ohne unseren `edge-`-Prefix
    (z.B. `de-DE-KatjaNeural`).

    Speaking-Rate: Edge-TTS akzeptiert `rate` als String wie `"+0%"`, `"-20%"`
    oder `"+25%"`. Wir mappen unseren Float (0.25 .. 2.0) auf das %-Format:
    1.0 → "+0%", 1.5 → "+50%", 0.5 → "-50%".

    Output: MP3-Bytes (24kHz mono, ~24 kbps).
    """
    import asyncio
    import edge_tts

    # Voice-Name vom Prefix befreien
    if voice.startswith(EDGE_VOICE_PREFIX):
        api_voice = voice[len(EDGE_VOICE_PREFIX):]
    else:
        api_voice = voice

    # Rate → %-String. Edge-TTS akzeptiert ganzzahlige Prozent-Deltas.
    delta_pct = round((speaking_rate - 1.0) * 100)
    rate_str = f"{'+' if delta_pct >= 0 else ''}{delta_pct}%"

    log.info(
        "edge-tts: synthesizing %d chars voice=%s rate=%s",
        len(text), api_voice, rate_str,
    )

    async def _run() -> bytes:
        communicate = edge_tts.Communicate(text, api_voice, rate=rate_str)
        chunks: list[bytes] = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                chunks.append(chunk["data"])
        return b"".join(chunks)

    try:
        # Edge-TTS-Lib ist async-only; wir starten eine eigene Event-Loop
        # in diesem Sync-Helper (er wird seinerseits aus asyncio.to_thread
        # aufgerufen, hat also keine laufende Loop).
        return asyncio.run(_run())
    except Exception as exc:  # noqa: BLE001
        # Edge-TTS-Fehler sind meist WebSocket-Probleme (Microsoft-Service
        # tot, Voice-Name unbekannt, Netzwerk-Glitch).
        short = str(exc).splitlines()[0][:200]
        log.warning("edge-tts error: %s (type=%s)", short, type(exc).__name__)
        # Als Transient klassifizieren — Retry kann klappen.
        raise TtsTransientError(
            api_key="",
            message=f"Edge-TTS Fehler: {short}",
            kind="5xx",
        ) from exc


# Erreichbarkeit des Vorlese-Dienstes. Wird bei jedem Statusabruf gebraucht,
# darf aber keine Anfrage aufhalten: deshalb ein kurzer Zwischenspeicher und
# ein knappes Zeitlimit. Loopback-Aufruf, der antwortet in Millisekunden oder
# gar nicht.
_WEB_TTS_CACHE: tuple[float, bool] = (0.0, False)
_WEB_TTS_CACHE_SEC = 60.0
_WEB_TTS_FEHLER_CACHE_SEC = 15.0


def gemini_web_available(force: bool = False) -> bool:
    """Sagt, ob der lokale Vorlese-Dienst antwortet und eine Sitzung hat."""
    import time as _t
    global _WEB_TTS_CACHE
    stand, letzter = _WEB_TTS_CACHE
    alter = _t.monotonic() - stand
    # Ein negatives Ergebnis kürzer glauben als ein positives: startet der
    # Dienst gerade neu, soll er nicht eine Minute lang als tot gelten.
    gueltig = _WEB_TTS_CACHE_SEC if letzter else _WEB_TTS_FEHLER_CACHE_SEC
    if not force and stand > 0 and alter < gueltig:
        return letzter
    ok = False
    try:
        r = httpx.get(f"{GEMINI_WEB_TTS_URL}/health", timeout=3.0)
        ok = r.status_code == 200 and bool(r.json().get("token"))
    except Exception as exc:  # noqa: BLE001 - jede Störung heisst schlicht "nein"
        log.debug("gemini-web-tts /health nicht erreichbar: %s", exc)
    _WEB_TTS_CACHE = (_t.monotonic(), ok)
    return ok


def _synthesize_gemini_web(text: str) -> bytes:
    """Synthese über den lokalen Vorlese-Dienst (Gemini-Web-Sitzung).

    Ausgabe ist Ogg/Opus, rund 60 kbit/s. Die Sprechgeschwindigkeit kann der
    Dienst nicht beeinflussen, deshalb nimmt diese Funktion auch keine
    entgegen: der Client stellt sie beim Abspielen ein.
    """
    log.info("gemini-web-tts: synthesizing %d chars via %s",
             len(text), GEMINI_WEB_TTS_URL)
    try:
        resp = httpx.post(
            f"{GEMINI_WEB_TTS_URL}/tts",
            json={"text": text, "lang": "de-DE"},
            # Grosszügig: 18.000 Zeichen brauchten gemessen rund 11 s, ein
            # langsames Netz zu Google darf das nicht sofort abwürgen.
            timeout=httpx.Timeout(90.0, connect=5.0),
        )
    except httpx.RequestError as exc:
        # Dienst nicht erreichbar (nicht gestartet, falscher Port). Als
        # transient melden: ein Neuversuch kann klappen, wenn er gerade neu
        # startet.
        raise TtsTransientError(
            api_key="",
            message=f"Vorlese-Dienst nicht erreichbar ({GEMINI_WEB_TTS_URL}): {exc}",
            kind="5xx",
        ) from exc

    if resp.status_code == 503:
        # Der Dienst lebt, aber die Google-Sitzung trägt nicht mehr. Ein
        # Neuversuch würde deterministisch wieder scheitern, deshalb ein
        # Dauerfehler mit einer Meldung, die sagt was zu tun ist.
        raise TtsSessionExpiredError(
            "Die Google-Sitzung des Vorlese-Dienstes ist abgelaufen. "
            "Auf dem Server neu anmelden: ~/gemini-tts/login.py"
        )
    if resp.status_code != 200:
        kurz = resp.text[:200].replace("\n", " ")
        raise TtsTransientError(
            api_key="",
            message=f"Vorlese-Dienst antwortete mit HTTP {resp.status_code}: {kurz}",
            kind="5xx",
        )
    audio = resp.content
    # Kopfdaten prüfen, bevor das an einen Player geht: eine JSON-Fehlermeldung
    # mit Statuscode 200 wäre sonst eine stumme, nie endende Wiedergabe.
    if not audio.startswith(b"OggS"):
        raise TtsTransientError(
            api_key="",
            message=f"Vorlese-Dienst lieferte kein Ogg ({len(audio)} Bytes)",
            kind="5xx",
        )
    return audio


def synthesize(
    text: str,
    voice: str = DEFAULT_VOICE,
    speaking_rate: float = DEFAULT_SPEED,
    provider: str = DEFAULT_PROVIDER,
    api_key: str | None = None,
    model_id: str | None = None,
) -> bytes:
    """Dispatch-Funktion: synthetisiert Text zu Audio.

    Returnt:
      - `provider="cloud_tts"`: MP3-Bytes
      - `provider="gemini_api"`: rohe PCM-Bytes (KEIN WAV-Header — der wird
        beim Streaming separat geschickt oder via `rebuild_wav` ergänzt).

    Für den Audio-File-Output (z.B. Caching) `synthesize_audio_file()` nutzen,
    das wrappt PCM in ein vollständiges WAV.
    """
    if provider not in VALID_PROVIDERS:
        raise ValueError(f"Unbekannter TTS-Provider: {provider!r}")

    cleaned = _strip_for_tts(text)
    if not cleaned:
        raise ValueError("Leerer Text nach Aufräumen — nichts zum Vorlesen.")
    # Gemini-Web verträgt ein Vielfaches dessen, was die anderen Anbieter in
    # einem Aufruf schaffen. Ihm die enge Grenze aufzuzwingen würde lange
    # Antworten mitten im Satz abschneiden, obwohl nichts dagegen spricht.
    grenze = GEMINI_WEB_MAX_CHARS if provider == PROVIDER_GEMINI_WEB else MAX_SYNTH_CHARS
    if len(cleaned) > grenze:
        cleaned = cleaned[:grenze] + " … Rest gekürzt."

    rate = _clamp_speed(speaking_rate)

    if provider == PROVIDER_GEMINI_API:
        if not api_key:
            # Pool ist erschöpft / acquire hat None zurückgegeben.
            # Spezielle Exception → Stream endet graceful.
            raise TtsPoolExhaustedError(
                "Kein TTS-API-Key verfügbar (alle Keys im Pool burned/erschöpft)."
            )
        return _synthesize_gemini_api(cleaned, voice, rate, api_key, model_id=model_id)

    if provider == PROVIDER_GEMINI_WEB:
        # Weder Stimme noch Geschwindigkeit sind hier einstellbar.
        return _synthesize_gemini_web(cleaned)

    if provider == PROVIDER_EDGE_TTS:
        # Idempotent: synthesize_chunked normalisiert die Voice bereits einmal
        # pro Stream. Direct-Calls (z.B. via synthesize_audio_file) gehen aber
        # an synthesize() OHNE Pre-Normalize — hier defensiv nochmal mappen.
        safe_voice = _normalize_voice_for_edge_tts(voice)
        return _synthesize_edge_tts(cleaned, safe_voice, rate)

    return _synthesize_cloud_tts(cleaned, voice, rate, model_id=model_id)


def synthesize_audio_file(
    text: str,
    voice: str = DEFAULT_VOICE,
    speaking_rate: float = DEFAULT_SPEED,
    provider: str = DEFAULT_PROVIDER,
    api_key: str | None = None,
    model_id: str | None = None,
) -> tuple[bytes, str]:
    """Convenience-Variante von `synthesize()` für Single-Shot-Calls.
    Returnt `(audio_bytes, media_type)` als komplette abspielbare Datei
    (WAV mit korrektem Header für gemini_api, MP3 für cloud_tts)."""
    raw = synthesize(text, voice, speaking_rate, provider, api_key, model_id=model_id)
    if provider == PROVIDER_GEMINI_API:
        return rebuild_wav(raw), MEDIA_TYPE_WAV
    if provider == PROVIDER_GEMINI_WEB:
        return raw, MEDIA_TYPE_OGG
    return raw, MEDIA_TYPE_MP3


# Chunking-Strategie: BALANCED DYNAMIC PROGRAMMING.
# Idee: statt feste Chunk-Größen
# durchprobieren wir mehrere Kandidaten-Caps zwischen PREFERRED und HARD_MAX,
# berechnen pro Cap per DP die optimale Partition, und wählen den, der unter
# unseren Parallelitäts-Constraints die schnellste Wallclock-Zeit ergibt.
# Vorteile gegenüber dem alten 50/150-Greedy:
#   - Kürzere Total-Latenz bei langen Texten (Wave-aware Score).
#   - Gleichmäßig große Chunks → keine Mini-Reste die nach Chunk-Größe rufen.
#   - Anpassung an Modell-Latenz (50 parallele Slots → wenn 60 Chunks → 2 Wellen).
# Quelle: ~/Library/Application Support/Claude/.../uploads/dynamic_chunking.md
PREFERRED_CHUNK_CHARS = 200
HARD_MAX_CHUNK_CHARS = 500
MAX_CHUNK_BYTES = 3800
MAX_CONCURRENT_TTS_REQUESTS = 50
BALANCED_MIN_RATIO = 0.5

# Wir bevorzugen Time-to-First-Audio: der ERSTE Chunk wird unabhängig vom DP
# auf eine kleine Größe gezwungen. Sobald er fertig ist, hört der User Audio,
# während die größeren Folge-Chunks parallel im Hintergrund laufen.
# Empirisch: Gemini-Flash-TTS braucht ~1.5s für 60-80 Zeichen,
#            ~3-4s für 180 Zeichen.
FIRST_CHUNK_FAST_START_CHARS = 80

# Unterhalb dieser Gesamtlänge wird gar nicht gechunkt — der Overhead lohnt nicht.
CHUNKING_MIN_TOTAL_CHARS = 200

# Sentence-Splitter (gleich wie zuvor, deutsche Satzgrenzen).
_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?:])\s+|\n{2,}|\n(?=[A-ZÄÖÜ])")
_CLAUSE_BOUNDARY_RE = re.compile(r"(?<=[,;])\s+")


def _utf8_len(text: str) -> int:
    """Byte-Länge für Google-Limits (das API-Limit ist Byte-, nicht Zeichen-basiert)."""
    return len(text.encode("utf-8"))


def _within_limit(text: str, max_chars: int, max_bytes: int) -> bool:
    return len(text) <= max_chars and _utf8_len(text) <= max_bytes


def _split_oversize_token(token: str, max_chars: int, max_bytes: int) -> list[str]:
    """Notfall: ein einzelnes Wort/Token ist länger als das Limit → hart schneiden."""
    parts: list[str] = []
    buf: list[str] = []
    for ch in token:
        candidate = "".join(buf) + ch
        if buf and not _within_limit(candidate, max_chars, max_bytes):
            parts.append("".join(buf))
            buf = [ch]
        else:
            buf.append(ch)
    if buf:
        parts.append("".join(buf))
    return parts


def _split_by_words(text: str, max_chars: int, max_bytes: int) -> list[str]:
    """Zerlegt einen langen Abschnitt an Wortgrenzen in API-Limit-konforme Stücke."""
    parts: list[str] = []
    buf = ""
    for word in text.split():
        candidate = f"{buf} {word}" if buf else word
        if _within_limit(candidate, max_chars, max_bytes):
            buf = candidate
            continue
        if buf:
            parts.append(buf)
            buf = ""
        if _within_limit(word, max_chars, max_bytes):
            buf = word
        else:
            parts.extend(_split_oversize_token(word, max_chars, max_bytes))
    if buf:
        parts.append(buf)
    return parts


def _tts_units(text: str, max_chars: int, max_bytes: int) -> list[str]:
    """Atomare Einheiten: erst Sätze, dann zu lange Sätze an Komma/Semikolon,
    dann an Wortgrenzen, im Notfall zeichenweise."""
    units: list[str] = []
    for sentence in _SENTENCE_BOUNDARY_RE.split(text):
        sentence = sentence.strip()
        if not sentence:
            continue
        if _within_limit(sentence, max_chars, max_bytes):
            units.append(sentence)
            continue
        for clause in _CLAUSE_BOUNDARY_RE.split(sentence):
            clause = clause.strip()
            if not clause:
                continue
            if _within_limit(clause, max_chars, max_bytes):
                units.append(clause)
            else:
                units.extend(_split_by_words(clause, max_chars, max_bytes))
    return units


def _prefix_lengths(units: list[str], *, in_bytes: bool = False) -> list[int]:
    """Präfix-Längen (kumulativ) für O(1)-Span-Längen im DP."""
    out = [0]
    total = 0
    for u in units:
        total += _utf8_len(u) if in_bytes else len(u)
        out.append(total)
    return out


def _span_len(prefix: list[int], start: int, end: int) -> int:
    """Länge von units[start:end] mit Single-Space-Joins."""
    if end <= start:
        return 0
    return prefix[end] - prefix[start] + (end - start - 1)


def _candidate_caps(preferred: int, hard_max: int, rounds: int = 5) -> list[int]:
    """Binär-Search-Kandidaten zwischen `preferred` und `hard_max`."""
    low, high = max(1, min(preferred, hard_max)), max(preferred, hard_max)
    caps = {low, high}
    intervals = [(low, high)]
    for _ in range(rounds):
        nxt: list[tuple[int, int]] = []
        for s, e in intervals:
            if e - s <= 1:
                continue
            m = (s + e) // 2
            caps.add(m)
            nxt.append((s, m))
            nxt.append((m, e))
        intervals = nxt
        if not intervals:
            break
    return sorted(caps)


def _balanced_partition(
    units: list[str],
    chars_prefix: list[int],
    bytes_prefix: list[int],
    cap_chars: int,
    min_chars: int,
    max_bytes: int,
) -> tuple[list[tuple[int, int]], int, int, int] | None:
    """DP: optimale Aufteilung von `units` in Chunks ≤ `cap_chars`.

    Bewertung (lexikographisch, kleinstes gewinnt):
    (chunk_count, small_chunk_count, small_char_deficit, max_chunk_len, balance_cost)

    Returnt (ranges, max_chunk_len, small_chunks, small_deficit) oder None
    wenn keine valide Aufteilung möglich ist.
    """
    n = len(units)
    best: list[tuple[int, int, int, int, int] | None] = [None] * (n + 1)
    prev = [-1] * (n + 1)
    best[0] = (0, 0, 0, 0, 0)

    for end in range(1, n + 1):
        for start in range(end - 1, -1, -1):
            chars = _span_len(chars_prefix, start, end)
            if chars > cap_chars:
                break  # weiter zurückgehen ändert auch nichts (length wächst)
            if _span_len(bytes_prefix, start, end) > max_bytes:
                break
            prior = best[start]
            if prior is None:
                continue
            deficit = max(0, min_chars - chars)
            small = 1 if deficit else 0
            cand = (
                prior[0] + 1,
                prior[1] + small,
                prior[2] + deficit,
                max(prior[3], chars),
                prior[4] + (cap_chars - chars) ** 2,
            )
            if best[end] is None or cand < best[end]:
                best[end] = cand
                prev[end] = start

    if best[n] is None:
        return None

    ranges: list[tuple[int, int]] = []
    e = n
    while e > 0:
        s = prev[e]
        if s < 0:
            return None
        ranges.append((s, e))
        e = s
    ranges.reverse()
    score = best[n]
    return ranges, score[3], score[1], score[2]


def _wave_score(
    cap: int,
    chunk_count: int,
    max_chunk_len: int,
    small_chunks: int,
    small_deficit: int,
    preferred: int,
    concurrency: int,
) -> tuple[int, int, int, int, int, int, int]:
    """Wallclock-Heuristik. Bei `concurrency` parallelen Slots laufen die
    Chunks in `waves` Wellen — Total ≈ waves × (Startup + größter-Chunk).

    Wenn alle Chunks in 1 Welle passen, gewinnen kleinere Chunks (kürzerer
    längster). Bei mehreren Wellen lohnen größere Chunks (weniger Wellen)."""
    waves = (chunk_count + concurrency - 1) // concurrency
    startup_weight = max(100, preferred)
    wallclock = waves * (startup_weight + max_chunk_len)
    return (wallclock, waves, max_chunk_len, small_deficit, small_chunks, chunk_count, cap)


def _split_into_chunks(
    text: str,
    fast_start: bool = True,
    max_chunks: int | None = None,
) -> list[str]:
    """Chunking-Pipeline mit zwei Strategien:

    1. Wenn `fast_start=True` (Default): erster Chunk wird klein gehalten
       (≤ `FIRST_CHUNK_FAST_START_CHARS`), damit Time-to-First-Audio minimal
       ist. Der Rest läuft durchs Balanced-DP.
    2. Wenn `fast_start=False`: kompletter Text via Balanced-DP.

    `max_chunks`: optionale Obergrenze für die Chunk-Anzahl. Wird vom Caller
    basierend auf der API-Key-Pool-Größe + Provider-Rate-Limits gesetzt.
    Wenn die Standard-Chunkgröße mehr als `max_chunks` ergeben würde,
    werden die Chunks ITERATIV vergrößert (Cap erhöht), bis das Limit
    eingehalten ist.

    Bei sehr kurzen Texten (< CHUNKING_MIN_TOTAL_CHARS) gibt's einen einzigen
    Chunk (`synthesize_chunked` macht dann einen direkten Call ohne Overhead).
    """
    text = text.strip()
    if not text:
        return []

    first_chunk: str | None = None
    remainder = text

    if fast_start and len(text) >= CHUNKING_MIN_TOTAL_CHARS:
        # Erstes Atom (= erster Satz) holen und nur dann als eigenen Chunk
        # rausziehen, wenn er unter dem Fast-Start-Limit liegt. Sonst hart
        # am Limit (bzw. an Komma/Wortgrenze) abschneiden.
        units_for_first = _tts_units(text, HARD_MAX_CHUNK_CHARS, MAX_CHUNK_BYTES)
        if units_for_first:
            first_atom = units_for_first[0]
            if len(first_atom) <= FIRST_CHUNK_FAST_START_CHARS:
                first_chunk = first_atom
                # remainder = alles nach dem ersten Atom
                remainder = text[len(first_atom):].lstrip()
            else:
                # Erstes Atom ist groß → an Komma/Semikolon teilen, ersten
                # passenden Sub-Teil als Chunk 0.
                subs = _CLAUSE_BOUNDARY_RE.split(first_atom)
                sub_buf = ""
                for sub in subs:
                    sub = sub.strip()
                    if not sub:
                        continue
                    candidate = f"{sub_buf} {sub}".strip() if sub_buf else sub
                    if len(candidate) <= FIRST_CHUNK_FAST_START_CHARS:
                        sub_buf = candidate
                    else:
                        break
                if sub_buf and len(sub_buf) >= 20:  # Mini-Mindestlänge
                    first_chunk = sub_buf
                    remainder = text[len(sub_buf):].lstrip()
            if first_chunk:
                log.debug("TTS fast-start: first_chunk=%d chars, remainder=%d",
                          len(first_chunk), len(remainder))

    # Rest durch das Balanced-DP (mit normalen Defaults erst)
    rest_chunks = _balanced_dp_chunks(remainder) if remainder else []

    if first_chunk:
        all_chunks = [first_chunk] + rest_chunks
    else:
        all_chunks = rest_chunks

    # Adaptive Rückskalierung: wenn `max_chunks` gesetzt ist und wir drüber
    # liegen, vergrößern wir die Chunks (außer dem fast-start-Chunk). Die
    # Schleife verdoppelt die Caps bis zum API-Hard-Limit (4000 Bytes/Field).
    if max_chunks is not None and len(all_chunks) > max_chunks:
        rest_target = max(1, max_chunks - (1 if first_chunk else 0))
        log.info(
            "TTS chunking: %d > max_chunks=%d → vergrößere Chunks (Ziel %d Rest-Chunks)",
            len(all_chunks), max_chunks, rest_target,
        )
        # Iterativ Caps verdoppeln bis Anzahl passt oder Hard-Limit erreicht
        pref = PREFERRED_CHUNK_CHARS
        hard = HARD_MAX_CHUNK_CHARS
        max_byte_per_field = 3800  # API-Hard-Limit
        max_chars_field = min(max_byte_per_field, 3500)  # konservativ unter Bytes-Limit
        for _attempt in range(6):
            new_pref = min(pref * 2, max_chars_field)
            new_hard = min(hard * 2, max_chars_field)
            rest_chunks = _balanced_dp_chunks_with_caps(remainder, new_pref, new_hard) \
                if remainder else []
            all_chunks = ([first_chunk] if first_chunk else []) + rest_chunks
            if len(all_chunks) <= max_chunks:
                break
            pref, hard = new_pref, new_hard
            if hard >= max_chars_field:
                break  # nichts mehr zu vergrößern

        # Falls wir trotz Hard-Limit immer noch über `max_chunks` liegen:
        # Rest-Chunks zusammenfassen, damit die Anzahl nie das RPM-Budget
        # (max_chunks) sprengt — sonst läuft der Aufrufer in Rate-Limits.
        if len(all_chunks) > max_chunks:
            log.warning(
                "TTS chunking: %d Chunks > max_chunks=%d trotz Max-Caps — "
                "führe überzählige Chunks zusammen",
                len(all_chunks), max_chunks,
            )
            head = all_chunks[: max_chunks - 1]
            tail = " ".join(all_chunks[max_chunks - 1:])
            all_chunks = head + [tail]

    log.info(
        "TTS chunking: %d chunks (fast_start=%s, sizes=%s, total=%d chars, max_chunks=%s)",
        len(all_chunks), fast_start and first_chunk is not None,
        [len(c) for c in all_chunks][:10], len(text), max_chunks,
    )
    return all_chunks


def _balanced_dp_chunks_with_caps(text: str, pref: int, hard: int) -> list[str]:
    """Wie `_balanced_dp_chunks`, aber mit konfigurierbaren Caps für die
    adaptive Rückskalierung. Wird nur intern aufgerufen, wenn die Standard-
    Caps zu viele Chunks ergeben hätten."""
    text = text.strip()
    if not text:
        return []
    min_chars = max(1, round(pref * BALANCED_MIN_RATIO))
    best_choice: tuple[list[tuple[int, int]], list[str], int, tuple] | None = None
    for cap in _candidate_caps(pref, hard):
        units = _tts_units(text, hard, MAX_CHUNK_BYTES)
        if not units:
            continue
        chars_prefix = _prefix_lengths(units)
        bytes_prefix = _prefix_lengths(units, in_bytes=True)
        result = _balanced_partition(
            units, chars_prefix, bytes_prefix, cap, min_chars, MAX_CHUNK_BYTES,
        )
        if result is None:
            continue
        ranges, max_chunk_len, small_chunks, small_deficit = result
        score = _wave_score(
            cap, len(ranges), max_chunk_len, small_chunks, small_deficit,
            pref, MAX_CONCURRENT_TTS_REQUESTS,
        )
        if best_choice is None or score < best_choice[3]:
            best_choice = (ranges, units, cap, score)
    if best_choice is None:
        return _tts_units(text, hard, MAX_CHUNK_BYTES) or [text]
    ranges, units, _cap, _score = best_choice
    return [" ".join(units[s:e]) for s, e in ranges]


def _balanced_dp_chunks(text: str) -> list[str]:
    """Reine Balanced-DP-Variante (kein Fast-Start). Findet die optimale
    Partition über alle Kandidaten-Caps."""
    text = text.strip()
    if not text:
        return []

    min_chars = max(1, round(PREFERRED_CHUNK_CHARS * BALANCED_MIN_RATIO))
    best_choice: tuple[list[tuple[int, int]], list[str], int, tuple] | None = None

    for cap in _candidate_caps(PREFERRED_CHUNK_CHARS, HARD_MAX_CHUNK_CHARS):
        units = _tts_units(text, HARD_MAX_CHUNK_CHARS, MAX_CHUNK_BYTES)
        if not units:
            continue
        chars_prefix = _prefix_lengths(units)
        bytes_prefix = _prefix_lengths(units, in_bytes=True)
        result = _balanced_partition(
            units, chars_prefix, bytes_prefix, cap, min_chars, MAX_CHUNK_BYTES,
        )
        if result is None:
            continue
        ranges, max_chunk_len, small_chunks, small_deficit = result
        score = _wave_score(
            cap, len(ranges), max_chunk_len, small_chunks, small_deficit,
            PREFERRED_CHUNK_CHARS, MAX_CONCURRENT_TTS_REQUESTS,
        )
        if best_choice is None or score < best_choice[3]:
            best_choice = (ranges, units, cap, score)

    if best_choice is None:
        units = _tts_units(text, HARD_MAX_CHUNK_CHARS, MAX_CHUNK_BYTES) or [text]
        return units

    ranges, units, _cap, _score = best_choice
    return [" ".join(units[s:e]) for s, e in ranges]


async def synthesize_chunked(
    text: str,
    voice: str = DEFAULT_VOICE,
    speaking_rate: float = DEFAULT_SPEED,
    provider: str = DEFAULT_PROVIDER,
    api_key: str | None = None,
    key_picker: "Callable[[], Awaitable[str | None]] | None" = None,  # type: ignore[name-defined]
    max_chunks: int | None = None,
    user_id: str | None = None,
    model_id: str | None = None,
    chunking_enabled: bool = True,
) -> AsyncIterator[bytes]:
    """Liefert Audio-Bytes als progressiver Stream.

    Text wird in Chunks gesplittet, alle Chunks laufen **parallel** durch die
    TTS-API. Der Server yielded Audio-Bytes in Reihenfolge.

    Multi-Key-Modus (für Gemini-API mit Pool aus mehreren Free-Tier-Keys):
    `key_picker` ist eine async-Funktion, die pro Chunk EINEN Key aus dem Pool
    auswählt (mit Rate-Limiter-Reservierung). Wenn `key_picker=None`, wird der
    statische `api_key` für alle Chunks verwendet (Single-Key-Modus).

    Format der gestreamten Bytes:
      - `provider="cloud_tts"`: MP3-Frames. Concatenieren natürlich.
      - `provider="gemini_api"`: Erster Yield = WAV-Header mit fake-Length,
        alle folgenden = rohe PCM-Bytes.
    """
    if provider not in VALID_PROVIDERS:
        raise ValueError(f"Unbekannter TTS-Provider: {provider!r}")

    cleaned = _strip_for_tts(text)
    if not cleaned:
        raise ValueError("Leerer Text nach Aufräumen — nichts zum Vorlesen.")
    if len(cleaned) > MAX_TOTAL_CHARS:
        cleaned = cleaned[:MAX_TOTAL_CHARS] + " … Rest gekürzt."
        log.warning("TTS-Stream: Text auf %d chars gekappt (Sicherheitsgrenze)",
                    MAX_TOTAL_CHARS)

    is_gemini_api = (provider == PROVIDER_GEMINI_API)
    is_edge_tts = (provider == PROVIDER_EDGE_TTS)
    # Ogg-Ströme lassen sich nicht aneinanderhängen, siehe chunking_default_for.
    # Das ist bewusst eine harte Sperre und keine Voreinstellung: eine von Hand
    # eingeschaltete Stückelung würde hier stumm kaputtes Audio erzeugen.
    if provider == PROVIDER_GEMINI_WEB:
        chunking_enabled = False

    # Voice EINMAL pro Stream auf den jeweiligen Provider mappen — sonst
    # spammt jeder der 12 Chunk-Calls denselben Voice-Fallback-Warning-Log.
    # Die normalisierte Voice geht dann an alle inner-Calls.
    if is_gemini_api:
        voice = f"gemini-{_normalize_voice_for_gemini_api(voice)}"
    elif is_edge_tts:
        voice = _normalize_voice_for_edge_tts(voice)

    async def _pick_key() -> str | None:
        if key_picker is not None:
            return await key_picker()
        return api_key

    # Helper für Single-Call mit Retry-on-429-und-Transient wie im Chunked-Pfad.
    async def _single_with_retry(chunk_text: str) -> bytes:
        key = await _pick_key()
        last_exc: Exception | None = None
        for _attempt in range(3):
            try:
                result = await asyncio.to_thread(
                    synthesize, chunk_text, voice, speaking_rate, provider, key,
                    model_id=model_id,
                )
                if user_id:
                    if provider == PROVIDER_GEMINI_API and key:
                        try:
                            from pocket_claude.server import _update_key_tier_on_success  # noqa
                            await _update_key_tier_on_success(user_id, key)
                        except Exception:
                            pass
                    elif provider == PROVIDER_CLOUD_TTS:
                        try:
                            from pocket_claude.server import _add_cloud_tts_chars  # noqa
                            await _add_cloud_tts_chars(user_id, len(chunk_text))
                        except Exception:
                            pass
                return result
            except TtsQuotaExceededError as e:
                last_exc = e
                try:
                    from pocket_claude.server import (
                        mark_key_burned, _update_key_tier_on_429,
                    )
                    mark_key_burned(e.api_key or "", e.retry_delay_sec, e.quota_id)
                    if user_id and e.api_key:
                        await _update_key_tier_on_429(
                            user_id, e.api_key, e.quota_id,
                        )
                except Exception:
                    pass
                if key_picker is None:
                    raise
                new_key = await key_picker()
                if new_key is None or new_key == key:
                    raise
                key = new_key
            except TtsTransientError as e:
                last_exc = e
                log.warning("TTS-Single transient (kind=%s): %s", e.kind, str(e)[:120])
                if _attempt < 2:
                    # Backoff vor dem nächsten Versuch — sofortiges Re-Try (vor
                    # allem im Single-Key-Modus, derselbe Endpoint) trifft ein
                    # 5xx genau dann wenn es am ehesten wieder failt.
                    await asyncio.sleep(
                        min(2 ** _attempt * 0.5, 4) + random.uniform(0, 0.3)
                    )
                if key_picker is not None:
                    new_key = await key_picker()
                    if new_key is not None:
                        key = new_key
        assert last_exc is not None
        raise last_exc

    # Single-Call-Pfad (kurzer Text, Chunking ergibt nur ein Stück, ODER
    # `chunking_enabled=False` weil Provider Free-Tier-RPD-limitiert ist).
    if not chunking_enabled or len(cleaned) < CHUNKING_MIN_TOTAL_CHARS:
        # Provider-spezifische Single-Call-Limits: Cloud-TTS hat 5000-Byte-
        # Hard-Limit pro Request, Gemini-Direct-API hat Token-Limit (~8k
        # Input-Tokens), Edge-TTS macht intern eigenes Chunking via
        # WebSocket — kein hartes Limit. Wir cappen daher nur für Cloud
        # und Gemini, NICHT für Edge.
        if not chunking_enabled and provider not in (PROVIDER_EDGE_TTS, PROVIDER_GEMINI_WEB):
            # Konservatives Soft-Limit (3500 Zeichen ≈ ~4900 UTF-8-Bytes für DE).
            # Sicher unter dem Cloud-TTS-5000-Byte-API-Hard-Limit.
            _NO_CHUNK_CHAR_LIMIT = 3500
            if len(cleaned) > _NO_CHUNK_CHAR_LIMIT:
                log.warning(
                    "TTS-Stream: chunking_enabled=False aber Text zu lang (%d > %d chars) "
                    "für Provider %s — kürze. Für lange Texte besser Chunking aktivieren.",
                    len(cleaned), _NO_CHUNK_CHAR_LIMIT, provider,
                )
                cleaned = cleaned[:_NO_CHUNK_CHAR_LIMIT] + " … Rest gekürzt."
        if not chunking_enabled and len(cleaned) >= CHUNKING_MIN_TOTAL_CHARS:
            log.info(
                "TTS-Stream: chunking_enabled=False — sende %d chars als single request "
                "(provider=%s, kein Chunk-Split)",
                len(cleaned), provider,
            )
        audio = await _single_with_retry(cleaned)
        if is_gemini_api:
            yield rebuild_wav(audio)
        else:
            yield audio
        return

    chunks = _split_into_chunks(cleaned, max_chunks=max_chunks)

    if len(chunks) <= 1:
        audio = await _single_with_retry(cleaned)
        if is_gemini_api:
            yield rebuild_wav(audio)
        else:
            yield audio
        return

    # Pre-Acquire eines Keys pro Chunk. Bei Multi-Key + Rate-Limiter blockiert
    # dieser Loop bis Slots frei sind — danach laufen alle Synth-Calls parallel.
    # Bei Single-Key oder kein-Picker: trivial.
    chunk_keys: list[str | None] = []
    for _ in chunks:
        chunk_keys.append(await _pick_key())

    log.info(
        "TTS-Stream: provider=%s voice=%s rate=%.2f chunks=%d concurrency=%d total_chars=%d "
        "distinct_keys=%d",
        provider, voice, speaking_rate, len(chunks),
        MAX_CONCURRENT_TTS_REQUESTS, len(cleaned),
        len({k for k in chunk_keys if k}),
    )

    # Per-Chunk-Wrapper mit Retry bei 429: wenn Google den Key als „erschöpft"
    # meldet, picken wir einen anderen Key aus dem Pool und versuchen erneut.
    # Max 3 Retries pro Chunk; danach geben wir auf und werfen die letzte
    # Exception nach oben.
    MAX_RETRIES_PER_CHUNK = 3

    async def _synth_one(chunk_text: str, initial_key: str | None) -> bytes:
        key = initial_key
        last_exc: Exception | None = None
        for attempt in range(MAX_RETRIES_PER_CHUNK):
            # `attempt` ist 0-basiert: erstes Try, dann bis zu 2 Retries.
            next_try_num = attempt + 1  # 1, 2, 3
            try:
                result = await asyncio.to_thread(
                    synthesize, chunk_text, voice, speaking_rate, provider, key,
                    model_id=model_id,
                )
                # Success → entsprechende Counter aktualisieren
                if user_id:
                    if provider == PROVIDER_GEMINI_API and key:
                        try:
                            from pocket_claude.server import _update_key_tier_on_success  # noqa
                            await _update_key_tier_on_success(user_id, key)
                        except Exception:
                            pass
                    elif provider == PROVIDER_CLOUD_TTS:
                        # Cloud-TTS-Zeichen-Verbrauch pro Monat zählen
                        try:
                            from pocket_claude.server import _add_cloud_tts_chars  # noqa
                            await _add_cloud_tts_chars(user_id, len(chunk_text))
                        except Exception:
                            pass
                return result
            except TtsPoolExhaustedError:
                # Pool komplett erschöpft → kein Retry sinnvoll. Direkt raisen,
                # Stream-Wrapper beendet graceful.
                raise
            except TtsQuotaExceededError as e:
                last_exc = e
                # Key burnen + Tier-Hint (free) aktualisieren
                try:
                    from pocket_claude.server import (
                        mark_key_burned, _update_key_tier_on_429,
                    )
                    mark_key_burned(e.api_key or "", e.retry_delay_sec, e.quota_id)
                    if user_id and e.api_key:
                        await _update_key_tier_on_429(
                            user_id, e.api_key, e.quota_id,
                        )
                except Exception:
                    pass
                if next_try_num >= MAX_RETRIES_PER_CHUNK:
                    log.warning(
                        "TTS-Chunk 429 (key=…%s, quota=%s): Retries erschöpft (%d/%d).",
                        (e.api_key or "")[-6:], e.quota_id,
                        next_try_num, MAX_RETRIES_PER_CHUNK,
                    )
                    break
                log.warning(
                    "TTS-Chunk 429 (key=…%s, quota=%s, retryDelay=%.0fs), versuche anderen Key (Versuch %d/%d).",
                    (e.api_key or "")[-6:], e.quota_id, e.retry_delay_sec,
                    next_try_num + 1, MAX_RETRIES_PER_CHUNK,
                )
                if key_picker is None:
                    raise
                new_key = await key_picker()
                if new_key is None:
                    # Pool jetzt komplett erschöpft → propagieren
                    raise TtsPoolExhaustedError(
                        "Alle Keys im Pool burned — kein Retry möglich."
                    ) from e
                key = new_key
            except TtsTransientError as e:
                last_exc = e
                if next_try_num >= MAX_RETRIES_PER_CHUNK:
                    log.warning(
                        "TTS-Chunk transient (kind=%s, key=…%s): Retries erschöpft (%d/%d).",
                        e.kind, (e.api_key or "")[-6:],
                        next_try_num, MAX_RETRIES_PER_CHUNK,
                    )
                    break
                log.warning(
                    "TTS-Chunk transient (kind=%s, key=…%s): %s — Retry %d/%d",
                    e.kind, (e.api_key or "")[-6:], str(e)[:120],
                    next_try_num + 1, MAX_RETRIES_PER_CHUNK,
                )
                # Backoff vor dem nächsten Versuch — sofortiges Re-Try gegen
                # ein 5xx hämmert die API genau dann wenn sie am ehesten
                # weiter failt (im Single-Key-Modus derselbe Endpoint).
                await asyncio.sleep(
                    min(2 ** attempt * 0.5, 4) + random.uniform(0, 0.3)
                )
                if key_picker is not None:
                    new_key = await key_picker()
                    if new_key is None:
                        raise TtsPoolExhaustedError(
                            "Alle Keys im Pool burned — kein Retry möglich."
                        ) from e
                    key = new_key
        assert last_exc is not None
        raise last_exc

    tasks = [
        asyncio.create_task(_synth_one(chunk, k))
        for chunk, k in zip(chunks, chunk_keys)
    ]

    async def _cleanup_remaining(remaining: list["asyncio.Task[bytes]"]) -> None:  # noqa: F821
        """Canceled + awaitet die übrigen Tasks. WICHTIG: ohne ein Await mit
        gather(..., return_exceptions=True) bleiben Task-Exceptions als
        'Task exception was never retrieved'-Warnungen im asyncio-Log hängen —
        bei 25 parallelen Chunks mit Cloud-TTS-Fehler waren das vorher 25
        Warnings mit kompletten Tracebacks pro fehlgeschlagenem Tap."""
        if not remaining:
            return
        for t in remaining:
            if not t.done():
                t.cancel()
        # gather mit return_exceptions=True schluckt alle (inkl. CancelledError);
        # wir wollten die Werte sowieso nicht mehr.
        await asyncio.gather(*remaining, return_exceptions=True)

    try:
        if is_gemini_api:
            yield streaming_wav_header()
        for i, task in enumerate(tasks):
            try:
                audio_bytes = await task
            except (
                TtsQuotaExceededError,
                TtsTransientError,
                TtsPoolExhaustedError,
                TtsCloudTtsUnavailableError,
            ) as e:
                # Alle Retries für diesen Chunk durch — wir crashen NICHT den
                # ganzen Stream. Bisherige Chunks sind raus; restliche Tasks
                # abbrechen + awaiten, Client bekommt bereits geyieldete Bytes
                # + sauberes Stream-Ende.
                if isinstance(e, TtsPoolExhaustedError):
                    kind = "pool-exhausted"
                elif isinstance(e, TtsCloudTtsUnavailableError):
                    kind = "cloud-tts-unavailable"
                elif isinstance(e, TtsQuotaExceededError):
                    kind = "quota"
                else:
                    kind = "transient"
                log.warning(
                    "TTS-Stream: chunk %d/%d fehlgeschlagen (%s: %s) — "
                    "stoppe Stream gracefully bei %d gelieferten Chunks.",
                    i + 1, len(tasks), kind, str(e)[:160], i,
                )
                await _cleanup_remaining(tasks[i + 1:])
                return
            log.info("TTS-Stream: chunk %d/%d ready (%d bytes)",
                     i + 1, len(tasks), len(audio_bytes))
            yield audio_bytes
    except BaseException:
        # Auch bei asyncio.CancelledError (Client-Disconnect) wollen wir die
        # Worker-Tasks aufräumen, sonst laufen sie weiter und feuern noch
        # API-Calls ab. `BaseException` deckt das mit ab.
        await _cleanup_remaining(tasks)
        raise
