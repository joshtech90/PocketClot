package de.smartzone.pocketclaude.ui.chat

import android.util.Log
import de.smartzone.pocketclaude.data.ApiException
import de.smartzone.pocketclaude.data.AudioController
import de.smartzone.pocketclaude.data.ChatRepository
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.launch

/**
 * Teilt eine Antwort, waehrend sie noch geschrieben wird, in vorlesbare Stuecke
 * (Joscha 27.10.2026). Das erste Stueck endet nach dem ersten Satz, damit das
 * Vorlesen schnell beginnt; danach geht es absatzweise weiter, so entstehen
 * wenige, grosse Stuecke. Claude schreibt rund zehnmal schneller, als
 * vorgelesen wird, das Vorlesen holt den Text also nicht ein.
 *
 * Nie geschnitten wird in einem offenen Codeblock: der Server wirft Code beim
 * Vorlesen ohnehin weg, er muss dafuer aber als Ganzes im Stueck liegen.
 */
internal object SpeechChunker {
    /** Das erste Stueck soll nicht nur aus "Ja." bestehen. */
    const val FIRST_MIN_CHARS = 40
    /** Spaetere Stuecke: erst ab dieser Laenge an einem Absatz schneiden. */
    const val NEXT_MIN_CHARS = 200
    /** Absatz ohne Ende in Sicht: dann am letzten Satzende schneiden. */
    const val NEXT_SENTENCE_FALLBACK_CHARS = 700

    // Kuerzel mit Punkt, die kein Satzende sind (Kleinschreibung verglichen).
    private val ABBREVIATIONS = setOf(
        "ca", "bzw", "usw", "etc", "dr", "nr", "vgl", "ggf", "inkl", "evtl", "max",
        "min", "st", "mio", "mrd", "tel", "bspw", "sog", "zb", "z.b", "prof", "abs",
        "e.g", "i.e", "vs", "mr", "mrs", "ms", "no", "u.a", "d.h", "z.t", "o.a", "s.o",
        "s.u", "u.u", "i.d.r",
    )

    /**
     * Ende des naechsten Stuecks ab `from` (exklusiv) oder -1, solange keins
     * fertig ist. `blockEnd`: ein Textblock ist zu Ende (etwa der kurze Satz
     * vor einer Websuche), dann geht alles bisher Geschriebene raus.
     * `final`: die Antwort ist fertig, der ganze Rest ist ein Stueck.
     */
    fun nextCut(text: String, from: Int, first: Boolean, blockEnd: Boolean = false, final: Boolean = false): Int {
        if (from >= text.length) return -1
        if (final) return text.length
        // Den Quellen-Block am Ende nie zerschneiden: der Server wirft ihn nur
        // als Ganzes weg, ein abgetrennter Rest wuerde vorgelesen. Er kommt
        // deshalb erst mit dem letzten Stueck.
        val usable = SOURCES_BLOCK.find(text)?.range?.first ?: text.length
        if (from >= usable) return -1
        val head = text.substring(0, usable)
        if (blockEnd) return if (insideCodeFence(head, head.length)) -1 else head.length
        return if (first) firstCut(head, from) else nextParagraphCut(head, from)
    }

    private val SOURCES_BLOCK = Regex("""(?:^|\n)[ \t]*\*\*Quellen\*\*""")

    private fun firstCut(text: String, from: Int): Int {
        var i = from
        while (i < text.length) {
            val end = boundaryAt(text, i)
            if (end > 0 && end - from >= FIRST_MIN_CHARS && !insideCodeFence(text, end)) return end
            i++
        }
        return -1
    }

    private fun nextParagraphCut(text: String, from: Int): Int {
        // Am LETZTEN Absatz schneiden, der weit genug weg ist: grosse Stuecke.
        var idx = text.lastIndexOf("\n\n")
        while (idx >= from) {
            val end = idx + 2
            if (end - from < NEXT_MIN_CHARS) break
            if (!insideCodeFence(text, end)) return end
            idx = text.lastIndexOf("\n\n", idx - 1)
        }
        if (text.length - from < NEXT_SENTENCE_FALLBACK_CHARS) return -1
        var i = text.length - 1
        while (i > from + NEXT_MIN_CHARS) {
            val end = boundaryAt(text, i)
            if (end > 0 && !insideCodeFence(text, end)) return end
            i--
        }
        return -1
    }

    /**
     * Satzende an Position i: Satzzeichen, dann Leerraum, dann etwas, das
     * einen neuen Satz beginnt. Ein Zeilenumbruch nach Text zaehlt auch
     * (Ueberschrift, "Die Optionen:"). Liefert das Ende inklusive Leerraum
     * oder -1. Am Textende unbekannt, deshalb -1: erst der naechste Buchstabe
     * zeigt, ob es "z. B." war.
     */
    private fun boundaryAt(text: String, i: Int): Int {
        val c = text[i]
        if (c == '\n') {
            if (i + 1 >= text.length) return -1
            val lineStart = text.lastIndexOf('\n', i - 1) + 1
            return if (text.substring(lineStart, i).any { it.isLetterOrDigit() }) i + 1 else -1
        }
        if (c != '.' && c != '!' && c != '?') return -1
        if (i + 2 >= text.length || !text[i + 1].isWhitespace()) return -1
        if (c == '.') {
            var w = i - 1
            while (w >= 0 && (text[w].isLetterOrDigit() || text[w] == '.')) w--
            val word = text.substring(w + 1, i)
            if (word.isEmpty()) return -1
            // "z." "B." und Aufzaehlungen "1." sind kein Satzende.
            if (word.length == 1 || word.all { it.isDigit() }) return -1
            if (word.lowercase() in ABBREVIATIONS) return -1
        }
        var j = i + 1
        while (j < text.length && text[j] == ' ') j++
        if (j >= text.length) return -1
        // Kleinbuchstabe danach: kein neuer Satz ("ca. drei", "z. B. so").
        val n = text[j]
        return if (!n.isLetter() || n.isUpperCase()) j else -1
    }

    private fun insideCodeFence(text: String, end: Int): Boolean {
        var count = 0
        var idx = text.indexOf("```")
        while (idx in 0 until end) {
            count++
            idx = text.indexOf("```", idx + 3)
        }
        return count % 2 == 1
    }
}

/**
 * Liest eine Antwort schon vor, waehrend sie noch geschrieben wird
 * (Sprachgespraech, seit 27.10.2026). Fertige Stuecke gehen der Reihe nach an
 * den Server und haengen sich an die Warteschlange des Players. Ein frueh
 * fertiges Stueck (etwa "Ich schaue kurz nach." vor einer Websuche) wird
 * vorgelesen, und wenn danach weiterer Text kommt, geht es mit ihm weiter.
 */
internal class LiveSpeaker(
    private val scope: CoroutineScope,
    private val repo: ChatRepository,
    private val audio: AudioController,
) {
    private enum class Status { Idle, Active, Cancelled, Unsupported }

    @Volatile private var status = Status.Idle
    private var consumed = 0
    private var cuts = 0
    @Volatile private var enqueued = 0
    private var queue: Channel<String>? = null
    private var worker: Job? = null

    /** Neue Antwort: ab jetzt mitlesen. */
    fun begin(voice: String?, serverRate: Float, playerRate: Float) {
        worker?.cancel()
        queue?.close()
        status = Status.Active
        consumed = 0
        cuts = 0
        enqueued = 0
        val ch = Channel<String>(Channel.UNLIMITED)
        queue = ch
        worker = scope.launch {
            // Scheitert ein Stueck zweimal am Netz, geht es nicht verloren,
            // sondern vor das naechste. Sonst fehlte mitten im Vorlesen ein
            // Absatz, ohne dass es jemand merkt.
            var carry = ""
            for (text in ch) {
                if (status != Status.Active) continue
                val piece = carry + text
                carry = if (sendOne(piece, voice, serverRate, playerRate)) "" else piece
                if (carry.length > MAX_SEGMENT_CHARS) {
                    Log.w("PC_TTS", "live segment dropped after repeated failures (${carry.length} chars)")
                    carry = ""
                }
            }
            if (carry.isNotEmpty() && status == Status.Active) {
                sendOne(carry, voice, serverRate, playerRate)
            }
        }
    }

    /** Der bisher geschriebene Text der Antwort (waechst nur). */
    fun onText(text: String, blockEnd: Boolean = false) {
        if (status != Status.Active) return
        while (true) {
            val end = SpeechChunker.nextCut(text, consumed, first = cuts == 0, blockEnd = blockEnd)
            if (end <= consumed) return
            push(text.substring(consumed, end))
            consumed = end
        }
    }

    /**
     * Antwort fertig. true: das Vorlesen ist erledigt bzw. bewusst
     * abgebrochen, nichts weiter tun. false: wie bisher die ganze Nachricht
     * vorlesen (Server zu alt oder kein Stueck ging durch).
     */
    suspend fun finish(text: String): Boolean {
        when (status) {
            Status.Idle -> return false
            Status.Cancelled -> { status = Status.Idle; return true }
            Status.Active -> {
                if (consumed < text.length) push(text.substring(consumed))
                consumed = text.length
            }
            Status.Unsupported -> Unit
        }
        queue?.close()
        worker?.join()
        val took = enqueued > 0 || status == Status.Cancelled
        status = Status.Idle
        return took
    }

    /** Vorlesen abgebrochen oder Sprachgespraech beendet: nichts mehr
     *  nachschieben. true, wenn gerade mitgelesen wurde. */
    fun cancel(): Boolean {
        val wasActive = status == Status.Active
        if (wasActive) status = Status.Cancelled
        queue?.close()
        worker?.cancel()
        return wasActive
    }

    /** Antwort abgebrochen oder Fehler: was schon im Player liegt, laeuft
     *  zu Ende, Neues kommt nicht dazu. */
    fun end() {
        if (status == Status.Active) status = Status.Idle
        queue?.close()
    }

    private fun push(text: String) {
        cuts++
        // Der Server nimmt hoechstens 20.000 Zeichen je Stueck; ein riesiger
        // Rest am Ende wird deshalb an Absaetzen bzw. Leerzeichen geteilt.
        var rest = text
        while (rest.length > MAX_SEGMENT_CHARS) {
            val window = rest.substring(0, MAX_SEGMENT_CHARS)
            val at = window.lastIndexOf("\n\n").takeIf { it > 0 }?.plus(2)
                ?: window.lastIndexOf(' ').takeIf { it > 0 }?.plus(1)
                ?: MAX_SEGMENT_CHARS
            queue?.trySend(rest.substring(0, at))
            rest = rest.substring(at)
        }
        if (rest.isNotEmpty()) queue?.trySend(rest)
    }

    /** true: erledigt (eingereiht, nichts Sprechbares oder Server zu alt).
     *  false: zweimal am Netz gescheitert, spaeter nochmal versuchen. */
    private suspend fun sendOne(text: String, voice: String?, serverRate: Float, playerRate: Float): Boolean {
        repeat(2) { attempt ->
            try {
                val id = repo.createLiveTts(text, voice, serverRate)
                val url = repo.liveTtsUrl(id)
                if (status != Status.Active) return true
                audio.enqueueLive(url, playerRate, first = enqueued == 0)
                enqueued++
                Log.d("PC_TTS", "live segment ${text.length} chars queued (#$enqueued)")
                return true
            } catch (e: CancellationException) {
                throw e
            } catch (e: ApiException) {
                when (e.code) {
                    // Nichts Sprechbares darin (nur Code, nur Quellen).
                    400 -> return true
                    // Server kennt das noch nicht: am Ende klassisch vorlesen.
                    404, 405 -> {
                        if (enqueued == 0) status = Status.Unsupported
                        Log.i("PC_TTS", "live TTS not supported by server (${e.code})")
                        return true
                    }
                }
                Log.w("PC_TTS", "live segment failed (${e.code}), attempt ${attempt + 1}")
            } catch (e: Exception) {
                Log.w("PC_TTS", "live segment failed: ${e::class.java.simpleName}, attempt ${attempt + 1}")
            }
        }
        return false
    }

    private companion object {
        /** Unter der Server-Grenze von 20.000 Zeichen je Stueck. */
        const val MAX_SEGMENT_CHARS = 12_000
    }
}
