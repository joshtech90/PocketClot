(function () {
  'use strict';

  var MAX_REFS = 4;
  var ALLOWED_MIME = ['image/png', 'image/jpeg', 'image/webp'];

  var scrollEl = null;
  var cardEl = null;
  var refsLabelEl = null;
  var refsClearBtn = null;
  var refsContainer = null;
  var promptEl = null;
  var providerRowEl = null;
  var providerContainer = null;
  var sizeContainer = null;
  var aspectContainer = null;
  var countContainer = null;
  var hintEl = null;
  var statusEl = null;
  var generateBtn = null;
  var generateLabelEl = null;
  var refInput = null;
  var clearHistoryBtn = null;
  var historyContainer = null;

  var config = null;
  var configLoadFailed = false;
  var configLoadingPromise = null;

  var selectedProvider = 'gemini';
  var selectedSize = '1K';
  var selectedAspect = '1:1';
  var selectedCount = 1;

  var references = [];
  var isGenerating = false;
  var statusTimer = null;
  var initialized = false;

  function init() {
    if (initialized) return true;

    scrollEl = document.getElementById('images-scroll');
    cardEl = document.getElementById('img-card');
    refsLabelEl = document.getElementById('img-refs-label');
    refsClearBtn = document.getElementById('img-refs-clear');
    refsContainer = document.getElementById('img-refs');
    promptEl = document.getElementById('img-prompt');
    providerRowEl = document.getElementById('img-provider-row');
    providerContainer = document.getElementById('img-provider');
    sizeContainer = document.getElementById('img-size');
    aspectContainer = document.getElementById('img-aspect');
    countContainer = document.getElementById('img-count');
    hintEl = document.getElementById('img-hint');
    statusEl = document.getElementById('img-status');
    generateBtn = document.getElementById('img-generate');
    generateLabelEl = document.getElementById('img-generate-label');
    refInput = document.getElementById('img-ref-input');
    clearHistoryBtn = document.getElementById('img-clear');
    historyContainer = document.getElementById('img-history');

    // Abbrechen, falls der DOM-Abschnitt nicht existiert (z. B. auf Login-Seite)
    if (!scrollEl || !cardEl || !refsContainer || !promptEl || !generateBtn || !historyContainer) {
      return false;
    }

    if (refInput) {
      refInput.addEventListener('change', function () {
        if (refInput.files && refInput.files.length) {
          handleFiles(refInput.files);
          refInput.value = '';
        }
      });
    }

    if (refsClearBtn) {
      refsClearBtn.addEventListener('click', clearReferences);
    }

    if (clearHistoryBtn) {
      clearHistoryBtn.addEventListener('click', onClearAllHistory);
    }

    generateBtn.addEventListener('click', generate);

    // Prompt: Enter mit Cmd/Ctrl startet Generierung
    promptEl.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        generate();
      }
    });

    // Paste von Bilddateien im Prompt abfangen und als Vorlage verwenden
    promptEl.addEventListener('paste', function (e) {
      var cd = e.clipboardData;
      if (!cd || !cd.items) return;
      var imgFiles = [];
      for (var i = 0; i < cd.items.length; i++) {
        var it = cd.items[i];
        if (it.type && it.type.indexOf('image/') === 0) {
          var f = it.getAsFile();
          if (f) imgFiles.push(f);
        }
      }
      if (imgFiles.length > 0) {
        e.preventDefault();
        handleFiles(imgFiles);
      }
    });

    // Drag&Drop auf die Karte: Chat-Handler stoppen und Vorlagen laden
    function hasFileTransfer(e) {
      if (!e.dataTransfer || !e.dataTransfer.types) return false;
      return Array.prototype.indexOf.call(e.dataTransfer.types, 'Files') !== -1;
    }

    cardEl.addEventListener('dragover', function (e) {
      if (hasFileTransfer(e)) {
        e.preventDefault();
        e.stopPropagation();
        cardEl.classList.add('dragover');
      }
    });

    cardEl.addEventListener('dragenter', function (e) {
      if (hasFileTransfer(e)) {
        e.preventDefault();
        e.stopPropagation();
        cardEl.classList.add('dragover');
      }
    });

    cardEl.addEventListener('dragleave', function (e) {
      if (e.target === cardEl || !cardEl.contains(e.relatedTarget)) {
        cardEl.classList.remove('dragover');
      }
    });

    cardEl.addEventListener('drop', function (e) {
      if (hasFileTransfer(e)) {
        e.preventDefault();
        e.stopPropagation();
        cardEl.classList.remove('dragover');
        if (e.dataTransfer.files && e.dataTransfer.files.length) {
          handleFiles(e.dataTransfer.files);
        }
      }
    });

    initialized = true;
    return true;
  }

  function getHistoryKey() {
    // `state` ist eine globale Konstante aus app.js, keine Eigenschaft von window.
    var userId = (typeof state !== 'undefined' && state.me && state.me.id) || 'anon';
    return 'pc.imageHistory.' + userId;
  }

  function loadHistory() {
    try {
      var raw = localStorage.getItem(getHistoryKey());
      if (!raw) return [];
      var parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed : [];
    } catch (_) {
      return [];
    }
  }

  function saveHistory(list) {
    try {
      localStorage.setItem(getHistoryKey(), JSON.stringify(list.slice(0, 50)));
    } catch (_) {}
  }

  function addHistoryEntry(entry) {
    var list = loadHistory();
    list.unshift(entry);
    if (list.length > 50) {
      list.length = 50;
    }
    saveHistory(list);
    renderHistory();
  }

  function getProviderLabel(id, serverLabel) {
    var key = 'images_provider_' + id;
    var translated = t(key);
    return (translated && translated !== key) ? translated : (serverLabel || id);
  }

  function applyConfigDefaults() {
    if (!config) return;
    var defs = config.defaults || {};
    selectedProvider = defs.provider || (config.providers && config.providers[0] && config.providers[0].id) || 'gemini';
    selectedSize = defs.size || (config.image_sizes && config.image_sizes[0] && config.image_sizes[0].id) || '1K';
    selectedAspect = defs.aspect_ratio || (config.aspect_ratios && config.aspect_ratios[0] && config.aspect_ratios[0].id) || '1:1';
    selectedCount = 1;
  }

  function renderOptions() {
    if (!config) return;

    // Anbieter
    if (providerContainer && providerRowEl) {
      providerContainer.innerHTML = '';
      var providers = config.providers || [];
      if (providers.length <= 1) {
        providerRowEl.classList.add('hidden');
      } else {
        providerRowEl.classList.remove('hidden');
        providers.forEach(function (p) {
          var btn = document.createElement('button');
          btn.type = 'button';
          btn.textContent = getProviderLabel(p.id, p.label);
          if (p.id === selectedProvider) btn.classList.add('active');
          btn.addEventListener('click', function () {
            selectedProvider = p.id;
            updateProviderButtons();
            updateUI();
          });
          providerContainer.appendChild(btn);
        });
      }
    }

    // Auflösung
    if (sizeContainer) {
      sizeContainer.innerHTML = '';
      (config.image_sizes || []).forEach(function (s) {
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'chip' + (s.id === selectedSize ? ' active' : '');
        btn.title = s.label || s.id;
        btn.textContent = s.id;
        btn.addEventListener('click', function () {
          selectedSize = s.id;
          updateSizeButtons();
        });
        sizeContainer.appendChild(btn);
      });
    }

    // Format
    if (aspectContainer) {
      aspectContainer.innerHTML = '';
      (config.aspect_ratios || []).forEach(function (a) {
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'chip' + (a.id === selectedAspect ? ' active' : '');
        btn.title = a.label || a.id;
        btn.textContent = a.id;
        btn.addEventListener('click', function () {
          selectedAspect = a.id;
          updateAspectButtons();
        });
        aspectContainer.appendChild(btn);
      });
    }

    // Varianten
    if (countContainer) {
      countContainer.innerHTML = '';
      var maxCandidates = Math.min(Math.max(1, config.max_candidates || 1), 4);
      for (var i = 1; i <= maxCandidates; i++) {
        (function (cnt) {
          var btn = document.createElement('button');
          btn.type = 'button';
          btn.className = 'chip' + (cnt === selectedCount ? ' active' : '');
          btn.textContent = String(cnt);
          btn.addEventListener('click', function () {
            selectedCount = cnt;
            updateCountButtons();
          });
          countContainer.appendChild(btn);
        })(i);
      }
    }
  }

  function updateProviderButtons() {
    if (!providerContainer || !config) return;
    var btns = providerContainer.querySelectorAll('button');
    (config.providers || []).forEach(function (p, idx) {
      if (btns[idx]) {
        btns[idx].classList.toggle('active', p.id === selectedProvider);
      }
    });
  }

  function updateSizeButtons() {
    if (!sizeContainer || !config) return;
    var btns = sizeContainer.querySelectorAll('button');
    (config.image_sizes || []).forEach(function (s, idx) {
      if (btns[idx]) {
        btns[idx].classList.toggle('active', s.id === selectedSize);
      }
    });
  }

  function updateAspectButtons() {
    if (!aspectContainer || !config) return;
    var btns = aspectContainer.querySelectorAll('button');
    (config.aspect_ratios || []).forEach(function (a, idx) {
      if (btns[idx]) {
        btns[idx].classList.toggle('active', a.id === selectedAspect);
      }
    });
  }

  function updateCountButtons() {
    if (!countContainer) return;
    var btns = countContainer.querySelectorAll('button');
    btns.forEach(function (btn, idx) {
      btn.classList.toggle('active', (idx + 1) === selectedCount);
    });
  }

  function updateUI() {
    var hasRefs = references.length > 0;

    if (refsLabelEl) {
      refsLabelEl.textContent = t(hasRefs ? 'image_reference_label_active' : 'image_reference_label');
    }
    if (promptEl) {
      promptEl.placeholder = t(hasRefs ? 'image_edit_prompt_placeholder' : 'image_prompt_placeholder');
    }
    if (generateLabelEl) {
      generateLabelEl.textContent = t(hasRefs ? 'image_edit_button' : 'image_generate_button');
    }
    if (refsClearBtn) {
      refsClearBtn.classList.toggle('hidden', !hasRefs);
    }

    if (hintEl) {
      if (config && config.configured === false) {
        hintEl.textContent = t('images_not_configured');
      } else if (hasRefs) {
        hintEl.textContent = t('image_reference_hint_active');
      } else if (selectedProvider === 'gemini') {
        hintEl.textContent = t('images_hint_gemini');
      } else if (selectedProvider === 'gpt') {
        hintEl.textContent = t('images_hint_gpt');
      } else if (selectedProvider === 'both') {
        hintEl.textContent = t('images_hint_both');
      } else {
        hintEl.textContent = '';
      }
    }

    if (generateBtn) {
      if (isGenerating || configLoadFailed) {
        generateBtn.disabled = true;
      } else if (config && config.configured === false) {
        generateBtn.disabled = true;
      } else {
        generateBtn.disabled = false;
      }
    }
  }

  // Bei jedem Oeffnen neu laden: ein Gateway kann inzwischen wieder laufen,
  // und geaenderte Vorgaben aus den Einstellungen sollen ankommen. Die
  // aktuelle Auswahl bleibt, solange es sie noch gibt.
  var defaultsDirty = true;
  function keepOr(value, items, fallback) {
    return (items || []).some(function (x) { return x.id === value; }) ? value : fallback;
  }
  function loadConfig() {
    if (configLoadingPromise) return configLoadingPromise;

    configLoadingPromise = api('GET', '/images/config')
      .then(function (res) {
        var first = !config || defaultsDirty;
        config = res;
        configLoadFailed = false;
        if (first) {
          applyConfigDefaults();
          defaultsDirty = false;
        } else {
          var defs = config.defaults || {};
          selectedProvider = keepOr(selectedProvider, config.providers, defs.provider || selectedProvider);
          selectedSize = keepOr(selectedSize, config.image_sizes, defs.size || selectedSize);
          selectedAspect = keepOr(selectedAspect, config.aspect_ratios, defs.aspect_ratio || selectedAspect);
          selectedCount = Math.min(selectedCount, Math.max(1, Math.min(config.max_candidates || 1, 4)));
        }
        if (statusEl && statusEl.classList.contains('error') && !isGenerating) {
          statusEl.className = 'img-status';
          statusEl.textContent = '';
        }
        renderOptions();
        updateUI();
        return config;
      })
      .catch(function (err) {
        configLoadFailed = true;
        if (statusEl) {
          statusEl.className = 'img-status error';
          statusEl.textContent = t('image_config_load_failed');
        }
        updateUI();
        throw err;
      })
      .finally(function () {
        configLoadingPromise = null;
      });

    return configLoadingPromise;
  }

  function clearStatusTimer() {
    if (statusTimer) {
      clearInterval(statusTimer);
      statusTimer = null;
    }
  }

  function startGeneratingStatus() {
    clearStatusTimer();
    isGenerating = true;
    updateUI();
    if (!statusEl) return;
    statusEl.className = 'img-status busy';
    var startTime = Date.now();
    var label = t('image_generating');

    function tick() {
      var elapsed = Math.floor((Date.now() - startTime) / 1000);
      statusEl.innerHTML = '<span class="spinner"></span> ' + escapeHtml(label) + ' &middot; ' + elapsed + ' s';
    }
    tick();
    statusTimer = setInterval(tick, 1000);
  }

  function stopGeneratingStatus(successText, errorText) {
    clearStatusTimer();
    isGenerating = false;
    if (statusEl) {
      if (errorText) {
        statusEl.className = 'img-status error';
        statusEl.textContent = errorText;
      } else if (successText) {
        statusEl.className = 'img-status ok';
        statusEl.textContent = successText;
      } else {
        statusEl.className = 'img-status';
        statusEl.textContent = '';
      }
    }
    updateUI();
  }

  function renderReferences() {
    if (!refsContainer) return;
    refsContainer.innerHTML = '';

    references.forEach(function (item, index) {
      var tile = document.createElement('div');
      tile.className = 'ref-tile';

      var img = document.createElement('img');
      img.src = item.url;
      img.alt = item.filename || '';
      tile.appendChild(img);

      if (item.status === 'uploading') {
        var pend = document.createElement('div');
        pend.className = 'pend-overlay';
        pend.innerHTML = '<div class="spinner"></div>';
        tile.appendChild(pend);
      } else if (item.status === 'error') {
        var errOverlay = document.createElement('div');
        errOverlay.className = 'pend-overlay error';
        errOverlay.innerHTML = '<svg class="icon"><use href="#icon-error"/></svg>';
        tile.appendChild(errOverlay);
      }

      var removeBtn = document.createElement('button');
      removeBtn.className = 'pend-remove';
      removeBtn.type = 'button';
      removeBtn.title = t('image_reference_remove');
      removeBtn.innerHTML = '<svg class="icon"><use href="#icon-close"/></svg>';
      removeBtn.addEventListener('click', function (e) {
        e.stopPropagation();
        removeReference(index);
      });
      tile.appendChild(removeBtn);

      refsContainer.appendChild(tile);
    });

    if (references.length < MAX_REFS) {
      var addBtn = document.createElement('button');
      addBtn.className = 'ref-add';
      addBtn.type = 'button';
      addBtn.innerHTML = '<svg class="icon"><use href="#icon-add-photo"/></svg><span>' + escapeHtml(t('image_reference_add')) + '</span>';
      addBtn.addEventListener('click', function () {
        if (refInput) {
          refInput.value = '';
          refInput.click();
        }
      });
      refsContainer.appendChild(addBtn);
    }
  }

  function removeReference(index) {
    var item = references[index];
    if (!item) return;
    item.cancelled = true;
    if (item.isBlobUrl) {
      try { URL.revokeObjectURL(item.url); } catch (_) {}
    }
    references.splice(index, 1);
    renderReferences();
    updateUI();
  }

  function clearReferences() {
    references.forEach(function (item) {
      item.cancelled = true;
      if (item.isBlobUrl) {
        try { URL.revokeObjectURL(item.url); } catch (_) {}
      }
    });
    references = [];
    renderReferences();
    updateUI();
  }

  function handleFiles(fileList) {
    if (!fileList || !fileList.length) return;

    var validFiles = [];
    var unsupported = false;

    for (var i = 0; i < fileList.length; i++) {
      var f = fileList[i];
      if (ALLOWED_MIME.indexOf(f.type) !== -1) {
        validFiles.push(f);
      } else {
        unsupported = true;
      }
    }

    if (unsupported) {
      toast(t('images_ref_unsupported'), { error: true });
    }

    if (validFiles.length === 0) return;

    var slots = MAX_REFS - references.length;
    if (slots <= 0) {
      toast(t('images_ref_limit', MAX_REFS));
      return;
    }

    if (validFiles.length > slots) {
      toast(t('images_ref_limit', MAX_REFS));
    }

    var toAdd = validFiles.slice(0, slots);
    toAdd.forEach(uploadReferenceFile);
  }

  function uploadReferenceFile(file) {
    var blobUrl = URL.createObjectURL(file);
    var item = {
      id: null,
      url: blobUrl,
      isBlobUrl: true,
      filename: file.name,
      mime_type: file.type,
      status: 'uploading',
      error: null,
      cancelled: false
    };

    references.push(item);
    renderReferences();
    updateUI();

    compressImage(file, 'edit')
      .then(function (compressed) {
        if (item.cancelled) return null;
        return uploadFile(compressed.blob, compressed.filename || file.name);
      })
      .then(function (uploaded) {
        if (!uploaded || item.cancelled) return;
        item.id = uploaded.id;
        item.filename = uploaded.filename;
        item.mime_type = uploaded.mime_type;
        item.status = 'ready';
      })
      .catch(function (err) {
        if (item.cancelled) return;
        var errText = apiErrorText(err);
        item.status = 'error';
        item.error = errText;
        toast(errText, { error: true });
      })
      .finally(function () {
        if (!item.cancelled) {
          renderReferences();
          updateUI();
        }
      });
  }

  function generate() {
    if (isGenerating) return;
    var prompt = (promptEl && promptEl.value ? promptEl.value : '').trim();
    if (!prompt) {
      if (promptEl) promptEl.focus();
      return;
    }

    // Nicht starten, solange Uploads aktiv sind
    var isUploading = references.some(function (r) { return r.status === 'uploading'; });
    if (isUploading) {
      toast(t('chat_wait_for_uploads'));
      return;
    }
    // Eine gescheiterte Vorlage darf nicht still zu einem Bild ohne Vorlage werden.
    if (references.some(function (r) { return r.status === 'error'; })) {
      toast(t('images_ref_failed'), { error: true });
      return;
    }

    var refIds = references
      .filter(function (r) { return r.status === 'ready' && r.id; })
      .map(function (r) { return r.id; });

    startGeneratingStatus();

    var payload = {
      prompt: prompt,
      provider: selectedProvider,
      aspect_ratio: selectedAspect,
      image_size: selectedSize,
      count: selectedCount,
      reference_attachment_ids: refIds
    };

    api('POST', '/images/generate', payload)
      .then(function (res) {
        var attachments = (res && res.attachments) || [];
        // Werte aus dem Auftrag, nicht die aktuelle Auswahl: die Knoepfe
        // bleiben waehrend des Zeichnens bedienbar.
        var entry = {
          id: 'img_' + Date.now() + '_' + Math.random().toString(36).slice(2, 8),
          created: new Date().toISOString(),
          prompt: prompt,
          provider: payload.provider,
          size: payload.image_size,
          aspect: payload.aspect_ratio,
          refs: refIds.length,
          images: attachments.map(function (a) {
            return {
              id: a.id,
              filename: a.filename,
              mime_type: a.mime_type
            };
          })
        };
        addHistoryEntry(entry);
        stopGeneratingStatus(t('images_done', attachments.length), null);
      })
      .catch(function (err) {
        var errText = apiErrorText(err);
        stopGeneratingStatus(null, errText);
        toast(errText, { error: true });
      });
  }

  function renderHistory() {
    if (!historyContainer) return;
    var history = loadHistory();

    if (clearHistoryBtn) {
      clearHistoryBtn.classList.toggle('hidden', history.length === 0);
    }

    historyContainer.innerHTML = '';
    if (history.length === 0) {
      var emptyEl = document.createElement('div');
      emptyEl.className = 'img-empty';
      // Illustration wie in der App (Entscheidung 22.10.2026), Text bleibt.
      var emptyArt = document.createElement('img');
      emptyArt.className = 'img-empty-art';
      emptyArt.src = 'images-empty.webp?v=20261022d';
      emptyArt.alt = '';
      var emptyText = document.createElement('p');
      emptyText.textContent = t('image_history_empty_web');
      emptyEl.append(emptyArt, emptyText);
      historyContainer.appendChild(emptyEl);
      return;
    }

    history.forEach(function (entry) {
      var article = document.createElement('article');
      article.className = 'img-entry';

      var imgsWrap = document.createElement('div');
      var imgCount = (entry.images && entry.images.length) || 0;
      imgsWrap.className = 'img-entry-images' + (imgCount === 1 ? ' n1' : '');

      (entry.images || []).forEach(function (img) {
        var fig = document.createElement('figure');

        var imageEl = document.createElement('img');
        var url = attachmentUrl(img.id);
        imageEl.src = url;
        imageEl.alt = img.filename || '';
        imageEl.loading = 'lazy';
        imageEl.addEventListener('click', function () {
          openLightbox(url, {
            filename: img.filename,
            onUseAsReference: function () { addReference(img); }
          });
        });
        fig.appendChild(imageEl);

        // Anbieter-Kennzeichnung nur bei Generierung mit beiden Anbietern
        if (entry.provider === 'both') {
          var fn = (img.filename || '').toLowerCase();
          var tagLabel = '';
          if (fn.indexOf('gemini') === 0) tagLabel = 'Gemini';
          else if (fn.indexOf('gpt') === 0) tagLabel = 'GPT';
          if (tagLabel) {
            var tagSpan = document.createElement('span');
            tagSpan.className = 'img-provider-tag';
            tagSpan.textContent = tagLabel;
            fig.appendChild(tagSpan);
          }
        }

        var actions = document.createElement('div');
        actions.className = 'img-actions';

        var brushBtn = document.createElement('button');
        brushBtn.type = 'button';
        brushBtn.title = t('image_use_as_reference');
        brushBtn.innerHTML = '<svg class="icon"><use href="#icon-brush"/></svg>';
        brushBtn.addEventListener('click', function (e) {
          e.stopPropagation();
          addReference(img);
        });
        actions.appendChild(brushBtn);

        var dlLink = document.createElement('a');
        dlLink.href = url;
        dlLink.download = img.filename || 'image.png';
        dlLink.title = t('img_action_download');
        dlLink.innerHTML = '<svg class="icon"><use href="#icon-download"/></svg>';
        dlLink.addEventListener('click', function (e) {
          e.stopPropagation();
        });
        actions.appendChild(dlLink);

        fig.appendChild(actions);
        imgsWrap.appendChild(fig);
      });

      article.appendChild(imgsWrap);

      var body = document.createElement('div');
      body.className = 'img-entry-body';

      var promptDiv = document.createElement('div');
      promptDiv.className = 'img-entry-prompt';
      promptDiv.textContent = entry.prompt || '';
      body.appendChild(promptDiv);

      var foot = document.createElement('div');
      foot.className = 'img-entry-foot';

      var metaSpan = document.createElement('span');
      metaSpan.className = 'img-entry-meta';
      metaSpan.textContent = t('image_meta_line', entry.size || '', entry.aspect || '', imgCount);
      foot.appendChild(metaSpan);

      var delBtn = document.createElement('button');
      delBtn.className = 'icon-btn';
      delBtn.type = 'button';
      delBtn.title = t('image_remove_entry');
      delBtn.innerHTML = '<svg class="icon"><use href="#icon-trash"/></svg>';
      delBtn.addEventListener('click', function () {
        showConfirm({
          title: t('image_delete_generation_title'),
          text: t('image_delete_generation_body'),
          okLabel: t('delete'),
          danger: true
        }).then(function (ok) {
          if (ok) {
            var remaining = loadHistory().filter(function (e) { return e.id !== entry.id; });
            saveHistory(remaining);
            renderHistory();
          }
        });
      });
      foot.appendChild(delBtn);

      body.appendChild(foot);
      article.appendChild(body);
      historyContainer.appendChild(article);
    });
  }

  function onClearAllHistory() {
    showConfirm({
      title: t('image_clear_all_title'),
      text: t('image_clear_all_body'),
      okLabel: t('image_clear_all_confirm'),
      danger: true
    }).then(function (ok) {
      if (ok) {
        saveHistory([]);
        renderHistory();
      }
    });
  }

  function addReference(att) {
    if (!init()) return;
    if (!att || !att.id) return;

    if (references.length >= MAX_REFS) {
      toast(t('images_ref_limit', MAX_REFS));
      return;
    }

    references.push({
      id: att.id,
      url: attachmentUrl(att.id),
      isBlobUrl: false,
      filename: att.filename || '',
      mime_type: att.mime_type || '',
      status: 'ready',
      error: null,
      cancelled: false
    });

    renderReferences();
    updateUI();

    if (scrollEl) scrollEl.scrollTop = 0;
    if (promptEl) promptEl.focus();
  }

  function show() {
    if (!init()) return;
    renderHistory();
    renderReferences();
    loadConfig().catch(function () {});
    if (promptEl) {
      promptEl.focus();
    }
  }

  function hide() {
    if (cardEl) {
      cardEl.classList.remove('dragover');
    }
  }

  // Sofortige DOM-Bindung versuchen
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // Nach einem Sprachwechsel setzt applyI18n die Beschriftungen auf ihren
  // Grundzustand zurueck; den aktuellen Stand (mit/ohne Vorlagen) neu setzen.
  document.addEventListener('pc:locale-changed', function () {
    if (!initialized) return;
    renderOptions();
    renderReferences();
    updateUI();
    renderHistory();
  });

  window.PocketImages = {
    show: show,
    hide: hide,
    addReference: addReference,
    // Nach geaenderten Vorgaben in den Einstellungen beim naechsten Oeffnen uebernehmen.
    invalidate: function () { defaultsDirty = true; }
  };
})();
