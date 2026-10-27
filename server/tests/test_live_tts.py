"""Vorlesen waehrend der Antwort: Stuecke gehoeren nur ihrem Nutzer, und
Unsprechbares wird gleich beim Anlegen abgewiesen statt spaeter beim Abspielen."""
from __future__ import annotations

import asyncio
import os
import tempfile
import uuid

os.environ.setdefault("SERVER_TOKEN", "x" * 40)
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="pc-test-data-"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from pocket_claude import db, server, tts  # noqa: E402


def _login(client: TestClient) -> dict:
    name = f"Tester{uuid.uuid4().hex[:6]}"
    asyncio.run(db.create_user(name, "passwort-3", must_change_password=False))
    r = client.post("/auth/login", json={"username": name, "password": "passwort-3"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="module")
def ctx():
    with TestClient(server.app) as client:
        yield client, _login(client), _login(client)


def test_live_segment_belongs_to_its_user(ctx, monkeypatch):
    c, alice, bob = ctx
    spoken: list[str] = []

    async def fake_synth(text, *a, **k):
        spoken.append(text)
        yield b"ID3fake"

    async def fake_providers():
        return {tts.PROVIDER_GROK: True}

    monkeypatch.setattr(tts, "synthesize_chunked", fake_synth)
    monkeypatch.setattr(server, "_available_providers", fake_providers)

    seg = c.post("/tts/live", headers=alice, json={"text": "Gute Frage, kurz vorweg."})
    assert seg.status_code == 200, seg.text
    url = f"/tts/live/{seg.json()['id']}/audio"

    assert c.get(url, headers=bob).status_code == 404
    r = c.get(url, headers=alice)
    assert r.status_code == 200 and r.content == b"ID3fake"
    assert spoken == ["Gute Frage, kurz vorweg."]


@pytest.mark.parametrize("text", [
    "```python\nprint(1)\n```",
    "[^1]: https://example.com/quelle",
    "\n\n**Quellen**\n1. [example.com](https://example.com)",
])
def test_unspeakable_segment_is_rejected(ctx, text):
    c, alice, _ = ctx
    assert c.post("/tts/live", headers=alice, json={"text": text}).status_code == 400
