"""Geteilte Sprachnachrichten: das Modell bekommt das Transkript als Text.

Kein Modell im Chat kann Audio selbst hoeren. Ohne Transkript stand bei Claude
nur ein Dateipfad im Prompt, bei Gemini/GPT "kann dieses Modell nicht oeffnen".
"""
import asyncio

from pocket_claude import attachments, voice


def _att(tmp_path, name="sprachnachricht.opus", mime="audio/ogg"):
    p = tmp_path / name
    p.write_bytes(b"OggS" + b"\x00" * 64)
    return {"id": "att_a", "filename": name, "mime_type": mime, "size_bytes": 68, "path": str(p)}


def test_transkript_wird_einmal_erzeugt_und_steht_im_prompt(monkeypatch, tmp_path):
    aufrufe = []

    async def fake_transcribe(**kw):
        aufrufe.append(kw)
        return "Hallo Joscha, ich komme morgen um zehn."
    monkeypatch.setattr(voice, "transcribe", fake_transcribe)
    a = _att(tmp_path)

    for _ in range(2):
        fehler = asyncio.run(attachments.ensure_transcripts([a], api_key="gsk_test"))
        assert fehler == []
    assert len(aufrufe) == 1
    # Ohne feste Sprache in der Spracheingabe erkennt Whisper sie selbst.
    assert aufrufe[0]["whisper_lang"] == ""

    text = attachments.build_prompt_text(
        {"content": "", "attachment_ids": ["att_a"]}, {"att_a": a})
    assert "ich komme morgen um zehn" in text
    assert not attachments.has_binary_attachments(["att_a"], {"att_a": a})


def test_ohne_schluessel_sagt_der_prompt_dass_der_inhalt_fehlt(tmp_path):
    a = _att(tmp_path, name="diktat.m4a", mime="audio/mp4")
    fehler = asyncio.run(attachments.ensure_transcripts([a], api_key=""))
    assert fehler
    text = attachments.build_prompt_text(
        {"content": "was sagt er?", "attachment_ids": ["att_a"]}, {"att_a": a})
    assert "kein Transkript" in text
