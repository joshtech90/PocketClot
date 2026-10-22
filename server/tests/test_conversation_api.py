"""Chat-Endpunkte ueber die echte FastAPI-App: Reihenfolge der Anhaenge,
Gem-Skills im Skills-Dialog, PATCH ohne Teil-Schreiben und Upload-Dateinamen."""
from __future__ import annotations

import asyncio
import os
import tempfile
import uuid

_TMP_DATA_DIR = tempfile.mkdtemp(prefix="pc-test-data-")
os.environ.setdefault("SERVER_TOKEN", "x" * 40)
os.environ.setdefault("DATA_DIR", _TMP_DATA_DIR)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from pocket_claude import db, server  # noqa: E402
from pocket_claude.config import settings  # noqa: E402


@pytest.fixture(scope="module")
def ctx():
    with TestClient(server.app) as client:
        name = f"Tester{uuid.uuid4().hex[:6]}"
        asyncio.run(db.create_user(name, "passwort-3", must_change_password=False))
        r = client.post("/auth/login", json={"username": name, "password": "passwort-3"})
        assert r.status_code == 200, r.text
        yield client, {"Authorization": f"Bearer {r.json()['token']}"}


def _upload(c, h, filename: str) -> dict:
    r = c.post("/attachments", headers=h, files={"file": (filename, b"hallo", "text/plain")})
    assert r.status_code == 200, r.text
    return r.json()


def test_message_attachments_keep_upload_order(ctx):
    # Frueher kamen die Anhaenge in der Reihenfolge der DB-Abfrage zurueck.
    c, h = ctx
    ids = [_upload(c, h, f"{n}.txt")["id"] for n in ("eins", "zwei", "drei", "vier")]
    wanted = [ids[2], ids[0], ids[3], ids[1]]
    cid = c.post("/conversations", headers=h, json={}).json()["id"]
    asyncio.run(db.add_message(cid, role="user", content="x", tokens=1, attachment_ids=wanted))
    detail = c.get(f"/conversations/{cid}", headers=h).json()
    assert [a["id"] for a in detail["messages"][0]["attachments"]] == wanted


def test_upload_name_with_slash_stays_in_upload_dir(ctx):
    c, h = ctx
    att = _upload(c, h, "bild.png/../../etwas")
    row = asyncio.run(db.get_attachments([att["id"]]))[0]
    path = os.path.realpath(row["path"])
    assert os.path.dirname(path) == os.path.realpath(settings.uploads_dir)
    assert os.path.isfile(path)


def test_patch_rejects_unknown_model_without_writing(ctx):
    c, h = ctx
    cid = c.post("/conversations", headers=h, json={}).json()["id"]
    r = c.patch(f"/conversations/{cid}", headers=h,
                json={"title": "Neu", "chat_model": "gibt-es-nicht"})
    assert r.status_code == 400
    conv = asyncio.run(db.get_conversation(cid))
    assert conv["title"] != "Neu" and not conv.get("chat_model")
    # Sperren ohne PIN wird abgelehnt, ebenfalls ohne den Titel zu schreiben
    r = c.patch(f"/conversations/{cid}", headers=h, json={"title": "Neu", "locked": True})
    assert r.status_code == 400
    assert asyncio.run(db.get_conversation(cid))["title"] != "Neu"


def test_skills_dialog_shows_gem_skills(ctx):
    # Der Turn nutzt die Gem-Skills; der Dialog muss dasselbe zeigen.
    c, h = ctx
    skills = {"web_search": False, "web_fetch": False, "code_execution": False}
    r = c.post("/me/gems", headers=h,
               json={"name": "Ohne Netz", "instructions": "Sei kurz.", "skills": skills})
    assert r.status_code == 201, r.text
    cid = c.post("/conversations", headers=h, json={"gem_id": r.json()["id"]}).json()["id"]
    got = c.get(f"/conversations/{cid}/skills", headers=h).json()
    assert got["is_override"] is True
    assert got["skills"]["web_search"] is False and got["skills"]["web_fetch"] is False
    # Chat-Override zuruecknehmen faellt auf das Gem zurueck, nicht auf den User
    got = c.put(f"/conversations/{cid}/skills", headers=h, json={"skills": None}).json()
    assert got["skills"]["web_search"] is False
