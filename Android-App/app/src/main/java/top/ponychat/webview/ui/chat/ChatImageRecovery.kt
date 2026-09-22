package top.ponychat.webview.ui.chat

import android.content.Context
import android.content.SharedPreferences
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.repeatOnLifecycle
import kotlinx.coroutines.delay
import top.ponychat.webview.data.model.MessageAttachment
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.data.repo.WebImageReceiver

/** Receipts can be saved by history/SSE while this unchanged message is still composed. */
@Composable
internal fun rememberResolvedChatImageUrl(url: String): String {
    if (!url.startsWith("/chat_images/")) return url
    val context = LocalContext.current
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    var resolved by remember(context, url) {
        mutableStateOf(localUrlForRemoteChatImage(context, url) ?: url)
    }
    DisposableEffect(context, url, lifecycle) {
        val prefs = context.getSharedPreferences(LOCAL_IMAGE_REMOTE_PREFS, Context.MODE_PRIVATE)
        fun refresh() { resolved = localUrlForRemoteChatImage(context, url) ?: url }
        val listener = SharedPreferences.OnSharedPreferenceChangeListener { store, key ->
            if (key == null || key == resolved || store.getString(key, null) == url) refresh()
        }
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_START) refresh()
        }
        prefs.registerOnSharedPreferenceChangeListener(listener)
        lifecycle.addObserver(observer)
        // Close the gap between the first lookup and listener registration.
        refresh()
        onDispose {
            prefs.unregisterOnSharedPreferenceChangeListener(listener)
            lifecycle.removeObserver(observer)
        }
    }
    return resolved
}

/** Retry interrupted/failed receipts while visible, and start again on foreground return. */
@Composable
internal fun ReceiveChatImageEffect(attachment: MessageAttachment) {
    if (!WebImageReceiver.supports(attachment)) return
    val context = LocalContext.current
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    val prefs = remember(context) { AppPreferences(context) }
    LaunchedEffect(lifecycle, prefs, attachment) {
        lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) {
            retryChatImageReceipt(prefs, attachment)
        }
    }
}

internal suspend fun retryChatImageReceipt(
    prefs: AppPreferences,
    attachment: MessageAttachment,
    receive: suspend () -> Unit = { WebImageReceiver.receive(prefs, attachment) },
) {
    val url = attachment.url ?: return
    val username = prefs.username
    for (attempt in 0 until 4) {
        if (prefs.username != username) return
        if (localUrlForRemoteChatImage(prefs.applicationContext, url) != null) return
        if (attempt > 0) delay(1000L shl (attempt - 1))
        if (prefs.username != username) return
        receive()
    }
}
