package de.smartzone.pocketclaude.ui.chat

import androidx.compose.ui.res.pluralStringResource
import de.smartzone.pocketclaude.data.MessageDto
import android.net.Uri
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsFocusedAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.ime
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.union
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.material3.AssistChip
import androidx.compose.material3.AssistChipDefaults
import androidx.compose.material3.FilterChip
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DrawerValue
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.TextButton
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalDrawerSheet
import androidx.compose.material3.ModalNavigationDrawer
import androidx.compose.material3.NavigationDrawerItem
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.SmallFloatingActionButton
import androidx.compose.material3.FloatingActionButtonDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.material3.rememberDrawerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import de.smartzone.pocketclaude.data.ConversationDto
import de.smartzone.pocketclaude.ui.components.AssistantBubble
import de.smartzone.pocketclaude.ui.components.CompactionNotice
import de.smartzone.pocketclaude.ui.components.PocketBackdrop
import de.smartzone.pocketclaude.ui.components.PocketBrandMark
import de.smartzone.pocketclaude.ui.components.PocketIconButton
import de.smartzone.pocketclaude.ui.components.TtsState
import de.smartzone.pocketclaude.ui.components.UserBubble
import de.smartzone.pocketclaude.ui.theme.PocketTheme
import kotlinx.coroutines.launch
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.rememberModalBottomSheetState
import de.smartzone.pocketclaude.data.ChatModelFamilies
import de.smartzone.pocketclaude.data.ChatModelOption
import de.smartzone.pocketclaude.data.ClaudeModels
import de.smartzone.pocketclaude.data.EFFORT_LEVELS
import de.smartzone.pocketclaude.data.EFFORT_LEVELS_ALL
import de.smartzone.pocketclaude.data.GatewayStatusDto
import de.smartzone.pocketclaude.data.familyForKey
import androidx.compose.ui.graphics.vector.ImageVector
import de.smartzone.pocketclaude.ui.theme.PocketIconSize
import de.smartzone.pocketclaude.ui.theme.PocketRadius
import de.smartzone.pocketclaude.ui.components.PocketChoiceChip
import de.smartzone.pocketclaude.ui.theme.PocketIcons

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatScreen(
    vm: ChatViewModel,
    onOpenSettings: () -> Unit,
    onOpenConversations: () -> Unit,
    onOpenImages: () -> Unit,
    onNewChat: () -> Unit,
    onSwitchChat: (String) -> Unit,
    onStartGemChat: (String) -> Unit = {},
) {
    val state by vm.state.collectAsState()
    val audioState by vm.audioState.collectAsState()
    val context = LocalContext.current
    val container = remember {
        (context.applicationContext as de.smartzone.pocketclaude.PocketClaudeApp).container
    }
    val appSettings by container.settingsRepository.settingsFlow
        .collectAsState(initial = de.smartzone.pocketclaude.data.AppSettings())
    // Welche gesperrten Chats sind in dieser Sitzung entsperrt (Re-Lock bei
    // App-Hintergrund via ChatLockManager).
    val unlockedChats by container.chatLock.unlocked.collectAsState()
    var input by remember { mutableStateOf("") }
    val listState = rememberLazyListState()
    val snackbar = remember { SnackbarHostState() }
    val scope = rememberCoroutineScope()
    var modelSheetOpen by remember { mutableStateOf(false) }
    var moreMenuOpen by remember { mutableStateOf(false) }
    var renameOpen by remember { mutableStateOf(false) }
    var renameInput by remember { mutableStateOf("") }
    var confirmDeleteOpen by remember { mutableStateOf(false) }
    var skillsDialogOpen by remember { mutableStateOf(false) }
    /** Antwort, ab der weitergemacht werden soll. Null heisst: Dialog zu. */
    var rewindTarget by remember { mutableStateOf<MessageDto?>(null) }
    var autoSpeakDialogOpen by remember { mutableStateOf(false) }

    // Drawer-State + Chat-Liste fürs Drawer (wird beim Öffnen aktualisiert)
    val drawerState = rememberDrawerState(initialValue = DrawerValue.Closed)
    var drawerChats by remember { mutableStateOf<List<ConversationDto>>(emptyList()) }
    var drawerGems by remember { mutableStateOf<List<de.smartzone.pocketclaude.data.GemDto>>(emptyList()) }
    LaunchedEffect(drawerState.currentValue, state.title) {
        if (drawerState.currentValue == DrawerValue.Open) {
            runCatching { container.chatRepository.list() }
                .onSuccess { drawerChats = it }
            runCatching { container.chatRepository.listGems() }
                .onSuccess { drawerGems = it }
        }
    }

    val defaultImageName = stringResource(de.smartzone.pocketclaude.R.string.chat_default_filename_image)
    val defaultDocName = stringResource(de.smartzone.pocketclaude.R.string.chat_default_filename_doc)
    // Mehrfachauswahl: bis zu MAX_PICK Bilder bzw. beliebig viele Dateien auf
    // einmal; jede wird einzeln hochgeladen und als Anhang vorgemerkt.
    val photoPicker = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.PickMultipleVisualMedia(MAX_PICK),
    ) { uris: List<Uri> ->
        for (uri in uris) vm.addPending(uri, queryName(context, uri) ?: defaultImageName)
    }
    val documentPicker = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.OpenMultipleDocuments(),
    ) { uris: List<Uri> ->
        for (uri in uris) vm.addPending(uri, queryName(context, uri) ?: defaultDocName)
    }
    // Kamera: Foto landet in einer eigenen Datei im Cache (FileProvider deckt
    // den ganzen Cache ab). Pfad ueberlebt per rememberSaveable auch, dass
    // Android die App waehrend der Kamera beendet.
    var cameraFile by rememberSaveable { mutableStateOf<String?>(null) }
    val cameraLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.TakePicture(),
    ) { ok: Boolean ->
        val file = cameraFile?.let { java.io.File(it) }
        cameraFile = null
        if (file == null) return@rememberLauncherForActivityResult
        if (ok && file.length() > 0) {
            val uri = androidx.core.content.FileProvider.getUriForFile(
                context, "${context.packageName}.fileprovider", file,
            )
            vm.addPending(uri, file.name)
        } else {
            file.delete()
        }
    }
    val launchCamera: () -> Unit = {
        val dir = java.io.File(context.cacheDir, "camera").apply { mkdirs() }
        val stamp = java.text.SimpleDateFormat("yyyyMMdd_HHmmss", java.util.Locale.ROOT)
            .format(java.util.Date())
        val file = java.io.File(dir, "IMG_$stamp.jpg")
        cameraFile = file.absolutePath
        val uri = androidx.core.content.FileProvider.getUriForFile(
            context, "${context.packageName}.fileprovider", file,
        )
        try {
            cameraLauncher.launch(uri)
        } catch (e: android.content.ActivityNotFoundException) {
            cameraFile = null
            android.widget.Toast.makeText(
                context,
                context.getString(de.smartzone.pocketclaude.R.string.chat_camera_unavailable),
                android.widget.Toast.LENGTH_SHORT,
            ).show()
        }
    }
    // Chat als .md lokal speichern (Storage Access Framework). Inhalt wird beim
    // Antippen via exportMarkdown geholt und hier nach Ziel-Auswahl geschrieben.
    var pendingExportMd by remember { mutableStateOf<String?>(null) }
    val saveMarkdownLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.CreateDocument("text/markdown"),
    ) { uri: Uri? ->
        val md = pendingExportMd
        pendingExportMd = null
        if (uri != null && md != null) {
            val ok = runCatching {
                context.contentResolver.openOutputStream(uri)?.use {
                    it.write(md.toByteArray(Charsets.UTF_8))
                }
            }.isSuccess
            android.widget.Toast.makeText(
                context,
                context.getString(
                    if (ok) de.smartzone.pocketclaude.R.string.chat_export_saved
                    else de.smartzone.pocketclaude.R.string.chat_export_save_failed
                ),
                android.widget.Toast.LENGTH_SHORT,
            ).show()
        }
    }

    // Share-to-PocketClaude: beim ersten Öffnen dieses Chats die per Intent
    // geteilten Datei(en)/Text aus dem Container abholen und als Anhänge/Text
    // übernehmen. Einmalig — pendingShare wird danach geleert.
    LaunchedEffect(Unit) {
        val container =
            (context.applicationContext as de.smartzone.pocketclaude.PocketClaudeApp).container
        val share = container.pendingShare ?: return@LaunchedEffect
        container.pendingShare = null
        for (uri in share.uris) {
            val name = queryName(context, uri) ?: defaultDocName
            vm.addPending(uri, name)
        }
        val sharedText = share.text
        if (!sharedText.isNullOrBlank()) {
            input = if (input.isBlank()) sharedText else "$input\n$sharedText"
        }
    }

    // --- Scroll-Logik ---
    var initialScrollDone by remember(state.conversationId) { mutableStateOf(false) }

    // Initial-Load: instant ans absolute Ende. Wir machen das in einer Retry-
    // Loop mit kleinen delays, damit LazyColumn zwischen den Versuchen Layout-
    // Passes durchführen kann — sonst clamped scrollBy gegen noch nicht
    // gemessene Items und wir landen nur halb unten.
    LaunchedEffect(state.isLoading, state.messages.size) {
        if (!state.isLoading && !initialScrollDone && state.messages.isNotEmpty()) {
            scrollToVeryBottom(listState)
            initialScrollDone = true
        }
    }

    // Echtes "Bottom" — letztes Item komplett sichtbar + bei viewportEnd.
    // Wird nur noch für die FAB-Sichtbarkeit verwendet (kein Auto-Scroll mehr).
    val isAtBottom by remember {
        derivedStateOf {
            val info = listState.layoutInfo
            val total = info.totalItemsCount
            if (total == 0) return@derivedStateOf true
            val last = info.visibleItemsInfo.lastOrNull() ?: return@derivedStateOf true
            last.index >= total - 1 && (last.offset + last.size) <= info.viewportEndOffset + 24
        }
    }

    // Process-Death-Restore: cid in DataStore halten, damit die App nach
    // einem Hintergrund-Kill wieder hier aufmacht statt frischen Chat.
    LaunchedEffect(state.conversationId) {
        val cid = state.conversationId
        if (cid.isNotBlank()) {
            container.settingsRepository.setLastChatCid(cid)
        }
    }

    // Beim Stream-Start einmalig ans Ende scrollen — damit die gerade
    // abgeschickte User-Frage und der Anfang der Antwort sichtbar werden.
    // Während des Streamings selbst gibt es KEIN Auto-Scroll mehr; der User
    // scrollt selbst mit. Die früheren Auto-Scroll-Sprünge entstanden, weil
    // LazyColumn mit wachsenden Items + Layout-Latenz kollidiert ist.
    LaunchedEffect(state.isStreaming) {
        if (initialScrollDone && state.isStreaming) {
            scrollToVeryBottom(listState)
        }
    }

    // FAB-Sichtbarkeit: wenn nicht unten UND Liste hat Inhalt
    val showScrollFab by remember {
        derivedStateOf {
            !isAtBottom && listState.layoutInfo.totalItemsCount > 0
        }
    }

    // Spring-to-Match: bei jeder Änderung des aktuellen Treffer-Index
    // (= User hat „Weiter"/„Zurück" gedrückt oder gerade neuen Begriff eingetippt)
    // scrollen wir den entsprechenden Message-Bubble ins Sichtfeld.
    LaunchedEffect(state.searchIndex, state.searchMatches) {
        val targetId = state.currentMatchMessageId ?: return@LaunchedEffect
        val msgIndex = state.messages.indexOfFirst { it.id == targetId }
        if (msgIndex < 0) return@LaunchedEffect
        // LazyColumn-Item-Offset: das CompactionNotice-Item (wenn da) ist
        // dem messages-Index um 1 vorgelagert.
        val offset = if (state.hasMidSummary || state.hasLongSummary) 1 else 0
        runCatching { listState.animateScrollToItem(offset + msgIndex) }
    }

    // Errors → Snackbar
    LaunchedEffect(state.errorMessage) {
        state.errorMessage?.let { msg ->
            snackbar.showSnackbar(msg)
            vm.dismissError()
        }
    }

    // Audio-Fehler ebenfalls in der Snackbar zeigen
    LaunchedEffect(audioState.error) {
        audioState.error?.let { err ->
            snackbar.showSnackbar(context.getString(de.smartzone.pocketclaude.R.string.chat_audio_prefix, err))
            vm.clearAudioError()
        }
    }

    // ───── Voice-Input: Mic-Permission, Transkript-Empfang, Fehler ─────
    var pendingMicAction by remember { mutableStateOf(false) }
    val micPermissionLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestPermission(),
    ) { granted ->
        if (granted && pendingMicAction) {
            vm.toggleRecording()
        } else if (!granted) {
            scope.launch {
                snackbar.showSnackbar(
                    context.getString(de.smartzone.pocketclaude.R.string.voice_error_no_permission)
                )
            }
        }
        pendingMicAction = false
    }
    // Zurueck beendet im Auto-Modus nur den Modus, nicht die ganze App
    // (Joscha 19.10.2026). Ein offener Drawer faengt Zurueck vorher ab.
    BackHandler(enabled = state.autoMode) { vm.setAutoMode(false) }
    // Auto-Modus (Sprachgespraech) starten: aus dem Drei-Punkte-Menue und vom
    // runden Knopf im leeren Eingabefeld.
    val startAutoMode: () -> Unit = {
        // Permission vorher klären — sonst landet der Loop im Error-Branch.
        if (!container.voiceRecorder.hasPermission()) {
            pendingMicAction = true
            micPermissionLauncher.launch(android.Manifest.permission.RECORD_AUDIO)
            // Permission-Result-Handler ruft toggleRecording() — einfacher
            // Trick: Auto-Mode-Flag gleich setzen, der Loop wartet dann auf
            // den Mic-Start.
        }
        vm.setAutoMode(true)
    }
    // Transkript aus dem VM ins Input-Feld einfügen (nur im manuellen Modus —
    // im Auto-Modus geht der Text direkt zu send(), nicht über input).
    LaunchedEffect(Unit) {
        vm.transcriptToInsert.collect { transcript ->
            input = if (input.isBlank()) transcript else "$input $transcript"
        }
    }
    LaunchedEffect(state.voiceError) {
        state.voiceError?.let { msg ->
            snackbar.showSnackbar(msg)
            vm.clearVoiceError()
        }
    }

    // Auto-Mode: Tastatur explizit ausblenden + Fokus weg vom TextField.
    // Das InputField bleibt vom Composition-Tree weg, solange autoMode an
    // ist; falls die IME vorher geöffnet war, würde sie sonst noch hängen.
    val keyboardCtrl = LocalSoftwareKeyboardController.current
    val focusManager = LocalFocusManager.current
    LaunchedEffect(state.autoMode) {
        if (state.autoMode) {
            focusManager.clearFocus(force = true)
            keyboardCtrl?.hide()
        }
    }

    ModalNavigationDrawer(
        drawerState = drawerState,
        // Abdunklung wie bei ChatGPT; die Leiste ist nur 80 % breit, ein Tipp
        // auf den sichtbaren Chat rechts daneben schliesst sie.
        scrimColor = Color.Black.copy(alpha = 0.5f),
        drawerContent = {
            ChatDrawerContent(
                open = drawerState.targetValue == DrawerValue.Open,
                currentCid = state.conversationId,
                chats = drawerChats,
                gems = drawerGems,
                onNewChat = {
                    scope.launch { drawerState.close() }
                    onNewChat()
                },
                onStartGem = { gemId ->
                    scope.launch { drawerState.close() }
                    onStartGemChat(gemId)
                },
                onGenerateImages = {
                    scope.launch { drawerState.close() }
                    onOpenImages()
                },
                onSwitch = { cid ->
                    scope.launch { drawerState.close() }
                    if (cid != state.conversationId) onSwitchChat(cid)
                },
                onAllChats = {
                    scope.launch { drawerState.close() }
                    onOpenConversations()
                },
                onSettings = {
                    scope.launch { drawerState.close() }
                    onOpenSettings()
                },
            )
        },
    ) {
    PocketBackdrop(Modifier.fillMaxSize()) {
    Scaffold(
        containerColor = Color.Transparent,
        contentColor = MaterialTheme.colorScheme.onBackground,
        // Wir kümmern uns ums Bottom-Inset selbst (im InputBar via union(ime, navBar)),
        // damit Tastatur und Navigation-Bar sich nicht aufsummieren.
        contentWindowInsets = WindowInsets(0),
        snackbarHost = {
            SnackbarHost(
                hostState = snackbar,
                modifier = Modifier
                    .windowInsetsPadding(WindowInsets.ime.union(WindowInsets.navigationBars))
                    .padding(bottom = 76.dp),
            )
        },
        topBar = {
            if (state.searchActive) {
                TopAppBar(
                    title = {
                        // Such-Modus: TextField statt Titel + Match-Counter
                        SearchBarTitle(
                            query = state.searchQuery,
                            onQueryChange = vm::setSearchQuery,
                            matchCount = state.searchMatches.size,
                            currentIndex = state.searchIndex,
                        )
                    },
                    navigationIcon = {
                        IconButton(onClick = { vm.closeSearch() }) {
                            Icon(PocketIcons.Close, contentDescription = stringResource(de.smartzone.pocketclaude.R.string.action_close))
                        }
                    },
                    actions = {
                        val hasMatches = state.searchMatches.isNotEmpty()
                        IconButton(onClick = { vm.previousMatch() }, enabled = hasMatches) {
                            Icon(PocketIcons.ExpandLess, contentDescription = null)
                        }
                        IconButton(
                            onClick = { vm.nextMatch() },
                            enabled = hasMatches,
                            modifier = Modifier.padding(end = 8.dp),
                        ) {
                            Icon(PocketIcons.ExpandMore, contentDescription = null)
                        }
                    },
                    // Deckend: der Verlauf laeuft unter der Kopfzeile durch.
                    colors = TopAppBarDefaults.topAppBarColors(
                        containerColor = MaterialTheme.colorScheme.background,
                    ),
                )
            } else {
                val appName = stringResource(de.smartzone.pocketclaude.R.string.app_name)
                val baseTitle = state.title.ifBlank { appName }
                ChatFloatingHeader(
                    title = if (state.gemEmoji.isNotBlank()) "${state.gemEmoji}  $baseTitle" else baseTitle,
                    onMenu = { scope.launch { drawerState.open() } },
                    menuDescription = stringResource(de.smartzone.pocketclaude.R.string.title_conversations),
                ) {
                    // Denkstufe (und Modell): Tacho wie bei ChatGPT, eingefaerbt
                    // nach der aktuellen Stufe. Das Sheet zeigt Claude zuerst,
                    // darunter die Zusatz-Modelle der erreichbaren Gateways.
                    HeaderIcon(
                        icon = PocketIcons.Speed,
                        description = stringResource(de.smartzone.pocketclaude.R.string.model_sheet_title),
                        onClick = { modelSheetOpen = true },
                        tint = effortTint(appSettings.effortFor(familyForKey(state.modelKey))),
                    )
                    HeaderIcon(
                        icon = PocketIcons.NewChat,
                        description = stringResource(de.smartzone.pocketclaude.R.string.new_chat),
                        onClick = onNewChat,
                    )
                    // Three-dot overflow — rename / pin / share / delete
                    Box {
                        HeaderIcon(
                            icon = PocketIcons.MoreVert,
                            description = stringResource(de.smartzone.pocketclaude.R.string.action_more),
                            onClick = { moreMenuOpen = true },
                        )
                            DropdownMenu(
                                expanded = moreMenuOpen,
                                onDismissRequest = { moreMenuOpen = false },
                            ) {
                                DropdownMenuItem(
                                    text = { Text(stringResource(de.smartzone.pocketclaude.R.string.action_rename)) },
                                    leadingIcon = {
                                        Icon(PocketIcons.Edit, contentDescription = null)
                                    },
                                    onClick = {
                                        moreMenuOpen = false
                                        renameInput = state.title
                                        renameOpen = true
                                    },
                                )
                                DropdownMenuItem(
                                    text = {
                                        Text(stringResource(if (state.pinned) de.smartzone.pocketclaude.R.string.conversation_unpin else de.smartzone.pocketclaude.R.string.conversation_pin))
                                    },
                                    leadingIcon = {
                                        Icon(
                                            if (state.pinned) PocketIcons.PushPinFilled else PocketIcons.PushPin,
                                            contentDescription = null,
                                            tint = if (state.pinned) MaterialTheme.colorScheme.primary
                                                   else MaterialTheme.colorScheme.onSurfaceVariant,
                                        )
                                    },
                                    onClick = {
                                        moreMenuOpen = false
                                        vm.togglePin()
                                    },
                                )
                                DropdownMenuItem(
                                    text = {
                                        Text(
                                            if (state.skillsIsOverride) stringResource(de.smartzone.pocketclaude.R.string.skills_for_this_chat_done)
                                            else stringResource(de.smartzone.pocketclaude.R.string.skills_for_this_chat)
                                        )
                                    },
                                    leadingIcon = {
                                        Icon(PocketIcons.Extension, contentDescription = null)
                                    },
                                    // Eigene Skills fuer diesen Chat: Haken am rechten Rand
                                    // statt eines ✓-Zeichens im Text.
                                    trailingIcon = if (state.skillsIsOverride) {
                                        {
                                            Icon(
                                                PocketIcons.Check,
                                                contentDescription = null,
                                                tint = MaterialTheme.colorScheme.primary,
                                                modifier = Modifier.size(PocketIconSize.Small),
                                            )
                                        }
                                    } else null,
                                    onClick = {
                                        moreMenuOpen = false
                                        skillsDialogOpen = true
                                    },
                                )
                                DropdownMenuItem(
                                    text = {
                                        Text(stringResource(de.smartzone.pocketclaude.R.string.auto_speak_for_this_chat, ""))
                                    },
                                    // Ein fester Wert fuer diesen Chat steht als kurzer
                                    // Zustand am rechten Rand (an/aus), wie in den
                                    // Systemeinstellungen.
                                    trailingIcon = state.autoSpeakOverride?.let { on ->
                                        {
                                            Text(
                                                stringResource(
                                                    if (on) de.smartzone.pocketclaude.R.string.chat_auto_speak_marker_on
                                                    else de.smartzone.pocketclaude.R.string.chat_auto_speak_marker_off
                                                ),
                                                style = MaterialTheme.typography.labelMedium,
                                                color = if (on) MaterialTheme.colorScheme.primary
                                                        else MaterialTheme.colorScheme.onSurfaceVariant,
                                            )
                                        }
                                    },
                                    leadingIcon = {
                                        Icon(
                                            PocketIcons.VolumeUp,
                                            contentDescription = null,
                                        )
                                    },
                                    onClick = {
                                        moreMenuOpen = false
                                        autoSpeakDialogOpen = true
                                    },
                                )
                                // Auto-Mode: Voice-Loop (Recording → Senden →
                                // TTS-Vorlesen → wieder Recording).
                                DropdownMenuItem(
                                    text = {
                                        Text(
                                            if (state.autoMode)
                                                stringResource(de.smartzone.pocketclaude.R.string.chat_auto_mode_stop)
                                            else
                                                stringResource(de.smartzone.pocketclaude.R.string.chat_auto_mode_start)
                                        )
                                    },
                                    leadingIcon = {
                                        Icon(
                                            PocketIcons.VoiceMode,
                                            contentDescription = null,
                                            tint = if (state.autoMode) MaterialTheme.colorScheme.primary
                                                   else MaterialTheme.colorScheme.onSurfaceVariant,
                                        )
                                    },
                                    onClick = {
                                        moreMenuOpen = false
                                        if (!state.autoMode) startAutoMode() else vm.setAutoMode(false)
                                    },
                                )
                                DropdownMenuItem(
                                    text = { Text(stringResource(de.smartzone.pocketclaude.R.string.search_in_chat)) },
                                    leadingIcon = {
                                        Icon(PocketIcons.Search, contentDescription = null)
                                    },
                                    onClick = {
                                        moreMenuOpen = false
                                        vm.openSearch()
                                    },
                                )
                                DropdownMenuItem(
                                    text = { Text(stringResource(de.smartzone.pocketclaude.R.string.share_as_markdown)) },
                                    leadingIcon = {
                                        Icon(PocketIcons.Share, contentDescription = null)
                                    },
                                    onClick = {
                                        moreMenuOpen = false
                                        vm.exportMarkdown { title, md ->
                                            shareMarkdownIntent(context, title, md)
                                        }
                                    },
                                )
                                DropdownMenuItem(
                                    text = { Text(stringResource(de.smartzone.pocketclaude.R.string.save_as_markdown)) },
                                    leadingIcon = {
                                        Icon(PocketIcons.Download, contentDescription = null)
                                    },
                                    onClick = {
                                        moreMenuOpen = false
                                        vm.exportMarkdown { title, md ->
                                            pendingExportMd = md
                                            val safe = title.replace(Regex("""[^\p{L}\p{N}\-_ ]"""), "_")
                                                .take(60).trim().ifBlank { "chat" }
                                            saveMarkdownLauncher.launch("$safe.md")
                                        }
                                    },
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
                                    onClick = {
                                        moreMenuOpen = false
                                        confirmDeleteOpen = true
                                    },
                                )
                            }
                    }
                }
            }
        },
    ) { pad ->
        // Kein Top-Padding: der Verlauf scrollt unter die schwebende Kopfzeile
        // (wie bei ChatGPT), die Liste bekommt den Abstand als contentPadding.
        val headerPad = pad.calculateTopPadding()
        Column(modifier = Modifier.fillMaxSize().padding(bottom = pad.calculateBottomPadding())) {

            // Message list
            Box(modifier = Modifier.weight(1f).fillMaxWidth()) {
                if (state.isLoading) {
                    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                        CircularProgressIndicator()
                    }
                } else {
                  // SelectionContainer wickelt die Liste, damit Long-Press auf
                  // einer Bubble den nativen Text-Selektion-Modus startet
                  // (statt direkt zu kopieren). User kann dann Text-Range
                  // markieren, Standard-Android-Toolbar gibt „Copy / Translate /
                  // Share" etc. Für Komplett-Kopie der Antwort gibt's das
                  // separate Copy-Icon in der AssistantBubble.
                  androidx.compose.foundation.text.selection.SelectionContainer {
                    LazyColumn(
                        state = listState,
                        contentPadding = PaddingValues(top = headerPad + 4.dp, bottom = 8.dp),
                        modifier = Modifier.fillMaxSize(),
                    ) {
                        if (state.hasMidSummary || state.hasLongSummary) {
                            item {
                                CompactionNotice(
                                    text = stringResource(de.smartzone.pocketclaude.R.string.chat_compaction_notice),
                                )
                            }
                        }
                        // Leerer Gem-Chat: Gem-Kopf + tappbare Gesprächs-Starter.
                        if (state.messages.isEmpty() && !state.isStreaming &&
                            (state.gemName.isNotBlank() || state.gemStarters.isNotEmpty())
                        ) {
                            item {
                                GemWelcome(
                                    emoji = state.gemEmoji,
                                    name = state.gemName,
                                    description = state.gemDescription,
                                    starters = state.gemStarters,
                                    onStarter = { vm.send(it) },
                                )
                            }
                        }
                        // Streaming-Bubble läuft als VIRTUELLES letztes Element
                        // im gleichen items()-Block. Slot bleibt index-basiert
                        // stabil über den gesamten Stream-Lebenszyklus (kein
                        // `key = { it.id }`, dann ist auch der UserSaved-Id-Swap
                        // slot-stabil).
                        //
                        // WICHTIG: Stream-Bubble und finale Bubble teilen sich
                        // EINEN AssistantBubble-Call-Site. Wenn sie an zwei
                        // verschiedenen Call-Sites hängen (z.B. `if (msg ==
                        // null) AssistantBubble(...) else AssistantBubble(...)`),
                        // sieht Compose das beim Done als Dispose + Re-Mount,
                        // nicht als Recompose — MarkdownText-Cache weg, Bubble
                        // wird frisch gemessen, sichtbarer Scroll-Sprung.
                        // Hier deshalb genau EIN Call-Site mit umgeschwenkten
                        // Parametern (text / isStreaming / onSpeakClick).
                        val msgs = state.messages
                        val displayCount = msgs.size + (if (state.isStreaming) 1 else 0)
                        items(count = displayCount) { i ->
                            val msg = msgs.getOrNull(i)
                            val isStreamingSlot = msg == null
                            if (msg?.role == "user") {
                                UserBubble(
                                    text = msg.content,
                                    attachments = msg.attachments,
                                    collapseLongMessages = appSettings.collapseLongUserMessages,
                                )
                            } else if (isStreamingSlot || msg?.role == "assistant") {
                                val bubbleText = msg?.content ?: state.streamingText
                                val bubbleThinking = if (isStreamingSlot) state.streamingThinking else ""
                                val bubbleAttachments =
                                    if (isStreamingSlot) state.streamingAttachments
                                    else msg?.attachments.orEmpty()
                                val ttsState = if (msg != null) when {
                                    audioState.loadingMessageId == msg.id -> TtsState.Loading
                                    audioState.playingMessageId == msg.id -> TtsState.Playing
                                    audioState.pausedMessageId == msg.id -> TtsState.Paused
                                    else -> TtsState.Idle
                                } else TtsState.Idle
                                val onSpeakClick: (() -> Unit)? = if (msg != null) {
                                    { vm.speak(msg.id) }
                                } else null
                                // An JEDER fertigen Antwort, auch an der
                                // letzten. Dort ist zwar nichts zu verwerfen,
                                // aber genau da will man oft das Modell
                                // wechseln und nochmal ansetzen. Frueher fehlte
                                // der Knopf an der letzten Antwort, und nach
                                // einem Ruecksprung war er dadurch scheinbar
                                // ganz verschwunden.
                                val onRewindClick: (() -> Unit)? =
                                    if (msg != null && !state.isStreaming &&
                                        msg.role == "assistant"
                                    ) {
                                        { rewindTarget = msg }
                                    } else null
                                AssistantBubble(
                                    text = bubbleText,
                                    attachments = bubbleAttachments,
                                    isStreaming = isStreamingSlot,
                                    thinkingText = bubbleThinking,
                                    ttsState = ttsState,
                                    onSpeakClick = onSpeakClick,
                                    onRewindClick = onRewindClick,
                                    onPauseClick = { vm.pauseSpeaking() },
                                    onResumeClick = { vm.resumeSpeaking() },
                                    onStopClick = { vm.stopSpeaking() },
                                )
                            }
                        }
                        item { Spacer(Modifier.height(8.dp)) }
                    }
                  } // SelectionContainer
                }

                if (state.isCompacting) {
                    AssistChip(
                        onClick = {},
                        label = { Text(stringResource(de.smartzone.pocketclaude.R.string.chat_compacting_chip)) },
                        leadingIcon = {
                            CircularProgressIndicator(
                                strokeWidth = 2.dp,
                                modifier = Modifier.size(PocketIconSize.Marker),
                            )
                        },
                        colors = AssistChipDefaults.assistChipColors(
                            containerColor = MaterialTheme.colorScheme.surface,
                        ),
                        shape = CircleShape,
                        modifier = Modifier.align(Alignment.TopCenter).padding(top = 8.dp),
                    )
                }

                // Scroll-to-bottom FAB — erscheint wenn der User weit hochgescrollt ist
                if (showScrollFab) {
                    SmallFloatingActionButton(
                        onClick = {
                            scope.launch {
                                scrollToVeryBottom(listState)
                            }
                        },
                        containerColor = MaterialTheme.colorScheme.surface,
                        contentColor = MaterialTheme.colorScheme.onSurface,
                        shape = CircleShape,
                        elevation = FloatingActionButtonDefaults.elevation(defaultElevation = 4.dp),
                        modifier = Modifier
                            .align(Alignment.BottomEnd)
                            .padding(end = 16.dp, bottom = 16.dp),
                    ) {
                        Icon(
                            PocketIcons.ExpandMore,
                            contentDescription = stringResource(de.smartzone.pocketclaude.R.string.chat_scroll_to_bottom_cd),
                        )
                    }
                }
            }

            // Input: Im Auto-Mode komplett ersetzt durch AutoModeBar (grosser
            // Mic + Status-Text + Exit-Button). Tastatur ist dort nutzlos,
            // wird beim Auto-Mode-Start aktiv ausgeblendet (siehe oben).
            // Image-Mode läuft eh über den eigenen Bilder-Screen (Drawer),
            // hier deshalb keine Mode-Unterscheidung mehr.
            val voiceEnabled = !state.isStreaming &&
                audioState.loadingMessageId == null &&
                audioState.playingMessageId == null
            val handleMicTap: () -> Unit = {
                if (container.voiceRecorder.hasPermission()) {
                    vm.toggleRecording()
                } else {
                    pendingMicAction = true
                    micPermissionLauncher.launch(android.Manifest.permission.RECORD_AUDIO)
                }
            }
            if (state.autoMode) {
                de.smartzone.pocketclaude.ui.components.AutoModeBar(
                    voiceState = state.voiceState,
                    isStreaming = state.isStreaming,
                    ttsLoading = audioState.loadingMessageId != null,
                    ttsPlaying = audioState.playingMessageId != null,
                    voiceEnabled = voiceEnabled,
                    autoSendEnabled = appSettings.autoSendEnabled,
                    autoSendSilenceMs = appSettings.autoSendSilenceMs,
                    silenceProgressMs = state.silenceProgressMs,
                    onMicTap = handleMicTap,
                    onMicCancel = { vm.cancelRecording() },
                    onExitAutoMode = { vm.setAutoMode(false) },
                    onStopSpeaking = { vm.stopSpeaking() },
                    onAutoSendChange = { enabled ->
                        scope.launch { container.settingsRepository.setAutoSendEnabled(enabled) }
                    },
                )
            } else {
                ChatComposer(
                    value = input,
                    onChange = { input = it },
                    pending = state.pending,
                    onRemovePending = { vm.removePending(it.uri) },
                    onSend = {
                        val text = input
                        input = ""
                        vm.send(text)
                    },
                    onStop = { vm.stop() },
                    onCamera = launchCamera,
                    onPhotos = {
                        photoPicker.launch(
                            PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)
                        )
                    },
                    onFiles = {
                        // Liberal-Liste: Claude kann mit allem umgehen, was Text ist
                        // (Code, Configs, Logs, Markdown, JSON, YAML, …) oder als
                        // Bild/PDF erkannt werden kann. Wir lassen den OS-Picker
                        // alles anbieten (`*/*`) — der Server entscheidet via
                        // _looks_like_text, ob's inline eingebettet wird oder als
                        // Binär-Referenz behandelt. Size-Schutz: 20 MB Upload-Limit
                        // im Server (.env: MAX_UPLOAD_MB).
                        documentPicker.launch(arrayOf("*/*"))
                    },
                    onVoiceConversation = startAutoMode,
                    sending = state.isStreaming,
                    voiceState = state.voiceState,
                    // Mic deaktivieren wenn LLM busy ist (Stream läuft oder TTS
                    // spielt) — sonst nimmt das Mic die TTS-Wiedergabe vom
                    // Lautsprecher mit auf.
                    voiceEnabled = voiceEnabled,
                    onMicTap = handleMicTap,
                    onMicCancel = { vm.cancelRecording() },
                )
            }
        }
    }
    // Sperr-Ansicht: liegt über dem ganzen Chat, solange dieser Chat gesperrt
    // und in dieser Sitzung noch nicht per PIN/Fingerabdruck entsperrt ist.
    if (state.locked && state.conversationId !in unlockedChats) {
        de.smartzone.pocketclaude.ui.lock.ChatLockGate(
            chatTitle = state.title,
            biometricEnabled = appSettings.chatLockBiometricEnabled,
            verifyPin = { pin -> vm.verifyChatLockPin(pin) },
            onUnlocked = { container.chatLock.unlock(state.conversationId) },
            onOpenMenu = { scope.launch { drawerState.open() } },
            menuContentDescription = stringResource(de.smartzone.pocketclaude.R.string.title_conversations),
            modifier = Modifier.fillMaxSize(),
        )
    }
    } // Backdrop (Gate-Overlay)
    } // ModalNavigationDrawer

    // Rename dialog
    if (modelSheetOpen) {
        ModelSheet(
            models = state.models,
            gateways = state.gateways,
            selectedKey = state.modelKey,
            effortForModel = { key, option -> appSettings.effortForModelKey(key, option) },
            availableEfforts = { family, option -> appSettings.availableEffortsFor(family, option) },
            loading = state.modelsLoading,
            errorText = state.modelsError,
            onSelectModel = { model -> vm.selectModel(model) },
            onSelectEffort = { family, effort -> vm.setEffort(family, effort) },
            onRefresh = { vm.refreshModels() },
            onDismiss = { modelSheetOpen = false },
        )
    }

    if (renameOpen) {
        AlertDialog(
            onDismissRequest = { renameOpen = false },
            title = { Text(stringResource(de.smartzone.pocketclaude.R.string.rename_dialog_title)) },
            text = {
                OutlinedTextField(
                    value = renameInput,
                    onValueChange = { renameInput = it },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                    shape = MaterialTheme.shapes.small,
                )
            },
            confirmButton = {
                TextButton(onClick = {
                    if (renameInput.isNotBlank()) vm.renameChat(renameInput)
                    renameOpen = false
                }) { Text(stringResource(de.smartzone.pocketclaude.R.string.action_save)) }
            },
            dismissButton = {
                TextButton(onClick = { renameOpen = false }) { Text(stringResource(de.smartzone.pocketclaude.R.string.action_cancel)) }
            },
        )
    }

    // Delete confirmation
    if (confirmDeleteOpen) {
        AlertDialog(
            onDismissRequest = { confirmDeleteOpen = false },
            title = { Text(stringResource(de.smartzone.pocketclaude.R.string.confirm_delete_title)) },
            text = { Text(stringResource(de.smartzone.pocketclaude.R.string.confirm_delete_message)) },
            confirmButton = {
                TextButton(onClick = {
                    confirmDeleteOpen = false
                    vm.deleteChat { onNewChat() }
                }) {
                    Text(stringResource(de.smartzone.pocketclaude.R.string.action_delete), color = MaterialTheme.colorScheme.error)
                }
            },
            dismissButton = {
                TextButton(onClick = { confirmDeleteOpen = false }) { Text(stringResource(de.smartzone.pocketclaude.R.string.action_cancel)) }
            },
        )
    }

    // Ruecksprung: zu welcher Antwort, und mit welchem Modell weiter.
    rewindTarget?.let { target ->
        RewindDialog(
            droppedCount = state.messages.count { it.id > target.id },
            models = state.models,
            currentModelKey = state.modelKey,
            onConfirm = { newModel ->
                vm.rewindTo(target.id, newModel)
                rewindTarget = null
            },
            onDismiss = { rewindTarget = null },
        )
    }

    // Skills-Override-Dialog
    if (skillsDialogOpen) {
        ChatSkillsDialog(
            currentSkills = state.skills,
            isOverride = state.skillsIsOverride,
            modelFamily = familyForKey(state.modelKey),
            onSave = { newSkills ->
                vm.setChatSkills(newSkills)
                skillsDialogOpen = false
            },
            onReset = {
                vm.resetChatSkills()
                skillsDialogOpen = false
            },
            onDismiss = { skillsDialogOpen = false },
        )
    }

    // Auto-Speak-Override-Dialog
    if (autoSpeakDialogOpen) {
        ChatAutoSpeakDialog(
            globalDefault = appSettings.ttsAutoSpeak,
            override = state.autoSpeakOverride,
            onSave = { newOverride ->
                vm.setAutoSpeakOverride(newOverride)
                autoSpeakDialogOpen = false
            },
            onDismiss = { autoSpeakDialogOpen = false },
        )
    }
}

/**
 * Per-Chat-Skills-Override-Dialog. "Speichern" setzt einen Override für DIESEN
 * Chat, "Auf Standard zurücksetzen" löscht den Override und der User-Default
 * greift wieder.
 *
 * Suche und Seitenabruf koennen alle Modelle. Code-Ausfuehrung kann nur Claude,
 * deshalb wird der Schalter bei den Zusatz-Modellen ausgegraut und erklaert,
 * statt so zu tun, als haette er dort eine Wirkung.
 */
@Composable
private fun ChatSkillsDialog(
    currentSkills: de.smartzone.pocketclaude.data.SkillsDto?,
    isOverride: Boolean,
    modelFamily: String,
    onSave: (de.smartzone.pocketclaude.data.SkillsDto) -> Unit,
    onReset: () -> Unit,
    onDismiss: () -> Unit,
) {
    val initial = currentSkills ?: de.smartzone.pocketclaude.data.SkillsDto()
    var webSearch by remember(initial) { mutableStateOf(initial.webSearch) }
    var webFetch by remember(initial) { mutableStateOf(initial.webFetch) }
    var codeExecution by remember(initial) { mutableStateOf(initial.codeExecution) }
    val codeAvailable = modelFamily == de.smartzone.pocketclaude.data.ChatModelFamilies.CLAUDE

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(de.smartzone.pocketclaude.R.string.chat_skills_dialog_title)) },
        text = {
            Column {
                Text(
                    if (isOverride)
                        stringResource(de.smartzone.pocketclaude.R.string.chat_skills_dialog_body_override)
                    else
                        stringResource(de.smartzone.pocketclaude.R.string.chat_skills_dialog_body_default),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(8.dp))
                de.smartzone.pocketclaude.ui.settings.SkillToggleRow(
                    label = stringResource(de.smartzone.pocketclaude.R.string.chat_skill_web_search_label),
                    description = stringResource(de.smartzone.pocketclaude.R.string.chat_skill_web_search_desc),
                    checked = webSearch,
                    onCheckedChange = { webSearch = it },
                )
                de.smartzone.pocketclaude.ui.settings.SkillToggleRow(
                    label = stringResource(de.smartzone.pocketclaude.R.string.chat_skill_web_fetch_label),
                    description = stringResource(de.smartzone.pocketclaude.R.string.chat_skill_web_fetch_desc),
                    checked = webFetch,
                    onCheckedChange = { webFetch = it },
                )
                de.smartzone.pocketclaude.ui.settings.SkillToggleRow(
                    label = stringResource(de.smartzone.pocketclaude.R.string.chat_skill_code_label),
                    description = stringResource(
                        if (codeAvailable) de.smartzone.pocketclaude.R.string.chat_skill_code_desc
                        else de.smartzone.pocketclaude.R.string.chat_skill_claude_only
                    ),
                    enabled = codeAvailable,
                    checked = codeExecution && codeAvailable,
                    onCheckedChange = { codeExecution = it },
                )
            }
        },
        confirmButton = {
            TextButton(onClick = {
                // `copy` statt einer neuen Instanz: sonst faellt die
                // Bild-Einstellung dieses Chats bei jedem Speichern auf den
                // Standardwert zurueck, obwohl der Dialog sie gar nicht zeigt.
                onSave(
                    initial.copy(
                        webSearch = webSearch,
                        webFetch = webFetch,
                        codeExecution = codeExecution,
                    )
                )
            }) { Text(stringResource(de.smartzone.pocketclaude.R.string.chat_skills_save_for_chat)) }
        },
        dismissButton = {
            Row {
                if (isOverride) {
                    TextButton(onClick = onReset) { Text(stringResource(de.smartzone.pocketclaude.R.string.chat_skills_reset_default)) }
                    Spacer(Modifier.width(4.dp))
                }
                TextButton(onClick = onDismiss) { Text(stringResource(de.smartzone.pocketclaude.R.string.action_cancel)) }
            }
        },
    )
}

/**
 * Per-Chat-Auto-Speak-Dialog. Drei Optionen: an / aus / globalen Default
 * nutzen. Override lebt nur app-lokal (DataStore), nicht server-seitig.
 */
@Composable
private fun ChatAutoSpeakDialog(
    globalDefault: Boolean,
    override: Boolean?,
    onSave: (Boolean?) -> Unit,
    onDismiss: () -> Unit,
) {
    val onLbl = stringResource(de.smartzone.pocketclaude.R.string.chat_auto_speak_on)
    val offLbl = stringResource(de.smartzone.pocketclaude.R.string.chat_auto_speak_off)
    val defaultLabel = stringResource(de.smartzone.pocketclaude.R.string.chat_auto_speak_default_label, if (globalDefault) onLbl else offLbl)
    val options = listOf<Pair<String, Boolean?>>(
        defaultLabel to null,
        stringResource(de.smartzone.pocketclaude.R.string.chat_auto_speak_always_on) to true,
        stringResource(de.smartzone.pocketclaude.R.string.chat_auto_speak_always_off) to false,
    )
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(de.smartzone.pocketclaude.R.string.chat_auto_speak_dialog_title)) },
        text = {
            Column {
                Text(
                    stringResource(de.smartzone.pocketclaude.R.string.chat_auto_speak_dialog_body),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(8.dp))
                options.forEach { (label, value) ->
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        modifier = Modifier
                            .fillMaxWidth()
                            .clickable { onSave(value) }
                            .padding(vertical = 8.dp),
                    ) {
                        val selected = override == value
                        Icon(
                            imageVector = if (selected) PocketIcons.CheckCircle
                                          else PocketIcons.RadioUnchecked,
                            contentDescription = null,
                            tint = if (selected) MaterialTheme.colorScheme.primary
                                   else MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.size(PocketIconSize.Regular),
                        )
                        Spacer(Modifier.width(12.dp))
                        Text(
                            label,
                            style = MaterialTheme.typography.bodyMedium,
                            fontWeight = if (selected) FontWeight.SemiBold
                                         else FontWeight.Normal,
                        )
                    }
                }
            }
        },
        confirmButton = {
            TextButton(onClick = onDismiss) { Text(stringResource(de.smartzone.pocketclaude.R.string.action_close)) }
        },
    )
}

@OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)
@Composable
private fun GemWelcome(
    emoji: String,
    name: String,
    description: String,
    starters: List<String>,
    onStarter: (String) -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text(emoji.ifBlank { "🤖" }, style = MaterialTheme.typography.displaySmall)
        if (name.isNotBlank()) {
            Text(
                name,
                style = MaterialTheme.typography.headlineSmall,
            )
        }
        if (description.isNotBlank()) {
            Text(
                description,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                textAlign = androidx.compose.ui.text.style.TextAlign.Center,
            )
        }
        if (starters.isNotEmpty()) {
            Spacer(Modifier.height(4.dp))
            // Mittig wie Emoji, Name und Beschreibung darueber.
            FlowRow(
                horizontalArrangement = Arrangement.spacedBy(8.dp, Alignment.CenterHorizontally),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                starters.forEach { s ->
                    // Radius 24 statt Kreisform: lange Starter brechen um und
                    // wuerden als Kreisform zu einer Linse.
                    AssistChip(
                        onClick = { onStarter(s) },
                        label = { Text(s, modifier = Modifier.padding(vertical = 6.dp)) },
                        shape = RoundedCornerShape(PocketRadius.Large),
                    )
                }
            }
        }
    }
}

/** Hoechstzahl Bilder pro Auswahl im Foto-Picker. */
private const val MAX_PICK = 10

private fun shareMarkdownIntent(context: android.content.Context, title: String, markdown: String) {
    // Markdown in temp-Datei, Share via FileProvider als .md
    try {
        val safe = title.replace(Regex("""[^\p{L}\p{N}\-_ ]"""), "_").take(60).trim().ifBlank { "chat" }
        val file = java.io.File(context.cacheDir, "exports").apply { mkdirs() }
            .let { java.io.File(it, "$safe.md") }
        file.writeText(markdown, Charsets.UTF_8)
        val uri = androidx.core.content.FileProvider.getUriForFile(
            context, "${context.packageName}.fileprovider", file,
        )
        val intent = android.content.Intent(android.content.Intent.ACTION_SEND).apply {
            type = "text/markdown"
            putExtra(android.content.Intent.EXTRA_STREAM, uri)
            putExtra(android.content.Intent.EXTRA_SUBJECT, title)
            putExtra(android.content.Intent.EXTRA_TEXT, markdown.take(4000))
            addFlags(android.content.Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        context.startActivity(android.content.Intent.createChooser(intent, context.getString(de.smartzone.pocketclaude.R.string.chat_share_chooser_title)))
    } catch (e: Exception) {
        android.widget.Toast.makeText(context, context.getString(de.smartzone.pocketclaude.R.string.chat_share_failed, e.message ?: ""), android.widget.Toast.LENGTH_LONG).show()
    }
}

@Composable
private fun effortTint(effort: String): Color = when (effort) {
    "off" -> MaterialTheme.colorScheme.onSurfaceVariant
    "low", "medium" -> MaterialTheme.colorScheme.onSurface
    else -> MaterialTheme.colorScheme.primary
}

@Composable
private fun SearchBarTitle(
    query: String,
    onQueryChange: (String) -> Unit,
    matchCount: Int,
    currentIndex: Int,
) {
    val focusRequester = remember { androidx.compose.ui.focus.FocusRequester() }
    LaunchedEffect(Unit) {
        // Beim Eintreten in den Suchmodus den Fokus aufs Feld setzen, damit
        // die Tastatur sofort aufgeht. Kleine Verzögerung damit das Layout fertig ist.
        kotlinx.coroutines.delay(50)
        runCatching { focusRequester.requestFocus() }
    }
    Row(verticalAlignment = Alignment.CenterVertically) {
        OutlinedTextField(
            value = query,
            onValueChange = onQueryChange,
            placeholder = { Text(stringResource(de.smartzone.pocketclaude.R.string.search_in_chat)) },
            singleLine = true,
            modifier = Modifier
                .weight(1f)
                .focusRequester(focusRequester),
            shape = RoundedCornerShape(12.dp),
            colors = OutlinedTextFieldDefaults.colors(
                unfocusedBorderColor = androidx.compose.ui.graphics.Color.Transparent,
                focusedBorderColor = androidx.compose.ui.graphics.Color.Transparent,
                focusedContainerColor = androidx.compose.ui.graphics.Color.Transparent,
                unfocusedContainerColor = androidx.compose.ui.graphics.Color.Transparent,
            ),
        )
        if (query.isNotBlank()) {
            val label = if (matchCount == 0) "0"
            else "${currentIndex + 1}/${matchCount}"
            Text(
                label,
                style = MaterialTheme.typography.labelMedium,
                color = if (matchCount == 0) MaterialTheme.colorScheme.error
                        else MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(horizontal = 8.dp),
            )
        }
    }
}

private fun queryName(context: android.content.Context, uri: Uri): String? {
    return try {
        context.contentResolver.query(uri, null, null, null, null)?.use { c ->
            val idx = c.getColumnIndex(android.provider.OpenableColumns.DISPLAY_NAME)
            if (idx >= 0 && c.moveToFirst()) c.getString(idx) else null
        }
    } catch (_: Exception) {
        null
    }
}

/**
 * Scrollt eine LazyColumn zuverlässig ans **absolute Ende**, auch bei sehr
 * langen letzten Items (Markdown-Bubbles, Code-Blöcke, Bilder), deren wahre
 * Höhe progressive über mehrere Layout-Passes erst entsteht.
 *
 * Pattern: scrollToItem mit großem scrollOffset → LazyColumn clamped die
 * Position so, dass das Item-Bottom am Viewport-Bottom sitzt. Mehrfach mit
 * kurzen Pausen wiederholen, weil sich die Item-Höhe noch ändern kann
 * (Markdown-Rendering, Image-Loading). Bricht ab, sobald wirklich am Ende
 * oder nach ~600ms.
 */
private suspend fun scrollToVeryBottom(listState: androidx.compose.foundation.lazy.LazyListState) {
    val totalAtStart = listState.layoutInfo.totalItemsCount
    if (totalAtStart == 0) return

    var attempts = 0
    while (attempts < 12) {
        val total = listState.layoutInfo.totalItemsCount
        val lastIdx = (total - 1).coerceAtLeast(0)
        // Großer scrollOffset → das Item wird so weit "rausgeschoben", dass
        // LazyColumn auf "Item-Bottom am Viewport-Bottom" clamped. Anders als
        // scrollBy weiß scrollToItem, dass es das Item zuerst messen muss.
        listState.scrollToItem(lastIdx, scrollOffset = 1_000_000)
        kotlinx.coroutines.delay(50)

        val info = listState.layoutInfo
        val last = info.visibleItemsInfo.lastOrNull() ?: break
        val atBottom = last.index >= info.totalItemsCount - 1 &&
            (last.offset + last.size) <= info.viewportEndOffset + 4
        if (atBottom) return
        attempts++
    }
}

/**
 * "Ab hier weitermachen": springt zu einer frueheren Antwort zurueck und laesst
 * im selben Zug das Modell wechseln.
 *
 * Beides gehoert zusammen, weil man meistens genau deshalb zurueckspringt:
 * die Antwort hat nicht gefallen, also nochmal, aber mit einem anderen Modell.
 * Zwei getrennte Schritte waeren hier eine Schikane.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun RewindDialog(
    droppedCount: Int,
    models: List<ChatModelOption>,
    currentModelKey: String,
    onConfirm: (String?) -> Unit,
    onDismiss: () -> Unit,
) {
    var chosenKey by remember(currentModelKey) { mutableStateOf(currentModelKey) }

    AlertDialog(
        onDismissRequest = onDismiss,
        icon = { Icon(PocketIcons.History, contentDescription = null) },
        title = { Text(stringResource(de.smartzone.pocketclaude.R.string.rewind_dialog_title)) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Text(
                    pluralStringResource(
                        de.smartzone.pocketclaude.R.plurals.rewind_dialog_body,
                        droppedCount, droppedCount,
                    ),
                    style = MaterialTheme.typography.bodyMedium,
                )
                if (models.isNotEmpty()) {
                    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                    Text(
                        stringResource(de.smartzone.pocketclaude.R.string.rewind_dialog_model_label),
                        style = MaterialTheme.typography.labelMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    FlowRow(
                        horizontalArrangement = Arrangement.spacedBy(6.dp),
                        verticalArrangement = Arrangement.spacedBy(6.dp),
                    ) {
                        models.forEach { option ->
                            PocketChoiceChip(
                                selected = option.key == chosenKey,
                                onClick = { chosenKey = option.key },
                                label = option.label,
                            )
                        }
                    }
                }
            }
        },
        confirmButton = {
            TextButton(onClick = {
                // Nur mitschicken, was sich wirklich aendert: sonst wuerde ein
                // unveraendertes Modell serverseitig als Wechsel gewertet.
                onConfirm(chosenKey.takeIf { it != currentModelKey })
            }) {
                Text(stringResource(de.smartzone.pocketclaude.R.string.rewind_dialog_confirm))
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) {
                Text(stringResource(de.smartzone.pocketclaude.R.string.action_cancel))
            }
        },
    )
}


@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
private fun ModelSheet(
    models: List<ChatModelOption>,
    gateways: List<GatewayStatusDto>,
    selectedKey: String,
    effortForModel: (String, ChatModelOption?) -> String,
    availableEfforts: (String, ChatModelOption?) -> List<String>,
    loading: Boolean,
    errorText: String?,
    onSelectModel: (ChatModelOption) -> Unit,
    onSelectEffort: (family: String, effort: String) -> Unit,
    onRefresh: () -> Unit,
    onDismiss: () -> Unit,
) {
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    val selectedOption = models.firstOrNull { it.key == selectedKey }
    val selectedFamily = selectedOption?.family ?: familyForKey(selectedKey)
    // Die angezeigte Stufe ist die, die wirklich gilt: die Familien-Vorgabe,
    // geklemmt auf das, was dieses Modell kann.
    val currentEffort = effortForModel(selectedKey, selectedOption)
    val currentEffortText = effortLabel(currentEffort)

    val currentModelLabel = when {
        selectedKey.isBlank() -> stringResource(de.smartzone.pocketclaude.R.string.model_auto)
        selectedOption != null -> selectedOption.label
        else -> ClaudeModels.labelFor(selectedKey) ?: selectedKey
    }

    ModalBottomSheet(
        onDismissRequest = onDismiss,
        sheetState = sheetState,
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .verticalScroll(rememberScrollState())
                .navigationBarsPadding(),
        ) {
            // 1. Kopfzeile
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp, vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = stringResource(de.smartzone.pocketclaude.R.string.model_sheet_title),
                        style = MaterialTheme.typography.titleMedium,
                    )
                    Text(
                        text = "$currentModelLabel · $currentEffortText",
                        style = MaterialTheme.typography.labelMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                if (loading) {
                    Box(
                        modifier = Modifier.size(48.dp),
                        contentAlignment = Alignment.Center,
                    ) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(PocketIconSize.Small),
                            strokeWidth = 2.dp,
                        )
                    }
                } else {
                    IconButton(onClick = onRefresh) {
                        Icon(
                            PocketIcons.Refresh,
                            contentDescription = stringResource(
                                de.smartzone.pocketclaude.R.string.model_refresh,
                            ),
                        )
                    }
                }
            }

            // 2. Fehlermeldung
            if (errorText != null) {
                Text(
                    text = errorText,
                    color = MaterialTheme.colorScheme.error,
                    style = MaterialTheme.typography.bodySmall,
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 16.dp, vertical = 4.dp),
                )
            }

            // 3., 4. und 5. Abschnitte nach ChatModelFamilies.order
            ChatModelFamilies.order.forEach { family ->
                val familyModels = models.filter { it.family == family }
                val isClaude = family == ChatModelFamilies.CLAUDE
                if (isClaude || familyModels.isNotEmpty()) {
                    val familyTitle = when (family) {
                        ChatModelFamilies.CLAUDE -> stringResource(de.smartzone.pocketclaude.R.string.model_family_claude)
                        ChatModelFamilies.GEMINI -> stringResource(de.smartzone.pocketclaude.R.string.model_family_gemini)
                        ChatModelFamilies.GPT -> stringResource(de.smartzone.pocketclaude.R.string.model_family_gpt)
                        else -> stringResource(de.smartzone.pocketclaude.R.string.model_family_other)
                    }

                    // Abschnitts-Ueberschrift
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(start = 16.dp, end = 16.dp, top = 12.dp, bottom = 4.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(
                            text = familyTitle,
                            style = MaterialTheme.typography.titleSmall,
                            color = MaterialTheme.colorScheme.primary,
                        )
                        if (isClaude) {
                            Spacer(Modifier.width(8.dp))
                            Text(
                                text = stringResource(de.smartzone.pocketclaude.R.string.model_family_claude_hint),
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                    }

                    // 4. Automatisch-Zeile bei Claude
                    if (isClaude) {
                        val autoLabel = stringResource(de.smartzone.pocketclaude.R.string.model_auto)
                        val isAutoSelected = selectedKey.isEmpty()
                        val autoOption = ChatModelOption(
                            key = "",
                            family = ChatModelFamilies.CLAUDE,
                            label = autoLabel,
                            efforts = EFFORT_LEVELS,
                        )
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .heightIn(min = 48.dp)
                                .clickable { onSelectModel(autoOption) }
                                .padding(horizontal = 16.dp, vertical = 10.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            if (isAutoSelected) {
                                Icon(
                                    PocketIcons.Check,
                                    contentDescription = null,
                                    tint = MaterialTheme.colorScheme.primary,
                                    modifier = Modifier.size(PocketIconSize.Regular),
                                )
                            } else {
                                Spacer(Modifier.size(20.dp))
                            }
                            Spacer(Modifier.width(12.dp))
                            Text(
                                text = autoLabel,
                                style = MaterialTheme.typography.bodyMedium,
                                fontWeight = if (isAutoSelected) FontWeight.SemiBold else FontWeight.Normal,
                            )
                        }
                    }

                    // 5. Modell-Zeilen
                    familyModels.forEach { model ->
                        val isSelected = selectedKey == model.key
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .heightIn(min = 48.dp)
                                .clickable { onSelectModel(model) }
                                .padding(horizontal = 16.dp, vertical = 10.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            if (isSelected) {
                                Icon(
                                    PocketIcons.Check,
                                    contentDescription = null,
                                    tint = MaterialTheme.colorScheme.primary,
                                    modifier = Modifier.size(PocketIconSize.Regular),
                                )
                            } else {
                                Spacer(Modifier.size(20.dp))
                            }
                            Spacer(Modifier.width(12.dp))
                            Column(modifier = Modifier.weight(1f)) {
                                Text(
                                    text = model.label,
                                    style = MaterialTheme.typography.bodyMedium,
                                    fontWeight = if (isSelected) FontWeight.SemiBold else FontWeight.Normal,
                                )
                                if (model.gatewayLabel.isNotBlank()) {
                                    Text(
                                        text = model.gatewayLabel,
                                        style = MaterialTheme.typography.labelSmall,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    )
                                }
                            }
                        }
                    }
                }
            }

            // 6. Nicht erreichbare Gateways
            val unreachableGateways = gateways.filter { !it.reachable }
            if (unreachableGateways.isNotEmpty()) {
                val firstError = unreachableGateways.firstNotNullOfOrNull { it.lastError?.takeIf { err -> err.isNotBlank() } }
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 16.dp, vertical = 8.dp),
                ) {
                    Text(
                        text = stringResource(de.smartzone.pocketclaude.R.string.model_gateway_unreachable),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.error,
                    )
                    if (!firstError.isNullOrBlank()) {
                        Text(
                            text = firstError,
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }

            // 7. HorizontalDivider und Denktiefe
            HorizontalDivider(modifier = Modifier.padding(vertical = 8.dp))

            Text(
                text = stringResource(de.smartzone.pocketclaude.R.string.effort_label),
                style = MaterialTheme.typography.titleSmall,
                color = MaterialTheme.colorScheme.primary,
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp),
            )

            // Nur die Stufen anbieten, die das gewaehlte Modell wirklich kann.
            // „Automatisch" bei Claude hat kein konkretes Modell, dort gelten die
            // Claude-Stufen. Ein Modell ohne gemeldete Stufen bekommt gar keine
            // Auswahl, statt eine vorzutaeuschen, die der Server verwirft.
            // Eine einzige Quelle fuer „welche Stufen gibt es hier": dieselbe
            // Funktion, die auch der Sendepfad benutzt. Fuer Zusatz-Modelle ist
            // „aus" nie dabei, das kennen die Gateways nicht.
            val modelEfforts = availableEfforts(selectedFamily, selectedOption)
            val displayEfforts = EFFORT_LEVELS_ALL.filter { it in modelEfforts }

            if (displayEfforts.isEmpty()) {
                Text(
                    text = stringResource(de.smartzone.pocketclaude.R.string.effort_not_supported),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp),
                )
            }
            FlowRow(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp, vertical = 4.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                displayEfforts.forEach { effort ->
                    val isEffortSelected = effort == currentEffort
                    PocketChoiceChip(
                        selected = isEffortSelected,
                        onClick = { onSelectEffort(selectedFamily, effort) },
                        label = effortLabel(effort),
                    )
                }
            }

            Spacer(Modifier.height(8.dp))
        }
    }
}

@Composable
private fun effortLabel(effort: String): String = when (effort) {
    "off" -> stringResource(de.smartzone.pocketclaude.R.string.effort_off_label)
    "minimal" -> stringResource(de.smartzone.pocketclaude.R.string.effort_minimal_label)
    "low" -> stringResource(de.smartzone.pocketclaude.R.string.effort_low_label)
    "medium" -> stringResource(de.smartzone.pocketclaude.R.string.effort_medium_label)
    "high" -> stringResource(de.smartzone.pocketclaude.R.string.effort_high_label)
    "xhigh" -> stringResource(de.smartzone.pocketclaude.R.string.effort_xhigh_label)
    "max" -> stringResource(de.smartzone.pocketclaude.R.string.effort_max_label)
    "ultra" -> stringResource(de.smartzone.pocketclaude.R.string.effort_ultra_label)
    else -> effort
}
