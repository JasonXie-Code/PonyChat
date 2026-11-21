package top.ponychat.companion.overlay

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class OverlayPointerGestureTest {
    @Test
    fun `short stationary gesture restores overlay`() {
        val gesture = OverlayPointerGesture(touchSlop = 8f)
        gesture.start(100f, 200f)

        assertTrue(gesture.finish(104f, 203f))
    }

    @Test
    fun `drag updates position and does not restore overlay`() {
        val gesture = OverlayPointerGesture(touchSlop = 8f)
        gesture.start(100f, 200f)
        gesture.move(140f, 260f)

        assertEquals(40f, gesture.deltaX)
        assertEquals(60f, gesture.deltaY)
        assertFalse(gesture.finish(140f, 260f))
    }
}
