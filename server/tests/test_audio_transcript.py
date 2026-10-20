"""Geteilte Sprachnachrichten: das Modell bekommt das Transkript als Text.

Kein Modell im Chat kann Audio selbst hoeren. Ohne Transkript stand bei Claude
nur ein Dateipfad im Prompt, bei Gemini/GPT "kann dieses Modell nicht oeffnen".
Das Transkript liegt am Anhang in der Datenbank, damit Konto-Loeschung und
Backups es mitnehmen.
"""
import asyncio
import os
import tempfile
from pathlib import Path

os.environ.setdefault("SERVER_TOKEN", "x" * 40)
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="pc-test-data-"))

from pocket_claude import attachments, claude_engine, db, voice  # noqa: E402


async def _audio(tmp_path, name="sprachnachricht.opus", mime="audio/ogg") -> dict:
    await db.init_db()
    p = tmp_path / name
    p.write_bytes(b"OggS" + b"\x00" * 64)
    aid = await db.add_attachment(name, mime, 68, Path(p), user_id="usr_audio")
    return (await db.get_attachments([aid]))[0]


def test_transkript_wird_einmal_erzeugt_und_steht_im_prompt(monkeypatch, tmp_path):
    aufrufe = []

    async def fake_transcribe(**kw):
        aufrufe.append(kw)
        return "Hallo Joscha, ich komme morgen um zehn."
    monkeypatch.setattr(voice, "transcribe", fake_transcribe)

    async def main():
        a = await _audio(tmp_path)
        for _ in range(2):
            frisch = (await db.get_attachments([a["id"]]))[0]
            assert await attachments.ensure_transcripts([frisch], api_key="gsk_test") == []
        assert len(aufrufe) == 1
        # Ohne feste Sprache in der Spracheingabe erkennt Whisper sie selbst.
        assert aufrufe[0]["whisper_lang"] == ""

        frisch = (await db.get_attachments([a["id"]]))[0]
        by_id = {a["id"]: frisch}
        text = attachments.build_prompt_text({"content": "", "attachment_ids": [a["id"]]}, by_id)
        assert "ich komme morgen um zehn" in text
        assert not attachments.has_binary_attachments([a["id"]], by_id)

        # Auch beim Neuaufbau des Verlaufs fuer Claude (nach Modellwechsel).
        verlauf = claude_engine._format_transcript(
            [{"id": 1, "role": "user", "content": "", "attachment_ids": [a["id"]]},
             {"id": 2, "role": "user", "content": "was wollte er?"}], 2, by_id)
        assert "ich komme morgen um zehn" in verlauf
    asyncio.run(main())


def test_ohne_schluessel_sagt_der_prompt_dass_der_inhalt_fehlt(tmp_path):
    async def main():
        a = await _audio(tmp_path, name="diktat.m4a", mime="audio/mp4")
        assert await attachments.ensure_transcripts([a], api_key="")
        text = attachments.build_prompt_text(
            {"content": "was sagt er?", "attachment_ids": [a["id"]]}, {a["id"]: a})
        assert "kein Transkript" in text
    asyncio.run(main())
