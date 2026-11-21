package top.ponychat.webview.ui.chat

import android.app.Application
import android.content.Context
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.os.SystemClock
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.runtime.*
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewModelScope
import androidx.test.core.app.ActivityScenario
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.cancel
import org.junit.Assert.assertTrue
import org.junit.Test
import top.ponychat.webview.data.model.Character
import top.ponychat.webview.data.model.Message
import top.ponychat.webview.debug.DialogPreviewActivity
import top.ponychat.webview.ui.theme.PonyChatTheme
import top.ponychat.webview.ui.theme.DarkBackground
import java.io.File
import kotlin.math.abs

/** Real input host + list compensation + auto-follow, with isolated synthetic messages. */
class QuoteInputLayoutInstrumentedTest {
    private class TestApplication(base: Context) : Application() {
        private val prefix = "quote_layout_${System.nanoTime()}_"
        init { attachBaseContext(base) }
        override fun getApplicationContext(): Context = this
        override fun getSharedPreferences(name: String, mode: Int) = super.getSharedPreferences(prefix + name, mode)
        override fun getFilesDir(): File = File(super.getFilesDir(), prefix).also { it.mkdirs() }
        override fun checkSelfPermission(permission: String) = PackageManager.PERMISSION_DENIED
        override fun checkPermission(permission: String, pid: Int, uid: Int) = PackageManager.PERMISSION_DENIED
    }

    @Test fun quoteOpensAndClosesWithoutExtraGap() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val app = TestApplication(instrumentation.targetContext)
        lateinit var model: ChatViewModel
        lateinit var list: LazyListState
        var density = 1f
        val inputTop = mutableFloatStateOf(0f)
        val lastBottom = mutableFloatStateOf(0f)
        val effectiveEnd = mutableIntStateOf(Int.MAX_VALUE)
        val listTop = mutableFloatStateOf(0f)
        val inputHeight = mutableFloatStateOf(0f)
        val ready = mutableStateOf(false)
        val ime = mutableIntStateOf(0)
        val character = Character(id = "quote-layout", name = "布局测试")
        val messages = (0 until 12).map { Message(id = "quote-$it", messageId = "quote-$it",
            role = "assistant", content = "这是第 $it 条布局测试消息。引用后消息与输入栏之间应只保留正常间距。") }
        ActivityScenario.launch(DialogPreviewActivity::class.java).use { scenario ->
            scenario.onActivity { activity ->
                model = ChatViewModel(app)
                model._state.value = ChatUiState(character = character, conversationId = "quote-layout",
                    mode = "normal", messages = messages, isLoadingHistory = false, hasMoreHistory = false)
                activity.setContent {
                    PonyChatTheme {
                        val state by model.state.collectAsState()
                        list = rememberLazyListState(initialFirstVisibleItemIndex = messages.lastIndex)
                        density = LocalDensity.current.density
                        val history = remember { mutableStateOf(false) }
                        val touching = remember { mutableStateOf(false) }
                        val suppressed = remember { mutableStateOf(false) }
                        val proximity = remember { ChatTailProximity() }
                        val threshold = with(LocalDensity.current) { ChatAutoFollowTailDistance.toPx() }
                        val near = remember { derivedStateOf { proximity.isNearBottom(list, threshold, effectiveEnd.intValue) } }
                        val scope = rememberCoroutineScope()
                        val picker = rememberLauncherForActivityResult(ActivityResultContracts.PickVisualMedia()) {}
                        val zero = remember { mutableIntStateOf(0) }
                        val no = remember { mutableStateOf(false) }
                        NormalChatAutoFollow(list, state, near, history, touching, suppressed,
                            effectiveEnd, with(LocalDensity.current) { 8.dp.roundToPx() }, 2f * density, ready.value)
                        ChatScreenScaffoldMain(
                            viewModel = model, character = character, prefs = model.prefs, state = state,
                            listState = list, imeBottomState = ime, imeTargetBottomState = ime,
                            imeAnimatingState = no, pendingAnimationIds = remember { mutableSetOf() },
                            lastAILayoutBottomPx = lastBottom, lazyColumnTopPx = listTop,
                            inputBarLayoutTopPx = inputTop, inputBarHeightPx = inputHeight,
                            listEffectiveViewportEndPxState = effectiveEnd, userScrolledUpState = history,
                            listTouchActiveState = touching, listAutoFollowSuppressedState = suppressed,
                            capsuleHeightPxState = zero, voiceBridge = null, showDisplaySettingsState = no,
                            pendingImages = remember { mutableStateListOf() }, currentFontScale = 1f,
                            currentShowTimestamp = false, galgameScore = null, showGalgameCapsuleAndBar = false,
                            isGalgameBroken = false, showLoadingOverlay = false, bottomInsetOverlayActiveState = no,
                            coroutineScope = scope, context = activity, showPrompt = {}, onNavigateBack = {},
                            onNavigateToEditCharacter = {}, onNavigateToCharacterProfile = {}, characterHome = {},
                            onNavigateToSettings = {}, onNavigateToProactiveTasks = {}, onNavigateToHistory = {},
                            awaitImeNotAnimating = {}, imagePickerLauncher = picker, onPickCamera = {},
                            isCompanionActive = false, isAgentCompanionActive = false, isAgentAutoLooping = false,
                            onOpenImagePreview = { _, _, _ -> }, onOpenVitalsPanel = {},
                        )
                        LaunchedEffect(Unit) {
                            kotlinx.coroutines.delay(500)
                            chatScrollToBottomAndRepair(list, messages.last().stableChatItemKey(),
                                (8 * density).toInt(), 2 * density, "quote-test-initial", effectiveViewportEndOffsetPx = effectiveEnd.intValue)
                            ready.value = true
                        }
                    }
                }
            }
            fun gap(): Float {
                var top = 0
                scenario.onActivity { top = inputTop.floatValue.toInt() }
                // Parent graphicsLayer movement does not always dispatch child position
                // callbacks. Measure rendered pixels, not the cached bubble coordinate.
                val bitmap = instrumentation.uiAutomation.takeScreenshot()
                var y = (top - 1).coerceIn(0, bitmap.height - 1)
                val edge = y
                // Skip the input surface's antialiased boundary pixel.
                while (y > 0 && edge - y < 4 * density &&
                    bitmap.getPixel(bitmap.width / 2, y) != DarkBackground.toArgb()) y--
                val start = y
                while (y > 0 && bitmap.getPixel(bitmap.width / 2, y) == DarkBackground.toArgb()) y--
                bitmap.recycle()
                return (start - y) / density
            }
            fun screenshot(name: String) {
                val bitmap = instrumentation.uiAutomation.takeScreenshot()
                File(instrumentation.targetContext.getExternalFilesDir(null), name).outputStream().use {
                    bitmap.compress(Bitmap.CompressFormat.PNG, 100, it)
                }
                bitmap.recycle()
            }
            SystemClock.sleep(1800)
            val baseline = gap()
            assertTrue("Initial rendered gap=$baseline", baseline in 4f..16f)
            screenshot("quote-before.png")
            for (keyboardHeightDp in listOf(0, 240)) {
                scenario.onActivity { ime.intValue = (keyboardHeightDp * density).toInt() }
                SystemClock.sleep(500)
                assertTrue("Keyboard compensation gap=${gap()} baseline=$baseline", abs(gap() - baseline) <= 4f)
                repeat(3) { cycle ->
                scenario.onActivity { model.quoteMessage(messages.last()) }
                SystemClock.sleep(1000)
                val openGap = gap()
                screenshot("quote-open-$keyboardHeightDp.png")
                if (keyboardHeightDp == 0) screenshot("quote-open.png")
                println("QUOTE_LAYOUT keyboard=$keyboardHeightDp cycle=$cycle baseline=$baseline open=$openGap")
                assertTrue("Quote opened gap=$openGap baseline=$baseline", abs(openGap - baseline) <= 4f)
                scenario.onActivity { model.clearQuotedMessage() }
                SystemClock.sleep(700)
                val closedGap = gap()
                println("QUOTE_LAYOUT keyboard=$keyboardHeightDp cycle=$cycle closed=$closedGap")
                assertTrue("Quote closed gap=$closedGap baseline=$baseline", abs(closedGap - baseline) <= 4f)
            }
            }
            scenario.onActivity { model.viewModelScope.cancel() }
        }
    }
}
