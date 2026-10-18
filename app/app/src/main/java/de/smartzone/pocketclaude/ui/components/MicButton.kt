package de.smartzone.pocketclaude.ui.components

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.LocalContentColor
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ripple
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import de.smartzone.pocketclaude.R
import de.smartzone.pocketclaude.ui.theme.PocketIcons

enum class MicState { Idle, Recording, Transcribing }

/**
 * Mic-Button für den Input-Bar. Visuelles Vokabular adaptiert von
 * WhisperTyper (pulsierendes Indikator-Element):
 *   - Idle: stilles Mikro-Icon
 *   - Recording: Mikro auf grünem Untergrund, zwei pulsierende Kreise
 *     drumherum (1.4 s Loop, gegeneinander versetzt → "Atmen")
 *   - Transcribing: Mikro durch Spinner ersetzt
 *
 * Tap toggle Idle↔Recording, Long-Press während Recording = Cancel
 * (silent discard, keine Transkription).
 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun MicButton(
    state: MicState,
    onTap: () -> Unit,
    onCancel: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    outerSize: Dp = 48.dp,
    /** Optionaler Countdown-Ring außen um den Button (0f..1f). Wird nur
     *  gerendert wenn > 0. Idee: VAD im Auto-Modus setzt das auf
     *  silenceProgressMs/silenceTargetMs — der Ring füllt sich, und kurz
     *  bevor er voll ist sendet die App automatisch. Ersetzt den vorher
     *  springenden „Senden in Ns"-Text. */
    progressFraction: Float = 0f,
) {
    val haptics = LocalHapticFeedback.current
    val interaction = remember { MutableInteractionSource() }
    // Inner-Disc-Größe und Mic-Icon proportional zum Outer berechnen,
    // damit der Button bei größeren Outer-Werten (Auto-Mode: 140dp+)
    // weiterhin stimmige Proportionen hat.
    val innerSize = outerSize * (40f / 48f)
    val iconSize = outerSize * (20f / 48f)

    // Animation: progressFraction snap-resets auf 0 wenn der User weiter
    // spricht — wir wollen aber nicht zurückspringen, sondern sanft
    // wegfaden. Deshalb animateFloatAsState statt direkte Bindung.
    val ringStrokeDp = (outerSize.value / 20f).coerceAtLeast(2.5f).dp
    val targetFrac = progressFraction.coerceIn(0f, 1f)
    val animFrac by animateFloatAsState(
        targetValue = targetFrac,
        animationSpec = tween(
            // Bei monotonem Aufwärts (Stille wächst): folgen wir schnell.
            // Bei Reset (User redet wieder) ebenfalls fix raus.
            durationMillis = if (targetFrac > 0f) 150 else 200,
        ),
        label = "mic-progress",
    )
    val showRing = animFrac > 0.01f
    val ringColor = MaterialTheme.colorScheme.primary
    val ringTrackColor = MaterialTheme.colorScheme.primary.copy(alpha = 0.18f)
    val density = LocalDensity.current

    Box(
        modifier = modifier
            .size(outerSize)
            .combinedClickable(
                enabled = enabled,
                interactionSource = interaction,
                indication = ripple(bounded = false, radius = outerSize / 2),
                onClick = {
                    haptics.performHapticFeedback(
                        androidx.compose.ui.hapticfeedback.HapticFeedbackType.LongPress
                    )
                    onTap()
                },
                onLongClick = if (state == MicState.Recording) {
                    {
                        haptics.performHapticFeedback(
                            androidx.compose.ui.hapticfeedback.HapticFeedbackType.LongPress
                        )
                        onCancel()
                    }
                } else null,
            ),
        contentAlignment = Alignment.Center,
    ) {
        // Countdown-Ring: liegt UNTER den Pulse-Halos / dem Mic-Kern, in
        // voller Outer-Größe. Track ist halbtransparent (immer sichtbar
        // wenn der Ring aktiv ist), Fortschritt ist Primary-Brand.
        if (showRing) {
            val strokePx = with(density) { ringStrokeDp.toPx() }
            Canvas(modifier = Modifier.size(outerSize)) {
                val pad = strokePx / 2f
                val arcSize = Size(size.width - strokePx, size.height - strokePx)
                val topLeft = Offset(pad, pad)
                // Track (Hintergrund-Kreis)
                drawArc(
                    color = ringTrackColor,
                    startAngle = 0f,
                    sweepAngle = 360f,
                    useCenter = false,
                    topLeft = topLeft,
                    size = arcSize,
                    style = Stroke(width = strokePx),
                )
                // Fortschritt (oben anfangen, im Uhrzeigersinn)
                drawArc(
                    color = ringColor,
                    startAngle = -90f,
                    sweepAngle = 360f * animFrac,
                    useCenter = false,
                    topLeft = topLeft,
                    size = arcSize,
                    style = Stroke(width = strokePx),
                )
            }
        }
        when (state) {
            MicState.Idle -> {
                Icon(
                    PocketIcons.Mic,
                    contentDescription = stringResource(R.string.voice_mic_idle_cd),
                    tint = if (enabled) {
                        MaterialTheme.colorScheme.onSurfaceVariant
                    } else {
                        MaterialTheme.colorScheme.onSurface.copy(alpha = 0.35f)
                    },
                    modifier = Modifier.size(iconSize),
                )
            }

            MicState.Recording -> {
                // Pulse-Animation: zwei konzentrische Halo-Kreise, 1400 ms
                // Loop, der zweite um 700 ms versetzt → optisches "Atmen".
                val transition = rememberInfiniteTransition(label = "mic-pulse")
                val pulseA by transition.animateFloat(
                    initialValue = 0f, targetValue = 1f,
                    animationSpec = infiniteRepeatable(
                        animation = tween(1400, easing = LinearEasing),
                        repeatMode = RepeatMode.Restart,
                    ),
                    label = "pulseA",
                )
                val pulseB by transition.animateFloat(
                    initialValue = 0f, targetValue = 1f,
                    animationSpec = infiniteRepeatable(
                        animation = tween(1400, easing = LinearEasing, delayMillis = 700),
                        repeatMode = RepeatMode.Restart,
                    ),
                    label = "pulseB",
                )
                // Pulse-Kreise hinter dem Mic
                Box(
                    modifier = Modifier
                        .size(innerSize)
                        .scale(1f + pulseA * 0.6f)
                        .alpha((1f - pulseA) * 0.55f)
                        .clip(CircleShape)
                        .background(PULSE_GREEN),
                )
                Box(
                    modifier = Modifier
                        .size(innerSize)
                        .scale(1f + pulseB * 0.6f)
                        .alpha((1f - pulseB) * 0.55f)
                        .clip(CircleShape)
                        .background(PULSE_GREEN),
                )
                // Mic im grünen Kern, fest skaliert (kein Wackeln)
                Box(
                    modifier = Modifier
                        .size(innerSize)
                        .clip(CircleShape)
                        .background(PULSE_GREEN),
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(
                        PocketIcons.Mic,
                        contentDescription = stringResource(R.string.voice_mic_recording_cd),
                        tint = Color.White,
                        modifier = Modifier.size(iconSize),
                    )
                }
            }

            MicState.Transcribing -> {
                Box(
                    modifier = Modifier
                        .size(innerSize)
                        .clip(CircleShape)
                        .background(MaterialTheme.colorScheme.surfaceVariant),
                    contentAlignment = Alignment.Center,
                ) {
                    CircularProgressIndicator(
                        modifier = Modifier.size(iconSize),
                        strokeWidth = (iconSize.value / 10f).dp.coerceAtLeast(2.dp),
                        color = LocalContentColor.current.copy(alpha = 0.7f),
                    )
                }
            }
        }
    }
}

/** Cancel-Indicator als Floating-Hint über dem Input während Recording —
 *  zeigt dem User, dass Long-Press abbricht. Wird vom Caller positioniert. */
@Composable
fun MicCancelHint(modifier: Modifier = Modifier) {
    Box(
        modifier = modifier
            .clip(CircleShape)
            .background(MaterialTheme.colorScheme.surfaceVariant)
            .size(20.dp),
        contentAlignment = Alignment.Center,
    ) {
        Icon(
            PocketIcons.Close,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.size(12.dp),
        )
    }
}

// Grün analog WhisperTyper / Material "live recording" — kräftig genug
// um auf hellem und dunklem Hintergrund klar sichtbar zu sein.
private val PULSE_GREEN = Color(0xFF22C55E)
