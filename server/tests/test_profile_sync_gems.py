"""Profilbilder, Umbenennen, geteilte Oberflaechen-Einstellungen und die
Startwerte von Gems (Modell und Denktiefe) ueber die echte FastAPI-App."""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
import uuid

_TMP_DATA_DIR = tempfile.mkdtemp(prefix="pc-test-data-")
os.environ.setdefault("SERVER_TOKEN", "x" * 40)
os.environ.setdefault("DATA_DIR", _TMP_DATA_DIR)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from pocket_claude import db, server  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _login(client: TestClient, name: str, password: str) -> dict:
    r = client.post("/auth/login", json={"username": name, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="module")
def ctx():
    with TestClient(server.app) as client:
        suffix = uuid.uuid4().hex[:6]
        admin_name, user_name = f"Chef{suffix}", f"Kati{suffix}"
        admin = asyncio.run(db.create_user(admin_name, "passwort-1", is_admin=True,
                                           must_change_password=False))
        user = asyncio.run(db.create_user(user_name, "passwort-2",
                                          must_change_password=False))
        yield {
            "client": client,
            "admin": admin, "user": user,
            "admin_h": _login(client, admin_name, "passwort-1"),
            "user_h": _login(client, user_name, "passwort-2"),
        }


def test_ui_settings_only_shared_keys(ctx):
    c, h, uid = ctx["client"], ctx["user_h"], ctx["user"]["id"]
    asyncio.run(db.kv_set_many({"chat_lock_pin_hash": "geheim"}, scope=uid))
    r = c.put("/ui-settings", headers=h, json={
        "theme": "dark", "effortByFamily": '{"gemini":"low"}',
        "chat_lock_pin_hash": "ueberschrieben", "claude_auth_mode": "api_key",
    })
    assert r.json()["count"] == 2
    got = c.get("/ui-settings", headers=h).json()["settings"]
    assert got["theme"] == "dark"
    assert got["effortByFamily"] == '{"gemini":"low"}'
    assert "chat_lock_pin_hash" not in got and "claude_auth_mode" not in got
    kv = asyncio.run(db.kv_get_all(scope=uid))
    assert kv["chat_lock_pin_hash"] == "geheim"
    assert "claude_auth_mode" not in kv


def test_avatar_roundtrip_and_access(ctx):
    c = ctx["client"]
    uid, aid = ctx["user"]["id"], ctx["admin"]["id"]
    assert c.get("/me", headers=ctx["user_h"]).json()["avatar_version"] is None
    r = c.put("/me/avatar", headers=ctx["user_h"], files={"file": ("a.png", PNG, "image/png")})
    assert r.status_code == 200 and r.json()["avatar_version"]
    r = c.get(f"/users/{uid}/avatar", headers=ctx["user_h"])
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    # ?token= fuer <img src>
    token = ctx["user_h"]["Authorization"].split()[1]
    assert c.get(f"/users/{uid}/avatar?token={token}").status_code == 200
    # Fremde Bilder sieht nur der Admin
    assert c.get(f"/users/{aid}/avatar", headers=ctx["user_h"]).status_code == 403
    assert c.get(f"/users/{uid}/avatar", headers=ctx["admin_h"]).status_code == 200
    # Kein Bild, falsches Format, zu gross
    bad = c.put("/me/avatar", headers=ctx["user_h"], files={"file": ("a.png", b"GIF89a....", "image/png")})
    assert bad.status_code == 415
    big = c.put("/me/avatar", headers=ctx["user_h"],
                files={"file": ("a.png", PNG + b"\x00" * 600_000, "image/png")})
    assert big.status_code == 413
    # Admin setzt und loescht fuer andere
    assert c.put(f"/users/{uid}/avatar", headers=ctx["user_h"],
                 files={"file": ("a.png", PNG, "image/png")}).status_code == 403
    assert c.delete(f"/users/{uid}/avatar", headers=ctx["admin_h"]).json()["avatar_version"] is None
    assert c.get(f"/users/{uid}/avatar", headers=ctx["user_h"]).status_code == 404


def test_admin_renames_user_and_session_survives(ctx):
    c, uid = ctx["client"], ctx["user"]["id"]
    new_name = "Umbenannt" + uuid.uuid4().hex[:4]
    assert c.patch(f"/users/{uid}", headers=ctx["user_h"], json={"name": "x"}).status_code == 403
    r = c.patch(f"/users/{uid}", headers=ctx["admin_h"], json={"name": new_name})
    assert r.status_code == 200 and r.json()["name"] == new_name
    assert c.get("/me", headers=ctx["user_h"]).json()["name"] == new_name
    # Doppelter Name (auch in anderer Schreibweise) wird abgelehnt
    taken = ctx["admin"]["name"].upper()
    assert c.patch(f"/users/{uid}", headers=ctx["admin_h"], json={"name": taken}).status_code == 409
    # Neuer Name ist der Anmeldename
    _login(c, new_name.lower(), "passwort-2")


def _gem(c, h, **extra) -> str:
    body = {"name": "Testgem", "instructions": "Sei kurz.", **extra}
    r = c.post("/me/gems", headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_gem_seeds_chat_model_and_effort(ctx):
    c, h = ctx["client"], ctx["user_h"]
    gid = _gem(c, h, model="opus", effort="low")
    conv = c.post("/conversations", headers=h, json={"gem_id": gid}).json()
    assert conv["chat_model"] == "opus" and conv["chat_effort"] == "low"
    detail = c.get(f"/conversations/{conv['id']}", headers=h).json()
    assert detail["chat_effort"] == "low"
    # Im Chat umstellen
    r = c.patch(f"/conversations/{conv['id']}", headers=h, json={"chat_effort": "max"})
    assert r.status_code == 200 and r.json()["chat_effort"] == "max"
    assert c.patch(f"/conversations/{conv['id']}", headers=h,
                   json={"chat_effort": "turbo"}).status_code == 400
    # Leer gibt an die Familien-Vorgabe zurueck
    r = c.patch(f"/conversations/{conv['id']}", headers=h, json={"chat_effort": ""})
    assert r.json()["chat_effort"] is None
    # Gem ohne Vorgaben legt nichts fest
    plain = c.post("/conversations", headers=h, json={"gem_id": _gem(c, h)}).json()
    assert plain["chat_model"] is None and plain["chat_effort"] is None


def test_ui_settings_map_entries_merge(ctx):
    c, h = ctx["client"], ctx["user_h"]
    c.put("/ui-settings", headers=h, json={"effortByFamily": '{"claude":"high","gemini":"high"}'})
    # Ein Geraet aendert nur Gemini, ein anderes nur Claude: beide bleiben.
    c.put("/ui-settings", headers=h, json={"effortByFamily": {"gemini": "low"}})
    c.put("/ui-settings", headers=h, json={"effortByFamily": {"claude": "max"}})
    got = c.get("/ui-settings", headers=h).json()["settings"]["effortByFamily"]
    assert json.loads(got) == {"claude": "max", "gemini": "low"}
    # null entfernt einen Eintrag
    c.put("/ui-settings", headers=h, json={"autoSpeakByChat": {"c1": True, "c2": False}})
    c.put("/ui-settings", headers=h, json={"autoSpeakByChat": {"c1": None}})
    got = c.get("/ui-settings", headers=h).json()["settings"]["autoSpeakByChat"]
    assert json.loads(got) == {"c2": False}
    # Objekte nur fuer die Listen-Schluessel
    assert c.put("/ui-settings", headers=h, json={"theme": {"x": 1}}).status_code == 400


def test_chat_speeds_merge_reset_and_stay_private(ctx):
    c, alice, bob = ctx["client"], ctx["user_h"], ctx["admin_h"]
    for values in ({"chat-a": 0.75}, {"chat-b": 1.5}, {"chat-a": 1.25}):
        assert c.put("/ui-settings", headers=alice,
                     json={"ttsSpeedByChat": values}).status_code == 200
    speeds = c.get("/ui-settings", headers=alice).json()["settings"]["ttsSpeedByChat"]
    assert json.loads(speeds) == {"chat-a": 1.25, "chat-b": 1.5}
    assert "ttsSpeedByChat" not in c.get("/ui-settings", headers=bob).json()["settings"]
    c.put("/ui-settings", headers=alice, json={"ttsSpeedByChat": {"chat-a": None}})
    speeds = c.get("/ui-settings", headers=alice).json()["settings"]["ttsSpeedByChat"]
    assert json.loads(speeds) == {"chat-b": 1.5}


def test_migration_pins_existing_gem_chats(ctx):
    c, h, uid = ctx["client"], ctx["user_h"], ctx["user"]["id"]
    gid = _gem(c, h, model="sonnet", effort="medium")
    old = asyncio.run(db.create_conversation("Alt", user_id=uid, gem_id=gid))

    async def downgrade_and_migrate():
        # Zustand vor dem Update: keine Spalte chat_effort, kein Modell am Chat
        async with db.get_db() as conn:
            await conn.execute("UPDATE conversations SET chat_model = NULL WHERE id = ?", (old,))
            await conn.execute("ALTER TABLE conversations DROP COLUMN chat_effort")
            await conn.commit()
        await db.init_db()

    asyncio.run(downgrade_and_migrate())
    detail = c.get(f"/conversations/{old}", headers=h).json()
    assert detail["chat_model"] == "sonnet" and detail["chat_effort"] == "medium"


def test_defaults_migration_sets_opus_high_once(ctx):
    uid = ctx["user"]["id"]
    asyncio.run(db.kv_set_many({"chatModel": "gw:x:y", "effortByFamily": '{"gemini":"low","claude":"max"}',
                                "defaults_opus_high_migrated": ""}, scope=uid))
    asyncio.run(server._migrate_defaults_opus_high())
    kv = asyncio.run(db.kv_get_all(scope=uid))
    assert kv["chatModel"] == "opus" and kv["effort"] == "high"
    assert json.loads(kv["effortByFamily"]) == {"gemini": "low", "claude": "high"}
    # Eine spaetere eigene Wahl bleibt
    asyncio.run(db.kv_set_many({"chatModel": "sonnet"}, scope=uid))
    asyncio.run(server._migrate_defaults_opus_high())
    assert asyncio.run(db.kv_get_all(scope=uid))["chatModel"] == "sonnet"


def test_new_user_gets_defaults_immediately(ctx):
    """Vom Admin angelegte Konten haben Opus/Hoch und Grok Leo sofort, nicht
    erst nach dem naechsten Neustart."""
    c, h = ctx["client"], ctx["admin_h"]
    r = c.post("/users", headers=h, json={"name": f"Neu{uuid.uuid4().hex[:6]}",
                                          "password": "passwort-3"})
    assert r.status_code == 200, r.text
    kv = asyncio.run(db.kv_get_all(scope=r.json()["id"]))
    assert kv["chatModel"] == server.claude_engine.DEFAULT_CLAUDE_MODEL
    assert kv["effort"] == "high"
    assert json.loads(kv["effortByFamily"]) == {"claude": "high"}
    assert kv[server._KV_TTS_PROVIDER] == server.tts.PROVIDER_GROK
    assert kv["ttsVoice"] == server.tts.DEFAULT_VOICE_GROK
