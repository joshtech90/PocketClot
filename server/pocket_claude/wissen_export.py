"""Verschluesselter Chat-Export fuer die Wissensauswertung.

Fuer Konten, die in der Kontenliste (WISSEN_KONTEN) `"export": true` tragen, legt der
Server ihre Chats regelmaessig als verschluesselte Datei in WISSEN_EXPORT_DIR ab.
Ein anderer Rechner holt sie dort ab und baut daraus das Gedaechtnis dieses Kontos;
der Server fragt selbst nirgends an. Verschluesselt wird an einen oeffentlichen
X25519-Schluessel (`export_empfaenger`): ECDH mit einem Einmal-Schluessel, HKDF-SHA256,
AES-256-GCM. Das private Gegenstueck liegt nur beim Empfaenger, hier kann niemand
die Datei wieder lesen.

Gesperrte Chats (PIN in der App) bleiben bewusst draussen: wer einen Chat sperrt,
will ihn nicht ausgewertet haben. Sperren oder Loeschen verwirft den bisherigen
Export sofort (`verwerfen`); ein Konto ohne Freigabe verliert seinen Export beim
naechsten Durchgang. Anhaenge gehen nicht mit, nur ihre Anzahl.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import gzip
import json
import logging
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path

from pocket_claude import db, wissen_tool
from pocket_claude.config import settings

log = logging.getLogger(__name__)

MAGIE = b"PCX1"
INFO = b"pocketclot-export-v1"
INTERVALL = 3600
_DATEI = __import__("re").compile(r"usr_[A-Za-z0-9_-]+")
_STAND: dict[str, tuple] = {}
# Zaehler je Konto: jedes Verwerfen erhoeht ihn. Ein Export, der waehrenddessen schon
# lief, sieht den neuen Wert und wird nicht mehr veroeffentlicht.
_GENERATION: dict[str, int] = {}


def _empfaenger(user_id: str) -> bytes | None:
    s = wissen_tool.export_empfaenger(user_id).strip()
    if not s:
        return None
    try:
        k = base64.b64decode(s + "=" * (-len(s) % 4), altchars=b"-_", validate=True)
    except (binascii.Error, ValueError):
        return None
    if len(k) != 32:
        return None
    # Auch formal 32 Byte lange Low-Order-Schluessel duerfen kein Konto blockieren.
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
    try:
        X25519PrivateKey.generate().exchange(X25519PublicKey.from_public_bytes(k))
    except ValueError:
        return None
    return k


def versiegeln(klar: bytes, empfaenger: bytes) -> bytes:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    einmal = X25519PrivateKey.generate()
    einmal_pub = einmal.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    geteilt = einmal.exchange(X25519PublicKey.from_public_bytes(empfaenger))
    k = HKDF(algorithm=hashes.SHA256(), length=32, salt=einmal_pub + empfaenger, info=INFO).derive(geteilt)
    nonce = secrets.token_bytes(12)
    return MAGIE + einmal_pub + nonce + AESGCM(k).encrypt(nonce, klar, MAGIE + einmal_pub)


def _ordner() -> Path | None:
    o = (settings.wissen_export_dir or "").strip()
    if o:
        return Path(o)
    k = (settings.wissen_konten or "").strip()
    return Path(k).parent / "aus" if k else None


async def _inhalt(user_id: str) -> tuple[dict, tuple]:
    konvs = [c for c in await db.list_conversations(user_id) if not c.get("locked")]
    out, stand = [], []
    for c in konvs:
        # Waehrend des Lesens gesperrt oder geloescht? Dann gehoert der Chat nicht hinein.
        aktuell = await db.get_conversation(c["id"], user_id=user_id)
        if not aktuell or aktuell.get("locked"):
            continue
        msgs = await db.list_messages(c["id"])
        stand.append((c["id"], len(msgs), msgs[-1]["id"] if msgs else 0))
        out.append({"id": c["id"], "titel": c.get("title") or "", "erstellt": c.get("created_at") or "",
                    "modell": c.get("chat_model") or "",
                    "nachrichten": [{"id": m["id"], "rolle": m["role"], "zeit": m["created_at"],
                                     "text": m["content"], "anhaenge": len(m.get("attachment_ids") or [])}
                                    for m in msgs if m["role"] in ("user", "assistant")]})
    return ({"user_id": user_id, "erstellt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "konversationen": out}, tuple(sorted(stand)))


def verwerfen(user_id: str) -> None:
    """Export eines Kontos sofort entfernen (nach Sperren oder Loeschen eines Chats)."""
    _GENERATION[user_id] = _GENERATION.get(user_id, 0) + 1
    _STAND.pop(user_id, None)
    ordner = _ordner()
    if ordner is not None and _DATEI.fullmatch(user_id or ""):
        try:
            (ordner / f"{user_id}.export").unlink(missing_ok=True)
        except OSError as exc:
            log.warning("PC_WISSEN: Export nicht entfernbar: %s", type(exc).__name__)


def _aufraeumen(ordner: Path | None, ziele: set[str]) -> None:
    """Exporte von Konten ohne Freigabe entfernen, auch wenn die Kontenliste fehlt."""
    if ordner is None or not ordner.is_dir():
        return
    for p in ordner.glob("*.export"):
        if p.stem not in ziele:
            try:
                p.unlink()
                _STAND.pop(p.stem, None)
            except OSError:
                pass


async def einmal() -> int:
    """Schreibt geaenderte Exporte; liefert die Zahl geschriebener Dateien."""
    ziele = [u for u, e in wissen_tool.konten().items() if e.get("export") and _DATEI.fullmatch(u)]
    ordner = _ordner()
    _aufraeumen(ordner, set(ziele))
    if not ziele:
        return 0
    if ordner is None or not ordner.is_dir() or not os.access(ordner, os.W_OK):
        log.warning("PC_WISSEN: Export eingerichtet, aber Empfaenger oder Ordner fehlt")
        return 0
    geschrieben = 0
    for uid in ziele:
        empfaenger = _empfaenger(uid)
        if empfaenger is None:
            # Kein Fallback bei explizit kaputtem Kontoschluessel; alten Export entziehen.
            verwerfen(uid)
            log.warning("PC_WISSEN: Exportempfaenger eines Kontos ungueltig")
            continue
        generation = _GENERATION.get(uid, 0)
        daten, stand = await _inhalt(uid)
        stand = (empfaenger, stand)   # neuer Empfaenger-Schluessel: neu versiegeln
        ziel = ordner / f"{uid}.export"
        if _STAND.get(uid) == stand and ziel.exists():
            continue
        roh = await asyncio.get_running_loop().run_in_executor(
            None, lambda: versiegeln(gzip.compress(json.dumps(daten, ensure_ascii=False).encode()), empfaenger))
        if _GENERATION.get(uid, 0) != generation:
            continue   # waehrenddessen gesperrt oder geloescht: naechster Durchgang
        tmp = ordner / f".{uid}.{secrets.token_hex(4)}.tmp"
        tmp.write_bytes(roh)
        os.chmod(tmp, 0o644)   # Datensalat; lesbar fuer den Abholer, schreibbar nur fuer diesen Dienst
        if _GENERATION.get(uid, 0) != generation:
            tmp.unlink(missing_ok=True)
            continue
        tmp.replace(ziel)
        _STAND[uid] = stand
        geschrieben += 1
        log.info("PC_WISSEN: Export fuer ein Konto geschrieben (%d Chats)", len(daten["konversationen"]))
    return geschrieben


async def schleife() -> None:
    await asyncio.sleep(90)
    while True:
        try:
            await einmal()
        except Exception as exc:  # nie den Server kippen
            log.warning("PC_WISSEN: Export gescheitert: %s", type(exc).__name__)
        await asyncio.sleep(INTERVALL)
