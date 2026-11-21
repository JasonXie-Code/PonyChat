package top.ponychat.webview.ui.images

import android.content.Context
import android.content.ContextWrapper
import android.graphics.Bitmap
import android.os.Bundle
import android.os.SystemClock
import android.view.accessibility.AccessibilityNodeInfo
import androidx.activity.compose.setContent
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import java.util.concurrent.atomic.AtomicInteger
import kotlinx.coroutines.CompletableDeferred
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import top.ponychat.webview.data.model.BooruImage
import top.ponychat.webview.data.model.BooruSearchResponse
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.debug.DialogPreviewActivity
import top.ponychat.webview.ui.theme.PonyChatTheme

@RunWith(AndroidJUnit4::class)
class BooruSearchLoadingInstrumentedTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val automation get() = instrumentation.uiAutomation

    private fun nodes(node: AccessibilityNodeInfo? = automation.rootInActiveWindow): List<AccessibilityNodeInfo> =
        if (node == null) emptyList() else listOf(node) + (0 until node.childCount).flatMap { nodes(node.getChild(it)) }

    private fun await(label: String, predicate: () -> Boolean) {
        repeat(100) {
            if (android.os.Build.VERSION.SDK_INT >= 33) automation.clearCache()
            if (predicate()) return
            SystemClock.sleep(100)
        }
        fail("Timed out: $label")
    }

    private fun click(label: String) {
        var node = nodes().first { it.text?.toString()?.contains(label) == true || it.contentDescription?.toString() == label }
        while (!node.isClickable && node.parent != null) node = node.parent
        assertTrue(node.performAction(AccessibilityNodeInfo.ACTION_CLICK))
    }

    private fun submit(query: String) {
        await("query input") { nodes().any { it.isEditable } }
        val input = nodes().first { it.isEditable }
        assertTrue(input.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, Bundle().apply {
            putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, query)
        }))
        SystemClock.sleep(200)
        click("开始找图")
    }

    @Test fun changedQueryClearsOldResultsDuringLoadingAndAfterFailure() {
        val requests = AtomicInteger()
        val pending = CompletableDeferred<BooruSearchResponse>()
        val failed = CompletableDeferred<BooruSearchResponse>()
        ActivityScenario.launch(DialogPreviewActivity::class.java).use { scenario ->
            scenario.onActivity { activity ->
                val imageFile = File(activity.cacheDir, "booru-loading-fixture.png")
                val bitmap = Bitmap.createBitmap(40, 40, Bitmap.Config.ARGB_8888)
                bitmap.eraseColor(android.graphics.Color.RED)
                imageFile.outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }
                bitmap.recycle()
                val prefs = AppPreferences(object : ContextWrapper(activity) {
                    override fun getSharedPreferences(name: String, mode: Int) =
                        activity.getSharedPreferences("booru-loading-test", Context.MODE_PRIVATE)
                })
                fun response(score: Int) = BooruSearchResponse("ok", listOf("pony"), "safe", "score", 1,
                    hasMore = false, images = listOf(BooruImage("fixture:$score", "Derpibooru",
                        url = "https://derpibooru.org/images/1", imageUrl = imageFile.toURI().toString(),
                        score = score, rating = "safe")))
                activity.setContent {
                    PonyChatTheme(darkTheme = false) {
                        BooruSearchScreen(prefs, {}, searchOverride = {
                            when (requests.incrementAndGet()) {
                                1 -> response(101)
                                2 -> pending.await()
                                else -> failed.await()
                            }
                        })
                    }
                }
                // Complete the second request later, after checking the loading UI.
                secondResponse = response(202)
            }
            submit("旧描述")
            await("old results") { nodes().any { it.text?.contains("101") == true } }
            click("搜索条件")
            submit("新描述")
            await("new search loading") { requests.get() == 2 && nodes().any { it.className == "android.widget.ProgressBar" } }
            assertFalse(nodes().any { it.text?.contains("101") == true })
            assertFalse(nodes().any { it.text?.contains("没有找到结果") == true })
            val screenshot = automation.takeScreenshot()
            val output = File(instrumentation.targetContext.getExternalFilesDir(null), "booru-new-search-loading.png")
            output.outputStream().use { screenshot.compress(Bitmap.CompressFormat.PNG, 100, it) }
            screenshot.recycle()
            pending.complete(checkNotNull(secondResponse))
            await("new results") { nodes().any { it.text?.contains("202") == true } }
            assertFalse(nodes().any { it.text?.contains("101") == true })
            click("搜索条件")
            submit("失败描述")
            await("failed search loading") { requests.get() == 3 && nodes().any { it.className == "android.widget.ProgressBar" } }
            assertFalse(nodes().any { it.text?.contains("202") == true })
            failed.completeExceptionally(IllegalStateException("fixture search failure"))
            await("search error") { nodes().any { it.text?.contains("fixture search failure") == true } }
            assertFalse(nodes().any { it.text?.contains("202") == true })
        }
    }

    private var secondResponse: BooruSearchResponse? = null
}
