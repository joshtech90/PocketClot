package de.smartzone.pocketclaude.ui.chat

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBars
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import de.smartzone.pocketclaude.ui.theme.PocketIconSize
import de.smartzone.pocketclaude.ui.theme.PocketIcons

/**
 * Kopfzeile im Chat nach dem Vorbild der ChatGPT-App (Joscha 19.10.2026):
 * keine Leiste, sondern schwebende Knoepfe ueber dem Verlauf. Links ein
 * runder Menue-Knopf und der Chat-Titel, rechts eine Pille mit Denkstufe,
 * neuem Chat und Mehr-Menue. Darunter blendet ein Verlauf den Text aus, der
 * unter die Kopfzeile scrollt. Kontext- und Token-Anzeige sind bewusst weg.
 */
@Composable
internal fun ChatFloatingHeader(
    title: String,
    onMenu: () -> Unit,
    menuDescription: String,
    actions: @Composable RowScope.() -> Unit,
) {
    val background = MaterialTheme.colorScheme.background
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .background(
                Brush.verticalGradient(
                    0f to background.copy(alpha = 0.96f),
                    0.75f to background.copy(alpha = 0.9f),
                    1f to background.copy(alpha = 0f),
                )
            ),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .windowInsetsPadding(WindowInsets.statusBars)
                .padding(start = 14.dp, end = 12.dp, top = 12.dp, bottom = 20.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            FloatingSurface(shape = CircleShape) {
                HeaderIcon(PocketIcons.MenuShort, menuDescription, onMenu)
            }
            Spacer(Modifier.width(12.dp))
            Text(
                title,
                style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.onBackground,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.weight(1f),
            )
            Spacer(Modifier.width(8.dp))
            FloatingSurface(shape = CircleShape) {
                Row(
                    modifier = Modifier.padding(horizontal = 2.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    content = actions,
                )
            }
        }
    }
}

/** Ein 44-dp-Knopf in der Kopfzeile, wie bei ChatGPT. */
@Composable
internal fun HeaderIcon(
    icon: ImageVector,
    description: String,
    onClick: () -> Unit,
    tint: Color = MaterialTheme.colorScheme.onSurface,
) {
    Box(
        modifier = Modifier
            .size(HEADER_BUTTON)
            .clip(CircleShape)
            .clickable(role = Role.Button, onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Icon(icon, contentDescription = description, tint = tint, modifier = Modifier.size(PocketIconSize.Regular))
    }
}

/** Weisse (dunkel: graue) Flaeche mit weichem Schatten, wie das Eingabefeld. */
@Composable
private fun FloatingSurface(
    shape: androidx.compose.ui.graphics.Shape,
    content: @Composable () -> Unit,
) {
    val dark = MaterialTheme.colorScheme.background.luminance() < 0.5f
    Surface(
        modifier = Modifier.height(HEADER_BUTTON),
        shape = shape,
        color = if (dark) MaterialTheme.colorScheme.surfaceContainerHigh
            else MaterialTheme.colorScheme.surfaceContainerLowest,
        contentColor = MaterialTheme.colorScheme.onSurface,
        shadowElevation = 3.dp,
        content = content,
    )
}

private val HEADER_BUTTON = 44.dp
