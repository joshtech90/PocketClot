"""Public listing tools work through each chat engine and follow web skills."""
import asyncio
import json
import os
import sys
import tempfile

import httpx
import pytest
from mcp.shared.memory import create_connected_server_and_client_session

os.environ.setdefault("SERVER_TOKEN", "x" * 40)
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="pc-research-tools-"))

from pocket_claude import claude_engine, db, gateways, openai_engine, research_tools, web_tool
from pocket_claude.config import settings


AD_URL = "https://www.kleinanzeigen.de/s-anzeige/1234567890"


@pytest.fixture
def public_cli(tmp_path, monkeypatch):
    path = tmp_path / "kleinanzeigen-cli"
    path.write_text(f"#!{sys.executable}\n" + '''
import json
import sys

ad = {"id": "1234567890", "title": "Fujifilm X100V", "price": 950,
      "description": "Leichter Kratzer am Gehäuse", "status": "ACTIVE"}
assert sys.argv[1] in ("search", "ad")
print(json.dumps([ad] if sys.argv[1] == "search" else ad))
''', encoding="utf-8")
    path.chmod(0o700)
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "kleinanzeigen_cli_path", str(path))


def test_claude_reads_link_via_registered_mcp(public_cli):
    async def run():
        research = research_tools.available({"web_search": False})
        server, _ = claude_engine._build_image_mcp_server(
            "usr_test", None, [], asyncio.Queue(), mit_bild=False, mit_web=True,
            research=research,
        )
        async with create_connected_server_and_client_session(server["instance"]) as client:
            assert "kleinanzeigen_search" not in {tool.name for tool in (await client.list_tools()).tools}
            result = await client.call_tool("kleinanzeigen_detail", {"url": AD_URL})
            assert not result.isError and "Kratzer" in result.content[0].text

        route = claude_engine._research_fetch_hook(research).hooks[0]
        routed = await route({"tool_input": {"url": AD_URL}}, None, {})
        assert "mcp__pocket__kleinanzeigen_detail" in routed["hookSpecificOutput"]["permissionDecisionReason"]
        assert await route({"tool_input": {"url": "https://example.org"}}, None, {}) == {}

    asyncio.run(run())


@pytest.mark.parametrize("family", ["gpt", "gemini"])
@pytest.mark.parametrize("search_enabled", [True, False])
def test_gateway_reads_link_and_respects_search_skill(public_cli, monkeypatch, family, search_enabled):
    model = gateways.ChatModel(
        key=f"gw:test:{family}", gateway_id="test", gateway_label="Test", family=family,
        base_id=family, label="Test", fallback_id=family, native_web_search=(family == "gpt"),
    )
    gateway = gateways.GatewayConfig(id="test", label="Test", base_url="https://gateway.test/v1")

    async def models(**kwargs):
        return [model]

    monkeypatch.setattr(gateways, "list_models", models)
    monkeypatch.setattr(gateways, "gateway_by_id", lambda _: gateway)
    requests = []

    def respond(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if len(requests) == 1:
            delta = {"tool_calls": [
                {"index": i, "id": f"call_{i}", "type": "function", "function": {
                    "name": name, "arguments": json.dumps(args),
                }} for i, (name, args) in enumerate([
                    ("kleinanzeigen_detail", {"url": AD_URL}),
                    ("kleinanzeigen_search", {"query": "Fujifilm X100V"}),
                ])
            ]}
        else:
            delta = {"content": "Die Anzeige beschreibt einen leichten Kratzer."}
        body = "data: " + json.dumps({"choices": [{"delta": delta}]}) + "\n\ndata: [DONE]\n\n"
        return httpx.Response(200, text=body)

    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(
        **kwargs, transport=httpx.MockTransport(respond)))

    async def run():
        await db.init_db()
        user = await db.create_user("test", "test-password-123", must_change_password=False)
        cid = await db.create_conversation(user_id=user["id"])
        mid = await db.add_message(cid, role="user", content=f"Prüfe {AD_URL}")
        return [event async for event in openai_engine.stream_reply(
            cid, mid, model_key=model.key, user_id=user["id"], allow_image_tool=False,
            skills={"web_search": search_enabled},
        )]

    events = asyncio.run(run())
    assert events[-1]["type"] == "done", events
    names = {tool.get("function", {}).get("name") for tool in requests[0]["tools"]}
    assert "kleinanzeigen_detail" in names
    assert ("kleinanzeigen_search" in names) == search_enabled
    results = {msg["tool_call_id"]: msg["content"] for msg in requests[1]["messages"] if msg["role"] == "tool"}
    assert "Kratzer" in results["call_0"]
    assert ("Fujifilm X100V" in results["call_1"]) == search_enabled
    assert AD_URL in "".join(event.get("text", "") for event in events)


def test_web_fetch_uses_cli_for_listing(public_cli, monkeypatch):
    def unexpected_network(*args, **kwargs):
        pytest.fail("A recognized Kleinanzeigen link should be read through the CLI")

    monkeypatch.setattr(web_tool, "_check_host", unexpected_network)
    result = asyncio.run(web_tool.fetch(AD_URL))
    assert result["ok"] and "Kratzer" in result["text"]
