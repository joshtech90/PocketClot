package de.smartzone.pocketclaude.ui.settings

import android.content.Context
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import de.smartzone.pocketclaude.R
import de.smartzone.pocketclaude.data.AppContainer
import de.smartzone.pocketclaude.data.AppSettings
import de.smartzone.pocketclaude.data.ApiException
import de.smartzone.pocketclaude.data.AudioController
import de.smartzone.pocketclaude.data.BillingStatusDto
import de.smartzone.pocketclaude.data.ChatModelFamilies
import de.smartzone.pocketclaude.data.ChatRepository
import de.smartzone.pocketclaude.data.ClaudeAuthDto
import de.smartzone.pocketclaude.data.ClaudeAuthUpdateRequest
import de.smartzone.pocketclaude.data.GemDto
import de.smartzone.pocketclaude.data.UsageStatsDto
import de.smartzone.pocketclaude.data.MeDto
import de.smartzone.pocketclaude.data.SettingsRepository
import de.smartzone.pocketclaude.data.SkillsDto
import de.smartzone.pocketclaude.data.SystemPromptMode
import de.smartzone.pocketclaude.data.TtsApiKeyEntryDto
import de.smartzone.pocketclaude.data.ThemeMode
import de.smartzone.pocketclaude.data.TtsStatusDto
import de.smartzone.pocketclaude.data.TtsVoiceDto
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch

sealed interface ConnectionTestResult {
    data object Idle : ConnectionTestResult
    data object Testing : ConnectionTestResult
    data class Success(val model: String, val version: String) : ConnectionTestResult
    data class Failure(val reason: String) : ConnectionTestResult
}

/** Status der Login/Profil-Anlage. UI rendert Spinner/Fehler/Erfolg dazu. */
sealed interface LoginUiState {
    data object Idle : LoginUiState
    data object Working : LoginUiState
    /** Login OK; wenn [mustChangePassword] true, soll die UI sofort den
     *  PW-Change-Dialog öffnen. Profil ist bereits aktiv. */
    data class Success(val user: MeDto, val mustChangePassword: Boolean) : LoginUiState
    data class Failure(val reason: String) : LoginUiState
}

sealed interface TtsTestResult {
    data object Idle : TtsTestResult
    data object Testing : TtsTestResult
    data class Failure(val reason: String) : TtsTestResult
}

class SettingsViewModel(
    private val settingsRepo: SettingsRepository,
    private val chatRepo: ChatRepository,
    private val audio: AudioController,
    private val appContext: Context,
) : ViewModel() {

    val settings: StateFlow<AppSettings> = MutableStateFlow(AppSettings()).also { flow ->
        viewModelScope.launch {
            settingsRepo.settingsFlow.collect { flow.value = it }
        }
    }.asStateFlow()

    private val _testResult = MutableStateFlow<ConnectionTestResult>(ConnectionTestResult.Idle)
    val testResult: StateFlow<ConnectionTestResult> = _testResult.asStateFlow()

    private val _ttsStatus = MutableStateFlow<TtsStatusDto?>(null)
    val ttsStatus: StateFlow<TtsStatusDto?> = _ttsStatus.asStateFlow()

    private val _ttsBusy = MutableStateFlow(false)
    val ttsBusy: StateFlow<Boolean> = _ttsBusy.asStateFlow()

    private val _ttsError = MutableStateFlow<String?>(null)
    val ttsError: StateFlow<String?> = _ttsError.asStateFlow()

    private val _ttsTest = MutableStateFlow<TtsTestResult>(TtsTestResult.Idle)
    val ttsTest: StateFlow<TtsTestResult> = _ttsTest.asStateFlow()

    // Cloud-Billing-Status (Spend, Budget, Credit). null = noch nicht geladen.
    private val _billingStatus = MutableStateFlow<BillingStatusDto?>(null)
    val billingStatus: StateFlow<BillingStatusDto?> = _billingStatus.asStateFlow()
    private val _billingBusy = MutableStateFlow(false)
    val billingBusy: StateFlow<Boolean> = _billingBusy.asStateFlow()

    fun refreshBillingStatus() = viewModelScope.launch {
        if (!settings.value.isConfigured) return@launch
        _billingBusy.value = true
        runCatching { chatRepo.billingStatus() }
            .onSuccess { _billingStatus.value = it }
            .onFailure {
                // Bei Fehler: einen „nicht verfügbar"-Stub erzeugen damit das
                // UI zumindest weiß dass kein Status da ist.
                _billingStatus.value = BillingStatusDto(
                    available = false,
                    error = it.message ?: "Status nicht ladbar",
                )
            }
        _billingBusy.value = false
    }

    // Claude auth-mode (Pro/Max | API key | Bedrock)
    private val _claudeAuth = MutableStateFlow<ClaudeAuthDto?>(null)
    val claudeAuth: StateFlow<ClaudeAuthDto?> = _claudeAuth.asStateFlow()
    private val _claudeAuthBusy = MutableStateFlow(false)
    val claudeAuthBusy: StateFlow<Boolean> = _claudeAuthBusy.asStateFlow()

    fun refreshClaudeAuth() = viewModelScope.launch {
        if (!settings.value.isConfigured) return@launch
        runCatching { chatRepo.getClaudeAuth() }
            .onSuccess { _claudeAuth.value = it }
    }

    fun updateClaudeAuth(req: ClaudeAuthUpdateRequest) = viewModelScope.launch {
        _claudeAuthBusy.value = true
        runCatching { chatRepo.updateClaudeAuth(req) }
            .onSuccess { _claudeAuth.value = it }
        _claudeAuthBusy.value = false
    }

    // Chat-Sperre (globaler PIN). null = noch nicht geladen.
    private val _chatLockIsSet = MutableStateFlow<Boolean?>(null)
    val chatLockIsSet: StateFlow<Boolean?> = _chatLockIsSet.asStateFlow()
    private val _chatLockBusy = MutableStateFlow(false)
    val chatLockBusy: StateFlow<Boolean> = _chatLockBusy.asStateFlow()

    fun refreshChatLock() = viewModelScope.launch {
        if (!settings.value.isConfigured) return@launch
        runCatching { chatRepo.getChatLock() }
            .onSuccess { _chatLockIsSet.value = it.isSet }
    }

    /** Setzt/ändert den PIN. `currentPin` nur nötig wenn schon einer existiert.
     *  onResult(null) = ok, sonst Fehlermeldung (z.B. „aktueller PIN falsch"). */
    fun setChatLockPin(newPin: String, currentPin: String?, onResult: (String?) -> Unit) =
        viewModelScope.launch {
            _chatLockBusy.value = true
            val res = runCatching { chatRepo.setChatLockPin(newPin, currentPin) }
            _chatLockBusy.value = false
            res.onSuccess { _chatLockIsSet.value = it.isSet; onResult(null) }
            res.onFailure { e ->
                val code = (e as? de.smartzone.pocketclaude.data.ApiException)?.code
                onResult(if (code == 401) "wrong" else (e.message ?: "error"))
            }
        }

    fun removeChatLockPin(currentPin: String, onResult: (String?) -> Unit) =
        viewModelScope.launch {
            _chatLockBusy.value = true
            val res = runCatching { chatRepo.clearChatLockPin(currentPin) }
            _chatLockBusy.value = false
            res.onSuccess { _chatLockIsSet.value = it.isSet; onResult(null) }
            res.onFailure { e ->
                val code = (e as? de.smartzone.pocketclaude.data.ApiException)?.code
                onResult(if (code == 401) "wrong" else (e.message ?: "error"))
            }
        }

    fun setChatLockBiometric(enabled: Boolean) = viewModelScope.launch {
        settingsRepo.setChatLockBiometricEnabled(enabled)
    }

    // Usage stats
    private val _usage = MutableStateFlow<UsageStatsDto?>(null)
    val usage: StateFlow<UsageStatsDto?> = _usage.asStateFlow()

    fun refreshUsage() = viewModelScope.launch {
        if (!settings.value.isConfigured) return@launch
        runCatching { chatRepo.getUsageStats("month") }
            .onSuccess { _usage.value = it }
    }

    // Gems (Custom Agents) — Liste für die Settings-Sektion.
    private val _gems = MutableStateFlow<List<GemDto>>(emptyList())
    val gems: StateFlow<List<GemDto>> = _gems.asStateFlow()

    fun refreshGems() = viewModelScope.launch {
        if (!settings.value.isConfigured) return@launch
        runCatching { chatRepo.listGems() }.onSuccess { _gems.value = it }
    }

    fun deleteGem(id: String) = viewModelScope.launch {
        runCatching { chatRepo.deleteGem(id) }
        refreshGems()
    }

    init {
        // Auf DataStore warten — beim Screen-Open ist settings.value erst noch der
        // Default (leerer URL/Token), DataStore-Emission kommt asynchron.
        viewModelScope.launch {
            settings.first { it.isConfigured }
            refreshTtsStatus()
            refreshImageConfig()
            refreshVoiceConfig()
            refreshDefaultSkills()
            refreshTtsKeyPool()
            refreshBillingStatus()
            refreshClaudeAuth()
            refreshChatModels(force = false)
            refreshUsage()
            refreshGems()
            refreshChatLock()
        }
    }

    // ---------- Skills (User-Default — gilt für alle neuen Chats) ----------

    private val _defaultSkills = MutableStateFlow<SkillsDto?>(null)
    val defaultSkills: StateFlow<SkillsDto?> = _defaultSkills.asStateFlow()

    private val _skillsBusy = MutableStateFlow(false)
    val skillsBusy: StateFlow<Boolean> = _skillsBusy.asStateFlow()

    fun refreshDefaultSkills() = viewModelScope.launch {
        if (!settings.value.isConfigured) return@launch
        runCatching { chatRepo.getDefaultSkills() }
            .onSuccess { _defaultSkills.value = it }
    }

    fun setDefaultSkills(skills: SkillsDto) = viewModelScope.launch {
        _skillsBusy.value = true
        runCatching { chatRepo.setDefaultSkills(skills) }
            .onSuccess { _defaultSkills.value = it }
        _skillsBusy.value = false
    }

    fun setServerUrl(value: String) = viewModelScope.launch {
        settingsRepo.setServerUrl(value)
        _testResult.value = ConnectionTestResult.Idle
    }

    fun setServerToken(value: String) = viewModelScope.launch {
        settingsRepo.setServerToken(value)
        _testResult.value = ConnectionTestResult.Idle
    }

    // ----- Profile-Management (Multi-User) -----

    private val _login = MutableStateFlow<LoginUiState>(LoginUiState.Idle)
    val loginState: StateFlow<LoginUiState> = _login.asStateFlow()

    fun clearLoginState() { _login.value = LoginUiState.Idle }

    /**
     * Login + neues Profil anlegen + aktivieren. Bei Erfolg landet ein neues
     * Profil mit dem vom Server zurückgegebenen Session-Token in den Settings,
     * und der `LoginUiState` signalisiert dem UI, ob ein Forced-PW-Change ansteht.
     */
    fun addProfileAndLogin(label: String, url: String, username: String, password: String) =
        viewModelScope.launch {
            if (url.isBlank() || username.isBlank() || password.isBlank()) {
                _login.value = LoginUiState.Failure("URL, Benutzername und Passwort sind erforderlich.")
                return@launch
            }
            _login.value = LoginUiState.Working
            try {
                val resp = chatRepo.login(url, username, password)
                // Profil mit Session-Token speichern und aktivieren
                settingsRepo.upsertProfile(
                    label = label.ifBlank { username },
                    url = url,
                    token = resp.token,
                    username = username,
                    makeActive = true,
                )
                _testResult.value = ConnectionTestResult.Idle
                _login.value = LoginUiState.Success(resp.user, resp.user.mustChangePassword)
            } catch (e: Exception) {
                _login.value = LoginUiState.Failure(loginErrorMessage(e))
            }
        }

    /**
     * Re-Login fürs aktive Profil — z.B. nach Session-Ablauf oder PW-Reset
     * durch den Admin. URL + Username bleiben gleich, nur das Token wird ersetzt.
     */
    fun relogActiveProfile(password: String) = viewModelScope.launch {
        val s = settingsRepo.current()
        val active = s.activeProfile
            ?: run {
                _login.value = LoginUiState.Failure("Kein Profil aktiv.")
                return@launch
            }
        if (active.username.isBlank()) {
            _login.value = LoginUiState.Failure("Profil hat keinen Username — neu anlegen.")
            return@launch
        }
        _login.value = LoginUiState.Working
        try {
            val resp = chatRepo.login(active.serverUrl, active.username, password)
            settingsRepo.setActiveSessionToken(resp.token)
            _login.value = LoginUiState.Success(resp.user, resp.user.mustChangePassword)
        } catch (e: Exception) {
            _login.value = LoginUiState.Failure(loginErrorMessage(e))
        }
    }

    private fun loginErrorMessage(e: Exception): String = when (e) {
        is ApiException -> when (e.code) {
            401 -> "Benutzername oder Passwort falsch."
            400 -> "Bitte Username + Passwort eintragen."
            else -> "HTTP ${e.code}: ${e.body.take(120)}"
        }
        else -> e.message ?: e::class.java.simpleName
    }

    /** Aktuelles Passwort ändern. `oldPassword=null` bei Forced-Change. */
    fun changePassword(oldPassword: String?, newPassword: String, onResult: (Result<Unit>) -> Unit = {}) =
        viewModelScope.launch {
            val outcome = runCatching { chatRepo.changePassword(oldPassword, newPassword) }
            onResult(outcome.map { })
        }

    /** Logout des aktiven Profils. Server-Session beenden + Token im Profil löschen. */
    fun logoutActiveProfile() = viewModelScope.launch {
        runCatching { chatRepo.logout() }
        settingsRepo.setActiveSessionToken("")
    }

    fun activateProfile(id: String) = viewModelScope.launch {
        settingsRepo.setActiveProfile(id)
        _testResult.value = ConnectionTestResult.Idle
    }

    fun renameProfile(id: String, newLabel: String) = viewModelScope.launch {
        settingsRepo.updateProfile(id, label = newLabel)
    }

    fun deleteProfile(id: String) = viewModelScope.launch {
        settingsRepo.deleteProfile(id)
        _testResult.value = ConnectionTestResult.Idle
    }

    fun setThemeMode(mode: ThemeMode) = viewModelScope.launch {
        settingsRepo.setThemeMode(mode)
    }

    // ----- Chat-Modelle (Claude plus Zusatz-Modelle) -----

    private val _chatModels =
        MutableStateFlow<List<de.smartzone.pocketclaude.data.ChatModelOption>>(emptyList())
    val chatModels: StateFlow<List<de.smartzone.pocketclaude.data.ChatModelOption>> =
        _chatModels.asStateFlow()

    private val _chatModelsLoading = MutableStateFlow(false)
    val chatModelsLoading: StateFlow<Boolean> = _chatModelsLoading.asStateFlow()

    /** Holt die Modell-Liste vom Server. Schlaegt das fehl, bleibt die Liste
     *  leer und der Picker zeigt nur „Automatisch"; Claude funktioniert
     *  trotzdem, weil der Server dann seinen eigenen Default nimmt. */
    fun refreshChatModels(force: Boolean = true) = viewModelScope.launch {
        if (!settings.value.isConfigured) return@launch
        _chatModelsLoading.value = true
        runCatching { chatRepo.getChatModels(force) }
            .onSuccess { dto ->
                _chatModels.value = dto.models.map { m ->
                    de.smartzone.pocketclaude.data.ChatModelOption(
                        key = m.key,
                        family = m.family,
                        label = m.label,
                        efforts = m.efforts,
                        defaultEffort = m.defaultEffort,
                        supportsVision = m.supportsVision,
                        gatewayLabel = m.gatewayLabel,
                    )
                }
            }
        _chatModelsLoading.value = false
    }

    /** Setzt das globale Standard-Modell. Wandert in die App-Einstellungen
     *  (die App schickt es pro Nachricht mit) UND in den Server-KV, damit die
     *  Web-UI dieselbe Vorauswahl sieht. */
    fun setDefaultChatModel(key: String) = viewModelScope.launch {
        settingsRepo.setChatModelKey(key)
        runCatching { chatRepo.updateClaudeAuth(ClaudeAuthUpdateRequest(defaultModel = key)) }
    }

    /** Denktiefe je Modell-Familie. Claude schreibt zusaetzlich das alte
     *  `effort`-Feld, damit bestehende Aufrufer unveraendert weiterlaufen. */
    fun setEffortForFamily(family: String, value: String) = viewModelScope.launch {
        settingsRepo.setEffortForFamily(family, value)
    }

    /**
     * Standardmodell je Anbieter. Fuer Claude wandert der Wert zusaetzlich in
     * den Server-KV: das ist derselbe Schluessel, aus dem sich die Web-UI und
     * die serverseitige Modellkette bedienen. Fuer Gemini und GPT gibt es
     * serverseitig keinen Default-Begriff, die bleiben App-lokal.
     */
    fun setDefaultModelForFamily(family: String, key: String) = viewModelScope.launch {
        settingsRepo.setDefaultModelForFamily(family, key)
        if (family == ChatModelFamilies.CLAUDE) {
            runCatching { chatRepo.updateClaudeAuth(ClaudeAuthUpdateRequest(defaultModel = key)) }
        }
    }

    /** Farbschema der App. Rein lokal, betrifft nur die Darstellung. */
    fun setPaletteIdLight(value: String) = viewModelScope.launch {
        settingsRepo.setPaletteIdLight(value)
    }

    fun setPaletteIdDark(value: String) = viewModelScope.launch {
        settingsRepo.setPaletteIdDark(value)
    }

    /** Standardwerte fuer erzeugte Bilder. Gelten fuer den Bilder-Screen UND
     *  fuer das Bild-Werkzeug im Chat, deshalb landen sie auf dem Server. */
    fun setImageDefaults(size: String? = null, aspectRatio: String? = null,
                         model: String? = null,
                         provider: String? = null) = viewModelScope.launch {
        runCatching { chatRepo.setImageDefaults(size, aspectRatio, model, provider) }
            .onSuccess { _imageConfig.value = it }
        if (size != null) settingsRepo.setImageDefaultSize(size)
        if (aspectRatio != null) settingsRepo.setImageDefaultAspect(aspectRatio)
    }

    fun setEffort(value: String) = viewModelScope.launch {
        settingsRepo.setEffort(value)
    }

    fun setSystemPromptMode(mode: SystemPromptMode) = viewModelScope.launch {
        settingsRepo.setSystemPromptMode(mode)
    }

    fun setCustomSystemPrompt(value: String) = viewModelScope.launch {
        settingsRepo.setCustomSystemPrompt(value)
    }

    fun setCollapseLongUserMessages(value: Boolean) = viewModelScope.launch {
        settingsRepo.setCollapseLongUserMessages(value)
    }

    fun testConnection() = viewModelScope.launch {
        _testResult.value = ConnectionTestResult.Testing
        _testResult.value = runCatching { chatRepo.health() }
            .map { ConnectionTestResult.Success(it.model ?: "Claude", it.version) as ConnectionTestResult }
            .getOrElse { e ->
                val msg = when (e) {
                    is ApiException -> "HTTP ${e.code}"
                    else -> e.message ?: e::class.java.simpleName
                }
                ConnectionTestResult.Failure(msg)
            }
    }

    // ---------- TTS ----------

    fun refreshTtsStatus() = viewModelScope.launch {
        if (!settings.value.isConfigured) return@launch
        runCatching { chatRepo.ttsStatus() }
            .onSuccess { status ->
                _ttsStatus.value = status
                // Der Anbieter kann sich auch ohne Zutun der App geaendert
                // haben — etwa durch die einmalige Umstellung auf den
                // Vorlese-Dienst beim Serverstart. Dann passt die hier
                // gemerkte Stimme womoeglich nicht mehr dazu.
                val aktuelleStimme = settings.value.ttsVoice
                val info = status.voices.firstOrNull { it.id == aktuelleStimme }
                val passtNicht = info == null ||
                    status.provider !in info.compatible_providers
                if (passtNicht && status.defaultVoice.isNotBlank() &&
                    status.defaultVoice != aktuelleStimme
                ) {
                    settingsRepo.setTtsVoice(status.defaultVoice)
                }
            }
            .onFailure { _ttsError.value = "Status nicht lesbar: ${it.message}" }
    }

    fun uploadTtsCredentials(json: String) = viewModelScope.launch {
        _ttsBusy.value = true
        _ttsError.value = null
        runCatching { chatRepo.setTtsCredentials(json) }
            .onSuccess { _ttsStatus.value = it }
            .onFailure { e ->
                val msg = when (e) {
                    is ApiException -> "HTTP ${e.code}: ${e.body.take(160)}"
                    else -> e.message ?: e::class.java.simpleName
                }
                _ttsError.value = msg
            }
        _ttsBusy.value = false
    }

    fun deleteTtsCredentials() = viewModelScope.launch {
        _ttsBusy.value = true
        runCatching { chatRepo.deleteTtsCredentials() }
        refreshTtsStatus()
        _ttsBusy.value = false
    }

    /** Setzt den TTS-spezifischen Gemini-API-Key (getrennt vom Image-Gen-Key). */
    fun setTtsApiKey(apiKey: String) = viewModelScope.launch {
        val k = apiKey.trim()
        if (k.isEmpty()) return@launch
        _ttsBusy.value = true
        _ttsError.value = null
        runCatching { chatRepo.setTtsApiKey(k) }
            .onSuccess { _ttsStatus.value = it }
            .onFailure { e ->
                val msg = when (e) {
                    is ApiException -> "HTTP ${e.code}: ${e.body.take(160)}"
                    else -> e.message ?: e::class.java.simpleName
                }
                _ttsError.value = "TTS-Key speichern fehlgeschlagen: $msg"
            }
        _ttsBusy.value = false
    }

    /** Entfernt den TTS-API-Key. Fallback auf Image-Key greift falls vorhanden. */
    fun deleteTtsApiKey() = viewModelScope.launch {
        _ttsBusy.value = true
        runCatching { chatRepo.deleteTtsApiKey() }
            .onSuccess { _ttsStatus.value = it }
        _ttsBusy.value = false
    }

    // ---------- Multi-Key-Pool ----------

    private val _ttsKeyPool = MutableStateFlow<List<TtsApiKeyEntryDto>>(emptyList())
    val ttsKeyPool: StateFlow<List<TtsApiKeyEntryDto>> = _ttsKeyPool.asStateFlow()

    fun refreshTtsKeyPool() = viewModelScope.launch {
        if (!settings.value.isConfigured) return@launch
        runCatching { chatRepo.listTtsApiKeys() }
            .onSuccess { _ttsKeyPool.value = it.keys }
    }

    fun addTtsKey(apiKey: String, label: String = "") = viewModelScope.launch {
        val k = apiKey.trim()
        if (k.isEmpty()) return@launch
        _ttsBusy.value = true
        _ttsError.value = null
        runCatching { chatRepo.addTtsApiKey(k, label.trim()) }
            .onSuccess {
                _ttsKeyPool.value = it.keys
                // Status auch refreshen (für gemini_api_key_count + masked-Anzeige)
                refreshTtsStatus()
            }
            .onFailure { e ->
                val msg = when (e) {
                    is ApiException -> when (e.code) {
                        409 -> appContext.getString(R.string.settings_pool_err_duplicate)
                        400 -> appContext.getString(R.string.settings_pool_err_invalid)
                        else -> "HTTP ${e.code}: ${e.body.take(160)}"
                    }
                    else -> e.message ?: e::class.java.simpleName
                }
                _ttsError.value = appContext.getString(R.string.settings_pool_err_add_failed, msg)
            }
        _ttsBusy.value = false
    }

    fun removeTtsKey(keyId: String) = viewModelScope.launch {
        _ttsBusy.value = true
        runCatching { chatRepo.removeTtsApiKey(keyId) }
            .onSuccess {
                _ttsKeyPool.value = it.keys
                refreshTtsStatus()
            }
            .onFailure { e ->
                _ttsError.value = "Key entfernen fehlgeschlagen: ${e.message}"
            }
        _ttsBusy.value = false
    }

    fun relabelTtsKey(keyId: String, label: String) = viewModelScope.launch {
        runCatching { chatRepo.relabelTtsApiKey(keyId, label.trim()) }
            .onSuccess { _ttsKeyPool.value = it.keys }
    }

    /** Wechselt den TTS-Provider per User auf dem Server. Wenn die aktuell
     *  ausgewählte Voice mit dem neuen Provider nicht kompatibel ist, wird
     *  sie automatisch auf die Server-empfohlene Default-Voice umgestellt
     *  (sonst hätte der User eine inkompatible Voice + Server-side Fallback). */
    fun setTtsProvider(provider: String) = viewModelScope.launch {
        _ttsBusy.value = true
        _ttsError.value = null
        runCatching { chatRepo.setTtsProvider(provider) }
            .onSuccess { status ->
                _ttsStatus.value = status
                // Voice-Kompatibilitäts-Check: aktuelle Voice noch nutzbar?
                val currentVoice = settings.value.ttsVoice
                val voiceInfo = status.voices.firstOrNull { it.id == currentVoice }
                val incompatible = voiceInfo != null &&
                    provider !in voiceInfo.compatible_providers
                if (incompatible || voiceInfo == null) {
                    // Auf Server-Default umstellen (provider-aware)
                    settingsRepo.setTtsVoice(status.defaultVoice)
                }
            }
            .onFailure { e ->
                val msg = when (e) {
                    is ApiException -> "HTTP ${e.code}: ${e.body.take(160)}"
                    else -> e.message ?: e::class.java.simpleName
                }
                _ttsError.value = "Provider-Wechsel fehlgeschlagen: $msg"
            }
        _ttsBusy.value = false
    }

    /** Setzt das TTS-Modell auf dem Server (per User). */
    fun setTtsModel(modelId: String) = viewModelScope.launch {
        _ttsBusy.value = true
        _ttsError.value = null
        runCatching { chatRepo.setTtsModel(modelId) }
            .onSuccess { _ttsStatus.value = it }
            .onFailure { e ->
                val msg = when (e) {
                    is ApiException -> "HTTP ${e.code}: ${e.body.take(160)}"
                    else -> e.message ?: e::class.java.simpleName
                }
                _ttsError.value = "Modell-Wechsel fehlgeschlagen: $msg"
            }
        _ttsBusy.value = false
    }

    fun setVoice(voice: String) = viewModelScope.launch {
        settingsRepo.setTtsVoice(voice)
    }

    /** Setzt die Chunking-Option. `enabled=null` → zurück auf Provider-Default. */
    fun setTtsChunking(enabled: Boolean?) = viewModelScope.launch {
        _ttsBusy.value = true
        _ttsError.value = null
        runCatching { chatRepo.setTtsChunking(enabled) }
            .onSuccess { _ttsStatus.value = it }
            .onFailure { e ->
                val msg = when (e) {
                    is ApiException -> "HTTP ${e.code}: ${e.body.take(160)}"
                    else -> e.message ?: e::class.java.simpleName
                }
                _ttsError.value = "Chunking-Umstellung fehlgeschlagen: $msg"
            }
        _ttsBusy.value = false
    }

    fun setAutoSpeak(enabled: Boolean) = viewModelScope.launch {
        settingsRepo.setTtsAutoSpeak(enabled)
    }

    fun setSpeed(speed: Float) = viewModelScope.launch {
        settingsRepo.setTtsSpeed(speed)
    }

    /** Spielt eine Test-Audio mit der aktuell gewählten Stimme.
     *  Wir nutzen dafür Message-ID -1 trickreich? Nein — wir nehmen einen echten
     *  Workflow: legen eine Dummy-Message in eine versteckte Test-Konversation
     *  und spielen die ab. Einfacher: Wir spielen über `/messages/{id}/audio`
     *  einer beliebigen vorhandenen Message — falls keine da ist, geben wir
     *  einen Hinweis. */
    fun testVoice() = viewModelScope.launch {
        _ttsTest.value = TtsTestResult.Testing
        try {
            val conversations = chatRepo.list()
            // Suche über ALLE Konversationen (Liste ist most-recent-first sortiert) bis
            // eine mit einer Assistant-Nachricht gefunden ist — nicht nur die erste.
            var testMsgId: Long? = null
            for (conv in conversations) {
                testMsgId = chatRepo.detail(conv.id).messages
                    .firstOrNull { m -> m.role == "assistant" }?.id
                if (testMsgId != null) break
            }
            if (testMsgId == null) {
                _ttsTest.value = TtsTestResult.Failure(
                    "Kein Beispiel-Text vorhanden — schreib erst eine Nachricht im Chat, dann teste hier."
                )
                return@launch
            }
            // Gleiche Aufteilung wie im Chat: bei Gemini-Web macht der Player
            // das Tempo, bei allen anderen der Server.
            val webTts = (ttsStatus.value?.provider ?: "") == "gemini_web"
            val serverRate = if (webTts) 1.0f else settings.value.ttsSpeed
            val playerRate = if (webTts) settings.value.ttsSpeed else 1.0f
            val url = chatRepo.audioUrl(testMsgId, settings.value.ttsVoice, serverRate)
            val cacheKey = "audio-$testMsgId-${settings.value.ttsVoice}-$serverRate"
            audio.play(testMsgId, url, cacheKey, speed = playerRate)
            _ttsTest.value = TtsTestResult.Idle
        } catch (e: Exception) {
            _ttsTest.value = TtsTestResult.Failure(e.message ?: e::class.java.simpleName)
        }
    }

    fun stopAudio() {
        audio.stop()
    }

    fun clearTtsError() {
        _ttsError.value = null
    }

    // ----- Image Generation (Gemini) -----

    private val _imageConfig = MutableStateFlow<de.smartzone.pocketclaude.data.ImageConfigDto?>(null)
    val imageConfig: StateFlow<de.smartzone.pocketclaude.data.ImageConfigDto?> = _imageConfig.asStateFlow()

    private val _imageKeyBusy = MutableStateFlow(false)
    val imageKeyBusy: StateFlow<Boolean> = _imageKeyBusy.asStateFlow()

    private val _imageKeyMessage = MutableStateFlow<String?>(null)
    val imageKeyMessage: StateFlow<String?> = _imageKeyMessage.asStateFlow()

    fun refreshImageConfig() = viewModelScope.launch {
        if (!settings.value.isConfigured) return@launch
        runCatching { chatRepo.imagesConfig() }
            .onSuccess { _imageConfig.value = it }
            .onFailure { _imageKeyMessage.value = "Image-Config nicht ladbar: ${it.message}" }
    }

    fun setImageApiKey(key: String) = viewModelScope.launch {
        val k = key.trim()
        if (k.isEmpty()) return@launch
        _imageKeyBusy.value = true
        _imageKeyMessage.value = null
        try {
            chatRepo.setImageApiKey(k)
            _imageKeyMessage.value = "✓ Key gespeichert"
            refreshImageConfig().join()
        } catch (e: Exception) {
            _imageKeyMessage.value = "Fehler: ${e.message}"
        } finally {
            _imageKeyBusy.value = false
        }
    }

    fun deleteImageApiKey() = viewModelScope.launch {
        _imageKeyBusy.value = true
        runCatching { chatRepo.deleteImageApiKey() }
        _imageKeyMessage.value = "Key entfernt"
        refreshImageConfig().join()
        _imageKeyBusy.value = false
    }

    fun clearImageKeyMessage() { _imageKeyMessage.value = null }

    // ----- Voice-Input (Groq Whisper) -----

    private val _voiceConfig =
        MutableStateFlow<de.smartzone.pocketclaude.data.VoiceConfigDto?>(null)
    val voiceConfig: StateFlow<de.smartzone.pocketclaude.data.VoiceConfigDto?> =
        _voiceConfig.asStateFlow()

    private val _voiceKeyBusy = MutableStateFlow(false)
    val voiceKeyBusy: StateFlow<Boolean> = _voiceKeyBusy.asStateFlow()

    private val _voiceKeyMessage = MutableStateFlow<String?>(null)
    val voiceKeyMessage: StateFlow<String?> = _voiceKeyMessage.asStateFlow()

    fun refreshVoiceConfig() = viewModelScope.launch {
        if (!settings.value.isConfigured) return@launch
        runCatching { chatRepo.voiceConfig() }
            .onSuccess { _voiceConfig.value = it }
            .onFailure { _voiceKeyMessage.value = "Voice-Config nicht ladbar: ${it.message}" }
    }

    fun setVoiceApiKey(key: String) = viewModelScope.launch {
        val k = key.trim()
        if (k.isEmpty()) return@launch
        _voiceKeyBusy.value = true
        _voiceKeyMessage.value = null
        try {
            chatRepo.setVoiceApiKey(k)
            _voiceKeyMessage.value = "✓ Key gespeichert"
            refreshVoiceConfig().join()
        } catch (e: Exception) {
            _voiceKeyMessage.value = "Fehler: ${e.message}"
        } finally {
            _voiceKeyBusy.value = false
        }
    }

    fun deleteVoiceApiKey() = viewModelScope.launch {
        _voiceKeyBusy.value = true
        runCatching { chatRepo.deleteVoiceApiKey() }
        _voiceKeyMessage.value = "Key entfernt"
        refreshVoiceConfig().join()
        _voiceKeyBusy.value = false
    }

    fun clearVoiceKeyMessage() { _voiceKeyMessage.value = null }

    // ----- Voice-Lang-Override + Auto-Translate via Claude -----

    /** Drei sichtbare UI-States für den Übersetzungs-Status. */
    enum class TranslateStatus { Idle, Running, Success, Error }

    private val _translateStatus = MutableStateFlow(TranslateStatus.Idle)
    val translateStatus: StateFlow<TranslateStatus> = _translateStatus.asStateFlow()

    private val _translateMessage = MutableStateFlow<String?>(null)
    val translateMessage: StateFlow<String?> = _translateMessage.asStateFlow()

    /** Setzt mode=auto und löscht jeden Override. */
    fun setVoiceLangAuto() = viewModelScope.launch {
        try {
            val cfg = chatRepo.setVoiceLangConfig("auto", null)
            _voiceConfig.value = cfg
            _translateStatus.value = TranslateStatus.Idle
            _translateMessage.value = null
        } catch (e: Exception) {
            _translateStatus.value = TranslateStatus.Error
            _translateMessage.value = e.message ?: e::class.java.simpleName
        }
    }

    /** Setzt mode=override mit konkreter Locale.
     *  Wenn die Locale nicht gebundlet ist UND noch nicht im Cache,
     *  triggert das im Anschluss automatisch eine Übersetzung — UI sieht
     *  dabei translateStatus=Running. */
    fun setVoiceLangOverride(locale: String) = viewModelScope.launch {
        val loc = locale.trim().lowercase()
        if (loc.isEmpty()) return@launch
        try {
            val cfg = chatRepo.setVoiceLangConfig("override", loc)
            _voiceConfig.value = cfg
            val isBundled = cfg.bundledLanguages.contains(cfg.currentLang)
            val cached = cfg.cachedLanguages.contains(cfg.currentLang)
            if (!isBundled && !cached) {
                translateVoicePrompt(cfg.currentLang, force = false)
            } else {
                _translateStatus.value = TranslateStatus.Idle
                _translateMessage.value = null
            }
        } catch (e: Exception) {
            _translateStatus.value = TranslateStatus.Error
            _translateMessage.value = e.message ?: e::class.java.simpleName
        }
    }

    /** Triggert eine Claude-Übersetzung; UI zeigt Spinner während Running. */
    fun translateVoicePrompt(locale: String, force: Boolean = false) = viewModelScope.launch {
        val loc = locale.trim().lowercase()
        if (loc.isEmpty()) return@launch
        _translateStatus.value = TranslateStatus.Running
        _translateMessage.value = null
        try {
            chatRepo.translateVoicePrompt(loc, force)
            _translateStatus.value = TranslateStatus.Success
            refreshVoiceConfig().join()
        } catch (e: Exception) {
            _translateStatus.value = TranslateStatus.Error
            _translateMessage.value = e.message ?: e::class.java.simpleName
        }
    }

    /** Löscht den Cache-Eintrag — danach greift wieder Bundled-Default
     *  (oder ein erneuter Translate-Call). */
    fun resetVoicePromptCache(locale: String) = viewModelScope.launch {
        runCatching { chatRepo.deleteCachedVoicePrompt(locale.trim().lowercase()) }
        refreshVoiceConfig().join()
        _translateStatus.value = TranslateStatus.Idle
        _translateMessage.value = null
    }

    fun clearTranslateStatus() {
        _translateStatus.value = TranslateStatus.Idle
        _translateMessage.value = null
    }

    // ----- Backup / Import -----

    sealed interface BackupState {
        data object Idle : BackupState
        /** App fragt den User nach einem optionalen Export-Passwort. */
        data object AwaitingExportPassword : BackupState
        /** Lädt das Backup-ZIP vom Server herunter. */
        data object Exporting : BackupState
        /** ZIP wird zum Server hochgeladen — entweder zum Peek (Manifest
         *  lesen) oder zum Re-Peek mit Passwort. */
        data object Verifying : BackupState
        /** Export fertig, ZIP-Bytes liegen vor → kann jetzt geshared werden. */
        data class Exported(val bytes: ByteArray, val filename: String) : BackupState
        /** Importierte ZIP ist verschlüsselt — App fragt nach PW. */
        data class AwaitingImportPassword(
            val bytes: ByteArray,
            val previousAttemptFailed: Boolean,
        ) : BackupState
        /** Datei für Import wurde gewählt + Manifest gelesen → Confirm-Dialog. */
        data class ReadyToImport(
            val bytes: ByteArray,
            val manifest: de.smartzone.pocketclaude.data.BackupManifestDto,
            /** Wenn ZIP verschlüsselt war: das funktionierende PW, damit
             *  der Import-Call es wiederverwenden kann. */
            val password: String?,
        ) : BackupState
        data object Importing : BackupState
        data class ImportSuccess(
            val response: de.smartzone.pocketclaude.data.BackupImportResponse,
        ) : BackupState
        data class Failure(val reason: String) : BackupState
    }

    private val _backup = MutableStateFlow<BackupState>(BackupState.Idle)
    val backup: StateFlow<BackupState> = _backup.asStateFlow()

    /** Schritt 1 des Exports: Password-Dialog öffnen. User kann PW eingeben
     *  oder leer lassen (= unverschlüsseltes Backup). */
    fun startExport() {
        _backup.value = BackupState.AwaitingExportPassword
    }

    /** Schritt 2 des Exports: Server-Call mit dem (optionalen) Passwort.
     *  Bei Erfolg → Exported-State, UI öffnet Share-Intent. */
    fun runExport(password: String?) = viewModelScope.launch {
        _backup.value = BackupState.Exporting
        try {
            val bytes = chatRepo.downloadBackup(password?.takeIf { it.isNotBlank() })
            val ts = java.text.SimpleDateFormat("yyyyMMdd-HHmmss", java.util.Locale.getDefault())
                .format(java.util.Date())
            val suffix = if (!password.isNullOrBlank()) ".enc.zip" else ".zip"
            val filename = "pocket-claude-backup-$ts$suffix"
            _backup.value = BackupState.Exported(bytes, filename)
        } catch (e: Exception) {
            _backup.value = BackupState.Failure(e.message ?: e::class.java.simpleName)
        }
    }

    /** User hat im File-Picker eine ZIP gewählt → wir versuchen das Manifest
     *  zu lesen. Bei HTTP 423 (verschlüsselt) → AwaitingImportPassword-State. */
    fun stageImport(zipBytes: ByteArray) = viewModelScope.launch {
        _backup.value = BackupState.Verifying
        try {
            val peek = chatRepo.peekBackup(zipBytes, null)
            _backup.value = BackupState.ReadyToImport(zipBytes, peek.manifest, password = null)
        } catch (e: ApiException) {
            if (e.code == 423) {
                _backup.value = BackupState.AwaitingImportPassword(zipBytes, previousAttemptFailed = false)
            } else {
                _backup.value = BackupState.Failure(e.message ?: e::class.java.simpleName)
            }
        } catch (e: Exception) {
            _backup.value = BackupState.Failure(e.message ?: e::class.java.simpleName)
        }
    }

    /** User hat im Password-Prompt das PW eingegeben (Import). */
    fun retryImportWithPassword(password: String) = viewModelScope.launch {
        val current = _backup.value
        val bytes = when (current) {
            is BackupState.AwaitingImportPassword -> current.bytes
            else -> return@launch
        }
        _backup.value = BackupState.Verifying
        try {
            val peek = chatRepo.peekBackup(bytes, password)
            _backup.value = BackupState.ReadyToImport(bytes, peek.manifest, password = password)
        } catch (e: ApiException) {
            if (e.code == 423) {
                // PW war falsch → nochmal fragen, mit Hinweis
                _backup.value = BackupState.AwaitingImportPassword(bytes, previousAttemptFailed = true)
            } else {
                _backup.value = BackupState.Failure(e.message ?: e::class.java.simpleName)
            }
        } catch (e: Exception) {
            _backup.value = BackupState.Failure(e.message ?: e::class.java.simpleName)
        }
    }

    /** User hat im Confirm-Dialog Replace oder Merge gewählt. */
    fun confirmImport(mode: String) = viewModelScope.launch {
        val current = _backup.value
        if (current !is BackupState.ReadyToImport) return@launch
        _backup.value = BackupState.Importing
        try {
            val resp = chatRepo.importBackup(current.bytes, mode, current.password)
            _backup.value = BackupState.ImportSuccess(resp)
        } catch (e: Exception) {
            _backup.value = BackupState.Failure(e.message ?: e::class.java.simpleName)
        }
    }

    fun resetBackupState() {
        _backup.value = BackupState.Idle
    }

    // ---------- Settings Export / Import (komplettes Bundle) ----------

    sealed interface SettingsTransferState {
        data object Idle : SettingsTransferState
        data object Exporting : SettingsTransferState
        data class Exported(val bytes: ByteArray, val filename: String) : SettingsTransferState
        data object Importing : SettingsTransferState
        data class ImportSuccess(
            val appliedServer: Int,
            val ttsKeysImported: Int,
        ) : SettingsTransferState
        data class Failure(val reason: String) : SettingsTransferState
    }

    private val _settingsTransfer = MutableStateFlow<SettingsTransferState>(SettingsTransferState.Idle)
    val settingsTransfer: StateFlow<SettingsTransferState> = _settingsTransfer.asStateFlow()

    fun resetSettingsTransfer() { _settingsTransfer.value = SettingsTransferState.Idle }

    /** Exportiert Server-seitige Settings + lokale App-Settings als JSON-File. */
    fun exportAllSettings() = viewModelScope.launch {
        _settingsTransfer.value = SettingsTransferState.Exporting
        try {
            val serverPart = chatRepo.exportServerSettings()
            val appPart = settingsRepo.snapshotForExport()
            val bundle = de.smartzone.pocketclaude.data.FullSettingsExportDto(
                schemaVersion = 1,
                exportedAt = java.time.OffsetDateTime.now().toString(),
                appVersion = "PocketClaudeApp",
                server = serverPart,
                app = appPart,
            )
            val json = kotlinx.serialization.json.Json {
                prettyPrint = true
                encodeDefaults = true
            }
            val bytes = json.encodeToString(
                de.smartzone.pocketclaude.data.FullSettingsExportDto.serializer(),
                bundle,
            ).toByteArray(Charsets.UTF_8)
            val ts = java.text.SimpleDateFormat("yyyyMMdd-HHmmss", java.util.Locale.getDefault())
                .format(java.util.Date())
            val filename = "pocket-claude-settings-$ts.json"
            _settingsTransfer.value = SettingsTransferState.Exported(bytes, filename)
        } catch (e: Exception) {
            _settingsTransfer.value = SettingsTransferState.Failure(
                "Export fehlgeschlagen: ${e.message ?: e::class.java.simpleName}"
            )
        }
    }

    /** Lädt ein zuvor exportiertes JSON, wendet Server-Anteil via API und
     *  App-Anteil via DataStore an. */
    fun importAllSettings(bytes: ByteArray) = viewModelScope.launch {
        _settingsTransfer.value = SettingsTransferState.Importing
        try {
            val text = bytes.toString(Charsets.UTF_8)
            val json = kotlinx.serialization.json.Json {
                ignoreUnknownKeys = true
                isLenient = true
            }
            val bundle = json.decodeFromString(
                de.smartzone.pocketclaude.data.FullSettingsExportDto.serializer(),
                text,
            )
            // Server-Anteil als Import-Request umpacken (mapped 1:1 inkl. Keys)
            val req = de.smartzone.pocketclaude.data.ServerSettingsImportRequest(
                schemaVersion = bundle.schemaVersion,
                ttsProvider = bundle.server.ttsProvider,
                ttsModel = bundle.server.ttsModel,
                ttsChunkingEnabled = bundle.server.ttsChunkingEnabled,
                ttsApiKeys = bundle.server.ttsApiKeys,
                imageApiKey = bundle.server.imageApiKey,
                skillsDefaults = bundle.server.skillsDefaults,
                extraKv = bundle.server.extraKv.takeIf { it.isNotEmpty() },
            )
            val resp = chatRepo.importServerSettings(req)
            // App-Anteil lokal anwenden
            settingsRepo.applyImport(bundle.app)
            // VM-State refreshen, damit UI die neuen Werte sieht
            refreshTtsStatus()
            refreshTtsKeyPool()
            refreshImageConfig()
            refreshDefaultSkills()
            _settingsTransfer.value = SettingsTransferState.ImportSuccess(
                appliedServer = resp.appliedKeys,
                ttsKeysImported = resp.ttsKeysImported,
            )
        } catch (e: Exception) {
            val hint = if (e is kotlinx.serialization.SerializationException)
                "JSON ist nicht im erwarteten Format. Stelle sicher, dass das die " +
                    "Export-Datei von PocketClot ist."
            else (e.message ?: e::class.java.simpleName)
            _settingsTransfer.value = SettingsTransferState.Failure("Import fehlgeschlagen: $hint")
        }
    }

    companion object {
        fun factory(container: AppContainer): ViewModelProvider.Factory =
            object : ViewModelProvider.Factory {
                @Suppress("UNCHECKED_CAST")
                override fun <T : ViewModel> create(modelClass: Class<T>): T {
                    return SettingsViewModel(
                        container.settingsRepository,
                        container.chatRepository,
                        container.audioController,
                        container.appContext,
                    ) as T
                }
            }
    }
}
