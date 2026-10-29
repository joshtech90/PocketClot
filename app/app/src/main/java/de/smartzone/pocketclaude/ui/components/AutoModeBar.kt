package de.smartzone.pocketclaude.ui.components

import androidx.compose.animation.Crossfade
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.ime
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.union
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Slider
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import de.smartzone.pocketclaude.R
import de.smartzone.pocketclaude.ui.theme.PocketIconSize
import de.smartzone.pocketclaude.ui.theme.PocketIcons

/**
 * Bildschirmfüllende Voice-Bar für den Auto-Modus. Ersetzt im Auto-Mode die
 * normale InputBar — Tastatur ist ohnehin nicht nötig (Caller blendet sie
 * aus), stattdessen prominenter Mic-Tap-Bereich.
 *
 * Layout (oben → unten):
 *   1) Status-Text (groß, fett, je nach Phase: Höre zu / Claude denkt / Liest vor / …)
 *   2) Hinweis-Text (klein, je nach Phase: Tippe zum Senden / Tippe zum Unterbrechen)
 *   3) PocketVoiceOrb: Klumpen im Ring (120 dp, seit 22.10.2026 statt des
 *      Mikrofon-Knopfs, gleiche Bedienung, Stille-Countdown als Bogen am Ring).
 *      Seit 28.10.2026 die einzige Bedienflaeche: waehrend des Vorlesens
 *      unterbricht ein Tippen, der eigene Knopf "Vorlesen abbrechen" ist weg.
 *   4) Exit-Button "Auto-Modus beenden"
 *
 * Status-Inferenz:
 *  - `voiceState=Recording` → Listening (User redet)
 *  - `voiceState=Transcribing` → Transcribing
 *  - `ttsPlaying` → Speaking
 *  - `ttsLoading` → Loading audio
 *  - `isStreaming` → Thinking
 *  - sonst → Idle (kurzer Settle-Moment zwischen Phasen)
 *
 * Hoehe ≈ 250 dp + NavBar-Inset (vor dem 27.10.2026 rund 330 dp). Wenn die
 * IME gerade noch ausgeht, zappelt die Bar einmal hoch, was tolerabel ist
 * (Auto-Mode-Start blendet die Tastatur direkt aus).
 */
@Composable
fun AutoModeBar(
    voiceState: de.smartzone.pocketclaude.ui.chat.VoiceState,
    isStreaming: Boolean,
    ttsLoading: Boolean,
    ttsPlaying: Boolean,
    ttsSpeed: Float,
    ttsSpeedIsOverride: Boolean,
    onTtsSpeedChange: (Float) -> Unit,
    onTtsSpeedReset: () -> Unit,
    autoSendEnabled: Boolean,
    autoSendSilenceMs: Long,
    silenceProgressMs: Long,
    onMicTap: () -> Unit,
    onMicCancel: () -> Unit,
    onExitAutoMode: () -> Unit,
    /** Tippen auf den Klumpen waehrend des Vorlesens: unterbrechen, der Loop
     *  hoert danach sofort wieder zu. */
    onStopSpeaking: () -> Unit,
    onAutoSendChange: (Boolean) -> Unit,
    modifier: Modifier = Modifier,
) {
    val phase = when {
        voiceState == de.smartzone.pocketclaude.ui.chat.VoiceState.Recording -> AutoPhase.Listening
        voiceState == de.smartzone.pocketclaude.ui.chat.VoiceState.Transcribing -> AutoPhase.Transcribing
        // Vorlesen vor "denkt": seit dem 27.10.2026 beginnt das Vorlesen schon,
        // waehrend die Antwort noch geschrieben wird.
        ttsPlaying -> AutoPhase.Speaking
        ttsLoading -> AutoPhase.LoadingAudio
        isStreaming -> AutoPhase.Thinking
        else -> AutoPhase.Idle
    }

    val statusRes = when (phase) {
        AutoPhase.Listening -> R.string.auto_mode_status_listening
        AutoPhase.Transcribing -> R.string.auto_mode_status_transcribing
        AutoPhase.Thinking -> R.string.auto_mode_status_thinking
        AutoPhase.LoadingAudio -> R.string.auto_mode_status_loading_audio
        AutoPhase.Speaking -> R.string.auto_mode_status_speaking
        AutoPhase.Idle -> R.string.auto_mode_status_idle
    }
    // Countdown wird AUSSCHLIESSLICH visuell als Bogen auf dem Ring gerendert
    // (siehe PocketVoiceOrb.progressFraction). Der Status-Text bleibt konstant
    // auf „Höre zu" — vermeidet das nervige Hin-Her-Springen zwischen
    // „Höre zu" und „Senden in Ns".
    val ringFraction = if (
        phase == AutoPhase.Listening && autoSendEnabled && autoSendSilenceMs > 0L
    ) (silenceProgressMs.toFloat() / autoSendSilenceMs.toFloat()).coerceIn(0f, 1f)
    else 0f

    val hintRes = when (phase) {
        AutoPhase.Listening -> if (autoSendEnabled) R.string.auto_mode_hint_listening_auto
                               else R.string.auto_mode_hint_listening
        AutoPhase.LoadingAudio, AutoPhase.Speaking -> R.string.auto_mode_hint_speaking
        // Während die KI mitschreibt/denkt und im kurzen Übergang (Idle): Tippen
        // tut nichts; Hinweis-Zeile bleibt leer, damit nicht der Eindruck
        // entsteht, der Tap würde was tun.
        else -> null
    }

    val orbPhase = when (phase) {
        AutoPhase.Listening -> VoiceOrbPhase.Listening
        AutoPhase.Transcribing, AutoPhase.Thinking -> VoiceOrbPhase.Working
        // Laden zaehlt schon als Vorlesen: gleiche Optik, gleiches Unterbrechen.
        AutoPhase.LoadingAudio, AutoPhase.Speaking -> VoiceOrbPhase.Speaking
        AutoPhase.Idle -> VoiceOrbPhase.Idle
    }
    val interrupts = orbPhase == VoiceOrbPhase.Speaking
    // Der Klumpen sendet beim Zuhoeren und unterbricht beim Vorlesen, sonst
    // nimmt er kein Tippen an. Aufnahmen startet im Sprachgespraech nur der
    // Loop: ein Tipp im Uebergang (Idle) oder waehrend die KI denkt startete
    // frueher eine Aufnahme an ihm vorbei, und die sendete dann trotz
    // Auto-Senden nie von selbst (Sol 28.10.2026).
    val orbEnabled = interrupts ||
        voiceState == de.smartzone.pocketclaude.ui.chat.VoiceState.Recording

    // Vom Chat abgesetzt (Joscha 27.10.2026): eigene, etwas dunklere Flaeche
    // mit einer Linie oben, statt nahtlos in den Verlauf ueberzugehen. Die
    // Abstaende sind bewusst knapp, das Panel soll vom Chat wenig verdecken.
    Column(
        modifier = modifier
            .fillMaxWidth()
            .background(MaterialTheme.colorScheme.surfaceContainerHigh),
    ) {
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .windowInsetsPadding(WindowInsets.ime.union(WindowInsets.navigationBars))
                .padding(start = 16.dp, end = 16.dp, top = 12.dp, bottom = 4.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            // Status-Crossfade verhindert Flacker beim Phase-Wechsel zwischen
            // Höre zu / Claude denkt / Liest vor. Während Auto-Send-Countdown
            // bleibt der Text auf „Höre zu" stehen — der Countdown lebt visuell
            // als Ring um den Mic-Button.
            Crossfade(targetState = statusRes, label = "auto-status") { res ->
                Text(
                    text = stringResource(res),
                    style = MaterialTheme.typography.titleLarge,
                    color = MaterialTheme.colorScheme.onSurface,
                    textAlign = TextAlign.Center,
                )
            }
            // Hinweis-Zeile — feste Höhe damit nichts wackelt
            Box(modifier = Modifier.heightIn(min = 20.dp)) {
                if (hintRes != null) {
                    Text(
                        text = stringResource(hintRes),
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        textAlign = TextAlign.Center,
                    )
                }
            }

            // Der Ring liegt bei 80 % der Flaeche, der Rand darum bleibt fuer
            // die Welle frei und wirkt schon wie Abstand.
            PocketVoiceOrb(
                phase = orbPhase,
                recording = voiceState == de.smartzone.pocketclaude.ui.chat.VoiceState.Recording,
                statusLabel = stringResource(statusRes),
                onTap = if (interrupts) onStopSpeaking else onMicTap,
                onCancel = onMicCancel,
                enabled = orbEnabled,
                size = 120.dp,
                progressFraction = ringFraction,
            )

            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Text(stringResource(R.string.settings_speed_label), style = MaterialTheme.typography.bodyMedium)
                Slider(
                    value = ttsSpeed,
                    onValueChange = onTtsSpeedChange,
                    valueRange = 0.25f..2.0f,
                    steps = 34,
                    modifier = Modifier.weight(1f),
                )
                Text(String.format(java.util.Locale.getDefault(), "%.2f×", ttsSpeed),
                    style = MaterialTheme.typography.bodyMedium)
            }
            TextButton(onClick = onTtsSpeedReset, enabled = ttsSpeedIsOverride) {
                Text(stringResource(R.string.voice_speed_default))
            }

            // Auto-Send-Toggle: dezent unter dem Mic, damit der User entscheiden
            // kann, ob die Aufnahme nach Stille selbst aufhört oder erst durch
            // Mic-Tap.
            Row(
                modifier = Modifier.padding(horizontal = 4.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Text(
                    stringResource(R.string.auto_mode_auto_send_label),
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Switch(
                    checked = autoSendEnabled,
                    onCheckedChange = onAutoSendChange,
                )
            }

            // Exit-Button: dezent, aber direkt erreichbar.
            TextButton(
                onClick = onExitAutoMode,
                contentPadding = PaddingValues(horizontal = 16.dp, vertical = 4.dp),
            ) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    Icon(
                        PocketIcons.Close,
                        contentDescription = null,
                        modifier = Modifier.size(PocketIconSize.Small),
                    )
                    Text(stringResource(R.string.auto_mode_exit))
                }
            }
        }
    }
}

private enum class AutoPhase {
    Listening, Transcribing, Thinking, LoadingAudio, Speaking, Idle,
}
