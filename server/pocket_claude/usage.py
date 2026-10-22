"""Token-usage accounting for non-subscription auth modes.

Pro/Max subscriptions bill flat-rate, so per-token counters are not
interesting. For Anthropic-API and Bedrock modes, where each request shows
up on a real invoice, we persist daily aggregates per user.

Schema (created on first call to `ensure_schema`):

  token_usage
    user_id          TEXT    NOT NULL
    day              TEXT    NOT NULL   -- "YYYY-MM-DD"
    provider         TEXT    NOT NULL   -- "pro_max" | "api_key" | "bedrock"
    input_tokens     INTEGER NOT NULL DEFAULT 0
    output_tokens    INTEGER NOT NULL DEFAULT 0
    cache_create     INTEGER NOT NULL DEFAULT 0
    cache_read       INTEGER NOT NULL DEFAULT 0
    request_count    INTEGER NOT NULL DEFAULT 0
    PRIMARY KEY (user_id, day, provider)

The 3-tuple PK gives us cheap UPSERT-on-conflict for the common case (one
user, same day, same mode) and lets us cleanly distinguish "spent today on
Bedrock" from "spent today on Pro/Max" in mixed setups.
"""
from __future__ import annotations

import datetime as _dt
import logging

from pocket_claude.db import get_db

log = logging.getLogger(__name__)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS token_usage (
    user_id        TEXT    NOT NULL,
    day            TEXT    NOT NULL,
    provider       TEXT    NOT NULL,
    input_tokens   INTEGER NOT NULL DEFAULT 0,
    output_tokens  INTEGER NOT NULL DEFAULT 0,
    cache_create   INTEGER NOT NULL DEFAULT 0,
    cache_read     INTEGER NOT NULL DEFAULT 0,
    request_count  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, day, provider)
);
CREATE INDEX IF NOT EXISTS idx_token_usage_user_day ON token_usage(user_id, day);
"""


async def ensure_schema() -> None:
    """Create the table + index if they don't exist. Idempotent."""
    async with get_db() as db:
        await db.executescript(_SCHEMA)
        await db.commit()


async def record(
    user_id: str | None,
    provider: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_create: int = 0,
    cache_read: int = 0,
) -> None:
    """Accumulate one request's usage into today's row.

    Safe to call with zero counters (just bumps `request_count`). Silently
    no-ops on missing/None counters."""
    if user_id is None or not provider:
        return
    day = _dt.datetime.now(_dt.timezone.utc).date().isoformat()
    async with get_db() as db:
        await db.execute(
            """
            INSERT INTO token_usage
                (user_id, day, provider, input_tokens, output_tokens,
                 cache_create, cache_read, request_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(user_id, day, provider) DO UPDATE SET
                input_tokens  = input_tokens  + excluded.input_tokens,
                output_tokens = output_tokens + excluded.output_tokens,
                cache_create  = cache_create  + excluded.cache_create,
                cache_read    = cache_read    + excluded.cache_read,
                request_count = request_count + 1
            """,
            (user_id, day, provider,
             int(input_tokens or 0), int(output_tokens or 0),
             int(cache_create or 0), int(cache_read or 0)),
        )
        await db.commit()


async def stats_for(
    user_id: str | None,
    period: str = "month",
) -> dict:
    """Return aggregated usage for the given user.

    `period`:
      - "month": from first day of the current calendar month up to today
      - "all":   lifetime total

    Returns a dict with the fields `UsageStatsDto` expects (period_start,
    period_end, input_tokens, output_tokens, cache_create_tokens,
    cache_read_tokens, request_count, provider).
    """
    today = _dt.datetime.now(_dt.timezone.utc).date()
    if period == "month":
        start = today.replace(day=1).isoformat()
    else:
        start = "0000-01-01"  # effectively the beginning of time
        period = "all"
    end = today.isoformat()

    async with get_db() as db:
        cur = await db.execute(
            """
            SELECT
                COALESCE(SUM(input_tokens),  0) AS input_tokens,
                COALESCE(SUM(output_tokens), 0) AS output_tokens,
                COALESCE(SUM(cache_create),  0) AS cache_create,
                COALESCE(SUM(cache_read),    0) AS cache_read,
                COALESCE(SUM(request_count), 0) AS request_count,
                GROUP_CONCAT(DISTINCT provider)  AS providers
            FROM token_usage
            WHERE user_id = ? AND day >= ? AND day <= ?
            """,
            (user_id, start, end),
        )
        row = await cur.fetchone()

    providers = (row["providers"] or "").split(",") if row and row["providers"] else []
    if len(providers) > 1:
        provider_label = "mixed"
    elif providers:
        provider_label = providers[0]
    else:
        provider_label = ""

    return {
        "period": period,
        "period_start": start,
        "period_end": end,
        "input_tokens": int(row["input_tokens"]) if row else 0,
        "output_tokens": int(row["output_tokens"]) if row else 0,
        "cache_create_tokens": int(row["cache_create"]) if row else 0,
        "cache_read_tokens": int(row["cache_read"]) if row else 0,
        "request_count": int(row["request_count"]) if row else 0,
        "provider": provider_label,
    }
