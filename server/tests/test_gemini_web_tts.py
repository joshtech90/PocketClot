"""Tests für den Vorlese-Anbieter Gemini-Web.

Geprüft wird das, was beim Anfassen leicht kaputtgeht: dass Ogg niemals
gestückelt wird, dass die Textgrenze dieses Anbieters gilt und nicht die viel
engere der anderen, dass ein Ausfall des Dienstes sauber unterschieden wird
(erneut versuchen gegen neu anmelden), und dass eine Antwort ohne Ogg-Kopf
nicht als Audio durchgereicht wird.
"""
import asyncio
import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("SERVER_TOKEN", "testtoken123")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pocket_claude import tts  # noqa: E402

OGG = b"OggS" + b"\x00" * 120


class Antwort:
    """Minimale httpx-Antwort für die Tests."""

    def __init__(self, status_code, content=b"", text=""):
        self.status_code = status_code
        self.content = content
        self.text = text or content.decode("utf-8", "replace")


class GrunddatenTest(unittest.TestCase):
    def test_provider_ist_gueltig_und_vorgabe(self):
        self.assertIn(tts.PROVIDER_GEMINI_WEB, tts.VALID_PROVIDERS)
        self.assertEqual(tts.DEFAULT_PROVIDER, tts.PROVIDER_GEMINI_WEB)

    def test_ogg_als_medientyp(self):
        self.assertEqual(tts.media_type_for(tts.PROVIDER_GEMINI_WEB), "audio/ogg")
        # Die anderen bleiben, wie sie waren.
        self.assertEqual(tts.media_type_for(tts.PROVIDER_CLOUD_TTS), "audio/mpeg")
        self.assertEqual(tts.media_type_for(tts.PROVIDER_GEMINI_API), "audio/wav")

    def test_stimme_existiert_und_passt_nur_zu_diesem_anbieter(self):
        stimme = tts.default_voice_for(tts.PROVIDER_GEMINI_WEB)
        treffer = [v for v in tts.CURATED_VOICES if v["id"] == stimme]
        self.assertEqual(len(treffer), 1, "Stimme fehlt in der Liste")
        self.assertEqual(treffer[0]["compatible_providers"], [tts.PROVIDER_GEMINI_WEB])

    def test_stueckeln_ist_ausgeschaltet(self):
        self.assertFalse(tts.chunking_default_for(tts.PROVIDER_GEMINI_WEB))


class SyntheseTest(unittest.TestCase):
    def test_liefert_audio(self):
        with mock.patch.object(tts.httpx, "post", return_value=Antwort(200, OGG)) as post:
            audio = tts._synthesize_gemini_web("Hallo")
        self.assertEqual(audio, OGG)
        self.assertEqual(post.call_args.kwargs["json"]["text"], "Hallo")

    def test_abgelaufene_sitzung_ist_ein_dauerfehler(self):
        # 503 heisst: der Dienst lebt, aber die Google-Sitzung traegt nicht mehr.
        # Ein erneuter Versuch wuerde genauso scheitern, deshalb darf das NICHT
        # als voruebergehend gelten.
        with mock.patch.object(tts.httpx, "post",
                               return_value=Antwort(503, b'{"error":"session_expired"}')):
            with self.assertRaises(tts.TtsSessionExpiredError):
                tts._synthesize_gemini_web("Hallo")

    def test_abgelaufene_sitzung_sperrt_nicht_cloud_tts(self):
        # Wichtig: NICHT TtsCloudTtsUnavailableError. Die setzt im Endpunkt eine
        # serverweite Cloud-TTS-Sperre fuer fuenf Minuten — also ausgerechnet
        # fuer den Anbieter, auf den die Fehlermeldung zum Ausweichen verweist.
        self.assertFalse(
            issubclass(tts.TtsSessionExpiredError, tts.TtsCloudTtsUnavailableError)
        )

    def test_dienst_nicht_erreichbar_ist_voruebergehend(self):
        with mock.patch.object(tts.httpx, "post",
                               side_effect=tts.httpx.ConnectError("weg")):
            with self.assertRaises(tts.TtsTransientError):
                tts._synthesize_gemini_web("Hallo")

    def test_antwort_ohne_ogg_kopf_wird_abgelehnt(self):
        # Eine Fehlermeldung mit Statuscode 200 wuerde als Audio durchgereicht
        # und im Player als stumme, nie endende Wiedergabe enden.
        with mock.patch.object(tts.httpx, "post",
                               return_value=Antwort(200, b'{"error":"irgendwas"}')):
            with self.assertRaises(tts.TtsTransientError):
                tts._synthesize_gemini_web("Hallo")


class TextgrenzeTest(unittest.TestCase):
    def test_eigene_grenze_statt_der_engen_fremden(self):
        lang = "Satz. " * 2000  # 12.000 Zeichen, weit ueber MAX_SYNTH_CHARS
        self.assertGreater(len(lang), tts.MAX_SYNTH_CHARS)
        self.assertLess(len(lang), tts.GEMINI_WEB_MAX_CHARS)
        gesehen = {}

        def merke(url, json, timeout):  # noqa: ARG001
            gesehen["laenge"] = len(json["text"])
            return Antwort(200, OGG)

        with mock.patch.object(tts.httpx, "post", side_effect=merke):
            tts.synthesize(lang, provider=tts.PROVIDER_GEMINI_WEB)
        # Ungekuerzt durchgereicht: keine Spur des Kuerzungs-Hinweises.
        self.assertEqual(gesehen["laenge"], len(lang.strip()))

    def test_ueber_der_eigenen_grenze_wird_gekuerzt(self):
        zu_lang = "a" * (tts.GEMINI_WEB_MAX_CHARS + 500)
        gesehen = {}

        def merke(url, json, timeout):  # noqa: ARG001
            gesehen["text"] = json["text"]
            return Antwort(200, OGG)

        with mock.patch.object(tts.httpx, "post", side_effect=merke):
            tts.synthesize(zu_lang, provider=tts.PROVIDER_GEMINI_WEB)
        self.assertLess(len(gesehen["text"]), len(zu_lang))
        self.assertTrue(gesehen["text"].endswith("Rest gekürzt."))


class StreamTest(unittest.TestCase):
    def test_ogg_wird_auch_auf_wunsch_nicht_gestueckelt(self):
        # Ogg-Stroeme lassen sich nicht aneinanderhaengen. Selbst wenn jemand
        # das Stueckeln von Hand einschaltet, muss genau EIN Stueck kommen,
        # sonst spielt der Player nur den Anfang ab.
        lang = "Ein Satz zum Vorlesen. " * 200
        rufe = []

        def merke(url, json, timeout):  # noqa: ARG001
            rufe.append(len(json["text"]))
            return Antwort(200, OGG)

        async def lauf():
            teile = []
            with mock.patch.object(tts.httpx, "post", side_effect=merke):
                async for stueck in tts.synthesize_chunked(
                    lang, provider=tts.PROVIDER_GEMINI_WEB, chunking_enabled=True
                ):
                    teile.append(stueck)
            return teile

        teile = asyncio.run(lauf())
        self.assertEqual(len(teile), 1, "Ogg darf nie in mehreren Stuecken kommen")
        self.assertEqual(len(rufe), 1, "Es darf nur ein Aufruf rausgehen")
        self.assertTrue(teile[0].startswith(b"OggS"))

    def test_langer_text_wird_im_stream_nicht_auf_3500_gekappt(self):
        # Ohne Ausnahme greift hier die enge Grenze der anderen Anbieter und
        # schneidet lange Antworten mitten im Satz ab.
        lang = "Ein Satz zum Vorlesen. " * 400  # ~9200 Zeichen
        gesehen = {}

        def merke(url, json, timeout):  # noqa: ARG001
            gesehen["laenge"] = len(json["text"])
            return Antwort(200, OGG)

        async def lauf():
            with mock.patch.object(tts.httpx, "post", side_effect=merke):
                async for _ in tts.synthesize_chunked(
                    lang, provider=tts.PROVIDER_GEMINI_WEB, chunking_enabled=False
                ):
                    pass

        asyncio.run(lauf())
        self.assertGreater(gesehen["laenge"], 3500)


class ErreichbarkeitTest(unittest.TestCase):
    def setUp(self):
        tts._WEB_TTS_CACHE = (0.0, False)

    def test_gesunder_dienst_mit_sitzung(self):
        class Ok:
            status_code = 200

            @staticmethod
            def json():
                return {"ok": True, "token": True}

        with mock.patch.object(tts.httpx, "get", return_value=Ok()):
            self.assertTrue(tts.gemini_web_available(force=True))

    def test_dienst_laeuft_aber_ohne_sitzung_gilt_als_nicht_verfuegbar(self):
        class Ohne:
            status_code = 200

            @staticmethod
            def json():
                return {"ok": False, "token": False}

        with mock.patch.object(tts.httpx, "get", return_value=Ohne()):
            self.assertFalse(tts.gemini_web_available(force=True))

    def test_ergebnis_wird_zwischengespeichert(self):
        class Ok:
            status_code = 200

            @staticmethod
            def json():
                return {"ok": True, "token": True}

        with mock.patch.object(tts.httpx, "get", return_value=Ok()) as get:
            tts.gemini_web_available(force=True)
            tts.gemini_web_available()
            tts.gemini_web_available()
        self.assertEqual(get.call_count, 1)


if __name__ == "__main__":
    unittest.main()
