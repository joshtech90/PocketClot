package de.smartzone.pocketclaude

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.activity.compose.setContent
import androidx.fragment.app.FragmentActivity
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.core.content.ContextCompat
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import de.smartzone.pocketclaude.data.LocalePrefs
import de.smartzone.pocketclaude.service.NotificationHelper
import android.net.Uri
import de.smartzone.pocketclaude.data.PendingShare
import de.smartzone.pocketclaude.ui.PocketNav
import de.smartzone.pocketclaude.ui.theme.PocketClaudeTheme

class MainActivity : FragmentActivity() {

    override fun attachBaseContext(newBase: Context) {
        super.attachBaseContext(LocalePrefs.wrap(newBase))
    }

    /** Wird vom Composable beobachtet — wenn das Intent eine cid trägt, zeigt
     *  die Navigation direkt diesen Chat statt einen frischen anzulegen. */
    private val initialChatCid = mutableStateOf<String?>(null)

    /** Erhöht sich bei jedem Share-Intent. Damit schwenkt die Navigation auch
     *  bei bereits offener App auf einen frischen Chat mit dem geteilten Inhalt. */
    private val shareNonce = mutableStateOf(0)

    /** Erhöht sich bei jedem Wunsch nach einem neuen Sprach-Chat bei bereits
     *  offener App (Kaltstart läuft über den Launch-Screen). */
    private val voiceNonce = mutableStateOf(0)

    private val requestNotifPermission = registerForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { /* Wir machen weiter, egal ob granted oder nicht. */ }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        initialChatCid.value = extractCid(intent)
        handleShareIntent(intent, bumpNonce = false)
        // Nur beim echten Start: nach Rotation o. ä. steckt dasselbe Intent
        // noch in der Activity und würde sonst einen zweiten Chat anlegen.
        if (savedInstanceState == null) handleVoiceIntent(intent, bumpNonce = false)
        // Permission-Prompt nur beim ECHTEN ersten Start, nicht bei jedem
        // Configuration-Change (Rotation, Dark-Mode-Switch, …). Sonst poppt
        // der Dialog jedes Mal neu auf, auch wenn der User schon entschieden hat.
        if (savedInstanceState == null) {
            maybeAskNotificationPermission()
        }
        setContent {
            PocketApp(
                initialChatCid = initialChatCid.value,
                shareNonce = shareNonce.value,
                voiceNonce = voiceNonce.value,
            )
        }
    }

    private fun maybeAskNotificationPermission() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            val granted = ContextCompat.checkSelfPermission(
                this,
                Manifest.permission.POST_NOTIFICATIONS,
            ) == PackageManager.PERMISSION_GRANTED
            if (!granted) {
                requestNotifPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        // App war bereits offen und wurde via Notification erneut gestartet —
        // wir aktualisieren das Composable-State, damit PocketNav umschwenkt.
        val cid = extractCid(intent)
        if (cid != null) initialChatCid.value = cid
        handleShareIntent(intent, bumpNonce = true)
        handleVoiceIntent(intent, bumpNonce = true)
    }

    /** Neuer Sprach-Chat (siehe [VoiceLaunch]): Wunsch im Container vormerken,
     *  die Navigation legt den Chat an und startet dort das Diktat. */
    private fun handleVoiceIntent(intent: Intent?, bumpNonce: Boolean) {
        if (!VoiceLaunch.isRequest(intent)) return
        val fresh = (application as PocketClaudeApp).container.voiceChat.request()
        // Erledigt: wird die Activity später neu aufgebaut, soll dasselbe
        // Intent keinen weiteren Chat öffnen.
        setIntent(Intent(intent).setAction(Intent.ACTION_MAIN))
        if (fresh && bumpNonce) voiceNonce.value += 1
    }

    private fun extractCid(intent: Intent?): String? {
        return intent?.getStringExtra(NotificationHelper.EXTRA_OPEN_CID)
    }

    /**
     * Verarbeitet ACTION_SEND / ACTION_SEND_MULTIPLE (PocketClaude als Share-Ziel):
     * extrahiert Datei-URIs bzw. Text und legt sie im Container ab. ChatScreen holt
     * sie beim Öffnen ab und hängt sie als Anhänge an. Bei bereits offener App
     * (`bumpNonce = true`) wird zusätzlich die Navigation getriggert.
     */
    private fun handleShareIntent(intent: Intent?, bumpNonce: Boolean) {
        if (intent == null) return
        val container = (application as PocketClaudeApp).container
        val payload: PendingShare? = when (intent.action) {
            Intent.ACTION_SEND -> {
                val uri: Uri? =
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU)
                        intent.getParcelableExtra(Intent.EXTRA_STREAM, Uri::class.java)
                    else @Suppress("DEPRECATION") intent.getParcelableExtra(Intent.EXTRA_STREAM)
                val text = intent.getStringExtra(Intent.EXTRA_TEXT)
                when {
                    uri != null -> PendingShare(uris = listOf(uri))
                    !text.isNullOrBlank() -> PendingShare(text = text)
                    else -> null
                }
            }
            Intent.ACTION_SEND_MULTIPLE -> {
                val uris: List<Uri>? =
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU)
                        intent.getParcelableArrayListExtra(Intent.EXTRA_STREAM, Uri::class.java)
                    else @Suppress("DEPRECATION") intent.getParcelableArrayListExtra(Intent.EXTRA_STREAM)
                if (!uris.isNullOrEmpty()) PendingShare(uris = uris.toList()) else null
            }
            else -> null
        } ?: return

        container.pendingShare = payload
        if (bumpNonce) shareNonce.value += 1
    }
}

@Composable
private fun PocketApp(initialChatCid: String?, shareNonce: Int, voiceNonce: Int) {
    val context = LocalContext.current
    val container = remember {
        (context.applicationContext as PocketClaudeApp).container
    }
    val settings by container.settingsRepository.settingsFlow
        .collectAsState(initial = de.smartzone.pocketclaude.data.AppSettings())

    PocketClaudeTheme(
        mode = settings.themeMode,
        paletteLight = de.smartzone.pocketclaude.ui.theme.PocketPalette
            .fromId(settings.paletteIdLight, de.smartzone.pocketclaude.ui.theme.PocketPalette.NORDIC_BLUE),
        paletteDark = de.smartzone.pocketclaude.ui.theme.PocketPalette
            .fromId(settings.paletteIdDark),
    ) {
        Surface(
            modifier = Modifier
                .fillMaxSize()
                .background(MaterialTheme.colorScheme.background),
            color = MaterialTheme.colorScheme.background,
        ) {
            PocketNav(
                container = container,
                initialChatCid = initialChatCid,
                shareNonce = shareNonce,
                voiceNonce = voiceNonce,
            )
        }
    }
}
