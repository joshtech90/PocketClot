package de.smartzone.pocketclaude.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/** Produkt-Default für die Denktiefe (CLAUDE_CODE_EFFORT_LEVEL). Eine einzige
 *  Quelle der Wahrheit — DTO-Defaults, Repo-Default und Settings-Fallback
 *  referenzieren diese Konstante, damit der Default nicht über mehrere
 *  Dateien hinweg auseinanderdriften kann. */
const val DEFAULT_EFFORT = "high"

@Serializable
data class HealthDto(
    val status: String,
    val version: String,
    /** Server returnt `null` wenn CLAUDE_MODEL nicht gesetzt ist (Default greift im CLI). */
    val model: String? = null,
    @SerialName("db_ok") val dbOk: Boolean,
)

@Serializable
data class ConversationDto(
    val id: String,
    val title: String,
    @SerialName("created_at") val createdAt: String,
    @SerialName("last_message_at") val lastMessageAt: String? = null,
    @SerialName("message_count") val messageCount: Int = 0,
    @SerialName("total_tokens") val totalTokens: Int = 0,
    @SerialName("has_mid_summary") val hasMidSummary: Boolean = false,
    @SerialName("has_long_summary") val hasLongSummary: Boolean = false,
    val pinned: Boolean = false,
    /** UI-Riegel: true = Chat ist gesperrt, braucht PIN/Fingerabdruck vor Anzeige. */
    val locked: Boolean = false,
    /** Wenn der Chat „mit einem Gem" gestartet wurde: dessen ID (für Badge im Drawer). */
    @SerialName("gem_id") val gemId: String? = null,
    /** Zuletzt in diesem Chat benutztes Modell. Leer/null = Claude. */
    @SerialName("chat_model") val chatModel: String? = null,
    /** Denktiefe nur fuer diesen Chat (vom Gem mitgebracht oder im Chat
     *  umgestellt). null = die gemerkte Denktiefe der Modell-Familie. */
    @SerialName("chat_effort") val chatEffort: String? = null,
)

@Serializable
data class AttachmentRefDto(
    val id: String,
    val filename: String,
    @SerialName("mime_type") val mimeType: String,
    @SerialName("size_bytes") val sizeBytes: Long,
)

@Serializable
data class MessageDto(
    val id: Long,
    @SerialName("conversation_id") val conversationId: String,
    val role: String,
    val content: String,
    @SerialName("created_at") val createdAt: String,
    val tokens: Int = 0,
    val attachments: List<AttachmentRefDto> = emptyList(),
)

@Serializable
data class ConversationDetailDto(
    val id: String,
    val title: String,
    @SerialName("created_at") val createdAt: String,
    @SerialName("last_message_at") val lastMessageAt: String? = null,
    @SerialName("message_count") val messageCount: Int = 0,
    @SerialName("total_tokens") val totalTokens: Int = 0,
    @SerialName("has_mid_summary") val hasMidSummary: Boolean = false,
    @SerialName("has_long_summary") val hasLongSummary: Boolean = false,
    val pinned: Boolean = false,
    val locked: Boolean = false,
    @SerialName("gem_id") val gemId: String? = null,
    /** Zuletzt in diesem Chat benutztes Modell. Leer/null = Claude. */
    @SerialName("chat_model") val chatModel: String? = null,
    /** Siehe [ConversationDto.chatEffort]. */
    @SerialName("chat_effort") val chatEffort: String? = null,
    val messages: List<MessageDto> = emptyList(),
    @SerialName("mid_summary") val midSummary: String? = null,
    @SerialName("long_summary") val longSummary: String? = null,
)

@Serializable
data class AttachmentDto(
    val id: String,
    val filename: String,
    @SerialName("mime_type") val mimeType: String,
    @SerialName("size_bytes") val sizeBytes: Long,
    @SerialName("uploaded_at") val uploadedAt: String,
)

@Serializable
data class SendMessageRequest(
    val content: String,
    @SerialName("attachment_ids") val attachmentIds: List<String> = emptyList(),
    /** off | low | medium | high | xhigh | max — steuert CLAUDE_CODE_EFFORT_LEVEL */
    val effort: String = DEFAULT_EFFORT,
    /** Modell-Key aus GET /chat/models. Leer oder null = Claude-Standard.
     *  Zusatz-Modelle tragen den Präfix „gw:". */
    val model: String? = null,
    /** Vom Client gewünschter System-Prompt (ersetzt Server-Default + Claude-Code-Default). */
    @SerialName("system_prompt") val systemPrompt: String? = null,
    /** TTS-Hints: Server startet nach Stream-Ende eine Pre-Generation in der
     *  ausgewählten Voice/Speed. Beim nächsten Vorlesen-Tap ist's Cache-Hit. */
    @SerialName("tts_voice") val ttsVoice: String? = null,
    @SerialName("tts_rate") val ttsRate: Float? = null,
    /** Plus-Menue „Bild erstellen": diese Nachricht soll ein Bild ergeben. */
    @SerialName("image_mode") val imageMode: Boolean = false,
)

@Serializable
data class CreateConversationRequest(
    val title: String? = null,
    /** Optional: Chat „mit einem Gem" starten. */
    @SerialName("gem_id") val gemId: String? = null,
)

@Serializable
data class PatchConversationRequest(
    val title: String? = null,
    val pinned: Boolean? = null,
    val locked: Boolean? = null,
    /** "" setzt den Chat zurück auf Claude, null lässt den Wert unverändert. */
    @SerialName("chat_model") val chatModel: String? = null,
    /** "" gibt die Denktiefe an die Familien-Vorgabe ab, null laesst sie. */
    @SerialName("chat_effort") val chatEffort: String? = null,
)

// ---------- Chat-Sperre (globaler PIN) ----------

@Serializable
data class ChatLockStatusDto(
    @SerialName("is_set") val isSet: Boolean = false,
)

@Serializable
data class ChatLockSetRequest(
    val pin: String,
    @SerialName("current_pin") val currentPin: String? = null,
)

@Serializable
data class ChatLockClearRequest(
    @SerialName("current_pin") val currentPin: String,
)

@Serializable
data class ChatLockVerifyRequest(
    val pin: String,
)

@Serializable
data class ChatLockVerifyResponse(
    val ok: Boolean = false,
    @SerialName("retry_after_seconds") val retryAfterSeconds: Int = 0,
)

@Serializable
data class TtsVoiceDto(
    val id: String,
    val label: String,
    val gender: String,
    val tier: String,
    // Welche TTS-Provider kennen diese Voice. Bei Provider-Switch in der UI
    // werden Voices ausgeblendet, deren `compatible_providers` den aktuellen
    // Provider nicht enthält. Default ["cloud_tts"] für Altdaten-Kompatibilität.
    val compatible_providers: List<String> = listOf("cloud_tts"),
)

@Serializable
data class TtsStatusDto(
    /** Es wird vorgelesen, notfalls vom einspringenden Anbieter. */
    val configured: Boolean,
    /** Mit diesem Anbieter wird gerade vorgelesen (grok, gemini_web, edge_tts).
     *  Ist der gewaehlte nicht nutzbar, steht hier der, der einspringt. */
    val provider: String = "grok",
    /** Was der Nutzer gewaehlt hat. Leer bei einem aelteren Server. */
    @SerialName("chosen_provider") val chosenProvider: String = "",
    @SerialName("providers_available") val providersAvailable: List<String> = emptyList(),
    @SerialName("default_voice") val defaultVoice: String,
    val voices: List<TtsVoiceDto> = emptyList(),
    /** Lange Texte in parallelen Teilen erzeugen (nur MP3: Grok, Edge). */
    @SerialName("chunking_enabled") val chunkingEnabled: Boolean = false,
    /** TRUE = vom Nutzer gesetzt, FALSE = Vorgabe des Anbieters. */
    @SerialName("chunking_explicit") val chunkingExplicit: Boolean = false,
)



/** Request-Body für PUT /tts/chunking. `enabled=null` setzt den Wert auf den
 *  Provider-Default zurück (löscht das KV-Override). */
@Serializable
data class TtsChunkingRequest(
    val enabled: Boolean? = null,
)





// ---------- Settings Export / Import ----------


/** Server-Anteil eines Settings-Exports (von GET /settings/export). */
@Serializable
data class ServerSettingsExportDto(
    @SerialName("schema_version") val schemaVersion: Int = 1,
    @SerialName("exported_at") val exportedAt: String,
    @SerialName("server_version") val serverVersion: String,
    @SerialName("tts_provider") val ttsProvider: String? = null,
    /** "1" / "0" / "" / null — siehe Server-Side DTO. */
    @SerialName("tts_chunking_enabled") val ttsChunkingEnabled: String? = null,
    @SerialName("image_api_key") val imageApiKey: String? = null,
    @SerialName("skills_defaults") val skillsDefaults: SkillsDto? = null,
    @SerialName("extra_kv") val extraKv: Map<String, String> = emptyMap(),
)

/** App-Anteil eines Settings-Exports (lokal aus DataStore zusammengestellt). */
@Serializable
data class AppSettingsExportDto(
    @SerialName("theme_mode") val themeMode: String = "SYSTEM",
    // Farbschema. Bis August 2026 gab es nur dieses eine Feld fuer hell und
    // dunkel; es bleibt im Schema, damit ein aelterer App-Stand einen neuen
    // Export noch lesen kann und umgekehrt.
    @SerialName("palette_id") val paletteId: String = DEFAULT_PALETTE_ID,
    // Die Defaults muessen zu AppSettings passen, sonst setzt ein Import aus
    // einer aelteren App-Version die Farbwahl zurueck. Leer heisst: der Export
    // kannte die Trennung noch nicht, dann gilt `paletteId` fuer beide.
    @SerialName("palette_id_light") val paletteIdLight: String = "",
    @SerialName("palette_id_dark") val paletteIdDark: String = "",
    // Default muss zu AppSettings.ttsVoice passen — sonst überschreibt der
    // Import bei fehlendem Feld die User-Wahl mit einer alten Voice.
    @SerialName("tts_voice") val ttsVoice: String = DEFAULT_TTS_VOICE,
    @SerialName("tts_auto_speak") val ttsAutoSpeak: Boolean = false,
    @SerialName("tts_speed") val ttsSpeed: Float = 1.0f,
    @SerialName("tts_speed_per_chat") val ttsSpeedByChat: Map<String, Float> = emptyMap(),
    val effort: String = DEFAULT_EFFORT,
    @SerialName("system_prompt_mode") val systemPromptMode: String = "STANDARD",
    @SerialName("custom_system_prompt") val customSystemPrompt: String = "",
    @SerialName("tts_auto_speak_per_chat") val ttsAutoSpeakPerChat: Map<String, Boolean> = emptyMap(),
    @SerialName("collapse_long_user_messages") val collapseLongUserMessages: Boolean = true,
    /** Zusatz-Modelle: gewähltes Standard-Modell und die Denktiefe je Familie. */
    @SerialName("chat_model_key") val chatModelKey: String = "",
    @SerialName("effort_by_family") val effortByFamily: Map<String, String> = emptyMap(),
    @SerialName("default_model_by_family") val defaultModelByFamily: Map<String, String> = emptyMap(),
    @SerialName("image_default_size") val imageDefaultSize: String = "2K",
    @SerialName("image_default_aspect") val imageDefaultAspect: String = "1:1",
)

/** Container für die kombinierte JSON-Datei (Server + App). */
@Serializable
data class FullSettingsExportDto(
    @SerialName("schema_version") val schemaVersion: Int = 1,
    @SerialName("exported_at") val exportedAt: String,
    @SerialName("app_version") val appVersion: String = "",
    val server: ServerSettingsExportDto,
    val app: AppSettingsExportDto,
)

/** Body für POST /settings/import (entspricht ServerSettingsExportDto, aber alle
 *  Felder nullable — Server treats null als „nicht ändern"). */
@Serializable
data class ServerSettingsImportRequest(
    @SerialName("schema_version") val schemaVersion: Int = 1,
    @SerialName("tts_provider") val ttsProvider: String? = null,
    @SerialName("tts_chunking_enabled") val ttsChunkingEnabled: String? = null,
    @SerialName("image_api_key") val imageApiKey: String? = null,
    @SerialName("skills_defaults") val skillsDefaults: SkillsDto? = null,
    @SerialName("extra_kv") val extraKv: Map<String, String>? = null,
)

@Serializable
data class SettingsImportResponseDto(
    val ok: Boolean = true,
    @SerialName("applied_keys") val appliedKeys: Int,
    @SerialName("tts_keys_imported") val ttsKeysImported: Int,
)



@Serializable
data class TtsProviderRequest(
    val provider: String,
)

// ---------- Skills (per-User-Default + per-Chat-Override) ----------

/**
 * Welche Tools darf Claude in dieser Konversation nutzen.
 *
 * Mapping zum Server (ClaudeAgentOptions.allowed_tools):
 * - webSearch     → "WebSearch"
 * - webFetch      → "WebFetch"
 * - codeExecution → "Bash" (Sandbox-Cwd, isoliert)
 */
/** Ein waehlbares Chat-Modell, so wie der Server es meldet. */
@Serializable
data class ChatModelDto(
    val key: String,
    /** "claude" | "gemini" | "gpt" | "other" */
    val family: String = "other",
    val label: String,
    val efforts: List<String> = emptyList(),
    @SerialName("default_effort") val defaultEffort: String = "",
    @SerialName("supports_vision") val supportsVision: Boolean = true,
    @SerialName("context_length") val contextLength: Int? = null,
    @SerialName("gateway_label") val gatewayLabel: String = "",
)

/** Erreichbarkeit eines Zusatz-Modell-Gateways (für die Fehleranzeige im Picker). */
@Serializable
data class GatewayStatusDto(
    val id: String,
    val label: String,
    @SerialName("base_url") val baseUrl: String = "",
    val reachable: Boolean = false,
    @SerialName("model_count") val modelCount: Int = 0,
    @SerialName("last_error") val lastError: String? = null,
    @SerialName("checked_at") val checkedAt: String? = null,
)

@Serializable
data class ChatModelsDto(
    val models: List<ChatModelDto> = emptyList(),
    val gateways: List<GatewayStatusDto> = emptyList(),
    @SerialName("default_key") val defaultKey: String = "",
)

@Serializable
data class SkillsDto(
    @SerialName("web_search") val webSearch: Boolean = true,
    @SerialName("web_fetch") val webFetch: Boolean = true,
    @SerialName("code_execution") val codeExecution: Boolean = false,
    /** Bilder direkt im Chat erzeugen (Werkzeug `generate_image`, laeuft immer
     *  ueber Nano Banana, egal welches Modell gerade antwortet). */
    @SerialName("image_generation") val imageGeneration: Boolean = true,
)

@Serializable
data class SkillsDefaultsRequest(
    val skills: SkillsDto,
)

/**
 * Server-Response für GET/PUT /conversations/{cid}/skills.
 * `isOverride=true` heißt: dieser Chat hat eine eigene Einstellung, die vom
 * User-Default abweicht; UI zeigt dann „pro Chat überschrieben".
 */
@Serializable
data class ConversationSkillsResponse(
    val skills: SkillsDto,
    @SerialName("is_override") val isOverride: Boolean,
)

/**
 * Request für PUT /conversations/{cid}/skills.
 * `skills=null` löscht den Override und fällt auf den User-Default zurück.
 */
@Serializable
data class ConversationSkillsRequest(
    val skills: SkillsDto? = null,
)

// ---------- Gems (Custom Agents — wie ChatGPT-GPTs / Gemini-Gems) ----------

@Serializable
data class GemFileDto(
    val id: String,
    val filename: String,
    @SerialName("mime_type") val mimeType: String,
    @SerialName("size_bytes") val sizeBytes: Long,
)

/** Ein Custom Agent. `isBuiltin=true` → vom Server ausgeliefert (read-only).
 *  `model`/`effort`/`skills`=null → globaler bzw. Chat-Default greift. */
@Serializable
data class GemDto(
    val id: String,
    val name: String,
    val emoji: String = "",
    val description: String = "",
    val instructions: String = "",
    @SerialName("conversation_starters") val conversationStarters: List<String> = emptyList(),
    val model: String? = null,
    val effort: String? = null,
    val skills: SkillsDto? = null,
    @SerialName("is_builtin") val isBuiltin: Boolean = false,
    val files: List<GemFileDto> = emptyList(),
    @SerialName("created_at") val createdAt: String? = null,
    @SerialName("updated_at") val updatedAt: String? = null,
)

/** Create/Update-Payload (Voll-Update, kein Partial). */
@Serializable
data class GemUpsertRequest(
    val name: String,
    val emoji: String = "",
    val description: String = "",
    val instructions: String = "",
    @SerialName("conversation_starters") val conversationStarters: List<String> = emptyList(),
    val model: String? = null,
    val effort: String? = null,
    val skills: SkillsDto? = null,
)

@Serializable
data class SearchHitDto(
    @SerialName("conversation_id") val conversationId: String,
    @SerialName("conversation_title") val conversationTitle: String,
    @SerialName("message_id") val messageId: Long,
    val role: String,
    @SerialName("created_at") val createdAt: String,
    val snippet: String,
)

@Serializable
data class SearchResponseDto(
    val query: String,
    val hits: List<SearchHitDto>,
)

@Serializable
data class BackupManifestDto(
    @SerialName("schema_version") val schemaVersion: Int,
    @SerialName("created_at") val createdAt: String,
    @SerialName("server_version") val serverVersion: String,
    @SerialName("conversation_count") val conversationCount: Int,
    @SerialName("message_count") val messageCount: Int,
    @SerialName("attachment_count") val attachmentCount: Int,
)

@Serializable
data class BackupPeekResponse(
    val ok: Boolean,
    val manifest: BackupManifestDto,
)

// ---------- Image Generation (Gemini / Nano Banana) ----------

@Serializable
data class ImageModelDto(
    val id: String,
    val label: String,
    val description: String = "",
    @SerialName("default") val isDefault: Boolean = false,
)

@Serializable
data class ImageAspectDto(
    val id: String,
    val label: String,
)

@Serializable
data class ImageConfigDto(
    val models: List<ImageModelDto>,
    /** Bild-Anbieter, die dieser Server wirklich anbietet. Leer heisst: keiner. */
    val providers: List<ImageProviderDto> = emptyList(),
    @SerialName("aspect_ratios") val aspectRatios: List<ImageAspectDto>,
    @SerialName("max_candidates") val maxCandidates: Int = 4,
    @SerialName("default_model") val defaultModel: String,
    @SerialName("default_aspect") val defaultAspect: String,
    @SerialName("image_sizes") val imageSizes: List<ImageSizeDto> = emptyList(),
    @SerialName("default_image_size") val defaultImageSize: String = "2K",
    @SerialName("default_provider") val defaultProvider: String = "both",
    val configured: Boolean = false,
    @SerialName("api_key_masked") val apiKeyMasked: String? = null,
    /** Die vom User gesetzten Standardwerte. Gelten für den Bilder-Screen UND
     *  für das Bild-Werkzeug im Chat. */
    val defaults: ImageDefaultsDto = ImageDefaultsDto(),
)

@Serializable
data class ImageSizeDto(val id: String, val label: String)

@Serializable
data class ImageProviderDto(val id: String, val label: String)

@Serializable
data class ImageDefaultsDto(
    val size: String = "2K",
    @SerialName("aspect_ratio") val aspectRatio: String = "1:1",
    val provider: String = "both",
    val model: String = "",
)

/** Zu einer frueheren Antwort zurueckspringen. Alles danach wird verworfen. */
@Serializable
data class RewindRequest(
    @SerialName("message_id") val messageId: Long,
    /** Optionaler Modellwechsel im selben Zug. Null laesst das Modell stehen. */
    @SerialName("chat_model") val chatModel: String? = null,
)

@Serializable
data class RewindResponse(
    val removed: Int = 0,
    @SerialName("chat_model") val chatModel: String? = null,
)

@Serializable
data class ImageDefaultsRequest(
    val size: String? = null,
    @SerialName("aspect_ratio") val aspectRatio: String? = null,
    val model: String? = null,
    val provider: String? = null,
)

@Serializable
data class ImageGenerateRequest(
    val prompt: String,
    @SerialName("conversation_id") val conversationId: String? = null,
    val model: String? = null,
    /** "auto", "gemini" oder "gpt". Leer heisst: die Vorgabe des Servers. */
    val provider: String? = null,
    @SerialName("aspect_ratio") val aspectRatio: String? = null,
    /** Aufloesungsstufe (1K/2K/4K). Fehlte bisher komplett, weshalb der
     *  Bilder-Screen die eingestellte Aufloesung gar nicht anwenden konnte. */
    @SerialName("image_size") val imageSize: String? = null,
    val count: Int = 1,
    @SerialName("reference_attachment_ids") val referenceAttachmentIds: List<String> = emptyList(),
)

@Serializable
data class ImageGenerateAttachment(
    val id: String,
    val filename: String,
    @SerialName("mime_type") val mimeType: String,
    @SerialName("size_bytes") val sizeBytes: Long,
    val text: String? = null,
)

@Serializable
data class ImageGenerateSavedMessage(
    val id: Long,
    @SerialName("conversation_id") val conversationId: String,
)

@Serializable
data class ImageGenerateResponse(
    val ok: Boolean,
    val model: String,
    @SerialName("aspect_ratio") val aspectRatio: String,
    val count: Int,
    val attachments: List<ImageGenerateAttachment>,
    val message: ImageGenerateSavedMessage? = null,
)

@Serializable
data class ImageCredentialsRequest(@SerialName("api_key") val apiKey: String)

// ---------- Voice-Input (Groq Whisper) ----------

@Serializable
data class VoiceConfigDto(
    val configured: Boolean = false,
    @SerialName("api_key_masked") val apiKeyMasked: String? = null,
    val model: String = "whisper-large-v3-turbo",
    /** "auto" oder "override" */
    @SerialName("lang_mode") val langMode: String = "auto",
    /** Bei mode=override: ISO-Code (`sv`, `ko`, …); sonst null */
    @SerialName("lang_override") val langOverride: String? = null,
    /** Aktuell aufgelöster Whisper-Sprachcode (preview) */
    @SerialName("current_lang") val currentLang: String = "en",
    /** Aktueller Bias-Prompt — wird in der UI als Read-Only-Preview gezeigt */
    @SerialName("current_prompt") val currentPrompt: String = "",
    /** "bundled" | "cache" | "fallback" — woher der current_prompt kommt */
    @SerialName("current_prompt_source") val currentPromptSource: String = "fallback",
    /** Alle Sprachen, für die wir einen Default-Prompt gebundelt haben */
    @SerialName("bundled_languages") val bundledLanguages: List<String> = emptyList(),
    /** ISO-Code → englischer Display-Name (Sprache, nicht UI-Label) */
    @SerialName("language_names") val languageNames: Map<String, String> = emptyMap(),
    /** Sprachen, für die der User bereits eine Übersetzung im Cache hat */
    @SerialName("cached_languages") val cachedLanguages: List<String> = emptyList(),
)

@Serializable
data class VoiceCredentialsRequest(@SerialName("api_key") val apiKey: String)

@Serializable
data class VoiceLangConfigRequest(
    val mode: String,
    val locale: String? = null,
)

@Serializable
data class VoiceTranslateRequest(
    val locale: String,
    val force: Boolean = false,
)

@Serializable
data class VoiceTranslateResponse(
    val locale: String,
    val prompt: String,
    /** "bundled" | "cache" | "translated" */
    val source: String,
)

@Serializable
data class VoiceTranscribeResponse(val text: String)

// ---------- Auth ----------

@Serializable
data class LoginRequest(val username: String, val password: String)

@Serializable
data class MeDto(
    val id: String,
    val name: String,
    @SerialName("is_admin") val isAdmin: Boolean = false,
    @SerialName("must_change_password") val mustChangePassword: Boolean = false,
    @SerialName("has_password") val hasPassword: Boolean = true,
    /** Aendert sich mit jedem neuen Profilbild. null = keins hinterlegt. */
    @SerialName("avatar_version") val avatarVersion: Long? = null,
)

@Serializable
data class UiSettingsDto(
    val settings: Map<String, String> = emptyMap(),
)

@Serializable
data class LoginResponse(
    val token: String,
    val user: MeDto,
)

@Suppress("ConstructorParameterNaming")
@Serializable
data class ChangePasswordRequest(
    val old_password: String? = null,
    val new_password: String,
)

@Serializable
data class BackupImportResponse(
    val ok: Boolean,
    val mode: String,
    val manifest: BackupManifestDto,
    @SerialName("conversations_added") val conversationsAdded: Int,
    @SerialName("conversations_skipped") val conversationsSkipped: Int,
    @SerialName("messages_imported") val messagesImported: Int,
    @SerialName("attachments_imported") val attachmentsImported: Int,
    @SerialName("pre_import_backup_path") val preImportBackupPath: String,
    @SerialName("restart_recommended") val restartRecommended: Boolean,
)

// ─── Claude auth-mode (Pro/Max | direct API | Bedrock) ────────────────────

@Serializable
data class ClaudeAuthDto(
    val mode: String,
    @SerialName("api_key_masked") val apiKeyMasked: String = "",
    @SerialName("aws_region") val awsRegion: String = "",
    @SerialName("aws_access_key_id_masked") val awsAccessKeyIdMasked: String = "",
    @SerialName("aws_secret_access_key_masked") val awsSecretAccessKeyMasked: String = "",
    @SerialName("aws_session_token_masked") val awsSessionTokenMasked: String = "",
    @SerialName("bedrock_opus_model") val bedrockOpusModel: String = "",
    @SerialName("bedrock_sonnet_model") val bedrockSonnetModel: String = "",
    @SerialName("bedrock_haiku_model") val bedrockHaikuModel: String = "",
    @SerialName("bedrock_model_alias") val bedrockModelAlias: String = "opus",
    /** Globales Standard-Modell (Pro/Max + API). "" = automatisch. */
    @SerialName("default_model") val defaultModel: String = "",
    @SerialName("api_key_set") val apiKeySet: Boolean = false,
    @SerialName("aws_access_key_set") val awsAccessKeySet: Boolean = false,
    @SerialName("aws_secret_set") val awsSecretSet: Boolean = false,
)

@Serializable
data class ClaudeAuthUpdateRequest(
    val mode: String? = null,
    @SerialName("api_key") val apiKey: String? = null,
    @SerialName("aws_region") val awsRegion: String? = null,
    @SerialName("aws_access_key_id") val awsAccessKeyId: String? = null,
    @SerialName("aws_secret_access_key") val awsSecretAccessKey: String? = null,
    @SerialName("aws_session_token") val awsSessionToken: String? = null,
    @SerialName("bedrock_opus_model") val bedrockOpusModel: String? = null,
    @SerialName("bedrock_sonnet_model") val bedrockSonnetModel: String? = null,
    @SerialName("bedrock_haiku_model") val bedrockHaikuModel: String? = null,
    @SerialName("bedrock_model_alias") val bedrockModelAlias: String? = null,
    /** "" leert (→ automatisch); null lässt unverändert. */
    @SerialName("default_model") val defaultModel: String? = null,
)

@Serializable
data class UsageStatsDto(
    val period: String,
    @SerialName("period_start") val periodStart: String,
    @SerialName("period_end") val periodEnd: String,
    @SerialName("input_tokens") val inputTokens: Long,
    @SerialName("output_tokens") val outputTokens: Long,
    @SerialName("cache_create_tokens") val cacheCreateTokens: Long,
    @SerialName("cache_read_tokens") val cacheReadTokens: Long,
    @SerialName("request_count") val requestCount: Long,
    val provider: String,
)

/**
 * Stream events from the server (matched to SSE `event:` types in server.py).
 */
sealed interface StreamEvent {
    data class TitleUpdated(val newTitle: String) : StreamEvent
    data class UserSaved(val userMessageId: Long) : StreamEvent
    data object CompactionStarted : StreamEvent
    data object CompactionDone : StreamEvent
    data class Delta(val text: String) : StreamEvent
    data class ThinkingDelta(val text: String) : StreamEvent
    data object BlockStop : StreamEvent
    /** Das Modell hat mitten in der Antwort Bilder erzeugt. */
    data class ImagesReady(val attachments: List<AttachmentRefDto>) : StreamEvent
    data class Done(
        val assistantMessageId: Long,
        val tokensIn: Int,
        val tokensOut: Int,
        val tokensCachedRead: Int = 0,
        val tokensCachedWrite: Int = 0,
    ) : StreamEvent
    data class ErrorEvent(val message: String) : StreamEvent
}

/** POST /tts/live: ein Stueck der laufenden Antwort zum Vorlesen. */
@Serializable
data class LiveTtsRequestDto(
    val text: String,
    val voice: String? = null,
    val rate: Float? = null,
)

@Serializable
data class LiveTtsResponseDto(val id: String)
