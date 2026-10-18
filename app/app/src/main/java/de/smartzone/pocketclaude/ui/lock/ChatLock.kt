package de.smartzone.pocketclaude.ui.lock

import android.content.Context
import android.content.ContextWrapper
import androidx.biometric.BiometricManager
import androidx.biometric.BiometricPrompt
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.core.content.ContextCompat
import androidx.fragment.app.FragmentActivity
import de.smartzone.pocketclaude.R
import de.smartzone.pocketclaude.data.ChatLockVerifyResponse
import de.smartzone.pocketclaude.ui.components.PocketIconButton
import de.smartzone.pocketclaude.ui.theme.PocketTheme
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import de.smartzone.pocketclaude.ui.theme.PocketIconSize
import de.smartzone.pocketclaude.ui.theme.PocketRadius
import de.smartzone.pocketclaude.ui.theme.PocketIcons

const val CHAT_LOCK_PIN_LENGTH = 5

/** Findet die umschließende FragmentActivity (für BiometricPrompt). */
fun Context.findFragmentActivity(): FragmentActivity? {
    var ctx: Context? = this
    while (ctx is ContextWrapper) {
        if (ctx is FragmentActivity) return ctx
        ctx = ctx.baseContext
    }
    return null
}

/** Kann das Gerät überhaupt Biometrie (Fingerabdruck/Gesicht schwach+)? */
fun isBiometricAvailable(context: Context): Boolean {
    return BiometricManager.from(context)
        .canAuthenticate(BiometricManager.Authenticators.BIOMETRIC_WEAK) ==
        BiometricManager.BIOMETRIC_SUCCESS
}

/** Zeigt den System-Biometrie-Dialog. onError bei Abbruch/Hardware-Fehler. */
fun promptBiometric(
    activity: FragmentActivity,
    title: String,
    subtitle: String,
    negativeText: String,
    onSuccess: () -> Unit,
    onError: () -> Unit,
) {
    val executor = ContextCompat.getMainExecutor(activity)
    val prompt = BiometricPrompt(
        activity, executor,
        object : BiometricPrompt.AuthenticationCallback() {
            override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) =
                onSuccess()

            override fun onAuthenticationError(errorCode: Int, errString: CharSequence) =
                onError()
            // onAuthenticationFailed = einzelner Fehlversuch → Dialog bleibt offen, ignorieren.
        },
    )
    val info = BiometricPrompt.PromptInfo.Builder()
        .setTitle(title)
        .setSubtitle(subtitle)
        .setNegativeButtonText(negativeText)
        .setAllowedAuthenticators(BiometricManager.Authenticators.BIOMETRIC_WEAK)
        .build()
    prompt.authenticate(info)
}

/**
 * Vollflächige Sperr-Ansicht — von ChatScreen gezeigt, solange ein gesperrter
 * Chat in dieser Sitzung noch nicht entsperrt wurde. Biometrie (falls aktiv +
 * verfügbar) wird beim Erscheinen automatisch angeboten; PIN-Eingabe ist
 * jederzeit als Fallback da.
 */
@Composable
fun ChatLockGate(
    chatTitle: String,
    biometricEnabled: Boolean,
    verifyPin: suspend (String) -> ChatLockVerifyResponse,
    onUnlocked: () -> Unit,
    modifier: Modifier = Modifier,
    // Öffnet das Seiten-Menü (Chat-Liste). Wird als Hamburger-Button oben in der
    // Sperr-Ansicht gezeigt, damit man bei geschlossener App und unbekanntem PIN
    // trotzdem zu einem ANDEREN Chat wechseln kann statt komplett festzustecken.
    onOpenMenu: (() -> Unit)? = null,
    menuContentDescription: String? = null,
) {
    val context = LocalContext.current
    val activity = remember { context.findFragmentActivity() }
    val biometricUsable = remember { biometricEnabled && isBiometricAvailable(context) }
    val scope = rememberCoroutineScope()
    val keyboardController = LocalSoftwareKeyboardController.current
    val focusManager = LocalFocusManager.current

    // Sobald die Sperr-Ansicht erscheint: Fokus vom (darunter liegenden) Chat-
    // Eingabefeld nehmen und Software-Tastatur schließen. Sonst „klappt die
    // Tastatur aus", obwohl zum Entsperren nur der Fingerabdruck bzw. das
    // In-App-Numpad genutzt wird — besonders störend beim Öffnen aus dem
    // Gerät-Sperrbildschirm.
    LaunchedEffect(Unit) {
        focusManager.clearFocus(force = true)
        keyboardController?.hide()
    }

    var pin by remember { mutableStateOf("") }
    var wrong by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var cooldown by remember { mutableStateOf(0) }
    var busy by remember { mutableStateOf(false) }

    val biometricTitle = stringResource(R.string.chat_lock_unlock_chat)
    val negativeText = stringResource(R.string.chat_lock_use_pin)

    fun triggerBiometric() {
        val act = activity ?: return
        promptBiometric(
            act, biometricTitle, chatTitle, negativeText,
            onSuccess = onUnlocked,
            // Weggeklickt/abgebrochen → das In-App-Numpad ist eh sichtbar.
            onError = { },
        )
    }

    // Cooldown-Countdown nach zu vielen Fehlversuchen.
    LaunchedEffect(cooldown) {
        if (cooldown > 0) {
            delay(1000)
            cooldown -= 1
        }
    }

    // Beim Erscheinen einmal Fingerabdruck anbieten (falls nutzbar). Egal ob
    // Erfolg oder Abbruch — das Numpad steht immer bereit.
    LaunchedEffect(Unit) {
        if (biometricUsable) triggerBiometric()
    }

    fun submit(candidate: String) {
        if (busy || cooldown > 0) return
        busy = true
        error = null
        wrong = false
        scope.launch {
            val res = runCatching { verifyPin(candidate) }.getOrElse {
                busy = false
                error = it.message
                pin = ""
                return@launch
            }
            busy = false
            when {
                res.ok -> onUnlocked()
                res.retryAfterSeconds > 0 -> {
                    cooldown = res.retryAfterSeconds
                    wrong = false
                    pin = ""
                }
                else -> {
                    wrong = true
                    pin = ""
                }
            }
        }
    }

    Box(
        modifier = modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.background)
            // Alle Gesten schlucken, die nicht von den Kind-Composables (PIN-Boxen,
            // Fingerabdruck-Button, Hamburger) verbraucht werden — sonst würden
            // Taps/Scrolls durch die Sperr-Ansicht hindurch auf den verdeckten
            // Chat wirken.
            .pointerInput(Unit) {
                awaitPointerEventScope {
                    while (true) {
                        awaitPointerEvent().changes.forEach { it.consume() }
                    }
                }
            },
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(32.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center,
        ) {
            Box(
                // Hero-Kachel: Symbol halb so gross wie die Flaeche, wie bei
                // den runden Knoepfen in der Kopfzeile.
                modifier = Modifier
                    .size(96.dp)
                    .background(
                        MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.72f),
                        RoundedCornerShape(PocketRadius.Large),
                    )
                    .border(
                        1.dp,
                        MaterialTheme.colorScheme.primary.copy(alpha = 0.22f),
                        RoundedCornerShape(PocketRadius.Large),
                    ),
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    PocketIcons.Lock,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.primary,
                    modifier = Modifier.size(PocketIconSize.Hero),
                )
            }
            Spacer(Modifier.height(24.dp))
            Text(
                stringResource(R.string.chat_lock_locked_heading),
                style = MaterialTheme.typography.headlineSmall,
            )
            Spacer(Modifier.height(8.dp))
            val isProblem = cooldown > 0 || wrong || error != null
            Text(
                when {
                    cooldown > 0 -> stringResource(R.string.chat_lock_locked_out, cooldown)
                    wrong -> stringResource(R.string.chat_lock_wrong_pin)
                    error != null -> error!!
                    else -> stringResource(R.string.chat_lock_enter_pin)
                },
                style = MaterialTheme.typography.bodyMedium,
                color = if (isProblem) MaterialTheme.colorScheme.error
                        else MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.height(24.dp))
            PinDots(value = pin, isError = wrong)
            Spacer(Modifier.height(32.dp))
            PinPad(
                enabled = !busy && cooldown == 0,
                onDigit = { d ->
                    if (pin.length < CHAT_LOCK_PIN_LENGTH) {
                        wrong = false; error = null
                        pin += d
                        if (pin.length == CHAT_LOCK_PIN_LENGTH) submit(pin)
                    }
                },
                onBackspace = { if (pin.isNotEmpty()) pin = pin.dropLast(1) },
            )
            if (biometricUsable) {
                Spacer(Modifier.height(24.dp))
                TextButton(onClick = { triggerBiometric() }) {
                    Icon(PocketIcons.Fingerprint, contentDescription = null, modifier = Modifier.size(PocketIconSize.Small))
                    Spacer(Modifier.width(8.dp))
                    Text(stringResource(R.string.chat_lock_use_fingerprint))
                }
            }
        }

        // Hamburger oben links: öffnet die Chat-Liste, damit man aus einem
        // gesperrten Chat (dessen PIN man evtl. nicht kennt) trotzdem zu einem
        // anderen Chat wechseln kann. Ohne diesen Ausweg steckt man bei
        // geschlossener App komplett fest.
        if (onOpenMenu != null) {
            PocketIconButton(
                icon = PocketIcons.Menu,
                contentDescription = menuContentDescription,
                onClick = onOpenMenu,
                modifier = Modifier
                    .align(Alignment.TopStart)
                    .statusBarsPadding()
                    .padding(8.dp),
            )
        }
    }
}

/**
 * PIN-Bestätigungs-Dialog — z.B. um die Sperre eines Chats wieder zu entfernen.
 * Reine PIN-Prüfung (kein Biometrie-Kurzschluss, weil hier eine bewusste
 * Bestätigung gewollt ist).
 */
@Composable
fun PinVerifyDialog(
    title: String,
    message: String,
    verifyPin: suspend (String) -> ChatLockVerifyResponse,
    onVerified: () -> Unit,
    onDismiss: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    var pin by remember { mutableStateOf("") }
    var wrong by remember { mutableStateOf(false) }
    var cooldown by remember { mutableStateOf(0) }
    var busy by remember { mutableStateOf(false) }

    LaunchedEffect(cooldown) {
        if (cooldown > 0) { delay(1000); cooldown -= 1 }
    }

    fun submit(candidate: String) {
        if (busy || cooldown > 0) return
        busy = true; wrong = false
        scope.launch {
            val res = runCatching { verifyPin(candidate) }.getOrNull()
            busy = false
            when {
                res == null -> { wrong = true; pin = "" }
                res.ok -> onVerified()
                res.retryAfterSeconds > 0 -> { cooldown = res.retryAfterSeconds; pin = "" }
                else -> { wrong = true; pin = "" }
            }
        }
    }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = {
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Text(message, style = MaterialTheme.typography.bodyMedium)
                Spacer(Modifier.height(16.dp))
                PinDots(value = pin, isError = wrong)
                Spacer(Modifier.height(20.dp))
                PinPad(
                    enabled = !busy && cooldown == 0,
                    onDigit = { d ->
                        if (pin.length < CHAT_LOCK_PIN_LENGTH) {
                            wrong = false
                            pin += d
                            if (pin.length == CHAT_LOCK_PIN_LENGTH) submit(pin)
                        }
                    },
                    onBackspace = { if (pin.isNotEmpty()) pin = pin.dropLast(1) },
                )
                if (cooldown > 0) {
                    Spacer(Modifier.height(10.dp))
                    Text(
                        stringResource(R.string.chat_lock_locked_out, cooldown),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.error,
                    )
                } else if (wrong) {
                    Spacer(Modifier.height(10.dp))
                    Text(
                        stringResource(R.string.chat_lock_wrong_pin),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.error,
                    )
                }
            }
        },
        confirmButton = {},
        dismissButton = {
            TextButton(onClick = onDismiss) {
                Text(stringResource(R.string.action_cancel))
            }
        },
    )
}

/** Fünf Kästchen, die den aktuellen PIN-Fortschritt zeigen (rein visuell). */
@Composable
fun PinDots(value: String, isError: Boolean, length: Int = CHAT_LOCK_PIN_LENGTH) {
    Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        repeat(length) { i ->
            val filled = i < value.length
            val border = when {
                isError -> MaterialTheme.colorScheme.error
                i == value.length -> MaterialTheme.colorScheme.primary
                else -> MaterialTheme.colorScheme.outline
            }
            Box(
                modifier = Modifier
                    .size(44.dp)
                    .border(1.5.dp, border, RoundedCornerShape(PocketRadius.Small)),
                contentAlignment = Alignment.Center,
            ) {
                if (filled) {
                    Box(
                        modifier = Modifier
                            .size(12.dp)
                            .background(MaterialTheme.colorScheme.onSurface, CircleShape),
                    )
                }
            }
        }
    }
}

/**
 * Einfaches In-App-Numpad (1-9, 0, Löschen). Bewusst KEINE System-Tastatur —
 * die ist bei der vollflächigen Sperr-Ansicht + Fingerabdruck-Dialog auf manchen
 * Geräten nicht zuverlässig aufgegangen. Das Numpad funktioniert immer.
 */
@Composable
fun PinPad(
    enabled: Boolean,
    onDigit: (Char) -> Unit,
    onBackspace: () -> Unit,
) {
    val rows = listOf(
        listOf("1", "2", "3"),
        listOf("4", "5", "6"),
        listOf("7", "8", "9"),
        listOf("", "0", "⌫"),
    )
    Column(
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        for (row in rows) {
            Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                for (key in row) {
                    when (key) {
                        "" -> Spacer(Modifier.size(64.dp))
                        "⌫" -> PinKey(enabled = enabled, onClick = onBackspace) {
                            Icon(
                                PocketIcons.Backspace,
                                contentDescription = stringResource(R.string.action_delete),
                                tint = MaterialTheme.colorScheme.onSurface,
                            )
                        }
                        else -> PinKey(enabled = enabled, onClick = { onDigit(key[0]) }) {
                            Text(
                                key,
                                style = MaterialTheme.typography.headlineSmall,
                                color = MaterialTheme.colorScheme.onSurface,
                            )
                        }
                    }
                }
            }
        }
    }
}

/** Eine runde Numpad-Taste. */
@Composable
private fun PinKey(
    enabled: Boolean,
    onClick: () -> Unit,
    content: @Composable () -> Unit,
) {
    Surface(
        onClick = onClick,
        enabled = enabled,
        // Runde Tasten wie auf jedem Telefon-Ziffernblock.
        shape = CircleShape,
        color = MaterialTheme.colorScheme.surface.copy(alpha = 0.88f),
        border = androidx.compose.foundation.BorderStroke(1.dp, PocketTheme.colors.outlineSoft),
        modifier = Modifier.size(64.dp),
    ) {
        Box(contentAlignment = Alignment.Center) { content() }
    }
}
