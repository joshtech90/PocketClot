package de.smartzone.pocketclaude.ui.components

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.AbsoluteRoundedCornerShape
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import de.smartzone.pocketclaude.R
import de.smartzone.pocketclaude.ui.theme.AtelierCoral
import de.smartzone.pocketclaude.ui.theme.AtelierGold
import de.smartzone.pocketclaude.ui.theme.PocketTheme
import java.util.Locale
import de.smartzone.pocketclaude.ui.theme.PocketRadius
import de.smartzone.pocketclaude.ui.theme.PocketIconSize
import de.smartzone.pocketclaude.ui.theme.PocketIcons

@Composable
fun PocketBackdrop(
    modifier: Modifier = Modifier,
    content: @Composable BoxScope.() -> Unit,
) {
    val colors = PocketTheme.colors
    val background = MaterialTheme.colorScheme.background
    Box(
        modifier = modifier.background(
            Brush.verticalGradient(
                listOf(background, colors.surfaceLow, background)
            )
        ),
    ) {
        // Weiche Lichtflecken statt Kreisen mit harter Kante: die Kanten der
        // alten Kreise zeichneten sich hinter Text und Karten als Boegen ab.
        Canvas(Modifier.fillMaxSize()) {
            val warm = Offset(size.width * 1.0f, size.height * 0.02f)
            val warmRadius = size.minDimension * 0.85f
            drawCircle(
                brush = Brush.radialGradient(
                    colors = listOf(colors.ambientPrimary.copy(alpha = 0.10f), Color.Transparent),
                    center = warm,
                    radius = warmRadius,
                ),
                radius = warmRadius,
                center = warm,
            )
            val cool = Offset(size.width * 0.0f, size.height * 0.55f)
            val coolRadius = size.minDimension * 0.75f
            drawCircle(
                brush = Brush.radialGradient(
                    colors = listOf(colors.ambientSecondary.copy(alpha = 0.07f), Color.Transparent),
                    center = cool,
                    radius = coolRadius,
                ),
                radius = coolRadius,
                center = cool,
            )
        }
        content()
    }
}

@Composable
fun PocketBrandMark(
    modifier: Modifier = Modifier,
    size: Dp = 42.dp,
) {
    // Das Markenzeichen der App, dasselbe Motiv wie das Launcher-Icon. Frueher
    // wurde hier ein generischer Vier-Zacken-Stern gezeichnet; der hatte mit
    // dem Icon auf dem Homescreen nichts zu tun.
    Image(
        painter = painterResource(R.drawable.ic_brand_mark),
        contentDescription = null,
        modifier = modifier.size(size),
    )
}

@Composable
fun PocketIconButton(
    icon: ImageVector,
    contentDescription: String?,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    emphasized: Boolean = false,
    contentColor: Color? = null,
) {
    val background = if (emphasized) {
        MaterialTheme.colorScheme.primary
    } else {
        MaterialTheme.colorScheme.surface.copy(alpha = 0.86f)
    }
    val defaultForeground = if (emphasized) {
        MaterialTheme.colorScheme.onPrimary
    } else {
        MaterialTheme.colorScheme.onSurface
    }
    val foreground = contentColor ?: defaultForeground
    Surface(
        modifier = modifier.size(48.dp),
        shape = CircleShape,
        color = background,
        contentColor = foreground,
        border = androidx.compose.foundation.BorderStroke(
            1.dp,
            if (emphasized) Color.Transparent else PocketTheme.colors.outlineSoft,
        ),
        shadowElevation = if (emphasized) 6.dp else 0.dp,
    ) {
        Box(
            modifier = Modifier
                .fillMaxSize()
                .clickable(role = Role.Button, onClick = onClick),
            contentAlignment = Alignment.Center,
        ) {
            Icon(icon, contentDescription = contentDescription, modifier = Modifier.size(PocketIconSize.Regular))
        }
    }
}

@Composable
fun PocketScreenTitle(
    title: String,
    eyebrow: String,
    modifier: Modifier = Modifier,
) {
    val showEyebrow = androidx.compose.ui.platform.LocalDensity.current.fontScale <= 1.3f
    androidx.compose.foundation.layout.Column(modifier) {
        if (showEyebrow) {
            Text(
                text = eyebrow.uppercase(Locale.ROOT),
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.primary,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
        Text(
            text = title,
            style = MaterialTheme.typography.titleLarge,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

@Composable
fun PocketStatusPill(
    text: String,
    modifier: Modifier = Modifier,
    tint: Color = MaterialTheme.colorScheme.secondary,
    icon: ImageVector? = PocketIcons.Sparkle,
) {
    Row(
        modifier = modifier
            .background(tint.copy(alpha = 0.12f), RoundedCornerShape(50))
            .border(1.dp, tint.copy(alpha = 0.2f), RoundedCornerShape(50))
            .padding(horizontal = 10.dp, vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (icon != null) {
            Icon(icon, contentDescription = null, tint = tint, modifier = Modifier.size(PocketIconSize.Marker))
            Spacer(Modifier.width(6.dp))
        }
        Text(
            text = text,
            style = MaterialTheme.typography.labelSmall,
            color = tint,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

/**
 * Karte der obersten Ebene. Einstellungen, Bilder und Gem-Editor nutzen
 * dieselbe Form; vorher hatte fast jede Karte ihren eigenen Radius (20, 24,
 * 26, 28 dp) und ihr eigenes Innenmass.
 */
@Composable
fun PocketCard(
    modifier: Modifier = Modifier,
    contentPadding: Dp = 16.dp,
    spacing: Dp = 12.dp,
    content: @Composable ColumnScope.() -> Unit,
) {
    Surface(
        modifier = modifier.fillMaxWidth(),
        shape = RoundedCornerShape(PocketRadius.Large),
        color = MaterialTheme.colorScheme.surface.copy(alpha = 0.88f),
        contentColor = MaterialTheme.colorScheme.onSurface,
        border = androidx.compose.foundation.BorderStroke(1.dp, PocketTheme.colors.outlineSoft),
    ) {
        Column(
            modifier = Modifier.padding(contentPadding),
            verticalArrangement = Arrangement.spacedBy(spacing),
            content = content,
        )
    }
}

/**
 * Auswahl-Chip fuer Einfach- und Mehrfachauswahl. Ausgewaehlt heisst ueberall
 * dasselbe: Flaeche in secondaryContainer, wie es Material 3 vorsieht. Vorher
 * waren manche Chips in der Akzentfarbe gefuellt und andere nicht.
 */
@Composable
fun PocketChoiceChip(
    selected: Boolean,
    onClick: () -> Unit,
    label: String,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    leadingIcon: (@Composable () -> Unit)? = null,
) {
    FilterChip(
        selected = selected,
        onClick = onClick,
        label = { Text(label, maxLines = 1, overflow = TextOverflow.Ellipsis) },
        modifier = modifier,
        enabled = enabled,
        leadingIcon = leadingIcon,
        shape = CircleShape,
    )
}
