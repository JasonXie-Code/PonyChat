package top.ponychat.webview.ui.chat

import android.content.Intent
import android.net.Uri
import android.util.Base64
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class PreviewImageShareInstrumentedTest {
    @Test
    fun sharesOriginalGifThroughReadOnlyContentUri() = runBlocking {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val bytes = Base64.decode("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7", Base64.DEFAULT)
        val intent = createPreviewImageShareIntent(context,
            "data:image/gif;base64," + Base64.encodeToString(bytes, Base64.NO_WRAP))!!
        assertEquals(Intent.ACTION_SEND, intent.action)
        assertEquals("image/gif", intent.type)
        val uri = intent.getParcelableExtra<Uri>(Intent.EXTRA_STREAM)!!
        assertEquals("content", uri.scheme)
        assertEquals("${context.packageName}.fileprovider", uri.authority)
        assertTrue(uri.path!!.contains("shared-preview-images"))
        assertEquals(uri, intent.clipData!!.getItemAt(0).uri)
        assertTrue(intent.flags and Intent.FLAG_GRANT_READ_URI_PERMISSION != 0)
        assertEquals(0, intent.flags and Intent.FLAG_GRANT_WRITE_URI_PERMISSION)
        assertArrayEquals(bytes, context.contentResolver.openInputStream(uri)!!.use { it.readBytes() })
        assertNull(intent.component)
    }
}
