package de.smartzone.pocketclaude.data

/**
 * Wählbare Claude-Modelle für den globalen Standard-Modell-Picker (Settings)
 * und den Modell-Override pro Gem. Die `id` ist der String, den der Server an
 * `ClaudeAgentOptions.model` reicht (Claude-CLI/Agent-SDK akzeptiert ihn direkt).
 *
 * Labels sind Produktnamen (nicht übersetzbar). Der „Automatisch"- bzw.
 * „Globaler Standard / Chat-Standard"-Eintrag wird in der UI per String-Resource
 * vorangestellt (Wert dort = "" bzw. null).
 */
object ClaudeModels {
    data class Option(val id: String, val label: String)

    /**
     * Nur Offline-Fallback: online kommt die Liste samt Generation im Namen
     * („Opus 5.5") vom Server (`GET /chat/models`). Schluessel sind Familien,
     * keine Versionsnummern, damit ein gespeichertes `opus` immer die neueste
     * Generation bekommt (Modell-Register im Projekt AI Worker).
     */
    val all: List<Option> = listOf(
        Option("opus", "Opus"),
        Option("fable", "Fable"),
        Option("sonnet", "Sonnet"),
        Option("haiku", "Haiku"),
    )

    /**
     * Alte gespeicherte IDs: der Server hebt sie auf die neueste Generation an.
     * Hier stehen sie nur, damit die Titelzeile einen lesbaren Namen zeigt.
     */
    private val legacy: List<Option> = listOf(
        Option("claude-opus-5", "Opus"),  // ki-modelle: ok (alte gespeicherte IDs)
        Option("claude-fable-5", "Fable"),  // ki-modelle: ok (alte gespeicherte IDs)
        Option("claude-sonnet-5", "Sonnet"),  // ki-modelle: ok (alte gespeicherte IDs)
        Option("claude-haiku-4-5", "Haiku"),  // ki-modelle: ok (alte gespeicherte IDs)
        Option("claude-opus-4-8", "Opus"),  // ki-modelle: ok (alte gespeicherte IDs)
        Option("claude-opus-4-7", "Opus"),  // ki-modelle: ok (alte gespeicherte IDs)
        Option("claude-opus-4-6", "Opus"),  // ki-modelle: ok (alte gespeicherte IDs)
        Option("claude-sonnet-4-6", "Sonnet"),  // ki-modelle: ok (alte gespeicherte IDs)
    )

    /** Anzeige-Label für eine Modell-ID; unbekannte IDs werden 1:1 gezeigt. */
    fun labelFor(id: String?): String? =
        id?.takeIf { it.isNotBlank() }?.let { mid ->
            (all + legacy).firstOrNull { it.id == mid }?.label ?: mid
        }
}

/** Effort-Stufen (CLAUDE_CODE_EFFORT_LEVEL). `off` = keine Steuerung. */
val EFFORT_LEVELS: List<String> = listOf("off", "low", "medium", "high", "xhigh", "max")

/** Modell-Familien. Gleiche Werte wie serverseitig in `gateways.py`. */
object ChatModelFamilies {
    const val CLAUDE = "claude"
    const val GEMINI = "gemini"
    const val GPT = "gpt"
    const val OTHER = "other"

    /** Reihenfolge im Picker: Claude zuerst, es bleibt das primaere Modell. */
    val order: List<String> = listOf(CLAUDE, GEMINI, GPT, OTHER)
}

/**
 * Ein waehlbares Chat-Modell, wie es `GET /chat/models` liefert. Claude-Modelle
 * haben als `key` die reine Modell-ID, Zusatz-Modelle den Gateway-Key
 * („gw:<gateway>:<modell>").
 */
data class ChatModelOption(
    val key: String,
    val family: String = ChatModelFamilies.OTHER,
    val label: String,
    val efforts: List<String> = emptyList(),
    val defaultEffort: String = DEFAULT_EFFORT,
    val supportsVision: Boolean = true,
    val gatewayLabel: String = "",
)

/**
 * Alle Denktiefen, die irgendein Modell kennen kann, aufsteigend sortiert.
 * `off` gibt es nur bei Claude, `minimal` und `ultra` nur bei Zusatz-Modellen.
 * Welche Stufen wirklich waehlbar sind, sagt das jeweilige Modell.
 */
val EFFORT_LEVELS_ALL: List<String> =
    listOf("off", "minimal", "low", "medium", "high", "xhigh", "max", "ultra")

/**
 * Vorauswahl der Denktiefe fuer eine Familie. Bewusst fuer alle drei „hoch":
 * Claude, Gemini und GPT sollen ohne Zutun gleich gut denken.
 */
@Suppress("UNUSED_PARAMETER")
fun defaultEffortForFamily(family: String): String = DEFAULT_EFFORT

/**
 * Klemmt eine Denktiefe auf das, was ein Modell tatsaechlich kann: erst eine
 * Stufe tiefer suchen, dann hoeher. Gleiche Semantik wie `clamp_effort` in
 * `gateways.py`, damit die App genau das anzeigt, was der Server auch benutzt.
 *
 * Das ist noetig, weil die Denktiefe pro FAMILIE gemerkt wird, die verfuegbaren
 * Stufen aber am einzelnen MODELL haengen: Gemini 3.7 Flash gibt es im Gateway
 * zum Beispiel nur in „hoch". Ohne das Klemmen zeigte die App eine Stufe an,
 * die der Server still verworfen hat.
 */
fun clampEffort(wanted: String, available: List<String>): String {
    if (available.isEmpty()) return ""
    if (wanted in available) return wanted
    // Die Skala ist bewusst die OHNE „aus", identisch zu EFFORT_ORDER im Server.
    // „aus" ist keine Denktiefe, sondern deren Abwesenheit, und kennt nur Claude.
    // Wuerde man es als unterste Stufe mitzaehlen, landete ein Claude-Chat mit
    // „aus" beim Wechsel auf ein Zusatz-Modell auf der niedrigsten Stufe,
    // waehrend der Server von „hoch" aus sucht und eine andere Stufe waehlt.
    val scale = EFFORT_LEVELS_ALL.filter { it != "off" }
    val idx = scale.indexOf(wanted).takeIf { it >= 0 } ?: scale.indexOf(DEFAULT_EFFORT)
    for (i in idx - 1 downTo 0) if (scale[i] in available) return scale[i]
    for (i in idx + 1 until scale.size) if (scale[i] in available) return scale[i]
    return available.first()
}

/**
 * Kurzform eines Modell-Labels fuer die Titelzeile, hoechstens zwei Woerter.
 * Aus „Gemini 3.7 Flash" wird „Gemini 3.7", aus „Opus 4.8" bleibt „Opus 4.8".
 */
fun shortModelLabel(label: String): String {
    val words = label.trim().split(Regex("\\s+")).filter { it.isNotBlank() }
    return when {
        words.isEmpty() -> ""
        words.size <= 2 -> words.joinToString(" ")
        else -> "${words[0]} ${words[1]}"
    }
}

/**
 * Familie eines Modell-Keys, ohne den Server fragen zu muessen. Wird gebraucht,
 * um beim Senden die richtige gemerkte Denktiefe zu waehlen, auch wenn die
 * Modell-Liste gerade nicht geladen ist.
 */
fun familyForKey(key: String?): String {
    val k = (key ?: "").trim()
    if (k.isEmpty() || k.startsWith("claude")) return ChatModelFamilies.CLAUDE
    if (!k.startsWith("gw:")) return ChatModelFamilies.CLAUDE
    val modelId = k.substringAfter(':', "").substringAfter(':', "")
    return when {
        modelId.contains("gemini") -> ChatModelFamilies.GEMINI
        modelId.startsWith("gpt") || modelId.startsWith("codex") ||
            modelId.contains("gpt-") -> ChatModelFamilies.GPT
        else -> ChatModelFamilies.OTHER
    }
}
