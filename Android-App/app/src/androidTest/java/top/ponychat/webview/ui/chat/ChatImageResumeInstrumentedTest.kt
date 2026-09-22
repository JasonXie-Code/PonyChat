package top.ponychat.webview.ui.chat

import android.content.Context
import android.graphics.Bitmap
import android.graphics.Color
import android.graphics.drawable.BitmapDrawable
import android.graphics.drawable.Drawable
import android.os.SystemClock
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.SideEffect
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import coil.compose.AsyncImage
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import top.ponychat.webview.debug.DialogPreviewActivity
import top.ponychat.webview.data.model.Message
import top.ponychat.webview.data.model.MessageAttachment
import top.ponychat.webview.ui.theme.PonyChatTheme
import java.io.ByteArrayOutputStream
import java.io.File

@RunWith(AndroidJUnit4::class)
class ChatImageResumeInstrumentedTest {
    @Test fun actualAttachmentBubbleRendersLateImageAfterResume() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        val remote = "/chat_images/tmp_bubble_resume_${System.nanoTime()}.png"
        var local: String? = null
        val message = Message(role = "assistant", content = "这是你要的图片", attachments = listOf(
            MessageAttachment(type = "image", url = remote, name = "后台图片",
                metadata = mapOf("source" to "web_search")),
        ))
        try {
            ActivityScenario.launch(DialogPreviewActivity::class.java).use { scenario ->
                scenario.onActivity { activity ->
                    activity.setContent {
                        PonyChatTheme {
                            MessageBubble(message = message, characterName = "测试角色",
                                characterAvatarUrl = "", userAvatarUrl = "", apiBase = "https://example.test",
                                onCopy = {}, onDelete = {})
                        }
                    }
                }
                SystemClock.sleep(500)
                scenario.moveToState(Lifecycle.State.CREATED)
                val bitmap = Bitmap.createBitmap(32, 32, Bitmap.Config.ARGB_8888)
                bitmap.eraseColor(Color.MAGENTA)
                val bytes = ByteArrayOutputStream().also { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }.toByteArray()
                bitmap.recycle()
                local = requireNotNull(saveLocalChatImageBytes(context, bytes, "png"))
                assertTrue(rememberLocalChatImageRemote(context, local!!, remote, synchronous = true))
                scenario.moveToState(Lifecycle.State.RESUMED)
                await("actual attachment bubble displays image pixels") {
                    val screen = instrumentation.uiAutomation.takeScreenshot() ?: return@await false
                    try {
                        val pixels = IntArray(screen.width * screen.height)
                        screen.getPixels(pixels, 0, screen.width, 0, 0, screen.width, screen.height)
                        pixels.count { it == Color.MAGENTA } > 1000
                    } finally { screen.recycle() }
                }
            }
        } finally {
            local?.let {
                context.getSharedPreferences("ponychat_local_image_remote", Context.MODE_PRIVATE)
                    .edit().remove(it).commit()
                File(android.net.Uri.parse(it).path!!).delete()
            }
        }
    }

    @Test fun thumbnailResolvesReceiptSavedWhileBackgrounded() = verifyLateReceipt(thumbnail = true)
    @Test fun fullPreviewResolvesReceiptSavedWhileBackgrounded() = verifyLateReceipt(thumbnail = false)
    @Test fun thumbnailResolvesReceiptFinishingAfterResume() = verifyLateReceipt(thumbnail = true, afterResume = true)
    @Test fun fullPreviewResolvesReceiptFinishingAfterResume() = verifyLateReceipt(thumbnail = false, afterResume = true)

    private fun verifyLateReceipt(thumbnail: Boolean, afterResume: Boolean = false) {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        val remote = "/chat_images/tmp_resume_${System.nanoTime()}.png"
        var local: String? = null
        var drawable: Drawable? = null
        var composed = false
        try {
            ActivityScenario.launch(DialogPreviewActivity::class.java).use { scenario ->
                scenario.onActivity { activity ->
                    activity.setContent {
                        SideEffect { composed = true }
                        AsyncImage(
                            model = if (thumbnail) rememberThumbnailImageRequest(remote)
                                else rememberChatImageRequest(remote),
                            contentDescription = "late image receipt",
                            modifier = Modifier.size(96.dp),
                            onSuccess = { drawable = it.result.drawable },
                        )
                    }
                }
                await("initial missing-image composition") {
                    var ready = false
                    instrumentation.runOnMainSync { ready = composed }
                    ready
                }
                SystemClock.sleep(300)
                scenario.moveToState(Lifecycle.State.CREATED)
                if (afterResume) scenario.moveToState(Lifecycle.State.RESUMED)
                val bitmap = Bitmap.createBitmap(24, 24, Bitmap.Config.ARGB_8888)
                bitmap.eraseColor(Color.BLUE)
                val bytes = ByteArrayOutputStream().also { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }.toByteArray()
                bitmap.recycle()
                local = requireNotNull(saveLocalChatImageBytes(context, bytes, "png"))
                assertTrue(rememberLocalChatImageRemote(context, local!!, remote, synchronous = true))
                scenario.moveToState(Lifecycle.State.RESUMED)
                await("actual image replaces transparent placeholder after resume") {
                    var loaded = false
                    instrumentation.runOnMainSync { loaded = drawable is BitmapDrawable }
                    loaded
                }
                instrumentation.runOnMainSync {
                    val pixels = requireNotNull((drawable as BitmapDrawable).bitmap.copy(Bitmap.Config.ARGB_8888, false))
                    assertEquals(Color.BLUE, pixels.getPixel(0, 0))
                    pixels.recycle()
                }
            }
        } finally {
            local?.let {
                context.getSharedPreferences("ponychat_local_image_remote", Context.MODE_PRIVATE)
                    .edit().remove(it).commit()
                File(android.net.Uri.parse(it).path!!).delete()
            }
        }
    }

    private fun await(description: String, condition: () -> Boolean) {
        val end = SystemClock.uptimeMillis() + 5000
        while (SystemClock.uptimeMillis() < end) {
            if (condition()) return
            SystemClock.sleep(50)
        }
        assertTrue(description, condition())
    }
}
