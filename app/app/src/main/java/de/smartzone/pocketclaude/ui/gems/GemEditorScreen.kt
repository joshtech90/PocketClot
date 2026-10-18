package de.smartzone.pocketclaude.ui.gems

import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.consumeWindowInsets
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.ExposedDropdownMenuDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import de.smartzone.pocketclaude.R
import de.smartzone.pocketclaude.data.ClaudeModels
import de.smartzone.pocketclaude.data.EFFORT_LEVELS
import de.smartzone.pocketclaude.ui.components.PocketBackdrop
import de.smartzone.pocketclaude.ui.components.PocketIconButton
import de.smartzone.pocketclaude.ui.components.PocketScreenTitle
import de.smartzone.pocketclaude.ui.theme.PocketTheme
import de.smartzone.pocketclaude.ui.theme.PocketIconSize
import de.smartzone.pocketclaude.ui.theme.PocketIcons

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun GemEditorScreen(
    vm: GemsViewModel,
    gemId: String?,
    dupFrom: String? = null,
    onBack: () -> Unit,
) {
    LaunchedEffect(gemId, dupFrom) {
        if (dupFrom != null) vm.loadForDuplicate(dupFrom) else vm.loadForEdit(gemId)
    }
    val st by vm.editor.collectAsState()
    val ctx = LocalContext.current

    val filePicker = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.OpenDocument(),
    ) { uri: Uri? ->
        if (uri != null) {
            val name = queryDisplayName(ctx, uri) ?: "Datei"
            vm.addPendingFile(uri, name)
        }
    }

    PocketBackdrop(Modifier.fillMaxSize()) {
    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    PocketScreenTitle(
                        eyebrow = stringResource(R.string.app_name),
                        title = stringResource(
                            if (gemId == null) R.string.gem_editor_title_new
                            else R.string.gem_editor_title_edit
                        ),
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
                    if (st.saving) {
                        CircularProgressIndicator(
                            strokeWidth = 2.dp,
                            modifier = Modifier.size(20.dp).padding(end = 12.dp),
                        )
                    } else {
                        Button(
                            onClick = { vm.save(onBack) },
                            enabled = st.canSave,
                            modifier = Modifier.padding(end = 8.dp),
                        ) {
                            Text(stringResource(R.string.gem_save))
                        }
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = Color.Transparent),
            )
        },
        containerColor = Color.Transparent,
        contentColor = MaterialTheme.colorScheme.onBackground,
    ) { pad ->
        if (st.loading) {
            Box(Modifier.fillMaxSize().padding(pad), contentAlignment = Alignment.Center) {
                CircularProgressIndicator()
            }
            return@Scaffold
        }
        Column(
            Modifier
                .fillMaxSize()
                .padding(pad)
                .consumeWindowInsets(pad)
                .imePadding()
                .verticalScroll(rememberScrollState())
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            if (st.isBuiltin) {
                Text(
                    stringResource(R.string.gem_builtin_readonly),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error,
                )
            }

            // Name + Emoji
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                OutlinedTextField(
                    value = st.emoji,
                    onValueChange = vm::setEmoji,
                    label = { Text(stringResource(R.string.gem_field_emoji)) },
                    singleLine = true,
                    enabled = !st.isBuiltin,
                    modifier = Modifier.width(96.dp),
                    shape = MaterialTheme.shapes.small,
                )
                OutlinedTextField(
                    value = st.name,
                    onValueChange = vm::setName,
                    label = { Text(stringResource(R.string.gem_field_name)) },
                    singleLine = true,
                    enabled = !st.isBuiltin,
                    modifier = Modifier.weight(1f),
                    shape = MaterialTheme.shapes.small,
                )
            }

            OutlinedTextField(
                value = st.description,
                onValueChange = vm::setDescription,
                label = { Text(stringResource(R.string.gem_field_description)) },
                enabled = !st.isBuiltin,
                modifier = Modifier.fillMaxWidth(),
                shape = MaterialTheme.shapes.small,
            )

            OutlinedTextField(
                value = st.instructions,
                onValueChange = vm::setInstructions,
                label = { Text(stringResource(R.string.gem_field_instructions)) },
                placeholder = { Text(stringResource(R.string.gem_field_instructions_hint)) },
                enabled = !st.isBuiltin,
                modifier = Modifier.fillMaxWidth().heightIn(min = 140.dp),
                shape = MaterialTheme.shapes.small,
            )

            // Conversation starters
            EditorSection(stringResource(R.string.gem_starters_label), stringResource(R.string.gem_starters_hint)) {
                st.starters.forEachIndexed { idx, value ->
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        OutlinedTextField(
                            value = value,
                            onValueChange = { vm.updateStarter(idx, it) },
                            singleLine = true,
                            enabled = !st.isBuiltin,
                            modifier = Modifier.weight(1f),
                            shape = MaterialTheme.shapes.small,
                        )
                        IconButton(onClick = { vm.removeStarter(idx) }, enabled = !st.isBuiltin) {
                            Icon(PocketIcons.Close, contentDescription = stringResource(R.string.chat_remove))
                        }
                    }
                }
                if (!st.isBuiltin) {
                    OutlinedButton(onClick = { vm.addStarter() }) {
                        Icon(PocketIcons.Add, contentDescription = null, modifier = Modifier.size(PocketIconSize.Small))
                        Spacer(Modifier.width(6.dp))
                        Text(stringResource(R.string.gem_add_starter))
                    }
                }
            }

            // Model picker
            LabeledDropdown(
                label = stringResource(R.string.gem_model_label),
                currentLabel = ClaudeModels.labelFor(st.model)
                    ?: stringResource(R.string.gem_model_global_default),
                enabled = !st.isBuiltin,
                entries = buildList {
                    add(null to stringResource(R.string.gem_model_global_default))
                    ClaudeModels.all.forEach { add(it.id to it.label) }
                },
                onSelect = vm::setModel,
            )

            // Effort picker
            LabeledDropdown(
                label = stringResource(R.string.gem_effort_label),
                currentLabel = st.effort?.replaceFirstChar { it.uppercase() }
                    ?: stringResource(R.string.gem_effort_chat_default),
                enabled = !st.isBuiltin,
                entries = buildList {
                    add(null to stringResource(R.string.gem_effort_chat_default))
                    EFFORT_LEVELS.forEach { add(it to it.replaceFirstChar { c -> c.uppercase() }) }
                },
                onSelect = vm::setEffort,
            )

            // Skills
            EditorSection(stringResource(R.string.gem_skills_label), null) {
                SkillSwitch(stringResource(R.string.gem_skill_web_search), st.skills.webSearch, !st.isBuiltin, vm::setWebSearch)
                SkillSwitch(stringResource(R.string.gem_skill_web_fetch), st.skills.webFetch, !st.isBuiltin, vm::setWebFetch)
                SkillSwitch(stringResource(R.string.gem_skill_code), st.skills.codeExecution, !st.isBuiltin, vm::setCodeExecution)
            }

            // Knowledge files
            EditorSection(stringResource(R.string.gem_knowledge_label), stringResource(R.string.gem_knowledge_hint)) {
                st.files.forEach { f ->
                    FileRow(f.filename, enabled = !st.isBuiltin) { vm.removeSavedFile(f.id) }
                }
                st.pending.forEach { p ->
                    FileRow(p.filename, enabled = true) { vm.removePendingFile(p.uri) }
                }
                if (!st.isBuiltin) {
                    OutlinedButton(onClick = { filePicker.launch(arrayOf("*/*")) }) {
                        Icon(PocketIcons.Document, contentDescription = null, modifier = Modifier.size(PocketIconSize.Small))
                        Spacer(Modifier.width(6.dp))
                        Text(stringResource(R.string.gem_add_file))
                    }
                }
            }

            st.error?.let {
                Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error)
            }
            Spacer(Modifier.height(24.dp))
        }
    }
    }
}

@Composable
private fun EditorSection(title: String, hint: String?, content: @Composable () -> Unit) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surface.copy(alpha = 0.88f),
            contentColor = MaterialTheme.colorScheme.onSurface,
        ),
        shape = RoundedCornerShape(26.dp),
        border = androidx.compose.foundation.BorderStroke(1.dp, PocketTheme.colors.outlineSoft),
    ) {
        Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(11.dp)) {
            Text(title, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
            if (hint != null) {
                Text(hint, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            content()
        }
    }
}

@Composable
private fun SkillSwitch(label: String, checked: Boolean, enabled: Boolean, onChange: (Boolean) -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(label, style = MaterialTheme.typography.bodyMedium)
        Switch(checked = checked, onCheckedChange = onChange, enabled = enabled)
    }
}

@Composable
private fun FileRow(name: String, enabled: Boolean, onRemove: () -> Unit) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Icon(
            PocketIcons.Document,
            contentDescription = null,
            modifier = Modifier.size(PocketIconSize.Small),
            tint = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.width(8.dp))
        Text(name, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
        if (enabled) {
            IconButton(onClick = onRemove, modifier = Modifier.size(48.dp)) {
                Icon(PocketIcons.Close, contentDescription = stringResource(R.string.chat_remove), modifier = Modifier.size(PocketIconSize.Regular))
            }
        }
    }
    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun LabeledDropdown(
    label: String,
    currentLabel: String,
    enabled: Boolean,
    entries: List<Pair<String?, String>>,
    onSelect: (String?) -> Unit,
) {
    var expanded by remember { mutableStateOf(false) }
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text(label, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
        ExposedDropdownMenuBox(
            expanded = expanded && enabled,
            onExpandedChange = { if (enabled) expanded = it },
        ) {
            OutlinedTextField(
                value = currentLabel,
                onValueChange = {},
                readOnly = true,
                enabled = enabled,
                modifier = Modifier.fillMaxWidth().menuAnchor(),
                trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded = expanded) },
                shape = MaterialTheme.shapes.small,
            )
            DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
                entries.forEach { (value, text) ->
                    DropdownMenuItem(
                        text = { Text(text) },
                        onClick = {
                            expanded = false
                            onSelect(value)
                        },
                    )
                }
            }
        }
    }
}

private fun queryDisplayName(context: Context, uri: Uri): String? {
    return try {
        context.contentResolver.query(uri, null, null, null, null)?.use { c ->
            val idx = c.getColumnIndex(OpenableColumns.DISPLAY_NAME)
            if (idx >= 0 && c.moveToFirst()) c.getString(idx) else null
        }
    } catch (_: Exception) {
        null
    }
}
