package top.ponychat.webview.ui.chat

import android.content.Context
import android.content.ContextWrapper
import android.graphics.Bitmap
import android.graphics.Color
import android.os.ParcelFileDescriptor
import android.os.SystemClock
import android.view.accessibility.AccessibilityNodeInfo
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import top.ponychat.webview.data.model.Character
import top.ponychat.webview.data.model.MessageAttachment
import top.ponychat.webview.data.model.SearchMessageResult
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.debug.DialogPreviewActivity
import top.ponychat.webview.ui.theme.PonyChatTheme
import java.io.ByteArrayOutputStream
import java.io.File

@RunWith(AndroidJUnit4::class)
class SearchImagePreviewInstrumentedTest {
    private var navigated = false
    private val instrumentation = InstrumentationRegistry.getInstrumentation()

    private fun picture(context: Context, color: Int): String {
        val bitmap = Bitmap.createBitmap(80, 80, Bitmap.Config.ARGB_8888).apply { eraseColor(color) }
        val bytes = ByteArrayOutputStream().also { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }.toByteArray()
        bitmap.recycle()
        return checkNotNull(saveLocalChatImageBytes(context, bytes, "png"))
    }

    @Test fun allResultsRenderCachedImagesInlineImagesAndStickers() {
        instrumentation.uiAutomation.serviceInfo = instrumentation.uiAutomation.serviceInfo.apply {
            flags = flags or android.accessibilityservice.AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS
        }
        ActivityScenario.launch(DialogPreviewActivity::class.java).use { scenario ->
            scenario.onActivity { activity ->
                if (android.os.Build.VERSION.SDK_INT >= 33) activity.setRecentsScreenshotEnabled(false)
                val cached = picture(activity, Color.RED)
                val inline = picture(activity, Color.BLUE)
                val sticker = picture(activity, Color.GREEN)
                val remote = "/chat_images/tmp_history_preview_fixture.png"
                assertTrue(rememberLocalChatImageRemote(activity, cached, remote, synchronous = true))
                val prefs = AppPreferences(object : ContextWrapper(activity) {
                    override fun getSharedPreferences(name: String, mode: Int) =
                        activity.getSharedPreferences("search-preview-test", mode)
                }).apply { username = "synthetic-history" }
                val now = System.currentTimeMillis()
                top.ponychat.webview.data.local.LocalHistoryImageStore(activity).record(
                    prefs.username, "fixture", "fixture", listOf(
                        top.ponychat.webview.data.model.ChatMessage(role = "user",
                            content = "照片说明 ![]($inline)", messageId = "inline", timestamp = now)))
                val rows = listOf(
                    SearchMessageResult("cached", 1, "fixture", "assistant", "", now,
                        listOf(MessageAttachment(type = "image", url = remote))),
                    SearchMessageResult("inline", 2, "fixture", "user", "照片说明", now),
                    SearchMessageResult("missing", 3, "fixture", "assistant", "", now,
                        listOf(MessageAttachment(type = "image", url = "/chat_images/tmp_missing_fixture.png"))),
                    SearchMessageResult("sticker", 4, "fixture", "assistant", "[表情]", now,
                        listOf(MessageAttachment(type = "sticker", url = sticker, name = "测试表情"))),
                ).withLocalHistoryImages(activity, prefs.username, "fixture")
                activity.setContent {
                    PonyChatTheme(darkTheme = false) {
                        var selected by remember { mutableStateOf<Set<String>>(emptySet()) }
                        val gallery = rememberHistoryImageGallery()
                        gallery.Preview()
                        Surface(Modifier.fillMaxSize()) {
                            Column(Modifier.statusBarsPadding()) {
                                Text("搜索消息 · 全部", Modifier.padding(16.dp))
                                rows.forEach { row ->
                                    MessageSearchResultItem(row, "照片", Character(id = "fixture", name = "测试角色"),
                                        prefs, onClick = { navigated = true }, onPrompt = {},
                                        isSelected = row.messageId in selected, isSelectionMode = selected.isNotEmpty(),
                                        onToggleSelect = { selected = if (it in selected) selected - it else selected + it },
                                        onPreviewImage = { gallery.open(rows, row, it) })
                                }
                            }
                        }
                    }
                }
            }
            val deadline = SystemClock.uptimeMillis() + 12000
            var verified = false
            while (SystemClock.uptimeMillis() < deadline && !verified) {
                SystemClock.sleep(300)
                val bitmap = instrumentation.uiAutomation.takeScreenshot()
                val colors = intArrayOf(Color.RED, Color.BLUE, Color.GREEN)
                val counts = IntArray(3)
                for (y in 0 until bitmap.height step 2) for (x in 0 until bitmap.width step 2) {
                    val index = colors.indexOf(bitmap.getPixel(x, y))
                    if (index >= 0) counts[index]++
                }
                verified = counts.all { it > 500 }
                if (verified) {
                    val file = File(instrumentation.targetContext.getExternalFilesDir(null), "search-image-preview.png")
                    file.outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }
                    ParcelFileDescriptor.AutoCloseInputStream(instrumentation.uiAutomation.executeShellCommand(
                        "cp ${file.absolutePath} /sdcard/Download/ponychat-search-image-preview.png")).use { it.readBytes() }
                }
                bitmap.recycle()
            }
            assertTrue("Cached attachment, inline picture and sticker must actually render", verified)
            val texts = allNodes().mapNotNull { it.text?.toString() }
            assertTrue(texts.contains("图片不可用"))
            assertTrue(texts.contains("照片说明"))
            assertFalse(texts.any { it.contains("file://") || it.contains("/chat_images/") })
            clickDescription("聊天图片")
            awaitText("1/4")
            swipe(true)
            awaitText("2/4")
            swipe(false)
            awaitText("1/4")
            clickDescription("关闭")
            SystemClock.sleep(400)
            clickDescription("测试表情")
            awaitText("4/4")
            swipe(false)
            awaitText("3/4")
            assertFalse("Media taps must not navigate to the message", navigated)
            clickDescription("关闭")
            var stickerNode = checkNotNull(allNodes()
                .firstOrNull { it.contentDescription?.toString() == "测试表情" })
            while (!stickerNode.isLongClickable && stickerNode.parent != null) stickerNode = stickerNode.parent
            assertTrue(stickerNode.performAction(AccessibilityNodeInfo.ACTION_LONG_CLICK))
            awaitText("多选")
            var menu = checkNotNull(allNodes().firstOrNull { it.text?.toString() == "多选" })
            while (!menu.isClickable && menu.parent != null) menu = menu.parent
            assertTrue(menu.performAction(AccessibilityNodeInfo.ACTION_CLICK))
            SystemClock.sleep(400)
            assertTrue(allNodes().any { it.isChecked })
            clickDescription("测试表情")
            assertFalse(allNodes().any { it.isChecked })
            assertFalse(allNodes().any { it.contentDescription?.toString() == "保存到相册" })
        }
    }

    private fun clickDescription(description: String) {
        var node = checkNotNull(allNodes()
            .firstOrNull { it.contentDescription?.toString() == description })
        while (!node.isClickable && node.parent != null) node = node.parent
        val bounds = android.graphics.Rect().also(node::getBoundsInScreen)
        ParcelFileDescriptor.AutoCloseInputStream(instrumentation.uiAutomation.executeShellCommand(
            "input tap ${bounds.centerX()} ${bounds.centerY()}")).use { it.readBytes() }
        SystemClock.sleep(350)
    }

    private fun awaitText(text: String) {
        val end = SystemClock.uptimeMillis() + 8000
        while (SystemClock.uptimeMillis() < end) {
            if (allNodes().any { it.text?.toString() == text }) return
            SystemClock.sleep(100)
        }
        fail("Missing preview page $text")
    }

    private fun swipe(forward: Boolean) {
        val bitmap = instrumentation.uiAutomation.takeScreenshot()
        val left = bitmap.width / 5
        val right = bitmap.width * 4 / 5
        val y = bitmap.height / 2
        bitmap.recycle()
        val start = if (forward) right else left
        val end = if (forward) left else right
        ParcelFileDescriptor.AutoCloseInputStream(instrumentation.uiAutomation.executeShellCommand(
            "input swipe $start $y $end $y 300")).use { it.readBytes() }
        SystemClock.sleep(500)
    }

    private fun allNodes(): List<AccessibilityNodeInfo> {
        if (android.os.Build.VERSION.SDK_INT >= 33) instrumentation.uiAutomation.clearCache()
        return nodes(instrumentation.uiAutomation.rootInActiveWindow) +
            instrumentation.uiAutomation.windows.flatMap { nodes(it.root) }
    }

    private fun nodes(node: AccessibilityNodeInfo?): List<AccessibilityNodeInfo> =
        if (node == null) emptyList() else listOf(node) + (0 until node.childCount).flatMap { nodes(node.getChild(it)) }
}
