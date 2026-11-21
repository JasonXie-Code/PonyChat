package top.ponychat.webview.ui.creation

import android.widget.TextView
import android.text.method.LinkMovementMethod
import android.util.TypedValue
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.viewinterop.AndroidView
import io.noties.markwon.Markwon
import io.noties.markwon.ext.strikethrough.StrikethroughPlugin
import io.noties.markwon.ext.tables.TablePlugin
import io.noties.markwon.ext.tasklist.TaskListPlugin
import io.noties.markwon.image.ImagesPlugin
import io.noties.markwon.linkify.LinkifyPlugin
import io.noties.markwon.html.HtmlPlugin
import io.noties.markwon.ext.latex.JLatexMathPlugin
import io.noties.markwon.inlineparser.MarkwonInlineParserPlugin

/** Preserve the model's original Markdown: no bubble JSON parsing or prose rewriting. */
@Composable
internal fun CreationMarkdownText(text: String, modifier: Modifier = Modifier, streaming: Boolean = false) {
    val context = LocalContext.current
    val bodySizePx = with(LocalDensity.current) { MaterialTheme.typography.bodyLarge.fontSize.toPx() }
    val color = MaterialTheme.colorScheme.onSurface.toArgb()
    val link = MaterialTheme.colorScheme.primary.toArgb()
    val codeBackground = MaterialTheme.colorScheme.surfaceVariant.toArgb()
    val markwon = remember(context, color, codeBackground, bodySizePx) {
        Markwon.builder(context).usePlugin(StrikethroughPlugin.create())
            .usePlugin(TablePlugin.create(context)).usePlugin(TaskListPlugin.create(context))
            .usePlugin(ImagesPlugin.create()).usePlugin(LinkifyPlugin.create()).usePlugin(HtmlPlugin.create())
            .usePlugin(MarkwonInlineParserPlugin.create())
            .usePlugin(JLatexMathPlugin.create(bodySizePx) { builder ->
                builder.inlinesEnabled(true).theme().textColor(color)
            })
            .usePlugin(object : io.noties.markwon.AbstractMarkwonPlugin() {
                override fun configureTheme(builder: io.noties.markwon.core.MarkwonTheme.Builder) {
                    builder.codeBlockBackgroundColor(codeBackground).codeBlockTextColor(color)
                        .codeBackgroundColor(codeBackground).codeTextColor(color)
                }
            }).build()
    }
    AndroidView(modifier = modifier, factory = { ctx -> TextView(ctx).apply {
        setLineSpacing(5f * resources.displayMetrics.density, 1.1f)
        setTextIsSelectable(true)
        movementMethod = LinkMovementMethod.getInstance()
    } }, update = { view ->
        view.setTextSize(TypedValue.COMPLEX_UNIT_PX, bodySizePx)
        view.setTextColor(color); view.setLinkTextColor(link)
        val display = creationMathMarkdown(text, streaming)
        val key = Triple(display, color, markwon)
        if (view.tag != key) {
            val previous = if ((view.tag as? Triple<*, *, *>)?.third === markwon)
                view.text as? android.text.Spanned else null
            view.tag = key
            markwon.setParsedMarkdown(view, creationMathBaselines(
                markwon.toMarkdown(display), markwon.configuration().theme(), previous))
        }
    })
}

@Composable
internal fun CreationMarkdown(text: String, modifier: Modifier = Modifier, streaming: Boolean = false) {
    val blocks = remember(text, streaming) { creationMarkdownBlocks(text, streaming) }
    androidx.compose.foundation.layout.Column(modifier) {
        blocks.forEach { block ->
            key(block.start, block.kind) {
                when {
                    block.pending -> CreationBlockPending(block.kind)
                    block.kind == CreationBlockKind.Diagram -> CreationMermaidBlock(block.text)
                    block.kind == CreationBlockKind.Code -> CreationCodeBlock(block.text, block.language)
                    block.kind == CreationBlockKind.Table -> CreationTableBlock(block.text)
                    else -> CreationMarkdownText(block.text, streaming = streaming)
                }
            }
        }
    }
}
