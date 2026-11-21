package top.ponychat.webview.ui.creation

import android.graphics.Canvas
import android.graphics.Paint
import android.text.SpannableStringBuilder
import android.text.Spanned
import io.noties.markwon.core.MarkwonTheme
import io.noties.markwon.ext.latex.JLatexAsyncDrawableSpan
import io.noties.markwon.utils.SpanUtils
import io.noties.markwon.image.AsyncDrawableSpan
import ru.noties.jlatexmath.JLatexMathDrawable
import kotlin.math.ceil

/** Preserve the loader and colour behaviour while aligning TeX's baseline to the text baseline. */
internal class CreationInlineMathSpan(theme: MarkwonTheme, private val original: JLatexAsyncDrawableSpan) :
    AsyncDrawableSpan(theme, original.drawable, ALIGN_CENTER, false) {
    internal fun baselineOffset(): Float {
        val math = drawable.result as? JLatexMathDrawable
        return drawable.bounds.height() * (math?.icon()?.baseLine ?: .8f)
    }

    override fun getSize(paint: Paint, text: CharSequence, start: Int, end: Int, fm: Paint.FontMetricsInt?): Int {
        if (!drawable.hasResult()) return original.getSize(paint, text, start, end, fm)
        val above = ceil(baselineOffset()).toInt()
        val below = ceil(drawable.bounds.height() - baselineOffset()).toInt()
        fm?.let {
            val font = paint.fontMetricsInt
            it.ascent = minOf(font.ascent, -above)
            it.descent = maxOf(font.descent, below)
            it.top = minOf(font.top, it.ascent)
            it.bottom = maxOf(font.bottom, it.descent)
        }
        return drawable.bounds.width()
    }

    override fun draw(canvas: Canvas, text: CharSequence, start: Int, end: Int, x: Float,
        top: Int, y: Int, bottom: Int, paint: Paint) {
        drawable.initWithKnownDimensions(SpanUtils.width(canvas, text), paint.textSize)
        if (!drawable.hasResult()) {
            original.draw(canvas, text, start, end, x, top, y, bottom, paint)
            return
        }
        val bounds = drawable.bounds
        val originalTop = bottom - bounds.bottom - (bottom - top - bounds.height()) / 2
        val desiredTop = y - baselineOffset()
        val saved = canvas.save()
        try {
            canvas.translate(0f, desiredTop - originalTop)
            original.draw(canvas, text, start, end, x, top, y, bottom, paint)
        } finally { canvas.restoreToCount(saved) }
    }
}

internal fun creationMathBaselines(parsed: Spanned, theme: MarkwonTheme, previous: Spanned? = null): Spanned {
    val result = SpannableStringBuilder(parsed)
    // Each occurrence owns its drawable; reuse only loaded instances from this TextView/style.
    val loaded = previous?.getSpans(0, previous.length, AsyncDrawableSpan::class.java)
        ?.filter { (it is CreationInlineMathSpan || it is JLatexAsyncDrawableSpan) && it.drawable.hasResult() }
        ?.sortedBy { previous.getSpanStart(it) }
        ?.groupBy { it.drawable.destination to (it is CreationInlineMathSpan) }
        ?.mapValues { (_, spans) -> java.util.ArrayDeque(spans) }.orEmpty()
    result.getSpans(0, result.length, JLatexAsyncDrawableSpan::class.java).forEach { span ->
        // Markwon's block span has this exact class; its only subclass represents inline math.
        // Class identity survives release obfuscation, unlike checking a class-name string.
        val inline = span.javaClass != JLatexAsyncDrawableSpan::class.java
        val reused = loaded[span.drawable.destination to inline]?.pollFirst()
        if (inline || reused != null) {
            val start = result.getSpanStart(span)
            val end = result.getSpanEnd(span)
            val flags = result.getSpanFlags(span)
            result.removeSpan(span)
            result.setSpan(reused ?: CreationInlineMathSpan(theme, span), start, end, flags)
        }
    }
    return result
}
