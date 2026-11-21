package top.ponychat.webview

import android.os.SystemClock
import androidx.activity.compose.setContent
import androidx.compose.material3.Text
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.test.core.app.ActivityScenario
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Test
import top.ponychat.webview.debug.DialogPreviewActivity
import top.ponychat.webview.ui.theme.PonyChatTheme

class RapidNavigationInstrumentedTest {
    private val instrument = InstrumentationRegistry.getInstrumentation()

    private fun withNavigation(check: (NavHostController) -> Unit) {
        lateinit var nav: NavHostController
        ActivityScenario.launch(DialogPreviewActivity::class.java).use { scenario ->
            scenario.onActivity { activity -> activity.setContent { PonyChatTheme {
                nav = rememberNavController()
                NavHost(nav, startDestination = "home") {
                    composable("home") { Text("首页") }
                    composable("creation") { Text("创造模式") }
                    composable("chat") { Text("普通对话") }
                    composable("settings") { Text("设置页面") }
                }
            } } }
            instrument.waitForIdleSync()
            scenario.onActivity { check(nav) }
            SystemClock.sleep(500)
            scenario.onActivity { assertNotNull("Navigation must keep a visible destination", nav.currentDestination) }
        }
    }

    @Test fun repeatedBackThenSettingsDoesNotEmptyTheStack() = withNavigation { nav ->
        for (route in listOf("creation", "chat")) repeat(20) {
            nav.navigate(route)
            val leaving = requireNotNull(nav.currentBackStackEntry)
            assertTrue(nav.popPage(leaving))
            assertFalse("Outgoing back callback must not pop home", nav.popPage(leaving))
            nav.navigate("settings")
            assertFalse("Outgoing back callback must not pop newly opened settings", nav.popPage(leaving))
            assertEquals("settings", nav.currentDestination?.route)
            val settings = requireNotNull(nav.currentBackStackEntry)
            assertTrue(nav.popPage(settings))
            assertFalse(nav.popPage(settings))
            assertEquals("home", nav.currentDestination?.route)
        }
    }

    @Test fun staleBackCannotPopAnotherVisitToTheSameRoute() = withNavigation { nav ->
        nav.navigate("creation")
        val old = requireNotNull(nav.currentBackStackEntry)
        assertTrue(nav.popPage(old))
        nav.navigate("creation")
        val current = requireNotNull(nav.currentBackStackEntry)
        assertNotSame(old, current)
        assertFalse(nav.popPage(old))
        assertSame(current, nav.currentBackStackEntry)
    }

    @Test fun rootDestinationCannotBeRemovedByAPageBackCallback() = withNavigation { nav ->
        val root = requireNotNull(nav.currentBackStackEntry)
        assertFalse(nav.popPage(root))
        assertEquals("home", nav.currentDestination?.route)
    }
}
