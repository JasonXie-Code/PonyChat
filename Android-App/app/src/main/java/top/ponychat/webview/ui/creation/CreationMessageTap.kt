package top.ponychat.webview.ui.creation

import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.pointer.PointerEventPass
import androidx.compose.ui.input.pointer.pointerInput

/** Observe taps without taking over selection, links, buttons, or horizontal scrolling. */
internal fun Modifier.creationMessageTap(onTap: () -> Unit) = pointerInput(Unit) {
    awaitEachGesture {
        val down = awaitFirstDown(requireUnconsumed = false, pass = PointerEventPass.Initial)
        var moved = false
        var multiTouch = false
        var endTime = down.uptimeMillis
        do {
            val event = awaitPointerEvent(PointerEventPass.Initial)
            multiTouch = multiTouch || event.changes.count { it.pressed } > 1
            val finger = event.changes.firstOrNull { it.id == down.id } ?: break
            moved = moved || (finger.position - down.position).getDistance() > viewConfiguration.touchSlop
            endTime = finger.uptimeMillis
        } while (event.changes.any { it.pressed })
        if (!moved && !multiTouch && endTime - down.uptimeMillis < viewConfiguration.longPressTimeoutMillis) onTap()
    }
}
