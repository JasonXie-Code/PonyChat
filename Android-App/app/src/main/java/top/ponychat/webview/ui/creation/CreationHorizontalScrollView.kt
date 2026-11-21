package top.ponychat.webview.ui.creation

import android.content.Context
import android.graphics.Rect
import android.view.MotionEvent
import android.view.View
import android.widget.HorizontalScrollView
import kotlin.math.abs

/** Reading a block must not leave native focus or request automatic repositioning. */
internal class CreationHorizontalScrollView(context: Context) : HorizontalScrollView(context) {
    var onHorizontalReading: () -> Unit = {}
    private var startX = 0f
    init { isFocusable = false; isFocusableInTouchMode = false }
    override fun dispatchTouchEvent(event: MotionEvent): Boolean {
        if (event.actionMasked == MotionEvent.ACTION_DOWN) startX = event.x
        val result = super.dispatchTouchEvent(event)
        if (event.actionMasked == MotionEvent.ACTION_UP && abs(event.x - startX) > 12 * resources.displayMetrics.density) {
            findFocus()?.clearFocus()
            parent.requestDisallowInterceptTouchEvent(false)
        }
        return result
    }
    override fun onScrollChanged(l: Int, t: Int, oldl: Int, oldt: Int) {
        super.onScrollChanged(l, t, oldl, oldt)
        if (l != oldl) onHorizontalReading()
    }
    override fun requestChildRectangleOnScreen(child: View, rectangle: Rect, immediate: Boolean) = false
}
