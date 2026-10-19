package de.smartzone.pocketclaude.ui.components

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.Crossfade
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.ime
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.union
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
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
 *   2) Hinweis-Text (klein, je nach Phase: Tippe zum Senden / Tippe zum Sprechen)
 *   3) Großer MicButton (140 dp Outer, leicht treffbar mit Daumen)
 *   4) Exit-Button "Auto-Modus beenden"
 *
 * Status-Inferenz:
 *  - `voiceState=Recording` → Listening (User redet)
 *  - `voiceState=Transcribing` → Transcribing
 *  - `isStreaming` → Thinking
 *  - `ttsLoading` → Loading audio
 *  - `ttsPlaying` → Speaking
 *  - sonst → Idle (kurzer Settle-Moment zwischen Phasen)
 *
 * Höhe ≈ 280 dp + IME/NavBar-Inset — deckt damit grob die Höhe der virtuellen
 * Tastatur ab. Wenn die IME gerade noch ausgeht, zappelt die Bar einmal hoch,
 * was tolerabel ist (Auto-Mode-Start blendet die Tastatur direkt aus).
 */
@Composable
fun AutoModeBar(
    voiceState: de.smartzone.pocketclaude.ui.chat.VoiceState,
    isStreaming: Boolean,
    ttsLoading: Boolean,
    ttsPlaying: Boolean,
    voiceEnabled: Boolean,
    autoSendEnabled: Boolean,
    autoSendSilenceMs: Long,
    silenceProgressMs: Long,
    onMicTap: () -> Unit,
    onMicCancel: () -> Unit,
    onExitAutoMode: () -> Unit,
    /** Bricht das laufende Vorlesen ab; der Loop nimmt danach sofort wieder auf. */
    onStopSpeaking: () -> Unit,
    onAutoSendChange: (Boolean) -> Unit,
    modifier: Modifier = Modifier,
) {
    val phase = when {
        voiceState == de.smartzone.pocketclaude.ui.chat.VoiceState.Recording -> AutoPhase.Listening
        voiceState == de.smartzone.pocketclaude.ui.chat.VoiceState.Transcribing -> AutoPhase.Transcribing
        isStreaming -> AutoPhase.Thinking
        ttsLoading -> AutoPhase.LoadingAudio
        ttsPlaying -> AutoPhase.Speaking
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
    // Countdown wird AUSSCHLIESSLICH visuell als Ring um den Mic gerendert
    // (siehe MicButton.progressFraction). Der Status-Text bleibt konstant
    // auf „Höre zu" — vermeidet das nervige Hin-Her-Springen zwischen
    // „Höre zu" und „Senden in Ns".
    val ringFraction = if (
        phase == AutoPhase.Listening && autoSendEnabled && autoSendSilenceMs > 0L
    ) (silenceProgressMs.toFloat() / autoSendSilenceMs.toFloat()).coerceIn(0f, 1f)
    else 0f

    val hintRes = when (phase) {
        AutoPhase.Listening -> if (autoSendEnabled) R.string.auto_mode_hint_listening_auto
                               else R.string.auto_mode_hint_listening
        AutoPhase.Idle -> R.string.auto_mode_hint_idle
        // Während Claude denkt/spricht: Mic ist deaktiviert; Hinweis-Zeile bleibt leer,
        // damit nicht der Eindruck entsteht, der Tap würde was tun.
        else -> null
    }

    val micState = when (voiceState) {
        de.smartzone.pocketclaude.ui.chat.VoiceState.Idle -> MicState.Idle
        de.smartzone.pocketclaude.ui.chat.VoiceState.Recording -> MicState.Recording
        de.smartzone.pocketclaude.ui.chat.VoiceState.Transcribing -> MicState.Transcribing
    }
    val micEnabled = voiceState == de.smartzone.pocketclaude.ui.chat.VoiceState.Recording ||
        (voiceEnabled && voiceState != de.smartzone.pocketclaude.ui.chat.VoiceState.Transcribing)

    Column(
        modifier = modifier
            .fillMaxWidth()
            .background(MaterialTheme.colorScheme.background)
            .windowInsetsPadding(WindowInsets.ime.union(WindowInsets.navigationBars))
            .padding(horizontal = 16.dp, vertical = 16.dp)
            .heightIn(min = 240.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        // Status-Crossfade verhindert Flacker beim Phase-Wechsel zwischen
        // Höre zu / Claude denkt / Liest vor. Während Auto-Send-Countdown
        // bleibt der Text auf „Höre zu" stehen — der Countdown lebt visuell
        // als Ring um den Mic-Button.
        Crossfade(targetState = statusRes, label = "auto-status") { res ->
            Text(
                text = stringResource(res),
                style = MaterialTheme.typography.titleLarge,
                color = MaterialTheme.colorScheme.onBackground,
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

        Spacer(Modifier.size(4.dp))

        MicButton(
            state = micState,
            onTap = onMicTap,
            onCancel = onMicCancel,
            enabled = micEnabled,
            outerSize = 140.dp,
            progressFraction = ringFraction,
        )

        // Vorlesen abbrechen (Joscha 19.10.2026): nur waehrend die Antwort
        // geladen oder vorgelesen wird. Der Loop wartet in Phase 6 genau auf
        // das Ende der Wiedergabe und startet danach selbst die Aufnahme.
        AnimatedVisibility(visible = phase == AutoPhase.LoadingAudio || phase == AutoPhase.Speaking) {
            FilledTonalButton(onClick = onStopSpeaking) {
                Icon(
                    PocketIcons.Stop,
                    contentDescription = null,
                    modifier = Modifier.size(PocketIconSize.Small),
                )
                Spacer(Modifier.size(8.dp))
                Text(stringResource(R.string.auto_mode_stop_speaking))
            }
        }

        Spacer(Modifier.size(4.dp))

        // Auto-Send-Toggle: dezent unter dem Mic, damit der User entscheiden
        // kann, ob die Aufnahme nach Stille selbst aufhört oder erst durch
        // Mic-Tap. Klick auf die ganze Zeile = Toggle (größerer Hit-Bereich
        // als nur der Switch).
        Row(
            modifier = Modifier
                .clip(RoundedCornerShape(20.dp))
                .padding(horizontal = 4.dp),
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
            contentPadding = PaddingValues(horizontal = 16.dp, vertical = 8.dp),
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

private enum class AutoPhase {
    Listening, Transcribing, Thinking, LoadingAudio, Speaking, Idle,
}
