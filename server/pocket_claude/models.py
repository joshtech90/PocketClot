"""Pydantic API models."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Role = Literal["user", "assistant", "system"]


class AttachmentRef(BaseModel):
    id: str
    filename: str
    mime_type: str
    size_bytes: int


class MessageOut(BaseModel):
    id: int
    conversation_id: str
    role: Role
    content: str
    created_at: datetime
    tokens: int = 0
    attachments: list[AttachmentRef] = Field(default_factory=list)


class ConversationOut(BaseModel):
    id: str
    title: str
    created_at: datetime
    last_message_at: datetime | None
    message_count: int
    total_tokens: int
    pinned: bool = False
    # UI-Riegel: True = dieser Chat ist gesperrt. App/Web-UI verlangen vor der
    # Anzeige den globalen PIN (bzw. Fingerabdruck in der App). Reiner Sichtschutz
    # gegen fremden Zugriff aufs entsperrte Gerät — keine Verschlüsselung.
    locked: bool = False
    # Wenn der Chat „mit einem Gem" gestartet wurde: dessen ID. NULL = normaler
    # Chat. Server speist dann pro Nachricht die Gem-Instructions/-Skills/-Modell
    # und -Wissensdateien ein.
    gem_id: str | None = None
    # Zuletzt in diesem Chat benutztes Modell (siehe SendMessageRequest.model).
    # NULL = Claude.
    chat_model: str | None = None
    # Denktiefe nur fuer diesen Chat (vom Gem mitgebracht oder im Chat
    # umgestellt). NULL = die gemerkte Denktiefe der Modell-Familie.
    chat_effort: str | None = None


class ConversationDetail(ConversationOut):
    messages: list[MessageOut]


class ConversationCreate(BaseModel):
    title: str | None = None
    # Optional: Chat „mit einem Gem" starten. Muss ein eigenes oder eingebautes
    # Gem des Users sein, sonst 404.
    gem_id: str | None = None


class ConversationPatch(BaseModel):
    title: str | None = None
    pinned: bool | None = None
    locked: bool | None = None
    # "" setzt den Chat auf Claude zurueck, None laesst den Wert unveraendert.
    chat_model: str | None = None
    # "" gibt die Denktiefe wieder an die Familien-Vorgabe ab, None laesst sie.
    chat_effort: str | None = None


class SendMessageRequest(BaseModel):
    content: str
    attachment_ids: list[str] = Field(default_factory=list)
    # Effort-Level für Claude-Code-Thinking: off | low | medium | high | xhigh | max
    # "off"  → keine Thinking-Steuerung (CLI-Default greift)
    # andere → CLAUDE_CODE_EFFORT_LEVEL wird auf den Wert gesetzt
    # `xhigh` gibt es ab Opus 4.7 und greift bei uns (claude-opus-5) als
    # echtes Extra-Level zwischen high und max.
    effort: str = "high"
    # Zusatz-Modelle: "" oder None = Claude (bisheriges Verhalten). Sonst der
    # `key` eines Modells aus GET /chat/models, also entweder eine reine
    # Claude-Modell-ID ("claude-opus-4-8") oder ein Gateway-Key
    # ("gw:pool:gemini-3.7-flash").
    model: str | None = None
    # System-Prompt komplett vorgegeben — ersetzt den Claude-Code-Default.
    # None/leer → Server-Fallback (kurzer Pocket-Claude-Prompt).
    # Die Android-App schickt hier den vollen String. Das Web-UI schickt
    # stattdessen nur `system_prompt_mode` + ggf. den Custom-Text in
    # `system_prompt` — der Server löst das via system_prompts.py auf.
    system_prompt: str | None = None
    # "STANDARD" | "PERMISSIVE" | "CUSTOM" | None. Wenn gesetzt, hat der Mode
    # Vorrang vor dem rohen system_prompt-String.
    system_prompt_mode: str | None = None
    # Optional: TTS-Voice + Rate vom Client. Wenn gesetzt, startet der Server
    # nach Stream-Done automatisch eine Pre-Generation der Audio und legt sie
    # im Cache ab — der nächste /messages/{id}/audio-Aufruf ist dann Cache-Hit.
    tts_voice: str | None = None
    tts_rate: float | None = None
    # Plus-Menue "Bild erstellen": diese eine Nachricht soll ein Bild ergeben.
    # Das Modell schreibt die Bildbeschreibung aus dem Verlauf, das Bild-
    # Werkzeug ist dafuer auch dann an, wenn der Skill-Schalter es abstellt.
    image_mode: bool = False


class AttachmentOut(BaseModel):
    id: str
    filename: str
    mime_type: str
    size_bytes: int
    uploaded_at: datetime


class HealthOut(BaseModel):
    status: str
    version: str
    model: str | None
    db_ok: bool


class TtsVoiceDto(BaseModel):
    id: str
    label: str
    gender: str
    tier: str
    # Mit welchen Anbietern diese Stimme funktioniert (grok, gemini_web, edge_tts).
    compatible_providers: list[str] = []


class TtsStatusDto(BaseModel):
    # `configured`: der GEWAEHLTE Anbieter laeuft und hat seine Sitzung.
    configured: bool
    # Mit diesem Anbieter wird gerade vorgelesen. Ist der gewaehlte nicht
    # nutzbar, steht hier der, der einspringt (Grok → Gemini Web → Edge).
    provider: str = "grok"
    # Was der Nutzer gewaehlt hat (bzw. die Vorgabe).
    chosen_provider: str = "grok"
    # Welche Anbieter gerade nutzbar sind.
    providers_available: list[str] = []
    default_voice: str
    voices: list[TtsVoiceDto]
    # Stueckeln: lange Texte in parallele Teile (nur MP3, also Edge und Grok).
    chunking_enabled: bool = False
    # Vom Nutzer gesetzt oder nur Vorgabe des Anbieters?
    chunking_explicit: bool = False


class TtsProviderRequest(BaseModel):
    provider: str  # "grok" | "gemini_web" | "edge_tts"


class TtsChunkingRequest(BaseModel):
    """Setzt die Chunking-Option des Users.

    `enabled=True/False` → explizit setzen. `enabled=None` → auf Provider-Default
    zurücksetzen (KV-Eintrag löschen)."""
    enabled: bool | None = None












# ---------- Settings Export / Import ----------

class SettingsExportDto(BaseModel):
    """Server-Anteil eines Settings-Exports. Enthält alle User-scoped KV-
    Werte inkl. Klartext-API-Keys. KEIN Profil (Username/Passwort/Token).

    Versioniert via `schema_version` für zukünftige Format-Migrationen.
    """
    schema_version: int = 1
    exported_at: str  # ISO-Timestamp
    server_version: str
    tts_provider: str | None = None
    tts_model: str | None = None
    # tts_chunking_enabled: "1" = manuell an, "0" = manuell aus, None oder ""
    # = Provider-Default greift. Eigenes Feld weil sonst der Wert beim Export
    # aus dem extra_kv-Catch-all rausgefiltert würde.
    tts_chunking_enabled: str | None = None
    tts_api_keys: list[dict] = []  # [{id, label, key (Klartext!)}, ...]
    image_api_key: str | None = None
    skills_defaults: SkillsDto | None = None
    # Catch-all für alle anderen KV-Werte (z.B. ui-settings vom Web-UI:
    # theme, effort, ttsVoice, ttsSpeed, spMode, spCustom, sidebar etc.).
    # Schlüssel sind die KV-Keys, Werte sind Strings (so wie KV sie speichert).
    extra_kv: dict[str, str] = {}


class SettingsImportRequest(BaseModel):
    """Komplettes Server-Settings-Bundle → wird auf den aktuellen User
    angewandt. Fehlende/None-Felder werden NICHT überschrieben (partial
    update). Wenn Du eine Einstellung explizit löschen willst, setze sie
    auf einen leeren String."""
    schema_version: int = 1
    tts_provider: str | None = None
    tts_model: str | None = None
    tts_chunking_enabled: str | None = None
    tts_api_keys: list[dict] | None = None
    image_api_key: str | None = None
    skills_defaults: SkillsDto | None = None
    extra_kv: dict[str, str] | None = None


class SettingsImportResponse(BaseModel):
    ok: bool = True
    applied_keys: int  # Anzahl gesetzter KV-Werte
    tts_keys_imported: int  # Anzahl Keys, die in den Pool gewandert sind


class ChatModelDto(BaseModel):
    """Ein waehlbares Chat-Modell fuer App und Web-UI.

    `key` ist das, was der Client spaeter als `SendMessageRequest.model`
    zurueckschickt: fuer Claude die reine Modell-ID, fuer Zusatz-Modelle der
    Gateway-Key `gw:<gateway>:<modell>`.
    """
    key: str
    family: str            # "claude" | "gemini" | "gpt" | "other"
    label: str
    efforts: list[str] = Field(default_factory=list)
    default_effort: str = ""
    supports_vision: bool = True
    context_length: int | None = None
    gateway_label: str = ""


class GatewayStatusDto(BaseModel):
    """Erreichbarkeit eines Zusatz-Modell-Gateways. Der API-Key bleibt draussen."""
    id: str
    label: str
    base_url: str
    reachable: bool = False
    model_count: int = 0
    last_error: str | None = None
    checked_at: str | None = None


class ChatModelsDto(BaseModel):
    """Antwort von GET /chat/models.

    Claude steht immer zuerst und ist auch dann da, wenn kein Gateway laeuft.
    """
    models: list[ChatModelDto] = Field(default_factory=list)
    gateways: list[GatewayStatusDto] = Field(default_factory=list)
    # Standard-Modell des Users ("" = Claude-Automatik).
    default_key: str = ""


class SkillsDto(BaseModel):
    """Welche Tools darf Claude pro Konversation/User nutzen.

    Wir nennen sie hier "Skills", weil das aus User-Sicht besser ist als
    "Tools" (Verwechslungsgefahr mit Werkzeug-im-Werkstattsinn) und auch
    weil andere LLM-Frontends den Begriff so verwenden.

    Mapping auf die ClaudeAgentOptions.allowed_tools:
    - web_search    → "WebSearch"
    - web_fetch     → "WebFetch"
    - code_execution → "Bash"
    """
    web_search: bool = True
    web_fetch: bool = True
    code_execution: bool = False
    # Bilderzeugung im Chat. Das Werkzeug heisst in beiden Engines
    # `generate_image` und laeuft immer ueber Nano Banana (image_engine),
    # egal welches Modell gerade antwortet.
    image_generation: bool = True


class RewindRequest(BaseModel):
    """Zu einem frueheren Punkt im Chat zurueckspringen.

    `message_id` ist die Nachricht, die stehen bleiben soll; alles danach wird
    verworfen. `chat_model` erlaubt es, im selben Zug das Modell zu wechseln:
    genau dafuer springt man meistens zurueck, naemlich um dieselbe Stelle mit
    einem anderen Modell weiterzugehen.
    """
    message_id: int
    chat_model: str | None = None


class RewindResponse(BaseModel):
    removed: int
    chat_model: str | None = None


class SkillsDefaultsRequest(BaseModel):
    """User-Settings (= Default für alle neuen Chats)."""
    skills: SkillsDto


class ConversationSkillsResponse(BaseModel):
    """Effektive Skills für eine Konversation = Override (falls gesetzt)
    sonst User-Default. `is_override=True` heißt: dieser Chat hat eine
    eigene Einstellung, die vom User-Default abweicht."""
    skills: SkillsDto
    is_override: bool


class ConversationSkillsRequest(BaseModel):
    """`skills=None` (oder Feld weglassen) löscht den Override und fällt
    auf den User-Default zurück."""
    skills: SkillsDto | None = None


class SearchHitOut(BaseModel):
    conversation_id: str
    conversation_title: str
    message_id: int
    role: Role
    created_at: datetime
    snippet: str


class SearchResponseOut(BaseModel):
    query: str
    hits: list[SearchHitOut]


# ─── Auth modes (Pro/Max | direct API | Bedrock) ─────────────────────────────

class ClaudeAuthDto(BaseModel):
    """Per-user Claude-provider configuration.

    Secrets come back masked (last 4 chars visible) — never plaintext. Set
    a field to empty string in the PUT request to clear it.
    """
    mode: str  # "pro_max" | "api_key" | "bedrock"
    api_key_masked: str = ""
    aws_region: str = ""
    aws_access_key_id_masked: str = ""
    aws_secret_access_key_masked: str = ""
    aws_session_token_masked: str = ""
    bedrock_opus_model: str = ""
    bedrock_sonnet_model: str = ""
    bedrock_haiku_model: str = ""
    bedrock_model_alias: str = "opus"
    # Globales Standard-Modell für Pro/Max + API-Key-Modus. Voller Modell-String
    # (z.B. "claude-opus-4-8") oder "" = automatisch (Server-/SDK-Default). Im
    # Bedrock-Modus ungenutzt (dort greift bedrock_model_alias).
    default_model: str = ""
    # Booleans for "is this set?" — lets the UI show a green check without
    # ever needing to reveal the value
    api_key_set: bool = False
    aws_access_key_set: bool = False
    aws_secret_set: bool = False


class ClaudeAuthUpdateRequest(BaseModel):
    """Partial-update payload. Any field set to None is left untouched.
    Setting a credential field to empty string clears it."""
    mode: str | None = None
    api_key: str | None = None
    aws_region: str | None = None
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_session_token: str | None = None
    bedrock_opus_model: str | None = None
    bedrock_sonnet_model: str | None = None
    bedrock_haiku_model: str | None = None
    bedrock_model_alias: str | None = None
    # "" leert den Wert (→ automatisch); None lässt ihn unverändert.
    default_model: str | None = None


# ─── Usage tracking ──────────────────────────────────────────────────────────

class UsageStatsDto(BaseModel):
    """Aggregated token usage for the current user.

    `period`: "month" (calendar month, billing-month equivalent) or "all".
    Always returns 0s for Pro/Max users — their usage doesn't bill per-token,
    so we don't bother counting.
    """
    period: str
    period_start: str  # ISO date
    period_end: str    # ISO date
    input_tokens: int
    output_tokens: int
    cache_create_tokens: int
    cache_read_tokens: int
    request_count: int
    # Coarse provider attribution: "anthropic" | "bedrock" | "pro_max" | "mixed"
    provider: str


# ─── Chat-Sperre (globaler PIN, per-Chat-Riegel) ─────────────────────────────

class ChatLockStatusDto(BaseModel):
    """Ist ein globaler Chat-Sperr-PIN für diesen User gesetzt? Der PIN-Hash
    selbst wird NIE über die Wire geschickt."""
    is_set: bool = False


class ChatLockSetRequest(BaseModel):
    """PIN setzen oder ändern. `pin` = neuer 5-stelliger PIN. Wenn schon einer
    gesetzt ist, muss `current_pin` stimmen (sonst 401)."""
    pin: str
    current_pin: str | None = None


class ChatLockClearRequest(BaseModel):
    """PIN entfernen. `current_pin` muss stimmen. Entsperrt implizit alle Chats
    (locked-Flag bleibt aber; ohne PIN wird die Sperre client-seitig ignoriert —
    der Server räumt die Flags mit auf)."""
    current_pin: str


class ChatLockVerifyRequest(BaseModel):
    pin: str


class ChatLockVerifyResponse(BaseModel):
    ok: bool
    # Wenn wegen zu vieler Fehlversuche gesperrt: Sekunden bis zum nächsten
    # erlaubten Versuch. 0 = nicht gesperrt.
    retry_after_seconds: int = 0


# ─── Gems (Custom Agents — wie ChatGPT-GPTs / Gemini-Gems) ───────────────────

class GemFileDto(BaseModel):
    """Eine Wissens-/Referenzdatei, die an ein Gem gehängt ist. Speichert intern
    eine `attachments`-Zeile; bei jeder Nachricht eines Gem-Chats wird die Datei
    in den Prompt eingespeist (Text inline, Binär via Read-Tool)."""
    id: str
    filename: str
    mime_type: str
    size_bytes: int


class GemDto(BaseModel):
    """Ein Custom Agent. `is_builtin=True` → vom Server ausgeliefert (read-only,
    z.B. „Meme-Finder"). `model`/`effort`/`skills`=None → globaler bzw.
    Chat-Default greift."""
    id: str
    name: str
    emoji: str = ""
    description: str = ""
    instructions: str = ""
    conversation_starters: list[str] = Field(default_factory=list)
    model: str | None = None
    effort: str | None = None
    skills: SkillsDto | None = None
    is_builtin: bool = False
    files: list[GemFileDto] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class GemUpsertRequest(BaseModel):
    """Create/Update-Payload. Bei Update werden alle Felder gesetzt (kein Partial)
    — die App schickt immer den vollen Stand zurück."""
    name: str
    emoji: str = ""
    description: str = ""
    instructions: str = ""
    conversation_starters: list[str] = Field(default_factory=list)
    model: str | None = None
    effort: str | None = None
    skills: SkillsDto | None = None
