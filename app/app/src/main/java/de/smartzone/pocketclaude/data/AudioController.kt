package de.smartzone.pocketclaude.data

import android.content.ComponentName
import android.content.Context
import androidx.media3.common.MediaItem
import androidx.media3.common.MediaMetadata
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.session.MediaController
import androidx.media3.session.SessionToken
import com.google.common.util.concurrent.ListenableFuture
import com.google.common.util.concurrent.MoreExecutors
import de.smartzone.pocketclaude.audio.PocketAudioService
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient

/**
 * Steuert die TTS-Wiedergabe über einen MediaSessionService (PocketAudioService).
 * Vorteile gegenüber direktem MediaPlayer:
 *   - Wiedergabe läuft weiter, wenn App im Hintergrund
 *   - Lock-Screen + Notification mit Play/Pause/Skip automatisch
 *   - Bluetooth-Kopfhörer-Controls greifen
 *   - Audio-Focus-Handling (Klingelton/Anrufe pausieren TTS)
 *
 * Workflow:
 *   1. play(messageId, url) bekommt eine vor-authentifizierte URL
 *      (Token als `?token=…` darin) und gibt sie direkt an ExoPlayer.
 *   2. ExoPlayer streamt die MP3 **progressive** über HTTP — die Wiedergabe
 *      startet, sobald genug MP3-Frames gepuffert sind, NICHT erst wenn die
 *      ganze Datei da ist. Bei Gemini-TTS-Chunking liefert der Server die
 *      ersten Frames schon nach 3-5s; vorher waren es 20-25s.
 */
class AudioController(
    private val context: Context,
    private val httpClient: OkHttpClient,
) {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var currentJob: Job? = null
    private var controllerFuture: ListenableFuture<MediaController>? = null
    private var controller: MediaController? = null

    private val _state = MutableStateFlow(State())
    val state: StateFlow<State> = _state.asStateFlow()

    data class State(
        val loadingMessageId: Long? = null,
        val playingMessageId: Long? = null,
        /** Wenn != null: Wiedergabe ist pausiert; Position bleibt erhalten,
         *  Resume nimmt da wieder auf. */
        val pausedMessageId: Long? = null,
        val error: String? = null,
    )

    @Synchronized
    private fun ensureController(onReady: (MediaController) -> Unit) {
        val existing = controller
        if (existing != null) {
            onReady(existing)
            return
        }
        // Wenn schon ein Future läuft (parallele play()-Aufrufe), nicht noch
        // einen zweiten MediaController-Build starten — sonst hängen zwei
        // verschiedene Player-Listener am State und Events doppeln sich.
        val pending = controllerFuture
        if (pending != null) {
            pending.addListener({
                val c = controller
                if (c != null) onReady(c)
            }, MoreExecutors.directExecutor())
            return
        }
        val token = SessionToken(context, ComponentName(context, PocketAudioService::class.java))
        val future = MediaController.Builder(context, token).buildAsync()
        controllerFuture = future
        future.addListener({
            try {
                val c = future.get()
                synchronized(this) {
                    if (controller == null) {
                        controller = c
                        c.addListener(playerListener)
                    }
                }
                onReady(controller ?: c)
            } catch (e: Exception) {
                _state.value = State(error = "Audio-Service nicht erreichbar: ${e.message}")
            }
        }, MoreExecutors.directExecutor())
    }

    private val playerListener = object : Player.Listener {
        override fun onIsPlayingChanged(isPlaying: Boolean) {
            val st = _state.value
            if (isPlaying) {
                // Beim Start (oder Resume aus Pause): playing-State setzen.
                val msgId = st.loadingMessageId ?: st.pausedMessageId ?: st.playingMessageId
                if (msgId != null) {
                    _state.value = st.copy(
                        loadingMessageId = null,
                        playingMessageId = msgId,
                        pausedMessageId = null,
                    )
                }
            } else {
                // !isPlaying kann heißen: Pause, oder Ende, oder Fehler.
                val controllerNow = controller
                val pbState = controllerNow?.playbackState
                if (controllerNow == null || pbState == Player.STATE_ENDED ||
                    pbState == Player.STATE_IDLE
                ) {
                    // Wiedergabe wirklich vorbei → State zurücksetzen.
                    cleanupCurrent()
                    _state.value = State()
                } else if (st.playingMessageId != null) {
                    // Pause aus dem Spiel-Zustand (kann auch von System-Media-
                    // Controls kommen, Lock Screen / Notification). State syncen.
                    _state.value = st.copy(
                        playingMessageId = null,
                        pausedMessageId = st.playingMessageId,
                    )
                }
            }
        }

        override fun onPlayerError(error: PlaybackException) {
            cleanupCurrent()
            _state.value = State(error = "Wiedergabe-Fehler: ${error.message}")
        }
    }

    @Synchronized
    fun play(
        messageId: Long,
        url: String,
        cacheKey: String? = null,
        headers: Map<String, String> = emptyMap(),
        speed: Float = 1.0f,
    ) {
        // headers wird inzwischen ignoriert — Token sitzt in der URL als
        // ?token=…, weil ExoPlayer keine eigenen Auth-Header mitschicken kann.
        // cacheKey: stabiler Schlüssel (ohne wechselnden Token-Param) für den
        // ExoPlayer-Cache. Bei Re-Listen → direkter Disk-Hit.
        currentJob?.cancel()
        cleanupCurrent()
        _state.value = State(loadingMessageId = messageId)

        currentJob = scope.launch {
            try {
                withContext(Dispatchers.Main) {
                    startPlayback(messageId, url, cacheKey, speed)
                }
            } catch (e: Exception) {
                _state.value = State(error = e.message ?: e::class.java.simpleName)
            }
        }
    }

    /**
     * `speed` ist nur fuer Anbieter gedacht, die das Tempo NICHT selbst
     * einstellen koennen (Gemini-Web). Alle anderen liefern das Audio bereits
     * in der gewuenschten Geschwindigkeit, dort bleibt der Wert auf 1.0 —
     * sonst wuerde das Tempo zweimal angewandt.
     */
    private fun startPlayback(messageId: Long, url: String, cacheKey: String?, speed: Float = 1.0f) {
        if (_state.value.loadingMessageId != messageId) {
            return
        }
        ensureController { c ->
            val builder = MediaItem.Builder()
                .setUri(android.net.Uri.parse(url))
                .setMediaMetadata(
                    MediaMetadata.Builder()
                        .setTitle("PocketClot")
                        .setArtist("Nachricht $messageId")
                        .setIsBrowsable(false)
                        .setIsPlayable(true)
                        .build()
                )
            if (!cacheKey.isNullOrBlank()) {
                builder.setCustomCacheKey(cacheKey)
            }
            c.setMediaItem(builder.build())
            c.setPlaybackSpeed(speed.coerceIn(0.25f, 2.0f))
            c.prepare()
            c.playWhenReady = true
        }
    }

    /** Pause: behält Player-Position, Resume nimmt da wieder auf. */
    @Synchronized
    fun pause() {
        val st = _state.value
        val msgId = st.playingMessageId ?: return
        controller?.let { c ->
            try { c.playWhenReady = false } catch (_: Exception) {}
        }
        _state.value = st.copy(
            playingMessageId = null,
            pausedMessageId = msgId,
        )
    }

    /** Resume aus dem Pause-Zustand. */
    @Synchronized
    fun resume() {
        val st = _state.value
        val msgId = st.pausedMessageId ?: return
        controller?.let { c ->
            try { c.playWhenReady = true } catch (_: Exception) {}
        }
        _state.value = st.copy(
            playingMessageId = msgId,
            pausedMessageId = null,
        )
    }

    /** Abbrechen: Player komplett platt machen → nächstes speak() fängt von vorn an. */
    @Synchronized
    fun stop() {
        currentJob?.cancel()
        currentJob = null
        controller?.let {
            try { it.stop() } catch (_: Exception) {}
            try { it.clearMediaItems() } catch (_: Exception) {}
        }
        _state.value = State()
    }

    /** No-op — Token-in-URL bedeutet, dass wir keine temporären Dateien mehr
     *  anlegen. Bleibt als Hook für künftige Cache-Erweiterungen. */
    private fun cleanupCurrent() { /* nichts mehr zu putzen */ }

    fun clearError() {
        if (_state.value.error != null) {
            _state.value = _state.value.copy(error = null)
        }
    }

    fun release() {
        try {
            controller?.removeListener(playerListener)
            controller?.release()
        } catch (_: Exception) {}
        controllerFuture?.let { MediaController.releaseFuture(it) }
        controller = null
        controllerFuture = null
    }
}
