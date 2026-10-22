// =====================================================================
// Gems (eigene Assistenten) wie ChatGPT-GPTs und Gemini-Gems:
// Seitenleiste, Begruessung im leeren Chat, Liste in den Einstellungen, Editor.
// =====================================================================

// Familien statt Versionsnummern, wie SELECTABLE_MODELS in claude_engine.py:
// der Server loest `opus` immer auf die neueste Generation auf.
const CLAUDE_MODELS = [
  { id: 'opus',   label: 'Opus (neueste Generation)' },
  { id: 'fable',  label: 'Fable (neueste Generation)' },
  { id: 'sonnet', label: 'Sonnet (neueste Generation)' },
  { id: 'haiku',  label: 'Haiku (neueste Generation)' },
];
window.PC_CLAUDE_MODELS = CLAUDE_MODELS;

// Global, weil openChat()/renderMessages() in app.js sie brauchen.
function gemFetch(id) { return api('GET', '/me/gems/' + encodeURIComponent(id)); }

/** Leerer Gem-Chat: Symbol, Name, Beschreibung und antippbare Starter. */
function gemWelcomeEl(gem) {
  const wrap = document.createElement('div');
  wrap.className = 'gem-welcome';
  const emoji = document.createElement('div');
  emoji.className = 'gem-welcome-emoji';
  emoji.textContent = gem.emoji || '🤖';
  const h = document.createElement('h3');
  h.textContent = gem.name || '';
  wrap.append(emoji, h);
  if (gem.description) {
    const p = document.createElement('p');
    p.textContent = gem.description;
    wrap.appendChild(p);
  }
  const starters = gem.conversation_starters || [];
  if (starters.length) {
    const row = document.createElement('div');
    row.className = 'gem-starter-chips';
    for (const s of starters) {
      const chip = document.createElement('button');
      chip.type = 'button';
      chip.className = 'gem-starter-chip';
      chip.textContent = s;
      chip.addEventListener('click', () => { els.input.value = s; sendMessage(s); });
      row.appendChild(chip);
    }
    wrap.appendChild(row);
  }
  return wrap;
}

(function initGems() {
  async function loadGems() {
    try { state.gems = await api('GET', '/me/gems'); }
    catch { state.gems = []; }
    renderGemsSidebar();
    renderGemsSettingsList();
  }

  function renderGemsSidebar() {
    const nav = $('gems-nav');
    if (!nav) return;
    nav.innerHTML = '';
    if (!state.gems.length) {
      const b = document.createElement('div');
      b.className = 'chat-item gem-item';
      b.innerHTML = `<span class="gem-emoji">✨</span><span class="chat-item-title" style="color:var(--text-muted)">${escapeHtml(t('gems_empty_sidebar'))}</span>`;
      b.addEventListener('click', () => openGemEditor(null, {}));
      nav.appendChild(b);
      return;
    }
    for (const g of state.gems) {
      const item = document.createElement('div');
      item.className = 'chat-item gem-item';
      item.innerHTML = `<span class="gem-emoji">${escapeHtml(g.emoji || '🤖')}</span><span class="chat-item-title">${escapeHtml(g.name)}</span>`;
      item.addEventListener('click', () => newChat({ gemId: g.id, gem: g }));
      nav.appendChild(item);
    }
  }

  function renderGemsSettingsList() {
    const list = $('gems-list');
    if (!list) return;
    list.innerHTML = '';
    if (!state.gems.length) {
      const p = document.createElement('p');
      p.className = 'set-hint';
      p.textContent = t('gems_empty');
      list.appendChild(p);
      return;
    }
    for (const g of state.gems) {
      const row = document.createElement('div');
      row.className = 'gem-row';
      const main = document.createElement('div');
      main.className = 'gem-row-main';
      const badge = g.is_builtin ? ` <em class="gem-badge">${escapeHtml(t('gem_builtin_badge'))}</em>` : '';
      main.innerHTML = `<span class="gem-emoji">${escapeHtml(g.emoji || '🤖')}</span>
        <span class="gem-row-text"><span class="gem-row-name">${escapeHtml(g.name)}${badge}</span>
        <span class="gem-row-desc">${escapeHtml(g.description || '')}</span></span>`;
      // Eingebaute Gems lassen sich ansehen, aber nicht aendern (wie in der App).
      main.addEventListener('click', () => openGemEditor(g, { readOnly: !!g.is_builtin }));
      row.appendChild(main);
      row.appendChild(iconButton('copy', t('gem_duplicate'), () => openGemEditor(g, { duplicate: true })));
      if (!g.is_builtin) {
        row.appendChild(iconButton('trash', t('delete'), async () => {
          const ok = await showConfirm({ title: t('delete'), text: t('gem_delete_confirm', g.name), okLabel: t('delete'), danger: true });
          if (!ok) return;
          try { await api('DELETE', '/me/gems/' + g.id); await loadGems(); }
          catch (err) { toast(t('toast_error_prefix', apiErrorText(err)), { error: true }); }
        }));
      }
      list.appendChild(row);
    }
  }

  function iconButton(icon, title, onClick) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'icon-btn';
    b.title = title;
    b.innerHTML = `<svg class="icon"><use href="#icon-${icon}"/></svg>`;
    b.addEventListener('click', onClick);
    return b;
  }

  // ---- Editor ----
  let editorGemId = null;   // null = neues Gem
  let editorFiles = [];     // schon gespeicherte Wissensdateien
  let queuedFiles = [];     // vor dem ersten Speichern gewaehlt, Upload beim Speichern
  let readOnly = false;

  function setSelect(sel, options, value) {
    sel.innerHTML = '';
    for (const o of options) {
      const opt = document.createElement('option');
      opt.value = o.value;
      opt.textContent = o.label;
      sel.appendChild(opt);
    }
    sel.value = value;
  }

  /** Alle Modelle wie im Modell-Menue des Chats, nach Anbieter gruppiert.
   *  Claude als Familie (der Server nimmt die neueste Generation), Gemini und
   *  GPT aus der Liste der Gateways. */
  function renderGemModelSelect(value) {
    const sel = $('gem-model');
    sel.innerHTML = '';
    const add = (parent, v, label) => {
      const o = document.createElement('option');
      o.value = v; o.textContent = label;
      parent.appendChild(o);
    };
    add(sel, '', t('gem_model_global_default'));
    const groups = [
      ['claude', t('model_family_claude'), CLAUDE_MODELS.map((m) => ({ key: m.id, label: m.label }))],
      ['gemini', t('model_family_gemini'), null],
      ['gpt', t('model_family_gpt'), null],
      ['other', t('model_family_other'), null],
    ];
    const known = new Set(['']);
    for (const [fam, label, fixed] of groups) {
      const list = fixed || state.chatModels.filter((m) => m.family === fam);
      if (!list.length) continue;
      const g = document.createElement('optgroup');
      g.label = label;
      for (const m of list) { add(g, m.key, m.label || m.key); known.add(m.key); }
      sel.appendChild(g);
    }
    // Ein Modell, das gerade nicht angeboten wird, bleibt sichtbar gewaehlt,
    // statt beim naechsten Speichern still zu verschwinden.
    if (value && !known.has(value)) add(sel, value, modelLabel(value));
    sel.value = value;
  }

  /** Denktiefen, die das gewaehlte Modell kann. */
  function renderGemEffortSelect(value) {
    const efforts = modelEfforts($('gem-model').value);
    const options = [{ value: '', label: t('gem_effort_chat_default') }]
      .concat(EFFORT_ORDER.filter((e) => efforts.includes(e)).map((e) => ({ value: e, label: formatEffortLabel(e) })));
    const keep = value && efforts.length ? clampEffort(value, efforts) : '';
    setSelect($('gem-effort'), options, keep);
  }

  function openGemEditor(gem, opts = {}) {
    const dup = !!opts.duplicate;
    readOnly = !!opts.readOnly;
    editorGemId = gem && !dup ? gem.id : null;
    editorFiles = gem && !dup ? (gem.files || []) : [];
    queuedFiles = [];
    $('gem-editor-title').textContent = readOnly ? (gem.name || '') : editorGemId ? t('gem_editor_title_edit') : t('gem_editor_title_new');
    $('gem-emoji').value = gem ? (gem.emoji || '') : '';
    $('gem-name').value = gem ? (dup ? t('gem_copy_name', gem.name) : gem.name) : '';
    $('gem-description').value = gem ? (gem.description || '') : '';
    $('gem-instructions').value = gem ? (gem.instructions || '') : '';
    $('gem-starters').innerHTML = '';
    ((gem && gem.conversation_starters) || []).forEach((s) => addStarterRow(s));
    renderGemModelSelect(gem && gem.model ? gem.model : '');
    renderGemEffortSelect(gem && gem.effort ? gem.effort : '');
    // Ohne geladene Modell-Liste fehlen Gemini und GPT; nachladen und die
    // Auswahl stehen lassen.
    if (!state.chatModels.length) {
      loadChatModels(false).then(() => {
        renderGemModelSelect($('gem-model').value);
        renderGemEffortSelect($('gem-effort').value);
      });
    }
    const sk = gem && gem.skills ? gem.skills : { web_search: true, web_fetch: true, code_execution: false };
    $('gem-skill-web-search').checked = sk.web_search !== false;
    $('gem-skill-web-fetch').checked = sk.web_fetch !== false;
    $('gem-skill-code').checked = !!sk.code_execution;
    renderEditorFiles();
    $('gem-files-savefirst').classList.toggle('hidden', !!editorGemId || readOnly);
    $('gem-add-file').classList.toggle('hidden', readOnly);
    $('gem-add-starter').classList.toggle('hidden', readOnly);
    $('gem-editor-save').classList.toggle('hidden', readOnly);
    $('gem-editor-cancel').textContent = readOnly ? t('close') : t('cancel');
    $('gem-editor-modal').querySelectorAll('.modal-body input, .modal-body textarea, .modal-body select')
      .forEach((el) => { if (el.type !== 'file') el.disabled = readOnly; });
    $('gem-editor-status').textContent = '';
    $('gem-editor-modal').classList.remove('hidden');
    if (!readOnly) setTimeout(() => $('gem-name').focus(), 30);
  }

  function addStarterRow(value) {
    const row = document.createElement('div');
    row.className = 'gem-starter-row';
    const inp = document.createElement('input');
    inp.type = 'text';
    inp.className = 'input';
    inp.value = value || '';
    inp.disabled = readOnly;
    row.appendChild(inp);
    if (!readOnly) row.appendChild(iconButton('close', t('remove_title'), () => row.remove()));
    $('gem-starters').appendChild(row);
    return inp;
  }

  function collectStarters() {
    return Array.from($('gem-starters').querySelectorAll('input')).map((i) => i.value.trim()).filter(Boolean);
  }

  function renderEditorFiles() {
    const wrap = $('gem-files');
    wrap.innerHTML = '';
    for (const f of editorFiles) {
      const row = document.createElement('div');
      row.className = 'gem-file-row';
      row.innerHTML = `<svg class="icon"><use href="#icon-file"/></svg><span>${escapeHtml(f.filename)}</span>`;
      if (!readOnly) {
        row.appendChild(iconButton('close', t('remove_title'), async () => {
          try {
            await api('DELETE', '/me/gems/' + editorGemId + '/files/' + f.id);
            editorFiles = editorFiles.filter((x) => x.id !== f.id);
            renderEditorFiles();
          } catch (e) { $('gem-editor-status').textContent = t('toast_error_prefix', apiErrorText(e)); }
        }));
      }
      wrap.appendChild(row);
    }
    for (const q of queuedFiles) {
      const row = document.createElement('div');
      row.className = 'gem-file-row queued';
      row.innerHTML = `<svg class="icon"><use href="#icon-file"/></svg><span>${escapeHtml(q.name)}</span>`;
      row.appendChild(iconButton('close', t('remove_title'), () => {
        queuedFiles = queuedFiles.filter((x) => x !== q);
        renderEditorFiles();
      }));
      wrap.appendChild(row);
    }
  }

  async function uploadGemFile(gemId, file) {
    const fd = new FormData();
    fd.append('file', file, file.name);
    return api('POST', '/me/gems/' + gemId + '/files', fd);
  }

  async function saveGem() {
    const name = $('gem-name').value.trim();
    const instructions = $('gem-instructions').value.trim();
    const status = $('gem-editor-status');
    if (!name || !instructions) { status.className = 'backup-status error'; status.textContent = t('gem_validation'); return; }
    const payload = {
      name,
      emoji: $('gem-emoji').value.trim(),
      description: $('gem-description').value.trim(),
      instructions,
      conversation_starters: collectStarters(),
      model: $('gem-model').value || null,
      effort: $('gem-effort').value || null,
      skills: {
        web_search: $('gem-skill-web-search').checked,
        web_fetch: $('gem-skill-web-fetch').checked,
        code_execution: $('gem-skill-code').checked,
      },
    };
    const saveBtn = $('gem-editor-save');
    saveBtn.disabled = true;
    // Gem und Dateiliste jetzt festhalten: wird waehrend des Speicherns ein
    // anderer Editor geoeffnet, landeten dessen Dateien sonst an diesem Gem.
    const startId = editorGemId;
    const files = queuedFiles;
    try {
      const saved = startId
        ? await api('PUT', '/me/gems/' + startId, payload)
        : await api('POST', '/me/gems', payload);
      const gemId = startId || saved.id;
      // Dateien, die vor dem ersten Speichern gewaehlt wurden, jetzt hochladen.
      if (files.length) {
        status.className = 'backup-status';
        status.textContent = t('gem_uploading');
        for (const f of files) await uploadGemFile(gemId, f);
        const done = [...files];
        queuedFiles = queuedFiles.filter((f) => !done.includes(f));
      }
      $('gem-editor-modal').classList.add('hidden');
      await loadGems();
    } catch (e) {
      status.className = 'backup-status error';
      status.textContent = t('toast_error_prefix', apiErrorText(e));
    } finally {
      saveBtn.disabled = false;
    }
  }

  const closeEditor = () => $('gem-editor-modal').classList.add('hidden');
  $('gems-new-btn')?.addEventListener('click', () => openGemEditor(null, {}));
  $('gems-new-sidebar')?.addEventListener('click', (e) => { e.stopPropagation(); openGemEditor(null, {}); });
  $('gem-editor-close')?.addEventListener('click', closeEditor);
  $('gem-editor-cancel')?.addEventListener('click', closeEditor);
  $('gem-editor-save')?.addEventListener('click', saveGem);
  $('gem-model')?.addEventListener('change', () => renderGemEffortSelect($('gem-effort').value));
  $('gem-add-starter')?.addEventListener('click', () => addStarterRow('').focus());
  const modal = $('gem-editor-modal');
  modal?.addEventListener('mousedown', (e) => { if (e.target === modal) closeEditor(); });
  modal?.addEventListener('keydown', (e) => { if (e.key === 'Escape') { e.stopPropagation(); closeEditor(); } });
  $('gem-add-file')?.addEventListener('click', () => $('gem-file-input').click());
  $('gem-file-input')?.addEventListener('change', async (e) => {
    const files = [...e.target.files];
    e.target.value = '';
    if (!files.length) return;
    if (!editorGemId) {
      queuedFiles.push(...files);
      renderEditorFiles();
      return;
    }
    const status = $('gem-editor-status');
    status.className = 'backup-status';
    status.textContent = t('gem_uploading');
    try {
      for (const f of files) editorFiles.push(await uploadGemFile(editorGemId, f));
      renderEditorFiles();
      status.textContent = '';
    } catch (err) {
      status.className = 'backup-status error';
      status.textContent = t('toast_error_prefix', apiErrorText(err));
    }
  });

  document.addEventListener('pc:settings-open', loadGems);
  document.addEventListener('pc:locale-changed', () => { renderGemsSidebar(); renderGemsSettingsList(); });
  window.PocketGems = { load: loadGems, openEditor: openGemEditor };
})();
