package top.ponychat.webview.ui.chat

import android.graphics.Bitmap
import android.os.SystemClock
import android.view.accessibility.AccessibilityNodeInfo
import androidx.activity.compose.setContent
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import top.ponychat.webview.data.model.ConversationSceneResponse
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.debug.DialogPreviewActivity
import top.ponychat.webview.ui.theme.PonyChatTheme
import java.io.File
import java.io.FileOutputStream

/** Shows the real settings screen with a complex synthetic scene for visual QA. */
@RunWith(AndroidJUnit4::class)
class ConversationSceneSettingsInstrumentedTest {
    @Test
    fun sceneFieldsRenderInConversationSettings() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        ActivityScenario.launch(DialogPreviewActivity::class.java).use { scenario ->
            scenario.onActivity { activity ->
                val prefs = AppPreferences(activity)
                activity.setContent {
                    PonyChatTheme {
                        ChatDisplaySettingsScreen(
                            prefs = prefs,
                            onDismiss = {},
                            onSave = {},
                            currentMode = "normal",
                            currentCharacterId = "twilight",
                            debugConversationId = "scene-preview",
                            sceneUserName = "Jason",
                            sceneCharacterName = "紫悦",
                            scenePreview = ConversationSceneResponse(
                                revision = 7,
                                fields = mapOf(
                                    "scene_time" to "第二天清晨，列车发车前十分钟",
                                    "interaction_mode" to "virtual_roleplay",
                                    "location" to "小马镇车站东侧的有顶站台，靠近第三节车厢入口",
                                    "user_position" to "Jason站在黄线后方，左手提着行李箱，面向紫悦",
                                    "character_position" to "紫悦站在长椅旁，身体转向你，前蹄扶着地图筒",
                                    "contact" to "Jason与紫悦没有持续身体接触",
                                    "surroundings" to "顶棚仍有雨滴落下，电子牌显示列车延误十五分钟；广播提醒旅客留在黄线后方",
                                    "item:行李箱" to "Jason持有，放在左侧地面；箱内物品未确认",
                                    "item:地图筒" to "紫悦持有，前蹄扶着，筒口封好",
                                    "item:车票" to "Jason持有，尚未检票",
                                ),
                            ),
                        )
                    }
                }
            }
            instrumentation.waitForIdleSync()
            instrumentation.uiAutomation.executeShellCommand("input swipe 520 800 520 550 400").close()
            SystemClock.sleep(800)
            lateinit var outputDir: File
            scenario.onActivity { activity ->
                outputDir = requireNotNull(activity.getExternalFilesDir(null))
            }
            captureScreenshot(instrumentation, File(outputDir, "scene-settings-complex-top.png"))
            instrumentation.uiAutomation.executeShellCommand("input swipe 520 1700 520 700 450").close()
            SystemClock.sleep(700)
            captureScreenshot(instrumentation, File(outputDir, "scene-settings-complex-bottom.png"))
        }
    }

    @Test
    fun emptySceneFinishesWithoutRefreshOrLoading() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        ActivityScenario.launch(DialogPreviewActivity::class.java).use { scenario ->
            scenario.onActivity { activity ->
                val prefs = AppPreferences(activity)
                activity.setContent {
                    PonyChatTheme {
                        ChatDisplaySettingsScreen(
                            prefs = prefs,
                            onDismiss = {},
                            onSave = {},
                            currentMode = "normal",
                            currentCharacterId = "twilight",
                            debugConversationId = "scene-empty-preview",
                            sceneUserName = "Jason",
                            sceneCharacterName = "紫悦",
                            scenePreview = ConversationSceneResponse(),
                        )
                    }
                }
            }
            instrumentation.waitForIdleSync()
            var visibleTexts = collectTexts(instrumentation.uiAutomation.rootInActiveWindow)
            repeat(4) {
                if (visibleTexts.any { it.contains("暂无已确认的场景状态") }) return@repeat
                instrumentation.uiAutomation.executeShellCommand("input swipe 520 1500 520 1000 350").close()
                SystemClock.sleep(500)
                visibleTexts = collectTexts(instrumentation.uiAutomation.rootInActiveWindow)
            }
            assertTrue(visibleTexts.any { it.contains("暂无已确认的场景状态") })
            assertTrue(visibleTexts.none { it.contains("正在读取场景状态") || it.contains("刷新场景状态") })
            lateinit var outputDir: File
            scenario.onActivity { activity -> outputDir = requireNotNull(activity.getExternalFilesDir(null)) }
            captureScreenshot(instrumentation, File(outputDir, "scene-settings-empty.png"))
        }
    }

    @Test
    fun liveSceneCardHasNoManualRefresh() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        ActivityScenario.launch(DialogPreviewActivity::class.java).use { scenario ->
            scenario.onActivity { activity ->
                val prefs = AppPreferences(activity)
                activity.setContent {
                    PonyChatTheme {
                        SceneStatusCard(prefs, "twilight", "scene-network-preview", "Jason", "紫悦")
                    }
                }
            }
            instrumentation.waitForIdleSync()
            var visibleTexts = collectTexts(instrumentation.uiAutomation.rootInActiveWindow)
            repeat(6) {
                if (visibleTexts.any { it.contains("当前场景") }) return@repeat
                SystemClock.sleep(500)
                visibleTexts = collectTexts(instrumentation.uiAutomation.rootInActiveWindow)
            }
            assertTrue(visibleTexts.any { it.contains("当前场景") })
            assertTrue(visibleTexts.none { it.contains("刷新场景状态") })
        }
    }

    private fun collectTexts(node: AccessibilityNodeInfo?): List<String> {
        if (node == null) return emptyList()
        val texts = mutableListOf<String>()
        node.text?.toString()?.let(texts::add)
        node.contentDescription?.toString()?.let(texts::add)
        for (index in 0 until node.childCount) texts += collectTexts(node.getChild(index))
        return texts
    }

    private fun captureScreenshot(
        instrumentation: android.app.Instrumentation,
        output: File,
    ) {
        for (attempt in 0 until 8) {
            val image = instrumentation.uiAutomation.takeScreenshot()
            FileOutputStream(output).use { image.compress(Bitmap.CompressFormat.PNG, 100, it) }
            image.recycle()
            if (output.length() > 50_000) break
            SystemClock.sleep(500)
        }
        assertTrue(output.length() > 50_000)
    }
}
