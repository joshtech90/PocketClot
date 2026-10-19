package de.smartzone.pocketclaude.ui.chat

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.MutableTransitionState
import androidx.compose.animation.core.animateDpAsState
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.scaleIn
import androidx.compose.animation.scaleOut
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsFocusedAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.ime
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.union
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.TransformOrigin
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.TextRange
import androidx.compose.ui.text.input.TextFieldValue
import androidx.compose.ui.text.style.LineHeightStyle
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Popup
import androidx.compose.ui.window.PopupProperties
import coil3.compose.AsyncImage
import de.smartzone.pocketclaude.R
import de.smartzone.pocketclaude.ui.components.MicButton
import de.smartzone.pocketclaude.ui.components.MicState
import de.smartzone.pocketclaude.ui.theme.PocketIconSize
import de.smartzone.pocketclaude.ui.theme.PocketIcons
import de.smartzone.pocketclaude.ui.theme.PocketRadius

/**
 * Eingabefeld nach dem Vorbild der ChatGPT-App (Joscha 19.10.2026: "eins zu
 * eins klonen", Denktiefe bleibt oben in der Leiste). Vermessen am Handy:
 *
 * - Leer und ohne Fokus eine einzeilige Pille: Plus | Platzhalter | Mikrofon |
 *   runder Knopf. Mit Fokus, Text oder Anhaengen waechst die Karte: Text oben,
 *   darunter die Knopfreihe.
 * - Der runde Knopf startet bei leerem Feld das Sprachgespraech (Auto-Modus),
 *   mit Inhalt sendet er, waehrend einer Antwort stoppt er.
 * - Anhaenge liegen oben IN der Karte, Bilder als Vorschau.
 *
 * Das Textfeld bleibt in beiden Formen dasselbe Element, nur seine Abstaende
 * aendern sich. Ein Wechsel zwischen zwei Layouts wuerde beim ersten Antippen
 * den Fokus und damit die Tastatur wieder verlieren.
 */
@Composable
internal fun ChatComposer(
    value: String,
    onChange: (String) -> Unit,
    pending: List<PendingAttachment>,
    onRemovePending: (PendingAttachment) -> Unit,
    onSend: () -> Unit,
    onStop: () -> Unit,
    onCamera: () -> Unit,
    onPhotos: () -> Unit,
    onFiles: () -> Unit,
    onVoiceConversation: () -> Unit,
    sending: Boolean,
    voiceState: VoiceState,
    voiceEnabled: Boolean,
    onMicTap: () -> Unit,
    onMicCancel: () -> Unit,
) {
    val interaction = remember { MutableInteractionSource() }
    val focused by interaction.collectIsFocusedAsState()
    val focusRequester = remember { FocusRequester() }
    val focusManager = LocalFocusManager.current
    val keyboard = LocalSoftwareKeyboardController.current
    val menuState = remember { MutableTransitionState(false) }

    // Eigener Cursor-Zustand: Kommt Text von aussen (Diktat, geteilter Text),
    // steht der Cursor danach am Ende statt am Anfang (Joscha 19.10.2026).
    var fieldState by remember { mutableStateOf(TextFieldValue(value, TextRange(value.length))) }
    val fieldValue = if (fieldState.text == value) fieldState
        else TextFieldValue(value, TextRange(value.length))

    val expanded = focused || value.isNotEmpty() || pending.isNotEmpty()
    val anim = tween<androidx.compose.ui.unit.Dp>(durationMillis = 180)
    // Eingeklappt: Zeile mittig in 48 dp, links Platz fuer Plus, rechts fuer
    // Mikrofon und Rundknopf. Ausgeklappt: 16 dp rundum, unten die Knopfreihe.
    val padStart by animateDpAsState(if (expanded) 16.dp else BUTTON, anim, label = "padStart")
    val padEnd by animateDpAsState(if (expanded) 16.dp else BUTTON * 2 + END_GAP, anim, label = "padEnd")
    val padTop by animateDpAsState(
        if (!expanded) 12.dp else if (pending.isNotEmpty()) 8.dp else 16.dp, anim, label = "padTop",
    )
    val padBottom by animateDpAsState(if (expanded) BUTTON + 4.dp else 12.dp, anim, label = "padBottom")

    // Volle 24-dp-Zeile auch bei einer einzigen Zeile. Der Standard schneidet
    // den Zeilenabstand oben und unten weg; dann sass der Text 3 dp zu hoch
    // und die Karte war niedriger als bei ChatGPT.
    val fieldStyle = MaterialTheme.typography.bodyLarge.copy(
        lineHeightStyle = LineHeightStyle(LineHeightStyle.Alignment.Center, LineHeightStyle.Trim.None),
    )
    val anyUploading = pending.any { it.uploading }
    val hasContent = value.isNotBlank() || pending.any { it.uploaded != null }
    val dark = MaterialTheme.colorScheme.background.luminance() < 0.5f
    val cardColor = if (dark) MaterialTheme.colorScheme.surfaceContainerHigh
        else MaterialTheme.colorScheme.surfaceContainerLowest

    Box(
        modifier = Modifier
            .fillMaxWidth()
            // Max von IME und Navigation-Bar, damit beide Insets nicht addiert werden.
            .windowInsetsPadding(WindowInsets.ime.union(WindowInsets.navigationBars))
            .padding(start = 12.dp, end = 12.dp, top = 8.dp, bottom = 12.dp),
    ) {
        Surface(
            modifier = Modifier.fillMaxWidth(),
            shape = RoundedCornerShape(PocketRadius.XLarge),
            color = cardColor,
            contentColor = MaterialTheme.colorScheme.onSurface,
            shadowElevation = 3.dp,
        ) {
            Column(
                // Antippen irgendwo auf der Karte setzt den Cursor ins Feld,
                // wie bei ChatGPT, nicht nur ein Treffer auf die Textzeile.
                modifier = Modifier.clickable(
                    interactionSource = remember { MutableInteractionSource() },
                    indication = null,
                ) {
                    focusRequester.requestFocus()
                    keyboard?.show()
                },
            ) {
                AnimatedVisibility(visible = pending.isNotEmpty()) {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .horizontalScroll(rememberScrollState())
                            .padding(start = 12.dp, end = 12.dp, top = 12.dp),
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        pending.forEach { p ->
                            PendingTile(p, onRemove = { onRemovePending(p) })
                        }
                    }
                }
                Box(modifier = Modifier.fillMaxWidth()) {
                    BasicTextField(
                        value = fieldValue,
                        onValueChange = {
                            fieldState = it
                            if (it.text != value) onChange(it.text)
                        },
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(start = padStart, end = padEnd, top = padTop, bottom = padBottom)
                            .focusRequester(focusRequester),
                        interactionSource = interaction,
                        textStyle = fieldStyle.copy(color = MaterialTheme.colorScheme.onSurface),
                        cursorBrush = SolidColor(MaterialTheme.colorScheme.primary),
                        maxLines = 8,
                        decorationBox = { inner ->
                            Box {
                                if (value.isEmpty()) {
                                    Text(
                                        stringResource(R.string.hint_message),
                                        style = fieldStyle,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.8f),
                                        maxLines = 1,
                                        overflow = TextOverflow.Ellipsis,
                                    )
                                }
                                inner()
                            }
                        },
                    )

                    IconButton(
                        onClick = {
                            focusManager.clearFocus()
                            keyboard?.hide()
                            menuState.targetState = true
                        },
                        modifier = Modifier.align(Alignment.BottomStart).size(BUTTON),
                    ) {
                        Icon(
                            PocketIcons.AddLarge,
                            contentDescription = stringResource(R.string.chat_attach),
                            tint = MaterialTheme.colorScheme.onSurface,
                        )
                    }

                    Row(
                        modifier = Modifier
                            .align(Alignment.BottomEnd)
                            .padding(end = END_GAP),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        // Tippen startet/stoppt das Diktat, langes Druecken
                        // waehrend der Aufnahme verwirft sie.
                        MicButton(
                            state = when (voiceState) {
                                VoiceState.Idle -> MicState.Idle
                                VoiceState.Recording -> MicState.Recording
                                VoiceState.Transcribing -> MicState.Transcribing
                            },
                            onTap = onMicTap,
                            onCancel = onMicCancel,
                            enabled = voiceState == VoiceState.Recording ||
                                (voiceEnabled && voiceState != VoiceState.Transcribing),
                            idleTint = MaterialTheme.colorScheme.onSurface,
                        )
                        when {
                            sending -> RoundAction(PocketIcons.Stop, stringResource(R.string.stop), true, onStop)
                            hasContent || anyUploading -> RoundAction(
                                PocketIcons.ArrowUpward,
                                stringResource(R.string.send),
                                // Erst senden, wenn alle Uploads fertig sind:
                                // send() nimmt nur hochgeladene Anhaenge mit,
                                // ein noch laufender ginge sonst stumm verloren.
                                enabled = hasContent && !anyUploading,
                                onClick = onSend,
                            )
                            else -> RoundAction(
                                PocketIcons.VoiceMode,
                                stringResource(R.string.chat_voice_conversation),
                                true,
                                onVoiceConversation,
                            )
                        }
                    }

                    if (menuState.currentState || menuState.targetState) {
                        AttachMenu(
                            state = menuState,
                            onCamera = onCamera,
                            onPhotos = onPhotos,
                            onFiles = onFiles,
                        )
                    }
                }
            }
        }
    }
}

/** Runder Knopf rechts aussen: 32 dp Scheibe in einer 48-dp-Trefferflaeche. */
@Composable
private fun RoundAction(icon: ImageVector, description: String, enabled: Boolean, onClick: () -> Unit) {
    Box(
        modifier = Modifier
            .size(BUTTON)
            .clip(CircleShape)
            .clickable(enabled = enabled, onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Box(
            modifier = Modifier
                .size(32.dp)
                .clip(CircleShape)
                .background(
                    if (enabled) MaterialTheme.colorScheme.primary
                    else MaterialTheme.colorScheme.surfaceVariant
                ),
            contentAlignment = Alignment.Center,
        ) {
            Icon(
                icon,
                contentDescription = description,
                tint = if (enabled) MaterialTheme.colorScheme.onPrimary
                    else MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.size(PocketIconSize.Regular),
            )
        }
    }
}

/**
 * Plus-Menue: Karte, die unten links buendig auf dem Eingabefeld aufgeht,
 * je Eintrag ein grauer Kreis mit Symbol und daneben die Beschriftung.
 */
@Composable
private fun AttachMenu(
    state: MutableTransitionState<Boolean>,
    onCamera: () -> Unit,
    onPhotos: () -> Unit,
    onFiles: () -> Unit,
) {
    val close = { state.targetState = false }
    Popup(
        alignment = Alignment.BottomStart,
        onDismissRequest = close,
        properties = PopupProperties(focusable = true),
    ) {
        AnimatedVisibility(
            visibleState = state,
            enter = fadeIn(tween(120)) + scaleIn(tween(160), initialScale = 0.85f, transformOrigin = TransformOrigin(0f, 1f)),
            exit = fadeOut(tween(100)) + scaleOut(tween(120), targetScale = 0.85f, transformOrigin = TransformOrigin(0f, 1f)),
        ) {
            val dark = MaterialTheme.colorScheme.background.luminance() < 0.5f
            Surface(
                modifier = Modifier.width(296.dp),
                shape = RoundedCornerShape(PocketRadius.XLarge),
                color = if (dark) MaterialTheme.colorScheme.surfaceContainerHigh
                    else MaterialTheme.colorScheme.surfaceContainerLowest,
                contentColor = MaterialTheme.colorScheme.onSurface,
                shadowElevation = 8.dp,
            ) {
                Column(modifier = Modifier.padding(vertical = 8.dp)) {
                    AttachMenuItem(PocketIcons.Camera, stringResource(R.string.chat_attach_camera_menu)) { close(); onCamera() }
                    AttachMenuItem(PocketIcons.Image, stringResource(R.string.chat_attach_image_menu)) { close(); onPhotos() }
                    AttachMenuItem(PocketIcons.AttachFile, stringResource(R.string.chat_attach_file_menu)) { close(); onFiles() }
                }
            }
        }
    }
}

@Composable
private fun AttachMenuItem(icon: ImageVector, label: String, onClick: () -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .height(60.dp)
            .clickable(onClick = onClick)
            .padding(horizontal = 16.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            modifier = Modifier
                .size(44.dp)
                .clip(CircleShape)
                .background(MaterialTheme.colorScheme.surfaceVariant),
            contentAlignment = Alignment.Center,
        ) {
            Icon(icon, contentDescription = null, modifier = Modifier.size(PocketIconSize.Regular))
        }
        Spacer(Modifier.width(12.dp))
        Text(label, style = MaterialTheme.typography.bodyLarge)
    }
}

/** Anhang oben in der Karte: Bilder als Vorschau, Dateien als Kachel mit Namen. */
@Composable
private fun PendingTile(p: PendingAttachment, onRemove: () -> Unit) {
    Box {
        if (p.isImage) {
            AsyncImage(
                model = p.uri,
                contentDescription = p.filename,
                contentScale = ContentScale.Crop,
                modifier = Modifier
                    .size(TILE)
                    .clip(RoundedCornerShape(PocketRadius.Medium))
                    .background(MaterialTheme.colorScheme.surfaceVariant),
            )
        } else {
            Row(
                modifier = Modifier
                    .height(TILE)
                    .widthIn(max = 220.dp)
                    .clip(RoundedCornerShape(PocketRadius.Medium))
                    .background(MaterialTheme.colorScheme.surfaceVariant)
                    .padding(start = 12.dp, end = 28.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(
                    PocketIcons.Document,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.size(PocketIconSize.Regular),
                )
                Spacer(Modifier.width(8.dp))
                Text(
                    p.filename,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
        if (p.uploading || p.error != null) {
            Box(
                modifier = Modifier
                    .matchParentSize()
                    .clip(RoundedCornerShape(PocketRadius.Medium))
                    .background(Color.Black.copy(alpha = 0.35f)),
                contentAlignment = Alignment.Center,
            ) {
                if (p.uploading) {
                    CircularProgressIndicator(
                        color = Color.White,
                        strokeWidth = 2.dp,
                        modifier = Modifier.size(PocketIconSize.Regular),
                    )
                } else {
                    Icon(
                        PocketIcons.Error,
                        contentDescription = p.error,
                        tint = MaterialTheme.colorScheme.error,
                        modifier = Modifier.size(PocketIconSize.Regular),
                    )
                }
            }
        }
        Box(
            modifier = Modifier
                .align(Alignment.TopEnd)
                .padding(4.dp)
                .size(20.dp)
                .clip(CircleShape)
                .background(Color.Black.copy(alpha = 0.6f))
                .clickable(onClick = onRemove),
            contentAlignment = Alignment.Center,
        ) {
            Icon(
                PocketIcons.Close,
                contentDescription = stringResource(R.string.chat_remove),
                tint = Color.White,
                modifier = Modifier.size(PocketIconSize.Marker),
            )
        }
    }
}

private val BUTTON = 48.dp
private val END_GAP = 2.dp
private val TILE = 56.dp
