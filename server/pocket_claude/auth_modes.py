"""Multi-provider authentication for the Claude CLI subprocess.

PocketClot can talk to Claude through three different paths, selectable
per user:

  - **pro_max** — the default. Uses the OAuth token the operator created
    with `claude login`. Quota is the Pro/Max subscription.
  - **api_key** — uses an Anthropic Console API key set as
    `ANTHROPIC_API_KEY`. Bypasses OAuth completely; pay-as-you-go billing
    against the console.anthropic.com account that owns the key.
  - **bedrock** — routes the request through Amazon Bedrock with the user's
    AWS credentials. Required for organizations that want billing through
    their AWS account, and the only path that currently supports Claude
    Opus 4.7 on Bedrock-pinned model IDs.

Per-user KV settings (scope = user_id):
  claude_auth_mode         "pro_max" | "api_key" | "bedrock"
  claude_api_key           Anthropic API key (sk-ant-...)
  aws_region               e.g. us-east-1
  aws_access_key_id        AWS access key
  aws_secret_access_key    AWS secret key
  aws_session_token        Optional STS session token
  bedrock_opus_model       e.g. us.anthropic.claude-opus-5 (default)
  bedrock_sonnet_model     e.g. us.anthropic.claude-sonnet-5
  bedrock_haiku_model      e.g. us.anthropic.claude-haiku-4-5-20251001-v1:0
  bedrock_model_alias      Which model alias to pin as the primary

The translation from these settings into subprocess environment variables
is the job of `build_provider_env()`. Token usage tracking is wired up
separately (see `usage.py`).
"""
from __future__ import annotations

from typing import Iterable

from pocket_claude import db


# ─── Mode constants ─────────────────────────────────────────────────────────
MODE_PRO_MAX = "pro_max"
MODE_API_KEY = "api_key"
MODE_BEDROCK = "bedrock"
VALID_MODES = {MODE_PRO_MAX, MODE_API_KEY, MODE_BEDROCK}

# ─── KV keys ────────────────────────────────────────────────────────────────
KV_MODE = "claude_auth_mode"
KV_API_KEY = "claude_api_key"
KV_AWS_REGION = "aws_region"
KV_AWS_ACCESS_KEY_ID = "aws_access_key_id"
KV_AWS_SECRET_ACCESS_KEY = "aws_secret_access_key"
KV_AWS_SESSION_TOKEN = "aws_session_token"
KV_BEDROCK_OPUS = "bedrock_opus_model"
KV_BEDROCK_SONNET = "bedrock_sonnet_model"
KV_BEDROCK_HAIKU = "bedrock_haiku_model"
KV_BEDROCK_ALIAS = "bedrock_model_alias"  # "opus" | "sonnet" | "haiku"
# Globales Standard-Modell für Pro/Max + API-Key-Modus (voller Modell-String
# wie "claude-opus-5"; "" = automatisch). Im Bedrock-Modus ungenutzt.
KV_DEFAULT_MODEL = "claude_default_model"

# Keys that are sensitive — never returned to the client in plaintext.
SECRET_KEYS: Iterable[str] = (
    KV_API_KEY,
    KV_AWS_SECRET_ACCESS_KEY,
    KV_AWS_SESSION_TOKEN,
)

# ─── Defaults ───────────────────────────────────────────────────────────────
# Bedrock cross-region inference-profile IDs. The `us.` prefix is required for
# cross-region inference; users on other AWS regions can override these via
# the settings UI.
DEFAULT_BEDROCK_OPUS = "us.anthropic.claude-opus-5"  # ki-modelle: ok (Bedrock-Namensraum, ungenutzt)
DEFAULT_BEDROCK_SONNET = "us.anthropic.claude-sonnet-5"  # ki-modelle: ok (Bedrock-Namensraum, ungenutzt)
DEFAULT_BEDROCK_HAIKU = "us.anthropic.claude-haiku-4-5-20251001-v1:0"  # ki-modelle: ok (Bedrock-Namensraum, ungenutzt)
DEFAULT_BEDROCK_ALIAS = "opus"
DEFAULT_AWS_REGION = "us-east-1"


async def _kv(user_id: int) -> dict[str, str]:
    return await db.kv_get_all(scope=user_id)


def _mode_from(kv: dict[str, str]) -> str:
    raw = kv.get(KV_MODE)
    return raw if raw in VALID_MODES else MODE_PRO_MAX


async def get_mode(user_id: int) -> str:
    """Return the user's configured auth mode, or pro_max as fallback."""
    return _mode_from(await _kv(user_id))


async def build_provider_env(user_id: int) -> tuple[dict[str, str], str | None]:
    """Compute the subprocess env-vars + primary model id for the given user.

    Returns `(env_overrides, model_override)` where:
      - `env_overrides` is a dict of variables to inject into the
        `ClaudeAgentOptions(env=…)` block. Empty for pro_max mode.
      - `model_override` is the model id to pass as `ClaudeAgentOptions.model`,
        or None to leave the existing server-default intact. Only non-None
        for Bedrock mode (Bedrock requires pinned model IDs).

    Missing creds don't raise here — the subprocess will fail fast and the
    engine reports the error to the user.
    """
    kv = await _kv(user_id)
    mode = _mode_from(kv)

    if mode == MODE_PRO_MAX:
        return ({}, None)

    if mode == MODE_API_KEY:
        api_key = kv.get(KV_API_KEY)
        if not api_key:
            return ({}, None)
        # The CLI uses ANTHROPIC_API_KEY automatically in non-interactive
        # mode (which is how we always invoke it), no further config needed.
        return ({"ANTHROPIC_API_KEY": api_key}, None)

    if mode == MODE_BEDROCK:
        region = kv.get(KV_AWS_REGION) or DEFAULT_AWS_REGION
        akid = kv.get(KV_AWS_ACCESS_KEY_ID)
        secret = kv.get(KV_AWS_SECRET_ACCESS_KEY)
        token = kv.get(KV_AWS_SESSION_TOKEN)

        env: dict[str, str] = {
            "CLAUDE_CODE_USE_BEDROCK": "1",
            "AWS_REGION": region,
        }
        if akid:
            env["AWS_ACCESS_KEY_ID"] = akid
        if secret:
            env["AWS_SECRET_ACCESS_KEY"] = secret
        if token:
            env["AWS_SESSION_TOKEN"] = token

        # Pin model aliases so `opus`/`sonnet`/`haiku` resolve to the IDs the
        # operator picked. Per Anthropic docs (Bedrock setup, point 4):
        # without these, `opus` resolves to Opus 4.6 even when 4.7 is enabled.
        opus = kv.get(KV_BEDROCK_OPUS) or DEFAULT_BEDROCK_OPUS
        sonnet = kv.get(KV_BEDROCK_SONNET) or DEFAULT_BEDROCK_SONNET
        haiku = kv.get(KV_BEDROCK_HAIKU) or DEFAULT_BEDROCK_HAIKU
        env["ANTHROPIC_DEFAULT_OPUS_MODEL"] = opus
        env["ANTHROPIC_DEFAULT_SONNET_MODEL"] = sonnet
        env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = haiku

        alias = kv.get(KV_BEDROCK_ALIAS) or DEFAULT_BEDROCK_ALIAS
        model_override = {
            "opus": opus,
            "sonnet": sonnet,
            "haiku": haiku,
        }.get(alias, opus)

        return (env, model_override)

    return ({}, None)


def mask_secret(value: str | None) -> str:
    """Return a UI-safe masked preview of a secret (last 4 chars visible).

    `None` and empty strings come back as empty strings so the client can
    distinguish "set but hidden" from "not configured".
    """
    if not value:
        return ""
    if len(value) <= 8:
        return "•" * len(value)
    return f"{'•' * 8}{value[-4:]}"
