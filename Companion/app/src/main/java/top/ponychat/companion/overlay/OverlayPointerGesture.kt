package top.ponychat.companion.overlay

import kotlin.math.hypot

internal class OverlayPointerGesture(
    private val touchSlop: Float,
) {
    private var startX = 0f
    private var startY = 0f
    private var moved = false

    var deltaX: Float = 0f
        private set
    var deltaY: Float = 0f
        private set

    fun start(x: Float, y: Float) {
        startX = x
        startY = y
        deltaX = 0f
        deltaY = 0f
        moved = false
    }

    fun move(x: Float, y: Float) {
        deltaX = x - startX
        deltaY = y - startY
        if (hypot(deltaX, deltaY) >= touchSlop) moved = true
    }

    fun finish(x: Float, y: Float): Boolean {
        move(x, y)
        return !moved
    }

    fun cancel() {
        moved = true
    }
}
