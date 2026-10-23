package de.smartzone.pocketclaude.audio

import android.content.Intent
import androidx.annotation.OptIn
import androidx.media3.common.AudioAttributes
import androidx.media3.common.C
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.DefaultHttpDataSource
import androidx.media3.datasource.cache.CacheDataSource
import androidx.media3.datasource.cache.LeastRecentlyUsedCacheEvictor
import androidx.media3.datasource.cache.SimpleCache
import androidx.media3.database.StandaloneDatabaseProvider
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import androidx.media3.session.DefaultMediaNotificationProvider
import androidx.media3.session.MediaSession
import androidx.media3.session.MediaSessionService
import java.io.File

/**
 * Foreground-Service mit MediaSession. Hält die Wiedergabe am Leben, auch wenn
 * die App im Hintergrund ist. Lock-Screen-Controls + Notification entstehen
 * automatisch durch media3-session.
 *
 * Audio-Cache: ExoPlayer hat einen eingebauten HTTP-Cache (media3-datasource).
 * Vorgenerierte TTS-Audios werden unter `cacheDir/tts_cache/` abgelegt
 * (LRU, max 100 MB). Beim erneuten Vorlesen derselben Message mit selber
 * Voice+Rate-Kombination wird direkt aus dem Cache gespielt — kein Server-
 * Roundtrip, kein erneutes Synthetisieren.
 */
@OptIn(UnstableApi::class)  // SimpleCache als Feld
class PocketAudioService : MediaSessionService() {
    private var mediaSession: MediaSession? = null
    private var cache: SimpleCache? = null

    @OptIn(UnstableApi::class)
    override fun onCreate() {
        super.onCreate()

        // Persistenter LRU-Cache fürs TTS-Audio
        val cacheDir = File(cacheDir, "tts_cache").also { it.mkdirs() }
        val cacheInstance = SimpleCache(
            cacheDir,
            LeastRecentlyUsedCacheEvictor(100L * 1024 * 1024),  // 100 MB
            StandaloneDatabaseProvider(this),
        )
        cache = cacheInstance

        // HTTP-Stack mit Timeouts und User-Agent
        val httpFactory = DefaultHttpDataSource.Factory()
            .setConnectTimeoutMs(10_000)
            .setReadTimeoutMs(60_000)
            .setAllowCrossProtocolRedirects(true)
            .setUserAgent("PocketClot/Android")

        val cacheFactory = CacheDataSource.Factory()
            .setCache(cacheInstance)
            .setUpstreamDataSourceFactory(httpFactory)
            // Bei Fehler beim Lesen aus Cache → Upstream direkt versuchen statt
            // zu scheitern. Vermeidet kaputten Cache-Zustand auf flaky-net.
            .setFlags(CacheDataSource.FLAG_IGNORE_CACHE_ON_ERROR)

        val mediaSourceFactory = DefaultMediaSourceFactory(this)
            .setDataSourceFactory(cacheFactory)

        val player = ExoPlayer.Builder(this)
            .setMediaSourceFactory(mediaSourceFactory)
            .setAudioAttributes(
                AudioAttributes.Builder()
                    .setUsage(C.USAGE_MEDIA)
                    .setContentType(C.AUDIO_CONTENT_TYPE_SPEECH)
                    .build(),
                /* handleAudioFocus = */ true,
            )
            .setHandleAudioBecomingNoisy(true)
            .build()

        mediaSession = MediaSession.Builder(this, player).build()

        // Vorlese-Benachrichtigung mit dem App-Symbol statt dem Notensymbol
        // von Media3, wie die uebrigen Benachrichtigungen.
        setMediaNotificationProvider(
            DefaultMediaNotificationProvider.Builder(this).build().apply {
                setSmallIcon(de.smartzone.pocketclaude.R.drawable.ic_notification)
            }
        )
    }

    override fun onGetSession(controllerInfo: MediaSession.ControllerInfo): MediaSession? =
        mediaSession

    override fun onTaskRemoved(rootIntent: Intent?) {
        // Wenn der User die App aus den Recents wischt: Wiedergabe stoppen + Service beenden
        mediaSession?.player?.let { player ->
            if (!player.playWhenReady || player.mediaItemCount == 0) {
                stopSelf()
            }
        }
    }

    @OptIn(UnstableApi::class)
    override fun onDestroy() {
        mediaSession?.run {
            player.release()
            release()
            mediaSession = null
        }
        try { cache?.release() } catch (_: Exception) {}
        cache = null
        super.onDestroy()
    }
}
