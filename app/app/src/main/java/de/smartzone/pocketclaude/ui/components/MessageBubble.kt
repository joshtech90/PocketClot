package de.smartzone.pocketclaude.ui.components

import android.widget.Toast
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.expandVertically
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.shrinkVertically
import androidx.compose.animation.core.tween
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import de.smartzone.pocketclaude.R
import de.smartzone.pocketclaude.data.AttachmentRefDto
import de.smartzone.pocketclaude.ui.theme.PocketTheme
import java.util.Locale
import de.smartzone.pocketclaude.ui.theme.PocketIconSize
import de.smartzone.pocketclaude.ui.theme.PocketRadius
import de.smartzone.pocketclaude.ui.theme.PocketIcons

@Composable
fun UserBubble(
    text: String,
    attachments: List<AttachmentRefDto> = emptyList(),
    /** Wenn TRUE: lange Nachrichten werden nach `COLLAPSE_MAX_LINES` Zeilen
     *  abgeschnitten. Tap auf die Bubble klappt sie auf/zu (kein „Mehr anzeigen"-
     *  Button — selbsterklärend). Wenn FALSE: immer der volle Text. */
    collapseLongMessages: Boolean = true,
    modifier: Modifier = Modifier,
) {
    val pocket = PocketTheme.colors
    // Per-Bubble State: ist der lange Text gerade ausgeklappt?
    var expanded by remember(text) { mutableStateOf(false) }

    val showCollapsed = collapseLongMessages && !expanded
    val maxLines = if (showCollapsed) COLLAPSE_MAX_LINES else Int.MAX_VALUE
    val copy = rememberCopyHandler(text)
    val bubbleShape = RoundedCornerShape(
        topStart = PocketRadius.Large,
        topEnd = PocketRadius.Large,
        bottomStart = PocketRadius.Large,
        bottomEnd = PocketRadius.XSmall,
    )

    Row(
        modifier = modifier
            .fillMaxWidth()
            // Rechts 16 dp wie links bei den Antworten: vorher klebte die
            // eigene Nachricht mit 10 dp naeher am Rand als die Antwort.
            .padding(start = 48.dp, end = 16.dp, top = 8.dp, bottom = 8.dp),
        horizontalArrangement = Arrangement.End,
    ) {
        Column(horizontalAlignment = Alignment.End) {
            if (attachments.isNotEmpty()) {
                AttachmentsStrip(attachments, alignEnd = true)
                Spacer(Modifier.height(4.dp))
            }
            if (text.isNotBlank()) {
                Box(
                    modifier = Modifier
                        .widthIn(max = 320.dp)
                        .clip(bubbleShape)
                        .background(pocket.bubbleUser)
                        .border(1.dp, Color.White.copy(alpha = 0.14f), bubbleShape)
                        // Normaler clickable (NICHT combinedClickable) — Long-
                        // Click bleibt dann beim eingebetteten SelectionContainer
                        // (wird vom ChatScreen umgewickelt), damit native Text-
                        // Selektion funktioniert. Tap toggelt nur Collapse, wenn
                        // das Feature aktiv ist.
                        .then(
                            if (collapseLongMessages) {
                                Modifier.clickable(
                                    interactionSource = remember { MutableInteractionSource() },
                                    indication = null,
                                ) { expanded = !expanded }
                            } else Modifier
                        )
                        .padding(horizontal = 16.dp, vertical = 12.dp),
                ) {
                    Text(
                        text = text,
                        color = pocket.onBubbleUser,
                        style = MaterialTheme.typography.bodyLarge,
                        maxLines = maxLines,
                        overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis,
                    )
                }
                // Compact copy-button below the bubble — mirrors the
                // assistant-side action so the user can lift their own
                // long messages back to the clipboard for re-use.
                // Um die halbe Knopf-Leerflaeche nach rechts versetzt, damit das
                // Symbol buendig mit der Bubble-Kante abschliesst.
                IconButton(
                    onClick = copy,
                    modifier = Modifier.offset(x = 15.dp).size(48.dp),
                ) {
                    Icon(
                        PocketIcons.Copy,
                        contentDescription = stringResource(R.string.bubble_copy),
                        tint = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.size(PocketIconSize.Small),
                    )
                }
            }
        }
    }
}

/** Bei einer Bubble-Breite von max 320 dp + bodyLarge entspricht das visuell
 *  ungefähr dem ChatGPT-Verhalten (~6 sichtbare Zeilen, dann Abbruch). */
private const val COLLAPSE_MAX_LINES = 6

/**
 * Liefert eine Lambda, die den gegebenen Text in die Zwischenablage kopiert und
 * via Toast bestätigt. Wird für Long-Press auf den Bubbles genutzt.
 */
@Composable
private fun rememberCopyHandler(text: String): () -> Unit {
    val clipboard = LocalClipboardManager.current
    val context = LocalContext.current
    val haptics = LocalHapticFeedback.current
    val copiedLabel = stringResource(R.string.bubble_copied)
    return {
        if (text.isNotBlank()) {
            clipboard.setText(AnnotatedString(text))
            haptics.performHapticFeedback(HapticFeedbackType.LongPress)
            Toast.makeText(context, copiedLabel, Toast.LENGTH_SHORT).show()
        }
    }
}

enum class TtsState { Idle, Loading, Playing, Paused }

/**
 * Kleiner dezenter Block, der den Gedankengang während Extended-Thinking zeigt.
 * Sieht aus wie eine flache Karte mit italic-Text und einem 💭-Indikator vorne.
 */
@Composable
private fun ThinkingBlock(text: String, isLive: Boolean) {
    val pocket = PocketTheme.colors
    Box(
        modifier = Modifier
            .widthIn(max = 320.dp)
            .clip(RoundedCornerShape(PocketRadius.Medium))
            .background(pocket.bubbleAssistant.copy(alpha = 0.55f))
            .padding(horizontal = 12.dp, vertical = 8.dp),
    ) {
        Column {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    text = if (isLive) stringResource(R.string.bubble_thinking_live) else stringResource(R.string.bubble_thinking_label),
                    style = MaterialTheme.typography.labelSmall,
                    color = pocket.onBubbleAssistant.copy(alpha = 0.7f),
                )
            }
            Spacer(Modifier.height(4.dp))
            Text(
                text = text.trim(),
                style = MaterialTheme.typography.bodySmall.copy(
                    fontStyle = androidx.compose.ui.text.font.FontStyle.Italic,
                ),
                color = pocket.onBubbleAssistant.copy(alpha = 0.65f),
            )
        }
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun AssistantBubble(
    text: String,
    /** Vom Modell im Chat erzeugte Bilder. Werden unter dem Text gezeigt. */
    attachments: List<AttachmentRefDto> = emptyList(),
    isStreaming: Boolean = false,
    thinkingText: String = "",
    ttsState: TtsState = TtsState.Idle,
    onSpeakClick: (() -> Unit)? = null,
    onPauseClick: (() -> Unit)? = null,
    onResumeClick: (() -> Unit)? = null,
    onStopClick: (() -> Unit)? = null,
    /** Ab hier weitermachen. Null blendet den Knopf aus, etwa waehrend eine
     *  Antwort noch streamt: da gibt es noch nichts, wohin man zurueck koennte. */
    onRewindClick: (() -> Unit)? = null,
    modifier: Modifier = Modifier,
) {
    val pocket = PocketTheme.colors
    val copy = rememberCopyHandler(text)
    // Assistant-Antwort hat KEINE eigene Bubble mehr — der Text nimmt fast die
    // volle Display-Breite ein. Long-Press ist jetzt nativ verfügbar dank
    // SelectionContainer (Wrap in ChatScreen) — User kann Text wie auf einer
    // Webseite markieren statt direkt zu kopieren. Zum Komplett-Kopieren gibt's
    // unten ein eigenes Copy-Icon neben dem Vorlese-Button.
    Column(
        modifier = modifier
            .fillMaxWidth()
            .padding(start = 16.dp, end = 16.dp, top = 12.dp, bottom = 8.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            // Das Markenzeichen wabert, solange auf das erste Wort gewartet wird,
            // und fliesst danach von selbst in die ruhige Silhouette zurueck.
            // Die Komponente rendert im Ruhezustand PocketBrandMark, deshalb hier
            // kein hartes Umschalten: das gaebe einen sichtbaren Sprung.
            PocketThinkingBlob(
                size = PocketIconSize.Regular,
                // isBlank statt isEmpty: faengt der Stream mit einem Umbruch oder
                // Leerzeichen an, ist noch kein Wort da und die Masse darf nicht
                // vorzeitig zur Ruhe kommen.
                isThinking = text.isBlank() && isStreaming,
            )
            Spacer(Modifier.width(8.dp))
            Text(
                text = stringResource(R.string.app_name).uppercase(Locale.ROOT),
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.primary,
            )
        }
        Spacer(Modifier.height(8.dp))
        // Denk-Block: animiertes Fade+Expand beim Erscheinen, animiertes
        // Shrink+Fade sobald die echte Antwort losgeht. Bleibt weg sobald
        // text einsetzt, auch wenn thinkingText noch was enthält.
        val showThinking = thinkingText.isNotBlank() && text.isEmpty()
        AnimatedVisibility(
            visible = showThinking,
            enter = fadeIn(animationSpec = tween(200)) +
                    expandVertically(animationSpec = tween(220), expandFrom = Alignment.Top),
            exit = fadeOut(animationSpec = tween(180)) +
                    shrinkVertically(animationSpec = tween(220), shrinkTowards = Alignment.Top),
        ) {
            Column {
                ThinkingBlock(text = thinkingText, isLive = isStreaming)
                Spacer(Modifier.height(4.dp))
            }
        }
        Box(modifier = Modifier.fillMaxWidth()) {
            if (text.isEmpty() && isStreaming) {
                TypingDots(color = pocket.onBubbleAssistant.copy(alpha = 0.6f))
            } else {
                Column {
                    MarkdownText(
                        text = text,
                        color = MaterialTheme.colorScheme.onBackground,
                    )
                    if (isStreaming) {
                        Spacer(Modifier.height(8.dp))
                        TypingDots(color = pocket.onBubbleAssistant.copy(alpha = 0.6f))
                    }
                }
            }
        }
        // Im Chat erzeugte Bilder. Sie erscheinen sofort, sobald das Werkzeug
        // fertig ist, und bleiben nach dem Neuladen an der Nachricht haengen.
        if (attachments.isNotEmpty()) {
            Spacer(Modifier.height(8.dp))
            AttachmentsStrip(attachments, alignEnd = false)
        }
        // Tool-Row: Vorlese-Button + Copy-Button nebeneinander. Erscheint nur
        // wenn Streaming fertig und Text da ist.
        if (onSpeakClick != null && !isStreaming && text.isNotBlank()) {
                // Um die halbe Knopf-Leerflaeche (48 - 18) / 2 nach links
                // versetzt: so beginnt das erste Symbol genau an der Textkante.
                Row(
                    modifier = Modifier.offset(x = (-15).dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    when (ttsState) {
                        TtsState.Idle -> IconButton(
                            onClick = onSpeakClick,
                            modifier = Modifier.size(48.dp),
                        ) {
                            Icon(
                                PocketIcons.VolumeUp,
                                contentDescription = stringResource(R.string.bubble_read_aloud),
                                tint = MaterialTheme.colorScheme.onSurfaceVariant,
                                modifier = Modifier.size(PocketIconSize.Small),
                            )
                        }
                        TtsState.Loading -> Box(
                            modifier = Modifier.size(48.dp),
                            contentAlignment = Alignment.Center,
                        ) {
                            CircularProgressIndicator(
                                modifier = Modifier.size(PocketIconSize.Small),
                                strokeWidth = 2.dp,
                            )
                        }
                        TtsState.Playing -> {
                            // Pause + Abbrechen nebeneinander
                            IconButton(
                                onClick = { onPauseClick?.invoke() },
                                modifier = Modifier.size(48.dp),
                            ) {
                                Icon(
                                    PocketIcons.Pause,
                                    contentDescription = stringResource(R.string.bubble_pause),
                                    tint = MaterialTheme.colorScheme.primary,
                                    modifier = Modifier.size(PocketIconSize.Small),
                                )
                            }
                            IconButton(
                                onClick = { onStopClick?.invoke() },
                                modifier = Modifier.size(48.dp),
                            ) {
                                Icon(
                                    PocketIcons.Stop,
                                    contentDescription = stringResource(R.string.bubble_cancel),
                                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                                    modifier = Modifier.size(PocketIconSize.Small),
                                )
                            }
                        }
                        TtsState.Paused -> {
                            // Weiter + Abbrechen nebeneinander
                            IconButton(
                                onClick = { onResumeClick?.invoke() },
                                modifier = Modifier.size(48.dp),
                            ) {
                                Icon(
                                    PocketIcons.Play,
                                    contentDescription = stringResource(R.string.bubble_resume),
                                    tint = MaterialTheme.colorScheme.primary,
                                    modifier = Modifier.size(PocketIconSize.Small),
                                )
                            }
                            IconButton(
                                onClick = { onStopClick?.invoke() },
                                modifier = Modifier.size(48.dp),
                            ) {
                                Icon(
                                    PocketIcons.Stop,
                                    contentDescription = stringResource(R.string.bubble_cancel),
                                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                                    modifier = Modifier.size(PocketIconSize.Small),
                                )
                            }
                        }
                    } // when
                    // Copy-Icon (immer sichtbar in der Tool-Row) — kopiert die
                    // gesamte Antwort in die Zwischenablage. Ersetzt den
                    // früheren Long-Click-auf-Bubble (war kollidierend mit der
                    // nativen Text-Selektion).
                    IconButton(
                        onClick = copy,
                        modifier = Modifier.size(48.dp),
                    ) {
                        Icon(
                            PocketIcons.Copy,
                            contentDescription = stringResource(R.string.bubble_copy),
                            tint = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.size(PocketIconSize.Small),
                        )
                    }
                    // Ab hier weitermachen. Bewusst in derselben Reihe wie
                    // Vorlesen und Kopieren statt als auffaelliger Knopf: es ist
                    // eine Nebenhandlung, keine Hauptsache.
                    if (onRewindClick != null) {
                        IconButton(
                            onClick = onRewindClick,
                            modifier = Modifier.size(48.dp),
                        ) {
                            Icon(
                                PocketIcons.History,
                                contentDescription = stringResource(R.string.bubble_rewind),
                                tint = MaterialTheme.colorScheme.onSurfaceVariant,
                                modifier = Modifier.size(PocketIconSize.Small),
                            )
                        }
                    }
                } // Row
            } // if (onSpeakClick != null …)
        } // Column outer
}

@Composable
fun CompactionNotice(
    modifier: Modifier = Modifier,
    text: String,
) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 6.dp),
        horizontalArrangement = Arrangement.Center,
    ) {
        Box(
            modifier = Modifier
                .clip(RoundedCornerShape(50))
                .background(MaterialTheme.colorScheme.primary.copy(alpha = 0.1f))
                .border(
                    1.dp,
                    MaterialTheme.colorScheme.primary.copy(alpha = 0.16f),
                    RoundedCornerShape(50),
                )
                .padding(horizontal = 12.dp, vertical = 6.dp),
        ) {
            Text(
                text,
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
fun AttachmentsStrip(
    attachments: List<AttachmentRefDto>,
    alignEnd: Boolean = false,
) {
    Row(
        horizontalArrangement = if (alignEnd) Arrangement.spacedBy(8.dp, Alignment.End) else Arrangement.spacedBy(8.dp),
        modifier = Modifier.fillMaxWidth(),
    ) {
        attachments.take(3).forEach { att ->
            AttachmentChip(att)
        }
        if (attachments.size > 3) {
            Text(
                "+${attachments.size - 3}",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(horizontal = 8.dp, vertical = 8.dp),
            )
        }
    }
}

@Composable
private fun AttachmentChip(att: AttachmentRefDto) {
    val isImage = att.mimeType.startsWith("image/")
    if (isImage) {
        // Inline-Thumbnail via Coil. URL enthält ?token=…, weil das ImageView
        // keine Auth-Header mitschicken kann (genau wie ExoPlayer beim TTS).
        val context = LocalContext.current
        val container = remember {
            (context.applicationContext as de.smartzone.pocketclaude.PocketClaudeApp).container
        }
        val settings by container.settingsRepository.settingsFlow
            .collectAsState(initial = de.smartzone.pocketclaude.data.AppSettings())
        val url = remember(settings.serverUrl, settings.serverToken, att.id) {
            "${settings.serverUrl}/attachments/${att.id}" +
                "?token=${android.net.Uri.encode(settings.serverToken)}"
        }
        // FIX (2026-05-19): Slot mit FESTEN 200×200 dp reservieren statt
        // widthIn/heightIn-MAX. Grund: ohne intrinsische Größe rendert Coil
        // den Slot anfangs mit 0 dp Höhe — sobald das Bild geladen ist, springt
        // er auf die finale Größe und schiebt alle darunter liegenden Items
        // nach unten. Beim Lesen wirkt das wie ein „Sprung nach unten" der
        // Ansicht. Mit fester Slot-Größe ist das Layout sofort stabil, Coil
        // füllt den Slot via ContentScale.Crop.
        coil3.compose.AsyncImage(
            model = url,
            contentDescription = att.filename,
            contentScale = androidx.compose.ui.layout.ContentScale.Crop,
            modifier = Modifier
                .size(width = 200.dp, height = 200.dp)
                .clip(RoundedCornerShape(PocketRadius.Medium))
                .background(MaterialTheme.colorScheme.surfaceVariant),
        )
        return
    }
    // Nicht-Bilder weiterhin als Chip mit Icon + Filename
    Row(
        modifier = Modifier
            .clip(RoundedCornerShape(PocketRadius.Small))
            .background(MaterialTheme.colorScheme.surfaceVariant)
            .padding(horizontal = 12.dp, vertical = 8.dp)
            .widthIn(max = 220.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        androidx.compose.material3.Icon(
            PocketIcons.Document,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.size(PocketIconSize.Small),
        )
        Spacer(Modifier.width(8.dp))
        Text(
            att.filename,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}
