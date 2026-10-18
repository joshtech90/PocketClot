package de.smartzone.pocketclaude.ui.conversations

import androidx.activity.compose.BackHandler
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.ui.res.stringResource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.consumeWindowInsets
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight as FW
import androidx.compose.ui.text.withStyle
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import de.smartzone.pocketclaude.data.ConversationDto
import de.smartzone.pocketclaude.ui.components.PocketBackdrop
import de.smartzone.pocketclaude.ui.components.PocketBrandMark
import de.smartzone.pocketclaude.ui.components.PocketIconButton
import de.smartzone.pocketclaude.ui.components.PocketScreenTitle
import de.smartzone.pocketclaude.ui.theme.PocketTheme
import de.smartzone.pocketclaude.util.formatRelative
import de.smartzone.pocketclaude.ui.theme.PocketIcons

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ConversationsScreen(
    vm: ConversationsViewModel,
    onOpenChat: (String) -> Unit,
    onOpenSettings: () -> Unit,
    onBack: (() -> Unit)? = null,
) {
    val state by vm.state.collectAsState()
    val search by vm.search.collectAsState()
    var renamingId by remember { mutableStateOf<String?>(null) }
    var renamingTitle by remember { mutableStateOf("") }
    var confirmDelete by remember { mutableStateOf<String?>(null) }
    // Chat-Sperre: cid, dessen Sperre entfernt werden soll (PIN-Dialog), bzw.
    // Hinweis „erst PIN in Einstellungen setzen".
    var unlockTarget by remember { mutableStateOf<String?>(null) }
    var needPinNotice by remember { mutableStateOf(false) }
    var searchActive by remember { mutableStateOf(false) }
    // Multi-Select: per Long-Press starten, weitere Taps toggeln. Set leer = inaktiv.
    var selectedIds by remember { mutableStateOf<Set<String>>(emptySet()) }
    val selectionMode = selectedIds.isNotEmpty()
    var confirmBulkDelete by remember { mutableStateOf(false) }

    // System-Back: erst aus dem Selection-Mode raus, danach (falls verfügbar) normaler Back.
    BackHandler(enabled = selectionMode) {
        selectedIds = emptySet()
    }

    // Liste neu laden, sobald der Screen wieder in den Vordergrund kommt
    // (z.B. nach Rückkehr aus einem Chat oder App-Wiederöffnung). Sonst
    // sieht man neu angelegte Chats erst nach manuellem Pull-down.
    val lifecycleOwner = LocalLifecycleOwner.current
    DisposableEffect(lifecycleOwner) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_RESUME) {
                vm.refresh()
            }
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose { lifecycleOwner.lifecycle.removeObserver(observer) }
    }

    PocketBackdrop(Modifier.fillMaxSize()) {
    Scaffold(
        containerColor = Color.Transparent,
        contentColor = MaterialTheme.colorScheme.onBackground,
        topBar = {
            if (selectionMode) {
                // Selection-AppBar: zeigt Anzahl, "Alle auswählen", "Löschen".
                val loadedIds = (state as? ConversationsState.Loaded)?.conversations?.map { it.id }
                    ?: emptyList()
                val allSelected = loadedIds.isNotEmpty() && selectedIds.size == loadedIds.size
                TopAppBar(
                    title = {
                        Text(
                            stringResource(de.smartzone.pocketclaude.R.string.convo_selection_count, selectedIds.size),
                            style = MaterialTheme.typography.titleLarge,
                            fontWeight = FontWeight.SemiBold,
                        )
                    },
                    navigationIcon = {
                        IconButton(onClick = { selectedIds = emptySet() }) {
                            Icon(PocketIcons.Close, contentDescription = stringResource(de.smartzone.pocketclaude.R.string.convo_selection_cancel))
                        }
                    },
                    actions = {
                        IconButton(
                            onClick = {
                                selectedIds = if (allSelected) emptySet() else loadedIds.toSet()
                            }
                        ) {
                            Icon(
                                PocketIcons.SelectAll,
                                contentDescription = stringResource(if (allSelected) de.smartzone.pocketclaude.R.string.convo_deselect_all else de.smartzone.pocketclaude.R.string.convo_select_all),
                            )
                        }
                        IconButton(onClick = { confirmBulkDelete = true }) {
                            Icon(
                                PocketIcons.Delete,
                                contentDescription = stringResource(de.smartzone.pocketclaude.R.string.action_delete),
                                tint = MaterialTheme.colorScheme.error,
                            )
                        }
                    },
                    colors = TopAppBarDefaults.topAppBarColors(
                        containerColor = Color.Transparent,
                    ),
                )
            } else {
                TopAppBar(
                    title = {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            PocketBrandMark(size = 38.dp)
                            Spacer(Modifier.width(12.dp))
                            PocketScreenTitle(
                                eyebrow = stringResource(de.smartzone.pocketclaude.R.string.app_name),
                                title = stringResource(de.smartzone.pocketclaude.R.string.all_conversations),
                            )
                        }
                    },
                    navigationIcon = {
                        if (onBack != null) {
                            IconButton(onClick = onBack) {
                                Icon(
                                    PocketIcons.ArrowBack,
                                    contentDescription = stringResource(de.smartzone.pocketclaude.R.string.action_back),
                                )
                            }
                        }
                    },
                    actions = {
                        PocketIconButton(
                            icon = if (searchActive) PocketIcons.Close else PocketIcons.Search,
                            contentDescription = stringResource(if (searchActive) de.smartzone.pocketclaude.R.string.action_close else de.smartzone.pocketclaude.R.string.action_search),
                            onClick = { searchActive = !searchActive; if (!searchActive) vm.clearSearch() },
                        )
                        Spacer(Modifier.width(6.dp))
                        PocketIconButton(
                            icon = PocketIcons.Settings,
                            contentDescription = stringResource(de.smartzone.pocketclaude.R.string.title_settings),
                            onClick = onOpenSettings,
                            modifier = Modifier.padding(end = 8.dp),
                        )
                    },
                    colors = TopAppBarDefaults.topAppBarColors(
                        containerColor = Color.Transparent,
                    ),
                )
            }
        },
        floatingActionButton = {
            if (!selectionMode && (state is ConversationsState.Loaded || state is ConversationsState.Error)) {
                ExtendedFloatingActionButton(
                    onClick = { vm.create(onCreated = onOpenChat) },
                    containerColor = MaterialTheme.colorScheme.primary,
                    contentColor = MaterialTheme.colorScheme.onPrimary,
                    icon = { Icon(PocketIcons.Add, contentDescription = null) },
                    text = { Text(stringResource(de.smartzone.pocketclaude.R.string.new_chat)) },
                    shape = RoundedCornerShape(20.dp),
                )
            }
        },
    ) { pad ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(pad)
                .consumeWindowInsets(pad)
                .imePadding(),
        ) {
            // Suchleiste (einklappbar)
            if (searchActive) {
                OutlinedTextField(
                    value = search.query,
                    onValueChange = vm::setSearchQuery,
                    leadingIcon = { Icon(PocketIcons.Search, contentDescription = null) },
                    trailingIcon = {
                        if (search.query.isNotEmpty()) {
                            IconButton(onClick = { vm.setSearchQuery("") }) {
                                Icon(PocketIcons.Close, contentDescription = stringResource(de.smartzone.pocketclaude.R.string.action_close))
                            }
                        }
                    },
                    placeholder = { Text(stringResource(de.smartzone.pocketclaude.R.string.conversation_search_placeholder)) },
                    singleLine = true,
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 16.dp, vertical = 8.dp),
                    shape = RoundedCornerShape(22.dp),
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedContainerColor = MaterialTheme.colorScheme.surface,
                        unfocusedContainerColor = MaterialTheme.colorScheme.surface,
                    ),
                )
            }

            Box(modifier = Modifier.weight(1f).fillMaxWidth()) {
                if (search.active) {
                    SearchResultsView(
                        search = search,
                        onHitClick = { hit -> onOpenChat(hit.conversationId) },
                    )
                } else when (val s = state) {
                ConversationsState.Loading -> CenterLoader()
                is ConversationsState.NeedsSetup -> NeedsSetupView(onOpenSettings)
                is ConversationsState.Error -> ErrorView(s.message, onRetry = vm::refresh)
                is ConversationsState.Loaded -> {
                    if (s.conversations.isEmpty()) {
                        EmptyView()
                    } else {
                        LazyColumn(
                            contentPadding = PaddingValues(
                                start = 16.dp, end = 16.dp, top = 12.dp, bottom = 104.dp,
                            ),
                            verticalArrangement = Arrangement.spacedBy(12.dp),
                        ) {
                            items(s.conversations, key = { it.id }) { conv ->
                                ConversationRow(
                                    conv = conv,
                                    selected = selectedIds.contains(conv.id),
                                    selectionMode = selectionMode,
                                    onClick = {
                                        if (selectionMode) {
                                            selectedIds = if (selectedIds.contains(conv.id)) {
                                                selectedIds - conv.id
                                            } else {
                                                selectedIds + conv.id
                                            }
                                        } else {
                                            onOpenChat(conv.id)
                                        }
                                    },
                                    onLongClick = {
                                        selectedIds = selectedIds + conv.id
                                    },
                                    onRename = {
                                        renamingId = conv.id
                                        renamingTitle = conv.title
                                    },
                                    onDelete = { confirmDelete = conv.id },
                                    onTogglePin = { vm.togglePin(conv.id, conv.pinned) },
                                    onToggleLock = {
                                        if (conv.locked) unlockTarget = conv.id
                                        else vm.lock(conv.id) { needPinNotice = true }
                                    },
                                )
                            }
                        }
                    }
                }
            }
            }
        }
    }
    }

    // Rename dialog
    renamingId?.let { id ->
        AlertDialog(
            onDismissRequest = { renamingId = null },
            title = { Text(stringResource(de.smartzone.pocketclaude.R.string.action_rename)) },
            text = {
                OutlinedTextField(
                    value = renamingTitle,
                    onValueChange = { renamingTitle = it },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                    shape = MaterialTheme.shapes.small,
                )
            },
            confirmButton = {
                TextButton(onClick = {
                    if (renamingTitle.isNotBlank()) vm.rename(id, renamingTitle.trim())
                    renamingId = null
                }) { Text(stringResource(de.smartzone.pocketclaude.R.string.action_save)) }
            },
            dismissButton = {
                TextButton(onClick = { renamingId = null }) { Text(stringResource(de.smartzone.pocketclaude.R.string.action_cancel)) }
            },
        )
    }

    // Delete confirmation
    confirmDelete?.let { id ->
        AlertDialog(
            onDismissRequest = { confirmDelete = null },
            title = { Text(stringResource(de.smartzone.pocketclaude.R.string.confirm_delete_title)) },
            text = { Text(stringResource(de.smartzone.pocketclaude.R.string.confirm_delete_message)) },
            confirmButton = {
                TextButton(onClick = {
                    vm.delete(id)
                    confirmDelete = null
                }) {
                    Text(stringResource(de.smartzone.pocketclaude.R.string.action_delete), color = MaterialTheme.colorScheme.error)
                }
            },
            dismissButton = {
                TextButton(onClick = { confirmDelete = null }) { Text(stringResource(de.smartzone.pocketclaude.R.string.action_cancel)) }
            },
        )
    }

    // Chat-Sperre entfernen — PIN-Bestätigung
    unlockTarget?.let { id ->
        de.smartzone.pocketclaude.ui.lock.PinVerifyDialog(
            title = stringResource(de.smartzone.pocketclaude.R.string.chat_lock_remove_from_chat_title),
            message = stringResource(de.smartzone.pocketclaude.R.string.chat_lock_remove_from_chat_msg),
            verifyPin = { pin -> vm.verifyChatLockPin(pin) },
            onVerified = { vm.unlock(id); unlockTarget = null },
            onDismiss = { unlockTarget = null },
        )
    }

    // Hinweis: erst globalen PIN in den Einstellungen setzen
    if (needPinNotice) {
        AlertDialog(
            onDismissRequest = { needPinNotice = false },
            title = { Text(stringResource(de.smartzone.pocketclaude.R.string.settings_section_chat_lock)) },
            text = { Text(stringResource(de.smartzone.pocketclaude.R.string.chat_lock_need_pin_first)) },
            confirmButton = {
                TextButton(onClick = { needPinNotice = false; onOpenSettings() }) {
                    Text(stringResource(de.smartzone.pocketclaude.R.string.action_ok))
                }
            },
            dismissButton = {
                TextButton(onClick = { needPinNotice = false }) {
                    Text(stringResource(de.smartzone.pocketclaude.R.string.action_cancel))
                }
            },
        )
    }

    // Bulk delete (multiple selected chats at once)
    if (confirmBulkDelete) {
        AlertDialog(
            onDismissRequest = { confirmBulkDelete = false },
            title = {
                Text(stringResource(de.smartzone.pocketclaude.R.string.confirm_delete_title))
            },
            text = {
                Text(stringResource(de.smartzone.pocketclaude.R.string.confirm_delete_message))
            },
            confirmButton = {
                TextButton(onClick = {
                    vm.deleteMany(selectedIds)
                    confirmBulkDelete = false
                    selectedIds = emptySet()
                }) {
                    Text(stringResource(de.smartzone.pocketclaude.R.string.action_delete), color = MaterialTheme.colorScheme.error)
                }
            },
            dismissButton = {
                TextButton(onClick = { confirmBulkDelete = false }) { Text(stringResource(de.smartzone.pocketclaude.R.string.action_cancel)) }
            },
        )
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun ConversationRow(
    conv: ConversationDto,
    selected: Boolean,
    selectionMode: Boolean,
    onClick: () -> Unit,
    onLongClick: () -> Unit,
    onRename: () -> Unit,
    onDelete: () -> Unit,
    onTogglePin: () -> Unit,
    onToggleLock: () -> Unit,
) {
    var menuOpen by remember { mutableStateOf(false) }
    val context = androidx.compose.ui.platform.LocalContext.current
    val shape = RoundedCornerShape(24.dp)
    val bgColor = if (selected) {
        MaterialTheme.colorScheme.primary.copy(alpha = 0.18f)
    } else {
        MaterialTheme.colorScheme.surface.copy(alpha = 0.88f)
    }
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .clip(shape)
            .combinedClickable(
                onClick = onClick,
                onLongClick = onLongClick,
            )
            .then(
                if (selected) {
                    Modifier.border(2.dp, MaterialTheme.colorScheme.primary, shape)
                } else {
                    Modifier
                }
            ),
        color = bgColor,
        contentColor = MaterialTheme.colorScheme.onSurface,
        shape = shape,
        tonalElevation = 0.dp,
        border = androidx.compose.foundation.BorderStroke(
            1.dp,
            if (selected) MaterialTheme.colorScheme.primary.copy(alpha = 0.6f)
            else PocketTheme.colors.outlineSoft,
        ),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 15.dp, vertical = 15.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            // Bubble avatar
            Box(
                modifier = Modifier
                    .size(44.dp)
                    .clip(RoundedCornerShape(16.dp))
                    .background(
                        Brush.linearGradient(
                            listOf(
                                MaterialTheme.colorScheme.primary.copy(alpha = 0.95f),
                                MaterialTheme.colorScheme.tertiary.copy(alpha = 0.85f),
                            )
                        )
                    ),
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    PocketIcons.ChatBubble,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.onPrimary,
                    modifier = Modifier.size(22.dp),
                )
            }

            Spacer(Modifier.width(14.dp))

            Column(modifier = Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    if (conv.pinned) {
                        Icon(
                            PocketIcons.PushPin,
                            contentDescription = stringResource(de.smartzone.pocketclaude.R.string.convo_pinned),
                            tint = MaterialTheme.colorScheme.primary,
                            modifier = Modifier.size(14.dp),
                        )
                        Spacer(Modifier.width(6.dp))
                    }
                    if (conv.locked) {
                        Icon(
                            PocketIcons.Lock,
                            contentDescription = stringResource(de.smartzone.pocketclaude.R.string.convo_locked),
                            tint = MaterialTheme.colorScheme.primary,
                            modifier = Modifier.size(14.dp),
                        )
                        Spacer(Modifier.width(6.dp))
                    }
                    Text(
                        conv.title,
                        style = MaterialTheme.typography.titleMedium,
                        maxLines = 1,
                        modifier = Modifier.weight(1f, fill = false),
                    )
                }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    val noun = stringResource(if (conv.messageCount == 1) de.smartzone.pocketclaude.R.string.convo_messages_one else de.smartzone.pocketclaude.R.string.convo_messages_other)
                    Text(
                        text = stringResource(
                            de.smartzone.pocketclaude.R.string.convo_count_with_time,
                            conv.messageCount,
                            noun,
                            formatRelative(context, conv.lastMessageAt ?: conv.createdAt),
                        ),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 1,
                    )
                    if (conv.hasMidSummary || conv.hasLongSummary) {
                        Spacer(Modifier.width(6.dp))
                        Icon(
                            PocketIcons.Compress,
                            contentDescription = stringResource(de.smartzone.pocketclaude.R.string.convo_condensed),
                            tint = PocketTheme.colors.accent,
                            modifier = Modifier.size(14.dp),
                        )
                    }
                }
            }

            if (selectionMode) {
                // Selection-Indikator statt 3-Dots-Menü
                Icon(
                    imageVector = if (selected) PocketIcons.CheckCircle else PocketIcons.RadioUnchecked,
                    contentDescription = stringResource(if (selected) de.smartzone.pocketclaude.R.string.convo_selected else de.smartzone.pocketclaude.R.string.convo_not_selected),
                    tint = if (selected) MaterialTheme.colorScheme.primary
                           else MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier
                        .padding(end = 8.dp)
                        .size(26.dp),
                )
            } else {
                Box {
                    IconButton(onClick = { menuOpen = true }) {
                        Icon(PocketIcons.MoreVert, contentDescription = null)
                    }
                    DropdownMenu(
                        expanded = menuOpen,
                        onDismissRequest = { menuOpen = false },
                    ) {
                        DropdownMenuItem(
                            text = { Text(stringResource(if (conv.pinned) de.smartzone.pocketclaude.R.string.conversation_unpin else de.smartzone.pocketclaude.R.string.conversation_pin)) },
                            leadingIcon = {
                                Icon(
                                    PocketIcons.PushPin,
                                    contentDescription = null,
                                    tint = if (conv.pinned) MaterialTheme.colorScheme.primary
                                           else MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            },
                            onClick = { menuOpen = false; onTogglePin() },
                        )
                        DropdownMenuItem(
                            text = { Text(stringResource(if (conv.locked) de.smartzone.pocketclaude.R.string.conversation_unlock else de.smartzone.pocketclaude.R.string.conversation_lock)) },
                            leadingIcon = {
                                Icon(
                                    if (conv.locked) PocketIcons.LockOpen else PocketIcons.Lock,
                                    contentDescription = null,
                                    tint = if (conv.locked) MaterialTheme.colorScheme.primary
                                           else MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            },
                            onClick = { menuOpen = false; onToggleLock() },
                        )
                        DropdownMenuItem(
                            text = { Text(stringResource(de.smartzone.pocketclaude.R.string.action_rename)) },
                            leadingIcon = { Icon(PocketIcons.Edit, contentDescription = null) },
                            onClick = { menuOpen = false; onRename() },
                        )
                        DropdownMenuItem(
                            text = { Text(stringResource(de.smartzone.pocketclaude.R.string.action_delete), color = MaterialTheme.colorScheme.error) },
                            leadingIcon = {
                                Icon(
                                    PocketIcons.Delete,
                                    contentDescription = null,
                                    tint = MaterialTheme.colorScheme.error,
                                )
                            },
                            onClick = { menuOpen = false; onDelete() },
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun SearchResultsView(
    search: SearchState,
    onHitClick: (de.smartzone.pocketclaude.data.SearchHitDto) -> Unit,
) {
    when {
        search.isSearching -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            CircularProgressIndicator(strokeWidth = 2.dp, modifier = Modifier.size(28.dp))
        }
        search.error != null -> Box(Modifier.fillMaxSize().padding(24.dp), contentAlignment = Alignment.Center) {
            Text(
                search.error,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.error,
            )
        }
        search.hits.isEmpty() -> Box(
            Modifier.fillMaxSize().padding(24.dp),
            contentAlignment = Alignment.Center,
        ) {
            Text(
                stringResource(de.smartzone.pocketclaude.R.string.convo_search_no_results, search.query),
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        else -> LazyColumn(
            contentPadding = PaddingValues(horizontal = 16.dp, vertical = 8.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            items(search.hits, key = { it.messageId }) { hit ->
                SearchHitCard(hit = hit, onClick = { onHitClick(hit) })
            }
        }
    }
}

@Composable
private fun SearchHitCard(
    hit: de.smartzone.pocketclaude.data.SearchHitDto,
    onClick: () -> Unit,
) {
    Card(
        onClick = onClick,
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        shape = RoundedCornerShape(14.dp),
        elevation = CardDefaults.cardElevation(defaultElevation = 0.dp),
    ) {
        Column(Modifier.padding(14.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    hit.conversationTitle,
                    style = MaterialTheme.typography.titleSmall,
                    maxLines = 1,
                    modifier = Modifier.weight(1f),
                )
                val roleLabel = stringResource(if (hit.role == "user") de.smartzone.pocketclaude.R.string.convo_role_you else de.smartzone.pocketclaude.R.string.convo_role_claude)
                Text(
                    roleLabel,
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Spacer(Modifier.height(4.dp))
            Text(
                highlightSnippet(hit.snippet),
                style = MaterialTheme.typography.bodySmall,
                maxLines = 3,
                color = MaterialTheme.colorScheme.onSurface,
            )
        }
    }
}

/** Wandelt `[[hit]]`-Marker aus dem FTS5-snippet in fett-formatierte Spans. */
private fun highlightSnippet(raw: String): AnnotatedString {
    return buildAnnotatedString {
        var i = 0
        while (i < raw.length) {
            val start = raw.indexOf("[[", i)
            if (start < 0) {
                append(raw.substring(i))
                break
            }
            val end = raw.indexOf("]]", start + 2)
            if (end < 0) {
                append(raw.substring(i))
                break
            }
            append(raw.substring(i, start))
            withStyle(SpanStyle(fontWeight = FW.SemiBold)) {
                append(raw.substring(start + 2, end))
            }
            i = end + 2
        }
    }
}

@Composable
private fun CenterLoader() {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        CircularProgressIndicator()
    }
}

@Composable
private fun EmptyView() {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(32.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        PocketBrandMark(size = 92.dp)
        Spacer(Modifier.height(16.dp))
        Text(stringResource(de.smartzone.pocketclaude.R.string.empty_conversations_title), style = MaterialTheme.typography.headlineSmall)
        Spacer(Modifier.height(6.dp))
        Text(
            stringResource(de.smartzone.pocketclaude.R.string.empty_conversations_subtitle),
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun NeedsSetupView(onOpenSettings: () -> Unit) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(32.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        PocketBrandMark(size = 108.dp)
        Spacer(Modifier.height(24.dp))
        Text(stringResource(de.smartzone.pocketclaude.R.string.setup_needed_title), style = MaterialTheme.typography.headlineMedium)
        Spacer(Modifier.height(8.dp))
        Text(
            stringResource(de.smartzone.pocketclaude.R.string.setup_needed_subtitle),
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.height(24.dp))
        Button(
            onClick = onOpenSettings,
        ) {
            Icon(PocketIcons.Settings, contentDescription = null)
            Spacer(Modifier.width(8.dp))
            Text(stringResource(de.smartzone.pocketclaude.R.string.convo_open_settings))
        }
    }
}

@Composable
private fun ErrorView(message: String, onRetry: () -> Unit) {
    Box(Modifier.fillMaxSize().padding(32.dp), contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Text(
                stringResource(de.smartzone.pocketclaude.R.string.convo_connection_failed),
                style = MaterialTheme.typography.titleLarge,
                color = MaterialTheme.colorScheme.error,
            )
            Spacer(Modifier.height(8.dp))
            Text(
                message,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.height(16.dp))
            Button(onClick = onRetry, shape = RoundedCornerShape(14.dp)) {
                Text(stringResource(de.smartzone.pocketclaude.R.string.action_retry))
            }
        }
    }
}
