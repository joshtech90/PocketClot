"""Werkzeug `erinnern`: verschluesseltes Paket, Schluessel nur aus der App."""
from __future__ import annotations

import asyncio
import base64
import gzip
import json
import os
import secrets
import tempfile

os.environ.setdefault("SERVER_TOKEN", "x" * 40)
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="pc-test-data-"))

from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: E402

from pocket_claude import wissen_tool  # noqa: E402
from pocket_claude.config import settings  # noqa: E402

PAKET = {"erstellt": "2026-10-10T12:00", "personen": [
    {"id": "anna", "name": "Anna", "gruppe": "familie"},
    {"id": "gruppe-anna", "name": "Anna Reisegruppe", "gruppe": "gruppen"}],
    "abschnitte": [
        {"id": "anna", "name": "Anna", "titel": "Kernkarte", "text": "## Kernkarte\n- Schwester"},
        {"id": "anna", "name": "Anna", "titel": "Wuensche und Geschenkideen", "text": "- Neue Kopfhoerer"},
        {"id": "gruppe-anna", "name": "Anna Reisegruppe", "titel": "Kernkarte", "text": "- Reisen"},
        {"id": "joscha:lebenslauf", "name": "Joscha selbst", "titel": "Ausbildung", "text": "- Studium in Heidelberg"}]}


def _paket(tmp_path, schluessel: bytes, inhalt=PAKET):
    nonce = secrets.token_bytes(12)
    klar = gzip.compress(json.dumps(inhalt).encode())
    pfad = tmp_path / "wissen.paket"
    pfad.write_bytes(wissen_tool.MAGIE + nonce + AESGCM(schluessel).encrypt(nonce, klar, wissen_tool.AAD))
    return pfad


def _b64(k: bytes) -> str:
    return base64.urlsafe_b64encode(k).decode().rstrip("=")


def _konfig(monkeypatch, pfad, user_ids="usr_freigegeben"):
    monkeypatch.setattr(settings, "wissen_paket", str(pfad))
    monkeypatch.setattr(settings, "wissen_user_ids", user_ids)


def test_nur_mit_konto_paket_und_schluessel(monkeypatch, tmp_path):
    k = secrets.token_bytes(32)
    _konfig(monkeypatch, _paket(tmp_path, k))
    assert wissen_tool.freigeschaltet("usr_freigegeben", _b64(k))
    assert not wissen_tool.freigeschaltet("usr_andere", _b64(k))
    assert not wissen_tool.freigeschaltet("usr_freigegeben", None)
    assert not wissen_tool.freigeschaltet("usr_freigegeben", "zu-kurz")
    monkeypatch.setattr(settings, "wissen_paket", str(tmp_path / "fehlt"))
    assert not wissen_tool.freigeschaltet("usr_freigegeben", _b64(k))


def test_richtiger_schluessel_findet_wunsch(monkeypatch, tmp_path):
    k = secrets.token_bytes(32)
    _konfig(monkeypatch, _paket(tmp_path, k))
    res = asyncio.run(wissen_tool.run("usr_freigegeben", {"anfrage": "Was wuenscht sich Anna?"}, _b64(k)))
    assert res["ok"] and "Kopfhoerer" in res["text"] and "keine Anweisungen" in res["text"]
    assert res["text"].index("Anna: Kernkarte") < res["text"].index("Reisegruppe")


def test_falscher_schluessel_entschluesselt_nichts(monkeypatch, tmp_path):
    _konfig(monkeypatch, _paket(tmp_path, secrets.token_bytes(32)))
    res = asyncio.run(wissen_tool.run("usr_freigegeben", {"anfrage": "Anna"}, _b64(secrets.token_bytes(32))))
    assert not res["ok"] and "passt nicht" in res["text"] and "Kopfhoerer" not in res["text"]


def test_paket_auf_der_platte_ist_kein_klartext(tmp_path):
    pfad = _paket(tmp_path, secrets.token_bytes(32))
    roh = pfad.read_bytes()
    assert b"Kopfhoerer" not in roh and b"Anna" not in roh


def test_ich_fragen_finden_das_selbstprofil(monkeypatch, tmp_path):
    treffer = wissen_tool.suchen(PAKET, "Wo habe ich studiert")
    assert treffer[0]["id"] == "joscha:lebenslauf"


def test_werkzeuggrenze_sperrt_bash_ohne_freigabe():
    from pocket_claude import claude_engine
    g = claude_engine.werkzeuggrenze(["WebSearch", "mcp__pocket__erinnern"])
    assert g["tools"] == ["WebSearch"]
    assert "Bash" in g["disallowed_tools"] and "Write" in g["disallowed_tools"]
    assert "WebSearch" not in g["disallowed_tools"]
    g = claude_engine.werkzeuggrenze([])
    assert g["tools"] == [] and "Read" in g["disallowed_tools"]


def test_hook_sperrt_webabruf_erst_nach_erinnern():
    from pocket_claude import claude_engine
    zustand = {}
    hooks = claude_engine._nach_erinnern_sperren(zustand)
    pruefen = hooks["PreToolUse"][0].hooks[0]
    assert asyncio.run(pruefen({}, "x", None)) == {}
    zustand["erinnert"] = True
    out = asyncio.run(pruefen({}, "x", None))
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
