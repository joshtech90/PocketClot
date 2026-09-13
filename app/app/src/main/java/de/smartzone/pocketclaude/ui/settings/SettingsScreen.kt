package de.smartzone.pocketclaude.ui.settings

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
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.animation.animateContentSize
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.InsertDriveFile
import androidx.compose.material.icons.automirrored.filled.VolumeUp
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.ArrowDropDown
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.DriveFileRenameOutline
import androidx.compose.material.icons.filled.Error
import androidx.compose.material.icons.filled.ExpandLess
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.RadioButtonUnchecked
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material.icons.filled.Upload
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.ui.text.font.FontWeight as FW
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.AssistChip
import androidx.compose.material3.AssistChipDefaults
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.ExposedDropdownMenuDefaults
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.foundation.shape.CircleShape
import de.smartzone.pocketclaude.ui.theme.PocketPalette
import de.smartzone.pocketclaude.ui.theme.specFor
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import android.app.Activity
import de.smartzone.pocketclaude.data.BillingStatusDto
import de.smartzone.pocketclaude.data.ClaudeAuthUpdateRequest
import de.smartzone.pocketclaude.R
import de.smartzone.pocketclaude.data.ChatModelFamilies
import de.smartzone.pocketclaude.data.EFFORT_LEVELS
import de.smartzone.pocketclaude.data.EFFORT_LEVELS_ALL
import de.smartzone.pocketclaude.data.ChatModelOption
import de.smartzone.pocketclaude.data.ImageConfigDto
import de.smartzone.pocketclaude.data.ImageProviderDto
import de.smartzone.pocketclaude.data.GemDto
import de.smartzone.pocketclaude.data.LocalePrefs
import de.smartzone.pocketclaude.data.SystemPromptMode
import de.smartzone.pocketclaude.data.ThemeMode
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import de.smartzone.pocketclaude.ui.components.InfoBulletParagraph
import de.smartzone.pocketclaude.ui.components.InfoButton
import de.smartzone.pocketclaude.ui.components.InfoParagraph
import de.smartzone.pocketclaude.ui.components.PocketBackdrop
import de.smartzone.pocketclaude.ui.components.PocketIconButton
import de.smartzone.pocketclaude.ui.components.PocketScreenTitle
import de.smartzone.pocketclaude.ui.theme.PocketTheme

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
fun SettingsScreen(
    vm: SettingsViewModel,
    onBack: () -> Unit,
    onEditGem: (String?) -> Unit = {},
    onDuplicateGem: (String) -> Unit = {},
) {
    val settings by vm.settings.collectAsState()
    val testResult by vm.testResult.collectAsState()
    // Gem-Liste bei jeder Rückkehr (z.B. aus dem Gem-Editor) neu laden.
    val lifecycleOwner = LocalLifecycleOwner.current
    DisposableEffect(lifecycleOwner) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_RESUME) vm.refreshGems()
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose { lifecycleOwner.lifecycle.removeObserver(observer) }
    }
    // ttsStatus auf Top-Level der Settings — wird vom Quick-Setup-Banner gelesen
    // (Edge-Provider ist „ready" auch ohne Setup), und von TtsSection selbst
    // weiter intern wieder collected. Doppelte Subscriptions sind in Compose
    // billig (StateFlow shared).
    val ttsStatus by vm.ttsStatus.collectAsState()
    // (showToken früher hier — Token-Feld ist entfallen; Username/PW ersetzen es)

    PocketBackdrop(Modifier.fillMaxSize()) {
    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    PocketScreenTitle(
                        eyebrow = stringResource(de.smartzone.pocketclaude.R.string.app_name),
                        title = stringResource(de.smartzone.pocketclaude.R.string.title_settings),
                    )
                },
                navigationIcon = {
                    PocketIconButton(
                        icon = Icons.AutoMirrored.Filled.ArrowBack,
                        contentDescription = stringResource(de.smartzone.pocketclaude.R.string.action_back),
                        onClick = onBack,
                        modifier = Modifier.padding(start = 8.dp),
                    )
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = Color.Transparent,
                    scrolledContainerColor = MaterialTheme.colorScheme.surface.copy(alpha = 0.94f),
                ),
            )
        },
        containerColor = Color.Transparent,
        contentColor = MaterialTheme.colorScheme.onBackground,
    ) { pad ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(pad)
                .consumeWindowInsets(pad)
                .imePadding()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 16.dp, vertical = 10.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            // ─── Quick-Setup-Banner — nur sichtbar bis alles eingerichtet ───
            val hasProfile = settings.activeProfile != null
            val isLoggedIn = settings.serverToken.isNotBlank()
            val ttsReady = (ttsStatus?.configured == true) ||
                (ttsStatus?.provider == "edge_tts")  // Edge ist immer ready
            if (!hasProfile || !isLoggedIn) {
                QuickSetupBanner(
                    hasProfile = hasProfile,
                    isLoggedIn = isLoggedIn,
                    ttsReady = ttsReady,
                )
            }

            // Forced-PW-Change-Dialog beobachtet den Login-State global.
            ForcedPasswordChangeWatcher(vm)

            // ═════════════════════════════════════════════════════════════
            //  1. PROFIL & SERVER — immer sichtbar, oberste Priorität.
            // ═════════════════════════════════════════════════════════════
            ProfileAndServerCard(
                vm = vm,
                settings = settings,
                testResult = testResult,
            )

            // ═════════════════════════════════════════════════════════════
            //  2. CLAUDE — Denktiefe + System-Prompt + Skills,
            //     alles was Claudes Verhalten direkt steuert.
            // ═════════════════════════════════════════════════════════════
            ClaudeBehaviorCard(vm = vm, settings = settings)

            // ═════════════════════════════════════════════════════════════
            //  GEMS — Custom Agents (wie ChatGPT-GPTs / Gemini-Gems)
            // ═════════════════════════════════════════════════════════════
            val gems by vm.gems.collectAsState()
            ExpandableSection(
                title = stringResource(de.smartzone.pocketclaude.R.string.section_gems),
                subtitle = stringResource(de.smartzone.pocketclaude.R.string.section_gems_subtitle),
                initiallyExpanded = false,
            ) {
                GemsSection(
                    gems = gems,
                    onEdit = onEditGem,
                    onDuplicate = onDuplicateGem,
                    onDelete = vm::deleteGem,
                )
            }

            // ═════════════════════════════════════════════════════════════
            //  3-7. Sekundäre Sektionen — alle als ExpandableSection für
            //  konsistentes Layout. Default collapsed, der User klappt
            //  nur das auf, was er gerade braucht.
            // ═════════════════════════════════════════════════════════════

            // Claude-Backend-Provider + Token-Usage — insert BEFORE TTS
            ExpandableSection(
                title = stringResource(de.smartzone.pocketclaude.R.string.section_claude_connection),
                subtitle = when (vm.claudeAuth.collectAsState().value?.mode) {
                    "api_key" -> stringResource(de.smartzone.pocketclaude.R.string.claude_mode_api_key)
                    "bedrock" -> stringResource(de.smartzone.pocketclaude.R.string.claude_mode_bedrock)
                    else      -> stringResource(de.smartzone.pocketclaude.R.string.claude_mode_pro_max)
                },
                initiallyExpanded = false,
            ) {
                ClaudeAuthSection(vm = vm)
            }

            ExpandableSection(
                title = stringResource(de.smartzone.pocketclaude.R.string.section_token_usage),
                subtitle = stringResource(de.smartzone.pocketclaude.R.string.usage_this_month),
                initiallyExpanded = false,
            ) {
                UsageStatsSection(vm = vm)
            }

            ExpandableSection(
                title = stringResource(de.smartzone.pocketclaude.R.string.settings_section_chat_lock),
                subtitle = stringResource(de.smartzone.pocketclaude.R.string.settings_subtitle_chat_lock),
                initiallyExpanded = false,
                infoTitle = stringResource(de.smartzone.pocketclaude.R.string.chat_lock_info_title),
                infoBody = {
                    InfoParagraph(
                        stringResource(de.smartzone.pocketclaude.R.string.chat_lock_info_body)
                    )
                },
            ) {
                ChatLockSection(vm = vm, settings = settings)
            }

            ExpandableSection(
                title = stringResource(de.smartzone.pocketclaude.R.string.settings_section_vorlesen),
                subtitle = stringResource(de.smartzone.pocketclaude.R.string.settings_subtitle_vorlesen),
                initiallyExpanded = false,
                infoTitle = stringResource(de.smartzone.pocketclaude.R.string.settings_info_tts_title),
                infoBody = {
                    InfoParagraph(
                        stringResource(de.smartzone.pocketclaude.R.string.settings_info_tts_intro)
                    )
                    InfoBulletParagraph(
                        stringResource(de.smartzone.pocketclaude.R.string.settings_info_tts_edge_label),
                        stringResource(de.smartzone.pocketclaude.R.string.settings_info_tts_edge_body)
                    )
                    InfoBulletParagraph(
                        stringResource(de.smartzone.pocketclaude.R.string.settings_info_tts_gemini_label),
                        stringResource(de.smartzone.pocketclaude.R.string.settings_info_tts_gemini_body)
                    )
                    InfoBulletParagraph(
                        stringResource(de.smartzone.pocketclaude.R.string.settings_info_tts_cloud_label),
                        stringResource(de.smartzone.pocketclaude.R.string.settings_info_tts_cloud_body)
                    )
                },
            ) {
                TtsSection(vm = vm, settings = settings)
            }

            ExpandableSection(
                title = stringResource(de.smartzone.pocketclaude.R.string.settings_section_images_title),
                subtitle = stringResource(de.smartzone.pocketclaude.R.string.settings_subtitle_images),
                initiallyExpanded = false,
                infoTitle = stringResource(de.smartzone.pocketclaude.R.string.settings_info_images_title),
                infoBody = {
                    InfoParagraph(
                        stringResource(de.smartzone.pocketclaude.R.string.settings_info_images_intro)
                    )
                    InfoBulletParagraph(stringResource(de.smartzone.pocketclaude.R.string.settings_info_images_step1), stringResource(de.smartzone.pocketclaude.R.string.settings_info_images_step1_body))
                    InfoBulletParagraph(
                        stringResource(de.smartzone.pocketclaude.R.string.settings_info_images_step2),
                        stringResource(de.smartzone.pocketclaude.R.string.settings_info_images_step2_body)
                    )
                    InfoBulletParagraph(stringResource(de.smartzone.pocketclaude.R.string.settings_info_images_step3), stringResource(de.smartzone.pocketclaude.R.string.settings_info_images_step3_body))
                    InfoBulletParagraph(
                        stringResource(de.smartzone.pocketclaude.R.string.settings_info_images_free_label),
                        stringResource(de.smartzone.pocketclaude.R.string.settings_info_images_free_body)
                    )
                    InfoBulletParagraph(
                        stringResource(de.smartzone.pocketclaude.R.string.settings_info_images_paid_label),
                        stringResource(de.smartzone.pocketclaude.R.string.settings_info_images_paid_body)
                    )
                },
            ) {
                // Der frueher hier stehende Hinweis auf den gemeinsamen
                // Google-Schluessel ist entfallen: fuer Bilder braucht es keinen
                // mehr. Fuer die Gemini-Sprachausgabe steht er im Abschnitt
                // Vorlesen.
                ImageGenSection(vm = vm)
            }

            ExpandableSection(
                title = stringResource(de.smartzone.pocketclaude.R.string.settings_section_voice_title),
                subtitle = stringResource(de.smartzone.pocketclaude.R.string.settings_subtitle_voice),
                initiallyExpanded = false,
                infoTitle = stringResource(de.smartzone.pocketclaude.R.string.settings_info_voice_title),
                infoBody = {
                    InfoParagraph(
                        stringResource(de.smartzone.pocketclaude.R.string.settings_info_voice_intro)
                    )
                    InfoBulletParagraph(
                        stringResource(de.smartzone.pocketclaude.R.string.settings_info_voice_step1),
                        stringResource(de.smartzone.pocketclaude.R.string.settings_info_voice_step1_body),
                    )
                    InfoBulletParagraph(
                        stringResource(de.smartzone.pocketclaude.R.string.settings_info_voice_step2),
                        stringResource(de.smartzone.pocketclaude.R.string.settings_info_voice_step2_body),
                    )
                    InfoBulletParagraph(
                        stringResource(de.smartzone.pocketclaude.R.string.settings_info_voice_automode_label),
                        stringResource(de.smartzone.pocketclaude.R.string.settings_info_voice_automode_body),
                    )
                },
            ) {
                VoiceSection(vm = vm)
            }

            ExpandableSection(
                title = stringResource(de.smartzone.pocketclaude.R.string.section_appearance),
                subtitle = when (settings.themeMode) {
                    ThemeMode.SYSTEM -> stringResource(de.smartzone.pocketclaude.R.string.settings_theme_system)
                    ThemeMode.LIGHT -> stringResource(de.smartzone.pocketclaude.R.string.settings_theme_light)
                    ThemeMode.DARK -> stringResource(de.smartzone.pocketclaude.R.string.settings_theme_dark)
                },
                initiallyExpanded = false,
            ) {
                ThemeCard(settings = settings, vm = vm)
                Spacer(Modifier.height(12.dp))
                LanguageCard()
            }

            ExpandableSection(
                title = stringResource(de.smartzone.pocketclaude.R.string.settings_section_data),
                subtitle = stringResource(de.smartzone.pocketclaude.R.string.settings_subtitle_data),
                initiallyExpanded = false,
                infoTitle = stringResource(de.smartzone.pocketclaude.R.string.settings_data_info_title),
                infoBody = {
                    InfoBulletParagraph(
                        stringResource(de.smartzone.pocketclaude.R.string.settings_data_chat_backup_label),
                        stringResource(de.smartzone.pocketclaude.R.string.settings_data_chat_backup_body)
                    )
                    InfoBulletParagraph(
                        stringResource(de.smartzone.pocketclaude.R.string.settings_data_settings_backup_label),
                        stringResource(de.smartzone.pocketclaude.R.string.settings_data_settings_backup_body)
                    )
                    InfoParagraph(
                        stringResource(de.smartzone.pocketclaude.R.string.settings_data_no_profiles_body)
                    )
                },
            ) {
                Column(verticalArrangement = Arrangement.spacedBy(20.dp)) {
                    // Sub-Sektion: Chat-Backup
                    SubsectionLabel(stringResource(de.smartzone.pocketclaude.R.string.settings_data_subsection_chats))
                    BackupSection(vm = vm)
                    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                    // Sub-Sektion: Settings-Backup
                    SubsectionLabel(stringResource(de.smartzone.pocketclaude.R.string.settings_data_subsection_settings))
                    SettingsTransferSection(vm = vm)
                }
            }

            ExpandableSection(
                title = stringResource(de.smartzone.pocketclaude.R.string.settings_section_about),
                subtitle = stringResource(de.smartzone.pocketclaude.R.string.settings_subtitle_about),
                initiallyExpanded = false,
            ) {
                AboutCard()
            }

            Spacer(Modifier.height(24.dp))
        }
    }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
//  Strukturelle Composables für die neue Settings-Hierarchie.
//  Jede Top-Level-Sektion ist ein einzelner Composable mit klarem Scope.
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Profil & Server — kompakte Card, immer sichtbar.
 * URL-Feld + Username-Status + Action-Buttons + Profil-Liste falls Multi-User.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun ProfileAndServerCard(
    vm: SettingsViewModel,
    settings: de.smartzone.pocketclaude.data.AppSettings,
    testResult: ConnectionTestResult,
) {
    var changePwOpen by remember { mutableStateOf(false) }
    var reLoginOpen by remember { mutableStateOf(false) }
    val activeUsername = settings.activeProfile?.username.orEmpty()
    val sessionOk = settings.serverToken.isNotBlank()

    SectionHeader(
        text = stringResource(de.smartzone.pocketclaude.R.string.settings_section_profile_card_title),
        infoTitle = stringResource(de.smartzone.pocketclaude.R.string.settings_info_profile_server_title),
    ) {
        InfoParagraph(
            stringResource(de.smartzone.pocketclaude.R.string.settings_info_profile_server_para1)
        )
        InfoBulletParagraph(
            stringResource(de.smartzone.pocketclaude.R.string.settings_info_profile_server_url_label),
            stringResource(de.smartzone.pocketclaude.R.string.settings_info_profile_server_url_body)
        )
        InfoBulletParagraph(
            stringResource(de.smartzone.pocketclaude.R.string.settings_info_profile_server_login_label),
            stringResource(de.smartzone.pocketclaude.R.string.settings_info_profile_server_login_body)
        )
    }

    // First-run UX: no profiles yet → show the sign-in form directly,
    // skip the "Add profile" detour. Users only see the multi-profile UI
    // after they're successfully logged in once.
    if (settings.profiles.isEmpty()) {
        FirstRunSignInCard(vm = vm)
        return
    }

    // Multi-profile list — only shown once the user has at least one
    // profile (so the first-run screen stays simple).
    ProfilesCard(vm = vm, settings = settings)

    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surface.copy(alpha = 0.9f),
            contentColor = MaterialTheme.colorScheme.onSurface,
        ),
        shape = RoundedCornerShape(28.dp),
        border = androidx.compose.foundation.BorderStroke(1.dp, PocketTheme.colors.outlineSoft),
    ) {
        Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
            OutlinedTextField(
                value = settings.serverUrl,
                onValueChange = vm::setServerUrl,
                label = { Text(stringResource(de.smartzone.pocketclaude.R.string.settings_server_url_label)) },
                placeholder = { Text(stringResource(de.smartzone.pocketclaude.R.string.settings_server_url_placeholder)) },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(14.dp),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
            )
            // Username + Session-Status als Info-Block (read-only, Editier-Pfad
            // läuft über „Neu anmelden").
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(12.dp))
                    .background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.4f))
                    .padding(horizontal = 14.dp, vertical = 10.dp),
                verticalArrangement = Arrangement.spacedBy(2.dp),
            ) {
                Text(
                    stringResource(de.smartzone.pocketclaude.R.string.settings_username),
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Text(
                    activeUsername.ifBlank { stringResource(de.smartzone.pocketclaude.R.string.settings_not_logged_in) },
                    style = MaterialTheme.typography.bodyLarge,
                    fontWeight = if (activeUsername.isNotBlank()) FW.Medium else FW.Normal,
                )
                Text(
                    if (sessionOk) stringResource(de.smartzone.pocketclaude.R.string.settings_session_active)
                    else stringResource(de.smartzone.pocketclaude.R.string.settings_not_logged_in_hint),
                    style = MaterialTheme.typography.bodySmall,
                    color = if (sessionOk) MaterialTheme.colorScheme.primary
                            else MaterialTheme.colorScheme.error,
                )
            }

            FlowRow(
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
                modifier = Modifier.fillMaxWidth(),
            ) {
                FilledTonalButton(
                    onClick = vm::testConnection,
                    enabled = settings.isConfigured && testResult !is ConnectionTestResult.Testing,
                    shape = RoundedCornerShape(12.dp),
                ) { Text(stringResource(de.smartzone.pocketclaude.R.string.settings_test_connection)) }
                FilledTonalButton(
                    onClick = { reLoginOpen = true },
                    enabled = activeUsername.isNotBlank() && settings.serverUrl.isNotBlank(),
                    shape = RoundedCornerShape(12.dp),
                ) { Text(if (sessionOk) stringResource(de.smartzone.pocketclaude.R.string.settings_relogin) else stringResource(de.smartzone.pocketclaude.R.string.settings_login)) }
                FilledTonalButton(
                    onClick = { changePwOpen = true },
                    enabled = sessionOk,
                    shape = RoundedCornerShape(12.dp),
                ) { Text(stringResource(de.smartzone.pocketclaude.R.string.settings_change_password)) }
                if (sessionOk) {
                    TextButton(onClick = { vm.logoutActiveProfile() }) {
                        Text(stringResource(de.smartzone.pocketclaude.R.string.settings_logout), color = MaterialTheme.colorScheme.error)
                    }
                }
            }
            TestResultIndicator(testResult)
        }
    }

    if (reLoginOpen) {
        ReLoginDialog(vm = vm, onDismiss = { reLoginOpen = false })
    }
    if (changePwOpen) {
        ChangePasswordDialog(vm = vm, forced = false, onDone = { changePwOpen = false })
    }
}

/**
 * Claude-Verhalten — Denktiefe + System-Prompt + Skills in einer
 * gemeinsamen Card. Das ist konzeptionell zusammenhängend (was/wie steuert
 * Claudes Antwort) und vorher unnötig in zwei separate Sektionen aufgeteilt.
 */
@Composable
private fun ClaudeBehaviorCard(
    vm: SettingsViewModel,
    settings: de.smartzone.pocketclaude.data.AppSettings,
) {
    SectionHeader(
        text = stringResource(de.smartzone.pocketclaude.R.string.settings_section_claude_card_title),
        infoTitle = stringResource(de.smartzone.pocketclaude.R.string.settings_info_claude_title),
    ) {
        InfoBulletParagraph(
            stringResource(de.smartzone.pocketclaude.R.string.settings_info_claude_effort_label),
            stringResource(de.smartzone.pocketclaude.R.string.settings_info_claude_effort_body)
        )
        InfoBulletParagraph(
            stringResource(de.smartzone.pocketclaude.R.string.settings_info_claude_prompt_label),
            stringResource(de.smartzone.pocketclaude.R.string.settings_info_claude_prompt_body)
        )
        InfoBulletParagraph(
            stringResource(de.smartzone.pocketclaude.R.string.settings_info_claude_skills_label),
            stringResource(de.smartzone.pocketclaude.R.string.settings_info_claude_skills_body)
        )
    }
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        shape = RoundedCornerShape(20.dp),
    ) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
            // Globales Standard-Modell für neue Chats, über alle Familien.
            val chatModels by vm.chatModels.collectAsState()
            val chatModelsLoading by vm.chatModelsLoading.collectAsState()
            DefaultModelPicker(
                models = chatModels,
                selectedKey = settings.chatModelKey,
                loading = chatModelsLoading,
                onSelect = vm::setDefaultChatModel,
                onRefresh = vm::refreshChatModels,
            )

            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)

            // Ein Block je Anbieter: welches Modell, und direkt darunter dessen
            // Denktiefe. Vorher standen Modell und Denktiefe in zwei getrennten
            // Listen, und die Stufen waren fest verdrahtet statt vom Modell
            // abgeleitet. Dann liess sich eine Stufe waehlen, die der Server
            // still verworfen hat.
            SubsectionLabel(stringResource(de.smartzone.pocketclaude.R.string.settings_provider_defaults))
            listOf(
                ChatModelFamilies.CLAUDE to de.smartzone.pocketclaude.R.string.settings_effort_claude,
                ChatModelFamilies.GEMINI to de.smartzone.pocketclaude.R.string.settings_effort_gemini,
                ChatModelFamilies.GPT to de.smartzone.pocketclaude.R.string.settings_effort_gpt,
            ).forEach { (family, labelRes) ->
                val familyModels = chatModels.filter { it.family == family }
                val selectedKey = settings.defaultModelFor(family)
                val selectedModel = familyModels.firstOrNull { it.key == selectedKey }
                // Claude ist immer da, auch ohne Gateway, und kennt zusaetzlich
                // die Stufe „aus". Bei den Zusatz-Modellen bestimmt das konkrete
                // Modell, welche Stufen es ueberhaupt gibt.
                // Dieselbe Quelle wie im Chat-Sheet und im Sendepfad. Ohne
                // gewaehltes Zusatz-Modell gibt es nichts einzustellen, dann
                // bleibt die Liste leer und der Block sagt das auch.
                val availableEfforts =
                    if (family != ChatModelFamilies.CLAUDE && selectedModel == null) emptyList()
                    else settings.availableEffortsFor(family, selectedModel)

                ProviderDefaultsBlock(
                    familyLabel = stringResource(labelRes),
                    models = familyModels,
                    selectedKey = selectedKey,
                    onSelectModel = { key -> vm.setDefaultModelForFamily(family, key) },
                    availableEfforts = availableEfforts,
                    selectedEffort = settings.effortForModelKey(selectedKey, selectedModel),
                    onSelectEffort = { value -> vm.setEffortForFamily(family, value) },
                )
            }
            Text(
                stringResource(de.smartzone.pocketclaude.R.string.settings_provider_defaults_hint),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )

            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)

            // System-Prompt
            SubsectionLabel(stringResource(de.smartzone.pocketclaude.R.string.settings_subsection_system_prompt))
            SystemPromptModeChips(
                selected = settings.systemPromptMode,
                onSelect = vm::setSystemPromptMode,
            )
            // Ohne diesen Satz ist nicht erkennbar, dass der Modus auch bei
            // Gemini und GPT wirkt. Er tut es, nur eben in angepasster Fassung.
            Text(
                stringResource(de.smartzone.pocketclaude.R.string.settings_prompt_all_models_hint),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            if (settings.systemPromptMode == SystemPromptMode.CUSTOM) {
                OutlinedTextField(
                    value = settings.customSystemPrompt,
                    onValueChange = vm::setCustomSystemPrompt,
                    label = { Text(stringResource(de.smartzone.pocketclaude.R.string.settings_custom_system_prompt_label)) },
                    placeholder = { Text(stringResource(de.smartzone.pocketclaude.R.string.settings_custom_system_prompt_placeholder)) },
                    modifier = Modifier.fillMaxWidth(),
                    minLines = 4,
                    maxLines = 14,
                    shape = RoundedCornerShape(14.dp),
                )
                Text(
                    stringResource(de.smartzone.pocketclaude.R.string.settings_custom_system_prompt_hint),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }

            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)

            // Skills (Default für alle neuen Chats)
            SubsectionLabel(stringResource(de.smartzone.pocketclaude.R.string.settings_subsection_skills_defaults))
            SkillsDefaultsSection(vm = vm)
        }
    }
}

/** Theme-Auswahl als kompakte Card (3 Filter-Chips). */
@Composable
private fun ThemeCard(
    settings: de.smartzone.pocketclaude.data.AppSettings,
    vm: SettingsViewModel,
) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        shape = RoundedCornerShape(20.dp),
    ) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            SubsectionLabel(stringResource(de.smartzone.pocketclaude.R.string.settings_theme_label))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                ThemeMode.entries.forEach { mode ->
                    FilterChip(
                        selected = settings.themeMode == mode,
                        onClick = { vm.setThemeMode(mode) },
                        label = {
                            Text(
                                when (mode) {
                                    ThemeMode.SYSTEM -> stringResource(de.smartzone.pocketclaude.R.string.theme_system)
                                    ThemeMode.LIGHT -> stringResource(de.smartzone.pocketclaude.R.string.settings_light)
                                    ThemeMode.DARK -> stringResource(de.smartzone.pocketclaude.R.string.settings_dark)
                                }
                            )
                        },
                        shape = RoundedCornerShape(12.dp),
                        colors = FilterChipDefaults.filterChipColors(
                            selectedContainerColor = MaterialTheme.colorScheme.primary,
                            selectedLabelColor = MaterialTheme.colorScheme.onPrimary,
                        ),
                    )
                }
            }

            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)

            // Farbschema, getrennt fuer hell und dunkel. Jede Palette hat beide
            // Varianten, aber welche hell gefaellt, muss dunkel nicht gefallen.
            // Die Proben zeigen jeweils die Variante, um die es gerade geht.
            SubsectionLabel(stringResource(de.smartzone.pocketclaude.R.string.settings_palette_label_light))
            PalettePicker(
                selectedId = settings.paletteIdLight,
                dark = false,
                fallback = PocketPalette.NORDIC_BLUE,
                onSelect = vm::setPaletteIdLight,
            )

            Spacer(Modifier.height(4.dp))

            SubsectionLabel(stringResource(de.smartzone.pocketclaude.R.string.settings_palette_label_dark))
            PalettePicker(
                selectedId = settings.paletteIdDark,
                dark = true,
                fallback = PocketPalette.MIDNIGHT_ATELIER,
                onSelect = vm::setPaletteIdDark,
            )
            Text(
                stringResource(de.smartzone.pocketclaude.R.string.settings_palette_hint),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )

            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)

            // Lange Nachrichten einklappen (ChatGPT-Style)
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        stringResource(de.smartzone.pocketclaude.R.string.settings_collapse_long_user_messages),
                        style = MaterialTheme.typography.titleSmall,
                    )
                    Text(
                        stringResource(de.smartzone.pocketclaude.R.string.settings_collapse_long_user_messages_desc),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                Switch(
                    checked = settings.collapseLongUserMessages,
                    onCheckedChange = { vm.setCollapseLongUserMessages(it) },
                )
            }
        }
    }
}

/** Language picker: dropdown with system-default + all bundled locales.
 *  Picking a value writes to LocalePrefs and recreates the Activity so the
 *  new strings.xml takes effect immediately. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun LanguageCard() {
    val ctx = LocalContext.current
    var expanded by remember { mutableStateOf(false) }
    var current by remember { mutableStateOf(LocalePrefs.get(ctx)) }

    val languageEntries = listOf(
        "" to stringResource(de.smartzone.pocketclaude.R.string.language_system_default),
        "en" to stringResource(de.smartzone.pocketclaude.R.string.language_english),
        "de" to stringResource(de.smartzone.pocketclaude.R.string.language_german),
        "es" to stringResource(de.smartzone.pocketclaude.R.string.language_spanish),
        "fr" to stringResource(de.smartzone.pocketclaude.R.string.language_french),
        "pt-BR" to stringResource(de.smartzone.pocketclaude.R.string.language_portuguese_br),
        "zh" to stringResource(de.smartzone.pocketclaude.R.string.language_chinese),
        "ja" to stringResource(de.smartzone.pocketclaude.R.string.language_japanese),
    )
    val currentLabel = languageEntries.firstOrNull { it.first == current }?.second
        ?: languageEntries.first().second

    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        shape = RoundedCornerShape(20.dp),
    ) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            SubsectionLabel(stringResource(de.smartzone.pocketclaude.R.string.language_label))
            ExposedDropdownMenuBox(
                expanded = expanded,
                onExpandedChange = { expanded = it },
            ) {
                OutlinedTextField(
                    value = currentLabel,
                    onValueChange = {},
                    readOnly = true,
                    modifier = Modifier
                        .fillMaxWidth()
                        .menuAnchor(),
                    trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded = expanded) },
                    shape = RoundedCornerShape(14.dp),
                )
                DropdownMenu(
                    expanded = expanded,
                    onDismissRequest = { expanded = false },
                ) {
                    languageEntries.forEach { (tag, label) ->
                        DropdownMenuItem(
                            text = { Text(label) },
                            onClick = {
                                expanded = false
                                if (tag != current) {
                                    LocalePrefs.set(ctx, tag)
                                    current = tag
                                    (ctx as? Activity)?.recreate()
                                }
                            },
                        )
                    }
                }
            }
        }
    }
}

/**
 * Provider picker for the Claude backend (Pro/Max OAuth | Anthropic API |
 * AWS Bedrock). Per-user setting. Pro/Max is the default and needs no
 * credentials — the others reveal their respective form fields.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun GemsSection(
    gems: List<GemDto>,
    onEdit: (String?) -> Unit,
    onDuplicate: (String) -> Unit,
    onDelete: (String) -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        gems.forEach { gem ->
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(14.dp))
                    .clickable(enabled = !gem.isBuiltin) { onEdit(gem.id) }
                    .padding(vertical = 8.dp, horizontal = 4.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    gem.emoji.ifBlank { "🤖" },
                    style = MaterialTheme.typography.titleLarge,
                    modifier = Modifier.padding(end = 10.dp),
                )
                Column(Modifier.weight(1f)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(
                            gem.name,
                            style = MaterialTheme.typography.bodyLarge,
                            fontWeight = FW.SemiBold,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                        )
                        if (gem.isBuiltin) {
                            Spacer(Modifier.width(6.dp))
                            Text(
                                stringResource(de.smartzone.pocketclaude.R.string.gem_builtin_badge),
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.primary,
                            )
                        }
                    }
                    if (gem.description.isNotBlank()) {
                        Text(
                            gem.description,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            maxLines = 2,
                            overflow = TextOverflow.Ellipsis,
                        )
                    }
                }
                IconButton(onClick = { onDuplicate(gem.id) }) {
                    Icon(
                        Icons.Filled.ContentCopy,
                        contentDescription = stringResource(de.smartzone.pocketclaude.R.string.gem_duplicate),
                    )
                }
                if (!gem.isBuiltin) {
                    IconButton(onClick = { onDelete(gem.id) }) {
                        Icon(
                            Icons.Filled.Delete,
                            contentDescription = stringResource(de.smartzone.pocketclaude.R.string.chat_remove),
                        )
                    }
                }
            }
            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
        }
        FilledTonalButton(onClick = { onEdit(null) }, modifier = Modifier.fillMaxWidth()) {
            Icon(Icons.Filled.Add, contentDescription = null, modifier = Modifier.size(18.dp))
            Spacer(Modifier.width(6.dp))
            Text(stringResource(de.smartzone.pocketclaude.R.string.gem_new))
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ClaudeAuthSection(vm: SettingsViewModel) {
    val auth by vm.claudeAuth.collectAsState()
    val busy by vm.claudeAuthBusy.collectAsState()
    val current = auth?.mode ?: "pro_max"

    val modes = listOf(
        "pro_max" to stringResource(de.smartzone.pocketclaude.R.string.claude_mode_pro_max),
        "api_key" to stringResource(de.smartzone.pocketclaude.R.string.claude_mode_api_key),
        "bedrock" to stringResource(de.smartzone.pocketclaude.R.string.claude_mode_bedrock),
    )

    var apiKeyInput by remember(auth?.apiKeyMasked) { mutableStateOf("") }
    var awsRegion by remember(auth?.awsRegion) { mutableStateOf(auth?.awsRegion.orEmpty()) }
    var awsAkid by remember(auth?.awsAccessKeyIdMasked) { mutableStateOf("") }
    var awsSecret by remember(auth?.awsSecretAccessKeyMasked) { mutableStateOf("") }
    var awsSession by remember(auth?.awsSessionTokenMasked) { mutableStateOf("") }
    var opusModel by remember(auth?.bedrockOpusModel) { mutableStateOf(auth?.bedrockOpusModel.orEmpty()) }
    var sonnetModel by remember(auth?.bedrockSonnetModel) { mutableStateOf(auth?.bedrockSonnetModel.orEmpty()) }
    var haikuModel by remember(auth?.bedrockHaikuModel) { mutableStateOf(auth?.bedrockHaikuModel.orEmpty()) }
    var aliasMenuOpen by remember { mutableStateOf(false) }
    val alias = auth?.bedrockModelAlias ?: "opus"

    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        shape = RoundedCornerShape(20.dp),
    ) {
        Column(
            Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            SingleChoiceSegmentedButtonRow(modifier = Modifier.fillMaxWidth()) {
                modes.forEachIndexed { idx, (key, label) ->
                    SegmentedButton(
                        selected = current == key,
                        onClick = {
                            vm.updateClaudeAuth(ClaudeAuthUpdateRequest(mode = key))
                        },
                        shape = SegmentedButtonDefaults.itemShape(index = idx, count = modes.size),
                    ) { Text(label, maxLines = 1, overflow = TextOverflow.Ellipsis) }
                }
            }

            // Hint per mode
            val hintRes = when (current) {
                "api_key" -> de.smartzone.pocketclaude.R.string.claude_mode_api_key_hint
                "bedrock" -> de.smartzone.pocketclaude.R.string.claude_mode_bedrock_hint
                else      -> de.smartzone.pocketclaude.R.string.claude_mode_pro_max_hint
            }
            Text(
                stringResource(hintRes),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )

            // Das globale Standard-Modell steht jetzt im Abschnitt
            // „Modelle und Denktiefe": dort sind auch die Zusatz-Modelle
            // wählbar, und es gibt nur EINE Stelle, die den Wert schreibt.
            if (current != "bedrock") {
                Text(
                    stringResource(de.smartzone.pocketclaude.R.string.settings_default_model_moved),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }

            when (current) {
                "api_key" -> {
                    val currentLabel = if (auth?.apiKeySet == true) auth?.apiKeyMasked
                        else stringResource(de.smartzone.pocketclaude.R.string.not_configured)
                    Text(
                        stringResource(de.smartzone.pocketclaude.R.string.current_value_label, currentLabel.orEmpty()),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    OutlinedTextField(
                        value = apiKeyInput,
                        onValueChange = { apiKeyInput = it },
                        label = { Text(stringResource(de.smartzone.pocketclaude.R.string.anthropic_api_key)) },
                        placeholder = { Text(stringResource(de.smartzone.pocketclaude.R.string.anthropic_api_key_hint)) },
                        visualTransformation = PasswordVisualTransformation(),
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Button(
                            enabled = !busy && apiKeyInput.isNotBlank(),
                            onClick = {
                                vm.updateClaudeAuth(ClaudeAuthUpdateRequest(apiKey = apiKeyInput.trim()))
                                apiKeyInput = ""
                            },
                        ) { Text(stringResource(de.smartzone.pocketclaude.R.string.action_save)) }
                        TextButton(
                            enabled = !busy && auth?.apiKeySet == true,
                            onClick = { vm.updateClaudeAuth(ClaudeAuthUpdateRequest(apiKey = "")) },
                        ) { Text(stringResource(de.smartzone.pocketclaude.R.string.clear)) }
                    }
                }

                "bedrock" -> {
                    OutlinedTextField(
                        value = awsRegion,
                        onValueChange = { awsRegion = it },
                        label = { Text(stringResource(de.smartzone.pocketclaude.R.string.aws_region)) },
                        placeholder = { Text(stringResource(de.smartzone.pocketclaude.R.string.aws_region_hint)) },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    val akidCurrent = if (auth?.awsAccessKeySet == true) auth?.awsAccessKeyIdMasked
                        else stringResource(de.smartzone.pocketclaude.R.string.not_configured)
                    Text(
                        stringResource(de.smartzone.pocketclaude.R.string.current_value_label, akidCurrent.orEmpty()),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    OutlinedTextField(
                        value = awsAkid,
                        onValueChange = { awsAkid = it },
                        label = { Text(stringResource(de.smartzone.pocketclaude.R.string.aws_access_key_id)) },
                        placeholder = { Text(stringResource(de.smartzone.pocketclaude.R.string.aws_access_key_id_hint)) },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    OutlinedTextField(
                        value = awsSecret,
                        onValueChange = { awsSecret = it },
                        label = { Text(stringResource(de.smartzone.pocketclaude.R.string.aws_secret_access_key)) },
                        visualTransformation = PasswordVisualTransformation(),
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    OutlinedTextField(
                        value = awsSession,
                        onValueChange = { awsSession = it },
                        label = { Text(stringResource(de.smartzone.pocketclaude.R.string.aws_session_token)) },
                        visualTransformation = PasswordVisualTransformation(),
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    OutlinedTextField(
                        value = opusModel,
                        onValueChange = { opusModel = it },
                        label = { Text(stringResource(de.smartzone.pocketclaude.R.string.bedrock_opus_model)) },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    OutlinedTextField(
                        value = sonnetModel,
                        onValueChange = { sonnetModel = it },
                        label = { Text(stringResource(de.smartzone.pocketclaude.R.string.bedrock_sonnet_model)) },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    OutlinedTextField(
                        value = haikuModel,
                        onValueChange = { haikuModel = it },
                        label = { Text(stringResource(de.smartzone.pocketclaude.R.string.bedrock_haiku_model)) },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )

                    // Default-model alias picker
                    SubsectionLabel(stringResource(de.smartzone.pocketclaude.R.string.bedrock_model_alias))
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        listOf(
                            "opus" to stringResource(de.smartzone.pocketclaude.R.string.bedrock_alias_opus),
                            "sonnet" to stringResource(de.smartzone.pocketclaude.R.string.bedrock_alias_sonnet),
                            "haiku" to stringResource(de.smartzone.pocketclaude.R.string.bedrock_alias_haiku),
                        ).forEach { (key, label) ->
                            FilterChip(
                                selected = alias == key,
                                onClick = {
                                    vm.updateClaudeAuth(ClaudeAuthUpdateRequest(bedrockModelAlias = key))
                                },
                                label = { Text(label) },
                                shape = RoundedCornerShape(12.dp),
                            )
                        }
                    }

                    Button(
                        enabled = !busy,
                        onClick = {
                            vm.updateClaudeAuth(
                                ClaudeAuthUpdateRequest(
                                    awsRegion = awsRegion.trim().ifBlank { null },
                                    awsAccessKeyId = awsAkid.trim().ifBlank { null },
                                    awsSecretAccessKey = awsSecret.trim().ifBlank { null },
                                    awsSessionToken = awsSession.trim().ifBlank { null },
                                    bedrockOpusModel = opusModel.trim().ifBlank { null },
                                    bedrockSonnetModel = sonnetModel.trim().ifBlank { null },
                                    bedrockHaikuModel = haikuModel.trim().ifBlank { null },
                                ),
                            )
                            awsAkid = ""; awsSecret = ""; awsSession = ""
                        },
                    ) { Text(stringResource(de.smartzone.pocketclaude.R.string.apply)) }
                }
            }
        }
    }
}

/** Token-usage widget: this-month aggregate fetched from /me/usage. */
@Composable
private fun UsageStatsSection(vm: SettingsViewModel) {
    val usage by vm.usage.collectAsState()
    val auth by vm.claudeAuth.collectAsState()
    val isProMax = (auth?.mode ?: "pro_max") == "pro_max"

    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        shape = RoundedCornerShape(20.dp),
    ) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            if (usage == null) {
                CircularProgressIndicator(modifier = Modifier.size(20.dp))
            } else {
                val u = usage!!
                UsageRow(stringResource(de.smartzone.pocketclaude.R.string.usage_input), u.inputTokens)
                UsageRow(stringResource(de.smartzone.pocketclaude.R.string.usage_output), u.outputTokens)
                UsageRow(stringResource(de.smartzone.pocketclaude.R.string.usage_cache_create), u.cacheCreateTokens)
                UsageRow(stringResource(de.smartzone.pocketclaude.R.string.usage_cache_read), u.cacheReadTokens)
                UsageRow(stringResource(de.smartzone.pocketclaude.R.string.usage_requests), u.requestCount)
                if (u.provider.isNotEmpty()) {
                    UsageRowText(stringResource(de.smartzone.pocketclaude.R.string.usage_provider), u.provider)
                }
                if (isProMax) {
                    Text(
                        stringResource(de.smartzone.pocketclaude.R.string.usage_pro_max_note),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
            TextButton(onClick = { vm.refreshUsage() }) {
                Text(stringResource(de.smartzone.pocketclaude.R.string.usage_refresh))
            }
        }
    }
}

@Composable
private fun UsageRow(label: String, value: Long) {
    UsageRowText(label, formatNumber(value))
}

@Composable
private fun UsageRowText(label: String, value: String) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
        Text(label, style = MaterialTheme.typography.bodyMedium)
        Text(value, style = MaterialTheme.typography.bodyMedium, fontWeight = FW.Medium)
    }
}

private fun formatNumber(n: Long): String {
    if (n < 1_000) return n.toString()
    if (n < 1_000_000) return "%.1fK".format(n / 1_000.0)
    return "%.2fM".format(n / 1_000_000.0)
}

/** Chat-Sperre: globalen 5-stelligen PIN setzen/ändern/entfernen + Fingerabdruck-
 *  Toggle (gerät-lokal). Die eigentliche Sperre pro Chat läuft über das ⋮-Menü. */
@Composable
private fun ChatLockSection(
    vm: SettingsViewModel,
    settings: de.smartzone.pocketclaude.data.AppSettings,
) {
    val isSet by vm.chatLockIsSet.collectAsState()
    val busy by vm.chatLockBusy.collectAsState()
    val context = androidx.compose.ui.platform.LocalContext.current
    val biometricAvailable = remember {
        de.smartzone.pocketclaude.ui.lock.isBiometricAvailable(context)
    }

    var currentPin by remember { mutableStateOf("") }
    var newPin by remember { mutableStateOf("") }
    var confirmPin by remember { mutableStateOf("") }
    var error by remember { mutableStateOf<String?>(null) }
    var success by remember { mutableStateOf<String?>(null) }

    val wrongPinText = stringResource(de.smartzone.pocketclaude.R.string.chat_lock_wrong_current)
    val mismatchText = stringResource(de.smartzone.pocketclaude.R.string.chat_lock_pins_mismatch)
    val invalidText = stringResource(de.smartzone.pocketclaude.R.string.chat_lock_pin_must_be_5)
    val savedText = stringResource(de.smartzone.pocketclaude.R.string.chat_lock_pin_saved)
    val removedText = stringResource(de.smartzone.pocketclaude.R.string.chat_lock_pin_removed)

    fun clearInputs() { currentPin = ""; newPin = ""; confirmPin = "" }
    fun isPin(s: String) = s.length == 5 && s.all { it.isDigit() }

    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        shape = RoundedCornerShape(20.dp),
    ) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            when (isSet) {
                null -> CircularProgressIndicator(modifier = Modifier.size(20.dp))
                false -> {
                    Text(
                        stringResource(de.smartzone.pocketclaude.R.string.chat_lock_no_pin),
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    PinTextField(
                        value = newPin,
                        onValueChange = { newPin = it.filter { c -> c.isDigit() }.take(5); error = null },
                        label = stringResource(de.smartzone.pocketclaude.R.string.chat_lock_new_pin),
                    )
                    PinTextField(
                        value = confirmPin,
                        onValueChange = { confirmPin = it.filter { c -> c.isDigit() }.take(5); error = null },
                        label = stringResource(de.smartzone.pocketclaude.R.string.chat_lock_confirm_pin),
                    )
                    Button(
                        onClick = {
                            error = null; success = null
                            when {
                                !isPin(newPin) -> error = invalidText
                                newPin != confirmPin -> error = mismatchText
                                else -> vm.setChatLockPin(newPin, null) { err ->
                                    if (err == null) { clearInputs(); success = savedText }
                                    else error = if (err == "wrong") wrongPinText else err
                                }
                            }
                        },
                        enabled = !busy,
                        modifier = Modifier.fillMaxWidth(),
                    ) { Text(stringResource(de.smartzone.pocketclaude.R.string.chat_lock_set_pin)) }
                }
                true -> {
                    Text(
                        stringResource(de.smartzone.pocketclaude.R.string.chat_lock_pin_active),
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    PinTextField(
                        value = currentPin,
                        onValueChange = { currentPin = it.filter { c -> c.isDigit() }.take(5); error = null },
                        label = stringResource(de.smartzone.pocketclaude.R.string.chat_lock_current_pin),
                    )
                    PinTextField(
                        value = newPin,
                        onValueChange = { newPin = it.filter { c -> c.isDigit() }.take(5); error = null },
                        label = stringResource(de.smartzone.pocketclaude.R.string.chat_lock_new_pin),
                    )
                    PinTextField(
                        value = confirmPin,
                        onValueChange = { confirmPin = it.filter { c -> c.isDigit() }.take(5); error = null },
                        label = stringResource(de.smartzone.pocketclaude.R.string.chat_lock_confirm_pin),
                    )
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Button(
                            onClick = {
                                error = null; success = null
                                when {
                                    !isPin(newPin) -> error = invalidText
                                    newPin != confirmPin -> error = mismatchText
                                    else -> vm.setChatLockPin(newPin, currentPin) { err ->
                                        if (err == null) { clearInputs(); success = savedText }
                                        else error = if (err == "wrong") wrongPinText else err
                                    }
                                }
                            },
                            enabled = !busy,
                            modifier = Modifier.weight(1f),
                        ) { Text(stringResource(de.smartzone.pocketclaude.R.string.chat_lock_change_pin)) }
                        TextButton(
                            onClick = {
                                error = null; success = null
                                if (!isPin(currentPin)) error = wrongPinText
                                else vm.removeChatLockPin(currentPin) { err ->
                                    if (err == null) { clearInputs(); success = removedText }
                                    else error = if (err == "wrong") wrongPinText else err
                                }
                            },
                            enabled = !busy,
                        ) {
                            Text(
                                stringResource(de.smartzone.pocketclaude.R.string.chat_lock_remove_pin),
                                color = MaterialTheme.colorScheme.error,
                            )
                        }
                    }
                }
            }

            error?.let {
                Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error)
            }
            success?.let {
                Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.primary)
            }

            if (biometricAvailable) {
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                Row(
                    Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.SpaceBetween,
                ) {
                    Column(Modifier.weight(1f)) {
                        Text(
                            stringResource(de.smartzone.pocketclaude.R.string.chat_lock_biometric_toggle),
                            style = MaterialTheme.typography.bodyMedium,
                        )
                        Text(
                            stringResource(de.smartzone.pocketclaude.R.string.chat_lock_biometric_toggle_sub),
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    Switch(
                        checked = settings.chatLockBiometricEnabled,
                        onCheckedChange = { vm.setChatLockBiometric(it) },
                    )
                }
            }
        }
    }
}

@Composable
private fun PinTextField(value: String, onValueChange: (String) -> Unit, label: String) {
    OutlinedTextField(
        value = value,
        onValueChange = onValueChange,
        label = { Text(label) },
        singleLine = true,
        visualTransformation = PasswordVisualTransformation(),
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword),
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(12.dp),
    )
}

/** Über-Sektion — minimal, nur App-Name + Beschreibung. */
@Composable
private fun AboutCard() {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        shape = RoundedCornerShape(20.dp),
    ) {
        Column(Modifier.padding(16.dp)) {
            Text(
                stringResource(de.smartzone.pocketclaude.R.string.app_name),
                style = MaterialTheme.typography.titleMedium,
            )
            Text(
                stringResource(de.smartzone.pocketclaude.R.string.settings_about_app_desc),
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

/**
 * Unified Section-Header. Ersetzt `SectionTitleRow` und `SectionTitle` —
 * vorher gab es drei verschiedene Header-Stile, jetzt nur noch einen
 * konsistenten. `infoTitle` + `infoBody` aktivieren den optionalen ⓘ-Button.
 */
@Composable
private fun SectionHeader(
    text: String,
    infoTitle: String? = null,
    infoBody: (@Composable () -> Unit)? = null,
) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier.fillMaxWidth(),
    ) {
        Box(
            modifier = Modifier
                .width(4.dp)
                .height(18.dp)
                .clip(RoundedCornerShape(50))
                .background(MaterialTheme.colorScheme.primary)
        )
        Spacer(Modifier.width(10.dp))
        Text(
            text = text,
            style = MaterialTheme.typography.titleMedium,
            color = MaterialTheme.colorScheme.onSurface,
            modifier = Modifier.weight(1f),
        )
        if (infoTitle != null && infoBody != null) {
            InfoButton(title = infoTitle, body = infoBody)
        }
    }
}

/** Kleiner Untertitel innerhalb einer Card (für Sub-Gruppen wie „Denktiefe",
 *  „System-Prompt", „Skills"). Spart das Stack-on-Stack-Card-Pattern. */
@Composable
private fun SubsectionLabel(text: String) {
    Text(
        text,
        style = MaterialTheme.typography.titleSmall,
        color = MaterialTheme.colorScheme.onSurface,
    )
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun EffortChips(
    available: List<String>,
    selected: String,
    onSelect: (String) -> Unit,
) {
    // Frueher stand hier eine feste Liste, unabhaengig davon, was das Modell
    // wirklich kann. `available` kommt jetzt vom Modell selbst, sortiert nach
    // der gemeinsamen Skala, damit die Reihenfolge immer gleich bleibt.
    val labels = mapOf(
        "off" to stringResource(de.smartzone.pocketclaude.R.string.effort_off),
        "minimal" to stringResource(de.smartzone.pocketclaude.R.string.effort_minimal_label),
        "low" to stringResource(de.smartzone.pocketclaude.R.string.effort_low),
        "medium" to stringResource(de.smartzone.pocketclaude.R.string.effort_medium),
        "high" to stringResource(de.smartzone.pocketclaude.R.string.effort_high),
        "xhigh" to stringResource(de.smartzone.pocketclaude.R.string.effort_xhigh),
        "max" to stringResource(de.smartzone.pocketclaude.R.string.effort_max),
        "ultra" to stringResource(de.smartzone.pocketclaude.R.string.effort_ultra_label),
    )
    val options = EFFORT_LEVELS_ALL
        .filter { it in available }
        .map { it to (labels[it] ?: it) }
    FlowRow(
        horizontalArrangement = Arrangement.spacedBy(6.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp),
        modifier = Modifier.fillMaxWidth(),
    ) {
        options.forEach { (value, label) ->
            FilterChip(
                selected = selected == value,
                onClick = { onSelect(value) },
                label = { Text(label, style = MaterialTheme.typography.labelMedium) },
                shape = RoundedCornerShape(10.dp),
                colors = FilterChipDefaults.filterChipColors(
                    selectedContainerColor = MaterialTheme.colorScheme.primary,
                    selectedLabelColor = MaterialTheme.colorScheme.onPrimary,
                ),
            )
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun SystemPromptModeChips(
    selected: SystemPromptMode,
    onSelect: (SystemPromptMode) -> Unit,
) {
    val options = listOf(
        SystemPromptMode.STANDARD to stringResource(de.smartzone.pocketclaude.R.string.settings_sysprompt_standard),
        SystemPromptMode.PERMISSIVE to stringResource(de.smartzone.pocketclaude.R.string.settings_sysprompt_permissive),
        SystemPromptMode.ULTRA_LIBERAL to stringResource(de.smartzone.pocketclaude.R.string.settings_sysprompt_ultra_liberal),
        SystemPromptMode.CUSTOM to stringResource(de.smartzone.pocketclaude.R.string.settings_sysprompt_custom),
    )
    FlowRow(
        horizontalArrangement = Arrangement.spacedBy(6.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp),
        modifier = Modifier.fillMaxWidth(),
    ) {
        options.forEach { (value, label) ->
            FilterChip(
                selected = selected == value,
                onClick = { onSelect(value) },
                label = { Text(label, style = MaterialTheme.typography.labelMedium) },
                shape = RoundedCornerShape(10.dp),
                colors = FilterChipDefaults.filterChipColors(
                    selectedContainerColor = MaterialTheme.colorScheme.primary,
                    selectedLabelColor = MaterialTheme.colorScheme.onPrimary,
                ),
            )
        }
    }
}

/**
 * Quick-Setup-Banner — ganz oben im Settings-Screen, sichtbar bis der User
 * vollständig eingerichtet ist (Profil angelegt + eingeloggt). Zeigt eine
 * kompakte Checkliste mit grünen Haken bzw. Buttons zu den entsprechenden
 * Sections darunter. Wenn TTS via Edge läuft (= sofort einsatzbereit ohne
 * Setup), ist der TTS-Punkt automatisch grün. Sobald alle drei Punkte grün
 * sind, verschwindet das Banner komplett (siehe `!hasProfile || !isLoggedIn`
 * Check beim Aufruf).
 */
@Composable
private fun QuickSetupBanner(
    hasProfile: Boolean,
    isLoggedIn: Boolean,
    ttsReady: Boolean,
) {
    val shape = RoundedCornerShape(26.dp)
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .clip(shape)
            .background(
                Brush.linearGradient(
                    listOf(
                        MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.76f),
                        MaterialTheme.colorScheme.secondaryContainer.copy(alpha = 0.42f),
                    )
                )
            )
            .border(1.dp, MaterialTheme.colorScheme.primary.copy(alpha = 0.16f), shape),
    ) {
        Column(
            modifier = Modifier.padding(18.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Text(
                stringResource(de.smartzone.pocketclaude.R.string.settings_quick_setup_header),
                style = MaterialTheme.typography.titleSmall,
            )
            QuickSetupRow(
                done = hasProfile,
                text = if (hasProfile) stringResource(de.smartzone.pocketclaude.R.string.settings_quick_setup_profile_added) else stringResource(de.smartzone.pocketclaude.R.string.settings_quick_setup_profile_add),
            )
            QuickSetupRow(
                done = isLoggedIn,
                text = if (isLoggedIn) stringResource(de.smartzone.pocketclaude.R.string.settings_quick_setup_login_active)
                    else if (hasProfile) stringResource(de.smartzone.pocketclaude.R.string.settings_quick_setup_login_needed)
                    else stringResource(de.smartzone.pocketclaude.R.string.settings_quick_setup_login_pending),
            )
            QuickSetupRow(
                done = ttsReady,
                text = if (ttsReady) stringResource(de.smartzone.pocketclaude.R.string.settings_quick_setup_tts_ready)
                    else stringResource(de.smartzone.pocketclaude.R.string.settings_quick_setup_tts_optional),
            )
        }
    }
}

@Composable
private fun QuickSetupRow(done: Boolean, text: String) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Icon(
            imageVector = if (done) Icons.Filled.CheckCircle else Icons.Filled.Error,
            contentDescription = null,
            tint = if (done) de.smartzone.pocketclaude.ui.theme.PocketTheme.colors.success
                else MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.size(18.dp),
        )
        Spacer(Modifier.width(8.dp))
        Text(
            text,
            style = MaterialTheme.typography.bodyMedium,
            color = if (done) MaterialTheme.colorScheme.onSurface
                else MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

/**
 * ExpandableSection — collapsible Wrapper für lange Settings-Bereiche.
 *
 * Header-Row mit Titel + Chevron-Icon, klickbar. Body wird animiert ein-/
 * ausgeblendet via `animateContentSize`. Defaultmäßig collapsed; per
 * `initiallyExpanded=true` für die wichtigsten Sections.
 *
 * Optional `infoTitle` + `infoBody`: dann wird ein InfoButton rechts neben
 * dem Titel platziert (analog zu `SectionTitleRow`).
 * Optional `subtitle`: kleiner Hinweis-Text unter dem Titel (z.B. „Stimme,
 * Geschwindigkeit, Auto-Vorlesen") — gibt dem User einen Inhalts-Vorschau-
 * Hinweis im collapsed-Zustand.
 */
@Composable
private fun ExpandableSection(
    title: String,
    subtitle: String? = null,
    initiallyExpanded: Boolean = false,
    infoTitle: String? = null,
    infoBody: (@Composable () -> Unit)? = null,
    content: @Composable () -> Unit,
) {
    var expanded by remember { mutableStateOf(initiallyExpanded) }
    Surface(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(24.dp),
        color = MaterialTheme.colorScheme.surface.copy(alpha = 0.82f),
        contentColor = MaterialTheme.colorScheme.onSurface,
        border = androidx.compose.foundation.BorderStroke(1.dp, PocketTheme.colors.outlineSoft),
    ) {
    Column(
        modifier = Modifier.animateContentSize().padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        // Header-Row: Titel + (optional) Info-Button + Chevron
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(16.dp))
                .clickable { expanded = !expanded }
                .padding(vertical = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    title,
                    style = MaterialTheme.typography.titleMedium,
                )
                if (subtitle != null && !expanded) {
                    Text(
                        subtitle,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
            if (infoTitle != null && infoBody != null) {
                InfoButton(title = infoTitle, body = infoBody)
            }
            Icon(
                imageVector = if (expanded) Icons.Filled.ExpandLess else Icons.Filled.ExpandMore,
                contentDescription = if (expanded) stringResource(de.smartzone.pocketclaude.R.string.settings_collapse) else stringResource(de.smartzone.pocketclaude.R.string.settings_expand),
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        if (expanded) {
            content()
        }
    }
    }
}

/** Kleines farbiges Badge das den Tier-Hint eines API-Keys anzeigt:
 *  - "free"        → orange „Free" (10 RPD Limit)
 *  - "likely_paid" → grün „Paid?" (hat >15 Erfolge ohne FreeTier-Burn → vermutl. Paid)
 *  - "unknown"     → grau „?" (noch zu wenig Daten) */
@Composable
private fun TierBadge(tierHint: String) {
    data class BadgeStyle(val text: String, val color: androidx.compose.ui.graphics.Color)
    val style = when (tierHint) {
        "free" -> BadgeStyle("Free", androidx.compose.ui.graphics.Color(0xFFE89F2C))
        "likely_paid" -> BadgeStyle("Paid?", androidx.compose.ui.graphics.Color(0xFF4CAF50))
        else -> BadgeStyle("?", MaterialTheme.colorScheme.onSurfaceVariant)
    }
    Box(
        modifier = Modifier
            .clip(RoundedCornerShape(6.dp))
            .background(style.color.copy(alpha = 0.18f))
            .padding(horizontal = 6.dp, vertical = 2.dp),
    ) {
        Text(
            style.text,
            style = MaterialTheme.typography.labelSmall,
            color = style.color,
        )
    }
}


@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun TtsSection(
    vm: SettingsViewModel,
    settings: de.smartzone.pocketclaude.data.AppSettings,
) {
    val ttsStatus by vm.ttsStatus.collectAsState()
    val ttsBusy by vm.ttsBusy.collectAsState()
    val ttsError by vm.ttsError.collectAsState()
    val ttsTest by vm.ttsTest.collectAsState()
    var showJsonDialog by remember { mutableStateOf(false) }
    var voiceMenuOpen by remember { mutableStateOf(false) }
    var jsonText by remember { mutableStateOf("") }

    // Provider-Flags auf TtsSection-Ebene, damit alle drei Cards Zugriff haben.
    val provider = ttsStatus?.provider ?: "gemini_web"
    val isGemini = provider == "gemini_api"
    val isCloud = provider == "cloud_tts"
    val isEdge = provider == "edge_tts"
    // Gemini-Web: die Vorlesefunktion von gemini.google.com ueber einen Dienst
    // auf dem Server. Gratis, ohne Einrichtung, und deutlich schneller als die
    // anderen — dafuer ohne Stimmauswahl.
    val isWeb = provider == "gemini_web"

    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {

    // ============================================================
    // Card A — Provider & Setup
    // ============================================================
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        shape = RoundedCornerShape(20.dp),
    ) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {

            Text(
                stringResource(de.smartzone.pocketclaude.R.string.settings_tts_provider_setup_title),
                style = MaterialTheme.typography.titleMedium,
            )

            // Provider-Auswahl: Edge (free, no-setup) / Gemini API (paid key) / Cloud TTS (service account).
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        stringResource(de.smartzone.pocketclaude.R.string.settings_tts_provider_label),
                        style = MaterialTheme.typography.labelLarge,
                        modifier = Modifier.weight(1f),
                    )
                    InfoButton(
                        title = stringResource(de.smartzone.pocketclaude.R.string.settings_tts_provider_info_title),
                    ) {
                        InfoBulletParagraph(
                            stringResource(de.smartzone.pocketclaude.R.string.settings_tts_provider_web_label),
                            stringResource(de.smartzone.pocketclaude.R.string.settings_tts_provider_web_body)
                        )
                        InfoBulletParagraph(
                            stringResource(de.smartzone.pocketclaude.R.string.settings_tts_provider_edge_label),
                            stringResource(de.smartzone.pocketclaude.R.string.settings_tts_provider_edge_body)
                        )
                        InfoBulletParagraph(
                            stringResource(de.smartzone.pocketclaude.R.string.settings_tts_provider_gemini_label),
                            stringResource(de.smartzone.pocketclaude.R.string.settings_tts_provider_gemini_body)
                        )
                        InfoBulletParagraph(
                            stringResource(de.smartzone.pocketclaude.R.string.settings_tts_provider_cloud_label),
                            stringResource(de.smartzone.pocketclaude.R.string.settings_tts_provider_cloud_body)
                        )
                    }
                }
                SingleChoiceSegmentedButtonRow(modifier = Modifier.fillMaxWidth()) {
                    SegmentedButton(
                        selected = isWeb,
                        onClick = {
                            if (!isWeb && !ttsBusy) vm.setTtsProvider("gemini_web")
                        },
                        shape = SegmentedButtonDefaults.itemShape(index = 0, count = 2),
                        enabled = !ttsBusy,
                    ) { Text(stringResource(de.smartzone.pocketclaude.R.string.settings_tts_provider_web_short)) }
                    SegmentedButton(
                        selected = isEdge,
                        onClick = {
                            if (!isEdge && !ttsBusy) vm.setTtsProvider("edge_tts")
                        },
                        shape = SegmentedButtonDefaults.itemShape(index = 1, count = 2),
                        enabled = !ttsBusy,
                    ) { Text("Edge") }
                }
                SingleChoiceSegmentedButtonRow(modifier = Modifier.fillMaxWidth()) {
                    SegmentedButton(
                        selected = isGemini,
                        onClick = {
                            if (!isGemini && !ttsBusy) vm.setTtsProvider("gemini_api")
                        },
                        shape = SegmentedButtonDefaults.itemShape(index = 0, count = 2),
                        enabled = !ttsBusy,
                    ) { Text("Gemini API") }
                    SegmentedButton(
                        selected = isCloud,
                        onClick = {
                            if (!isCloud && !ttsBusy) vm.setTtsProvider("cloud_tts")
                        },
                        shape = SegmentedButtonDefaults.itemShape(index = 1, count = 2),
                        enabled = !ttsBusy,
                    ) { Text("Cloud TTS") }
                }
                // Status-Hint mit Farb-Tönung je nach Provider.
                //
                // Wichtig: der Hint trennt jetzt SAUBER zwischen Pool-Effekt
                // (= Round-Robin über aufeinanderfolgende Antworten) und
                // Chunking-Effekt (= mehrere parallele API-Calls pro Antwort).
                // Vorher stand „Round-Robin + Rate-Limiter" im selben Satz —
                // das war irreführend, weil der Rate-Limiter nur greift wenn
                // Chunking AN ist und parallele Calls rausgehen.
                data class Hint(val text: String, val emphasis: Boolean)
                val keySource = ttsStatus?.geminiApiKeySource ?: "none"
                val keyCount = ttsStatus?.geminiApiKeyCount ?: 0
                val chunkOn = ttsStatus?.chunkingEnabled ?: false
                val hint = when {
                    isWeb && ttsStatus?.configured == false -> Hint(
                        stringResource(de.smartzone.pocketclaude.R.string.settings_tts_status_web_down),
                        emphasis = true,
                    )
                    isWeb -> Hint(
                        stringResource(de.smartzone.pocketclaude.R.string.settings_tts_status_web_active),
                        emphasis = false,
                    )
                    isEdge -> Hint(
                        stringResource(de.smartzone.pocketclaude.R.string.settings_tts_status_edge_active),
                        emphasis = false,
                    )
                    isGemini && keyCount >= 2 && chunkOn -> Hint(
                        stringResource(de.smartzone.pocketclaude.R.string.settings_tts_status_gemini_pool_chunk_on, keyCount, keyCount * 3),
                        emphasis = false,
                    )
                    isGemini && keyCount >= 2 && !chunkOn -> Hint(
                        stringResource(de.smartzone.pocketclaude.R.string.settings_tts_status_gemini_pool_chunk_off, keyCount),
                        emphasis = false,
                    )
                    isGemini && ttsStatus?.geminiApiConfigured == true && keySource == "tts" -> Hint(
                        stringResource(de.smartzone.pocketclaude.R.string.settings_tts_status_gemini_1key_tts),
                        emphasis = false,
                    )
                    isGemini && ttsStatus?.geminiApiConfigured == true && keySource == "image" -> Hint(
                        stringResource(de.smartzone.pocketclaude.R.string.settings_tts_status_gemini_image_shared),
                        emphasis = false,
                    )
                    isGemini -> Hint(
                        stringResource(de.smartzone.pocketclaude.R.string.settings_tts_status_gemini_no_key),
                        emphasis = true,
                    )
                    isCloud && ttsStatus?.cloudTtsConfigured == true && chunkOn -> Hint(
                        stringResource(de.smartzone.pocketclaude.R.string.settings_tts_status_cloud_chunk_on),
                        emphasis = false,
                    )
                    isCloud && ttsStatus?.cloudTtsConfigured == true -> Hint(
                        stringResource(de.smartzone.pocketclaude.R.string.settings_tts_status_cloud_ok),
                        emphasis = false,
                    )
                    else -> Hint(
                        stringResource(de.smartzone.pocketclaude.R.string.settings_tts_status_cloud_no_json),
                        emphasis = true,
                    )
                }
                Text(
                    hint.text,
                    style = MaterialTheme.typography.bodySmall,
                    color = if (hint.emphasis) MaterialTheme.colorScheme.error
                            else MaterialTheme.colorScheme.onSurfaceVariant,
                )

                // === Chunking-Toggle ===
                // Bewusst HIER in derselben Card wie der Status-Hint, weil
                // der Hint sich auf den Chunking-Stand bezieht. Bei Edge-TTS
                // ausgeblendet — die edge-tts-Lib chunkt intern via WebSocket,
                // ein zusätzliches App-Chunking bringt nichts. Bei Gemini-Web
                // ebenfalls ausgeblendet, und dort ist es keine Frage des
                // Nutzens: dessen Audioformat laesst sich nicht stueckweise
                // aneinanderhaengen, ein eingeschalteter Schalter wuerde stumm
                // kaputtes Audio erzeugen. Der Server sperrt das zusaetzlich.
                if (!isEdge && !isWeb) {
                    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                    val chunkingExplicit = ttsStatus?.chunkingExplicit ?: false
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Column(modifier = Modifier.weight(1f)) {
                            Text(
                                stringResource(de.smartzone.pocketclaude.R.string.settings_tts_chunking_label),
                                style = MaterialTheme.typography.titleSmall,
                            )
                            val ttsCloudLabel = stringResource(de.smartzone.pocketclaude.R.string.settings_tts_for_cloud_tts)
                            val ttsGeminiRateHint = stringResource(de.smartzone.pocketclaude.R.string.settings_tts_gemini_rate_hint)
                            val sub = when {
                                chunkingExplicit && chunkOn ->
                                    stringResource(de.smartzone.pocketclaude.R.string.settings_tts_chunking_manual_on)
                                chunkingExplicit && !chunkOn ->
                                    stringResource(de.smartzone.pocketclaude.R.string.settings_tts_chunking_manual_off)
                                chunkOn ->
                                    stringResource(de.smartzone.pocketclaude.R.string.settings_tts_auto_default_on, if (isCloud) ttsCloudLabel else provider)
                                else ->
                                    stringResource(de.smartzone.pocketclaude.R.string.settings_tts_auto_default_off, if (isGemini) ttsGeminiRateHint else provider)
                            }
                            Text(
                                sub,
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                        InfoButton(title = stringResource(de.smartzone.pocketclaude.R.string.settings_tts_chunking_info_title)) {
                            InfoParagraph(
                                stringResource(de.smartzone.pocketclaude.R.string.settings_tts_chunking_info_intro)
                            )
                            InfoBulletParagraph(
                                stringResource(de.smartzone.pocketclaude.R.string.settings_tts_chunking_info_cloud_label),
                                stringResource(de.smartzone.pocketclaude.R.string.settings_tts_chunking_info_cloud_body)
                            )
                            InfoBulletParagraph(
                                stringResource(de.smartzone.pocketclaude.R.string.settings_tts_chunking_info_gemini_label),
                                stringResource(de.smartzone.pocketclaude.R.string.settings_tts_chunking_info_gemini_body)
                            )
                        }
                        Switch(
                            checked = chunkOn,
                            onCheckedChange = { v -> vm.setTtsChunking(v) },
                            enabled = !ttsBusy,
                        )
                    }
                    if (chunkingExplicit) {
                        TextButton(
                            onClick = { vm.setTtsChunking(null) },
                            enabled = !ttsBusy,
                        ) {
                            Text(stringResource(de.smartzone.pocketclaude.R.string.settings_tts_back_to_default))
                        }
                    }
                }
            }

            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)

            // Eigenes API-Key-Feld für TTS — nur wenn Provider = Gemini API.
            // Bewusst getrennt von der Image-Gen-API-Key-Eingabe, weil:
            //   - Image-Gen läuft oft über Paid-Account (4K-Output, Pro-Modelle)
            //   - TTS kann komplett über Free-Tier-Account laufen (Gemini-3.1-
            //     Flash-TTS ist im Free Tier verfügbar, verifiziert Mai 2026)
            if (isGemini) {
                // Hinweis-Banner: Image- und TTS-Key können derselbe sein, müssen
                // aber nicht — der Server fällt bei fehlendem TTS-Key automatisch
                // auf den Image-Key zurück. Klärt das verbreitete „warum zwei
                // Felder?"-Verständnis-Problem.
                Surface(
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(10.dp),
                    color = MaterialTheme.colorScheme.tertiaryContainer.copy(alpha = 0.4f),
                ) {
                    Text(
                        stringResource(de.smartzone.pocketclaude.R.string.settings_tts_image_shared_key_tip),
                        style = MaterialTheme.typography.bodySmall,
                        modifier = Modifier.padding(10.dp),
                    )
                }
                TtsGeminiApiKeyField(vm = vm, ttsStatus = ttsStatus, ttsBusy = ttsBusy)
            }

            // Status — nur informativ wenn nicht Edge (Edge braucht nichts).
            if (!isEdge) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    val configured = ttsStatus?.configured == true
                    Icon(
                        imageVector = if (configured) Icons.Filled.CheckCircle else Icons.Filled.Error,
                        contentDescription = null,
                        tint = if (configured) de.smartzone.pocketclaude.ui.theme.PocketTheme.colors.success
                               else MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.size(20.dp),
                    )
                    Spacer(Modifier.width(8.dp))
                    Column(Modifier.weight(1f)) {
                        Text(
                            if (configured) stringResource(de.smartzone.pocketclaude.R.string.settings_tts_provider_ready)
                            else stringResource(de.smartzone.pocketclaude.R.string.settings_tts_provider_not_ready),
                            style = MaterialTheme.typography.titleSmall,
                        )
                        if (configured && isCloud) {
                            val email = ttsStatus?.clientEmail.orEmpty()
                            if (email.isNotBlank()) {
                                Text(
                                    email,
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                        }
                    }
                    // Lösch-Button für Cloud-TTS-Credentials nur bei Cloud-Provider.
                    if (ttsStatus?.cloudTtsConfigured == true && isCloud) {
                        IconButton(onClick = { vm.deleteTtsCredentials() }, enabled = !ttsBusy) {
                            Icon(Icons.Filled.Delete, contentDescription = stringResource(de.smartzone.pocketclaude.R.string.settings_tts_remove_credentials))
                        }
                    }
                }
            }

            // JSON-Upload-Button — nur für Cloud-TTS-Pfad (Edge braucht's nicht, Gemini hat eigenen Key-Slot).
            if (isCloud) {
                FilledTonalButton(
                    onClick = {
                        jsonText = ""
                        showJsonDialog = true
                    },
                    enabled = !ttsBusy && settings.isConfigured,
                    shape = RoundedCornerShape(12.dp),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    if (ttsBusy) {
                        CircularProgressIndicator(modifier = Modifier.size(16.dp), strokeWidth = 2.dp)
                        Spacer(Modifier.width(8.dp))
                    }
                    Icon(Icons.Filled.Upload, contentDescription = null)
                    Spacer(Modifier.width(8.dp))
                    Text(if (ttsStatus?.cloudTtsConfigured == true) stringResource(de.smartzone.pocketclaude.R.string.settings_tts_replace_cloud_credentials) else stringResource(de.smartzone.pocketclaude.R.string.settings_tts_paste_cloud_credentials))
                }
            }

            if (!settings.isConfigured) {
                Text(
                    stringResource(de.smartzone.pocketclaude.R.string.settings_tts_need_server_config),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }

            ttsError?.let { err ->
                Text(
                    err,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error,
                )
                TextButton(onClick = vm::clearTtsError) { Text(stringResource(de.smartzone.pocketclaude.R.string.action_ok)) }
            }

            // Cloud-Billing-Widget: Spend, Budget, AI-Pro-Credit-Restwert.
            // Nur sichtbar wenn Cloud-TTS konfiguriert ist (vorher gibt's
            // keinen Service-Account → API-Call ginge ins Leere).
            if (ttsStatus?.cloudTtsConfigured == true) {
                CloudBillingWidget(vm = vm)
            }
        }
    }

    // ============================================================
    // Card B — Stimme & Wiedergabe
    // ============================================================
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        shape = RoundedCornerShape(20.dp),
    ) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {

            Text(
                stringResource(de.smartzone.pocketclaude.R.string.settings_voice_playback_title),
                style = MaterialTheme.typography.titleMedium,
            )

            // Voice-Auswahl — nach Engine-Tier gruppiert, damit Gemini-Voices
            // klar von den klassischen Cloud-TTS-Voices getrennt sind.
            // Filtert auf den aktuell aktiven Provider: bei `gemini_api` sind
            // nur die `gemini-*`-Voices kompatibel (Direct-API kennt keine
            // Chirp/Studio/Neural2/etc.), bei `cloud_tts` ist alles möglich.
            val allVoices = ttsStatus?.voices.orEmpty()
            val voices = allVoices.filter { provider in it.compatible_providers }
            if (isWeb) {
                // Ehrlicher Hinweis statt einer Auswahl, die keine ist: der
                // Vorlese-Aufruf von Gemini kennt schlicht keinen Parameter
                // fuer die Stimme.
                Text(
                    stringResource(de.smartzone.pocketclaude.R.string.settings_tts_voice_web_fixed),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            if (voices.isNotEmpty()) {
                ExposedDropdownMenuBox(
                    expanded = voiceMenuOpen,
                    onExpandedChange = { voiceMenuOpen = !voiceMenuOpen },
                ) {
                    // Aktuelle Voice: Label aus der vollen (un-gefilterten) Liste
                    // lesen, damit der Anzeigename sichtbar bleibt — selbst wenn
                    // die Voice mit dem aktuellen Provider nicht kompatibel ist
                    // (Server fällt dann intern auf einen Default zurück).
                    val currentVoice = allVoices.firstOrNull { it.id == settings.ttsVoice }
                    val currentVoiceIncompatible = currentVoice != null &&
                        provider !in currentVoice.compatible_providers
                    OutlinedTextField(
                        value = if (currentVoiceIncompatible)
                            stringResource(de.smartzone.pocketclaude.R.string.settings_voice_incompatible, currentVoice.label, provider)
                        else currentVoice?.label ?: settings.ttsVoice,
                        onValueChange = {},
                        readOnly = true,
                        label = { Text(stringResource(de.smartzone.pocketclaude.R.string.settings_voice_label)) },
                        trailingIcon = {
                            ExposedDropdownMenuDefaults.TrailingIcon(expanded = voiceMenuOpen)
                        },
                        modifier = Modifier
                            .fillMaxWidth()
                            .menuAnchor(),
                        shape = RoundedCornerShape(14.dp),
                    )
                    DropdownMenu(
                        expanded = voiceMenuOpen,
                        onDismissRequest = { voiceMenuOpen = false },
                    ) {
                        val tierOrder = listOf("edge", "gemini", "chirp3hd", "studio", "neural2", "wavenet", "standard")
                        val tierLabels = mapOf(
                            "edge" to stringResource(de.smartzone.pocketclaude.R.string.settings_tier_label_edge),
                            "gemini" to stringResource(de.smartzone.pocketclaude.R.string.settings_tier_label_gemini),
                            "chirp3hd" to stringResource(de.smartzone.pocketclaude.R.string.settings_tier_label_chirp3hd),
                            "studio" to stringResource(de.smartzone.pocketclaude.R.string.settings_tier_label_studio),
                            "neural2" to stringResource(de.smartzone.pocketclaude.R.string.settings_tier_label_neural2),
                            "wavenet" to stringResource(de.smartzone.pocketclaude.R.string.settings_tier_label_wavenet),
                            "standard" to stringResource(de.smartzone.pocketclaude.R.string.settings_tier_label_standard),
                        )
                        val grouped = voices.groupBy { it.tier }
                        val orderedTiers = tierOrder.filter { grouped.containsKey(it) } +
                            grouped.keys.filter { it !in tierOrder }
                        orderedTiers.forEachIndexed { idx, tier ->
                            if (idx > 0) HorizontalDivider()
                            Text(
                                text = tierLabels[tier] ?: tier.replaceFirstChar { it.uppercase() },
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                modifier = Modifier.padding(
                                    start = 16.dp, end = 16.dp, top = 8.dp, bottom = 4.dp,
                                ),
                            )
                            grouped[tier].orEmpty().forEach { v ->
                                DropdownMenuItem(
                                    text = { Text(v.label) },
                                    onClick = {
                                        vm.setVoice(v.id)
                                        voiceMenuOpen = false
                                    },
                                )
                            }
                        }
                    }
                }
            }

            // Wiedergabe-Geschwindigkeit — diskrete 0.25-Schritte von 0.25x bis 2.0x.
            // Wird als ?rate=... Query-Param an den Server geschickt.
            Column {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        stringResource(de.smartzone.pocketclaude.R.string.settings_speed_label),
                        style = MaterialTheme.typography.titleSmall,
                        modifier = Modifier.weight(1f),
                    )
                    Text(
                        stringResource(de.smartzone.pocketclaude.R.string.settings_speed_value, "%.2f".format(settings.ttsSpeed)),
                        style = MaterialTheme.typography.titleSmall,
                        color = MaterialTheme.colorScheme.primary,
                    )
                }
                Slider(
                    value = settings.ttsSpeed,
                    onValueChange = { v ->
                        // auf 0.25-Schritte snappen
                        val snapped = (v * 4f).toInt().coerceIn(1, 8) / 4f
                        if (snapped != settings.ttsSpeed) vm.setSpeed(snapped)
                    },
                    valueRange = 0.25f..2.0f,
                    steps = 6,  // 0.25, 0.50, 0.75, 1.00, 1.25, 1.50, 1.75, 2.00 → 6 Stops zwischen 8 Werten
                    enabled = ttsStatus?.configured == true,
                    colors = SliderDefaults.colors(
                        activeTrackColor = MaterialTheme.colorScheme.primary,
                        inactiveTrackColor = MaterialTheme.colorScheme.surfaceVariant,
                    ),
                )
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                ) {
                    Text(stringResource(de.smartzone.pocketclaude.R.string.settings_speed_min), style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Text(stringResource(de.smartzone.pocketclaude.R.string.settings_speed_one), style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Text(stringResource(de.smartzone.pocketclaude.R.string.settings_speed_max), style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }

            // Auto-Speak Switch
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(Modifier.weight(1f)) {
                    Text(stringResource(de.smartzone.pocketclaude.R.string.settings_auto_speak_label), style = MaterialTheme.typography.titleSmall)
                    Text(
                        stringResource(de.smartzone.pocketclaude.R.string.settings_auto_speak_desc),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                Switch(
                    checked = settings.ttsAutoSpeak,
                    onCheckedChange = vm::setAutoSpeak,
                    enabled = ttsStatus?.configured == true,
                )
            }

            // Test-Button
            Row(verticalAlignment = Alignment.CenterVertically) {
                FilledTonalButton(
                    onClick = vm::testVoice,
                    enabled = ttsStatus?.configured == true && ttsTest !is TtsTestResult.Testing,
                    shape = RoundedCornerShape(12.dp),
                ) {
                    Icon(Icons.AutoMirrored.Filled.VolumeUp, contentDescription = null)
                    Spacer(Modifier.width(8.dp))
                    Text(stringResource(de.smartzone.pocketclaude.R.string.settings_tts_test_btn))
                }
                Spacer(Modifier.width(8.dp))
                FilledTonalButton(
                    onClick = vm::stopAudio,
                    shape = RoundedCornerShape(12.dp),
                ) {
                    Icon(Icons.Filled.Stop, contentDescription = null)
                    Spacer(Modifier.width(8.dp))
                    Text(stringResource(de.smartzone.pocketclaude.R.string.settings_tts_stop_btn))
                }
            }
            when (val t = ttsTest) {
                is TtsTestResult.Failure -> Text(
                    t.reason,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error,
                )
                else -> Unit
            }
        }
    }

    // ============================================================
    // Card C — TTS-Modell-Wahl (nur sichtbar bei Gemini-Voice)
    // ============================================================
    // Chunking wurde 2026-05-19 nach Card A verschoben (gehört konzeptionell
    // zum Provider-Status, weil sich der Hint-Text dort auf den Chunking-
    // Stand bezieht). Diese Card hier zeigt nur noch die Modell-Wahl, und
    // nur wenn überhaupt eine Gemini-Voice aktiv ist — sonst ist die ganze
    // Card unsichtbar.
    val allVoicesForModel = ttsStatus?.voices.orEmpty()
    val voicesForModel = allVoicesForModel.filter { provider in it.compatible_providers }
    val isGeminiVoice = settings.ttsVoice.startsWith("gemini-") ||
        voicesForModel.firstOrNull { it.id == settings.ttsVoice }?.tier == "gemini"
    val availableModels = ttsStatus?.availableModels.orEmpty()
    if (isGeminiVoice && availableModels.isNotEmpty()) {
        Card(
            modifier = Modifier.fillMaxWidth(),
            colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
            shape = RoundedCornerShape(20.dp),
        ) {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
                Text(
                    stringResource(de.smartzone.pocketclaude.R.string.settings_gemini_tts_model_title),
                    style = MaterialTheme.typography.titleMedium,
                )
                run {
                val currentModelId = ttsStatus?.ttsModel
                    ?: availableModels.firstOrNull { it.default }?.id
                    ?: availableModels.first().id
                val currentModel = availableModels.firstOrNull { it.id == currentModelId }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        stringResource(de.smartzone.pocketclaude.R.string.settings_tts_model_label),
                        style = MaterialTheme.typography.titleSmall,
                        modifier = Modifier.weight(1f),
                    )
                    InfoButton(title = stringResource(de.smartzone.pocketclaude.R.string.settings_tts_model_picker_title)) {
                        InfoParagraph(
                            stringResource(de.smartzone.pocketclaude.R.string.settings_tts_model_picker_intro)
                        )
                        InfoBulletParagraph(
                            stringResource(de.smartzone.pocketclaude.R.string.settings_tts_model_25_flash_label),
                            stringResource(de.smartzone.pocketclaude.R.string.settings_tts_model_25_flash_body)
                        )
                        InfoBulletParagraph(
                            stringResource(de.smartzone.pocketclaude.R.string.settings_tts_model_31_flash_label),
                            stringResource(de.smartzone.pocketclaude.R.string.settings_tts_model_31_flash_body)
                        )
                        InfoBulletParagraph(
                            stringResource(de.smartzone.pocketclaude.R.string.settings_tts_model_25_pro_label),
                            stringResource(de.smartzone.pocketclaude.R.string.settings_tts_model_25_pro_body)
                        )
                    }
                }
                var modelMenuOpen by remember { mutableStateOf(false) }
                ExposedDropdownMenuBox(
                    expanded = modelMenuOpen,
                    onExpandedChange = { if (!ttsBusy) modelMenuOpen = !modelMenuOpen },
                ) {
                    val priceText = currentModel?.priceHint?.takeIf { it.isNotBlank() }.orEmpty()
                    OutlinedTextField(
                        value = currentModel?.label ?: currentModelId,
                        onValueChange = {},
                        readOnly = true,
                        label = { Text(stringResource(de.smartzone.pocketclaude.R.string.settings_model_label)) },
                        supportingText = {
                            if (priceText.isNotEmpty()) Text(priceText)
                        },
                        trailingIcon = {
                            ExposedDropdownMenuDefaults.TrailingIcon(expanded = modelMenuOpen)
                        },
                        enabled = !ttsBusy,
                        modifier = Modifier
                            .fillMaxWidth()
                            .menuAnchor(),
                        shape = RoundedCornerShape(14.dp),
                    )
                    DropdownMenu(
                        expanded = modelMenuOpen,
                        onDismissRequest = { modelMenuOpen = false },
                    ) {
                        availableModels.forEach { m ->
                            DropdownMenuItem(
                                text = {
                                    Column {
                                        Text(m.label)
                                        if (m.priceHint.isNotBlank()) {
                                            Text(
                                                m.priceHint,
                                                style = MaterialTheme.typography.labelSmall,
                                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                            )
                                        }
                                    }
                                },
                                onClick = {
                                    if (m.id != currentModelId) vm.setTtsModel(m.id)
                                    modelMenuOpen = false
                                },
                            )
                        }
                    }
                }
                }  // close run {}
            }  // close Column
        }  // close Card
    }  // close if (isGeminiVoice && ...)

    } // outer Column (Cards A/B/C)

    if (showJsonDialog) {
        AlertDialog(
            onDismissRequest = { showJsonDialog = false },
            title = { Text(stringResource(de.smartzone.pocketclaude.R.string.settings_sa_dialog_title)) },
            text = {
                Column {
                    Text(
                        stringResource(de.smartzone.pocketclaude.R.string.settings_sa_dialog_body),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Spacer(Modifier.height(10.dp))
                    OutlinedTextField(
                        value = jsonText,
                        onValueChange = { jsonText = it },
                        placeholder = { Text(stringResource(de.smartzone.pocketclaude.R.string.settings_sa_dialog_placeholder)) },
                        maxLines = 12,
                        modifier = Modifier.fillMaxWidth(),
                        shape = RoundedCornerShape(12.dp),
                    )
                }
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        if (jsonText.isNotBlank()) {
                            vm.uploadTtsCredentials(jsonText)
                            showJsonDialog = false
                        }
                    },
                ) { Text(stringResource(de.smartzone.pocketclaude.R.string.settings_sa_upload_btn)) }
            },
            dismissButton = {
                TextButton(onClick = { showJsonDialog = false }) { Text(stringResource(de.smartzone.pocketclaude.R.string.action_cancel)) }
            },
        )
    }
}

@Composable
private fun TestResultIndicator(state: ConnectionTestResult) {
    when (state) {
        ConnectionTestResult.Idle -> {}
        ConnectionTestResult.Testing -> Row(verticalAlignment = Alignment.CenterVertically) {
            CircularProgressIndicator(modifier = Modifier.size(18.dp), strokeWidth = 2.dp)
            Spacer(Modifier.width(8.dp))
            Text(stringResource(de.smartzone.pocketclaude.R.string.settings_testing), style = MaterialTheme.typography.bodySmall)
        }
        is ConnectionTestResult.Success -> Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(
                Icons.Filled.CheckCircle,
                contentDescription = null,
                tint = PocketTheme.colors.success,
                modifier = Modifier.size(18.dp),
            )
            Spacer(Modifier.width(8.dp))
            Text(
                stringResource(de.smartzone.pocketclaude.R.string.settings_ok_with_model, state.model),
                style = MaterialTheme.typography.bodySmall,
                color = PocketTheme.colors.success,
            )
        }
        is ConnectionTestResult.Failure -> Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(
                Icons.Filled.Error,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.error,
                modifier = Modifier.size(18.dp),
            )
            Spacer(Modifier.width(8.dp))
            Text(
                state.reason,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.error,
            )
        }
    }
}

@Composable
private fun BackupSection(vm: SettingsViewModel) {
    val context = androidx.compose.ui.platform.LocalContext.current
    val state by vm.backup.collectAsState()

    // File-Picker für Import — akzeptiert ZIP + andere Container-Formate
    val importPicker = androidx.activity.compose.rememberLauncherForActivityResult(
        contract = androidx.activity.result.contract.ActivityResultContracts.OpenDocument(),
    ) { uri: android.net.Uri? ->
        if (uri != null) {
            try {
                val bytes = context.contentResolver.openInputStream(uri)?.use { it.readBytes() }
                if (bytes != null && bytes.isNotEmpty()) {
                    vm.stageImport(bytes)
                }
            } catch (e: Exception) {
                android.widget.Toast.makeText(
                    context,
                    context.getString(de.smartzone.pocketclaude.R.string.settings_backup_file_read_failed, e.message ?: ""),
                    android.widget.Toast.LENGTH_LONG,
                ).show()
            }
        }
    }

    // Bei Exported: ZIP in Cache schreiben + Share-Intent öffnen
    androidx.compose.runtime.LaunchedEffect(state) {
        val s = state
        if (s is SettingsViewModel.BackupState.Exported) {
            shareBackupZip(context, s.bytes, s.filename)
            vm.resetBackupState()
        }
    }

    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        shape = RoundedCornerShape(20.dp),
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Text(
                stringResource(de.smartzone.pocketclaude.R.string.settings_backup_intro),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            val busy = state is SettingsViewModel.BackupState.Exporting ||
                state is SettingsViewModel.BackupState.Verifying ||
                state is SettingsViewModel.BackupState.Importing
            Row(
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                FilledTonalButton(
                    onClick = { vm.startExport() },
                    enabled = !busy,
                    shape = RoundedCornerShape(12.dp),
                ) {
                    Icon(Icons.Filled.Upload, contentDescription = null)
                    Spacer(Modifier.width(8.dp))
                    Text(stringResource(de.smartzone.pocketclaude.R.string.settings_backup_btn_export))
                }
                FilledTonalButton(
                    onClick = {
                        // ZIP-MIME-Types — Android lässt unterschiedliche
                        // MIME-Strings je nach Quelle (z.B. Telegram nutzt
                        // application/zip, andere application/x-zip-compressed).
                        importPicker.launch(arrayOf(
                            "application/zip",
                            "application/x-zip-compressed",
                            "application/octet-stream",
                            "*/*",
                        ))
                    },
                    enabled = !busy,
                    shape = RoundedCornerShape(12.dp),
                ) {
                    Icon(Icons.Filled.PlayArrow, contentDescription = null)
                    Spacer(Modifier.width(8.dp))
                    Text(stringResource(de.smartzone.pocketclaude.R.string.settings_backup_btn_import))
                }
            }
            if (busy) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    CircularProgressIndicator(
                        modifier = Modifier.size(14.dp),
                        strokeWidth = 2.dp,
                    )
                    Spacer(Modifier.width(8.dp))
                    Text(
                        when (state) {
                            is SettingsViewModel.BackupState.Importing -> stringResource(de.smartzone.pocketclaude.R.string.settings_backup_importing)
                            is SettingsViewModel.BackupState.Verifying -> stringResource(de.smartzone.pocketclaude.R.string.settings_backup_checking)
                            else -> stringResource(de.smartzone.pocketclaude.R.string.settings_backup_loading)
                        },
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
            }
        }
    }

    // Confirm-Dialog: Manifest-Info anzeigen + Replace/Merge wählen
    val ready = state as? SettingsViewModel.BackupState.ReadyToImport
    if (ready != null) {
        AlertDialog(
            onDismissRequest = { vm.resetBackupState() },
            title = { Text(stringResource(de.smartzone.pocketclaude.R.string.settings_backup_import_title)) },
            text = {
                Column {
                    val m = ready.manifest
                    Text(
                        stringResource(de.smartzone.pocketclaude.R.string.settings_backup_created, m.createdAt.substringBefore('T')),
                        style = MaterialTheme.typography.bodyMedium,
                    )
                    Text(
                        stringResource(de.smartzone.pocketclaude.R.string.settings_backup_stats, m.conversationCount, m.messageCount, m.attachmentCount),
                        style = MaterialTheme.typography.bodyMedium,
                    )
                    Text(
                        stringResource(de.smartzone.pocketclaude.R.string.settings_backup_versions, m.serverVersion, m.schemaVersion),
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Spacer(Modifier.height(12.dp))
                    Text(
                        stringResource(de.smartzone.pocketclaude.R.string.settings_backup_replace_or_merge),
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
            },
            confirmButton = {
                Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                    TextButton(onClick = { vm.confirmImport("merge") }) {
                        Text(stringResource(de.smartzone.pocketclaude.R.string.settings_backup_btn_merge))
                    }
                    TextButton(onClick = { vm.confirmImport("replace") }) {
                        Text(stringResource(de.smartzone.pocketclaude.R.string.settings_backup_btn_replace), color = MaterialTheme.colorScheme.error)
                    }
                }
            },
            dismissButton = {
                TextButton(onClick = { vm.resetBackupState() }) { Text(stringResource(de.smartzone.pocketclaude.R.string.action_cancel)) }
            },
        )
    }

    val success = state as? SettingsViewModel.BackupState.ImportSuccess
    if (success != null) {
        AlertDialog(
            onDismissRequest = { vm.resetBackupState() },
            title = { Text(stringResource(de.smartzone.pocketclaude.R.string.settings_backup_import_success_title)) },
            text = {
                Column {
                    val r = success.response
                    Text(
                        if (r.mode == "replace")
                            stringResource(de.smartzone.pocketclaude.R.string.settings_backup_replace_result, r.conversationsAdded, r.messagesImported)
                        else
                            stringResource(de.smartzone.pocketclaude.R.string.settings_backup_merge_result, r.conversationsAdded, r.conversationsSkipped),
                        style = MaterialTheme.typography.bodyMedium,
                    )
                    if (r.restartRecommended) {
                        Spacer(Modifier.height(8.dp))
                        Text(
                            stringResource(de.smartzone.pocketclaude.R.string.settings_backup_restart_recommended),
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.error,
                        )
                    }
                }
            },
            confirmButton = {
                TextButton(onClick = { vm.resetBackupState() }) { Text(stringResource(de.smartzone.pocketclaude.R.string.action_ok)) }
            },
        )
    }

    val failure = state as? SettingsViewModel.BackupState.Failure
    if (failure != null) {
        AlertDialog(
            onDismissRequest = { vm.resetBackupState() },
            title = { Text(stringResource(de.smartzone.pocketclaude.R.string.settings_backup_error_title)) },
            text = { Text(failure.reason, style = MaterialTheme.typography.bodyMedium) },
            confirmButton = {
                TextButton(onClick = { vm.resetBackupState() }) { Text(stringResource(de.smartzone.pocketclaude.R.string.action_ok)) }
            },
        )
    }

    // Password-Prompt beim Export — User kann PW eingeben oder leer lassen
    if (state is SettingsViewModel.BackupState.AwaitingExportPassword) {
        var pw by remember { mutableStateOf("") }
        var showPw by remember { mutableStateOf(false) }
        AlertDialog(
            onDismissRequest = { vm.resetBackupState() },
            title = { Text(stringResource(de.smartzone.pocketclaude.R.string.settings_backup_encrypt_title)) },
            text = {
                Column {
                    Text(
                        stringResource(de.smartzone.pocketclaude.R.string.settings_backup_encrypt_body),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Spacer(Modifier.height(12.dp))
                    OutlinedTextField(
                        value = pw,
                        onValueChange = { pw = it },
                        label = { Text(stringResource(de.smartzone.pocketclaude.R.string.settings_backup_password_label_optional)) },
                        singleLine = true,
                        visualTransformation = if (showPw) VisualTransformation.None
                                               else PasswordVisualTransformation(),
                        trailingIcon = {
                            IconButton(onClick = { showPw = !showPw }) {
                                Icon(
                                    if (showPw) Icons.Filled.VisibilityOff
                                    else Icons.Filled.Visibility,
                                    contentDescription = if (showPw) stringResource(de.smartzone.pocketclaude.R.string.settings_backup_password_hide)
                                                         else stringResource(de.smartzone.pocketclaude.R.string.settings_backup_password_show),
                                )
                            }
                        },
                        modifier = Modifier.fillMaxWidth(),
                        shape = RoundedCornerShape(12.dp),
                    )
                }
            },
            confirmButton = {
                TextButton(onClick = { vm.runExport(pw) }) {
                    Text(if (pw.isNotBlank()) stringResource(de.smartzone.pocketclaude.R.string.settings_backup_encrypted_export) else stringResource(de.smartzone.pocketclaude.R.string.settings_backup_export_button))
                }
            },
            dismissButton = {
                TextButton(onClick = { vm.resetBackupState() }) { Text(stringResource(de.smartzone.pocketclaude.R.string.action_cancel)) }
            },
        )
    }

    // Password-Prompt beim Import (Backup ist verschlüsselt)
    val pwPrompt = state as? SettingsViewModel.BackupState.AwaitingImportPassword
    if (pwPrompt != null) {
        var pw by remember { mutableStateOf("") }
        var showPw by remember { mutableStateOf(false) }
        AlertDialog(
            onDismissRequest = { vm.resetBackupState() },
            title = { Text(stringResource(de.smartzone.pocketclaude.R.string.settings_backup_encrypted_title)) },
            text = {
                Column {
                    Text(
                        if (pwPrompt.previousAttemptFailed)
                            stringResource(de.smartzone.pocketclaude.R.string.settings_backup_wrong_password)
                        else
                            stringResource(de.smartzone.pocketclaude.R.string.settings_backup_encrypted_body),
                        style = MaterialTheme.typography.bodyMedium,
                        color = if (pwPrompt.previousAttemptFailed) MaterialTheme.colorScheme.error
                                else MaterialTheme.colorScheme.onSurface,
                    )
                    Spacer(Modifier.height(12.dp))
                    OutlinedTextField(
                        value = pw,
                        onValueChange = { pw = it },
                        label = { Text(stringResource(de.smartzone.pocketclaude.R.string.settings_backup_password_label)) },
                        singleLine = true,
                        visualTransformation = if (showPw) VisualTransformation.None
                                               else PasswordVisualTransformation(),
                        trailingIcon = {
                            IconButton(onClick = { showPw = !showPw }) {
                                Icon(
                                    if (showPw) Icons.Filled.VisibilityOff
                                    else Icons.Filled.Visibility,
                                    contentDescription = null,
                                )
                            }
                        },
                        modifier = Modifier.fillMaxWidth(),
                        shape = RoundedCornerShape(12.dp),
                    )
                }
            },
            confirmButton = {
                TextButton(
                    onClick = { vm.retryImportWithPassword(pw) },
                    enabled = pw.isNotBlank(),
                ) { Text(stringResource(de.smartzone.pocketclaude.R.string.settings_backup_unlock_btn)) }
            },
            dismissButton = {
                TextButton(onClick = { vm.resetBackupState() }) { Text(stringResource(de.smartzone.pocketclaude.R.string.action_cancel)) }
            },
        )
    }
}

/** Schreibt die Backup-Bytes in cacheDir/exports/, holt sich eine
 *  FileProvider-Uri und öffnet den Share-Chooser. */
private fun shareBackupZip(context: android.content.Context, bytes: ByteArray, filename: String) {
    try {
        val dir = java.io.File(context.cacheDir, "exports").apply { mkdirs() }
        val file = java.io.File(dir, filename)
        file.writeBytes(bytes)
        val uri = androidx.core.content.FileProvider.getUriForFile(
            context, "${context.packageName}.fileprovider", file,
        )
        val intent = android.content.Intent(android.content.Intent.ACTION_SEND).apply {
            type = "application/zip"
            putExtra(android.content.Intent.EXTRA_STREAM, uri)
            putExtra(android.content.Intent.EXTRA_SUBJECT, context.getString(de.smartzone.pocketclaude.R.string.settings_backup_share_subject))
            addFlags(android.content.Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        context.startActivity(android.content.Intent.createChooser(intent, context.getString(de.smartzone.pocketclaude.R.string.settings_backup_share_chooser)))
    } catch (e: Exception) {
        android.widget.Toast.makeText(
            context, context.getString(de.smartzone.pocketclaude.R.string.settings_backup_share_failed, e.message ?: ""), android.widget.Toast.LENGTH_LONG,
        ).show()
    }
}

/**
 * First-run sign-in card. Shown when the user has zero profiles. Replaces
 * the "empty profile-list + add-profile-dialog detour" with an inline
 * Server-URL + Username + Password form so the very first interaction is
 * obvious. Profile-label is moved to the bottom and marked optional —
 * users who don't bother get a sensible default ("Server").
 */
@Composable
private fun FirstRunSignInCard(vm: SettingsViewModel) {
    val loginState by vm.loginState.collectAsState()
    val working = loginState is LoginUiState.Working

    var url by remember { mutableStateOf("") }
    var username by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var label by remember { mutableStateOf("") }
    var showPw by remember { mutableStateOf(false) }
    var attempted by remember { mutableStateOf(false) }

    // Clear any stale state on first composition
    LaunchedEffect(Unit) { vm.clearLoginState() }
    DisposableEffect(Unit) { onDispose { vm.clearLoginState() } }

    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surface.copy(alpha = 0.9f),
            contentColor = MaterialTheme.colorScheme.onSurface,
        ),
        shape = RoundedCornerShape(28.dp),
        border = androidx.compose.foundation.BorderStroke(1.dp, PocketTheme.colors.outlineSoft),
    ) {
        Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
            Text(
                stringResource(de.smartzone.pocketclaude.R.string.login_title),
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FW.SemiBold,
            )
            Text(
                stringResource(de.smartzone.pocketclaude.R.string.settings_profile_first_run),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )

            OutlinedTextField(
                value = url,
                onValueChange = { url = it },
                label = { Text(stringResource(de.smartzone.pocketclaude.R.string.server_url)) },
                placeholder = { Text(stringResource(de.smartzone.pocketclaude.R.string.server_url_hint)) },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(18.dp),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
                enabled = !working,
            )
            OutlinedTextField(
                value = username,
                onValueChange = { username = it },
                label = { Text(stringResource(de.smartzone.pocketclaude.R.string.username)) },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(18.dp),
                enabled = !working,
            )
            OutlinedTextField(
                value = password,
                onValueChange = { password = it },
                label = { Text(stringResource(de.smartzone.pocketclaude.R.string.password)) },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(18.dp),
                visualTransformation = if (showPw) VisualTransformation.None else PasswordVisualTransformation(),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                trailingIcon = {
                    IconButton(onClick = { showPw = !showPw }) {
                        Icon(
                            if (showPw) Icons.Filled.VisibilityOff else Icons.Filled.Visibility,
                            contentDescription = stringResource(
                                if (showPw) de.smartzone.pocketclaude.R.string.settings_label_hide
                                else de.smartzone.pocketclaude.R.string.settings_label_show
                            ),
                        )
                    }
                },
                enabled = !working,
            )
            OutlinedTextField(
                value = label,
                onValueChange = { label = it },
                label = { Text(stringResource(de.smartzone.pocketclaude.R.string.settings_label_display_name_optional)) },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(18.dp),
                enabled = !working,
            )

            val state = loginState
            if (attempted && state is LoginUiState.Failure) {
                Text(
                    state.reason,
                    color = MaterialTheme.colorScheme.error,
                    style = MaterialTheme.typography.bodySmall,
                )
            }

            Button(
                onClick = {
                    if (url.isNotBlank() && username.isNotBlank() && password.isNotBlank()) {
                        attempted = true
                        vm.addProfileAndLogin(label, url, username, password)
                    }
                },
                enabled = !working && url.isNotBlank() && username.isNotBlank() && password.isNotBlank(),
                shape = RoundedCornerShape(18.dp),
                modifier = Modifier.fillMaxWidth(),
            ) {
                if (working) {
                    CircularProgressIndicator(
                        modifier = Modifier.size(16.dp),
                        strokeWidth = 2.dp,
                        color = MaterialTheme.colorScheme.onPrimary,
                    )
                    Spacer(Modifier.width(8.dp))
                    Text(stringResource(de.smartzone.pocketclaude.R.string.settings_signing_in))
                } else {
                    Text(stringResource(de.smartzone.pocketclaude.R.string.settings_sign_in_btn))
                }
            }
        }
    }
}

@Composable
private fun ProfilesCard(vm: SettingsViewModel, settings: de.smartzone.pocketclaude.data.AppSettings) {
    var addDialogOpen by remember { mutableStateOf(false) }
    var renameId by remember { mutableStateOf<String?>(null) }
    var renameLabel by remember { mutableStateOf("") }
    var confirmDeleteId by remember { mutableStateOf<String?>(null) }
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        shape = RoundedCornerShape(20.dp),
    ) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            if (settings.profiles.isEmpty()) {
                Text(
                    stringResource(de.smartzone.pocketclaude.R.string.settings_profile_first_run),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(8.dp),
                )
            } else {
                for (p in settings.profiles) {
                    val isActive = p.id == settings.activeProfileId
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clip(RoundedCornerShape(12.dp))
                            .background(
                                if (isActive) MaterialTheme.colorScheme.primary.copy(alpha = 0.10f)
                                else androidx.compose.ui.graphics.Color.Transparent
                            )
                            .clickable { vm.activateProfile(p.id) }
                            .padding(horizontal = 12.dp, vertical = 10.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Icon(
                            if (isActive) Icons.Filled.CheckCircle else Icons.Filled.RadioButtonUnchecked,
                            contentDescription = null,
                            tint = if (isActive) MaterialTheme.colorScheme.primary
                                   else MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.size(20.dp),
                        )
                        Spacer(Modifier.width(12.dp))
                        Column(modifier = Modifier.weight(1f)) {
                            Text(
                                p.label.ifBlank { stringResource(de.smartzone.pocketclaude.R.string.settings_profile_default) },
                                style = MaterialTheme.typography.bodyMedium,
                                fontWeight = if (isActive) FW.SemiBold else FW.Normal,
                            )
                            Text(
                                p.serverUrl.ifBlank { stringResource(de.smartzone.pocketclaude.R.string.settings_profile_no_url) },
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                maxLines = 1,
                            )
                        }
                        IconButton(onClick = { renameId = p.id; renameLabel = p.label }) {
                            Icon(Icons.Filled.DriveFileRenameOutline, contentDescription = stringResource(de.smartzone.pocketclaude.R.string.settings_profile_rename),
                                modifier = Modifier.size(18.dp))
                        }
                        if (settings.profiles.size > 1) {
                            IconButton(onClick = { confirmDeleteId = p.id }) {
                                Icon(Icons.Filled.Delete, contentDescription = stringResource(de.smartzone.pocketclaude.R.string.settings_delete_profile_cd),
                                    tint = MaterialTheme.colorScheme.error,
                                    modifier = Modifier.size(18.dp))
                            }
                        }
                    }
                }
            }
            TextButton(
                onClick = { addDialogOpen = true },
                modifier = Modifier.padding(start = 4.dp),
            ) {
                Icon(Icons.Filled.Add, contentDescription = null, modifier = Modifier.size(18.dp))
                Spacer(Modifier.width(6.dp))
                Text(stringResource(de.smartzone.pocketclaude.R.string.settings_add_profile))
            }
        }
    }

    if (addDialogOpen) {
        AddProfileLoginDialog(
            vm = vm,
            onDismiss = { addDialogOpen = false },
        )
    }

    if (renameId != null) {
        AlertDialog(
            onDismissRequest = { renameId = null },
            title = { Text(stringResource(de.smartzone.pocketclaude.R.string.settings_profile_rename_title)) },
            text = {
                OutlinedTextField(
                    value = renameLabel,
                    onValueChange = { renameLabel = it },
                    singleLine = true,
                    shape = RoundedCornerShape(12.dp),
                )
            },
            confirmButton = {
                TextButton(onClick = {
                    if (renameLabel.isNotBlank()) vm.renameProfile(renameId!!, renameLabel)
                    renameId = null
                }) { Text(stringResource(de.smartzone.pocketclaude.R.string.action_save)) }
            },
            dismissButton = {
                TextButton(onClick = { renameId = null }) { Text(stringResource(de.smartzone.pocketclaude.R.string.action_cancel)) }
            },
        )
    }

    if (confirmDeleteId != null) {
        val p = settings.profiles.firstOrNull { it.id == confirmDeleteId }
        AlertDialog(
            onDismissRequest = { confirmDeleteId = null },
            title = { Text(stringResource(de.smartzone.pocketclaude.R.string.settings_delete_profile_title)) },
            text = {
                Text(stringResource(de.smartzone.pocketclaude.R.string.settings_delete_profile_body, p?.label ?: ""))
            },
            confirmButton = {
                TextButton(onClick = {
                    confirmDeleteId?.let { vm.deleteProfile(it) }
                    confirmDeleteId = null
                }) { Text(stringResource(de.smartzone.pocketclaude.R.string.action_delete), color = MaterialTheme.colorScheme.error) }
            },
            dismissButton = {
                TextButton(onClick = { confirmDeleteId = null }) { Text(stringResource(de.smartzone.pocketclaude.R.string.action_cancel)) }
            },
        )
    }
}


// =====================================================================
// Login + Forced-Password-Change Dialoge
// =====================================================================

@Composable
private fun AddProfileLoginDialog(vm: SettingsViewModel, onDismiss: () -> Unit) {
    var label by remember { mutableStateOf("") }
    var url by remember { mutableStateOf("") }
    var username by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var showPw by remember { mutableStateOf(false) }
    val loginState by vm.loginState.collectAsState()
    val working = loginState is LoginUiState.Working

    // Beim Öffnen: alten State (z.B. ein hängendes Success aus einem
    // früheren Login) wegputzen, damit das LaunchedEffect unten nicht
    // sofort feuert und den Dialog wieder zumacht.
    var loginAttempted by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) { vm.clearLoginState() }

    // Nur auf Success reagieren, NACHDEM der User auf "Anmelden" geklickt hat.
    LaunchedEffect(loginState) {
        if (loginAttempted && loginState is LoginUiState.Success) {
            onDismiss()
            vm.clearLoginState()
        }
    }
    DisposableEffect(Unit) {
        onDispose { vm.clearLoginState() }
    }

    AlertDialog(
        onDismissRequest = { if (!working) onDismiss() },
        title = { Text(stringResource(de.smartzone.pocketclaude.R.string.settings_add_profile_title)) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(
                    value = label,
                    onValueChange = { label = it },
                    label = { Text(stringResource(de.smartzone.pocketclaude.R.string.settings_label_display_name)) },
                    singleLine = true,
                    shape = RoundedCornerShape(12.dp),
                    enabled = !working,
                )
                OutlinedTextField(
                    value = url,
                    onValueChange = { url = it },
                    label = { Text(stringResource(de.smartzone.pocketclaude.R.string.settings_label_server_url)) },
                    placeholder = { Text("https://…trycloudflare.com") },
                    singleLine = true,
                    shape = RoundedCornerShape(12.dp),
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
                    enabled = !working,
                )
                OutlinedTextField(
                    value = username,
                    onValueChange = { username = it },
                    label = { Text(stringResource(de.smartzone.pocketclaude.R.string.settings_label_username)) },
                    singleLine = true,
                    shape = RoundedCornerShape(12.dp),
                    enabled = !working,
                )
                OutlinedTextField(
                    value = password,
                    onValueChange = { password = it },
                    label = { Text(stringResource(de.smartzone.pocketclaude.R.string.settings_label_password)) },
                    singleLine = true,
                    shape = RoundedCornerShape(12.dp),
                    visualTransformation = if (showPw) VisualTransformation.None else PasswordVisualTransformation(),
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                    trailingIcon = {
                        IconButton(onClick = { showPw = !showPw }) {
                            Icon(
                                if (showPw) Icons.Filled.VisibilityOff else Icons.Filled.Visibility,
                                contentDescription = if (showPw) stringResource(de.smartzone.pocketclaude.R.string.settings_label_hide) else stringResource(de.smartzone.pocketclaude.R.string.settings_label_show),
                            )
                        }
                    },
                    enabled = !working,
                )
                val state = loginState
                if (state is LoginUiState.Failure) {
                    Text(
                        state.reason,
                        color = MaterialTheme.colorScheme.error,
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
                if (working) {
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        CircularProgressIndicator(modifier = Modifier.size(14.dp), strokeWidth = 2.dp)
                        Text(stringResource(de.smartzone.pocketclaude.R.string.settings_signing_in), style = MaterialTheme.typography.bodySmall)
                    }
                }
            }
        },
        confirmButton = {
            TextButton(
                enabled = !working,
                onClick = {
                    if (url.isNotBlank() && username.isNotBlank() && password.isNotBlank()) {
                        loginAttempted = true
                        vm.addProfileAndLogin(label, url, username, password)
                    }
                },
            ) { Text(stringResource(de.smartzone.pocketclaude.R.string.settings_sign_in_btn)) }
        },
        dismissButton = {
            TextButton(onClick = { if (!working) onDismiss() }) { Text(stringResource(de.smartzone.pocketclaude.R.string.action_cancel)) }
        },
    )
}

@Composable
private fun ReLoginDialog(vm: SettingsViewModel, onDismiss: () -> Unit) {
    val settings by vm.settings.collectAsState()
    val active = settings.activeProfile
    var password by remember { mutableStateOf("") }
    var showPw by remember { mutableStateOf(false) }
    val loginState by vm.loginState.collectAsState()
    val working = loginState is LoginUiState.Working
    var loginAttempted by remember { mutableStateOf(false) }

    LaunchedEffect(Unit) { vm.clearLoginState() }
    LaunchedEffect(loginState) {
        if (loginAttempted && loginState is LoginUiState.Success) {
            onDismiss()
            vm.clearLoginState()
        }
    }
    DisposableEffect(Unit) { onDispose { vm.clearLoginState() } }

    AlertDialog(
        onDismissRequest = { if (!working) onDismiss() },
        title = { Text(stringResource(de.smartzone.pocketclaude.R.string.settings_relogin_title)) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(
                    stringResource(de.smartzone.pocketclaude.R.string.settings_relogin_subtitle, active?.label ?: "", active?.username ?: "?"),
                    style = MaterialTheme.typography.bodySmall,
                )
                OutlinedTextField(
                    value = password,
                    onValueChange = { password = it },
                    label = { Text(stringResource(de.smartzone.pocketclaude.R.string.settings_label_password)) },
                    singleLine = true,
                    shape = RoundedCornerShape(12.dp),
                    visualTransformation = if (showPw) VisualTransformation.None else PasswordVisualTransformation(),
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                    trailingIcon = {
                        IconButton(onClick = { showPw = !showPw }) {
                            Icon(
                                if (showPw) Icons.Filled.VisibilityOff else Icons.Filled.Visibility,
                                contentDescription = null,
                            )
                        }
                    },
                    enabled = !working,
                )
                val state = loginState
                if (state is LoginUiState.Failure) {
                    Text(state.reason, color = MaterialTheme.colorScheme.error,
                        style = MaterialTheme.typography.bodySmall)
                }
                if (working) {
                    Row(verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        CircularProgressIndicator(modifier = Modifier.size(14.dp), strokeWidth = 2.dp)
                        Text(stringResource(de.smartzone.pocketclaude.R.string.settings_signing_in), style = MaterialTheme.typography.bodySmall)
                    }
                }
            }
        },
        confirmButton = {
            TextButton(
                enabled = !working && password.isNotBlank(),
                onClick = {
                    loginAttempted = true
                    vm.relogActiveProfile(password)
                },
            ) { Text(stringResource(de.smartzone.pocketclaude.R.string.settings_sign_in_btn)) }
        },
        dismissButton = {
            TextButton(onClick = { if (!working) onDismiss() }) { Text(stringResource(de.smartzone.pocketclaude.R.string.action_cancel)) }
        },
    )
}

/**
 * Wird vom SettingsScreen am obersten Level eingehängt. Beobachtet den
 * Login-State und zeigt nach Login mit `must_change_password=true` den
 * Forced-PW-Change-Dialog. Außerdem über `triggerManually` für den
 * normalen "Passwort ändern"-Button.
 */
@Composable
fun ForcedPasswordChangeWatcher(vm: SettingsViewModel) {
    var forcedOpen by remember { mutableStateOf(false) }
    val loginState by vm.loginState.collectAsState()
    LaunchedEffect(loginState) {
        val s = loginState
        if (s is LoginUiState.Success && s.mustChangePassword) {
            forcedOpen = true
        }
    }
    if (forcedOpen) {
        ChangePasswordDialog(
            vm = vm,
            forced = true,
            onDone = { forcedOpen = false; vm.clearLoginState() },
        )
    }
}

@Composable
fun ChangePasswordDialog(vm: SettingsViewModel, forced: Boolean, onDone: () -> Unit) {
    var oldPw by remember { mutableStateOf("") }
    var newPw by remember { mutableStateOf("") }
    var newPw2 by remember { mutableStateOf("") }
    var showPw by remember { mutableStateOf(false) }
    var working by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }

    val errPwMin = stringResource(de.smartzone.pocketclaude.R.string.settings_pw_min_chars)
    val errPwMismatch = stringResource(de.smartzone.pocketclaude.R.string.settings_password_mismatch)
    val errPwEnterOld = stringResource(de.smartzone.pocketclaude.R.string.settings_pw_enter_old)
    AlertDialog(
        onDismissRequest = { if (!forced && !working) onDone() },
        title = { Text(if (forced) stringResource(de.smartzone.pocketclaude.R.string.settings_password_dialog_force_title) else stringResource(de.smartzone.pocketclaude.R.string.settings_password_dialog_change_title)) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                if (forced) {
                    Text(
                        stringResource(de.smartzone.pocketclaude.R.string.settings_pw_change_info_first_login),
                        style = MaterialTheme.typography.bodySmall,
                    )
                } else {
                    OutlinedTextField(
                        value = oldPw,
                        onValueChange = { oldPw = it },
                        label = { Text(stringResource(de.smartzone.pocketclaude.R.string.settings_pw_current_label)) },
                        singleLine = true,
                        shape = RoundedCornerShape(12.dp),
                        visualTransformation = if (showPw) VisualTransformation.None else PasswordVisualTransformation(),
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                        enabled = !working,
                    )
                }
                OutlinedTextField(
                    value = newPw,
                    onValueChange = { newPw = it },
                    label = { Text(stringResource(de.smartzone.pocketclaude.R.string.settings_pw_new_label)) },
                    singleLine = true,
                    shape = RoundedCornerShape(12.dp),
                    visualTransformation = if (showPw) VisualTransformation.None else PasswordVisualTransformation(),
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                    trailingIcon = {
                        IconButton(onClick = { showPw = !showPw }) {
                            Icon(
                                if (showPw) Icons.Filled.VisibilityOff else Icons.Filled.Visibility,
                                contentDescription = null,
                            )
                        }
                    },
                    enabled = !working,
                )
                OutlinedTextField(
                    value = newPw2,
                    onValueChange = { newPw2 = it },
                    label = { Text(stringResource(de.smartzone.pocketclaude.R.string.settings_pw_new_repeat_label)) },
                    singleLine = true,
                    shape = RoundedCornerShape(12.dp),
                    visualTransformation = if (showPw) VisualTransformation.None else PasswordVisualTransformation(),
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                    enabled = !working,
                )
                if (error != null) {
                    Text(error!!, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
                }
                if (working) {
                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        CircularProgressIndicator(modifier = Modifier.size(14.dp), strokeWidth = 2.dp)
                        Text(stringResource(de.smartzone.pocketclaude.R.string.settings_pw_saving), style = MaterialTheme.typography.bodySmall)
                    }
                }
            }
        },
        confirmButton = {
            TextButton(
                enabled = !working,
                onClick = {
                    if (newPw.length < 8) { error = errPwMin; return@TextButton }
                    if (newPw != newPw2) { error = errPwMismatch; return@TextButton }
                    if (!forced && oldPw.isBlank()) { error = errPwEnterOld; return@TextButton }
                    error = null
                    working = true
                    vm.changePassword(
                        oldPassword = if (forced) null else oldPw,
                        newPassword = newPw,
                    ) { result ->
                        working = false
                        result.onSuccess { onDone() }
                            .onFailure { e -> error = e.message ?: e::class.java.simpleName }
                    }
                },
            ) { Text(stringResource(de.smartzone.pocketclaude.R.string.action_save)) }
        },
        dismissButton = {
            if (!forced) TextButton(onClick = { if (!working) onDone() }) { Text(stringResource(de.smartzone.pocketclaude.R.string.action_cancel)) }
        },
    )
}


// =====================================================================
// Settings Export / Import (vollständiges Bundle inkl. API-Keys)
// =====================================================================
@Composable
private fun SettingsTransferSection(vm: SettingsViewModel) {
    val state by vm.settingsTransfer.collectAsState()
    val context = LocalContext.current

    val pickerLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.OpenDocument(),
    ) { uri ->
        if (uri != null) {
            try {
                val bytes = context.contentResolver.openInputStream(uri)?.use { it.readBytes() }
                if (bytes != null && bytes.isNotEmpty()) {
                    vm.importAllSettings(bytes)
                } else {
                    // Picker abgebrochen oder Datei leer
                }
            } catch (e: Exception) {
                // Best-effort — error wandert via VM-State weiter
            }
        }
    }

    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        shape = RoundedCornerShape(20.dp),
    ) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text(
                stringResource(de.smartzone.pocketclaude.R.string.settings_transfer_intro),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )

            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                FilledTonalButton(
                    onClick = { vm.exportAllSettings() },
                    enabled = state !is SettingsViewModel.SettingsTransferState.Exporting &&
                              state !is SettingsViewModel.SettingsTransferState.Importing,
                    shape = RoundedCornerShape(12.dp),
                    modifier = Modifier.weight(1f),
                ) {
                    Icon(Icons.Filled.Upload, contentDescription = null)
                    Spacer(Modifier.width(6.dp))
                    Text(stringResource(de.smartzone.pocketclaude.R.string.settings_transfer_export))
                }
                FilledTonalButton(
                    onClick = {
                        // OpenDocument expects MIME-Type-Array; JSON ist nicht überall
                        // sauber registriert → application/* zulassen.
                        pickerLauncher.launch(arrayOf("application/json", "application/*", "*/*"))
                    },
                    enabled = state !is SettingsViewModel.SettingsTransferState.Exporting &&
                              state !is SettingsViewModel.SettingsTransferState.Importing,
                    shape = RoundedCornerShape(12.dp),
                    modifier = Modifier.weight(1f),
                ) {
                    Icon(Icons.AutoMirrored.Filled.InsertDriveFile, contentDescription = null)
                    Spacer(Modifier.width(6.dp))
                    Text(stringResource(de.smartzone.pocketclaude.R.string.settings_transfer_import))
                }
            }

            // State-Anzeige
            when (val s = state) {
                SettingsViewModel.SettingsTransferState.Idle -> Unit
                SettingsViewModel.SettingsTransferState.Exporting,
                SettingsViewModel.SettingsTransferState.Importing -> Row(
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    CircularProgressIndicator(strokeWidth = 2.dp, modifier = Modifier.size(16.dp))
                    Spacer(Modifier.width(8.dp))
                    Text(
                        if (s == SettingsViewModel.SettingsTransferState.Exporting)
                            stringResource(de.smartzone.pocketclaude.R.string.settings_transfer_exporting) else stringResource(de.smartzone.pocketclaude.R.string.settings_transfer_importing),
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
                is SettingsViewModel.SettingsTransferState.Exported -> {
                    // Datei sofort sharen — User wählt Ziel (E-Mail, Files, Drive…)
                    LaunchedEffect(s) {
                        shareSettingsJson(context, s.bytes, s.filename)
                    }
                    Text(
                        stringResource(de.smartzone.pocketclaude.R.string.settings_transfer_exported_msg, s.filename, s.bytes.size),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.primary,
                    )
                    TextButton(onClick = vm::resetSettingsTransfer) { Text(stringResource(de.smartzone.pocketclaude.R.string.action_ok)) }
                }
                is SettingsViewModel.SettingsTransferState.ImportSuccess -> {
                    Text(
                        stringResource(de.smartzone.pocketclaude.R.string.settings_transfer_import_success, s.appliedServer, s.ttsKeysImported),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.primary,
                    )
                    TextButton(onClick = vm::resetSettingsTransfer) { Text(stringResource(de.smartzone.pocketclaude.R.string.action_ok)) }
                }
                is SettingsViewModel.SettingsTransferState.Failure -> {
                    Text(
                        s.reason,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.error,
                    )
                    TextButton(onClick = vm::resetSettingsTransfer) { Text(stringResource(de.smartzone.pocketclaude.R.string.action_ok)) }
                }
            }
        }
    }
}

/** Schreibt das Settings-Bundle in die App-Cache + öffnet den Share-Sheet. */
private fun shareSettingsJson(
    context: android.content.Context,
    bytes: ByteArray,
    filename: String,
) {
    val dir = java.io.File(context.cacheDir, "settings-exports").apply { mkdirs() }
    val file = java.io.File(dir, filename)
    file.writeBytes(bytes)
    val uri = androidx.core.content.FileProvider.getUriForFile(
        context, "${context.packageName}.fileprovider", file,
    )
    val send = android.content.Intent(android.content.Intent.ACTION_SEND).apply {
        type = "application/json"
        putExtra(android.content.Intent.EXTRA_STREAM, uri)
        addFlags(android.content.Intent.FLAG_GRANT_READ_URI_PERMISSION)
    }
    context.startActivity(
        android.content.Intent.createChooser(send, context.getString(de.smartzone.pocketclaude.R.string.settings_transfer_share_chooser))
    )
}


// =====================================================================
// Skills-Defaults (User-Level — gilt für alle Chats ohne Override)
// =====================================================================
@Composable
private fun SkillsDefaultsSection(vm: SettingsViewModel) {
    val skills by vm.defaultSkills.collectAsState()
    val busy by vm.skillsBusy.collectAsState()
    val current = skills

    // Diese Sektion wird nur noch innerhalb der ClaudeBehaviorCard aufgerufen
    // und braucht keine eigene Card mehr drumherum — sonst entsteht Card-in-
    // Card und der visuelle Stack wird doppelt. Spacing reicht.
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        if (current == null) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                CircularProgressIndicator(
                    strokeWidth = 2.dp, modifier = Modifier.size(16.dp),
                )
                Spacer(Modifier.width(10.dp))
                Text(
                    stringResource(de.smartzone.pocketclaude.R.string.settings_skills_loading),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        } else {
            SkillToggleRow(
                label = stringResource(de.smartzone.pocketclaude.R.string.chat_skill_web_search_label),
                description = stringResource(de.smartzone.pocketclaude.R.string.settings_skill_websearch_desc),
                enabled = !busy,
                checked = current.webSearch,
                onCheckedChange = {
                    vm.setDefaultSkills(current.copy(webSearch = it))
                },
            )
            SkillToggleRow(
                label = stringResource(de.smartzone.pocketclaude.R.string.chat_skill_web_fetch_label),
                description = stringResource(de.smartzone.pocketclaude.R.string.settings_skill_webfetch_desc),
                enabled = !busy,
                checked = current.webFetch,
                onCheckedChange = {
                    vm.setDefaultSkills(current.copy(webFetch = it))
                },
            )
            SkillToggleRow(
                label = stringResource(de.smartzone.pocketclaude.R.string.settings_skill_code_execution_label),
                description = stringResource(de.smartzone.pocketclaude.R.string.settings_skill_code_execution_desc),
                enabled = !busy,
                checked = current.codeExecution,
                onCheckedChange = {
                    vm.setDefaultSkills(current.copy(codeExecution = it))
                },
            )

            SkillToggleRow(
                label = stringResource(de.smartzone.pocketclaude.R.string.skill_image_generation),
                description = stringResource(de.smartzone.pocketclaude.R.string.settings_image_in_chat_hint),
                enabled = !busy,
                checked = current.imageGeneration,
                onCheckedChange = {
                    vm.setDefaultSkills(current.copy(imageGeneration = it))
                },
            )
        }
    }
}

/**
 * Zeile mit Label + Beschreibung links und Switch rechts. Wird sowohl in den
 * Settings-Defaults als auch im Per-Chat-Override-Dialog verwendet — deshalb
 * `internal` und nicht private.
 */
@Composable
internal fun SkillToggleRow(
    label: String,
    description: String,
    checked: Boolean,
    enabled: Boolean = true,
    onCheckedChange: (Boolean) -> Unit,
) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 6.dp),
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(label, style = MaterialTheme.typography.titleSmall)
            Text(
                description,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        Switch(
            checked = checked,
            onCheckedChange = onCheckedChange,
            enabled = enabled,
        )
    }
}


// =====================================================================
// TTS Gemini-API-Key-Pool (Multi-Key + Rate-Limiter im Server)
// =====================================================================
@Composable
private fun TtsGeminiApiKeyField(
    vm: SettingsViewModel,
    ttsStatus: de.smartzone.pocketclaude.data.TtsStatusDto?,
    ttsBusy: Boolean,
) {
    val pool by vm.ttsKeyPool.collectAsState()
    var input by remember { mutableStateOf("") }
    var labelInput by remember { mutableStateOf("") }
    var showKey by remember { mutableStateOf(false) }

    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                stringResource(de.smartzone.pocketclaude.R.string.settings_pool_section_title),
                style = MaterialTheme.typography.labelLarge,
                modifier = Modifier.weight(1f),
            )
            InfoButton(title = stringResource(de.smartzone.pocketclaude.R.string.settings_pool_info_title)) {
                InfoParagraph(
                    stringResource(de.smartzone.pocketclaude.R.string.settings_pool_info_intro)
                )
                InfoBulletParagraph(
                    stringResource(de.smartzone.pocketclaude.R.string.settings_pool_why_label),
                    stringResource(de.smartzone.pocketclaude.R.string.settings_pool_why_body)
                )
                InfoBulletParagraph(
                    stringResource(de.smartzone.pocketclaude.R.string.settings_pool_how_label),
                    stringResource(de.smartzone.pocketclaude.R.string.settings_pool_how_body)
                )
                InfoBulletParagraph(
                    stringResource(de.smartzone.pocketclaude.R.string.settings_pool_dispatcher_label),
                    stringResource(de.smartzone.pocketclaude.R.string.settings_pool_dispatcher_body)
                )
                InfoBulletParagraph(
                    stringResource(de.smartzone.pocketclaude.R.string.settings_pool_alt_label),
                    stringResource(de.smartzone.pocketclaude.R.string.settings_pool_alt_body)
                )
            }
        }

        // Aktuelle Pool-Übersicht
        if (pool.isEmpty()) {
            Text(
                stringResource(de.smartzone.pocketclaude.R.string.settings_pool_empty),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        } else {
            val plural = if (pool.size == 1) stringResource(de.smartzone.pocketclaude.R.string.settings_pool_plural_none) else stringResource(de.smartzone.pocketclaude.R.string.settings_pool_plural_s)
            Text(
                stringResource(de.smartzone.pocketclaude.R.string.settings_pool_status, pool.size, plural, pool.size * 2),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.primary,
            )
            pool.forEach { entry ->
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    modifier = Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(12.dp))
                        .background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.4f))
                        .padding(horizontal = 14.dp, vertical = 8.dp),
                ) {
                    Column(Modifier.weight(1f)) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text(entry.masked, style = MaterialTheme.typography.bodyMedium)
                            Spacer(Modifier.width(8.dp))
                            TierBadge(entry.tierHint)
                        }
                        if (entry.label.isNotBlank()) {
                            Text(
                                entry.label,
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                        if (entry.successCount > 0) {
                            Text(
                                stringResource(de.smartzone.pocketclaude.R.string.settings_pool_call_count, entry.successCount),
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                    }
                    IconButton(
                        onClick = { vm.removeTtsKey(entry.id) },
                        enabled = !ttsBusy,
                    ) {
                        Icon(Icons.Filled.Delete, contentDescription = stringResource(de.smartzone.pocketclaude.R.string.settings_pool_remove_key))
                    }
                }
            }
        }

        Spacer(Modifier.height(6.dp))

        // Neuer-Key-Eingabe
        OutlinedTextField(
            value = input,
            onValueChange = { input = it },
            label = { Text(stringResource(de.smartzone.pocketclaude.R.string.settings_pool_new_key_label)) },
            placeholder = { Text("AIza…") },
            singleLine = true,
            visualTransformation = if (showKey) VisualTransformation.None
                                   else PasswordVisualTransformation(),
            trailingIcon = {
                IconButton(onClick = { showKey = !showKey }) {
                    Icon(
                        imageVector = if (showKey) Icons.Filled.VisibilityOff
                                      else Icons.Filled.Visibility,
                        contentDescription = if (showKey) stringResource(de.smartzone.pocketclaude.R.string.settings_label_hide) else stringResource(de.smartzone.pocketclaude.R.string.settings_label_show),
                    )
                }
            },
            modifier = Modifier.fillMaxWidth(),
            shape = RoundedCornerShape(12.dp),
        )
        OutlinedTextField(
            value = labelInput,
            onValueChange = { labelInput = it },
            label = { Text(stringResource(de.smartzone.pocketclaude.R.string.settings_pool_label_label)) },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
            shape = RoundedCornerShape(12.dp),
        )
        FilledTonalButton(
            onClick = {
                if (input.isNotBlank()) {
                    vm.addTtsKey(input.trim(), labelInput.trim())
                    input = ""
                    labelInput = ""
                }
            },
            enabled = !ttsBusy && input.isNotBlank(),
            shape = RoundedCornerShape(12.dp),
            modifier = Modifier.fillMaxWidth(),
        ) {
            if (ttsBusy) {
                CircularProgressIndicator(modifier = Modifier.size(16.dp), strokeWidth = 2.dp)
                Spacer(Modifier.width(8.dp))
            }
            Icon(Icons.Filled.Add, contentDescription = null)
            Spacer(Modifier.width(8.dp))
            Text(stringResource(de.smartzone.pocketclaude.R.string.settings_pool_add_btn))
        }
    }
}


// =====================================================================
// Bilder: nur noch Aufloesung und Seitenverhaeltnis.
//
// Bis August 2026 stand hier zusaetzlich ein Feld fuer den Google-API-Key und
// eine Modellwahl. Beides ist entfallen: die Bilder entstehen jetzt ueber das
// Modell-Gateway und damit ueber die dort eingeloggten Konten. Das kostet
// nichts pro Bild, und welches Bildmodell es gibt, sagt das Gateway.
// =====================================================================
@Composable
private fun ImageGenSection(vm: SettingsViewModel) {
    val cfg by vm.imageConfig.collectAsState()

    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        shape = RoundedCornerShape(20.dp),
    ) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text(
                stringResource(de.smartzone.pocketclaude.R.string.settings_image_intro),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            // Standardwerte für erzeugte Bilder. Gelten auch für Bilder, die
            // ein Modell mitten im Chat erzeugt.
            ImageDefaultsRow(
                cfg = cfg,
                onSetSize = { vm.setImageDefaults(size = it) },
                onSetAspect = { vm.setImageDefaults(aspectRatio = it) },
                onSetProvider = { vm.setImageDefaults(provider = it) },
            )

            if (cfg == null) {
                Text(
                    stringResource(de.smartzone.pocketclaude.R.string.settings_image_loading_status),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }

            Text(
                stringResource(de.smartzone.pocketclaude.R.string.settings_image_help_text),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

/**
 * Voice-Input-Section: Groq-API-Key + Sprach-Override + Translate-Logik
 * für nicht-gebundelte Sprachen. Layout:
 *   1. Key-Block (paste/save/remove, Status)
 *   2. Sprach-Wahl (Auto / Override-Dropdown / Custom-Locale)
 *   3. Translate-Status + Prompt-Preview
 */
@Composable
private fun VoiceSection(vm: SettingsViewModel) {
    val cfg by vm.voiceConfig.collectAsState()
    val busy by vm.voiceKeyBusy.collectAsState()
    val msg by vm.voiceKeyMessage.collectAsState()
    val translateStatus by vm.translateStatus.collectAsState()
    val translateMsg by vm.translateMessage.collectAsState()
    var apiKey by remember { mutableStateOf("") }
    var showKey by remember { mutableStateOf(false) }

    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        shape = RoundedCornerShape(20.dp),
    ) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text(
                stringResource(de.smartzone.pocketclaude.R.string.settings_voice_intro),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            cfg?.let { c ->
                if (c.configured) {
                    Row(verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        Icon(Icons.Filled.CheckCircle, contentDescription = null,
                            tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(16.dp))
                        Text(
                            stringResource(
                                de.smartzone.pocketclaude.R.string.settings_voice_configured,
                                c.apiKeyMasked ?: "", c.model,
                            ),
                            style = MaterialTheme.typography.bodySmall,
                        )
                    }
                } else {
                    Text(stringResource(de.smartzone.pocketclaude.R.string.settings_voice_no_key),
                         style = MaterialTheme.typography.bodySmall,
                         color = MaterialTheme.colorScheme.error)
                }
            } ?: Text(stringResource(de.smartzone.pocketclaude.R.string.settings_voice_loading_status),
                      style = MaterialTheme.typography.bodySmall,
                      color = MaterialTheme.colorScheme.onSurfaceVariant)

            OutlinedTextField(
                value = apiKey,
                onValueChange = { apiKey = it },
                modifier = Modifier.fillMaxWidth(),
                label = { Text(stringResource(de.smartzone.pocketclaude.R.string.settings_voice_new_api_key)) },
                placeholder = { Text("gsk_…") },
                singleLine = true,
                visualTransformation = if (showKey) VisualTransformation.None else PasswordVisualTransformation(),
                trailingIcon = {
                    IconButton(onClick = { showKey = !showKey }) {
                        Icon(if (showKey) Icons.Filled.VisibilityOff else Icons.Filled.Visibility,
                             contentDescription = null)
                    }
                },
                shape = RoundedCornerShape(14.dp),
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                FilledTonalButton(
                    onClick = { vm.setVoiceApiKey(apiKey); apiKey = "" },
                    enabled = !busy && apiKey.isNotBlank(),
                    shape = RoundedCornerShape(12.dp),
                ) { Text(stringResource(de.smartzone.pocketclaude.R.string.settings_voice_save_btn)) }
                TextButton(
                    onClick = { vm.deleteVoiceApiKey() },
                    enabled = !busy && cfg?.configured == true,
                ) {
                    Text(stringResource(de.smartzone.pocketclaude.R.string.settings_voice_remove_btn),
                         color = MaterialTheme.colorScheme.error)
                }
                if (busy) {
                    Spacer(Modifier.width(8.dp))
                    CircularProgressIndicator(strokeWidth = 2.dp, modifier = Modifier.size(16.dp))
                }
            }
            msg?.let { m ->
                Text(m, style = MaterialTheme.typography.bodySmall,
                     color = if (m.startsWith("Fehler") || m.startsWith("Error"))
                                 MaterialTheme.colorScheme.error
                             else MaterialTheme.colorScheme.onSurfaceVariant)
            }
            Text(
                stringResource(de.smartzone.pocketclaude.R.string.settings_voice_help_text),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )

            // ── 2. Sprach-Wahl ──
            cfg?.let { c ->
                HorizontalDivider(modifier = Modifier.padding(vertical = 4.dp))
                VoiceLanguagePicker(
                    cfg = c,
                    translateStatus = translateStatus,
                    translateMsg = translateMsg,
                    onSetAuto = { vm.setVoiceLangAuto() },
                    onSetOverride = { vm.setVoiceLangOverride(it) },
                    onRetranslate = { loc -> vm.translateVoicePrompt(loc, force = true) },
                    onResetCache = { loc -> vm.resetVoicePromptCache(loc) },
                )
            }
        }
    }
}

/** Picker für die Transkriptions-Sprache + Translate-Status + Prompt-Preview. */
@Composable
private fun VoiceLanguagePicker(
    cfg: de.smartzone.pocketclaude.data.VoiceConfigDto,
    translateStatus: SettingsViewModel.TranslateStatus,
    translateMsg: String?,
    onSetAuto: () -> Unit,
    onSetOverride: (String) -> Unit,
    onRetranslate: (String) -> Unit,
    onResetCache: (String) -> Unit,
) {
    val isOverride = cfg.langMode == "override"
    var modeOverride by remember(cfg.langMode) { mutableStateOf(isOverride) }
    var dropdownOpen by remember { mutableStateOf(false) }
    var customMode by remember(cfg.langOverride) {
        mutableStateOf(isOverride && cfg.langOverride !in cfg.bundledLanguages)
    }
    var customLocale by remember(cfg.langOverride) {
        mutableStateOf(if (customMode) (cfg.langOverride ?: "") else "")
    }

    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(
            stringResource(de.smartzone.pocketclaude.R.string.settings_voice_lang_title),
            style = MaterialTheme.typography.titleSmall,
        )
        Text(
            stringResource(de.smartzone.pocketclaude.R.string.settings_voice_lang_hint),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )

        // Toggle Auto vs. Override
        Row(verticalAlignment = Alignment.CenterVertically) {
            RadioButton(
                selected = !modeOverride,
                onClick = {
                    modeOverride = false
                    customMode = false
                    onSetAuto()
                },
            )
            Text(stringResource(de.smartzone.pocketclaude.R.string.settings_voice_lang_auto),
                 style = MaterialTheme.typography.bodyMedium)
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            RadioButton(
                selected = modeOverride,
                onClick = { modeOverride = true },
            )
            Text(stringResource(de.smartzone.pocketclaude.R.string.settings_voice_lang_manual),
                 style = MaterialTheme.typography.bodyMedium)
        }

        if (modeOverride) {
            // Bundled-Dropdown
            val current = cfg.langOverride ?: cfg.currentLang
            Box {
                OutlinedButton(
                    onClick = { dropdownOpen = true },
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(12.dp),
                ) {
                    val displayName = cfg.languageNames[current] ?: current
                    val cached = current in cfg.cachedLanguages
                    val bundled = current in cfg.bundledLanguages
                    val tag = when {
                        bundled -> stringResource(de.smartzone.pocketclaude.R.string.settings_voice_lang_tag_bundled)
                        cached -> stringResource(de.smartzone.pocketclaude.R.string.settings_voice_lang_tag_translated)
                        else -> stringResource(de.smartzone.pocketclaude.R.string.settings_voice_lang_tag_pending)
                    }
                    Text("$displayName ($current) — $tag",
                         style = MaterialTheme.typography.bodyMedium,
                         maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
                DropdownMenu(
                    expanded = dropdownOpen,
                    onDismissRequest = { dropdownOpen = false },
                    modifier = Modifier.heightIn(max = 360.dp),
                ) {
                    cfg.bundledLanguages.sortedBy {
                        cfg.languageNames[it]?.lowercase() ?: it
                    }.forEach { code ->
                        DropdownMenuItem(
                            text = { Text("${cfg.languageNames[code] ?: code} ($code)") },
                            onClick = {
                                dropdownOpen = false
                                customMode = false
                                onSetOverride(code)
                            },
                        )
                    }
                    HorizontalDivider()
                    DropdownMenuItem(
                        text = { Text(stringResource(de.smartzone.pocketclaude.R.string.settings_voice_lang_custom)) },
                        onClick = {
                            dropdownOpen = false
                            customMode = true
                        },
                    )
                }
            }

            if (customMode) {
                Row(verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(
                        value = customLocale,
                        onValueChange = { customLocale = it.lowercase().take(6) },
                        modifier = Modifier.weight(1f),
                        label = { Text(stringResource(de.smartzone.pocketclaude.R.string.settings_voice_lang_custom_label)) },
                        placeholder = { Text("sv, ko, eu, …") },
                        singleLine = true,
                        shape = RoundedCornerShape(12.dp),
                    )
                    FilledTonalButton(
                        onClick = { onSetOverride(customLocale) },
                        enabled = customLocale.length in 2..6,
                        shape = RoundedCornerShape(12.dp),
                    ) { Text(stringResource(de.smartzone.pocketclaude.R.string.settings_voice_lang_apply)) }
                }
            }

            // Translate-Status
            when (translateStatus) {
                SettingsViewModel.TranslateStatus.Running -> Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    CircularProgressIndicator(strokeWidth = 2.dp, modifier = Modifier.size(14.dp))
                    Text(stringResource(de.smartzone.pocketclaude.R.string.settings_voice_translate_running),
                         style = MaterialTheme.typography.bodySmall)
                }
                SettingsViewModel.TranslateStatus.Success -> Text(
                    stringResource(de.smartzone.pocketclaude.R.string.settings_voice_translate_success),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.primary,
                )
                SettingsViewModel.TranslateStatus.Error -> Text(
                    stringResource(de.smartzone.pocketclaude.R.string.settings_voice_translate_error,
                                   translateMsg ?: ""),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error,
                )
                SettingsViewModel.TranslateStatus.Idle -> Unit
            }
        }

        // Prompt-Preview — read-only, monospace-ish, immer sichtbar damit man
        // sieht was Whisper als Bias kriegt
        Surface(
            modifier = Modifier.fillMaxWidth(),
            shape = RoundedCornerShape(10.dp),
            color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.55f),
        ) {
            Column(Modifier.padding(10.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.SpaceBetween,
                    modifier = Modifier.fillMaxWidth()) {
                    Text(
                        stringResource(de.smartzone.pocketclaude.R.string.settings_voice_prompt_preview_label,
                                       cfg.currentLang),
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    val srcLabel = when (cfg.currentPromptSource) {
                        "bundled" -> stringResource(de.smartzone.pocketclaude.R.string.settings_voice_lang_tag_bundled)
                        "cache" -> stringResource(de.smartzone.pocketclaude.R.string.settings_voice_lang_tag_translated)
                        else -> stringResource(de.smartzone.pocketclaude.R.string.settings_voice_lang_tag_fallback)
                    }
                    Text(srcLabel,
                         style = MaterialTheme.typography.labelSmall,
                         color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                Text(cfg.currentPrompt,
                     style = MaterialTheme.typography.bodySmall,
                     fontStyle = androidx.compose.ui.text.font.FontStyle.Italic)
                if (cfg.currentPromptSource == "cache") {
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        TextButton(onClick = { onRetranslate(cfg.currentLang) }) {
                            Text(stringResource(de.smartzone.pocketclaude.R.string.settings_voice_retranslate))
                        }
                        TextButton(onClick = { onResetCache(cfg.currentLang) }) {
                            Text(stringResource(de.smartzone.pocketclaude.R.string.settings_voice_reset_to_default))
                        }
                    }
                }
            }
        }
    }
}

/**
 * Cloud-Billing-Status-Widget: zeigt aktuellen Monats-Spend (Brutto-Schätzung
 * aus dem Cloud-TTS-Counter × Voice-Preis), den Budget-Hard-Cap und den
 * Restwert des AI-Pro-Credits.
 *
 * Wichtig: der Brutto-Spend ist eine SCHÄTZUNG, kein Live-Wert aus der
 * Cloud-Console. Google's Public-Billing-API liefert den echten Spend nicht
 * ohne BigQuery-Export. Für die UI-Anzeige „komme ich noch im Credit aus"
 * reicht die Schätzung allemal.
 */
@Composable
private fun CloudBillingWidget(vm: SettingsViewModel) {
    val billing by vm.billingStatus.collectAsState()
    val busy by vm.billingBusy.collectAsState()

    // Beim Composable-Mount einmal laden falls noch nicht da.
    LaunchedEffect(Unit) {
        if (vm.billingStatus.value == null) vm.refreshBillingStatus()
    }

    Surface(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(14.dp),
        color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.4f),
        tonalElevation = 0.dp,
    ) {
        Column(
            modifier = Modifier.padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    stringResource(de.smartzone.pocketclaude.R.string.settings_billing_widget_title),
                    style = MaterialTheme.typography.titleSmall,
                    modifier = Modifier.weight(1f),
                )
                InfoButton(title = stringResource(de.smartzone.pocketclaude.R.string.settings_billing_info_widget_title)) {
                    InfoParagraph(
                        stringResource(de.smartzone.pocketclaude.R.string.settings_billing_info_widget_para1)
                    )
                    InfoParagraph(
                        stringResource(de.smartzone.pocketclaude.R.string.settings_billing_info_widget_para2)
                    )
                    InfoParagraph(
                        stringResource(de.smartzone.pocketclaude.R.string.settings_billing_info_widget_para3)
                    )
                }
                if (busy) {
                    CircularProgressIndicator(
                        strokeWidth = 2.dp,
                        modifier = Modifier.size(16.dp),
                    )
                } else {
                    IconButton(onClick = { vm.refreshBillingStatus() }) {
                        Icon(Icons.Filled.Refresh, contentDescription = stringResource(de.smartzone.pocketclaude.R.string.settings_billing_refresh_cd))
                    }
                }
            }

            val b = billing
            when {
                b == null -> {
                    Text(
                        stringResource(de.smartzone.pocketclaude.R.string.settings_billing_loading),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                !b.available -> {
                    Text(
                        b.error ?: stringResource(de.smartzone.pocketclaude.R.string.settings_billing_unavailable_text),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                else -> {
                    val currency = b.currencyCode
                    val symbol = if (currency == "EUR") "€" else currency
                    fun fmt(v: Double): String = "%.2f %s".format(v, symbol)
                    val budgetTotal = b.budgetAmount ?: 0.0
                    val creditOrig = b.creditOriginal ?: 0.0
                    val spendNet = b.spendThisMonth.coerceAtLeast(0.0)
                    val creditUsed = minOf(spendNet, creditOrig)
                    val realCost = b.estimatedRealCost.coerceAtLeast(0.0)

                    // Hauptzeile: Brutto-Spend, prominent
                    Text(
                        stringResource(de.smartzone.pocketclaude.R.string.settings_billing_this_month_gross, fmt(spendNet)),
                        style = MaterialTheme.typography.bodyLarge,
                    )

                    // Info-Hinweis (z.B. „Budget-API nicht aktiviert") — subtil,
                    // kein Error, nur kleiner Hinweis-Text in Akzent-Farbe.
                    b.warning?.takeIf { it.isNotBlank() }?.let { w ->
                        Text(
                            "ℹ $w",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }

                    // Credit-Progress: wieviel vom AI-Pro-Credit ist schon „verbraucht"
                    if (creditOrig > 0.0) {
                        val pct = (creditUsed / creditOrig).coerceIn(0.0, 1.0).toFloat()
                        Column {
                            LinearProgressIndicator(
                                progress = { pct },
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .height(6.dp)
                                    .clip(RoundedCornerShape(3.dp)),
                                color = MaterialTheme.colorScheme.primary,
                                trackColor = MaterialTheme.colorScheme.surfaceVariant,
                            )
                            Spacer(Modifier.height(4.dp))
                            val creditLeft = (b.creditRemaining ?: creditOrig).coerceAtLeast(0.0)
                            Text(
                                stringResource(de.smartzone.pocketclaude.R.string.settings_billing_credit_remaining, fmt(creditLeft), fmt(creditOrig)),
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                    }

                    // Budget-Info (Hard Cap)
                    if (budgetTotal > 0.0) {
                        Text(
                            stringResource(de.smartzone.pocketclaude.R.string.settings_billing_budget_cap, b.budgetName ?: "Budget", fmt(budgetTotal)),
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }

                    // Real-Cost-Hinweis: wenn über Credit raus → Warnung
                    if (realCost > 0.01) {
                        Text(
                            stringResource(de.smartzone.pocketclaude.R.string.settings_billing_real_cost, fmt(realCost)),
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.error,
                        )
                    } else if (creditOrig > 0.0) {
                        Text(
                            stringResource(de.smartzone.pocketclaude.R.string.settings_billing_in_credit),
                            style = MaterialTheme.typography.bodySmall,
                            color = de.smartzone.pocketclaude.ui.theme.PocketTheme.colors.success,
                        )
                    }

                    // Footer: Projekt-ID + last_updated für Debugging
                    val proj = b.projectId
                    val updated = b.lastUpdatedAt
                    if (proj != null || updated != null) {
                        val projLine = if (proj != null) stringResource(de.smartzone.pocketclaude.R.string.settings_billing_project_label, proj) else ""
                        val updLine = if (updated != null) stringResource(de.smartzone.pocketclaude.R.string.settings_billing_updated_label, updated.take(16)) else ""
                        Text(
                            buildString {
                                if (projLine.isNotEmpty()) append(projLine)
                                if (projLine.isNotEmpty() && updLine.isNotEmpty()) append(" · ")
                                if (updLine.isNotEmpty()) append(updLine)
                            },
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }
        }
    }
}

/**
 * Globaler Standard-Modell-Picker für alle Modell-Familien.
 * Zeigt die Modelle gruppiert nach ChatModelFamilies.order an.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun DefaultModelPicker(
    models: List<ChatModelOption>,
    selectedKey: String,
    loading: Boolean,
    onSelect: (String) -> Unit,
    onRefresh: () -> Unit,
) {
    var expanded by remember { mutableStateOf(false) }
    val selectedLabel = if (selectedKey.isBlank()) {
        stringResource(R.string.model_auto)
    } else {
        models.firstOrNull { it.key == selectedKey }?.label ?: selectedKey
    }

    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            SubsectionLabel(stringResource(R.string.settings_default_model))
            if (loading) {
                Box(Modifier.size(48.dp), contentAlignment = Alignment.Center) {
                    CircularProgressIndicator(
                        strokeWidth = 2.dp,
                        modifier = Modifier.size(16.dp),
                    )
                }
            } else {
                IconButton(
                    onClick = onRefresh,
                    modifier = Modifier.size(48.dp),
                ) {
                    Icon(
                        Icons.Filled.Refresh,
                        contentDescription = stringResource(R.string.model_refresh),
                        modifier = Modifier.size(16.dp),
                    )
                }
            }
        }

        ExposedDropdownMenuBox(
            expanded = expanded,
            onExpandedChange = { expanded = !expanded },
            modifier = Modifier.fillMaxWidth(),
        ) {
            OutlinedTextField(
                value = selectedLabel,
                onValueChange = {},
                readOnly = true,
                trailingIcon = {
                    ExposedDropdownMenuDefaults.TrailingIcon(expanded = expanded)
                },
                shape = RoundedCornerShape(14.dp),
                modifier = Modifier
                    .fillMaxWidth()
                    .menuAnchor(),
            )
            ExposedDropdownMenu(
                expanded = expanded,
                onDismissRequest = { expanded = false },
            ) {
                DropdownMenuItem(
                    text = { Text(stringResource(R.string.model_auto)) },
                    onClick = {
                        onSelect("")
                        expanded = false
                    },
                )
                ChatModelFamilies.order.forEach { family ->
                    val groupModels = models.filter { it.family == family }
                    if (groupModels.isNotEmpty()) {
                        val familyLabelRes = when (family) {
                            ChatModelFamilies.CLAUDE -> R.string.model_family_claude
                            ChatModelFamilies.GEMINI -> R.string.model_family_gemini
                            ChatModelFamilies.GPT -> R.string.model_family_gpt
                            else -> R.string.model_family_other
                        }
                        Text(
                            text = stringResource(familyLabelRes),
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.padding(horizontal = 16.dp, vertical = 6.dp),
                        )
                        groupModels.forEach { opt ->
                            DropdownMenuItem(
                                text = {
                                    Column {
                                        Text(opt.label)
                                        if (opt.gatewayLabel.isNotBlank()) {
                                            Text(
                                                text = opt.gatewayLabel,
                                                style = MaterialTheme.typography.labelSmall,
                                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                            )
                                        }
                                    }
                                },
                                onClick = {
                                    onSelect(opt.key)
                                    expanded = false
                                },
                            )
                        }
                    }
                }
            }
        }

        Text(
            text = stringResource(R.string.settings_default_model_hint),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

/**
 * Anzeigename eines Bild-Anbieters, uebersetzt statt vom Server uebernommen.
 * Begruendung steht bei der gleichnamigen Funktion im Bilder-Screen.
 */
@Composable
private fun imageProviderLabel(p: ImageProviderDto): String = when (p.id) {
    "both" -> stringResource(R.string.image_provider_both)
    "gemini" -> "Gemini"
    "gpt" -> "GPT"
    else -> p.label
}

/**
 * Standard-Einstellungen für die Bildgenerierung: Größe, Seitenverhältnis und Modell.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun ImageDefaultsRow(
    cfg: ImageConfigDto?,
    onSetSize: (String) -> Unit,
    onSetAspect: (String) -> Unit,
    onSetProvider: (String) -> Unit,
) {
    if (cfg == null) return

    Column(
        verticalArrangement = Arrangement.spacedBy(10.dp),
        modifier = Modifier.fillMaxWidth(),
    ) {
        // Anbieter. Nur zeigen, wenn es hier ueberhaupt etwas zu waehlen gibt:
        // ohne zweites Gateway meldet der Server nur einen einzigen Anbieter.
        if (cfg.providers.size > 1) {
            SubsectionLabel(stringResource(R.string.settings_image_provider_label))
            FlowRow(
                horizontalArrangement = Arrangement.spacedBy(6.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp),
                modifier = Modifier.fillMaxWidth(),
            ) {
                cfg.providers.forEach { item ->
                    FilterChip(
                        selected = cfg.defaults.provider == item.id,
                        onClick = { onSetProvider(item.id) },
                        label = {
                            Text(
                                imageProviderLabel(item),
                                style = MaterialTheme.typography.labelMedium,
                            )
                        },
                        shape = RoundedCornerShape(10.dp),
                        colors = FilterChipDefaults.filterChipColors(
                            selectedContainerColor = MaterialTheme.colorScheme.primary,
                            selectedLabelColor = MaterialTheme.colorScheme.onPrimary,
                        ),
                    )
                }
            }
            Text(
                stringResource(R.string.settings_image_provider_hint),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }

        // 1. Standard-Bildgröße
        SubsectionLabel(stringResource(R.string.settings_image_default_size))
        FlowRow(
            horizontalArrangement = Arrangement.spacedBy(6.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp),
            modifier = Modifier.fillMaxWidth(),
        ) {
            cfg.imageSizes.forEach { item ->
                FilterChip(
                    selected = cfg.defaults.size == item.id,
                    onClick = { onSetSize(item.id) },
                    label = { Text(item.label, style = MaterialTheme.typography.labelMedium) },
                    shape = RoundedCornerShape(10.dp),
                    colors = FilterChipDefaults.filterChipColors(
                        selectedContainerColor = MaterialTheme.colorScheme.primary,
                        selectedLabelColor = MaterialTheme.colorScheme.onPrimary,
                    ),
                )
            }
        }

        // 2. Standard-Seitenverhältnis
        SubsectionLabel(stringResource(R.string.settings_image_default_aspect))
        FlowRow(
            horizontalArrangement = Arrangement.spacedBy(6.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp),
            modifier = Modifier.fillMaxWidth(),
        ) {
            cfg.aspectRatios.forEach { item ->
                FilterChip(
                    selected = cfg.defaults.aspectRatio == item.id,
                    onClick = { onSetAspect(item.id) },
                    label = { Text(item.label, style = MaterialTheme.typography.labelMedium) },
                    shape = RoundedCornerShape(10.dp),
                    colors = FilterChipDefaults.filterChipColors(
                        selectedContainerColor = MaterialTheme.colorScheme.primary,
                        selectedLabelColor = MaterialTheme.colorScheme.onPrimary,
                    ),
                )
            }
        }

        // Ein Modell zur Auswahl gibt es nicht mehr: welches Bildmodell laeuft,
        // sagt das Gateway. Frueher stand hier eine Liste, aus der man auch das
        // teure Pro-Modell waehlen konnte.
    }
}

/**
 * Farbschema-Auswahl. Jede Palette wird als Farbprobe gezeigt statt nur als
 * Name: welche Farbe ein Schema hat, laesst sich nicht sinnvoll lesen, nur
 * ansehen.
 *
 * `dark` sagt, um welche der beiden Varianten es geht. Die Proben zeigen genau
 * diese, auch wenn die App gerade in der anderen laeuft: sonst waehlt man den
 * hellen Look blind, weil man nachts die dunklen Proben sieht.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun PalettePicker(
    selectedId: String,
    dark: Boolean,
    fallback: PocketPalette,
    onSelect: (String) -> Unit,
) {
    val selected = PocketPalette.fromId(selectedId, fallback)

    FlowRow(
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
        modifier = Modifier.fillMaxWidth(),
    ) {
        PocketPalette.entries.forEach { palette ->
            val spec = specFor(palette)
            val scheme = if (dark) spec.darkScheme else spec.lightScheme
            val isSelected = palette == selected

            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                modifier = Modifier
                    .clip(RoundedCornerShape(12.dp))
                    .background(
                        if (isSelected) MaterialTheme.colorScheme.primaryContainer
                        else MaterialTheme.colorScheme.surfaceContainerHigh
                    )
                    .border(
                        width = if (isSelected) 2.dp else 1.dp,
                        color = if (isSelected) MaterialTheme.colorScheme.primary
                                else MaterialTheme.colorScheme.outlineVariant,
                        shape = RoundedCornerShape(12.dp),
                    )
                    .clickable { onSelect(palette.id) }
                    .padding(horizontal = 10.dp, vertical = 8.dp),
            ) {
                // Drei Tupfer: Hintergrund, Primaerfarbe, Akzent. Das reicht,
                // um zwei Schemata auf einen Blick zu unterscheiden.
                Row(horizontalArrangement = Arrangement.spacedBy(2.dp)) {
                    listOf(scheme.background, scheme.primary, scheme.secondary).forEach { c ->
                        Box(
                            modifier = Modifier
                                .size(14.dp)
                                .clip(CircleShape)
                                .background(c)
                                .border(1.dp, MaterialTheme.colorScheme.outlineVariant, CircleShape)
                        )
                    }
                }
                Text(
                    palette.displayName,
                    style = MaterialTheme.typography.labelLarge,
                    color = if (isSelected) MaterialTheme.colorScheme.onPrimaryContainer
                            else MaterialTheme.colorScheme.onSurface,
                )
                if (isSelected) {
                    Icon(
                        Icons.Filled.Check,
                        contentDescription = null,
                        modifier = Modifier.size(16.dp),
                        tint = MaterialTheme.colorScheme.onPrimaryContainer,
                    )
                }
            }
        }
    }
}

/**
 * Ein Anbieter-Block: Standardmodell plus die Denktiefen, die genau dieses
 * Modell kann.
 *
 * Bewusst zusammen und nicht in zwei Listen: die waehlbaren Denktiefen haengen
 * am Modell, nicht am Anbieter. Gemini 3.7 Flash gibt es im Gateway zum Beispiel
 * nur in „hoch", und eine Stufenliste, die trotzdem sechs Knoepfe zeigt, ist
 * schlicht gelogen.
 *
 * Ist die Modell-Liste leer, laeuft das Gateway dieser Familie nicht. Der Block
 * bleibt dann sichtbar, aber gesperrt, statt kommentarlos zu verschwinden.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ProviderDefaultsBlock(
    familyLabel: String,
    models: List<ChatModelOption>,
    selectedKey: String,
    onSelectModel: (String) -> Unit,
    availableEfforts: List<String>,
    selectedEffort: String,
    onSelectEffort: (String) -> Unit,
) {
    var expanded by remember { mutableStateOf(false) }
    val available = models.isNotEmpty()
    val label = when {
        !available -> stringResource(de.smartzone.pocketclaude.R.string.settings_default_model_family_unavailable)
        selectedKey.isBlank() -> stringResource(de.smartzone.pocketclaude.R.string.model_auto)
        else -> models.firstOrNull { it.key == selectedKey }?.label ?: selectedKey
    }

    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text(
            familyLabel,
            style = MaterialTheme.typography.labelLarge,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        ExposedDropdownMenuBox(
            expanded = expanded && available,
            onExpandedChange = { if (available) expanded = !expanded },
            modifier = Modifier.fillMaxWidth(),
        ) {
            OutlinedTextField(
                value = label,
                onValueChange = {},
                readOnly = true,
                enabled = available,
                trailingIcon = {
                    ExposedDropdownMenuDefaults.TrailingIcon(expanded = expanded && available)
                },
                shape = RoundedCornerShape(14.dp),
                modifier = Modifier
                    .fillMaxWidth()
                    .menuAnchor(),
            )
            ExposedDropdownMenu(
                expanded = expanded && available,
                onDismissRequest = { expanded = false },
            ) {
                models.forEach { opt ->
                    DropdownMenuItem(
                        text = {
                            Column {
                                Text(opt.label)
                                if (opt.gatewayLabel.isNotBlank()) {
                                    Text(
                                        text = opt.gatewayLabel,
                                        style = MaterialTheme.typography.labelSmall,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    )
                                }
                            }
                        },
                        onClick = {
                            onSelectModel(opt.key)
                            expanded = false
                        },
                    )
                }
            }
        }

        when {
            !available -> Unit
            availableEfforts.isEmpty() -> Text(
                stringResource(de.smartzone.pocketclaude.R.string.effort_not_supported),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            else -> EffortChips(
                available = availableEfforts,
                selected = selectedEffort,
                onSelect = onSelectEffort,
            )
        }
    }
}
