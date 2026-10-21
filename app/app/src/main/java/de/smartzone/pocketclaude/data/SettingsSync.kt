package de.smartzone.pocketclaude.data

import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * Haelt die Oberflaechen-Einstellungen der App mit dem Server abgleich, damit
 * App und Web-UI dieselben haben.
 *
 * - Holen: beim Start, nach Login oder Profilwechsel und wenn die App wieder in
 *   den Vordergrund kommt (hoechstens alle 30 s).
 * - Senden: jede Aenderung in der App, kurz gesammelt.
 *
 * Bei gleichzeitigen Aenderungen gewinnt die zuletzt gesendete, je Schluessel
 * bzw. je Eintrag der Listen pro Familie und Chat. Ohne Netz bleibt alles
 * lokal; Ausstehendes geht beim naechsten Versuch raus und wird bis dahin von
 * keinem Abgleich ueberschrieben.
 */
class SettingsSync(
    private val settings: SettingsRepository,
    private val api: ApiClient,
    private val scope: CoroutineScope,
) {
    private val mutex = Mutex()

    // Noch nicht bestaetigte Aenderungen, immer fuer genau EIN Profil. Wechselt
    // das Profil, wird verworfen statt sie ins falsche Konto zu schicken.
    private val lock = Any()
    private var pendingProfile: String? = null
    private val pending = mutableMapOf<String, JsonElement>()

    private var pushJob: Job? = null
    private var lastPullAt = 0L

    init {
        settings.onLocalChange = { profileId, changed ->
            addPending(profileId, changed, newerWins = true)
            schedulePush()
        }
        // Login und Profilwechsel: die Einstellungen gehoeren zum Konto.
        scope.launch {
            settings.settingsFlow
                .map { it.activeProfileId to it.serverToken }
                .distinctUntilChanged()
                .collect { (_, token) -> if (token.isNotBlank()) pull(force = true) }
        }
    }

    /** App kommt in den Vordergrund. */
    fun onForeground() {
        scope.launch { pull(force = false) }
    }

    /** `newerWins = false`: nur nachtragen, eine neuere Aenderung bleibt. */
    private fun addPending(profileId: String, changed: Map<String, JsonElement>, newerWins: Boolean) =
        synchronized(lock) {
            if (pendingProfile != profileId) {
                pending.clear()
                pendingProfile = profileId
            }
            for ((key, value) in changed) {
                val old = pending[key]
                pending[key] = when {
                    old is JsonObject && value is JsonObject ->
                        JsonObject(if (newerWins) old + value else value + old)
                    old == null || newerWins -> value
                    else -> old
                }
            }
        }

    private fun schedulePush() {
        pushJob?.cancel()
        pushJob = scope.launch {
            delay(700)
            push()
        }
    }

    private suspend fun push() = mutex.withLock {
        val active = settings.current()
        val (profile, batch) = synchronized(lock) {
            (pendingProfile to pending.toMap()).also { pending.clear() }
        }
        if (batch.isEmpty() || profile == null) return@withLock
        if (profile != active.activeProfileId || !active.isConfigured) {
            Log.i("PC_NET", "ui-settings: ${batch.size} changes of an inactive profile dropped")
            return@withLock
        }
        runCatching { api.putUiSettings(batch) }
            .onFailure { e ->
                Log.w("PC_NET", "ui-settings push failed: ${e::class.java.simpleName}")
                addPending(profile, batch, newerWins = false)
            }
    }

    private suspend fun pull(force: Boolean) {
        val now = System.currentTimeMillis()
        if (!force && now - lastPullAt < 30_000) return
        val current = settings.current()
        if (!current.isConfigured) return
        // Erst eigene, noch nicht gesendete Aenderungen raus.
        pushJob?.cancel()
        push()
        mutex.withLock {
            val remote = runCatching { api.getUiSettings().settings }
                .onFailure { Log.w("PC_NET", "ui-settings pull failed: ${it::class.java.simpleName}") }
                .getOrNull() ?: return@withLock
            lastPullAt = now
            // Was waehrend des Abrufs geaendert wurde oder nicht gesendet werden
            // konnte, ist neuer als die Antwort und wird nicht ueberschrieben.
            val dirty = synchronized(lock) {
                if (pendingProfile == current.activeProfileId) pending.keys.toSet() else emptySet()
            }
            val upload = settings.syncWithRemote(current.activeProfileId, remote, dirty)
            if (upload.isNotEmpty()) {
                val asJson = upload.mapValues { JsonPrimitive(it.value) as JsonElement }
                runCatching { api.putUiSettings(asJson) }
                    .onFailure {
                        Log.w("PC_NET", "ui-settings upload failed: ${it::class.java.simpleName}")
                        // Beim naechsten Mal erneut, und bis dahin geschuetzt.
                        addPending(current.activeProfileId, asJson, newerWins = false)
                        schedulePush()
                    }
            }
            Log.i("PC_NET", "ui-settings synced: ${remote.size} from server, ${upload.size} up, ${dirty.size} kept")
        }
    }
}
