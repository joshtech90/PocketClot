package de.smartzone.pocketclaude.ui.components

import androidx.compose.foundation.layout.Column
import androidx.compose.ui.res.stringResource
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import de.smartzone.pocketclaude.ui.theme.PocketIconSize
import de.smartzone.pocketclaude.ui.theme.PocketIcons

/**
 * Dezenter „ⓘ"-Knopf neben Settings-Labels. Klick → AlertDialog mit ausführlicher
 * Erklärung. Der Body kommt als Composable-Lambda rein, damit auch Markdown-artige
 * Inhalte (mehrere Absätze, fett, Aufzählungen via Text) sauber gerendert werden.
 *
 * Bewusst keine Tooltip-Variante: auf Touch-Geräten umständlich, und der Hinweis
 * soll in einer veröffentlichten App auch für DAUs gut auffindbar bleiben.
 *
 * Beispiel:
 *
 * ```
 * Row(verticalAlignment = Alignment.CenterVertically) {
 *     Text("Provider", style = MaterialTheme.typography.labelLarge)
 *     InfoButton(title = "TTS-Provider erklärt") {
 *         Text("Cloud TTS Studio-B liegt im Free-Tier von 1 Mio Zeichen/Monat …")
 *     }
 * }
 * ```
 */
@Composable
fun InfoButton(
    title: String,
    contentDescription: String = "Info",
    body: @Composable () -> Unit,
) {
    var open by remember { mutableStateOf(false) }
    IconButton(
        onClick = { open = true },
        modifier = Modifier.size(48.dp),
    ) {
        Icon(
            imageVector = PocketIcons.Info,
            contentDescription = contentDescription,
            tint = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.size(PocketIconSize.Small),
        )
    }
    if (open) {
        AlertDialog(
            onDismissRequest = { open = false },
            title = { Text(title) },
            text = {
                Column(
                    modifier = Modifier.verticalScroll(rememberScrollState()),
                ) {
                    body()
                    Spacer(Modifier.height(2.dp))
                }
            },
            confirmButton = {
                TextButton(onClick = { open = false }) {
                    Text(stringResource(de.smartzone.pocketclaude.R.string.action_got_it))
                }
            },
        )
    }
}

/**
 * Hilfs-Composable für Info-Body-Absätze. Standard-Body-Style + bisschen
 * Abstand nach unten, damit man nicht jedes Mal manuell `Text + Spacer`
 * tippen muss.
 */
@Composable
fun InfoParagraph(text: String) {
    Text(
        text = text,
        style = MaterialTheme.typography.bodyMedium,
    )
    Spacer(Modifier.height(10.dp))
}

/**
 * Variant with a bold lead word. Used for "Tip:" / "Note:" / "Free-Tier:" lines.
 */
@Composable
fun InfoBulletParagraph(lead: String, rest: String) {
    Text(
        text = buildAnnotatedString(lead, rest),
        style = MaterialTheme.typography.bodyMedium,
    )
    Spacer(Modifier.height(10.dp))
}

private fun buildAnnotatedString(lead: String, rest: String) =
    androidx.compose.ui.text.buildAnnotatedString {
        pushStyle(
            androidx.compose.ui.text.SpanStyle(
                fontWeight = androidx.compose.ui.text.font.FontWeight.SemiBold,
            )
        )
        append(lead)
        pop()
        append(" ")
        append(rest)
    }
