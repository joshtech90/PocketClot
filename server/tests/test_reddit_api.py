"""Read-only Reddit fetches, credential isolation and provider integration."""
import asyncio
import json
import os
import re
import tempfile

import httpx
import pytest

os.environ.setdefault("SERVER_TOKEN", "x" * 40)
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="pc-reddit-test-"))

from pocket_claude import reddit_api, web_tool


@pytest.fixture
def api(monkeypatch, tmp_path):
    path = tmp_path / "reddit.json"
    path.write_text(json.dumps([
        {"client_id": f"client-{i}", "client_secret": f"secret-{i}"} for i in range(3)
    ]))
    monkeypatch.setenv("REDDIT_CREDENTIALS_FILE", str(path))
    # Reload only the adapter to isolate its in-memory OAuth state.
    import importlib
    importlib.reload(reddit_api)
    real_client = httpx.AsyncClient

    def install(handler):
        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real_client(
            **kw, transport=httpx.MockTransport(handler)))
    return install


def listing():
    return {"kind": "Listing", "data": {"children": [{"kind": "t3", "data": {
        "title": "Battery life", "selftext": "Two days on one charge.", "subreddit": "Android",
        "permalink": "/r/Android/comments/abc123/battery/", "url": "https://example.org/review",
    }}]}}


@pytest.mark.parametrize("url", [
    "https://www.reddit.com/r/Android/hot",
    "https://old.reddit.com/r/Android/search.json?q=battery&restrict_sr=on",
    "https://redd.it/abc123",
])
def test_fetch_reads_posts_and_comments_via_fixed_oauth_host(api, url):
    def handler(req):
        if req.url.path == "/api/v1/access_token":
            return httpx.Response(200, json={"access_token": "access-test", "expires_in": 3600})
        assert req.method == "GET" and req.url.host == "oauth.reddit.com"
        assert req.headers["Authorization"] == "Bearer access-test"
        assert "secret-" not in str(req.url)
        return httpx.Response(200, json=[listing(), {"kind": "Listing", "data": {"children": [
            {"kind": "t1", "data": {"author": "reader", "body": "Helpful comment", "replies": ""}}
        ]}}])
    api(handler)
    result = asyncio.run(web_tool.fetch(url))
    assert result["ok"]
    assert "Battery life" in result["text"] and "Helpful comment" in result["text"]
    assert result["sources"]
    assert "access-test" not in result["text"] and "secret-" not in result["text"]


@pytest.mark.parametrize("url", [
    "https://reddit.com.evil.example/r/Android", "https://evil.example/r/Android",
    "http://127.0.0.1/", "https://user:pass@reddit.com/r/Android",
    "https://www.reddit.com:444/r/Android", "https://www.reddit.com/api/vote",
    "https://oauth.reddit.com/api/me", "https://www.reddit.com/r/../api/vote",
])
def test_rejected_routes_never_send_credentials(api, url):
    def handler(req):
        pytest.fail("Rejected URL must not cause any request")
    api(handler)
    result = asyncio.run(reddit_api.fetch(url))
    assert not result["ok"]


def test_auth_failure_uses_spare_but_rate_limit_does_not(api):
    tokens = []
    def handler(req):
        if req.url.path == "/api/v1/access_token":
            tokens.append(req.headers["Authorization"])
            if len(tokens) == 1:
                return httpx.Response(401)
            return httpx.Response(200, json={"access_token": "access-test", "expires_in": 3600})
        return httpx.Response(429, headers={"Retry-After": "30"})
    api(handler)
    async def run():
        first = await reddit_api.fetch("https://reddit.com/r/Android/hot")
        second = await reddit_api.fetch("https://reddit.com/r/Android/hot")
        assert not first["ok"] and not second["ok"]
    asyncio.run(run())
    assert len(tokens) == 2


def test_redirect_does_not_leak_token(api):
    def handler(req):
        if req.url.path == "/api/v1/access_token":
            return httpx.Response(200, json={"access_token": "access-test", "expires_in": 3600})
        assert req.url.host == "oauth.reddit.com"
        return httpx.Response(302, headers={"Location": "http://100.64.0.1/steal"})
    api(handler)
    assert not asyncio.run(reddit_api.fetch("https://reddit.com/r/Android"))["ok"]


def test_claude_fetch_uses_same_reader_and_memory_guard(api, monkeypatch):
    from pocket_claude import claude_engine
    api(lambda req: httpx.Response(200, json={"access_token": "access-test", "expires_in": 3600})
        if req.url.path == "/api/v1/access_token" else httpx.Response(200, json=listing()))
    state = {}
    server, names = claude_engine._build_image_mcp_server(
        "usr_test", None, [], asyncio.Queue(), mit_bild=False, mit_web=True,
        wissen_zustand=state)
    assert "mcp__pocket__web_fetch" in names
    hooks = claude_engine._nach_erinnern_sperren(state)
    assert re.search(hooks["PreToolUse"][0].matcher, "mcp__pocket__web_fetch")
    # Exercise the actual registered SDK tool, including the defence in depth.
    from mcp.shared.memory import create_connected_server_and_client_session
    async def run():
        async with create_connected_server_and_client_session(server["instance"]) as client:
            result = await client.call_tool("web_fetch", {"url": "https://reddit.com/r/Android"})
            assert not result.isError and "Battery life" in str(result)
            state["erinnert"] = True
            result = await client.call_tool("web_fetch", {"url": "https://reddit.com/r/Android"})
            assert result.isError and "gesperrt" in str(result) and "Battery life" not in str(result)
    asyncio.run(run())


@pytest.mark.parametrize('location', [
    '/r/Android/comments/abc123/battery/',
    'http://100.64.0.1/private',
    'https://reddit.com.evil.example/steal',
])
def test_share_link_validates_redirect_before_oauth(api, location):
    requests = []
    def handler(req):
        requests.append(req)
        if '/s/' in req.url.path:
            assert req.url.host == 'www.reddit.com'
            assert 'Authorization' not in req.headers
            return httpx.Response(302, headers={'Location': location})
        if req.url.path == '/api/v1/access_token':
            return httpx.Response(200, json={'access_token': 'access-test', 'expires_in': 3600})
        assert req.url.host == 'oauth.reddit.com'
        return httpx.Response(200, json=listing())
    api(handler)
    result = asyncio.run(web_tool.fetch('https://www.reddit.com/r/Android/s/Share123'))
    assert result['ok'] == location.startswith('/r/')
    if not result['ok']:
        assert len(requests) == 1


def test_claude_routes_only_reddit_away_from_builtin_fetch():
    from pocket_claude import claude_engine
    hook = claude_engine._reddit_nativ_sperren()['PreToolUse'][0].hooks[0]
    async def run():
        assert await hook({'tool_input': {'url': 'https://example.org/'}}, 'x', None) == {}
        blocked = await hook({'tool_input': {'url': 'https://www.reddit.com/r/Android'}}, 'x', None)
        assert blocked['hookSpecificOutput']['permissionDecision'] == 'deny'
        assert 'mcp__pocket__web_fetch' in blocked['hookSpecificOutput']['permissionDecisionReason']
    asyncio.run(run())
