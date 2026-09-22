package top.ponychat.webview.ui.character

import android.app.Application
import android.content.Context
import android.graphics.Bitmap
import android.graphics.Rect
import android.os.SystemClock
import android.view.InputDevice
import android.view.MotionEvent
import android.view.ViewConfiguration
import android.view.accessibility.AccessibilityNodeInfo
import androidx.activity.compose.setContent
import androidx.compose.material3.SnackbarHostState
import androidx.compose.runtime.CompositionLocalProvider
import androidx.lifecycle.ViewModelProvider
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import java.net.ServerSocket
import kotlin.concurrent.thread
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.debug.DialogPreviewActivity
import top.ponychat.webview.ui.theme.PonyChatTheme

/** Exercises the production list, gesture arbitration and repository on an emulator. */
@RunWith(AndroidJUnit4::class)
class ManualCharacterSortInstrumentedTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val automation get() = instrumentation.uiAutomation
    private val output get() = File(instrumentation.targetContext.getExternalFilesDir(null), "manual-sort-qa").apply { mkdirs() }
    @Volatile private var selected = ""
    @Volatile private var saved = JSONArray()
    @Volatile private var saves = 0
    private var checkGesture: () -> Unit = {}

    private fun nodes(root: AccessibilityNodeInfo? = automation.rootInActiveWindow): List<AccessibilityNodeInfo> =
        if (root == null) emptyList() else listOf(root) + (0 until root.childCount).flatMap { nodes(root.getChild(it)) }

    private fun bounds(name: String): Rect {
        val node = nodes().firstOrNull { it.text?.toString() == name }
        assertNotNull("Missing $name: ${nodes().mapNotNull { it.text }}", node)
        return Rect().also { node!!.getBoundsInScreen(it) }
    }

    private fun await(label: String, predicate: () -> Boolean) {
        repeat(100) { if (predicate()) return; SystemClock.sleep(100) }
        fail("Timed out: $label")
    }

    private fun screenshot(name: String) {
        val bitmap = automation.takeScreenshot()
        File(output, "$name.png").outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }
        bitmap.recycle()
    }

    private fun shell(command: String): String = automation.executeShellCommand(command).use {
        android.os.ParcelFileDescriptor.AutoCloseInputStream(it).bufferedReader().readText()
    }

    private fun sortHaptics(): Int = shell("dumpsys vibrator_manager").lineSequence()
        .count { "top.ponychat.webview" in it && "original: Step=55ms" in it }

    private fun touch(action: Int, x: Float, y: Float, down: Long) {
        val event = MotionEvent.obtain(down, SystemClock.uptimeMillis(), action, x, y, 0)
        event.source = InputDevice.SOURCE_TOUCHSCREEN
        assertTrue("Touch injection", automation.injectInputEvent(event, true))
        event.recycle()
    }

    private fun drag(name: String, target: String, hold: Boolean = true, capture: Boolean = false) {
        val density = instrumentation.targetContext.resources.displayMetrics.density
        val x = 41f * density // Center of the production 50dp avatar, after its 16dp inset.
        val start = bounds(name).centerY().toFloat() + 12f * density
        val end = bounds(target).centerY().toFloat() + 12f * density
        val down = SystemClock.uptimeMillis()
        touch(MotionEvent.ACTION_DOWN, x, start, down)
        SystemClock.sleep(if (hold) ViewConfiguration.getLongPressTimeout().toLong() + 200 else 30)
        if (capture) {
            screenshot("02-long-press")
            File(output, "vibrator-after-long-press.txt").writeText(shell("dumpsys vibrator_manager"))
        }
        for (step in 1..24) {
            touch(MotionEvent.ACTION_MOVE, x, start + (end - start) * step / 24, down)
            checkGesture()
            SystemClock.sleep(18)
        }
        if (capture) screenshot("03-dragging")
        touch(MotionEvent.ACTION_UP, x, end, down)
        SystemClock.sleep(400)
    }

    @Test fun longPressDragSaveReloadAndGestureBoundaries() {
        val context = instrumentation.targetContext
        val rawPrefs = context.getSharedPreferences("ponychat_prefs", Context.MODE_PRIVATE)
        val original = rawPrefs.all
        val server = ServerSocket(0)
        saved = JSONArray((1..12).map { JSONObject().put("id", "sort-qa-$it").put("name", "Sort Pony %02d".format(it))
            .put("description", "Manual sorting acceptance fixture") })
        thread(isDaemon = true) {
            while (!server.isClosed) {
                try {
                    server.accept().use { socket ->
                        val input = socket.getInputStream().buffered()
                        fun line(): String {
                            val bytes = ArrayList<Byte>()
                            while (true) { val b = input.read(); if (b < 0 || b == 10) break; if (b != 13) bytes.add(b.toByte()) }
                            return bytes.toByteArray().toString(Charsets.UTF_8)
                        }
                        val request = line()
                        var length = 0
                        while (true) {
                            val header = line(); if (header.isBlank()) break
                            if (header.startsWith("Content-Length:", true)) length = header.substringAfter(':').trim().toInt()
                        }
                        val body = ByteArray(length)
                        var read = 0
                        while (read < length) { val n = input.read(body, read, length - read); if (n < 0) break; read += n }
                        if (request.contains("/api/save_characters")) {
                            saved = JSONObject(body.toString(Charsets.UTF_8)).getJSONArray("characters")
                            saves++
                        }
                        val payload = if (request.contains("/api/load_characters")) JSONObject().put("characters", saved).put("success", true).toString()
                            else """{"success":true,"conversations":[],"messages":[]}"""
                        val bytes = payload.toByteArray()
                        socket.getOutputStream().apply {
                            write("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: ${bytes.size}\r\nConnection: close\r\n\r\n".toByteArray())
                            write(bytes); flush()
                        }
                    }
                } catch (_: Exception) { if (server.isClosed) break }
            }
        }
        var scenario: ActivityScenario<DialogPreviewActivity>? = null
        try {
            val prefs = AppPreferences(context).apply {
                username = "manual-sort-emulator-fixture"
                authToken = ""
                debugMode = true
                activeApiBase = "http://127.0.0.1:${server.localPort}/"
                lanUrl = activeApiBase
                wanUrl = activeApiBase
                characterSort = "manual"
                pinnedCharacterIds = emptySet()
                chatMode = "normal"
            }
            lateinit var model: CharacterViewModel
            scenario = ActivityScenario.launch(DialogPreviewActivity::class.java)
            scenario.onActivity { host ->
                model = ViewModelProvider(host, ViewModelProvider.AndroidViewModelFactory(context.applicationContext as Application))[CharacterViewModel::class.java]
                host.setContent { CompositionLocalProvider(top.ponychat.webview.CustomToast provides SnackbarHostState()) { PonyChatTheme(darkTheme = true) {
                    CharacterListScreen(model, prefs, onCharacterSelected = { c, _ -> selected = c.stableId() }, onNavigateToSettings = {})
                } } }
            }
            await("loaded roles") { nodes().any { it.text?.toString() == "Sort Pony 04" } }
            SystemClock.sleep(1200)
            screenshot("01-before")
            File(output, "vibrator-before.txt").writeText(shell("dumpsys vibrator_manager"))
            val hapticsBefore = sortHaptics()
            checkGesture = { assertFalse("Drag must not activate refresh", model.state.value.isRefreshingAllChats) }
            drag("Sort Pony 01", "Sort Pony 03", capture = true)
            await("first role moved below third") { model.state.value.characters.indexOfFirst { it.id == "sort-qa-1" } == 2 }
            assertEquals("Drag must not open chat", "", selected)
            assertFalse("Drag must not activate refresh", model.state.value.isRefreshingAllChats)
            await("saved order") { saves > 0 && saved.getJSONObject(2).getString("id") == "sort-qa-1" }
            assertEquals("One 55ms vibration at long-press activation", hapticsBefore + 1, sortHaptics())
            screenshot("04-after-down")
            scenario.onActivity { model.loadMyCharacters() }
            await("reload complete") { !model.state.value.isLoading }
            SystemClock.sleep(400)
            assertTrue("Reload keeps visual order", bounds("Sort Pony 03").top < bounds("Sort Pony 01").top)
            screenshot("05-after-reload")
            drag("Sort Pony 01", "Sort Pony 02")
            await("upward reorder") { model.state.value.characters.first().id == "sort-qa-1" }
            SystemClock.sleep(1100)
            screenshot("06-after-up")

            // A quick swipe must scroll, without reordering or opening chat.
            val beforeSwipe = model.state.value.characters.map { it.id }
            drag("Sort Pony 04", "Sort Pony 02", hold = false)
            assertEquals(beforeSwipe, model.state.value.characters.map { it.id })
            assertEquals("", selected)

            // Recreate the screen to reset scroll, and verify ordinary avatar taps.
            scenario.recreate()
            scenario.onActivity { host -> host.setContent { CompositionLocalProvider(top.ponychat.webview.CustomToast provides SnackbarHostState()) { PonyChatTheme(darkTheme = true) {
                CharacterListScreen(model, prefs, onCharacterSelected = { c, _ -> selected = c.stableId() }, onNavigateToSettings = {})
            } } } }
            await("recreated list") { nodes().any { it.text?.toString() == "Sort Pony 01" } }
            SystemClock.sleep(400)
            val density = context.resources.displayMetrics.density
            val tapY = bounds("Sort Pony 01").centerY() + 12f * density
            val down = SystemClock.uptimeMillis()
            touch(MotionEvent.ACTION_DOWN, 41f * density, tapY, down)
            SystemClock.sleep(40)
            touch(MotionEvent.ACTION_UP, 41f * density, tapY, down)
            await("avatar tap opens role") { selected == "sort-qa-1" }
            selected = ""

            scenario.onActivity { model.setCharacterSort("name") }
            SystemClock.sleep(400)
            val beforeAutomatic = model.state.value.characters.map { it.id }
            val hapticsBeforeAutomatic = sortHaptics()
            drag("Sort Pony 04", "Sort Pony 02")
            assertEquals("Name sorting cannot reorder", beforeAutomatic, model.state.value.characters.map { it.id })
            assertEquals("Name sorting does not trigger sort haptics", hapticsBeforeAutomatic, sortHaptics())
            screenshot("07-name-sort")
            File(output, "result.txt").writeText("PASS: long press, downward drag at list top without refresh, upward drag, save/reload, quick swipe, avatar tap, automatic-sort boundary.\n")
        } finally {
            scenario?.close()
            server.close()
            rawPrefs.edit().clear().apply {
                original.forEach { (key, value) -> when (value) {
                    is String -> putString(key, value)
                    is Boolean -> putBoolean(key, value)
                    is Int -> putInt(key, value)
                    is Long -> putLong(key, value)
                    is Float -> putFloat(key, value)
                    is Set<*> -> { @Suppress("UNCHECKED_CAST") putStringSet(key, value as Set<String>) }
                } }
            }.commit()
        }
    }
}
