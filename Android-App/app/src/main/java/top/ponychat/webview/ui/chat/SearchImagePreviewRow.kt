package top.ponychat.webview.ui.chat

import androidx.compose.foundation.background
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import coil.compose.AsyncImage

/** Uses the same durable phone image mapping and Coil cache as chat bubbles. */
@OptIn(ExperimentalFoundationApi::class)
@Composable
internal fun SearchImagePreviewRow(urls: List<String>, onClick: (String) -> Unit, onLongClick: () -> Unit) {
    val context = LocalContext.current
    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        urls.take(3).forEach { url ->
            key(url) {
                val local = localUrlForRemoteChatImage(context, url)
                val missing = url.startsWith("/chat_images/") && local == null
                var failed by remember(url) { mutableStateOf(false) }
                var loaded by remember(url) { mutableStateOf(false) }
                Box(
                    Modifier.size(72.dp).clip(RoundedCornerShape(10.dp))
                        .background(MaterialTheme.colorScheme.surfaceVariant)
                        .combinedClickable(onClick = { onClick(url) }, onLongClick = onLongClick),
                    contentAlignment = Alignment.Center,
                ) {
                    if (!loaded || missing || failed) {
                        Text(if (missing || failed) "图片不可用" else "图片加载中",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    if (!missing) {
                        AsyncImage(
                            model = rememberThumbnailImageRequest(local ?: url),
                            contentDescription = "聊天图片",
                            contentScale = ContentScale.Fit,
                            modifier = Modifier.fillMaxSize(),
                            onSuccess = { loaded = true; failed = false },
                            onError = { loaded = false; failed = true },
                        )
                    }
                }
            }
        }
    }
}
