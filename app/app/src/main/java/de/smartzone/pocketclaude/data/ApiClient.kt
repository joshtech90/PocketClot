package de.smartzone.pocketclaude.data

import android.net.Uri
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.channels.trySendBlocking
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.flow.flowOn
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.decodeFromJsonElement
import okhttp3.Call
import okhttp3.Callback
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import okhttp3.sse.EventSource
import okhttp3.sse.EventSourceListener
import okhttp3.sse.EventSources
import java.io.IOException
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

class ApiException(val code: Int, val body: String) : IOException("HTTP $code: $body")

class ApiClient(
    private val client: OkHttpClient,
    /** Separater Client für Endlos-Streams (SSE). Hat `readTimeout = 0`.
     *  Default = derselbe Client; AppContainer reicht zwei verschiedene rein. */
    private val streamingClient: OkHttpClient = client,
    private val settings: SettingsRepository,
) {
    @Suppress("unused")  // Backward-compat single-client Konstruktor
    constructor(client: OkHttpClient, settings: SettingsRepository) :
        this(client, client, settings)

    private val json = Json {
        ignoreUnknownKeys = true
        encodeDefaults = true
    }

    private suspend fun baseUrl(): String {
        val s = settings.current()
        require(s.isConfigured) { "Server URL and token must be set in settings." }
        return s.serverUrl
    }

    private suspend fun authHeader(): String {
        return "Bearer ${settings.current().serverToken}"
    }

    private suspend inline fun <reified T> get(path: String): T {
        val req = Request.Builder()
            .url("${baseUrl()}$path")
            .header("Authorization", authHeader())
            .get()
            .build()
        return execute(req)
    }

    private suspend inline fun <reified Body, reified R> postJson(path: String, body: Body): R {
        val payload = json.encodeToString(body).toRequestBody("application/json".toMediaType())
        val req = Request.Builder()
            .url("${baseUrl()}$path")
            .header("Authorization", authHeader())
            .post(payload)
            .build()
        return execute(req)
    }

    private suspend inline fun <reified Body, reified R> patchJson(path: String, body: Body): R {
        val payload = json.encodeToString(body).toRequestBody("application/json".toMediaType())
        val req = Request.Builder()
            .url("${baseUrl()}$path")
            .header("Authorization", authHeader())
            .patch(payload)
            .build()
        return execute(req)
    }

    private suspend inline fun <reified Body, reified R> putJson(path: String, body: Body): R {
        val payload = json.encodeToString(body).toRequestBody("application/json".toMediaType())
        val req = Request.Builder()
            .url("${baseUrl()}$path")
            .header("Authorization", authHeader())
            .put(payload)
            .build()
        return execute(req)
    }

    private suspend fun delete(path: String) {
        val req = Request.Builder()
            .url("${baseUrl()}$path")
            .header("Authorization", authHeader())
            .delete()
            .build()
        execute<Unit>(req)
    }

    private suspend inline fun <reified T> execute(req: Request): T {
        return suspendCancellableCoroutine { cont ->
            val call = client.newCall(req)
            cont.invokeOnCancellation { call.cancel() }
            call.enqueue(object : Callback {
                override fun onFailure(call: Call, e: IOException) {
                    cont.resumeWithException(e)
                }

                override fun onResponse(call: Call, response: Response) {
                    response.use { resp ->
                        val body = resp.body?.string().orEmpty()
                        if (!resp.isSuccessful) {
                            cont.resumeWithException(ApiException(resp.code, body))
                            return
                        }
                        try {
                            if (T::class == Unit::class) {
                                @Suppress("UNCHECKED_CAST")
                                cont.resume(Unit as T)
                            } else {
                                val parsed = json.decodeFromString<T>(body)
                                cont.resume(parsed)
                            }
                        } catch (e: Exception) {
                            cont.resumeWithException(e)
                        }
                    }
                }
            })
        }
    }

    // ---------- Auth ----------

    /**
     * Username+Passwort gegen die gegebene Server-URL eintauschen → Session-Token.
     * Wird beim Anlegen/Aktivieren eines Profils gerufen, BEVOR ein Token im
     * Settings-Repo gespeichert ist — deshalb braucht es URL/User/PW als
     * explizite Parameter und geht NICHT über `authHeader()`/`baseUrl()`.
     */
    suspend fun login(serverUrl: String, username: String, password: String): LoginResponse {
        val cleanBase = cleanServerUrl(serverUrl)
        val payload = json.encodeToString(
            LoginRequest(username = username, password = password)
        ).toRequestBody("application/json".toMediaType())
        val req = Request.Builder()
            .url("$cleanBase/auth/login")
            .post(payload)
            .build()
        return execute(req)
    }

    /** Beendet die aktuelle Server-Session (best effort). */
    suspend fun logout() {
        try {
            val req = Request.Builder()
                .url("${baseUrl()}/auth/logout")
                .header("Authorization", authHeader())
                .post("".toRequestBody("application/json".toMediaType()))
                .build()
            execute<Unit>(req)
        } catch (_: Exception) { /* swallow — Token kann schon weg sein */ }
    }

    /** Ändert das Passwort. Bei `must_change_password=1` darf `oldPassword`
     *  null sein (Forced Change nach Reset). */
    suspend fun changePassword(oldPassword: String?, newPassword: String) {
        val body = ChangePasswordRequest(
            old_password = oldPassword?.takeIf { it.isNotBlank() },
            new_password = newPassword,
        )
        val payload = json.encodeToString(body)
            .toRequestBody("application/json".toMediaType())
        val req = Request.Builder()
            .url("${baseUrl()}/auth/change-password")
            .header("Authorization", authHeader())
            .post(payload)
            .build()
        execute<Map<String, Boolean>>(req)
    }

    suspend fun me(): MeDto = get("/me")

    /** Gemeinsame Oberflaechen-Einstellungen (geteilt mit der Web-UI). */
    suspend fun getUiSettings(): UiSettingsDto = get("/ui-settings")

    /** Teil-Update: nur die mitgeschickten Schluessel aendern sich. */
    suspend fun putUiSettings(values: Map<String, kotlinx.serialization.json.JsonElement>) {
        putJson<kotlinx.serialization.json.JsonObject, kotlinx.serialization.json.JsonObject>(
            "/ui-settings", kotlinx.serialization.json.JsonObject(values),
        )
    }

    // ---------- Claude auth mode (Pro/Max | API key | Bedrock) ----------

    suspend fun getClaudeAuth(): ClaudeAuthDto = get("/me/claude-auth")

    suspend fun updateClaudeAuth(req: ClaudeAuthUpdateRequest): ClaudeAuthDto =
        putJson("/me/claude-auth", req)

    suspend fun getUsageStats(period: String = "month"): UsageStatsDto =
        get("/me/usage?period=$period")

    // ---------- Image Generation (Gemini) ----------

    suspend fun imagesConfig(): ImageConfigDto = get("/images/config")

    suspend fun setImageApiKey(apiKey: String): Map<String, String> =
        putJson("/images/credentials", ImageCredentialsRequest(apiKey))

    suspend fun deleteImageApiKey() = delete("/images/credentials")

    /** Standard-Auflösung, Seitenverhältnis und Bildmodell des Users setzen.
     *  Leerer String setzt einen Wert auf den Server-Default zurück, null lässt
     *  ihn unverändert. */
    suspend fun setImageDefaults(
        size: String? = null,
        aspectRatio: String? = null,
        model: String? = null,
        provider: String? = null,
    ): ImageConfigDto = putJson(
        "/images/defaults",
        ImageDefaultsRequest(size = size, aspectRatio = aspectRatio,
                             model = model, provider = provider),
    )

    // ---------- Chat-Modelle (Claude plus Zusatz-Modelle) ----------

    /** Liefert alle wählbaren Modelle und den Zustand der Zusatz-Gateways.
     *  `refresh = true` umgeht den serverseitigen Modell-Cache. */
    /** `include`: Modell-Key, den der Server auch dann mitliefern soll, wenn er
     *  nicht kuratiert ist. Das ist das Modell des aktuellen Chats. */
    suspend fun getChatModels(refresh: Boolean = false, include: String = ""): ChatModelsDto {
        val params = buildList {
            if (refresh) add("refresh=1")
            if (include.isNotBlank()) {
                add("include=" + java.net.URLEncoder.encode(include, "UTF-8"))
            }
        }
        val query = if (params.isEmpty()) "" else "?" + params.joinToString("&")
        return get("/chat/models$query")
    }

    suspend fun generateImage(req: ImageGenerateRequest): ImageGenerateResponse =
        postJson("/images/generate", req)

    // ---------- Voice-Input (Groq Whisper) ----------

    suspend fun voiceConfig(): VoiceConfigDto = get("/voice/config")

    suspend fun setVoiceApiKey(apiKey: String): Map<String, String> =
        putJson("/voice/credentials", VoiceCredentialsRequest(apiKey))

    suspend fun deleteVoiceApiKey() = delete("/voice/credentials")

    suspend fun setVoiceLangConfig(mode: String, locale: String?): VoiceConfigDto =
        putJson("/voice/lang-config", VoiceLangConfigRequest(mode, locale))

    suspend fun translateVoicePrompt(locale: String, force: Boolean = false): VoiceTranslateResponse =
        postJson("/voice/prompt/translate", VoiceTranslateRequest(locale, force))

    suspend fun deleteCachedVoicePrompt(locale: String) =
        delete("/voice/prompt/cache/$locale")

    /** Schickt eine Audio-Datei (m4a/aac, mono 16 kHz) an Groq Whisper,
     *  zurück kommt der Transkript-Text. `language` ist die UI-Locale
     *  (`en`, `de`, `pt-BR`, …) — der Server mappt auf den passenden
     *  Whisper-Bias-Prompt. */
    suspend fun transcribeVoice(
        bytes: ByteArray,
        filename: String,
        mime: String,
        language: String,
    ): VoiceTranscribeResponse {
        val body = MultipartBody.Builder()
            .setType(MultipartBody.FORM)
            .addFormDataPart(
                "file",
                filename,
                bytes.toRequestBody(mime.toMediaType()),
            )
            .addFormDataPart("language", language)
            .build()
        val req = Request.Builder()
            .url("${baseUrl()}/voice/transcribe")
            .header("Authorization", authHeader())
            .post(body)
            .build()
        return execute(req)
    }

    // ---------- Public API ----------

    suspend fun health(): HealthDto = get("/health")

    suspend fun listConversations(): List<ConversationDto> = get("/conversations")

    suspend fun createConversation(title: String? = null, gemId: String? = null): ConversationDto =
        postJson("/conversations", CreateConversationRequest(title, gemId))

    suspend fun getConversation(id: String): ConversationDetailDto = get("/conversations/$id")

    suspend fun deleteConversation(id: String) = delete("/conversations/$id")

    suspend fun renameConversation(id: String, title: String): ConversationDto =
        patchJson("/conversations/$id", PatchConversationRequest(title = title))

    suspend fun setPinned(id: String, pinned: Boolean): ConversationDto =
        patchJson("/conversations/$id", PatchConversationRequest(pinned = pinned))

    /** Merkt das gewählte Modell am Chat. Leerer String = zurück auf Claude. */
    suspend fun setChatModel(id: String, modelKey: String): ConversationDto =
        patchJson("/conversations/$id", PatchConversationRequest(chatModel = modelKey))

    suspend fun setChatEffort(id: String, effort: String): ConversationDto =
        patchJson("/conversations/$id", PatchConversationRequest(chatEffort = effort))

    /** Springt im Chat zu einer frueheren Antwort zurueck. */
    suspend fun rewindConversation(
        id: String, messageId: Long, chatModel: String? = null,
    ): RewindResponse = postJson(
        "/conversations/$id/rewind",
        RewindRequest(messageId = messageId, chatModel = chatModel),
    )

    suspend fun setLocked(id: String, locked: Boolean): ConversationDto =
        patchJson("/conversations/$id", PatchConversationRequest(locked = locked))

    // ---------- Chat-Sperre (globaler PIN) ----------

    suspend fun getChatLock(): ChatLockStatusDto = get("/me/chat-lock")

    /** Setzt oder ändert den globalen PIN. `currentPin` nur nötig wenn schon einer existiert. */
    suspend fun setChatLockPin(pin: String, currentPin: String? = null): ChatLockStatusDto =
        putJson("/me/chat-lock", ChatLockSetRequest(pin = pin, currentPin = currentPin))

    suspend fun clearChatLockPin(currentPin: String): ChatLockStatusDto =
        postJson("/me/chat-lock/clear", ChatLockClearRequest(currentPin = currentPin))

    suspend fun verifyChatLockPin(pin: String): ChatLockVerifyResponse =
        postJson("/me/chat-lock/verify", ChatLockVerifyRequest(pin = pin))

    suspend fun search(query: String, limit: Int = 30): SearchResponseDto {
        // OkHttp's HttpUrl-Builder kümmert sich um korrektes URL-Encoding der
        // Query-Params, inklusive Sonderzeichen, Unicode, Umlaute etc.
        val url = "${baseUrl()}/search".toHttpUrlOrNull()
            ?.newBuilder()
            ?.addQueryParameter("q", query)
            ?.addQueryParameter("limit", limit.toString())
            ?.build()
            ?: error("Invalid server URL for search.")
        val req = Request.Builder()
            .url(url)
            .header("Authorization", authHeader())
            .get()
            .build()
        return execute(req)
    }

    /** Liefert den Markdown-Export einer Konversation als String. */
    suspend fun exportMarkdown(id: String): String {
        val req = Request.Builder()
            .url("${baseUrl()}/conversations/$id/export.md")
            .header("Authorization", authHeader())
            .get()
            .build()
        return suspendCancellableCoroutine { cont ->
            val call = client.newCall(req)
            cont.invokeOnCancellation { call.cancel() }
            call.enqueue(object : Callback {
                override fun onFailure(call: Call, e: IOException) {
                    cont.resumeWithException(e)
                }
                override fun onResponse(call: Call, response: Response) {
                    response.use { resp ->
                        val body = resp.body?.string().orEmpty()
                        if (!resp.isSuccessful) {
                            cont.resumeWithException(ApiException(resp.code, body))
                        } else {
                            cont.resume(body)
                        }
                    }
                }
            })
        }
    }

    // ---------- TTS ----------

    suspend fun getTtsStatus(): TtsStatusDto = get("/tts/status")





    // ---------- Multi-Key-Pool (für Free-Tier-Throughput-Skalierung) ----------





    // ---------- Settings Export / Import ----------

    /** Holt das Server-Anteil des Settings-Exports (alle KV-Werte inkl.
     *  Klartext-API-Keys). */
    suspend fun exportServerSettings(): ServerSettingsExportDto =
        get("/settings/export")

    /** Wendet ein Settings-Bundle auf den aktuellen Server-User an. */
    suspend fun importServerSettings(req: ServerSettingsImportRequest): SettingsImportResponseDto =
        postJson("/settings/import", req)

    // ---------- Skills (Default + Per-Chat-Override) ----------

    suspend fun getDefaultSkills(): SkillsDto = get("/skills/defaults")

    suspend fun setDefaultSkills(skills: SkillsDto): SkillsDto =
        putJson("/skills/defaults", SkillsDefaultsRequest(skills))

    suspend fun getConversationSkills(cid: String): ConversationSkillsResponse =
        get("/conversations/$cid/skills")

    /** `skills=null` löscht den Override → User-Default greift wieder. */
    suspend fun setConversationSkills(cid: String, skills: SkillsDto?): ConversationSkillsResponse =
        putJson("/conversations/$cid/skills", ConversationSkillsRequest(skills))

    // ---------- Gems (Custom Agents) ----------

    suspend fun listGems(): List<GemDto> = get("/me/gems")

    suspend fun getGem(id: String): GemDto = get("/me/gems/$id")

    suspend fun createGem(req: GemUpsertRequest): GemDto = postJson("/me/gems", req)

    suspend fun updateGem(id: String, req: GemUpsertRequest): GemDto = putJson("/me/gems/$id", req)

    suspend fun deleteGem(id: String) = delete("/me/gems/$id")

    suspend fun listGemFiles(gemId: String): List<GemFileDto> = get("/me/gems/$gemId/files")

    suspend fun deleteGemFile(gemId: String, attachmentId: String) =
        delete("/me/gems/$gemId/files/$attachmentId")

    /** Lädt eine Wissens-/Referenzdatei zu einem Gem hoch (gleiche Multipart-
     *  Pipeline wie Chat-Anhänge, nur anderer Endpoint). */
    suspend fun uploadGemFile(
        gemId: String,
        filename: String,
        mime: String,
        bytes: ByteArray,
    ): GemFileDto {
        val body = MultipartBody.Builder()
            .setType(MultipartBody.FORM)
            .addFormDataPart(
                "file",
                filename,
                bytes.toRequestBody(mime.toMediaType()),
            )
            .build()
        val req = Request.Builder()
            .url("${baseUrl()}/me/gems/$gemId/files")
            .header("Authorization", authHeader())
            .post(body)
            .build()
        return execute(req)
    }

    /** Setzt den TTS-Provider per User: "gemini_api" (8 € Hard-Cap) oder
     *  "cloud_tts" (Service-Account, kein Hard-Cap). */
    suspend fun setTtsProvider(provider: String): TtsStatusDto {
        return execute(
            Request.Builder()
                .url("${baseUrl()}/tts/provider")
                .header("Authorization", authHeader())
                .put(
                    json.encodeToString(TtsProviderRequest(provider))
                        .toRequestBody("application/json".toMediaType())
                )
                .build()
        )
    }



    /** Setzt die Chunking-Option des Users.
     *  - `enabled=true/false` → explizites KV-Setting (überschreibt Provider-Default)
     *  - `enabled=null`       → KV löschen, Provider-Default greift wieder */
    suspend fun setTtsChunking(enabled: Boolean?): TtsStatusDto {
        return execute(
            Request.Builder()
                .url("${baseUrl()}/tts/chunking")
                .header("Authorization", authHeader())
                .put(
                    json.encodeToString(TtsChunkingRequest(enabled))
                        .toRequestBody("application/json".toMediaType())
                )
                .build()
        )
    }

    /** Baut die Audio-URL für eine Message inkl. optionaler Voice, Rate und
     *  Auth-Token als Query-Param. Token in der URL ist nötig, weil ExoPlayer
     *  Medien progressive über seinen eigenen HTTP-Stack lädt und keine
     *  zusätzlichen Header mitgeben kann. Server akzeptiert für genau diesen
     *  Endpoint Token via `?token=` als Alternative zum Authorization-Header. */
    suspend fun audioUrl(messageId: Long, voice: String?, rate: Float? = null): String {
        val s = settings.current()
        val base = s.serverUrl
        val params = buildList {
            if (!voice.isNullOrBlank()) add("voice=${Uri.encode(voice)}")
            if (rate != null && rate > 0f) add("rate=$rate")
            if (s.serverToken.isNotBlank()) add("token=${Uri.encode(s.serverToken)}")
        }
        val q = if (params.isEmpty()) "" else "?" + params.joinToString("&")
        return "$base/messages/$messageId/audio$q"
    }

    /** Auth-Headers für MediaPlayer-Streaming. */
    suspend fun authHeaders(): Map<String, String> =
        mapOf("Authorization" to authHeader())

    /** Lädt das komplette Server-Backup als ZIP-Bytes herunter. Optional
     *  AES-256 verschlüsselt mit `password`. */
    suspend fun downloadBackup(password: String? = null): ByteArray = withContext(Dispatchers.IO) {
        val q = if (!password.isNullOrBlank()) "?password=${Uri.encode(password)}" else ""
        val req = Request.Builder()
            .url("${baseUrl()}/backup$q")
            .header("Authorization", authHeader())
            .header("Accept", "application/zip")
            .get()
            .build()
        client.newCall(req).execute().use { resp ->
            if (!resp.isSuccessful) {
                val body = resp.body?.string()?.take(400).orEmpty()
                throw ApiException(resp.code, body)
            }
            resp.body?.bytes() ?: throw IOException("Leere Backup-Response")
        }
    }

    /** Liest nur das Manifest aus einem ZIP — für den Confirm-Dialog.
     *  Wirft `ApiException(423, ...)` wenn ZIP verschlüsselt ist und Passwort
     *  fehlt/falsch ist — App reagiert mit PW-Prompt. */
    suspend fun peekBackup(zipBytes: ByteArray, password: String? = null): BackupPeekResponse {
        val body = MultipartBody.Builder()
            .setType(MultipartBody.FORM)
            .addFormDataPart(
                "file",
                "backup.zip",
                zipBytes.toRequestBody("application/zip".toMediaType()),
            )
            .build()
        val q = if (!password.isNullOrBlank()) "?password=${Uri.encode(password)}" else ""
        val req = Request.Builder()
            .url("${baseUrl()}/backup/peek$q")
            .header("Authorization", authHeader())
            .post(body)
            .build()
        return execute(req)
    }

    /** Importiert ein Backup-ZIP. mode = "replace" oder "merge". Wirft
     *  `ApiException(423, ...)` wenn verschlüsselt + PW falsch/fehlt. */
    suspend fun importBackup(
        zipBytes: ByteArray,
        mode: String,
        password: String? = null,
    ): BackupImportResponse {
        val body = MultipartBody.Builder()
            .setType(MultipartBody.FORM)
            .addFormDataPart(
                "file",
                "backup.zip",
                zipBytes.toRequestBody("application/zip".toMediaType()),
            )
            .build()
        val params = buildList {
            add("mode=$mode")
            if (!password.isNullOrBlank()) add("password=${Uri.encode(password)}")
        }
        val req = Request.Builder()
            .url("${baseUrl()}/backup/import?${params.joinToString("&")}")
            .header("Authorization", authHeader())
            .post(body)
            .build()
        return execute(req)
    }

    suspend fun uploadAttachment(
        filename: String,
        mime: String,
        bytes: ByteArray,
    ): AttachmentDto {
        val body = MultipartBody.Builder()
            .setType(MultipartBody.FORM)
            .addFormDataPart(
                "file",
                filename,
                bytes.toRequestBody(mime.toMediaType()),
            )
            .build()
        val req = Request.Builder()
            .url("${baseUrl()}/attachments")
            .header("Authorization", authHeader())
            .post(body)
            .build()
        return execute(req)
    }

    /**
     * Send a user message and stream the assistant reply via SSE.
     */
    fun streamMessage(
        conversationId: String,
        request: SendMessageRequest,
    ): Flow<StreamEvent> = callbackFlow {
        // Ein einziger Profil-Stand fuer URL, Token und Schluessel: ein Profilwechsel
        // waehrend des Aufbaus darf den Schluessel nie an einen anderen Server schicken.
        val stand = settings.current()
        require(stand.isConfigured) { "Server URL and token must be set in settings." }
        val base = stand.serverUrl
        val auth = "Bearer ${stand.serverToken}"
        val url = "$base/conversations/$conversationId/messages".toHttpUrlOrNull()
            ?: error("Invalid server URL: $base")
        // Gedaechtnis-Schluessel nur an den Server, fuer den er eingetragen wurde, nur ueber
        // HTTPS und nur bei Chat-Nachrichten. Der Server entschluesselt damit nur fuer diese Antwort.
        val wissenSchluessel = settings.wissenSchluesselFuer(stand.activeProfileId, url)
            .takeIf { it.isNotBlank() && url.isHttps }

        val builder = Request.Builder()
            .url(url)
            .header("Authorization", auth)
            .header("Accept", "text/event-stream")
        if (wissenSchluessel != null) builder.header("X-Wissen-Schluessel", wissenSchluessel)
        val req = builder
            .post(
                json.encodeToString(request)
                    .toRequestBody("application/json".toMediaType())
            )
            .build()

        // SSE-Streams nutzen den Client OHNE Read-Timeout, sonst bricht der
        // Stream bei längeren Thinking-Pausen ab.
        // Mit Schluessel keine Weiterleitungen folgen: OkHttp entfernt bei einem Wechsel des
        // Hosts nur den Authorization-Header, den Gedaechtnis-Schluessel wuerde es mitschicken.
        val sseClient = if (wissenSchluessel != null)
            streamingClient.newBuilder().followRedirects(false).followSslRedirects(false).build()
        else streamingClient
        val factory = EventSources.createFactory(sseClient)
        val source: EventSource = factory.newEventSource(req, object : EventSourceListener() {
            override fun onEvent(
                eventSource: EventSource,
                id: String?,
                type: String?,
                data: String,
            ) {
                val event = parseEvent(type, data)
                if (event != null) {
                    // Blockierend senden: OkHttp ruft das auf seinem eigenen Lese-Thread
                    // auf. `trySend` hat bei vollem Puffer (64 Events) still Deltas
                    // verworfen, wenn die Oberflaeche beim schnellen Streamen nicht
                    // hinterherkam. Dann fehlten mitten in der Antwort Satzteile oder
                    // das `done` ging verloren und die Antwort brach einfach ab.
                    trySendBlocking(event)
                    if (event is StreamEvent.Done || event is StreamEvent.ErrorEvent) {
                        close()
                    }
                }
            }

            override fun onFailure(eventSource: EventSource, t: Throwable?, response: Response?) {
                // `response.message` ist bei HTTP/2 (Tailscale, Cloudflare) immer
                // leer; dann kam ein leerer Fehlertext an. Der Server schreibt den
                // Grund als JSON-`detail` in den Body.
                val msg = t?.message ?: response?.let { r ->
                    val body = runCatching { r.peekBody(4096).string() }.getOrDefault("")
                    val detail = runCatching {
                        (json.parseToJsonElement(body) as? kotlinx.serialization.json.JsonObject)
                            ?.get("detail")?.let { (it as? kotlinx.serialization.json.JsonPrimitive)?.content }
                    }.getOrNull()
                    "HTTP ${r.code}: " + (detail ?: r.message.ifBlank { body.take(200) })
                } ?: "Verbindung verloren"
                trySendBlocking(StreamEvent.ErrorEvent(msg))
                close(t)
            }

            override fun onClosed(eventSource: EventSource) {
                close()
            }
        })

        awaitClose { source.cancel() }
    }.flowOn(Dispatchers.IO)

    private fun parseEvent(type: String?, data: String): StreamEvent? {
        return try {
            val element = json.parseToJsonElement(data)
            val obj = element as? kotlinx.serialization.json.JsonObject

            fun str(key: String): String =
                (obj?.get(key) as? kotlinx.serialization.json.JsonPrimitive)?.content.orEmpty()

            fun long(key: String): Long =
                (obj?.get(key) as? kotlinx.serialization.json.JsonPrimitive)?.content?.toLongOrNull() ?: 0L

            fun int(key: String): Int =
                (obj?.get(key) as? kotlinx.serialization.json.JsonPrimitive)?.content?.toIntOrNull() ?: 0

            when (type) {
                "title" -> StreamEvent.TitleUpdated(str("title"))
                "user_saved" -> StreamEvent.UserSaved(long("user_message_id"))
                "compaction_started" -> StreamEvent.CompactionStarted
                "compaction_done" -> StreamEvent.CompactionDone
                "delta" -> StreamEvent.Delta(str("text"))
                "thinking_delta" -> StreamEvent.ThinkingDelta(str("text"))
                "block_stop" -> StreamEvent.BlockStop
                "image" -> {
                    // Das Modell hat mitten in der Antwort Bilder erzeugt. Die
                    // Attachments hängen beim `done` auch an der DB-Message, das
                    // Event ist nur dafür da, dass sie sofort sichtbar werden.
                    val arr = obj?.get("attachments")
                    val atts = if (arr != null) {
                        runCatching {
                            json.decodeFromJsonElement<List<AttachmentRefDto>>(arr)
                        }.getOrDefault(emptyList())
                    } else emptyList()
                    StreamEvent.ImagesReady(atts)
                }
                "done" -> StreamEvent.Done(
                    assistantMessageId = long("assistant_message_id"),
                    tokensIn = int("tokens_in"),
                    tokensOut = int("tokens_out"),
                    tokensCachedRead = int("tokens_cached_read"),
                    tokensCachedWrite = int("tokens_cached_write"),
                )
                "error" -> StreamEvent.ErrorEvent(str("message").ifEmpty { "Unbekannter Fehler" })
                else -> null
            }
        } catch (_: Exception) {
            null
        }
    }
}
