package de.smartzone.pocketclaude.data

import android.content.Context
import android.net.Uri
import android.webkit.MimeTypeMap
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.withContext

/**
 * Higher-level facade combining API + local context concerns.
 */
class ChatRepository(
    private val api: ApiClient,
    private val context: Context,
) {

    suspend fun health(): HealthDto = api.health()

    // Auth
    suspend fun login(url: String, username: String, password: String): LoginResponse =
        api.login(url, username, password)
    suspend fun logout() = api.logout()
    suspend fun changePassword(oldPw: String?, newPw: String) =
        api.changePassword(oldPw, newPw)
    suspend fun me(): MeDto = api.me()

    // Image Generation
    suspend fun imagesConfig(): ImageConfigDto = api.imagesConfig()
    suspend fun setImageApiKey(key: String) = api.setImageApiKey(key)
    suspend fun deleteImageApiKey() = api.deleteImageApiKey()
    suspend fun generateImage(req: ImageGenerateRequest): ImageGenerateResponse =
        api.generateImage(req)

    // Voice-Input (Groq Whisper)
    suspend fun voiceConfig(): VoiceConfigDto = api.voiceConfig()
    suspend fun setVoiceApiKey(key: String) = api.setVoiceApiKey(key)
    suspend fun deleteVoiceApiKey() = api.deleteVoiceApiKey()
    suspend fun setVoiceLangConfig(mode: String, locale: String?): VoiceConfigDto =
        api.setVoiceLangConfig(mode, locale)
    suspend fun translateVoicePrompt(locale: String, force: Boolean = false): VoiceTranslateResponse =
        api.translateVoicePrompt(locale, force)
    suspend fun deleteCachedVoicePrompt(locale: String) = api.deleteCachedVoicePrompt(locale)

    suspend fun list(): List<ConversationDto> = api.listConversations()

    suspend fun create(title: String? = null, gemId: String? = null): ConversationDto =
        api.createConversation(title, gemId)

    suspend fun detail(id: String): ConversationDetailDto = api.getConversation(id)

    suspend fun delete(id: String) = api.deleteConversation(id)

    suspend fun rename(id: String, title: String): ConversationDto = api.renameConversation(id, title)
    suspend fun setPinned(id: String, pinned: Boolean): ConversationDto = api.setPinned(id, pinned)
    suspend fun setLocked(id: String, locked: Boolean): ConversationDto = api.setLocked(id, locked)

    // ---------- Chat-Sperre (globaler PIN) ----------
    suspend fun getChatLock(): ChatLockStatusDto = api.getChatLock()
    suspend fun setChatLockPin(pin: String, currentPin: String? = null): ChatLockStatusDto =
        api.setChatLockPin(pin, currentPin)
    suspend fun clearChatLockPin(currentPin: String): ChatLockStatusDto =
        api.clearChatLockPin(currentPin)
    suspend fun verifyChatLockPin(pin: String): ChatLockVerifyResponse = api.verifyChatLockPin(pin)

    suspend fun search(query: String): SearchResponseDto = api.search(query)
    suspend fun exportMarkdown(id: String): String = api.exportMarkdown(id)

    // Skills (Default + Per-Chat-Override)
    suspend fun getDefaultSkills(): SkillsDto = api.getDefaultSkills()
    suspend fun setDefaultSkills(skills: SkillsDto): SkillsDto = api.setDefaultSkills(skills)
    suspend fun getConversationSkills(cid: String): ConversationSkillsResponse =
        api.getConversationSkills(cid)
    /** `skills=null` löscht den Override → User-Default greift. */
    suspend fun setConversationSkills(cid: String, skills: SkillsDto?): ConversationSkillsResponse =
        api.setConversationSkills(cid, skills)

    // Gems (Custom Agents)
    suspend fun listGems(): List<GemDto> = api.listGems()
    suspend fun getGem(id: String): GemDto = api.getGem(id)
    suspend fun createGem(req: GemUpsertRequest): GemDto = api.createGem(req)
    suspend fun updateGem(id: String, req: GemUpsertRequest): GemDto = api.updateGem(id, req)
    suspend fun deleteGem(id: String) = api.deleteGem(id)
    suspend fun listGemFiles(gemId: String): List<GemFileDto> = api.listGemFiles(gemId)
    suspend fun deleteGemFile(gemId: String, attachmentId: String) =
        api.deleteGemFile(gemId, attachmentId)
    suspend fun uploadGemFileFromUri(gemId: String, uri: Uri): GemFileDto {
        val (filename, mime, bytes) = readUpload(uri)
        return api.uploadGemFile(gemId, filename, mime, bytes)
    }

    // Billing (Cloud-Spend + Credit)
    suspend fun billingStatus(): BillingStatusDto = api.getBillingStatus()

    // Claude auth-mode + usage stats
    suspend fun getClaudeAuth(): ClaudeAuthDto = api.getClaudeAuth()
    suspend fun updateClaudeAuth(req: ClaudeAuthUpdateRequest): ClaudeAuthDto = api.updateClaudeAuth(req)
    suspend fun getUsageStats(period: String): UsageStatsDto = api.getUsageStats(period)

    // TTS
    suspend fun ttsStatus(): TtsStatusDto = api.getTtsStatus()

    // Welcher Vorlese-Anbieter aktiv ist, braucht der Chat bei jedem Tippen auf
    // "Vorlesen" — aber nur, um zu entscheiden, wer die Geschwindigkeit macht.
    // Deshalb einmal holen und ein paar Minuten behalten, statt vor jedem
    // Abspielen eine zusaetzliche Anfrage zu schicken.
    private var cachedTtsProvider: String? = null
    private var cachedTtsProviderAt: Long = 0L

    suspend fun ttsProviderCached(): String {
        val jetzt = System.currentTimeMillis()
        val gemerkt = cachedTtsProvider
        if (gemerkt != null && jetzt - cachedTtsProviderAt < 5 * 60_000L) return gemerkt
        return try {
            val p = api.getTtsStatus().provider
            cachedTtsProvider = p
            cachedTtsProviderAt = jetzt
            p
        } catch (e: Exception) {
            // Kein Status erreichbar: der alte Weg (Server macht das Tempo) ist
            // die sichere Annahme, sonst klingt Audio unerwartet beschleunigt.
            gemerkt ?: ""
        }
    }

    suspend fun setTtsCredentials(json: String): TtsStatusDto = api.setTtsCredentials(json)
    suspend fun deleteTtsCredentials() = api.deleteTtsCredentials()
    suspend fun setTtsProvider(provider: String): TtsStatusDto {
        cachedTtsProvider = null
        return api.setTtsProvider(provider)
    }
    suspend fun setTtsModel(modelId: String): TtsStatusDto = api.setTtsModel(modelId)
    suspend fun setTtsChunking(enabled: Boolean?): TtsStatusDto = api.setTtsChunking(enabled)
    suspend fun setTtsApiKey(key: String): TtsStatusDto = api.setTtsApiKey(key)
    suspend fun deleteTtsApiKey(): TtsStatusDto = api.deleteTtsApiKey()
    // Multi-Key-Pool
    suspend fun listTtsApiKeys(): TtsApiKeysDto = api.listTtsApiKeys()
    suspend fun addTtsApiKey(apiKey: String, label: String = ""): TtsApiKeysDto =
        api.addTtsApiKey(apiKey, label)
    suspend fun removeTtsApiKey(keyId: String): TtsApiKeysDto = api.removeTtsApiKey(keyId)
    suspend fun relabelTtsApiKey(keyId: String, label: String): TtsApiKeysDto =
        api.relabelTtsApiKey(keyId, label)

    // Settings Export / Import (Server-Anteil)
    suspend fun exportServerSettings(): ServerSettingsExportDto =
        api.exportServerSettings()
    suspend fun importServerSettings(req: ServerSettingsImportRequest): SettingsImportResponseDto =
        api.importServerSettings(req)
    suspend fun audioUrl(messageId: Long, voice: String?, rate: Float? = null): String =
        api.audioUrl(messageId, voice, rate)

    // Backup-Endpoints (pass-through)
    suspend fun downloadBackup(password: String? = null): ByteArray =
        api.downloadBackup(password)
    suspend fun peekBackup(zip: ByteArray, password: String? = null): BackupPeekResponse =
        api.peekBackup(zip, password)
    suspend fun importBackup(zip: ByteArray, mode: String, password: String? = null): BackupImportResponse =
        api.importBackup(zip, mode, password)
    suspend fun audioHeaders(): Map<String, String> = api.authHeaders()

    fun stream(
        id: String,
        content: String,
        attachmentIds: List<String>,
        effort: String = DEFAULT_EFFORT,
        model: String? = null,
        systemPrompt: String? = null,
        ttsVoice: String? = null,
        ttsRate: Float? = null,
    ): Flow<StreamEvent> =
        api.streamMessage(id, SendMessageRequest(
            content = content,
            attachmentIds = attachmentIds,
            effort = effort,
            // Leerer String heisst „nimm Claude" und muss so beim Server
            // ankommen. Nur `null` bedeutet „keine Angabe, entscheide selbst".
            model = model,
            systemPrompt = systemPrompt,
            ttsVoice = ttsVoice,
            ttsRate = ttsRate,
        ))

    suspend fun setImageDefaults(
        size: String?, aspectRatio: String?, model: String?, provider: String? = null,
    ): ImageConfigDto = api.setImageDefaults(size, aspectRatio, model, provider)

    /** Alle wählbaren Modelle plus Gateway-Zustand. */
    suspend fun getChatModels(refresh: Boolean = false, include: String = ""): ChatModelsDto =
        api.getChatModels(refresh, include)

    /** Merkt das gewählte Modell am Chat, damit es beim nächsten Öffnen wieder
     *  greift. Leerer String setzt den Chat zurück auf Claude. */
    suspend fun setChatModel(cid: String, modelKey: String): ConversationDto =
        api.setChatModel(cid, modelKey)

    /** Springt zu einer frueheren Antwort zurueck, optional mit Modellwechsel. */
    suspend fun rewind(cid: String, messageId: Long, chatModel: String? = null): RewindResponse =
        api.rewindConversation(cid, messageId, chatModel)

    suspend fun uploadFromUri(
        uri: Uri,
        purpose: ImageCompressor.Purpose = ImageCompressor.Purpose.VISION,
    ): AttachmentDto {
        val (filename, mime, bytes) = readUpload(uri, purpose)
        return api.uploadAttachment(filename, mime, bytes)
    }

    /** Liest einen content-URI in (filename, mime, bytes) — inkl. Bild-Kompression.
     *  Geteilt von Chat-Anhängen und Gem-Wissensdateien. */
    private suspend fun readUpload(
        uri: Uri,
        purpose: ImageCompressor.Purpose = ImageCompressor.Purpose.VISION,
    ): ImageCompressor.Result =
        withContext(Dispatchers.IO) {
            val resolver = context.contentResolver
            val rawMime = resolver.getType(uri)
                ?: MimeTypeMap.getSingleton()
                    .getMimeTypeFromExtension(uri.lastPathSegment?.substringAfterLast('.').orEmpty())
                ?: "application/octet-stream"
            val rawName = queryDisplayName(uri) ?: "upload_${System.currentTimeMillis()}"
            val rawBytes = resolver.openInputStream(uri)?.use { it.readBytes() }
                ?: error("Anhang nicht lesbar.")
            // Bei Bildern clientseitig runterskalieren + JPEG-recodieren — spart
            // 80–95% Speicher gegenüber Handy-Originalen, und Claude/Gemini-Vision
            // resizen eh auf ~1568px-Kante.
            ImageCompressor.maybeCompress(rawName, rawMime, rawBytes, purpose)
        }

    private fun queryDisplayName(uri: Uri): String? {
        return try {
            context.contentResolver.query(uri, null, null, null, null)?.use { c ->
                val idx = c.getColumnIndex(android.provider.OpenableColumns.DISPLAY_NAME)
                if (idx >= 0 && c.moveToFirst()) c.getString(idx) else null
            }
        } catch (_: Exception) {
            null
        }
    }
}
