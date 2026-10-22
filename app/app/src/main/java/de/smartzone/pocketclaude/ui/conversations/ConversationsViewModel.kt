package de.smartzone.pocketclaude.ui.conversations

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import de.smartzone.pocketclaude.data.AppContainer
import de.smartzone.pocketclaude.data.AppSettings
import de.smartzone.pocketclaude.data.ChatRepository
import de.smartzone.pocketclaude.data.ConversationDto
import de.smartzone.pocketclaude.data.SettingsRepository
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

sealed interface ConversationsState {
    data object Loading : ConversationsState
    data class NeedsSetup(val reason: String? = null) : ConversationsState
    data class Loaded(val conversations: List<ConversationDto>) : ConversationsState
    data class Error(val message: String) : ConversationsState
}

data class SearchState(
    val query: String = "",
    val isSearching: Boolean = false,
    val hits: List<de.smartzone.pocketclaude.data.SearchHitDto> = emptyList(),
    val error: String? = null,
) {
    val active: Boolean get() = query.isNotBlank()
}

class ConversationsViewModel(
    private val settingsRepo: SettingsRepository,
    private val chatRepo: ChatRepository,
) : ViewModel() {

    private val _state = MutableStateFlow<ConversationsState>(ConversationsState.Loading)
    val state: StateFlow<ConversationsState> = _state.asStateFlow()

    private val _search = MutableStateFlow(SearchState())
    val search: StateFlow<SearchState> = _search.asStateFlow()
    private var searchJob: kotlinx.coroutines.Job? = null

    val settings: StateFlow<AppSettings> = MutableStateFlow(AppSettings()).also { flow ->
        // Raw-Collector: nur den exponierten `settings`-State spiegeln. KEIN refresh()
        // hier — settingsFlow emittiert bei JEDEM DataStore-Write (Theme, TTS-Speed,
        // Effort, Image-History …), und ein voller GET /conversations pro Tastenanschlag
        // wäre verschwendet (und kann einen laufenden Scroll/Search stören).
        viewModelScope.launch {
            settingsRepo.settingsFlow.collect { flow.value = it }
        }
        // refresh() nur, wenn sich die Verbindungs-Identität ändert (aktives Profil /
        // dessen URL+Token). distinctUntilChanged filtert die unrelated Settings-Churn.
        viewModelScope.launch {
            settingsRepo.settingsFlow
                .map { Triple(it.activeProfileId, it.serverUrl, it.serverToken) }
                .distinctUntilChanged()
                .collect { refresh() }
        }
    }.asStateFlow()

    init {
        refresh()
    }

    private var refreshJob: kotlinx.coroutines.Job? = null

    /** Nur die juengste Abfrage zaehlt: nach einem Profilwechsel darf die noch
     *  laufende Liste des alten Profils die neue nicht ueberschreiben. */
    fun refresh() {
        refreshJob?.cancel()
        refreshJob = viewModelScope.launch { loadList() }
    }

    private suspend fun loadList() {
        val s = settingsRepo.current()
        if (!s.isConfigured) {
            _state.value = ConversationsState.NeedsSetup()
            return
        }
        _state.value = ConversationsState.Loading
        _state.value = runCatching { chatRepo.list() }
            .onFailure { if (it is kotlinx.coroutines.CancellationException) throw it }
            .map { ConversationsState.Loaded(it) as ConversationsState }
            .getOrElse { ConversationsState.Error(it.message ?: it::class.java.simpleName) }
    }

    fun create(onCreated: (String) -> Unit) = viewModelScope.launch {
        runCatching { chatRepo.create() }
            .onSuccess { onCreated(it.id); refresh() }
            .onFailure { _state.value = ConversationsState.Error(it.message ?: "Fehler") }
    }

    fun delete(id: String) = viewModelScope.launch {
        runCatching { chatRepo.delete(id) }
        clearLastChatIfMatches(setOf(id))
        refresh()
    }

    /** Mehrere Chats hintereinander löschen (Bulk-Delete aus dem Selection-Modus). */
    fun deleteMany(ids: Collection<String>) = viewModelScope.launch {
        ids.forEach { runCatching { chatRepo.delete(it) } }
        clearLastChatIfMatches(ids.toSet())
        refresh()
    }

    /** Wenn der gerade-zuletzt-offene Chat gelöscht wurde, lastChatCid resetten,
     *  damit der nächste App-Start nicht auf einem 404 landet. */
    private suspend fun clearLastChatIfMatches(deletedIds: Set<String>) {
        val last = settingsRepo.getLastChatCid() ?: return
        if (last in deletedIds) settingsRepo.setLastChatCid(null)
    }

    fun rename(id: String, title: String) = viewModelScope.launch {
        runCatching { chatRepo.rename(id, title) }
        refresh()
    }

    fun togglePin(id: String, currentlyPinned: Boolean) = viewModelScope.launch {
        runCatching { chatRepo.setPinned(id, !currentlyPinned) }
        refresh()
    }

    /** Sperrt einen Chat. Wenn der Server 400 meldet (noch kein globaler PIN
     *  gesetzt), wird `onNeedPin` aufgerufen, damit die UI zu den Einstellungen
     *  leiten kann. */
    fun lock(id: String, onNeedPin: () -> Unit) = viewModelScope.launch {
        val result = runCatching { chatRepo.setLocked(id, true) }
        result.onSuccess { refresh() }
        result.onFailure { e ->
            val code = (e as? de.smartzone.pocketclaude.data.ApiException)?.code
            if (code == 400) onNeedPin() else refresh()
        }
    }

    /** Entfernt die Sperre (nachdem die UI den PIN verifiziert hat). */
    fun unlock(id: String) = viewModelScope.launch {
        runCatching { chatRepo.setLocked(id, false) }
        refresh()
    }

    suspend fun verifyChatLockPin(pin: String) = chatRepo.verifyChatLockPin(pin)

    fun setSearchQuery(q: String) {
        _search.update { it.copy(query = q, error = null) }
        searchJob?.cancel()
        if (q.isBlank()) {
            _search.update { it.copy(hits = emptyList(), isSearching = false) }
            return
        }
        searchJob = viewModelScope.launch {
            kotlinx.coroutines.delay(250)  // Debounce
            _search.update { it.copy(isSearching = true) }
            runCatching { chatRepo.search(q) }
                // Abgebrochen, weil schon weitergetippt wurde: kein Fehler fuer
                // die neue Suche, einfach aufhoeren.
                .onFailure { if (it is kotlinx.coroutines.CancellationException) throw it }
                .onSuccess { resp -> _search.update { it.copy(isSearching = false, hits = resp.hits) } }
                .onFailure { e -> _search.update { it.copy(isSearching = false, error = e.message ?: "Suche fehlgeschlagen") } }
        }
    }

    fun clearSearch() {
        searchJob?.cancel()
        _search.value = SearchState()
    }

    companion object {
        fun factory(container: AppContainer): ViewModelProvider.Factory =
            object : ViewModelProvider.Factory {
                @Suppress("UNCHECKED_CAST")
                override fun <T : ViewModel> create(modelClass: Class<T>): T {
                    return ConversationsViewModel(
                        container.settingsRepository,
                        container.chatRepository,
                    ) as T
                }
            }
    }
}
