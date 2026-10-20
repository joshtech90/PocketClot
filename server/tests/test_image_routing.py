"""Welches Gateway und welches Modell die Bilderzeugung bekommt.

Hintergrund: Der gemeinsame Pool auf Paradies listet `gpt-image-*` neben
`gemini-*-image`. Der Gemini-Weg nahm das erste Modell mit `-image` im Namen,
also ein GPT-Modell, und `generateContent` lehnte es mit 503 ab. Den GPT-Weg
erkannte der Server gar nicht, weil der Pool keine Denkstufen meldet.
"""
import asyncio
import os
import tempfile
import time

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


def test_anderes_gpt_bildmodell_reicht_nicht(pool):
    # Angefordert wird fest gpt-image-2; ein Gateway ohne dieses Modell darf
    # nicht als GPT-Bildweg gelten.
    gateways._cache["pool"].image_models = ["gpt-image-1.5", "gemini-3.1-flash-image"]
    assert asyncio.run(gateways.gpt_image_gateway()) is None


def test_codexlb_hat_vorrang_vor_gelistetem_bildmodell(monkeypatch):
    gem = gateways.GatewayConfig(id="gemini", label="G", base_url="http://g.test/v1", api_key="k")
    codex = gateways.GatewayConfig(id="gpt", label="C", base_url="http://c.test/v1", api_key="k")
    monkeypatch.setattr(gateways, "gateway_configs", lambda: [gem, codex])

    async def _no_refresh(force=False, curated=True):
        return []
    monkeypatch.setattr(gateways, "list_models", _no_refresh)
    codex_payload = {"data": [{"id": "gpt-5.6-sol", "metadata": {
        "supported_reasoning_levels": [{"effort": "high"}]}}]}
    monkeypatch.setattr(gateways, "_cache", {
        "gemini": gateways._CacheEntry([], None, 0.0, "",
                                       ["gemini-3.1-flash-image", "gpt-image-2"]),
        "gpt": gateways._CacheEntry(gateways.normalize(codex, codex_payload), None, 0.0, "", []),
    })
    assert asyncio.run(gateways.gpt_image_gateway()) is codex


# ---------- Modus "beide": Gnadenfrist erst nach dem ersten Bild ----------

def _fake_providers(monkeypatch, verhalten):
    """`verhalten`: Anbieter -> (Verzoegerung in s, Fehler oder None)."""
    from pocket_claude import image_engine

    async def order(provider, family_hint, has_refs):
        return [image_engine.PROVIDER_GEMINI, image_engine.PROVIDER_GPT], None

    async def run(kind, **kwargs):
        delay, fehler = verhalten[kind]
        await asyncio.sleep(delay)
        if fehler:
            raise image_engine.ImageGenError(fehler)
        return [image_engine.GeneratedImage(index=0, mime_type="image/png",
                                            data=b"x", text="", provider=kind)]

    monkeypatch.setattr(image_engine, "_provider_order", order)
    monkeypatch.setattr(image_engine, "_run_provider", run)
    monkeypatch.setattr(image_engine, "BOTH_GRACE_SECONDS", 0.05)
    return image_engine


def test_schneller_fehlschlag_bricht_den_anderen_anbieter_nicht_ab(monkeypatch):
    ie = _fake_providers(monkeypatch, {"gemini": (0.0, "Kontingent erschoepft"),
                                       "gpt": (0.3, None)})
    images = asyncio.run(ie.generate(prompt="Fuchs", provider=ie.PROVIDER_BOTH))
    assert [i.provider for i in images] == ["gpt"]


def test_nach_erstem_bild_nur_noch_gnadenfrist(monkeypatch):
    ie = _fake_providers(monkeypatch, {"gemini": (0.0, None), "gpt": (5.0, None)})
    images = asyncio.run(ie.generate(prompt="Fuchs", provider=ie.PROVIDER_BOTH,
                                     timeout=10))
    assert [i.provider for i in images] == ["gemini"]


def test_gnadenfrist_endet_am_gesamtzeitlimit(monkeypatch):
    ie = _fake_providers(monkeypatch, {"gemini": (0.15, None), "gpt": (5.0, None)})
    monkeypatch.setattr(ie, "BOTH_GRACE_SECONDS", 0.5)
    t0 = time.monotonic()
    asyncio.run(ie.generate(prompt="Fuchs", provider=ie.PROVIDER_BOTH, timeout=0.2))
    assert time.monotonic() - t0 < 0.4


def test_abbruch_des_aufrufers_beendet_beide_anbieter(monkeypatch):
    ie = _fake_providers(monkeypatch, {"gemini": (5.0, None), "gpt": (5.0, None)})
    gestartet: list[asyncio.Task] = []
    original = ie._run_provider

    async def merken(kind, **kwargs):
        gestartet.append(asyncio.current_task())
        return await original(kind, **kwargs)
    monkeypatch.setattr(ie, "_run_provider", merken)

    async def main():
        aufruf = asyncio.create_task(ie.generate(prompt="Fuchs", provider=ie.PROVIDER_BOTH))
        await asyncio.sleep(0.05)
        aufruf.cancel()
        with pytest.raises(asyncio.CancelledError):
            await aufruf
        assert len(gestartet) == 2
        assert all(t.done() for t in gestartet)
    asyncio.run(main())


def test_beide_scheitern_ergibt_fehler(monkeypatch):
    ie = _fake_providers(monkeypatch, {"gemini": (0.0, "weg"), "gpt": (0.01, "auch weg")})
    with pytest.raises(ie.ImageGenError):
        asyncio.run(ie.generate(prompt="Fuchs", provider=ie.PROVIDER_BOTH))
