package de.smartzone.pocketclaude.ui.images

import android.net.Uri
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import de.smartzone.pocketclaude.data.AppContainer
import de.smartzone.pocketclaude.data.ChatRepository
import de.smartzone.pocketclaude.data.ImageConfigDto
import de.smartzone.pocketclaude.data.ImageGenerateRequest
import de.smartzone.pocketclaude.data.ImageCompressor
import de.smartzone.pocketclaude.data.ImageGenerateAttachment
import de.smartzone.pocketclaude.data.SettingsRepository
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json

/**
 * Ein einzelner generierter Bild-Satz aus einer Prompt-Aktion. Eine Aktion
 * kann mehrere Output-Bilder erzeugen (count=1..4 in der UI).
 */
@Serializable
data class GeneratedImageEntry(
    val timestampMs: Long,
    val prompt: String,
    val model: String,
    val aspectRatio: String,
    val attachments: List<ImageGenerateAttachment>,
)

/**
 * Ein Vorlagenbild fuer den Bearbeiten-Modus. `id` ist die Attachment-ID auf
 * dem Server, `label` nur fuer die Anzeige.
 */
data class ReferenceImageUi(
    val id: String,
    val label: String,
)

data class ImageGenUiState(
    val config: ImageConfigDto? = null,
    val configLoading: Boolean = true,
    val configError: String? = null,
    val selectedModel: String? = null,
    val selectedAspect: String = "1:1",
    val selectedSize: String = "2K",
    val selectedProvider: String = "both",
    val count: Int = 1,
    val prompt: String = "",
    val isGenerating: Boolean = false,
    val generationError: String? = null,
    val history: List<GeneratedImageEntry> = emptyList(),
    /** Vorlagen fuer den Bearbeiten-Modus. Leer heisst: neues Bild erzeugen. */
    val references: List<ReferenceImageUi> = emptyList(),
    /** Wieviele Uploads gerade laufen. Bewusst ein Zaehler und kein Schalter:
     *  sonst meldet der erste fertige Upload "fertig", waehrend ein zweiter
     *  noch laeuft, und der Knopf waere zu frueh wieder frei. */
    val uploadsRunning: Int = 0,
) {
    /** Mit mindestens einer Vorlage wird bearbeitet statt neu erzeugt. */
    val isEditing: Boolean get() = references.isNotEmpty()
    val isUploading: Boolean get() = uploadsRunning > 0
    /** Waehrend einer laufenden Erzeugung duerfen die Vorlagen nicht wandern:
     *  der Auftrag ist raus, und die Oberflaeche wuerde etwas anderes zeigen
     *  als das, was gerade wirklich gerechnet wird. */
    val canEditReferences: Boolean get() = !isGenerating
}

/**
 * Standalone-ViewModel für die Bild-Generierung. Bewusst losgelöst vom
 * ChatViewModel — Bilder leben in einem eigenen Screen, hängen NICHT an einer
 * Konversation und werden serverseitig auch nicht in Chats geschrieben
 * (conversationId=null beim Generate-Request).
 *
 * History wird lokal in DataStore persistiert (über `SettingsRepository`).
 * Limit: HISTORY_MAX_ENTRIES Einträge — älteste fliegen raus.
 */
class ImageGenViewModel(
    private val repo: ChatRepository,
    private val settingsRepo: SettingsRepository,
) : ViewModel() {

    private val _state = MutableStateFlow(ImageGenUiState())
    val state: StateFlow<ImageGenUiState> = _state.asStateFlow()

    private val json = Json { ignoreUnknownKeys = true }

    init {
        refreshConfig()
        loadHistory()
    }

    fun refreshConfig() = viewModelScope.launch {
        _state.update { it.copy(configLoading = true, configError = null) }
        runCatching { repo.imagesConfig() }
            .onSuccess { cfg ->
                _state.update {
                    it.copy(
                        configLoading = false,
                        config = cfg,
                        selectedModel = it.selectedModel ?: cfg.defaultModel,
                        selectedAspect = if (it.selectedAspect == "1:1") cfg.defaults.aspectRatio else it.selectedAspect,
                        selectedSize = if (it.selectedSize == "2K") cfg.defaults.size else it.selectedSize,
                        selectedProvider = if (it.selectedProvider == "both") cfg.defaults.provider else it.selectedProvider,
                    )
                }
            }
            .onFailure { e ->
                _state.update {
                    it.copy(configLoading = false, configError = e.message ?: "Image-Config nicht ladbar")
                }
            }
    }

    fun setPrompt(value: String) = _state.update { it.copy(prompt = value) }
    fun setModel(id: String) = _state.update { it.copy(selectedModel = id) }
    fun setAspect(id: String) = _state.update { it.copy(selectedAspect = id) }
    fun setSize(id: String) = _state.update { it.copy(selectedSize = id) }
    fun setProvider(id: String) = _state.update { it.copy(selectedProvider = id) }
    fun setCount(n: Int) = _state.update {
        it.copy(count = n.coerceIn(1, it.config?.maxCandidates ?: 4))
    }

    fun clearError() = _state.update { it.copy(generationError = null) }

    // ---------- Vorlagen fuer den Bearbeiten-Modus ----------

    /**
     * Laedt ein Bild vom Geraet hoch und nimmt es als Vorlage.
     *
     * Der Upload laeuft ueber denselben Weg wie Chat-Anhaenge, inklusive der
     * dortigen Bild-Verkleinerung: ein 12-MP-Handyfoto unveraendert an das
     * Gateway zu schicken waere Verschwendung.
     */
    fun addReferenceFromUri(uri: Uri, label: String) = viewModelScope.launch {
        val s = _state.value
        if (!s.canEditReferences) return@launch
        if (s.references.size + s.uploadsRunning >= MAX_REFERENCES) {
            _state.update { it.copy(generationError = tooManyReferences) }
            return@launch
        }
        _state.update {
            it.copy(uploadsRunning = it.uploadsRunning + 1, generationError = null)
        }
        // Vorlagen bekommen mehr Auflösung als ein reiner Ansehen-Anhang: was
        // hier wegkomprimiert wird, kann die Bearbeitung nicht zurückholen.
        runCatching { repo.uploadFromUri(uri, ImageCompressor.Purpose.EDIT) }
            .onSuccess { att ->
                _state.update {
                    val done = it.copy(uploadsRunning = (it.uploadsRunning - 1).coerceAtLeast(0))
                    // Erneut pruefen: zwischen Start und Ende des Uploads kann
                    // ein zweiter fertig geworden sein, oder der Nutzer hat
                    // inzwischen alles geleert.
                    if (done.references.size >= MAX_REFERENCES ||
                        done.references.any { r -> r.id == att.id }
                    ) done
                    else done.copy(references = done.references + ReferenceImageUi(att.id, label))
                }
            }
            .onFailure { e ->
                _state.update {
                    it.copy(uploadsRunning = (it.uploadsRunning - 1).coerceAtLeast(0),
                            generationError = e.message ?: uploadFailed)
                }
            }
    }

    /** Nimmt ein bereits erzeugtes Bild als Vorlage, ohne es neu hochzuladen. */
    fun addReferenceFromAttachment(att: ImageGenerateAttachment) = _state.update {
        if (!it.canEditReferences) it
        // Laufende Uploads mitzaehlen, sonst nimmt eine Verlaufs-Vorlage
        // deren Platz weg und der fertige Upload wird stillschweigend verworfen.
        else if (it.references.any { r -> r.id == att.id } ||
                 it.references.size + it.uploadsRunning >= MAX_REFERENCES) it
        else it.copy(references = it.references + ReferenceImageUi(att.id, att.filename))
    }

    fun removeReference(id: String) = _state.update {
        if (!it.canEditReferences) it
        else it.copy(references = it.references.filterNot { r -> r.id == id })
    }

    fun clearReferences() = _state.update {
        if (!it.canEditReferences) it else it.copy(references = emptyList())
    }

    fun generate() = viewModelScope.launch {
        val s = _state.value
        val cfg = s.config
        if (cfg == null || !cfg.configured) {
            _state.update {
                it.copy(generationError = "Auf dem Server ist gerade kein Bild-Anbieter erreichbar.")
            }
            return@launch
        }
        val prompt = s.prompt.trim()
        if (prompt.isEmpty() || s.isGenerating) return@launch

        _state.update { it.copy(isGenerating = true, generationError = null) }
        try {
            val resp = repo.generateImage(
                ImageGenerateRequest(
                    prompt = prompt,
                    // Bewusst KEINE conversationId — Bilder hängen nicht an einem Chat.
                    conversationId = null,
                    model = s.selectedModel,
                    provider = s.selectedProvider,
                    aspectRatio = s.selectedAspect,
                    imageSize = s.selectedSize,
                    count = s.count,
                    referenceAttachmentIds = s.references.map { it.id },
                )
            )
            val entry = GeneratedImageEntry(
                timestampMs = System.currentTimeMillis(),
                prompt = prompt,
                model = resp.model,
                aspectRatio = resp.aspectRatio,
                attachments = resp.attachments,
            )
            val newHistory = (listOf(entry) + s.history).take(HISTORY_MAX_ENTRIES)
            _state.update {
                it.copy(
                    isGenerating = false,
                    prompt = "",     // Prompt-Feld leeren nach erfolgreicher Generation
                    history = newHistory,
                )
            }
            saveHistory(newHistory)
        } catch (e: Exception) {
            val msg = when (e) {
                is de.smartzone.pocketclaude.data.ApiException ->
                    "HTTP ${e.code}: ${e.body.take(200)}"
                else -> e.message ?: e::class.java.simpleName
            }
            _state.update {
                it.copy(isGenerating = false, generationError = "Generierung fehlgeschlagen: $msg")
            }
        }
    }

    fun deleteEntry(entry: GeneratedImageEntry) = viewModelScope.launch {
        val newHistory = _state.value.history.filterNot { it.timestampMs == entry.timestampMs }
        _state.update { it.copy(history = newHistory) }
        saveHistory(newHistory)
    }

    fun clearHistory() = viewModelScope.launch {
        _state.update { it.copy(history = emptyList()) }
        saveHistory(emptyList())
    }

    // ----- History-Persistenz via SettingsRepository -----

    private fun loadHistory() = viewModelScope.launch {
        val raw = settingsRepo.getImageHistoryRaw()
        if (raw.isNotBlank()) {
            runCatching { json.decodeFromString<List<GeneratedImageEntry>>(raw) }
                .onSuccess { list ->
                    _state.update { it.copy(history = list.take(HISTORY_MAX_ENTRIES)) }
                }
        }
    }

    private suspend fun saveHistory(list: List<GeneratedImageEntry>) {
        settingsRepo.setImageHistoryRaw(json.encodeToString(list))
    }

    companion object {
        const val HISTORY_MAX_ENTRIES = 50

        /** Muss zu `MAX_REFERENCE_IMAGES` in image_engine.py passen. */
        const val MAX_REFERENCES = 4

        // Diese beiden Meldungen stehen wie die uebrigen Fehlertexte dieses
        // ViewModels direkt hier statt in den Ressourcen: ein ViewModel hat
        // keinen Context, und der Bestand macht es an dieser Stelle genauso.
        private const val tooManyReferences =
            "Mehr als $MAX_REFERENCES Vorlagen gehen nicht."
        private const val uploadFailed =
            "Das Bild konnte nicht hochgeladen werden."


        fun factory(container: AppContainer): ViewModelProvider.Factory =
            object : ViewModelProvider.Factory {
                @Suppress("UNCHECKED_CAST")
                override fun <T : ViewModel> create(modelClass: Class<T>): T {
                    return ImageGenViewModel(
                        repo = container.chatRepository,
                        settingsRepo = container.settingsRepository,
                    ) as T
                }
            }
    }
}
