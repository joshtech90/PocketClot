package de.smartzone.pocketclaude.data

import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.MutablePreferences
import androidx.datastore.preferences.core.floatPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.core.stringSetPreferencesKey
import kotlinx.coroutines.flow.Flow
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/** Vorgabe-Farbschema fuer den hellen Modus. Muss zur ID von
 *  `PocketPalette.NORDIC_BLUE` passen. */
const val DEFAULT_PALETTE_ID_LIGHT = "nordic_blue"

/** Vorgabe-Farbschema fuer den dunklen Modus. Muss zur ID von
 *  `PocketPalette.MIDNIGHT_ATELIER` passen. */
const val DEFAULT_PALETTE_ID_DARK = "midnight_atelier"

/** Alter, gemeinsamer Vorgabewert. Bleibt nur, damit ein Export aus einer
 *  aelteren App-Version noch gelesen werden kann. */
const val DEFAULT_PALETTE_ID = DEFAULT_PALETTE_ID_DARK

/** Claude-Alltagsmodell als Familie (Server nimmt die neueste Generation).
 *  Muss zu `DEFAULT_CLAUDE_MODEL` in claude_engine.py passen. */
const val DEFAULT_CLAUDE_MODEL = "opus"

enum class ThemeMode {
    SYSTEM, LIGHT, DARK;

    companion object {
        fun fromString(value: String?): ThemeMode = entries.firstOrNull { it.name == value } ?: SYSTEM
    }
}

/**
 * Ein Server-Profil: URL + Login + Session-Token. Mit Multi-User-Server kann
 * jedes Familienmitglied sein eigenes Profil haben und die App schnell zwischen
 * ihnen wechseln, ohne sich jedes Mal neu einzuloggen.
 *
 * - `username`: Benutzername fürs Login (wird gespeichert, damit der User ihn
 *   nicht jedes Mal neu eintippen muss).
 * - `serverToken`: das vom Server zurückgegebene Session-Token. Wenn leer →
 *   Profil ist noch nicht aktiviert und der nächste API-Call schlägt fehl;
 *   die App zeigt dann den Login-Screen. Das Passwort wird NICHT gespeichert.
 *
 * Migration aus der Token-Only-Zeit: alte Profile haben einen `serverToken`,
 * aber keinen `username`. Beim ersten Login wird `username` befüllt; das alte
 * Token gilt einmalig als „Passwort" für den Server (siehe auth.py).
 */
@Serializable
data class Profile(
    val id: String,
    val label: String,
    val serverUrl: String,
    val serverToken: String,
    val username: String = "",
)

data class AppSettings(
    /** Alle gespeicherten Server-Profile. */
    val profiles: List<Profile> = emptyList(),
    /** ID des aktuell aktiven Profils. Leer wenn keins gewählt. */
    val activeProfileId: String = "",
    val themeMode: ThemeMode = ThemeMode.SYSTEM,
    /** ID des Farbschemas (siehe `PocketPalette` in ui.theme). Bewusst als
     *  String und nicht als Enum: die Datenschicht soll nichts aus der
     *  UI-Schicht importieren muessen. Unbekannte Werte fallen in der UI
     *  automatisch auf die Standardpalette zurueck. */
    val paletteIdLight: String = DEFAULT_PALETTE_ID_LIGHT,
    /** Farbschema fuer den dunklen Modus. Hell und dunkel sind bewusst
     *  getrennt: der helle Look darf ein anderer sein als der dunkle. */
    val paletteIdDark: String = DEFAULT_PALETTE_ID_DARK,
    /** Default-Voice ist Edge KatjaNeural (gratis, kein Setup nötig). Passt
     *  zum Default-Provider `edge_tts`. Für User mit Cloud-TTS-/Gemini-API-
     *  Setup liefert der Server via /tts/status einen passenden Default
     *  (chirp3hd-Algenib bzw. gemini-Algenib), und beim Provider-Switch in
     *  der App wird die Voice automatisch nachgezogen. */
    val ttsVoice: String = "edge-de-DE-KatjaNeural",
    val ttsAutoSpeak: Boolean = false,
    /** Wiedergabegeschwindigkeit [0.25 .. 2.0], Default 1.0. */
    val ttsSpeed: Float = 1.0f,
    /** off | low | medium | high | xhigh | max — Denktiefe für Claude.
     *  `xhigh` ist Opus-4.7-only (fällt auf anderen Modellen auf `high` zurück);
     *  wir nutzen Opus 4.7, also ist es für uns ein echtes Extra-Level. */
    val effort: String = DEFAULT_EFFORT,
    /** STANDARD | PERMISSIVE | CUSTOM — welcher System-Prompt soll Claude bekommen. */
    val systemPromptMode: SystemPromptMode = SystemPromptMode.STANDARD,
    /** Frei einzugebender Custom-System-Prompt (nur aktiv wenn mode = CUSTOM). */
    val customSystemPrompt: String = "",
    /** Lange eigene Nachrichten in der Chat-Ansicht einklappen (à la ChatGPT) —
     *  nach 6 Zeilen Fade-Out + „Mehr anzeigen"-Toggle. Default: AN. */
    val collapseLongUserMessages: Boolean = true,
    /** Auto-Send im Auto-Modus: nach `autoSendSilenceMs` Stille wird die
     *  Aufnahme automatisch beendet + gesendet. AUS → User muss aktiv tippen,
     *  um zu senden (manuelles Stoppen). Default: AUS — die VAD-Heuristik ist
     *  device-abhängig (MediaRecorder.maxAmplitude liefert je nach Encoder
     *  unterschiedliche Werte), deshalb opt-in statt opt-out. */
    val autoSendEnabled: Boolean = false,
    /** Stille-Schwellwert in ms für Auto-Send. Default 3000 (3 s). */
    val autoSendSilenceMs: Long = 3000L,
    /** Gesperrte Chats per Fingerabdruck/Gesichtsscan entsperren (statt PIN).
     *  Gerät-lokal (Biometrie ist gerätspezifisch), Default: AN — wenn das
     *  Gerät Biometrie hat, ist das der bequemste Weg; PIN bleibt Fallback. */
    val chatLockBiometricEnabled: Boolean = true,
    /** Global gewähltes Chat-Modell. Leer = Claude (Server-Automatik). Zusatz-
     *  Modelle tragen den Präfix „gw:". */
    val chatModelKey: String = "",
    /** Denktiefe je Modell-Familie („claude", „gemini", „gpt"). Fehlt ein
     *  Eintrag, gilt „high". Claude liest weiterhin aus `effort`, damit alte
     *  Einstellungen erhalten bleiben. */
    val effortByFamily: Map<String, String> = emptyMap(),
    /** Standardmodell je Anbieter, z.B. {"claude": "opus"}. Leer heisst:
     *  nimm den eingebauten Standard der Familie. */
    val defaultModelByFamily: Map<String, String> = emptyMap(),
    /** Standard-Auflösung für erzeugte Bilder. 2K passt zu Handy-Displays. */
    val imageDefaultSize: String = "2K",
    /** Standard-Seitenverhältnis für erzeugte Bilder. */
    val imageDefaultAspect: String = "1:1",
) {
    /** Aktuell aktives Profil (oder null wenn keins gewählt). */
    val activeProfile: Profile?
        get() = profiles.firstOrNull { it.id == activeProfileId }

    /** Server-URL des aktiven Profils — Kompatibilität mit altem Code. */
    val serverUrl: String get() = activeProfile?.serverUrl.orEmpty()
    /** Token des aktiven Profils. */
    val serverToken: String get() = activeProfile?.serverToken.orEmpty()

    val isConfigured: Boolean
        get() = serverUrl.isNotBlank() && serverToken.isNotBlank()

    /** Den finalen String, der an den Server geschickt wird. */
    val resolvedSystemPrompt: String
        get() = effectiveSystemPrompt(systemPromptMode, customSystemPrompt)

    /** Denktiefe für eine Modell-Familie. Claude nutzt weiter `effort`, alles
     *  andere die Map. Nichts gesetzt heißt „high". */
    fun effortFor(family: String): String =
        if (family == ChatModelFamilies.CLAUDE) effort.ifBlank { DEFAULT_EFFORT }
        else effortByFamily[family]?.takeIf { it.isNotBlank() } ?: DEFAULT_EFFORT

    /**
     * Standardmodell einer Familie. Fuer Claude gibt es einen eingebauten
     * Rueckfall, damit ohne jede Einstellung das aktuelle Alltagsmodell laeuft
     * statt irgendeines CLI-Defaults. Die Zusatz-Familien haben keinen festen
     * Rueckfall: welche Modelle es dort gibt, sagt erst das Gateway.
     */
    fun defaultModelFor(family: String): String =
        defaultModelByFamily[family]?.takeIf { it.isNotBlank() }
            ?: if (family == ChatModelFamilies.CLAUDE) DEFAULT_CLAUDE_MODEL else ""

    /** Modellschluessel fuer einen NEUEN Chat: explizite Wahl vor Claude-Standard. */
    fun modelKeyForNewChat(): String =
        chatModelKey.ifBlank { defaultModelFor(ChatModelFamilies.CLAUDE) }

    /**
     * Die Denktiefe, die fuer ein konkretes Modell wirklich gilt.
     *
     * Gemerkt wird die Denktiefe pro Familie („bei Gemini denke gruendlich"),
     * koennen tut sie aber das einzelne Modell. Deshalb wird die Familien-Wahl
     * hier auf die Stufen des Modells geklemmt, genau wie es der Server tut.
     * Meldet ein Modell gar keine Stufen (`efforts` leer), gibt es nichts zu
     * waehlen und das Ergebnis ist leer.
     */
    fun effortForModel(option: ChatModelOption?): String =
        effortForModelKey(option?.key ?: "", option)

    /**
     * Wie [effortForModel], aber auch dann verwendbar, wenn zum Modell-Key
     * gerade keine Beschreibung vorliegt: etwa weil die Liste noch laedt oder
     * ein Gateway kurz weg ist.
     *
     * Claude ist der Sonderfall. Es laeuft nicht ueber die Gateways, seine
     * Stufen stehen fest (inklusive „aus") und duerfen nicht davon abhaengen,
     * ob der Server gerade eine Stufenliste mitgeschickt hat.
     */
    fun effortForModelKey(
        modelKey: String,
        option: ChatModelOption?,
        chatEffort: String? = null,
    ): String {
        val family = option?.family ?: familyForKey(modelKey)
        val available = availableEffortsFor(family, option)
        if (available.isEmpty()) return ""
        // Hat der Chat eine eigene Denktiefe (vom Gem), gilt die statt der Familie.
        return clampEffort(chatEffort?.takeIf { it.isNotBlank() } ?: effortFor(family), available)
    }

    /**
     * Die Stufen, die fuer ein Modell zur Wahl stehen.
     *
     * Fuer Claude sind das immer [EFFORT_LEVELS]. Fuer die Zusatz-Modelle sagt
     * das Modell selbst, was es kann; ist es unbekannt, wird die gemeinsame
     * Skala OHNE „aus" angenommen, denn Abschalten kennen die Gateways nicht.
     */
    fun availableEffortsFor(family: String, option: ChatModelOption?): List<String> = when {
        family == ChatModelFamilies.CLAUDE -> EFFORT_LEVELS
        option != null -> option.efforts
        else -> EFFORT_LEVELS.filter { it != "off" }
    }
}

class SettingsRepository(
    private val dataStore: DataStore<Preferences>,
    private val wissenPrefs: android.content.SharedPreferences? = null,
) {

    private val json = Json { ignoreUnknownKeys = true }

    // Legacy-Keys (für Migration vom Single-Profile-Setup)
    private val keyServerUrl = stringPreferencesKey("server_url")
    private val keyServerToken = stringPreferencesKey("server_token")

    private val keyProfiles = stringPreferencesKey("profiles_json")
    private val keyActiveProfileId = stringPreferencesKey("active_profile_id")

    private val keyLastChatCid = stringPreferencesKey("last_chat_cid")
    /** Per-Chat-Override für Auto-Speak. JSON: { "cid1": true, "cid2": false }.
     *  Wenn ein Chat KEINEN Eintrag hat → globaler ttsAutoSpeak greift. */
    private val keyTtsAutoSpeakPerChat = stringPreferencesKey("tts_auto_speak_per_chat")
    private val keyThemeMode = stringPreferencesKey("theme_mode")
    /** Alter, gemeinsamer Schluessel. Wird nur noch gelesen, um die Wahl eines
     *  Bestandsnutzers auf die beiden neuen Schluessel zu uebernehmen. */
    private val keyPaletteId = stringPreferencesKey("palette_id")
    private val keyPaletteIdLight = stringPreferencesKey("palette_id_light")
    private val keyPaletteIdDark = stringPreferencesKey("palette_id_dark")
    private val keyTtsVoice = stringPreferencesKey("tts_voice")
    private val keyTtsAutoSpeak = stringPreferencesKey("tts_auto_speak")
    private val keyTtsSpeed = floatPreferencesKey("tts_speed")
    private val keyEffort = stringPreferencesKey("effort")
    private val keySystemPromptMode = stringPreferencesKey("system_prompt_mode")
    private val keyCustomSystemPrompt = stringPreferencesKey("custom_system_prompt")
    private val keyCollapseLongUserMessages = stringPreferencesKey("collapse_long_user_messages")
    private val keyAutoSendEnabled = stringPreferencesKey("auto_send_enabled")
    private val keyAutoSendSilenceMs = stringPreferencesKey("auto_send_silence_ms")
    private val keyChatLockBiometric = stringPreferencesKey("chat_lock_biometric")
    private val keyImageHistoryJson = stringPreferencesKey("image_history_json")
    private val keyChatModelKey = stringPreferencesKey("chat_model_key")
    private val keyEffortByFamily = stringPreferencesKey("effort_by_family_json")
    private val keyDefaultModelByFamily = stringPreferencesKey("default_model_by_family_json")
    private val keyImageDefaultSize = stringPreferencesKey("image_default_size")
    private val keyImageDefaultAspect = stringPreferencesKey("image_default_aspect")
    /** Profile, deren Einstellungen schon einmal mit dem Server abgeglichen
     *  wurden. Beim ERSTEN Abgleich gewinnt, was die App schon hat. */
    private val keyUiSyncedProfiles = stringSetPreferencesKey("ui_synced_profiles")

    /** Liest eine JSON-Map aus den Preferences. Kaputtes JSON gilt als leer,
     *  damit ein beschaedigter Eintrag nicht die ganzen Settings blockiert. */
    /**
     * Liest ein Farbschema und uebernimmt dabei die alte, gemeinsame Wahl.
     *
     * Bis August 2026 gab es nur EIN Schema fuer hell und dunkel. Wer damals
     * eines gewaehlt hat, soll es behalten, statt beim Update ungefragt auf die
     * neuen Vorgaben gesetzt zu werden. Wer nie etwas gewaehlt hat, hat keinen
     * alten Eintrag und bekommt die neuen Vorgaben.
     */
    private fun resolvePalette(
        prefs: Preferences,
        key: Preferences.Key<String>,
        fallback: String,
    ): String = prefs[key]?.takeIf { it.isNotBlank() }
        ?: prefs[keyPaletteId]?.takeIf { it.isNotBlank() }
        ?: fallback

    private fun parseStringMap(raw: String?): Map<String, String> {
        if (raw.isNullOrBlank()) return emptyMap()
        return runCatching {
            json.decodeFromString<Map<String, String>>(raw)
        }.getOrDefault(emptyMap())
    }

    val settingsFlow: Flow<AppSettings> = dataStore.data.map { prefs ->
        // Profile aus JSON laden; bei leerer Liste aber vorhandenem Legacy-Token
        // → on-the-fly migrieren (erstes Profil "Standard" anlegen).
        val profiles = loadProfilesWithMigration(prefs)
        val activeId = prefs[keyActiveProfileId]?.takeIf { id ->
            profiles.any { it.id == id }
        } ?: profiles.firstOrNull()?.id.orEmpty()

        AppSettings(
            profiles = profiles,
            activeProfileId = activeId,
            themeMode = ThemeMode.fromString(prefs[keyThemeMode]),
            paletteIdLight = resolvePalette(prefs, keyPaletteIdLight, DEFAULT_PALETTE_ID_LIGHT),
            paletteIdDark = resolvePalette(prefs, keyPaletteIdDark, DEFAULT_PALETTE_ID_DARK),
            ttsVoice = prefs[keyTtsVoice].orEmpty().ifBlank { "edge-de-DE-KatjaNeural" },
            ttsAutoSpeak = (prefs[keyTtsAutoSpeak] ?: "false").toBooleanStrictOrNull() ?: false,
            ttsSpeed = (prefs[keyTtsSpeed] ?: 1.0f).coerceIn(0.25f, 2.0f),
            effort = prefs[keyEffort]?.takeIf { it.isNotBlank() } ?: DEFAULT_EFFORT,
            systemPromptMode = SystemPromptMode.fromString(prefs[keySystemPromptMode]),
            customSystemPrompt = prefs[keyCustomSystemPrompt].orEmpty(),
            collapseLongUserMessages =
                (prefs[keyCollapseLongUserMessages] ?: "true").toBooleanStrictOrNull() ?: true,
            autoSendEnabled =
                (prefs[keyAutoSendEnabled] ?: "false").toBooleanStrictOrNull() ?: false,
            autoSendSilenceMs = (prefs[keyAutoSendSilenceMs]?.toLongOrNull() ?: 3000L)
                .coerceIn(500L, 10_000L),
            chatLockBiometricEnabled =
                (prefs[keyChatLockBiometric] ?: "true").toBooleanStrictOrNull() ?: true,
            chatModelKey = prefs[keyChatModelKey].orEmpty(),
            effortByFamily = parseStringMap(prefs[keyEffortByFamily]),
            defaultModelByFamily = parseStringMap(prefs[keyDefaultModelByFamily]),
            imageDefaultSize = prefs[keyImageDefaultSize]?.takeIf { it.isNotBlank() } ?: "2K",
            imageDefaultAspect = prefs[keyImageDefaultAspect]?.takeIf { it.isNotBlank() } ?: "1:1",
        )
    }

    /** Setzt das global gewählte Modell. Leer = zurück auf Claude. */
    suspend fun setChatModelKey(value: String) {
        dataStore.edit { prefs ->
            if (value.isBlank()) prefs.remove(keyChatModelKey)
            else prefs[keyChatModelKey] = value
        }
        localChanged("chatModel")
    }

    /** Merkt sich das Standardmodell einer Familie. Leerer Wert loescht den
     *  Eintrag und stellt damit den eingebauten Standard wieder her. */
    suspend fun setDefaultModelForFamily(family: String, value: String) {
        dataStore.edit { prefs ->
            val map = parseStringMap(prefs[keyDefaultModelByFamily]).toMutableMap()
            if (value.isBlank()) map.remove(family) else map[family] = value
            if (map.isEmpty()) prefs.remove(keyDefaultModelByFamily)
            else prefs[keyDefaultModelByFamily] = json.encodeToString(map)
        }
        localEntriesChanged(
            "defaultModelByFamily",
            mapOf(family to if (value.isBlank()) JsonNull else JsonPrimitive(value)),
        )
    }

    /** Merkt sich die Denktiefe pro Familie. Für Claude wird zusätzlich das alte
     *  `effort`-Feld gepflegt, damit bestehender Code weiter funktioniert. */
    suspend fun setEffortForFamily(family: String, value: String) {
        dataStore.edit { prefs ->
            if (family == ChatModelFamilies.CLAUDE) prefs[keyEffort] = value
            val map = parseStringMap(prefs[keyEffortByFamily]).toMutableMap()
            map[family] = value
            prefs[keyEffortByFamily] = json.encodeToString(map)
        }
        if (family == ChatModelFamilies.CLAUDE) localChanged("effort")
        localEntriesChanged("effortByFamily", mapOf(family to JsonPrimitive(value)))
    }

    suspend fun setImageDefaultSize(value: String) {
        dataStore.edit { it[keyImageDefaultSize] = value }
    }

    suspend fun setImageDefaultAspect(value: String) {
        dataStore.edit { it[keyImageDefaultAspect] = value }
    }

    suspend fun setChatLockBiometricEnabled(value: Boolean) {
        dataStore.edit { it[keyChatLockBiometric] = value.toString() }
    }

    suspend fun setCollapseLongUserMessages(value: Boolean) {
        dataStore.edit { it[keyCollapseLongUserMessages] = value.toString() }
        localChanged("collapseUserMsgs")
    }

    suspend fun setAutoSendEnabled(value: Boolean) {
        dataStore.edit { it[keyAutoSendEnabled] = value.toString() }
        localChanged("autoSend")
    }

    suspend fun setAutoSendSilenceMs(value: Long) {
        dataStore.edit { it[keyAutoSendSilenceMs] = value.coerceIn(500L, 10_000L).toString() }
        localChanged("autoSendSilenceMs")
    }

    // ---------- Image-Generation-History (App-lokal) ----------
    //
    // Speichert die bisherigen Bild-Generierungen als JSON-Blob im DataStore.
    // Bewusst NICHT in der Server-DB, weil die Bilder selbst dort als
    // Attachments liegen — wir brauchen hier nur die Liste der Referenzen +
    // Prompt-Metadaten, damit der Bilder-Screen seinen Verlauf zeigen kann.

    suspend fun getImageHistoryRaw(): String =
        dataStore.data.first()[keyImageHistoryJson].orEmpty()

    suspend fun setImageHistoryRaw(json: String) {
        dataStore.edit { prefs ->
            if (json.isBlank()) prefs.remove(keyImageHistoryJson)
            else prefs[keyImageHistoryJson] = json
        }
    }

    private fun loadProfilesWithMigration(prefs: Preferences): List<Profile> {
        val raw = prefs[keyProfiles]
        if (!raw.isNullOrBlank()) {
            return runCatching { json.decodeFromString<List<Profile>>(raw) }.getOrDefault(emptyList())
        }
        // Migration vom Single-Profile-Setup
        val url = prefs[keyServerUrl].orEmpty().trim().trimEnd('/')
        val token = prefs[keyServerToken].orEmpty()
        if (url.isNotBlank() && token.isNotBlank()) {
            return listOf(Profile(id = "default", label = "Standard", serverUrl = url, serverToken = token))
        }
        return emptyList()
    }

    suspend fun current(): AppSettings = settingsFlow.first()

    /** Fügt ein neues Profil hinzu (oder aktualisiert ein bestehendes mit gleicher id)
     *  und macht es aktiv. Returnt die ID. */
    suspend fun upsertProfile(label: String, url: String, token: String,
                              username: String = "",
                              makeActive: Boolean = true): String {
        val cleanUrl = url.trim().trimEnd('/')
        val cleanTok = token.trim()
        val cleanUser = username.trim()
        val id = "p_" + (label.lowercase().replace(Regex("[^a-z0-9]+"), "_") + "_" +
            System.currentTimeMillis().toString(36))
        dataStore.edit { prefs ->
            val list = loadProfilesWithMigration(prefs).toMutableList()
            list.add(Profile(id = id, label = label.ifBlank { "Profil" },
                serverUrl = cleanUrl, serverToken = cleanTok, username = cleanUser))
            prefs[keyProfiles] = json.encodeToString(list)
            if (makeActive) prefs[keyActiveProfileId] = id
        }
        return id
    }

    suspend fun updateProfile(id: String, label: String? = null,
                              url: String? = null, token: String? = null,
                              username: String? = null) {
        dataStore.edit { prefs ->
            val list = loadProfilesWithMigration(prefs).map { p ->
                if (p.id != id) p else p.copy(
                    label = label ?: p.label,
                    serverUrl = (url ?: p.serverUrl).trim().trimEnd('/'),
                    serverToken = (token ?: p.serverToken).trim(),
                    username = (username ?: p.username).trim(),
                )
            }
            prefs[keyProfiles] = json.encodeToString(list)
        }
    }

    /** Aktualisiert den Session-Token des aktiven Profils (nach Login). */
    suspend fun setActiveSessionToken(token: String, username: String? = null) {
        val s = current()
        val active = s.activeProfile ?: return
        updateProfile(active.id, token = token, username = username)
    }

    suspend fun deleteProfile(id: String) {
        dataStore.edit { prefs ->
            val list = loadProfilesWithMigration(prefs).filterNot { it.id == id }
            prefs[keyProfiles] = json.encodeToString(list)
            // Falls das aktive Profil gelöscht wurde, erstes wählen
            if (prefs[keyActiveProfileId] == id) {
                prefs[keyActiveProfileId] = list.firstOrNull()?.id.orEmpty()
            }
        }
    }

    suspend fun setActiveProfile(id: String) {
        dataStore.edit { prefs ->
            val list = loadProfilesWithMigration(prefs)
            if (list.any { it.id == id }) prefs[keyActiveProfileId] = id
        }
    }

    // Editiert das AKTIVE Profil. Wenn noch keins existiert (erster Setup),
    // wird automatisch ein erstes "Standard"-Profil angelegt.
    suspend fun setServerUrl(value: String) {
        val s = current()
        val active = s.activeProfile
        if (active != null) updateProfile(active.id, url = value)
        else upsertProfile("Standard", value, "", makeActive = true)
    }

    // ----- Gedaechtnis-Schluessel -----
    // Liegt NICHT im DataStore, sondern in einer eigenen Datei, die vom
    // Android-Backup und der Geraeteuebertragung ausgeschlossen ist
    // (res/xml/data_extraction_rules.xml, backup_rules.xml). Je Profil ein Eintrag.

    private val _wissenGesetzt = MutableStateFlow(false)
    val wissenGesetzt: StateFlow<Boolean> = _wissenGesetzt

    suspend fun wissenSchluessel(): String {
        val id = current().activeProfileId
        if (id.isBlank()) return ""
        return wissenPrefs?.getString("k_$id", null).orEmpty()
    }

    /** Schluessel nur, wenn Profil UND Server-Adresse zu dem passen, fuer die er
     *  eingetragen wurde. Aendert sich die Adresse, muss er neu eingetragen werden. */
    fun wissenSchluesselFuer(profileId: String, url: okhttp3.HttpUrl): String {
        if (profileId.isBlank()) return ""
        val gespeichert = wissenPrefs?.getString("o_$profileId", null) ?: return ""
        if (gespeichert != herkunft(url)) return ""
        return wissenPrefs.getString("k_$profileId", null).orEmpty()
    }

    private fun herkunft(url: okhttp3.HttpUrl): String = "${url.scheme}://${url.host}:${url.port}"

    suspend fun refreshWissenStatus() {
        _wissenGesetzt.value = wissenSchluessel().isNotBlank()
    }

    /** Setzt den Gedaechtnis-Schluessel des aktiven Profils (leer = entfernen). */
    suspend fun setWissenSchluessel(value: String) {
        val s = current()
        val id = s.activeProfileId
        if (id.isBlank()) return
        val ziel = s.serverUrl.toHttpUrlOrNull()
        wissenPrefs?.edit()?.apply {
            if (value.isBlank() || ziel == null || !ziel.isHttps) {
                remove("k_$id"); remove("o_$id")
            } else {
                putString("k_$id", value.trim())
                putString("o_$id", herkunft(ziel))   // an diese Server-Adresse gebunden
            }
        }?.commit()
        refreshWissenStatus()
    }

    suspend fun setServerToken(value: String) {
        val s = current()
        val active = s.activeProfile
        if (active != null) updateProfile(active.id, token = value)
        else upsertProfile("Standard", "", value, makeActive = true)
    }

    suspend fun setThemeMode(mode: ThemeMode) {
        dataStore.edit { it[keyThemeMode] = mode.name }
        localChanged("theme")
    }

    suspend fun setPaletteIdLight(value: String) {
        dataStore.edit { it[keyPaletteIdLight] = value }
        localChanged("paletteLight")
    }

    suspend fun setPaletteIdDark(value: String) {
        dataStore.edit { it[keyPaletteIdDark] = value }
        localChanged("paletteDark")
    }

    suspend fun setTtsVoice(value: String) {
        dataStore.edit { it[keyTtsVoice] = value }
        localChanged("ttsVoice")
    }

    suspend fun setTtsAutoSpeak(value: Boolean) {
        dataStore.edit { it[keyTtsAutoSpeak] = value.toString() }
        localChanged("autoSpeak")
    }

    suspend fun setTtsSpeed(value: Float) {
        dataStore.edit { it[keyTtsSpeed] = value.coerceIn(0.25f, 2.0f) }
        localChanged("ttsSpeed")
    }

    suspend fun setEffort(value: String) {
        dataStore.edit { it[keyEffort] = value }
        localChanged("effort")
        localEntriesChanged("effortByFamily", mapOf(ChatModelFamilies.CLAUDE to JsonPrimitive(value)))
    }

    suspend fun setSystemPromptMode(mode: SystemPromptMode) {
        dataStore.edit { it[keySystemPromptMode] = mode.name }
        localChanged("spMode")
    }

    suspend fun setCustomSystemPrompt(value: String) {
        dataStore.edit { it[keyCustomSystemPrompt] = value }
        localChanged("spCustom")
    }

    /** Merkt sich die zuletzt offene Chat-cid, damit die App nach Process Death
     *  (Speicher knapp + Hintergrund-Kill) wieder im richtigen Chat aufmacht
     *  statt einen frischen anzulegen. */
    suspend fun setLastChatCid(cid: String?) {
        dataStore.edit { prefs ->
            if (cid.isNullOrBlank()) prefs.remove(keyLastChatCid)
            else prefs[keyLastChatCid] = cid
        }
    }

    suspend fun getLastChatCid(): String? {
        return dataStore.data.first()[keyLastChatCid]?.takeIf { it.isNotBlank() }
    }

    // ---------- Per-Chat-Override: TTS Auto-Speak ----------
    // Bewusst client-only (kein Server-Roundtrip): die Einstellung ist
    // app-spezifisch (Auto-Vorlesen beim Erhalt einer Antwort) und macht auf
    // anderen Geräten/Sessions sowieso wenig Sinn.

    private fun parseAutoSpeakMap(raw: String?): Map<String, Boolean> {
        if (raw.isNullOrBlank()) return emptyMap()
        return runCatching {
            json.decodeFromString<Map<String, Boolean>>(raw)
        }.getOrDefault(emptyMap())
    }

    /** Returnt: true = Auto-Speak für diesen Chat AN, false = AUS,
     *  null = kein Override (globaler Default greift). */
    suspend fun getAutoSpeakOverride(cid: String): Boolean? {
        val prefs = dataStore.data.first()
        return parseAutoSpeakMap(prefs[keyTtsAutoSpeakPerChat])[cid]
    }

    /** Setzt oder löscht (`override=null`) den Override für einen Chat. */
    suspend fun setAutoSpeakOverride(cid: String, override: Boolean?) {
        dataStore.edit { prefs ->
            val map = parseAutoSpeakMap(prefs[keyTtsAutoSpeakPerChat]).toMutableMap()
            if (override == null) map.remove(cid) else map[cid] = override
            if (map.isEmpty()) prefs.remove(keyTtsAutoSpeakPerChat)
            else prefs[keyTtsAutoSpeakPerChat] = json.encodeToString(map)
        }
        localEntriesChanged(
            "autoSpeakByChat",
            mapOf(cid to if (override == null) JsonNull else JsonPrimitive(override)),
        )
    }

    // ---------- Settings Export / Import (App-Anteil) ----------

    /** Erzeugt ein Snapshot aller App-lokalen Settings für den Export.
     *  Profile (URL/Token/Username) sind bewusst NICHT enthalten — die
     *  bleiben pro Gerät. */
    suspend fun snapshotForExport(): AppSettingsExportDto {
        val prefs = dataStore.data.first()
        return AppSettingsExportDto(
            themeMode = prefs[keyThemeMode] ?: "SYSTEM",
            // `paletteId` ist das alte, gemeinsame Feld. Es wird weiter
            // mitgeschrieben, damit ein aelterer App-Stand den Export lesen kann.
            paletteId = resolvePalette(prefs, keyPaletteIdDark, DEFAULT_PALETTE_ID_DARK),
            paletteIdLight = resolvePalette(prefs, keyPaletteIdLight, DEFAULT_PALETTE_ID_LIGHT),
            paletteIdDark = resolvePalette(prefs, keyPaletteIdDark, DEFAULT_PALETTE_ID_DARK),
            ttsVoice = prefs[keyTtsVoice].orEmpty().ifBlank { "edge-de-DE-KatjaNeural" },
            ttsAutoSpeak = (prefs[keyTtsAutoSpeak] ?: "false").toBooleanStrictOrNull() ?: false,
            ttsSpeed = (prefs[keyTtsSpeed] ?: 1.0f).coerceIn(0.25f, 2.0f),
            effort = prefs[keyEffort]?.takeIf { it.isNotBlank() } ?: DEFAULT_EFFORT,
            systemPromptMode = (prefs[keySystemPromptMode] ?: SystemPromptMode.STANDARD.name),
            customSystemPrompt = prefs[keyCustomSystemPrompt].orEmpty(),
            ttsAutoSpeakPerChat = parseAutoSpeakMap(prefs[keyTtsAutoSpeakPerChat]),
            collapseLongUserMessages =
                (prefs[keyCollapseLongUserMessages] ?: "true").toBooleanStrictOrNull() ?: true,
            chatModelKey = prefs[keyChatModelKey].orEmpty(),
            effortByFamily = parseStringMap(prefs[keyEffortByFamily]),
            defaultModelByFamily = parseStringMap(prefs[keyDefaultModelByFamily]),
            imageDefaultSize = prefs[keyImageDefaultSize]?.takeIf { it.isNotBlank() } ?: "2K",
            imageDefaultAspect = prefs[keyImageDefaultAspect]?.takeIf { it.isNotBlank() } ?: "1:1",
        )
    }

    /** Wendet ein importiertes Snapshot auf die App-lokalen Settings an.
     *  Profile/Token bleiben unangetastet. */
    suspend fun applyImport(s: AppSettingsExportDto) {
        dataStore.edit { prefs ->
            prefs[keyThemeMode] = s.themeMode
            // Ein Export aus einer aelteren Version kennt nur `paletteId`.
            // Dann gilt der eine Wert fuer beide Modi.
            prefs[keyPaletteIdLight] = s.paletteIdLight.ifBlank { s.paletteId }
            prefs[keyPaletteIdDark] = s.paletteIdDark.ifBlank { s.paletteId }
            prefs[keyTtsVoice] = s.ttsVoice
            prefs[keyTtsAutoSpeak] = s.ttsAutoSpeak.toString()
            prefs[keyTtsSpeed] = s.ttsSpeed.coerceIn(0.25f, 2.0f)
            prefs[keyEffort] = s.effort
            prefs[keySystemPromptMode] = s.systemPromptMode
            prefs[keyCustomSystemPrompt] = s.customSystemPrompt
            prefs[keyCollapseLongUserMessages] = s.collapseLongUserMessages.toString()
            prefs[keyChatModelKey] = s.chatModelKey
            prefs[keyImageDefaultSize] = s.imageDefaultSize
            prefs[keyImageDefaultAspect] = s.imageDefaultAspect
            if (s.effortByFamily.isEmpty()) prefs.remove(keyEffortByFamily)
            else prefs[keyEffortByFamily] = json.encodeToString(s.effortByFamily)
            if (s.defaultModelByFamily.isEmpty()) prefs.remove(keyDefaultModelByFamily)
            else prefs[keyDefaultModelByFamily] = json.encodeToString(s.defaultModelByFamily)
            if (s.ttsAutoSpeakPerChat.isEmpty()) {
                prefs.remove(keyTtsAutoSpeakPerChat)
            } else {
                prefs[keyTtsAutoSpeakPerChat] = json.encodeToString(s.ttsAutoSpeakPerChat)
            }
        }
        localChanged(*SHARED_UI_KEYS.toTypedArray())
    }

    // ---------- Abgleich mit dem Server (GET/PUT /ui-settings) ----------
    //
    // App und Web-UI teilen ihre Oberflaechen-Einstellungen ueber den Server,
    // mit denselben Schluesseln wie die Web-UI. Lokal bleibt alles im
    // DataStore: die App startet auch offline mit dem letzten Stand.
    // Geraetebezogenes bleibt draussen (Server-Profile, Fingerabdruck,
    // Bilder-Verlauf, Sprache).

    /** Wird bei jeder lokalen Aenderung mit dem aktiven Profil und den
     *  geaenderten Server-Werten gerufen; [SettingsSync] schickt sie hoch.
     *  Ein [JsonObject] heisst: nur diese Eintraege der Liste aendern. */
    @Volatile
    var onLocalChange: ((profileId: String, changes: Map<String, JsonElement>) -> Unit)? = null

    /** Einzelne Eintraege einer Liste (pro Familie bzw. Chat) haben sich
     *  geaendert; `JsonNull` heisst entfernt. Nur sie gehen an den Server, damit
     *  ein Geraet mit altem Stand die uebrigen Eintraege nicht zuruecksetzt. */
    private suspend fun localEntriesChanged(key: String, entries: Map<String, JsonElement>) {
        val listener = onLocalChange ?: return
        listener(current().activeProfileId, mapOf(key to JsonObject(entries)))
    }

    private suspend fun localChanged(vararg remoteKeys: String) {
        val listener = onLocalChange ?: return
        val prefs = dataStore.data.first()
        val values = sharedValues(prefs)
        // Ein geleerter Wert steht lokal gar nicht mehr da; der Server muss
        // ihn trotzdem erfahren, sonst kaeme der alte Wert beim Abgleich zurueck.
        val changed = remoteKeys.associateWith { key -> values[key] ?: CLEARED_VALUES[key] }
            .filterValues { it != null }
            .mapValues { JsonPrimitive(it.value!!) as JsonElement }
        if (changed.isNotEmpty()) listener(current().activeProfileId, changed)
    }

    private companion object {
        val CLEARED_VALUES = mapOf(
            "chatModel" to "",
            "autoSpeakByChat" to "{}",
            "defaultModelByFamily" to "{}",
        )
    }

    /** Die geteilten Einstellungen als Server-Werte, nur was lokal gesetzt ist. */
    private fun sharedValues(prefs: Preferences): Map<String, String> = buildMap {
        prefs[keyThemeMode]?.let { put("theme", it.lowercase()) }
        (prefs[keyPaletteIdLight] ?: prefs[keyPaletteId])?.takeIf { it.isNotBlank() }
            ?.let { put("paletteLight", it) }
        (prefs[keyPaletteIdDark] ?: prefs[keyPaletteId])?.takeIf { it.isNotBlank() }
            ?.let { put("paletteDark", it) }
        prefs[keyTtsVoice]?.takeIf { it.isNotBlank() }?.let { put("ttsVoice", it) }
        prefs[keyTtsSpeed]?.let { put("ttsSpeed", it.toString()) }
        prefs[keyTtsAutoSpeak]?.let { put("autoSpeak", it) }
        prefs[keyTtsAutoSpeakPerChat]?.let { put("autoSpeakByChat", it) }
        prefs[keyCollapseLongUserMessages]?.let { put("collapseUserMsgs", it) }
        prefs[keyAutoSendEnabled]?.let { put("autoSend", it) }
        prefs[keyAutoSendSilenceMs]?.let { put("autoSendSilenceMs", it) }
        prefs[keySystemPromptMode]?.let { put("spMode", it) }
        prefs[keyCustomSystemPrompt]?.let { put("spCustom", it) }
        prefs[keyChatModelKey]?.let { put("chatModel", it) }
        prefs[keyDefaultModelByFamily]?.let { put("defaultModelByFamily", it) }
        val claudeEffort = prefs[keyEffort]?.takeIf { it.isNotBlank() }
        claudeEffort?.let { put("effort", it) }
        val byFamily = parseStringMap(prefs[keyEffortByFamily]).toMutableMap()
        // Die Web-UI fuehrt Claude in derselben Liste, die App im alten Feld.
        if (claudeEffort != null) byFamily[ChatModelFamilies.CLAUDE] = claudeEffort
        if (byFamily.isNotEmpty()) put("effortByFamily", json.encodeToString(byFamily.toMap()))
    }

    /** Uebernimmt Werte vom Server. Unbrauchbare Werte werden uebersprungen,
     *  ein kaputter Eintrag darf die anderen nicht blockieren. */
    private fun applyShared(prefs: MutablePreferences, remote: Map<String, String>) {
        remote["theme"]?.uppercase()?.takeIf { v -> ThemeMode.entries.any { it.name == v } }
            ?.let { prefs[keyThemeMode] = it }
        remote["paletteLight"]?.takeIf { it.isNotBlank() }?.let { prefs[keyPaletteIdLight] = it }
        remote["paletteDark"]?.takeIf { it.isNotBlank() }?.let { prefs[keyPaletteIdDark] = it }
        remote["ttsVoice"]?.takeIf { it.isNotBlank() }?.let { prefs[keyTtsVoice] = it }
        remote["ttsSpeed"]?.toFloatOrNull()?.let { prefs[keyTtsSpeed] = it.coerceIn(0.25f, 2.0f) }
        remote["autoSpeak"]?.toBooleanStrictOrNull()?.let { prefs[keyTtsAutoSpeak] = it.toString() }
        remote["autoSpeakByChat"]?.let { raw ->
            runCatching { json.decodeFromString<Map<String, Boolean>>(raw) }.getOrNull()
                ?.let { prefs[keyTtsAutoSpeakPerChat] = json.encodeToString(it) }
        }
        remote["collapseUserMsgs"]?.toBooleanStrictOrNull()
            ?.let { prefs[keyCollapseLongUserMessages] = it.toString() }
        remote["autoSend"]?.toBooleanStrictOrNull()?.let { prefs[keyAutoSendEnabled] = it.toString() }
        remote["autoSendSilenceMs"]?.toLongOrNull()
            ?.let { prefs[keyAutoSendSilenceMs] = it.coerceIn(500L, 10_000L).toString() }
        remote["spMode"]?.takeIf { v -> SystemPromptMode.entries.any { it.name == v } }
            ?.let { prefs[keySystemPromptMode] = it }
        remote["spCustom"]?.let { prefs[keyCustomSystemPrompt] = it }
        remote["chatModel"]?.let { prefs[keyChatModelKey] = it }
        remote["defaultModelByFamily"]?.let { raw ->
            runCatching { json.decodeFromString<Map<String, String>>(raw) }.getOrNull()
                ?.let { prefs[keyDefaultModelByFamily] = json.encodeToString(it) }
        }
        val byFamily = remote["effortByFamily"]?.let { raw ->
            runCatching { json.decodeFromString<Map<String, String>>(raw) }.getOrNull()
        }
        if (byFamily != null) prefs[keyEffortByFamily] = json.encodeToString(byFamily)
        // Claude: die Liste ist genauer als das alte Einzelfeld, denn die
        // Web-UI schreibt dort die zuletzt gewaehlte Stufe JEDER Familie hinein.
        (byFamily?.get(ChatModelFamilies.CLAUDE) ?: remote["effort"])
            ?.takeIf { it.isNotBlank() }?.let { prefs[keyEffort] = it }
    }

    /**
     * Gleicht mit dem Stand vom Server ab und liefert, was die App ihrerseits
     * hochladen soll.
     *
     * Beim ersten Abgleich eines Profils gewinnt, was die App schon hat: sonst
     * wuerden die Werte eines kaum benutzten Browsers die eingerichtete App
     * ueberschreiben. Danach gilt der Server, die App laedt nur hoch, was dort
     * noch fehlt.
     */
    suspend fun syncWithRemote(
        profileId: String,
        remote: Map<String, String>,
        protectedKeys: Set<String> = emptySet(),
    ): Map<String, String>? {
        var upload: Map<String, String>? = null
        dataStore.edit { prefs ->
            // Kein Abgleich fuer ein Profil, das inzwischen nicht mehr aktiv ist.
            if (prefs[keyActiveProfileId] != null && prefs[keyActiveProfileId] != profileId) return@edit
            val local = sharedValues(prefs)
            val firstSync = profileId !in (prefs[keyUiSyncedProfiles] ?: emptySet())
            // Was hier gerade geaendert und noch nicht bestaetigt ist, bleibt.
            val fresh = remote.filterKeys { it !in protectedKeys }
            val take = if (firstSync) fresh.filterKeys { it !in local } else fresh
            applyShared(prefs, take)
            upload = if (firstSync) local.filter { (k, v) -> remote[k] != v }
                     else local.filterKeys { it !in remote }
        }
        return upload
    }

    /** Erstabgleich fuer dieses Profil abgeschlossen (Upload bestaetigt). */
    suspend fun markUiSynced(profileId: String) {
        dataStore.edit { prefs ->
            prefs[keyUiSyncedProfiles] = (prefs[keyUiSyncedProfiles] ?: emptySet()) + profileId
        }
    }
}

/** Schluessel, die App und Web-UI ueber den Server teilen (wie
 *  `UI_SETTING_KEYS` in server.py, ohne die reinen Web-Schluessel). */
val SHARED_UI_KEYS: List<String> = listOf(
    "theme", "paletteLight", "paletteDark", "ttsVoice", "ttsSpeed", "autoSpeak",
    "autoSpeakByChat", "collapseUserMsgs", "autoSend", "autoSendSilenceMs",
    "spMode", "spCustom", "chatModel", "defaultModelByFamily", "effort", "effortByFamily",
)
