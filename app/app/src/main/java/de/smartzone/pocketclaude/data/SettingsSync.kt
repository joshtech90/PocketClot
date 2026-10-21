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

/**
 * Haelt die Oberflaechen-Einstellungen der App mit dem Server abgleich, damit
 * App und Web-UI dieselben haben.
 *
 * - Holen: beim Start, nach Login oder Profilwechsel und wenn die App wieder in
 *   den Vordergrund kommt (hoechstens alle 30 s).
 * - Senden: jede Aenderung in der App, kurz gesammelt.
 *
 * Bei gleichzeitigen Aenderungen gewinnt die zuletzt gesendete, je Schluessel.
 * Ohne Netz bleibt alles lokal; Ausstehendes geht beim naechsten Versuch raus.
 */
class SettingsSync(
    private val settings: SettingsRepository,
    private val api: ApiClient,
    private val scope: CoroutineScope,
) {
    private val mutex = Mutex()
    private val pending = mutableMapOf<String, String>()
    private var pushJob: Job? = null
    private var lastPullAt = 0L

    init {
        settings.onLocalChange = { changed ->
            synchronized(pending) { pending.putAll(changed) }
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

    private fun schedulePush() {
        pushJob?.cancel()
        pushJob = scope.launch {
            delay(700)
            push()
        }
    }

    private suspend fun push() = mutex.withLock {
        val batch = synchronized(pending) { pending.toMap().also { pending.clear() } }
        if (batch.isEmpty() || !settings.current().isConfigured) return@withLock
        runCatching { api.putUiSettings(batch) }
            .onFailure { e ->
                Log.w("PC_NET", "ui-settings push failed: ${e::class.java.simpleName}")
                // Neuere Aenderungen derselben Schluessel nicht ueberschreiben.
                synchronized(pending) { batch.forEach { (k, v) -> pending.putIfAbsent(k, v) } }
            }
    }

    private suspend fun pull(force: Boolean) {
        val now = System.currentTimeMillis()
        if (!force && now - lastPullAt < 30_000) return
        val current = settings.current()
        if (!current.isConfigured) return
        // Erst eigene, noch nicht gesendete Aenderungen raus, sonst holt der
        // Abgleich den alten Server-Wert zurueck.
        pushJob?.cancel()
        push()
        mutex.withLock {
            val remote = runCatching { api.getUiSettings().settings }
                .onFailure { Log.w("PC_NET", "ui-settings pull failed: ${it::class.java.simpleName}") }
                .getOrNull() ?: return@withLock
            lastPullAt = now
            val upload = settings.syncWithRemote(current.activeProfileId, remote)
            if (upload.isNotEmpty()) {
                runCatching { api.putUiSettings(upload) }
                    .onFailure { Log.w("PC_NET", "ui-settings upload failed: ${it::class.java.simpleName}") }
            }
            Log.i("PC_NET", "ui-settings synced: ${remote.size} from server, ${upload.size} up")
        }
    }
}
