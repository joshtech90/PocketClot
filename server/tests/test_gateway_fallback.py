"""Two gateways, saved chat keys and one retry before a reply starts."""
import asyncio
import base64
import json
import os
import ssl
import tempfile
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa

os.environ.setdefault("SERVER_TOKEN", "x" * 40)
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="pc-test-data-"))

from pocket_claude import db, gateways, image_engine, openai_engine, server, tts, web_tool
from pocket_claude.config import settings

FLASH = "gemini-3.8-flash"
HYDROGEN = "gemini-4-hydrogen"
LUNA = "gpt-luna"
OLD_FLASH = "gw:pool:gemini-flash"
NEW_FLASH = f"gw:relay:{FLASH}"
POOL = gateways.GatewayConfig("pool", "Pool", "https://pool.test/v1")
RELAY = gateways.GatewayConfig("relay", "Gemini", "https://relay.test/v1",
                               families=("gemini",), efforts=("low", "medium", "high"))


def models(config, *ids):
    return gateways.normalize(config, {"data": [{"id": mid} for mid in ids]})


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "model_allowlist", f"{FLASH},{HYDROGEN},{LUNA}")
    monkeypatch.setattr(settings, "gemini_fallback_model", "")
    monkeypatch.setattr(settings, "extra_model_last_resort", LUNA)
    monkeypatch.setattr(gateways, "_cache", {})
    monkeypatch.setattr(gateways, "_unsupported_efforts", {})


def test_config_legacy_and_new_fields(monkeypatch):
    monkeypatch.setattr(settings, "gemini_gateway_url", "https://one.test/v1/")
    monkeypatch.setattr(settings, "gpt_gateway_url", "https://two.test/v1")
    monkeypatch.setattr(settings, "gemini_gateway_key", "")
    monkeypatch.setattr(settings, "gpt_gateway_key", "")
    monkeypatch.setattr(settings, "extra_model_gateways", "")
    assert [(gw.id, gw.base_url) for gw in gateways.gateway_configs()] == [
        ("gemini", "https://one.test/v1"), ("gpt", "https://two.test/v1"),
    ]
    monkeypatch.setattr(settings, "gpt_gateway_url", settings.gemini_gateway_url)
    assert gateways.gateway_configs() == [
        gateways.GatewayConfig("pool", "Modell-Pool", "https://one.test/v1"),
    ]
    monkeypatch.setattr(settings, "extra_model_gateways", json.dumps([
        {"id": "relay", "base_url": RELAY.base_url, "label": "Gemini",
         "ca_file": "/path/to/test-ca.pem", "families": ["gemini"],
         "efforts": ["high", "low", "medium"], "timeout": 300},
        {"id": POOL.id, "base_url": POOL.base_url, "label": POOL.label},
    ]))
    relay, pool = gateways.gateway_configs()
    assert (relay.ca_file, relay.families, relay.efforts, relay.timeout) == (
        "/path/to/test-ca.pem", ("gemini",), ("low", "medium", "high"), 300,
    )
    assert pool == POOL


def test_efforts_only_fill_in_missing_gateway_metadata():
    payload = {"data": [
        {"id": FLASH},
        {"id": f"{HYDROGEN}-xhigh"},
        {"id": "gemini-lite", "metadata": {"supported_reasoning_levels": ["medium"]}},
    ]}
    offered = {m.base_id: m for m in gateways.normalize(RELAY, payload)}
    plain, variant, metadata = (offered[key] for key in (FLASH, HYDROGEN, "gemini-lite"))
    assert (plain.effort_mode, plain.default_effort) == ("reasoning_effort", "high")
    assert gateways.resolve(plain.key, "low", [plain])[1:] == (FLASH, "low")
    assert gateways.resolve(variant.key, "low", [variant])[1:] == (f"{HYDROGEN}-xhigh", "low")
    assert metadata.efforts == ["medium"]


@pytest.mark.parametrize("key,relay_ids,pool_ids,preferred,curated_ids,expected,reason", [
    (NEW_FLASH, [FLASH], [FLASH], "", [], NEW_FLASH, "exact"),
    (f"gw:pool:{FLASH}", [FLASH], [], "", [], NEW_FLASH, "same_model"),
    (OLD_FLASH, [FLASH], [], "", [], NEW_FLASH, "alias"),
    (NEW_FLASH, [], ["gemini-flash-high"], "", [], OLD_FLASH, "alias"),
    (NEW_FLASH, [], [f"{FLASH}-high"], "", [], f"gw:pool:{FLASH}", "same_model"),
    (OLD_FLASH, [HYDROGEN, "gemini-other"], [LUNA], "gemini-other", [HYDROGEN],
     "gw:relay:gemini-other", "gemini_fallback"),
    (OLD_FLASH, [HYDROGEN, "gemini-other"], [LUNA], "", [HYDROGEN],
     f"gw:relay:{HYDROGEN}", "gemini_fallback"),
    (OLD_FLASH, [], [LUNA], "", [], f"gw:pool:{LUNA}", "last_resort"),
    (OLD_FLASH, [], ["gpt-sol"], "", [], "gw:pool:gpt-sol", "last_resort"),
    (OLD_FLASH, [], [], "", [], None, None),
    ("gw:pool:gpt-unknown", [FLASH], [LUNA], "", [FLASH], None, None),
])
def test_resolution_chain(key, relay_ids, pool_ids, preferred, curated_ids, expected, reason):
    offered = models(RELAY, *relay_ids) + models(POOL, *pool_ids)
    kwargs = dict(curated=[m for m in offered if m.base_id in curated_ids],
                  gemini_fallback=preferred,
                  last_resort="gpt-sol" if "gpt-sol" in pool_ids else LUNA)
    if expected is None:
        with pytest.raises(KeyError):
            gateways.resolve_turn_model(key, offered, **kwargs)
    else:
        resolved = gateways.resolve_turn_model(key, offered, **kwargs)
        assert (resolved.model.key, resolved.reason) == (expected, reason)


def test_replacement_prefers_gateway_order():
    second = gateways.GatewayConfig("second", "Second", "https://second.test/v1")
    offered = models(second, FLASH) + models(RELAY, FLASH)
    selected = gateways.resolve_turn_model(OLD_FLASH, offered, curated=offered)
    assert selected.model.key == f"gw:second:{FLASH}"


def fake_http(monkeypatch, respond):
    real_client = httpx.AsyncClient
    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(
        **kwargs, transport=transport,
    ))


def sse(*deltas):
    return "".join(f"data: {json.dumps({'choices': [{'delta': delta}]})}\n\n"
                   for delta in deltas).encode()


def answer():
    return httpx.Response(200, content=sse({"content": "Die Antwort."}) + b"data: [DONE]\n\n")


@pytest.fixture
def setup_gateway_chat(monkeypatch):
    async def run(key, respond, *, relay_ids=(FLASH,), pool_ids=(LUNA,), effort="high"):
        monkeypatch.setattr(gateways, "gateway_configs", lambda: [RELAY, POOL])
        offered = models(RELAY, *relay_ids) + models(POOL, *pool_ids)

        async def list_models(**kwargs):
            return offered

        monkeypatch.setattr(gateways, "list_models", list_models)
        fake_http(monkeypatch, respond)
        await db.init_db()
        conv = await db.create_conversation(title="Test", chat_model=key)
        msg = await db.add_message(conv, role="user", content="Frage")
        events = [event async for event in openai_engine.stream_reply(
            conv, msg, model_key=key, effort=effort, system_prompt="Du bist Claude.",
            skills={"web_search": False, "web_fetch": False},
        )]
        return events, await db.list_messages(conv)

    return run


def test_no_gateway_model_left_returns_clear_error(setup_gateway_chat):
    def respond(request):
        pytest.fail(f"Unexpected gateway request: {request.url}")

    events, messages = asyncio.run(setup_gateway_chat(
        OLD_FLASH, respond, relay_ids=(), pool_ids=(),
    ))
    assert [e["type"] for e in events] == ["error"]
    assert "wird gerade nicht angeboten" in events[0]["message"]
    assert len(messages) == 1


@pytest.mark.parametrize("relay_ids,first_label", [((FLASH,), None), ((), "GPT-6 Luna")])
def test_notice_in_stream_database_and_live_tts(setup_gateway_chat, caplog, relay_ids, first_label):
    events, messages = asyncio.run(setup_gateway_chat(
        OLD_FLASH, lambda request: answer(), relay_ids=relay_ids,
    ))
    deltas = [e["text"] for e in events if e["type"] == "delta"]
    expected = (f"_Gemini ist gerade nicht erreichbar, {first_label} antwortet._\n\n"
                if first_label else "")
    assert deltas == ([expected] if expected else []) + ["Die Antwort."]
    assert messages[-1]["content"] == expected + "Die Antwort."
    assert OLD_FLASH in caplog.text
    assert (f"gw:pool:{LUNA}" if first_label else NEW_FLASH) in caplog.text
    if expected:
        assert tts._strip_for_tts(messages[-1]["content"]) == "Die Antwort."
        # Android may send just the line including the first newline.
        assert tts._strip_for_tts(expected.rstrip("\n") + "\n") == ""


@pytest.mark.parametrize("status,detail,should_retry", [
    (401, "bad key", True),
    (403, "permission denied", True),
    (403, "safety policy violation", False),
    (403, "SAFETY", False),
    (403, "unsupported reasoning_effort", False),
    (404, "model_not_found", True),
    (404, "unknown provider", True),
    (404, "unknown route", False),
    (429, "quota", True),
    (502, "upstream unavailable", True),
    (400, "invalid input", False),
    (422, "content_policy", False),
])
def test_retry_only_for_eligible_status(setup_gateway_chat, status, detail, should_retry):
    requested = []

    def respond(request):
        payload = json.loads(request.content)
        requested.append(payload["model"])
        if payload["model"] == FLASH:
            return httpx.Response(status, json={"error": {"status": detail, "message": detail}})
        assert "GPT-6 Luna" in payload["messages"][0]["content"]
        return answer()

    events, _ = asyncio.run(setup_gateway_chat(NEW_FLASH, respond))
    assert requested == ([FLASH, LUNA] if should_retry else [FLASH])
    assert events[-1]["type"] == ("done" if should_retry else "error")
    if should_retry:
        assert events[0]["text"].startswith("_Gemini ist gerade nicht erreichbar, ")


class InterruptedStream(httpx.AsyncByteStream):
    def __init__(self, delta):
        self.delta = delta

    async def __aiter__(self):
        if self.delta is not None:
            yield sse(self.delta)
        raise httpx.ReadTimeout("interrupted")


@pytest.mark.parametrize("delta", [
    None, {"role": "assistant"}, {"content": "Text"}, {"reasoning_content": "Denken"},
    {"tool_calls": [{"index": 0, "id": "call_1"}]}, {"refusal": "content policy"},
])
def test_retry_stops_at_first_token_or_tool_delta(setup_gateway_chat, delta):
    requested = []

    def respond(request):
        model = json.loads(request.content)["model"]
        requested.append(model)
        if model == FLASH:
            return httpx.Response(200, stream=InterruptedStream(delta))
        return answer()

    events, _ = asyncio.run(setup_gateway_chat(NEW_FLASH, respond))
    retry = delta is None or delta == {"role": "assistant"}
    assert requested == ([FLASH, LUNA] if retry else [FLASH])
    assert events[-1]["type"] == ("done" if retry else "error")


@pytest.mark.parametrize("after_text", [False, True])
def test_error_event_inside_stream_obeys_same_retry_boundary(setup_gateway_chat, after_text):
    requested = []

    def respond(request):
        model = json.loads(request.content)["model"]
        requested.append(model)
        if model == FLASH:
            prefix = sse({"content": "Text"}) if after_text else b""
            return httpx.Response(200, content=prefix +
                                  b'data: {"error":{"status":"UNAVAILABLE"}}\n\n')
        return answer()

    events, _ = asyncio.run(setup_gateway_chat(NEW_FLASH, respond))
    assert requested == ([FLASH] if after_text else [FLASH, LUNA])
    assert events[-1]["type"] == ("error" if after_text else "done")


@pytest.mark.parametrize("failure", ["connect", "tls", "timeout"])
def test_retry_on_connection_failures(setup_gateway_chat, failure):
    requested = []

    def respond(request):
        model = json.loads(request.content)["model"]
        requested.append(model)
        if model == FLASH:
            if failure == "tls":
                raise httpx.ConnectError("certificate verify failed") from ssl.SSLError()
            exc = httpx.ConnectError if failure == "connect" else httpx.ConnectTimeout
            raise exc("unavailable")
        return answer()

    events, _ = asyncio.run(setup_gateway_chat(NEW_FLASH, respond, relay_ids=(FLASH, HYDROGEN)))
    assert requested == [FLASH, LUNA]
    assert events[-1]["type"] == "done"


@pytest.mark.parametrize("second_succeeds", [True, False])
def test_model_error_tries_other_gemini_then_luna(setup_gateway_chat, second_succeeds):
    """Ein Modellfehler (429) darf ein anderes Gemini-Modell desselben Gateways
    probieren; scheitert auch das, muss Luna einspringen, laut angesagt."""
    requested = []

    def respond(request):
        model = json.loads(request.content)["model"]
        requested.append(model)
        if model == LUNA or (model == HYDROGEN and second_succeeds):
            return answer()
        return httpx.Response(429)

    events, _ = asyncio.run(setup_gateway_chat(NEW_FLASH, respond, relay_ids=(FLASH, HYDROGEN)))
    assert requested == ([FLASH, HYDROGEN] if second_succeeds else [FLASH, HYDROGEN, LUNA])
    assert events[-1]["type"] == "done"
    noticed = any(e.get("text", "").startswith("_Gemini") for e in events)
    assert noticed is (not second_succeeds)


@pytest.mark.parametrize("status", [401, 403, 502, 503, 504])
def test_gateway_level_error_skips_other_models_on_same_gateway(setup_gateway_chat, status):
    """Filter erreichbar, Dienst dahinter tot: kein zweites Gemini auf demselben
    Gateway, sondern direkt der Ersatz auf einem anderen Gateway."""
    requested = []

    def respond(request):
        model = json.loads(request.content)["model"]
        requested.append(model)
        if model == LUNA:
            return answer()
        return httpx.Response(status, json={"error": {"status": "relay", "message": "down"}})

    events, _ = asyncio.run(setup_gateway_chat(NEW_FLASH, respond, relay_ids=(FLASH, HYDROGEN)))
    assert requested == [FLASH, LUNA]
    assert events[-1]["type"] == "done"
    assert events[0]["text"].startswith("_Gemini ist gerade nicht erreichbar, ")


def test_retries_are_bounded(setup_gateway_chat):
    requested = []

    def respond(request):
        requested.append(json.loads(request.content)["model"])
        return httpx.Response(429)

    events, _ = asyncio.run(setup_gateway_chat(NEW_FLASH, respond, relay_ids=(FLASH, HYDROGEN)))
    assert requested == [FLASH, HYDROGEN, LUNA]
    assert events[-1]["type"] == "error"


def test_rejected_effort_changes_effort_on_same_model(setup_gateway_chat):
    attempted = []

    def respond(request):
        payload = json.loads(request.content)
        attempted.append((payload["model"], payload.get("reasoning_effort")))
        if len(attempted) == 1:
            return httpx.Response(400, json={"error": {"message": "Unsupported reasoning_effort"}})
        return answer()

    events, _ = asyncio.run(setup_gateway_chat(NEW_FLASH, respond, effort="low"))
    assert attempted == [(FLASH, "low"), (FLASH, "medium")]
    assert gateways.unsupported_efforts(NEW_FLASH) == {"low"}
    assert events[-1]["type"] == "done"


def test_missing_ca_reports_unreachable_and_leaves_other_gateways_available(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "extra_model_gateways", json.dumps([
        {"id": "relay", "base_url": RELAY.base_url, "ca_file": str(tmp_path / "missing.pem")},
        {"id": "pool", "base_url": POOL.base_url},
    ]))

    def respond(request):
        assert request.url.host == "pool.test"
        return httpx.Response(200, json={"data": [{"id": LUNA}]})

    fake_http(monkeypatch, respond)
    offered = asyncio.run(gateways.list_models())
    assert [m.base_id for m in offered] == [LUNA]
    relay, pool = asyncio.run(gateways.status())
    assert not relay["reachable"] and "CA-Datei fehlt" in relay["last_error"]
    assert pool["reachable"]


def test_gpt_image_prefers_first_eligible_gateway_in_extended_config(monkeypatch):
    monkeypatch.setattr(settings, "extra_model_gateways", json.dumps([
        {"id": "pool", "base_url": POOL.base_url, "families": ["gpt"]},
        {"id": "second", "base_url": "https://second.test/v1"},
    ]))

    def respond(request):
        if request.url.host == "pool.test":
            return httpx.Response(200, json={"data": [{"id": "gpt-image-2"}]})
        return httpx.Response(200, json={"data": [{
            "id": LUNA, "metadata": {"supported_reasoning_levels": ["high"]},
        }]})

    fake_http(monkeypatch, respond)
    assert asyncio.run(gateways.gpt_image_gateway()).id == "pool"


@pytest.fixture
def pinned_cert(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, "Gateway test CA")])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=1))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .sign(key, hashes.SHA256()))
    path = tmp_path / "ca.pem"
    path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return path, cert.public_bytes(serialization.Encoding.DER)


def test_tls_at_all_gateway_routes_and_two_gateway_image_routing(monkeypatch, pinned_cert):
    ca_path, cert = pinned_cert
    monkeypatch.setattr(settings, "extra_model_gateways", json.dumps([
        {"id": "relay", "base_url": RELAY.base_url, "ca_file": str(ca_path),
         "families": ["gemini"], "efforts": ["low", "medium", "high"]},
        {"id": "pool", "base_url": POOL.base_url, "ca_file": str(ca_path), "families": ["gpt"]},
    ]))
    gemini_images = ["gemini-3.1-flash-image", "gemini-3-pro-image"]
    relay_ids = [FLASH, HYDROGEN, *gemini_images, "gpt-image-2", LUNA]
    pool_ids = ["gemini-flash-high", *gemini_images, "gpt-image-2", LUNA]
    requests = []
    image_bytes = b"\x89PNG\r\n\x1a\nexample"
    encoded = base64.b64encode(image_bytes).decode()

    def respond(request):
        path = request.url.path
        host = request.url.host
        requests.append((host, path))
        if path == "/v1/models":
            ids = relay_ids if host == "relay.test" else pool_ids
            return httpx.Response(200, json={"data": [{"id": mid} for mid in ids]})
        if path == "/v1/chat/completions":
            payload = json.loads(request.content)
            assert host == "relay.test" and payload["model"] == FLASH
            assert payload["reasoning_effort"] == "high"
            if requests.count((host, path)) == 1:
                return httpx.Response(200, content=sse({"tool_calls": [{
                    "index": 0, "id": "call_1", "function": {
                        "name": web_tool.SEARCH_TOOL_NAME, "arguments": '{"query":"Licht"}',
                    },
                }]}))
            assert payload["messages"][-1]["role"] == "tool"
            assert "Treffer" in payload["messages"][-1]["content"]
            return answer()
        if path == f"/v1beta/models/{FLASH}:generateContent":
            assert host == "relay.test"
            assert json.loads(request.content)["tools"] == [{"google_search": {}}]
            return httpx.Response(200, json={"candidates": [{
                "content": {"parts": [{"text": "Treffer"}]},
                "groundingMetadata": {"groundingChunks": [
                    {"web": {"title": "Quelle", "uri": "https://example.org/quelle"}},
                ]},
            }]})
        if path == f"/v1beta/models/{gemini_images[0]}:generateContent":
            assert host == "relay.test"
            assert json.loads(request.content)["generationConfig"]["imageConfig"]["aspectRatio"] == "1:1"
            return httpx.Response(200, json={"candidates": [{"content": {"parts": [
                {"inlineData": {"mimeType": "image/png", "data": encoded}},
            ]}}]})
        if path in ("/v1/images/generations", "/v1/images/edits"):
            assert host == "pool.test"
            if path.endswith("/edits"):
                assert b'name="image"' in request.content
            return httpx.Response(200, json={"data": [{"b64_json": encoded}]})
        pytest.fail(f"Unexpected gateway request: {request.url}")

    real_client = httpx.AsyncClient

    def pinned_client(*, verify, trust_env, **kwargs):
        assert verify.check_hostname and verify.verify_mode == ssl.CERT_REQUIRED
        assert verify.get_ca_certs(binary_form=True) == [cert]
        assert not trust_env
        return real_client(**kwargs, transport=httpx.MockTransport(respond))

    monkeypatch.setattr(httpx, "AsyncClient", pinned_client)

    async def run():
        offered = await gateways.list_models(curated=False)
        assert {m.key for m in offered} == {NEW_FLASH, f"gw:relay:{HYDROGEN}", f"gw:pool:{LUNA}"}
        assert gateways._cache["relay"].image_models == gemini_images
        assert gateways._cache["pool"].image_models == ["gpt-image-2"]
        gw, model_id = await gateways.image_target()
        assert (gw.id, model_id) == ("relay", gemini_images[0])
        assert (await gateways.gpt_image_gateway()).id == "pool"
        await db.init_db()
        conv = await db.create_conversation(title="Test", chat_model=OLD_FLASH)
        msg = await db.add_message(conv, role="user", content="Frage")
        events = [e async for e in openai_engine.stream_reply(conv, msg, model_key=OLD_FLASH)]
        assert events[-1]["type"] == "done", events
        assert any("https://example.org/quelle" in e.get("text", "") for e in events)
        images = await image_engine.generate(prompt="Fuchs", aspect_ratio="1:1", provider="both")
        assert {im.provider for im in images} == {"gemini", "gpt"}
        edited = await image_engine.generate(prompt="Heller", provider="gpt", references=[
            image_engine.ReferenceImage(mime_type="image/png", data=image_bytes),
        ])
        assert edited[0].provider == "gpt"

    asyncio.run(run())
    assert set(requests) == {
        ("relay.test", "/v1/models"), ("pool.test", "/v1/models"),
        ("relay.test", "/v1/chat/completions"),
        ("relay.test", f"/v1beta/models/{FLASH}:generateContent"),
        ("relay.test", f"/v1beta/models/{gemini_images[0]}:generateContent"),
        ("pool.test", "/v1/images/generations"), ("pool.test", "/v1/images/edits"),
    }


def test_existing_chat_send_and_model_selection_endpoints(monkeypatch):
    real_client = httpx.AsyncClient
    user = {"id": "usr_test", "is_admin": False}
    monkeypatch.setitem(server.app.dependency_overrides, server.require_user, lambda: user)
    monkeypatch.setattr(gateways, "gateway_configs", lambda: [RELAY, POOL])

    def respond(request):
        if request.url.path == "/v1/models":
            mid = FLASH if request.url.host == "relay.test" else LUNA
            return httpx.Response(200, json={"data": [{"id": mid}]})
        assert request.url.host == "relay.test"
        return answer()

    fake_http(monkeypatch, respond)

    async def run():
        await db.init_db()
        cid = await db.create_conversation(title="Test", user_id=user["id"], chat_model=OLD_FLASH)
        async with real_client(transport=httpx.ASGITransport(app=server.app),
                               base_url="http://app.test") as client:
            path = f"/conversations/{cid}"
            picker = await client.get("/chat/models")
            included = await client.get("/chat/models", params={"include": OLD_FLASH})
            assert OLD_FLASH not in [m["key"] for m in picker.json()["models"]]
            assert OLD_FLASH in [m["key"] for m in included.json()["models"]]
            assert (await client.patch(path, json={"chat_model": OLD_FLASH})).status_code == 400
            arbitrary = await client.post(path + "/messages", json={
                "model": "gw:unused:gemini-unknown", "content": "Frage",
            })
            assert arbitrary.status_code == 400
            sent = await client.post(path + "/messages", json={"model": OLD_FLASH, "content": "Frage"})
            assert sent.status_code == 200 and "event: done" in sent.text, sent.text
            detail = (await client.get(path)).json()
            assert detail["chat_model"] == OLD_FLASH
            rewind = await client.post(path + "/rewind", json={
                "message_id": detail["messages"][-1]["id"], "chat_model": OLD_FLASH,
            })
            assert rewind.status_code == 400

    asyncio.run(run())
