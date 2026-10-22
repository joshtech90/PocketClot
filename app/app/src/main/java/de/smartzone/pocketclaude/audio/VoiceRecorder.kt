package de.smartzone.pocketclaude.audio

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaCodec
import android.media.MediaCodecInfo
import android.media.MediaFormat
import android.media.MediaMuxer
import android.media.MediaRecorder
import android.util.Log
import androidx.core.content.ContextCompat
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger
import kotlin.math.abs
import kotlin.concurrent.thread

/**
 * Kapselt eine Voice-Input-Aufnahme.
 *
 * Mai 2026 — komplett umgebaut wegen zweier Anforderungen, die sich
 * gegenseitig zwicken:
 *
 *  1) **VAD (Voice Activity Detection)** im Auto-Modus braucht Zugriff
 *     auf Peak-Amplitude der Samples. `MediaRecorder.getMaxAmplitude()`
 *     funktioniert offiziell nur mit AMR-Encoder; bei AAC liefert es auf
 *     vielen Devices durchgehend 0 (verifiziert auf Pixel 8, PC_VAD-Logs
 *     2026-05-22).
 *
 *  2) **Dateigröße** soll klein bleiben fürs Upload zu Groq Whisper.
 *     Rohes PCM/WAV ist 32 KB/s → 60 s = ~1,9 MB; AAC bei 32 kbps ist
 *     ~4 KB/s → 60 s = ~240 KB. Faktor 8.
 *
 * Lösung: `AudioRecord` liest rohes PCM (für VAD), die Samples werden
 * gleichzeitig durch einen `MediaCodec`-AAC-Encoder geschoben und mit
 * `MediaMuxer` in einen MPEG-4-Container gemuxt. Output ist .m4a wie
 * früher mit MediaRecorder — Groq frisst das unverändert.
 *
 * Lifecycle:
 *   - `start()`: AudioRecord + MediaCodec + MediaMuxer öffnen,
 *     Reader-Thread starten.
 *   - `stop()`: EOS senden, Encoder ausdrainieren, Muxer schließen,
 *     File-Handle zurückgeben.
 *   - `cancel()`: hart abbrechen, Datei löschen.
 *
 * `currentAmplitude()` ist Lock-frei via AtomicInteger und resettet beim
 * Lesen — passt zur MediaRecorder-Semantik.
 */
class VoiceRecorder(private val appContext: Context) {

    @Volatile private var recorder: AudioRecord? = null
    @Volatile private var outputFile: File? = null
    @Volatile private var codec: MediaCodec? = null
    @Volatile private var muxer: MediaMuxer? = null
    @Volatile private var audioTrackIdx: Int = -1
    @Volatile private var muxerStarted: Boolean = false
    @Volatile private var readerThread: Thread? = null

    private val active = AtomicBoolean(false)
    private val lastPeak = AtomicInteger(0)
    private var startedAtMs: Long = 0L

    val isRecording: Boolean get() = active.get()
    val elapsedMs: Long get() = if (active.get() && startedAtMs > 0) {
        System.currentTimeMillis() - startedAtMs
    } else 0L

    /** Peak seit dem letzten Aufruf (0..32767, monotones Maximum innerhalb
     *  des Polling-Intervalls). 0 wenn keine Session läuft. */
    fun currentAmplitude(): Int =
        if (active.get()) lastPeak.getAndSet(0) else 0

    fun hasPermission(): Boolean =
        ContextCompat.checkSelfPermission(
            appContext, Manifest.permission.RECORD_AUDIO
        ) == PackageManager.PERMISSION_GRANTED

    @Throws(IllegalStateException::class, SecurityException::class)
    fun start() {
        if (active.get()) {
            Log.w(TAG, "Leftover recording detected on start() — cancelling first.")
            cancel()
        }
        if (!hasPermission()) {
            throw SecurityException("RECORD_AUDIO permission missing.")
        }

        val cacheDir = File(appContext.cacheDir, "voice").apply { mkdirs() }
        val file = File(cacheDir, "voice-${System.currentTimeMillis()}.m4a")

        // --- AudioRecord setup ---
        val minBuf = AudioRecord.getMinBufferSize(
            SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT
        )
        if (minBuf <= 0) {
            throw IllegalStateException(
                "AudioRecord.getMinBufferSize fehlgeschlagen (Rate $SAMPLE_RATE)."
            )
        }
        val bufSize = maxOf(minBuf * 2, CHUNK_BYTES * 4)
        @Suppress("MissingPermission")
        val rec = try {
            AudioRecord(
                MediaRecorder.AudioSource.VOICE_RECOGNITION,
                SAMPLE_RATE,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT,
                bufSize,
            )
        } catch (t: Throwable) {
            throw IllegalStateException("AudioRecord create fehlgeschlagen: ${t.message}", t)
        }
        if (rec.state != AudioRecord.STATE_INITIALIZED) {
            runCatching { rec.release() }
            throw IllegalStateException("AudioRecord state=${rec.state} (nicht INITIALIZED)")
        }

        // --- MediaCodec AAC encoder + MediaMuxer setup ---
        val codec: MediaCodec
        val muxer: MediaMuxer
        var createdCodec: MediaCodec? = null
        try {
            val format = MediaFormat.createAudioFormat(
                MIME_AAC, SAMPLE_RATE, CHANNELS,
            ).apply {
                setInteger(
                    MediaFormat.KEY_AAC_PROFILE,
                    MediaCodecInfo.CodecProfileLevel.AACObjectLC,
                )
                setInteger(MediaFormat.KEY_BIT_RATE, AAC_BITRATE)
                setInteger(MediaFormat.KEY_MAX_INPUT_SIZE, CHUNK_BYTES * 2)
            }
            codec = MediaCodec.createEncoderByType(MIME_AAC).also {
                createdCodec = it
                it.configure(format, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE)
                it.start()
            }
            muxer = MediaMuxer(file.absolutePath, MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4)
        } catch (t: Throwable) {
            runCatching { rec.release() }
            // Ein schon gestarteter Hardware-Encoder muss frei werden, sonst
            // fehlt er bis zum App-Neustart (Geraete haben nur wenige davon).
            runCatching { createdCodec?.stop() }
            runCatching { createdCodec?.release() }
            file.delete()
            throw IllegalStateException("AAC-Encoder/Muxer Setup fehlgeschlagen: ${t.message}", t)
        }

        try {
            rec.startRecording()
        } catch (t: Throwable) {
            runCatching { codec.stop(); codec.release() }
            runCatching { muxer.release() }
            runCatching { rec.release() }
            file.delete()
            throw IllegalStateException("AudioRecord.startRecording fehlgeschlagen: ${t.message}", t)
        }

        this.recorder = rec
        this.codec = codec
        this.muxer = muxer
        this.outputFile = file
        this.audioTrackIdx = -1
        this.muxerStarted = false
        this.lastPeak.set(0)
        this.startedAtMs = System.currentTimeMillis()
        this.active.set(true)

        readerThread = thread(name = "VoiceRecorder-Reader", isDaemon = true) {
            runReaderLoop(rec, codec, muxer)
        }

        Log.d(TAG, "Recording started → ${file.absolutePath}")
    }

    /** Reader-Thread: pollt AudioRecord, tracked Peak, schaufelt Samples in
     *  den AAC-Encoder, drainiert Encoder-Output in den Muxer. Stoppt
     *  sobald `active = false` — der Caller (stop()) signalisiert das
     *  Ende und drainiert den Encoder dann ein letztes Mal. */
    private fun runReaderLoop(
        rec: AudioRecord,
        codec: MediaCodec,
        muxer: MediaMuxer,
    ) {
        val pcmShorts = ShortArray(CHUNK_SHORTS)
        val pcmBytes = ByteArray(CHUNK_BYTES)
        val pcmBB = ByteBuffer.wrap(pcmBytes).order(ByteOrder.LITTLE_ENDIAN)
        val info = MediaCodec.BufferInfo()
        var presentationTimeUs = 0L
        try {
            while (active.get()) {
                val r = rec.read(pcmShorts, 0, pcmShorts.size)
                if (r <= 0) {
                    if (r < 0) {
                        Log.w(TAG, "AudioRecord.read returned $r — stopping reader.")
                        break
                    }
                    continue
                }
                // Peak im Chunk berechnen (linearer Scan, vernachlässigbar).
                var peak = 0
                for (i in 0 until r) {
                    val v = abs(pcmShorts[i].toInt())
                    if (v > peak) peak = v
                }
                var prev: Int
                do {
                    prev = lastPeak.get()
                } while (peak > prev && !lastPeak.compareAndSet(prev, peak))

                // PCM in Bytes konvertieren
                pcmBB.clear()
                for (i in 0 until r) pcmBB.putShort(pcmShorts[i])
                val nBytes = r * 2

                // In Encoder einspeisen
                val inIdx = codec.dequeueInputBuffer(10_000L)
                if (inIdx >= 0) {
                    val inBuf = codec.getInputBuffer(inIdx)
                    inBuf?.let {
                        it.clear()
                        it.put(pcmBytes, 0, nBytes)
                    }
                    codec.queueInputBuffer(inIdx, 0, nBytes, presentationTimeUs, 0)
                    presentationTimeUs += (r * 1_000_000L) / SAMPLE_RATE
                }

                // Encoder-Output abgreifen + an Muxer weiterreichen
                drainEncoder(codec, muxer, info, endOfStream = false)
            }
        } catch (t: Throwable) {
            Log.w(TAG, "Reader-Thread exception", t)
        }
    }

    /** Pumpt fertige AAC-Frames aus dem Encoder in den Muxer. Bei EOS
     *  blockiert es bis der Encoder durch ist. */
    private fun drainEncoder(
        codec: MediaCodec,
        muxer: MediaMuxer,
        info: MediaCodec.BufferInfo,
        endOfStream: Boolean,
    ) {
        val timeoutUs = if (endOfStream) 10_000L else 0L
        // Obergrenze fuers Ausdrainieren: Kommt das EOS-Flag nie (Encoder
        // haengt, EOS liess sich nicht einreihen), lief die Schleife vorher
        // endlos auf einem IO-Thread.
        val deadline = System.currentTimeMillis() + EOS_DRAIN_TIMEOUT_MS
        while (true) {
            val outIdx = codec.dequeueOutputBuffer(info, timeoutUs)
            if (outIdx == MediaCodec.INFO_TRY_AGAIN_LATER) {
                if (!endOfStream) return
                // bei EOS: weiterpollen bis BUFFER_FLAG_END_OF_STREAM da ist
                if (System.currentTimeMillis() > deadline) {
                    throw IllegalStateException("Encoder lieferte kein Ende-Signal")
                }
                continue
            }
            if (outIdx == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) {
                if (muxerStarted) {
                    Log.w(TAG, "Format change after muxer start — ignored.")
                    continue
                }
                val newFormat = codec.outputFormat
                synchronized(this) {
                    audioTrackIdx = muxer.addTrack(newFormat)
                    muxer.start()
                    muxerStarted = true
                }
                continue
            }
            if (outIdx < 0) continue

            val outBuf = codec.getOutputBuffer(outIdx)
            if (outBuf != null && info.size > 0 && muxerStarted &&
                (info.flags and MediaCodec.BUFFER_FLAG_CODEC_CONFIG) == 0
            ) {
                outBuf.position(info.offset)
                outBuf.limit(info.offset + info.size)
                synchronized(this) {
                    if (muxerStarted && audioTrackIdx >= 0) {
                        muxer.writeSampleData(audioTrackIdx, outBuf, info)
                    }
                }
            }
            codec.releaseOutputBuffer(outIdx, false)

            if ((info.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM) != 0) return
        }
    }

    fun stop(): File? {
        if (!active.compareAndSet(true, false)) return null
        val rec = this.recorder
        val file = this.outputFile
        val codec = this.codec
        val muxer = this.muxer
        val thread = this.readerThread
        this.recorder = null
        this.codec = null
        this.muxer = null
        this.outputFile = null
        this.readerThread = null

        val durMs = if (startedAtMs > 0) System.currentTimeMillis() - startedAtMs else 0L
        startedAtMs = 0L

        // Reader-Thread joinen (max 500 ms — dann sind alle Samples
        // garantiert in den Encoder geschoben).
        try { thread?.join(500) } catch (_: InterruptedException) {}

        // AudioRecord ab jetzt nicht mehr benötigt.
        runCatching { rec?.stop() }
        runCatching { rec?.release() }

        // EOS an den Encoder schicken + ausdrainieren.
        var fileOk = false
        if (codec != null && muxer != null) {
            try {
                // Sind gerade alle Eingabepuffer belegt, muss der Encoder erst
                // Ausgabe loswerden; deshalb abwechselnd drainieren und warten.
                val info = MediaCodec.BufferInfo()
                var inIdx = -1
                repeat(50) {
                    if (inIdx < 0) {
                        inIdx = codec.dequeueInputBuffer(10_000L)
                        if (inIdx < 0) drainEncoder(codec, muxer, info, endOfStream = false)
                    }
                }
                if (inIdx < 0) throw IllegalStateException("Kein Eingabepuffer fuer das Ende-Signal")
                codec.queueInputBuffer(
                    inIdx, 0, 0, 0,
                    MediaCodec.BUFFER_FLAG_END_OF_STREAM,
                )
                drainEncoder(codec, muxer, info, endOfStream = true)
                fileOk = muxerStarted
            } catch (t: Throwable) {
                Log.w(TAG, "Stop/drain failed: $t")
            }
            runCatching { codec.stop() }
            runCatching { codec.release() }
            // Scheitert muxer.stop(), fehlt der moov-Block und die Datei ist
            // unbrauchbar, obwohl sie Bytes enthaelt.
            if (runCatching { if (muxerStarted) muxer.stop() }.isFailure) fileOk = false
            runCatching { muxer.release() }
        }
        muxerStarted = false
        audioTrackIdx = -1

        if (file == null) return null
        if (!fileOk || !file.exists() || file.length() == 0L) {
            file.delete()
            return null
        }
        if (durMs < 200) {
            Log.d(TAG, "Recording too short ($durMs ms) — discarded.")
            file.delete()
            return null
        }
        Log.d(TAG, "Recording stopped — ${file.length()} bytes, ${durMs} ms (AAC ${AAC_BITRATE/1000}kbps)")
        return file
    }

    fun cancel() {
        if (!active.compareAndSet(true, false)) return
        val rec = this.recorder
        val file = this.outputFile
        val codec = this.codec
        val muxer = this.muxer
        val thread = this.readerThread
        this.recorder = null
        this.codec = null
        this.muxer = null
        this.outputFile = null
        this.readerThread = null
        startedAtMs = 0L
        try { thread?.join(300) } catch (_: InterruptedException) {}
        runCatching { rec?.stop() }
        runCatching { rec?.release() }
        runCatching { codec?.stop() }
        runCatching { codec?.release() }
        runCatching { if (muxerStarted) muxer?.stop() }
        runCatching { muxer?.release() }
        muxerStarted = false
        audioTrackIdx = -1
        file?.delete()
        Log.d(TAG, "Recording cancelled.")
    }

    fun release() {
        cancel()
    }

    companion object {
        private const val TAG = "VoiceRecorder"
        private const val MIME_AAC = MediaFormat.MIMETYPE_AUDIO_AAC
        private const val SAMPLE_RATE = 16_000
        private const val CHANNELS = 1
        /** 32 kbps reicht für Sprache, ergibt ~4 KB/s — ein 60-s-Take = ~240 KB. */
        private const val AAC_BITRATE = 32_000
        /** 1024 Samples = 64 ms bei 16 kHz. Trade-off zwischen VAD-Polling-Latenz
         *  und Codec-Overhead. AAC erwartet sowieso 1024-sample-Frames bei LC,
         *  also matched das perfekt. */
        private const val CHUNK_SHORTS = 1024
        private const val CHUNK_BYTES = CHUNK_SHORTS * 2
        private const val EOS_DRAIN_TIMEOUT_MS = 2_000L
    }
}
