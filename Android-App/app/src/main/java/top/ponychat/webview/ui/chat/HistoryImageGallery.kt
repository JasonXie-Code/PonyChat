package top.ponychat.webview.ui.chat

import android.content.Context
import androidx.compose.runtime.*
import androidx.compose.ui.platform.LocalContext
import top.ponychat.webview.data.model.SearchMessageResult

/** Snapshot the displayed results so paging cannot move an open preview. */
internal class HistoryImageGallery(private val context: Context) {
    private var images by mutableStateOf<List<String>>(emptyList())
    private var selected by mutableStateOf<Int?>(null)

    fun open(messages: List<SearchMessageResult>, message: SearchMessageResult, url: String) {
        val entries = messages.flatMap { row -> row.historyImageUrls(context).map { row.messageId to it } }
        val index = entries.indexOfFirst { it.first == message.messageId && it.second == url }
        if (index < 0) return
        images = entries.map { it.second }
        selected = index
    }

    @Composable
    fun Preview() {
        val scope = rememberCoroutineScope()
        selected?.let { index ->
            ChatScreenImagePreviewOverlay(images[index], images, index,
                onDismiss = { selected = null }, coroutineScope = scope, context = context)
        }
    }
}

@Composable
internal fun rememberHistoryImageGallery(): HistoryImageGallery {
    val context = LocalContext.current
    return remember(context) { HistoryImageGallery(context) }
}
