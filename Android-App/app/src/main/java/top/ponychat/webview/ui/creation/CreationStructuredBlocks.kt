package top.ponychat.webview.ui.creation

import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.util.TypedValue
import android.view.ViewGroup
import android.widget.HorizontalScrollView
import android.widget.TableLayout
import android.widget.TableRow
import android.widget.TextView
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import io.noties.markwon.Markwon

@Composable
internal fun CreationBlockPending(kind: CreationBlockKind) {
    CreationCard(Modifier.fillMaxWidth().padding(vertical = 8.dp)) {
        Text(when (kind) { CreationBlockKind.Table -> "表格正在生成中…"; CreationBlockKind.Diagram -> "流程图正在生成中…"; else -> "代码块正在生成中…" },
            modifier = Modifier.padding(16.dp), style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
internal fun CreationCodeBlock(code: String, language: String) {
    val onReading = LocalCreationHorizontalReading.current
    val color = MaterialTheme.colorScheme.onSurface.toArgb()
    val size = with(LocalDensity.current) { MaterialTheme.typography.bodyLarge.fontSize.toPx() }
    val dark = MaterialTheme.colorScheme.surface.luminance() < .5f
    val highlighted = remember(code, language, dark) { highlightCreationCode(code, language, dark) }
    CreationCard(Modifier.fillMaxWidth().padding(vertical = 8.dp)) {
        Text(language.ifBlank { "代码" }, Modifier.padding(12.dp),
            style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        AndroidView(modifier = Modifier.fillMaxWidth(), factory = { ctx ->
            CreationHorizontalScrollView(ctx).apply {
                contentDescription = "代码横向滚动"
                isFillViewport = false
                addView(CreationSelectableTextView(ctx).apply {
                    typeface = Typeface.MONOSPACE
                    setHorizontallyScrolling(true)
                    val pad = (12 * resources.displayMetrics.density).toInt()
                    setPadding(pad, pad, pad, pad)
                }, ViewGroup.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT))
            }
        }, update = { scroller ->
            scroller.onHorizontalReading = onReading
            val view = scroller.getChildAt(0) as TextView
            view.setTextSize(TypedValue.COMPLEX_UNIT_PX, size)
            view.setTextColor(color)
            if (view.tag != listOf(code, language, dark)) {
                view.tag = listOf(code, language, dark); view.text = highlighted
            }
        })
    }
}

@Composable
internal fun CreationTableBlock(markdown: String) {
    val context = LocalContext.current
    val onReading = LocalCreationHorizontalReading.current
    val color = MaterialTheme.colorScheme.onSurface.toArgb()
    val border = MaterialTheme.colorScheme.outline.copy(alpha = .45f).toArgb()
    val cellBackground = MaterialTheme.colorScheme.surface.toArgb()
    val headerBackground = MaterialTheme.colorScheme.surfaceVariant.toArgb()
    val size = with(LocalDensity.current) { MaterialTheme.typography.bodyLarge.fontSize.toPx() }
    val markwon = remember(context) { Markwon.create(context) }
    val rows = remember(markdown) { markdown.lines().filterIndexed { i, _ -> i != 1 }.map(::creationTableCells) }
    CreationCard(Modifier.fillMaxWidth().padding(vertical = 8.dp)) {
        AndroidView(modifier = Modifier.fillMaxWidth(), factory = { ctx -> CreationHorizontalScrollView(ctx).apply {
            contentDescription = "表格横向滚动"
            isFillViewport = false
            addView(TableLayout(ctx), ViewGroup.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT))
        } }, update = { scroller ->
            scroller.onHorizontalReading = onReading
            val table = scroller.getChildAt(0) as TableLayout
            val tag = listOf(markdown, color, border, cellBackground, headerBackground, size)
            if (table.tag != tag) {
                table.tag = tag; table.removeAllViews()
                val density = table.resources.displayMetrics.density
                val columns = rows.maxOfOrNull { it.size } ?: 0
                val paint = android.text.TextPaint().apply { textSize = size }
                val widths = (0 until columns).map { column ->
                    ((rows.maxOfOrNull { row -> paint.measureText(row.getOrNull(column).orEmpty()) } ?: 0f) + 24 * density)
                        .coerceIn(144 * density, 320 * density).toInt()
                }
                rows.forEachIndexed { index, row ->
                    val tableRow = TableRow(context)
                    repeat(columns) { column ->
                        tableRow.addView(CreationSelectableTextView(context).apply {
                            setTextSize(TypedValue.COMPLEX_UNIT_PX, size); setTextColor(color)
                                    if (index == 0) setTypeface(typeface, Typeface.BOLD)
                            val pad = (12 * density).toInt(); setPadding(pad, pad, pad, pad)
                            this.background = GradientDrawable().apply {
                                setColor(if (index == 0) headerBackground else cellBackground)
                                setStroke(density.toInt().coerceAtLeast(1), border)
                            }
                            markwon.setMarkdown(this, row.getOrNull(column).orEmpty())
                        }, TableRow.LayoutParams(widths[column], ViewGroup.LayoutParams.MATCH_PARENT))
                    }
                    table.addView(tableRow)
                }
            }
        })
    }
}
