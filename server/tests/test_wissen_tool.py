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


def test_zu_grosses_entpacktes_paket_wird_abgelehnt(monkeypatch, tmp_path):
    k = secrets.token_bytes(32)
    monkeypatch.setattr(wissen_tool, "MAX_KLARTEXT", 1000)
    pfad = _paket(tmp_path, k, {"personen": [], "abschnitte": [{"text": "x" * 5000}]})
    _konfig(monkeypatch, pfad)
    res = asyncio.run(wissen_tool.run("usr_freigegeben", {"anfrage": "x"}, _b64(k)))
    assert not res["ok"]


def test_hook_sperrt_auch_bilder():
    from pocket_claude import claude_engine
    hooks = claude_engine._nach_erinnern_sperren({})
    assert "mcp__pocket__generate_image" in hooks["PreToolUse"][0].matcher


# ── Mehrere Konten, jedes mit eigenem Paket ─────────────────────────────────

def _konten(monkeypatch, tmp_path, eintraege, empfaenger=""):
    datei = tmp_path / "konten.json"
    datei.write_text(json.dumps({"konten": eintraege, "export_empfaenger": empfaenger}))
    monkeypatch.setattr(settings, "wissen_konten", str(datei))
    monkeypatch.setattr(wissen_tool, "_KONTEN_CACHE", {"stempel": None, "daten": {}})
    return datei


def test_jedes_konto_liest_nur_sein_eigenes_paket(monkeypatch, tmp_path):
    ka, kb = secrets.token_bytes(32), secrets.token_bytes(32)
    (tmp_path / "a.paket").write_bytes(_paket(tmp_path, ka).read_bytes())
    anders = dict(PAKET, abschnitte=[{"id": "selbst:profil", "name": "Du selbst", "titel": "Arbeit",
                                      "text": "- Fitnesstrainerin"}])
    (tmp_path / "b.paket").write_bytes(_paket(tmp_path, kb, anders).read_bytes())
    _konten(monkeypatch, tmp_path, {"usr_a": {"paket": "a.paket"}, "usr_b": {"paket": "b.paket"},
                                    "usr_c": {"paket": "../wissen.paket"}})
    res = asyncio.run(wissen_tool.run("usr_b", {"anfrage": "Was arbeite ich?"}, _b64(kb)))
    assert res["ok"] and "Fitnesstrainerin" in res["text"] and "Kopfhoerer" not in res["text"]
    # Fremder Schluessel oeffnet das eigene Paket nicht, und ein Pfad nach draussen gilt nicht
    assert not asyncio.run(wissen_tool.run("usr_b", {"anfrage": "Anna"}, _b64(ka)))["ok"]
    assert not wissen_tool.freigeschaltet("usr_c", _b64(ka))
    assert wissen_tool.freigeschaltet("usr_a", _b64(ka))


def test_ich_frage_findet_auch_selbst_abschnitte():
    paket = {"personen": [], "abschnitte": [
        {"id": "joscha", "name": "Joscha", "titel": "Arbeit", "text": "- arbeitet bei smartzone"},
        {"id": "selbst:profil", "name": "Du selbst", "titel": "Arbeit", "text": "- arbeitet als Trainerin"}]}
    assert wissen_tool.suchen(paket, "Wo arbeite ich")[0]["id"] == "selbst:profil"


def test_export_ist_nur_fuer_den_empfaenger_lesbar_und_ohne_gesperrte_chats(monkeypatch, tmp_path):
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    from pocket_claude import db, wissen_export
    privat = X25519PrivateKey.generate()
    pub = privat.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    (tmp_path / "aus").mkdir()
    _konten(monkeypatch, tmp_path, {"usr_e": {"paket": "e.paket", "export": True},
                                    "usr_x": {"paket": "x.paket"}}, _b64(pub))
    monkeypatch.setattr(settings, "wissen_export_dir", "")

    async def ablauf():
        await db.init_db()
        offen = await db.create_conversation("Victors Fuss", user_id="usr_e")
        await db.add_message(offen, "user", "Victor hat am Montag Physiotherapie")
        zu = await db.create_conversation("Geheim", user_id="usr_e")
        await db.add_message(zu, "user", "streng privat")
        await db.set_locked(zu, True)
        fremd = await db.create_conversation("Fremd", user_id="usr_x")
        await db.add_message(fremd, "user", "anderes Konto")
        n1 = await wissen_export.einmal()
        n2 = await wissen_export.einmal()   # unveraendert: nichts neu schreiben
        return n1, n2
    n1, n2 = asyncio.run(ablauf())
    assert (n1, n2) == (1, 0)
    assert not (tmp_path / "aus" / "usr_x.export").exists()
    roh = (tmp_path / "aus" / "usr_e.export").read_bytes()
    assert roh.startswith(wissen_export.MAGIE) and b"Physiotherapie" not in roh
    einmal_pub, nonce, ct = roh[4:36], roh[36:48], roh[48:]
    k = HKDF(algorithm=hashes.SHA256(), length=32, salt=einmal_pub + pub,
             info=wissen_export.INFO).derive(privat.exchange(X25519PublicKey.from_public_bytes(einmal_pub)))
    daten = json.loads(gzip.decompress(AESGCM(k).decrypt(nonce, ct, wissen_export.MAGIE + einmal_pub)))
    texte = [m["text"] for c in daten["konversationen"] for m in c["nachrichten"]]
    assert texte == ["Victor hat am Montag Physiotherapie"]
