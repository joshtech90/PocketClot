"""Grok als Vorlese-Anbieter: Stimmen, Tempo, Fehlerfaelle, Ausweichen."""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("SERVER_TOKEN", "x" * 40)
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="pc-test-data-"))

from pocket_claude import tts  # noqa: E402

MP3 = b"ID3\x04\x00" + b"\x00" * 64


class Antwort:
    def __init__(self, status, content=b"", payload=None):
        self.status_code = status
        self.content = content
        self.text = content.decode("latin-1")
        self._payload = payload

    def json(self):
        return self._payload


class GrokTest(unittest.TestCase):
    def test_leo_ist_vorgabe_und_steht_vorne(self):
        self.assertEqual(tts.default_voice_for(tts.PROVIDER_GROK), "grok-leo")
        self.assertEqual(tts.CURATED_VOICES[0]["id"], "grok-leo")
        grok = [v for v in tts.CURATED_VOICES if v["tier"] == "grok"]
        self.assertEqual(len(grok), 28)
        self.assertTrue(all(v["compatible_providers"] == ["grok"] for v in grok))

    def test_keine_google_cloud_stimmen_mehr(self):
        ids = [v["id"] for v in tts.CURATED_VOICES]
        self.assertFalse([i for i in ids if i.startswith(("gemini-", "chirp3hd-", "de-DE-"))])

    def test_aufruf_mit_stimme_und_begrenztem_tempo(self):
        with mock.patch.object(tts.httpx, "post", return_value=Antwort(200, MP3)) as post:
            audio = tts.synthesize("Hallo Welt", "grok-ara", 0.25, tts.PROVIDER_GROK)
        self.assertEqual(audio, MP3)
        body = post.call_args.kwargs["json"]
        self.assertEqual(body["voice"], "ara")
        self.assertEqual(body["speed"], 0.5)   # Grok kann nicht langsamer
        self.assertEqual(body["format"], "mp3")

    def test_fremde_stimme_wird_leo(self):
        with mock.patch.object(tts.httpx, "post", return_value=Antwort(200, MP3)) as post:
            tts.synthesize("Hallo", "edge-de-DE-KatjaNeural", 1.0, tts.PROVIDER_GROK)
        self.assertEqual(post.call_args.kwargs["json"]["voice"], "leo")

    def test_fehlende_sitzung_ist_dauerfehler(self):
        with mock.patch.object(tts.httpx, "post", return_value=Antwort(503, b'{"error":"session_expired"}')):
            with self.assertRaises(tts.TtsSessionExpiredError):
                tts.synthesize("Hallo", "grok-leo", 1.0, tts.PROVIDER_GROK)

    def test_kein_mp3_ist_fehler(self):
        with mock.patch.object(tts.httpx, "post", return_value=Antwort(200, b'{"ok":false}')):
            with self.assertRaises(tts.TtsTransientError):
                tts.synthesize("Hallo", "grok-leo", 1.0, tts.PROVIDER_GROK)

    def test_verfuegbar_nur_mit_sitzung(self):
        with mock.patch.object(tts.httpx, "get", return_value=Antwort(200, payload={"ok": False})):
            self.assertFalse(tts.grok_available(force=True))
        with mock.patch.object(tts.httpx, "get", return_value=Antwort(200, payload={"ok": True})):
            self.assertTrue(tts.grok_available(force=True))


class AusweichenTest(unittest.IsolatedAsyncioTestCase):
    async def test_grok_ohne_sitzung_faellt_auf_gemini_web(self):
        from pocket_claude import server
        with mock.patch.object(tts, "grok_available", return_value=False), \
             mock.patch.object(tts, "gemini_web_available", return_value=True):
            self.assertEqual(await server._resolve_provider_with_kv({"tts_provider": "grok"}), "gemini_web")
            # Entfernte Anbieter aus alten Einstellungen
            self.assertEqual(await server._resolve_provider_with_kv({"tts_provider": "cloud_tts"}), "gemini_web")
        with mock.patch.object(tts, "grok_available", return_value=True), \
             mock.patch.object(tts, "gemini_web_available", return_value=True):
            self.assertEqual(await server._resolve_provider_with_kv({}), "grok")
            self.assertEqual(await server._resolve_provider_with_kv({"tts_provider": "edge_tts"}), "edge_tts")
        with mock.patch.object(tts, "grok_available", return_value=False), \
             mock.patch.object(tts, "gemini_web_available", return_value=False):
            self.assertEqual(await server._resolve_provider_with_kv({"tts_provider": "grok"}), "edge_tts")


class SicherheitsnetzTest(unittest.IsolatedAsyncioTestCase):
    async def test_strict_gibt_bei_spaeterem_fehler_keinen_halben_stream(self):
        aufrufe = {"n": 0}

        def fake(text, voice, rate, provider):
            aufrufe["n"] += 1
            if aufrufe["n"] == 1:
                return MP3
            raise tts.TtsSessionExpiredError("weg")

        lang = "Ein Satz, der lang genug ist. " * 40
        with mock.patch.object(tts, "synthesize", side_effect=fake), \
             mock.patch.object(tts, "MAX_CONCURRENT_TTS_REQUESTS", 1):
            # Ohne strict: was raus ist, bleibt, der Stream endet sauber.
            teile = [b async for b in tts.synthesize_chunked(lang, "grok-leo", 1.0, "grok", chunking_enabled=True)]
            self.assertEqual(teile, [MP3])
            aufrufe["n"] = 0
            with self.assertRaises(tts.TtsSessionExpiredError):
                [b async for b in tts.synthesize_chunked(lang, "grok-leo", 1.0, "grok",
                                                         chunking_enabled=True, strict=True)]

    async def test_abgelaufene_sitzung_markiert_dienst_als_weg(self):
        with mock.patch.object(tts.httpx, "get", return_value=Antwort(200, payload={"ok": True})):
            self.assertTrue(tts.grok_available(force=True))
        tts.mark_unavailable("grok")
        with mock.patch.object(tts.httpx, "get", side_effect=AssertionError("nicht erneut fragen")):
            self.assertFalse(tts.grok_available())


class EndpunktAusweichenTest(unittest.TestCase):
    def test_grok_scheitert_beim_vorlesen_edge_springt_ein(self):
        import asyncio
        import uuid
        from fastapi.testclient import TestClient
        from pocket_claude import db, server
        with TestClient(server.app) as c:
            name = "Vorleser" + uuid.uuid4().hex[:6]
            u = asyncio.run(db.create_user(name, "passwort-9", must_change_password=False))
            tok = c.post("/auth/login", json={"username": name, "password": "passwort-9"}).json()["token"]
            h = {"Authorization": f"Bearer {tok}"}
            cid = asyncio.run(db.create_conversation("T", user_id=u["id"]))
            mid = asyncio.run(db.add_message(cid, "assistant", "Hallo Welt."))

            def fake(text, voice, rate, provider):
                if provider == "grok":
                    raise tts.TtsSessionExpiredError("abgelaufen")
                return MP3

            with mock.patch.object(tts, "grok_available", return_value=True), \
                 mock.patch.object(tts, "gemini_web_available", return_value=False), \
                 mock.patch.object(tts, "synthesize", side_effect=fake), \
                 mock.patch.object(tts, "mark_unavailable") as weg:
                r = c.get(f"/messages/{mid}/audio?voice=grok-leo&rate=1.0", headers=h)
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.content, MP3)
            self.assertEqual(r.headers["x-pocket-claude-provider"], "edge_tts")
            weg.assert_called_with("grok")
