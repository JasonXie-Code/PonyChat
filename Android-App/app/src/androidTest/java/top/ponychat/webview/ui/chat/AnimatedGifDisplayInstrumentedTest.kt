package top.ponychat.webview.ui.chat

import android.graphics.drawable.Animatable
import android.graphics.drawable.Drawable
import android.graphics.Bitmap
import android.graphics.Canvas
import android.os.Build
import android.os.SystemClock
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import coil.compose.AsyncImage
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import top.ponychat.webview.debug.DialogPreviewActivity
import top.ponychat.webview.ui.theme.PonyChatTheme

/** Exercises the production thumbnail request and global Coil loader on a real emulator. */
@RunWith(AndroidJUnit4::class)
class AnimatedGifDisplayInstrumentedTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()

    @Test
    fun chatThumbnailPlaysTwoFrameGif() {
        require(Build.VERSION.SDK_INT >= Build.VERSION_CODES.P)
        val loadedDrawable = mutableStateOf<Drawable?>(null)
        ActivityScenario.launch(DialogPreviewActivity::class.java).use { scenario ->
            scenario.onActivity { activity ->
                activity.setContent {
                    PonyChatTheme(darkTheme = true) {
                        AsyncImage(
                            model = rememberThumbnailImageRequest(TWO_FRAME_GIF_DATA_URL),
                            contentDescription = "two-frame animated GIF",
                            modifier = Modifier.size(96.dp),
                            onSuccess = { result ->
                                loadedDrawable.value = result.result.drawable
                            },
                        )
                    }
                }
            }
            waitFor("GIF loaded") { loadedDrawable.value != null }
            val drawable = loadedDrawable.value!!
            // Coil may wrap the platform drawable to scale a tiny GIF thumbnail.
            assertTrue("GIF must remain animated through its wrapper", drawable is Animatable)
            val animation = drawable as Animatable
            instrumentation.runOnMainSync { animation.stop(); animation.start() }
            assertTrue("The rendered GIF drawable must play", animation.isRunning)
            val firstPixel = drawablePixel(drawable, waitMs = 200)
            val laterPixel = drawablePixel(drawable, waitMs = 600)
            assertTrue(
                "The rendered GIF must advance to its second frame",
                firstPixel != laterPixel,
            )
        }
    }

    private fun waitFor(description: String, condition: () -> Boolean) {
        val deadline = SystemClock.uptimeMillis() + 3_000
        while (SystemClock.uptimeMillis() < deadline) {
            if (condition()) return
            SystemClock.sleep(30)
        }
        assertTrue(description, condition())
    }

    private fun drawablePixel(drawable: Drawable, waitMs: Long): Int {
        SystemClock.sleep(waitMs)
        val bitmap = Bitmap.createBitmap(1, 1, Bitmap.Config.ARGB_8888)
        instrumentation.runOnMainSync {
            drawable.setBounds(0, 0, 1, 1)
            drawable.draw(Canvas(bitmap))
        }
        return bitmap.getPixel(0, 0).also { bitmap.recycle() }
    }

    private companion object {
        // A looping 1×1 GIF with one red and one blue frame (50 cs each).
        const val TWO_FRAME_GIF_DATA_URL =
            "data:image/gif;base64,R0lGODlhAQABAIAAAP8AAAAA/yH/C05FVFNDQVBFMi4wAwEAAAAh+QQEMgAAACwAAAAAAQABAAACAkQBACH5BAQyAAAALAAAAAABAAEAAAICTAEAOw=="
    }
}
