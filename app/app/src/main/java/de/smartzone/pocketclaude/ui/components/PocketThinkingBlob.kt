package de.smartzone.pocketclaude.ui.components

import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.rotate
import androidx.compose.ui.graphics.drawscope.scale
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.sin

/**
 * PocketThinkingBlob: der PocketClot-Klumpen ("Nordic Soft", seit 22.10.2026), der beim Denken atmet.
 *
 * - Ruhezustand (isThinking = false): das Markenzeichen `ic_brand_mark`, gleiche Silhouette mit 6 Lappen.
 * - Reinfliessen (isThinking -> true): die Kontur geht ueber 1200 ms in ein ruhiges Morphen ueber.
 * - Stil "Sanftes Atmen" (Joschas Wahl im Icon-Bogen): 3,6 s je Zyklus, Groesse 97 bis 103 %,
 *   Drehung +-2 Grad, kleine Formaenderung.
 * - Zurueckfliessen (isThinking -> false): klingt ueber 1400 ms ab, dann uebernimmt das statische Bild.
 */
@Composable
fun PocketThinkingBlob(
    modifier: Modifier = Modifier,
    size: Dp = 25.dp,
    isThinking: Boolean = true,
    speedMultiplier: Float = 1f,
    morphIntensity: Float = 0.12f,
    specularShine: Float = 0.3f,
    glowEnabled: Boolean = false,
) {
    val transitionProgress by animateFloatAsState(
        targetValue = if (isThinking) 1f else 0f,
        animationSpec = tween(
            durationMillis = if (isThinking) 1200 else 1400,
            easing = FastOutSlowInEasing,
        ),
        label = "PocketThinkingBlob3DProgress",
    )

    // Falls komplett im Ruhezustand und Transition beendet: Statische Marken-Komponente
    if (transitionProgress == 0f && !isThinking) {
        PocketBrandMark(modifier = modifier, size = size)
        return
    }

    val transition = rememberInfiniteTransition(label = "PocketThinkingBlob3DInfinite")

    val phase1 by transition.animateFloat(
        initialValue = 0f,
        targetValue = (2 * PI).toFloat(),
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = (3600 / speedMultiplier).toInt(), easing = LinearEasing),
            repeatMode = RepeatMode.Restart,
        ),
        label = "Phase1",
    )

    val phase2 by transition.animateFloat(
        initialValue = 0f,
        targetValue = (2 * PI).toFloat(),
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = (5000 / speedMultiplier).toInt(), easing = LinearEasing),
            repeatMode = RepeatMode.Restart,
        ),
        label = "Phase2",
    )

    // Ein Atemzug: hin und zurueck in 3,6 s. Groesse und Drehung laufen
    // gemeinsam, wie in der Vorschau des Icon-Bogens.
    val breath by transition.animateFloat(
        initialValue = 0f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = (1800 / speedMultiplier).toInt(), easing = FastOutSlowInEasing),
            repeatMode = RepeatMode.Reverse,
        ),
        label = "Breath",
    )
    val rawBreathingScale = 0.97f + 0.06f * breath
    val rawWobbleAngle = -2f + 4f * breath

    val rawGlowAlpha by transition.animateFloat(
        initialValue = 0.20f,
        targetValue = 0.50f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = (1800 / speedMultiplier).toInt(), easing = LinearEasing),
            repeatMode = RepeatMode.Reverse,
        ),
        label = "GlowAlpha",
    )

    val currentBreathingScale = 1.0f + (rawBreathingScale - 1.0f) * transitionProgress
    val currentWobbleAngle = rawWobbleAngle * transitionProgress
    val currentGlowAlpha = rawGlowAlpha * transitionProgress

    Box(
        modifier = modifier.size(size),
        contentAlignment = Alignment.Center,
    ) {
        // Ueberblendung zum Ruhebild: Das PNG ist anders beleuchtet als der
        // Canvas-Verlauf, ein hartes Umschalten bei progress 0 waere ein
        // sichtbarer Farbsprung. Unten liegt das Markenzeichen, deckend bis zur
        // Haelfte des Uebergangs; oben wird die Zeichnung erst ab dort ganz
        // deckend. So bleibt die Flaeche nie halbdurchsichtig.
        PocketBrandMark(
            size = size,
            modifier = Modifier.graphicsLayer {
                alpha = (2f * (1f - transitionProgress)).coerceIn(0f, 1f)
            },
        )
        Canvas(
            modifier = Modifier
                .matchParentSize()
                .graphicsLayer { alpha = (2f * transitionProgress).coerceIn(0f, 1f) },
        ) {
            val baseRadius = minOf(this.size.width, this.size.height) * 0.36f
            // Schwerpunkt des Klumpens liegt nicht exakt in der Bildmitte des
            // Markenzeichens; so deckt sich die Kontur mit dem Ruhebild.
            val center = Offset(
                this.size.width / 2f + baseRadius * CENTER_OFFSET_X,
                this.size.height / 2f + baseRadius * CENTER_OFFSET_Y,
            )

            rotate(degrees = currentWobbleAngle, pivot = center) {
                scale(scale = currentBreathingScale, pivot = center) {
                    // 1. Ambient Aura
                    if (glowEnabled && currentGlowAlpha > 0.01f) {
                        drawCircle(
                            brush = Brush.radialGradient(
                                colors = listOf(
                                    Color(0xFF7CB8EB).copy(alpha = currentGlowAlpha * 0.42f),
                                    Color(0xFF1B649E).copy(alpha = currentGlowAlpha * 0.18f),
                                    Color.Transparent,
                                ),
                                center = center,
                                radius = baseRadius * 1.60f,
                            ),
                            radius = baseRadius * 1.60f,
                            center = center,
                        )
                    }

                    // 2. 3D Knetmassen-Path mit PocketClot-Proportionen
                    val blobPath = create3DClayBlobPath(
                        center = center,
                        baseRadius = baseRadius,
                        phase1 = phase1,
                        phase2 = phase2,
                        morphProgress = transitionProgress,
                        morphIntensity = morphIntensity,
                    )

                    // 3. Satin-Verlauf, Farben am Icon abgenommen
                    val lightSource = Offset(center.x - baseRadius * 0.30f, center.y - baseRadius * 0.45f)
                    val blobBrush = Brush.radialGradient(
                        0.00f to Color(0xFF9AD3FF),
                        0.18f to Color(0xFF5EAEF4),
                        0.45f to Color(0xFF2F86E3),
                        0.78f to Color(0xFF1F66C9),
                        1.00f to Color(0xFF1A3F93),
                        center = lightSource,
                        radius = baseRadius * 1.8f,
                    )
                    drawPath(path = blobPath, brush = blobBrush)

                    // 4. Glanzpunkt (Specular Clay Highlight)
                    if (specularShine > 0f) {
                        val highlightCenter = Offset(
                            center.x - baseRadius * 0.32f + (cos(phase1.toDouble()) * baseRadius * 0.06f * transitionProgress).toFloat(),
                            center.y - baseRadius * 0.32f + (sin(phase2.toDouble()) * baseRadius * 0.06f * transitionProgress).toFloat(),
                        )
                        drawCircle(
                            brush = Brush.radialGradient(
                                colors = listOf(
                                    Color.White.copy(alpha = 0.65f * specularShine),
                                    Color.White.copy(alpha = 0.20f * specularShine),
                                    Color.Transparent,
                                ),
                                center = highlightCenter,
                                radius = baseRadius * 0.45f,
                            ),
                            radius = baseRadius * 0.45f,
                            center = highlightCenter,
                        )
                    }
                }
            }
        }
    }
}

// 36 Kontrollpunkte im 10-Grad-Raster, vermessen am Masterbild
// `Animation/nordic_soft_master.png` (Winkel im Uhrzeigersinn ab 3 Uhr,
// Radien relativ zu baseRadius, skaliert wie ic_brand_mark mit 92 %).
// Weniger Punkte machen die Lappen spitz und die Taeler flach.
private val CONTROL_ANGLES = FloatArray(36) { (it * 10.0 * PI / 180.0).toFloat() }

private val CONTROL_RADII = floatArrayOf(
    1.166f, 1.293f, 1.345f, 1.329f, 1.253f, 1.084f, 1.051f, 1.155f, 1.224f,
    1.243f, 1.214f, 1.148f, 1.152f, 1.267f, 1.334f, 1.347f, 1.302f, 1.156f,
    1.113f, 1.265f, 1.333f, 1.326f, 1.251f, 1.105f, 1.067f, 1.159f, 1.243f,
    1.287f, 1.284f, 1.208f, 1.067f, 1.118f, 1.277f, 1.335f, 1.321f, 1.222f,
)

// Abstand Schwerpunkt zu Bildmitte des Markenzeichens, in baseRadius.
private const val CENTER_OFFSET_X = -0.010f
private const val CENTER_OFFSET_Y = 0.022f

private fun create3DClayBlobPath(
    center: Offset,
    baseRadius: Float,
    phase1: Float,
    phase2: Float,
    morphProgress: Float,
    morphIntensity: Float = 0.12f,
): Path {
    val n = CONTROL_ANGLES.size
    val points = ArrayList<Offset>(n)

    for (i in 0 until n) {
        val angle = CONTROL_ANGLES[i]
        val baseR = baseRadius * CONTROL_RADII[i]

        val wave = 1.0f + (morphProgress * morphIntensity) * (
            0.16f * sin((2 * angle + phase1).toDouble()).toFloat() +
            0.11f * cos((3 * angle - phase2).toDouble()).toFloat() +
            0.06f * sin((5 * angle + phase1 * 0.7f).toDouble()).toFloat()
        )

        val r = baseR * wave
        val x = center.x + r * cos(angle.toDouble()).toFloat()
        val y = center.y + r * sin(angle.toDouble()).toFloat()
        points.add(Offset(x, y))
    }

    val path = Path()
    if (points.isEmpty()) return path

    path.moveTo(points[0].x, points[0].y)

    for (i in 0 until n) {
        val pPrev = points[(i - 1 + n) % n]
        val pCurr = points[i]
        val pNext = points[(i + 1) % n]
        val pNext2 = points[(i + 2) % n]

        val c1x = pCurr.x + (pNext.x - pPrev.x) / 6.0f
        val c1y = pCurr.y + (pNext.y - pPrev.y) / 6.0f
        val c2x = pNext.x - (pNext2.x - pCurr.x) / 6.0f
        val c2y = pNext.y - (pNext2.y - pCurr.y) / 6.0f

        path.cubicTo(c1x, c1y, c2x, c2y, pNext.x, pNext.y)
    }
    path.close()
    return path
}

@Preview(showBackground = true, backgroundColor = 0xFFF7F4EF)
@Composable
fun PocketThinkingBlobPreviewLight() {
    PocketThinkingBlob(size = 48.dp, isThinking = true)
}

@Preview(showBackground = true, backgroundColor = 0xFF1C1B1F)
@Composable
fun PocketThinkingBlobPreviewDark() {
    PocketThinkingBlob(size = 48.dp, isThinking = true)
}
