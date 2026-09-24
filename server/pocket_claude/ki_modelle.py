"""Welche Claude-Generation aktuell ist, aus dem Modell-Register.

`ki_modelle.json` daneben ist eine Kopie von `AI Worker/config/ki-modelle.json`
(dort die einzige Quelle; `ki-modelle anwenden` frischt diese Kopie auf).
Hier wird nichts von Hand gepflegt: neue Generation = Register anheben,
Kopie ausrollen.

Grundsatz wie in Smartzone OS: an die Claude-CLI geht nur der Kurzname
(`opus`, `opus[1m]` ...), den die CLI selbst auf die neueste Generation
aufloest. Gespeicherte Alt-IDs wie `claude-opus-5` werden dabei angehoben,
statt einen Chat auf einer alten Generation festzuhalten.
"""
from __future__ import annotations

import json
import logging
import os
import re
from functools import lru_cache
from pathlib import Path

log = logging.getLogger(__name__)

_DATEI = Path(__file__).resolve().parent / "ki_modelle.json"
_CLAUDE_MUSTER = re.compile(r"claude-(opus|sonnet|fable|haiku)-\d+(?:[-.]\d+)*")

# Nur fuer den Fall, dass die Kopie fehlt oder kaputt ist.
_RUECKFALL = {
    "opus": {"anbieter": "claude", "name": "Opus", "cli_alias": "opus"},
    "fable": {"anbieter": "claude", "name": "Fable", "cli_alias": "fable"},
    "sonnet": {"anbieter": "claude", "name": "Sonnet", "cli_alias": "sonnet"},
    "haiku": {"anbieter": "claude", "name": "Haiku", "cli_alias": "haiku"},
}

# Reihenfolge im Picker: Opus ist das Alltagsmodell, Fable das staerkere fuer
# die schwersten Aufgaben, Sonnet das schnellere, Haiku das kleinste.
PICKER_REIHENFOLGE = ("opus", "fable", "sonnet", "haiku")


@lru_cache(maxsize=1)
def _alle() -> dict[str, dict]:
    pfad = Path(os.environ.get("KI_MODELLE_DATEI") or _DATEI)
    try:
        roh = json.loads(pfad.read_text(encoding="utf-8"))["familien"]
        # Nur wohlgeformte Eintraege: ein kaputtes Register darf den Server
        # nicht beim Import umwerfen.
        return {str(k): v for k, v in roh.items() if isinstance(v, dict)}
    except Exception as exc:  # noqa: BLE001 - Rueckfall statt Serverabsturz
        log.warning("PC_MODELLE: Register %s nicht lesbar (%s), nutze Rueckfall", pfad, exc)
        return {}


def familien() -> dict[str, dict]:
    """Nur die Claude-Familien."""
    claude = {k: v for k, v in _alle().items() if v.get("anbieter") == "claude"}
    return claude or dict(_RUECKFALL)


def pool_anzeigename(base_id: str) -> str:
    """Anzeigename fuer einen Pool-Kurznamen, z. B. gemini-flash -> Gemini 3.8 Flash.

    Der Pool meldet unter /v1/models keinen Anzeigenamen; ohne das stuende im
    Picker nur "Gemini Flash" und man saehe nicht, welche Generation laeuft.
    """
    b = str(base_id or "").lower()
    for f in _alle().values():
        alias = str(f.get("pool_alias") or "").lower()
        if alias and b in {alias, re.sub(r"-(high|medium|low|minimal|xhigh)$", "", alias)}:
            return str(f.get("name") or "")
    return ""


def picker() -> list[tuple[str, str]]:
    """(Schluessel, Anzeigename) fuer den Modell-Picker, Schluessel = Familie."""
    fam = familien()
    return [(name, str(fam[name].get("name") or name.title()))
            for name in PICKER_REIHENFOLGE if name in fam]


def bekannte_ids() -> set[str]:
    """Alles, was als Claude-Modell akzeptiert wird (ohne Suffix wie [1m])."""
    out: set[str] = set()
    for name, f in familien().items():
        out |= {name, str(f.get("cli_alias") or name)}
        if f.get("id"):
            out.add(str(f["id"]))
        out |= {str(x) for x in (f.get("abgeloest") or [])}
    return out


def ist_claude_modell(modell: str | None) -> bool:
    """Akzeptiert der Server diese Angabe als Claude-Modell?

    Bewusst ueber die Familie statt ueber eine feste Liste: so laufen
    Bestandschats mit alten IDs (claude-opus-4-8 ...) auch dann weiter, wenn
    das Register fehlt und nur der Rueckfall gilt.
    """
    return familie_von(modell) is not None


def familie_von(modell: str | None) -> str | None:
    basis = str(modell or "").strip().lower().split("[")[0]
    if not basis:
        return None
    for name, f in familien().items():
        if basis in {name, f.get("cli_alias"), f.get("id"), *(f.get("abgeloest") or [])}:
            return name
    m = _CLAUDE_MUSTER.fullmatch(re.sub(r"-\d{8}$", "", basis))
    return m.group(1) if m and m.group(1) in familien() else None


def fuer_cli(modell: str | None) -> str | None:
    """Beliebige Claude-Angabe -> Kurzname fuer die CLI, Suffix bleibt.

    `claude-opus-5[1m]` -> `opus[1m]`, `opus` -> `opus`. Unbekanntes kommt
    unveraendert zurueck (z. B. Bedrock-IDs, die ihren eigenen Namensraum haben).
    """
    if not modell:
        return modell
    roh = str(modell).strip()
    fam = familie_von(roh)
    if not fam:
        return roh
    suffix = roh[roh.index("["):] if "[" in roh else ""
    return str(familien()[fam].get("cli_alias") or fam) + suffix


def anzeigename(modell: str | None) -> str:
    fam = familie_von(modell)
    return str(familien()[fam].get("name")) if fam else str(modell or "")
