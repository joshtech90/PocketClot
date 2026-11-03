"""Read-only Reddit OAuth adapter shared by all chat providers. Tokens stay in memory."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import urllib.parse
from typing import Any

import httpx

from pocket_claude.config import settings

log = logging.getLogger(__name__)

USER_AGENT = "pocket_claude:v1.0 (read-only reddit client)"
OAUTH_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
OAUTH_BASE_URL = "https://oauth.reddit.com"

MAX_RESPONSE_BYTES = 3 * 1024 * 1024  # 3 MB
GLOBAL_TIMEOUT = 40.0
MAX_OUTPUT_CHARS = 12000

ALLOWED_HOSTS = {
    "www.reddit.com",
    "old.reddit.com",
    "new.reddit.com",
    "m.reddit.com",
    "oauth.reddit.com",
    "reddit.com",
    "redd.it",
}

ALLOWED_QUERY_KEYS = {"q", "sort", "t", "after", "before", "context", "depth"}

POST_ROUTE = re.compile(
    r"/(?:r/[A-Za-z0-9_]+/)?comments/([A-Za-z0-9]+)"
    r"(?:/[^/]*)?(?:/([A-Za-z0-9]+))?/?"
)
LIST_ROUTE = re.compile(r"/r/[A-Za-z0-9_]+(?:/(?:hot|new|top|rising|search))?")


def is_reddit_url(url: str) -> bool:
    try:
        return (urllib.parse.urlsplit(url).hostname or "").lower() in ALLOWED_HOSTS
    except ValueError:
        return False


class RedditCredential:
    """Repraesentiert einen OAuth-Client ohne Secret-Exposure."""

    def __init__(self, client_id: str, client_secret: str) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token: str | None = None
        self.expires_at: float = 0.0
        self.lock = asyncio.Lock()
        self.auth_failed_until: float = 0.0

    def is_token_valid(self) -> bool:
        return bool(self.access_token and time.monotonic() < self.expires_at)

    def __repr__(self) -> str:
        return "<RedditCredential [REDACTED]>"

    def __str__(self) -> str:
        return "<RedditCredential [REDACTED]>"


_credentials_cache: list[RedditCredential] = []
_credentials_file_path: str | None = None
_credentials_file_mtime: float = -1.0
_rate_limit_cooldown_until: float = 0.0


def _get_credentials() -> list[RedditCredential]:
    """Laedt Credentials aus REDDIT_CREDENTIALS_FILE mit Invalidation bei Dateiänderung."""
    global _credentials_cache, _credentials_file_path, _credentials_file_mtime
    file_path = os.getenv("REDDIT_CREDENTIALS_FILE", settings.reddit_credentials_file)
    if not file_path:
        _credentials_cache = []
        _credentials_file_path = None
        return []

    try:
        if not os.path.isfile(file_path):
            _credentials_cache = []
            _credentials_file_path = None
            return []

        mtime = os.path.getmtime(file_path)
        if (
            file_path == _credentials_file_path
            and mtime == _credentials_file_mtime
            and _credentials_cache
        ):
            return _credentials_cache

        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, list):
            _credentials_cache = []
            return []

        new_creds: list[RedditCredential] = []
        for item in data:
            if isinstance(item, dict):
                cid = item.get("client_id")
                csec = item.get("client_secret")
                if cid and csec:
                    new_creds.append(RedditCredential(str(cid).strip(), str(csec).strip()))

        _credentials_cache = new_creds
        _credentials_file_path = file_path
        _credentials_file_mtime = mtime
        return _credentials_cache
    except Exception as exc:
        log.warning("PC_REDDIT: credential file unreadable (%s)", type(exc).__name__)
        return []


def configured() -> bool:
    """Prueft, ob gueltige Reddit-Credentials konfiguriert sind."""
    return len(_get_credentials()) > 0


def _parse_and_validate_url(raw_url: str) -> tuple[str, dict[str, str]]:
    parsed = urllib.parse.urlsplit(raw_url.strip())
    if (parsed.scheme not in ("http", "https") or parsed.username is not None
            or parsed.password is not None or parsed.port not in (None, 80, 443)
            or (parsed.hostname or "").lower() not in ALLOWED_HOSTS):
        raise ValueError("Only public Reddit URLs without credentials are allowed")
    path = parsed.path.rstrip("/")
    if path.endswith(".json"):
        path = path[:-5].rstrip("/")
    # Never pass user paths through unchanged: even a plausible comment URL
    # could contain encoded slashes or dot segments that httpx normalizes.
    if parsed.hostname == "redd.it":
        if not re.fullmatch(r"/[A-Za-z0-9]+", path):
            raise ValueError("Invalid Reddit shortlink")
        target = "/comments" + path
    elif re.fullmatch(r"/gallery/[A-Za-z0-9]+", path):
        target = "/comments/" + path.rsplit("/", 1)[1]
    elif match := POST_ROUTE.fullmatch(path):
        target = "/comments/" + match[1]
        if match[2]:
            target += "/_/" + match[2]
    elif LIST_ROUTE.fullmatch(path) or path in ("/search", "/hot", "/new", "/top", "/best", ""):
        target = path or "/hot"
    else:
        raise ValueError("Unsupported Reddit URL")
    params = {"limit": "25", "raw_json": "1", "depth": "5"}
    for key, value in urllib.parse.parse_qsl(parsed.query, max_num_fields=40):
        if key in ALLOWED_QUERY_KEYS:
            params[key] = value
    # Bound comments regardless of the supplied depth. Search within a
    # subreddit must stay inside it rather than becoming a global search.
    params["depth"] = str(max(1, min(8, int(params["depth"]))))
    if target.startswith("/r/") and target.endswith("/search"):
        params["restrict_sr"] = "on"
    return target, params


def _apply_rate_limit(headers: httpx.Headers) -> float:
    global _rate_limit_cooldown_until
    retry_after = headers.get("retry-after")
    cooldown = 60.0
    if retry_after:
        try:
            cooldown = max(float(retry_after), 1.0)
        except (ValueError, TypeError):
            pass
    _rate_limit_cooldown_until = time.monotonic() + cooldown
    return cooldown


async def _ensure_token(cred: RedditCredential, client: httpx.AsyncClient) -> bool:
    async with cred.lock:
        if cred.is_token_valid():
            return True
        if time.monotonic() < _rate_limit_cooldown_until:
            return False
        async with client.stream(
            "POST", OAUTH_TOKEN_URL, auth=(cred.client_id, cred.client_secret),
            data={"grant_type": "client_credentials", "scope": "read"},
        ) as resp:
            if resp.status_code == 429:
                _apply_rate_limit(resp.headers)
                return False
            if resp.status_code == 401:
                cred.auth_failed_until = time.monotonic() + 900
                return False
            if resp.status_code != 200:
                raise ValueError("Reddit authentication is unavailable")
            body, error = await _read_bounded_stream(resp)
        if error:
            raise ValueError(error)
        payload = json.loads(body)
        if payload.get("error") == "invalid_client":
            cred.auth_failed_until = time.monotonic() + 900
            return False
        token = payload.get("access_token")
        if not isinstance(token, str) or not token:
            raise ValueError("No OAuth token")
        cred.access_token = token
        cred.expires_at = time.monotonic() + max(float(payload.get("expires_in", 3600)) - 60, 1)
        return True


async def _read_bounded_stream(resp: httpx.Response) -> tuple[bytes | None, str | None]:
    """Liest den Response-Body gestreamt bis maximal 3 MB."""
    chunks: list[bytes] = []
    total = 0
    async for chunk in resp.aiter_bytes():
        total += len(chunk)
        if total > MAX_RESPONSE_BYTES:
            return None, "Response exceeded maximum size limit (3 MB)."
        chunks.append(chunk)
    return b"".join(chunks), None


def _format_post(data: dict[str, Any]) -> tuple[str, str | None]:
    title = str(data.get("title") or "").strip()
    subreddit = str(data.get("subreddit") or "").strip()
    selftext = str(data.get("selftext") or "").strip()
    url = str(data.get("url") or "").strip()
    permalink = str(data.get("permalink") or "").strip()

    canonical = f"https://www.reddit.com{permalink}" if permalink else None

    header = f"[r/{subreddit}] {title}" if subreddit else title
    parts = [header]
    if url and url != canonical:
        parts.append(f"Link: {url}")
    if canonical:
        parts.append(f"Permalink: {canonical}")
    if selftext:
        parts.append(f"\n{selftext}")

    return "\n".join(parts), canonical


def _format_comments(data: dict[str, Any], depth: int = 0) -> list[str]:
    author = str(data.get("author") or "[deleted]")
    body = str(data.get("body") or "").strip()
    indent = "  " * depth

    lines = [f"{indent}[u/{author}]:"]
    for line in body.splitlines():
        lines.append(f"{indent}  {line}")

    replies = data.get("replies")
    if isinstance(replies, dict) and depth < 8:
        children = replies.get("data", {}).get("children", [])
        for child in children:
            if isinstance(child, dict) and child.get("kind") == "t1":
                lines.extend(_format_comments(child.get("data", {}), depth + 1))

    return lines


def _format_payload(raw_json: Any) -> tuple[str, list[str]]:
    sources: list[str] = []
    sections: list[str] = []

    def _process_children(children: list[Any]) -> None:
        for item in children:
            if not isinstance(item, dict):
                continue
            kind = item.get("kind")
            data = item.get("data", {})
            if kind == "t3":
                formatted, canonical = _format_post(data)
                sections.append(formatted)
                if canonical and canonical not in sources:
                    sources.append(canonical)
            elif kind == "t1":
                comment_lines = _format_comments(data, depth=0)
                sections.append("\n".join(comment_lines))

    if isinstance(raw_json, list):
        for entry in raw_json:
            if isinstance(entry, dict) and entry.get("kind") == "Listing":
                _process_children(entry.get("data", {}).get("children", []))
    elif isinstance(raw_json, dict):
        if raw_json.get("kind") == "Listing":
            _process_children(raw_json.get("data", {}).get("children", []))
        elif raw_json.get("kind") == "t3":
            formatted, canonical = _format_post(raw_json.get("data", {}))
            sections.append(formatted)
            if canonical and canonical not in sources:
                sources.append(canonical)

    output = "\n\n---\n\n".join(sections).strip()
    if not output:
        output = "Keine Reddit-Beitraege gefunden."

    if len(output) > MAX_OUTPUT_CHARS:
        output = output[: MAX_OUTPUT_CHARS - 18] + "\n...[truncated]"

    return output, sources


def _failure(text: str) -> dict:
    return {"ok": False, "text": text, "sources": []}


async def fetch(url: str) -> dict:
    """Errors are tool results, never exceptions or raw provider responses."""
    try:
        return await asyncio.wait_for(_fetch_inner(url), GLOBAL_TIMEOUT)
    except (asyncio.TimeoutError, httpx.TimeoutException):
        log.warning("PC_REDDIT: request timed out")
        return _failure("Der Reddit-Abruf hat zu lange gedauert.")
    except Exception as exc:
        log.warning("PC_REDDIT: fetch failed (%s)", type(exc).__name__)
        return _failure("Reddit konnte nicht ueber die API gelesen werden. "
                        "Bitte pruefe die Adresse und versuche es spaeter erneut.")


async def _fetch_inner(url: str) -> dict:
    # Reddit's mobile share URLs redirect to a canonical post address.
    # Resolve only this fixed host without auth, then validate the destination
    # through the same strict route parser before any OAuth token is acquired.
    parsed = urllib.parse.urlsplit(url.strip())
    if (is_reddit_url(url) and re.fullmatch(r"/r/[A-Za-z0-9_]+/s/[A-Za-z0-9]+/?", parsed.path)):
        if (parsed.username is not None or parsed.password is not None
                or parsed.port not in (None, 80, 443) or parsed.scheme not in ("http", "https")):
            raise ValueError("Invalid share URL")
        async with httpx.AsyncClient(timeout=10, follow_redirects=False,
                                     headers={"User-Agent": USER_AGENT}) as client:
            async with client.stream("GET", "https://www.reddit.com" + parsed.path) as response:
                if response.status_code not in (301, 302, 303, 307, 308) or not response.headers.get("location"):
                    return _failure("Der Reddit-Teilen-Link konnte nicht aufgeloest werden. "
                                    "Bitte oeffne ihn und kopiere die vollstaendige Beitragsadresse.")
                url = urllib.parse.urljoin("https://www.reddit.com", response.headers["location"])
    target_path, params = _parse_and_validate_url(url)
    if time.monotonic() < _rate_limit_cooldown_until:
        return _failure("Reddit begrenzt die Anfragen. Bitte spaeter erneut versuchen.")
    creds = _get_credentials()
    if not creds:
        return _failure("Der Reddit-API-Zugang ist nicht eingerichtet.")
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(15, connect=8), follow_redirects=False,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        for cred in creds:
            if time.monotonic() < cred.auth_failed_until:
                continue
            # Retry an expired/revoked access token once with the same client.
            # Only authentication failures may fall back to another key.
            for attempt in range(2):
                if not await _ensure_token(cred, client):
                    if time.monotonic() < _rate_limit_cooldown_until:
                        return _failure("Reddit begrenzt die Anfragen. Bitte spaeter erneut versuchen.")
                    break
                async with client.stream(
                    "GET", OAUTH_BASE_URL + target_path, params=params,
                    headers={"Authorization": "Bearer " + cred.access_token},
                ) as resp:
                    if resp.status_code == 401:
                        cred.access_token = None
                        if attempt == 1:
                            cred.auth_failed_until = time.monotonic() + 900
                        continue
                    if resp.status_code == 429:
                        _apply_rate_limit(resp.headers)
                        return _failure("Reddit begrenzt die Anfragen. Bitte spaeter erneut versuchen.")
                    if resp.status_code != 200:
                        log.warning("PC_REDDIT: API HTTP %d", resp.status_code)
                        return _failure(f"Reddit hat mit HTTP {resp.status_code} geantwortet.")
                    body, error = await _read_bounded_stream(resp)
                if error:
                    return _failure("Die Reddit-Antwort ist zu gross.")
                text, urls = _format_payload(json.loads(body))
                canonical = "https://www.reddit.com" + target_path
                if params.get("q"):
                    canonical += "?" + urllib.parse.urlencode({"q": params["q"]})
                sources = [{"title": "Reddit", "url": u} for u in (urls or [canonical])]
                return {"ok": True, "text": text, "sources": sources}
    log.warning("PC_REDDIT: all configured clients failed authentication")
    return _failure("Keiner der eingerichteten Reddit-Zugaenge konnte sich anmelden.")
