package de.smartzone.pocketclaude.ui.components

import android.widget.Toast
import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.AnnotatedString
import de.smartzone.pocketclaude.R
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextLinkStyles
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.halilibo.richtext.commonmark.Markdown
import com.halilibo.richtext.ui.RichTextStyle
import com.halilibo.richtext.ui.material3.RichText
import com.halilibo.richtext.ui.string.RichTextStringStyle
import de.smartzone.pocketclaude.ui.theme.AtelierIce
import de.smartzone.pocketclaude.ui.theme.AtelierIceDeep
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.em
import com.halilibo.richtext.ui.BlockQuoteGutter
import com.halilibo.richtext.ui.TableStyle
import de.smartzone.pocketclaude.ui.theme.PocketCodeStyle
import de.smartzone.pocketclaude.ui.theme.PocketRadius
import de.smartzone.pocketclaude.ui.theme.PocketIconSize
import de.smartzone.pocketclaude.ui.theme.PocketIcons

/**
 * Markdown-Renderer mit Custom-Code-Block-Handling. Code-Blöcke werden aus dem
 * Markdown extrahiert und mit eigenem Composable gerendert (Sprach-Label,
 * Copy-Button, Monospace, scrollbar bei langen Zeilen). Der Rest geht via
 * compose-richtext.
 */
@Composable
fun MarkdownText(
    text: String,
    modifier: Modifier = Modifier,
    color: Color = MaterialTheme.colorScheme.onSurface,
    style: TextStyle = MaterialTheme.typography.bodyLarge,
) {
    val segments = remember(text) { splitIntoSegments(text) }
    // Links sollen je nach Theme genug Kontrast haben:
    // - Dark: helles Eisblau auf dem fast schwarzen
    //   Bubble-Hintergrund deutlich lesbarer als das mittelblaue Primary.
    // - Light: tiefes Eisblau mit gutem Kontrast auf hellem Hintergrund.
    val isDarkTheme = MaterialTheme.colorScheme.background.luminance() < 0.5f
    val linkColor = if (isDarkTheme) AtelierIce else AtelierIceDeep
    // Ueberschriften, Inline-Code, Tabellen und Zitate waren bisher die
    // Bibliotheks-Vorgaben: graue, zu grosse Ueberschriften, Inline-Code als
    // greller Kasten, Tabellen mit harten weissen Linien. Jetzt folgen sie der
    // App-Typografie und den Theme-Farben.
    val typography = MaterialTheme.typography
    val scheme = MaterialTheme.colorScheme
    val hairline = with(LocalDensity.current) { 1.dp.toPx() }
    val richTextStyle = remember(linkColor, color, typography, scheme, hairline) {
        RichTextStyle(
            headingStyle = { level, base ->
                val target = when (level) {
                    1 -> typography.titleLarge
                    2 -> typography.titleLarge.copy(fontSize = 18.sp, lineHeight = 26.sp)
                    3 -> typography.titleMedium
                    else -> typography.titleSmall
                }
                base.merge(target).copy(color = color)
            },
            blockQuoteGutter = BlockQuoteGutter.BarGutter(
                startMargin = 2.sp,
                barWidth = 3.sp,
                endMargin = 12.sp,
                color = { scheme.primary.copy(alpha = 0.5f) },
            ),
            tableStyle = TableStyle(
                headerTextStyle = typography.titleSmall.copy(color = color),
                cellPadding = 8.sp,
                borderColor = scheme.outlineVariant,
                borderStrokeWidth = hairline,
            ),
            stringStyle = RichTextStringStyle(
                codeStyle = SpanStyle(
                    fontFamily = FontFamily.Monospace,
                    fontSize = 0.9.em,
                    background = scheme.onSurface.copy(alpha = 0.08f),
                ),
                linkStyle = TextLinkStyles(
                    style = SpanStyle(
                        color = linkColor,
                        textDecoration = TextDecoration.Underline,
                    ),
                ),
            ),
        )
    }
    Column(
        modifier = modifier,
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        segments.forEach { segment ->
            when (segment) {
                is MdSegment.Text -> {
                    RichText(style = richTextStyle) {
                        Markdown(content = segment.content)
                    }
                }
                is MdSegment.Code -> CodeBlock(
                    code = segment.code,
                    language = segment.language,
                )
            }
        }
    }
}

private sealed interface MdSegment {
    data class Text(val content: String) : MdSegment
    data class Code(val code: String, val language: String?) : MdSegment
}

/** Trennt den Markdown-Text in normale Abschnitte und ``` ... ```-Code-Blöcke. */
private fun splitIntoSegments(text: String): List<MdSegment> {
    val regex = Regex("""```([^\n`]*)\n([\s\S]*?)```""", RegexOption.MULTILINE)
    val out = mutableListOf<MdSegment>()
    var lastEnd = 0
    for (match in regex.findAll(text)) {
        val before = text.substring(lastEnd, match.range.first)
        if (before.isNotBlank()) out.add(MdSegment.Text(before))
        val lang = match.groupValues[1].trim().takeIf { it.isNotEmpty() }
        val code = match.groupValues[2].trimEnd('\n')
        out.add(MdSegment.Code(code, lang))
        lastEnd = match.range.last + 1
    }
    val tail = text.substring(lastEnd)
    if (tail.isNotBlank()) out.add(MdSegment.Text(tail))
    if (out.isEmpty()) out.add(MdSegment.Text(text))
    return out
}

@Composable
private fun CodeBlock(
    code: String,
    language: String?,
) {
    val clipboard = LocalClipboardManager.current
    val context = LocalContext.current
    val bg = MaterialTheme.colorScheme.surfaceVariant
    val border = MaterialTheme.colorScheme.outline.copy(alpha = 0.4f)

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(PocketRadius.Medium))
            .background(bg),
    ) {
        // Header: Sprach-Label + Copy-Button
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .background(border.copy(alpha = 0.15f))
                .padding(start = 12.dp, end = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = language?.lowercase() ?: "code",
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.weight(1f),
            )
            val codeCopiedMsg = stringResource(R.string.markdown_code_copied)
            IconButton(
                onClick = {
                    clipboard.setText(AnnotatedString(code))
                    Toast.makeText(context, codeCopiedMsg, Toast.LENGTH_SHORT).show()
                },
                modifier = Modifier.size(40.dp),
            ) {
                Icon(
                    PocketIcons.Copy,
                    contentDescription = stringResource(R.string.markdown_copy_code),
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.size(PocketIconSize.Small),
                )
            }
        }
        // Code body — horizontal scrollbar bei langen Zeilen
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .horizontalScroll(rememberScrollState())
                .padding(horizontal = 12.dp, vertical = 12.dp),
        ) {
            Text(
                text = code,
                style = PocketCodeStyle,
                color = MaterialTheme.colorScheme.onSurface,
                softWrap = false,
            )
        }
    }
}
