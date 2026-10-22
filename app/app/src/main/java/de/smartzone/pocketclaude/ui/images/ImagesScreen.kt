package de.smartzone.pocketclaude.ui.images

import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.border
import androidx.compose.material3.FilledTonalIconButton
import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.provider.MediaStore
import android.widget.Toast
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.consumeWindowInsets
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.FlowRowScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.LocalContentColor
import androidx.compose.material3.Button
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import coil3.compose.AsyncImage
import de.smartzone.pocketclaude.PocketClaudeApp
import de.smartzone.pocketclaude.R
import de.smartzone.pocketclaude.data.AppSettings
import de.smartzone.pocketclaude.data.ImageGenerateAttachment
import de.smartzone.pocketclaude.data.ImageProviderDto
import de.smartzone.pocketclaude.ui.components.PocketBackdrop
import de.smartzone.pocketclaude.ui.components.PocketIconButton
import de.smartzone.pocketclaude.ui.components.PocketScreenTitle
import de.smartzone.pocketclaude.ui.theme.PocketTheme
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.util.Locale
import de.smartzone.pocketclaude.ui.components.PocketChoiceChip
import de.smartzone.pocketclaude.ui.components.PocketCard
import de.smartzone.pocketclaude.ui.theme.PocketIconSize
import de.smartzone.pocketclaude.ui.theme.PocketRadius
import de.smartzone.pocketclaude.ui.theme.PocketIcons

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
fun ImagesScreen(
    vm: ImageGenViewModel,
    onBack: () -> Unit,
    onOpenSettings: () -> Unit,
) {
    val state by vm.state.collectAsState()
    val context = LocalContext.current
    val container = remember {
        (context.applicationContext as PocketClaudeApp).container
    }
    val appSettings by container.settingsRepository.settingsFlow
        .collectAsState(initial = AppSettings())

    // Fullscreen-Vorschau
    var fullscreenAttachment by remember { mutableStateOf<ImageGenerateAttachment?>(null) }
    // Lösch-Bestätigung
    var entryToDelete by remember { mutableStateOf<GeneratedImageEntry?>(null) }
    var clearAllOpen by remember { mutableStateOf(false) }

    // Bild vom Geraet als Vorlage. Derselbe Picker wie im Chat, damit sich das
    // Auswaehlen an beiden Stellen gleich anfuehlt.
    val referenceName = stringResource(R.string.image_reference_default_name)
    val photoPicker = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.PickVisualMedia(),
    ) { uri: Uri? ->
        if (uri != null) vm.addReferenceFromUri(uri, referenceName)
    }

    PocketBackdrop(Modifier.fillMaxSize()) {
    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    PocketScreenTitle(
                        eyebrow = stringResource(R.string.app_name),
                        title = stringResource(R.string.image_screen_title),
                    )
                },
                navigationIcon = {
                    PocketIconButton(
                        icon = PocketIcons.ArrowBack,
                        contentDescription = stringResource(R.string.action_back),
                        onClick = onBack,
                        modifier = Modifier.padding(start = 8.dp),
                    )
                },
                actions = {
                    if (state.history.isNotEmpty()) {
                        PocketIconButton(
                            icon = PocketIcons.Delete,
                            contentDescription = stringResource(R.string.image_clear_history),
                            onClick = { clearAllOpen = true },
                        )
                        Spacer(Modifier.width(4.dp))
                    }
                    PocketIconButton(
                        icon = PocketIcons.Settings,
                        contentDescription = stringResource(R.string.image_open_settings),
                        onClick = onOpenSettings,
                        modifier = Modifier.padding(end = 8.dp),
                    )
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = Color.Transparent,
                ),
            )
        },
        containerColor = Color.Transparent,
        contentColor = MaterialTheme.colorScheme.onBackground,
    ) { pad ->
        val cfg = state.config
        when {
            state.configLoading -> {
                Box(Modifier.fillMaxSize().padding(pad), contentAlignment = Alignment.Center) {
                    CircularProgressIndicator()
                }
            }
            cfg == null -> {
                Box(Modifier.fillMaxSize().padding(pad).padding(24.dp), contentAlignment = Alignment.Center) {
                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                        Text(
                            stringResource(R.string.image_config_load_failed),
                            style = MaterialTheme.typography.bodyMedium,
                        )
                        Spacer(Modifier.height(8.dp))
                        Text(
                            state.configError.orEmpty(),
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.error,
                        )
                        Spacer(Modifier.height(16.dp))
                        FilledTonalButton(onClick = { vm.refreshConfig() }) {
                            Text(stringResource(R.string.action_retry))
                        }
                    }
                }
            }
            !cfg.configured -> {
                // Setup-Hinweis falls kein API-Key
                Column(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(pad)
                        .padding(24.dp),
                    verticalArrangement = Arrangement.Center,
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    Icon(
                        PocketIcons.Sparkle,
                        contentDescription = null,
                        modifier = Modifier.size(PocketIconSize.Hero),
                        tint = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Spacer(Modifier.height(12.dp))
                    Text(
                        stringResource(R.string.image_disabled_title),
                        style = MaterialTheme.typography.titleMedium,
                    )
                    Spacer(Modifier.height(6.dp))
                    Text(
                        stringResource(R.string.image_disabled_body),
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Spacer(Modifier.height(20.dp))
                    FilledTonalButton(onClick = onOpenSettings) {
                        Text(stringResource(R.string.image_open_settings_button))
                    }
                }
            }
            else -> {
                LazyColumn(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(pad)
                        .consumeWindowInsets(pad)
                        .imePadding(),
                    contentPadding = PaddingValues(bottom = 12.dp),
                ) {
                    item(key = "generator") {
                        GeneratorCard(
                            state = state,
                            vm = vm,
                            serverBaseUrl = appSettings.serverUrl,
                            serverToken = appSettings.serverToken,
                            onPickImage = {
                                photoPicker.launch(
                                    PickVisualMediaRequest(
                                        ActivityResultContracts.PickVisualMedia.ImageOnly
                                    )
                                )
                            },
                        )
                    }
                    if (state.history.isEmpty()) {
                        item(key = "empty") {
                            // Leerzustand mit Illustration (Klumpen vor Bildrahmen,
                            // Entscheidung 22.10.2026). Nur hier, ohne Animation;
                            // der Hinweistext bleibt, damit ein fehlender
                            // Bildanbieter weiter erkennbar ist.
                            Column(
                                Modifier
                                    .fillMaxWidth()
                                    .padding(horizontal = 24.dp, vertical = 32.dp),
                                horizontalAlignment = Alignment.CenterHorizontally,
                                verticalArrangement = Arrangement.spacedBy(16.dp),
                            ) {
                                Image(
                                    painter = painterResource(R.drawable.img_empty_images),
                                    contentDescription = null,
                                    modifier = Modifier.size(112.dp),
                                )
                                Text(
                                    stringResource(R.string.image_history_empty),
                                    style = MaterialTheme.typography.bodyMedium,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    textAlign = androidx.compose.ui.text.style.TextAlign.Center,
                                )
                            }
                        }
                    } else {
                        items(state.history, key = { it.timestampMs }) { entry ->
                            HistoryRow(
                                entry = entry,
                                serverBaseUrl = appSettings.serverUrl,
                                serverToken = appSettings.serverToken,
                                canEdit = state.canEditReferences,
                                onEditImage = { att -> vm.addReferenceFromAttachment(att) },
                                onImageClick = { att -> fullscreenAttachment = att },
                                onDelete = { entryToDelete = entry },
                            )
                        }
                    }
                }
            }
        }
    }
    }

    // Fullscreen-Vorschau
    fullscreenAttachment?.let { att ->
        de.smartzone.pocketclaude.ui.components.ImageViewerDialog(
            image = de.smartzone.pocketclaude.ui.components.ViewerImage(att.id, att.filename, att.mimeType),
            serverBaseUrl = appSettings.serverUrl,
            serverToken = appSettings.serverToken,
            onDismiss = { fullscreenAttachment = null },
        )
    }

    // Lösch-Bestätigung
    entryToDelete?.let { entry ->
        AlertDialog(
            onDismissRequest = { entryToDelete = null },
            title = { Text(stringResource(R.string.image_delete_generation_title)) },
            text = { Text(stringResource(R.string.image_delete_generation_body)) },
            confirmButton = {
                TextButton(onClick = {
                    vm.deleteEntry(entry)
                    entryToDelete = null
                }) { Text(stringResource(R.string.action_delete), color = MaterialTheme.colorScheme.error) }
            },
            dismissButton = {
                TextButton(onClick = { entryToDelete = null }) { Text(stringResource(R.string.action_cancel)) }
            },
        )
    }

    if (clearAllOpen) {
        AlertDialog(
            onDismissRequest = { clearAllOpen = false },
            title = { Text(stringResource(R.string.image_clear_all_title)) },
            text = { Text(stringResource(R.string.image_clear_all_body)) },
            confirmButton = {
                TextButton(onClick = {
                    vm.clearHistory()
                    clearAllOpen = false
                }) { Text(stringResource(R.string.image_clear_all_confirm), color = MaterialTheme.colorScheme.error) }
            },
            dismissButton = {
                TextButton(onClick = { clearAllOpen = false }) { Text(stringResource(R.string.action_cancel)) }
            },
        )
    }
}

/**
 * Eine beschriftete Reihe von Auswahl-Chips. Ohne Beschriftung standen im
 * Generator drei Chip-Reihen untereinander, ohne dass erkennbar war, welche
 * wofuer ist.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun SubsectionRow(label: String, content: @Composable FlowRowScope.() -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(
            label,
            style = MaterialTheme.typography.titleSmall,
            color = MaterialTheme.colorScheme.onSurface,
        )
        FlowRow(
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
            content = content,
        )
    }
}


/**
 * Anzeigename eines Bild-Anbieters.
 *
 * Der Server liefert zwar ein `label`, das ist aber ein fester deutscher Text
 * und wuerde in den anderen sechs Sprachen durchschlagen. Fuer die bekannten
 * Kennungen wird deshalb uebersetzt, unbekannte behalten das Server-Label:
 * so taucht ein spaeter dazukommender Anbieter trotzdem auf.
 */
@Composable
private fun imageProviderLabel(p: ImageProviderDto): String = when (p.id) {
    "both" -> stringResource(R.string.image_provider_both)
    "gemini" -> "Gemini"
    "gpt" -> "GPT"
    else -> p.label
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun GeneratorCard(
    state: ImageGenUiState,
    vm: ImageGenViewModel,
    serverBaseUrl: String,
    serverToken: String,
    onPickImage: () -> Unit,
) {
    val cfg = state.config ?: return
    PocketCard(
        modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
        spacing = 16.dp,
    ) {
        // Vorlagen. Sind welche da, wird bearbeitet statt neu erzeugt.
        ReferenceStrip(
            references = state.references,
            isUploading = state.isUploading,
            enabled = state.canEditReferences,
            serverBaseUrl = serverBaseUrl,
            serverToken = serverToken,
            onAdd = onPickImage,
            onRemove = vm::removeReference,
            onClear = vm::clearReferences,
        )

        // Prompt-Eingabe
        OutlinedTextField(
            value = state.prompt,
            onValueChange = vm::setPrompt,
            placeholder = {
                Text(stringResource(
                    if (state.isEditing) R.string.image_edit_prompt_placeholder
                    else R.string.image_prompt_placeholder
                ))
            },
            maxLines = 4,
            modifier = Modifier.fillMaxWidth(),
            shape = MaterialTheme.shapes.small,
            enabled = !state.isGenerating,
        )

        // Anbieter. Die frueher hier stehende Modellwahl ist entfallen:
        // welches Bildmodell laeuft, sagt der jeweilige Anbieter.
        if (cfg.providers.size > 1) {
            SubsectionRow(stringResource(R.string.image_provider_label)) {
                cfg.providers.forEach { p ->
                    PocketChoiceChip(
                        selected = p.id == state.selectedProvider,
                        onClick = { vm.setProvider(p.id) },
                        label = imageProviderLabel(p),
                        enabled = !state.isGenerating,
                    )
                }
            }
        }

        // Aufloesung. Fehlte bisher komplett, obwohl der Server sie laengst
        // versteht: die Einstellung war nur als Vorgabe da und wurde vom
        // Bilder-Screen nie mitgeschickt.
        if (cfg.imageSizes.isNotEmpty()) {
            SubsectionRow(stringResource(R.string.image_size_label)) {
                cfg.imageSizes.forEach { s ->
                    PocketChoiceChip(
                        selected = s.id == state.selectedSize,
                        onClick = { vm.setSize(s.id) },
                        label = s.id,
                        enabled = !state.isGenerating,
                    )
                }
            }
        }

        // Je Auswahl ein eigener Hinweis. Frueher stand hier ein einziger
        // Text, der von "beide zeichnen gleichzeitig" sprach: bei direkter
        // GPT-Wahl war das schlicht falsch.
        val providerHint = when (state.selectedProvider) {
            "both" -> R.string.image_both_hint
            "gpt" -> R.string.image_gpt_size_hint
            else -> null
        }
        if (providerHint != null) {
            Text(
                stringResource(providerHint),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }

        // Seitenverhaeltnis
        SubsectionRow(stringResource(R.string.image_aspect_label)) {
            cfg.aspectRatios.forEach { a ->
                PocketChoiceChip(
                    selected = a.id == state.selectedAspect,
                    onClick = { vm.setAspect(a.id) },
                    label = a.id,
                    enabled = !state.isGenerating,
                )
            }
        }

        // Anzahl
        SubsectionRow(stringResource(R.string.image_variants_label)) {
            for (n in 1..cfg.maxCandidates) {
                PocketChoiceChip(
                    selected = n == state.count,
                    onClick = { vm.setCount(n) },
                    label = n.toString(),
                    enabled = !state.isGenerating,
                )
            }
        }

        // Der Knopf sagt, was wirklich passiert: mit Vorlage wird
        // bearbeitet, ohne wird neu erzeugt.
        Button(
            onClick = { vm.generate() },
            enabled = !state.isGenerating && !state.isUploading && state.prompt.isNotBlank(),
            modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp),
        ) {
            if (state.isGenerating) {
                CircularProgressIndicator(
                    strokeWidth = 2.dp,
                    color = LocalContentColor.current,
                    modifier = Modifier.size(PocketIconSize.Small),
                )
                Spacer(Modifier.width(8.dp))
                // Einzeilig und ohne Kuerzung: sonst schob sich der Text in
                // das Auslassungszeichen und es sah aus wie ein Fehler.
                Text(
                    stringResource(
                        if (state.isEditing) R.string.image_editing
                        else R.string.image_generating
                    ),
                    maxLines = 1,
                    softWrap = false,
                )
            } else {
                Icon(
                    if (state.isEditing) PocketIcons.Brush else PocketIcons.Sparkle,
                    contentDescription = null, modifier = Modifier.size(PocketIconSize.Small),
                )
                Spacer(Modifier.width(8.dp))
                Text(stringResource(
                    if (state.isEditing) R.string.image_edit_button
                    else R.string.image_generate_button
                ))
            }
        }

        state.generationError?.let { err ->
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    err,
                    color = MaterialTheme.colorScheme.error,
                    style = MaterialTheme.typography.bodySmall,
                    modifier = Modifier.weight(1f),
                )
                TextButton(onClick = vm::clearError) { Text(stringResource(R.string.action_ok)) }
            }
        }
    
    }
}

/**
 * Der Vorlagen-Streifen ueber dem Prompt-Feld.
 *
 * Er ist immer sichtbar, auch ohne Vorlage: sonst waere nicht zu erkennen,
 * dass sich hier ueberhaupt Bilder hochladen lassen. Genau das war vorher das
 * Problem, der Bearbeiten-Weg existierte serverseitig, aber in der App gab es
 * keinen Knopf dafuer.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun ReferenceStrip(
    references: List<ReferenceImageUi>,
    isUploading: Boolean,
    enabled: Boolean,
    serverBaseUrl: String,
    serverToken: String,
    onAdd: () -> Unit,
    onRemove: (String) -> Unit,
    onClear: () -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                stringResource(
                    if (references.isEmpty()) R.string.image_reference_label
                    else R.string.image_reference_label_active
                ),
                style = MaterialTheme.typography.titleSmall,
                color = MaterialTheme.colorScheme.onSurface,
                modifier = Modifier.weight(1f),
            )
            if (references.isNotEmpty()) {
                TextButton(onClick = onClear, enabled = enabled) {
                    Text(stringResource(R.string.image_reference_clear))
                }
            }
        }

        FlowRow(
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            references.forEach { ref ->
                val url = remember(serverBaseUrl, serverToken, ref.id) {
                    "$serverBaseUrl/attachments/${ref.id}?token=${android.net.Uri.encode(serverToken)}"
                }
                Box {
                    AsyncImage(
                        model = url,
                        contentDescription = ref.label,
                        contentScale = ContentScale.Crop,
                        modifier = Modifier
                            .size(64.dp)
                            .clip(RoundedCornerShape(PocketRadius.Small))
                            .background(MaterialTheme.colorScheme.surface),
                    )
                    FilledTonalIconButton(
                        onClick = { onRemove(ref.id) },
                        enabled = enabled,
                        modifier = Modifier
                            .align(Alignment.TopEnd)
                            .size(22.dp),
                    ) {
                        Icon(PocketIcons.Close,
                             contentDescription = stringResource(R.string.image_reference_remove),
                             modifier = Modifier.size(PocketIconSize.Marker))
                    }
                }
            }

            // Hinzufuegen-Kachel, im selben Raster wie die Vorlagen.
            if (references.size < ImageGenViewModel.MAX_REFERENCES) {
                Box(
                    modifier = Modifier
                        .size(64.dp)
                        .clip(RoundedCornerShape(PocketRadius.Small))
                        .background(MaterialTheme.colorScheme.surfaceContainerHigh)
                        .border(1.dp, MaterialTheme.colorScheme.outlineVariant,
                                RoundedCornerShape(PocketRadius.Small))
                        .clickable(enabled = enabled && !isUploading) { onAdd() },
                    contentAlignment = Alignment.Center,
                ) {
                    if (isUploading) {
                        CircularProgressIndicator(strokeWidth = 2.dp,
                                                  modifier = Modifier.size(PocketIconSize.Small))
                    } else {
                        Icon(PocketIcons.AddPhoto,
                             contentDescription = stringResource(R.string.image_reference_add),
                             tint = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
            }
        }

        Text(
            stringResource(
                if (references.isEmpty()) R.string.image_reference_hint
                else R.string.image_reference_hint_active
            ),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}


@Composable
private fun HistoryRow(
    entry: GeneratedImageEntry,
    serverBaseUrl: String,
    serverToken: String,
    canEdit: Boolean,
    onEditImage: (ImageGenerateAttachment) -> Unit,
    onImageClick: (ImageGenerateAttachment) -> Unit,
    onDelete: () -> Unit,
) {
    PocketCard(modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp)) {
        // Header: Prompt-Snippet + Delete-Button
        Row(verticalAlignment = Alignment.Top) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    entry.prompt,
                    style = MaterialTheme.typography.bodyMedium,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
                Text(
                    stringResource(R.string.image_meta_line, entry.model, entry.aspectRatio, entry.attachments.size),
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            IconButton(onClick = onDelete, modifier = Modifier.size(48.dp)) {
                Icon(
                    PocketIcons.Delete,
                    contentDescription = stringResource(R.string.image_remove_entry),
                    modifier = Modifier.size(PocketIconSize.Regular),
                )
            }
        }
        // Bilder-Reihe (horizontal)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            entry.attachments.forEach { att ->
                val url = remember(serverBaseUrl, serverToken, att.id) {
                    "$serverBaseUrl/attachments/${att.id}?token=${android.net.Uri.encode(serverToken)}"
                }
                Box {
                    AsyncImage(
                        model = url,
                        contentDescription = att.filename,
                        contentScale = ContentScale.Crop,
                        modifier = Modifier
                            .size(width = 140.dp, height = 140.dp)
                            .clip(RoundedCornerShape(PocketRadius.Small))
                            .background(MaterialTheme.colorScheme.surface)
                            .clickable { onImageClick(att) },
                    )
                    // Ohne diesen Knopf muesste man ein erzeugtes Bild erst
                    // herunterladen und wieder hochladen, um damit
                    // weiterzuarbeiten.
                    FilledTonalIconButton(
                        onClick = { onEditImage(att) },
                        enabled = canEdit,
                        modifier = Modifier
                            .align(Alignment.BottomEnd)
                            .padding(4.dp)
                            .size(30.dp),
                    ) {
                        Icon(
                            PocketIcons.Brush,
                            contentDescription = stringResource(R.string.image_use_as_reference),
                            modifier = Modifier.size(PocketIconSize.Small),
                        )
                    }
                }
            }
        }
    
    }
}
