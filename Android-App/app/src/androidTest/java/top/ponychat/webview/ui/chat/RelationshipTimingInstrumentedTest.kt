package top.ponychat.webview.ui.chat

import android.app.Application
import android.content.Context
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.os.SystemClock
import android.view.accessibility.AccessibilityNodeInfo
import androidx.activity.compose.setContent
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.lifecycle.viewModelScope
import androidx.test.core.app.ActivityScenario
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import kotlinx.coroutines.cancel
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Test
import top.ponychat.webview.data.api.NetworkClient
import top.ponychat.webview.data.model.Character
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.debug.DialogPreviewActivity
import top.ponychat.webview.ui.theme.PonyChatTheme

/** Opt-in real backend and model acceptance, with isolated account and phone data. */
class RelationshipTimingInstrumentedTest {
    private class TestApplication(base: Context) : Application() {
        private val prefix = "relationship_timing_${System.nanoTime()}_"
        init { attachBaseContext(base) }
        override fun getApplicationContext(): Context = this
        override fun getSharedPreferences(name: String, mode: Int) = super.getSharedPreferences(prefix + name, mode)
        override fun getFilesDir(): File = File(super.getFilesDir(), prefix).also { it.mkdirs() }
        override fun checkSelfPermission(permission: String) = PackageManager.PERMISSION_DENIED
        override fun checkPermission(permission: String, pid: Int, uid: Int) = PackageManager.PERMISSION_DENIED
    }

    @Test fun measureRealRelationshipLoads() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        assumeTrue(InstrumentationRegistry.getArguments().getString("relationshipTiming") == "true")
        val context = instrumentation.targetContext
        val account = JSONObject(File(context.getExternalFilesDir(null), "relationship-benchmark-account.json").readText())
        val base = "http://127.0.0.1:61923/"
        val connection = URL(base + "api/auth/login").openConnection() as HttpURLConnection
        connection.requestMethod = "POST"
        connection.setRequestProperty("Content-Type", "application/json")
        connection.doOutput = true
        connection.outputStream.use { it.write(JSONObject().put("username", account.getString("username"))
            .put("password", account.getString("password")).toString().toByteArray()) }
        assertEquals(200, connection.responseCode)
        val token = JSONObject(connection.inputStream.bufferedReader().use { it.readText() }).getString("auth_token")
        connection.disconnect()
        val app = TestApplication(context.applicationContext)
        val prefs = AppPreferences(app).apply {
            username = account.getString("username")
            authToken = token
            debugMode = true
            activeApiBase = base
        }
        NetworkClient.bindPreferences(prefs)
        val results = JSONArray()
        val output = File(context.getExternalFilesDir(null), "relationship-qa").apply { mkdirs() }
        var vm: ChatViewModel? = null
        val scenario = ActivityScenario.launch(DialogPreviewActivity::class.java)
        try {
            scenario.onActivity { host ->
                val model = ChatViewModel(app)
                vm = model
                host.setContent {
                    val state by model.state.collectAsState()
                    PonyChatTheme(darkTheme = true) {
                        state.character?.let { character ->
                            ChatRelationshipPanel(character, prefs, state, { model.loadRelationshipSnapshot(force = true) })
                        }
                    }
                }
            }
            fun measure(label: String, first: Boolean = false, cold: Boolean = false, refresh: Boolean = false) {
                val model = requireNotNull(vm)
                val previous = model._state.value.relationshipSnapshot?.pageUpdatedAtMs ?: 0L
                val started = SystemClock.elapsedRealtime()
                scenario.onActivity {
                    if (!refresh) model._state.value = ChatUiState(
                        character = Character(account.getString(if (first) "first_character_id" else if (cold) "cold_character_id" else "character_id"), "青禾"),
                        conversationId = account.getString(if (first) "first_conversation_id" else if (cold) "cold_conversation_id" else "conversation_id")
                    )
                    model.loadRelationshipSnapshot(force = refresh)
                }
                while (model._state.value.isLoadingRelationshipSnapshot && SystemClock.elapsedRealtime() - started < 40000) {
                    SystemClock.sleep(20)
                }
                fun containsText(node: AccessibilityNodeInfo?, text: String): Boolean {
                    if (node == null) return false
                    if (node.text?.toString() == text) return true
                    return (0 until node.childCount).any { containsText(node.getChild(it), text) }
                }
                val overview = model._state.value.relationshipSnapshot?.pageContent?.overview
                if (!overview.isNullOrBlank()) {
                    while (!containsText(instrumentation.uiAutomation.rootInActiveWindow, overview) &&
                        SystemClock.elapsedRealtime() - started < 40000) SystemClock.sleep(20)
                    assertTrue(containsText(instrumentation.uiAutomation.rootInActiveWindow, overview))
                }
                val elapsed = SystemClock.elapsedRealtime() - started
                val state = model._state.value
                results.put(JSONObject().put("label", label).put("elapsed_ms", elapsed)
                    .put("error", state.relationshipSnapshotError ?: JSONObject.NULL)
                    .put("has_page", state.relationshipSnapshot?.pageContent != null)
                    .put("updated_at_ms", state.relationshipSnapshot?.pageUpdatedAtMs ?: 0))
                File(output, "relationship-real-timing.json").writeText(results.toString(2))
                instrumentation.uiAutomation.takeScreenshot().let { bitmap ->
                    File(output, "real-$label.png").outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }
                    bitmap.recycle()
                }
                assertNull(state.relationshipSnapshotError)
                assertNotNull(state.relationshipSnapshot?.pageContent)
                if (refresh) assertTrue((state.relationshipSnapshot?.pageUpdatedAtMs ?: 0) > previous)
            }
            measure("first-round", first = true)
            measure("after-15-rounds-first-open", cold = true)
            measure("after-15-rounds")
            measure("refresh", refresh = true)
        } finally {
            scenario.onActivity { it.setContent {}; vm?.viewModelScope?.cancel() }
            scenario.close()
            NetworkClient.bindPreferences(AppPreferences(context))
        }
    }
}
