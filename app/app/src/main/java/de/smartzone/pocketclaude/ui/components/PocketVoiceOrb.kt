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
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ripple
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.ProgressBarRangeInfo
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.progressBarRangeInfo
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import de.smartzone.pocketclaude.R

/** Was das Sprachgespraech gerade tut; bestimmt nur die Optik des Rings. */
enum class VoiceOrbPhase { Idle, Listening, Working, Speaking }

/**
 * Sprachgespraech-Anzeige: der PocketClot-Klumpen in einem duennen Ring
 * (Entscheidung 22.10.2026, Entwurf von Astra). Ersetzt im Auto-Modus den
 * grossen Mikrofon-Knopf und uebernimmt dessen Bedienung unveraendert:
 * Tippen startet/sendet, langes Druecken verwirft eine laufende Aufnahme.
 *
 * Der Ring zeigt die Phase, keinen Pegel. Einziger Countdown ist der
 * Stille-Countdown (`progressFraction`), der sich als Bogen auf dem Ring
 * fuellt, genau wie vorher am Mikrofon-Knopf.
 *
 * - Idle: ruhiger Ring, Klumpen still.
 * - Listening: Ring kraeftiger, eine leise Welle laedt zum Sprechen ein.
 * - Working (schreibt mit, denkt, laedt Audio): der Klumpen atmet.
 * - Speaking: atmen und langsamere Welle.
 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun PocketVoiceOrb(
    phase: VoiceOrbPhase,
    recording: Boolean,
    /** Sichtbarer Statustext ("Antwortet", "Liest vor"); TalkBack nennt ihn,
     *  solange der Orb nicht zum Aufnehmen bereit ist. */
    statusLabel: String,
    onTap: () -> Unit,
    onCancel: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    size: Dp = 140.dp,
    progressFraction: Float = 0f,
) {
    val haptics = LocalHapticFeedback.current
    val interaction = remember { MutableInteractionSource() }
    val accent = MaterialTheme.colorScheme.primary

    // Gesperrt (denkt, liest vor, kein Diktat eingerichtet): der Ring wird
    // blasser. Der Klumpen bleibt beim Arbeiten bewusst voll sichtbar, er
    // zeigt ja gerade die Arbeit an.
    val ringAlpha by animateFloatAsState(
        targetValue = when (phase) {
            VoiceOrbPhase.Listening -> 0.8f
            VoiceOrbPhase.Speaking -> 0.6f
            else -> 0.35f
        } * (if (enabled) 1f else 0.5f),
        animationSpec = tween(400),
        label = "orb-ring",
    )
    val targetFrac = progressFraction.coerceIn(0f, 1f)
    val countdown by animateFloatAsState(
        targetValue = targetFrac,
        animationSpec = tween(durationMillis = if (targetFrac > 0f) 150 else 200),
        label = "orb-countdown",
    )
    val waving = phase == VoiceOrbPhase.Listening || phase == VoiceOrbPhase.Speaking
    val wave = if (waving) {
        val transition = rememberInfiniteTransition(label = "orb-wave")
        val t by transition.animateFloat(
            initialValue = 0f,
            targetValue = 1f,
            animationSpec = infiniteRepeatable(
                animation = tween(
                    durationMillis = if (phase == VoiceOrbPhase.Listening) 2400 else 3600,
                    easing = LinearEasing,
                ),
                repeatMode = RepeatMode.Restart,
            ),
            label = "orb-wave-t",
        )
        t
    } else {
        -1f
    }

    val description = when {
        recording -> stringResource(R.string.voice_mic_recording_cd)
        enabled && (phase == VoiceOrbPhase.Idle || phase == VoiceOrbPhase.Listening) ->
            stringResource(R.string.voice_mic_idle_cd)
        else -> statusLabel
    }
    val working = phase == VoiceOrbPhase.Working

    Box(
        modifier = modifier
            .size(size)
            .semantics {
                contentDescription = description
                // Wie frueher der Spinner am Mikrofon: "arbeitet" fuer TalkBack.
                if (working) progressBarRangeInfo = ProgressBarRangeInfo.Indeterminate
            }
            .combinedClickable(
                enabled = enabled,
                interactionSource = interaction,
                indication = ripple(bounded = false, radius = size / 2),
                onClick = {
                    haptics.performHapticFeedback(HapticFeedbackType.LongPress)
                    onTap()
                },
                onLongClick = if (recording) {
                    {
                        haptics.performHapticFeedback(HapticFeedbackType.LongPress)
                        onCancel()
                    }
                } else null,
            ),
        contentAlignment = Alignment.Center,
    ) {
        Canvas(modifier = Modifier.size(size)) {
            // Ring bei 80 % der Flaeche, damit die Welle bis zum Rand Platz hat.
            val ringRadius = this.size.minDimension / 2f * 0.8f
            val stroke = 1.5.dp.toPx()
            if (wave >= 0f) {
                drawCircle(
                    color = accent.copy(alpha = 0.45f * (1f - wave)),
                    radius = ringRadius * (1f + 0.25f * wave),
                    style = Stroke(width = stroke),
                )
            }
            drawCircle(
                color = accent.copy(alpha = ringAlpha),
                radius = ringRadius,
                style = Stroke(width = stroke),
            )
            if (countdown > 0.01f) {
                val arcStroke = 3.dp.toPx()
                drawArc(
                    color = accent,
                    startAngle = -90f,
                    sweepAngle = 360f * countdown,
                    useCenter = false,
                    topLeft = Offset(center.x - ringRadius, center.y - ringRadius),
                    size = Size(ringRadius * 2f, ringRadius * 2f),
                    style = Stroke(width = arcStroke),
                )
            }
        }
        PocketThinkingBlob(
            size = size * (64f / 140f),
            isThinking = phase == VoiceOrbPhase.Working || phase == VoiceOrbPhase.Speaking,
            modifier = Modifier.alpha(if (enabled || phase != VoiceOrbPhase.Idle) 1f else 0.5f),
        )
    }
}
