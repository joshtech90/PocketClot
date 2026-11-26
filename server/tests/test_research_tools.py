"""Public listing tools work through each chat engine and follow web skills."""
import asyncio
import base64
import io
import json
import os
import sys
import tempfile

import httpx
import pytest
from mcp.shared.memory import create_connected_server_and_client_session
from PIL import Image

os.environ.setdefault("SERVER_TOKEN", "x" * 40)
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="pc-research-tools-"))

from pocket_claude import claude_engine, db, gateways, openai_engine, research_tools, web_tool
from pocket_claude.config import settings


AD_URL = "https://www.kleinanzeigen.de/s-anzeige/1234567890"
PHOTO_CDN = "https://img.kleinanzeigen.de/api/v1/prod-ads/images/"
PHOTO_URLS = [f"{PHOTO_CDN}{n:02x}/{n:02x}000000-1234-5678-90ab-0123456789ab"
              for n in range(1, 5)]


@pytest.fixture
def photo_cdn():
    data = io.BytesIO()
    Image.new("RGB", (37, 23), "darkgreen").save(data, "JPEG")
    jpeg = data.getvalue()

    def respond(request):
        if str(request.url) in PHOTO_URLS:
            return httpx.Response(200, headers={"content-type": "image/jpeg"},
                                  stream=httpx.ByteStream(jpeg))
        pytest.fail(f"Unexpected CDN request: {request.url}")

    return respond


def assert_image(encoded):
    with Image.open(io.BytesIO(base64.b64decode(encoded, validate=True))) as img:
        img.load()
        assert img.format == "JPEG" and img.size == (37, 23)


@pytest.fixture
def public_cli(tmp_path, monkeypatch):
    path = tmp_path / "kleinanzeigen-cli"
    path.write_text(f"#!{sys.executable}\n" + f'''
import json
import sys

ad = {{"id": "1234567890", "title": "Fujifilm X100V", "price": 950,
       "description": "Leichter Kratzer am Gehäuse", "status": "ACTIVE",
       "pictures": {PHOTO_URLS!r}}}
assert sys.argv[1] in ("search", "ad")
print(json.dumps([ad] if sys.argv[1] == "search" else ad))
''', encoding="utf-8")
    path.chmod(0o700)
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "kleinanzeigen_cli_path", str(path))


def test_claude_reads_link_via_registered_mcp(public_cli, photo_cdn, monkeypatch):
    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(
        **kwargs, transport=httpx.MockTransport(photo_cdn)))

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
            assert len(result.content) == 1
            result = await client.call_tool("kleinanzeigen_detail", {"url": AD_URL, "photo_numbers": [1]})
            assert not result.isError and result.content[1].text.endswith("Foto 1")
            assert result.content[2].mimeType == "image/jpeg"
            assert_image(result.content[2].data)
            result = await client.call_tool("kleinanzeigen_detail", {"url": AD_URL, "photo_numbers": [3, 2, 4]})
            assert [block.text.rsplit(" ", 1)[-1] for block in result.content[1::2]] == ["3", "2"]
            assert "Fotolimit erreicht): 4" in result.content[0].text

        route = claude_engine._research_fetch_hook(research).hooks[0]
        routed = await route({"tool_input": {"url": AD_URL}}, None, {})
        assert "mcp__pocket__kleinanzeigen_detail" in routed["hookSpecificOutput"]["permissionDecisionReason"]
        assert await route({"tool_input": {"url": "https://example.org"}}, None, {}) == {}

    asyncio.run(run())


def test_photo_error_keeps_listing_and_other_selected_photo(public_cli, photo_cdn, monkeypatch):
    from pocket_claude import listing_media

    real_client = httpx.AsyncClient

    def respond(request):
        if str(request.url) == PHOTO_URLS[0]:
            # A truncated file must not invalidate the listing or another photo.
            return httpx.Response(200, headers={"content-type": "image/jpeg"},
                                  stream=httpx.ByteStream(b"\xff\xd8\xff"))
        return photo_cdn(request)

    monkeypatch.setattr(listing_media.httpx, "AsyncClient", lambda **kwargs: real_client(
        **kwargs, transport=httpx.MockTransport(respond)))
    detail = research_tools.available({"web_search": False})["kleinanzeigen_detail"]
    result = asyncio.run(detail.run({"url": AD_URL, "photo_numbers": [1, 2]}))
    assert result["ok"] and "Kratzer" in result["text"]
    assert "Fotolimit erreicht): 1" in result["text"]
    assert [image["label"] for image in result["images"]] == ["Kleinanzeige 1234567890, Foto 2"]
    assert_image(result["images"][0]["data"])


@pytest.mark.parametrize("family", ["gpt", "gemini"])
@pytest.mark.parametrize("search_enabled,fetch_enabled,vision", [
    (False, True, True), (True, True, False), (True, False, True),
])
def test_gateway_reads_link_and_respects_web_skills(public_cli, photo_cdn, monkeypatch,
                                                     family, search_enabled, fetch_enabled, vision):
    model = gateways.ChatModel(
        key=f"gw:test:{family}", gateway_id="test", gateway_label="Test", family=family,
        base_id=family, label="Test", fallback_id=family, native_web_search=(family == "gpt"),
        supports_vision=vision,
    )
    gateway = gateways.GatewayConfig(id="test", label="Test", base_url="https://gateway.test/v1")

    async def models(**kwargs):
        return [model]

    monkeypatch.setattr(gateways, "list_models", models)
    monkeypatch.setattr(gateways, "gateway_by_id", lambda _: gateway)
    requests = []

    def respond(request):
        if request.url.host != "gateway.test":
            assert fetch_enabled and vision
            assert str(request.url) == PHOTO_URLS[0]
            return photo_cdn(request)
        payload = json.loads(request.content)
        requests.append(payload)
        if len(requests) == 1:
            delta = {"tool_calls": [
                {"index": i, "id": f"call_{i}", "type": "function", "function": {
                    "name": name, "arguments": json.dumps(args),
                }} for i, (name, args) in enumerate([
                    ("kleinanzeigen_detail", {"url": AD_URL, "photo_numbers": [1, 19]}),
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
            skills={"web_search": search_enabled, "web_fetch": fetch_enabled},
        )]

    events = asyncio.run(run())
    assert events[-1]["type"] == "done", events
    names = {tool.get("function", {}).get("name") for tool in requests[0]["tools"]}
    assert ("kleinanzeigen_detail" in names) == fetch_enabled
    assert ("kleinanzeigen_search" in names) == search_enabled
    results = {msg["tool_call_id"]: msg["content"] for msg in requests[1]["messages"] if msg["role"] == "tool"}
    assert ("Kratzer" in results["call_0"]) == fetch_enabled
    assert ("Fujifilm X100V" in results["call_1"]) == search_enabled
    assert (AD_URL in "".join(event.get("text", "") for event in events)) == (fetch_enabled or search_enabled)
    last = requests[1]["messages"][-1]
    if fetch_enabled and vision:
        assert last["role"] == "user"
        assert [msg["role"] for msg in requests[1]["messages"][-4:]] == ["assistant", "tool", "tool", "user"]
        _, label, image = last["content"]
        assert label["text"].endswith("Foto 1") and image["type"] == "image_url"
        media, data = image["image_url"]["url"].split(",", 1)
        assert media == "data:image/jpeg;base64"
        assert_image(data)
        assert "Fotolimit erreicht): 19" in results["call_0"]
    else:
        assert last["role"] == "tool"
        if fetch_enabled:
            assert "kann die angeforderten Fotos nicht ansehen" in results["call_0"]


def test_web_fetch_uses_cli_for_listing(public_cli, monkeypatch):
    def unexpected_network(*args, **kwargs):
        pytest.fail("A recognized Kleinanzeigen link should be read through the CLI")

    monkeypatch.setattr(web_tool, "_check_host", unexpected_network)
    result = asyncio.run(web_tool.fetch(AD_URL))
    assert result["ok"] and "Kratzer" in result["text"]
