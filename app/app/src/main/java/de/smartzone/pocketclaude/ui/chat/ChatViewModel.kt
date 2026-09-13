package de.smartzone.pocketclaude.ui.chat

import android.content.Context
import android.net.Uri
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import de.smartzone.pocketclaude.PocketClaudeApp
import de.smartzone.pocketclaude.R
import de.smartzone.pocketclaude.audio.VoiceRecorder
import de.smartzone.pocketclaude.data.ApiClient
import de.smartzone.pocketclaude.data.AppContainer
import de.smartzone.pocketclaude.data.AttachmentDto
import de.smartzone.pocketclaude.data.AttachmentRefDto
import de.smartzone.pocketclaude.data.AudioController
import de.smartzone.pocketclaude.data.AppSettings
import de.smartzone.pocketclaude.data.ApiException
import de.smartzone.pocketclaude.data.ChatModelFamilies
import de.smartzone.pocketclaude.data.ChatModelOption
import de.smartzone.pocketclaude.data.ClaudeModels
import de.smartzone.pocketclaude.data.EFFORT_LEVELS
import de.smartzone.pocketclaude.data.ChatRepository
import de.smartzone.pocketclaude.data.DEFAULT_EFFORT
import de.smartzone.pocketclaude.data.GatewayStatusDto
import de.smartzone.pocketclaude.data.familyForKey
import de.smartzone.pocketclaude.data.ConversationDetailDto
import de.smartzone.pocketclaude.data.LocalePrefs
import de.smartzone.pocketclaude.data.MessageDto
import de.smartzone.pocketclaude.data.SettingsRepository
import de.smartzone.pocketclaude.data.SkillsDto
import de.smartzone.pocketclaude.data.StreamEvent
import de.smartzone.pocketclaude.service.NotificationHelper
import de.smartzone.pocketclaude.service.StreamingService
import kotlinx.coroutines.Job
import kotlinx.coroutines.async
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.Dispatchers
import java.time.OffsetDateTime

data class PendingAttachment(
    val uri: Uri,
    val filename: String,
    val uploading: Boolean,
    val uploaded: AttachmentDto? = null,
    val error: String? = null,
)

data class ChatUiState(
    val conversationId: String,
    val title: String = "",
    val isLoading: Boolean = true,
    val errorMessage: String? = null,
    val messages: List<MessageDto> = emptyList(),
    val streamingText: String = "",
    val streamingThinking: String = "",
    /** Bilder, die das Modell im laufenden Turn erzeugt hat. Sie hängen beim
     *  `done` auch an der DB-Message; das hier ist nur die Sofortanzeige. */
    val streamingAttachments: List<AttachmentRefDto> = emptyList(),
    val isStreaming: Boolean = false,
    val isCompacting: Boolean = false,
    val totalTokens: Int = 0,
    val hasMidSummary: Boolean = false,
    val hasLongSummary: Boolean = false,
    val lastTurnCachedRead: Int = 0,
    val lastTurnCachedWrite: Int = 0,
    val pending: List<PendingAttachment> = emptyList(),
    val pinned: Boolean = false,
    /** UI-Riegel: dieser Chat ist gesperrt und braucht PIN/Fingerabdruck. */
    val locked: Boolean = false,
    // Gem-Bindung dieses Chats (falls „mit einem Gem" gestartet). Für Header
    // + Starter-Chips im leeren Chat.
    val gemId: String? = null,
    val gemEmoji: String = "",
    val gemName: String = "",
    val gemDescription: String = "",
    val gemStarters: List<String> = emptyList(),
    // (Image-Gen-State wurde nach ui/images/ImageGenViewModel ausgelagert —
    // Bild-Generation läuft jetzt in eigenem Screen, nicht mehr im Chat.)
    // Skills für diesen Chat: effektive Werte (Override oder User-Default).
    // `skillsIsOverride=true` → dieser Chat hat eine eigene Einstellung.
    val skills: SkillsDto? = null,
    val skillsIsOverride: Boolean = false,
    // Auto-Speak-Override für diesen Chat. null = globaler Default greift,
    // true/false = Override aktiv.
    val autoSpeakOverride: Boolean? = null,
    // ───── Modell & Denktiefe ─────
    // `modelKey` gilt für DIESEN Chat: beim Öffnen kommt er vom Server
    // (zuletzt benutzt), sonst greift die globale Wahl. Wer im Sheet umschaltet,
    // ändert beides, damit auch neue Chats das gewählte Modell erben.
    val modelKey: String = "",
    val models: List<ChatModelOption> = emptyList(),
    val gateways: List<GatewayStatusDto> = emptyList(),
    val modelsLoading: Boolean = false,
    val modelsError: String? = null,
    // ───── In-Chat-Suche ─────
    // Tritt an, wenn der User im ⋮-Menü "Im Chat suchen" wählt. Der Server
    // wird NICHT befragt — wir suchen client-seitig in `messages`. Vorteil:
    // sofortige Treffer-Anzeige, kein Network-Roundtrip, keine FTS-Limits.
    val searchActive: Boolean = false,
    val searchQuery: String = "",
    /** Message-IDs aller Treffer, in Reihenfolge des Verlaufs (alt → neu). */
    val searchMatches: List<Long> = emptyList(),
    /** Aktuell anvisierter Treffer-Index in `searchMatches`. -1 = kein Treffer. */
    val searchIndex: Int = -1,
    // ───── Voice-Input ─────
    val voiceState: VoiceState = VoiceState.Idle,
    /** Letzter Voice-Fehler (Permission denied, Groq-Fehler, Timeout, …). UI
     *  zeigt das einmal als Snackbar und ruft `clearVoiceError()`. */
    val voiceError: String? = null,
    /** Auto-Modus: nach jedem Stream-Done wird automatisch vorgelesen, dann
     *  startet die Aufnahme von alleine wieder. User stoppt mit Toggle aus. */
    val autoMode: Boolean = false,
    /** Wie lange das Mic in Folge unter dem Silence-Threshold ist, in ms.
     *  Nur während Auto-Mode + autoSendEnabled relevant. Wenn ≥ silenceTarget,
     *  wird automatisch gestoppt + gesendet. 0 = Stille noch nicht begonnen. */
    val silenceProgressMs: Long = 0L,
) {
    /** Die aktuell anvisierte Message-ID, oder null wenn kein Treffer. */
    val currentMatchMessageId: Long?
        get() = searchMatches.getOrNull(searchIndex)
}

/** Drei Phasen des Voice-Input-Zyklus.
 *  - Idle: Mic-Button bereit
 *  - Recording: MediaRecorder läuft, Pulsing-Halo sichtbar
 *  - Transcribing: Recorder gestoppt, Audio wird hochgeladen, Spinner sichtbar */
enum class VoiceState { Idle, Recording, Transcribing }

class ChatViewModel(
    private val repo: ChatRepository,
    private val cid: String,
    private val audio: AudioController,
    private val settingsRepo: SettingsRepository,
    private val appContext: Context,
    private val apiClient: ApiClient,
    private val voiceRecorder: VoiceRecorder,
) : ViewModel() {

    private val _state = MutableStateFlow(ChatUiState(conversationId = cid))
    val state: StateFlow<ChatUiState> = _state.asStateFlow()

    val audioState: StateFlow<AudioController.State> = audio.state

    private var streamJob: Job? = null

    /** Einmal-Events für den ChatScreen: transkribierter Text, der ins
     *  Input-Feld eingefügt werden soll (nur im manuellen Modus — im
     *  Auto-Modus geht der Transkript direkt zu `send()`, ohne UI-Detour). */
    private val _transcriptToInsert = MutableSharedFlow<String>(extraBufferCapacity = 4)
    val transcriptToInsert: SharedFlow<String> = _transcriptToInsert.asSharedFlow()

    /** Laufender Auto-Mode-Loop, oder null wenn aus. */
    private var autoModeJob: Job? = null

    init {
        refresh()
        observeSettings()
        loadModels()
        loadSkills()
        loadAutoSpeakOverride()
        startVoiceGuard()
    }

    /** Defensive Watchdog: wenn der LLM gerade beschäftigt ist (Stream läuft
     *  oder TTS spielt), darf NIE eine Voice-Aufnahme aktiv sein. Falls doch,
     *  brechen wir sie ab — sonst würde das Mikro die TTS-Wiedergabe vom
     *  Lautsprecher mit aufnehmen und Müll in die nächste Transkription
     *  einbauen. Wirkt in Manual UND Auto-Mode. */
    private fun startVoiceGuard() {
        viewModelScope.launch {
            kotlinx.coroutines.flow.combine(state, audio.state) { s, a ->
                s.voiceState == VoiceState.Recording &&
                    (s.isStreaming ||
                        a.loadingMessageId != null ||
                        a.playingMessageId != null)
            }.collect { needsAbort ->
                if (needsAbort) {
                    android.util.Log.w("ChatVM", "Voice guard: LLM busy " +
                        "while recording — auto-cancel.")
                    runCatching { voiceRecorder.cancel() }
                    _state.update { it.copy(voiceState = VoiceState.Idle) }
                }
            }
        }
    }

    /** Holt die Modell-Liste vom Server. Claude ist immer dabei, die
     *  Zusatz-Modelle nur wenn ein Gateway antwortet. Schlägt der Aufruf fehl,
     *  bleibt Claude wählbar und die Meldung steht im Sheet. */
    fun loadModels(refresh: Boolean = false) = viewModelScope.launch {
        _state.update { it.copy(modelsLoading = true, modelsError = null) }
        val globalKey = settingsRepo.current().chatModelKey
        // Das Modell dieses Chats mitschicken: der Server haengt es an die
        // Liste, auch wenn es nicht mehr kuratiert ist. Sonst haelt die App es
        // faelschlich fuer verschwunden und setzt den Chat zurueck.
        val wanted = _state.value.modelKey.ifBlank { globalKey }
        runCatching { repo.getChatModels(refresh, include = wanted) }
            .onSuccess { dto ->
                val options = dto.models.map { m ->
                    ChatModelOption(
                        key = m.key,
                        family = m.family,
                        label = m.label,
                        efforts = m.efforts,
                        defaultEffort = m.defaultEffort,
                        supportsVision = m.supportsVision,
                        gatewayLabel = m.gatewayLabel,
                    )
                }
                _state.update { st ->
                    // Ein Modell, das der Server nicht mehr anbietet, darf nicht
                    // stehenbleiben: sonst läuft jede Nachricht in einen Fehler.
                    val current = st.modelKey.ifBlank { globalKey }
                    val stillThere = current.isBlank() || options.any { it.key == current }
                    if (!stillThere) {
                        // Auch die globale Wahl muss weg. Sonst zeigt das Sheet
                        // zwar „Automatisch", der naechste Sendevorgang faellt
                        // aber wieder auf denselben toten Key zurueck.
                        viewModelScope.launch { settingsRepo.setChatModelKey("") }
                    }
                    st.copy(
                        models = options,
                        gateways = dto.gateways,
                        modelsLoading = false,
                        modelKey = if (stillThere) current else "",
                    )
                }
            }
            .onFailure { e ->
                // Der Server antwortet nicht mit einer Modell-Liste. Frueher blieb
                // das Sheet dann komplett leer und zeigte nur den rohen HTTP-Text,
                // obwohl Claude selbst normal weiterlief. Stattdessen: die
                // eingebauten Claude-Modelle anbieten und im Klartext sagen,
                // woran es liegt.
                val code = (e as? ApiException)?.code
                val message = when (code) {
                    // 404 heisst hier praktisch immer: der Server ist aelter als
                    // die App und kennt /chat/models noch nicht.
                    404 -> appContext.getString(R.string.model_sheet_server_outdated)
                    else -> appContext.getString(
                        R.string.model_sheet_load_failed,
                        e.message ?: e::class.java.simpleName,
                    )
                }
                val fallback = ClaudeModels.all.map { m ->
                    ChatModelOption(
                        key = m.id,
                        family = ChatModelFamilies.CLAUDE,
                        label = m.label,
                        efforts = EFFORT_LEVELS,
                        defaultEffort = DEFAULT_EFFORT,
                        supportsVision = true,
                        gatewayLabel = "",
                    )
                }
                _state.update {
                    it.copy(
                        models = fallback,
                        modelsLoading = false,
                        modelsError = message,
                        modelKey = it.modelKey.ifBlank { globalKey },
                    )
                }
            }
    }

    fun refreshModels() = loadModels(refresh = true)

    /** Modellwechsel. Gilt sofort für diesen Chat und wird die neue globale
     *  Vorauswahl, damit der nächste Chat genauso startet. */
    fun selectModel(option: ChatModelOption) = viewModelScope.launch {
        _state.update { it.copy(modelKey = option.key) }
        settingsRepo.setChatModelKey(option.key)
        runCatching { repo.setChatModel(cid, option.key) }
    }

    /**
     * Springt zu einer frueheren Antwort zurueck und macht dort weiter.
     *
     * Alles nach dieser Nachricht wird verworfen, die Nachricht selbst bleibt.
     * `modelKey` wechselt im selben Zug das Modell: meistens springt man genau
     * deshalb zurueck, naemlich um dieselbe Stelle anders weiterzugehen. Ein
     * `null` laesst das Modell unveraendert.
     *
     * Waehrend eines laufenden Streams passiert nichts: die Antwort ist noch
     * unterwegs, und sie hinter ihrem eigenen Ruecksprung ankommen zu lassen
     * waere ein Zustand, den niemand versteht.
     */
    fun rewindTo(messageId: Long, modelKey: String? = null) = viewModelScope.launch {
        if (_state.value.isStreaming) return@launch
        val vorher = _state.value.modelKey
        _state.update { it.copy(isLoading = true, errorMessage = null) }
        runCatching {
            val res = repo.rewind(cid, messageId, modelKey)
            // Bewusst INNERHALB des runCatching: schlägt das Speichern der
            // Modellwahl fehl, darf das nicht am Fehlerzweig vorbeilaufen und
            // die Ansicht in „lädt" stehenlassen.
            res.chatModel?.let { m ->
                _state.update { st -> st.copy(modelKey = m) }
                settingsRepo.setChatModelKey(m)
                // Nur bei einem ECHTEN Wechsel die Denktiefe anheben. Der
                // Endpunkt gibt das Modell auch dann zurueck, wenn es gleich
                // geblieben ist; ohne diese Pruefung wuerde schon ein reiner
                // Ruecksprung die gespeicherte Denktiefe dauerhaft verstellen.
                if (m != vorher) {
                    val family = familyForKey(m)
                    if (cachedSettings?.effortFor(family) != "high") {
                        settingsRepo.setEffortForFamily(family, "high")
                    }
                }
            }
        }
            .onSuccess { refresh() }
            .onFailure { e ->
                _state.update {
                    it.copy(isLoading = false,
                            errorMessage = e.message ?: e::class.java.simpleName)
                }
                // Der Server kann den Rücksprung ausgeführt haben und erst die
                // Antwort verloren gegangen sein. Dann zeigte die App weiter
                // Nachrichten, die es nicht mehr gibt. Also in jedem Fall neu
                // laden und den Serverstand übernehmen.
                refresh()
            }
    }

    /** Denktiefe der aktuell gewählten Familie. */
    fun effortFor(family: String): String =
        cachedSettings?.effortFor(family) ?: DEFAULT_EFFORT

    fun setEffort(family: String, effort: String) = viewModelScope.launch {
        settingsRepo.setEffortForFamily(family, effort)
    }

    // Letzter bekannter Settings-Stand, damit `effortFor` synchron aus einem
    // Composable heraus lesbar ist (der Flow unten hält ihn aktuell).
    private var cachedSettings: AppSettings? = null

    private fun observeSettings() = viewModelScope.launch {
        settingsRepo.settingsFlow.collect { s ->
            cachedSettings = s
            // Wenn der Chat selbst noch nichts gesetzt hat, folgt er der
            // globalen Wahl.
            _state.update { st ->
                if (st.modelKey.isBlank() && s.chatModelKey.isNotBlank())
                    st.copy(modelKey = s.chatModelKey) else st
            }
        }
    }

    private fun loadAutoSpeakOverride() = viewModelScope.launch {
        val override = settingsRepo.getAutoSpeakOverride(cid)
        _state.update { it.copy(autoSpeakOverride = override) }
    }

    /** Setzt den Auto-Speak-Override für diesen Chat.
     *  `override=null` → globaler Default greift wieder. */
    fun setAutoSpeakOverride(override: Boolean?) = viewModelScope.launch {
        settingsRepo.setAutoSpeakOverride(cid, override)
        _state.update { it.copy(autoSpeakOverride = override) }
    }

    /** Lädt die effektiven Skills für diese Konversation vom Server.
     *  Wird beim Eintritt in den Chat aufgerufen + nach jedem Set/Reset. */
    private fun loadSkills() = viewModelScope.launch {
        runCatching { repo.getConversationSkills(cid) }
            .onSuccess { resp ->
                _state.update {
                    it.copy(skills = resp.skills, skillsIsOverride = resp.isOverride)
                }
            }
    }

    /** Setzt einen Per-Chat-Override (`skills`). */
    fun setChatSkills(skills: SkillsDto) = viewModelScope.launch {
        runCatching { repo.setConversationSkills(cid, skills) }
            .onSuccess { resp ->
                _state.update {
                    it.copy(skills = resp.skills, skillsIsOverride = resp.isOverride)
                }
            }
            .onFailure { e ->
                _state.update {
                    it.copy(errorMessage = appContext.getString(R.string.error_skills_save, e.message ?: ""))
                }
            }
    }

    /** Löscht den Per-Chat-Override → User-Default greift wieder. */
    fun resetChatSkills() = viewModelScope.launch {
        runCatching { repo.setConversationSkills(cid, null) }
            .onSuccess { resp ->
                _state.update {
                    it.copy(skills = resp.skills, skillsIsOverride = resp.isOverride)
                }
            }
            .onFailure { e ->
                _state.update {
                    it.copy(errorMessage = appContext.getString(R.string.error_skills_reset, e.message ?: ""))
                }
            }
    }

    fun refresh() = viewModelScope.launch {
        _state.update { it.copy(isLoading = true, errorMessage = null) }
        runCatching { repo.detail(cid) }
            .onSuccess { applyDetail(it) }
            .onFailure { e ->
                _state.update { it.copy(isLoading = false, errorMessage = e.message ?: e::class.java.simpleName) }
            }
    }

    private fun applyDetail(detail: ConversationDetailDto) {
        _state.update {
            it.copy(
                isLoading = false,
                title = detail.title,
                messages = detail.messages,
                totalTokens = detail.totalTokens,
                hasMidSummary = detail.hasMidSummary,
                hasLongSummary = detail.hasLongSummary,
                pinned = detail.pinned,
                locked = detail.locked,
                gemId = detail.gemId,
                // Der Server ist die Quelle für „was lief zuletzt in diesem
                // Chat". Nur wenn er nichts weiß, greift die globale Wahl.
                modelKey = detail.chatModel?.takeIf { m -> m.isNotBlank() } ?: it.modelKey,
            )
        }
        loadGemMeta(detail.gemId)
    }

    // Zuletzt geladenes Gem — verhindert Refetch bei jedem refresh() (die gem_id
    // eines Chats ändert sich nie).
    private var lastGemMetaId: String? = null

    /** Lädt Emoji/Name/Beschreibung/Starter des gebundenen Gems (Header + leerer Chat). */
    private fun loadGemMeta(gemId: String?) {
        if (gemId.isNullOrBlank()) {
            lastGemMetaId = null
            _state.update {
                it.copy(gemEmoji = "", gemName = "", gemDescription = "", gemStarters = emptyList())
            }
            return
        }
        if (gemId == lastGemMetaId) return  // schon geladen
        lastGemMetaId = gemId
        viewModelScope.launch {
            runCatching { repo.getGem(gemId) }
                .onSuccess { g ->
                    _state.update {
                        it.copy(
                            gemEmoji = g.emoji,
                            gemName = g.name,
                            gemDescription = g.description,
                            gemStarters = g.conversationStarters,
                        )
                    }
                }
                .onFailure {
                    // z.B. Gem wurde gelöscht → keine Geister-Meta zeigen (kein Retry-Spam).
                    _state.update {
                        it.copy(gemEmoji = "", gemName = "", gemDescription = "", gemStarters = emptyList())
                    }
                }
        }
    }

    /** Setzt den Titel der aktuellen Konversation. */
    fun renameChat(newTitle: String) = viewModelScope.launch {
        val trimmed = newTitle.trim()
        if (trimmed.isBlank()) return@launch
        runCatching { repo.rename(cid, trimmed) }
            .onSuccess { _state.update { it.copy(title = trimmed) } }
            .onFailure { e ->
                _state.update { it.copy(errorMessage = appContext.getString(R.string.error_rename, e.message ?: "")) }
            }
    }

    /** Pin/Unpin der aktuellen Konversation. */
    fun togglePin() = viewModelScope.launch {
        val now = _state.value.pinned
        runCatching { repo.setPinned(cid, !now) }
            .onSuccess { _state.update { it.copy(pinned = !now) } }
            .onFailure { e ->
                _state.update { it.copy(errorMessage = appContext.getString(R.string.error_pin, e.message ?: "")) }
            }
    }

    /** Prüft den Chat-Sperr-PIN gegen den Server (für die Sperr-Ansicht). */
    suspend fun verifyChatLockPin(pin: String) = repo.verifyChatLockPin(pin)

    /** Löscht die aktuelle Konversation. Callback wird nach erfolgreichem Löschen
     *  ausgelöst — typisch: zur Übersicht navigieren oder neuen Chat starten. */
    fun deleteChat(onDeleted: () -> Unit) = viewModelScope.launch {
        runCatching { repo.delete(cid) }
            .onSuccess {
                // Wenn dieser Chat als last_chat_cid gemerkt war, raus damit.
                runCatching { settingsRepo.setLastChatCid(null) }
                onDeleted()
            }
            .onFailure { e ->
                _state.update { it.copy(errorMessage = appContext.getString(R.string.error_delete, e.message ?: "")) }
            }
    }

    fun addPending(uri: Uri, filename: String) {
        _state.update { st ->
            st.copy(pending = st.pending + PendingAttachment(uri, filename, uploading = true))
        }
        viewModelScope.launch {
            runCatching { repo.uploadFromUri(uri) }
                .onSuccess { dto ->
                    _state.update { st ->
                        st.copy(pending = st.pending.map { p ->
                            if (p.uri == uri) p.copy(uploading = false, uploaded = dto) else p
                        })
                    }
                }
                .onFailure { e ->
                    _state.update { st ->
                        st.copy(pending = st.pending.map { p ->
                            if (p.uri == uri) p.copy(uploading = false, error = e.message ?: appContext.getString(R.string.error_upload)) else p
                        })
                    }
                }
        }
    }

    fun removePending(uri: Uri) {
        _state.update { st -> st.copy(pending = st.pending.filter { it.uri != uri }) }
    }

    fun send(content: String) {
        val text = content.trim()
        val pending = _state.value.pending
        if (text.isEmpty() && pending.none { it.uploaded != null }) return
        if (_state.value.isStreaming) return

        val attachmentIds = pending.mapNotNull { it.uploaded?.id }
        val attachmentRefs = pending.mapNotNull { p ->
            p.uploaded?.let {
                AttachmentRefDto(it.id, it.filename, it.mimeType, it.sizeBytes)
            }
        }

        // Optimistic user message
        val optimistic = MessageDto(
            id = -System.currentTimeMillis(),
            conversationId = cid,
            role = "user",
            content = text,
            createdAt = OffsetDateTime.now().toString(),
            tokens = 0,
            attachments = attachmentRefs,
        )
        _state.update {
            it.copy(
                messages = it.messages + optimistic,
                pending = emptyList(),
                streamingText = "",
                streamingAttachments = emptyList(),
                isStreaming = true,
            )
        }

        // Foreground-Service starten — hält den Prozess am Leben, falls der
        // User die App in den Hintergrund schiebt, während Claude streamt.
        runCatching {
            StreamingService.start(appContext, _state.value.title.ifBlank { null }, cid)
        }

        streamJob = viewModelScope.launch {
            val s = settingsRepo.current()
            // Das Modell DIESES Chats gewinnt vor der globalen Wahl. Ein
            // Bestandschat bringt sein Modell vom Server mit (`chat_model`),
            // die globale Wahl kommt dagegen aus dem zuletzt geoeffneten Chat.
            // Wurde hier nur der globale Wert benutzt, zeigte das Sheet das eine
            // Modell an und gesendet wurde ein anderes.
            val modelKey = _state.value.modelKey.ifBlank { s.chatModelKey }
            // Die Denktiefe haengt am gewaehlten Modell: gemerkt wird sie pro
            // Familie, koennen tut sie das einzelne Modell. Ist das Modell
            // bekannt, wird auf dessen Stufen geklemmt, sonst bleibt es bei der
            // Familien-Vorgabe. So geht genau die Stufe raus, die das Sheet auch
            // anzeigt.
            val selected = _state.value.models.firstOrNull { it.key == modelKey }
            val effort = s.effortForModelKey(modelKey, selected)
            repo.stream(
                cid,
                text,
                attachmentIds,
                effort = effort,
                model = modelKey,
                systemPrompt = s.resolvedSystemPrompt,
                // Server startet nach Done eine Pre-Generation für die
                // gewählte Voice/Speed. Nächster Vorlesen-Tap = Cache-Hit.
                ttsVoice = s.ttsVoice,
                ttsRate = s.ttsSpeed,
            ).collect { ev -> handleEvent(ev) }
        }
    }

    fun stop() {
        streamJob?.cancel()
        streamJob = null
        runCatching { StreamingService.stop(appContext) }
        finalizeStreaming()
    }

    private fun handleEvent(ev: StreamEvent) {
        when (ev) {
            is StreamEvent.TitleUpdated -> {
                _state.update { it.copy(title = ev.newTitle.ifBlank { it.title }) }
            }

            is StreamEvent.UserSaved -> {
                // Update optimistic user message ID to the real one
                _state.update { st ->
                    val msgs = st.messages.toMutableList()
                    val idx = msgs.indexOfLast { it.role == "user" && it.id < 0 }
                    if (idx >= 0) {
                        msgs[idx] = msgs[idx].copy(id = ev.userMessageId)
                    }
                    st.copy(messages = msgs)
                }
            }

            StreamEvent.CompactionStarted -> _state.update { it.copy(isCompacting = true) }
            StreamEvent.CompactionDone -> _state.update {
                it.copy(isCompacting = false, hasMidSummary = true)
            }

            is StreamEvent.Delta -> _state.update {
                it.copy(streamingText = it.streamingText + ev.text)
            }

            is StreamEvent.ThinkingDelta -> _state.update {
                it.copy(streamingThinking = it.streamingThinking + ev.text)
            }

            is StreamEvent.ImagesReady -> _state.update { st ->
                // Duplikate vermeiden, falls der Server dasselbe Bild zweimal
                // meldet (Tool-Retry).
                val known = st.streamingAttachments.map { it.id }.toSet()
                st.copy(
                    streamingAttachments = st.streamingAttachments +
                        ev.attachments.filterNot { it.id in known },
                )
            }

            StreamEvent.BlockStop -> {
                // Block-Stop kommt nach jedem content_block (Thinking oder Text).
                // Wir machen nichts speziell — die State-Updates geben das UI
                // genug Information.
            }

            is StreamEvent.Done -> {
                val finalText = _state.value.streamingText
                val totalThisTurn = ev.tokensIn + ev.tokensOut + ev.tokensCachedRead + ev.tokensCachedWrite
                _state.update { st ->
                    val newMsg = MessageDto(
                        id = ev.assistantMessageId,
                        conversationId = cid,
                        role = "assistant",
                        content = finalText,
                        createdAt = OffsetDateTime.now().toString(),
                        tokens = totalThisTurn,
                        attachments = st.streamingAttachments,
                    )
                    st.copy(
                        messages = st.messages + newMsg,
                        streamingText = "",
                        streamingThinking = "",
                        streamingAttachments = emptyList(),
                        isStreaming = false,
                        totalTokens = totalThisTurn,
                        lastTurnCachedRead = ev.tokensCachedRead,
                        lastTurnCachedWrite = ev.tokensCachedWrite,
                    )
                }
                // Foreground-Service stoppen
                runCatching { StreamingService.stop(appContext) }
                // App im Hintergrund? → Notification posten
                postResultNotificationIfBackground(finalText)
                // Auto-Speak: per-Chat-Override (falls gesetzt) hat Vorrang,
                // sonst globaler ttsAutoSpeak. Im Auto-Modus IMMER vorlesen —
                // ohne TTS-Schritt wäre der Loop nutzlos.
                viewModelScope.launch {
                    val s = settingsRepo.current()
                    val override = _state.value.autoSpeakOverride
                    val shouldSpeak = _state.value.autoMode || (override ?: s.ttsAutoSpeak)
                    if (shouldSpeak) {
                        speak(ev.assistantMessageId)
                    }
                }
            }

            is StreamEvent.ErrorEvent -> {
                _state.update {
                    it.copy(
                        isStreaming = false,
                        streamingText = "",
                        streamingThinking = "",
                        streamingAttachments = emptyList(),
                        errorMessage = ev.message,
                    )
                }
                runCatching { StreamingService.stop(appContext) }
            }
        }
    }

    /** Postet die "Antwort fertig"-Notification, falls die App gerade im Hintergrund ist. */
    private fun postResultNotificationIfBackground(replyText: String) {
        val app = appContext.applicationContext as? PocketClaudeApp ?: return
        if (app.isInForeground) return
        runCatching {
            NotificationHelper.showResultNotification(
                context = appContext,
                conversationTitle = _state.value.title.ifBlank { appContext.getString(R.string.app_name) },
                conversationId = cid,
                snippet = replyText,
            )
        }
    }

    private fun finalizeStreaming() {
        val partial = _state.value.streamingText
        if (partial.isNotEmpty()) {
            _state.update { st ->
                val newMsg = MessageDto(
                    id = -System.currentTimeMillis(),
                    conversationId = cid,
                    role = "assistant",
                    content = partial + "\n\n_" + appContext.getString(R.string.generated_chat_aborted) + "_",
                    createdAt = OffsetDateTime.now().toString(),
                )
                st.copy(
                    messages = st.messages + newMsg,
                    streamingText = "",
                    isStreaming = false,
                )
            }
        } else {
            _state.update { it.copy(isStreaming = false, streamingText = "") }
        }
    }

    fun dismissError() {
        _state.update { it.copy(errorMessage = null) }
    }

    // ===================== In-Chat-Suche =====================

    fun openSearch() = _state.update { it.copy(searchActive = true) }

    fun closeSearch() = _state.update {
        it.copy(
            searchActive = false,
            searchQuery = "",
            searchMatches = emptyList(),
            searchIndex = -1,
        )
    }

    /** Aktualisiert den Suchbegriff und berechnet die Treffer neu.
     *  Sucht case-insensitive in `content` aller Messages. Erster Treffer wird
     *  zu searchIndex=0 — der ChatScreen springt dann via LaunchedEffect dahin. */
    fun setSearchQuery(query: String) = _state.update { st ->
        val q = query.trim()
        if (q.isEmpty()) {
            st.copy(searchQuery = query, searchMatches = emptyList(), searchIndex = -1)
        } else {
            val matches = st.messages
                .asSequence()
                .filter { it.content.contains(q, ignoreCase = true) }
                .map { it.id }
                .toList()
            st.copy(
                searchQuery = query,
                searchMatches = matches,
                searchIndex = if (matches.isEmpty()) -1 else 0,
            )
        }
    }

    fun nextMatch() = _state.update { st ->
        if (st.searchMatches.isEmpty()) st
        else st.copy(searchIndex = (st.searchIndex + 1) % st.searchMatches.size)
    }

    fun previousMatch() = _state.update { st ->
        if (st.searchMatches.isEmpty()) st
        else st.copy(
            searchIndex = (st.searchIndex - 1 + st.searchMatches.size) % st.searchMatches.size
        )
    }

    fun speak(messageId: Long) = viewModelScope.launch {
        val s = settingsRepo.current()
        try {
            // Gemini-Web kann die Sprechgeschwindigkeit nicht selbst aendern,
            // die stellt hier der Player ein. Bei allen anderen Anbietern macht
            // das der Server beim Erzeugen — dort waere ein zweites Mal Tempo
            // genau ein Mal zu viel.
            val webTts = repo.ttsProviderCached() == "gemini_web"
            val serverRate = if (webTts) 1.0f else s.ttsSpeed
            val playerRate = if (webTts) s.ttsSpeed else 1.0f
            val url = repo.audioUrl(messageId, s.ttsVoice, serverRate)
            val cacheKey = "audio-$messageId-${s.ttsVoice}-$serverRate"
            audio.play(messageId, url, cacheKey, speed = playerRate)
        } catch (e: Exception) {
            _state.update { it.copy(errorMessage = appContext.getString(R.string.error_speak, e.message ?: "")) }
        }
    }

    fun stopSpeaking() {
        audio.stop()
    }

    fun pauseSpeaking() {
        audio.pause()
    }

    fun resumeSpeaking() {
        audio.resume()
    }

    fun clearAudioError() {
        audio.clearError()
    }

    /** Lädt den Markdown-Export der Konversation. Callback bekommt Markdown-Text. */
    fun exportMarkdown(onReady: (String, String) -> Unit) = viewModelScope.launch {
        runCatching { repo.exportMarkdown(cid) }
            .onSuccess { md ->
                val title = _state.value.title.ifBlank { appContext.getString(R.string.generated_chat_default_title) }
                onReady(title, md)
            }
            .onFailure { e ->
                _state.update { it.copy(errorMessage = appContext.getString(R.string.error_export, e.message ?: "")) }
            }
    }

    override fun onCleared() {
        super.onCleared()
        // Voice-Cleanup ZUERST: bei Chat-Wechsel hängt sonst die laufende
        // Aufnahme + der Auto-Mode-Loop. Singleton-Recorder bleibt damit
        // belegt → das nächste Mic-Tap im neuen Chat-VM scheitert mit
        // "Recording already in progress".
        autoModeJob?.cancel()
        autoModeJob = null
        runCatching { voiceRecorder.cancel() }

        streamJob?.cancel()
        audio.stop()
        if (_state.value.isStreaming) {
            runCatching { StreamingService.stop(appContext) }
        }
    }

    // ===================== Image Generation (Gemini) =====================
    // Image-Gen ist 2026-05-19 in einen eigenen Screen migriert worden
    // (ui/images/ImageGenViewModel + ImagesScreen). Die Methoden hier sind
    // tot, lassen wir aber als private fun bestehen wäre verwirrend — also
    // raus. Falls noch ein Aufrufer existiert: Compile-Fehler ist gewollt.

    // ===================== Voice-Input (Groq Whisper) =====================

    /** Mic-Tap: Toggle Recording. Falls bereits transkribiert wird oder ein
     *  Stream läuft, ignorieren (UI sollte den Button dann sowieso disabled
     *  zeigen — aber doppelt hält besser). */
    fun toggleRecording() {
        val st = _state.value
        when (st.voiceState) {
            VoiceState.Idle -> startRecordingInternal()
            VoiceState.Recording -> stopRecordingAndTranscribe()
            VoiceState.Transcribing -> Unit
        }
    }

    /** Long-Press auf Mic während Recording: Abbrechen ohne zu transkribieren. */
    fun cancelRecording() {
        if (_state.value.voiceState != VoiceState.Recording) return
        runCatching { voiceRecorder.cancel() }
        _state.update { it.copy(voiceState = VoiceState.Idle) }
        // Wenn der Cancel im Auto-Modus passiert, Auto-Modus mit-aushebeln —
        // der User wollte explizit nicht senden.
        if (_state.value.autoMode) setAutoMode(false)
    }

    fun clearVoiceError() = _state.update { it.copy(voiceError = null) }

    private fun startRecordingInternal() {
        if (!voiceRecorder.hasPermission()) {
            _state.update {
                it.copy(voiceError = appContext.getString(R.string.voice_error_no_permission))
            }
            return
        }
        // Sicherheitsnetz: wenn das LLM grade beschäftigt ist, NICHT aufnehmen.
        // Manual-Path würde das sonst übergehen (Auto-Mode hat eigenen Guard).
        val s = _state.value
        val a = audio.state.value
        if (s.isStreaming || a.loadingMessageId != null || a.playingMessageId != null) {
            _state.update {
                it.copy(voiceError = appContext.getString(R.string.voice_error_llm_busy))
            }
            return
        }
        try {
            voiceRecorder.start()
            _state.update { it.copy(voiceState = VoiceState.Recording, voiceError = null) }
        } catch (t: Throwable) {
            _state.update {
                it.copy(
                    voiceState = VoiceState.Idle,
                    voiceError = appContext.getString(
                        R.string.voice_error_start_failed, t.message ?: ""
                    ),
                )
            }
        }
    }

    private fun stopRecordingAndTranscribe() {
        // voiceState sofort auf Transcribing — der teure VoiceRecorder.stop()
        // (thread.join + MediaCodec-EOS-Drain + muxer.stop/release) darf NICHT
        // auf dem Main-Thread laufen (ANR-Risiko), daher off-thread in der Coroutine.
        _state.update { it.copy(voiceState = VoiceState.Transcribing) }
        viewModelScope.launch {
            val file = withContext(Dispatchers.IO) { voiceRecorder.stop() }
            if (file == null) {
                _state.update { it.copy(voiceState = VoiceState.Idle) }
                return@launch
            }
            try {
                val bytes = withContext(Dispatchers.IO) { file.readBytes() }
                runCatching { withContext(Dispatchers.IO) { file.delete() } }

                // UI-Locale aus den Prefs ziehen (leer = System-Locale → ISO).
                val locale = LocalePrefs.get(appContext).ifBlank {
                    java.util.Locale.getDefault().toLanguageTag()
                }

                val resp = apiClient.transcribeVoice(
                    bytes = bytes,
                    filename = file.name,
                    mime = "audio/mp4",
                    language = locale,
                )
                val text = resp.text.trim()
                if (text.isEmpty()) {
                    _state.update { it.copy(voiceState = VoiceState.Idle) }
                    return@launch
                }
                if (_state.value.autoMode) {
                    // KRITISCH die Reihenfolge: send() FIRST — setzt isStreaming=true
                    // atomar via _state.update. ERST DANACH voiceState → Idle. So
                    // sieht der Auto-Mode-Loop den Übergang voiceState=Idle in einem
                    // Snapshot, der bereits isStreaming=true enthält — der Loop
                    // wartet dann korrekt auf das Stream-Ende statt vorher
                    // schon das nächste Recording zu starten und damit den
                    // send() durch die `if (isStreaming) return`-Wache zu killen.
                    send(text)
                    _state.update { it.copy(voiceState = VoiceState.Idle) }
                } else {
                    _state.update { it.copy(voiceState = VoiceState.Idle) }
                    _transcriptToInsert.emit(text)
                }
            } catch (e: Exception) {
                _state.update {
                    it.copy(
                        voiceState = VoiceState.Idle,
                        voiceError = appContext.getString(
                            R.string.voice_error_transcribe_failed, e.message ?: ""
                        ),
                    )
                }
            }
        }
    }

    // ===================== Auto-Modus =====================

    fun setAutoMode(enabled: Boolean) {
        if (_state.value.autoMode == enabled) return
        _state.update { it.copy(autoMode = enabled) }
        autoModeJob?.cancel()
        autoModeJob = null
        if (enabled) {
            autoModeJob = viewModelScope.launch { runAutoModeLoop() }
        } else {
            // Beim Ausschalten: laufende Aufnahme abbrechen (NICHT transkribieren).
            if (_state.value.voiceState == VoiceState.Recording) {
                runCatching { voiceRecorder.cancel() }
                _state.update { it.copy(voiceState = VoiceState.Idle) }
            }
        }
    }

    /** Auto-Mode-Loop. Phasen:
     *   0) waitUntilSettled — kein Stream läuft, kein Audio spielt,
     *      voiceState=Idle. Garantiert dass wir NIE während LLM-Aktivität
     *      ein Recording starten (sonst nimmt das Mic die TTS-Wiedergabe
     *      auf und sendet die als nächste Frage).
     *   1) startRecordingInternal — Mic an.
     *   2) Warten bis User mic tappt oder Auto-Modus aus geht.
     *   3) Warten bis Transcribe fertig — voiceState=Idle.
     *   4) Kurzer Buffer-Delay, damit der durch transcribe ausgelöste send()
     *      seine State-Updates (isStreaming=true, neue Message) atomar
     *      landen lassen kann, BEVOR wir auf Stream-Ende warten.
     *   5) Warten bis Stream zu Ende ist (isStreaming=false).
     *   6) Warten bis TTS-Wiedergabe komplett durch ist.
     *   → zurück zu Phase 0.
     *
     *  Polling statt Flow.first() weil StateFlow-Snapshots beim Phase-Wechsel
     *  race-empfindlich sind und der Polling-Overhead (200ms) zu vernachlässigen
     *  ist — Phase-Wechsel sind ohnehin sub-sekündlich. */
    private suspend fun runAutoModeLoop() {
        while (_state.value.autoMode) {
            try {
                // Phase 0 — alles ruhig kriegen
                waitUntilSettled()
                if (!_state.value.autoMode) return

                // Phase 1 — Recording starten
                startRecordingInternal()
                if (_state.value.voiceState != VoiceState.Recording) {
                    _state.update { it.copy(autoMode = false) }
                    return
                }

                // Phase 2 — User stoppt durch Mic-Tap, oder (wenn autoSend an)
                // VAD-Auto-Stop nach `silenceTargetMs` Stille.
                //
                // VAD-Schema:
                //  - MediaRecorder.getMaxAmplitude() liefert Peak seit letztem
                //    Aufruf (0..32767, -1 bei Fehler). Wir pollen alle 80 ms.
                //  - Initial-Block 5 s: in dieser Zeit greift VAD GAR NICHT
                //    — User-Nachdenken am Anfang ist explizit erlaubt.
                //  - Danach: amp < threshold → silence-counter += 80 ms,
                //    sonst → reset. Threshold 1500 ist empirisch geraten;
                //    bei VOICE_RECOGNITION-Source mit AAC variieren die
                //    maxAmplitude-Werte aber stark device-abhängig. Deshalb
                //    PC_VAD-Logging: User schickt `adb logcat -s PC_VAD`
                //    nach einem Probelauf, dann tunen wir nach Evidence.
                //  - silenceProgressMs in den State für UI-Countdown.
                val pollMs = 80L
                val silenceThreshold = 1500
                val initialBlockMs = 5_000L  // 5 s Bedenkzeit
                var silentSinceMs = 0L
                var vadLogTick = 0
                var maxSeenAmp = 0
                while (_state.value.autoMode &&
                       _state.value.voiceState == VoiceState.Recording) {
                    // Settings JEDEN Tick live lesen, nicht beim Loop-Start einfrieren:
                    // sonst greift ein Auto-Send-Toggle, das WÄHREND der Aufnahme
                    // umgelegt wird, erst beim nächsten Recording. settingsRepo.current()
                    // ist ein In-Memory-Snapshot (kein Disk-I/O), 80-ms-Poll unkritisch.
                    val curSettings = settingsRepo.current()
                    val autoSend = curSettings.autoSendEnabled
                    val silenceTargetMs = curSettings.autoSendSilenceMs
                    if (autoSend && voiceRecorder.elapsedMs >= initialBlockMs) {
                        val amp = voiceRecorder.currentAmplitude()
                        if (amp > maxSeenAmp) maxSeenAmp = amp
                        // alle ~500 ms loggen (6 × 80 ms), damit der logcat
                        // nicht überflutet wird.
                        if (++vadLogTick % 6 == 0) {
                            android.util.Log.d(
                                "PC_VAD",
                                "amp=$amp max=$maxSeenAmp threshold=$silenceThreshold " +
                                "silentMs=$silentSinceMs elapsedMs=${voiceRecorder.elapsedMs}"
                            )
                        }
                        // amp < 0 = Fehler von MediaRecorder (z.B. Source noch
                        // nicht aktiv) — als Stille werten wäre falsch, also
                        // counter unverändert lassen.
                        if (amp in 0 until silenceThreshold) {
                            silentSinceMs += pollMs
                            if (_state.value.silenceProgressMs != silentSinceMs) {
                                _state.update { it.copy(silenceProgressMs = silentSinceMs) }
                            }
                            if (silentSinceMs >= silenceTargetMs) {
                                android.util.Log.d("PC_VAD",
                                    "silence target reached → auto-send (maxAmp=$maxSeenAmp)")
                                _state.update { it.copy(silenceProgressMs = 0L) }
                                stopRecordingAndTranscribe()
                                break
                            }
                        } else if (amp >= silenceThreshold) {
                            // Sprache erkannt → counter reset
                            if (silentSinceMs != 0L || _state.value.silenceProgressMs != 0L) {
                                silentSinceMs = 0L
                                _state.update { it.copy(silenceProgressMs = 0L) }
                            }
                        }
                    } else if (_state.value.silenceProgressMs != 0L) {
                        _state.update { it.copy(silenceProgressMs = 0L) }
                    }
                    delay(pollMs)
                }
                // Counter immer zurücksetzen, falls die Loop anders verlassen
                // wurde (User-Tap, autoMode aus).
                if (_state.value.silenceProgressMs != 0L) {
                    _state.update { it.copy(silenceProgressMs = 0L) }
                }
                if (!_state.value.autoMode) return

                // Phase 3 — Transcribe-Ende abwarten
                while (_state.value.autoMode &&
                       _state.value.voiceState == VoiceState.Transcribing) {
                    delay(150)
                }
                if (!_state.value.autoMode) return

                // Phase 4 — send() (im Transcribe-Callback) hat schon
                // isStreaming=true gesetzt BEVOR voiceState=Idle wurde
                // (siehe Reihenfolge in stopRecordingAndTranscribe). Kurzer
                // Buffer-Delay schadet trotzdem nicht — gibt den Co-Routinen
                // Zeit ihre Emissions zu propagieren.
                delay(250)

                // Phase 5 — Stream-Ende abwarten
                while (_state.value.autoMode && _state.value.isStreaming) {
                    delay(200)
                }
                if (!_state.value.autoMode) return

                // Phase 6 — TTS-Wiedergabe abwarten. Done-Handler triggert
                // auto-speak() asynchron — kurz warten dass der State sich
                // aufgebaut hat, dann auf Idle pollen.
                delay(400)
                while (_state.value.autoMode &&
                       (audio.state.value.loadingMessageId != null ||
                        audio.state.value.playingMessageId != null)) {
                    delay(300)
                }
            } catch (e: kotlinx.coroutines.CancellationException) {
                throw e  // niemals swallowen — sonst setAutoMode(false)
                         // killt den Loop nicht mehr
            } catch (e: Exception) {
                _state.update {
                    it.copy(
                        autoMode = false,
                        voiceError = appContext.getString(
                            R.string.voice_error_auto_loop, e.message ?: ""
                        ),
                    )
                }
                return
            }
        }
    }

    /** Wartet bis alle drei Bedingungen erfüllt sind: voiceState=Idle,
     *  isStreaming=false, kein Audio in Loading/Playing. */
    private suspend fun waitUntilSettled() {
        while (_state.value.autoMode) {
            val s = _state.value
            val a = audio.state.value
            val settled =
                s.voiceState == VoiceState.Idle &&
                !s.isStreaming &&
                a.loadingMessageId == null &&
                a.playingMessageId == null
            if (settled) return
            delay(200)
        }
    }

    companion object {
        fun factory(container: AppContainer, cid: String): ViewModelProvider.Factory =
            object : ViewModelProvider.Factory {
                @Suppress("UNCHECKED_CAST")
                override fun <T : ViewModel> create(modelClass: Class<T>): T {
                    return ChatViewModel(
                        repo = container.chatRepository,
                        cid = cid,
                        audio = container.audioController,
                        settingsRepo = container.settingsRepository,
                        appContext = container.appContext,
                        apiClient = container.apiClient,
                        voiceRecorder = container.voiceRecorder,
                    ) as T
                }
            }
    }
}
