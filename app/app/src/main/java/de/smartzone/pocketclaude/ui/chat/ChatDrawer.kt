package de.smartzone.pocketclaude.ui.chat

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.consumeWindowInsets
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalDrawerSheet
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.RectangleShape
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import de.smartzone.pocketclaude.R
import de.smartzone.pocketclaude.data.ConversationDto
import de.smartzone.pocketclaude.data.GemDto
import de.smartzone.pocketclaude.data.SearchHitDto
import de.smartzone.pocketclaude.ui.conversations.highlightSnippet
import de.smartzone.pocketclaude.ui.theme.PocketIconSize
import de.smartzone.pocketclaude.ui.theme.PocketIcons
import kotlinx.coroutines.delay

/**
 * Seitenleiste nach dem Vorbild der ChatGPT-App (Joscha 19.10.2026, am Handy
 * vermessen): 80 % der Breite, rechts bleibt der abgedunkelte Chat sichtbar
 * und schliesst die Leiste beim Antippen. Oben Name und Suchfeld, darunter
 * Eintraege mit Symbol, dann Gems, Angeheftet und Letzte, die Chats als reine
 * Textzeilen ohne Symbol. Unten schweben "Neuer Chat" und die Einstellungen.
 *
 * Die Suche filtert sofort nach Titeln und fragt nach kurzer Pause zusaetzlich
 * die Volltextsuche des Servers (gleiche Treffer wie unter "Alle Gespraeche").
 */
@Composable
internal fun ChatDrawerContent(
    open: Boolean,
    currentCid: String,
    chats: List<ConversationDto>,
    gems: List<GemDto>,
    onNewChat: () -> Unit,
    onStartGem: (String) -> Unit,
    onGenerateImages: () -> Unit,
    onSwitch: (String) -> Unit,
    onAllChats: () -> Unit,
    onSettings: () -> Unit,
) {
    val context = LocalContext.current
    val container = remember {
        (context.applicationContext as de.smartzone.pocketclaude.PocketClaudeApp).container
    }
    val focusManager = LocalFocusManager.current
    // Bilder-Eintrag nur, wenn ueberhaupt ein Bild-Anbieter erreichbar ist.
    var imageGenAvailable by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) {
        runCatching { container.chatRepository.imagesConfig() }
            .onSuccess { cfg -> imageGenAvailable = cfg.configured }
    }
    // Profilbild statt Zahnrad unten rechts, wenn eines hinterlegt ist (wie
    // in der Web-UI). Die Version in der URL haelt den Bild-Cache aktuell.
    var avatarUrl by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(open) {
        if (!open) return@LaunchedEffect
        runCatching { container.chatRepository.me() }.onSuccess { me ->
            val s = container.settingsRepository.current()
            avatarUrl = me.avatarVersion?.let { v ->
                "${s.serverUrl}/users/${android.net.Uri.encode(me.id)}/avatar" +
                    "?v=$v&token=${android.net.Uri.encode(s.serverToken)}"
            }
        }
    }

    var query by remember { mutableStateOf("") }
    // Treffer merken sich ihren Suchbegriff: alte Volltexttreffer duerfen nicht
    // neben den Titeltreffern eines neuen Begriffs stehen bleiben.
    var hits by remember { mutableStateOf<Pair<String, List<SearchHitDto>>>("" to emptyList()) }
    var searching by remember { mutableStateOf(false) }
    // Beim Schliessen leeren, sonst oeffnet die Leiste beim naechsten Mal
    // mitten in einer alten Suche.
    LaunchedEffect(open) {
        if (!open) {
            query = ""
            focusManager.clearFocus()
        }
    }
    LaunchedEffect(query) {
        val q = query.trim()
        if (q.isEmpty()) {
            hits = "" to emptyList()
            searching = false
            return@LaunchedEffect
        }
        searching = true
        delay(250)
        val found = try {
            container.chatRepository.search(q).hits
        } catch (e: kotlinx.coroutines.CancellationException) {
            throw e
        } catch (e: Exception) {
            android.util.Log.w("PC_NET", "drawer search failed: ${e.message}")
            emptyList()
        }
        hits = q to found
        searching = false
    }

    val screenWidth = LocalConfiguration.current.screenWidthDp.dp
    val untitled = stringResource(R.string.chat_untitled)
    ModalDrawerSheet(
        modifier = Modifier.width((screenWidth * 0.8f).coerceAtMost(360.dp)),
        drawerShape = RectangleShape,
        drawerContainerColor = MaterialTheme.colorScheme.surfaceContainerLowest,
        drawerContentColor = MaterialTheme.colorScheme.onSurface,
    ) {
        // Tastatur der Suche schiebt Liste und untere Knoepfe hoch, statt sie
        // zu verdecken. Die Navigationsleiste rechnet der Sheet schon ein.
        Box(
            Modifier
                .fillMaxSize()
                .consumeWindowInsets(WindowInsets.navigationBars)
                .imePadding(),
        ) {
            Column(Modifier.fillMaxSize()) {
                Text(
                    stringResource(R.string.app_name),
                    style = MaterialTheme.typography.headlineMedium,
                    maxLines = 1,
                    modifier = Modifier.padding(start = SIDE, end = 16.dp, top = 20.dp, bottom = 12.dp),
                )
                DrawerSearchField(query = query, onQueryChange = { query = it })
                LazyColumn(
                    modifier = Modifier.fillMaxWidth().weight(1f),
                    contentPadding = PaddingValues(top = 8.dp, bottom = 96.dp),
                ) {
                    val q = query.trim()
                    if (q.isEmpty()) {
                        if (imageGenAvailable) {
                            item { DrawerNavItem(PocketIcons.Image, stringResource(R.string.title_images), onGenerateImages) }
                        }
                        item { DrawerNavItem(PocketIcons.Forum, stringResource(R.string.all_conversations), onAllChats) }
                        if (gems.isNotEmpty()) {
                            item { DrawerSection(stringResource(R.string.section_gems)) }
                            items(gems, key = { "gem-" + it.id }) { gem ->
                                DrawerRow(onClick = { onStartGem(gem.id) }) {
                                    Box(Modifier.size(PocketIconSize.Regular), contentAlignment = Alignment.Center) {
                                        Text(gem.emoji.ifBlank { "🤖" }, style = MaterialTheme.typography.titleMedium)
                                    }
                                    Spacer(Modifier.width(ICON_GAP))
                                    RowLabel(gem.name)
                                }
                            }
                        }
                        val pinned = chats.filter { it.pinned }
                        if (pinned.isNotEmpty()) {
                            item { DrawerSection(stringResource(R.string.convo_pinned)) }
                            items(pinned, key = { "pin-" + it.id }) { conv ->
                                ChatRow(conv.title.ifBlank { untitled }, conv.id == currentCid) { onSwitch(conv.id) }
                            }
                        }
                        item { DrawerSection(stringResource(R.string.recent_chats)) }
                        items(chats.filterNot { it.pinned }.take(RECENT_LIMIT), key = { it.id }) { conv ->
                            ChatRow(conv.title.ifBlank { untitled }, conv.id == currentCid) { onSwitch(conv.id) }
                        }
                    } else {
                        val titleMatches = chats.filter { it.title.contains(q, ignoreCase = true) }
                        val titleIds = titleMatches.map { it.id }.toSet()
                        // Pro Chat nur der beste Treffer; Chats, die schon ueber
                        // den Titel gefunden wurden, nicht doppelt.
                        val messageHits = (if (hits.first == q) hits.second else emptyList())
                            .distinctBy { it.conversationId }
                            .filterNot { it.conversationId in titleIds }
                        items(titleMatches, key = { "t-" + it.id }) { conv ->
                            ChatRow(conv.title.ifBlank { untitled }, conv.id == currentCid) { onSwitch(conv.id) }
                        }
                        items(messageHits, key = { "m-" + it.conversationId }) { hit ->
                            ChatRow(
                                title = hit.conversationTitle.ifBlank { untitled },
                                selected = hit.conversationId == currentCid,
                                snippet = hit.snippet,
                            ) { onSwitch(hit.conversationId) }
                        }
                        if (titleMatches.isEmpty() && messageHits.isEmpty() && !searching) {
                            item {
                                Text(
                                    stringResource(R.string.search_no_matches),
                                    style = MaterialTheme.typography.bodyLarge,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    modifier = Modifier.padding(horizontal = SIDE, vertical = 12.dp),
                                )
                            }
                        }
                    }
                }
            }
            DrawerBottomBar(
                onNewChat = onNewChat,
                onSettings = onSettings,
                avatarUrl = avatarUrl,
                modifier = Modifier.align(Alignment.BottomCenter),
            )
        }
    }
}

/** Suchfeld als graue Pille, wie die Suche in der ChatGPT-App. */
@Composable
private fun DrawerSearchField(query: String, onQueryChange: (String) -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp)
            .height(44.dp)
            .clip(CircleShape)
            .background(MaterialTheme.colorScheme.surfaceVariant)
            .padding(start = 12.dp, end = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(
            PocketIcons.Search,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.size(PocketIconSize.Regular),
        )
        Spacer(Modifier.width(8.dp))
        BasicTextField(
            value = query,
            onValueChange = onQueryChange,
            singleLine = true,
            textStyle = MaterialTheme.typography.bodyLarge.copy(color = MaterialTheme.colorScheme.onSurface),
            cursorBrush = SolidColor(MaterialTheme.colorScheme.primary),
            modifier = Modifier.weight(1f),
            decorationBox = { inner ->
                Box(contentAlignment = Alignment.CenterStart) {
                    if (query.isEmpty()) {
                        Text(
                            stringResource(R.string.action_search),
                            style = MaterialTheme.typography.bodyLarge,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    inner()
                }
            },
        )
        if (query.isNotEmpty()) {
            Box(
                modifier = Modifier
                    .size(36.dp)
                    .clip(CircleShape)
                    .clickable(role = Role.Button) { onQueryChange("") },
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    PocketIcons.Close,
                    contentDescription = stringResource(R.string.action_close),
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.size(PocketIconSize.Small),
                )
            }
        }
    }
}

/** Zeile mit Symbol: Icon bei 32 dp, Beschriftung bei 68 dp, 48 dp hoch. */
@Composable
private fun DrawerNavItem(icon: ImageVector, label: String, onClick: () -> Unit) {
    DrawerRow(onClick = onClick) {
        Icon(icon, contentDescription = null, modifier = Modifier.size(PocketIconSize.Regular))
        Spacer(Modifier.width(ICON_GAP))
        RowLabel(label)
    }
}

/** Chat als reine Textzeile; der offene Chat ist grau hinterlegt. */
@Composable
private fun ChatRow(title: String, selected: Boolean, snippet: String? = null, onClick: () -> Unit) {
    DrawerRow(onClick = onClick, selected = selected) {
        Column(Modifier.weight(1f)) {
            RowLabel(title)
            if (!snippet.isNullOrBlank()) {
                Text(
                    highlightSnippet(snippet),
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
    }
}

/**
 * Gemeinsamer Zeilenrahmen. Die Auswahl-Pille sitzt 16 dp vom Rand, der Inhalt
 * beginnt trotzdem bei 32 dp, buendig mit Titel und Abschnitten.
 */
@Composable
private fun DrawerRow(
    onClick: () -> Unit,
    selected: Boolean = false,
    content: @Composable androidx.compose.foundation.layout.RowScope.() -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp)
            .heightIn(min = 48.dp)
            .clip(RoundedCornerShape(24.dp))
            .background(if (selected) MaterialTheme.colorScheme.secondaryContainer else Color.Transparent)
            .clickable(onClick = onClick)
            .padding(horizontal = 16.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
        content = content,
    )
}

@Composable
private fun RowLabel(text: String) {
    Text(
        text,
        style = MaterialTheme.typography.bodyLarge,
        maxLines = 1,
        overflow = TextOverflow.Ellipsis,
    )
}

/** Abschnittstitel fett wie "Angeheftet" und "Letzte" bei ChatGPT. */
@Composable
private fun DrawerSection(text: String) {
    Text(
        text,
        style = MaterialTheme.typography.titleMedium,
        fontWeight = FontWeight.Bold,
        modifier = Modifier.padding(start = SIDE, end = SIDE, top = 24.dp, bottom = 8.dp),
    )
}

/**
 * Schwebende Knoepfe unten: links die blaue "Neuer Chat"-Pille, rechts der
 * runde Einstellungen-Knopf. Ein Verlauf blendet die Liste darunter aus.
 */
@Composable
private fun DrawerBottomBar(
    onNewChat: () -> Unit,
    onSettings: () -> Unit,
    modifier: Modifier,
    avatarUrl: String? = null,
) {
    val bg = MaterialTheme.colorScheme.surfaceContainerLowest
    Row(
        modifier = modifier
            .fillMaxWidth()
            .background(Brush.verticalGradient(listOf(bg.copy(alpha = 0f), bg.copy(alpha = 0.9f), bg)))
            .padding(start = SIDE, end = 20.dp, top = 24.dp, bottom = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Surface(
            onClick = onNewChat,
            shape = CircleShape,
            color = MaterialTheme.colorScheme.primary,
            contentColor = MaterialTheme.colorScheme.onPrimary,
            shadowElevation = 3.dp,
        ) {
            Row(
                modifier = Modifier.height(48.dp).padding(start = 16.dp, end = 20.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(PocketIcons.NewChat, contentDescription = null, modifier = Modifier.size(PocketIconSize.Regular))
                Spacer(Modifier.width(8.dp))
                Text(stringResource(R.string.new_chat), style = MaterialTheme.typography.titleMedium)
            }
        }
        val dark = MaterialTheme.colorScheme.background.luminance() < 0.5f
        Surface(
            onClick = onSettings,
            shape = CircleShape,
            color = if (dark) MaterialTheme.colorScheme.surfaceContainerHigh
                else MaterialTheme.colorScheme.surfaceContainerLowest,
            contentColor = MaterialTheme.colorScheme.onSurface,
            shadowElevation = 3.dp,
            modifier = Modifier.size(48.dp),
        ) {
            Box(contentAlignment = Alignment.Center) {
                if (avatarUrl != null) {
                    coil3.compose.AsyncImage(
                        model = avatarUrl,
                        contentDescription = stringResource(R.string.title_settings),
                        contentScale = androidx.compose.ui.layout.ContentScale.Crop,
                        modifier = Modifier.fillMaxSize().clip(CircleShape),
                    )
                } else {
                    Icon(
                        PocketIcons.Settings,
                        contentDescription = stringResource(R.string.title_settings),
                        modifier = Modifier.size(PocketIconSize.Regular),
                    )
                }
            }
        }
    }
}

private val SIDE = 32.dp
private val ICON_GAP = 12.dp
private const val RECENT_LIMIT = 40
