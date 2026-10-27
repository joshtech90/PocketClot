"""Vorlesen: Text zu Audio, nur ueber kostenlose Wege.

Drei Anbieter, pro Nutzer waehlbar (KV `tts_provider`):

1. **Grok** (`provider="grok"`, Vorgabe seit 21.10.2026): ein kleiner Dienst auf
   demselben Rechner (127.0.0.1:8812) haelt eine angemeldete Grok-Sitzung und
   liefert MP3. 28 Stimmen, Tempo macht der Dienst selbst (0,5 bis 2,0).
2. **Gemini Web** (`provider="gemini_web"`): Dienst auf 127.0.0.1:8811 mit
   angemeldeter Google-Sitzung, liefert Ogg/Opus. Eine einzige Stimme, das
   Tempo stellt der Client beim Abspielen ein.
3. **Edge** (`provider="edge_tts"`): Microsofts Vorlesefunktion ueber die
   `edge-tts`-Library, ohne Anmeldung, MP3.

Google Cloud TTS und die kostenpflichtige Gemini-API sind seit dem 21.10.2026
raus (Joschas Entscheidung: nur noch kostenlose Wege im Code).

`synthesize_chunked` kann den Text an Satzgrenzen teilen, die Stuecke parallel
erzeugen und in Reihenfolge streamen. Das geht nur mit MP3 (Edge, Grok);
Ogg-Stroeme lassen sich nicht aneinanderhaengen.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import random
import re
from typing import AsyncIterator

import httpx

log = logging.getLogger(__name__)


class TtsTransientError(RuntimeError):
    """Voruebergehender Fehler (Zeitueberschreitung, 5xx, Dienst startet neu).
    Ein erneuter Versuch kann klappen."""
    def __init__(self, api_key: str, message: str, kind: str = "transient"):
        super().__init__(message)
        self.api_key = api_key
        self.kind = kind  # "timeout" | "5xx" | "transient"


class TtsSessionExpiredError(RuntimeError):
    """Die Sitzung eines Vorlese-Dienstes (Gemini Web oder Grok) traegt nicht
    mehr. Erneut versuchen ist sinnlos, es hilft nur eine neue Anmeldung auf
    dem Server."""


# Anbieter
PROVIDER_EDGE_TTS = "edge_tts"
PROVIDER_GEMINI_WEB = "gemini_web"
PROVIDER_GROK = "grok"
VALID_PROVIDERS = {PROVIDER_EDGE_TTS, PROVIDER_GEMINI_WEB, PROVIDER_GROK}

# Adressen der lokalen Vorlese-Dienste. Laeuft einer nicht oder hat keine
# Sitzung, taucht er nicht als verfuegbar auf und niemand wird umgestellt.
GEMINI_WEB_TTS_URL = os.environ.get("GEMINI_WEB_TTS_URL", "http://127.0.0.1:8811").rstrip("/")
GROK_TTS_URL = os.environ.get("GROK_TTS_URL", "http://127.0.0.1:8812").rstrip("/")
# Die Dienste deckeln selbst (Gemini 20.000, Grok 10.000 Zeichen); hier etwas
# darunter bleiben, damit die Kuerzung bei uns passiert und nicht dort scheitert.
GEMINI_WEB_MAX_CHARS = 18000
# Der Grok-Dienst teilt lange Texte selbst in Abschnitte (6 parallel) und
# streamt; er nimmt bis zu 20.000 Zeichen.
GROK_MAX_CHARS = 19000

# Vorgabe, wenn ein Nutzer nichts gewaehlt hat und der Server nicht nachsehen
# kann, was laeuft. Die eigentliche Auswahl macht server._resolve_provider_with_kv.
DEFAULT_PROVIDER = PROVIDER_GROK

# Media-Types fuer die Clients.
MEDIA_TYPE_MP3 = "audio/mpeg"
MEDIA_TYPE_OGG = "audio/ogg"


def media_type_for(provider: str) -> str:
    # Gemini Web liefert Ogg/Opus, Edge und Grok MP3.
    if provider == PROVIDER_GEMINI_WEB:
        return MEDIA_TYPE_OGG
    return MEDIA_TYPE_MP3


# ===== Edge =====
# Interne Stimm-IDs tragen den Praefix `edge-`, die Library bekommt den Namen
# ohne (z.B. "de-DE-KatjaNeural").
EDGE_VOICE_PREFIX = "edge-"
EDGE_VOICES_DE: list[dict] = [
    {"voice": "de-DE-KatjaNeural", "gender": "FEMALE", "label": "Katja"},
    {"voice": "de-DE-AmalaNeural", "gender": "FEMALE", "label": "Amala"},
    {"voice": "de-DE-ConradNeural", "gender": "MALE", "label": "Conrad"},
    {"voice": "de-DE-KillianNeural", "gender": "MALE", "label": "Killian"},
    {"voice": "de-DE-FlorianMultilingualNeural", "gender": "MALE", "label": "Florian (multilingual)"},
    {"voice": "de-DE-SeraphinaMultilingualNeural", "gender": "FEMALE", "label": "Seraphina (multilingual)"},
]
EDGE_VOICES: set[str] = {f"{EDGE_VOICE_PREFIX}{v['voice']}" for v in EDGE_VOICES_DE}

# ===== Grok =====
# 28 Stimmen, alle mehrsprachig (GET /voices des Dienstes, Hoerproben auf
# Joschas Mac unter ~/Desktop/grok-vorlesen/stimmen/). Interne ID `grok-<name>`.
GROK_VOICE_PREFIX = "grok-"
GROK_VOICES: list[tuple[str, str]] = [
    ("altair", "MALE"), ("ara", "FEMALE"), ("atlas", "MALE"), ("aurora", "FEMALE"),
    ("carina", "FEMALE"), ("castor", "MALE"), ("celeste", "FEMALE"), ("cosmo", "MALE"),
    ("eve", "FEMALE"), ("helios", "MALE"), ("helix", "MALE"), ("iris", "FEMALE"),
    ("kepler", "MALE"), ("leo", "MALE"), ("liora", "FEMALE"), ("lumen", "MALE"),
    ("luna", "FEMALE"), ("lux", "MALE"), ("naksh", "MALE"), ("orion", "MALE"),
    ("perseus", "MALE"), ("rex", "MALE"), ("rigel", "MALE"), ("sal", "MALE"),
    ("sirius", "MALE"), ("ursa", "FEMALE"), ("zagan", "MALE"), ("zenith", "MALE"),
]
GROK_VOICE_NAMES: set[str] = {name for name, _ in GROK_VOICES}
# Grok kann 0,5 bis 2,0; langsamer lehnt der Dienst ab.
GROK_MIN_SPEED = 0.5

_EDGE_ONLY = [PROVIDER_EDGE_TTS]
_WEB_ONLY = [PROVIDER_GEMINI_WEB]
_GROK_ONLY = [PROVIDER_GROK]

_GENDER_LABEL = {"MALE": "männlich", "FEMALE": "weiblich"}

CURATED_VOICES: list[dict] = (
    # Grok zuerst: das ist die Vorgabe. Leo steht vorne.
    [{"id": "grok-leo", "label": "Grok Leo — männlich", "gender": "MALE",
      "tier": "grok", "compatible_providers": _GROK_ONLY}]
    + [{"id": f"{GROK_VOICE_PREFIX}{name}",
        "label": f"Grok {name.capitalize()} — {_GENDER_LABEL[gender]}",
        "gender": gender, "tier": "grok", "compatible_providers": _GROK_ONLY}
       for name, gender in GROK_VOICES if name != "leo"]
    # Gemini Web: eine einzige Stimme. Trotzdem als Eintrag gefuehrt, sonst
    # stuende die Liste leer da, sobald dieser Anbieter aktiv ist.
    + [{"id": "geminiweb-standard", "label": "Gemini (Standard, keine Auswahl)",
        "gender": "FEMALE", "tier": "geminiweb", "compatible_providers": _WEB_ONLY}]
    + [{"id": f"{EDGE_VOICE_PREFIX}{v['voice']}",
        "label": f"Edge {v['label']} — {_GENDER_LABEL[v['gender']]}",
        "gender": v["gender"], "tier": "edge", "compatible_providers": _EDGE_ONLY}
       for v in EDGE_VOICES_DE]
)

DEFAULT_VOICE_EDGE_TTS = "edge-de-DE-KatjaNeural"
# Gemini Web kennt keine Stimmauswahl; die ID haelt Cache und Liste stabil.
DEFAULT_VOICE_GEMINI_WEB = "geminiweb-standard"
DEFAULT_VOICE_GROK = "grok-leo"
DEFAULT_VOICE = DEFAULT_VOICE_GROK


def default_voice_for(provider: str | None) -> str:
    """Vorgabe-Stimme passend zum Anbieter."""
    if provider == PROVIDER_EDGE_TTS:
        return DEFAULT_VOICE_EDGE_TTS
    if provider == PROVIDER_GEMINI_WEB:
        return DEFAULT_VOICE_GEMINI_WEB
    return DEFAULT_VOICE_GROK


def provider_for_voice(voice: str | None) -> str | None:
    """Welcher Anbieter zu einer Stimm-ID gehoert (None = unbekannt)."""
    v = voice or ""
    if v.startswith(GROK_VOICE_PREFIX):
        return PROVIDER_GROK
    if v.startswith(EDGE_VOICE_PREFIX):
        return PROVIDER_EDGE_TTS
    if v.startswith("geminiweb-"):
        return PROVIDER_GEMINI_WEB
    return None


def chunking_default_for(provider: str | None) -> bool:
    """Stueckeln ist bei allen drei Anbietern standardmaessig aus.

    - edge_tts: eine WebSocket-Sitzung pro Aufruf, Stueckeln bringt nichts.
    - grok: der Dienst teilt lange Texte selbst (an Absaetzen, nie mitten im
      Satz) und streamt; ein zweites Stueckeln hier waere nur langsamer.
    - gemini_web: Pflicht, nicht Abwaegung. Ogg-Stroeme lassen sich nicht
      aneinanderhaengen; gestueckelt kaeme nur der erste Teil an.
    """
    return False


# Tempo-Grenzen
MIN_SPEED = 0.25
MAX_SPEED = 2.0
DEFAULT_SPEED = 1.0


# Emojis wuerden als Unicode-Name vorgelesen ("waving hand"), deshalb raus.
_EMOJI_PATTERN = re.compile(
    "["
    "\U0001F1E0-\U0001F1FF"
    "\U0001F300-\U0001F5FF"
    "\U0001F600-\U0001F64F"
    "\U0001F680-\U0001F6FF"
    "\U0001F700-\U0001F77F"
    "\U0001F780-\U0001F7FF"
    "\U0001F800-\U0001F8FF"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FA6F"
    "\U0001FA70-\U0001FAFF"
    "\U00002600-\U000026FF"
    "\U00002700-\U000027BF"
    "\U0001F004-\U0001F0CF"
    "\U0000FE0E-\U0000FE0F"
    "\U0001F018-\U0001F270"
    "\U0000200D"
    "\U000020E3"
    "]",
    flags=re.UNICODE,
)


def _strip_for_tts(text: str) -> str:
    """Bereitet Markdown-haltigen Text für TTS auf."""
    if not text:
        return ""
    # Code-Blöcke entfernen (werden sonst als endlose Zeichenfolge vorgelesen)
    text = re.sub(r"```[\s\S]*?```", " ", text)
    # Quellen-Block, den openai_engine ans Ende haengt (vor dem Fett-Entfernen) ("**Quellen**" plus
    # Linkliste): nur Titel und Domains, beim Zuhoeren reines Rauschen.
    text = re.sub(r"(?:^|\n)\s*\*\*Quellen\*\*\s*\n(?:\s*\d+\.\s.*(?:\n|$))*\s*$", "\n", text)
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
    # Quellen-Fussnoten: Definitionen am Ende ganz raus, Verweise im Text
    # ("[^1]") ebenso, sonst liest der Dienst die Zeichen vor.
    text = re.sub(r"^\[\^[^\]]+\]:.*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\[\^[^\]]+\]", "", text)
    # Emojis komplett raus
    text = _EMOJI_PATTERN.sub("", text)
    # Mehrfache Leerzeichen / Newlines
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


# Sicherheitsgrenze fuer den Gesamttext, damit ein riesiger Text nicht
# Hunderte paralleler Aufrufe ausloest.
MAX_TOTAL_CHARS = 100_000

# Grenze fuer einen einzelnen Edge-Aufruf ohne Stueckeln.
MAX_SYNTH_CHARS = 4800


def _clamp_speed(speed: float | None) -> float:
    """Begrenzt das Tempo auf [MIN_SPEED, MAX_SPEED]. None → DEFAULT_SPEED."""
    if speed is None:
        return DEFAULT_SPEED
    try:
        s = float(speed)
    except (TypeError, ValueError):
        return DEFAULT_SPEED
    return min(max(s, MIN_SPEED), MAX_SPEED)


def _normalize_voice_for_edge_tts(voice: str) -> str:
    """Eine fremde Stimme (Grok, Gemini) wuerde Edge per WebSocket ablehnen;
    dann die Edge-Vorgabe nehmen."""
    if voice and voice.startswith(EDGE_VOICE_PREFIX):
        if voice[len(EDGE_VOICE_PREFIX):] in {v["voice"] for v in EDGE_VOICES_DE}:
            return voice
    log.warning("Stimme %r passt nicht zu Edge — nehme %r", voice, DEFAULT_VOICE_EDGE_TTS)
    return DEFAULT_VOICE_EDGE_TTS


def _normalize_voice_for_grok(voice: str) -> str:
    """`grok-leo` → `leo`. Eine fremde oder unbekannte Stimme wird Leo."""
    if voice and voice.startswith(GROK_VOICE_PREFIX):
        name = voice[len(GROK_VOICE_PREFIX):].lower()
        if name in GROK_VOICE_NAMES:
            return name
    if voice != DEFAULT_VOICE_GROK:
        log.warning("Stimme %r passt nicht zu Grok — nehme %r", voice, DEFAULT_VOICE_GROK)
    return DEFAULT_VOICE_GROK[len(GROK_VOICE_PREFIX):]


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

# Erreichbarkeit des Grok-Dienstes, wie bei Gemini Web kurz zwischengespeichert.
_GROK_TTS_CACHE: tuple[float, bool] = (0.0, False)


def grok_available(force: bool = False) -> bool:
    """Sagt, ob der lokale Grok-Dienst antwortet und eine Sitzung hat."""
    import time as _t
    global _GROK_TTS_CACHE
    stand, letzter = _GROK_TTS_CACHE
    gueltig = _WEB_TTS_CACHE_SEC if letzter else _WEB_TTS_FEHLER_CACHE_SEC
    if not force and stand > 0 and _t.monotonic() - stand < gueltig:
        return letzter
    ok = False
    try:
        r = httpx.get(f"{GROK_TTS_URL}/health", timeout=3.0)
        ok = r.status_code == 200 and r.json().get("ok") is True
    except Exception as exc:  # noqa: BLE001 - jede Stoerung heisst schlicht "nein"
        log.debug("grok-tts /health nicht erreichbar: %s", exc)
    _GROK_TTS_CACHE = (_t.monotonic(), ok)
    return ok


def _grok_body(text: str, voice: str, speaking_rate: float, stream: bool) -> dict:
    speed = min(max(speaking_rate, GROK_MIN_SPEED), MAX_SPEED)
    return {"text": text, "voice": _normalize_voice_for_grok(voice), "lang": "de",
            "speed": speed, "format": "mp3", "stream": stream}


def _looks_like_mp3(head: bytes) -> bool:
    return head.startswith(b"ID3") or (len(head) > 1 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0)


async def _stream_grok(text: str, voice: str, speaking_rate: float) -> AsyncIterator[bytes]:
    """Reicht das MP3 des Grok-Dienstes Stueck fuer Stueck durch, sobald es
    ankommt: das erste Audio ist nach rund einer halben Sekunde da, egal wie
    lang der Text ist (gemessen auf Paradies: 5.220 Zeichen, erstes Audio nach
    0,6 s, fertig nach 7 s; gepuffert waren es bei 2.476 Zeichen 13 s Stille).

    Fehler vor dem ersten Byte kommen mit Status (503 = Sitzung weg). Bricht
    der Dienst danach ab, fehlt das Schlussstueck der Uebertragung; httpx meldet
    das, und daraus wird ein TtsTransientError, damit niemand ein halbes Audio
    fuer fertig haelt.
    """
    body = _grok_body(text, voice, speaking_rate, stream=True)
    log.info("grok-tts: streaming %d chars voice=%s speed=%.2f", len(text), body["voice"], body["speed"])
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=5.0)) as client:
            async with client.stream("POST", f"{GROK_TTS_URL}/tts", json=body) as resp:
                if resp.status_code == 503:
                    await resp.aread()
                    raise TtsSessionExpiredError(
                        "Die Grok-Sitzung des Vorlese-Dienstes fehlt oder ist abgelaufen. "
                        "Auf dem Server neu anmelden: ~/grok-tts/README.md")
                if resp.status_code != 200:
                    kurz = (await resp.aread())[:200].decode("utf-8", "replace").replace("\n", " ")
                    raise TtsTransientError(
                        api_key="", message=f"Grok-Vorlesedienst antwortete mit HTTP {resp.status_code}: {kurz}",
                        kind="5xx")
                kopf = b""
                async for teil in resp.aiter_bytes():
                    if not teil:
                        continue
                    if kopf is not None:
                        kopf += teil
                        if len(kopf) < 3:
                            continue
                        if not _looks_like_mp3(kopf):
                            raise TtsTransientError(
                                api_key="", message=f"Grok-Vorlesedienst lieferte kein MP3 ({len(kopf)} Bytes)",
                                kind="5xx")
                        teil, kopf = kopf, None
                    yield teil
                if kopf:   # sehr kurzer Rest, der nie die Pruefgroesse erreichte
                    yield kopf
    except httpx.HTTPError as exc:
        raise TtsTransientError(
            api_key="", message=f"Grok-Vorlesedienst abgebrochen ({GROK_TTS_URL}): {exc}", kind="5xx",
        ) from exc


def _synthesize_grok(text: str, voice: str, speaking_rate: float) -> bytes:
    """Synthese ueber den lokalen Grok-Dienst als fertige Datei. MP3, das Tempo
    rechnet der Dienst ein (deshalb gehoert es bei Grok in den Cache-Schluessel).
    Fuers Vorlesen im Chat wird stattdessen `_stream_grok` benutzt."""
    body = _grok_body(text, voice, speaking_rate, stream=False)
    log.info("grok-tts: synthesizing %d chars voice=%s speed=%.2f", len(text), body["voice"], body["speed"])
    try:
        resp = httpx.post(
            f"{GROK_TTS_URL}/tts",
            json=body,
            timeout=httpx.Timeout(120.0, connect=5.0),
        )
    except httpx.RequestError as exc:
        raise TtsTransientError(
            api_key="", message=f"Grok-Vorlesedienst nicht erreichbar ({GROK_TTS_URL}): {exc}",
            kind="5xx",
        ) from exc
    if resp.status_code == 503:
        raise TtsSessionExpiredError(
            "Die Grok-Sitzung des Vorlese-Dienstes fehlt oder ist abgelaufen. "
            "Auf dem Server neu anmelden: ~/grok-tts/README.md"
        )
    if resp.status_code != 200:
        kurz = resp.text[:200].replace("\n", " ")
        raise TtsTransientError(
            api_key="", message=f"Grok-Vorlesedienst antwortete mit HTTP {resp.status_code}: {kurz}",
            kind="5xx",
        )
    audio = resp.content
    # MP3 beginnt mit einem ID3-Kopf oder direkt mit einem Frame (0xFFE…).
    # Eine JSON-Fehlermeldung mit 200 waere sonst eine stumme Wiedergabe.
    if not _looks_like_mp3(audio):
        raise TtsTransientError(
            api_key="", message=f"Grok-Vorlesedienst lieferte kein MP3 ({len(audio)} Bytes)", kind="5xx",
        )
    return audio


def mark_unavailable(provider: str) -> None:
    """Ein Dienst hat gerade eine abgelaufene Sitzung gemeldet: bis zur
    naechsten Pruefung als nicht nutzbar fuehren, statt noch bis zu einer
    Minute dem alten "ja" zu glauben."""
    import time as _t
    global _WEB_TTS_CACHE, _GROK_TTS_CACHE
    if provider == PROVIDER_GROK:
        _GROK_TTS_CACHE = (_t.monotonic(), False)
    elif provider == PROVIDER_GEMINI_WEB:
        _WEB_TTS_CACHE = (_t.monotonic(), False)


def _max_chars_for(provider: str) -> int:
    if provider == PROVIDER_GEMINI_WEB:
        return GEMINI_WEB_MAX_CHARS
    if provider == PROVIDER_GROK:
        return GROK_MAX_CHARS
    return MAX_SYNTH_CHARS


def synthesize(
    text: str,
    voice: str = DEFAULT_VOICE,
    speaking_rate: float = DEFAULT_SPEED,
    provider: str = DEFAULT_PROVIDER,
) -> bytes:
    """Synthetisiert Text zu Audio (MP3 bei Edge und Grok, Ogg bei Gemini Web)."""
    if provider not in VALID_PROVIDERS:
        raise ValueError(f"Unbekannter TTS-Provider: {provider!r}")
    cleaned = _strip_for_tts(text)
    if not cleaned:
        raise ValueError("Leerer Text nach Aufräumen — nichts zum Vorlesen.")
    grenze = _max_chars_for(provider)
    if len(cleaned) > grenze:
        cleaned = cleaned[:grenze] + " … Rest gekürzt."
    rate = _clamp_speed(speaking_rate)
    if provider == PROVIDER_GEMINI_WEB:
        # Weder Stimme noch Tempo sind hier einstellbar.
        return _synthesize_gemini_web(cleaned)
    if provider == PROVIDER_GROK:
        return _synthesize_grok(cleaned, voice, rate)
    return _synthesize_edge_tts(cleaned, _normalize_voice_for_edge_tts(voice), rate)


def synthesize_audio_file(
    text: str,
    voice: str = DEFAULT_VOICE,
    speaking_rate: float = DEFAULT_SPEED,
    provider: str = DEFAULT_PROVIDER,
) -> tuple[bytes, str]:
    """Wie `synthesize()`, liefert zusaetzlich den Media-Type."""
    return synthesize(text, voice, speaking_rate, provider), media_type_for(provider)

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
    max_chunks: int | None = None,
    chunking_enabled: bool = False,
    strict: bool = False,
) -> AsyncIterator[bytes]:
    """Liefert Audio-Bytes als Stream.

    Mit Stueckeln wird der Text geteilt, alle Teile laufen parallel, und die
    Bytes kommen in Reihenfolge. Das geht nur mit MP3 (Edge, Grok); bei
    Gemini Web ist es hart abgeschaltet.

    Scheitert ein spaeteres Stueck, endet der Stream normalerweise nach dem,
    was schon raus ist. Mit `strict=True` gibt es stattdessen den Fehler: die
    Vorab-Erzeugung darf ein halbes Audio nicht als fertig zwischenspeichern.
    """
    if provider not in VALID_PROVIDERS:
        raise ValueError(f"Unbekannter TTS-Provider: {provider!r}")

    cleaned = _strip_for_tts(text)
    if not cleaned:
        raise ValueError("Leerer Text nach Aufräumen — nichts zum Vorlesen.")
    if len(cleaned) > MAX_TOTAL_CHARS:
        cleaned = cleaned[:MAX_TOTAL_CHARS] + " … Rest gekürzt."
        log.warning("TTS-Stream: Text auf %d chars gekappt (Sicherheitsgrenze)", MAX_TOTAL_CHARS)

    # Grok streamt und teilt selbst: Bytes durchreichen, sobald sie da sind.
    # Ein Neuversuch nur, solange noch nichts geliefert ist.
    if provider == PROVIDER_GROK:
        if len(cleaned) > GROK_MAX_CHARS:
            cleaned = cleaned[:GROK_MAX_CHARS] + " … Rest gekürzt."
        rate = _clamp_speed(speaking_rate)
        for attempt in range(2):
            geliefert = False
            try:
                # aclosing: bricht der Hoerer ab, wird die Verbindung zum Dienst
                # sofort geschlossen und nicht erst beim Aufraeumen der Loop.
                async with contextlib.aclosing(_stream_grok(cleaned, voice, rate)) as strom:
                    async for teil in strom:
                        geliefert = True
                        yield teil
                return
            except TtsTransientError as e:
                if geliefert or attempt == 1:
                    raise
                log.warning("Grok-Stream transient vor dem ersten Byte: %s — neuer Versuch", str(e)[:120])
                await asyncio.sleep(0.5)

    # Ogg-Stroeme lassen sich nicht aneinanderhaengen: harte Sperre, keine
    # Voreinstellung, sonst erzeugt ein von Hand eingeschalteter Schalter
    # stumm kaputtes Audio.
    if provider == PROVIDER_GEMINI_WEB:
        chunking_enabled = False
    # Stimme einmal pro Stream auf den Anbieter abbilden, nicht pro Stueck.
    if provider == PROVIDER_EDGE_TTS:
        voice = _normalize_voice_for_edge_tts(voice)

    async def _with_retry(chunk_text: str) -> bytes:
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                return await asyncio.to_thread(synthesize, chunk_text, voice, speaking_rate, provider)
            except TtsTransientError as e:
                last_exc = e
                log.warning("TTS transient (kind=%s): %s — Versuch %d/3", e.kind, str(e)[:120], attempt + 1)
                if attempt < 2:
                    await asyncio.sleep(min(2 ** attempt * 0.5, 4) + random.uniform(0, 0.3))
        assert last_exc is not None
        raise last_exc

    if not chunking_enabled or len(cleaned) < CHUNKING_MIN_TOTAL_CHARS:
        yield await _with_retry(cleaned)
        return

    chunks = _split_into_chunks(cleaned, max_chunks=max_chunks)
    if len(chunks) <= 1:
        yield await _with_retry(cleaned)
        return

    log.info("TTS-Stream: provider=%s voice=%s rate=%.2f chunks=%d total_chars=%d",
             provider, voice, speaking_rate, len(chunks), len(cleaned))
    sem = asyncio.Semaphore(MAX_CONCURRENT_TTS_REQUESTS)

    async def _one(chunk_text: str) -> bytes:
        async with sem:
            return await _with_retry(chunk_text)

    tasks = [asyncio.create_task(_one(c)) for c in chunks]

    async def _cleanup(remaining: list["asyncio.Task[bytes]"]) -> None:  # noqa: F821
        """Uebrige Aufgaben abbrechen UND abwarten, sonst bleiben 'Task
        exception was never retrieved'-Warnungen im Log haengen."""
        for t in remaining:
            if not t.done():
                t.cancel()
        if remaining:
            await asyncio.gather(*remaining, return_exceptions=True)

    try:
        for i, task in enumerate(tasks):
            try:
                audio_bytes = await task
            except (TtsTransientError, TtsSessionExpiredError) as e:
                # Nicht den ganzen Stream abstuerzen lassen: was schon raus
                # ist, bleibt, der Rest endet sauber.
                log.warning("TTS-Stream: Stueck %d/%d fehlgeschlagen (%s) — Ende bei %d Stuecken.",
                            i + 1, len(tasks), str(e)[:160], i)
                await _cleanup(tasks[i + 1:])
                if i == 0 or strict:
                    raise
                return
            yield audio_bytes
    except BaseException:
        # Auch bei Abbruch durch den Client die Hintergrundaufgaben beenden.
        await _cleanup(tasks)
        raise
