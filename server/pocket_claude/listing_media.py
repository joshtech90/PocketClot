"""Fetch and normalize public Kleinanzeigen listing photos."""
from __future__ import annotations

import asyncio
import io
import logging
import re
from urllib.parse import urlsplit

import httpx
from PIL import Image, ImageOps

log = logging.getLogger(__name__)

PHOTO_HOST = "img.kleinanzeigen.de"
MAX_URL_LENGTH = 512
MAX_REDIRECTS = 2
MAX_INPUT_BYTES = 2 * 1024 * 1024
MAX_OUTPUT_BYTES = 1_000_000
MAX_INPUT_DIMENSION = 8192
MAX_INPUT_PIXELS = 16_000_000
MAX_LONG_EDGE = 1568
TOTAL_TIMEOUT_SECONDS = 8.0

_PHOTO_PATH = re.compile(
    r"/api/v1/prod-ads/images/(?i:[0-9a-f]{2}/"
    r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})",
)
_RULE_QUERY = re.compile(r"rule=[A-Za-z0-9_$.~-]{1,64}")
_MIME_FORMAT = {"image/jpeg": "JPEG", "image/jpg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}
_REDIRECTS = {301, 302, 303, 307, 308}


def _safe_url_chars(url: str) -> bool:
    return 0 < len(url) <= MAX_URL_LENGTH and all(
        32 < ord(char) < 127 and char not in "\\#" for char in url
    )


def _allowed(url: str) -> bool:
    if not _safe_url_chars(url):
        return False
    parsed = urlsplit(url)
    return (
        parsed.scheme == "https"
        and parsed.netloc.lower() in (PHOTO_HOST, f"{PHOTO_HOST}:443")
        and _PHOTO_PATH.fullmatch(parsed.path) is not None
        and (not parsed.query or _RULE_QUERY.fullmatch(parsed.query) is not None)
    )


def _normalize(raw: bytes, image_format: str) -> bytes | None:
    try:
        with Image.open(io.BytesIO(raw), formats=(image_format,)) as photo:
            width, height = photo.size
            if (max(photo.size) > MAX_INPUT_DIMENSION or width * height > MAX_INPUT_PIXELS
                    or getattr(photo, "is_animated", False)):
                return None
            photo.verify()

        with Image.open(io.BytesIO(raw), formats=(image_format,)) as photo:
            photo.thumbnail((MAX_LONG_EDGE, MAX_LONG_EDGE), Image.Resampling.LANCZOS)
            with ImageOps.exif_transpose(photo) as oriented:
                if "A" in oriented.getbands() or "transparency" in oriented.info:
                    with oriented.convert("RGBA") as transparent:
                        rgb = Image.new("RGB", transparent.size, "white")
                        rgb.paste(transparent, mask=transparent.getchannel("A"))
                else:
                    rgb = oriented.convert("RGB")
                with rgb:
                    rgb.info.clear()
                    for quality in (85, 65, 50, 35):
                        output = io.BytesIO()
                        rgb.save(output, "JPEG", quality=quality, optimize=True)
                        if output.tell() <= MAX_OUTPUT_BYTES:
                            return output.getvalue()
    except Exception as exc:
        # Codec and metadata failures must leave the listing text usable.
        log.debug("PC_MEDIA: Bildverarbeitung abgelehnt: %s", type(exc).__name__)
    return None


async def _download(url: str) -> tuple[bytes, str] | None:
    async with httpx.AsyncClient(
        verify=True, trust_env=False, follow_redirects=False, timeout=5.0,
        headers={"Accept-Encoding": "identity", "Accept": ", ".join(_MIME_FORMAT)},
    ) as client:
        for _ in range(MAX_REDIRECTS + 1):
            if not _allowed(url):
                return None
            client.cookies.clear()
            async with client.stream("GET", url) as response:
                if response.status_code in _REDIRECTS:
                    location = response.headers.get("location", "")
                    if not _safe_url_chars(location):
                        return None
                    url = str(response.url.join(location))
                    continue
                if response.status_code != 200:
                    return None
                if response.headers.get("content-encoding", "identity").strip().lower() != "identity":
                    return None
                mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                image_format = _MIME_FORMAT.get(mime)
                size = response.headers.get("content-length")
                if image_format is None or (size is not None and not 0 < int(size) <= MAX_INPUT_BYTES):
                    return None

                data = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(data) + len(chunk) > MAX_INPUT_BYTES:
                        return None
                    data.extend(chunk)
                if data:
                    return bytes(data), image_format
                return None
    return None


async def _fetch_and_normalize(url: str) -> bytes | None:
    downloaded = await _download(url)
    if downloaded is not None:
        return await asyncio.to_thread(_normalize, *downloaded)
    return None


async def fetch_photo(url: str) -> bytes | None:
    """Return a small JPEG from the fixed photo CDN, or None on a fetch or image error."""
    try:
        return await asyncio.wait_for(_fetch_and_normalize(url), TOTAL_TIMEOUT_SECONDS)
    except (asyncio.TimeoutError, httpx.HTTPError, httpx.InvalidURL, httpx.StreamError, OSError, ValueError) as exc:
        log.info("PC_MEDIA: Fotoabruf fehlgeschlagen: %s", type(exc).__name__)
    return None
