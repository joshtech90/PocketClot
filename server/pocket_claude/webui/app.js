// =====================================================================
// PocketClot Web-UI — Kern: Anmeldung, Seitenleiste, Chat, Eingabefeld.
// Weitere Teile in eigenen Dateien (gleiche globale Helfer):
//   voice.js    Diktat und Sprachgespraech
//   gems.js     eigene Assistenten
//   images.js   Bilder-Bereich
//   settings.js Einstellungen
// =====================================================================
// PC_SSE LOAD MARKER — bump this any time you change PC_SSE logging.
console.log('PC_SSE: app.js LOADED build=2026-10-21-desktop');
// Kurzform fuer die Uebersetzung.
const t = (k, ...args) => (window.PocketI18n ? window.PocketI18n.t(k, ...args) : k);

const LS = {
  url:        'pc.serverUrl',
  token:      'pc.serverToken',
  theme:      'pc.theme',          // system | light | dark
  paletteLight: 'pc.paletteLight',
  paletteDark:  'pc.paletteDark',
  effort:     'pc.effort',
  lastCid:    'pc.lastCid',
  spMode:     'pc.spMode',
  spCustom:   'pc.spCustom',
  ttsVoice:   'pc.ttsVoice',
  ttsSpeed:   'pc.ttsSpeed',
  autoSpeak:  'pc.autoSpeak',
  autoSpeakByChat: 'pc.autoSpeakByChat',
  sidebar:    'pc.sidebarCollapsed',
  collapseUserMsgs: 'pc.collapseUserMsgs',
  chatModel:      'pc.chatModel',
  effortByFamily: 'pc.effortByFamily',
};

// Vorgaben wie in der App: hell Nordic Blue, dunkel Midnight Atelier.
const PALETTES = [
  { id: 'midnight_atelier', name: 'Midnight Atelier' },
  { id: 'nordic_blue',      name: 'Nordic Blue' },
  { id: 'forest_sage',      name: 'Forest Sage' },
  { id: 'plum_dusk',        name: 'Plum Dusk' },
  { id: 'graphite_mono',    name: 'Graphite Mono' },
  { id: 'chatgpt',          name: 'ChatGPT' },
];
const DEFAULT_PALETTE = { light: 'nordic_blue', dark: 'midnight_atelier' };

const EFFORT_ORDER = ['off', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra'];
const CLAUDE_EFFORTS = ['off', 'low', 'medium', 'high', 'xhigh', 'max'];
const EFFORT_DEFAULTS = { claude: 'high', gemini: 'high', gpt: 'high', other: 'high' };
// Wie in der App: Anhaenge bis 50 MB, hoechstens zwei Uploads gleichzeitig,
// hoechstens zehn Fotos auf einmal.
const MAX_UPLOAD_BYTES = 50 * 1024 * 1024;
const MAX_PARALLEL_UPLOADS = 2;
const MAX_PICK = 10;

function readJson(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return fallback;
    const v = JSON.parse(raw);
    return v && typeof v === 'object' ? v : fallback;
  } catch { return fallback; }
}
function legacyThemeMode() {
  const v = localStorage.getItem(LS.theme);
  return v === 'light' || v === 'dark' ? v : 'system';
}

const state = {
  serverUrl: localStorage.getItem(LS.url)   || '',
  token:     localStorage.getItem(LS.token) || '',
  themeMode: legacyThemeMode(),
  paletteLight: localStorage.getItem(LS.paletteLight) || DEFAULT_PALETTE.light,
  paletteDark:  localStorage.getItem(LS.paletteDark)  || DEFAULT_PALETTE.dark,
  effort:    localStorage.getItem(LS.effort) || 'high',
  // Globale Modell-Vorauswahl: damit starten neue Chats. "" = Claude-Automatik.
  chatModel: localStorage.getItem(LS.chatModel) || '',
  // Modell des offenen Chats (vom Server). null = folgt der Vorauswahl.
  convModel: null,
  effortByFamily: Object.assign({}, EFFORT_DEFAULTS, readJson(LS.effortByFamily, {})),
  chatModels: [],
  gateways:   [],
  spMode:    localStorage.getItem(LS.spMode)   || 'STANDARD',
  spCustom:  localStorage.getItem(LS.spCustom) || '',
  ttsVoice:  localStorage.getItem(LS.ttsVoice) || 'edge-de-DE-KatjaNeural',
  ttsSpeed:  parseFloat(localStorage.getItem(LS.ttsSpeed) || '1.0') || 1.0,
  autoSpeak: localStorage.getItem(LS.autoSpeak) === 'true',
  autoSpeakByChat: readJson(LS.autoSpeakByChat, {}),
  collapseUserMsgs: (localStorage.getItem(LS.collapseUserMsgs) ?? 'true') !== 'false',

  me: null,
  view: 'chat',            // chat | images
  cid: null,
  title: 'PocketClot',
  pinned: false,
  chatLocked: false,
  unlockedCids: new Set(), // nur in dieser Sitzung entsperrt, bewusst nicht gespeichert
  gem: null,
  gems: [],
  chats: [],               // Liste aus GET /conversations
  _allCids: [],
  messages: [],
  skills: null,            // effektive Skills des offenen Chats
  skillsIsOverride: false,

  isStreaming: false,
  streamingText: '',
  streamingThinking: '',
  _streamAttachments: [],
  abort: null,
  stoppedByUser: false,

  pending: [],             // Anhaenge im Eingabefeld
  imageMode: false,
  audio: { msgId: null, status: 'idle' },  // idle | loading | playing | paused
};

// =========================================================
// DOM-Refs
// =========================================================
const $ = (id) => document.getElementById(id);
const els = {
  login:        $('login'),
  app:          $('app'),
  main:         $('main'),
  sidebar:      $('sidebar'),
  sidebarScrim: $('sidebar-scrim'),
  sidebarToggle: $('sidebar-toggle'),
  sidebarOpen:  $('sidebar-open'),
  chatNav:      $('chat-nav'),
  newChatBtn:   $('new-chat-btn'),
  headerNewChat: $('header-new-chat'),
  sbBrand:      $('sb-brand'),
  sbSearchBtn:  $('sb-search-btn'),
  imagesBtn:    $('images-btn'),
  footerUser:   $('footer-user'),
  profileMenu:  $('profile-menu'),
  topbar:       $('topbar'),
  topbarTitle:  $('chat-title'),
  effortBtn:    $('effort-btn'),
  effortLabel:  $('effort-label'),
  modelLabel:   $('model-label'),
  effortMenu:   $('effort-menu'),
  shareBtn:     $('share-btn'),
  moreBtn:      $('more-btn'),
  moreMenu:     $('more-menu'),
  chatView:     $('chat-view'),
  imagesView:   $('images-view'),
  messages:     $('messages'),
  scrollDown:   $('scroll-down-btn'),
  inputForm:    $('input-form'),
  input:        $('input'),
  sendBtn:      $('send-btn'),
  attachBtn:    $('attach-btn'),
  plusMenu:     $('plus-menu'),
  imageChip:    $('image-chip'),
  fileInput:    $('file-input'),
  photoInput:   $('photo-input'),
  cameraInput:  $('camera-input'),
  pendingWrap:  $('pending-attachments'),
  composerHint: $('composer-hint'),
  audio:        $('audio-player'),
  searchModal:  $('search-modal'),
  searchInput:  $('search-input'),
  searchResults: $('search-results'),
  searchBar:    $('chat-search-bar'),
  searchBarInput: $('chat-search-input'),
  searchBarCount: $('chat-search-count'),
  settingsModal: $('settings-modal'),
  promptModal:  $('prompt-modal'),
  promptTitle:  $('prompt-title'),
  promptText:   $('prompt-text'),
  promptInput:  $('prompt-input'),
  promptOk:     $('prompt-ok'),
  promptCancel: $('prompt-cancel'),
  toast:        $('toast'),
};
const isMobile = () => window.matchMedia('(max-width: 768px)').matches;

// =========================================================
// Hell/Dunkel und Farbschema
// =========================================================
const darkQuery = window.matchMedia('(prefers-color-scheme: dark)');
function resolvedDark() {
  return state.themeMode === 'dark' || (state.themeMode === 'system' && darkQuery.matches);
}
function applyTheme() {
  const dark = resolvedDark();
  const root = document.documentElement;
  root.dataset.theme = dark ? 'dark' : 'light';
  root.dataset.palette = dark ? state.paletteDark : state.paletteLight;
  // Browserleiste (Handy, PWA) in der Hintergrundfarbe
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute('content', getComputedStyle(root).getPropertyValue('--bg').trim() || '#100E14');
  document.querySelectorAll('[data-theme-mode]').forEach((b) => {
    b.classList.toggle('active', b.dataset.themeMode === state.themeMode);
  });
}
function setThemeMode(mode, persist = true) {
  state.themeMode = ['light', 'dark'].includes(mode) ? mode : 'system';
  localStorage.setItem(LS.theme, state.themeMode);
  applyTheme();
  if (persist) queueSettingsPush();
}
function setPalette(mode, id, persist = true) {
  if (!PALETTES.some((p) => p.id === id)) return;
  if (mode === 'dark') { state.paletteDark = id; localStorage.setItem(LS.paletteDark, id); }
  else { state.paletteLight = id; localStorage.setItem(LS.paletteLight, id); }
  applyTheme();
  if (persist) queueSettingsPush();
}
darkQuery.addEventListener?.('change', applyTheme);
document.querySelectorAll('[data-theme-mode]').forEach((b) => {
  b.addEventListener('click', () => setThemeMode(b.dataset.themeMode));
});
applyTheme();

// =========================================================
// Hinweis-Leiste
// =========================================================
let toastTimer;
function toast(msg, opts = {}) {
  els.toast.textContent = msg;
  els.toast.className = 'toast' + (opts.error ? ' error' : '');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => els.toast.classList.add('hidden'), opts.duration || (opts.error ? 5000 : 2600));
}

// =========================================================
// Hilfen
// =========================================================
function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, (m) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[m]));
}
function formatBytes(n) {
  if (!n && n !== 0) return '';
  if (n < 1024) return n + ' B';
  if (n < 1024 * 1024) return Math.round(n / 1024) + ' KB';
  return (n / 1024 / 1024).toFixed(1) + ' MB';
}
function fileExt(name) {
  const m = /\.([a-z0-9]{1,6})$/i.exec(name || '');
  return m ? m[1].toUpperCase() : '';
}
function isImageMime(m) { return (m || '').startsWith('image/'); }

marked.setOptions({ breaks: true, gfm: true });
function renderMarkdown(text) {
  if (!text) return '';
  return DOMPurify.sanitize(marked.parse(text), { ADD_ATTR: ['target'] });
}

/** Nach jedem Rendern: Codebloecke bekommen Kopfzeile mit Sprache und
 *  Kopieren, Tabellen einen eigenen Rollbalken, Links ein neues Fenster. */
function enhanceContent(root) {
  for (const pre of root.querySelectorAll('pre')) {
    if (pre.parentElement?.classList.contains('codeblock')) continue;
    const code = pre.querySelector('code');
    if (!code) continue;
    let lang = '';
    for (const cls of code.classList) if (cls.startsWith('language-')) { lang = cls.slice(9); break; }
    const wrap = document.createElement('div');
    wrap.className = 'codeblock';
    const header = document.createElement('div');
    header.className = 'codeblock-header';
    header.innerHTML = `
      <span class="codeblock-lang">${escapeHtml(lang || 'code')}</span>
      <button type="button" class="codeblock-copy">
        <svg class="icon icon-sm"><use href="#icon-copy"/></svg><span>${escapeHtml(t('copy'))}</span>
      </button>`;
    pre.parentNode.insertBefore(wrap, pre);
    wrap.appendChild(header);
    wrap.appendChild(pre);
    header.querySelector('.codeblock-copy').addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(code.textContent || '');
        const lbl = header.querySelector('.codeblock-copy span');
        lbl.textContent = t('toast_copied');
        setTimeout(() => { lbl.textContent = t('copy'); }, 1200);
      } catch { toast(t('toast_copy_failed'), { error: true }); }
    });
  }
  for (const table of root.querySelectorAll('table')) {
    if (table.parentElement?.classList.contains('table-wrap')) continue;
    const w = document.createElement('div');
    w.className = 'table-wrap';
    table.parentNode.insertBefore(w, table);
    w.appendChild(table);
  }
  for (const a of root.querySelectorAll('a[href]')) {
    const href = a.getAttribute('href') || '';
    if (/^https?:/i.test(href)) { a.target = '_blank'; a.rel = 'noopener noreferrer'; }
  }
}

// =========================================================
// API
// =========================================================
class ApiError extends Error {
  constructor(status, body) { super(`HTTP ${status}: ${body}`); this.status = status; this.body = body; }
}
async function api(method, path, body, opts = {}) {
  const url = state.serverUrl + path;
  const headers = { 'Authorization': 'Bearer ' + state.token };
  let bodyData = body;
  if (body && !(body instanceof FormData) && !(body instanceof Blob)) {
    headers['Content-Type'] = 'application/json';
    bodyData = JSON.stringify(body);
  }
  const resp = await fetch(url, { method, headers, body: bodyData, ...opts });
  if (!resp.ok) {
    const txt = await resp.text().catch(() => '');
    throw new ApiError(resp.status, txt || resp.statusText);
  }
  if (resp.status === 204) return null;
  const ct = resp.headers.get('content-type') || '';
  return ct.includes('application/json') ? resp.json() : resp.text();
}
/** Lesbarer Fehlertext: FastAPI schickt {"detail": "..."}, das soll nicht roh erscheinen. */
function apiErrorText(e) {
  if (e instanceof ApiError) {
    try {
      const j = JSON.parse(e.body);
      if (typeof j.detail === 'string') return j.detail;
      if (Array.isArray(j.detail)) return j.detail.map((d) => d.msg || JSON.stringify(d)).join('; ');
    } catch { /* kein JSON */ }
    return String(e.body || `HTTP ${e.status}`).slice(0, 300);
  }
  return (e && e.message) || String(e);
}
function attachmentUrl(id) {
  return `${state.serverUrl}/attachments/${encodeURIComponent(id)}?token=${encodeURIComponent(state.token)}`;
}
async function uploadFile(blob, filename) {
  const fd = new FormData();
  fd.append('file', blob, filename);
  return api('POST', '/attachments', fd);
}

/** Bilder vor dem Upload verkleinern, zwei Profile wie ImageCompressor der App:
 *  'vision' fuer Anhaenge, die ein Modell nur liest, 'edit' fuer Vorlagen, die
 *  bearbeitet werden (dort begrenzt die Vorlage die Qualitaet des Ergebnisses). */
const COMPRESS = {
  vision: { edge: 1568, quality: 0.85, keepBelow: 200 * 1024, keepMax: 1_500_000 },
  edit:   { edge: 2560, quality: 0.92, keepBelow: 400 * 1024, keepMax: 2_500_000 },
};
async function compressImage(file, profile = 'vision') {
  const p = COMPRESS[profile] || COMPRESS.vision;
  const name = file.name || 'bild.jpg';
  if (!isImageMime(file.type) || file.type === 'image/gif' || file.size <= p.keepBelow) {
    return { blob: file, filename: name };
  }
  try {
    const bmp = await createImageBitmap(file, { imageOrientation: 'from-image' });
    const longest = Math.max(bmp.width, bmp.height);
    if (longest <= p.edge && file.size <= p.keepMax) { bmp.close(); return { blob: file, filename: name }; }
    const scale = Math.min(1, p.edge / longest);
    const w = Math.round(bmp.width * scale), h = Math.round(bmp.height * scale);
    const canvas = document.createElement('canvas');
    canvas.width = w; canvas.height = h;
    canvas.getContext('2d').drawImage(bmp, 0, 0, w, h);
    bmp.close();
    const blob = await new Promise((r) => canvas.toBlob(r, 'image/jpeg', p.quality));
    if (!blob) return { blob: file, filename: name };
    return { blob, filename: name.replace(/\.[^.]+$/, '') + '.jpg' };
  } catch {
    return { blob: file, filename: name };
  }
}

// =========================================================
// Dialoge und Popups
// =========================================================
/** Kleiner Dialog: Titel, Text, beliebiger Inhalt, Knoepfe. Liefert den
 *  `value` des gedrueckten Knopfs, bei Abbruch null. */
function openDialog({ title, icon, text, body, actions, wide = false, onMount }) {
  return new Promise((resolve) => {
    const wrap = document.createElement('div');
    wrap.className = 'modal';
    wrap.innerHTML = `
      <div class="modal-card ${wide ? '' : 'small'}" role="dialog" aria-modal="true">
        <div class="modal-header">
          ${icon ? `<svg class="icon dlg-icon"><use href="#icon-${icon}"/></svg>` : ''}
          <h2 style="flex:1"></h2>
        </div>
        <div class="modal-body"></div>
        <div class="modal-footer"></div>
      </div>`;
    wrap.querySelector('h2').textContent = title || '';
    const bodyEl = wrap.querySelector('.modal-body');
    if (text) {
      const p = document.createElement('p');
      p.className = 'dlg-text';
      p.textContent = text;
      bodyEl.appendChild(p);
    }
    if (body) bodyEl.appendChild(body);
    if (!text && !body) bodyEl.remove();
    const foot = wrap.querySelector('.modal-footer');
    let done = false;
    const close = (v) => {
      if (done) return;
      done = true;
      wrap.remove();
      document.removeEventListener('keydown', onKey, true);
      resolve(v);
    };
    for (const a of actions || []) {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = a.kind || 'btn-ghost';
      b.textContent = a.label;
      b.addEventListener('click', () => close(typeof a.value === 'function' ? a.value() : a.value));
      foot.appendChild(b);
    }
    const onKey = (e) => { if (e.key === 'Escape') { e.stopPropagation(); close(null); } };
    document.addEventListener('keydown', onKey, true);
    wrap.addEventListener('mousedown', (e) => { if (e.target === wrap) close(null); });
    document.body.appendChild(wrap);
    if (onMount) onMount(wrap, close);
    const primary = foot.querySelector('.btn-primary, .btn-danger');
    if (primary && !wrap.querySelector('input, textarea')) primary.focus();
  });
}
async function showConfirm({ title, text, okLabel, danger = false }) {
  const v = await openDialog({
    title, text,
    actions: [
      { label: t('cancel'), value: false },
      { label: okLabel || t('ok'), kind: danger ? 'btn-danger' : 'btn-primary', value: true },
    ],
  });
  return v === true;
}
/** Eingabe-Dialog (Passwort, PIN, Name). Liefert den Text oder null. */
function showPrompt({ title, text, placeholder = '', type = 'password', okLabel = 'OK', value = '' }) {
  return new Promise((resolve) => {
    els.promptTitle.textContent = title;
    els.promptText.textContent = text || '';
    els.promptText.classList.toggle('hidden', !text);
    els.promptInput.type = type;
    els.promptInput.placeholder = placeholder;
    els.promptInput.value = value;
    els.promptOk.textContent = okLabel;
    els.promptModal.classList.remove('hidden');
    setTimeout(() => { els.promptInput.focus(); els.promptInput.select(); }, 30);
    const close = (val) => {
      els.promptModal.classList.add('hidden');
      els.promptOk.onclick = null;
      els.promptCancel.onclick = null;
      els.promptInput.onkeydown = null;
      resolve(val);
    };
    els.promptOk.onclick = () => close(els.promptInput.value);
    els.promptCancel.onclick = () => close(null);
    els.promptInput.onkeydown = (e) => {
      if (e.key === 'Enter') { e.preventDefault(); close(els.promptInput.value); }
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(null); }
    };
  });
}

// Immer nur ein Popup-Menue offen. Klick daneben oder Escape schliesst es.
let openPopup = null;
function showPopup(el, anchor, onClose) {
  closePopup();
  el.classList.remove('hidden');
  if (anchor) anchor.setAttribute('aria-expanded', 'true');
  openPopup = { el, anchor, onClose };
}
function closePopup() {
  if (!openPopup) return;
  const p = openPopup;
  openPopup = null;
  if (p.el.isConnected) {
    if (p.el.dataset.transient === '1') p.el.remove();
    else p.el.classList.add('hidden');
  }
  if (p.anchor) p.anchor.setAttribute('aria-expanded', 'false');
  document.querySelectorAll('.chat-item.menu-open').forEach((r) => r.classList.remove('menu-open'));
  if (p.onClose) p.onClose();
}
function togglePopup(el, anchor, onOpen) {
  if (openPopup && openPopup.el === el) { closePopup(); return false; }
  if (onOpen) onOpen();
  showPopup(el, anchor);
  return true;
}
document.addEventListener('pointerdown', (e) => {
  if (!openPopup) return;
  if (openPopup.el.contains(e.target)) return;
  if (openPopup.anchor && openPopup.anchor.contains(e.target)) return;
  closePopup();
});
window.addEventListener('resize', closePopup);

/** Menueeintrag fuer dynamisch gebaute Menues. */
function menuButton({ icon, label, trail, trailOn, danger, disabled, onClick }) {
  const b = document.createElement('button');
  b.type = 'button';
  b.setAttribute('role', 'menuitem');
  if (danger) b.classList.add('danger');
  if (disabled) b.disabled = true;
  b.innerHTML = `${icon ? `<svg class="icon"><use href="#icon-${icon}"/></svg>` : ''}<span class="label"></span>` +
    (trail ? `<span class="trail${trailOn ? ' on' : ''}"></span>` : '');
  b.querySelector('.label').textContent = label;
  if (trail) b.querySelector('.trail').textContent = trail;
  b.addEventListener('click', () => { closePopup(); onClick && onClick(); });
  return b;
}
function menuSep() { const d = document.createElement('div'); d.className = 'menu-sep'; return d; }

// =========================================================
// Anmeldung
// =========================================================
$('login-form').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const url = $('login-url').value.trim().replace(/\/+$/, '');
  const username = $('login-username').value.trim();
  const password = $('login-password').value;
  const $st = $('login-status');
  if (!url || !username || !password) {
    $st.className = 'login-status error';
    $st.textContent = t('login_url_required');
    return;
  }
  $st.className = 'login-status';
  $st.textContent = t('login_signing_in');
  try {
    const resp = await fetch(url + '/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    if (resp.status === 401) throw new Error(t('login_bad_credentials'));
    if (!resp.ok) {
      const txt = await resp.text().catch(() => '');
      throw new Error('HTTP ' + resp.status + ': ' + txt.slice(0, 200));
    }
    const data = await resp.json();
    state.serverUrl = url;
    state.token = data.token;
    state.me = data.user;
    localStorage.setItem(LS.url, url);
    localStorage.setItem(LS.token, data.token);
    $st.className = 'login-status ok';
    $st.textContent = t('login_signed_in');
    if (data.user && data.user.must_change_password) {
      $('login-password').value = '';
      openPasswordChange({ forced: true });
    } else {
      setTimeout(showApp, 150);
    }
  } catch (e) {
    $st.className = 'login-status error';
    $st.textContent = t('login_failed', e.message);
  }
});

async function logout() {
  if (!(await showConfirm({ title: t('logout_title'), text: t('confirm_logout_session'), okLabel: t('logout_title') }))) return;
  try { await api('POST', '/auth/logout'); } catch (_) { /* Token evtl. schon ungueltig */ }
  localStorage.removeItem(LS.token);
  wissenVergessen();
  state.token = '';
  state.cid = null;
  location.hash = '';
  location.reload();
}

// Passwort aendern: Pflicht nach erstem Login oder aus den Einstellungen
let _pwChangeForced = false;
function openPasswordChange({ forced = false } = {}) {
  _pwChangeForced = !!forced;
  $('pwchange-title').textContent = forced ? t('pwchange_title_set_now') : t('change_password');
  $('pwchange-text').textContent = forced ? t('pwchange_text_forced') : t('pwchange_text_normal');
  $('pwchange-old-field').style.display = forced ? 'none' : '';
  $('pwchange-old').value = '';
  $('pwchange-new').value = '';
  $('pwchange-new2').value = '';
  $('pwchange-cancel').style.display = forced ? 'none' : '';
  $('pwchange-status').textContent = '';
  $('pwchange-status').className = 'login-status';
  $('pwchange-modal').classList.remove('hidden');
  setTimeout(() => ($(forced ? 'pwchange-new' : 'pwchange-old')).focus(), 100);
}
function closePasswordChange() { $('pwchange-modal').classList.add('hidden'); }
$('pwchange-cancel').addEventListener('click', () => { if (!_pwChangeForced) closePasswordChange(); });
$('pwchange-form').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const oldPw = $('pwchange-old').value;
  const newPw = $('pwchange-new').value;
  const newPw2 = $('pwchange-new2').value;
  const $st = $('pwchange-status');
  if (newPw.length < 8) { $st.className = 'login-status error'; $st.textContent = t('pwchange_min_chars'); return; }
  if (newPw !== newPw2) { $st.className = 'login-status error'; $st.textContent = t('pwchange_mismatch'); return; }
  $st.className = 'login-status'; $st.textContent = t('pwchange_saving');
  try {
    const body = _pwChangeForced ? { new_password: newPw } : { old_password: oldPw, new_password: newPw };
    await api('POST', '/auth/change-password', body);
    $st.className = 'login-status ok'; $st.textContent = t('pwchange_done');
    if (state.me) state.me.must_change_password = false;
    setTimeout(() => {
      closePasswordChange();
      if (_pwChangeForced) { _pwChangeForced = false; showApp(); }
      else toast(t('toast_password_changed'));
    }, 250);
  } catch (e) {
    $st.className = 'login-status error';
    $st.textContent = t('pwchange_error_prefix', apiErrorText(e));
  }
});

// =========================================================
// Einstellungen auf dem Server: jeder Browser sieht dieselben Werte.
// localStorage bleibt Zwischenspeicher fuer den Start vor dem Login.
// =========================================================
let _settingsPushTimer = null;
function boolFrom(v) { return v === true || v === 'true' || v === '1'; }

async function loadServerSettings() {
  try {
    const resp = await api('GET', '/ui-settings');
    const s = resp.settings || {};
    if (['system', 'light', 'dark'].includes(s.theme)) setThemeMode(s.theme, false);
    if (s.paletteLight) setPalette('light', s.paletteLight, false);
    if (s.paletteDark) setPalette('dark', s.paletteDark, false);
    if (s.effort) { localStorage.setItem(LS.effort, s.effort); state.effort = s.effort; }
    if (s.spMode) { localStorage.setItem(LS.spMode, s.spMode); state.spMode = s.spMode; }
    if (s.spCustom !== undefined) { localStorage.setItem(LS.spCustom, s.spCustom); state.spCustom = s.spCustom; }
    if (s.ttsVoice) { localStorage.setItem(LS.ttsVoice, s.ttsVoice); state.ttsVoice = s.ttsVoice; }
    if (s.ttsSpeed) { localStorage.setItem(LS.ttsSpeed, s.ttsSpeed); state.ttsSpeed = parseFloat(s.ttsSpeed) || 1.0; }
    if (s.autoSpeak !== undefined) { state.autoSpeak = boolFrom(s.autoSpeak); localStorage.setItem(LS.autoSpeak, String(state.autoSpeak)); }
    if (s.collapseUserMsgs !== undefined) {
      state.collapseUserMsgs = boolFrom(s.collapseUserMsgs);
      localStorage.setItem(LS.collapseUserMsgs, String(state.collapseUserMsgs));
    }
    if (s.autoSpeakByChat) {
      try {
        const m = JSON.parse(s.autoSpeakByChat);
        if (m && typeof m === 'object') { state.autoSpeakByChat = m; localStorage.setItem(LS.autoSpeakByChat, JSON.stringify(m)); }
      } catch { /* kaputter Eintrag: lokalen Stand behalten */ }
    }
    if (s.sidebar) {
      localStorage.setItem(LS.sidebar, s.sidebar);
      if (!isMobile()) els.app.classList.toggle('sidebar-collapsed', s.sidebar === '1');
    }
    if (s.chatModel !== undefined) { localStorage.setItem(LS.chatModel, s.chatModel); state.chatModel = s.chatModel; }
    if (s.effortByFamily !== undefined) {
      try {
        const parsed = typeof s.effortByFamily === 'string' ? JSON.parse(s.effortByFamily) : s.effortByFamily;
        if (parsed && typeof parsed === 'object') {
          state.effortByFamily = Object.assign({}, EFFORT_DEFAULTS, parsed);
          localStorage.setItem(LS.effortByFamily, JSON.stringify(state.effortByFamily));
        }
      } catch (e) { console.log('effortByFamily unlesbar:', e.message); }
    }
  } catch (e) {
    console.log('Server-Settings nicht abrufbar:', e.message);
  }
}
function queueSettingsPush() {
  clearTimeout(_settingsPushTimer);
  _settingsPushTimer = setTimeout(pushSettingsToServer, 600);
}
async function pushSettingsToServer() {
  if (!state.token) return;
  const payload = {
    theme: state.themeMode,
    paletteLight: state.paletteLight,
    paletteDark: state.paletteDark,
    effort: state.effort,
    spMode: state.spMode,
    spCustom: state.spCustom,
    ttsVoice: state.ttsVoice,
    ttsSpeed: String(state.ttsSpeed),
    autoSpeak: String(state.autoSpeak),
    autoSpeakByChat: JSON.stringify(state.autoSpeakByChat),
    collapseUserMsgs: String(state.collapseUserMsgs),
    sidebar: localStorage.getItem(LS.sidebar) || '0',
    chatModel: state.chatModel,
    effortByFamily: JSON.stringify(state.effortByFamily),
  };
  try { await api('PUT', '/ui-settings', payload); }
  catch (e) { console.log('Settings-Push fehlgeschlagen:', e.message); }
}

// =========================================================
// Start und Navigation (#/chat/<id>, #/images)
// =========================================================
function routeFromHash() {
  if (/^#\/images\b/.test(location.hash)) return { view: 'images' };
  const m = location.hash.match(/^#\/chat\/([^/?]+)/);
  return { view: 'chat', cid: m ? decodeURIComponent(m[1]) : null };
}

async function showApp() {
  els.login.classList.add('hidden');
  els.app.classList.remove('hidden');
  try {
    state.me = await api('GET', '/me');
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) return showLogin();
    state.me = null;
  }
  renderFooterUser();
  applyAdminVisibility();
  await loadServerSettings();
  applyTheme();
  await loadChatModels(false);
  if (window.PocketGems) window.PocketGems.load();
  await refreshChatList();
  const r = routeFromHash();
  if (r.view === 'images') { showImagesView(); return; }
  if (r.cid && state._allCids.includes(r.cid)) openChat(r.cid, { fromHash: true });
  else newChat();
}

window.addEventListener('hashchange', () => {
  const r = routeFromHash();
  if (r.view === 'images') { if (state.view !== 'images') showImagesView(); return; }
  if (state.view !== 'chat') showChatView();
  if (r.cid && r.cid !== state.cid && state._allCids.includes(r.cid)) openChat(r.cid, { fromHash: true });
});

function showLogin() {
  $('login-url').value = state.serverUrl || location.origin;
  els.login.classList.remove('hidden');
  els.app.classList.add('hidden');
}

function showChatView() {
  state.view = 'chat';
  els.main.classList.remove('images-mode');
  els.chatView.classList.remove('hidden');
  els.imagesView.classList.add('hidden');
  els.imagesBtn.classList.remove('active');
  if (window.PocketImages) window.PocketImages.hide();
  markActiveChat();
  updateTopbar();
}
function showImagesView() {
  closeChatSearch();
  state.view = 'images';
  els.main.classList.add('images-mode');
  els.chatView.classList.add('hidden');
  els.imagesView.classList.remove('hidden');
  els.imagesBtn.classList.add('active');
  document.querySelectorAll('.chat-item.active').forEach((el) => el.classList.remove('active'));
  if (location.hash !== '#/images') history.replaceState(null, '', '#/images');
  document.title = t('nav_images') + ' · PocketClot';
  els.topbar.classList.remove('scrolled');
  if (isMobile()) closeSidebar();
  if (window.PocketImages) window.PocketImages.show();
}

// =========================================================
// Seitenleiste
// =========================================================
function closeSidebar() { els.sidebar.classList.remove('open'); }
function toggleSidebar() {
  if (isMobile()) { els.sidebar.classList.toggle('open'); return; }
  const collapsed = els.app.classList.toggle('sidebar-collapsed');
  localStorage.setItem(LS.sidebar, collapsed ? '1' : '0');
  queueSettingsPush();
}
els.sidebarToggle.addEventListener('click', toggleSidebar);
els.sidebarOpen.addEventListener('click', toggleSidebar);
els.sidebarScrim.addEventListener('click', closeSidebar);
if (localStorage.getItem(LS.sidebar) === '1' && !isMobile()) els.app.classList.add('sidebar-collapsed');
els.newChatBtn.addEventListener('click', () => newChat());
els.headerNewChat.addEventListener('click', () => newChat());
els.sbBrand.addEventListener('click', () => newChat());
els.imagesBtn.addEventListener('click', () => showImagesView());
els.sbSearchBtn.addEventListener('click', () => openSearch());
$('search-kbd').textContent = /Mac|iPhone|iPad/.test(navigator.platform) ? '⌘K' : 'Ctrl K';

async function refreshChatList() {
  try {
    const list = await api('GET', '/conversations');
    state.chats = list;
    state._allCids = list.map((c) => c.id);
    renderChatList();
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) return showLogin();
    toast(t('toast_list_failed', apiErrorText(e)), { error: true });
  }
}

function chatSortKey(c) { return c.last_message_at || c.created_at || ''; }

/** Abschnitte wie in der App: Angeheftet, dann Letzte. */
function renderChatList() {
  const items = state.chats.slice().sort((a, b) => chatSortKey(b).localeCompare(chatSortKey(a)));
  els.chatNav.innerHTML = '';
  if (!items.length) {
    els.chatNav.innerHTML = `<div class="sb-section"><div class="sb-label"><span>${escapeHtml(t('section_recent'))}</span></div><div class="empty-chats">${escapeHtml(t('no_chats_yet'))}</div></div>`;
    return;
  }
  const groups = [
    [t('convo_pinned'), items.filter((c) => c.pinned)],
    [t('section_recent'), items.filter((c) => !c.pinned)],
  ];
  for (const [label, chats] of groups) {
    if (!chats.length) continue;
    const sec = document.createElement('section');
    sec.className = 'sb-section';
    sec.innerHTML = `<div class="sb-label"><span>${escapeHtml(label)}</span></div><div class="sb-group"></div>`;
    const list = sec.querySelector('.sb-group');
    for (const c of chats) list.appendChild(chatRow(c));
    els.chatNav.appendChild(sec);
  }
}

function chatRow(c) {
  const row = document.createElement('div');
  row.className = 'chat-item' + (c.id === state.cid && state.view === 'chat' ? ' active' : '');
  row.dataset.cid = c.id;
  row.setAttribute('role', 'link');
  row.tabIndex = 0;
  const lock = c.locked
    ? `<span class="lock-mark" title="${escapeHtml(t('chat_locked_badge'))}"><svg><use href="#icon-lock-filled"/></svg></span>` : '';
  row.innerHTML = `
    <span class="title">${escapeHtml(c.title || t('no_title'))}</span>
    ${lock}
    <button class="chat-row-more" type="button" aria-label="${escapeHtml(t('more'))}" title="${escapeHtml(t('more'))}">
      <svg><use href="#icon-more"/></svg>
    </button>`;
  row.addEventListener('click', () => openChat(c.id));
  row.addEventListener('keydown', (e) => { if (e.key === 'Enter') openChat(c.id); });
  row.querySelector('.chat-row-more').addEventListener('click', (e) => {
    e.stopPropagation();
    openChatRowMenu(row, c, e.currentTarget);
  });
  return row;
}

function markActiveChat() {
  document.querySelectorAll('.chat-item[data-cid]').forEach((el) => {
    el.classList.toggle('active', state.view === 'chat' && el.dataset.cid === state.cid);
  });
}

function openChatRowMenu(row, chat, anchor) {
  if (openPopup && openPopup.anchor === anchor) { closePopup(); return; }
  const menu = document.createElement('div');
  menu.className = 'menu chat-row-menu';
  menu.dataset.transient = '1';
  menu.append(
    menuButton({ icon: 'edit', label: t('rename'), onClick: () => renameInline(row, chat) }),
    menuButton({ icon: chat.pinned ? 'pin-filled' : 'pin', label: chat.pinned ? t('unpin') : t('pin'), onClick: () => togglePin(chat) }),
    menuButton({ icon: chat.locked ? 'unlock' : 'lock', label: chat.locked ? t('unlock_chat') : t('lock_chat'), onClick: () => toggleLock(chat) }),
    menuSep(),
    menuButton({ icon: 'trash', label: t('delete'), danger: true, onClick: () => deleteChat(chat) }),
  );
  document.body.appendChild(menu);
  const r = anchor.getBoundingClientRect();
  const w = 220;
  let left = r.right + 6;
  if (left + w > window.innerWidth - 8) left = Math.max(8, r.left - w);
  menu.style.left = left + 'px';
  menu.style.top = Math.min(r.top - 6, window.innerHeight - 200) + 'px';
  row.classList.add('menu-open');
  showPopup(menu, anchor);
}

/** Umbenennen direkt in der Zeile wie bei ChatGPT. */
function renameInline(row, chat) {
  const titleEl = row.querySelector('.title');
  if (!titleEl) return;
  const input = document.createElement('input');
  input.className = 'rename-input';
  input.value = chat.title || '';
  titleEl.replaceWith(input);
  input.focus();
  input.select();
  let finished = false;
  const finish = async (save) => {
    if (finished) return;
    finished = true;
    const next = input.value.trim();
    if (save && next && next !== chat.title) await renameChat(chat.id, next);
    else renderChatList();
  };
  input.addEventListener('click', (e) => e.stopPropagation());
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); finish(true); }
    if (e.key === 'Escape') { e.preventDefault(); finish(false); }
  });
  input.addEventListener('blur', () => finish(true));
}
async function renameChat(cid, title) {
  try {
    await api('PATCH', '/conversations/' + cid, { title });
    if (state.cid === cid) { state.title = title; updateTopbar(); }
    await refreshChatList();
  } catch (e) { toast(t('toast_error_prefix', apiErrorText(e)), { error: true }); }
}
async function togglePin(chat) {
  try {
    const next = !chat.pinned;
    await api('PATCH', '/conversations/' + chat.id, { pinned: next });
    if (state.cid === chat.id) state.pinned = next;
    await refreshChatList();
  } catch (e) { toast(t('toast_error_prefix', apiErrorText(e)), { error: true }); }
}
async function toggleLock(chat) {
  if (chat.locked) {
    if (!(await verifyPinDialog())) return;
    try {
      await api('PATCH', '/conversations/' + chat.id, { locked: false });
      state.unlockedCids.add(chat.id);
      if (state.cid === chat.id) { state.chatLocked = false; renderMessages(); }
      await refreshChatList();
      toast(t('toast_chat_unlocked'));
    } catch (e) { toast(t('toast_error_prefix', apiErrorText(e)), { error: true }); }
    return;
  }
  try {
    await api('PATCH', '/conversations/' + chat.id, { locked: true });
    state.unlockedCids.delete(chat.id);
    if (state.cid === chat.id) { state.chatLocked = true; renderMessages(); }
    await refreshChatList();
    toast(t('toast_chat_locked'));
  } catch (e) {
    if (e instanceof ApiError && e.status === 400) {
      // Ohne PIN laesst der Server nicht sperren: dorthin, wo man sie setzt.
      toast(t('chat_lock_need_pin_first'), { error: true });
      if (window.openSettings) window.openSettings('privacy');
    } else {
      toast(t('toast_error_prefix', apiErrorText(e)), { error: true });
    }
  }
}
async function deleteChat(chat) {
  const ok = await showConfirm({
    title: t('delete_chat_title'),
    text: t('confirm_delete_chat', chat.title || t('no_title')),
    okLabel: t('delete'), danger: true,
  });
  if (!ok) return;
  try {
    await api('DELETE', '/conversations/' + chat.id);
    const wasOpen = state.cid === chat.id;
    await refreshChatList();
    if (wasOpen) newChat();
  } catch (e) { toast(t('toast_error_prefix', apiErrorText(e)), { error: true }); }
}

// Profil unten in der Leiste: Einstellungen, Design, Abmelden
function renderFooterUser() {
  const name = state.me?.name || '';
  const initial = (name || '?').trim().slice(0, 1).toUpperCase();
  const role = state.me?.is_admin ? t('admin_label') : '';
  els.footerUser.innerHTML = `
    <span class="avatar">${escapeHtml(initial)}</span>
    <span class="who"><span class="name">${escapeHtml(name)}</span>${role ? `<span class="role">${escapeHtml(role)}</span>` : ''}</span>
    <svg class="icon"><use href="#icon-expand-less"/></svg>`;
  $('profile-menu-head').innerHTML = `
    <span class="avatar">${escapeHtml(initial)}</span>
    <span><span class="name">${escapeHtml(name)}</span><br><span class="sub">${escapeHtml(state.serverUrl.replace(/^https?:\/\//, ''))}</span></span>`;
}
els.footerUser.addEventListener('click', () => togglePopup(els.profileMenu, els.footerUser, applyTheme));
els.profileMenu.addEventListener('click', (e) => {
  const b = e.target.closest('[data-profile]');
  if (!b) return;
  closePopup();
  if (b.dataset.profile === 'settings') window.openSettings && window.openSettings();
  if (b.dataset.profile === 'logout') logout();
});
function applyAdminVisibility() {
  const isAdmin = !!(state.me && state.me.is_admin);
  document.querySelectorAll('.admin-only').forEach((el) => el.classList.toggle('hidden', !isAdmin));
}

// =========================================================
// Chats durchsuchen (⌘K): Titel sofort, Volltext nach 250 ms
// =========================================================
let searchTimer = null;
let searchSeq = 0;
function openSearch() {
  closePopup();
  if (isMobile()) closeSidebar();
  els.searchModal.classList.remove('hidden');
  els.searchInput.value = '';
  renderSearch('');
  setTimeout(() => els.searchInput.focus(), 20);
}
function closeSearch() { els.searchModal.classList.add('hidden'); }
$('search-close').addEventListener('click', closeSearch);
els.searchModal.addEventListener('mousedown', (e) => { if (e.target === els.searchModal) closeSearch(); });
els.searchInput.addEventListener('input', () => {
  const q = els.searchInput.value.trim();
  renderSearch(q);
  clearTimeout(searchTimer);
  if (q.length >= 2) searchTimer = setTimeout(() => fullTextSearch(q), 250);
});
els.searchInput.addEventListener('keydown', (e) => {
  const items = [...els.searchResults.querySelectorAll('.sr-item')];
  if (!items.length) { if (e.key === 'Escape') closeSearch(); return; }
  let i = items.findIndex((x) => x.classList.contains('kbd-focus'));
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    e.preventDefault();
    i = e.key === 'ArrowDown' ? Math.min(items.length - 1, i + 1) : Math.max(0, i - 1);
    items.forEach((x, j) => x.classList.toggle('kbd-focus', j === i));
    items[i].scrollIntoView({ block: 'nearest' });
  } else if (e.key === 'Enter') {
    e.preventDefault();
    (items[i] || items[0]).click();
  } else if (e.key === 'Escape') {
    e.preventDefault();
    closeSearch();
  }
});
function highlightTitle(title, q) {
  const safe = escapeHtml(title);
  if (!q) return safe;
  const idx = title.toLowerCase().indexOf(q.toLowerCase());
  if (idx < 0) return safe;
  return escapeHtml(title.slice(0, idx)) + '<b>' + escapeHtml(title.slice(idx, idx + q.length)) + '</b>' + escapeHtml(title.slice(idx + q.length));
}
function relativeWhen(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const diff = Math.round((today - new Date(d.getFullYear(), d.getMonth(), d.getDate())) / 86400000);
  if (diff <= 0) return t('group_today');
  if (diff === 1) return t('group_yesterday');
  return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
}
function searchItem({ icon, titleHtml, snippetHtml, when, onClick }) {
  const b = document.createElement('button');
  b.type = 'button';
  b.className = 'sr-item';
  b.innerHTML = `<svg class="icon"><use href="#icon-${icon}"/></svg>
    <span class="sr-text"><span class="sr-title">${titleHtml}</span>${snippetHtml ? `<span class="sr-snippet">${snippetHtml}</span>` : ''}</span>
    ${when ? `<span class="sr-when">${escapeHtml(when)}</span>` : ''}`;
  b.addEventListener('click', () => { closeSearch(); onClick(); });
  return b;
}
function renderSearch(q) {
  searchSeq++;
  const box = els.searchResults;
  box.innerHTML = '';
  if (!q) {
    box.appendChild(searchItem({ icon: 'new-chat', titleHtml: escapeHtml(t('new_chat')), onClick: () => newChat() }));
  }
  const sorted = state.chats.slice().sort((a, b) => chatSortKey(b).localeCompare(chatSortKey(a)));
  const matches = q ? sorted.filter((c) => (c.title || '').toLowerCase().includes(q.toLowerCase())) : sorted;
  if (matches.length) {
    const lbl = document.createElement('div');
    lbl.className = 'sr-label';
    lbl.textContent = q ? t('search_section_chats') : t('section_recent');
    box.appendChild(lbl);
    for (const c of matches.slice(0, q ? 30 : 12)) {
      box.appendChild(searchItem({
        icon: c.locked ? 'lock' : 'chat',
        titleHtml: highlightTitle(c.title || t('no_title'), q),
        when: relativeWhen(chatSortKey(c)),
        onClick: () => { showChatView(); openChat(c.id); },
      }));
    }
  }
  if (q && !matches.length) {
    const p = document.createElement('div');
    p.className = 'sr-empty';
    p.id = 'sr-pending';
    p.textContent = q.length >= 2 ? t('search_running') : t('no_search_results', q);
    box.appendChild(p);
  }
  const first = box.querySelector('.sr-item');
  if (first) first.classList.add('kbd-focus');
}
async function fullTextSearch(q) {
  const seq = searchSeq;
  try {
    const res = await api('GET', '/search?q=' + encodeURIComponent(q));
    if (seq !== searchSeq) return;   // inzwischen weitergetippt
    const box = els.searchResults;
    box.querySelector('#sr-pending')?.remove();
    const hits = (res.hits || []).filter((h) => !state.chats.find((c) => c.id === h.conversation_id)?.locked);
    if (!hits.length) {
      if (!box.querySelector('.sr-item')) {
        box.innerHTML = `<div class="sr-empty">${escapeHtml(t('no_search_results', q))}</div>`;
      }
      return;
    }
    const lbl = document.createElement('div');
    lbl.className = 'sr-label';
    lbl.textContent = t('search_section_messages');
    box.appendChild(lbl);
    for (const h of hits.slice(0, 30)) {
      // Der Treffer kommt als [[...]] markiert; erst escapen, dann markieren.
      const snippet = escapeHtml(h.snippet || '').replace(/\[\[(.+?)\]\]/g, '<b>$1</b>');
      box.appendChild(searchItem({
        icon: h.role === 'user' ? 'person' : 'forum',
        titleHtml: escapeHtml(h.conversation_title || t('no_title')),
        snippetHtml: snippet,
        when: relativeWhen(h.created_at),
        onClick: () => { showChatView(); openChat(h.conversation_id); },
      }));
    }
    if (!box.querySelector('.kbd-focus')) box.querySelector('.sr-item')?.classList.add('kbd-focus');
  } catch (e) {
    if (seq === searchSeq) toast(t('toast_search_failed', apiErrorText(e)), { error: true });
  }
}

// =========================================================
// Chats oeffnen und anlegen
// =========================================================
async function openChat(cid, opts = {}) {
  if (state.view !== 'chat') showChatView();
  if (state.cid === cid && !opts.reload) {
    closeSidebar();
    return;
  }
  stopStreamLocal();
  if (window.PocketVoice) { try { window.PocketVoice.resetForChatSwitch(); } catch (_) {} }
  stopAudio();
  closeChatSearch();
  state.cid = cid;
  localStorage.setItem(LS.lastCid, cid);
  if (!opts.fromHash) {
    const wanted = '#/chat/' + cid;
    if (location.hash !== wanted) history.replaceState(null, '', wanted);
  }
  markActiveChat();
  closeSidebar();
  try {
    const detail = await api('GET', '/conversations/' + cid);
    if (state.cid !== cid) return;   // inzwischen anderer Chat
    applyDetail(detail);
    resetComposerFor(cid);
    if (state.chatLocked && !state.unlockedCids.has(cid)) renderLockGate(cid);
    else { renderMessages(); scrollToVeryBottom(); }
    loadChatSkills(cid);
    // Das Modell dieses Chats muss in der Liste stehen, auch wenn es nicht mehr kuratiert ist.
    if (state.convModel && !state.chatModels.some((m) => m.key === state.convModel)) loadChatModels(false);
    if (!opts.keepFocus && !isMobile()) els.input.focus();
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) { newChat(); return; }
    toast(t('toast_load_chat_failed', apiErrorText(e)), { error: true });
  }
}
function applyDetail(detail) {
  state.title = detail.title;
  state.pinned = !!detail.pinned;
  state.chatLocked = !!detail.locked;
  state.messages = detail.messages || [];
  state.streamingText = '';
  state.streamingThinking = '';
  state.isStreaming = false;
  // Der Server weiss, was zuletzt in diesem Chat lief. Nur wenn nicht, gilt die Vorauswahl.
  state.convModel = (detail.chat_model || '').trim() || null;
  state.gem = null;
  if (detail.gem_id) {
    gemFetch(detail.gem_id).then((g) => {
      if (state.cid === detail.id) { state.gem = g; updateTopbar(); if (!state.messages.length) renderMessages(); }
    }).catch(() => {});
  }
  updateTopbar();
  updateModelButton();
  renderModelMenu();
}

async function newChat(opts = {}) {
  if (state.view !== 'chat') showChatView();
  stopStreamLocal();
  if (window.PocketVoice) { try { window.PocketVoice.resetForChatSwitch(); } catch (_) {} }
  stopAudio();
  closeChatSearch();
  try {
    const c = await api('POST', '/conversations', opts.gemId ? { gem_id: opts.gemId } : {});
    state.cid = c.id;
    state.title = c.title;
    state.pinned = false;
    state.chatLocked = false;
    state.gem = opts.gem || null;
    state.messages = [];
    state.convModel = null;
    state.skills = null;
    state.skillsIsOverride = false;
    resetComposerFor(c.id);
    updateTopbar();
    updateModelButton();
    renderModelMenu();
    renderMessages();
    localStorage.setItem(LS.lastCid, c.id);
    history.replaceState(null, '', '#/chat/' + c.id);
    markActiveChat();
    closeSidebar();
    loadChatSkills(c.id);
    if (!isMobile()) els.input.focus();
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) return showLogin();
    toast(t('toast_new_chat_failed', apiErrorText(e)), { error: true });
  }
}

async function reloadChatMessages(cid) {
  try {
    const detail = await api('GET', `/conversations/${cid}`);
    if (state.cid !== cid) return;
    applyDetail(detail);
    if (state.chatLocked && !state.unlockedCids.has(cid)) renderLockGate(cid);
    else renderMessages();
  } catch (_) { /* naechster Klick laedt neu */ }
}

function updateTopbar() {
  const gemPrefix = state.gem && state.gem.emoji ? state.gem.emoji + '  ' : '';
  const hasContent = state.messages.length > 0;
  const title = hasContent || state.gem ? gemPrefix + (state.title || '') : '';
  els.topbarTitle.textContent = title === t('new_chat') || title === 'Neuer Chat' ? '' : title;
  if (state.view === 'chat') document.title = (els.topbarTitle.textContent ? els.topbarTitle.textContent + ' · ' : '') + 'PocketClot';
  els.shareBtn.classList.toggle('hidden', !hasContent);
}

// =========================================================
// Modell und Denktiefe (ModelSheet der App als Popover)
// =========================================================
function familyForKey(key) {
  if (!key) return 'claude';
  const found = state.chatModels.find((m) => m.key === key);
  if (found && found.family) return found.family;
  if (!key.startsWith('gw:')) return 'claude';
  const low = key.toLowerCase();
  if (low.includes('gemini')) return 'gemini';
  if (low.includes('gpt') || /(^|[:/-])o\d/.test(low)) return 'gpt';
  return 'other';
}
/** Das Modell, mit dem jetzt gesendet wird: das des Chats, sonst die Vorauswahl. */
function effectiveModelKey() {
  return state.convModel != null ? state.convModel : (state.chatModel || '');
}
function modelEfforts(key) {
  if (!key) return CLAUDE_EFFORTS;
  const m = state.chatModels.find((x) => x.key === key);
  if (m && Array.isArray(m.efforts) && m.efforts.length) return m.efforts;
  return familyForKey(key) === 'claude' ? CLAUDE_EFFORTS : [];
}
/** Gemerkt wird pro Familie, geklemmt auf das, was das Modell kann. */
function clampEffort(effort, available) {
  if (!available.length || available.includes(effort)) return effort;
  const idx = EFFORT_ORDER.indexOf(effort);
  for (let i = idx; i >= 0; i--) if (available.includes(EFFORT_ORDER[i])) return EFFORT_ORDER[i];
  for (let i = idx + 1; i < EFFORT_ORDER.length; i++) if (available.includes(EFFORT_ORDER[i])) return EFFORT_ORDER[i];
  return available[0];
}
function currentEffort() {
  const key = effectiveModelKey();
  const fam = familyForKey(key);
  return clampEffort(state.effortByFamily[fam] || 'high', modelEfforts(key));
}
function formatEffortLabel(eff) {
  if (!eff) return '';
  const k = 'effort_' + eff;
  const label = t(k);
  return label && label !== k ? label : eff.charAt(0).toUpperCase() + eff.slice(1);
}
function modelLabel(key) {
  if (!key) return t('model_family_claude');
  const m = state.chatModels.find((x) => x.key === key);
  if (m) return m.label || m.key;
  return key.startsWith('gw:') ? key.split(':').pop() : key;
}

async function loadChatModels(force = false) {
  try {
    const include = effectiveModelKey();
    const qs = new URLSearchParams();
    if (force) qs.set('refresh', '1');
    if (include) qs.set('include', include);
    const resp = await api('GET', '/chat/models' + (qs.toString() ? '?' + qs : ''));
    state.chatModels = Array.isArray(resp.models) ? resp.models : [];
    state.gateways = Array.isArray(resp.gateways) ? resp.gateways : [];
    // Ein Modell, das der Server nicht mehr anbietet, darf nicht stehenbleiben:
    // sonst laeuft jede Nachricht in einen Fehler.
    if (state.chatModel && !state.chatModels.some((m) => m.key === state.chatModel)) {
      state.chatModel = '';
      localStorage.setItem(LS.chatModel, '');
      queueSettingsPush();
    }
  } catch (e) {
    console.log('Modell-Liste nicht abrufbar, Fallback auf Claude:', e.message);
    state.chatModels = [];
    state.gateways = [];
  }
  renderModelMenu();
  updateModelButton();
  document.dispatchEvent(new CustomEvent('pc:models-loaded'));
}

function updateModelButton() {
  els.modelLabel.textContent = modelLabel(effectiveModelKey());
  const eff = currentEffort();
  els.effortLabel.textContent = eff ? formatEffortLabel(eff) : '';
}

function renderModelMenu() {
  const menu = els.effortMenu;
  const key = effectiveModelKey();
  menu.innerHTML = '';
  const head = document.createElement('div');
  head.className = 'mm-head';
  head.innerHTML = `<div><div class="mm-title">${escapeHtml(t('model_menu_title'))}</div>
    <div class="mm-sub">${escapeHtml(modelLabel(key))} · ${escapeHtml(formatEffortLabel(currentEffort()))}</div></div>
    <button type="button" class="icon-btn" data-refresh title="${escapeHtml(t('model_refresh'))}"><svg class="icon"><use href="#icon-refresh"/></svg></button>`;
  head.querySelector('[data-refresh]').addEventListener('click', (e) => { e.stopPropagation(); loadChatModels(true); });
  menu.appendChild(head);

  const families = [
    ['claude', t('model_family_claude')],
    ['gemini', t('model_family_gemini')],
    ['gpt', t('model_family_gpt')],
    ['other', t('model_family_other')],
  ];
  for (const [fam, label] of families) {
    const list = state.chatModels.filter((m) => m.family === fam);
    if (fam !== 'claude' && !list.length) continue;
    const h = document.createElement('div');
    h.className = 'mm-family';
    h.textContent = label;
    menu.appendChild(h);
    const rows = fam === 'claude' ? [{ key: '', label: t('model_auto') }, ...list] : list;
    for (const m of rows) {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'mm-model' + (m.key === key ? ' selected' : '');
      b.innerHTML = `<svg class="icon mm-check"><use href="#icon-check"/></svg>
        <span class="label">${escapeHtml(m.label || m.key)}${m.gateway_label ? `<span class="mm-gw">${escapeHtml(m.gateway_label)}</span>` : ''}</span>`;
      b.addEventListener('click', () => selectModel(m.key));
      menu.appendChild(b);
    }
  }
  const down = (state.gateways || []).filter((g) => g && g.reachable === false);
  for (const gw of down) {
    const n = document.createElement('div');
    n.className = 'mm-notice';
    n.textContent = `${gw.label || gw.id}: ${gw.last_error || t('model_gateway_unreachable')}`;
    menu.appendChild(n);
  }
  menu.appendChild(menuSep());
  const eff = document.createElement('div');
  eff.className = 'mm-effort';
  const efforts = modelEfforts(key);
  eff.innerHTML = `<div class="mm-family">${escapeHtml(t('effort_label'))}</div>`;
  if (!efforts.length) {
    eff.insertAdjacentHTML('beforeend', `<div class="mm-notice" style="color:var(--text-muted)">${escapeHtml(t('effort_not_supported'))}</div>`);
  } else {
    const row = document.createElement('div');
    row.className = 'chip-row';
    const cur = currentEffort();
    for (const e of EFFORT_ORDER.filter((x) => efforts.includes(x))) {
      const c = document.createElement('button');
      c.type = 'button';
      c.className = 'chip' + (e === cur ? ' active' : '');
      c.textContent = formatEffortLabel(e);
      c.addEventListener('click', () => { setEffort(e); closePopup(); });
      row.appendChild(c);
    }
    eff.appendChild(row);
  }
  menu.appendChild(eff);
}

/** Modellwechsel gilt sofort fuer diesen Chat und wird die neue Vorauswahl,
 *  damit der naechste Chat genauso startet (wie selectModel in der App). */
function selectModel(key) {
  key = key || '';
  state.convModel = key;
  state.chatModel = key;
  localStorage.setItem(LS.chatModel, key);
  queueSettingsPush();
  if (state.cid) {
    api('PATCH', '/conversations/' + state.cid, { chat_model: key })
      .catch((e) => console.log('Modell am Chat nicht gespeichert:', e.message));
  }
  updateModelButton();
  renderModelMenu();
  updateSkillsAvailability();
}
function setEffort(value, family) {
  const fam = family || familyForKey(effectiveModelKey());
  state.effortByFamily[fam] = value;
  state.effort = value;
  localStorage.setItem(LS.effortByFamily, JSON.stringify(state.effortByFamily));
  localStorage.setItem(LS.effort, value);
  queueSettingsPush();
  updateModelButton();
  renderModelMenu();
  document.dispatchEvent(new CustomEvent('pc:effort-changed'));
}
els.effortBtn.addEventListener('click', () => togglePopup(els.effortMenu, els.effortBtn, renderModelMenu));

// =========================================================
// Chat-Menue (Mehr): wie in der App
// =========================================================
function autoSpeakOverride(cid) {
  const v = state.autoSpeakByChat[cid || state.cid];
  return v === true || v === false ? v : null;
}
function autoSpeakFor(cid) {
  const o = autoSpeakOverride(cid);
  return o === null ? state.autoSpeak : o;
}
function buildMoreMenu() {
  const m = els.moreMenu;
  m.innerHTML = '';
  const chat = state.chats.find((c) => c.id === state.cid) || { id: state.cid, title: state.title, pinned: state.pinned, locked: state.chatLocked };
  const hasMsgs = state.messages.length > 0;
  const ov = autoSpeakOverride();
  const autoOn = window.PocketVoice && window.PocketVoice.isAutoMode();
  m.append(
    menuButton({ icon: 'edit', label: t('rename'), disabled: !hasMsgs, onClick: renameCurrentChat }),
    menuButton({ icon: state.pinned ? 'pin-filled' : 'pin', label: state.pinned ? t('unpin') : t('pin'), disabled: !hasMsgs, onClick: () => togglePin(chat) }),
    menuButton({ icon: state.chatLocked ? 'unlock' : 'lock', label: state.chatLocked ? t('unlock_chat') : t('lock_chat'), disabled: !hasMsgs, onClick: () => toggleLock(chat) }),
    menuSep(),
    menuButton({ icon: 'extension', label: t('skills_for_this_chat'), trail: state.skillsIsOverride ? t('skills_own') : '', trailOn: true, onClick: openSkillsDialog }),
    menuButton({ icon: 'speaker', label: t('auto_speak_menu'), trail: ov === null ? '' : (ov ? t('chat_auto_speak_marker_on') : t('chat_auto_speak_marker_off')), trailOn: ov === true, onClick: openAutoSpeakDialog }),
    menuButton({ icon: 'voice', label: autoOn ? t('auto_mode_stop') : t('voice_conversation'), onClick: () => window.PocketVoice && window.PocketVoice.toggleAutoMode() }),
    menuButton({ icon: 'search', label: t('search_in_chat'), disabled: !hasMsgs, onClick: openChatSearch }),
    menuSep(),
    menuButton({ icon: 'share', label: t('share_as_markdown'), disabled: !hasMsgs, onClick: () => exportMarkdown('share') }),
    menuButton({ icon: 'download', label: t('save_as_markdown'), disabled: !hasMsgs, onClick: () => exportMarkdown('save') }),
    menuSep(),
    menuButton({ icon: 'trash', label: t('delete'), danger: true, disabled: !hasMsgs, onClick: () => deleteChat(chat) }),
  );
}
els.moreBtn.addEventListener('click', () => togglePopup(els.moreMenu, els.moreBtn, buildMoreMenu));
els.shareBtn.addEventListener('click', () => exportMarkdown('share'));

async function renameCurrentChat() {
  const next = await showPrompt({ title: t('rename'), type: 'text', value: state.title || '', okLabel: t('save') });
  if (next === null) return;
  const trimmed = next.trim();
  if (trimmed && trimmed !== state.title) renameChat(state.cid, trimmed);
}

/** Teilen: mit Web-Share als Datei (Handy, Safari), sonst Download. */
async function exportMarkdown(mode) {
  if (!state.cid) return;
  if (state.chatLocked && !state.unlockedCids.has(state.cid)) {
    toast(t('chat_lock_need_pin_first'), { error: true });
    return;
  }
  try {
    const md = await api('GET', '/conversations/' + state.cid + '/export.md');
    const safe = (state.title || 'chat').replace(/[^\p{L}\p{N}\-_ ]/gu, '_').slice(0, 60).trim() || 'chat';
    const file = new File([md], safe + '.md', { type: 'text/markdown' });
    if (mode === 'share' && navigator.canShare && navigator.canShare({ files: [file] })) {
      try { await navigator.share({ files: [file], title: state.title }); return; }
      catch (e) { if (e.name === 'AbortError') return; }
    }
    const a = document.createElement('a');
    a.href = URL.createObjectURL(file);
    a.download = file.name;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
    if (mode === 'share') toast(t('toast_markdown_saved'));
  } catch (e) { toast(t('toast_action_failed', apiErrorText(e)), { error: true }); }
}

// Skills fuer diesen Chat: Override setzen oder auf den Standard zuruecksetzen
async function loadChatSkills(cid) {
  try {
    const r = await api('GET', `/conversations/${cid}/skills`);
    if (state.cid !== cid) return;
    state.skills = r.skills;
    state.skillsIsOverride = !!r.is_override;
  } catch { state.skills = null; state.skillsIsOverride = false; }
}
function updateSkillsAvailability() { /* Platzhalter: der Dialog liest die Familie beim Oeffnen */ }
function toggleRow(label, desc, checked, disabled) {
  const row = document.createElement('label');
  row.className = 'dlg-toggle';
  row.innerHTML = `<span class="set-text"><span class="set-title"></span><span class="set-hint"></span></span>
    <input type="checkbox" class="switch">`;
  row.querySelector('.set-title').textContent = label;
  row.querySelector('.set-hint').textContent = desc;
  const input = row.querySelector('input');
  input.checked = !!checked;
  input.disabled = !!disabled;
  return { row, input };
}
async function openSkillsDialog() {
  if (!state.cid) return;
  await loadChatSkills(state.cid);
  const s = Object.assign({ web_search: true, web_fetch: true, code_execution: false, image_generation: true }, state.skills || {});
  const codeAvailable = familyForKey(effectiveModelKey()) === 'claude';
  const body = document.createElement('div');
  const intro = document.createElement('p');
  intro.className = 'dlg-text';
  intro.textContent = state.skillsIsOverride ? t('chat_skills_dialog_body_override') : t('chat_skills_dialog_body_default');
  body.appendChild(intro);
  const ws = toggleRow(t('skill_web_search'), t('skill_web_search_desc'), s.web_search);
  const wf = toggleRow(t('skill_web_fetch'), t('skill_web_fetch_desc'), s.web_fetch);
  const code = toggleRow(t('skill_code'), codeAvailable ? t('skill_code_desc') : t('chat_skill_claude_only'), s.code_execution && codeAvailable, !codeAvailable);
  body.append(ws.row, wf.row, code.row);
  const actions = [{ label: t('cancel'), value: null }];
  if (state.skillsIsOverride) actions.push({ label: t('chat_skills_reset_default'), value: 'reset' });
  actions.push({ label: t('chat_skills_save_for_chat'), kind: 'btn-primary', value: 'save' });
  const res = await openDialog({ title: t('chat_skills_dialog_title'), icon: 'extension', body, actions });
  if (!res) return;
  try {
    const payload = res === 'reset' ? { skills: null } : {
      // Bild-Einstellung mitnehmen, sonst faellt sie beim Speichern auf den Standard zurueck.
      skills: { ...s, web_search: ws.input.checked, web_fetch: wf.input.checked, code_execution: code.input.checked },
    };
    const r = await api('PUT', `/conversations/${state.cid}/skills`, payload);
    state.skills = r.skills;
    state.skillsIsOverride = !!r.is_override;
    toast(res === 'reset' ? t('toast_skills_reset') : t('toast_skills_saved'));
  } catch (e) { toast(t('toast_error_prefix', apiErrorText(e)), { error: true }); }
}

async function openAutoSpeakDialog() {
  const cid = state.cid;
  const ov = autoSpeakOverride(cid);
  const body = document.createElement('div');
  const intro = document.createElement('p');
  intro.className = 'dlg-text';
  intro.textContent = t('chat_auto_speak_dialog_body');
  body.appendChild(intro);
  const opts = [
    [null, t('chat_auto_speak_default_label', state.autoSpeak ? t('chat_auto_speak_on') : t('chat_auto_speak_off'))],
    [true, t('chat_auto_speak_always_on')],
    [false, t('chat_auto_speak_always_off')],
  ];
  let close;
  for (const [val, label] of opts) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'dlg-option' + (ov === val ? ' selected' : '');
    b.innerHTML = `<svg class="icon"><use href="#icon-${ov === val ? 'check-circle' : 'radio'}"/></svg><span></span>`;
    b.querySelector('span').textContent = label;
    b.addEventListener('click', () => {
      if (val === null) delete state.autoSpeakByChat[cid]; else state.autoSpeakByChat[cid] = val;
      localStorage.setItem(LS.autoSpeakByChat, JSON.stringify(state.autoSpeakByChat));
      queueSettingsPush();
      close && close(true);
    });
    body.appendChild(b);
  }
  await openDialog({
    title: t('chat_auto_speak_dialog_title'), icon: 'speaker', body,
    actions: [{ label: t('close'), value: null }],
    onMount: (_w, c) => { close = c; },
  });
}

// =========================================================
// Verlauf
// =========================================================
function setComposerLocked(locked) {
  els.input.disabled = locked;
  els.inputForm.classList.toggle('composer-locked', locked);
  updateComposerState();
}

function renderMessages() {
  if (state.chatLocked && state.cid && !state.unlockedCids.has(state.cid)) {
    setComposerLocked(true);
    renderLockGate(state.cid);
    return;
  }
  setComposerLocked(false);
  els.messages.innerHTML = '';
  const inner = document.createElement('div');
  inner.className = 'messages-inner';
  els.messages.appendChild(inner);
  const empty = !state.messages.length && !state.isStreaming;
  els.chatView.classList.toggle('is-empty', empty);
  updateTopbar();
  if (empty) {
    if (state.gem) inner.appendChild(gemWelcomeEl(state.gem));
    else {
      const first = (state.me?.name || '').split(/\s+/)[0];
      inner.innerHTML = `
        <div class="empty-hero">
          <img class="e-logo brand-mark" src="brand-mark.png" alt="">
          <h3>${escapeHtml(first ? t('greeting_named', first) : t('greeting'))}</h3>
        </div>`;
    }
    updateScrollUi();
    return;
  }
  const lastAssistantIdx = (() => {
    for (let i = state.messages.length - 1; i >= 0; i--) if (state.messages[i].role === 'assistant') return i;
    return -1;
  })();
  state.messages.forEach((m, i) => inner.appendChild(renderMessage(m, i === lastAssistantIdx && !state.isStreaming)));
  if (state.isStreaming) inner.appendChild(renderStreamingMessage());
  enhanceContent(inner);
  if (searchState.open) refreshChatSearch();
  updateScrollUi();
}

function ttsButtonsHtml(m) {
  const a = state.audio.msgId === m.id ? state.audio.status : 'idle';
  if (a === 'loading') return `<span class="spin"><span class="spinner" style="width:16px;height:16px"></span></span>`;
  if (a === 'playing') {
    return `<button class="icon-btn active" data-tool="pause" title="${escapeHtml(t('bubble_pause'))}"><svg class="icon"><use href="#icon-pause"/></svg></button>
      <button class="icon-btn" data-tool="stop-tts" title="${escapeHtml(t('stop_reading'))}"><svg class="icon"><use href="#icon-stop"/></svg></button>`;
  }
  if (a === 'paused') {
    return `<button class="icon-btn active" data-tool="resume" title="${escapeHtml(t('bubble_resume'))}"><svg class="icon"><use href="#icon-play"/></svg></button>
      <button class="icon-btn" data-tool="stop-tts" title="${escapeHtml(t('stop_reading'))}"><svg class="icon"><use href="#icon-stop"/></svg></button>`;
  }
  return `<button class="icon-btn" data-tool="tts" title="${escapeHtml(t('tts_title'))}"><svg class="icon"><use href="#icon-speaker"/></svg></button>`;
}

function renderMessage(m, isLast) {
  const div = document.createElement('div');
  div.className = 'msg ' + (m.role === 'user' ? 'user' : 'assistant') + (isLast ? ' last' : '');
  div.dataset.mid = m.id;
  const attHtml = attachmentsToHtml(m.attachments);
  if (m.role === 'user') {
    div.innerHTML = `${attHtml}${m.content ? `<div class="bubble"></div>` : ''}
      ${m.content ? `<div class="msg-tools"><button class="icon-btn" data-tool="copy" title="${escapeHtml(t('copy_title'))}"><svg class="icon"><use href="#icon-copy"/></svg></button></div>` : ''}`;
    if (m.content) {
      const bubble = div.querySelector('.bubble');
      bubble.textContent = m.content;
      if (state.collapseUserMsgs) {
        bubble.classList.add('collapsed');
        // Erst nach dem Layout entscheiden, ob es ueberhaupt etwas einzuklappen gibt.
        requestAnimationFrame(() => {
          if (bubble.scrollHeight <= bubble.clientHeight + 2) bubble.classList.remove('collapsed');
          else bubble.classList.add('collapsible');
        });
        bubble.addEventListener('click', () => {
          if (window.getSelection().toString()) return;
          if (!bubble.classList.contains('collapsible')) return;
          bubble.classList.toggle('collapsed');
        });
      }
    }
  } else {
    const thinking = m._thinking ? thinkingEl(m._thinking, false) : null;
    div.innerHTML = `<div class="content">${renderMarkdown(m.content)}</div>${attHtml}`;
    if (thinking) div.prepend(thinking);
    if (m.content || (m.attachments || []).length) {
      const tools = document.createElement('div');
      tools.className = 'msg-tools';
      const serverId = typeof m.id === 'number' && m.id > 0;
      tools.innerHTML = `${serverId && m.content ? `<span class="tts-slot">${ttsButtonsHtml(m)}</span>` : ''}
        <button class="icon-btn" data-tool="copy" title="${escapeHtml(t('copy_title'))}"><svg class="icon"><use href="#icon-copy"/></svg></button>
        ${serverId ? `<button class="icon-btn" data-tool="rewind" title="${escapeHtml(t('bubble_rewind'))}"><svg class="icon"><use href="#icon-history"/></svg></button>` : ''}`;
      div.appendChild(tools);
    }
  }
  div.addEventListener('click', (e) => {
    const b = e.target.closest('[data-tool]');
    if (!b) return;
    const tool = b.dataset.tool;
    if (tool === 'copy') {
      navigator.clipboard.writeText(m.content || '').then(() => toast(t('toast_copied')), () => toast(t('toast_copy_failed'), { error: true }));
    } else if (tool === 'tts') speak(m.id);
    else if (tool === 'pause') pauseAudio();
    else if (tool === 'resume') resumeAudio();
    else if (tool === 'stop-tts') stopAudio();
    else if (tool === 'rewind') openRewindDialog(m);
  });
  return div;
}

function thinkingEl(text, live) {
  const box = document.createElement('div');
  box.className = 'thinking' + (live ? ' live' : '');
  box.innerHTML = `<button type="button" class="thinking-toggle">
      <span class="${live ? 'shimmer' : ''}">${escapeHtml(live ? t('bubble_thinking_live') : t('thinking_show'))}</span>
      ${live ? '' : '<svg class="icon"><use href="#icon-chevron-down"/></svg>'}
    </button>
    <div class="thinking-body"><div></div></div>`;
  box.querySelector('.thinking-body > div').textContent = (text || '').trim();
  if (!live) {
    box.querySelector('.thinking-toggle').addEventListener('click', () => {
      box.classList.toggle('open');
      box.querySelector('.thinking-toggle span').textContent = box.classList.contains('open') ? t('thinking_hide') : t('thinking_show');
    });
  }
  return box;
}

function renderStreamingMessage() {
  const div = document.createElement('div');
  div.className = 'msg assistant streaming';
  div.id = 'streaming-msg';
  fillStreamingMessage(div);
  return div;
}
function fillStreamingMessage(div) {
  const text = state.streamingText;
  const thinking = state.streamingThinking;
  div.innerHTML = '';
  if (thinking) div.appendChild(thinkingEl(thinking, !text));
  if (!text) {
    if (!thinking) {
      div.insertAdjacentHTML('beforeend', `<div class="waiting"><img class="brand-mark brand-pulse" src="brand-mark.png" alt="">
        <span class="shimmer">${escapeHtml(t('bubble_thinking_live'))}</span></div>`);
    }
  } else {
    const c = document.createElement('div');
    c.className = 'content';
    c.innerHTML = renderMarkdown(text);
    div.appendChild(c);
    div.insertAdjacentHTML('beforeend', '<div class="streaming-dots"><span></span><span></span><span></span></div>');
  }
  if (state._streamAttachments.length) div.insertAdjacentHTML('beforeend', attachmentsToHtml(state._streamAttachments));
  enhanceContent(div);
}
let _streamRaf = 0;
function updateStreaming() {
  // Hoechstens ein Neuzeichnen pro Bild, sonst bremst Markdown lange Antworten aus.
  if (_streamRaf) return;
  _streamRaf = requestAnimationFrame(() => {
    _streamRaf = 0;
    let div = $('streaming-msg');
    if (!div) { renderMessages(); div = $('streaming-msg'); }
    if (div) fillStreamingMessage(div);
    scrollToBottom();
  });
}

// =========================================================
// Gesperrte Chats: PIN statt Inhalt
// =========================================================
function renderLockGate(cid) {
  els.chatView.classList.remove('is-empty');
  els.messages.innerHTML = '';
  const inner = document.createElement('div');
  inner.className = 'messages-inner';
  els.messages.appendChild(inner);
  const gate = document.createElement('div');
  gate.className = 'lock-gate';
  gate.innerHTML = `
    <div class="lock-gate-icon"><svg><use href="#icon-lock"/></svg></div>
    <h3>${escapeHtml(t('lock_gate_title'))}</h3>
    <p>${escapeHtml(t('lock_gate_hint'))}</p>
    <input type="password" inputmode="numeric" maxlength="5" autocomplete="off" aria-label="${escapeHtml(t('chat_lock_pin'))}">
    <div class="lock-gate-error"></div>
    <button type="button" class="btn-primary" data-role="unlock">${escapeHtml(t('lock_gate_unlock'))}</button>`;
  inner.appendChild(gate);
  setComposerLocked(true);
  const input = gate.querySelector('input');
  const errEl = gate.querySelector('.lock-gate-error');
  const btn = gate.querySelector('[data-role="unlock"]');
  let countdown = null;
  const onlyDigits = () => { input.value = input.value.replace(/\D/g, '').slice(0, 5); };
  input.addEventListener('input', onlyDigits);
  const submit = async () => {
    onlyDigits();
    if (input.value.length !== 5) { errEl.textContent = t('chat_lock_pin_5_digits'); return; }
    btn.disabled = true;
    try {
      const r = await api('POST', '/me/chat-lock/verify', { pin: input.value });
      if (r.ok) {
        state.unlockedCids.add(cid);
        if (state.cid === cid) { renderMessages(); scrollToVeryBottom(); }
        return;
      }
      input.value = '';
      const wait = r.retry_after_seconds || 0;
      if (wait > 0) startLockout(wait);
      else { errEl.textContent = t('lock_gate_wrong'); btn.disabled = false; input.focus(); }
    } catch (e) {
      errEl.textContent = t('toast_error_prefix', apiErrorText(e));
      btn.disabled = false;
    }
  };
  function startLockout(seconds) {
    input.disabled = true; btn.disabled = true;
    let remaining = seconds;
    const tick = () => {
      errEl.textContent = t('lock_gate_locked_out', remaining);
      if (remaining <= 0) {
        clearInterval(countdown); countdown = null;
        input.disabled = false; btn.disabled = false; errEl.textContent = '';
        input.focus();
        return;
      }
      remaining -= 1;
    };
    tick();
    countdown = setInterval(tick, 1000);
  }
  btn.addEventListener('click', submit);
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); submit(); } });
  setTimeout(() => input.focus(), 50);
}

async function verifyPinDialog() {
  while (true) {
    const pin = await showPrompt({
      title: t('lock_gate_title'), text: t('lock_gate_hint'),
      placeholder: t('chat_lock_pin'), type: 'password', okLabel: t('lock_gate_unlock'),
    });
    if (pin === null) return false;
    const digits = (pin || '').replace(/\D/g, '');
    if (digits.length !== 5) { toast(t('chat_lock_pin_5_digits'), { error: true }); continue; }
    try {
      const r = await api('POST', '/me/chat-lock/verify', { pin: digits });
      if (r.ok) return true;
      if (r.retry_after_seconds > 0) { toast(t('lock_gate_locked_out', r.retry_after_seconds), { error: true }); return false; }
      toast(t('lock_gate_wrong'), { error: true });
    } catch (e) {
      toast(t('toast_error_prefix', apiErrorText(e)), { error: true });
      return false;
    }
  }
}

// =========================================================
// Scrollen
// =========================================================
function distanceFromBottom() {
  const m = els.messages;
  return m.scrollHeight - m.scrollTop - m.clientHeight;
}
function scrollToBottom(force = false) {
  if (force || distanceFromBottom() < 200) els.messages.scrollTop = els.messages.scrollHeight + 1e6;
  updateScrollUi();
}
function updateScrollUi() {
  els.scrollDown.classList.toggle('hidden', state.view !== 'chat' || distanceFromBottom() < 400);
  els.topbar.classList.toggle('scrolled', state.view === 'chat' && els.messages.scrollTop > 4);
}
els.messages.addEventListener('scroll', updateScrollUi, { passive: true });
els.scrollDown.addEventListener('click', () => {
  els.messages.scrollTo({ top: els.messages.scrollHeight, behavior: 'smooth' });
});

// Beim Oeffnen: am Ende halten, bis Markdown, Code und Bilder fertig gelayoutet
// sind. Endet, sobald der Nutzer selbst scrollt, spaetestens nach 4 Sekunden.
let _pinBottomCleanup = null;
function scrollToVeryBottom() {
  const m = els.messages;
  if (_pinBottomCleanup) { _pinBottomCleanup(); _pinBottomCleanup = null; }
  const jump = () => { m.scrollTop = m.scrollHeight + 1e6; };
  jump();
  const retries = setInterval(jump, 80);
  setTimeout(() => clearInterval(retries), 1500);
  let userScrolled = false;
  const onScroll = () => { if (distanceFromBottom() > 80) userScrolled = true; };
  m.addEventListener('scroll', onScroll, { passive: true });
  const ro = new ResizeObserver(() => { if (!userScrolled) jump(); });
  ro.observe(m);
  for (const child of m.children) ro.observe(child);
  const imgs = [];
  for (const img of m.querySelectorAll('img')) {
    if (!img.complete) {
      const h = () => { if (!userScrolled) jump(); };
      img.addEventListener('load', h, { once: true });
      img.addEventListener('error', h, { once: true });
      imgs.push([img, h]);
    }
  }
  const stopAt = setTimeout(stop, 4000);
  function stop() {
    clearTimeout(stopAt);
    clearInterval(retries);
    m.removeEventListener('scroll', onScroll);
    ro.disconnect();
    for (const [img, h] of imgs) { img.removeEventListener('load', h); img.removeEventListener('error', h); }
    _pinBottomCleanup = null;
    updateScrollUi();
  }
  _pinBottomCleanup = stop;
}

// =========================================================
// Zurueckspringen: ab einer Antwort weitermachen, wahlweise mit anderem Modell
// =========================================================
async function openRewindDialog(m) {
  if (state.isStreaming) return;
  const idx = state.messages.findIndex((x) => x.id === m.id);
  if (idx < 0) return;
  const dropped = state.messages.length - idx - 1;
  const current = effectiveModelKey();
  let chosen = current;
  const body = document.createElement('div');
  const p = document.createElement('p');
  p.className = 'dlg-text';
  p.textContent = dropped === 0 ? t('rewind_body_none') : dropped === 1 ? t('rewind_body_one') : t('rewind_body_many', dropped);
  body.appendChild(p);
  const options = [{ key: '', label: t('model_auto') }, ...state.chatModels.filter((x) => x.key)];
  if (options.length > 1) {
    const lbl = document.createElement('div');
    lbl.className = 'dlg-label';
    lbl.textContent = t('rewind_dialog_model_label');
    body.appendChild(lbl);
    const row = document.createElement('div');
    row.className = 'chip-row';
    for (const o of options) {
      const c = document.createElement('button');
      c.type = 'button';
      c.className = 'chip' + (o.key === current ? ' active' : '');
      c.textContent = o.label || o.key;
      c.addEventListener('click', () => {
        chosen = o.key;
        row.querySelectorAll('.chip').forEach((x) => x.classList.toggle('active', x === c));
      });
      row.appendChild(c);
    }
    body.appendChild(row);
  }
  const ok = await openDialog({
    title: t('rewind_dialog_title'), icon: 'history', body,
    actions: [{ label: t('cancel'), value: false }, { label: t('rewind_dialog_confirm'), kind: 'btn-primary', value: true }],
  });
  if (!ok) return;
  const cid = state.cid;
  try {
    // Nur mitschicken, was sich wirklich aendert: sonst gilt es serverseitig als Wechsel.
    const payload = { message_id: m.id };
    if (chosen !== current) payload.chat_model = chosen;
    const res = await api('POST', `/conversations/${cid}/rewind`, payload);
    if (res.chat_model != null && chosen !== current) {
      const fam = familyForKey(res.chat_model);
      selectModel(res.chat_model);
      // Nach einem echten Wechsel mit hoher Denktiefe weiter, wie in der App.
      if (state.effortByFamily[fam] !== 'high') setEffort('high', fam);
    }
    toast(t('toast_rewind_done'));
  } catch (e) {
    toast(t('toast_error_prefix', apiErrorText(e)), { error: true });
  }
  // In jedem Fall den Serverstand uebernehmen: der Ruecksprung kann gelungen
  // und nur die Antwort verloren gegangen sein.
  await reloadChatMessages(cid);
  scrollToVeryBottom();
}

// =========================================================
// Suche im Chat (Markierungen ueber die CSS-Highlight-API)
// =========================================================
const searchState = { open: false, ranges: [], index: -1 };
function openChatSearch() {
  if (state.view !== 'chat') return;
  searchState.open = true;
  els.searchBar.classList.remove('hidden');
  els.searchBarInput.value = '';
  els.searchBarCount.textContent = '';
  setTimeout(() => els.searchBarInput.focus(), 20);
}
function closeChatSearch() {
  if (!searchState.open) return;
  searchState.open = false;
  els.searchBar.classList.add('hidden');
  searchState.ranges = [];
  searchState.index = -1;
  if (window.CSS && CSS.highlights) { CSS.highlights.delete('pc-search'); CSS.highlights.delete('pc-search-current'); }
}
function refreshChatSearch(keepIndex = true) {
  const q = els.searchBarInput.value.trim().toLowerCase();
  const ranges = [];
  if (q) {
    const roots = els.messages.querySelectorAll('.msg .bubble, .msg .content');
    for (const root of roots) {
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
      let node;
      while ((node = walker.nextNode())) {
        const text = node.nodeValue.toLowerCase();
        let from = 0, i;
        while ((i = text.indexOf(q, from)) >= 0) {
          const r = new Range();
          r.setStart(node, i);
          r.setEnd(node, i + q.length);
          ranges.push(r);
          from = i + q.length;
        }
      }
    }
  }
  searchState.ranges = ranges;
  if (!keepIndex || searchState.index >= ranges.length) searchState.index = ranges.length ? ranges.length - 1 : -1;
  paintChatSearch();
}
function paintChatSearch() {
  const { ranges, index } = searchState;
  const q = els.searchBarInput.value.trim();
  els.searchBarCount.textContent = q ? (ranges.length ? `${index + 1}/${ranges.length}` : t('search_no_matches')) : '';
  els.searchBarCount.classList.toggle('none', !!q && !ranges.length);
  if (window.CSS && CSS.highlights && typeof Highlight === 'function') {
    CSS.highlights.set('pc-search', new Highlight(...ranges));
    if (index >= 0) CSS.highlights.set('pc-search-current', new Highlight(ranges[index]));
    else CSS.highlights.delete('pc-search-current');
  }
  if (index >= 0) {
    const el = ranges[index].startContainer.parentElement;
    const bubble = el && el.closest('.bubble.collapsed');
    if (bubble) bubble.classList.remove('collapsed');
    el?.scrollIntoView({ block: 'center', behavior: 'smooth' });
  }
}
function stepChatSearch(dir) {
  const n = searchState.ranges.length;
  if (!n) return;
  searchState.index = (searchState.index + dir + n) % n;
  paintChatSearch();
}
els.searchBarInput.addEventListener('input', () => refreshChatSearch(false));
els.searchBarInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') { e.preventDefault(); stepChatSearch(e.shiftKey ? 1 : -1); }
  if (e.key === 'Escape') { e.preventDefault(); closeChatSearch(); }
});
$('chat-search-prev').addEventListener('click', () => stepChatSearch(-1));
$('chat-search-next').addEventListener('click', () => stepChatSearch(1));
$('chat-search-close').addEventListener('click', closeChatSearch);

// =========================================================
// Anhaenge im Verlauf und Bildbetrachter
// =========================================================
function providerFromFilename(name) {
  const m = /^(gemini|gpt)-\d+\./i.exec(name || '');
  return m ? (m[1].toLowerCase() === 'gpt' ? 'GPT' : 'Gemini') : '';
}
function attachmentsToHtml(atts) {
  if (!atts || !atts.length) return '';
  const images = atts.filter((a) => isImageMime(a.mime_type));
  const others = atts.filter((a) => !isImageMime(a.mime_type));
  let html = '';
  if (images.length) {
    html += `<div class="image-grid${images.length === 1 ? ' single' : ''}">`;
    for (const a of images) {
      const url = attachmentUrl(a.id);
      const prov = providerFromFilename(a.filename);
      html += `
        <figure data-att-id="${escapeHtml(a.id)}">
          <img src="${url}" alt="${escapeHtml(a.filename)}" loading="lazy"
               data-lightbox="${url}" data-att-id="${escapeHtml(a.id)}" data-filename="${escapeHtml(a.filename)}" data-mime="${escapeHtml(a.mime_type)}">
          ${prov ? `<span class="img-provider-tag">${prov}</span>` : ''}
          <div class="img-actions">
            <button type="button" title="${escapeHtml(t('img_action_edit'))}" data-img-action="edit" data-att-id="${escapeHtml(a.id)}" data-filename="${escapeHtml(a.filename)}" data-mime="${escapeHtml(a.mime_type)}"><svg class="icon"><use href="#icon-brush"/></svg></button>
            <a href="${url}" download="${escapeHtml(a.filename)}" title="${escapeHtml(t('img_action_download'))}"><svg class="icon"><use href="#icon-download"/></svg></a>
          </div>
        </figure>`;
    }
    html += '</div>';
  }
  if (others.length) {
    html += '<div class="attachments">';
    for (const a of others) {
      html += `<a class="file-card" href="${attachmentUrl(a.id)}" target="_blank" rel="noopener">
        <span class="file-ico"><svg class="icon"><use href="#icon-file"/></svg></span>
        <span><span class="file-name">${escapeHtml(a.filename)}</span><span class="file-type">${escapeHtml(fileExt(a.filename) || a.mime_type || '')}</span></span>
      </a>`;
    }
    html += '</div>';
  }
  return html;
}

/** Bild als Vorlage im Chat weiterbearbeiten: Bildmodus an, Bild als Anhang. */
function editImageInChat(att) {
  if (state.view !== 'chat') showChatView();
  if (!state.pending.some((p) => p.uploaded && p.uploaded.id === att.id)) {
    state.pending.push({
      key: 'existing-' + att.id, filename: att.filename, mime: att.mime_type,
      previewUrl: attachmentUrl(att.id), uploading: false, error: null,
      uploaded: { id: att.id, filename: att.filename, mime_type: att.mime_type },
    });
  }
  setImageMode(true);
  renderPending();
  els.input.focus();
  toast(t('toast_image_set_as_edit'));
}

document.addEventListener('click', (e) => {
  const img = e.target.closest && e.target.closest('.msg img[data-lightbox]');
  if (img) {
    const att = { id: img.dataset.attId, filename: img.dataset.filename, mime_type: img.dataset.mime };
    openLightbox(img.dataset.lightbox, { filename: att.filename, onUseAsReference: () => editImageInChat(att) });
    return;
  }
  const btn = e.target.closest && e.target.closest('[data-img-action="edit"]');
  if (btn) editImageInChat({ id: btn.dataset.attId, filename: btn.dataset.filename, mime_type: btn.dataset.mime });
});

/** Vollbild-Betrachter: Klick zoomt auf Originalgroesse, Leiste mit
 *  Herunterladen und "als Vorlage". */
function openLightbox(url, opts = {}) {
  document.getElementById('lightbox')?.remove();
  const lb = document.createElement('div');
  lb.id = 'lightbox';
  lb.className = 'lightbox';
  lb.innerHTML = `
    <div class="lb-stage"><img alt=""></div>
    <div class="lb-bar">
      ${opts.onUseAsReference ? `<button type="button" data-lb="ref" title="${escapeHtml(t('image_use_as_reference'))}"><svg class="icon"><use href="#icon-brush"/></svg></button>` : ''}
      <a href="${url}" download="${escapeHtml(opts.filename || 'bild')}" title="${escapeHtml(t('img_action_download'))}"><svg class="icon"><use href="#icon-download"/></svg></a>
      <button type="button" data-lb="close" title="${escapeHtml(t('lightbox_close'))}"><svg class="icon"><use href="#icon-close"/></svg></button>
    </div>`;
  const stage = lb.querySelector('.lb-stage');
  const img = lb.querySelector('img');
  img.src = url;
  const close = () => { lb.remove(); document.removeEventListener('keydown', onKey, true); };
  const onKey = (e) => { if (e.key === 'Escape') { e.stopPropagation(); close(); } };
  document.addEventListener('keydown', onKey, true);
  img.addEventListener('click', (e) => { e.stopPropagation(); stage.classList.toggle('zoomed'); });
  stage.addEventListener('click', (e) => { if (e.target === stage) close(); });
  lb.addEventListener('click', (e) => {
    const b = e.target.closest('[data-lb]');
    if (!b) return;
    if (b.dataset.lb === 'close') close();
    if (b.dataset.lb === 'ref') { close(); opts.onUseAsReference(); }
  });
  document.body.appendChild(lb);
}

// =========================================================
// Eingabefeld: Anhaenge, Plus-Menue, Bildmodus, runder Knopf
// =========================================================
let _pendingSeq = 0;
let _uploadsRunning = 0;
const _uploadQueue = [];

function addFiles(fileList, opts = {}) {
  let files = Array.from(fileList || []);
  if (!files.length) return;
  if (opts.photos && files.length > MAX_PICK) {
    toast(t('toast_pick_limit', MAX_PICK));
    files = files.slice(0, MAX_PICK);
  }
  if (state.chatLocked && !state.unlockedCids.has(state.cid)) return;
  for (const file of files) {
    if (file.size > MAX_UPLOAD_BYTES) {
      toast(t('toast_file_too_large', file.name, 50), { error: true });
      continue;
    }
    const item = {
      key: 'p' + (++_pendingSeq),
      file,
      filename: file.name || 'datei',
      mime: file.type || '',
      size: file.size,
      previewUrl: isImageMime(file.type) ? URL.createObjectURL(file) : null,
      uploading: true,
      error: null,
      uploaded: null,
    };
    state.pending.push(item);
    _uploadQueue.push(item);
  }
  renderPending();
  pumpUploads();
}
function pumpUploads() {
  while (_uploadsRunning < MAX_PARALLEL_UPLOADS && _uploadQueue.length) {
    const item = _uploadQueue.shift();
    if (!state.pending.includes(item)) continue;   // inzwischen entfernt
    _uploadsRunning++;
    (async () => {
      try {
        const prepared = await compressImage(item.file, 'vision');
        const r = await uploadFile(prepared.blob, prepared.filename);
        item.uploaded = r;
      } catch (e) {
        item.error = apiErrorText(e);
        toast(t('toast_upload_failed', item.error), { error: true });
      } finally {
        item.uploading = false;
        _uploadsRunning--;
        renderPending();
        pumpUploads();
      }
    })();
  }
}
function removePending(item) {
  state.pending = state.pending.filter((x) => x !== item);
  if (item.previewUrl && item.previewUrl.startsWith('blob:')) URL.revokeObjectURL(item.previewUrl);
  renderPending();
}
function renderPending() {
  const wrap = els.pendingWrap;
  wrap.innerHTML = '';
  wrap.classList.toggle('hidden', !state.pending.length);
  for (const p of state.pending) {
    const tile = document.createElement('div');
    const isImg = isImageMime(p.mime) && p.previewUrl;
    tile.className = 'pend-tile ' + (isImg ? 'image' : 'file');
    if (isImg) {
      tile.innerHTML = `<img alt="">`;
      tile.querySelector('img').src = p.previewUrl;
    } else {
      tile.innerHTML = `<span class="file-ico"><svg class="icon"><use href="#icon-file"/></svg></span>
        <span><span class="pend-name"></span><span class="pend-meta"></span></span>`;
      tile.querySelector('.pend-name').textContent = p.filename;
      tile.querySelector('.pend-meta').textContent = [fileExt(p.filename), formatBytes(p.size)].filter(Boolean).join(' · ');
    }
    if (p.uploading) tile.insertAdjacentHTML('beforeend', '<div class="pend-overlay"><span class="spinner"></span></div>');
    else if (p.error) tile.insertAdjacentHTML('beforeend', `<div class="pend-overlay error" title="${escapeHtml(p.error)}"><svg class="icon"><use href="#icon-error"/></svg></div>`);
    const rm = document.createElement('button');
    rm.type = 'button';
    rm.className = 'pend-remove';
    rm.title = t('remove_title');
    rm.innerHTML = '<svg class="icon"><use href="#icon-close"/></svg>';
    rm.addEventListener('click', (e) => { e.stopPropagation(); removePending(p); });
    tile.appendChild(rm);
    wrap.appendChild(tile);
  }
  updateComposerState();
}
/** Beim Chatwechsel: angefangene Anhaenge und Bildmodus gehoeren zum alten Chat. */
function resetComposerFor(_cid) {
  for (const p of state.pending) if (p.previewUrl && p.previewUrl.startsWith('blob:')) URL.revokeObjectURL(p.previewUrl);
  state.pending = [];
  _uploadQueue.length = 0;
  setImageMode(false);
  renderPending();
}

function setImageMode(on) {
  state.imageMode = !!on;
  els.imageChip.classList.toggle('hidden', !state.imageMode);
  els.input.placeholder = state.imageMode ? t('hint_image_mode') : t('compose_placeholder');
  updateComposerState();
}
els.imageChip.addEventListener('click', (e) => { e.stopPropagation(); setImageMode(false); els.input.focus(); });

function hasSendableContent() {
  return !!els.input.value.trim() || state.pending.some((p) => p.uploaded);
}
/** Karte aufklappen (Fokus, Text, Anhaenge, Bildmodus) und den runden Knopf
 *  passend schalten: Sprachgespraech, Senden oder Stoppen. */
function updateComposerState() {
  const focused = document.activeElement === els.input;
  const expanded = focused || !!els.input.value || state.pending.length > 0 || state.imageMode;
  els.inputForm.classList.toggle('expanded', expanded);
  const btn = els.sendBtn;
  const uploading = state.pending.some((p) => p.uploading);
  let mode;
  if (state.isStreaming) mode = 'stop';
  else if (hasSendableContent() || uploading) mode = 'send';
  else mode = 'voice';
  btn.dataset.mode = mode;
  btn.disabled = mode === 'send' && (uploading || !hasSendableContent());
  const icon = { stop: 'stop', send: 'arrow-up', voice: 'voice' }[mode];
  btn.innerHTML = `<svg class="icon"><use href="#icon-${icon}"/></svg>`;
  btn.title = mode === 'stop' ? t('stop') : mode === 'send' ? t('send_title') : t('voice_conversation');
}

function autoResize() {
  els.input.style.height = 'auto';
  els.input.style.height = Math.min(els.input.scrollHeight, Math.round(window.innerHeight * 0.4)) + 'px';
}
els.input.addEventListener('input', () => { autoResize(); updateComposerState(); });
els.input.addEventListener('focus', updateComposerState);
els.input.addEventListener('blur', () => setTimeout(updateComposerState, 120));
els.input.addEventListener('keydown', (e) => {
  // Enter sendet, Umschalt+Enter macht eine neue Zeile (wie ChatGPT).
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    if (!state.isStreaming) els.inputForm.requestSubmit();
    else toast(t('toast_reply_running'));
  }
});
els.input.addEventListener('paste', (e) => {
  const files = [...(e.clipboardData?.files || [])];
  if (files.length) { e.preventDefault(); addFiles(files); }
});
// Klick irgendwo auf die Karte setzt den Cursor ins Feld.
els.inputForm.addEventListener('mousedown', (e) => {
  if (e.target.closest('button, input, .pend-tile, .menu')) return;
  if (e.target !== els.input) { e.preventDefault(); els.input.focus(); }
});

els.attachBtn.addEventListener('click', (e) => { e.stopPropagation(); togglePopup(els.plusMenu, els.attachBtn); });
els.plusMenu.addEventListener('click', (e) => {
  const b = e.target.closest('[data-plus]');
  if (!b) return;
  closePopup();
  const what = b.dataset.plus;
  if (what === 'photos') els.photoInput.click();
  else if (what === 'files') els.fileInput.click();
  else if (what === 'camera') els.cameraInput.click();
  else if (what === 'image') { setImageMode(true); els.input.focus(); }
});
for (const [input, photos] of [[els.fileInput, false], [els.photoInput, true], [els.cameraInput, true]]) {
  input.addEventListener('change', (e) => {
    const files = [...e.target.files];
    e.target.value = '';
    addFiles(files, { photos });
  });
}

// Dateien ins Fenster ziehen: Overlay und Upload (nur in der Chat-Ansicht)
(function setupDragDrop() {
  const overlay = $('drop-overlay');
  let depth = 0;
  const hasFiles = (e) => !!e.dataTransfer && Array.from(e.dataTransfer.types || []).includes('Files');
  const canDrop = () => els.login.classList.contains('hidden') && els.settingsModal.classList.contains('hidden') && state.view === 'chat';
  window.addEventListener('dragenter', (e) => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    if (!canDrop()) return;
    depth++;
    overlay.classList.remove('hidden');
  });
  window.addEventListener('dragover', (e) => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    if (canDrop()) { try { e.dataTransfer.dropEffect = 'copy'; } catch (_) {} }
  });
  window.addEventListener('dragleave', (e) => {
    if (!hasFiles(e)) return;
    depth = Math.max(0, depth - 1);
    if (!depth) overlay.classList.add('hidden');
  });
  window.addEventListener('drop', (e) => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    depth = 0;
    overlay.classList.add('hidden');
    if (!canDrop()) return;
    addFiles(e.dataTransfer.files);
  });
})();

// Runder Knopf: Senden (submit), Stoppen oder Sprachgespraech
els.sendBtn.addEventListener('click', (e) => {
  const mode = els.sendBtn.dataset.mode;
  if (mode === 'stop') { e.preventDefault(); stopGenerating(); }
  else if (mode === 'voice') { e.preventDefault(); if (window.PocketVoice) window.PocketVoice.toggleAutoMode(); }
});

// =========================================================
// Senden und Streamen
// =========================================================
els.inputForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  await sendMessage(els.input.value);
});

/** Sendet Text plus fertig hochgeladene Anhaenge. Liefert true, wenn ein
 *  Turn gestartet wurde (fuer das Sprachgespraech). */
async function sendMessage(rawText, opts = {}) {
  const content = (rawText || '').trim();
  const uploaded = state.pending.filter((p) => p.uploaded);
  if (!content && !uploaded.length) return false;
  if (state.isStreaming) { toast(t('toast_reply_running')); return false; }
  // Ein noch laufender Upload ginge sonst stumm verloren.
  if (state.pending.some((p) => p.uploading)) { toast(t('chat_wait_for_uploads')); return false; }
  if (state.cid && state.chatLocked && !state.unlockedCids.has(state.cid)) return false;
  if (!state.cid) await newChat();
  if (!state.cid) return false;
  closeChatSearch();
  const atts = uploaded.map((p) => ({ id: p.uploaded.id, filename: p.uploaded.filename, mime_type: p.uploaded.mime_type }));
  const imageMode = state.imageMode;
  state.messages.push({ id: -Date.now(), role: 'user', content, attachments: atts, created_at: new Date().toISOString() });
  for (const p of state.pending) if (p.previewUrl && p.previewUrl.startsWith('blob:')) URL.revokeObjectURL(p.previewUrl);
  state.pending = [];
  setImageMode(false);
  renderPending();
  if (!opts.keepInput) { els.input.value = ''; autoResize(); }
  state.streamingText = '';
  state.streamingThinking = '';
  state._streamAttachments = [];
  state.isStreaming = true;
  state.stoppedByUser = false;
  updateComposerState();
  renderMessages();
  scrollToBottom(true);
  state._sseTurnStart = performance.now();
  state._sseGotDone = false;
  state._sseGotError = false;
  state._sseDeltaCount = 0;
  const cidAtSubmit = state.cid;
  console.log('PC_SSE: submit START cid=%s content_len=%d image_mode=%s', cidAtSubmit, content.length, imageMode);
  try {
    await streamReply(content, atts.map((a) => a.id), imageMode);
  } catch (err) {
    console.log('PC_SSE: submit CATCH', err?.name, err?.message);
    if (err.name !== 'AbortError') {
      toast(t('toast_reply_failed', apiErrorText(err)), { error: true });
    }
  } finally {
    const dt = (performance.now() - state._sseTurnStart).toFixed(0);
    console.log('PC_SSE: submit FINALLY cid=%s gotDone=%s gotError=%s deltas=%d elapsed=%sms',
      cidAtSubmit, state._sseGotDone, state._sseGotError, state._sseDeltaCount, dt);
    if (state.cid === cidAtSubmit && state.isStreaming && !state._sseGotDone && !state._sseGotError) {
      if (state.stoppedByUser) finalizeStopped();
      else {
        // Stream zu, aber weder done noch Fehler: der Server hat die Antwort
        // vermutlich gespeichert. Neu laden statt Punkte stehen zu lassen.
        console.warn('PC_SSE: submit RESCUE — stream ended without done; reloading messages');
        state.isStreaming = false;
        state.streamingText = '';
        reloadChatMessages(cidAtSubmit);
      }
    }
    state.isStreaming = false;
    state.abort = null;
    updateComposerState();
  }
  refreshChatList();
  return true;
}

function stopStreamLocal() {
  if (state.abort) { try { state.abort.abort(); } catch {} state.abort = null; }
  state.isStreaming = false;
  state.streamingText = '';
  state.streamingThinking = '';
  state._streamAttachments = [];
}
/** Stoppen wie in der App: Verbindung kappen, bisherigen Text als
 *  abgebrochene Antwort stehen lassen. */
function stopGenerating() {
  if (!state.isStreaming) return;
  state.stoppedByUser = true;
  if (state.abort) { try { state.abort.abort(); } catch {} }
}
function finalizeStopped() {
  const partial = state.streamingText;
  if (partial) {
    state.messages.push({
      id: -Date.now(), role: 'assistant',
      content: partial + '\n\n_' + t('generated_chat_aborted') + '_',
      attachments: state._streamAttachments.slice(),
      _thinking: state.streamingThinking,
      created_at: new Date().toISOString(),
    });
  }
  state.isStreaming = false;
  state.streamingText = '';
  state.streamingThinking = '';
  state._streamAttachments = [];
  renderMessages();
}

// Gedaechtnis-Schluessel (wie in der App): je Konto ein Eintrag, gebunden an
// die Server-Adresse. Geht nur ueber HTTPS und nur mit Chat-Nachrichten raus.
const WISSEN_PREFIX = 'pc.wissen.';
const WISSEN_FORMAT = /^[A-Za-z0-9_-]{43}=?$/;
function serverOrigin() { try { return new URL(state.serverUrl).origin; } catch { return ''; } }
function sichereHerkunft(origin) {
  return origin.startsWith('https://') || /^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(origin);
}
function wissenSchluessel() {
  if (!state.me || !state.me.id) return '';
  const origin = serverOrigin();
  if (!sichereHerkunft(origin)) return '';
  try {
    const e = JSON.parse(localStorage.getItem(WISSEN_PREFIX + state.me.id) || 'null');
    return e && e.o === origin && WISSEN_FORMAT.test(e.k || '') ? e.k : '';
  } catch { return ''; }
}
function wissenVergessen() {
  Object.keys(localStorage).filter((k) => k.startsWith(WISSEN_PREFIX)).forEach((k) => localStorage.removeItem(k));
}

async function streamReply(content, attachmentIds, imageMode) {
  if (state.abort) { try { state.abort.abort(); } catch {} }
  const ctrl = new AbortController();
  state.abort = ctrl;
  const headers = {
    'Authorization': 'Bearer ' + state.token,
    'Content-Type': 'application/json',
    'Accept': 'text/event-stream',
  };
  const wissen = wissenSchluessel();
  if (wissen) headers['X-Wissen-Schluessel'] = wissen;
  const resp = await fetch(state.serverUrl + '/conversations/' + state.cid + '/messages', {
    method: 'POST',
    headers,
    // Mit Schluessel keiner Weiterleitung folgen: der Browser wuerde den Header
    // auch an eine fremde Adresse mitschicken.
    redirect: wissen ? 'error' : 'follow',
    body: JSON.stringify({
      content,
      attachment_ids: attachmentIds,
      effort: currentEffort(),
      // Leerer String heisst ausdruecklich "nimm Claude". null waere "keine
      // Angabe" und liesse das zuletzt benutzte Modell weiterlaufen.
      model: effectiveModelKey(),
      system_prompt_mode: state.spMode,
      system_prompt: state.spMode === 'CUSTOM' ? state.spCustom : null,
      tts_voice: state.ttsVoice,
      tts_rate: state.ttsSpeed,
      image_mode: !!imageMode,
    }),
    signal: ctrl.signal,
  });
  if (!resp.ok) {
    const txt = await resp.text().catch(() => '');
    console.log('PC_SSE: streamReply HTTP-FAIL status=%s body=%s', resp.status, txt.slice(0, 200));
    throw new ApiError(resp.status, txt);
  }
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      if (buffer.length) console.warn('PC_SSE: streamReply UNFLUSHED-BUFFER:', buffer.slice(0, 400));
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buffer.indexOf('\n\n')) >= 0) {
      const raw = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      handleSseEvent(raw);
    }
  }
}

function handleSseEvent(raw) {
  let event = 'message';
  let data = '';
  for (const line of raw.split('\n')) {
    if (line.startsWith('event:')) event = line.slice(6).trim();
    else if (line.startsWith('data:')) data += line.slice(5).trim();
  }
  let payload = {};
  if (data) { try { payload = JSON.parse(data); } catch {} }
  if (event === 'delta') {
    state._sseDeltaCount = (state._sseDeltaCount || 0) + 1;
    if (state._sseDeltaCount <= 3 || state._sseDeltaCount % 25 === 0) {
      console.log('PC_SSE: recv delta #%d len=%d', state._sseDeltaCount, (payload.text || '').length);
    }
  } else if (event !== 'thinking_delta') {
    console.log('PC_SSE: recv event=%s payload=%o', event, payload);
  }
  switch (event) {
    case 'title': {
      state.title = payload.title || state.title;
      const chat = state.chats.find((c) => c.id === state.cid);
      if (chat) chat.title = state.title;
      const item = document.querySelector(`.chat-item[data-cid="${CSS.escape(state.cid || '')}"] .title`);
      if (item) item.textContent = state.title;
      updateTopbar();
      break;
    }
    case 'user_saved': {
      const lastUser = [...state.messages].reverse().find((m) => m.role === 'user' && m.id < 0);
      if (lastUser) lastUser.id = payload.user_message_id;
      break;
    }
    case 'delta':
      state.streamingText += payload.text || '';
      updateStreaming();
      break;
    case 'thinking_delta':
      state.streamingThinking += payload.text || '';
      updateStreaming();
      break;
    case 'image':
      // Das Modell hat mitten in der Antwort Bilder erzeugt: sofort zeigen.
      (payload.attachments || []).forEach((a) => {
        if (a && a.id && !state._streamAttachments.some((x) => x.id === a.id)) state._streamAttachments.push(a);
      });
      updateStreaming();
      break;
    case 'done': {
      state._sseGotDone = true;
      const msgId = payload.assistant_message_id || payload.message_id;
      state.messages.push({
        id: msgId,
        role: 'assistant',
        content: state.streamingText,
        attachments: state._streamAttachments.slice(),
        _thinking: state.streamingThinking,
        tokens: (payload.tokens_in || 0) + (payload.tokens_out || 0),
        created_at: new Date().toISOString(),
      });
      state._streamAttachments = [];
      state.streamingText = '';
      state.streamingThinking = '';
      state.isStreaming = false;
      renderMessages();
      updateComposerState();
      refreshChatList();
      // Vorlesen: im Sprachgespraech immer, sonst nach Chat- bzw. Standardwahl.
      const voiceLoop = window.PocketVoice && window.PocketVoice.isAutoMode();
      if (msgId && (voiceLoop || autoSpeakFor(state.cid))) speak(msgId);
      break;
    }
    case 'error':
      state._sseGotError = true;
      state._streamAttachments = [];
      toast(t('toast_server_error', payload.message || ''), { error: true });
      state.isStreaming = false;
      state.streamingText = '';
      state.streamingThinking = '';
      renderMessages();
      updateComposerState();
      break;
    case 'compaction_started':
      toast(t('toast_compacting'));
      break;
  }
}

// =========================================================
// Vorlesen
// =========================================================
function renderTtsSlots() {
  document.querySelectorAll('.msg[data-mid] .tts-slot').forEach((slot) => {
    const id = Number(slot.closest('.msg').dataset.mid);
    slot.innerHTML = ttsButtonsHtml({ id });
  });
}
function setAudioState(msgId, status) {
  state.audio = { msgId: status === 'idle' ? null : msgId, status };
  renderTtsSlots();
}
function speak(messageId) {
  els.audio.pause();
  const params = new URLSearchParams({ voice: state.ttsVoice, rate: String(state.ttsSpeed), token: state.token });
  els.audio.src = `${state.serverUrl}/messages/${messageId}/audio?${params}`;
  setAudioState(messageId, 'loading');
  els.audio.play().catch((err) => {
    if (err.name === 'AbortError') return;
    setAudioState(messageId, 'idle');
    toast(t('toast_playback', err.message), { error: true });
  });
}
function pauseAudio() { els.audio.pause(); }
function resumeAudio() { els.audio.play().catch(() => {}); }
function stopAudio() {
  try { els.audio.pause(); els.audio.removeAttribute('src'); els.audio.load(); } catch (_) {}
  if (state.audio.status !== 'idle') setAudioState(null, 'idle');
}
els.audio.addEventListener('playing', () => { if (state.audio.msgId) setAudioState(state.audio.msgId, 'playing'); });
els.audio.addEventListener('pause', () => {
  if (state.audio.msgId && state.audio.status === 'playing' && !els.audio.ended) setAudioState(state.audio.msgId, 'paused');
});
els.audio.addEventListener('ended', () => setAudioState(null, 'idle'));
els.audio.addEventListener('error', () => {
  if (!state.audio.msgId) return;
  setAudioState(null, 'idle');
  toast(t('toast_tts_error', t('tts_unavailable')), { error: true });
});
function isAudioBusy() { return state.audio.status === 'loading' || state.audio.status === 'playing'; }

// =========================================================
// Tastatur
// =========================================================
document.addEventListener('keydown', (e) => {
  const mod = e.metaKey || e.ctrlKey;
  if (mod && !e.shiftKey && e.key.toLowerCase() === 'k') {
    if (els.app.classList.contains('hidden')) return;
    e.preventDefault();
    if (els.searchModal.classList.contains('hidden')) openSearch(); else closeSearch();
    return;
  }
  if (mod && e.shiftKey && e.key.toLowerCase() === 'o') {
    if (els.app.classList.contains('hidden')) return;
    e.preventDefault();
    newChat();
    return;
  }
  if (mod && !e.shiftKey && e.key.toLowerCase() === 'f' && state.view === 'chat' && state.messages.length
      && els.settingsModal.classList.contains('hidden') && els.searchModal.classList.contains('hidden')) {
    e.preventDefault();
    openChatSearch();
    return;
  }
  if (e.key === 'Escape') {
    if (openPopup) { closePopup(); return; }
    if (!els.searchModal.classList.contains('hidden')) { closeSearch(); return; }
    if (searchState.open) { closeChatSearch(); return; }
    if (isMobile() && els.sidebar.classList.contains('open')) { closeSidebar(); return; }
    if (state.isStreaming && document.activeElement === els.input) stopGenerating();
  }
});

// Start, sobald alle Teile (voice.js, gems.js, images.js, settings.js) geladen sind.
document.addEventListener('DOMContentLoaded', () => {
  if (window.PocketI18n) window.PocketI18n.applyI18n();
  setImageMode(false);
  updateComposerState();
  if (state.serverUrl && state.token) showApp(); else showLogin();
});
document.addEventListener('pc:locale-changed', () => {
  setImageMode(state.imageMode);
  renderFooterUser();
  renderChatList();
  renderModelMenu();
  updateModelButton();
  if (state.view === 'chat') renderMessages();
});
