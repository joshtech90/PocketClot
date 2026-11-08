"""Gedächtnisabfragen lassen Bilder und Webwerkzeuge im selben Turn nutzbar."""
import asyncio
import json
import os
import tempfile

import httpx
import pytest

os.environ.setdefault("SERVER_TOKEN", "x" * 40)
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="pc-memory-tools-"))

from pocket_claude import db, gateways, image_tool, openai_engine, web_tool, wissen_tool
from pocket_claude.config import settings


@pytest.mark.parametrize("family", ["gpt", "gemini"])
def test_tools_continue_after_memory_recall(tmp_path, monkeypatch, family):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    model = gateways.ChatModel(
        key=f"gw:test:{family}", gateway_id="test", gateway_label="Test", family=family,
        base_id=f"{family}-model", label="Test", fallback_id=f"{family}-model",
        native_web_search=(family == "gpt"))
    gateway = gateways.GatewayConfig(id="test", label="Test", base_url="https://gateway.test/v1")

    async def models(**kwargs):
        return [model]

    monkeypatch.setattr(gateways, "list_models", models)
    monkeypatch.setattr(gateways, "gateway_by_id", lambda _: gateway)
    attachment = {}

    async def recall(user_id, args, key=None):
        return {"ok": True, "text": "Nutzer mag Kakteen."}

    async def draw(user_id, args, defaults):
        return {"ok": True, "text": "Kaktus-Bild erstellt.", "attachments": [attachment]}

    async def fetch(url, **kwargs):
        return {"ok": True, "text": "Kaktus-Info"}

    async def search(gw, model_id, query):
        return {"ok": True, "text": "Kaktus-Pflegetipps"}

    monkeypatch.setattr(wissen_tool, "freigeschaltet", lambda *args: True)
    monkeypatch.setattr(wissen_tool, "run", recall)
    monkeypatch.setattr(image_tool, "run", draw)
    monkeypatch.setattr(web_tool, "fetch", fetch)
    monkeypatch.setattr(web_tool, "search", search)
    requests = []

    def respond(request):
        payload = json.loads(request.content)
        step = len(requests)
        requests.append(payload)
        if step == 0:
            calls = [(wissen_tool.TOOL_NAME, {"anfrage": "Was mag ich?"})]
        elif step == 1:
            calls = [(image_tool.TOOL_NAME, {"prompt": "Kaktus"}),
                     (web_tool.FETCH_TOOL_NAME, {"url": "https://example.org/kaktus"})]
            if family == "gemini":
                calls.append((web_tool.SEARCH_TOOL_NAME, {"query": "Kaktus-Pflege"}))
        else:
            calls = []
        delta = {"tool_calls": [
            {"index": i, "id": f"call_{step}_{i}", "type": "function",
             "function": {"name": name, "arguments": json.dumps(args)}}
            for i, (name, args) in enumerate(calls)
        ]} if calls else {"content": "Hier ist dein Bild."}
        body = "data: " + json.dumps({"choices": [{"delta": delta}]}) + "\n\ndata: [DONE]\n\n"
        return httpx.Response(200, text=body)

    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(
        **kwargs, transport=httpx.MockTransport(respond)))

    async def run():
        await db.init_db()
        user = await db.create_user("test", "test-password-123", must_change_password=False)
        cid = await db.create_conversation(user_id=user["id"])
        mid = await db.add_message(cid, role="user", content="Male etwas, das ich mag, und suche Tipps.")
        path = tmp_path / "kaktus.png"
        path.write_bytes(b"test-bild")
        aid = await db.add_attachment("kaktus.png", "image/png", 9, path, user_id=user["id"])
        attachment.update(id=aid, filename="kaktus.png")
        events = [e async for e in openai_engine.stream_reply(
            cid, mid, model_key=model.key, user_id=user["id"], wissen_schluessel="test-key")]
        assert not any(e["type"] == "error" for e in events), events
        assert any(e["type"] == "image" and e["attachments"] == [attachment] for e in events)
        assert any(e["type"] == "done" for e in events)

    asyncio.run(run())
    assert len(requests) == 3
    # Both advertisement and execution must continue after recall.
    tools = requests[1]["tools"]
    names = {t.get("function", {}).get("name") for t in tools}
    assert {image_tool.TOOL_NAME, web_tool.FETCH_TOOL_NAME} <= names
    if family == "gpt":
        assert any(t.get("type") == "web_search" for t in tools)
    else:
        assert web_tool.SEARCH_TOOL_NAME in names
    results = {m["content"] for m in requests[2]["messages"] if m["role"] == "tool"}
    assert {"Nutzer mag Kakteen.", "Kaktus-Bild erstellt.", "Kaktus-Info"} <= results
    if family == "gemini":
        assert "Kaktus-Pflegetipps" in results
