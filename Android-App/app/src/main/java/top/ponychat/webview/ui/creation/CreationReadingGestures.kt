package top.ponychat.webview.ui.creation

import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.pointer.PointerEventPass
import androidx.compose.ui.input.pointer.pointerInput
import kotlin.math.abs

internal val LocalCreationHorizontalReading = androidx.compose.runtime.staticCompositionLocalOf<() -> Unit> { {} }

/** Observe horizontal reading without consuming the table/code's own scroll gesture. */
internal fun Modifier.creationHorizontalReading(onReading: () -> Unit) = pointerInput(Unit) {
    awaitEachGesture {
        val down = awaitFirstDown(requireUnconsumed = false, pass = PointerEventPass.Initial)
        do {
            val event = awaitPointerEvent(PointerEventPass.Initial)
            val finger = event.changes.firstOrNull { it.id == down.id } ?: break
            val distance = finger.position - down.position
            if (abs(distance.x) > 12 && abs(distance.x) > abs(distance.y)) onReading()
        } while (event.changes.any { it.pressed })
    }
}
