package top.ponychat.webview.ui.chat

import android.content.Context
import android.content.ContextWrapper
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
import android.graphics.Rect
import android.os.SystemClock
import android.util.Base64
import android.view.WindowManager
import android.view.accessibility.AccessibilityNodeInfo
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.unit.dp
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.google.gson.Gson
import okhttp3.OkHttpClient
import okhttp3.Protocol
import okhttp3.Response
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import top.ponychat.webview.data.api.ApiService
import top.ponychat.webview.data.model.Character
import top.ponychat.webview.data.model.SearchMessageResult
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.debug.DialogPreviewActivity
import top.ponychat.webview.ui.theme.PonyChatTheme
import java.io.ByteArrayOutputStream
import java.io.File
import java.util.concurrent.CopyOnWriteArrayList

/** Real controls, Retrofit paging and measured grid; synthetic records only. */
@RunWith(AndroidJUnit4::class)
class HistoryFilterInstrumentedTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val requests = CopyOnWriteArrayList<String>()

    private fun picture(index: Int): String {
        val bitmap = Bitmap.createBitmap(480, 480, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(bitmap)
        val paint = Paint(Paint.ANTI_ALIAS_FLAG)
        val skies = intArrayOf(0xffc6e4f5.toInt(), 0xffffd1bc.toInt(), 0xffcfc5ea.toInt(), 0xffb8ded4.toInt())
        canvas.drawColor(skies[index % skies.size])
        paint.color = 0xfffff4cd.toInt(); canvas.drawCircle(355f, 110f, 45f, paint)
        paint.color = 0xff728ead.toInt()
        canvas.drawPath(Path().apply { moveTo(0f, 330f); lineTo(160f, 120f); lineTo(360f, 360f); close() }, paint)
        paint.color = 0xff425f80.toInt()
        canvas.drawPath(Path().apply { moveTo(170f, 390f); lineTo(350f, 180f); lineTo(480f, 350f); lineTo(480f, 480f); close() }, paint)
        paint.color = 0xff365a67.toInt(); canvas.drawRect(0f, 370f, 480f, 480f, paint)
        paint.color = Color.WHITE; paint.textSize = 36f
        canvas.drawText("TRAVEL ${index + 1}", 26f, 439f, paint)
        val bytes = ByteArrayOutputStream().also { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }.toByteArray()
        bitmap.recycle()
        return "data:image/png;base64," + Base64.encodeToString(bytes, Base64.NO_WRAP)
    }

    @Test
    fun filterPagingGridAndScreenshots() {
        val now = System.currentTimeMillis()
        val records: List<Map<String, Any>> = (400 downTo 269).map { seq ->
            val image = seq <= 300
            mapOf<String, Any>("message_id" to "fixture-$seq", "sequence_number" to seq,
                "conversation_id" to "fixture", "role" to if (seq % 2 == 0) "user" else "assistant",
                "content" to if (image) "" else "旅行记录：今天的风景很好，我们把沿途的照片整理起来了。",
                "timestamp" to now - (400 - seq) * 60000L,
                "attachments" to if (image) listOf(mapOf("type" to if (seq == 299) "sticker" else "image", "name" to "旅行风景",
                    "url" to picture(300 - seq))) else emptyList<Map<String, String>>())
        }
        val client = OkHttpClient.Builder().addInterceptor { chain ->
            val url = chain.request().url
            requests += url.toString()
            val sender = url.queryParameter("sender")
            var rows: List<Map<String, Any>> = records.filter {
                sender == "all" || it["role"] == (if (sender == "user") "user" else "assistant")
            }
            url.queryParameter("date_from")?.toLong()?.let { from -> rows = rows.filter { (it["timestamp"] as Long) >= from } }
            url.queryParameter("date_to")?.toLong()?.let { to -> rows = rows.filter { (it["timestamp"] as Long) <= to } }
            val body: Map<String, Any?> = if (url.encodedPath.endsWith("/search")) {
                val offset = url.queryParameter("offset")!!.toInt()
                val page = rows.drop(offset).take(50)
                mapOf("results" to page, "total" to rows.size, "has_more" to (offset + page.size < rows.size))
            } else {
                url.queryParameter("before_seq")?.toInt()?.let { before -> rows = rows.filter { (it["sequence_number"] as Int) < before } }
                val page = rows.take(100)
                mapOf("messages" to page.reversed(), "has_more" to (rows.size > page.size),
                    "min_seq" to page.lastOrNull()?.get("sequence_number"), "conversation_id" to "fixture")
            }
            Response.Builder().request(chain.request()).protocol(Protocol.HTTP_1_1).code(200).message("OK")
                .body(Gson().toJson(body).toResponseBody("application/json".toMediaType())).build()
        }.build()
        val api = Retrofit.Builder().baseUrl("http://127.0.0.1/").client(client)
            .addConverterFactory(GsonConverterFactory.create()).build().create(ApiService::class.java)
        val mode = mutableStateOf("image")
        val query = mutableStateOf("")
        val sender = mutableStateOf("all")
        val date = mutableStateOf("all")
        val scenario = ActivityScenario.launch(DialogPreviewActivity::class.java)
        try {
            scenario.onActivity { activity ->
                val prefs = AppPreferences(object : ContextWrapper(activity) {
                    override fun getSharedPreferences(name: String, mode: Int) =
                        activity.getSharedPreferences("history-filter-fixture", mode)
                }).apply { username = "synthetic-gallery" }
                activity.setContent {
                    PonyChatTheme(darkTheme = true) {
                        Surface(Modifier.fillMaxSize()) {
                            Column(Modifier.fillMaxSize().statusBarsPadding()) {
                                Text("‹   搜索消息", Modifier.padding(20.dp, 16.dp), style = MaterialTheme.typography.headlineSmall)
                                Text("验收对话 · 测试图片", Modifier.padding(horizontal = 20.dp),
                                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                MessageSearchBar(query.value, { query.value = it }, remember { FocusRequester() },
                                    Modifier.fillMaxWidth().padding(12.dp))
                                FiltersDropdownRow(sender.value, { sender.value = it }, date.value, { date.value = it },
                                    mode.value, { mode.value = it }, Modifier.padding(16.dp, 4.dp))
                                HorizontalDivider(Modifier.padding(top = 12.dp))
                                key(mode.value, query.value, sender.value, date.value) {
                                    HistoryFilteredResults(Character("fixture", "紫悦"), prefs, mode.value,
                                        query.value, sender.value, date.value, {}, {}, {}, api)
                                }
                            }
                        }
                    }
                }
            }
            await("all images beyond first text page") { findText("已加载 32 张图片") != null }
            assertTrue(requests.any { it.contains("before_seq=301") })
            val bounds = (1..3).map { index ->
                val node = findDescription("对话图片 $index")!!
                Rect().also(node::getBoundsInScreen)
            }
            assertEquals(bounds[0].top, bounds[1].top); assertEquals(bounds[1].top, bounds[2].top)
            assertTrue(bounds[0].left < bounds[1].left && bounds[1].left < bounds[2].left)
            screenshot("images-grid.png")
            clickText("图片")
            await("three filter options") { findText("文本") != null && findText("全部") != null }
            screenshot("filter-options.png")
            clickText("文本")
            await("text results") { findText("已加载 100 条文本") != null }
            assertNull(findDescription("对话图片 1"))
            screenshot("text-results.png")
            clickText("文本"); clickText("图片")
            await("grid restored") { findText("已加载 32 张图片") != null }
            clickDescription("对话图片 1")
            await("full screen preview") { findDescription("保存到相册") != null }
            screenshot("full-preview.png")
            val screen = instrumentation.uiAutomation.takeScreenshot()
            val x1 = screen.width * 4 / 5
            val x2 = screen.width / 5
            val y = screen.height / 2
            screen.recycle()
            android.os.ParcelFileDescriptor.AutoCloseInputStream(instrumentation.uiAutomation.executeShellCommand(
                "input swipe $x1 $y $x2 $y 300")).use { it.readBytes() }
            await("swipe to sticker") { findText("2/32") != null }
            SystemClock.sleep(500)
            android.os.ParcelFileDescriptor.AutoCloseInputStream(instrumentation.uiAutomation.executeShellCommand(
                "input swipe $x2 $y $x1 $y 300")).use { it.readBytes() }
            await("swipe back to picture") { findText("1/32") != null }
            instrumentation.uiAutomation.performGlobalAction(android.accessibilityservice.AccessibilityService.GLOBAL_ACTION_BACK)
            await("preview closed") { findDescription("保存到相册") == null }
            clickText("全部人"); clickText("我")
            await("sender filter") { findText("已加载 16 张图片") != null }
            clickText("全部时间"); clickText("今天")
            await("date filter forwarded") { requests.any { it.contains("date_from=") } }
            instrumentation.runOnMainSync { query.value = "旅行" }
            await("search pages scanned") { requests.any { it.contains("/search") && it.contains("offset=50") } }
            await("search images") { findText("已加载 16 张图片") != null }
            // Predicate handles mixed text/image messages and excludes pure image rows from text.
            val sample = SearchMessageResult("s", 1, "fixture", "user", picture(0), now)
            assertTrue(sample.matchesHistoryContent("image")); assertFalse(sample.matchesHistoryContent("text"))
            println("HISTORY_FILTER all 32 images, 3 columns, text, sender, date, search pagination and preview PASS")
        } finally {
            scenario.onActivity { it.window.addFlags(WindowManager.LayoutParams.FLAG_SECURE) }
            scenario.close()
        }
    }

    private fun nodes(node: AccessibilityNodeInfo?): List<AccessibilityNodeInfo> =
        if (node == null) emptyList() else listOf(node) + (0 until node.childCount).flatMap { nodes(node.getChild(it)) }
    private fun findText(text: String) = nodes(instrumentation.uiAutomation.rootInActiveWindow).firstOrNull { it.text?.toString() == text }
    private fun findDescription(text: String) = nodes(instrumentation.uiAutomation.rootInActiveWindow).firstOrNull { it.contentDescription?.toString() == text }
    private fun click(node: AccessibilityNodeInfo?) {
        var target = checkNotNull(node)
        while (!target.isClickable && target.parent != null) target = target.parent
        assertTrue(target.performAction(AccessibilityNodeInfo.ACTION_CLICK))
        SystemClock.sleep(250)
    }
    private fun clickText(text: String) { await(text) { findText(text) != null }; click(findText(text)) }
    private fun clickDescription(text: String) { click(findDescription(text)) }
    private fun await(label: String, condition: () -> Boolean) {
        val until = SystemClock.uptimeMillis() + 12000
        while (SystemClock.uptimeMillis() < until) { if (condition()) return; SystemClock.sleep(100) }
        assertTrue(label, condition())
    }
    private fun screenshot(name: String) {
        SystemClock.sleep(1000)
        val directory = File(instrumentation.targetContext.getExternalFilesDir(null), "history-filter-review").apply { mkdirs() }
        val file = File(directory, name)
        instrumentation.uiAutomation.takeScreenshot().let { bitmap ->
            file.outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }
            bitmap.recycle()
        }
        // Gradle uninstalls the target after acceptance, deleting its private
        // external directory. Preserve these requested screenshots for review.
        // UiAutomation executes argv directly, rather than interpreting shell quotes.
        val command = "cp ${file.absolutePath} /sdcard/Download/ponychat-history-$name"
        val output = android.os.ParcelFileDescriptor.AutoCloseInputStream(
            instrumentation.uiAutomation.executeShellCommand(command)).use { it.readBytes().decodeToString() }
        assertTrue("Screenshot export: $output", output.isBlank())
    }
}
