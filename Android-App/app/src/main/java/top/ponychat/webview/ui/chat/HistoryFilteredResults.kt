package top.ponychat.webview.ui.chat

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.itemsIndexed
import androidx.compose.foundation.lazy.grid.rememberLazyGridState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import coil.compose.AsyncImage
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.launch
import top.ponychat.webview.data.api.NetworkClient
import top.ponychat.webview.data.api.ApiService
import top.ponychat.webview.data.model.Character
import top.ponychat.webview.data.model.SearchMessageResult
import top.ponychat.webview.data.prefs.AppPreferences

/** Scans source pages, not just the messages already loaded by the chat screen. */
@OptIn(ExperimentalFoundationApi::class)
@Composable
internal fun HistoryFilteredResults(
    character: Character,
    prefs: AppPreferences,
    contentFilter: String,
    query: String,
    senderFilter: String,
    dateFilter: String,
    onNavigate: (Int) -> Unit,
    onPrompt: (String) -> Unit,
    onDelete: (SearchMessageResult) -> Unit,
    apiOverride: ApiService? = null,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val api = remember { apiOverride ?: NetworkClient.createApiService(prefs) }
    var messages by remember { mutableStateOf<List<SearchMessageResult>>(emptyList()) }
    var beforeSeq by remember { mutableStateOf<Int?>(null) }
    var conversationId by remember { mutableStateOf<String?>(null) }
    var offset by remember { mutableIntStateOf(0) }
    var loading by remember { mutableStateOf(false) }
    var hasMore by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }
    var selected by remember { mutableStateOf<Set<String>>(emptySet()) }
    var previewIndex by remember { mutableStateOf<Int?>(null) }
    val listState = rememberLazyListState()
    val gridState = rememberLazyGridState()
    val pictures = remember(messages) {
        messages.flatMap { message -> message.historyImageUrls(context).map { message to it } }
    }
    val isImages = contentFilter == "image"
    BackHandler(selected.isNotEmpty()) { selected = emptySet() }

    fun loadMore() {
        if (loading || !hasMore) return
        loading = true
        error = null
        scope.launch {
            try {
                val (from, to) = computeDateRange(dateFilter)
                var added = 0
                // Sparse image pages must not hide older images. Continue until a
                // useful batch is found or the source is exhausted; retain cursors.
                do {
                    val page: List<SearchMessageResult>
                    if (query.isBlank()) {
                        val response = api.getConversationMessagesPaged(prefs.username, character.id.orEmpty(),
                            conversationId = conversationId, beforeSeq = beforeSeq, sender = senderFilter,
                            dateFrom = from, dateTo = to, limit = 100)
                        check(response.isSuccessful)
                        val body = checkNotNull(response.body())
                        check(!body.hasMore || (body.minSeq != null &&
                            (beforeSeq == null || body.minSeq < beforeSeq!!)))
                        page = body.messages.asReversed().map { message ->
                            SearchMessageResult(message.messageId ?: message.sequenceNumber.toString(),
                                message.sequenceNumber ?: 0, body.conversationId.orEmpty(), message.role,
                                message.content, message.timestamp ?: 0L, message.attachments)
                        }
                        conversationId = body.conversationId ?: conversationId
                        beforeSeq = body.minSeq
                        hasMore = body.hasMore
                    } else {
                        val response = api.searchMessages(prefs.username, character.id.orEmpty(), query,
                            sender = senderFilter, dateFrom = from, dateTo = to, limit = 50, offset = offset)
                        check(response.isSuccessful)
                        val body = checkNotNull(response.body())
                        check(!body.hasMore || body.results.isNotEmpty())
                        page = body.results
                        offset += page.size
                        hasMore = body.hasMore
                    }
                    val matched = page.withLocalHistoryImages(context, prefs.username, character.id.orEmpty())
                        .filter { it.matchesHistoryContent(contentFilter, context) }
                    messages = (messages + matched).distinctBy { it.conversationId to it.messageId }
                    added += matched.size
                } while (hasMore && added < 30)
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Exception) {
                error = "加载失败，请重试"
            } finally {
                loading = false
            }
        }
    }
    LaunchedEffect(Unit) { loadMore() }
    val nearEnd by remember {
        derivedStateOf {
            if (isImages) (gridState.layoutInfo.visibleItemsInfo.lastOrNull()?.index ?: -1) >=
                gridState.layoutInfo.totalItemsCount - 7
            else (listState.layoutInfo.visibleItemsInfo.lastOrNull()?.index ?: -1) >=
                listState.layoutInfo.totalItemsCount - 4
        }
    }
    LaunchedEffect(nearEnd, messages.size, loading, hasMore) {
        if (messages.isNotEmpty() && nearEnd && !loading && error == null) loadMore()
    }
    fun toggle(id: String) { selected = if (id in selected) selected - id else selected + id }
    val caption = if (isImages) "已加载 ${pictures.size} 张图片" else "已加载 ${messages.size} 条文本"
    val footer: @Composable () -> Unit = {
        Box(Modifier.fillMaxWidth().padding(16.dp), contentAlignment = Alignment.Center) {
            when {
                loading -> CircularProgressIndicator(Modifier.size(24.dp), strokeWidth = 2.dp)
                error != null -> TextButton(onClick = { loadMore() }) { Text(error!!) }
                hasMore -> TextButton(onClick = { loadMore() }) { Text("加载更多") }
                else -> Text(if (isImages) "已加载全部图片" else "已加载全部文本",
                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    }
    Box(Modifier.fillMaxSize()) {
        when {
            messages.isEmpty() -> Column(Modifier.align(Alignment.Center), horizontalAlignment = Alignment.CenterHorizontally) {
                if (!loading && error == null) Text(if (isImages) "没有符合条件的图片" else "没有符合条件的文本")
                footer()
            }
            isImages -> LazyVerticalGrid(GridCells.Fixed(3), state = gridState,
                modifier = Modifier.fillMaxSize(), contentPadding = PaddingValues(12.dp, 8.dp, 12.dp, 80.dp),
                horizontalArrangement = Arrangement.spacedBy(5.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
                item(span = { GridItemSpan(maxLineSpan) }) {
                    Text(caption, Modifier.padding(vertical = 10.dp), style = MaterialTheme.typography.labelMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                itemsIndexed(pictures, key = { index, entry -> "${entry.first.messageId}/$index" }) { index, (message, url) ->
                    Box(Modifier.aspectRatio(1f).clip(RoundedCornerShape(8.dp))
                        .background(MaterialTheme.colorScheme.surfaceVariant)
                        .combinedClickable(onClick = {
                            if (selected.isEmpty()) previewIndex = index else toggle(message.messageId)
                        }, onLongClick = { toggle(message.messageId) })) {
                        AsyncImage(rememberThumbnailImageRequest(url), "对话图片 ${index + 1}",
                            modifier = Modifier.fillMaxSize(), contentScale = ContentScale.Crop)
                        if (message.messageId in selected) Text("✓", Modifier.align(Alignment.TopEnd)
                            .background(MaterialTheme.colorScheme.primary).padding(6.dp),
                            color = MaterialTheme.colorScheme.onPrimary)
                    }
                }
                item(span = { GridItemSpan(maxLineSpan) }) { footer() }
            }
            else -> LazyColumn(state = listState, contentPadding = PaddingValues(bottom = 80.dp)) {
                item { Text(caption, Modifier.padding(16.dp), style = MaterialTheme.typography.labelMedium) }
                items(messages, key = { it.messageId }) { message ->
                    MessageSearchResultItem(message, query, character, prefs,
                        isSelected = message.messageId in selected, isSelectionMode = selected.isNotEmpty(),
                        onToggleSelect = ::toggle, onDelete = {
                            messages = messages.filterNot { it.messageId == message.messageId }
                            selected = selected - message.messageId
                            onDelete(message)
                        }, onClick = { onNavigate(message.sequenceNumber) }, onPrompt = onPrompt,
                        onPreviewImage = { url ->
                            previewIndex = pictures.indexOfFirst { it.first.messageId == message.messageId && it.second == url }.takeIf { it >= 0 }
                        })
                }
                item { footer() }
            }
        }
        if (selected.isNotEmpty()) Surface(Modifier.align(Alignment.BottomCenter).fillMaxWidth()) {
            Row(Modifier.padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
                TextButton(onClick = { selected = emptySet() }) { Text("取消") }
                Spacer(Modifier.weight(1f))
                Button(onClick = {
                    val deleted = messages.filter { it.messageId in selected }
                    messages = messages.filterNot { it.messageId in selected }
                    selected = emptySet()
                    deleted.forEach(onDelete)
                }) { Text("删除 (${selected.size}条)") }
            }
        }
    }
    previewIndex?.takeIf { it in pictures.indices }?.let { index ->
        ChatScreenImagePreviewOverlay(pictures[index].second, pictures.map { it.second }, index,
            onDismiss = { previewIndex = null }, coroutineScope = scope, context = context)
    }
}
