"""Welches Gateway und welches Modell die Bilderzeugung bekommt.

Hintergrund: Der gemeinsame Pool auf Paradies listet `gpt-image-*` neben
`gemini-*-image`. Der Gemini-Weg nahm das erste Modell mit `-image` im Namen,
also ein GPT-Modell, und `generateContent` lehnte es mit 503 ab. Den GPT-Weg
erkannte der Server gar nicht, weil der Pool keine Denkstufen meldet.
"""
import asyncio
import os
import tempfile

os.environ.setdefault("SERVER_TOKEN", "x" * 40)
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="pc-test-data-"))

import pytest  # noqa: E402

from pocket_claude import gateways  # noqa: E402

POOL_PAYLOAD = {"data": [
    {"id": "gemini-3-flash", "owned_by": "antigravity"},
    {"id": "gpt-5.6-sol", "owned_by": "openai"},
    {"id": "gpt-image-2.5-flare", "owned_by": "openai"},
    {"id": "gpt-image-2", "owned_by": "openai"},
    {"id": "gemini-3.1-flash-image", "owned_by": "antigravity"},
]}


@pytest.fixture
def pool(monkeypatch):
    gw = gateways.GatewayConfig(id="pool", label="Modell-Pool",
                                base_url="http://pool.test/v1", api_key="k")
    monkeypatch.setattr(gateways, "gateway_configs", lambda: [gw])

    async def _no_refresh(force=False, curated=True):
        return []
    monkeypatch.setattr(gateways, "list_models", _no_refresh)
    gateways._cache.clear()
    gateways._cache["pool"] = gateways._CacheEntry(
        models=gateways.normalize(gw, POOL_PAYLOAD), error=None, fetched_at=0.0,
        checked_at="", image_models=gateways.extract_image_models(POOL_PAYLOAD),
    )
    yield gw
    gateways._cache.clear()


def test_gemini_weg_nimmt_nur_gemini_bildmodelle(pool):
    gw, model = asyncio.run(gateways.image_target())
    assert gw is pool
    assert model == "gemini-3.1-flash-image"


def test_gpt_modell_als_wunsch_wird_fuer_gemini_ignoriert(pool):
    _, model = asyncio.run(gateways.image_target(preferred="gpt-image-2"))
    assert model == "gemini-3.1-flash-image"


def test_pool_mit_gpt_image_zaehlt_als_gpt_bildweg(pool):
    assert asyncio.run(gateways.gpt_image_gateway()) is pool


def test_ohne_gemini_bildmodell_kein_gemini_weg(pool):
    gateways._cache["pool"].image_models = ["gpt-image-2"]
    assert asyncio.run(gateways.image_target()) is None
    assert asyncio.run(gateways.gpt_image_gateway()) is pool
