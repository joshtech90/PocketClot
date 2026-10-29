// =====================================================================
// Spracheingabe: Diktat ins Eingabefeld und Sprachgespraech (Auto-Modus).
// Spiegelt die App: Aufnahme -> Upload -> Whisper-Text. Im Sprachgespraech
// geht der Text direkt raus, die Antwort wird vorgelesen, dann hoert es
// wieder zu. "Automatisch senden" schickt nach Stille ab (wie AutoModeBar).
// =====================================================================
window.PocketVoice = (() => {
  const micBtn = $('mic-btn');
  const bar = $('voice-bar');
  const barText = $('voice-bar-text');
  const barHint = $('voice-bar-hint');
  const barSend = $('voice-bar-send');
  const barStop = $('voice-bar-stop');
  const orb = $('voice-orb');
  const autoSendBox = $('voice-auto-send');
  const silenceEl = $('voice-silence');
  const LS_AUTO_SEND = 'pc.voiceAutoSend';
  // Stille bis zum automatischen Senden; kommt wie in der App aus den
  // geteilten Einstellungen, sonst 3 s.
  const LS_SILENCE_MS = 'pc.voiceSilenceMs';

  // Werte wie in der App (ChatViewModel.runAutoModeLoop): 5 s Bedenkzeit am
  // Anfang, danach sendet 3 s Stille automatisch, wenn der Schalter an ist.
  const VAD_INITIAL_BLOCK_MS = 5000;
  const VAD_SILENCE_MS = 3000;
  const VAD_POLL_MS = 80;

  let mediaRecorder = null;
  let mediaStream = null;
  let chunks = [];
  let micState = 'idle';          // idle | recording | busy
  let autoMode = false;
  let autoAbort = null;
  let listenResolve = null;       // beendet das Zuhoeren im Sprachgespraech
  let vad = null;                 // { ctx, timer }
  let autoSend = localStorage.getItem(LS_AUTO_SEND) === 'true';
  function silenceMs() {
    const v = Number(localStorage.getItem(LS_SILENCE_MS));
    return v >= 500 && v <= 10000 ? v : VAD_SILENCE_MS;
  }
  // Jede Aufnahme hat eine Generation. Abbrechen zaehlt hoch: eine spaet
  // eintreffende Mikrofon-Freigabe oder Transkription gehoert dann zu einer
  // verworfenen Aufnahme und wird nicht mehr verwendet.
  let recGen = 0;
  let transcribeAbort = null;

  function isLlmBusy() { return state.isStreaming || isAudioBusy(); }

  function setMicState(s) {
    micState = s;
    if (!micBtn) return;
    micBtn.classList.remove('idle', 'recording', 'busy');
    micBtn.classList.add(s);
    micBtn.title = s === 'recording' ? t('voice_mic_recording_title') : t('voice_mic_title');
    updateMicEnabled();
  }
  /** Waehrend einer Antwort oder beim Vorlesen kein Mikrofon: es wuerde die
   *  Wiedergabe mit aufnehmen. Eine laufende Aufnahme bleibt stoppbar. */
  function updateMicEnabled() {
    if (!micBtn) return;
    const off = isLlmBusy() && micState !== 'recording';
    micBtn.disabled = off;
    micBtn.classList.toggle('mic-disabled', off);
  }

  async function startRecording({ withVad = false, signal = null } = {}) {
    if (micState !== 'idle') return false;
    if (isLlmBusy()) { toast(t('voice_error_llm_busy'), { error: true }); return false; }
    const gen = ++recGen;
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    } catch {
      if (gen === recGen) toast(t('voice_error_no_permission'), { error: true });
      return false;
    }
    // Waehrend der Freigabe abgebrochen (Sprachgespraech beendet, Chat
    // gewechselt): das Mikrofon sofort wieder schliessen.
    if (gen !== recGen || (signal && signal.aborted) || micState !== 'idle') {
      stream.getTracks().forEach((tr) => tr.stop());
      return false;
    }
    mediaStream = stream;
    chunks = [];
    const opts = window.MediaRecorder && MediaRecorder.isTypeSupported('audio/webm;codecs=opus') ? { mimeType: 'audio/webm;codecs=opus' } : {};
    try {
      mediaRecorder = new MediaRecorder(mediaStream, opts);
    } catch (e) {
      stopStream();
      toast(t('voice_error_start_failed', e.message), { error: true });
      return false;
    }
    mediaRecorder.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data); };
    mediaRecorder.start(250);
    setMicState('recording');
    if (withVad) startVad();
    return true;
  }

  function stopStream() {
    stopVad();
    if (mediaStream) { mediaStream.getTracks().forEach((tr) => tr.stop()); mediaStream = null; }
    mediaRecorder = null;
  }

  /** Stoppt die Aufnahme und laedt sie hoch. Liefert den erkannten Text
   *  (leer bei zu kurzer Aufnahme oder Fehler). */
  async function stopAndTranscribe() {
    if (micState !== 'recording' || !mediaRecorder) return '';
    const gen = recGen;
    const cid = state.cid;
    const rec = mediaRecorder;
    const done = new Promise((resolve) => rec.addEventListener('stop', resolve, { once: true }));
    rec.stop();
    await done;
    const mime = rec.mimeType || 'audio/webm';
    const blob = new Blob(chunks, { type: mime });
    stopStream();
    chunks = [];
    if (gen !== recGen) return '';
    if (blob.size < 1000) { setMicState('idle'); return ''; }
    setMicState('busy');
    const ctrl = new AbortController();
    transcribeAbort = ctrl;
    try {
      const locale = (localStorage.getItem('pc_locale') || '').trim() || navigator.language || 'en';
      const fd = new FormData();
      const ext = mime.includes('webm') ? 'webm' : mime.includes('mp4') ? 'm4a' : 'wav';
      fd.append('file', blob, `voice-${Date.now()}.${ext}`);
      fd.append('language', locale);
      const data = await api('POST', '/voice/transcribe', fd, { signal: ctrl.signal });
      // Inzwischen abgebrochen oder anderer Chat: der Text gehoert nicht hierher.
      if (gen !== recGen || state.cid !== cid) return '';
      setMicState('idle');
      return ((data && data.text) || '').trim();
    } catch (e) {
      if (gen !== recGen || (e && e.name === 'AbortError')) return '';
      setMicState('idle');
      toast(t('voice_error_transcribe_failed', apiErrorText(e)), { error: true });
      return '';
    } finally {
      if (transcribeAbort === ctrl) transcribeAbort = null;
    }
  }

  function cancelRecording() {
    // Immer hochzaehlen, auch ohne laufende Aufnahme: so verfaellt auch eine
    // Mikrofon-Freigabe, auf die gerade noch gewartet wird.
    recGen++;
    if (transcribeAbort) { try { transcribeAbort.abort(); } catch (_) {} transcribeAbort = null; }
    try { if (mediaRecorder && mediaRecorder.state !== 'inactive') mediaRecorder.stop(); } catch (_) {}
    stopStream();
    chunks = [];
    if (micState !== 'idle') setMicState('idle');
  }

  function insertTranscript(text) {
    if (!text) return;
    const input = els.input;
    input.value = input.value.trim() ? input.value.replace(/\s*$/, ' ') + text : text;
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.focus();
    // Cursor ans Ende, wie in der App bei Text von aussen.
    input.setSelectionRange(input.value.length, input.value.length);
  }

  // ---- Stille-Erkennung (VAD) ----
  function startVad() {
    stopVad();
    if (!autoSend || !mediaStream) return;
    let ctx;
    try { ctx = new (window.AudioContext || window.webkitAudioContext)(); } catch { return; }
    const src = ctx.createMediaStreamSource(mediaStream);
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 2048;
    src.connect(analyser);
    const buf = new Float32Array(analyser.fftSize);
    const started = performance.now();
    let noiseFloor = Infinity;
    let silentMs = 0;
    const timer = setInterval(() => {
      if (micState !== 'recording') return;
      analyser.getFloatTimeDomainData(buf);
      let sum = 0;
      for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i];
      const rms = Math.sqrt(sum / buf.length);
      const elapsed = performance.now() - started;
      if (elapsed < 1000) { noiseFloor = Math.min(noiseFloor, rms); return; }
      // Schwelle relativ zum Grundrauschen, aber nie empfindlicher als 0.012.
      const threshold = Math.max(0.012, (isFinite(noiseFloor) ? noiseFloor : 0) * 3);
      if (!autoSend || elapsed < VAD_INITIAL_BLOCK_MS) { setSilence(0); return; }
      if (rms < threshold) silentMs += VAD_POLL_MS; else silentMs = 0;
      setSilence(silentMs / silenceMs());
      if (silentMs >= silenceMs()) {
        setSilence(0);
        finishListening();
      }
    }, VAD_POLL_MS);
    vad = { ctx, timer };
  }
  function stopVad() {
    if (!vad) return;
    clearInterval(vad.timer);
    try { vad.ctx.close(); } catch (_) {}
    vad = null;
    setSilence(0);
  }
  function setSilence(frac) {
    if (silenceEl) silenceEl.style.width = Math.round(Math.min(1, frac) * 100) + '%';
  }

  // ---- Sprachgespraech ----
  const PHASE_TEXT = {
    listening: 'voice_listening',
    transcribing: 'voice_transcribing',
    thinking: 'voice_answering',
    speaking: 'voice_speaking',
    idle: 'voice_ready',
  };
  function setPhase(phase) {
    if (!bar) return;
    bar.dataset.phase = phase;
    barText.textContent = t(PHASE_TEXT[phase] || 'voice_ready');
    barHint.textContent = phase === 'listening'
      ? (autoSend ? t('voice_hint_listening_auto') : t('voice_hint_listening'))
      : phase === 'speaking' ? t('voice_hint_speaking') : '';
    barSend.classList.toggle('hidden', phase !== 'listening');
    // Der Klumpen ist die Bedienflaeche: zuhoeren = senden, vorlesen = unterbrechen.
    if (orb) {
      orb.disabled = phase !== 'listening' && phase !== 'speaking';
      orb.setAttribute('aria-label', phase === 'speaking' ? t('stop_reading')
        : phase === 'listening' ? t('voice_send_now') : barText.textContent);
    }
  }
  function showBar(on) {
    bar.classList.toggle('hidden', !on);
    els.inputForm.classList.toggle('hidden', on);
    if (on) renderSpeed();
  }

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  function waitFor(pred, signal, every = 150) {
    return new Promise((resolve) => {
      const check = () => {
        if (signal && signal.aborted) return resolve(false);
        let ok = false;
        try { ok = pred(); } catch { ok = true; }
        if (ok) return resolve(true);
        setTimeout(check, every);
      };
      check();
    });
  }

  /** Einmal zuhoeren: endet per "Senden", Mikrofon-Klick oder Stille. */
  async function listenOnce(signal) {
    const ok = await startRecording({ withVad: true, signal });
    if (!ok || signal.aborted) { if (ok) cancelRecording(); return null; }
    let onAbort = null;
    try {
      await new Promise((resolve) => {
        listenResolve = resolve;
        onAbort = resolve;
        signal.addEventListener('abort', onAbort, { once: true });
      });
    } finally {
      // Je Runde ein Listener; nach der Runde wieder weg, sonst sammeln sie sich.
      signal.removeEventListener('abort', onAbort);
      listenResolve = null;
    }
    if (signal.aborted) { cancelRecording(); return null; }
    setPhase('transcribing');
    return stopAndTranscribe();
  }
  function finishListening() { if (listenResolve) listenResolve(); }

  async function startAutoMode() {
    if (autoMode) return;
    if (!state.cid || (state.chatLocked && !state.unlockedCids.has(state.cid))) return;
    autoMode = true;
    autoAbort = new AbortController();
    const signal = autoAbort.signal;
    showBar(true);
    setPhase('idle');
    try {
      while (autoMode && !signal.aborted) {
        // Erst wenn alles ruhig ist: sonst nimmt das Mikrofon die Wiedergabe auf.
        await waitFor(() => micState === 'idle' && !isLlmBusy(), signal, 200);
        if (signal.aborted) break;
        setPhase('listening');
        const text = await listenOnce(signal);
        if (text === null || signal.aborted) break;
        if (!text) { setPhase('idle'); await sleep(300); continue; }
        setPhase('thinking');
        const started = await sendMessage(text, { keepInput: true });
        if (!started) break;
        await waitFor(() => !state.isStreaming, signal, 200);
        if (signal.aborted) break;
        // Der done-Handler startet das Vorlesen; kurz warten, bis es laeuft.
        setPhase('speaking');
        await sleep(500);
        await waitFor(() => !isAudioBusy(), signal, 250);
      }
    } finally {
      stopAutoMode();
    }
  }
  function stopAutoMode() {
    if (!autoMode && bar.classList.contains('hidden')) return;
    autoMode = false;
    state.suppressTurnSpeech = true;
    stopAudio();
    if (autoAbort) { autoAbort.abort(); autoAbort = null; }
    cancelRecording();
    finishListening();
    showBar(false);
    setSilence(0);
  }
  const speedInput = $('voice-speed');
  const speedValue = $('voice-speed-value');
  const speedReset = $('voice-speed-reset');
  function renderSpeed() {
    if (!speedInput) return;
    speedInput.value = chatTtsSpeed();
    speedValue.textContent = chatTtsSpeed().toFixed(2) + '×';
    speedReset.disabled = !Object.hasOwn(validChatSpeeds(state.ttsSpeedByChat), state.cid);
  }
  speedInput?.addEventListener('input', () => {
    if (!state.cid) return;
    state.ttsSpeedByChat = { ...validChatSpeeds(state.ttsSpeedByChat), [state.cid]: Number(speedInput.value) };
    localStorage.setItem(LS.ttsSpeedByChat, JSON.stringify(state.ttsSpeedByChat));
    updateAudioSpeed();
    renderSpeed();
    queueSettingsPush();
  });
  speedReset?.addEventListener('click', () => {
    delete state.ttsSpeedByChat[state.cid];
    localStorage.setItem(LS.ttsSpeedByChat, JSON.stringify(state.ttsSpeedByChat));
    updateAudioSpeed();
    renderSpeed();
    queueSettingsPush();
  });
  function toggleAutoMode() {
    if (autoMode) { stopAutoMode(); stopAudio(); }
    else startAutoMode();
  }
  function resetForChatSwitch() {
    if (autoMode) stopAutoMode();
    cancelRecording();
  }

  // ---- Bedienung ----
  if (micBtn) {
    // Klick startet/stoppt das Diktat, langes Druecken waehrend der Aufnahme verwirft sie.
    let pressTimer = null;
    let longPressed = false;
    micBtn.addEventListener('pointerdown', () => {
      longPressed = false;
      pressTimer = setTimeout(() => {
        if (micState === 'recording') { longPressed = true; cancelRecording(); toast(t('voice_cancelled')); }
      }, 700);
    });
    const clear = () => { clearTimeout(pressTimer); pressTimer = null; };
    micBtn.addEventListener('pointerup', clear);
    micBtn.addEventListener('pointerleave', clear);
    micBtn.addEventListener('click', async (e) => {
      e.preventDefault();
      if (longPressed) { longPressed = false; return; }
      if (micState === 'idle') await startRecording();
      else if (micState === 'recording') insertTranscript(await stopAndTranscribe());
    });
  }
  barSend?.addEventListener('click', finishListening);
  // Unterbrechen: der Loop wartet nur aufs Ende der Wiedergabe und hoert
  // danach von selbst wieder zu (vorgelesen wird erst nach der Antwort).
  orb?.addEventListener('click', () => {
    if (!autoMode) return;
    if (bar.dataset.phase === 'speaking') stopAudio();
    else if (bar.dataset.phase === 'listening') finishListening();
  });
  barStop?.addEventListener('click', () => { stopAutoMode(); stopAudio(); });
  if (autoSendBox) {
    autoSendBox.checked = autoSend;
    autoSendBox.addEventListener('change', () => {
      autoSend = autoSendBox.checked;
      localStorage.setItem(LS_AUTO_SEND, String(autoSend));
      queueSettingsPush();
      if (autoMode && micState === 'recording') { if (autoSend) startVad(); else stopVad(); }
      if (autoMode) setPhase(bar.dataset.phase || 'listening');
    });
  }
  // Einstellungen vom Server (z.B. in der App umgestellt) uebernehmen.
  document.addEventListener('pc:settings-synced', () => {
    autoSend = localStorage.getItem(LS_AUTO_SEND) === 'true';
    if (autoSendBox) autoSendBox.checked = autoSend;
    renderSpeed();
    updateAudioSpeed();
  });
  setInterval(updateMicEnabled, 400);
  // Vorlesen startet schon im done-Handler, die Schleife merkt es erst, wenn
  // die Verbindung zu ist. Bis dahin waere der Klumpen grau gesperrt und das
  // Unterbrechen unmoeglich (Sol 28.10.2026): Phase am Audio ablesen.
  setInterval(() => {
    if (autoMode && bar.dataset.phase === 'thinking' && isAudioBusy()) setPhase('speaking');
  }, 300);
  setMicState('idle');

  // ---- Einstellungen: Groq-Schluessel und Transkriptions-Sprache ----
  const voiceKeyInput = $('voice-api-key-input');
  const voiceKeyStatus = $('voice-api-key-status');
  const langModeAuto = $('voice-lang-mode-auto');
  const langModeOverride = $('voice-lang-mode-override');
  const langOverrideBlock = $('voice-lang-override-block');
  const langSelect = $('voice-lang-select');
  const langCustomInput = $('voice-lang-custom');
  const langApplyBtn = $('voice-lang-apply');
  const translateStatus = $('voice-translate-status');
  const promptText = $('voice-prompt-text');
  const promptLabel = $('voice-prompt-label');
  const promptSource = $('voice-prompt-source');
  const promptActions = $('voice-prompt-actions');
  const CUSTOM = '__custom__';
  let lastCfg = null;

  function renderVoiceCfg(cfg) {
    lastCfg = cfg;
    if (voiceKeyStatus) {
      voiceKeyStatus.className = 'backup-status set-pad' + (cfg.configured ? ' ok' : '');
      voiceKeyStatus.textContent = cfg.configured ? `${cfg.api_key_masked || ''} · ${cfg.model || ''}` : t('voice_key_not_set');
    }
    const isOverride = cfg.lang_mode === 'override';
    if (langModeAuto) langModeAuto.checked = !isOverride;
    if (langModeOverride) langModeOverride.checked = isOverride;
    langOverrideBlock?.classList.toggle('hidden', !isOverride);
    if (langSelect) {
      langSelect.innerHTML = '';
      const names = cfg.language_names || {};
      const bundled = (cfg.bundled_languages || []).slice().sort((a, b) => (names[a] || a).localeCompare(names[b] || b));
      for (const code of bundled) {
        const o = document.createElement('option');
        o.value = code;
        o.textContent = `${names[code] || code} (${code})`;
        langSelect.appendChild(o);
      }
      for (const code of cfg.cached_languages || []) {
        if (bundled.includes(code)) continue;
        const o = document.createElement('option');
        o.value = code;
        o.textContent = `${code} — ${t('voice_lang_tag_translated')}`;
        langSelect.appendChild(o);
      }
      const custom = document.createElement('option');
      custom.value = CUSTOM;
      custom.textContent = t('voice_lang_custom');
      langSelect.appendChild(custom);
      const current = cfg.lang_override || cfg.current_lang || 'en';
      const isCustom = isOverride && !bundled.includes(current) && !(cfg.cached_languages || []).includes(current);
      langSelect.value = isCustom ? CUSTOM : current;
      if (langCustomInput) { langCustomInput.value = isCustom ? current : ''; langCustomInput.classList.toggle('hidden', !isCustom); }
      langApplyBtn?.classList.toggle('hidden', !isCustom);
    }
    if (promptText) promptText.textContent = cfg.current_prompt || '';
    if (promptLabel) promptLabel.textContent = t('voice_prompt_preview_label', cfg.current_lang || 'en');
    if (promptSource) {
      const map = { bundled: t('voice_lang_tag_bundled'), cache: t('voice_lang_tag_translated'), fallback: t('voice_lang_tag_fallback') };
      promptSource.textContent = map[cfg.current_prompt_source] || cfg.current_prompt_source || '';
    }
    promptActions?.classList.toggle('hidden', cfg.current_prompt_source !== 'cache');
  }
  async function loadVoiceConfig() {
    try { renderVoiceCfg(await api('GET', '/voice/config')); } catch (_) { /* Server evtl. aelter */ }
  }
  async function setLangConfig(mode, locale) {
    try {
      const cfg = await api('PUT', '/voice/lang-config', { mode, locale: locale || null });
      renderVoiceCfg(cfg);
      if (mode === 'override' && cfg.current_prompt_source === 'fallback') await translatePrompt(cfg.current_lang, false);
      else if (translateStatus) translateStatus.textContent = '';
    } catch (e) {
      if (translateStatus) { translateStatus.className = 'backup-status error'; translateStatus.textContent = t('voice_translate_error', apiErrorText(e)); }
    }
  }
  async function translatePrompt(locale, force) {
    if (!locale) return;
    if (translateStatus) { translateStatus.className = 'backup-status'; translateStatus.textContent = t('voice_translate_running'); }
    try {
      await api('POST', '/voice/prompt/translate', { locale, force: !!force });
      if (translateStatus) { translateStatus.className = 'backup-status ok'; translateStatus.textContent = t('voice_translate_success'); }
      await loadVoiceConfig();
    } catch (e) {
      if (translateStatus) { translateStatus.className = 'backup-status error'; translateStatus.textContent = t('voice_translate_error', apiErrorText(e)); }
    }
  }
  langModeAuto?.addEventListener('change', () => { if (langModeAuto.checked) setLangConfig('auto', null); });
  langModeOverride?.addEventListener('change', () => {
    if (!langModeOverride.checked) return;
    const v = langSelect && langSelect.value && langSelect.value !== CUSTOM ? langSelect.value : (lastCfg && lastCfg.current_lang) || 'en';
    setLangConfig('override', v);
  });
  langSelect?.addEventListener('change', () => {
    const v = langSelect.value;
    const custom = v === CUSTOM;
    langCustomInput?.classList.toggle('hidden', !custom);
    langApplyBtn?.classList.toggle('hidden', !custom);
    if (!custom) setLangConfig('override', v);
  });
  langApplyBtn?.addEventListener('click', () => {
    const v = (langCustomInput.value || '').trim().toLowerCase();
    if (v.length >= 2) setLangConfig('override', v);
  });
  $('voice-retranslate-btn')?.addEventListener('click', () => { if (lastCfg) translatePrompt(lastCfg.current_lang, true); });
  $('voice-reset-cache-btn')?.addEventListener('click', async () => {
    if (!lastCfg) return;
    try {
      await api('DELETE', '/voice/prompt/cache/' + encodeURIComponent(lastCfg.current_lang));
      await loadVoiceConfig();
      if (translateStatus) translateStatus.textContent = '';
    } catch (e) { toast(t('toast_error_prefix', apiErrorText(e)), { error: true }); }
  });
  $('voice-api-key-save')?.addEventListener('click', async () => {
    const key = (voiceKeyInput.value || '').trim();
    if (!key) return;
    try {
      await api('PUT', '/voice/credentials', { api_key: key });
      voiceKeyInput.value = '';
      toast(t('toast_api_key_saved'));
      await loadVoiceConfig();
    } catch (e) { toast(t('toast_save_failed', apiErrorText(e)), { error: true }); }
  });
  $('voice-api-key-delete')?.addEventListener('click', async () => {
    if (!(await showConfirm({ title: t('remove'), text: t('confirm_remove_api_key'), okLabel: t('remove'), danger: true }))) return;
    try {
      await api('DELETE', '/voice/credentials');
      voiceKeyInput.value = '';
      toast(t('toast_removed'));
      await loadVoiceConfig();
    } catch (e) { toast(t('toast_error_prefix', apiErrorText(e)), { error: true }); }
  });
  document.addEventListener('pc:settings-open', loadVoiceConfig);
  document.addEventListener('pc:locale-changed', () => { if (lastCfg) renderVoiceCfg(lastCfg); if (autoMode) setPhase(bar.dataset.phase); });

  return { toggleAutoMode, resetForChatSwitch, isAutoMode: () => autoMode };
})();
