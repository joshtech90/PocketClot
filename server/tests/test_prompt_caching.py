"""Cache-Vertrag am Gateway und stabile Standardprompts bei Folgefragen."""
import asyncio
from datetime import datetime, timezone
import json
from unittest.mock import patch

import httpx
import pytest

from pocket_claude import db, gateways, openai_engine, system_prompts
from pocket_claude.config import settings


def test_date_placeholder_does_not_change_between_minutes():
    prompts = []
    for minute in (1, 42):
        with patch("datetime.datetime") as clock:
            clock.now.return_value = datetime(2026, 11, 3, 9, minute, tzinfo=timezone.utc)
            prompts.append(system_prompts.resolve_system_prompt(
                "CUSTOM", "Heute: {{currentDateTime}} / __CURRENT_DATETIME__"))
    assert prompts == ["Heute: 2026-11-03 UTC / 2026-11-03 UTC"] * 2


@pytest.mark.parametrize("family", ["gpt", "gemini", "other"])
def test_gateway_cache_is_stable_scoped_and_usage_is_not_double_counted(
    tmp_path, monkeypatch, family,
):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    model = gateways.ChatModel(
        key="gw:test:model", gateway_id="test", gateway_label="Test",
        family=family, base_id="model", label="Test", fallback_id="model",
    )
    gateway = gateways.GatewayConfig(id="test", label="Test", base_url="https://gateway.test/v1")

    async def models(**kwargs):
        return [model]

    monkeypatch.setattr(gateways, "list_models", models)
    monkeypatch.setattr(gateways, "gateway_by_id", lambda _: gateway)
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        chunks = [
            {"choices": [{"delta": {"content": "OK"}}]},
            {"choices": [], "usage": {"prompt_tokens": 2000, "completion_tokens": 5,
                                      "prompt_tokens_details": {"cached_tokens": 1536}}},
        ]
        body = "".join("data: " + json.dumps(chunk) + "\n\n" for chunk in chunks)
        return httpx.Response(200, text=body + "data: [DONE]\n\n")

    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(
        **kwargs, transport=httpx.MockTransport(respond)))

    async def run():
        await db.init_db()
        first = await db.create_conversation(title="Cache")
        second = await db.create_conversation(title="Anderer Chat")
        events = []
        for conv in (first, first, second):
            mid = await db.add_message(conv, role="user", content="Antworte OK")
            events.append([event async for event in openai_engine.stream_reply(
                conv, mid, model_key=model.key, system_prompt="Sei kurz.",
                allow_image_tool=False, skills={"web_search": False, "web_fetch": False},
            )])
        for result in events:
            assert not any(event["type"] == "error" for event in result), result
            done = next(event for event in result if event["type"] == "done")
            assert done["tokens_in"] == 2000
            assert done["tokens_cached_read"] == 1536
        assert (await db.get_conversation(first))["total_tokens"] == 2005

    asyncio.run(run())
    if family == "gpt":
        keys = [request["prompt_cache_key"] for request in requests]
        assert keys[0] == keys[1] and keys[0] != keys[2]
        assert len(keys[0]) <= 64
    else:
        assert all("prompt_cache_key" not in request for request in requests)
