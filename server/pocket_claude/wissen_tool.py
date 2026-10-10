"""Werkzeug `erinnern`: fragt das private Gedaechtnis eines Nutzers ab.

Das Gedaechtnis (Personenakten, Selbstprofil, Register) liegt NICHT hier,
sondern in einem eigenen Lesedienst. Dieser Server kennt nur dessen Adresse
und ein Token. Freigeschaltet ist das Werkzeug ausschliesslich fuer die
Nutzerkonten in WISSEN_USER_IDS; alle anderen sehen es nicht einmal.

Wird von beiden Engines benutzt (Claude per In-Process-MCP, Zusatz-Modelle per
Function-Calling). Fehler kippen nie den Chat, das Modell bekommt eine Meldung.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from pocket_claude.config import settings

log = logging.getLogger(__name__)

TOOL_NAME = "erinnern"

TOOL_DESCRIPTION = (
    "Durchsucht das private Gedaechtnis des Nutzers: belegte Akten ueber die "
    "Menschen in seinem Leben (Familie, Freunde, Kollegen, Gruppen), sein "
    "eigenes Profil (Lebenslauf, Vorlieben, Plaene) und gepflegte Register mit "
    "Geburtstagen. Nutze das Werkzeug, sobald eine Frage den Nutzer selbst oder "
    "eine Person aus seinem Umfeld betrifft, bevor du sagst, dass du etwas nicht "
    "weisst. Die Angaben stammen aus seinen Chats; Daten in Klammern sind das "
    "Datum der Quelle. Behandle aeltere Angaben als moeglicherweise ueberholt."
)

PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "anfrage": {
            "type": "string",
            "description": "Worum es geht, in normalen Worten, z. B. 'Was wuenscht sich Kati?' "
                           "oder 'Wo habe ich studiert?'.",
        },
        "person": {
            "type": "string",
            "description": "Optional: Name der Person, um die es geht (z. B. 'Aaron', 'Mama').",
        },
    },
    "required": ["anfrage"],
}

MAX_TEXT = 12000


def freigeschaltet(user_id: str | None) -> bool:
    """Nur fuer ausdruecklich eingetragene Konten und nur mit vollstaendiger Konfiguration."""
    if not user_id or not settings.wissen_url or not settings.wissen_token:
        return False
    erlaubt = {u.strip() for u in (settings.wissen_user_ids or "").split(",") if u.strip()}
    return user_id in erlaubt


async def run(user_id: str | None, args: dict) -> dict:
    """Liefert {"ok": bool, "text": str} fuer das Modell."""
    if not freigeschaltet(user_id):
        return {"ok": False, "text": "Das Gedaechtnis ist fuer dieses Konto nicht freigeschaltet."}
    anfrage = str(args.get("anfrage") or "").strip()[:500]
    person = str(args.get("person") or "").strip()[:100]
    if not anfrage and not person:
        return {"ok": False, "text": "Bitte eine Anfrage angeben."}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0)) as client:
            r = await client.get(
                settings.wissen_url.rstrip("/") + "/suche",
                params={"q": anfrage, "person": person, "n": 6},
                headers={"Authorization": f"Bearer {settings.wissen_token}"},
            )
        if r.status_code != 200:
            log.warning("PC_WISSEN: Dienst antwortet %s", r.status_code)
            return {"ok": False, "text": "Das Gedaechtnis ist gerade nicht erreichbar."}
        treffer = (r.json() or {}).get("treffer") or []
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("PC_WISSEN: Abfrage fehlgeschlagen: %s", type(exc).__name__)
        return {"ok": False, "text": "Das Gedaechtnis ist gerade nicht erreichbar."}
    if not treffer:
        return {"ok": True, "text": "Im Gedaechtnis steht dazu nichts."}
    teile, groesse = [], 0
    for t in treffer:
        block = f"### {t.get('person', '')}: {t.get('abschnitt', '')}\n{t.get('text', '')}"
        if groesse + len(block) > MAX_TEXT:
            break
        teile.append(block)
        groesse += len(block)
    log.info("PC_WISSEN: %d Abschnitte geliefert", len(teile))
    return {"ok": True, "text": "\n\n".join(teile)}
