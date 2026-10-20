"""Weiterbearbeiten im Chat: "mach den Himmel abendlich" ohne neuen Anhang.

Vorher zeichnete das Modell dann komplett neu, und das Motiv war ein anderes.
Jetzt dient das zuletzt im Chat gezeigte Bild als Vorlage.
"""
import asyncio
import base64
import os
import tempfile
from pathlib import Path

os.environ.setdefault("SERVER_TOKEN", "x" * 40)
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="pc-test-data-"))

from pocket_claude import db, image_engine, image_tool  # noqa: E402

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


def test_aenderung_ohne_anhang_nimmt_das_letzte_bild_als_vorlage(monkeypatch, tmp_path):
    gesehen: dict = {}

    async def fake_generate(**kwargs):
        gesehen["refs"] = kwargs.get("references") or []
        return [image_engine.GeneratedImage(index=0, mime_type="image/png", data=PNG,
                                            text="", provider="gemini")]
    monkeypatch.setattr(image_engine, "generate", fake_generate)

    async def main():
        await db.init_db()
        user = await db.create_user("bildtest", "bildtest-pw-123", must_change_password=False)
        uid = user["id"]
        cid = await db.create_conversation(user_id=uid)
        alt = tmp_path / "alt.png"
        alt.write_bytes(PNG)
        alt_id = await db.add_attachment("alt.png", "image/png", len(PNG), Path(alt), user_id=uid)
        await db.add_message(cid, role="user", content="Mal einen Fuchs")
        await db.add_message(cid, role="assistant", content="Hier.", attachment_ids=[alt_id])
        frage = await db.add_message(cid, role="user", content="mach den Himmel abendlich")

        vorher = await image_tool.previous_image_ids(cid, before_message_id=frage)
        assert vorher == [alt_id]
        res = await image_tool.run(uid, {"prompt": "sunset sky", "edit_attached_images": True},
                                   {"attachment_ids": [], "previous_image_ids": vorher})
        assert res["ok"]
        assert len(gesehen["refs"]) == 1

        # Ohne Aenderungswunsch bleibt es ein neues Bild ohne Vorlage.
        await image_tool.run(uid, {"prompt": "a new fox"},
                             {"attachment_ids": [], "previous_image_ids": vorher})
        assert gesehen["refs"] == []

        # Ein neues, aber unbrauchbares Bild darf NICHT durch das alte ersetzt
        # werden: das alte Foto ginge sonst ungewollt an den Anbieter.
        heic = tmp_path / "neu.heic"
        heic.write_bytes(b"\x00\x00\x00\x18ftypheic" + b"\x00" * 64)
        heic_id = await db.add_attachment("neu.heic", "image/heic", 76, Path(heic), user_id=uid)
        gesehen.clear()
        res = await image_tool.run(uid, {"prompt": "edit", "edit_attached_images": True},
                                   {"attachment_ids": [heic_id], "previous_image_ids": vorher})
        assert not res["ok"]
        assert "refs" not in gesehen
    asyncio.run(main())
