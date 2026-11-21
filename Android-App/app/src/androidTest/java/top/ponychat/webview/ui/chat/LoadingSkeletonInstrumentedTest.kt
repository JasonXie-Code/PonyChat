package top.ponychat.webview.ui.chat

import android.graphics.Bitmap
import android.os.SystemClock
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.Modifier
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.positionInWindow
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import top.ponychat.webview.data.model.ConversationSceneResponse
import top.ponychat.webview.debug.DialogPreviewActivity
import top.ponychat.webview.ui.common.*
import top.ponychat.webview.ui.theme.PonyChatTheme
import java.io.File
import java.util.concurrent.CopyOnWriteArrayList

@RunWith(AndroidJUnit4::class)
class LoadingSkeletonInstrumentedTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()

    private fun capture(name: String): Bitmap {
        val bitmap = requireNotNull(instrumentation.uiAutomation.takeScreenshot())
        val dir = requireNotNull(instrumentation.targetContext.getExternalFilesDir(null))
        File(dir, name).outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }
        return bitmap
    }

    @Test fun skeletonAnimatesWithoutChangingLayoutBounds() {
        val bounds = CopyOnWriteArrayList<Pair<Int, Int>>()
        ActivityScenario.launch(DialogPreviewActivity::class.java).use { scenario ->
            scenario.onActivity { activity ->
                activity.setContent {
                    PonyChatTheme {
                        Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
                            Column(Modifier.onGloballyPositioned { bounds.add(it.size.width to it.size.height) }) {
                                Text("加载中的角色列表")
                                SkeletonList(rows = 3)
                                Text("加载中的图片网格")
                                SkeletonGrid(rows = 1)
                            }
                        }
                    }
                }
            }
            SystemClock.sleep(800)
            val first = capture("skeleton-loading-a.png")
            SystemClock.sleep(420)
            val second = capture("skeleton-loading-b.png")
            assertEquals("Animation must not remeasure placeholder bounds", 1, bounds.distinct().size)
            val pixelsA = IntArray(first.width * first.height)
            val pixelsB = IntArray(second.width * second.height)
            first.getPixels(pixelsA, 0, first.width, 0, 0, first.width, first.height)
            second.getPixels(pixelsB, 0, second.width, 0, 0, second.width, second.height)
            assertTrue("Skeleton must visibly animate", pixelsA.indices.count { pixelsA[it] != pixelsB[it] } > 1000)
            first.recycle(); second.recycle()
        }
    }

    @Test fun sceneLoadingToLongContentChangesHeightGraduallyAndStopsOnError() {
        val scene = mutableStateOf<ConversationSceneResponse?>(null)
        val loading = mutableStateOf(true)
        val error = mutableStateOf<String?>(null)
        val positions = CopyOnWriteArrayList<Int>()
        ActivityScenario.launch(DialogPreviewActivity::class.java).use { scenario ->
            scenario.onActivity { activity ->
                activity.setContent {
                    PonyChatTheme {
                        Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
                            Column {
                                SceneStatusContent(scene.value, loading.value, error.value, "fixture", "Jason", "紫悦")
                                Text("下一张卡片", Modifier.onGloballyPositioned {
                                    positions.add(it.positionInWindow().y.toInt())
                                })
                            }
                        }
                    }
                }
            }
            SystemClock.sleep(700)
            capture("scene-skeleton.png").recycle()
            positions.clear()
            scenario.onActivity {
                scene.value = ConversationSceneResponse(revision = 1, fields = mapOf(
                    "scene_time" to "清晨", "location" to "车站",
                    "user_position" to "Jason站在站台上，提着行李箱，等待列车到达。".repeat(4),
                    "character_position" to "紫悦站在长椅旁，面向站台入口，前蹄扶着地图筒。".repeat(4),
                    "contact" to "没有接触", "surroundings" to "雨滴从顶棚落下，广播提醒旅客在黄线后等候。".repeat(4),
                ))
                loading.value = false
            }
            SystemClock.sleep(1100)
            val frames = positions.distinct()
            assertTrue("Content height should animate through intermediate sizes", frames.size > 3)
            val span = frames.max() - frames.min()
            assertTrue("A single layout frame must not jump the full height", frames.zipWithNext().maxOf { kotlin.math.abs(it.second - it.first) } < span)
            capture("scene-loaded.png").recycle()
            scenario.onActivity {
                scene.value = null
                loading.value = false
                error.value = "场景状态读取超时"
            }
            SystemClock.sleep(700)
            capture("scene-loading-error.png").recycle()
            fun texts(node: android.view.accessibility.AccessibilityNodeInfo?): List<String> =
                if (node == null) emptyList() else listOfNotNull(node.text?.toString(), node.contentDescription?.toString()) +
                    (0 until node.childCount).flatMap { texts(node.getChild(it)) }
            val visible = texts(instrumentation.uiAutomation.rootInActiveWindow)
            assertTrue(visible.any { it.contains("场景状态读取超时") })
            assertFalse("Failed request must stop the loading skeleton", visible.any { it == "正在加载" })
        }
    }
}
