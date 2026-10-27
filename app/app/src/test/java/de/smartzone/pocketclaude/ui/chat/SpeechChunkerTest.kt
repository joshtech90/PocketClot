package de.smartzone.pocketclaude.ui.chat

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

/**
 * Vorlesen waehrend der Antwort: der Text kommt in kleinen Happen, die Stuecke
 * muessen am Ende genau den ganzen Text ergeben, frueh mit dem ersten Satz
 * beginnen und duerfen weder Kuerzel noch Codebloecke zerschneiden.
 */
class SpeechChunkerTest {

    /** Spielt das Streamen nach wie LiveSpeaker.onText/finish. Ein `|` im
     *  Text markiert das Ende eines Textblocks (etwa vor einer Websuche). */
    private fun stream(marked: String, step: Int = 7): List<String> {
        val blockEnds = mutableSetOf<Int>()
        val text = StringBuilder()
        for (ch in marked) if (ch == '|') blockEnds += text.length else text.append(ch)
        val full = text.toString()
        val chunks = mutableListOf<String>()
        var consumed = 0
        fun drain(sofar: String, blockEnd: Boolean) {
            while (true) {
                val end = SpeechChunker.nextCut(sofar, consumed, first = chunks.isEmpty(), blockEnd = blockEnd)
                if (end <= consumed) return
                chunks += sofar.substring(consumed, end)
                consumed = end
            }
        }
        var pos = 0
        while (pos < full.length) {
            val nextBlock = blockEnds.filter { it > pos }.minOrNull()
            val end = minOf(pos + step, full.length, nextBlock ?: Int.MAX_VALUE)
            pos = end
            drain(full.substring(0, pos), blockEnd = false)
            if (pos in blockEnds) drain(full.substring(0, pos), blockEnd = true)
        }
        if (consumed < full.length) chunks += full.substring(consumed)
        assertEquals("Stuecke ergeben den ganzen Text", full, chunks.joinToString(""))
        return chunks
    }

    private val paragraph =
        "Ein Balkonkraftwerk lohnt sich vor allem, wenn tagsueber jemand zu Hause ist. " +
            "Dann wird der Strom direkt verbraucht und nicht verschenkt. " +
            "Die Anschaffung kostet heute ca. 400 Euro, z. B. fuer zwei Module. " +
            "Nach etwa fuenf Jahren hat sich das in vielen Haushalten bezahlt gemacht."

    @Test
    fun firstChunkIsTheFirstSentence() {
        val chunks = stream("Gute Frage, das haengt vor allem von deinem Verbrauch ab. $paragraph\n\n$paragraph")
        assertEquals("Gute Frage, das haengt vor allem von deinem Verbrauch ab. ", chunks.first())
    }

    @Test
    fun abbreviationsAndNumbersAreNoSentenceEnd() {
        val text = "Das kostet ca. 400 Euro und bringt z. B. im Sommer viel. Danach geht es weiter mit mehr Text."
        val chunks = stream(text)
        assertEquals("Das kostet ca. 400 Euro und bringt z. B. im Sommer viel. ", chunks.first())
    }

    @Test
    fun shortSentenceBeforeToolUseIsSpokenAtOnce() {
        val chunks = stream("Ich schaue kurz nach.|\n\n$paragraph\n\n$paragraph")
        assertEquals("Ich schaue kurz nach.", chunks.first())
        assert(chunks.size >= 2)
    }

    @Test
    fun codeBlocksAreNeverSplit() {
        val code = "```kotlin\nval a = 1. \n\nval b = 2. Ende\n\nprintln(a + b)\n```"
        val chunks = stream("$paragraph\n\nSo sieht das aus:\n\n$code\n\n$paragraph\n\n$paragraph", step = 3)
        for (c in chunks) {
            assertFalse("Codeblock zerschnitten: $c", c.split("```").size % 2 == 0)
        }
    }

    @Test
    fun sourcesBlockStaysInOnePiece() {
        // Der Server wirft den Block nur als Ganzes weg; ein abgetrennter Rest
        // ("Quelle 8") wuerde vorgelesen.
        val sources = (1..8).joinToString("\n") { "$it. [Quelle $it mit langem Titel](https://example.com/$it)" }
        val chunks = stream("$paragraph\n\n$paragraph\n\n**Quellen**\n$sources", step = 5)
        assertEquals(1, chunks.count { "Quelle" in it })
        assert(chunks.last().contains("**Quellen**") && chunks.last().endsWith("/8)"))
    }
}
