package de.smartzone.pocketclaude.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.ui.res.stringResource
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import kotlinx.coroutines.launch
import de.smartzone.pocketclaude.data.AppContainer
import de.smartzone.pocketclaude.ui.chat.ChatScreen
import de.smartzone.pocketclaude.ui.chat.ChatViewModel
import de.smartzone.pocketclaude.ui.conversations.ConversationsScreen
import de.smartzone.pocketclaude.ui.conversations.ConversationsViewModel
import de.smartzone.pocketclaude.ui.gems.GemEditorScreen
import de.smartzone.pocketclaude.ui.gems.GemsViewModel
import de.smartzone.pocketclaude.ui.settings.SettingsScreen
import de.smartzone.pocketclaude.ui.settings.SettingsViewModel
import de.smartzone.pocketclaude.ui.components.PocketBackdrop
import de.smartzone.pocketclaude.ui.components.PocketBrandMark
import de.smartzone.pocketclaude.ui.theme.PocketIconSize

object Routes {
    /** Startroute: erzeugt einen frischen Chat (oder zeigt Setup-Hinweis) und leitet weiter. */
    const val LAUNCH = "launch"
    const val CONVERSATIONS = "conversations"
    const val CHAT = "chat/{cid}"
    const val SETTINGS = "settings"
    /** Standalone-Screen für die Bild-Generation (Gemini/Nano Banana). */
    const val IMAGES = "images"
    /** Gem-Editor (Create ohne Args; Edit mit gemId; Duplizieren mit dup=Quell-ID). */
    const val GEM_EDITOR = "gem_editor?gemId={gemId}&dup={dup}"
    fun chat(cid: String) = "chat/$cid"
    fun gemEditor(gemId: String? = null) =
        if (gemId == null) "gem_editor" else "gem_editor?gemId=$gemId"
    fun gemDuplicate(sourceId: String) = "gem_editor?dup=$sourceId"
}

@Composable
fun PocketNav(
    container: AppContainer,
    initialChatCid: String? = null,
    shareNonce: Int = 0,
    voiceNonce: Int = 0,
) {
    val nav = rememberNavController()
    val coroutineScope = androidx.compose.runtime.rememberCoroutineScope()
    val context = androidx.compose.ui.platform.LocalContext.current

    // Share-to-PocketClaude bei BEREITS offener App: frischen Chat anlegen und
    // dorthin navigieren. ChatScreen holt den geteilten Inhalt aus
    // container.pendingShare ab. shareNonce == 0 ist der Kaltstart — der läuft
    // über LaunchScreen, daher hier das Guard.
    LaunchedEffect(shareNonce) {
        if (shareNonce <= 0 || container.pendingShare == null) return@LaunchedEffect
        runCatching { container.chatRepository.create() }
            .onSuccess { fresh ->
                nav.navigate(Routes.chat(fresh.id)) {
                    popUpTo(Routes.CHAT) { inclusive = true }
                    launchSingleTop = true
                }
            }
    }

    // Neuer Sprach-Chat bei BEREITS offener App (Assistenten-Taste, Kachel,
    // Verknuepfung): frischen Chat anlegen, ChatScreen startet dort das
    // Diktat. Den Kaltstart erledigt der Launch-Screen. Eigener Scope statt
    // des Effekts: ein weiterer Druck darf ein laufendes Anlegen nicht
    // abbrechen, sonst laege der Chat auf dem Server und die App bliebe stehen.
    LaunchedEffect(voiceNonce) {
        if (voiceNonce <= 0) return@LaunchedEffect
        coroutineScope.launch {
            try {
                val cid = container.voiceChat.createIfRequested {
                    container.chatRepository.create().id
                } ?: return@launch
                nav.navigate(Routes.chat(cid)) {
                    popUpTo(Routes.CHAT) { inclusive = true }
                    launchSingleTop = true
                }
            } catch (e: kotlinx.coroutines.CancellationException) {
                throw e
            } catch (e: Exception) {
                android.widget.Toast.makeText(
                    context,
                    context.getString(
                        de.smartzone.pocketclaude.R.string.connection_failed_prefix,
                        e.message ?: e::class.java.simpleName,
                    ),
                    android.widget.Toast.LENGTH_LONG,
                ).show()
            }
        }
    }

    // Re-Open mit cid aus Notification, App war bereits geladen: zum Ziel-Chat
    // navigieren statt am Launch hängen zu bleiben.
    LaunchedEffect(initialChatCid) {
        val cid = initialChatCid ?: return@LaunchedEffect
        val current = nav.currentBackStackEntry?.destination?.route ?: return@LaunchedEffect
        // Der Launch-Screen oeffnet den Chat selbst. Von ueberall sonst
        // (auch Einstellungen, Chatliste, Gem-Editor) zum Ziel springen;
        // vorher endete der Tipp auf die Benachrichtigung dort im Nichts.
        if (current == Routes.LAUNCH) return@LaunchedEffect
        val currentCid = if (current.startsWith("chat/"))
            nav.currentBackStackEntry?.arguments?.getString("cid") else null
        if (currentCid != cid) {
            nav.navigate(Routes.chat(cid)) {
                popUpTo(Routes.CHAT) { inclusive = true }
                launchSingleTop = true
            }
        }
    }

    NavHost(navController = nav, startDestination = Routes.LAUNCH) {

        composable(Routes.LAUNCH) {
            LaunchScreen(
                container = container,
                preloadedCid = initialChatCid,
                onChatReady = { cid ->
                    nav.navigate(Routes.chat(cid)) {
                        // Launch-Screen aus dem Backstack entfernen — Back im Chat
                        // soll nicht hierher zurückführen.
                        popUpTo(Routes.LAUNCH) { inclusive = true }
                        launchSingleTop = true
                    }
                },
                onNeedsSettings = {
                    nav.navigate(Routes.SETTINGS)
                },
            )
        }

        composable(Routes.CONVERSATIONS) {
            val vm: ConversationsViewModel = viewModel(
                factory = ConversationsViewModel.factory(container)
            )
            ConversationsScreen(
                vm = vm,
                onOpenChat = { cid ->
                    nav.navigate(Routes.chat(cid)) {
                        popUpTo(Routes.CHAT) { inclusive = true }
                        launchSingleTop = true
                    }
                },
                onOpenSettings = { nav.navigate(Routes.SETTINGS) },
                onBack = { nav.popBackStack() },
            )
        }

        composable(
            Routes.CHAT,
            arguments = listOf(navArgument("cid") { type = NavType.StringType })
        ) { backStack ->
            val cid = backStack.arguments?.getString("cid").orEmpty()
            val vm: ChatViewModel = viewModel(
                factory = ChatViewModel.factory(container, cid),
                key = "chat_$cid",
            )
            ChatScreen(
                vm = vm,
                onOpenSettings = { nav.navigate(Routes.SETTINGS) },
                onOpenConversations = { nav.navigate(Routes.CONVERSATIONS) },
                onOpenImages = { nav.navigate(Routes.IMAGES) },
                onNewChat = {
                    // Create a fresh chat directly. Going through LAUNCH would
                    // hit the process-death-restore path which navigates back
                    // to the last chat — wrong for an explicit "New chat" tap.
                    coroutineScope.launch {
                        runCatching { container.chatRepository.create() }
                            .onSuccess { fresh ->
                                nav.navigate(Routes.chat(fresh.id)) {
                                    popUpTo(Routes.CHAT) { inclusive = true }
                                    launchSingleTop = true
                                }
                            }
                    }
                },
                onSwitchChat = { newCid ->
                    if (newCid != cid) {
                        nav.navigate(Routes.chat(newCid)) {
                            popUpTo(Routes.CHAT) { inclusive = true }
                            launchSingleTop = true
                        }
                    }
                },
                onStartGemChat = { gemId ->
                    // Frischen Chat „mit einem Gem" anlegen und hinein-navigieren.
                    coroutineScope.launch {
                        runCatching { container.chatRepository.create(gemId = gemId) }
                            .onSuccess { fresh ->
                                nav.navigate(Routes.chat(fresh.id)) {
                                    popUpTo(Routes.CHAT) { inclusive = true }
                                    launchSingleTop = true
                                }
                            }
                    }
                },
            )
        }

        composable(Routes.SETTINGS) {
            val vm: SettingsViewModel = viewModel(
                factory = SettingsViewModel.factory(container)
            )
            SettingsScreen(
                vm = vm,
                onBack = { nav.popBackStack() },
                onEditGem = { gemId -> nav.navigate(Routes.gemEditor(gemId)) },
                onDuplicateGem = { sourceId -> nav.navigate(Routes.gemDuplicate(sourceId)) },
            )
        }

        composable(
            Routes.GEM_EDITOR,
            arguments = listOf(
                navArgument("gemId") {
                    type = NavType.StringType
                    nullable = true
                    defaultValue = null
                },
                navArgument("dup") {
                    type = NavType.StringType
                    nullable = true
                    defaultValue = null
                },
            ),
        ) { backStack ->
            val gemId = backStack.arguments?.getString("gemId")
            val dup = backStack.arguments?.getString("dup")
            val vm: GemsViewModel = viewModel(
                factory = GemsViewModel.factory(container),
                key = "gem_editor_${dup?.let { "dup_$it" } ?: gemId ?: "new"}",
            )
            GemEditorScreen(
                vm = vm,
                gemId = gemId,
                dupFrom = dup,
                onBack = { nav.popBackStack() },
            )
        }

        composable(Routes.IMAGES) {
            val vm: de.smartzone.pocketclaude.ui.images.ImageGenViewModel = viewModel(
                factory = de.smartzone.pocketclaude.ui.images.ImageGenViewModel.factory(container)
            )
            de.smartzone.pocketclaude.ui.images.ImagesScreen(
                vm = vm,
                onBack = { nav.popBackStack() },
                onOpenSettings = { nav.navigate(Routes.SETTINGS) },
            )
        }
    }
}

/**
 * Wird beim App-Start gezeigt. Prüft Settings, erzeugt einen frischen Chat
 * und gibt die neue cid zurück. Während die Konversation angelegt wird, sieht
 * der User einen Spinner.
 */
@Composable
private fun LaunchScreen(
    container: AppContainer,
    preloadedCid: String?,
    onChatReady: (String) -> Unit,
    onNeedsSettings: () -> Unit,
) {
    var errorMessage by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(Unit) {
        // Wenn die Activity mit einer cid aus einer Notification kam,
        // springen wir direkt dorthin — keinen frischen Chat anlegen.
        if (preloadedCid != null) {
            onChatReady(preloadedCid)
            return@LaunchedEffect
        }
        // Sonst: auf den ersten echten Settings-Emit aus DataStore warten —
        // sonst würden wir auf dem Default isConfigured=false sofort
        // zu Settings springen, obwohl der User längst alles eingetragen hat.
        val s = container.settingsRepository.current()
        if (!s.isConfigured) {
            // Ohne Server kein Chat: den Sprach-Wunsch verwerfen, sonst
            // oeffnete ihn erst ein spaeterer, normaler Start.
            container.voiceChat.discard()
            onNeedsSettings()
            return@LaunchedEffect
        }
        // Process-Death-Restore: wenn die App schon mal mit einem Chat offen
        // war (cid in DataStore), wieder dort öffnen statt frischen Chat
        // anzulegen. Falls der Chat zwischenzeitlich gelöscht wurde, fängt
        // ChatScreen das ab und der User landet einfach auf Error/leer —
        // besser als überrascht in einem neuen Chat zu stehen.
        // Neuer Sprach-Chat beim KALTSTART: frischer Chat, dort startet
        // ChatScreen das Diktat.
        val voiceCid = try {
            container.voiceChat.createIfRequested { container.chatRepository.create().id }
        } catch (e: kotlinx.coroutines.CancellationException) {
            throw e
        } catch (e: Exception) {
            errorMessage = e.message ?: e::class.java.simpleName
            return@LaunchedEffect
        }
        if (voiceCid != null) {
            onChatReady(voiceCid)
            return@LaunchedEffect
        }
        // Share-Intent beim KALTSTART: frischen Chat für den geteilten Inhalt
        // (nicht den letzten Chat wiederöffnen).
        if (container.pendingShare != null) {
            runCatching { container.chatRepository.create() }
                .onSuccess { onChatReady(it.id) }
                .onFailure { errorMessage = it.message ?: it::class.java.simpleName }
            return@LaunchedEffect
        }
        val lastCid = container.settingsRepository.getLastChatCid()
        if (!lastCid.isNullOrBlank()) {
            onChatReady(lastCid)
            return@LaunchedEffect
        }
        runCatching { container.chatRepository.create() }
            .onSuccess { onChatReady(it.id) }
            .onFailure { errorMessage = it.message ?: it::class.java.simpleName }
    }

    PocketBackdrop(Modifier.fillMaxSize()) {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        if (errorMessage != null) {
            // Verbindungs-/Auth-Fehler beim Start: NICHT in der Sackgasse hängen
            // bleiben. Ein Weg in die Einstellungen erlaubt Re-Login (z.B. wenn
            // der Session-Token serverseitig nicht mehr gültig ist → HTTP 401).
            Column(
                horizontalAlignment = Alignment.CenterHorizontally,
                modifier = Modifier.padding(24.dp),
            ) {
                Text(
                    stringResource(
                        de.smartzone.pocketclaude.R.string.connection_failed_prefix,
                        errorMessage ?: "",
                    ),
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.error,
                )
                Spacer(Modifier.height(16.dp))
                OutlinedButton(onClick = onNeedsSettings) {
                    Text(stringResource(de.smartzone.pocketclaude.R.string.title_settings))
                }
            }
        } else {
            Column(
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.Center,
            ) {
                // Gleiche Hero-Groesse und Titelstufe wie die leeren Zustaende.
                PocketBrandMark(size = 96.dp)
                Spacer(Modifier.height(24.dp))
                Text(
                    stringResource(de.smartzone.pocketclaude.R.string.app_name),
                    style = MaterialTheme.typography.headlineSmall,
                )
                Spacer(Modifier.height(16.dp))
                CircularProgressIndicator(
                    modifier = Modifier.size(PocketIconSize.Regular),
                    strokeWidth = 2.dp,
                )
            }
        }
    }
    }
}
