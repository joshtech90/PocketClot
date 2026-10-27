package de.smartzone.pocketclaude.data

import android.content.Context
import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import java.io.File

/**
 * Inhalt der Seitenleiste, fuer die ganze App gemeinsam (Joscha 27.10.2026).
 *
 * Vorher holte jeder Chat-Bildschirm die Liste erst, wenn die Leiste fertig
 * aufgeklappt war, und begann mit einer leeren Liste: Chats und der Gems-
 * Abschnitt bauten sich bei jedem Oeffnen sichtbar auf. Jetzt liegt die Liste
 * hier, wird im Vordergrund jede Minute und bei Anlaessen (Oeffnen der
 * Leiste, neue Antwort, Umbenennen, Loeschen) im Hintergrund abgeglichen und
 * ist beim Aufklappen schon fertig. Chats und Gems ueberleben auch einen
 * Neustart der App (je Profil eine Datei), Bilder-Eintrag und Profilbild
 * werden nur im Speicher gehalten.
 */
class DrawerData(
    context: Context,
    private val repo: ChatRepository,
    private val settings: SettingsRepository,
    private val scope: CoroutineScope,
) {
    data class Snapshot(
        val profileId: String = "",
        val chats: List<ConversationDto> = emptyList(),
        val gems: List<GemDto> = emptyList(),
        val imagesAvailable: Boolean = false,
        val userId: String? = null,
        val avatarVersion: Long? = null,
    )

    @Serializable
    private data class Stored(
        val chats: List<ConversationDto> = emptyList(),
        val gems: List<GemDto> = emptyList(),
    )

    private val dir = File(context.filesDir, "drawer_cache")
    private val json = Json { ignoreUnknownKeys = true; explicitNulls = false }
    private val mutex = Mutex()
    private val _state = MutableStateFlow(Snapshot())
    val state: StateFlow<Snapshot> = _state.asStateFlow()

    @Volatile private var lastRefreshAt = 0L
    private var pollJob: Job? = null

    /** Zaehlt Konto- und Anmeldewechsel. Ein Abruf, der unter einer anderen
     *  Generation begann, gehoert womoeglich zum vorigen Konto und wird
     *  verworfen, auch bei A -> B -> A. */
    private val generation = java.util.concurrent.atomic.AtomicInteger()

    init {
        // Profilwechsel und Login: die Liste gehoert zum Konto. Erst die
        // gemerkte Liste zeigen, dann abgleichen.
        scope.launch {
            settings.settingsFlow
                .map { it.activeProfileId to it.serverToken }
                .distinctUntilChanged()
                .collect { (profileId, token) ->
                    // Sofort umschalten, nicht erst nach laufenden Abrufen:
                    // die Netzaufrufe halten den Mutex nicht.
                    generation.incrementAndGet()
                    mutex.withLock {
                        if (_state.value.profileId != profileId) {
                            _state.value = load(profileId)
                        }
                    }
                    if (token.isNotBlank()) refresh(force = true)
                }
        }
    }

    /** App kommt in den Vordergrund: sofort abgleichen, dann jede Minute. */
    fun onForeground() {
        pollJob?.cancel()
        pollJob = scope.launch {
            while (isActive) {
                refresh(force = false)
                delay(POLL_MS)
            }
        }
    }

    fun onBackground() {
        pollJob?.cancel()
        pollJob = null
    }

    /** Abgleich anstossen. Ohne `force` hoechstens alle paar Sekunden, damit
     *  mehrere Anlaesse kurz hintereinander nur einen Abruf ausloesen. */
    fun refresh(force: Boolean = false) {
        scope.launch { refreshNow(force) }
    }

    private suspend fun refreshNow(force: Boolean) {
        val now = System.currentTimeMillis()
        if (!force && now - lastRefreshAt < THROTTLE_MS) return
        val gen = generation.get()
        val s = settings.current()
        if (!s.isConfigured) return
        lastRefreshAt = now
        val profileId = s.activeProfileId
        val chats = runCatching { repo.list() }
            .onFailure { Log.w("PC_NET", "drawer chats failed: ${it::class.java.simpleName}") }
            .getOrNull()
        val gems = runCatching { repo.listGems() }.getOrNull()
        val images = runCatching { repo.imagesConfig().configured }.getOrNull()
        val me = runCatching { repo.me() }.getOrNull()
        // Waehrend des Abrufs kann das Profil gewechselt haben: dann gehoert
        // das Ergebnis (ganz oder teilweise) zum alten Konto und wird verworfen.
        mutex.withLock { apply(gen, profileId, chats, gems, images, me) }
    }

    private fun apply(
        gen: Int,
        profileId: String,
        chats: List<ConversationDto>?,
        gems: List<GemDto>?,
        images: Boolean?,
        me: MeDto?,
    ) {
        if (generation.get() != gen || _state.value.profileId != profileId) return
        val old = _state.value.takeIf { it.profileId == profileId } ?: Snapshot(profileId)
        val next = old.copy(
            chats = chats ?: old.chats,
            gems = gems ?: old.gems,
            imagesAvailable = images ?: old.imagesAvailable,
            userId = me?.id ?: old.userId,
            avatarVersion = if (me != null) me.avatarVersion else old.avatarVersion,
        )
        // Gleiche Daten: nichts ausloesen, die Leiste zeichnet dann nicht neu.
        if (next != _state.value) _state.value = next
        if (chats != null || gems != null) save(profileId, next)
    }

    private fun file(profileId: String) =
        File(dir, "drawer-" + profileId.replace(Regex("[^A-Za-z0-9_-]"), "_") + ".json")

    private fun load(profileId: String): Snapshot {
        if (profileId.isBlank()) return Snapshot(profileId)
        val stored = runCatching {
            json.decodeFromString(Stored.serializer(), file(profileId).readText())
        }.getOrNull() ?: return Snapshot(profileId)
        return Snapshot(profileId, chats = stored.chats, gems = stored.gems)
    }

    private fun save(profileId: String, snap: Snapshot) {
        if (profileId.isBlank()) return
        runCatching {
            dir.mkdirs()
            val tmp = File(dir, "drawer.tmp")
            tmp.writeText(json.encodeToString(Stored.serializer(), Stored(snap.chats, snap.gems)))
            tmp.renameTo(file(profileId))
        }.onFailure { Log.w("PC_NET", "drawer cache not saved: ${it.message}") }
    }

    companion object {
        private const val POLL_MS = 60_000L
        private const val THROTTLE_MS = 3_000L
    }
}
