package top.ponychat.webview.ui.chat

import android.graphics.Bitmap
import android.os.SystemClock
import androidx.activity.compose.setContent
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.graphics.toArgb
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertEquals
import org.junit.Test
import org.junit.runner.RunWith
import top.ponychat.webview.debug.DialogPreviewActivity
import top.ponychat.webview.ui.theme.PonyChatTheme
import java.io.File

@RunWith(AndroidJUnit4::class)
class ImagePreviewThemeInstrumentedTest {
    @Test fun lightAndDarkViewerUseThemeBackground() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        for (dark in listOf(false, true)) {
            var expected = 0
            ActivityScenario.launch(DialogPreviewActivity::class.java).use { scenario ->
                scenario.onActivity { activity ->
                    activity.setContent {
                        PonyChatTheme(darkTheme = dark) {
                            expected = MaterialTheme.colorScheme.background.toArgb()
                            ChatScreenImagePreviewOverlay(
                                previewImageUrl = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7",
                                previewImages = emptyList(), previewIndex = 0, onDismiss = {},
                                coroutineScope = rememberCoroutineScope(), context = activity,
                            )
                        }
                    }
                }
                instrumentation.waitForIdleSync()
                SystemClock.sleep(3000)
                val bitmap = instrumentation.uiAutomation.takeScreenshot()
                File(instrumentation.targetContext.getExternalFilesDir(null),
                    "image-preview-${if (dark) "dark" else "light"}.png").outputStream().use {
                    bitmap.compress(Bitmap.CompressFormat.PNG, 100, it)
                }
                assertEquals("Viewer background dark=$dark", expected,
                    bitmap.getPixel(bitmap.width / 2, bitmap.height / 5))
                bitmap.recycle()
            }
        }
    }
}
