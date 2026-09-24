"""Claude-Engine via `claude-agent-sdk` (offizielles Anthropic Python-SDK).

Architektur:
  - Auth: weiterhin über lokale Claude-Code-Anmeldung (`claude login` → OAuth-Token
    in `~/.claude/credentials.json`). Kein API-Key nötig.
  - Unter der Haube spawnt die SDK das gleiche `claude`-Binary, das wir vorher
    direkt aufgerufen haben. Die SDK gibt uns aber zwei wichtige Knöpfe an die
    Hand, die das CLI nicht hatte:
      * `system_prompt="..."` ersetzt den Claude-Code-Default KOMPLETT
        → keine Coding-Agent-Persona mehr, schlanker Prompt-Overhead
      * `setting_sources=[]` lädt keine CLAUDE.md o.ä. mehr
        → kein zusätzlicher Token-Müll aus Projekt-Configs
  - Sessions: weiterhin per `--resume <id>`-Mechanismus (über
    `ClaudeAgentOptions.resume=session_id`).
  - WebSearch standardmäßig erlaubt; Read kommt dazu wenn Anhänge dabei sind.

Anhänge: Text-Dateien werden inline in den Prompt eingebettet (gleiche Logik
wie zuvor). Bilder/PDFs werden via Read-Tool referenziert.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
from pathlib import Path
from typing import AsyncIterator

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    CLINotFoundError,
    ProcessError,
    ResultMessage,
    StreamEvent,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    query,
)

from pocket_claude import auth_modes, db, ki_modelle, usage
from pocket_claude.attachments import (
    build_prompt_text as _build_prompt_text,
    has_binary_attachments as _has_binary_attachments,
)
from pocket_claude.config import settings

log = logging.getLogger(__name__)


class _PublicClaudeError(RuntimeError):
    """Fehler, dessen Text absichtlich fuer Client und aufrufenden Code sicher ist."""


def _result_error_message(message: ResultMessage) -> str:
    """Mappt SDK-Abschlussfehler auf eine klare, sichere Nutzermeldung."""
    status = getattr(message, "api_error_status", None)
    if status == 401:
        return (
            "Claude: Die Anmeldung auf dem Server ist abgelaufen. "
            "Der Administrator muss Claude neu anmelden."
        )
    if status == 429:
        return (
            "Claude: Das Nutzungslimit ist erreicht oder der Dienst ist gerade "
            "ausgelastet. Bitte spaeter erneut versuchen."
        )
    if status in {500, 502, 503, 529}:
        return (
            f"Claude: Der Dienst ist voruebergehend nicht erreichbar (HTTP {status}). "
            "Bitte gleich noch einmal versuchen."
        )
    if status is not None:
        return f"Claude: Die Anfrage ist mit HTTP {status} fehlgeschlagen."

    subtype = (message.subtype or "").strip()
    if subtype and subtype != "success":
        return "Claude: Der Aufruf ist fehlgeschlagen."
    if message.errors:
        return "Claude: Der Aufruf ist mit einem internen Providerfehler fehlgeschlagen."
    return "Claude: Der Aufruf ist ohne weitere Fehlermeldung fehlgeschlagen."


def _process_error_client_message(exit_code: int | None, diagnostic: str) -> str:
    """Leitet aus rohen CLI-Daten nur eine feste, sichere Nutzermeldung ab."""
    normalized = diagnostic.lower()
    if "invalid api key" in normalized or "authentication" in normalized:
        return (
            "Claude: Die Anmeldung fehlt oder ist abgelaufen. "
            "Der Administrator muss Claude neu anmelden."
        )
    if "unknown option" in normalized:
        return "Claude: Die Server-Installation muss aktualisiert werden."
    if "permission" in normalized:
        return "Claude: Der Server hat den angeforderten Zugriff verweigert."
    suffix = f" (Fehlercode {exit_code})" if exit_code is not None else ""
    return f"Claude: Der Serverprozess ist fehlgeschlagen{suffix}."


# Waehlbare Claude-Modelle fuer den Modell-Picker in App und Web-UI.
# Seit 24.09.2026 aus dem Modell-Register (`ki_modelle.json`, Kopie aus dem
# Projekt AI Worker). Schluessel sind Familien (`opus`, `fable` ...), keine
# Versionsnummern: ein gespeichertes `opus` bekommt so immer die neueste
# Generation, und eine neue Generation braucht hier keine Code-Aenderung.
# Die App-Liste (`ClaudeModels.kt`) ist nur Offline-Fallback.
SELECTABLE_MODELS: list[tuple[str, str]] = ki_modelle.picker()

# Alles, was der Server als Claude-Modell akzeptiert: Familien, aktuelle und
# abgeloeste IDs. Abgeloeste muessen durch, weil Bestandschats die ID in
# `conversations.chat_model` stehen haben; sie laufen auf der neuesten
# Generation weiter (`ki_modelle.fuer_cli`).
ALLOWED_MODELS: frozenset[str] = frozenset(ki_modelle.bekannte_ids())


def is_allowed_model(key: str | None) -> bool:
    """Server-Allowlist fuer Claude: jede ID einer bekannten Familie."""
    return bool(key) and (key in ALLOWED_MODELS or ki_modelle.ist_claude_modell(key))

# Das Modell, das laeuft, wenn niemand etwas anderes sagt. Bewusst explizit:
# ohne diesen Wert entscheidet die Claude-CLI selbst, welches Modell antwortet.
DEFAULT_CLAUDE_MODEL = "opus"

# Denktiefen, die der Claude-Pfad kennt. "off" heisst: keine Steuerung, der
# CLI-Default greift.
CLAUDE_EFFORTS: list[str] = ["off", "low", "medium", "high", "xhigh", "max"]


# Slim, claude.ai-style system prompt. Fully replaces the Claude Code default
# (saves ~10K tokens per turn). Always respond in the user's language.
#
# IMPORTANT: every prompt must end with the explicit "always respond" clause
# below. The Claude Code CLI has a skip-turn shortcut intended for agentic
# runs that decides to reply with "No response requested." when the user's
# message looks like a bare statement. In a chat app that's a silent
# failure, so we forbid it.
SYSTEM_PROMPT = """You are PocketClot — a personal chat assistant the user talks \
to from their phone. Always reply in the same language the user writes in. Be friendly, \
direct, and helpful, like the Claude assistant on claude.ai. Markdown is allowed and \
renders nicely in the app; code blocks with a language hint (```kotlin etc.) are great. \
You have access to the WebSearch tool for current information and to the Read tool when \
the user attaches an image or PDF. No other tools — you are primarily a conversation \
partner, not a coding agent.

Every user message expects a substantive assistant reply — even if the message is a \
statement, observation, or single word rather than an explicit question. Never reply \
with "No response requested.", "(no reply)", or any other skip-turn placeholder. If \
you genuinely have nothing to add, briefly acknowledge and offer one relevant follow-up \
thought."""


# ---------- One-shot non-streaming Claude call ----------

async def oneshot_text(
    *,
    system_prompt: str,
    user_message: str,
    user_id: str | None = None,
    timeout_sec: float = 30.0,
    allowed_tools: list[str] | None = None,
    model: str | None = None,
) -> str:
    """Schickt EINEN Prompt an Claude, sammelt den vollen Antwort-Text und gibt
    ihn zurück. Keine Session, keine Tools (per default), kein Streaming-State.

    Nutzt den User-Auth-Kontext (Pro/Max OAuth, API-Key oder Bedrock) wenn
    `user_id` gesetzt ist; sonst läuft's gegen die Operator-Session (`claude
    login` auf dem Server). Geeignet für kurze interne Tasks wie
    Prompt-Übersetzungen, wo wir kein Conversation-State brauchen.

    Wirft `RuntimeError` bei Timeout / SDK-Fehler / leerer Antwort, damit
    der Caller das in eine sprechende UI-Meldung wickeln kann.
    """
    # Auth-Env (Bedrock-Override, API-Key-Mode etc.) wie im stream_reply
    engine_env: dict[str, str] = {}
    model_override: str | None = None
    if user_id is not None:
        provider_env, model_override = await auth_modes.build_provider_env(user_id)
        if provider_env:
            engine_env.update(provider_env)

    # Expliziter `model`-Override (z.B. günstiges Haiku für den Titel) gewinnt
    # vor dem User-Default und dem Server-Default.
    effective_model = (ki_modelle.fuer_cli(model) or model_override
                       or ki_modelle.fuer_cli(settings.claude_model or None))
    sandbox_cwd = settings.data_dir / "claude-sandbox"
    sandbox_cwd.mkdir(parents=True, exist_ok=True)

    options_kwargs: dict = dict(
        system_prompt=system_prompt,
        allowed_tools=allowed_tools or [],
        permission_mode="bypassPermissions",
        cwd=str(sandbox_cwd),
        include_partial_messages=False,
        model=effective_model,
        setting_sources=[],
        env=engine_env,
    )
    resolved_cli = settings.claude_binary or shutil.which("claude")
    if resolved_cli:
        options_kwargs["cli_path"] = resolved_cli
    options = ClaudeAgentOptions(**options_kwargs)

    text_parts: list[str] = []
    received_success_result = False

    async def _run() -> None:
        nonlocal received_success_result
        async for message in query(prompt=user_message, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock) and block.text:
                        text_parts.append(block.text)
            elif isinstance(message, ResultMessage):
                if message.is_error:
                    raise _PublicClaudeError(_result_error_message(message))
                received_success_result = True
            # SystemMessage / erfolgreiche ResultMessage / StreamEvent bleiben ungenutzt.

    try:
        await asyncio.wait_for(_run(), timeout=timeout_sec)
    except asyncio.TimeoutError as e:
        raise RuntimeError(
            f"Claude antwortete nicht innerhalb von {int(timeout_sec)}s."
        ) from e
    except _PublicClaudeError:
        raise
    except CLINotFoundError as e:
        log.error("Claude oneshot failed: error_type=CLINotFoundError")
        raise RuntimeError("Claude-CLI nicht gefunden.") from e
    except ProcessError as e:
        log.error("Claude oneshot subprocess failed: exit=%s", e.exit_code)
        raise RuntimeError("Claude-Serverprozess ist fehlgeschlagen.") from e
    except Exception as e:  # noqa: BLE001 — alle anderen Fehler weiterreichen
        log.error("Claude oneshot failed: error_type=%s", type(e).__name__)
        raise RuntimeError("Claude-Aufruf ist intern fehlgeschlagen.") from e

    if not received_success_result:
        raise RuntimeError("Claude-Aufruf endete ohne Abschlussmeldung.")

    out = "".join(text_parts).strip()
    if not out:
        raise RuntimeError("Claude lieferte einen leeren Text-Output.")
    return out


# ---------- Auto-Titel (kurz, tokenarm) ----------

# Systemprompt fürs Betiteln. Bewusst mit Beispielen, damit ein günstiges Haiku
# das 1-2-Wort-Format zuverlässig trifft.
_TITLE_SYSTEM_PROMPT = (
    "You turn a chat's first user message into an ultra-short title.\n"
    "Rules:\n"
    "- 1 to 2 words, never more.\n"
    "- Name the core topic only. No verbs, no filler, no punctuation, no quotes.\n"
    "- Same language as the message.\n"
    "Examples:\n"
    "'Wie backe ich einen Himbeerkuchen?' -> Himbeerkuchen\n"
    "'Hallo, das hier ist eine Testunterhaltung' -> Testunterhaltung\n"
    "'Can you help me debug this Python asyncio deadlock?' -> Python Asyncio\n"
    "'Schreib mir eine Mail an meinen Vermieter wegen der Heizung' -> Heizung Mail\n"
    "Reply with ONLY the title, nothing else."
)


async def _cheap_title_model(user_id: str | None) -> str | None:
    """Günstiges Modell fürs Betiteln. Pro/Max + API-Key → Haiku-Alias (die CLI
    löst ihn auf). Bedrock → konfiguriertes Bedrock-Haiku (sonst Default-Modell,
    weil ein blanker Haiku-Alias auf Bedrock ungültig wäre)."""
    if user_id is None:
        return "haiku"
    try:
        mode = await auth_modes.get_mode(user_id)
    except Exception:  # noqa: BLE001
        return "haiku"
    if mode == auth_modes.MODE_BEDROCK:
        kv = await db.kv_get_all(scope=user_id)
        return kv.get(auth_modes.KV_BEDROCK_HAIKU) or auth_modes.DEFAULT_BEDROCK_HAIKU
    return "haiku"


def _sanitize_title(raw: str) -> str:
    """Modell-Output in einen sauberen Kurztitel überführen: erste Zeile, ohne
    Anführungszeichen/Doppelpunkte, auf max. 3 Wörter / 40 Zeichen begrenzt."""
    t = (raw or "").strip().splitlines()[0] if raw and raw.strip() else ""
    t = t.strip().strip('"\'`').strip()
    # Ein evtl. mitgeliefertes „Titel:"/„Title:" abschneiden.
    if ":" in t and len(t.split(":", 1)[0]) <= 10:
        t = t.split(":", 1)[1].strip()
    # Nachlaufende Satzzeichen weg.
    t = t.rstrip(".!?,;:").strip()
    # Sicherheitsnetz gegen ein ganzes Satz-Output: harte Wort-/Längen-Grenze.
    words = t.split()
    if len(words) > 3:
        words = words[:3]
    t = " ".join(words)
    if len(t) > 40:
        t = t[:40].rstrip()
    return t


def _fallback_title(first_user_message: str) -> str:
    """Fallback wenn die LLM-Betitelung scheitert: erste Zeile gekürzt (das alte
    Verhalten), damit ein Chat NIE ohne Titel bleibt."""
    t = first_user_message.strip().split("\n")[0].strip()
    if len(t) > 60:
        t = t[:57] + "…"
    return t


async def generate_conversation_title(
    cid: str, first_user_message: str, user_id: str | None = None,
) -> str | None:
    """Erzeugt EINEN kurzen Titel (1-2 Wörter) aus der ersten User-Nachricht und
    speichert ihn — aber nur, wenn der Chat noch den Default-Titel „Neuer Chat"
    trägt. Günstiges Haiku, gedeckelter Input. Bei Fehlern greift der
    Erste-Zeile-Fallback. Returnt den gesetzten Titel oder None (kein Rename)."""
    conv = await db.get_conversation(cid, user_id=user_id)
    if not conv or conv["title"] != "Neuer Chat":
        return None
    snippet = (first_user_message or "").strip()
    if not snippet:
        return None
    # Token-Deckel: fürs Thema reicht der Anfang der Nachricht.
    snippet = snippet[:600]

    title = ""
    try:
        model = await _cheap_title_model(user_id)
        raw = await oneshot_text(
            system_prompt=_TITLE_SYSTEM_PROMPT,
            user_message=snippet,
            user_id=user_id,
            timeout_sec=15.0,
            model=model,
        )
        title = _sanitize_title(raw)
    except Exception as exc:  # noqa: BLE001 — nie den Chat-Flow blockieren
        log.info(
            "PC_TITLE: LLM-Titel fehlgeschlagen; error_type=%s; Fallback",
            type(exc).__name__,
        )

    if not title:
        title = _fallback_title(first_user_message)
    if not title:
        return None

    # Race-Schutz (BR-027): atomarer Compare-and-Set — der Titel wird NUR
    # gesetzt, wenn der Chat DB-seitig noch exakt „Neuer Chat" heisst. Während
    # des LLM-await oben kann der User manuell umbenannt haben; ein erneutes
    # Re-Read wäre weiterhin racy, deshalb macht das WHERE-Prädikat die
    # Bedingung Teil des UPDATE selbst.
    changed = await db.set_title_if_default(
        cid, title, expected="Neuer Chat", user_id=user_id,
    )
    if not changed:
        # Manueller Rename hat gewonnen → NICHT überschreiben und KEIN
        # SSE-title-Event auslösen (Caller schickt es nur bei Rückgabe != None).
        log.info("PC_TITLE: cid=%s auto-title verworfen (manueller Rename gewann)", cid)
        return None
    log.info("PC_TITLE: cid=%s title=%r", cid, title)
    return title


# ---------- Verlaufs-Wiedergabe ----------

# So viele Zeichen darf der mitgelieferte Verlauf hoechstens haben. 120.000
# Zeichen sind grob 30.000 Tokens, das passt bequem neben eine lange Antwort.
MAX_TRANSCRIPT_CHARS = 120_000


def _format_transcript(all_msgs: list[dict], current_user_message_id: int) -> str:
    """Baut aus den DB-Nachrichten einen lesbaren Verlauf fuer den Prompt.

    Die aktuelle User-Nachricht bleibt draussen, die steht separat im Prompt.
    Gekuerzt wird von vorne, damit die juengsten Turns erhalten bleiben.
    """
    lines: list[str] = []
    for m in all_msgs:
        if m["id"] == current_user_message_id:
            break
        text = (m.get("content") or "").strip()
        if not text:
            continue
        role = m.get("role")
        who = {"user": "Nutzer", "assistant": "Assistent"}.get(role, "System")
        lines.append(f"{who}: {text}")
    if not lines:
        return ""

    out = "\n\n".join(lines)
    if len(out) > MAX_TRANSCRIPT_CHARS:
        out = out[-MAX_TRANSCRIPT_CHARS:]
        # Nicht mitten in einer Zeile anfangen.
        cut = out.find("\n\n")
        if cut > 0:
            out = out[cut + 2:]
        out = ("[Aeltere Teile des Verlaufs wurden aus Platzgruenden "
               "weggelassen.]\n\n" + out)
    return out


# ---------- Bild-Werkzeug fuer den Claude-Pfad ----------

def _build_image_mcp_server(user_id: str | None, image_defaults: dict | None,
                            collected: list[dict], events: "asyncio.Queue"):
    """Registriert `generate_image` als In-Process-MCP-Werkzeug.

    Die Claude-Agent-SDK kann Werkzeuge direkt im Server-Prozess ausfuehren, ohne
    dass ein externer MCP-Prozess noetig waere. Wir nutzen das, damit Claude
    dieselbe Bilderzeugung bekommt wie die Zusatz-Modelle (die es ueber ihr
    natives Function-Calling ansprechen).

    Rueckgabe: (mcp_server, tool_name) oder (None, None), wenn die SDK das nicht
    kann. Ein Fehler hier darf den Chat nie kippen.
    """
    if user_id is None:
        return None, None
    try:
        from claude_agent_sdk import create_sdk_mcp_server, tool

        from pocket_claude import image_tool as _image_tool
    except ImportError as exc:
        log.warning("PC_IMG: Bild-Werkzeug nicht verfuegbar: %s", exc)
        return None, None

    @tool(_image_tool.TOOL_NAME, _image_tool.TOOL_DESCRIPTION, _image_tool.PARAMETERS)
    async def _generate_image(args: dict) -> dict:
        result = await _image_tool.run(user_id, args or {}, image_defaults or {})
        atts = result.get("attachments") or []
        if result.get("ok") and atts:
            collected.extend(atts)
            # Der Stream-Loop pollt die Queue und schiebt daraus das
            # `image`-Event raus, damit das Bild sofort in der App auftaucht.
            events.put_nowait({"type": "image", "attachments": atts})
        return {"content": [{"type": "text", "text": result.get("text") or ""}]}

    try:
        server = create_sdk_mcp_server(
            name="pocket", version="1.0.0", tools=[_generate_image],
        )
    except Exception as exc:  # noqa: BLE001 - SDK-Version passt nicht, dann eben ohne
        log.warning("PC_IMG: MCP-Server konnte nicht gebaut werden: %s", exc)
        return None, None
    return server, f"mcp__pocket__{_image_tool.TOOL_NAME}"


# ---------- Streaming via claude-agent-sdk ----------

async def stream_reply(
    cid: str,
    user_message_id: int,
    effort: str = "high",
    system_prompt: str | None = None,
    skills: dict | None = None,
    user_id: str | None = None,
    default_model: str | None = None,
    extra_attachment_ids: list[str] | None = None,
    replay_history: bool = False,
    image_defaults: dict | None = None,
) -> AsyncIterator[dict]:
    """Yieldet SSE-kompatible Events:
      - {"type": "delta", "text": "..."}
      - {"type": "done", "assistant_message_id": int, "tokens_in": int,
         "tokens_out": int, "tokens_cached_read": int, "tokens_cached_write": int}
      - {"type": "error", "message": str}

    `user_id` enables per-user auth-mode resolution (Pro/Max OAuth vs.
    direct API key vs. AWS Bedrock). When None, falls back to the operator's
    `claude login` session (Pro/Max).
    """
    # Defensiv vor-initialisieren — falls eine frühe Exception (DB-Lookup-
    # Fehler etc.) in den `except ProcessError`-Branch fällt, wo wir
    # `session_id` lesen, hätten wir sonst einen NameError.
    session_id: str | None = None
    log.info("PC_SSE: stream_reply START cid=%s user_msg_id=%s effort=%s user_id=%s",
             cid, user_message_id, effort, user_id)
    try:
        conv = await db.get_conversation(cid, user_id=user_id)
        if not conv:
            yield {"type": "error", "message": "Konversation nicht gefunden."}
            return

        all_msgs = await db.list_messages(cid)
        user_msg = next((m for m in all_msgs if m["id"] == user_message_id), None)
        if not user_msg:
            yield {"type": "error", "message": "User-Message in DB nicht gefunden."}
            return

        # Anhänge laden für Inline-Einbettung. Gem-Wissensdateien
        # (extra_attachment_ids) werden zusätzlich an JEDE Nachricht des
        # Gem-Chats gehängt — Text inline, Binär per Read-Tool.
        own_ids = user_msg.get("attachment_ids") or []
        own_set = set(own_ids)
        gem_ids = [x for x in (extra_attachment_ids or []) if x not in own_set]
        attach_ids = own_ids + gem_ids
        attachments = await db.get_attachments(attach_ids) if attach_ids else []
        attachments_by_id = {a["id"]: a for a in attachments}

        # Prompt-Bau über die kombinierte ID-Liste (user_msg trägt nur die
        # eigenen Anhänge des Nutzers).
        msg_for_prompt = {**user_msg, "attachment_ids": attach_ids}
        prompt = _build_prompt_text(msg_for_prompt, attachments_by_id)
        need_read_tool = _has_binary_attachments(attach_ids, attachments_by_id)
        session_id = conv.get("claude_session_id")

        # Ohne Session kennt Claude den Chat nicht. Das passiert in zwei Faellen:
        # der User hat zwischendurch mit einem Zusatz-Modell geschrieben, oder
        # die Session ist verloren gegangen. In beiden Faellen bekommt Claude
        # den bisherigen Verlauf als Textblock mitgeliefert, sonst antwortet es
        # ins Leere.
        if replay_history and not session_id:
            transcript = _format_transcript(all_msgs, user_message_id)
            if transcript:
                prompt = (
                    "<bisheriger_verlauf>\n"
                    f"{transcript}\n"
                    "</bisheriger_verlauf>\n\n"
                    "<aktuelle_nachricht>\n"
                    f"{prompt}\n"
                    "</aktuelle_nachricht>"
                )
                log.info("PC_SESSION: cid=%s Verlauf mitgeliefert (%d Zeichen)",
                         cid, len(transcript))

        # Skills → allowed_tools.
        # Caller (server.py /messages-Endpoint) reicht ein dict mit den
        # SkillsDto-Feldern durch. Fehlende oder None → Server-Defaults
        # (WebSearch/WebFetch on, Bash off).
        sk = skills or {}
        allowed_tools: list[str] = []
        if sk.get("web_search", True):
            allowed_tools.append("WebSearch")
        if sk.get("web_fetch", True):
            allowed_tools.append("WebFetch")
        if sk.get("code_execution", False):
            # Server-side veto: even if the client requested Bash, drop it
            # unless the operator explicitly opted in via ALLOW_BASH=1 in
            # .env. Without this, any app user could run arbitrary commands
            # as the pocket-claude system user.
            if settings.allow_bash:
                allowed_tools.append("Bash")
            else:
                log.warning(
                    "Bash requested by client but blocked by server policy "
                    "(ALLOW_BASH=false). Set ALLOW_BASH=1 in .env to enable."
                )
        if need_read_tool:
            allowed_tools.append("Read")

        # Bild-Werkzeug. Laeuft als In-Process-MCP-Server, damit Claude im Chat
        # dieselben Bilder erzeugen kann wie die Zusatz-Modelle.
        image_attachments: list[dict] = []
        image_events: asyncio.Queue = asyncio.Queue()
        mcp_servers: dict = {}
        if sk.get("image_generation", True):
            img_server, img_tool_name = _build_image_mcp_server(
                user_id, image_defaults, image_attachments, image_events,
            )
            if img_server is not None and img_tool_name:
                mcp_servers["pocket"] = img_server
                allowed_tools.append(img_tool_name)

        log.info("Skills enabled → allowed_tools: %s", allowed_tools)

        # Sandbox cwd so Claude Code (even if setting_sources had leaks)
        # doesn't pick up any project CLAUDE.md. We place it under the
        # data directory because systemd's PrivateTmp=true would otherwise
        # hide it from the subprocess — the data dir is explicitly granted
        # ReadWritePaths in the service unit.
        sandbox_cwd = settings.data_dir / "claude-sandbox"
        sandbox_cwd.mkdir(parents=True, exist_ok=True)

        # Effort-Level für Thinking via Env-Var an den Subprocess weitergeben.
        # Issue #7840: im headless Mode wird Thinking trotz aller Flags nicht
        # im Stream angezeigt — aber das Modell denkt. Effort steuert die Tiefe.
        # SDK-Werte: low, medium, high, xhigh, max. "off" → wir setzen die Var
        # nicht (CLI-Default greift). `xhigh` ist Opus-4.7-only, fällt auf
        # anderen Modellen auf `high` zurück; wir laufen auf Opus 4.7, also
        # ist es bei uns ein echtes Extra-Level.
        valid_efforts = {"low", "medium", "high", "xhigh", "max"}
        eff = (effort or "").lower().strip()
        engine_env: dict = {}
        if eff in valid_efforts:
            engine_env["CLAUDE_CODE_EFFORT_LEVEL"] = eff
            log.info("CLAUDE_CODE_EFFORT_LEVEL=%s", eff)
        elif eff and eff != "off":
            log.warning("Unbekanntes effort=%r, ignoriert", effort)

        # Multi-provider auth: load the user's configured auth mode and inject
        # the right env vars (ANTHROPIC_API_KEY for direct-API mode, or
        # CLAUDE_CODE_USE_BEDROCK=1 + AWS creds for Bedrock). Pro/Max OAuth is
        # the default and needs no extra env.
        model_override: str | None = None
        if user_id is not None:
            provider_env, model_override = await auth_modes.build_provider_env(user_id)
            if provider_env:
                engine_env.update(provider_env)
                mode = await auth_modes.get_mode(user_id)
                log.info("Auth-mode=%s, %d env override(s)", mode, len(provider_env))

        # System-Prompt: kommt von der App; Fallback ist unser kurzer Default.
        sp = (system_prompt or "").strip() or SYSTEM_PROMPT
        log.info(
            "SystemPrompt: %s (%d chars)",
            "App-supplied" if (system_prompt or "").strip() else "Server-Default",
            len(sp),
        )

        # Modell-Kette:
        #   1. model_override  → Bedrock-Pin (build_provider_env), gewinnt im
        #      Bedrock-Modus immer (eigener IDs-Namespace).
        #   2. default_model   → globales User-Standard-Modell bzw. Gem-Modell
        #      (Pro/Max + API-Key), z.B. "opus".
        #   3. settings.claude_model → Server-Default aus der .env.
        #   4. DEFAULT_CLAUDE_MODEL → das aktuelle Alltagsmodell.
        #
        # Frueher endete die Kette bei None und damit beim CLI-Default. Das war
        # unsichtbar versionsabhaengig: nach einem CLI-Update konnte ploetzlich
        # ein anderes Modell antworten, ohne dass sich in der App etwas aenderte.
        # Alles ausser dem Bedrock-Pin geht als Kurzname an die CLI; eine
        # gespeicherte Alt-ID (claude-opus-5) wird dabei auf die aktuelle
        # Generation angehoben. Der Bedrock-Pin hat eigene IDs, bleibt roh.
        effective_model = (
            model_override
            or ki_modelle.fuer_cli(default_model or None)
            or ki_modelle.fuer_cli(settings.claude_model or None)
            or DEFAULT_CLAUDE_MODEL
        )
        log.info(
            "PC_RESOLVE: model bedrock=%s default=%s server=%s effective=%s",
            model_override, default_model, settings.claude_model, effective_model,
        )

        # Without a stderr callback the SDK lets the CLI subprocess inherit
        # our stderr (-> systemd journal) and synthesises a useless
        # `stderr="Check stderr output for details"` on ProcessError. The most
        # important failure mode we need to surface — "No conversation found
        # with session ID: …" when a `--resume` references an unknown session
        # — is written to *stderr* by the CLI, so we MUST capture it here to
        # drive the auto-recovery below.
        cli_stderr_lines: list[str] = []
        def _capture_stderr(line: str) -> None:
            cli_stderr_lines.append(line)

        # Permission mode: bypassPermissions skips per-tool prompts, which is
        # what we want for the read-only tools (WebSearch / WebFetch / Read).
        # The only way "destructive" tools reach this point is if the operator
        # set ALLOW_BASH=1 AND the user opted in per-chat — at that point the
        # operator has accepted the risk explicitly, so we still bypass to
        # avoid hanging on prompts the headless mode can't answer.
        options_kwargs: dict = dict(
            system_prompt=sp,
            allowed_tools=allowed_tools,
            permission_mode="bypassPermissions",
            cwd=str(sandbox_cwd),
            include_partial_messages=True,
            resume=session_id,
            model=effective_model,
            setting_sources=[],
            env=engine_env,
            stderr=_capture_stderr,
        )
        if mcp_servers:
            options_kwargs["mcp_servers"] = mcp_servers
        # cli_path: global installiertes `claude` (Dein Login + Sessions) statt SDK-Bundle
        resolved_cli = settings.claude_binary or shutil.which("claude")
        if resolved_cli:
            options_kwargs["cli_path"] = resolved_cli

        options = ClaudeAgentOptions(**options_kwargs)

        log.info(
            "SDK-query: %s [tools: %s]",
            f"resume {session_id[:8]}…" if session_id else "(neue Session)",
            ", ".join(allowed_tools),
        )

        # Streaming-Loop
        full_text_parts: list[str] = []
        new_session_id: str | None = None
        input_tokens = 0
        output_tokens = 0
        cache_read = 0
        cache_write = 0
        # Persistenter Akkumulator über alle Messages: ein partielles
        # ResultMessage-Feld (z.B. output_tokens=None) darf einen bereits aus
        # AssistantMessage gelesenen Wert NICHT auf 0 zurücksetzen.
        usage_acc: dict = {}
        emitted_via_stream = False
        received_success_result = False

        async for message in query(prompt=prompt, options=options):
            # Vom Bild-Werkzeug erzeugte Events sofort rausschieben, damit das
            # Bild in der App erscheint, sobald es fertig ist, und nicht erst
            # wenn Claude seinen Text zu Ende geschrieben hat.
            while not image_events.empty():
                yield image_events.get_nowait()

            # Session-ID aus jedem Event abfischen (Init, Stream, Result haben sie)
            sid = getattr(message, "session_id", None)
            if sid:
                new_session_id = sid

            if isinstance(message, SystemMessage):
                # Init: enthält Modell, Tools, Cwd etc. — wir loggen nur das Modell
                if message.subtype == "init" and isinstance(message.data, dict):
                    mdl = message.data.get("model")
                    if mdl:
                        log.info("Modell: %s", mdl)

            elif isinstance(message, StreamEvent):
                # Token-Deltas — text_delta wird die Antwort, thinking_delta
                # ist die summarized Reasoning-Spur (display="summarized" oben).
                # Beide leiten wir an die App durch; die App entscheidet via
                # Setting, ob das Thinking angezeigt wird.
                ev = message.event or {}
                etype_inner = ev.get("type")
                if etype_inner == "content_block_delta":
                    delta = ev.get("delta") or {}
                    delta_type = delta.get("type")
                    if delta_type == "text_delta":
                        text = delta.get("text", "")
                        if text:
                            full_text_parts.append(text)
                            emitted_via_stream = True
                            yield {"type": "delta", "text": text}
                    elif delta_type == "thinking_delta":
                        thinking_text = delta.get("thinking", "")
                        if thinking_text:
                            log.debug("thinking_delta: %r", thinking_text[:80])
                            yield {"type": "thinking_delta", "text": thinking_text}
                    # signature_delta etc. → ignoriert
                elif etype_inner == "content_block_start":
                    block = ev.get("content_block") or {}
                    btype = block.get("type")
                    log.info("Stream-Block start: type=%s", btype)
                elif etype_inner == "content_block_stop":
                    yield {"type": "block_stop"}

            elif isinstance(message, AssistantMessage):
                # Diagnose: was für Content-Blöcke kommen rein?
                block_types = [type(b).__name__ for b in message.content]
                if block_types:
                    log.info("AssistantMessage block types: %s", block_types)
                # Falls Stream-Events nicht greifen, Volltext nachholen.
                if not emitted_via_stream:
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            text = block.text
                            if text:
                                full_text_parts.append(text)
                                yield {"type": "delta", "text": text}
                        elif isinstance(block, ThinkingBlock):
                            # Falls aus irgendeinem Grund thinking nicht über
                            # Stream-Events kommt, dann mal hier abgreifen:
                            thinking_str = getattr(block, "thinking", "") or ""
                            if thinking_str:
                                log.info("ThinkingBlock im AssistantMessage: %d chars", len(thinking_str))
                                yield {"type": "thinking_delta", "text": thinking_str}
                # Usage-Stats von AssistantMessage auch ablesen (ResultMessage hat sie
                # nochmal, aber je nach SDK-Version kann eines davon None sein)
                _accumulate_usage(message.usage, usage_acc)
                input_tokens = usage_acc.get("input_tokens", input_tokens)
                output_tokens = usage_acc.get("output_tokens", output_tokens)
                cache_read = usage_acc.get("cache_read", cache_read)
                cache_write = usage_acc.get("cache_write", cache_write)

            elif isinstance(message, ResultMessage):
                # Final stats — autoritativ wenn vorhanden
                if message.usage:
                    _accumulate_usage(message.usage, usage_acc)
                    input_tokens = usage_acc.get("input_tokens", input_tokens)
                    output_tokens = usage_acc.get("output_tokens", output_tokens)
                    cache_read = usage_acc.get("cache_read", cache_read)
                    cache_write = usage_acc.get("cache_write", cache_write)
                if message.is_error:
                    log.error(
                        "Claude ResultMessage error: subtype=%s api_status=%s "
                        "stop_reason=%s errors_count=%d result_len=%d "
                        "assistant_text_len=%d stderr_len=%d",
                        message.subtype,
                        getattr(message, "api_error_status", None),
                        message.stop_reason,
                        len(message.errors or []),
                        len(message.result or ""),
                        sum(len(part) for part in full_text_parts),
                        sum(len(line) for line in cli_stderr_lines),
                    )
                    yield {"type": "error", "message": _result_error_message(message)}
                    return
                received_success_result = True

        while not image_events.empty():
            yield image_events.get_nowait()

        if not received_success_result:
            log.error(
                "Claude stream ended without ResultMessage: assistant_text_len=%d "
                "generated_images=%d session_received=%s",
                sum(len(part) for part in full_text_parts),
                len(image_attachments),
                bool(new_session_id),
            )
            yield {
                "type": "error",
                "message": (
                    "Claude: Die Antwort wurde ohne Abschlussmeldung unterbrochen. "
                    "Bitte erneut versuchen."
                ),
            }
            return

        full_text = "".join(full_text_parts).strip()

        # Skip-turn guard. Claude Code's headless mode sometimes replies
        # with a short placeholder when it thinks no response is needed
        # (intended for agentic runs, not chat). Detect those and surface
        # an error to the app instead of saving a useless message.
        #
        # Match is intentionally narrow: only exact (case-/punctuation-
        # normalized) matches qualify, no prefix match. A legitimate reply
        # that happens to start with "(skip)" stays valid.
        SKIP_TURN_SENTINELS = {
            "no response requested",
            "(no reply)",
            "(skip)",
            "(no response)",
        }
        normalized = full_text.lower().rstrip(".").strip()
        # Ein reiner Bild-Turn ohne Begleittext ist eine legitime Antwort.
        is_skip_turn = (
            not image_attachments
            and (not full_text or normalized in SKIP_TURN_SENTINELS)
        )
        if is_skip_turn:
            log.warning(
                "Skip-turn / empty reply detected (text=%r). Surfacing error to client.",
                full_text[:80],
            )
            yield {
                "type": "error",
                "message": (
                    "Claude returned an empty / skip-turn reply. This is a "
                    "Claude Code CLI optimization for agentic runs that "
                    "doesn't fit chat. Try rephrasing your message as a "
                    "question, or re-send to retry."
                ),
            }
            return

        current_context = input_tokens + output_tokens + cache_read + cache_write

        if new_session_id and new_session_id != session_id:
            await db.set_claude_session_id(cid, new_session_id)

        msg_id = await db.add_message(
            cid,
            role="assistant",
            content=full_text,
            tokens=current_context,
            attachment_ids=[a["id"] for a in image_attachments] or None,
        )
        await db.set_total_tokens(cid, current_context)

        # Persist this turn's token usage if we have a user. Pro/Max calls
        # still flow through here so the operator can see the same chart for
        # all three modes — the UI just labels "pro_max" vs "billed" usage.
        if user_id is not None:
            try:
                mode = await auth_modes.get_mode(user_id)
                await usage.record(
                    user_id=user_id,
                    provider=mode,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cache_create=cache_write,
                    cache_read=cache_read,
                )
            except Exception as e:  # noqa: BLE001
                # Usage tracking must never break the user's chat reply.
                log.warning("usage.record failed: error_type=%s", type(e).__name__)

        log.info("PC_SSE: stream_reply ABOUT TO YIELD done cid=%s msg_id=%s "
                 "in=%d out=%d cr=%d cw=%d full_text_len=%d",
                 cid, msg_id, input_tokens, output_tokens,
                 cache_read, cache_write, len(full_text))
        yield {
            "type": "done",
            "assistant_message_id": msg_id,
            "tokens_in": input_tokens,
            "tokens_out": output_tokens,
            "tokens_cached_read": cache_read,
            "tokens_cached_write": cache_write,
        }
        log.info("PC_SSE: stream_reply YIELDED done cid=%s msg_id=%s", cid, msg_id)

    except CLINotFoundError as exc:
        log.error("Claude-CLI nicht gefunden; error_type=%s", type(exc).__name__)
        yield {
            "type": "error",
            "message": (
                "Claude-CLI nicht gefunden. Stelle sicher dass `claude` im PATH liegt "
                "(`which claude`). Ggf. CLAUDE_BINARY in .env auf den Pfad setzen."
            ),
        }
    except ProcessError as exc:
        # exc.stderr from the SDK is the synthetic "Check stderr output for
        # details" placeholder — the real CLI stderr is what we collected via
        # our `_capture_stderr` callback above. Prefer the captured lines.
        captured_stderr = "".join(cli_stderr_lines).strip()
        diagnostic = (captured_stderr or (exc.stderr or "")).strip()
        log.error(
            "Claude-Subprocess abgestuerzt: exit=%s stderr_len=%d",
            exc.exit_code,
            len(diagnostic),
        )

        # Auto-Recovery: Session-ID veraltet (z.B. weil sie mit anderer CLI-Installation
        # angelegt wurde, oder Claude Code hat seinen Session-Storage aufgeräumt).
        # Wir löschen die Session-ID aus der DB und sagen dem User Bescheid.
        combined = diagnostic + " " + str(exc)
        if (
            "no conversation found" in combined.lower()
            or "session id" in combined.lower()
        ) and session_id:
            log.warning(
                "Session %s nicht (mehr) auffindbar — lösche aus DB. "
                "Nächste Nachricht startet eine frische Session.",
                session_id,
            )
            await db.set_claude_session_id(cid, None)
            yield {
                "type": "error",
                "message": (
                    "Die Claude-Session zu diesem Chat ist nicht mehr verfügbar "
                    "(vermutlich von einer anderen CLI-Installation angelegt). "
                    "Schick die Nachricht nochmal — ich starte dann eine neue Session."
                ),
            }
            return

        yield {
            "type": "error",
            "message": _process_error_client_message(exc.exit_code, combined),
        }
    except Exception as exc:  # noqa: BLE001
        log.error(
            "SDK-Stream-Fehler: cid=%s error_type=%s",
            cid,
            type(exc).__name__,
        )
        yield {
            "type": "error",
            "message": "Claude: Der Serverprozess ist intern fehlgeschlagen.",
        }


def _accumulate_usage(usage, out: dict) -> None:
    """Verträgt sowohl dict-Usage als auch typed-Objekt-Usage.

    Wichtig: wir nutzen `value if value is not None else fallback`, NICHT
    `value or fallback` — sonst würde ein legitimer 0-Wert (z.B. cache_write=0
    weil keine neuen Cache-Einträge entstanden sind) auf den Fallback
    zurückgesetzt und vorhandene Counts überschreiben.
    """
    if not usage:
        return

    def _pick(d_val, fallback):
        return d_val if d_val is not None else fallback

    if isinstance(usage, dict):
        out["input_tokens"] = _pick(usage.get("input_tokens"), out.get("input_tokens", 0))
        out["output_tokens"] = _pick(usage.get("output_tokens"), out.get("output_tokens", 0))
        out["cache_read"] = _pick(
            usage.get("cache_read_input_tokens"), out.get("cache_read", 0),
        )
        out["cache_write"] = _pick(
            usage.get("cache_creation_input_tokens"), out.get("cache_write", 0),
        )
    else:
        # Dataclass-Variante (z.B. TaskUsage)
        out["input_tokens"] = _pick(
            getattr(usage, "input_tokens", None), out.get("input_tokens", 0),
        )
        out["output_tokens"] = _pick(
            getattr(usage, "output_tokens", None), out.get("output_tokens", 0),
        )
        out["cache_read"] = _pick(
            getattr(usage, "cache_read_input_tokens", None), out.get("cache_read", 0),
        )
        out["cache_write"] = _pick(
            getattr(usage, "cache_creation_input_tokens", None), out.get("cache_write", 0),
        )
