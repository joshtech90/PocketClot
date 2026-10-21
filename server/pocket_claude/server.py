"""FastAPI-Server: HTTP-Endpoints für PocketClot."""
from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import time as _time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import AsyncIterator

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Path as PathParam,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from pocket_claude import attachments as attachments_mod
from pocket_claude import (
    __version__, auth_modes, backup, claude_engine, db, gateways,
    image_engine, image_tool, openai_engine, system_prompts, tts, tts_cache,
    usage, voice,
)
from pocket_claude.auth import (
    require_admin,
    require_token,
    require_token_header_or_query,
    require_user,
    require_user_header_or_query,
)
from pocket_claude.login_throttle import client_ip, login_throttler, throttle_error
from pocket_claude.config import settings
from pocket_claude.models import (
    RewindRequest,
    RewindResponse,
    AttachmentOut,
    AttachmentRef,
    ChatLockClearRequest,
    ChatLockSetRequest,
    ChatLockStatusDto,
    ChatLockVerifyRequest,
    ChatLockVerifyResponse,
    ChatModelDto,
    ChatModelsDto,
    ClaudeAuthDto,
    ClaudeAuthUpdateRequest,
    ConversationCreate,
    ConversationDetail,
    ConversationOut,
    ConversationPatch,
    ConversationSkillsRequest,
    ConversationSkillsResponse,
    GatewayStatusDto,
    GemDto,
    GemFileDto,
    GemUpsertRequest,
    HealthOut,
    MessageOut,
    SearchHitOut,
    SearchResponseOut,
    SendMessageRequest,
    SettingsExportDto,
    SettingsImportRequest,
    SettingsImportResponse,
    SkillsDefaultsRequest,
    SkillsDto,
    TtsChunkingRequest,
    TtsProviderRequest,
    TtsStatusDto,
    TtsVoiceDto,
    UsageStatsDto,
)

log = logging.getLogger("pocket_claude")
logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# --- Query-String-Secret-Redaction -------------------------------------------
# token=/password=/api_key= in Query-Strings dürfen NICHT im Klartext in Access-/
# App-Logs landen. Der Filter (inkl. Wiring an Root- + uvicorn-Logger) lebt in
# einem eigenen, leichtgewichtigen Modul, damit er ohne den vollen Server-Import
# getestet werden kann.
from pocket_claude.log_redaction import (  # noqa: E402
    _RedactQuerySecretsFilter,
    _scrub_secret,
    install_query_secret_redaction,
)

install_query_secret_redaction()
# -----------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    await db.init_db()
    await usage.ensure_schema()
    log.info("PocketClot Server v%s gestartet — DB: %s", __version__, settings.db_path)
    # TTS-Pre-Warm: Service-Account-JSON laden, OAuth-Token holen, gRPC-Channel
    # zu Google öffnen — spart 200-500ms beim ersten echten TTS-Tap.
    import asyncio as _asyncio
    app.state.grok_migration = _asyncio.create_task(_migrate_tts_to_grok())
    _asyncio.create_task(_migrate_defaults_opus_high())
    from pocket_claude import wissen_export as _wissen_export
    app.state.wissen_export = _asyncio.create_task(_wissen_export.schleife())
    yield


async def _migrate_tts_to_grok() -> None:
    """Stellt jeden Nutzer einmalig auf Grok mit der Stimme Leo um (Joschas
    Entscheidung vom 21.10.2026, fuer alle Konten).

    Erst wenn der Grok-Dienst angemeldet ist: vorher gaebe es mit Grok keine
    Sprachausgabe. Bis dahin wird alle zehn Minuten nachgesehen. Der Merker pro
    Nutzer sorgt dafuer, dass eine spaetere eigene Wahl bleibt.
    """
    import asyncio as _asyncio
    await _asyncio.sleep(5)
    while True:
        try:
            if await _asyncio.to_thread(tts.grok_available, True):
                users = await db.list_users()
                umgestellt = 0
                for u in users:
                    uid = u.get("id")
                    if not uid:
                        continue
                    async with _settings_lock(uid):
                        kv = await db.kv_get_all(scope=uid)
                        if (kv.get(_KV_TTS_GROK_MIGRATED) or "").strip() == "1":
                            continue
                        await db.kv_set_many({
                            _KV_TTS_PROVIDER: tts.PROVIDER_GROK,
                            # Die Clients merken sich die Stimme im selben Speicher.
                            "ttsVoice": tts.DEFAULT_VOICE_GROK,
                            _KV_TTS_GROK_MIGRATED: "1",
                        }, scope=uid)
                    umgestellt += 1
                if umgestellt:
                    log.info("TTS-Umstellung auf Grok Leo: %d von %d Nutzern", umgestellt, len(users))
        except Exception as exc:  # noqa: BLE001 - darf den Server nie stoeren
            log.warning("TTS-Umstellung auf Grok fehlgeschlagen (nicht kritisch): %s", exc)
        await _asyncio.sleep(600)


_KV_DEFAULTS_OPUS_MIGRATED = "defaults_opus_high_migrated"


async def _migrate_defaults_opus_high() -> None:
    """Setzt einmalig fuer jeden Nutzer die Vorauswahl neuer Chats auf Opus
    (die Familie, der Server nimmt die neueste Generation) mit Denktiefe Hoch.

    Joschas Entscheidung vom 21.10.2026, fuer alle Konten. Der Merker sorgt
    dafuer, dass eine spaeter getroffene eigene Wahl beim naechsten Start
    nicht wieder ueberschrieben wird. Andere Familien bleiben, wie sie sind.
    """
    try:
        users = await db.list_users()
        umgestellt = 0
        for u in users:
            uid = u.get("id")
            if not uid:
                continue
            async with _settings_lock(uid):
                kv = await db.kv_get_all(scope=uid)
                if (kv.get(_KV_DEFAULTS_OPUS_MIGRATED) or "").strip() == "1":
                    continue
                try:
                    by_family = json.loads(kv.get("effortByFamily") or "{}")
                except json.JSONDecodeError:
                    by_family = {}
                if not isinstance(by_family, dict):
                    by_family = {}
                by_family["claude"] = "high"
                await db.kv_set_many({
                    "chatModel": claude_engine.DEFAULT_CLAUDE_MODEL,
                    "effort": "high",
                    "effortByFamily": json.dumps(by_family, separators=(",", ":")),
                    auth_modes.KV_DEFAULT_MODEL: claude_engine.DEFAULT_CLAUDE_MODEL,
                    _KV_DEFAULTS_OPUS_MIGRATED: "1",
                }, scope=uid)
            umgestellt += 1
        if umgestellt:
            log.info("Vorauswahl Opus/Hoch fuer %d von %d Nutzern gesetzt", umgestellt, len(users))
    except Exception as exc:  # noqa: BLE001 - darf den Start nie verhindern
        log.warning("Umstellung auf Opus/Hoch fehlgeschlagen (nicht kritisch): %s", exc)


app = FastAPI(
    title="PocketClot",
    version=__version__,
    description="Persönlicher Claude-Chat-Server für die PocketClot Android-App.",
    lifespan=lifespan,
)

# CORS ist konfigurierbar (CORS_ORIGINS in der .env, komma-separiert). Default
# bleibt "*" — die App spricht eh via Tunnel, und browser-basierte Tests sind so
# bequemer. Wer es enger will, setzt CORS_ORIGINS auf die App-/Web-UI-Origin(s).
_cors_origins = settings.cors_origin_list
if _cors_origins == ["*"]:
    log.warning(
        "CORS: allow_origins=['*'] — jede Website darf diese API aufrufen. "
        "Für ein engeres Setup CORS_ORIGINS in der .env auf die App-/Web-UI-Origin setzen."
    )
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- Helpers ----------

def _row_to_conv_out(row: dict) -> ConversationOut:
    return ConversationOut(
        id=row["id"],
        title=row["title"],
        created_at=datetime.fromisoformat(row["created_at"]),
        last_message_at=(
            datetime.fromisoformat(row["last_message_at"]) if row["last_message_at"] else None
        ),
        message_count=row["msg_count"],
        total_tokens=row["total_tokens"],
        pinned=bool(row.get("pinned", 0)),
        locked=bool(row.get("locked", 0)),
        gem_id=row.get("gem_id"),
        chat_model=row.get("chat_model") or None,
        chat_effort=row.get("chat_effort") or None,
    )


async def _attachment_refs(ids: list[str]) -> list[AttachmentRef]:
    atts = await db.get_attachments(ids)
    return [
        AttachmentRef(
            id=a["id"],
            filename=a["filename"],
            mime_type=a["mime_type"],
            size_bytes=a["size_bytes"],
        )
        for a in atts
    ]


async def _row_to_message_out(row: dict) -> MessageOut:
    return MessageOut(
        id=row["id"],
        conversation_id=row["conversation_id"],
        role=row["role"],
        content=row["content"],
        created_at=datetime.fromisoformat(row["created_at"]),
        tokens=row["tokens"],
        attachments=await _attachment_refs(row["attachment_ids"]),
    )


# ---------- Health ----------

@app.get("/health", response_model=HealthOut)
async def health() -> HealthOut:
    db_ok = settings.db_path.exists()
    model = settings.claude_model or "Claude (Default via claude CLI)"
    return HealthOut(
        status="ok",
        version=__version__,
        model=model,
        db_ok=db_ok,
    )


# ---------- Conversations ----------

@app.get("/conversations", response_model=list[ConversationOut])
async def list_conversations(user=Depends(require_user)) -> list[ConversationOut]:
    rows = await db.list_conversations(user_id=user["id"])
    return [_row_to_conv_out(r) for r in rows]


@app.post(
    "/conversations",
    response_model=ConversationOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_conversation(body: ConversationCreate, user=Depends(require_user)) -> ConversationOut:
    gem_id = (body.gem_id or "").strip() or None
    gem = None
    if gem_id is not None:
        gem = await db.get_gem(gem_id, user_id=user["id"])
        if not gem:
            raise HTTPException(404, "Gem nicht gefunden.")
    # Ein Gem startet den Chat mit seinem Modell und seiner Denktiefe. Beides
    # landet beim Chat selbst: stellt man es dort um, gilt ab dann die
    # Wahl im Chat und nicht mehr die Vorgabe des Gems.
    cid = await db.create_conversation(
        body.title, user_id=user["id"], gem_id=gem_id,
        chat_model=(gem.get("model") if gem else None),
        chat_effort=(gem.get("effort") if gem else None),
    )
    conv = await db.get_conversation(cid, user_id=user["id"])
    assert conv is not None
    return ConversationOut(
        id=conv["id"],
        title=conv["title"],
        created_at=datetime.fromisoformat(conv["created_at"]),
        last_message_at=None,
        message_count=0,
        total_tokens=0,
        gem_id=conv.get("gem_id"),
        chat_model=conv.get("chat_model") or None,
        chat_effort=conv.get("chat_effort") or None,
    )


@app.get("/conversations/{cid}", response_model=ConversationDetail)
async def get_conversation(cid: str = PathParam(...), user=Depends(require_user)) -> ConversationDetail:
    # ABSICHTLICH: liefert auch locked Chats samt Messages aus. Die Chat-Sperre
    # ist ein reines UI-Gate (siehe Design-Kommentar am Chat-Sperre-Block unten),
    # keine serverseitige Zugriffskontrolle — kein Bug.
    conv = await db.get_conversation(cid, user_id=user["id"])
    if not conv:
        raise HTTPException(404, "Konversation nicht gefunden.")
    msg_rows = await db.list_messages(cid)
    messages = [await _row_to_message_out(m) for m in msg_rows]
    return ConversationDetail(
        id=conv["id"],
        title=conv["title"],
        created_at=datetime.fromisoformat(conv["created_at"]),
        last_message_at=(
            datetime.fromisoformat(conv["last_message_at"]) if conv["last_message_at"] else None
        ),
        message_count=len(messages),
        total_tokens=conv["total_tokens"],
        pinned=bool(conv.get("pinned", 0)),
        locked=bool(conv.get("locked", 0)),
        gem_id=conv.get("gem_id"),
        chat_model=conv.get("chat_model") or None,
        chat_effort=conv.get("chat_effort") or None,
        messages=messages,
    )


async def _model_key_is_known(model_key: str) -> bool:
    """Prueft einen Modell-Key, so wie es `send_message` auch tut.

    Leer heisst Claude-Standard und ist immer gueltig. Zusatz-Modelle werden
    UNGEFILTERT geprueft: ein Chat darf auf einem Modell weiterlaufen, das
    inzwischen nicht mehr kuratiert ist, sonst wechselte er beim naechsten
    Turn stillschweigend das Modell.
    """
    key = (model_key or "").strip()
    if not key:
        return True
    if key.startswith("gw:"):
        models = await gateways.list_models(curated=False)
        return any(m.key == key for m in models)
    return claude_engine.is_allowed_model(key)


@app.post("/conversations/{cid}/rewind", response_model=RewindResponse)
async def rewind_conversation(
    cid: str, body: RewindRequest, user=Depends(require_user),
) -> RewindResponse:
    """Springt im Chat zu einer frueheren Antwort zurueck.

    Alles nach der angegebenen Nachricht wird verworfen, die Nachricht selbst
    bleibt stehen. Optional wird im selben Zug das Modell gewechselt: genau
    dafuer springt man meistens zurueck.

    Die Claude-Session wird verworfen. Sie kennt die geloeschten Turns noch,
    und ohne diesen Schritt wuerde Claude munter auf einer Antwort weiterreden,
    die der Nutzer gerade weggeworfen hat. Beim naechsten Turn baut
    `replay_history` den Verlauf aus der Datenbank neu auf.

    Der ganze Vorgang laeuft unter derselben Sperre wie ein Chat-Turn. Sonst
    koennte ein gerade laufender Stream seine Antwort hinter das Loeschen
    schreiben, und im Chat stuende wieder etwas, das eben verworfen wurde.
    """
    conv = await db.get_conversation(cid, user_id=user["id"])
    if not conv:
        raise HTTPException(404, "Konversation nicht gefunden.")

    # ERST pruefen, DANN loeschen. Ein ungueltiges Modell darf nicht dazu
    # fuehren, dass die Nachrichten schon weg sind und der Aufruf trotzdem mit
    # einem Fehler endet.
    new_model = conv.get("chat_model")
    if body.chat_model is not None:
        candidate = body.chat_model.strip()
        if candidate and not await _model_key_is_known(candidate):
            raise HTTPException(400, f"Unbekanntes Modell: {candidate!r}")
        new_model = candidate

    lock = _conv_lock(cid)
    async with lock:
        msgs = await db.list_messages(cid)
        target = next((m for m in msgs if m["id"] == body.message_id), None)
        if target is None:
            raise HTTPException(404, "Diese Nachricht gehoert nicht zu diesem Chat.")
        # Zurueckgesprungen wird auf eine Antwort, nicht auf eine eigene Frage:
        # sonst endet der Verlauf mit einer unbeantworteten Nachricht, und der
        # naechste Turn faengt mit zwei Nutzer-Nachrichten hintereinander an.
        if target["role"] != "assistant":
            raise HTTPException(
                400, "Es kann nur auf eine Antwort zurueckgesprungen werden.",
            )

        is_last = bool(msgs) and msgs[-1]["id"] == body.message_id
        if is_last and body.chat_model is None:
            # Nichts zu verwerfen und kein Modellwechsel: dann war der Aufruf
            # gegenstandslos, und wir fassen die Session nicht ohne Not an.
            return RewindResponse(removed=0, chat_model=conv.get("chat_model"))

        removed = await db.truncate_after(cid, body.message_id)
        if body.chat_model is not None:
            await db.set_chat_model(cid, new_model or "", user_id=user["id"])
        await db.set_claude_session_id(cid, None)

    log.info("PC_SESSION: cid=%s Ruecksprung auf msg=%s, %d Nachrichten "
             "verworfen, Modell=%r", cid, body.message_id, removed,
             new_model or "claude")
    return RewindResponse(removed=removed, chat_model=new_model)


# Alles, was irgendein Modell als Denktiefe kennt. Was das gerade gewaehlte
# Modell davon kann, klaeren die Engines beim Senden.
_CHAT_EFFORTS = {"off", *gateways.EFFORT_ORDER}


@app.patch("/conversations/{cid}", response_model=ConversationOut)
async def patch_conversation(cid: str, body: ConversationPatch, user=Depends(require_user)) -> ConversationOut:
    conv = await db.get_conversation(cid, user_id=user["id"])
    if not conv:
        raise HTTPException(404, "Konversation nicht gefunden.")
    if body.title is not None:
        await db.update_conversation_title(cid, body.title, user_id=user["id"])
    if body.pinned is not None:
        await db.set_pinned(cid, body.pinned, user_id=user["id"])
    if body.chat_model is not None:
        # Wie in send_message: ein Modellwechsel macht die Claude-Session
        # ungueltig, weil sie die Turns des anderen Modells nicht kennt.
        old_model = (conv.get("chat_model") or "").strip()
        new_model = body.chat_model.strip()
        await db.set_chat_model(cid, new_model, user_id=user["id"])
        if old_model and new_model != old_model and conv.get("claude_session_id"):
            await db.set_claude_session_id(cid, None)
            log.info("PC_RESOLVE: cid=%s Modellwechsel per PATCH %r -> %r, "
                     "Claude-Session verworfen", cid, old_model, new_model)
    if body.chat_effort is not None:
        effort_value = body.chat_effort.strip().lower()
        if effort_value and effort_value not in _CHAT_EFFORTS:
            raise HTTPException(400, f"Unbekannte Denktiefe: {effort_value!r}")
        await db.set_chat_effort(cid, effort_value, user_id=user["id"])
    if body.locked is not None:
        # Sperren nur erlauben, wenn ein globaler PIN gesetzt ist — sonst hätte
        # der User einen gesperrten Chat, den er nicht mehr aufbekommt.
        if body.locked:
            kv = await db.kv_get_all(scope=user["id"])
            if not kv.get(KV_CHAT_LOCK_PIN_HASH):
                raise HTTPException(
                    400,
                    "Kein Chat-Sperr-PIN gesetzt. Lege zuerst in den Einstellungen "
                    "einen PIN fest.",
                )
        await db.set_locked(cid, body.locked, user_id=user["id"])
        if body.locked:
            from pocket_claude import wissen_export
            wissen_export.verwerfen(user["id"])
    rows = await db.list_conversations(user_id=user["id"])
    for r in rows:
        if r["id"] == cid:
            return _row_to_conv_out(r)
    # list_conversations only returns chats that already have at least one
    # message. A freshly created (still empty) chat that gets patched
    # (renamed/pinned) is therefore absent from that list — re-fetch it
    # directly and build the response, instead of falsely 404-ing a write
    # that actually succeeded.
    updated = await db.get_conversation(cid, user_id=user["id"])
    if updated is None:
        raise HTTPException(404, "Konversation verschwunden.")
    return ConversationOut(
        id=updated["id"],
        title=updated["title"],
        created_at=datetime.fromisoformat(updated["created_at"]),
        last_message_at=(
            datetime.fromisoformat(updated["last_message_at"])
            if updated["last_message_at"] else None
        ),
        message_count=0,
        total_tokens=updated["total_tokens"],
        pinned=bool(updated.get("pinned", 0)),
        locked=bool(updated.get("locked", 0)),
        gem_id=updated.get("gem_id"),
        chat_model=updated.get("chat_model") or None,
        chat_effort=updated.get("chat_effort") or None,
    )


@app.delete(
    "/conversations/{cid}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=JSONResponse,
)
async def delete_conversation(cid: str, user=Depends(require_user)):
    ok = await db.delete_conversation(cid, user_id=user["id"])
    if not ok:
        raise HTTPException(404, "Konversation nicht gefunden.")
    from pocket_claude import wissen_export
    wissen_export.verwerfen(user["id"])
    return JSONResponse(status_code=204, content=None)


# ---------- Messages ----------

# ---------- Chat-Modelle (Claude plus Zusatz-Modelle) ----------

@app.get("/chat/models", response_model=ChatModelsDto)
async def list_chat_models(
    refresh: bool = Query(False, description="Gateway-Cache umgehen"),
    include: str = Query("", description="Zusaetzlich diesen Modell-Key mitliefern, "
                                         "auch wenn er nicht kuratiert ist"),
    user=Depends(require_user),
) -> ChatModelsDto:
    """Alle waehlbaren Modelle plus den Zustand der Zusatz-Gateways.

    Claude steht immer an erster Stelle und ist auch dann waehlbar, wenn kein
    Gateway laeuft. Faellt ein Gateway aus, taucht es mit `reachable=false` und
    der Fehlermeldung in `gateways` auf; die App zeigt das an, statt einfach
    Modelle verschwinden zu lassen.
    """
    models: list[ChatModelDto] = [
        ChatModelDto(
            key=model_id,
            family="claude",
            label=label,
            efforts=list(claude_engine.CLAUDE_EFFORTS),
            default_effort="high",
            supports_vision=True,
            gateway_label="",
        )
        for model_id, label in claude_engine.SELECTABLE_MODELS
    ]

    gw_models = await gateways.list_models(force=refresh)
    # Das Modell, das im aktuellen Chat steht, gehoert immer in die Liste, auch
    # wenn es nicht kuratiert ist. Sonst haelt die App es faelschlich fuer
    # verschwunden und setzt den Chat auf ein anderes Modell zurueck.
    wanted = (include or "").strip()
    if wanted and not any(m.key == wanted for m in gw_models):
        extra = next((m for m in await gateways.list_models(curated=False)
                      if m.key == wanted), None)
        if extra is not None:
            gw_models = [*gw_models, extra]

    for gm in gw_models:
        models.append(ChatModelDto(
            key=gm.key,
            family=gm.family,
            label=gm.label,
            efforts=list(gm.efforts),
            default_effort=gm.default_effort,
            supports_vision=gm.supports_vision,
            context_length=gm.context_length,
            gateway_label=gm.gateway_label,
        ))

    # Die interne Basis-URL geht nur an Admins. Normale User sehen nur, ob das
    # Gateway laeuft und woran es ggf. klemmt.
    is_admin = bool(user.get("is_admin"))
    gw_status = []
    for g in await gateways.status():
        entry = dict(g)
        if not is_admin:
            entry["base_url"] = ""
        gw_status.append(GatewayStatusDto(**entry))
    kv = await db.kv_get_all(scope=user["id"])
    default_key = (kv.get(auth_modes.KV_DEFAULT_MODEL) or "").strip()

    log.info("PC_RESOLVE: /chat/models -> %d Modelle, %d Gateways, default=%r",
             len(models), len(gw_status), default_key)
    return ChatModelsDto(models=models, gateways=gw_status, default_key=default_key)


# Pro Konversation darf immer nur EIN Turn laufen. Ohne das koennen zwei
# Requests (Doppeltipp, Retry, zweites Geraet) denselben Ausgangszustand lesen
# und danach Modell, Session, Nachrichten und Token-Stand gegenseitig
# ueberschreiben. Der Lock ist prozesslokal, was reicht: der Server laeuft als
# EIN uvicorn-Prozess.
_CONV_LOCKS: dict[str, asyncio.Lock] = {}


def _conv_lock(cid: str) -> asyncio.Lock:
    lock = _CONV_LOCKS.get(cid)
    if lock is None:
        lock = asyncio.Lock()
        _CONV_LOCKS[cid] = lock
    return lock


@app.post("/conversations/{cid}/messages")
async def send_message(cid: str, body: SendMessageRequest, request: Request,
                       user=Depends(require_user)) -> EventSourceResponse:
    """Sendet eine User-Message und streamt die Assistant-Antwort via SSE."""
    # Gedaechtnis-Schluessel aus der App: nur durchreichen, nie speichern oder loggen
    from pocket_claude import wissen_tool
    wissen_schluessel = request.headers.get(wissen_tool.HEADER) or None
    conv = await db.get_conversation(cid, user_id=user["id"])
    if not conv:
        raise HTTPException(404, "Konversation nicht gefunden.")

    # Anhänge validieren — müssen demselben User gehören
    if body.attachment_ids:
        existing = await db.get_attachments(body.attachment_ids)
        if len(existing) != len(body.attachment_ids):
            raise HTTPException(400, "One or more attachment IDs are invalid.")
        for a in existing:
            if a.get("user_id") != user["id"]:
                raise HTTPException(403, "Attachment belongs to a different user.")

    # Gem und Modell werden VOR dem Speichern der User-Nachricht aufgeloest.
    # Ein ungueltiges Modell soll mit 400 abbrechen, ohne eine verwaiste
    # Nachricht im Chat zu hinterlassen.
    gem = None
    if conv.get("gem_id"):
        gem = await db.get_gem(conv["gem_id"], user_id=user["id"])

    # Modell-Aufloesung. Die erste Quelle, die etwas sagt, gewinnt:
    #   1. was die App diesmal mitschickt. Ein LEERER String ist hier eine
    #      Aussage ("nimm Claude"), `None` heisst "hab ich nicht mitgeschickt".
    #   2. das Modell des Gems (ein Gem definiert sein Modell wie ein GPT)
    #   3. das zuletzt in diesem Chat benutzte Modell
    #   4. das globale Standard-Modell des Users
    #   5. leer = Claude-Automatik (Bedrock-Alias bzw. SDK-Default)
    user_kv = await db.kv_get_all(scope=user["id"])
    previous_model = (conv.get("chat_model") or "").strip()
    if body.model is not None:
        resolved_model = body.model.strip()
    else:
        resolved_model = (
            ((gem.get("model") or "").strip() if gem else "")
            or previous_model
            or (user_kv.get(auth_modes.KV_DEFAULT_MODEL) or "").strip()
        )

    # Zusatz-Modelle tragen den Gateway-Praefix. Alles andere ist Claude.
    use_gateway = resolved_model.startswith("gw:")

    # Allowlist. Ohne die waere `SELECTABLE_MODELS` reine UI-Dekoration und ein
    # Client koennte beliebige Modell-Strings an die Claude-CLI durchreichen.
    # Der Bedrock-Pin bleibt unberuehrt, der kommt aus dem KV, nicht von hier.
    # Ungefiltert pruefen: kuratiert wird nur der Picker. Sonst wuerde ein
    # Bestandschat, dessen Modell inzwischen aus der Allowlist gefallen ist,
    # beim naechsten Turn mit 400 abbrechen.
    gateway_models = await gateways.list_models(curated=False) if use_gateway else []
    gw_model = next((m for m in gateway_models if m.key == resolved_model), None)
    if use_gateway and gw_model is None:
        raise HTTPException(400, (
            f"Das Modell '{resolved_model}' wird gerade nicht angeboten. "
            f"Bitte in den Einstellungen ein anderes waehlen."
        ))
    if resolved_model and not use_gateway:
        if not claude_engine.is_allowed_model(resolved_model):
            raise HTTPException(400, f"Unbekanntes Modell: {resolved_model!r}")

    default_model = None if use_gateway else (resolved_model or None)

    # Modellwechsel im laufenden Chat: die Claude-Session kennt die Turns der
    # anderen Modelle nicht, also wird sie verworfen und der naechste
    # Claude-Turn bekommt den Verlauf ueber `replay_history` neu.
    #
    # Wichtig: NUR wenn der Chat vorher schon ein Modell vermerkt hatte. Bei
    # Bestandschats ist `chat_model` NULL, obwohl dort die ganze Zeit dasselbe
    # Claude-Modell lief. Wuerden wir dort die Session wegwerfen, waere das eine
    # Regression fuer jeden bestehenden Chat.
    model_changed = bool(previous_model) and resolved_model != previous_model
    drop_session = bool(model_changed and conv.get("claude_session_id"))
    if drop_session:
        # Fuer `replay_history` unten so tun, als waere die Session schon weg.
        conv["claude_session_id"] = None

    # Claude soll auch dann den Faden kennen, wenn die Session frisch ist, weil
    # zwischendurch ein Zusatz-Modell geantwortet hat (oder die Session verloren
    # ging). Nur wenn es ueberhaupt aeltere Nachrichten gibt.
    replay_history = (
        not use_gateway
        and not conv.get("claude_session_id")
        and conv.get("last_message_at") is not None
    )


    # Kurzer Auto-Titel (1-2 Wörter) wird — falls das die erste Nachricht des
    # Chats ist — im Hintergrund per günstigem Haiku erzeugt (siehe event_gen).
    # Bewusst NICHT hier blockierend, damit die eigentliche Antwort ohne
    # Verzögerung streamt; der Titel läuft parallel und wird kurz vor `done`
    # ausgeliefert.
    needs_title = (conv.get("title") == "Neuer Chat")

    # Denktiefe: die dieses Chats, sonst was der Client mitschickt. Ein Gem
    # legt sie beim Start am Chat an (aeltere Gem-Chats hat die Migration in
    # db.py nachgetragen), im Chat umgestellt wird sie per PATCH. So gilt sie
    # auch fuer aeltere Clients, die nur ihre Familien-Vorgabe mitschicken.
    effort = (
        (conv.get("chat_effort") or "").strip()
        or (body.effort or "high")
    ).lower().strip()

    # System-Prompt: Gem-Instructions gewinnen. Sonst: Mode (Web-UI) bzw. roher
    # String (App). Sonst Server-Default (in claude_engine).
    if gem and (gem.get("instructions") or "").strip():
        # Gem-Instructions wie andere Prompts durch die Platzhalter-Ersetzung
        # schicken, damit z.B. {{currentDateTime}} im Gem funktioniert.
        system_prompt = system_prompts._substitute_placeholders(gem["instructions"])
    elif body.system_prompt_mode:
        system_prompt = system_prompts.resolve_system_prompt(
            body.system_prompt_mode, body.system_prompt,
        )
    else:
        system_prompt = body.system_prompt

    # Skills: Per-Chat-Override > Gem-Skills > User-Default > Server-Default.
    effective_skills, _is_override = await _resolve_effective_skills(
        user["id"], conv.get("skills_override"),
        gem_skills_override=(gem.get("skills") if gem else None),
    )
    skills_dict = effective_skills.model_dump()

    # Bild-Werkzeug: Skill-Schalter des Chats plus die Standardwerte des Users.
    # Wer ausdruecklich "Bild erstellen" waehlt, bekommt es auch bei
    # abgeschaltetem Skill: sonst liefe der Wunsch ins Leere.
    if body.image_mode:
        skills_dict["image_generation"] = True
    allow_image_tool = bool(skills_dict.get("image_generation", True))
    image_defaults = {
        "size": (user_kv.get(_KV_IMAGE_DEFAULT_SIZE) or "").strip() or None,
        "aspect_ratio": (user_kv.get(_KV_IMAGE_DEFAULT_ASPECT) or "").strip() or None,
        "model": (user_kv.get(_KV_IMAGE_DEFAULT_MODEL) or "").strip() or None,
        "provider": image_engine.canonical_provider(user_kv.get(_KV_IMAGE_PROVIDER)),
        # Die Bilder dieser Nachricht, falls das Modell sie bearbeiten soll.
        "attachment_ids": list(body.attachment_ids or []),
        # Zeichnet nur ein Anbieter, weil das zweite Gateway fehlt, dann der
        # des Modells, das gerade antwortet. Claude hat keinen eigenen, dort
        # bleibt es bei Gemini.
        "family_hint": (gw_model.family if gw_model is not None else ""),
    }

    # Zusatz-Modelle bekommen den Prompt in einer angepassten Fassung: ohne den
    # Anthropic-Produktblock und mit dem echten Modellnamen statt „Claude".
    # Sonst behauptet Gemini oder GPT, Claude zu sein, und wir bezahlen jeden
    # Turn ein paar tausend Tokens Produktwissen, das dort nichts nutzt.
    if use_gateway and system_prompt and gw_model is not None:
        system_prompt = system_prompts.adapt_for_model(
            system_prompt, model_label=gw_model.label, family=gw_model.family,
        )

    # Gem-Wissensdateien an jede Nachricht des Gem-Chats anhängen.
    extra_attachment_ids = (
        await db.get_gem_file_ids(conv["gem_id"]) if gem else []
    )
    log.info(
        "PC_GEM: send cid=%s gem=%s model=%s gateway=%s replay=%s gem_files=%d",
        cid, (gem["id"] if gem else None), resolved_model or "claude",
        use_gateway, replay_history, len(extra_attachment_ids),
    )

    async def event_gen() -> AsyncIterator[dict]:
        # PC_SSE diagnostic logging — see PocketClaude "denkt"-bug investigation.
        # Temporary, remove after root cause is fixed.
        delta_count = 0
        last_event = None
        assistant_msg_id: int | None = None
        user_msg_id: int | None = None
        title_sent = False
        # Titel-Task läuft PARALLEL zum Antwort-Stream (überlappt die Wartezeit,
        # kostet also praktisch keine Extra-Latenz) und wird kurz vor `done`
        # eingesammelt + als `title`-Event geschickt.
        title_task = (
            asyncio.create_task(
                claude_engine.generate_conversation_title(
                    cid, body.content, user_id=user["id"],
                )
            ) if needs_title else None
        )
        log.info("PC_SSE: event_gen START cid=%s user=%s", cid, user["id"])
        # Der Lock haelt den zweiten gleichzeitigen Turn desselben Chats auf,
        # bis der erste durch ist. Sonst schreiben beide Modell, Session und
        # Token-Stand durcheinander.
        lock = _conv_lock(cid)
        await lock.acquire()
        try:
            # Ab hier ist der Chat exklusiv. Erst jetzt wird geschrieben, damit
            # ein zweiter gleichzeitiger Turn nicht denselben Ausgangszustand
            # sieht und ihn anschliessend ueberschreibt.
            if resolved_model != previous_model:
                await db.set_chat_model(cid, resolved_model, user_id=user["id"])
            if drop_session:
                await db.set_claude_session_id(cid, None)
                log.info("PC_RESOLVE: cid=%s Modellwechsel %r -> %r, "
                         "Claude-Session verworfen",
                         cid, previous_model or "claude", resolved_model or "claude")

            # User-Message speichern (Token-Schaetzung grob ueber Zeichenlaenge
            # geteilt durch 4, die genauen Werte traegt das Usage-Event nach).
            user_msg_id = await db.add_message(
                cid,
                role="user",
                content=body.content,
                tokens=max(1, len(body.content) // 4),
                attachment_ids=body.attachment_ids,
            )
            yield {"event": "user_saved", "data": json.dumps({"user_message_id": user_msg_id})}
            log.info("PC_SSE: yield user_saved cid=%s user_msg_id=%s", cid, user_msg_id)

            # Fuer "aendere das Bild" ohne neuen Anhang: das zuletzt gezeigte
            # Bild. Erst hier unter dem Lock, damit es zum Verlauf passt.
            if allow_image_tool:
                image_defaults["previous_image_ids"] = await image_tool.previous_image_ids(
                    cid, before_message_id=user_msg_id)
            if body.image_mode:
                log.info("PC_IMG: cid=%s Bild erstellen gewaehlt", cid)

            # Geteilte Sprachnachrichten: einmal per Groq transkribieren, bevor
            # das Modell die Nachricht sieht. Sprache erkennt Whisper selbst,
            # ausser der Nutzer hat in der Spracheingabe eine feste gewaehlt.
            # Auch fruehere Audios im Chat ohne Transkript (etwa vor diesem
            # Feature geteilt oder bei einem Fehlschlag): sonst laeuft
            # "transkribiere" unter einer alten Sprachnachricht ins Leere.
            chat_ids = [aid for m in await db.list_messages(cid)
                        for aid in (m.get("attachment_ids") or [])]
            if chat_ids:
                audio_atts = [a for a in await db.get_attachments(chat_ids)
                              if attachments_mod.is_audio(a.get("filename") or "",
                                                          a.get("mime_type") or "")
                              and a.get("user_id") == user["id"]]
                if audio_atts:
                    sprache = ""
                    if (user_kv.get(voice.KV_LANG_MODE) or "").strip().lower() == "override":
                        sprache = voice.resolve_effective_lang(kv=user_kv, request_locale=None)
                    hinweis = voice.resolve_prompt(kv=user_kv, lang=sprache)[0] if sprache else ""
                    fehler = await attachments_mod.ensure_transcripts(
                        audio_atts,
                        api_key=(user_kv.get(_KV_VOICE_GROQ_API_KEY) or "").strip(),
                        whisper_lang=sprache, bias_prompt=hinweis,
                    )
                    for f in fehler:
                        log.warning("PC_AUDIO: cid=%s %s", cid, f)

            if use_gateway:
                engine_stream = openai_engine.stream_reply(
                    cid, user_msg_id,
                    model_key=resolved_model,
                    effort=effort,
                    system_prompt=system_prompt,
                    user_id=user["id"],
                    extra_attachment_ids=extra_attachment_ids,
                    allow_image_tool=allow_image_tool,
                    image_defaults=image_defaults,
                    # Dieselben Schalter wie bei Claude. Was ein Zusatz-Modell
                    # nicht kann (Bash), faellt in der Engine still weg.
                    skills=skills_dict,
                    wissen_schluessel=wissen_schluessel,
                    image_wish=body.image_mode,
                )
            else:
                engine_stream = claude_engine.stream_reply(
                    cid, user_msg_id,
                    effort=effort,
                    system_prompt=system_prompt,
                    skills=skills_dict,
                    user_id=user["id"],
                    default_model=default_model,
                    extra_attachment_ids=extra_attachment_ids,
                    replay_history=replay_history,
                    image_defaults=image_defaults,
                    wissen_schluessel=wissen_schluessel,
                    image_wish=body.image_mode,
                )

            async for ev in engine_stream:
                etype = ev.pop("type")
                last_event = etype
                if etype == "delta":
                    delta_count += 1
                    if delta_count <= 3 or delta_count % 25 == 0:
                        log.info("PC_SSE: yield delta #%d cid=%s len=%d",
                                 delta_count, cid, len(ev.get("text", "")))
                else:
                    log.info("PC_SSE: yield event=%s cid=%s payload_keys=%s",
                             etype, cid, list(ev.keys()))
                # Auto-Titel ausliefern, SOBALD der Hintergrund-Task fertig ist
                # (Haiku ist schnell, meist nach 1-2s → i.d.R. noch während die
                # Antwort streamt, damit die Seitenleiste früh den echten Namen zeigt).
                if title_task is not None and not title_sent and title_task.done():
                    auto_title = None
                    if not title_task.cancelled():
                        try:
                            auto_title = title_task.result()
                        except Exception:  # noqa: BLE001
                            auto_title = None
                    if auto_title:
                        yield {"event": "title", "data": json.dumps({"title": auto_title})}
                        log.info("PC_SSE: yield title (early) cid=%s title=%r", cid, auto_title)
                    title_sent = True
                if etype == "done":
                    assistant_msg_id = ev.get("assistant_message_id") or ev.get("message_id")
                    # Falls der Titel bis hierher noch nicht raus ist: jetzt noch
                    # VOR dem done-Event einsammeln (danach schließt der Client).
                    if title_task is not None and not title_sent:
                        auto_title = None
                        try:
                            auto_title = await asyncio.wait_for(
                                asyncio.shield(title_task), timeout=8.0,
                            )
                        except Exception as _te:  # noqa: BLE001
                            log.info("PC_SSE: Titel nicht rechtzeitig (%s)", _te)
                        if auto_title:
                            yield {"event": "title",
                                   "data": json.dumps({"title": auto_title})}
                            log.info("PC_SSE: yield title cid=%s title=%r", cid, auto_title)
                        title_sent = True
                yield {"event": etype, "data": json.dumps(ev)}

            log.info(
                "PC_SSE: event_gen FOR-LOOP-EXIT cid=%s deltas=%d last=%s assistant_msg_id=%s",
                cid, delta_count, last_event, assistant_msg_id,
            )
        except BaseException as _sse_exc:  # noqa: BLE001 — catches GeneratorExit + cancels
            import traceback as _tb
            log.error(
                "PC_SSE: event_gen EXCEPTION cid=%s deltas=%d last=%s exc=%s\n%s",
                cid, delta_count, last_event, _sse_exc, _tb.format_exc(),
            )
            # Try to surface an error to the client if connection is still open
            try:
                yield {"event": "error", "data": json.dumps({
                    "message": f"Stream interrupted: {type(_sse_exc).__name__}: {_sse_exc}",
                })}
            except BaseException:  # noqa: BLE001
                pass
            raise
        finally:
            # Wenn der Stream vor `done` abbrach, läuft der Titel-Task evtl. noch.
            # Weiterlaufen lassen (er setzt den Titel in der DB), aber eine evtl.
            # Exception konsumieren, damit asyncio keine „never retrieved"-Warnung
            # loggt.
            if title_task is not None and not title_task.done():
                title_task.add_done_callback(
                    lambda t: t.cancelled() or t.exception()
                )
            lock.release()
            log.info(
                "PC_SSE: event_gen END cid=%s deltas=%d last=%s assistant_msg_id=%s",
                cid, delta_count, last_event, assistant_msg_id,
            )

        # Pre-Generation: wenn der Client TTS-Voice + Rate beim Senden
        # mitgeschickt hat, synthetisieren wir die Antwort jetzt im
        # Hintergrund — der nächste Vorlesen-Tap ist dann Cache-Hit.
        if assistant_msg_id and body.tts_voice:
            # Nur fuer Grok und Edge: Gemini Web ist so schnell, dass sich das
            # Vorab-Erzeugen nicht lohnt. Grok nur, wenn der Dienst angemeldet ist.
            provider, chunking_enabled = await _resolve_tts_provider(user["id"])
            ready = provider == tts.PROVIDER_EDGE_TTS or (
                provider == tts.PROVIDER_GROK and await _asyncio_to_thread(tts.grok_available)
            )
            if ready:
                import asyncio as _asyncio
                _asyncio.create_task(_pregen_tts(
                    int(assistant_msg_id),
                    body.tts_voice,
                    body.tts_rate or tts.DEFAULT_SPEED,
                    provider,
                    chunking_enabled=chunking_enabled,
                ))

    return EventSourceResponse(event_gen())


async def _asyncio_to_thread(fn, *args):
    import asyncio as _asyncio
    return await _asyncio.to_thread(fn, *args)


async def _pregen_tts(
    message_id: int,
    voice: str,
    rate: float,
    provider: str,
    chunking_enabled: bool = False,
) -> None:
    """Erzeugt das Audio einer fertigen Antwort im Hintergrund und legt es in
    den Zwischenspeicher. Fehler werden nur geloggt: schlimmstenfalls wird
    beim Antippen frisch erzeugt."""
    try:
        from pocket_claude.db import get_db
        async with get_db() as conn:
            cur = await conn.execute(
                "SELECT content FROM messages WHERE id = ?", (message_id,),
            )
            row = await cur.fetchone()
        if not row or not row["content"]:
            return
        import io as _io
        buf = _io.BytesIO()
        # strict: bricht ein spaeteres Stueck ab, nichts zwischenspeichern.
        async for chunk_bytes in tts.synthesize_chunked(
            row["content"], voice, rate, provider,
            chunking_enabled=chunking_enabled, strict=True,
        ):
            buf.write(chunk_bytes)
        audio = buf.getvalue()
        media_type = tts.media_type_for(provider)
        await tts_cache.put(message_id, voice, rate, provider, audio, media_type)
        log.info(
            "TTS pre-gen OK msg=%d voice=%s rate=%.2f provider=%s (%d KB)",
            message_id, voice, rate, provider, len(audio) // 1024,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "TTS pre-gen für msg=%d (provider=%s) fehlgeschlagen: %s",
            message_id, provider, exc,
        )


# ---------- Attachments ----------

async def _store_upload(file: UploadFile, user_id: str) -> dict:
    """Schreibt einen Upload auf Disk + legt die attachments-Zeile an. Gibt die
    Attachment-Row zurück. Geteilt von /attachments und /me/gems/{id}/files."""
    contents = await file.read()
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(contents) > max_bytes:
        raise HTTPException(413, f"File too large (max {settings.max_upload_mb} MB).")

    filename = file.filename or "upload"
    mime = file.content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"

    # Auf Disk speichern — über asyncio.to_thread, damit ein 20-MB-Upload
    # nicht den Event-Loop blockiert (sonst hängen parallele Requests).
    import secrets as _secrets
    import asyncio as _asyncio
    suffix = (filename.rsplit(".", 1)[-1] if "." in filename else "bin")[:10]
    disk_name = f"{_secrets.token_urlsafe(12)}.{suffix}"
    target = settings.uploads_dir / disk_name
    await _asyncio.to_thread(target.write_bytes, contents)

    aid = await db.add_attachment(filename, mime, len(contents), target, user_id=user_id)
    att = await db.get_attachment(aid)
    assert att
    return att


@app.post("/attachments", response_model=AttachmentOut)
async def upload_attachment(file: UploadFile = File(...), user=Depends(require_user)) -> AttachmentOut:
    att = await _store_upload(file, user["id"])
    return AttachmentOut(
        id=att["id"],
        filename=att["filename"],
        mime_type=att["mime_type"],
        size_bytes=att["size_bytes"],
        uploaded_at=datetime.fromisoformat(att["uploaded_at"]),
    )


@app.get("/attachments/{aid}")
async def download_attachment(
    aid: str,
    token: str | None = None,  # noqa: ARG001 — wird von der Dep konsumiert
    user=Depends(require_user_header_or_query),
):
    """Token kann via Bearer-Header ODER ?token=... kommen — letzteres,
    damit das Web-UI Bilder direkt per <img src> einbetten kann."""
    from fastapi.responses import FileResponse
    att = await db.get_attachment(aid, user_id=user["id"])
    if not att:
        raise HTTPException(404, "Attachment nicht gefunden.")
    return FileResponse(
        att["path"],
        media_type=att["mime_type"],
        filename=att["filename"],
    )


# ---------- Search ----------

@app.get("/search", response_model=SearchResponseOut)
async def search(q: str, limit: int = Query(30, ge=1, le=100), user=Depends(require_user)) -> SearchResponseOut:
    if not q or len(q.strip()) < 2:
        return SearchResponseOut(query=q, hits=[])
    rows = await db.search_messages(q, limit=limit, user_id=user["id"])
    hits = [
        SearchHitOut(
            conversation_id=r["conversation_id"],
            conversation_title=r["conversation_title"] or "(ohne Titel)",
            message_id=r["message_id"],
            role=r["role"],
            created_at=datetime.fromisoformat(r["created_at"]),
            snippet=r["snippet"] or "",
        )
        for r in rows
    ]
    return SearchResponseOut(query=q, hits=hits)


# ---------- Markdown-Export ----------

@app.get("/conversations/{cid}/export.md")
async def export_markdown(cid: str, user=Depends(require_user)):
    # ABSICHTLICH: exportiert auch locked Chats. Die Chat-Sperre ist ein reines
    # UI-Gate (siehe Design-Kommentar am Chat-Sperre-Block), kein Server-Gate.
    conv = await db.get_conversation(cid, user_id=user["id"])
    if not conv:
        raise HTTPException(404, "Konversation nicht gefunden.")
    messages = await db.list_messages(cid)

    from fastapi.responses import PlainTextResponse
    from datetime import timezone as _tz

    def fmt_date(iso: str) -> str:
        try:
            dt = datetime.fromisoformat(iso)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=_tz.utc)
            return dt.astimezone().strftime("%Y-%m-%d %H:%M")
        except Exception:
            return iso

    title = conv["title"] or "Pocket-Claude-Chat"
    created = fmt_date(conv["created_at"])
    lines: list[str] = [
        f"# {title}",
        "",
        f"_PocketClot export · started {created} · {len(messages)} messages_",
        "",
        "---",
        "",
    ]
    for m in messages:
        role = m["role"]
        when = fmt_date(m["created_at"])
        speaker = {"user": "**You**", "assistant": "**Claude**", "system": "_System_"}.get(
            role, f"**{role}**"
        )
        lines.append(f"### {speaker} · {when}")
        lines.append("")
        lines.append(m["content"] or "")
        if m.get("attachment_ids"):
            atts = await db.get_attachments(m["attachment_ids"])
            for a in atts:
                lines.append(f"\n> 📎 Attachment: `{a['filename']}` ({a['mime_type']}, {a['size_bytes']} bytes)")
        lines.append("")
        lines.append("---")
        lines.append("")
    body = "\n".join(lines)

    safe_title = "".join(c if c.isalnum() or c in " -_." else "_" for c in title)[:60].strip() or "chat"
    headers = {
        "Content-Disposition": f'attachment; filename="{safe_title}.md"',
    }
    return PlainTextResponse(content=body, media_type="text/markdown; charset=utf-8", headers=headers)


# ---------- TTS (Dual-Provider: Cloud TTS + Gemini API) ----------

# Per-User-Settings (in DB-KV abgelegt, scope=user_id):
_KV_TTS_PROVIDER = "tts_provider"   # "grok" | "gemini_web" | "edge_tts"
# Merker fuer die einmalige Umstellung auf Gemini Web (13.09.2026). Bleibt,
# damit alte Werte nicht stoeren; die aktuelle Umstellung ist die auf Grok.
_KV_TTS_WEB_MIGRATED = "tts_provider_geminiweb_migrated"
# Merker fuer die einmalige Umstellung auf Grok Leo (21.10.2026).
_KV_TTS_GROK_MIGRATED = "tts_provider_grok_migrated"
# Stueckeln: "1" an, "0" aus, leer = Vorgabe des Anbieters.
_KV_TTS_CHUNKING_ENABLED = "tts_chunking_enabled"
# Alter Schluessel aus der Zeit der Gemini-API; der Bildbereich liest ihn noch
# als Rueckfall fuer seinen eigenen Schluessel.
_KV_IMAGE_API_KEY_LEGACY_FALLBACK = "image_api_key"


async def _available_providers() -> dict[str, bool]:
    """Welche Anbieter gerade nutzbar sind. Edge braucht keine Anmeldung."""
    grok_ok, web_ok = await asyncio.gather(
        asyncio.to_thread(tts.grok_available),
        asyncio.to_thread(tts.gemini_web_available),
    )
    return {tts.PROVIDER_GROK: grok_ok, tts.PROVIDER_GEMINI_WEB: web_ok, tts.PROVIDER_EDGE_TTS: True}


async def _resolve_provider_with_kv(kv: dict) -> str:
    """Der Anbieter, mit dem fuer diesen Nutzer gerade vorgelesen wird.

    Gewaehlt ist, was im KV steht. Ist das nicht nutzbar (Sitzung abgelaufen,
    Dienst aus) oder ein inzwischen entfernter Anbieter (cloud_tts,
    gemini_api), springt der naechste ein: Grok, Gemini Web, Edge. Sonst waere
    das Vorlesen stumm, bis jemand die Einstellung findet.
    """
    raw = (kv.get(_KV_TTS_PROVIDER) or "").strip()
    avail = await _available_providers()
    if raw in tts.VALID_PROVIDERS and avail.get(raw):
        return raw
    for candidate in (tts.PROVIDER_GROK, tts.PROVIDER_GEMINI_WEB, tts.PROVIDER_EDGE_TTS):
        if avail.get(candidate):
            if raw and raw != candidate:
                log.info("TTS: %r gerade nicht nutzbar, lese mit %s vor", raw, candidate)
            return candidate
    return tts.PROVIDER_EDGE_TTS


def _resolve_chunking_from_kv(kv: dict, provider: str) -> bool:
    """"1" an, "0" aus, sonst die Vorgabe des Anbieters. Grok teilt selbst und
    Gemini Web kann es nicht: dort ist es immer aus."""
    if provider in (tts.PROVIDER_GROK, tts.PROVIDER_GEMINI_WEB):
        return False
    raw = (kv.get(_KV_TTS_CHUNKING_ENABLED) or "").strip()
    if raw == "1":
        return True
    if raw == "0":
        return False
    return tts.chunking_default_for(provider)


async def _resolve_tts_provider(user_id: str) -> tuple[str, bool]:
    """(provider, chunking_enabled) mit einem KV-Zugriff."""
    kv = await db.kv_get_all(scope=user_id)
    provider = await _resolve_provider_with_kv(kv)
    return provider, _resolve_chunking_from_kv(kv, provider)


async def _build_tts_status(user_id: str) -> TtsStatusDto:
    kv = await db.kv_get_all(scope=user_id)
    chosen = (kv.get(_KV_TTS_PROVIDER) or "").strip()
    provider = await _resolve_provider_with_kv(kv)
    avail = await _available_providers()
    chunking_raw = (kv.get(_KV_TTS_CHUNKING_ENABLED) or "").strip()
    return TtsStatusDto(
        # "Eingerichtet" heisst: es wird vorgelesen, notfalls vom einspringenden
        # Anbieter. Dass das nicht der gewaehlte ist, sagt `provider` != Wahl.
        configured=avail.get(provider, False),
        provider=provider,
        chosen_provider=chosen if chosen in tts.VALID_PROVIDERS else provider,
        providers_available=[p for p, ok in avail.items() if ok],
        # Vorgabe-Stimme des GEWAEHLTEN Anbieters: springt gerade ein anderer
        # ein, sollen die Clients die Stimme des gewaehlten behalten.
        default_voice=tts.default_voice_for(chosen if chosen in tts.VALID_PROVIDERS else provider),
        voices=[TtsVoiceDto(**v) for v in tts.CURATED_VOICES],
        chunking_enabled=_resolve_chunking_from_kv(kv, provider),
        chunking_explicit=chunking_raw in ("0", "1"),
    )


@app.get("/tts/status", response_model=TtsStatusDto)
async def tts_status(user=Depends(require_user)) -> TtsStatusDto:
    return await _build_tts_status(user["id"])


@app.put("/tts/provider", response_model=TtsStatusDto)
async def tts_set_provider(body: TtsProviderRequest, user=Depends(require_user)) -> TtsStatusDto:
    """Setzt den Vorlese-Anbieter des Nutzers (grok, gemini_web, edge_tts)."""
    prov = (body.provider or "").strip()
    if prov not in tts.VALID_PROVIDERS:
        raise HTTPException(400, f"Invalid provider {prov!r}. "
                                  f"Allowed: {sorted(tts.VALID_PROVIDERS)}")
    # Die Umstellungs-Merker gleich mitsetzen: wer selbst waehlt, soll beim
    # naechsten Serverstart nicht wieder umgestellt werden.
    async with _settings_lock(user["id"]):
        await db.kv_set_many({
            _KV_TTS_PROVIDER: prov, _KV_TTS_WEB_MIGRATED: "1", _KV_TTS_GROK_MIGRATED: "1",
        }, scope=user["id"])
    log.info("TTS-Provider von user=%s auf %s gesetzt", user["id"], prov)
    return await _build_tts_status(user["id"])


@app.put("/tts/chunking", response_model=TtsStatusDto)
async def tts_set_chunking(body: TtsChunkingRequest, user=Depends(require_user)) -> TtsStatusDto:
    """`enabled=True/False` setzt den Wert, `None` gibt an den Anbieter zurueck."""
    if body.enabled is None:
        await db.kv_set_many({_KV_TTS_CHUNKING_ENABLED: ""}, scope=user["id"])
    else:
        await db.kv_set_many({_KV_TTS_CHUNKING_ENABLED: "1" if body.enabled else "0"},
                             scope=user["id"])
    return await _build_tts_status(user["id"])


@app.get("/messages/{message_id}/audio")
async def tts_message_audio(
    message_id: int,
    voice: str | None = None,
    rate: float | None = None,
    token: str | None = None,  # noqa: ARG001 — von Dep konsumiert
    user=Depends(require_user_header_or_query),
):
    """Synthetisiert den Inhalt einer Message und streamt das Audio.

    Anbieter nach den Einstellungen des Nutzers (Grok, Gemini Web, Edge), mit
    Ausweichen auf den naechsten, wenn einer gerade nicht nutzbar ist.
    `rate` wird auf [0.25, 2.0] begrenzt; Vorgabe 1.0.
    """
    provider, chunking_enabled = await _resolve_tts_provider(user["id"])

    # Message aus DB holen UND prüfen, dass die zugehörige Conversation dem
    # aktuellen User gehört. Sonst könnte ein User mit gültigem Token jede
    # beliebige Message vorlesen lassen.
    from pocket_claude.db import get_db
    async with get_db() as conn:
        cur = await conn.execute(
            """
            SELECT m.content, m.role
            FROM messages m
            JOIN conversations c ON c.id = m.conversation_id
            WHERE m.id = ? AND c.user_id = ?
            """,
            (message_id, user["id"]),
        )
        row = await cur.fetchone()
    if not row:
        raise HTTPException(404, "Message nicht gefunden.")
    content = row["content"]
    if not content or not content.strip():
        raise HTTPException(400, "Message hat keinen Text.")

    chosen_voice = (voice or tts.default_voice_for(provider)).strip()
    chosen_rate = rate if rate is not None else tts.DEFAULT_SPEED
    stream_media_type = tts.media_type_for(provider)

    # Pre-Generation-Cache (provider ist Teil des Keys, damit MP3- und WAV-
    # Cache nicht kollidieren wenn der User mid-Session umschaltet).
    cached = await tts_cache.get(message_id, chosen_voice, chosen_rate, provider)
    if cached is not None:
        log.info(
            "TTS-Cache HIT msg=%d voice=%s rate=%.2f provider=%s (%d KB, %s)",
            message_id, chosen_voice, chosen_rate, provider,
            len(cached.audio) // 1024, cached.media_type,
        )
        from fastapi.responses import Response
        return Response(
            content=cached.audio,
            media_type=cached.media_type,
            headers={
                "Cache-Control": "no-store",
                "Content-Length": str(len(cached.audio)),
                "X-Pocket-Claude-Cache": "hit",
                "X-Pocket-Claude-Provider": provider,
            },
        )

    # Das erste Stueck abwarten, bevor die Antwort beginnt: scheitert der
    # Anbieter gleich zu Beginn (Sitzung eben abgelaufen, Dienst weg), springt
    # der naechste ein. Nach dem ersten Byte geht das nicht mehr, MP3 und Ogg
    # lassen sich nicht mischen.
    avail = await _available_providers()
    order = [provider] + [p for p in (tts.PROVIDER_GROK, tts.PROVIDER_GEMINI_WEB, tts.PROVIDER_EDGE_TTS)
                          if p != provider and avail.get(p)]
    gen = None
    first = b""
    for candidate in order:
        gen = tts.synthesize_chunked(
            content, chosen_voice, chosen_rate, candidate,
            chunking_enabled=chunking_enabled if candidate == provider else False,
        )
        try:
            first = await gen.__anext__()
        except StopAsyncIteration:
            first = b""
        except (tts.TtsSessionExpiredError, tts.TtsTransientError) as e:
            if isinstance(e, tts.TtsSessionExpiredError):
                tts.mark_unavailable(candidate)
            log.warning("TTS: %s scheitert (%s), versuche den naechsten Anbieter",
                        candidate, str(e)[:160])
            gen = None
            continue
        if candidate != provider:
            log.info("TTS: %s springt fuer %s ein", candidate, provider)
            provider = candidate
            stream_media_type = tts.media_type_for(provider)
        break
    if gen is None:
        raise HTTPException(503, "Gerade kann kein Vorlese-Anbieter vorlesen. Bitte gleich nochmal versuchen.")

    async def audio_stream():
        try:
            if first:
                yield first
            async for audio_chunk in gen:
                yield audio_chunk
        except tts.TtsSessionExpiredError as e:
            log.warning("TTS-Stream beendet: Sitzung des Vorlese-Dienstes (%s) fehlt "
                        "oder ist abgelaufen: %s", provider, str(e)[:160])
            return
        except RuntimeError as e:
            log.warning("TTS-Stream RuntimeError (provider=%s): %s", provider, e)
            return  # statt raise: Stream sauber beenden, sonst crasht ASGI
        except asyncio.CancelledError:
            # Client hat die Verbindung geschlossen: weiterreichen, damit die
            # Aufraeumarbeit in synthesize_chunked greift.
            raise
        except Exception:
            log.exception("TTS-Stream-Fehler (provider=%s)", provider)
            return
        finally:
            # Hoerer weg oder Fehler: den Erzeuger sofort schliessen, damit
            # offene Verbindungen (Grok-Stream) nicht haengen bleiben.
            await gen.aclose()

    from fastapi.responses import StreamingResponse
    return StreamingResponse(
        audio_stream(),
        media_type=stream_media_type,
        headers={
            "Cache-Control": "no-store",
            "X-Pocket-Claude-Provider": provider,
            # KEIN Content-Length — wir wissen die Länge erst am Ende.
        },
    )


# ---------- Image Generation (Google Gemini / Nano Banana) ----------

_KV_IMAGE_API_KEY = "image_api_key"

# Bild-Standards des Users. Sie gelten fuer den Bilder-Screen UND fuer das
# `generate_image`-Werkzeug im Chat, damit ein im Chat erzeugtes Bild genauso
# aussieht wie eins vom Bilder-Screen.
_KV_IMAGE_DEFAULT_SIZE = "image_default_size"
_KV_IMAGE_DEFAULT_ASPECT = "image_default_aspect"
_KV_IMAGE_DEFAULT_MODEL = "image_default_model"
_KV_IMAGE_PROVIDER = "image_provider"


def _mask_key(k: str) -> str:
    """Maskiert einen API-Key fürs UI: 'AIzaSy…pPWk'."""
    if not k:
        return ""
    if len(k) <= 10:
        return "•" * len(k)
    return f"{k[:6]}…{k[-4:]}"


@app.get("/images/config")
async def images_config(user=Depends(require_user)):
    """Statische Config plus die Standardwerte des Users.

    `configured` sagt seit dem Umstieg aufs Gateway nicht mehr, ob ein
    API-Schluessel hinterlegt ist, sondern ob ueberhaupt ein Anbieter
    bereitsteht. Sonst wuerde der Bilder-Screen alles verweigern, obwohl
    ueber die Gateways laengst Bilder moeglich sind.
    """
    cfg = image_engine.get_config()
    kv = await db.kv_get_all(scope=user["id"])
    gemini_ok = await gateways.image_target() is not None
    gpt_ok = await gateways.gpt_image_gateway() is not None
    cfg["configured"] = bool(gemini_ok or gpt_ok)
    # Nur die Anbieter anbieten, die es hier auch wirklich gibt. "Beide" nur,
    # wenn es auch wirklich zwei gibt: mit einem Anbieter waere es dasselbe wie
    # dessen eigener Knopf und nur eine Auswahl ohne Unterschied.
    available: set[str] = set()
    if gemini_ok:
        available.add(image_engine.PROVIDER_GEMINI)
    if gpt_ok:
        available.add(image_engine.PROVIDER_GPT)
    if gemini_ok and gpt_ok:
        available.add(image_engine.PROVIDER_BOTH)
    cfg["providers"] = [p for p in cfg["providers"] if p["id"] in available]
    cfg["api_key_masked"] = None
    # Die vom User gesetzten Standardwerte. Nicht gesetzt = der Wert aus
    # image_engine, damit der Client immer etwas Sinnvolles vorbelegen kann.
    # Kanonisiert, damit ein gespeichertes "auto" von frueher hier und beim
    # Zeichnen dasselbe bedeutet: sonst stuende in der App "Beide", waehrend
    # der Server nur einen Anbieter beauftragt.
    provider = image_engine.canonical_provider(kv.get(_KV_IMAGE_PROVIDER))
    # Der Wert kann trotzdem wegfallen, wenn ein Gateway nicht mehr laeuft.
    # Dann stuende in der App kein Knopf auf ausgewaehlt.
    if provider not in available:
        provider = next((p["id"] for p in cfg["providers"]), "")
    cfg["defaults"] = {
        "size": (kv.get(_KV_IMAGE_DEFAULT_SIZE) or "").strip() or cfg["default_image_size"],
        "aspect_ratio": (kv.get(_KV_IMAGE_DEFAULT_ASPECT) or "").strip() or cfg["default_aspect"],
        "model": (kv.get(_KV_IMAGE_DEFAULT_MODEL) or "").strip() or cfg["default_model"],
        "provider": provider,
    }
    return cfg


@app.put("/images/defaults")
async def images_set_defaults(body: dict, user=Depends(require_user)):
    """Setzt Standard-Aufloesung, Seitenverhaeltnis und Bildmodell des Users.

    Ein leerer String setzt den jeweiligen Wert auf den Server-Default zurueck,
    ein fehlendes Feld laesst ihn unveraendert.
    """
    if not isinstance(body, dict):
        raise HTTPException(400, "JSON-Objekt erwartet.")
    cfg = image_engine.get_config()
    valid_sizes = {x["id"] for x in cfg["image_sizes"]}
    valid_aspects = {x["id"] for x in cfg["aspect_ratios"]}

    # Das Bildmodell waehlt seit dem Umstieg aufs Gateway nicht mehr der Nutzer,
    # sondern das Gateway. Ein mitgeschicktes `model` wird deshalb ignoriert
    # statt abgelehnt, damit aeltere App-Staende keinen Fehler bekommen.
    valid_providers = {x["id"] for x in cfg["providers"]}

    mapping = [
        ("size", _KV_IMAGE_DEFAULT_SIZE, valid_sizes),
        ("aspect_ratio", _KV_IMAGE_DEFAULT_ASPECT, valid_aspects),
        ("provider", _KV_IMAGE_PROVIDER, valid_providers),
    ]
    updates: dict[str, str] = {}
    for field, kv_key, allowed in mapping:
        if field not in body:
            continue
        raw = body.get(field)
        if raw is not None and not isinstance(raw, str):
            raise HTTPException(400, f"{field} muss ein String sein.")
        value = (raw or "").strip()
        if value and value not in allowed:
            raise HTTPException(400, f"Unbekannter Wert fuer {field}: {value!r}")
        updates[kv_key] = value
    if updates:
        await db.kv_set_many(updates, scope=user["id"])

    return await images_config(user=user)


@app.put("/images/credentials")
async def images_set_credentials(body: dict, user=Depends(require_user)):
    """Speichert den Gemini-API-Key des Users (per-User, nicht global)."""
    key = (body.get("api_key") or "").strip()
    if not key:
        raise HTTPException(400, "Leerer API-Key.")
    if not key.startswith("AIza"):
        raise HTTPException(400, "Sieht nicht aus wie ein Google-API-Key (sollte mit 'AIza' beginnen).")
    await db.kv_set_many({_KV_IMAGE_API_KEY: key}, scope=user["id"])
    return {"ok": True, "api_key_masked": _mask_key(key)}


@app.delete("/images/credentials", status_code=status.HTTP_204_NO_CONTENT)
async def images_delete_credentials(user=Depends(require_user)):
    # KV-Setting auf leeren String setzen — kein extra delete-Path nötig
    await db.kv_set_many({_KV_IMAGE_API_KEY: ""}, scope=user["id"])
    return JSONResponse(status_code=204, content=None)


# ---------- Voice-Input (Groq Whisper Large v3 Turbo) ----------

_KV_VOICE_GROQ_API_KEY = voice.KV_GROQ_API_KEY


def _voice_status_payload(kv: dict) -> dict:
    """Baut den vollen Voice-Status — Key-Status + Lang-Settings + aktueller
    effektiver Bias-Prompt. Geteilt zwischen GET /voice/config und allen PUT/
    POST-Endpoints, damit der Client immer eine konsistente Snapshot bekommt."""
    api_key = (kv.get(_KV_VOICE_GROQ_API_KEY) or "").strip()
    mode = (kv.get(voice.KV_LANG_MODE) or "auto").strip().lower()
    if mode not in ("auto", "override"):
        mode = "auto"
    override = (kv.get(voice.KV_LANG_OVERRIDE) or "").strip()
    cache = voice.get_prompt_cache(kv)
    # Für die Preview ohne explizite Request-Locale: nehmen wir den Override
    # bzw. „en" als sinnvolle Default-Anzeige.
    preview_lang = voice._to_whisper_code(override or "en")
    prompt_text, prompt_source = voice.resolve_prompt(kv=kv, lang=preview_lang)
    return {
        "configured": bool(api_key),
        "api_key_masked": _mask_key(api_key) if api_key else None,
        "model": voice.GROQ_DEFAULT_MODEL,
        "lang_mode": mode,
        "lang_override": override or None,
        "current_lang": preview_lang,
        "current_prompt": prompt_text,
        "current_prompt_source": prompt_source,
        "bundled_languages": sorted(voice.BUNDLED_PROMPTS.keys()),
        "language_names": voice.LANG_DISPLAY_NAMES,
        "cached_languages": sorted(cache.keys()),
    }


@app.get("/voice/config")
async def voice_config(user=Depends(require_user)):
    """Per-User Voice-Setup: API-Key-Status, Sprach-Override, aktueller
    Bias-Prompt. Wird vom App- + WebUI-Settings-Screen + vom Mic-Button-Check
    benutzt."""
    kv = await db.kv_get_all(scope=user["id"])
    return _voice_status_payload(kv)


@app.put("/voice/credentials")
async def voice_set_credentials(body: dict, user=Depends(require_user)):
    """Speichert den Groq-API-Key des Users (per-User, nicht global).

    Body: `{api_key: str}`. Format-Check: Groq-Keys beginnen mit `gsk_`.
    """
    key = (body.get("api_key") or "").strip()
    if not key:
        raise HTTPException(400, "Leerer API-Key.")
    if not key.startswith("gsk_"):
        raise HTTPException(
            400,
            "Sieht nicht aus wie ein Groq-API-Key (sollte mit 'gsk_' beginnen).")
    await db.kv_set_many({_KV_VOICE_GROQ_API_KEY: key}, scope=user["id"])
    return {"ok": True, "api_key_masked": _mask_key(key)}


@app.delete("/voice/credentials", status_code=status.HTTP_204_NO_CONTENT)
async def voice_delete_credentials(user=Depends(require_user)):
    await db.kv_set_many({_KV_VOICE_GROQ_API_KEY: ""}, scope=user["id"])
    return JSONResponse(status_code=204, content=None)


@app.put("/voice/lang-config")
async def voice_set_lang_config(body: dict, user=Depends(require_user)):
    """Setzt die per-User-Sprache für Voice-Input.

    Body: `{mode: "auto"|"override", locale?: str}`. Bei `auto` folgt
    Whisper der UI-Sprache des Requests; bei `override` wird die angegebene
    Locale verwendet (egal welche Sprache die App grade hat). Locale-Codes
    sind 2-stellig ISO 639-1 (`en`, `de`, `sv`, `ko`, …).
    """
    mode = (body.get("mode") or "").strip().lower()
    if mode not in ("auto", "override"):
        raise HTTPException(400, "mode muss 'auto' oder 'override' sein.")
    locale = (body.get("locale") or "").strip().lower()
    if mode == "override" and not locale:
        raise HTTPException(400, "override braucht eine 'locale'.")
    if locale and not locale.replace("-", "").isalpha():
        raise HTTPException(400, "Ungültiger locale-Code.")
    await db.kv_set_many(
        {
            voice.KV_LANG_MODE: mode,
            voice.KV_LANG_OVERRIDE: locale if mode == "override" else "",
        },
        scope=user["id"],
    )
    kv = await db.kv_get_all(scope=user["id"])
    return _voice_status_payload(kv)


@app.post("/voice/prompt/translate")
async def voice_translate_prompt(body: dict, user=Depends(require_user)):
    """Übersetzt den englischen Default-Bias-Prompt in die angegebene Sprache
    via Anthropic Claude (oneshot, kein Conversation-State).

    Body: `{locale: str, force?: bool}`. `force=true` ignoriert den Cache
    und triggert eine frische Übersetzung. Das Ergebnis landet im Cache
    (KV `voice_prompt_cache`) und kann sofort von /voice/transcribe genutzt
    werden.
    """
    locale = (body.get("locale") or "").strip().lower()
    force = bool(body.get("force"))
    if not locale:
        raise HTTPException(400, "Locale fehlt.")
    if not locale.replace("-", "").isalpha():
        raise HTTPException(400, "Ungültiger locale-Code.")
    lang = voice._to_whisper_code(locale)

    kv = await db.kv_get_all(scope=user["id"])
    if not force:
        cache = voice.get_prompt_cache(kv)
        if lang in cache and cache[lang].strip():
            return {
                "locale": lang,
                "prompt": cache[lang],
                "source": "cache",
            }

    # Bundled? Dann bleibt der Default — kein Claude-Roundtrip nötig.
    if lang in voice.BUNDLED_PROMPTS and not force:
        return {
            "locale": lang,
            "prompt": voice.BUNDLED_PROMPTS[lang],
            "source": "bundled",
        }

    try:
        translated = await voice.translate_bias_prompt(
            target_lang=lang,
            user_id=user["id"],
        )
    except Exception as e:  # noqa: BLE001 — Claude-Fehler werden direkt durchgereicht
        log.warning("Voice-Prompt-Translate user=%s lang=%s failed: %s",
                    user["id"], lang, e)
        raise HTTPException(
            502, f"Übersetzung fehlgeschlagen: {e}"
        ) from e

    # In den per-User-Cache schreiben (merge, nicht überschreiben)
    cache = voice.get_prompt_cache(kv)
    cache[lang] = translated
    import json as _json
    await db.kv_set_many(
        {voice.KV_PROMPT_CACHE: _json.dumps(cache, ensure_ascii=False)},
        scope=user["id"],
    )
    log.info("Voice-Prompt für user=%s lang=%s frisch übersetzt (%d chars)",
             user["id"], lang, len(translated))
    return {
        "locale": lang,
        "prompt": translated,
        "source": "translated",
    }


@app.delete("/voice/prompt/cache/{locale}",
            status_code=status.HTTP_204_NO_CONTENT)
async def voice_delete_cached_prompt(locale: str, user=Depends(require_user)):
    """Löscht einen einzelnen Cache-Eintrag — danach greift wieder der
    Bundled-Default (oder eine frische Übersetzung beim nächsten Translate-
    Call)."""
    kv = await db.kv_get_all(scope=user["id"])
    cache = voice.get_prompt_cache(kv)
    lang = voice._to_whisper_code(locale)
    if lang in cache:
        cache.pop(lang)
        import json as _json
        await db.kv_set_many(
            {voice.KV_PROMPT_CACHE: _json.dumps(cache, ensure_ascii=False)
                                    if cache else ""},
            scope=user["id"],
        )
    return JSONResponse(status_code=204, content=None)


@app.post("/voice/transcribe")
async def voice_transcribe_endpoint(
    file: UploadFile = File(...),
    language: str = Form(default="en"),
    user=Depends(require_user),
):
    """Audio → Transkript via Groq Whisper Large v3 Turbo.

    `language`: UI-Locale aus dem Client (`en`, `de`, `pt-BR`, …). Server
    resolved daraus + dem User-Setting (auto vs. override) die effektive
    Whisper-Sprache + den passenden Bias-Prompt (bundled oder aus dem
    Translation-Cache).
    """
    kv = await db.kv_get_all(scope=user["id"])
    api_key = (kv.get(_KV_VOICE_GROQ_API_KEY) or "").strip()
    if not api_key:
        raise HTTPException(
            400,
            "Kein Groq-API-Key gesetzt. In den Einstellungen unter "
            "'Spracheingabe' eintragen.")

    raw = await file.read()
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(raw) > max_bytes:
        raise HTTPException(
            413,
            f"Audio zu groß (max {settings.max_upload_mb} MB).")
    if not raw:
        raise HTTPException(400, "Audio-Daten leer.")

    effective_lang = voice.resolve_effective_lang(
        kv=kv, request_locale=language,
    )
    bias_prompt, _src = voice.resolve_prompt(kv=kv, lang=effective_lang)

    try:
        text = await voice.transcribe(
            audio_bytes=raw,
            filename=file.filename or "audio.m4a",
            content_type=file.content_type or "audio/mp4",
            api_key=api_key,
            whisper_lang=effective_lang,
            bias_prompt=bias_prompt,
        )
    except voice.VoiceTranscribeError as e:
        log.warning("Voice-Transcribe für user=%s fehlgeschlagen: %s",
                    user["id"], e)
        raise HTTPException(400, str(e)) from e

    log.info("Voice-Transcribe ok user=%s req-lang=%s effective=%s chars=%d",
             user["id"], language, effective_lang, len(text))
    return {"text": text}


@app.post("/images/generate")
async def images_generate(body: dict, user=Depends(require_user)):
    """Generiert ein Bild (oder mehrere Varianten) und speichert die Outputs
    als Attachments. Returnt die neuen Attachment-IDs + Metadaten.

    Body:
      prompt:                  str (required)
      conversation_id:         str (optional: wenn gesetzt, wird die Generation als
                               Assistant-Message im Chat-Stream gespeichert)
      model:                   str (optional, default = neuestes Nano-Banana)
      aspect_ratio:            str (optional, '1:1' | '16:9' | '9:16' | '4:3' | '3:4')
      image_size / size:       str (optional, '1K' | '2K' | '4K')
      count:                   int (optional, default 1, max 4)
      reference_attachment_ids: list[str] (optional, fuer Image-Editing)
    """
    if not isinstance(body, dict):
        raise HTTPException(400, "JSON-Objekt erwartet.")
    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(400, "prompt fehlt.")

    # Anbieter-Vorgabe des Nutzers, falls der Request selbst keine mitschickt.
    kv_img = await db.kv_get_all(scope=user["id"])

    # Referenz-Bilder laden (fuer Image-Editing): read_bytes in to_thread,
    # damit ein 10-MB-Bild nicht den Event-Loop blockiert.
    import asyncio as _asyncio_for_imgs
    ref_ids = body.get("reference_attachment_ids") or []
    raw_refs: list[tuple[str, bytes]] = []
    for aid in ref_ids:
        att = await db.get_attachment(aid, user_id=user["id"])
        if not att:
            raise HTTPException(400, f"Referenz-Attachment {aid} nicht gefunden / nicht Deins.")
        try:
            from pathlib import Path as _P
            raw = await _asyncio_for_imgs.to_thread(_P(str(att["path"])).read_bytes)
        except (OSError, KeyError, TypeError):
            raise HTTPException(500, f"Referenz-Datei {aid} konnte nicht gelesen werden.")
        raw_refs.append((str(att.get("mime_type") or ""), raw))
    # Dieselbe Pruefung wie im Chat-Werkzeug: Groesse, echtes Format, keine
    # Dubletten. Ein eigener API-Client verkleinert nichts von allein.
    references = image_engine.usable_references(raw_refs)
    if ref_ids and not references:
        raise HTTPException(
            400,
            "Keines der Referenz-Bilder ist verwendbar. Erlaubt sind PNG, JPEG "
            "und WebP bis 8 MB.",
        )

    # Generieren: `count` defensiv parsen, sonst crasht der Endpoint mit
    # 500 wenn der Client versehentlich `count="2"` als String schickt.
    try:
        raw_count = body.get("count")
        count_val = int(raw_count) if raw_count not in (None, "") else 1
    except (TypeError, ValueError):
        raise HTTPException(400, f"Invalid count value: {raw_count!r}")

    image_size = (
        body.get("image_size") or body.get("size")
        or (kv_img.get(_KV_IMAGE_DEFAULT_SIZE) or "").strip() or None
    )
    try:
        images = await image_engine.generate(
            prompt=prompt,
            provider=image_engine.canonical_provider(
                (body.get("provider") or "").strip()
                or (kv_img.get(_KV_IMAGE_PROVIDER) or "").strip()
            ),
            model=body.get("model"),
            aspect_ratio=body.get("aspect_ratio"),
            image_size=image_size,
            count=count_val,
            references=references or None,
        )
    except image_engine.ImageGenError as e:
        raise HTTPException(502, str(e))

    # Outputs zentral ueber image_tool als Attachments speichern
    from pocket_claude import image_tool
    out_atts = await image_tool.store_images(images, user_id=user["id"])

    # Optional: Als Assistant-Message in eine Konversation einhaengen, damit es
    # im Chat-Stream auftaucht.
    cid = (body.get("conversation_id") or "").strip()
    saved_message = None
    if cid:
        conv = await db.get_conversation(cid, user_id=user["id"])
        if not conv:
            raise HTTPException(404, "Konversation nicht gefunden.")
        # User-Prompt als 'user'-Message, dann die Bilder als 'assistant'-Message
        await db.add_message(
            cid, role="user",
            content=_format_image_user_prompt(prompt, body),
            attachment_ids=ref_ids,
            tokens=max(1, len(prompt) // 4),
        )
        assistant_text = _format_image_assistant_text(prompt, body, images)
        msg_id = await db.add_message(
            cid, role="assistant",
            content=assistant_text,
            attachment_ids=[a["id"] for a in out_atts],
            tokens=0,
        )
        # Gleicher kurzer Auto-Titel wie im Chat-Flow (1-2 Woerter statt der
        # verbatim ersten Zeile). Non-streaming: Client zieht den Titel beim
        # naechsten Laden der Liste.
        await claude_engine.generate_conversation_title(cid, prompt, user_id=user["id"])
        saved_message = {"id": msg_id, "conversation_id": cid}

    return {
        "ok": True,
        "model": body.get("model") or image_engine.get_config()["default_model"],
        "aspect_ratio": body.get("aspect_ratio") or "1:1",
        "count": len(out_atts),
        "attachments": out_atts,
        "message": saved_message,
    }


def _format_image_user_prompt(prompt: str, body: dict) -> str:
    """Lesbarer Eintrag im Chat-Verlauf für die User-Seite einer Bild-Generation."""
    bits = [f"🎨 **Bild generieren:** {prompt}"]
    if body.get("aspect_ratio"):
        bits.append(f"_Format: {body['aspect_ratio']}_")
    # `count` kann String oder Int sein; defensiv parsen statt int()-crash.
    try:
        c = int(body.get("count") or 1)
    except (TypeError, ValueError):
        c = 1
    if c > 1:
        bits.append(f"_Varianten: {c}_")
    return " · ".join(bits)


def _format_image_assistant_text(prompt: str, body: dict,
                                  images: list[image_engine.GeneratedImage]) -> str:
    """Kurzer Text-Begleiter zur Assistant-Message mit den Bildern."""
    model = body.get("model") or image_engine.get_config()["default_model"]
    extra = next((img.text for img in images if img.text), None)
    parts = [f"_{len(images)}× Bild generiert mit {model}_"]
    if extra:
        parts.append(extra)
    return "\n\n".join(parts)


# ---------- UI-Settings ----------

# Oberflaechen-Einstellungen, die App und Web-UI teilen. Beide lesen und
# schreiben dieselben Schluessel, deshalb hat ein Nutzer auf dem Handy und am
# Desktop dieselben Einstellungen.
#
# Bewusst eine feste Liste: im selben KV-Bereich liegen auch PIN-Hash,
# API-Schluessel und Anmeldemodus. Frueher gab GET alles davon an jeden Client
# heraus, und PUT konnte es ueberschreiben.
UI_SETTING_KEYS: frozenset[str] = frozenset({
    "theme",               # system | light | dark
    "paletteLight", "paletteDark",
    "effort",              # Denktiefe fuer Claude (alter Einzelwert)
    "effortByFamily",      # JSON {"claude": "high", "gemini": ...}
    "chatModel",           # Vorauswahl fuer neue Chats, "" = Claude
    "defaultModelByFamily",  # JSON {"claude": "opus", ...}
    "spMode", "spCustom",  # System-Prompt-Modus und eigener Text
    "ttsVoice", "ttsSpeed", "autoSpeak",
    "autoSpeakByChat",     # JSON {"<cid>": true}
    "collapseUserMsgs",
    "autoSend", "autoSendSilenceMs",
    "sidebar",             # nur Web: Seitenleiste eingeklappt
})
_UI_SETTING_MAX_LEN = 64_000
# JSON-Objekte, deren Eintraege einzeln zusammengefuehrt werden, wenn der Client
# ein Objekt statt eines Strings schickt: {"gemini": "low"} aendert nur Gemini,
# `null` entfernt einen Eintrag. Sonst wuerde ein Geraet mit altem Stand beim
# Umstellen EINER Familie die anderen zuruecksetzen. Ein String ersetzt weiter
# das Ganze (aeltere Clients, Import, Erstabgleich).
_UI_MAP_KEYS = frozenset({"effortByFamily", "defaultModelByFamily", "autoSpeakByChat"})
# Lesen, Zusammenfuehren und Schreiben pro User am Stueck, sonst verliert von
# zwei gleichzeitigen Aenderungen verschiedener Eintraege eine. Der Server
# laeuft als ein Prozess, ein asyncio-Lock reicht.
_UI_SETTINGS_LOCKS: dict[str, asyncio.Lock] = {}


def _settings_lock(user_id: str) -> asyncio.Lock:
    """Eine Sperre pro Nutzer fuer alles, was Einstellungen liest und dann
    schreibt: Abgleich, Anbieterwahl, Import und die einmaligen Umstellungen.
    Sonst koennte eine Umstellung eine gleichzeitig getroffene Wahl ueberschreiben."""
    return _UI_SETTINGS_LOCKS.setdefault(user_id, asyncio.Lock())


@app.get("/ui-settings")
async def get_ui_settings(user=Depends(require_user)):
    """Gemeinsame Oberflaechen-Einstellungen des Users (siehe UI_SETTING_KEYS)."""
    values = await db.kv_get_all(scope=user["id"])
    return {"settings": {k: v for k, v in values.items() if k in UI_SETTING_KEYS}}


@app.put("/ui-settings")
async def put_ui_settings(body: dict, user=Depends(require_user)):
    """Teil-Update: nur die mitgeschickten Schluessel aendern sich. Unbekannte
    Schluessel werden ignoriert, damit ein neuerer Client mit einem alten
    Server nicht scheitert."""
    if not isinstance(body, dict):
        raise HTTPException(400, "JSON-Objekt erwartet.")
    async with _settings_lock(user["id"]):
        return await _put_ui_settings_locked(body, user)


async def _put_ui_settings_locked(body: dict, user: dict) -> dict:
    current: dict | None = None
    flat: dict[str, str] = {}
    for k, v in body.items():
        key = str(k)
        if v is None or key not in UI_SETTING_KEYS:
            continue
        if isinstance(v, dict):
            if key not in _UI_MAP_KEYS:
                raise HTTPException(400, f"{key}: Text erwartet.")
            if current is None:
                current = await db.kv_get_all(scope=user["id"])
            try:
                merged = json.loads(current.get(key) or "{}")
            except json.JSONDecodeError:
                merged = {}
            if not isinstance(merged, dict):
                merged = {}
            for entry, value in v.items():
                if value is None:
                    merged.pop(str(entry), None)
                else:
                    merged[str(entry)] = value
            flat[key] = json.dumps(merged, ensure_ascii=False, separators=(",", ":"))
        else:
            flat[key] = str(v)
    if any(len(v) > _UI_SETTING_MAX_LEN for v in flat.values()):
        raise HTTPException(413, "Einstellung zu gross.")
    if flat:
        await db.kv_set_many(flat, scope=user["id"])
    return {"ok": True, "count": len(flat)}


# ---------- Skills (per-User-Default + per-Chat-Override) ----------
#
# Welche Tools darf Claude pro Konversation aufrufen? Aktuell drei:
#   - web_search    → "WebSearch"
#   - web_fetch     → "WebFetch"
#   - code_execution → "Bash"
#
# Persistenz:
#   - User-Default: KV-Tabelle (scope=user_id), Key = _KV_SKILLS_DEFAULTS,
#     Wert = JSON-Dump von SkillsDto.
#   - Chat-Override: conversations.skills_override (JSON oder NULL).
#     NULL = User-Default greift.

_KV_SKILLS_DEFAULTS = "skills_defaults"

# Server-weiter Hardcoded-Default (greift, wenn der User noch nichts gesetzt
# hat). Kein per-User-Setup nötig → out-of-the-box funktioniert WebSearch.
_SERVER_DEFAULT_SKILLS = SkillsDto(
    web_search=True,
    web_fetch=True,
    code_execution=False,
)


def _skills_to_json(s: SkillsDto) -> str:
    return json.dumps(s.model_dump(), separators=(",", ":"))


def _skills_from_json(raw: str | None) -> SkillsDto | None:
    """Parsed einen JSON-Skills-String. None bei NULL/leer/kaputt."""
    if not raw:
        return None
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            return None
        return SkillsDto(**data)
    except (json.JSONDecodeError, TypeError, ValueError):
        log.warning("Skills-JSON nicht parsebar: %r", raw[:200])
        return None


async def _resolve_user_default_skills(user_id: str) -> SkillsDto:
    """User-Default-Skills lesen (Fallback: Server-Default)."""
    kv = await db.kv_get_all(scope=user_id)
    return _skills_from_json(kv.get(_KV_SKILLS_DEFAULTS)) or _SERVER_DEFAULT_SKILLS


async def _resolve_effective_skills(
    user_id: str, conv_skills_override: str | None,
    gem_skills_override: str | None = None,
) -> tuple[SkillsDto, bool]:
    """Effektive Skills für eine bestimmte Conversation.

    Reihenfolge: Per-Chat-Override > Gem-Skills > User-Default > Server-Default.
    Returnt `(skills, is_override)`. `is_override=True` heißt: der Chat hat
    eine eigene Einstellung (Chat-Override oder Gem), die vom User-Default
    abweichen kann.
    """
    override = _skills_from_json(conv_skills_override)
    if override is not None:
        return override, True
    gem_skills = _skills_from_json(gem_skills_override)
    if gem_skills is not None:
        return gem_skills, True
    return await _resolve_user_default_skills(user_id), False


@app.get("/skills/defaults", response_model=SkillsDto)
async def get_skills_defaults(user=Depends(require_user)) -> SkillsDto:
    """User-Default-Skills (gelten für alle neuen + nicht-überschriebenen Chats)."""
    return await _resolve_user_default_skills(user["id"])


@app.put("/skills/defaults", response_model=SkillsDto)
async def set_skills_defaults(
    body: SkillsDefaultsRequest, user=Depends(require_user),
) -> SkillsDto:
    await db.kv_set_many(
        {_KV_SKILLS_DEFAULTS: _skills_to_json(body.skills)},
        scope=user["id"],
    )
    return body.skills


@app.get("/conversations/{cid}/skills", response_model=ConversationSkillsResponse)
async def get_conversation_skills(
    cid: str, user=Depends(require_user),
) -> ConversationSkillsResponse:
    conv = await db.get_conversation(cid, user_id=user["id"])
    if not conv:
        raise HTTPException(404, "Konversation nicht gefunden.")
    skills, is_override = await _resolve_effective_skills(
        user["id"], conv.get("skills_override"),
    )
    return ConversationSkillsResponse(skills=skills, is_override=is_override)


@app.put("/conversations/{cid}/skills", response_model=ConversationSkillsResponse)
async def set_conversation_skills(
    cid: str, body: ConversationSkillsRequest, user=Depends(require_user),
) -> ConversationSkillsResponse:
    """Setzt oder löscht (skills=null) den Per-Chat-Override."""
    conv = await db.get_conversation(cid, user_id=user["id"])
    if not conv:
        raise HTTPException(404, "Konversation nicht gefunden.")
    override_json = _skills_to_json(body.skills) if body.skills is not None else None
    ok = await db.set_conversation_skills_override(
        cid, override_json, user_id=user["id"],
    )
    if not ok:
        raise HTTPException(404, "Konversation nicht gefunden.")
    skills, is_override = await _resolve_effective_skills(
        user["id"], override_json,
    )
    return ConversationSkillsResponse(skills=skills, is_override=is_override)


# ---------- /me + User-Verwaltung (Admin) ----------

def _user_public(u: dict) -> dict:
    """Reduziert ein User-Dict auf API-safe Felder (kein password_hash, kein
    bearer)."""
    return {
        "id": u["id"],
        "name": u["name"],
        "is_admin": bool(u.get("is_admin")),
        "must_change_password": bool(u.get("must_change_password")),
        "has_password": bool(u.get("password_hash")),
        "created_at": u.get("created_at"),
        # Aendert sich mit jedem neuen Profilbild; die Clients haengen ihn an
        # die Bild-URL, damit kein altes Bild aus dem Cache kommt. None = keins.
        "avatar_version": _avatar_version(u["id"]),
    }


@app.get("/me")
async def get_me(user=Depends(require_user)):
    """Aktueller User-Info — App und Web-UI fragen das nach Login, um zu
    wissen, ob Admin-Features sichtbar gemacht werden sollen."""
    return _user_public(user)


# ---------- Profilbilder ----------
#
# Eine Datei pro User unter data/avatars/<user_id>. Verkleinert wird im Client
# (Web-UI per Canvas auf 256 px), der Server prueft nur Format und Groesse und
# braucht dafuer keine Bildbibliothek.

_AVATAR_MAX_BYTES = 512 * 1024
_AVATAR_DIR = settings.data_dir / "avatars"


def _avatar_path(user_id: str):
    # User-IDs sind serverseitig erzeugt ("usr_" + urlsafe), trotzdem nur
    # harmlose Zeichen in einen Dateinamen lassen.
    safe = "".join(c for c in user_id if c.isalnum() or c in "-_")
    return _AVATAR_DIR / safe


def _avatar_version(user_id: str) -> int | None:
    # Millisekunden: zwei Uploads in derselben Sekunde muessen verschiedene
    # URLs ergeben, sonst bliebe das erste Bild im Cache.
    try:
        return _avatar_path(user_id).stat().st_mtime_ns // 1_000_000
    except OSError:
        return None


def _avatar_mime(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


async def _store_avatar(user_id: str, file: UploadFile) -> None:
    data = await file.read(_AVATAR_MAX_BYTES + 1)
    if len(data) > _AVATAR_MAX_BYTES:
        raise HTTPException(413, "Profilbild zu gross (hoechstens 512 KB).")
    if _avatar_mime(data) is None:
        raise HTTPException(415, "Profilbild muss PNG, JPEG oder WebP sein.")
    _AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    target = _avatar_path(user_id)
    tmp = target.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.replace(target)


def _remove_avatar(user_id: str) -> None:
    _avatar_path(user_id).unlink(missing_ok=True)


@app.get("/users/{user_id}/avatar")
async def get_avatar(
    user_id: str,
    token: str | None = None,  # noqa: ARG001 — wird von der Dep konsumiert
    user=Depends(require_user_header_or_query),
):
    """Profilbild. Das eigene darf jeder sehen, fremde nur der Admin (fuer die
    Benutzerliste). `?token=` wie bei Anhaengen, damit <img src> geht."""
    if user_id != user["id"] and not user.get("is_admin"):
        raise HTTPException(403, "Kein Zugriff.")
    path = _avatar_path(user_id)
    try:
        data = path.read_bytes()
    except OSError:
        raise HTTPException(404, "Kein Profilbild.")
    from fastapi.responses import Response
    return Response(
        content=data,
        media_type=_avatar_mime(data) or "application/octet-stream",
        # Die URL traegt die Version, also darf der Browser lange cachen.
        headers={"Cache-Control": "private, max-age=31536000"},
    )


@app.put("/me/avatar")
async def put_my_avatar(file: UploadFile = File(...), user=Depends(require_user)):
    await _store_avatar(user["id"], file)
    return _user_public(user)


@app.delete("/me/avatar")
async def delete_my_avatar(user=Depends(require_user)):
    _remove_avatar(user["id"])
    return _user_public(user)


# ---------- Auth (Login/Logout/Password) ----------

@app.post("/auth/login")
async def auth_login(
    request: Request,
    body: dict,
    user_agent: str | None = Header(default=None, alias="User-Agent"),
):
    """Login mit Username + Passwort. Erstellt eine neue Session und liefert
    `{token, user}` zurück. Bei Migration aus der Token-Only-Zeit akzeptiert
    der `password`-Wert auch das alte Bearer-Token (einmalig, bis ein echtes
    Passwort gesetzt wurde — `must_change_password=true` im Response signalisiert
    das dem Client)."""
    source_ip = client_ip(request)
    login_attempt = login_throttler.reserve(source_ip)
    if login_attempt.retry_after:
        log.warning(
            "LOGIN_THROTTLED ip=%s retry_after=%ds",
            source_ip,
            login_attempt.retry_after,
        )
        raise throttle_error(login_attempt.retry_after)

    if not isinstance(body, dict):
        raise HTTPException(400, "JSON-Objekt erwartet.")
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    if not username or not password:
        raise HTTPException(400, "Username und Passwort erforderlich.")

    target = await db.get_user_by_name(username)
    if target is None:
        # Generische Fehlermeldung — kein Username-Enumeration-Leak
        raise HTTPException(401, "Username oder Passwort falsch.")

    pw_ok = False
    if target.get("password_hash"):
        # Normaler Pfad: scrypt-Verify (verify_password nutzt intern compare_digest).
        pw_ok = db.verify_password(password, target["password_hash"])
    else:
        # Legacy-User ohne Passwort: das alte API-Token gilt einmalig als „Passwort".
        # Nach Login MUSS er ein echtes Passwort setzen (must_change_password=1 wird
        # gleich gesetzt). compare_digest gegen Timing-Leaks.
        import hmac as _hmac
        legacy_token = target.get("token") or ""
        if legacy_token and _hmac.compare_digest(password, legacy_token):
            pw_ok = True
            # must_change_password=1 setzen, damit der Client den Forced-Change-
            # Dialog zeigt. Wird beim ersten POST /auth/change-password wieder
            # auf 0 gestellt.
            if not target.get("must_change_password"):
                await db.set_must_change_password(target["id"], True)
                target["must_change_password"] = 1

    if not pw_ok:
        raise HTTPException(401, "Username oder Passwort falsch.")

    login_throttler.record_success(login_attempt)
    token = await db.create_session(target["id"], user_agent=user_agent)
    return {
        "token": token,
        "user": _user_public(target),
    }


@app.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def auth_logout(user=Depends(require_user)):
    """Beendet die aktuelle Session (nur die, nicht alle Geräte des Users)."""
    bearer = user.get("__bearer__")
    if bearer:
        await db.delete_session(bearer)
    return JSONResponse(status_code=204, content=None)


@app.post("/auth/change-password")
async def auth_change_password(body: dict, user=Depends(require_user)):
    """Passwort ändern. Wenn der User `must_change_password=1` hat (Forced
    Change nach Reset oder Migration), darf das alte Passwort weggelassen
    werden — wir vertrauen der bestehenden Session.

    Body: `{old_password?: str, new_password: str, logout_other_sessions?: bool}`.
    Erfolg: 200 mit `{ok: true}` und der aktuellen Session bleibt gültig;
    andere Sessions werden auf Wunsch invalidiert.
    """
    if not isinstance(body, dict):
        raise HTTPException(400, "JSON-Objekt erwartet.")
    new_pw = body.get("new_password") or ""
    if len(new_pw) < 8:
        raise HTTPException(400, "Passwort muss mind. 8 Zeichen lang sein.")

    must_change = bool(user.get("must_change_password"))
    old_pw = body.get("old_password") or ""

    if not must_change:
        # Normaler Path: altes Passwort muss verifiziert werden
        if not old_pw:
            raise HTTPException(400, "Altes Passwort erforderlich.")
        if not db.verify_password(old_pw, user.get("password_hash")):
            raise HTTPException(401, "Altes Passwort falsch.")
    # else: Forced-Change — kein old_pw nötig, Session reicht als Beweis

    await db.set_user_password(user["id"], new_pw, must_change=False)

    if body.get("logout_other_sessions"):
        bearer = user.get("__bearer__")
        await db.delete_sessions_for_user(user["id"], except_token=bearer)

    return {"ok": True}


@app.get("/auth/sessions")
async def auth_list_sessions(user=Depends(require_user)):
    """Aktive Sessions des aktuellen Users — fürs Settings-„aktive Geräte"-UI."""
    sessions = await db.list_sessions_for_user(user["id"])
    bearer = user.get("__bearer__")
    return {"sessions": [
        {
            "id": s["token"][:12] + "…",  # nicht den vollen Token leaken
            "is_current": s["token"] == bearer,
            "created_at": s["created_at"],
            "last_seen_at": s["last_seen_at"],
            "user_agent": s["user_agent"] or "",
        }
        for s in sessions
    ]}


@app.post("/auth/logout-all", status_code=status.HTTP_204_NO_CONTENT)
async def auth_logout_all(user=Depends(require_user)):
    """Aus allen Sessions ausloggen (inkl. der aktuellen)."""
    await db.delete_sessions_for_user(user["id"])
    return JSONResponse(status_code=204, content=None)


# ---------- Claude auth mode (Pro/Max | direct API | Bedrock) ----------

@app.get("/me/claude-auth", response_model=ClaudeAuthDto)
async def get_claude_auth(user=Depends(require_user)):
    """Return the current user's Claude provider config (secrets masked)."""
    kv = await db.kv_get_all(scope=user["id"])
    return ClaudeAuthDto(
        mode=kv.get(auth_modes.KV_MODE) or auth_modes.MODE_PRO_MAX,
        api_key_masked=auth_modes.mask_secret(kv.get(auth_modes.KV_API_KEY)),
        aws_region=kv.get(auth_modes.KV_AWS_REGION) or "",
        aws_access_key_id_masked=auth_modes.mask_secret(kv.get(auth_modes.KV_AWS_ACCESS_KEY_ID)),
        aws_secret_access_key_masked=auth_modes.mask_secret(kv.get(auth_modes.KV_AWS_SECRET_ACCESS_KEY)),
        aws_session_token_masked=auth_modes.mask_secret(kv.get(auth_modes.KV_AWS_SESSION_TOKEN)),
        bedrock_opus_model=kv.get(auth_modes.KV_BEDROCK_OPUS) or auth_modes.DEFAULT_BEDROCK_OPUS,
        bedrock_sonnet_model=kv.get(auth_modes.KV_BEDROCK_SONNET) or auth_modes.DEFAULT_BEDROCK_SONNET,
        bedrock_haiku_model=kv.get(auth_modes.KV_BEDROCK_HAIKU) or auth_modes.DEFAULT_BEDROCK_HAIKU,
        bedrock_model_alias=kv.get(auth_modes.KV_BEDROCK_ALIAS) or auth_modes.DEFAULT_BEDROCK_ALIAS,
        default_model=kv.get(auth_modes.KV_DEFAULT_MODEL) or "",
        api_key_set=bool(kv.get(auth_modes.KV_API_KEY)),
        aws_access_key_set=bool(kv.get(auth_modes.KV_AWS_ACCESS_KEY_ID)),
        aws_secret_set=bool(kv.get(auth_modes.KV_AWS_SECRET_ACCESS_KEY)),
    )


@app.put("/me/claude-auth", response_model=ClaudeAuthDto)
async def update_claude_auth(body: ClaudeAuthUpdateRequest, user=Depends(require_user)):
    """Partial update. Setting a credential field to empty clears it."""
    updates: dict[str, str] = {}
    mode_changed = False

    if body.mode is not None:
        if body.mode not in auth_modes.VALID_MODES:
            raise HTTPException(
                400,
                f"Invalid mode {body.mode!r}. Allowed: {sorted(auth_modes.VALID_MODES)}",
            )
        # Detect whether this is a real switch — if so, we need to drop the
        # cached CLI session IDs of existing conversations so they don't try
        # to resume a session that belonged to the previous provider.
        prior_mode = await auth_modes.get_mode(user["id"])
        if body.mode != prior_mode:
            mode_changed = True
        updates[auth_modes.KV_MODE] = body.mode

    if body.bedrock_model_alias is not None:
        v = body.bedrock_model_alias.strip().lower()
        if v and v not in ("opus", "sonnet", "haiku"):
            raise HTTPException(
                400,
                f"Invalid bedrock_model_alias {body.bedrock_model_alias!r}. "
                f"Allowed: opus, sonnet, haiku",
            )

    # Pre-flight: switching to bedrock without AWS credentials is a recipe
    # for opaque downstream errors. Reject it eagerly with a clear message.
    if body.mode == "bedrock":
        kv = await db.kv_get_all(scope=user["id"])
        has_akid = bool(
            (body.aws_access_key_id and body.aws_access_key_id.strip())
            or kv.get(auth_modes.KV_AWS_ACCESS_KEY_ID)
        )
        has_secret = bool(
            (body.aws_secret_access_key and body.aws_secret_access_key.strip())
            or kv.get(auth_modes.KV_AWS_SECRET_ACCESS_KEY)
        )
        if not (has_akid and has_secret):
            raise HTTPException(
                400,
                "Bedrock mode requires AWS credentials. Set aws_access_key_id + "
                "aws_secret_access_key first (or include them in this request).",
            )

    # Map of (incoming-field, kv-key). String fields: empty string clears.
    field_map = (
        ("api_key", auth_modes.KV_API_KEY),
        ("aws_region", auth_modes.KV_AWS_REGION),
        ("aws_access_key_id", auth_modes.KV_AWS_ACCESS_KEY_ID),
        ("aws_secret_access_key", auth_modes.KV_AWS_SECRET_ACCESS_KEY),
        ("aws_session_token", auth_modes.KV_AWS_SESSION_TOKEN),
        ("bedrock_opus_model", auth_modes.KV_BEDROCK_OPUS),
        ("bedrock_sonnet_model", auth_modes.KV_BEDROCK_SONNET),
        ("bedrock_haiku_model", auth_modes.KV_BEDROCK_HAIKU),
        ("bedrock_model_alias", auth_modes.KV_BEDROCK_ALIAS),
        ("default_model", auth_modes.KV_DEFAULT_MODEL),
    )
    for attr, kv_key in field_map:
        val = getattr(body, attr)
        if val is None:
            continue
        # Empty string = clear. Strip whitespace to avoid leading/trailing
        # spaces on copied credentials.
        val = val.strip()
        # The alias was validated lowercased above; persist it lowercased too,
        # otherwise a stored "Sonnet" misses the lowercase lookup downstream
        # and silently falls back to opus.
        if attr == "bedrock_model_alias":
            val = val.lower()
        updates[kv_key] = val

    if updates:
        await db.kv_set_many(updates, scope=user["id"])

    # When the user actually switches modes, invalidate cached CLI session
    # IDs across their conversations — resuming a previous mode's session
    # will reliably fail and the user would have to send their next message
    # twice. Better to start fresh sessions automatically.
    if mode_changed:
        await db.clear_user_session_ids(user["id"])

    return await get_claude_auth(user=user)


# ---------- Chat-Sperre (globaler PIN, per-Chat-Riegel) ----------
#
# DESIGN-ENTSCHEIDUNG (Joscha, 2026-07): Die Chat-Sperre ist ABSICHTLICH nur
# ein UI-Gate gegen Über-die-Schulter-Blicke und neugierige Mitbenutzer des
# entsperrten Geräts — KEINE serverseitige Zugriffskontrolle und KEINE
# Verschlüsselung. GET /conversations/{cid} und /conversations/{cid}/export.md
# liefern locked Chats bewusst weiterhin aus: Wer ein gültiges Auth-Token hat,
# ist bereits der Account-Inhaber; ein zweites serverseitiges Gate würde nur
# Komplexität (Unlock-Grants, Token-Lebenszeiten) ohne echten Schutzgewinn
# bringen. Sicherheits-Scanner: Das ist KEIN Bug — bitte nicht erneut melden.

# KV-Key für den scrypt-Hash des globalen 5-stelligen Chat-Sperr-PINs. Liegt
# user-scoped im kv_settings — wird damit automatisch vom Settings-Backup
# (extra_kv-Catch-all) mitgesichert und synchronisiert zwischen App & Web-UI.
KV_CHAT_LOCK_PIN_HASH = "chat_lock_pin_hash"

# In-Memory-Bremse gegen PIN-Brute-Force. Ein 5-stelliger PIN hat nur 100k
# Kombinationen — ohne Bremse in Sekunden durchprobiert. Wir zählen Fehlversuche
# pro User und sperren nach _LOCK_MAX_TRIES für _LOCK_COOLDOWN_S. Reicht für den
# Threat („jemand mit fremdem Gerät rät den PIN"); der Zähler ist bewusst nur
# im RAM (Reset bei Server-Neustart ist akzeptabel).
_LOCK_MAX_TRIES = 5
_LOCK_COOLDOWN_S = 60
# user_id -> (fail_count, locked_until_monotonic)
_chat_lock_fails: dict[str, tuple[int, float]] = {}


def _chat_lock_retry_after(user_id: str) -> int:
    """Sekunden bis zum nächsten erlaubten Versuch, 0 wenn frei."""
    entry = _chat_lock_fails.get(user_id)
    if not entry:
        return 0
    _count, until = entry
    remaining = until - _time.monotonic()
    return int(remaining) + 1 if remaining > 0 else 0


def _chat_lock_register_fail(user_id: str) -> None:
    count, prev_until = _chat_lock_fails.get(user_id, (0, 0.0))
    now = _time.monotonic()
    # Ist ein früherer Lockout abgelaufen, fangen wir frisch an zu zählen —
    # sonst würde nach dem ersten 60-s-Lockout JEDER weitere Fehlversuch sofort
    # wieder 60 s sperren (statt erneut 5 Versuche zu erlauben).
    if prev_until and now >= prev_until:
        count = 0
    count += 1
    until = now + _LOCK_COOLDOWN_S if count >= _LOCK_MAX_TRIES else 0.0
    _chat_lock_fails[user_id] = (count, until)


def _chat_lock_reset(user_id: str) -> None:
    _chat_lock_fails.pop(user_id, None)


def _validate_pin(pin: str) -> str:
    """Normalisiert + validiert einen PIN: exakt 5 Ziffern. Wirft 400 sonst."""
    pin = (pin or "").strip()
    if len(pin) != 5 or not pin.isdigit():
        raise HTTPException(400, "PIN muss aus genau 5 Ziffern bestehen.")
    return pin


@app.get("/me/chat-lock", response_model=ChatLockStatusDto)
async def get_chat_lock(user=Depends(require_user)) -> ChatLockStatusDto:
    """Ist ein globaler Chat-Sperr-PIN gesetzt? (Hash wird nie ausgeliefert.)"""
    kv = await db.kv_get_all(scope=user["id"])
    return ChatLockStatusDto(is_set=bool(kv.get(KV_CHAT_LOCK_PIN_HASH)))


@app.put("/me/chat-lock", response_model=ChatLockStatusDto)
async def set_chat_lock(body: ChatLockSetRequest, user=Depends(require_user)) -> ChatLockStatusDto:
    """PIN setzen oder ändern. Wenn schon einer existiert, muss `current_pin`
    stimmen. Speichert nur den scrypt-Hash."""
    new_pin = _validate_pin(body.pin)
    kv = await db.kv_get_all(scope=user["id"])
    existing = kv.get(KV_CHAT_LOCK_PIN_HASH)
    if existing:
        # Ändern erfordert den aktuellen PIN.
        if not db.verify_password(body.current_pin or "", existing):
            raise HTTPException(401, "Aktueller PIN falsch.")
    await db.kv_set_many(
        {KV_CHAT_LOCK_PIN_HASH: db.hash_password(new_pin)}, scope=user["id"],
    )
    _chat_lock_reset(user["id"])
    return ChatLockStatusDto(is_set=True)


@app.post("/me/chat-lock/clear", response_model=ChatLockStatusDto)
async def clear_chat_lock(body: ChatLockClearRequest, user=Depends(require_user)) -> ChatLockStatusDto:
    """PIN entfernen (erfordert aktuellen PIN). Entsperrt implizit alle Chats,
    damit kein Chat mit gesetztem `locked`-Flag ohne PIN unerreichbar bleibt."""
    kv = await db.kv_get_all(scope=user["id"])
    existing = kv.get(KV_CHAT_LOCK_PIN_HASH)
    if existing and not db.verify_password(body.current_pin or "", existing):
        raise HTTPException(401, "Aktueller PIN falsch.")
    # Hash löschen (leerer String = clear, wie bei den anderen KV-Secrets).
    await db.kv_set_many({KV_CHAT_LOCK_PIN_HASH: ""}, scope=user["id"])
    # Alle locked-Flags des Users räumen — sonst wären Chats markiert-gesperrt
    # ohne dass ein PIN existiert (die Clients ignorieren das zwar, aber sauber
    # ist sauber).
    await db.clear_user_locks(user["id"])
    _chat_lock_reset(user["id"])
    return ChatLockStatusDto(is_set=False)


@app.post("/me/chat-lock/verify", response_model=ChatLockVerifyResponse)
async def verify_chat_lock(body: ChatLockVerifyRequest, user=Depends(require_user)) -> ChatLockVerifyResponse:
    """Prüft einen PIN gegen den gespeicherten Hash. Mit Brute-Force-Bremse."""
    retry_after = _chat_lock_retry_after(user["id"])
    if retry_after > 0:
        return ChatLockVerifyResponse(ok=False, retry_after_seconds=retry_after)
    kv = await db.kv_get_all(scope=user["id"])
    existing = kv.get(KV_CHAT_LOCK_PIN_HASH)
    # Kein PIN gesetzt → nichts zu entsperren; als „ok" behandeln, damit ein
    # verwaistes locked-Flag den Client nicht dauerhaft aussperrt.
    if not existing:
        return ChatLockVerifyResponse(ok=True)
    if db.verify_password((body.pin or "").strip(), existing):
        _chat_lock_reset(user["id"])
        return ChatLockVerifyResponse(ok=True)
    _chat_lock_register_fail(user["id"])
    return ChatLockVerifyResponse(ok=False, retry_after_seconds=_chat_lock_retry_after(user["id"]))


# ---------- Gems (Custom Agents) ----------

def _json_str_list(raw: str | None) -> list[str]:
    """Parsed ein JSON-Array von Strings. Leere/kaputte Werte → []."""
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [str(x) for x in data if isinstance(x, str) and x.strip()]


async def _gem_to_dto(row: dict) -> GemDto:
    files = await db.get_gem_files(row["id"])
    return GemDto(
        id=row["id"],
        name=row["name"],
        emoji=row.get("emoji") or "",
        description=row.get("description") or "",
        instructions=row.get("instructions") or "",
        conversation_starters=_json_str_list(row.get("conversation_starters")),
        model=(row.get("model") or None),
        effort=(row.get("effort") or None),
        skills=_skills_from_json(row.get("skills")),
        is_builtin=bool(row.get("is_builtin", 0)),
        files=[
            GemFileDto(
                id=f["id"], filename=f["filename"],
                mime_type=f["mime_type"], size_bytes=f["size_bytes"],
            )
            for f in files
        ],
        created_at=(
            datetime.fromisoformat(row["created_at"]) if row.get("created_at") else None
        ),
        updated_at=(
            datetime.fromisoformat(row["updated_at"]) if row.get("updated_at") else None
        ),
    )


def _gem_starters_json(starters: list[str]) -> str:
    return json.dumps([s.strip() for s in starters if s.strip()], ensure_ascii=False)


@app.get("/me/gems", response_model=list[GemDto])
async def list_gems(user=Depends(require_user)) -> list[GemDto]:
    rows = await db.list_gems(user["id"])
    return [await _gem_to_dto(r) for r in rows]


@app.post("/me/gems", response_model=GemDto, status_code=status.HTTP_201_CREATED)
async def create_gem(body: GemUpsertRequest, user=Depends(require_user)) -> GemDto:
    name = body.name.strip()
    instructions = body.instructions.strip()
    if not name:
        raise HTTPException(400, "Name ist erforderlich.")
    if not instructions:
        raise HTTPException(400, "Instructions sind erforderlich.")
    gid = await db.create_gem(
        user_id=user["id"],
        name=name,
        emoji=(body.emoji or "").strip(),
        description=(body.description or "").strip(),
        instructions=instructions,
        conversation_starters=_gem_starters_json(body.conversation_starters),
        model=(body.model or "").strip() or None,
        effort=(body.effort or "").strip() or None,
        skills=_skills_to_json(body.skills) if body.skills is not None else None,
    )
    row = await db.get_gem(gid, user_id=user["id"])
    assert row is not None
    return await _gem_to_dto(row)


@app.get("/me/gems/{gem_id}", response_model=GemDto)
async def get_gem(gem_id: str, user=Depends(require_user)) -> GemDto:
    row = await db.get_gem(gem_id, user_id=user["id"])
    if not row:
        raise HTTPException(404, "Gem nicht gefunden.")
    return await _gem_to_dto(row)


@app.put("/me/gems/{gem_id}", response_model=GemDto)
async def update_gem(gem_id: str, body: GemUpsertRequest, user=Depends(require_user)) -> GemDto:
    name = body.name.strip()
    instructions = body.instructions.strip()
    if not name:
        raise HTTPException(400, "Name ist erforderlich.")
    if not instructions:
        raise HTTPException(400, "Instructions sind erforderlich.")
    ok = await db.update_gem(
        gem_id, user["id"],
        name=name,
        emoji=(body.emoji or "").strip(),
        description=(body.description or "").strip(),
        instructions=instructions,
        conversation_starters=_gem_starters_json(body.conversation_starters),
        model=(body.model or "").strip() or None,
        effort=(body.effort or "").strip() or None,
        skills=_skills_to_json(body.skills) if body.skills is not None else None,
    )
    if not ok:
        raise HTTPException(404, "Gem nicht gefunden oder nicht editierbar.")
    row = await db.get_gem(gem_id, user_id=user["id"])
    assert row is not None
    return await _gem_to_dto(row)


@app.delete(
    "/me/gems/{gem_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=JSONResponse,
)
async def delete_gem(gem_id: str, user=Depends(require_user)):
    ok = await db.delete_gem(gem_id, user["id"])
    if not ok:
        raise HTTPException(404, "Gem nicht gefunden oder nicht löschbar.")
    return JSONResponse(status_code=204, content=None)


@app.get("/me/gems/{gem_id}/files", response_model=list[GemFileDto])
async def list_gem_files(gem_id: str, user=Depends(require_user)) -> list[GemFileDto]:
    row = await db.get_gem(gem_id, user_id=user["id"])
    if not row:
        raise HTTPException(404, "Gem nicht gefunden.")
    files = await db.get_gem_files(gem_id)
    return [
        GemFileDto(
            id=f["id"], filename=f["filename"],
            mime_type=f["mime_type"], size_bytes=f["size_bytes"],
        )
        for f in files
    ]


@app.post("/me/gems/{gem_id}/files", response_model=GemFileDto)
async def upload_gem_file(
    gem_id: str, file: UploadFile = File(...), user=Depends(require_user),
) -> GemFileDto:
    row = await db.get_gem(gem_id, user_id=user["id"])
    if not row or bool(row.get("is_builtin", 0)):
        # Built-ins sind read-only.
        raise HTTPException(404, "Gem nicht gefunden oder nicht editierbar.")
    att = await _store_upload(file, user["id"])
    await db.add_gem_file(gem_id, att["id"])
    return GemFileDto(
        id=att["id"], filename=att["filename"],
        mime_type=att["mime_type"], size_bytes=att["size_bytes"],
    )


@app.delete(
    "/me/gems/{gem_id}/files/{aid}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=JSONResponse,
)
async def delete_gem_file(gem_id: str, aid: str, user=Depends(require_user)):
    row = await db.get_gem(gem_id, user_id=user["id"])
    if not row or bool(row.get("is_builtin", 0)):
        raise HTTPException(404, "Gem nicht gefunden oder nicht editierbar.")
    await db.remove_gem_file(gem_id, aid)
    return JSONResponse(status_code=204, content=None)


# ---------- Token usage ----------

@app.get("/me/usage", response_model=UsageStatsDto)
async def get_my_usage(period: str = "month", user=Depends(require_user)):
    """Aggregated per-user token usage. `period` = 'month' (default) or 'all'."""
    if period not in ("month", "all"):
        raise HTTPException(400, "period must be 'month' or 'all'")
    stats = await usage.stats_for(user["id"], period=period)
    return UsageStatsDto(**stats)


# ---------- Admin: User-CRUD ----------

@app.get("/users")
async def list_users_endpoint(user=Depends(require_admin)):  # noqa: ARG001
    rows = await db.list_users()
    return {"users": [_user_public(r) for r in rows]}


@app.post("/users")
async def create_user_endpoint(body: dict, user=Depends(require_admin)):  # noqa: ARG001
    """Admin legt neuen User an. Body: `{name, password?, is_admin?}`.

    Wenn `password` weggelassen wird, generiert der Server ein temporäres
    Passwort und gibt es einmalig im Response zurück. Der User MUSS es beim
    ersten Login ändern (`must_change_password=true`).
    """
    name = (body.get("name") or "").strip()
    is_admin = bool(body.get("is_admin"))
    password = body.get("password") or ""
    if not name:
        raise HTTPException(400, "Name erforderlich.")
    if len(name) > 60:
        raise HTTPException(400, "Name zu lang (max 60).")
    # Username muss unique sein (case-insensitive)
    existing = await db.get_user_by_name(name)
    if existing:
        raise HTTPException(409, f"Username '{name}' ist bereits vergeben.")

    initial_temp = False
    if not password:
        password = db.generate_temp_password()
        initial_temp = True
    elif len(password) < 8:
        raise HTTPException(400, "Passwort muss mind. 8 Zeichen lang sein.")

    new_user = await db.create_user(
        name=name, password=password, is_admin=is_admin,
        must_change_password=True,  # bei Admin-Create immer
    )
    out = _user_public(new_user)
    # Klartext-PW einmalig mitgeben, damit Admin es dem User mitteilen kann
    out["initial_password"] = password
    out["initial_password_temp"] = initial_temp
    return out


@app.post("/users/{user_id}/reset-password")
async def reset_user_password_endpoint(user_id: str, body: dict | None = None,
                                       user=Depends(require_admin)):  # noqa: ARG001
    """Admin setzt das Passwort eines Users zurück. Body optional:
    `{password: str}` → exakt dieses Passwort verwenden. Sonst Server-
    generiertes temporäres Passwort. In jedem Fall `must_change_password=1`
    und ALLE aktiven Sessions des Users werden gekickt."""
    target = await db.get_user_by_id(user_id)
    if not target:
        raise HTTPException(404, "User nicht gefunden.")
    body = body or {}
    new_pw = (body.get("password") or "").strip()
    if new_pw and len(new_pw) < 8:
        raise HTTPException(400, "Passwort muss mind. 8 Zeichen lang sein.")
    if not new_pw:
        new_pw = db.generate_temp_password()
    await db.set_user_password(user_id, new_pw, must_change=True)
    await db.delete_sessions_for_user(user_id)
    return {
        "id": user_id,
        "name": target["name"],
        "new_password": new_pw,
        "sessions_revoked": True,
    }


@app.patch("/users/{user_id}")
async def patch_user_endpoint(user_id: str, body: dict, user=Depends(require_admin)):  # noqa: ARG001
    """Admin benennt einen User um. Der Name ist zugleich der Anmeldename;
    alles andere haengt an der ID, Sessions bleiben gueltig."""
    target = await db.get_user_by_id(user_id)
    if not target:
        raise HTTPException(404, "User nicht gefunden.")
    if "name" in body:
        name = str(body.get("name") or "").strip()
        if not name:
            raise HTTPException(400, "Name erforderlich.")
        if len(name) > 60:
            raise HTTPException(400, "Name zu lang (max 60).")
        existing = await db.get_user_by_name(name)
        if existing and existing["id"] != user_id:
            raise HTTPException(409, f"Username '{name}' ist bereits vergeben.")
        await db.rename_user(user_id, name)
        target["name"] = name
    return _user_public(target)


@app.put("/users/{user_id}/avatar")
async def put_user_avatar(user_id: str, file: UploadFile = File(...),
                          user=Depends(require_admin)):  # noqa: ARG001
    target = await db.get_user_by_id(user_id)
    if not target:
        raise HTTPException(404, "User nicht gefunden.")
    await _store_avatar(user_id, file)
    return _user_public(target)


@app.delete("/users/{user_id}/avatar")
async def delete_user_avatar(user_id: str, user=Depends(require_admin)):  # noqa: ARG001
    target = await db.get_user_by_id(user_id)
    if not target:
        raise HTTPException(404, "User nicht gefunden.")
    _remove_avatar(user_id)
    return _user_public(target)


@app.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user_endpoint(user_id: str, user=Depends(require_admin)):
    if user_id == user["id"]:
        raise HTTPException(400, "You cannot delete your own account.")
    target = await db.get_user_by_id(user_id)
    if target is None:
        raise HTTPException(404, "User nicht gefunden.")
    if target["is_admin"] and await db.count_admins() <= 1:
        raise HTTPException(400, "Cannot delete the last admin user.")
    await db.delete_user(user_id)
    _remove_avatar(user_id)
    return JSONResponse(status_code=204, content=None)


# ---------- Settings Export / Import (Per-User) ----------
#
# Exportiert alle User-scoped KV-Werte (Vorlese-Anbieter, Image-API-Key,
# Skills-Defaults, sonstige UI-Settings) als JSON-Payload.
# Bewusst KEIN Profil-Export (Username/Passwort/Token bleiben raus) — das
# Bundle wird IN den Account des aktuellen Users importiert, in dessen
# Namen man eingeloggt ist.
#
# Achtung: Export enthält API-Keys im KLARTEXT. App muss den User warnen
# und sollte die Datei sicher behandeln.

"""
Was wird exportiert?

  • Explizite Felder im DTO (`tts_provider`, `tts_chunking_enabled`,
    `image_api_key`, `skills_defaults`). `tts_model` und `tts_api_keys` stehen
    nur noch im Format, damit aeltere Exporte lesbar bleiben; sie gehoerten
    zur Gemini-API, die seit 21.10.2026 raus ist, und werden ignoriert.
  • Alles andere im KV-Store geht in `extra_kv` — Catch-all. Dazu gehören vor
    allem die Web-UI-Settings (theme, effort, ttsVoice, ttsSpeed, spMode,
    spCustom, sidebar etc.), die das Web-UI ohne Prefix in den KV-Store legt.

Ausgeschlossen werden:
  • Die expliziten Keys oben (sind schon im DTO).
  • Reste von Google Cloud TTS und Gemini-API (Modell, Schluessel,
    Zeichenzaehler), siehe `_is_export_excluded`.
"""

# Keys, die im DTO ein eigenes Feld haben → NICHT zusätzlich in extra_kv.
_EXPORT_EXPLICIT_KEYS = {
    _KV_TTS_PROVIDER,
    _KV_TTS_CHUNKING_ENABLED,
    _KV_IMAGE_API_KEY_LEGACY_FALLBACK,  # = "image_api_key"
    _KV_SKILLS_DEFAULTS,
}

# Reste der entfernten Anbieter: weder exportieren noch importieren.
_REMOVED_TTS_KEYS = {"tts_model", "tts_api_key", "tts_api_keys"}


def _is_export_excluded(key: str) -> bool:
    return key in _REMOVED_TTS_KEYS or key.startswith("cloud_tts_chars_")


@app.get("/settings/export", response_model=SettingsExportDto)
async def settings_export(user=Depends(require_user)) -> SettingsExportDto:
    """Bündelt alle Server-seitigen Settings des aktuellen Users in ein
    JSON-Payload. Enthält API-Keys im KLARTEXT — Caller (App) muss die
    Datei entsprechend behandeln."""
    user_id = user["id"]
    kv = await db.kv_get_all(scope=user_id)

    skills = _skills_from_json(kv.get(_KV_SKILLS_DEFAULTS))

    # extra_kv: alles aus KV-Store EXCEPT
    #  - die DTO-Explicit-Keys (sind oben im Bundle bereits typisiert)
    #  - die expliziten Excludes (Verbrauchs-Counter etc.)
    # Damit landen auch die Web-UI-Settings ohne ui_-Prefix (theme, effort, …)
    # sauber im Backup — vorher gingen die verloren weil der Prefix-Filter
    # zu eng war.
    extra: dict[str, str] = {}
    for k, v in kv.items():
        if k in _EXPORT_EXPLICIT_KEYS:
            continue
        if _is_export_excluded(k):
            continue
        extra[k] = v

    from datetime import timezone as _tz
    return SettingsExportDto(
        schema_version=1,
        # `datetime.utcnow()` ist deprecated in Py 3.12+ — explizite UTC-Zone.
        # WICHTIG: timezone.utc (Instanz), nicht timezone (Klasse).
        exported_at=datetime.now(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        server_version=__version__,
        tts_provider=(kv.get(_KV_TTS_PROVIDER) or None),
        tts_chunking_enabled=(kv.get(_KV_TTS_CHUNKING_ENABLED) or None),
        image_api_key=(kv.get(_KV_IMAGE_API_KEY_LEGACY_FALLBACK) or None),
        skills_defaults=skills,
        extra_kv=extra,
    )


@app.post("/settings/import", response_model=SettingsImportResponse)
async def settings_import(body: SettingsImportRequest,
                          user=Depends(require_user)) -> SettingsImportResponse:
    """Wendet ein zuvor exportiertes Settings-Bundle auf den aktuellen User
    an. None-Felder bleiben unverändert (partial update).

    `tts_model` und `tts_api_keys` aus aelteren Exporten werden ignoriert.
    """
    user_id = user["id"]
    updates: dict[str, str] = {}

    if body.tts_provider is not None:
        prov = body.tts_provider.strip()
        # Ein Export von frueher kann cloud_tts oder gemini_api enthalten.
        # Die gibt es nicht mehr; dann bleibt die bisherige Wahl.
        if prov in tts.VALID_PROVIDERS:
            updates[_KV_TTS_PROVIDER] = prov
            # Wie bei PUT /tts/provider: eine eigene Wahl schuetzt vor den
            # einmaligen Umstellungen beim Serverstart.
            updates[_KV_TTS_WEB_MIGRATED] = "1"
            updates[_KV_TTS_GROK_MIGRATED] = "1"

    if body.tts_chunking_enabled is not None:
        v = (body.tts_chunking_enabled or "").strip()
        if v not in ("", "0", "1"):
            raise HTTPException(400, f"Invalid tts_chunking_enabled: {v!r} (allowed: '', '0', '1')")
        updates[_KV_TTS_CHUNKING_ENABLED] = v

    if body.image_api_key is not None:
        updates[_KV_IMAGE_API_KEY_LEGACY_FALLBACK] = body.image_api_key.strip()

    if body.skills_defaults is not None:
        updates[_KV_SKILLS_DEFAULTS] = _skills_to_json(body.skills_defaults)

    tts_keys_imported = 0

    if body.extra_kv:
        for k, v in body.extra_kv.items():
            if k in _EXPORT_EXPLICIT_KEYS:
                continue
            if _is_export_excluded(k):
                continue
            updates[k] = str(v)

    if updates:
        async with _settings_lock(user_id):
            await db.kv_set_many(updates, scope=user_id)

    log.info("Settings-Import von user=%s: %d KV-Updates", user_id, len(updates))
    return SettingsImportResponse(
        ok=True,
        applied_keys=len(updates),
        tts_keys_imported=tts_keys_imported,
    )


# ---------- Backup / Restore ----------

@app.get("/backup")
async def export_backup(password: str | None = None, user=Depends(require_user)):
    """Backup-Export. Admin → global (alle User). Normaler User → nur eigene
    Daten. `?password=` verschlüsselt das ZIP AES-256."""
    scope_user_id = None if user.get("is_admin") else user["id"]
    scope_user_name = None if user.get("is_admin") else user["name"]
    try:
        data = await backup.create_backup_zip(
            password=password or None,
            user_id=scope_user_id,
            user_name=scope_user_name,
        )
    except Exception as e:  # noqa: BLE001
        log.exception("Backup-Export-Fehler")
        raise HTTPException(500, f"Backup-Export-Fehler: {type(e).__name__}: {e}")

    suffix = ".enc.zip" if password else ".zip"
    base = backup.suggested_filename().replace(".zip", suffix)
    # Per-User: User-Name im Filename
    if scope_user_id:
        safe = "".join(c for c in user["name"] if c.isalnum() or c in "-_")[:20]
        base = base.replace("pocket-claude-backup", f"pocket-claude-{safe}")
    from fastapi.responses import Response
    return Response(
        content=data,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{base}"',
            "Cache-Control": "no-store",
        },
    )


@app.post("/backup/import")
async def import_backup_endpoint(
    file: UploadFile = File(...),
    mode: str = "replace",
    password: str | None = None,
    user=Depends(require_admin),  # noqa: ARG001 — Import ist Admin-only
):
    """Importiert ein zuvor exportiertes Backup-ZIP. `mode` = "replace" oder
    "merge". Bei verschlüsselten Backups: `?password=...` mitgeben.

    Vor dem Import wird der aktuelle Zustand intern gesichert
    (data/backup-before-import-*.zip), damit Du im Notfall zurück kannst.
    Nach erfolgreichem Replace ist ein Server-Restart sinnvoll.
    """
    if mode not in ("replace", "merge"):
        raise HTTPException(400, f"Unbekannter Modus: {mode}. Erlaubt: replace, merge.")
    data = await file.read()
    if not data:
        raise HTTPException(400, "Leere Datei.")

    try:
        # Import läuft sync; wir lagern es in einen Thread aus.
        import asyncio
        result = await asyncio.to_thread(
            backup.import_backup, data, mode, password or None,
        )
    except backup.BackupPasswordError as e:
        # 423 Locked — vermittelt der App, dass Passwort fehlt/falsch ist
        raise HTTPException(423, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # noqa: BLE001
        log.exception("Backup-Import-Fehler")
        raise HTTPException(500, f"Backup-Import-Fehler: {type(e).__name__}: {e}")

    return {
        "ok": True,
        "mode": result.mode,
        "manifest": result.manifest.to_dict(),
        "conversations_added": result.conversations_added,
        "conversations_skipped": result.conversations_skipped,
        "messages_imported": result.messages_imported,
        "attachments_imported": result.attachments_imported,
        "pre_import_backup_path": result.pre_import_backup_path,
        "restart_recommended": result.mode == "replace",
    }


@app.post("/backup/peek")
async def peek_backup(
    file: UploadFile = File(...),
    password: str | None = None,
    user=Depends(require_admin),  # noqa: ARG001 — Peek vor Import = Admin-only
):
    """Liest NUR das Manifest aus dem Upload — für den Confirm-Dialog der App.
    Bei verschlüsselten Backups: `?password=...`. Ohne PW gibt's HTTP 423
    (Locked), darauf reagiert die App mit einem PW-Prompt."""
    data = await file.read()
    if not data:
        raise HTTPException(400, "Leere Datei.")
    try:
        m = backup.peek_manifest(data, password or None)
    except backup.BackupPasswordError as e:
        raise HTTPException(423, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "manifest": m.to_dict()}


# ---------- Default-Errorhandler ----------

@app.exception_handler(Exception)
async def fallback_error(_request, exc: Exception):  # noqa: ANN001
    # Details NUR ins Server-Log — niemals den rohen Exception-Text an den
    # Client geben (kann Pfade/SQL/3rd-Party-URLs mit Credentials enthalten).
    rid = uuid.uuid4().hex
    log.exception("Unbehandelter Server-Fehler [%s]", rid)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "request_id": rid},
    )


# ---------- Web-UI ----------
# Statics-Mount MUSS nach allen API-Routes kommen, weil StaticFiles auf "/"
# alles wegschnappt. Auth-Token wird browserseitig im localStorage gehalten,
# nicht über Cookies — die Statics selbst brauchen daher keinen Auth-Check.
from fastapi.staticfiles import StaticFiles
from pathlib import Path as _PathLib

class _HttpOnlyStaticFiles(StaticFiles):
    """Wrap StaticFiles to gracefully reject non-HTTP ASGI scopes.

    The default StaticFiles asserts ``scope["type"] == "http"`` (see
    starlette/staticfiles.py:91), which throws AssertionError into the
    journal every time a service worker or browser-extension speculatively
    opens a WebSocket on our root mount. Reject those with a clean close
    so we don't pollute logs with a stack trace per probe.
    """
    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            # Politely close any non-HTTP attempt (websocket, lifespan, …)
            if scope.get("type") == "websocket":
                await send({"type": "websocket.close", "code": 1008})
            return
        await super().__call__(scope, receive, send)

_webui_dir = _PathLib(__file__).parent / "webui"
if _webui_dir.exists():
    app.mount("/", _HttpOnlyStaticFiles(directory=str(_webui_dir), html=True), name="webui")
    log.info("Web-UI gemountet aus %s", _webui_dir)
else:
    log.warning("webui/-Verzeichnis nicht gefunden — Web-UI nicht aktiv.")
