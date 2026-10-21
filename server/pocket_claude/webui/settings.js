// =====================================================================
// Einstellungen: Rubriken links, Inhalt rechts (wie chatgpt.com).
// Inhalt und Reihenfolge folgen der App (SettingsScreen.kt).
// =====================================================================
(function initSettings() {
  const modal = els.settingsModal;
  const nav = $('settings-nav');
  let currentPane = 'general';

  function showPane(name) {
    const btn = nav.querySelector(`[data-pane="${name}"]`);
    if (!btn || btn.classList.contains('hidden')) name = 'general';
    currentPane = name;
    nav.querySelectorAll('[data-pane]').forEach((b) => b.classList.toggle('active', b.dataset.pane === name));
    document.querySelectorAll('.settings-pane').forEach((p) => p.classList.toggle('active', p.dataset.pane === name));
    $('settings-body').scrollTop = 0;
    paneLoaders[name]?.();
  }
  nav.addEventListener('click', (e) => {
    const b = e.target.closest('[data-pane]');
    if (b) showPane(b.dataset.pane);
  });

  window.openSettings = function openSettings(pane) {
    closePopup();
    if (isMobile()) closeSidebar();
    modal.classList.remove('hidden');
    document.dispatchEvent(new CustomEvent('pc:settings-open'));
    showPane(pane || currentPane);
  };
  function closeSettings() {
    modal.classList.add('hidden');
    ['claude-auth-status', 'skills-defaults-status', 'img-defaults-status', 'settings-backup-status'].forEach((id) => {
      const el = $(id); if (el) { el.textContent = ''; el.className = 'backup-status'; }
    });
  }
  $('settings-close').addEventListener('click', closeSettings);
  modal.addEventListener('mousedown', (e) => { if (e.target === modal) closeSettings(); });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !modal.classList.contains('hidden') && !document.querySelector('.modal:not(.settings-modal):not(.hidden)')) {
      closeSettings();
    }
  });

  function setStatus(id, text, cls = '') {
    const el = $(id);
    if (!el) return;
    el.textContent = text || '';
    el.className = 'backup-status' + (el.classList.contains('set-pad') ? ' set-pad' : '') + (cls ? ' ' + cls : '');
  }
  function flashSaved(id) { setStatus(id, t('saved'), 'ok'); }

  // =========================================================
  // Allgemein: Design, Farbschemata, Einklappen, Sprache
  // =========================================================
  function renderPalettes() {
    for (const mode of ['light', 'dark']) {
      const grid = $(mode === 'light' ? 'palette-light-grid' : 'palette-dark-grid');
      if (!grid) continue;
      const active = mode === 'light' ? state.paletteLight : state.paletteDark;
      grid.innerHTML = '';
      for (const p of PALETTES) {
        const b = document.createElement('button');
        b.type = 'button';
        b.className = 'palette-card' + (p.id === active ? ' active' : '');
        b.setAttribute('aria-pressed', String(p.id === active));
        // Die Vorschau traegt ihre eigene Palette: die CSS-Variablen aus
        // palettes.css greifen an jedem Element mit data-theme und data-palette.
        b.innerHTML = `<span class="palette-preview" data-theme="${mode}" data-palette="${p.id}">
            <span class="pp-side"></span>
            <span class="pp-main"><span class="pp-bubble"></span><span class="pp-line l1"></span><span class="pp-line l2"></span><span class="pp-dot"></span></span>
          </span><span class="pp-name">${escapeHtml(p.name)}</span>`;
        b.addEventListener('click', () => { setPalette(mode, p.id); renderPalettes(); });
        grid.appendChild(b);
      }
    }
  }
  const collapseBox = $('setting-collapse-user-msgs');
  collapseBox.addEventListener('change', () => {
    state.collapseUserMsgs = collapseBox.checked;
    localStorage.setItem(LS.collapseUserMsgs, String(state.collapseUserMsgs));
    queueSettingsPush();
    if (state.view === 'chat') renderMessages();
  });
  // Benachrichtigung: die Erlaubnis fragt der Browser nur nach einem Klick ab.
  const notifyBox = $('setting-notify');
  function renderNotify() {
    const supported = 'Notification' in window;
    const denied = supported && Notification.permission === 'denied';
    notifyBox.checked = state.notify && supported && Notification.permission === 'granted';
    notifyBox.disabled = !supported || denied;
    $('notify-hint').textContent = denied ? t('notify_denied') : t('notify_done_hint');
  }
  notifyBox.addEventListener('change', async () => {
    let on = notifyBox.checked;
    if (on && Notification.permission !== 'granted') on = (await Notification.requestPermission()) === 'granted';
    state.notify = on;
    localStorage.setItem('pc.notify', String(on));
    renderNotify();
  });
  const localeSel = $('ui-locale-select');
  localeSel.addEventListener('change', () => {
    window.PocketI18n.setLocale(localeSel.value);
    document.dispatchEvent(new CustomEvent('pc:locale-changed'));
  });
  function loadGeneral() {
    applyTheme();
    renderPalettes();
    collapseBox.checked = state.collapseUserMsgs;
    renderNotify();
    localeSel.value = localStorage.getItem('pc_locale') || '';
  }

  // =========================================================
  // Modelle: Standardmodell, Denktiefe je Familie, System-Prompt
  // =========================================================
  const FAMILY_LABEL = () => ({ claude: t('model_family_claude'), gemini: t('model_family_gemini'), gpt: t('model_family_gpt'), other: t('model_family_other') });
  function renderDefaultModel() {
    const sel = $('default-model-select');
    if (!sel) return;
    sel.innerHTML = '';
    const auto = document.createElement('option');
    auto.value = '';
    auto.textContent = t('model_auto');
    sel.appendChild(auto);
    const labels = FAMILY_LABEL();
    for (const fam of ['claude', 'gemini', 'gpt', 'other']) {
      const list = state.chatModels.filter((m) => m.family === fam && m.key);
      if (!list.length) continue;
      const og = document.createElement('optgroup');
      og.label = labels[fam];
      for (const m of list) {
        const o = document.createElement('option');
        o.value = m.key;
        o.textContent = (m.label || m.key) + (m.gateway_label ? ` · ${m.gateway_label}` : '');
        og.appendChild(o);
      }
      sel.appendChild(og);
    }
    sel.value = state.chatModel || '';
    if (sel.value !== (state.chatModel || '')) sel.value = '';
  }
  $('default-model-select').addEventListener('change', (e) => {
    state.chatModel = e.target.value;
    localStorage.setItem(LS.chatModel, state.chatModel);
    queueSettingsPush();
    updateModelButton();
    renderModelMenu();
  });
  function familyEfforts(fam) {
    if (fam === 'claude') return CLAUDE_EFFORTS;
    const set = new Set();
    for (const m of state.chatModels) if (m.family === fam) (m.efforts || []).forEach((e) => set.add(e));
    return EFFORT_ORDER.filter((e) => set.has(e));
  }
  function renderEffortDefaults() {
    const box = $('effort-defaults');
    if (!box) return;
    box.innerHTML = '';
    const labels = FAMILY_LABEL();
    for (const fam of ['claude', 'gemini', 'gpt']) {
      const efforts = familyEfforts(fam);
      if (!efforts.length) continue;
      const row = document.createElement('div');
      row.className = 'effort-row';
      row.innerHTML = `<span class="set-title">${escapeHtml(labels[fam])}</span><div class="chip-row"></div>`;
      const chips = row.querySelector('.chip-row');
      const cur = clampEffort(state.effortByFamily[fam] || 'high', efforts);
      for (const e of efforts) {
        const c = document.createElement('button');
        c.type = 'button';
        c.className = 'chip' + (e === cur ? ' active' : '');
        c.textContent = formatEffortLabel(e);
        c.addEventListener('click', () => { setEffort(e, fam); renderEffortDefaults(); });
        chips.appendChild(c);
      }
      box.appendChild(row);
    }
  }
  document.querySelectorAll('input[name="sp-mode"]').forEach((r) => {
    r.addEventListener('change', () => {
      if (!r.checked) return;
      state.spMode = r.value;
      localStorage.setItem(LS.spMode, r.value);
      queueSettingsPush();
      $('sp-custom').classList.toggle('hidden', r.value !== 'CUSTOM');
    });
  });
  $('sp-custom').addEventListener('input', (e) => {
    state.spCustom = e.target.value;
    localStorage.setItem(LS.spCustom, state.spCustom);
    queueSettingsPush();
  });
  function loadModels() {
    renderDefaultModel();
    renderEffortDefaults();
    document.querySelectorAll('input[name="sp-mode"]').forEach((r) => { r.checked = r.value === state.spMode; });
    $('sp-custom').value = state.spCustom;
    $('sp-custom').classList.toggle('hidden', state.spMode !== 'CUSTOM');
  }
  document.addEventListener('pc:models-loaded', () => { if (!modal.classList.contains('hidden')) { renderDefaultModel(); renderEffortDefaults(); } });
  document.addEventListener('pc:effort-changed', () => { if (!modal.classList.contains('hidden')) renderEffortDefaults(); });

  // =========================================================
  // Faehigkeiten: Standard fuer neue Chats
  // =========================================================
  const skillBoxes = [...document.querySelectorAll('[data-skill]')];
  let skillDefaults = null;
  async function loadSkills() {
    try {
      skillDefaults = await api('GET', '/skills/defaults');
      for (const b of skillBoxes) b.checked = !!skillDefaults[b.dataset.skill];
    } catch (e) { setStatus('skills-defaults-status', t('toast_error_prefix', apiErrorText(e)), 'error'); }
  }
  for (const b of skillBoxes) {
    b.addEventListener('change', async () => {
      const skills = Object.assign({ web_search: true, web_fetch: true, code_execution: false, image_generation: true }, skillDefaults || {});
      for (const x of skillBoxes) skills[x.dataset.skill] = x.checked;
      try {
        skillDefaults = await api('PUT', '/skills/defaults', { skills });
        flashSaved('skills-defaults-status');
      } catch (e) {
        b.checked = !b.checked;
        setStatus('skills-defaults-status', t('toast_error_prefix', apiErrorText(e)), 'error');
      }
    });
  }

  // =========================================================
  // Vorlesen
  // =========================================================
  const ttsProvider = $('tts-provider');
  const ttsVoice = $('tts-voice');
  const ttsSpeed = $('tts-speed');
  const ttsSpeedLabel = $('tts-speed-label');
  const autoSpeakBox = $('tts-auto-speak');
  const chunkBox = $('tts-chunking');
  let ttsStatus = null;
  const TIER_LABELS = () => ({ grok: 'Grok', geminiweb: 'Gemini Web', edge: 'Microsoft Edge' });
  const TIER_ORDER = ['grok', 'geminiweb', 'edge'];
  /** Gewaehlter Anbieter. `provider` ist der, der gerade wirklich vorliest;
   *  springt einer ein, weil der gewaehlte nicht laeuft, bleibt die Wahl. */
  const chosenProvider = (s) => s.chosen_provider || s.provider || 'grok';

  function renderTtsHint(s) {
    const el = $('tts-provider-hint');
    const p = chosenProvider(s);
    let ok, text;
    if (s.provider && s.provider !== p) {
      ok = false;
      text = t('tts_hint_fallback', ttsProvider.querySelector(`option[value="${s.provider}"]`)?.textContent || s.provider);
    } else if (p === 'grok') { ok = !!s.configured; text = ok ? t('tts_hint_grok_ok') : t('tts_hint_grok_down'); }
    else if (p === 'gemini_web') { ok = !!s.configured; text = ok ? t('tts_hint_web_ok') : t('tts_hint_web_down'); }
    else { ok = true; text = t('tts_hint_edge_ok'); }
    el.textContent = text;
    el.classList.toggle('status-ok', ok);
    el.classList.toggle('status-warn', !ok);
  }
  /** Stimmen nur fuer den gewaehlten Anbieter anbieten (compatible_providers),
   *  wie die App. Passt die gemerkte Stimme nicht, gilt die Vorgabe des Anbieters. */
  function renderVoices(s) {
    const provider = chosenProvider(s);
    const voices = (s.voices || []).filter((v) => !v.compatible_providers || !v.compatible_providers.length || v.compatible_providers.includes(provider));
    ttsVoice.innerHTML = '';
    const grouped = {};
    for (const v of voices) (grouped[v.tier] = grouped[v.tier] || []).push(v);
    const labels = TIER_LABELS();
    const tiers = TIER_ORDER.concat(Object.keys(grouped).filter((k) => !TIER_ORDER.includes(k)));
    for (const tier of tiers) {
      if (!grouped[tier]) continue;
      const og = document.createElement('optgroup');
      og.label = labels[tier] || tier;
      for (const v of grouped[tier]) {
        const o = document.createElement('option');
        o.value = v.id;
        o.textContent = v.label;
        og.appendChild(o);
      }
      ttsVoice.appendChild(og);
    }
    const ids = voices.map((v) => v.id);
    if (ids.length && !ids.includes(state.ttsVoice)) {
      const fallback = provider === 'grok' ? 'grok-leo' : s.default_voice;
      state.ttsVoice = ids.includes(fallback) ? fallback : ids[0];
      localStorage.setItem(LS.ttsVoice, state.ttsVoice);
      queueSettingsPush();
    }
    ttsVoice.value = state.ttsVoice;
    ttsVoice.disabled = provider === 'gemini_web' && ids.length <= 1;
  }
  function renderTts(s) {
    ttsStatus = s;
    state.ttsProvider = s.provider || null;
    ttsProvider.value = chosenProvider(s);
    renderTtsHint(s);
    renderVoices(s);
    ttsSpeed.value = state.ttsSpeed;
    ttsSpeedLabel.textContent = state.ttsSpeed.toFixed(2) + '×';
    autoSpeakBox.checked = state.autoSpeak;
    // Stueckeln nur bei Edge: Grok teilt und streamt selbst, und das Ogg von
    // Gemini Web laesst sich gar nicht aneinanderhaengen.
    $('tts-chunking-row').classList.toggle('hidden', chosenProvider(s) !== 'edge_tts');
    chunkBox.checked = !!s.chunking_enabled;
  }
  async function loadTts() {
    try { renderTts(await api('GET', '/tts/status')); }
    catch (e) { toast(t('toast_tts_error', apiErrorText(e)), { error: true }); }
  }
  ttsProvider.addEventListener('change', async () => {
    try {
      const s = await api('PUT', '/tts/provider', { provider: ttsProvider.value });
      renderTts(s);
      toast(t('toast_provider_changed', ttsProvider.options[ttsProvider.selectedIndex].textContent));
    } catch (e) {
      toast(t('toast_provider_switch_failed', apiErrorText(e)), { error: true });
      if (ttsStatus) ttsProvider.value = chosenProvider(ttsStatus);
    }
  });
  ttsVoice.addEventListener('change', () => {
    state.ttsVoice = ttsVoice.value;
    localStorage.setItem(LS.ttsVoice, state.ttsVoice);
    queueSettingsPush();
  });
  ttsSpeed.addEventListener('input', () => {
    state.ttsSpeed = parseFloat(ttsSpeed.value);
    ttsSpeedLabel.textContent = state.ttsSpeed.toFixed(2) + '×';
    localStorage.setItem(LS.ttsSpeed, String(state.ttsSpeed));
    queueSettingsPush();
  });
  // Stimme testen wie in der App: eine vorhandene Antwort mit der gewaehlten
  // Stimme abspielen (der Server liest nur gespeicherte Nachrichten vor).
  $('tts-test-btn').addEventListener('click', async () => {
    const status = $('tts-test-status');
    status.textContent = '';
    // Ein gesperrter Chat liefert keinen Beispieltext, weder der offene noch einer aus der Liste.
    let msgId = isCurrentChatLocked() ? null
      : [...state.messages].reverse().find((m) => m.role === 'assistant' && m.id > 0 && m.content)?.id;
    const recent = state.chats.slice().sort((a, b) => chatSortKey(b).localeCompare(chatSortKey(a))).filter((c) => !c.locked);
    for (const c of recent.slice(0, 8)) {
      if (msgId) break;
      try {
        const d = await api('GET', '/conversations/' + c.id);
        msgId = (d.messages || []).find((m) => m.role === 'assistant' && m.content)?.id;
      } catch { /* naechsten Chat versuchen */ }
    }
    if (!msgId) { status.textContent = t('tts_test_no_message'); return; }
    speak(msgId);
    $('tts-test-stop').classList.remove('hidden');
  });
  $('tts-test-stop').addEventListener('click', () => { stopAudio(); $('tts-test-stop').classList.add('hidden'); });
  els.audio.addEventListener('ended', () => $('tts-test-stop').classList.add('hidden'));
  autoSpeakBox.addEventListener('change', () => {
    state.autoSpeak = autoSpeakBox.checked;
    localStorage.setItem(LS.autoSpeak, String(state.autoSpeak));
    queueSettingsPush();
  });
  chunkBox.addEventListener('change', async () => {
    try { renderTts(await api('PUT', '/tts/chunking', { enabled: chunkBox.checked })); }
    catch (e) { chunkBox.checked = !chunkBox.checked; toast(t('toast_error_prefix', apiErrorText(e)), { error: true }); }
  });

  // =========================================================
  // Bilder: Vorgaben fuer Anbieter, Aufloesung und Format
  // =========================================================
  let imgCfg = null;
  function providerLabel(p) {
    const k = 'images_provider_' + p.id;
    const v = t(k);
    return v && v !== k ? v : (p.label || p.id);
  }
  function renderImageDefaults(cfg) {
    imgCfg = cfg;
    const d = cfg.defaults || {};
    const provBox = $('img-default-provider');
    const providers = cfg.providers || [];
    $('img-default-provider-row').classList.toggle('hidden', providers.length <= 1);
    provBox.innerHTML = '';
    for (const p of providers) {
      const b = document.createElement('button');
      b.type = 'button';
      b.textContent = providerLabel(p);
      b.classList.toggle('active', p.id === d.provider);
      b.addEventListener('click', () => saveImageDefault('provider', p.id));
      provBox.appendChild(b);
    }
    const hint = { gemini: 'images_hint_gemini', gpt: 'images_hint_gpt', both: 'images_hint_both' }[d.provider];
    $('img-default-provider-hint').textContent = hint ? t(hint) : '';
    const chips = (boxId, items, value, field, showLabel) => {
      const box = $(boxId);
      box.innerHTML = '';
      for (const it of items) {
        const c = document.createElement('button');
        c.type = 'button';
        c.className = 'chip' + (it.id === value ? ' active' : '');
        c.textContent = showLabel ? it.label : it.id;
        c.title = it.label || it.id;
        c.addEventListener('click', () => saveImageDefault(field, it.id));
        box.appendChild(c);
      }
    };
    chips('img-default-size', cfg.image_sizes || [], d.size, 'size', false);
    chips('img-default-aspect', cfg.aspect_ratios || [], d.aspect_ratio, 'aspect_ratio', true);
  }
  async function loadImageDefaults() {
    try { renderImageDefaults(await api('GET', '/images/config')); }
    catch (e) { setStatus('img-defaults-status', t('image_config_load_failed'), 'error'); }
  }
  async function saveImageDefault(field, value) {
    try {
      renderImageDefaults(await api('PUT', '/images/defaults', { [field]: value }));
      if (window.PocketImages) window.PocketImages.invalidate();
      flashSaved('img-defaults-status');
    } catch (e) { setStatus('img-defaults-status', t('toast_error_prefix', apiErrorText(e)), 'error'); }
  }

  // =========================================================
  // Sperre und Gedaechtnis
  // =========================================================
  function setChatLockStatus(text, cls = '') { setStatus('chat-lock-status', text, cls); }
  document.querySelectorAll('#chat-lock-section input[inputmode="numeric"]').forEach((inp) => {
    inp.addEventListener('input', () => { inp.value = inp.value.replace(/\D/g, '').slice(0, 5); });
  });
  async function loadChatLockStatus() {
    const setForm = $('chat-lock-set-form');
    const changeForm = $('chat-lock-change-form');
    try {
      const r = await api('GET', '/me/chat-lock');
      const isSet = !!r.is_set;
      setForm.classList.toggle('hidden', isSet);
      changeForm.classList.toggle('hidden', !isSet);
      // Felder leeren, damit keine PIN im DOM haengen bleibt.
      ['chat-lock-pin', 'chat-lock-pin-confirm', 'chat-lock-current', 'chat-lock-new', 'chat-lock-new-confirm']
        .forEach((id) => { const el = $(id); if (el) el.value = ''; });
      setChatLockStatus(isSet ? t('chat_lock_is_set') : t('chat_lock_not_set'));
    } catch {
      setForm.classList.add('hidden');
      changeForm.classList.add('hidden');
    }
  }
  const pinVal = (id) => ($(id)?.value || '').replace(/\D/g, '');
  $('chat-lock-save').addEventListener('click', async () => {
    const pin = pinVal('chat-lock-pin');
    if (pin.length !== 5) return setChatLockStatus(t('chat_lock_pin_5_digits'), 'error');
    if (pin !== pinVal('chat-lock-pin-confirm')) return setChatLockStatus(t('chat_lock_pin_mismatch'), 'error');
    try { await api('PUT', '/me/chat-lock', { pin }); await loadChatLockStatus(); setChatLockStatus(t('chat_lock_saved'), 'ok'); }
    catch (e) { setChatLockStatus(t('toast_error_prefix', apiErrorText(e)), 'error'); }
  });
  $('chat-lock-change').addEventListener('click', async () => {
    const pin = pinVal('chat-lock-new');
    if (pin.length !== 5) return setChatLockStatus(t('chat_lock_pin_5_digits'), 'error');
    if (pin !== pinVal('chat-lock-new-confirm')) return setChatLockStatus(t('chat_lock_pin_mismatch'), 'error');
    try {
      await api('PUT', '/me/chat-lock', { pin, current_pin: pinVal('chat-lock-current') });
      await loadChatLockStatus();
      setChatLockStatus(t('chat_lock_saved'), 'ok');
    } catch (e) {
      setChatLockStatus(e instanceof ApiError && e.status === 401 ? t('chat_lock_wrong_pin') : t('toast_error_prefix', apiErrorText(e)), 'error');
    }
  });
  $('chat-lock-remove').addEventListener('click', async () => {
    const current = pinVal('chat-lock-current');
    if (current.length !== 5) return setChatLockStatus(t('chat_lock_pin_5_digits'), 'error');
    try {
      await api('POST', '/me/chat-lock/clear', { current_pin: current });
      // Der Server entsperrt dabei alle Chats; lokalen Stand angleichen.
      state.unlockedCids.clear();
      state.chatLocked = false;
      await loadChatLockStatus();
      setChatLockStatus(t('chat_lock_removed'), 'ok');
      await refreshChatList();
      if (state.cid && state.view === 'chat') renderMessages();
    } catch (e) {
      setChatLockStatus(e instanceof ApiError && e.status === 401 ? t('chat_lock_wrong_pin') : t('toast_error_prefix', apiErrorText(e)), 'error');
    }
  });

  function loadMemoryKeyStatus(msg = '', cls = '') {
    const set = !!wissenSchluessel();
    setStatus('memory-key-status', msg || t(set ? 'memory_key_set' : 'memory_key_unset'), cls || (set ? 'ok' : ''));
    $('memory-key-remove').classList.toggle('hidden', !set);
  }
  $('memory-key-save').addEventListener('click', () => {
    const input = $('memory-key-input');
    const k = (input.value || '').trim();
    if (!WISSEN_FORMAT.test(k)) return loadMemoryKeyStatus(t('memory_key_invalid'), 'error');
    const origin = serverOrigin();
    if (!sichereHerkunft(origin)) return loadMemoryKeyStatus(t('memory_key_https'), 'error');
    if (!state.me || !state.me.id) return;
    localStorage.setItem(WISSEN_PREFIX + state.me.id, JSON.stringify({ k, o: origin }));
    input.value = '';
    loadMemoryKeyStatus();
  });
  $('memory-key-remove').addEventListener('click', () => {
    if (state.me && state.me.id) localStorage.removeItem(WISSEN_PREFIX + state.me.id);
    loadMemoryKeyStatus();
  });

  // =========================================================
  // Konto
  // =========================================================
  // Profilbild: ein gemeinsamer Datei-Dialog fuer das eigene Bild und (als
  // Admin) fuer die Bilder der anderen.
  let avatarTarget = null;   // null = eigenes Bild, sonst User-ID
  function pickAvatar(userId) {
    avatarTarget = userId || null;
    $('avatar-file-input').click();
  }
  function renderMyAvatar() {
    $('my-avatar-preview').replaceChildren(avatarEl(state.me || {}, 'avatar-lg'));
    $('my-avatar-remove').classList.toggle('hidden', !(state.me && state.me.avatar_version));
  }
  $('avatar-file-input').addEventListener('change', async (e) => {
    const file = e.target.files[0];
    e.target.value = '';
    if (!file) return;
    const target = avatarTarget;
    try {
      const u = await uploadAvatar(file, target);
      if (!target || (state.me && u.id === state.me.id)) {
        state.me = Object.assign({}, state.me, u);
        renderFooterUser();
        renderMyAvatar();
      }
      if (target) await loadUsersList();
      toast(t('avatar_saved'));
    } catch (err) {
      toast(t('toast_error_prefix', err && err.name === 'InvalidStateError' ? t('avatar_unreadable') : apiErrorText(err)), { error: true });
    }
  });
  $('my-avatar-pick').addEventListener('click', () => pickAvatar(null));
  $('my-avatar-remove').addEventListener('click', async () => {
    try {
      state.me = Object.assign({}, state.me, await api('DELETE', '/me/avatar'));
      renderFooterUser();
      renderMyAvatar();
    } catch (err) { toast(t('toast_error_prefix', apiErrorText(err)), { error: true }); }
  });

  async function loadAccount() {
    $('my-account-name').textContent = state.me ? state.me.name : '—';
    renderMyAvatar();
    $('account-server').textContent = state.serverUrl || location.origin;
    const conn = $('account-conn');
    conn.className = 'conn-state';
    conn.textContent = '…';
    try {
      const h = await api('GET', '/health');
      conn.className = 'conn-state ok status-ok';
      conn.textContent = t('connection_ok', h.version || '');
    } catch (e) {
      conn.className = 'conn-state error status-warn';
      conn.textContent = t('connection_failed');
    }
  }
  $('change-pw-btn').addEventListener('click', () => openPasswordChange({ forced: false }));
  $('account-logout-btn').addEventListener('click', () => logout());
  $('logout-all-btn').addEventListener('click', async () => {
    if (!(await showConfirm({ title: t('logout_all'), text: t('confirm_logout_all'), okLabel: t('logout_all'), danger: true }))) return;
    try {
      await api('POST', '/auth/logout-all');
      localStorage.removeItem(LS.token);
      wissenVergessen();
      state.token = '';
      location.reload();
    } catch (e) { toast(t('toast_logout_all_failed', apiErrorText(e)), { error: true }); }
  });

  // =========================================================
  // Anbieter und Zugaenge: Claude ueber Pro/Max, API-Schluessel oder Bedrock
  // =========================================================
  function authStatus(text, cls = '') { setStatus('claude-auth-status', text, cls); }
  async function loadClaudeAuth() {
    try {
      const data = await api('GET', '/me/claude-auth');
      const mode = data.mode || 'pro_max';
      document.querySelectorAll('input[name="claude-auth-mode"]').forEach((el) => { el.checked = el.value === mode; });
      const hints = { pro_max: 'claude_mode_pro_max_hint', api_key: 'claude_mode_api_key_hint', bedrock: 'claude_mode_bedrock_hint' };
      $('claude-auth-mode-hint').textContent = t(hints[mode] || hints.pro_max);
      $('claude-auth-apikey-form').classList.toggle('hidden', mode !== 'api_key');
      $('claude-auth-bedrock-form').classList.toggle('hidden', mode !== 'bedrock');
      $('claude-auth-apikey-current').textContent = data.api_key_set ? t('current_value_label', data.api_key_masked) : t('not_configured');
      $('bedrock-region').value = data.aws_region || '';
      ['bedrock-akid', 'bedrock-secret', 'bedrock-session'].forEach((id) => { $(id).value = ''; });  // Geheimnisse nie vorbelegen
      $('bedrock-opus').value = data.bedrock_opus_model || '';
      $('bedrock-sonnet').value = data.bedrock_sonnet_model || '';
      $('bedrock-haiku').value = data.bedrock_haiku_model || '';
      document.querySelectorAll('input[name="bedrock-alias"]').forEach((el) => { el.checked = el.value === (data.bedrock_model_alias || 'opus'); });
    } catch { /* noch nicht angemeldet */ }
  }
  async function putClaudeAuth(payload) { return api('PUT', '/me/claude-auth', payload); }
  document.querySelectorAll('input[name="claude-auth-mode"]').forEach((el) => {
    el.addEventListener('change', async () => {
      try { await putClaudeAuth({ mode: el.value }); await loadClaudeAuth(); flashSaved('claude-auth-status'); }
      catch (e) { authStatus(t('toast_error_prefix', apiErrorText(e)), 'error'); }
    });
  });
  $('claude-anthropic-save').addEventListener('click', async () => {
    const key = $('claude-anthropic-key').value.trim();
    if (!key) return;
    try { await putClaudeAuth({ api_key: key }); $('claude-anthropic-key').value = ''; flashSaved('claude-auth-status'); await loadClaudeAuth(); }
    catch (e) { authStatus(t('toast_error_prefix', apiErrorText(e)), 'error'); }
  });
  $('claude-anthropic-clear').addEventListener('click', async () => {
    if (!(await showConfirm({ title: t('clear'), text: t('confirm_remove_api_key'), okLabel: t('remove'), danger: true }))) return;
    try { await putClaudeAuth({ api_key: '' }); await loadClaudeAuth(); }
    catch (e) { authStatus(t('toast_error_prefix', apiErrorText(e)), 'error'); }
  });
  $('bedrock-apply').addEventListener('click', async () => {
    const alias = (document.querySelector('input[name="bedrock-alias"]:checked') || {}).value;
    const body = {
      aws_region: $('bedrock-region').value.trim() || null,
      aws_access_key_id: $('bedrock-akid').value.trim() || null,
      aws_secret_access_key: $('bedrock-secret').value || null,
      aws_session_token: $('bedrock-session').value || null,
      bedrock_opus_model: $('bedrock-opus').value.trim() || null,
      bedrock_sonnet_model: $('bedrock-sonnet').value.trim() || null,
      bedrock_haiku_model: $('bedrock-haiku').value.trim() || null,
      bedrock_model_alias: alias || null,
    };
    Object.keys(body).forEach((k) => body[k] === null && delete body[k]);
    try { await putClaudeAuth(body); flashSaved('claude-auth-status'); await loadClaudeAuth(); }
    catch (e) { authStatus(t('toast_error_prefix', apiErrorText(e)), 'error'); }
  });
  document.querySelectorAll('input[name="bedrock-alias"]').forEach((el) => {
    el.addEventListener('change', async () => {
      try { await putClaudeAuth({ bedrock_model_alias: el.value }); await loadClaudeAuth(); }
      catch (e) { authStatus(t('toast_error_prefix', apiErrorText(e)), 'error'); }
    });
  });

  // =========================================================
  // Token-Verbrauch
  // =========================================================
  async function loadUsage() {
    try {
      const u = await api('GET', '/me/usage?period=month');
      const fmt = (n) => (n || 0) < 1000 ? String(n || 0) : n < 1e6 ? (n / 1000).toFixed(1) + 'K' : (n / 1e6).toFixed(2) + 'M';
      const rows = [
        [t('usage_input'), fmt(u.input_tokens)],
        [t('usage_output'), fmt(u.output_tokens)],
        [t('usage_cache_create'), fmt(u.cache_create_tokens)],
        [t('usage_cache_read'), fmt(u.cache_read_tokens)],
        [t('usage_requests'), fmt(u.request_count)],
      ];
      if (u.provider) rows.push([t('usage_provider'), u.provider]);
      $('usage-grid').innerHTML = rows.map(([l, v]) => `<div>${escapeHtml(l)}</div><div>${escapeHtml(v)}</div>`).join('');
      $('usage-pro-max-note').classList.toggle('hidden', !(u.provider === 'pro_max' || !u.provider));
    } catch { /* aeltere Server ohne Statistik */ }
  }
  $('usage-refresh').addEventListener('click', loadUsage);

  // =========================================================
  // Daten: Chat-Backup (ZIP) und Einstellungs-Backup (JSON)
  // =========================================================
  function setBackupStatus(text, cls = '') { setStatus('backup-status', text, cls); }
  function downloadBlob(blob, filename) {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  }
  $('backup-export-btn').addEventListener('click', async () => {
    const pw = await showPrompt({
      title: t('backup_encrypt_title'), text: t('backup_encrypt_text'),
      placeholder: t('backup_password_placeholder'), type: 'password', okLabel: t('backup_export_button'),
    });
    if (pw === null) return;
    setBackupStatus(t('backup_loading'));
    try {
      const params = new URLSearchParams();
      if (pw) params.set('password', pw);
      const resp = await fetch(`${state.serverUrl}/backup${params.toString() ? '?' + params : ''}`, {
        headers: { 'Authorization': 'Bearer ' + state.token },
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const blob = await resp.blob();
      const m = (resp.headers.get('Content-Disposition') || '').match(/filename="([^"]+)"/);
      const filename = m ? m[1] : `pocket-claude-backup${pw ? '.enc' : ''}.zip`;
      downloadBlob(blob, filename);
      setBackupStatus(t('backup_export_done', filename, (blob.size / 1024 / 1024).toFixed(1)), 'ok');
    } catch (e) { setBackupStatus(t('backup_export_failed', apiErrorText(e)), 'error'); }
  });
  $('backup-import-btn').addEventListener('click', () => $('backup-file-input').click());
  $('backup-file-input').addEventListener('change', async (e) => {
    const file = e.target.files[0];
    e.target.value = '';
    if (!file) return;
    setBackupStatus(t('backup_checking'));
    try {
      const bytes = await file.arrayBuffer();
      let password = null;
      let manifest;
      while (true) {
        try { manifest = await backupRequest('/backup/peek', bytes, password); break; }
        catch (err) {
          if (err.status !== 423) throw err;
          const pw = await showPrompt({
            title: t('backup_encrypted_title'),
            text: password ? t('backup_password_wrong') : t('backup_password_enter'),
            placeholder: t('backup_password_placeholder_short'), type: 'password', okLabel: t('backup_unlock'),
          });
          if (!pw) { setBackupStatus(''); return; }
          password = pw;
        }
      }
      const mode = await openDialog({
        title: t('backup_import_title'),
        text: t('backup_import_summary_plain', manifest.conversation_count, manifest.message_count, manifest.attachment_count),
        actions: [
          { label: t('cancel'), value: null },
          { label: t('backup_merge'), kind: 'btn-secondary', value: 'merge' },
          { label: t('backup_replace'), kind: 'btn-danger', value: 'replace' },
        ],
      });
      if (!mode) { setBackupStatus(''); return; }
      setBackupStatus(t('backup_importing', mode));
      const r = await backupRequest('/backup/import', bytes, password, mode);
      setBackupStatus(t('backup_import_result', r.conversations_added, r.conversations_skipped, r.messages_imported), 'ok');
      refreshChatList();
    } catch (err) { setBackupStatus(t('backup_import_failed', apiErrorText(err)), 'error'); }
  });
  function backupRequest(path, buf, password, mode) {
    const fd = new FormData();
    fd.append('file', new Blob([buf]), 'backup.zip');
    const params = new URLSearchParams();
    if (mode) params.set('mode', mode);
    if (password) params.set('password', password);
    return api('POST', path + (params.toString() ? '?' + params : ''), fd);
  }

  // Einstellungs-Backup im Format der App (FullSettingsExportDto): dieselbe
  // Datei laesst sich in App und Web einlesen. Felder der App, die das Web
  // nicht kennt, werden beim Import gemerkt und beim Export wieder mitgegeben.
  const LS_APP_PASSTHROUGH = 'pc.appSettingsPassthrough';
  function webAppSettings(imageDefaults) {
    const passthrough = readJson(LS_APP_PASSTHROUGH, {});
    return Object.assign({}, passthrough, {
      theme_mode: state.themeMode.toUpperCase(),
      palette_id: state.paletteDark,
      palette_id_light: state.paletteLight,
      palette_id_dark: state.paletteDark,
      tts_voice: state.ttsVoice,
      tts_auto_speak: state.autoSpeak,
      tts_speed: state.ttsSpeed,
      effort: state.effortByFamily.claude || state.effort,
      system_prompt_mode: state.spMode,
      custom_system_prompt: state.spCustom,
      tts_auto_speak_per_chat: state.autoSpeakByChat,
      collapse_long_user_messages: state.collapseUserMsgs,
      chat_model_key: state.chatModel,
      effort_by_family: state.effortByFamily,
    }, imageDefaults ? {
      image_default_size: imageDefaults.size,
      image_default_aspect: imageDefaults.aspect_ratio,
    } : {});
  }
  function applyAppSettings(app) {
    if (!app || typeof app !== 'object') return;
    const mode = String(app.theme_mode || '').toLowerCase();
    if (['system', 'light', 'dark'].includes(mode)) setThemeMode(mode, false);
    const light = app.palette_id_light || app.palette_id;
    const dark = app.palette_id_dark || app.palette_id;
    if (light) setPalette('light', light, false);
    if (dark) setPalette('dark', dark, false);
    if (app.tts_voice) { state.ttsVoice = app.tts_voice; localStorage.setItem(LS.ttsVoice, state.ttsVoice); }
    if (typeof app.tts_auto_speak === 'boolean') { state.autoSpeak = app.tts_auto_speak; localStorage.setItem(LS.autoSpeak, String(state.autoSpeak)); }
    if (app.tts_speed) { state.ttsSpeed = Number(app.tts_speed) || 1; localStorage.setItem(LS.ttsSpeed, String(state.ttsSpeed)); }
    if (app.system_prompt_mode) { state.spMode = app.system_prompt_mode; localStorage.setItem(LS.spMode, state.spMode); }
    if (typeof app.custom_system_prompt === 'string') { state.spCustom = app.custom_system_prompt; localStorage.setItem(LS.spCustom, state.spCustom); }
    if (app.tts_auto_speak_per_chat && typeof app.tts_auto_speak_per_chat === 'object') {
      state.autoSpeakByChat = app.tts_auto_speak_per_chat;
      localStorage.setItem(LS.autoSpeakByChat, JSON.stringify(state.autoSpeakByChat));
    }
    if (typeof app.collapse_long_user_messages === 'boolean') {
      state.collapseUserMsgs = app.collapse_long_user_messages;
      localStorage.setItem(LS.collapseUserMsgs, String(state.collapseUserMsgs));
    }
    if (typeof app.chat_model_key === 'string') { state.chatModel = app.chat_model_key; localStorage.setItem(LS.chatModel, state.chatModel); }
    const byFamily = app.effort_by_family && typeof app.effort_by_family === 'object' ? app.effort_by_family : {};
    if (Object.keys(byFamily).length || app.effort) {
      // Aeltere Exporte kennen nur eine Denktiefe; sie gilt dann fuer Claude.
      state.effortByFamily = Object.assign({}, EFFORT_DEFAULTS, app.effort ? { claude: app.effort } : {}, byFamily);
      localStorage.setItem(LS.effortByFamily, JSON.stringify(state.effortByFamily));
    }
    localStorage.setItem(LS_APP_PASSTHROUGH, JSON.stringify(app));
  }
  /** Bild-Vorgaben aus dem App-Teil liegen serverseitig; einzeln setzen, damit
   *  ein unbekannter Wert nicht den ganzen Import scheitern laesst. */
  async function applyAppImageDefaults(app) {
    const failed = [];
    for (const [field, value] of [['size', app && app.image_default_size], ['aspect_ratio', app && app.image_default_aspect]]) {
      if (!value) continue;
      try { await api('PUT', '/images/defaults', { [field]: value }); }
      catch { failed.push(field); }
    }
    if (window.PocketImages) window.PocketImages.invalidate();
    return failed;
  }
  $('settings-export-btn').addEventListener('click', async () => {
    try {
      const server = await api('GET', '/settings/export');
      let imageDefaults = null;
      try { imageDefaults = (await api('GET', '/images/config')).defaults; } catch { /* ohne Bild-Vorgaben */ }
      const bundle = {
        schema_version: 1,
        exported_at: new Date().toISOString(),
        app_version: 'PocketClotWeb',
        server,
        app: webAppSettings(imageDefaults),
      };
      const ts = new Date().toISOString().replace(/[-:]/g, '').replace('T', '-').slice(0, 15);
      downloadBlob(new Blob([JSON.stringify(bundle, null, 2)], { type: 'application/json' }), `pocket-claude-settings-${ts}.json`);
      setStatus('settings-backup-status', t('settings_export_done'), 'ok');
    } catch (e) { setStatus('settings-backup-status', t('toast_error_prefix', apiErrorText(e)), 'error'); }
  });
  $('settings-import-btn').addEventListener('click', () => $('settings-file-input').click());
  $('settings-file-input').addEventListener('change', async (e) => {
    const file = e.target.files[0];
    e.target.value = '';
    if (!file) return;
    try {
      const bundle = JSON.parse(await file.text());
      // Akzeptiert die kombinierte Datei (App/Web) und einen reinen Server-Export.
      const server = bundle.server && typeof bundle.server === 'object' ? bundle.server : bundle;
      const ok = await showConfirm({ title: t('settings_import_title'), text: t('settings_import_confirm'), okLabel: t('backup_import') });
      if (!ok) return;
      const req = { schema_version: server.schema_version || 1 };
      for (const k of ['tts_provider', 'tts_chunking_enabled', 'image_api_key', 'skills_defaults', 'extra_kv']) {
        if (server[k] !== undefined && server[k] !== null) req[k] = server[k];
      }
      const r = await api('POST', '/settings/import', req);
      await loadServerSettings();
      let imageFailed = [];
      if (bundle.app) {
        applyAppSettings(bundle.app);
        imageFailed = await applyAppImageDefaults(bundle.app);
      }
      await pushSettingsToServer();
      applyTheme();
      updateModelButton();
      renderModelMenu();
      const applied = typeof r.applied_keys === 'number' ? r.applied_keys : (r.applied_keys || []).length;
      const msg = t('settings_import_done', applied, r.tts_keys_imported || 0)
        + (imageFailed.length ? ' ' + t('settings_import_partial', imageFailed.join(', ')) : '');
      setStatus('settings-backup-status', msg, imageFailed.length ? 'error' : 'ok');
    } catch (err) {
      setStatus('settings-backup-status', t('settings_import_failed', err instanceof SyntaxError ? t('settings_import_bad_json') : apiErrorText(err)), 'error');
    }
  });

  // =========================================================
  // Benutzer (nur Admin)
  // =========================================================
  async function loadUsersList() {
    if (!(state.me && state.me.is_admin)) return;
    const wrap = $('users-list');
    try {
      const r = await api('GET', '/users');
      wrap.innerHTML = '';
      for (const u of r.users) {
        const row = document.createElement('div');
        row.className = 'user-row';
        row.innerHTML = `<span class="name"></span>
          ${u.is_admin ? `<span class="badge">${escapeHtml(t('admin_label'))}</span>` : ''}
          ${u.must_change_password ? `<span class="badge warn" title="${escapeHtml(t('user_pw_reset_due_title'))}">${escapeHtml(t('user_pw_reset_due'))}</span>` : ''}
          <span class="user-spacer"></span>
          <span class="actions">
            <button class="icon-btn" data-act="rename" title="${escapeHtml(t('user_rename'))}"><svg class="icon"><use href="#icon-edit"/></svg></button>
            <button class="icon-btn" data-act="avatar" title="${escapeHtml(t('avatar_choose'))}"><svg class="icon"><use href="#icon-add-photo"/></svg></button>
            <button class="icon-btn" data-act="reset" title="${escapeHtml(t('reset_password_title'))}"><svg class="icon"><use href="#icon-key"/></svg></button>
            ${u.id === state.me.id ? '' : `<button class="icon-btn" data-act="delete" title="${escapeHtml(t('delete'))}"><svg class="icon"><use href="#icon-trash"/></svg></button>`}
          </span>`;
        row.querySelector('.name').textContent = u.name;
        row.prepend(avatarEl(u));
        row.querySelector('[data-act="avatar"]').addEventListener('click', () => pickAvatar(u.id));
        row.querySelector('[data-act="rename"]').addEventListener('click', async () => {
          const name = await showPrompt({ title: t('user_rename'), text: t('user_rename_prompt', u.name), type: 'text', value: u.name, okLabel: t('save') });
          if (name === null || !name.trim() || name.trim() === u.name) return;
          try {
            const updated = await api('PATCH', '/users/' + u.id, { name: name.trim() });
            if (state.me && updated.id === state.me.id) {
              state.me = Object.assign({}, state.me, updated);
              renderFooterUser();
            }
            await loadUsersList();
          } catch (e) { toast(t('toast_error_prefix', apiErrorText(e)), { error: true }); }
        });
        row.querySelector('[data-act="reset"]').addEventListener('click', async () => {
          const custom = await showPrompt({ title: t('reset_password_title'), text: t('user_reset_pw_prompt', u.name), type: 'text', okLabel: t('ok') });
          if (custom === null) return;
          try {
            const resp = await api('POST', '/users/' + u.id + '/reset-password', custom.trim() ? { password: custom.trim() } : {});
            await loadUsersList();
            try { await navigator.clipboard.writeText(resp.new_password); } catch {}
            await openDialog({ title: t('reset_password_title'), text: t('user_reset_pw_alert', u.name, resp.new_password), actions: [{ label: t('ok'), kind: 'btn-primary', value: true }] });
          } catch (e) { toast(t('toast_reset_failed', apiErrorText(e)), { error: true }); }
        });
        row.querySelector('[data-act="delete"]')?.addEventListener('click', async () => {
          if (!(await showConfirm({ title: t('delete'), text: t('confirm_delete_user', u.name), okLabel: t('delete'), danger: true }))) return;
          try { await api('DELETE', '/users/' + u.id); await loadUsersList(); toast(t('toast_deleted')); }
          catch (e) { toast(t('toast_delete_failed', apiErrorText(e)), { error: true }); }
        });
        wrap.appendChild(row);
      }
    } catch (e) { toast(t('toast_user_list_failed', apiErrorText(e)), { error: true }); }
  }
  $('new-user-btn').addEventListener('click', async () => {
    const name = $('new-user-name').value.trim();
    const pw = $('new-user-password').value.trim();
    if (!name) return;
    if (pw && pw.length < 8) { toast(t('toast_password_min_chars'), { error: true }); return; }
    try {
      const body = { name, is_admin: $('new-user-admin').checked };
      if (pw) body.password = pw;
      const u = await api('POST', '/users', body);
      $('new-user-name').value = ''; $('new-user-password').value = ''; $('new-user-admin').checked = false;
      await loadUsersList();
      if (u.initial_password) {
        try { await navigator.clipboard.writeText(u.initial_password); } catch {}
        setStatus('new-user-result', t('user_create_success_plain', name, u.initial_password), 'ok');
      } else {
        setStatus('new-user-result', t('user_create_success_no_pw', name), 'ok');
      }
    } catch (e) { setStatus('new-user-result', t('user_create_failed', apiErrorText(e)), 'error'); }
  });

  // =========================================================
  // Ueber
  // =========================================================
  async function loadAbout() {
    try {
      const h = await api('GET', '/health');
      $('about-version').textContent = t('about_version', h.version || '?');
    } catch { $('about-version').textContent = '—'; }
  }

  const paneLoaders = {
    general: loadGeneral,
    models: loadModels,
    skills: loadSkills,
    tts: loadTts,
    images: loadImageDefaults,
    privacy: () => { loadChatLockStatus(); loadMemoryKeyStatus(); },
    account: loadAccount,
    connection: loadClaudeAuth,
    usage: loadUsage,
    users: loadUsersList,
    about: loadAbout,
  };
  document.addEventListener('pc:locale-changed', () => {
    if (!modal.classList.contains('hidden')) paneLoaders[currentPane]?.();
  });
})();
