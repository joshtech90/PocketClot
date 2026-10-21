package de.smartzone.pocketclaude.ui.gems

import android.net.Uri
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import de.smartzone.pocketclaude.data.AppContainer
import de.smartzone.pocketclaude.data.ChatModelFamilies
import de.smartzone.pocketclaude.data.ChatModelOption
import de.smartzone.pocketclaude.data.ClaudeModels
import de.smartzone.pocketclaude.data.EFFORT_LEVELS
import de.smartzone.pocketclaude.data.clampEffort
import de.smartzone.pocketclaude.data.familyForKey
import de.smartzone.pocketclaude.data.ChatRepository
import de.smartzone.pocketclaude.data.GemDto
import de.smartzone.pocketclaude.data.GemFileDto
import de.smartzone.pocketclaude.data.GemUpsertRequest
import de.smartzone.pocketclaude.data.SkillsDto
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** Eine noch nicht hochgeladene Wissensdatei (URI gepickt, Upload erst beim Speichern). */
data class PendingGemFile(
    val uri: Uri,
    val filename: String,
)

/** Editor-Zustand für ein einzelnes Gem (Create wenn `gemId == null`). */
data class GemEditorState(
    val gemId: String? = null,
    val isBuiltin: Boolean = false,
    val loading: Boolean = false,
    val saving: Boolean = false,
    val name: String = "",
    val emoji: String = "",
    val description: String = "",
    val instructions: String = "",
    val starters: List<String> = emptyList(),
    /** null = globaler Standard. Sonst ein Modell-Key wie im Chat
     *  (`opus` oder `gw:<gateway>:<modell>`). */
    val model: String? = null,
    /** null = Chat-Standard. Sonst Effort-Level. */
    val effort: String? = null,
    val skills: SkillsDto = SkillsDto(),
    /** Bereits serverseitig gespeicherte Dateien (nur im Edit-Modus). */
    val files: List<GemFileDto> = emptyList(),
    /** Lokal gepickte, noch nicht hochgeladene Dateien. */
    val pending: List<PendingGemFile> = emptyList(),
    val error: String? = null,
) {
    val canSave: Boolean
        get() = name.isNotBlank() && instructions.isNotBlank() && !saving && !isBuiltin
}

/** ViewModel des Gem-Editors (Create/Edit/Duplizieren eines einzelnen Gems).
 *  Die Gem-LISTE in den Settings lebt im SettingsViewModel. */
class GemsViewModel(
    private val chatRepo: ChatRepository,
) : ViewModel() {

    private val _editor = MutableStateFlow(GemEditorState())
    val editor: StateFlow<GemEditorState> = _editor.asStateFlow()

    /** Alle Modelle wie im Modell-Sheet des Chats: Claude plus Gemini und GPT,
     *  soweit ein Gateway antwortet. Ohne Server bleiben die Claude-Familien. */
    private val _models = MutableStateFlow(
        ClaudeModels.all.map { ChatModelOption(it.id, ChatModelFamilies.CLAUDE, it.label, EFFORT_LEVELS) },
    )
    val models: StateFlow<List<ChatModelOption>> = _models.asStateFlow()

    init {
        viewModelScope.launch {
            runCatching { chatRepo.getChatModels(false, include = "") }
                .onSuccess { dto ->
                    if (dto.models.isNotEmpty()) {
                        _models.value = dto.models.map { m ->
                            ChatModelOption(
                                key = m.key, family = m.family, label = m.label,
                                efforts = m.efforts, defaultEffort = m.defaultEffort,
                                supportsVision = m.supportsVision, gatewayLabel = m.gatewayLabel,
                            )
                        }
                    }
                }
        }
    }

    /** Denktiefen, die das Modell kann; ohne Modell die von Claude. */
    fun effortsFor(modelKey: String?): List<String> {
        if (modelKey.isNullOrBlank()) return EFFORT_LEVELS
        val option = _models.value.firstOrNull { it.key == modelKey }
        val family = option?.family ?: familyForKey(modelKey)
        return when {
            family == ChatModelFamilies.CLAUDE -> EFFORT_LEVELS
            option != null -> option.efforts
            else -> EFFORT_LEVELS.filter { it != "off" }
        }
    }

    /** Lädt ein Gem zum Bearbeiten, oder setzt den Editor für ein neues Gem zurück. */
    fun loadForEdit(gemId: String?) = viewModelScope.launch {
        if (gemId.isNullOrBlank()) {
            _editor.value = GemEditorState()
            return@launch
        }
        _editor.value = GemEditorState(gemId = gemId, loading = true)
        runCatching { chatRepo.getGem(gemId) }
            .onSuccess { g -> _editor.value = g.toEditorState() }
            .onFailure { e -> _editor.update { it.copy(loading = false, error = e.message ?: "Fehler") } }
    }

    /** Lädt die Konfiguration eines (auch eingebauten) Gems als Vorlage für ein
     *  NEUES eigenes Gem — Instructions/Starter/Modell/Effort/Skills werden
     *  übernommen, Wissensdateien NICHT (die gehören dem Original). */
    fun loadForDuplicate(sourceGemId: String) = viewModelScope.launch {
        _editor.value = GemEditorState(loading = true)
        runCatching { chatRepo.getGem(sourceGemId) }
            .onSuccess { g ->
                _editor.value = g.toEditorState().copy(
                    gemId = null,          // → Save legt ein NEUES Gem an
                    isBuiltin = false,
                    name = "${g.name} (Kopie)",
                    files = emptyList(),   // Wissensdateien nicht mitkopieren
                    loading = false,
                )
            }
            .onFailure { e -> _editor.update { it.copy(loading = false, error = e.message ?: "Fehler") } }
    }

    private fun GemDto.toEditorState() = GemEditorState(
        gemId = id,
        isBuiltin = isBuiltin,
        name = name,
        emoji = emoji,
        description = description,
        instructions = instructions,
        starters = conversationStarters,
        model = model,
        effort = effort,
        skills = skills ?: SkillsDto(),
        files = files,
    )

    fun setName(v: String) = _editor.update { it.copy(name = v) }
    fun setEmoji(v: String) = _editor.update { it.copy(emoji = capEmoji(v)) }
    fun setDescription(v: String) = _editor.update { it.copy(description = v) }
    fun setInstructions(v: String) = _editor.update { it.copy(instructions = v) }
    fun setModel(id: String?) = _editor.update {
        val model = id?.takeIf { s -> s.isNotBlank() }
        // Eine Denktiefe, die das neue Modell nicht kann, auf die naechste ziehen.
        val efforts = effortsFor(model)
        val effort = it.effort?.let { e -> if (efforts.isEmpty()) null else clampEffort(e, efforts) }
        it.copy(model = model, effort = effort)
    }
    fun setEffort(level: String?) = _editor.update { it.copy(effort = level?.takeIf { s -> s.isNotBlank() }) }
    fun setWebSearch(on: Boolean) = _editor.update { it.copy(skills = it.skills.copy(webSearch = on)) }
    fun setWebFetch(on: Boolean) = _editor.update { it.copy(skills = it.skills.copy(webFetch = on)) }
    fun setCodeExecution(on: Boolean) = _editor.update { it.copy(skills = it.skills.copy(codeExecution = on)) }

    fun addStarter() = _editor.update { it.copy(starters = it.starters + "") }
    fun updateStarter(index: Int, value: String) = _editor.update { st ->
        st.copy(starters = st.starters.toMutableList().also { if (index in it.indices) it[index] = value })
    }
    fun removeStarter(index: Int) = _editor.update { st ->
        st.copy(starters = st.starters.toMutableList().also { if (index in it.indices) it.removeAt(index) })
    }

    fun addPendingFile(uri: Uri, filename: String) = _editor.update {
        it.copy(pending = it.pending + PendingGemFile(uri, filename))
    }
    fun removePendingFile(uri: Uri) = _editor.update {
        it.copy(pending = it.pending.filter { p -> p.uri != uri })
    }

    /** Entfernt eine bereits gespeicherte Datei. Im Edit-Modus serverseitig;
     *  Fehler werden angezeigt statt verschluckt. */
    fun removeSavedFile(fileId: String) = viewModelScope.launch {
        val gid = _editor.value.gemId
        if (gid == null) {
            _editor.update { it.copy(files = it.files.filter { f -> f.id != fileId }) }
            return@launch
        }
        runCatching { chatRepo.deleteGemFile(gid, fileId) }
            .onSuccess { _editor.update { it.copy(files = it.files.filter { f -> f.id != fileId }) } }
            .onFailure { e -> _editor.update { it.copy(error = e.message ?: "Datei konnte nicht entfernt werden") } }
    }

    /** Speichert (Create oder Update), lädt anschließend gependete Dateien hoch.
     *  Idempotent bei Retry: nach erfolgreichem Create wird die neue ID sofort
     *  in den State übernommen, sodass ein zweiter Save-Tap UPDATE macht (kein
     *  Duplikat). Nur erfolgreich hochgeladene Dateien verlassen `pending`. */
    fun save(onSaved: () -> Unit) = viewModelScope.launch {
        val st = _editor.value
        if (!st.canSave) return@launch
        _editor.update { it.copy(saving = true, error = null) }
        val req = GemUpsertRequest(
            name = st.name.trim(),
            emoji = st.emoji.trim(),
            description = st.description.trim(),
            instructions = st.instructions.trim(),
            conversationStarters = st.starters.map { it.trim() }.filter { it.isNotBlank() },
            model = st.model,
            effort = st.effort,
            skills = st.skills,
        )
        val saved = runCatching {
            if (st.gemId == null) chatRepo.createGem(req) else chatRepo.updateGem(st.gemId, req)
        }.getOrElse { e ->
            _editor.update { it.copy(saving = false, error = e.message ?: "Speichern fehlgeschlagen") }
            return@launch
        }
        // ID sofort übernehmen → ein erneuter Save macht UPDATE statt CREATE.
        _editor.update { it.copy(gemId = saved.id, isBuiltin = saved.isBuiltin, files = saved.files) }

        // Gependete Dateien hochladen; fehlgeschlagene bleiben in `pending`.
        var uploadError: String? = null
        val stillPending = mutableListOf<PendingGemFile>()
        for (p in st.pending) {
            runCatching { chatRepo.uploadGemFileFromUri(saved.id, p.uri) }
                .onFailure { e ->
                    uploadError = e.message ?: "Datei-Upload fehlgeschlagen"
                    stillPending.add(p)
                }
        }
        // Falls Dateien hochgeladen wurden: Gem neu laden, damit `files` aktuell ist.
        val files = if (st.pending.size != stillPending.size) {
            runCatching { chatRepo.getGem(saved.id).files }.getOrDefault(saved.files)
        } else saved.files
        _editor.update {
            it.copy(saving = false, pending = stillPending, files = files, error = uploadError)
        }
        if (uploadError == null) onSaved()
    }

    private fun capEmoji(v: String): String {
        val t = v.trim()
        // Nach Code-Points begrenzen (nie ein Surrogat-Paar zerschneiden); 8
        // Code-Points decken auch ZWJ-Emojis ab.
        return if (t.codePointCount(0, t.length) <= 8) t
        else t.substring(0, t.offsetByCodePoints(0, 8))
    }

    companion object {
        fun factory(container: AppContainer): ViewModelProvider.Factory =
            object : ViewModelProvider.Factory {
                @Suppress("UNCHECKED_CAST")
                override fun <T : ViewModel> create(modelClass: Class<T>): T {
                    return GemsViewModel(container.chatRepository) as T
                }
            }
    }
}
