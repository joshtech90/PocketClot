"""Behavior and security regression tests for pocket_claude.listing_media."""
from __future__ import annotations

import asyncio
import io
import os
import struct
from collections.abc import AsyncIterator

import httpx
import pytest
from PIL import Image

from pocket_claude import listing_media

VALID_URL = (
    "https://img.kleinanzeigen.de/api/v1/prod-ads/images/"
    "63/63c23c05-212f-43e7-a58b-f7d67f265c86?rule=$_57.JPG"
)
VALID_URL_ALT = (
    "https://img.kleinanzeigen.de/api/v1/prod-ads/images/"
    "aF/A1B2C3D4-E5F6-4789-ABCD-0123456789EF?rule=$_59.JPG"
)


def _make_image_bytes(
    fmt: str = "JPEG",
    size: tuple[int, int] = (64, 48),
    *,
    mode: str = "RGB",
    color: tuple[int, ...] = (40, 120, 200),
    exif_orientation: int | None = None,
    icc_profile: bytes | None = None,
) -> bytes:
    img = Image.new(mode, size, color)
    kwargs: dict[str, object] = {}
    if exif_orientation is not None:
        exif = Image.Exif()
        exif[0x0112] = exif_orientation
        exif[0x010E] = "Private Camera Note"
        kwargs["exif"] = exif.tobytes()
    if icc_profile is not None:
        kwargs["icc_profile"] = icc_profile
    buf = io.BytesIO()
    img.save(buf, format=fmt, **kwargs)
    return buf.getvalue()


def _make_animated_bytes(fmt: str) -> bytes:
    f1 = Image.new("RGB", (16, 16), (255, 0, 0))
    f2 = Image.new("RGB", (16, 16), (0, 0, 255))
    buf = io.BytesIO()
    f1.save(buf, format=fmt, save_all=True, append_images=[f2], duration=100)
    return buf.getvalue()


@pytest.fixture
def mock_cdn(monkeypatch):
    """Intercepts httpx.AsyncClient with MockTransport and records requests/options."""
    real_client = httpx.AsyncClient
    recorded: list[dict] = []
    client_kwargs: list[dict] = []

    def install(handler):
        async def async_handler(request: httpx.Request) -> httpx.Response:
            recorded.append({
                "url": str(request.url),
                "headers": dict(request.headers),
                "method": request.method,
            })
            result = handler(request)
            if asyncio.iscoroutine(result):
                return await result
            return result

        def factory(**kwargs):
            client_kwargs.append(kwargs)
            return real_client(**kwargs, transport=httpx.MockTransport(async_handler))

        monkeypatch.setattr(httpx, "AsyncClient", factory)
        return recorded, client_kwargs

    return install


def test_valid_jpeg_normalized_dimensions_decodable_and_no_metadata(mock_cdn):
    raw_jpeg = _make_image_bytes(
        "JPEG",
        size=(2400, 1200),
        exif_orientation=6,
        icc_profile=b"fake-icc-profile",
    )
    recorded, client_kwargs = mock_cdn(
        lambda req: httpx.Response(
            200,
            content=raw_jpeg,
            headers={
                "content-type": "image/jpeg; charset=binary",
                "content-length": str(len(raw_jpeg)),
            },
        )
    )

    result = asyncio.run(listing_media.fetch_photo(VALID_URL))
    assert result is not None
    assert len(result) <= listing_media.MAX_OUTPUT_BYTES
    assert len(recorded) == 1
    assert recorded[0]["headers"].get("accept-encoding") == "identity"
    assert "cookie" not in recorded[0]["headers"]
    assert "authorization" not in recorded[0]["headers"]
    assert client_kwargs[0]["verify"] is True
    assert client_kwargs[0]["trust_env"] is False
    assert client_kwargs[0]["follow_redirects"] is False

    with Image.open(io.BytesIO(result), formats=("JPEG",)) as out:
        out.load()
        assert out.format == "JPEG"
        assert out.mode == "RGB"
        # Orientation 6 transposed 2400x1200 -> 1200x2400, then long edge capped at 1568 -> 784x1568
        assert out.size == (784, 1568)
        assert "exif" not in out.info
        assert "icc_profile" not in out.info


@pytest.mark.parametrize(
    ("fmt", "mime", "mode", "color"),
    [
        ("PNG", "image/png", "RGBA", (10, 20, 30, 128)),
        ("WEBP", "image/webp", "RGB", (200, 100, 50)),
    ],
)
def test_valid_png_and_webp_normalized_to_rgb_jpeg(mock_cdn, fmt, mime, mode, color):
    raw = _make_image_bytes(fmt, size=(120, 80), mode=mode, color=color)
    mock_cdn(
        lambda req: httpx.Response(
            200,
            content=raw,
            headers={"content-type": mime, "content-encoding": "identity"},
        )
    )

    result = asyncio.run(listing_media.fetch_photo(VALID_URL_ALT))
    assert result is not None
    with Image.open(io.BytesIO(result), formats=("JPEG",)) as out:
        out.load()
        assert out.format == "JPEG"
        assert out.mode == "RGB"
        assert out.size == (120, 80)


def test_same_host_redirect_success_up_to_two_hops(mock_cdn):
    raw = _make_image_bytes("JPEG", size=(64, 48))
    hop1 = "/api/v1/prod-ads/images/ab/63c23c05-212f-43e7-a58b-f7d67f265c86?rule=$_59.JPG"
    hop2 = "https://img.kleinanzeigen.de:443/api/v1/prod-ads/images/cd/63c23c05-212f-43e7-a58b-f7d67f265c86?rule=$_57.JPG"

    calls = 0

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                302,
                headers={"location": hop1, "set-cookie": "track=evil; Path=/"},
            )
        if calls == 2:
            return httpx.Response(301, headers={"location": hop2})
        return httpx.Response(200, content=raw, headers={"content-type": "image/jpeg"})

    recorded, _ = mock_cdn(handler)
    result = asyncio.run(listing_media.fetch_photo(VALID_URL))
    assert result is not None
    assert len(recorded) == 3
    assert all("cookie" not in req["headers"] for req in recorded)


def test_more_than_two_redirects_stops_and_returns_none(mock_cdn):
    raw = _make_image_bytes("JPEG")
    calls = 0

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls <= 3:
            return httpx.Response(302, headers={"location": VALID_URL_ALT})
        return httpx.Response(200, content=raw, headers={"content-type": "image/jpeg"})

    recorded, _ = mock_cdn(handler)
    assert asyncio.run(listing_media.fetch_photo(VALID_URL)) is None
    assert len(recorded) == 3


@pytest.mark.parametrize(
    "bad_location",
    [
        "https://evil.example/api/v1/prod-ads/images/63/63c23c05-212f-43e7-a58b-f7d67f265c86?rule=$_57.JPG",
        "//evil.example/api/v1/prod-ads/images/63/63c23c05-212f-43e7-a58b-f7d67f265c86?rule=$_57.JPG",
        "http://img.kleinanzeigen.de/api/v1/prod-ads/images/63/63c23c05-212f-43e7-a58b-f7d67f265c86?rule=$_57.JPG",
        "https://img.kleinanzeigen.de/other/path.jpg",
        "/api/v1/prod-ads/images/zz/63c23c05-212f-43e7-a58b-f7d67f265c86?rule=$_57.JPG",
        "https://user:pass@img.kleinanzeigen.de/api/v1/prod-ads/images/63/63c23c05-212f-43e7-a58b-f7d67f265c86?rule=$_57.JPG",
        "https://img.kleinanzeigen.de/api/v1/prod-ads/images/63/63c23c05-212f-43e7-a58b-f7d67f265c86?rule=$_57.JPG#frag",
        "https://img.kleinanzeigen.de:8443/api/v1/prod-ads/images/63/63c23c05-212f-43e7-a58b-f7d67f265c86?rule=$_57.JPG",
    ],
)
def test_disallowed_redirects_never_requested(mock_cdn, bad_location):
    recorded, _ = mock_cdn(
        lambda req: httpx.Response(302, headers={"location": bad_location})
    )
    assert asyncio.run(listing_media.fetch_photo(VALID_URL)) is None
    assert len(recorded) == 1


@pytest.mark.parametrize(
    "bad_url",
    [
        "",
        "not a url",
        "http://img.kleinanzeigen.de/api/v1/prod-ads/images/63/63c23c05-212f-43e7-a58b-f7d67f265c86?rule=$_57.JPG",
        "https://www.kleinanzeigen.de/api/v1/prod-ads/images/63/63c23c05-212f-43e7-a58b-f7d67f265c86?rule=$_57.JPG",
        "https://img.kleinanzeigen.de.evil.com/api/v1/prod-ads/images/63/63c23c05-212f-43e7-a58b-f7d67f265c86?rule=$_57.JPG",
        "https://img.kleinanzeigen.de./api/v1/prod-ads/images/63/63c23c05-212f-43e7-a58b-f7d67f265c86?rule=$_57.JPG",
        "https://img.kleinanzeigen.de:8443/api/v1/prod-ads/images/63/63c23c05-212f-43e7-a58b-f7d67f265c86?rule=$_57.JPG",
        "https://user@img.kleinanzeigen.de/api/v1/prod-ads/images/63/63c23c05-212f-43e7-a58b-f7d67f265c86?rule=$_57.JPG",
        "https://@img.kleinanzeigen.de/api/v1/prod-ads/images/63/63c23c05-212f-43e7-a58b-f7d67f265c86?rule=$_57.JPG",
        "https://img.kleinanzeigen.de/api/v1/prod-ads/images/63/63c23c05-212f-43e7-a58b-f7d67f265c86?rule=$_57.JPG#frag",
        "https://img.kleinanzeigen.de/api/v1/prod-ads/images/63/63c23c05-212f-43e7-a58b-f7d67f265c86#",
        "https://img.kleinanzeigen.de/api/v1/prod-ads/images/63/63c23c05-212f-43e7-a58b-f7d67f265c86?rule=$_57.JPG ",
        "https://img.kleinanzeigen.de/api/v1/prod-ads/images/63/63c23c05-212f-43e7-a58b-f7d67f265c86\\?rule=$_57.JPG",
        "https://img.kleinanzeigen.de/api/v1/prod-ads/images/63/63c23c05-212f-43e7-a58b-f7d67f265c86\n",
        "https://img.kleinanzeigen.de/api/v1/prod-ads/images/634/63c23c05-212f-43e7-a58b-f7d67f265c86?rule=$_57.JPG",
        "https://img.kleinanzeigen.de/api/v1/prod-ads/images/63/not-a-uuid?rule=$_57.JPG",
        "https://img.kleinanzeigen.de/api/v1/prod-ads/images/63/63c23c05-212f-43e7-a58b-f7d67f265c86/extra?rule=$_57.JPG",
        "https://img.kleinanzeigen.de/api/v1/prod-ads/images/63/63c23c05-212f-43e7-a58b-f7d67f265c86?rule=$_57.JPG&x=1",
        VALID_URL + "A" * 500,
    ],
)
def test_invalid_urls_never_requested(mock_cdn, bad_url):
    recorded, _ = mock_cdn(lambda req: httpx.Response(200))
    assert asyncio.run(listing_media.fetch_photo(bad_url)) is None
    assert recorded == []


def test_rejects_html_spoofed_content_type_invalid_and_truncated_bytes(mock_cdn):
    png_bytes = _make_image_bytes("PNG")
    jpeg_bytes = _make_image_bytes("JPEG")
    gif_buf = io.BytesIO()
    Image.new("RGB", (8, 8), (1, 2, 3)).save(gif_buf, format="GIF")
    gif_bytes = gif_buf.getvalue()

    cases = [
        ("text/html", b"<html><body>nope</body></html>"),
        ("image/jpeg", b"<html><body>fake jpeg</body></html>"),
        ("image/jpeg", png_bytes),
        ("image/png", jpeg_bytes),
        ("image/webp", gif_bytes),
        ("application/octet-stream", jpeg_bytes),
        ("image/jpeg", b"not-an-image-at-all"),
        ("image/jpeg", jpeg_bytes[:-4]),
        ("image/png", png_bytes[: len(png_bytes) // 2]),
        ("image/webp", _make_animated_bytes("WEBP")),
        ("image/png", _make_animated_bytes("PNG")),
    ]
    for ctype, payload in cases:
        mock_cdn(
            lambda req, c=ctype, p=payload: httpx.Response(
                200, content=p, headers={"content-type": c}
            )
        )
        assert asyncio.run(listing_media.fetch_photo(VALID_URL)) is None, (ctype, len(payload))


def test_metadata_decoder_error_discards_only_the_photo(mock_cdn, monkeypatch):
    raw = _make_image_bytes("JPEG", exif_orientation=6)
    mock_cdn(lambda request: httpx.Response(200, content=raw,
                                           headers={"content-type": "image/jpeg"}))

    def corrupt_metadata(image):
        raise struct.error("corrupt EXIF data")

    monkeypatch.setattr(listing_media.ImageOps, "exif_transpose", corrupt_metadata)
    assert asyncio.run(listing_media.fetch_photo(VALID_URL)) is None


@pytest.mark.parametrize("encoding", ["gzip", "br", "deflate"])
def test_rejects_non_identity_content_encoding(mock_cdn, encoding):
    jpeg_bytes = _make_image_bytes("JPEG")
    mock_cdn(
        lambda req: httpx.Response(
            200,
            content=jpeg_bytes,
            headers={"content-type": "image/jpeg", "content-encoding": encoding},
        )
    )
    assert asyncio.run(listing_media.fetch_photo(VALID_URL)) is None


@pytest.mark.parametrize("status", [201, 204, 403, 404, 500])
def test_rejects_non_200_status(mock_cdn, status):
    jpeg_bytes = _make_image_bytes("JPEG")
    mock_cdn(
        lambda req: httpx.Response(
            status, content=jpeg_bytes, headers={"content-type": "image/jpeg"}
        )
    )
    assert asyncio.run(listing_media.fetch_photo(VALID_URL)) is None


def test_rejects_oversized_declared_content_length_without_reading_body(mock_cdn):
    class ExplodingStream(httpx.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            raise AssertionError("stream should not be read when Content-Length exceeds limit")
            yield b""

    mock_cdn(
        lambda req: httpx.Response(
            200,
            stream=ExplodingStream(),
            headers={
                "content-type": "image/jpeg",
                "content-length": str(listing_media.MAX_INPUT_BYTES + 1),
            },
        )
    )
    assert asyncio.run(listing_media.fetch_photo(VALID_URL)) is None


def test_aborts_oversized_stream_without_content_length(mock_cdn):
    chunks_yielded = 0

    class BigStream(httpx.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            nonlocal chunks_yielded
            chunk = b"x" * (256 * 1024)
            for _ in range(20):
                chunks_yielded += 1
                yield chunk

    mock_cdn(
        lambda req: httpx.Response(
            200,
            stream=BigStream(),
            headers={"content-type": "image/jpeg"},
        )
    )
    assert asyncio.run(listing_media.fetch_photo(VALID_URL)) is None
    assert chunks_yielded == 9  # 8 * 256 KiB == 2 MiB; 9th chunk crosses limit and aborts


def test_rejects_oversized_dimensions_before_decoding(mock_cdn, monkeypatch):
    monkeypatch.setattr(listing_media, "MAX_INPUT_PIXELS", 1000)
    raw = _make_image_bytes("PNG", size=(50, 50))  # 2500 pixels > 1000
    mock_cdn(
        lambda req: httpx.Response(
            200, content=raw, headers={"content-type": "image/png"}
        )
    )
    assert asyncio.run(listing_media.fetch_photo(VALID_URL)) is None


def test_slow_stream_hits_absolute_timeout(mock_cdn, monkeypatch):
    monkeypatch.setattr(listing_media, "TOTAL_TIMEOUT_SECONDS", 0.05)

    class SlowStream(httpx.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            for _ in range(20):
                await asyncio.sleep(0.02)
                yield b"abc"

    mock_cdn(
        lambda req: httpx.Response(
            200, stream=SlowStream(), headers={"content-type": "image/jpeg"}
        )
    )
    assert asyncio.run(listing_media.fetch_photo(VALID_URL)) is None


def test_cancellation_propagates(mock_cdn):
    started = asyncio.Event()

    class HangingStream(httpx.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            started.set()
            await asyncio.sleep(10)
            yield b""

    mock_cdn(
        lambda req: httpx.Response(
            200, stream=HangingStream(), headers={"content-type": "image/jpeg"}
        )
    )

    async def run() -> None:
        task = asyncio.create_task(listing_media.fetch_photo(VALID_URL))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())


def test_output_cap_steps_down_quality(mock_cdn, monkeypatch):
    # Use incompressible random RGB image so quality=85 > cap and lower quality fits
    raw_pixels = os.urandom(256 * 256 * 3)
    img = Image.frombytes("RGB", (256, 256), raw_pixels)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    png_bytes = buf.getvalue()

    monkeypatch.setattr(listing_media, "MAX_OUTPUT_BYTES", 40_000)
    mock_cdn(
        lambda req: httpx.Response(
            200, content=png_bytes, headers={"content-type": "image/png"}
        )
    )

    result = asyncio.run(listing_media.fetch_photo(VALID_URL))
    assert result is not None
    assert len(result) <= 40_000
    with Image.open(io.BytesIO(result), formats=("JPEG",)) as out:
        out.load()
        assert out.size == (256, 256)
        assert out.mode == "RGB"
