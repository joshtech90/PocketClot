package de.smartzone.pocketclaude.data

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.preferencesDataStore
import android.util.Log
import okhttp3.ConnectionPool
import okhttp3.Interceptor
import okhttp3.OkHttpClient
import okhttp3.Response
import okhttp3.logging.HttpLoggingInterceptor
import java.io.IOException
import java.util.concurrent.TimeUnit
import javax.net.ssl.SSLException

private val Context.dataStore: DataStore<Preferences> by preferencesDataStore(name = "pocket_claude_prefs")

/**
 * Inhalte aus einem ACTION_SEND/SEND_MULTIPLE-Intent (Datei/Text an PocketClaude
 * geteilt). MainActivity legt sie hier ab, ChatScreen konsumiert sie einmalig.
 */
data class PendingShare(
    val uris: List<android.net.Uri> = emptyList(),
    val text: String? = null,
)

/**
 * Simple manual DI container — keeps things lightweight, no Hilt overhead.
 */
class AppContainer(context: Context) {

    /** Application-Context, für Service-Starts u.ä. außerhalb von Composables. */
    val appContext: Context = context.applicationContext

    /** Per Share-Intent hereingereichte Datei(en)/Text — von ChatScreen einmalig
     *  abgeholt (dann auf null gesetzt). Kein DataStore: lebt nur im Prozess. */
    @Volatile
    var pendingShare: PendingShare? = null

    /** Wunsch nach einem neuen Sprach-Chat (Assistenten-Taste, Kachel,
     *  Verknuepfung). Wer ihn per getAndSet(false) abholt, legt den Chat an;
     *  so entsteht auch bei Kaltstart und onNewIntent gleichzeitig nur einer. */
    val voiceChatRequested = java.util.concurrent.atomic.AtomicBoolean(false)

    /** Chat, in dem das Diktat beim ersten Anzeigen sofort starten soll.
     *  An die cid gebunden, damit kein anderer Chat den Start abgreift. */
    @Volatile
    var pendingVoiceCid: String? = null

    val settingsRepository: SettingsRepository = SettingsRepository(
        context.dataStore,
        // Eigene Datei fuer den Gedaechtnis-Schluessel, vom Backup ausgeschlossen
        context.getSharedPreferences("wissen_schluessel", Context.MODE_PRIVATE),
    )

    /** Merkt sich, welche gesperrten Chats in dieser Sitzung entsperrt wurden.
     *  Wird beim Wechsel in den Hintergrund geleert (Re-Lock). */
    val chatLock: ChatLockManager = ChatLockManager()

    // Connection-Pool — explizit konfiguriert, damit gestorbene TCP-Verbindungen
    // (Mobile-Network-Switch, Carrier-NAT-Timeout, lange Background-Phase)
    // schnell aus dem Pool fliegen statt beim nächsten Request einen "Stale
    // Connection"-Error zu provozieren.
    //
    // 60 Sek. KeepAlive ist konservativ — viele Carrier-NATs killen idle-TCP
    // nach 30-90 Sek. Mit 60s und retryOnConnectionFailure=true bekommen wir
    // einen automatischen Retry auf fresher Connection bei jedem Hick.
    private val connectionPool = ConnectionPool(
        maxIdleConnections = 5,
        keepAliveDuration = 60,
        timeUnit = TimeUnit.SECONDS,
    )

    // HTTP-Logging — auf BASIC, damit jeder Request/Response als eine Zeile in
    // logcat landet. Macht Diagnose von "Verbindung fehlgeschlagen"-Mysterien
    // wesentlich einfacher (vorher musste man im Server raten was die App
    // gerade versucht). BASIC zeigt URL + Method + Response-Code + Dauer —
    // keine Header oder Bodies, also auch keine Token-Leaks im Log.
    // BASIC loggt die volle URL. Backup-Passwort (`?password=`) und der
    // Vorlese-Token (`?token=`) stehen dort im Klartext, also vor dem Loggen
    // schwaerzen (wie der Server es in seinen Access-Logs macht).
    private val secretQuery = Regex("(?i)([?&](?:token|password|api_key|key)=)[^&\\s]+")
    private val loggingInterceptor = HttpLoggingInterceptor { message ->
        android.util.Log.i("OkHttp", message.replace(secretQuery, "$1***"))
    }.apply {
        level = HttpLoggingInterceptor.Level.BASIC
        // Vorsorglich, falls jemand den Level hochdreht: Schluessel nie ins Log
        redactHeader("Authorization")
        redactHeader("X-Wissen-Schluessel")
    }

    /**
     * Retry-on-transient-error Interceptor.
     *
     * OkHttp's eingebauter `retryOnConnectionFailure=true` deckt nur
     * connect/stale-Failures ab — NICHT SSL-Handshake-Exceptions. Genau die
     * traten aber bei Tailscale-Funnel auf, wenn ein TLS-Handshake mit dem
     * Tailscale-Edge sporadisch fehlschlägt (Mobile-Carrier-Hicks, TCP-MTU-
     * Probleme, transient Edge-Issues). Wir retrien bis zu 2× mit kurzem
     * Backoff, was solche Aussetzer für den User unsichtbar macht.
     *
     * Nicht retrien wir bei: User-Errors (4xx-Antworten kommen vom Server,
     * 5xx ebenso — die behandelt der Caller). Nur bei Network-Layer-Fehlern.
     */
    private val retryInterceptor = Interceptor { chain ->
        val request = chain.request()
        // Nur idempotente Methoden automatisch wiederholen. Ein blindes Retry
        // auf POST würde nicht-idempotente Mutationen (Nachricht senden, Login,
        // Passwort ändern, Backup-Import, Bild-Generierung) doppelt absetzen —
        // der Server hat keine Dedup/Idempotency-Keys, also entstünde z.B. eine
        // doppelte User-Nachricht + zweite Generierung.
        if (request.method !in setOf("GET", "HEAD", "PUT", "DELETE")) {
            return@Interceptor chain.proceed(request)
        }
        var lastError: IOException? = null
        for (attempt in 0..2) {
            try {
                val response: Response = chain.proceed(request)
                if (attempt > 0) {
                    Log.i("PocketClaude", "Retry #$attempt erfolgreich: ${request.url}")
                }
                return@Interceptor response
            } catch (e: SSLException) {
                lastError = e
                Log.w("PocketClaude", "SSL-Fehler Versuch ${attempt + 1}/3: ${e.message} — Retry…")
            } catch (e: IOException) {
                lastError = e
                Log.w("PocketClaude", "I/O-Fehler Versuch ${attempt + 1}/3: ${e.message} — Retry…")
            }
            // Exponential-Backoff: 200 ms, 600 ms — kurz genug damit der User
            // es kaum merkt, lang genug damit Carrier-NAT-Restorations greifen.
            if (attempt < 2) Thread.sleep(200L * (1L shl attempt))
        }
        throw lastError!!
    }

    // Zwei OkHttp-Clients aus einem gemeinsamen ConnectionPool: einer mit
    // realem Read-Timeout (für normale REST-Calls), einer ohne (für SSE-
    // Streams, deren Read-Phase beliebig lange dauern darf). Vorher hatten
    // ALLE Requests `readTimeout=0`, was bei einem stehengebliebenen Backend
    // dazu führt, dass z.B. ein hängender /health-Call auf ewig blockt
    // statt nach 30s mit Timeout-Fehler abzubrechen.
    private val baseClient: OkHttpClient = OkHttpClient.Builder()
        .connectionPool(connectionPool)
        .connectTimeout(20, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .writeTimeout(30, TimeUnit.SECONDS)
        // retryOnConnectionFailure=true (default) sorgt dafür, dass OkHttp bei
        // einer toten Pool-Connection automatisch ein neues TCP aufbaut statt
        // einen IOException-Stale-Fehler nach oben zu reichen. Explizit
        // setzen, damit niemand das versehentlich auf false dreht.
        .retryOnConnectionFailure(true)
        // Retry-Interceptor MUSS vor Logging stehen, damit Retries auch geloggt
        // werden (sonst sieht man im Log nur den finalen Erfolg/Fehler).
        .addInterceptor(retryInterceptor)
        .addInterceptor(loggingInterceptor)
        .build()

    /** Für reguläre REST-Calls (GET/POST/PUT/PATCH/DELETE) — hat Read-Timeout. */
    val httpClient: OkHttpClient = baseClient

    /** Für SSE-Streams — Read-Timeout deaktiviert, damit der Stream-Tail nicht
     *  während längerer Thinking-Pausen abbricht. */
    val streamingHttpClient: OkHttpClient = baseClient.newBuilder()
        .readTimeout(0, TimeUnit.MILLISECONDS)
        .build()

    val apiClient: ApiClient = ApiClient(httpClient, streamingHttpClient, settingsRepository)

    val chatRepository: ChatRepository = ChatRepository(apiClient, context)

    /** Lebt so lange wie der Prozess; Fehler einzelner Abgleiche bleiben lokal. */
    private val appScope = kotlinx.coroutines.CoroutineScope(
        kotlinx.coroutines.SupervisorJob() + kotlinx.coroutines.Dispatchers.IO,
    )

    /** Gleicht die Oberflaechen-Einstellungen mit dem Server ab (App = Web). */
    val settingsSync: SettingsSync = SettingsSync(settingsRepository, apiClient, appScope)

    val audioController: AudioController = AudioController(context, streamingHttpClient)

    /** Voice-Input (Mic → Groq Whisper). Eine globale Instanz reicht — es
     *  läuft sowieso nur eine Aufnahme zur Zeit, und der MediaRecorder wird
     *  beim Stop sauber freigegeben. Stateful zwischen Activities (Auto-Modus). */
    val voiceRecorder: de.smartzone.pocketclaude.audio.VoiceRecorder =
        de.smartzone.pocketclaude.audio.VoiceRecorder(appContext)
}
