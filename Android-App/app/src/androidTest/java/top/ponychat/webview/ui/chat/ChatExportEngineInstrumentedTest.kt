package top.ponychat.webview.ui.chat

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.util.Base64
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import top.ponychat.webview.data.model.Character
import top.ponychat.webview.data.model.Message
import top.ponychat.webview.data.model.MessageAttachment
import java.io.ByteArrayOutputStream

@RunWith(AndroidJUnit4::class)
class ChatExportEngineInstrumentedTest {
    @Test
    fun exportedStickersAndImagesUseChatBubbleMediaSizing() = runBlocking {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val redSticker = solidPngDataUrl(width = 200, height = 100, color = Color.RED)
        val greenImage = solidPngDataUrl(width = 200, height = 100, color = Color.GREEN)
        val engine = ChatExportEngine(context)

        val bitmap = engine.generateBitmap(
            messages = listOf(
                Message(
                    role = "user",
                    content = "",
                    attachments = listOf(
                        MessageAttachment(
                            type = "sticker",
                            url = redSticker,
                            name = "wide sticker",
                        )
                    ),
                ),
                Message(
                    role = "user",
                    content = greenImage,
                ),
            ),
            character = Character(id = "export_test_character", name = "Export Test"),
            characterAvatarUrl = "",
            userAvatarUrl = "",
            userName = "Tester",
            apiBase = "",
        )

        val stickerBounds = colorBounds(bitmap) { color ->
            Color.red(color) > 220 && Color.green(color) < 40 && Color.blue(color) < 40
        }
        val imageBounds = colorBounds(bitmap) { color ->
            Color.green(color) > 170 && Color.red(color) < 40 && Color.blue(color) < 40
        }

        assertTrue("sticker width should be about 100dp at export scale", stickerBounds.width in 292..308)
        assertTrue("sticker height should preserve its 2:1 ratio", stickerBounds.height in 142..158)
        assertTrue("chat image tile should match the normal conversation grid", imageBounds.width in 348..362)
        assertTrue("chat image tile should be square", imageBounds.height in 348..362)
    }

    private fun solidPngDataUrl(width: Int, height: Int, color: Int): String {
        val bitmap = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)
        Canvas(bitmap).drawColor(color)
        val out = ByteArrayOutputStream()
        bitmap.compress(Bitmap.CompressFormat.PNG, 100, out)
        bitmap.recycle()
        val encoded = Base64.encodeToString(out.toByteArray(), Base64.NO_WRAP)
        return "data:image/png;base64,$encoded"
    }

    private data class PixelBounds(
        val minX: Int,
        val minY: Int,
        val maxX: Int,
        val maxY: Int,
    ) {
        val width: Int get() = maxX - minX + 1
        val height: Int get() = maxY - minY + 1
    }

    private fun colorBounds(bitmap: Bitmap, predicate: (Int) -> Boolean): PixelBounds {
        var minX = bitmap.width
        var minY = bitmap.height
        var maxX = -1
        var maxY = -1
        for (y in 0 until bitmap.height) {
            for (x in 0 until bitmap.width) {
                if (predicate(bitmap.getPixel(x, y))) {
                    minX = minOf(minX, x)
                    minY = minOf(minY, y)
                    maxX = maxOf(maxX, x)
                    maxY = maxOf(maxY, y)
                }
            }
        }
        assertTrue("expected color was not rendered", maxX >= minX && maxY >= minY)
        return PixelBounds(minX, minY, maxX, maxY)
    }
}
