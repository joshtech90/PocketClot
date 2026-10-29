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
    e, x = "usr_e" + secrets.token_hex(4), "usr_x" + secrets.token_hex(4)   # DB wird geteilt
    privat = X25519PrivateKey.generate()
    pub = privat.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    (tmp_path / "aus").mkdir()
    _konten(monkeypatch, tmp_path, {e: {"paket": "e.paket", "export": True},
                                    x: {"paket": "x.paket"}}, _b64(pub))
    monkeypatch.setattr(settings, "wissen_export_dir", "")

    async def ablauf():
        await db.init_db()
        offen = await db.create_conversation("Victors Fuss", user_id=e)
        await db.add_message(offen, "user", "Victor hat am Montag Physiotherapie")
        zu = await db.create_conversation("Geheim", user_id=e)
        await db.add_message(zu, "user", "streng privat")
        await db.set_locked(zu, True)
        fremd = await db.create_conversation("Fremd", user_id=x)
        await db.add_message(fremd, "user", "anderes Konto")
        n1 = await wissen_export.einmal()
        n2 = await wissen_export.einmal()   # unveraendert: nichts neu schreiben
        return n1, n2
    n1, n2 = asyncio.run(ablauf())
    assert (n1, n2) == (1, 0)
    assert not (tmp_path / "aus" / f"{x}.export").exists()
    roh = (tmp_path / "aus" / f"{e}.export").read_bytes()
    assert roh.startswith(wissen_export.MAGIE) and b"Physiotherapie" not in roh
    einmal_pub, nonce, ct = roh[4:36], roh[36:48], roh[48:]
    k = HKDF(algorithm=hashes.SHA256(), length=32, salt=einmal_pub + pub,
             info=wissen_export.INFO).derive(privat.exchange(X25519PublicKey.from_public_bytes(einmal_pub)))
    daten = json.loads(gzip.decompress(AESGCM(k).decrypt(nonce, ct, wissen_export.MAGIE + einmal_pub)))
    texte = [m["text"] for c in daten["konversationen"] for m in c["nachrichten"]]
    assert texte == ["Victor hat am Montag Physiotherapie"]


def test_export_verschwindet_bei_sperre_und_ohne_freigabe(monkeypatch, tmp_path):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

    from pocket_claude import db, wissen_export
    pub = X25519PrivateKey.generate().public_key().public_bytes(serialization.Encoding.Raw,
                                                                  serialization.PublicFormat.Raw)
    v = "usr_v" + secrets.token_hex(4)
    aus = tmp_path / "aus"
    aus.mkdir()
    monkeypatch.setattr(settings, "wissen_export_dir", "")
    _konten(monkeypatch, tmp_path, {v: {"paket": "v.paket", "export": True}}, _b64(pub))
    (aus / "usr_alt.export").write_bytes(b"PCX1alt")

    async def ablauf():
        await db.init_db()
        c = await db.create_conversation("Ein Chat", user_id=v)
        await db.add_message(c, "user", "Hallo")
        await wissen_export.einmal()
        assert (aus / f"{v}.export").exists() and not (aus / "usr_alt.export").exists()
        wissen_export.verwerfen(v)
        assert not (aus / f"{v}.export").exists()
        await wissen_export.einmal()
        assert (aus / f"{v}.export").exists()
        _konten(monkeypatch, tmp_path, {v: {"paket": "v.paket"}}, _b64(pub))
        await wissen_export.einmal()
        assert not (aus / f"{v}.export").exists()
    asyncio.run(ablauf())


def test_konto_verschwindet_waehrend_der_abfrage(monkeypatch, tmp_path):
    k = secrets.token_bytes(32)
    (tmp_path / "a.paket").write_bytes(_paket(tmp_path, k).read_bytes())
    datei = _konten(monkeypatch, tmp_path, {"usr_a": {"paket": "a.paket"}})
    echt = wissen_tool._paket_pfad
    aufrufe = []

    def pfad(uid):
        aufrufe.append(uid)
        return echt(uid) if len(aufrufe) == 1 else None
    monkeypatch.setattr(wissen_tool, "_paket_pfad", pfad)
    res = asyncio.run(wissen_tool.run("usr_a", {"anfrage": "Anna"}, _b64(k)))
    assert not res["ok"] and datei.exists()


def test_laufender_export_nach_sperre_wird_nicht_veroeffentlicht(monkeypatch, tmp_path):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

    from pocket_claude import db, wissen_export
    pub = X25519PrivateKey.generate().public_key().public_bytes(serialization.Encoding.Raw,
                                                                  serialization.PublicFormat.Raw)
    g = "usr_g" + secrets.token_hex(4)
    (tmp_path / "aus").mkdir()
    monkeypatch.setattr(settings, "wissen_export_dir", "")
    _konten(monkeypatch, tmp_path, {g: {"paket": "g.paket", "export": True}}, _b64(pub))
    echt = wissen_export._inhalt

    async def inhalt_mit_sperre(uid):
        ergebnis = await echt(uid)
        wissen_export.verwerfen(uid)          # Sperre kommt waehrend des Lesens
        return ergebnis
    monkeypatch.setattr(wissen_export, "_inhalt", inhalt_mit_sperre)

    async def ablauf():
        await db.init_db()
        c = await db.create_conversation("Chat", user_id=g)
        await db.add_message(c, "user", "Hallo")
        return await wissen_export.einmal()
    assert asyncio.run(ablauf()) == 0
    assert not (tmp_path / "aus" / f"{g}.export").exists()


def test_markdown_personensuche_ohne_index_bevorzugt_den_genauen_namen():
    paket = {'personen': [], 'abschnitte': [
        {'id': f'selbst:{i}', 'name': 'Notizen', 'text': f'{name} mag Wandern.'}
        for i, name in enumerate(['Anna', 'Bernd', 'Clara', 'Dora', 'Emil', 'Frank', 'Greta', 'Hannah'])]}
    assert wissen_tool.suchen(paket, 'Vorlieben', person='Hannah')[0]['text'] == 'Hannah mag Wandern.'
    assert wissen_tool.suchen(PAKET, 'Geschenke', person='Anna')[0]['id'] == 'anna'


def test_exportempfaenger_sind_getrennt_und_defekte_konten_verlieren_den_export(monkeypatch, tmp_path):
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    from pocket_claude import wissen_export
    import pytest

    alt, clivia = X25519PrivateKey.generate(), X25519PrivateKey.generate()
    def pub(k):
        return k.public_key().public_bytes_raw()
    konten = {'usr_joscha': {'paket': 'wissen.paket', 'export': True},
              'usr_kati': {'paket': 'kati.paket', 'export': True},
              'usr_clivia': {'paket': 'clivia.paket', 'export': True, 'export_empfaenger': _b64(pub(clivia))}}
    for n, kaputt in enumerate(('', 'kein-schluessel!', _b64(bytes(32)), None)):
        konten[f'usr_defekt{n}'] = {'paket': f'defekt{n}.paket', 'export': True, 'export_empfaenger': kaputt}
    (tmp_path / 'aus').mkdir()
    for uid in konten:
        (tmp_path / 'aus' / f'{uid}.export').write_bytes(b'PCX1veraltet')
    _konten(monkeypatch, tmp_path, konten, _b64(pub(alt)))
    monkeypatch.setattr(settings, 'wissen_export_dir', '')
    monkeypatch.setattr(wissen_export, '_STAND', {})
    monkeypatch.setattr(wissen_export, '_GENERATION', {})
    async def inhalt(uid):
        return {'user_id': uid, 'konversationen': []}, ()
    monkeypatch.setattr(wissen_export, '_inhalt', inhalt)
    assert asyncio.run(wissen_export.einmal()) == 3
    def oeffnen(uid, privat):
        roh = (tmp_path / 'aus' / f'{uid}.export').read_bytes()
        ep, nonce = roh[4:36], roh[36:48]
        k = HKDF(algorithm=hashes.SHA256(), length=32, salt=ep + pub(privat), info=wissen_export.INFO).derive(
            privat.exchange(X25519PublicKey.from_public_bytes(ep)))
        return json.loads(gzip.decompress(AESGCM(k).decrypt(nonce, roh[48:], b'PCX1' + ep)))
    for uid in ('usr_joscha', 'usr_kati'):
        assert oeffnen(uid, alt)['user_id'] == uid
        with pytest.raises(InvalidTag):
            oeffnen(uid, clivia)
    assert oeffnen('usr_clivia', clivia)['user_id'] == 'usr_clivia'
    with pytest.raises(InvalidTag):
        oeffnen('usr_clivia', alt)
    for uid in konten:
        if uid.startswith('usr_defekt'):
            assert not (tmp_path / 'aus' / f'{uid}.export').exists()
