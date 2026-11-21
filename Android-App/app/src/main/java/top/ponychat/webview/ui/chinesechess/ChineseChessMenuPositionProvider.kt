package top.ponychat.webview.ui.chinesechess

import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.IntRect
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.window.PopupPositionProvider

internal class AboveAnchorMenuPositionProvider(
    private val verticalGapPx: Int,
    private val screenMarginPx: Int
) : PopupPositionProvider {
    override fun calculatePosition(
        anchorBounds: IntRect,
        windowSize: IntSize,
        layoutDirection: LayoutDirection,
        popupContentSize: IntSize
    ): IntOffset {
        val minX = screenMarginPx
        val maxX = (windowSize.width - popupContentSize.width - screenMarginPx).coerceAtLeast(minX)
        val preferredX = if (layoutDirection == LayoutDirection.Ltr) {
            anchorBounds.left
        } else {
            anchorBounds.right - popupContentSize.width
        }
        val x = preferredX.coerceIn(minX, maxX)

        val aboveY = anchorBounds.top - popupContentSize.height - verticalGapPx
        val maxY = (windowSize.height - popupContentSize.height - screenMarginPx).coerceAtLeast(screenMarginPx)
        val y = if (aboveY >= screenMarginPx) {
            aboveY
        } else {
            (anchorBounds.bottom + verticalGapPx).coerceIn(screenMarginPx, maxY)
        }
        return IntOffset(x, y)
    }
}