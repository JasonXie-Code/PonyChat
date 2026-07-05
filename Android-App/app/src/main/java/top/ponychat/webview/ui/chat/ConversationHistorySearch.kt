package top.ponychat.webview.ui.chat

import androidx.activity.compose.BackHandler
import coil.compose.AsyncImage
import androidx.compose.animation.*
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.positionInWindow
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.IntRect
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Popup
import androidx.compose.ui.window.PopupPositionProvider
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import top.ponychat.webview.CustomToast
import top.ponychat.webview.data.api.NetworkClient
import top.ponychat.webview.data.model.Character
import top.ponychat.webview.data.model.CompanionMessage
import top.ponychat.webview.data.model.CompanionSessionSummary
import top.ponychat.webview.data.model.MessageAttachment
import top.ponychat.webview.data.model.ResetCharacterChatRequest
import top.ponychat.webview.data.model.SearchMessageResult
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.ui.character.CharacterAvatar
import top.ponychat.webview.ui.common.adaptivePopupMenuAccentColor
import top.ponychat.webview.ui.common.adaptivePopupMenuBorder
import top.ponychat.webview.ui.common.adaptivePopupMenuContainerColor
import top.ponychat.webview.ui.common.adaptivePopupMenuContentColor
import top.ponychat.webview.ui.common.adaptivePopupMenuDangerColor
import top.ponychat.webview.ui.common.PonyDangerCountdownConfirmDialog
import top.ponychat.webview.ui.common.PonyTopBar
import top.ponychat.webview.ui.common.PonyTopSearchBar
import top.ponychat.webview.ui.theme.*
import top.ponychat.webview.util.DebugLog
import java.text.SimpleDateFormat
import java.util.*
import kotlin.math.roundToInt

// ==================== 消息搜索 Tab ====================

/** 将 ChatMessage 转换为 SearchMessageResult 便于统一显示 */
private fun top.ponychat.webview.data.model.ChatMessage.toSearchResult(conversationId: String?): SearchMessageResult =
    SearchMessageResult(
        messageId = messageId ?: sequenceNumber?.toString() ?: "",
        sequenceNumber = sequenceNumber ?: 0,
        conversationId = conversationId.orEmpty(),
        role = role,
        content = content,
        timestamp = timestamp ?: 0L,
        attachments = attachments ?: emptyList()
    )

@Composable
internal fun MessageSearchTab(
    viewModel: ChatViewModel,
    character: Character,
    prefs: AppPreferences,
    resetVersion: Int,
    onNavigateToMessagePosition: (Int) -> Unit,
    onPrompt: (String) -> Unit,
    onVisibleMessageDeleted: (Int) -> Unit
) {
    val username = prefs.username
    val characterId = character.id ?: ""
    val scope = rememberCoroutineScope()

    // 多选删除状态
    var selectedMessageIds by remember { mutableStateOf<Set<String>>(emptySet()) }
    val isSelectionMode = selectedMessageIds.isNotEmpty()
    BackHandler(enabled = isSelectionMode) { selectedMessageIds = emptySet() }

    var query by remember { mutableStateOf("") }
    var debouncedQuery by remember { mutableStateOf("") }
    var senderFilter by remember { mutableStateOf("all") }
    var dateFilter by remember { mutableStateOf("all") }

    // 搜索模式状态
    var searchResults by remember { mutableStateOf<List<SearchMessageResult>>(emptyList()) }
    var isSearching by remember { mutableStateOf(false) }
    var searchTotal by remember { mutableStateOf(0) }
    var completedSearchKey by remember { mutableStateOf("") }

    // 浏览模式状态（空 query 时展示最近消息，新↑旧↓）
    var browseMessages by remember { mutableStateOf<List<SearchMessageResult>>(emptyList()) }
    var browseMinSeq by remember { mutableIntStateOf(Int.MAX_VALUE) }
    var hasBrowseMore by remember { mutableStateOf(false) }
    var isBrowseLoading by remember { mutableStateOf(false) }
    var completedBrowseKey by remember { mutableStateOf("") }
    var localHistoryGeneration by remember { mutableIntStateOf(0) }
    val browseListState = rememberLazyListState()
    val searchLoadKey = "$characterId|$debouncedQuery|$senderFilter|$dateFilter|$resetVersion"
    val browseLoadKey = "$characterId|$senderFilter|$dateFilter|$resetVersion"

    val focusRequester = remember { FocusRequester() }

    fun removeDeletedMessages(ids: Set<String>) {
        if (ids.isEmpty()) return
        val beforeSearchCount = searchResults.size
        searchResults = searchResults.filterNot { it.messageId in ids }
        browseMessages = browseMessages.filterNot { it.messageId in ids }
        selectedMessageIds = selectedMessageIds - ids
        val removedFromSearch = beforeSearchCount - searchResults.size
        if (removedFromSearch > 0) {
            searchTotal = (searchTotal - removedFromSearch).coerceAtLeast(searchResults.size)
        }
        onVisibleMessageDeleted(ids.size)
    }

    // 加载最近消息（浏览模式）
    fun clearLocalHistoryState() {
        localHistoryGeneration++
        selectedMessageIds = emptySet()
        searchResults = emptyList()
        isSearching = false
        searchTotal = 0
        completedSearchKey = ""
        browseMessages = emptyList()
        browseMinSeq = Int.MAX_VALUE
        hasBrowseMore = false
        isBrowseLoading = false
        completedBrowseKey = ""
    }

    fun loadBrowseMessages(beforeSeq: Int? = null) {
        if (isBrowseLoading) return
        val generation = localHistoryGeneration
        val (dateFrom, dateTo) = computeDateRange(dateFilter)
        scope.launch {
            isBrowseLoading = true
            try {
                val api = NetworkClient.createApiService(prefs)
                val resp = api.getConversationMessagesPaged(
                    username = username,
                    characterId = characterId,
                    conversationId = null,
                    beforeSeq = beforeSeq,
                    sender = senderFilter,
                    dateFrom = dateFrom,
                    dateTo = dateTo,
                    limit = 50
                )
                if (resp.isSuccessful) {
                    if (generation != localHistoryGeneration) return@launch
                    val body = resp.body()
                    val newItems = (body?.messages ?: emptyList()).map { it.toSearchResult(body?.conversationId) }
                    if (beforeSeq == null) {
                        // 首次加载：最新 50 条，倒序（新↑旧↓）
                        browseMessages = newItems.reversed()
                    } else {
                        // 加载更多旧消息：追加到列表末尾（更旧的在下面）
                        browseMessages = browseMessages + newItems.reversed()
                    }
                    hasBrowseMore = body?.hasMore ?: false
                    val minSeq = body?.minSeq ?: Int.MAX_VALUE
                    if (minSeq < browseMinSeq) browseMinSeq = minSeq
                }
            } catch (_: Exception) {}
            if (generation == localHistoryGeneration) {
                if (beforeSeq == null) {
                    completedBrowseKey = browseLoadKey
                }
                isBrowseLoading = false
            }
        }
    }

    // query 防抖
    LaunchedEffect(query) {
        delay(300)
        debouncedQuery = query
    }

    // 浏览模式加载：空 query 时筛选项同样生效
    LaunchedEffect(debouncedQuery, senderFilter, dateFilter, resetVersion) {
        if (debouncedQuery.isBlank()) {
            clearLocalHistoryState()
            loadBrowseMessages()
        }
    }

    // 搜索触发（有 query 时）
    LaunchedEffect(debouncedQuery, senderFilter, dateFilter, resetVersion) {
        if (debouncedQuery.isBlank()) {
            isSearching = false
            searchResults = emptyList()
            searchTotal = 0
            completedSearchKey = ""
            return@LaunchedEffect
        }
        isSearching = true
        completedSearchKey = ""
        val (dateFrom, dateTo) = computeDateRange(dateFilter)
        try {
            val api = NetworkClient.createApiService(prefs)
            val resp = api.searchMessages(
                username = username,
                characterId = characterId,
                query = debouncedQuery,
                sender = senderFilter,
                dateFrom = dateFrom,
                dateTo = dateTo,
                limit = 20,
                offset = 0
            )
            if (resp.isSuccessful) {
                val body = resp.body()
                searchResults = body?.results ?: emptyList()
                searchTotal = body?.total ?: 0
            }
        } catch (_: Exception) {}
        completedSearchKey = searchLoadKey
        isSearching = false
    }

    // 浏览模式：滑到底部时加载更多旧消息
    val lastVisibleIndex by remember { derivedStateOf { browseListState.layoutInfo.visibleItemsInfo.lastOrNull()?.index ?: 0 } }
    LaunchedEffect(lastVisibleIndex) {
        if (debouncedQuery.isBlank() && hasBrowseMore && !isBrowseLoading) {
            val total = browseListState.layoutInfo.totalItemsCount
            if (total > 0 && lastVisibleIndex >= total - 3) {
                loadBrowseMessages(beforeSeq = browseMinSeq)
            }
        }
    }

    Column(modifier = Modifier.fillMaxSize()) {
        // 搜索栏
        MessageSearchBar(
            query = query,
            onQueryChange = { query = it },
            focusRequester = focusRequester,
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 12.dp, vertical = 8.dp)
        )

        // 下拉筛选（发送方 + 时间范围，一行两个紧凑按钮）
        FiltersDropdownRow(
            senderFilter = senderFilter,
            onSenderChange = { senderFilter = it },
            dateFilter = dateFilter,
            onDateChange = { dateFilter = it },
            modifier = Modifier.padding(horizontal = 16.dp, vertical = 2.dp)
        )

        HorizontalDivider(
            modifier = Modifier.padding(top = 8.dp),
            color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.12f)
        )

        Box(modifier = Modifier.fillMaxSize()) {
            val isCurrentSearchLoading = debouncedQuery.isNotBlank() &&
                (isSearching || completedSearchKey != searchLoadKey)
            val isInitialBrowseLoading = debouncedQuery.isBlank() &&
                browseMessages.isEmpty() &&
                (isBrowseLoading || completedBrowseKey != browseLoadKey)
            when {
                // 搜索中
                isCurrentSearchLoading -> {
                    Column(
                        modifier = Modifier.align(Alignment.Center),
                        horizontalAlignment = Alignment.CenterHorizontally
                    ) {
                        CircularProgressIndicator(color = Primary, modifier = Modifier.size(32.dp))
                        Spacer(Modifier.height(12.dp))
                        Text("搜索中…", color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodySmall)
                    }
                }
                // 有搜索词：展示搜索结果
                debouncedQuery.isNotBlank() -> {
                    if (searchResults.isEmpty()) {
                        Column(
                            modifier = Modifier.align(Alignment.Center).padding(32.dp),
                            horizontalAlignment = Alignment.CenterHorizontally
                        ) {
                            Icon(Icons.Filled.SearchOff, contentDescription = null, modifier = Modifier.size(52.dp), tint = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.35f))
                            Spacer(Modifier.height(14.dp))
                            Text("未找到相关记录", color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Medium)
                            Spacer(Modifier.height(4.dp))
                            Text("试试其他关键词或调整筛选条件", color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.6f), style = MaterialTheme.typography.bodySmall)
                        }
                    } else {
                        LazyColumn(modifier = Modifier.fillMaxSize()) {
                            item {
                                Text(
                                    text = "共找到 $searchTotal 条结果",
                                    style = MaterialTheme.typography.labelSmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.6f),
                                    modifier = Modifier.padding(horizontal = 20.dp, vertical = 10.dp)
                                )
                            }
                            items(items = searchResults, key = { it.messageId }) { result ->
                                MessageSearchResultItem(
                                    result = result,
                                    keyword = debouncedQuery,
                                    character = character,
                                    prefs = prefs,
                                    isSelected = result.messageId in selectedMessageIds,
                                    isSelectionMode = isSelectionMode,
                                    onToggleSelect = { id ->
                                        selectedMessageIds = if (id in selectedMessageIds) {
                                            selectedMessageIds - id
                                        } else {
                                            selectedMessageIds + id
                                        }
                                    },
                                    onDelete = { id ->
                                        removeDeletedMessages(setOf(id))
                                        viewModel.deleteMessage(id, result.conversationId)
                                    },
                                    onClick = { onNavigateToMessagePosition(result.sequenceNumber) },
                                    onPrompt = onPrompt
                                )
                            }
                            item { Spacer(Modifier.height(24.dp)) }
                        }
                    }
                }
                // 无搜索词：浏览模式（最近消息，新↑旧↓）
                isInitialBrowseLoading -> {
                    Column(
                        modifier = Modifier.align(Alignment.Center),
                        horizontalAlignment = Alignment.CenterHorizontally
                    ) {
                        CircularProgressIndicator(color = Primary, modifier = Modifier.size(32.dp))
                        Spacer(Modifier.height(12.dp))
                        Text("加载消息中…", color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodySmall)
                    }
                }
                // 无搜索词：浏览模式（最近消息，新↑旧↓）
                else -> {
                    LazyColumn(
                        state = browseListState,
                        modifier = Modifier.fillMaxSize()
                    ) {
                        item {
                            Text(
                                text = "最近消息",
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.6f),
                                modifier = Modifier.padding(horizontal = 20.dp, vertical = 10.dp)
                            )
                        }
                        items(items = browseMessages, key = { it.messageId.ifBlank { it.sequenceNumber.toString() } }) { msg ->
                            MessageSearchResultItem(
                                result = msg,
                                keyword = "",
                                character = character,
                                prefs = prefs,
                                isSelected = msg.messageId in selectedMessageIds,
                                isSelectionMode = isSelectionMode,
                                onToggleSelect = { id ->
                                    selectedMessageIds = if (id in selectedMessageIds) {
                                        selectedMessageIds - id
                                    } else {
                                        selectedMessageIds + id
                                    }
                                },
                                onDelete = { id ->
                                    removeDeletedMessages(setOf(id))
                                    viewModel.deleteMessage(id, msg.conversationId)
                                },
                                onClick = { onNavigateToMessagePosition(msg.sequenceNumber) },
                                onPrompt = onPrompt
                            )
                        }
                        // 底部加载更多（旧消息）
                        if (isBrowseLoading) {
                            item {
                                Box(
                                    modifier = Modifier.fillMaxWidth().padding(16.dp),
                                    contentAlignment = Alignment.Center
                                ) {
                                    CircularProgressIndicator(modifier = Modifier.size(24.dp), color = Primary, strokeWidth = 2.dp)
                                }
                            }
                        }
                        if (!hasBrowseMore && browseMessages.isNotEmpty()) {
                            item {
                                Text(
                                    text = "已加载全部消息",
                                    style = MaterialTheme.typography.labelSmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.4f),
                                    modifier = Modifier.fillMaxWidth().padding(vertical = 16.dp),
                                    textAlign = TextAlign.Center
                                )
                            }
                        }
                        item { Spacer(Modifier.height(24.dp)) }
                    }
                }
            }
            if (isSelectionMode) {
                Surface(
                    modifier = Modifier
                        .align(Alignment.BottomCenter)
                        .fillMaxWidth(),
                    color = MaterialTheme.colorScheme.surface,
                    shadowElevation = 8.dp
                ) {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .navigationBarsPadding()
                            .padding(horizontal = 16.dp, vertical = 10.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        TextButton(onClick = { selectedMessageIds = emptySet() }) {
                            Text("取消")
                        }
                        Spacer(Modifier.weight(1f))
                        Button(
                            onClick = {
                                val idsToDelete = selectedMessageIds
                                val conversationByMessageId = (searchResults + browseMessages)
                                    .associate { it.messageId to it.conversationId }
                                removeDeletedMessages(idsToDelete)
                                idsToDelete.forEach { id -> viewModel.deleteMessage(id, conversationByMessageId[id]) }
                                selectedMessageIds = emptySet()
                            },
                            colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.error)
                        ) {
                            Text("删除 (${selectedMessageIds.size}条)")
                        }
                    }
                }
            }
        }
    }
}

// ==================== 搜索结果条目 ====================

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun MessageSearchResultItem(
    result: SearchMessageResult,
    keyword: String,
    character: Character,
    prefs: AppPreferences,
    isSelected: Boolean = false,
    isSelectionMode: Boolean = false,
    onToggleSelect: (String) -> Unit = {},
    onDelete: (String) -> Unit = {},
    onClick: () -> Unit,
    onPrompt: (String) -> Unit
) {
    val isUser = result.role == "user"
    val context = androidx.compose.ui.platform.LocalContext.current
    val haptic = androidx.compose.ui.platform.LocalHapticFeedback.current
    var showMenu by remember { mutableStateOf(false) }
    var menuPosition by remember(result.messageId) { mutableStateOf(IntOffset.Zero) }
    var rowWindowTopLeft by remember(result.messageId) { mutableStateOf(androidx.compose.ui.geometry.Offset.Zero) }
    val actionMenuTextColor = historyActionMenuContentColor()
    val actionMenuDeleteColor = historyActionMenuDangerColor()
    val stickerAttachments = remember(result.attachments) {
        result.attachments.orEmpty().filter { it.type == "sticker" || it.type == "emoji_asset" }
    }
    val previewText = remember(result.content, stickerAttachments) {
        result.searchPreviewText(stickerAttachments)
    }

    Box {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .onGloballyPositioned { coords ->
                    rowWindowTopLeft = coords.positionInWindow()
                }
                .pointerInput(isSelectionMode, result.messageId) {
                    detectTapGestures(
                        onTap = {
                            if (isSelectionMode) onToggleSelect(result.messageId) else onClick()
                        },
                        onLongPress = { offset ->
                            haptic.performHapticFeedback(HapticFeedbackType.LongPress)
                            if (isSelectionMode) {
                                onToggleSelect(result.messageId)
                            } else {
                                val windowOffset = rowWindowTopLeft + offset
                                menuPosition = IntOffset(windowOffset.x.roundToInt(), windowOffset.y.roundToInt())
                                showMenu = true
                            }
                        }
                    )
                }
                .background(
                    if (isSelected) MaterialTheme.colorScheme.primary.copy(alpha = 0.1f)
                    else MaterialTheme.colorScheme.background
                )
        ) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp, vertical = 10.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                if (isSelectionMode) {
                    Checkbox(
                        checked = isSelected,
                        onCheckedChange = { onToggleSelect(result.messageId) },
                        colors = CheckboxDefaults.colors(checkedColor = Primary),
                        modifier = Modifier.size(24.dp)
                    )
                    Spacer(Modifier.width(8.dp))
                }
                // 头像：用真实头像替代纯色占位
                if (isUser) {
                    PonyStyleAvatar(
                        avatarUrl = prefs.avatar,
                        name = "我",
                        apiBase = prefs.effectiveApiBase(),
                        size = 32
                    )
                } else {
                    CharacterAvatar(
                        avatarUrl = character.avatarUrl(),
                        name = character.displayName(),
                        apiBase = prefs.effectiveApiBase(),
                        size = 32
                    )
                }

                Spacer(Modifier.width(10.dp))

                Column(modifier = Modifier.weight(1f)) {
                    // 发送方名称 + 时间戳
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Text(
                            text = if (isUser) "我" else character.displayName(),
                            style = MaterialTheme.typography.labelMedium,
                            fontWeight = FontWeight.SemiBold,
                            color = if (isUser)
                                MaterialTheme.colorScheme.onBackground
                            else
                                Primary
                        )
                        Text(
                            text = formatTimestampMs(result.timestamp),
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.6f)
                        )
                    }
                    Spacer(Modifier.height(3.dp))
                    if (stickerAttachments.isNotEmpty()) {
                        SearchStickerPreviewRow(stickerAttachments)
                        Spacer(Modifier.height(4.dp))
                    }
                    // 消息预览（关键词高亮，最多 2 行）
                    if (previewText.isNotBlank()) {
                        Text(
                            text = buildHighlightedText(previewText, keyword),
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            maxLines = 2,
                            overflow = TextOverflow.Ellipsis
                        )
                    }
                }
            }
            HorizontalDivider(
                color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.08f),
                modifier = Modifier.padding(start = if (isSelectionMode) 90.dp else 58.dp)
            )
        }
        HistoryFingerAnchoredDropdownMenu(
            expanded = showMenu,
            onDismissRequest = { showMenu = false },
            positionInWindow = menuPosition
        ) {
            DropdownMenuItem(
                text = { Text("复制", color = actionMenuTextColor) },
                leadingIcon = { Icon(Icons.Filled.ContentCopy, contentDescription = null, tint = actionMenuTextColor) },
                onClick = {
                    showMenu = false
                    val clipboard = context.getSystemService(android.content.Context.CLIPBOARD_SERVICE)
                        as android.content.ClipboardManager
                    clipboard.setPrimaryClip(
                        android.content.ClipData.newPlainText("消息", previewText.ifBlank { result.content })
                    )
                    onPrompt("已复制")
                }
            )
            DropdownMenuItem(
                text = { Text("多选", color = actionMenuTextColor) },
                leadingIcon = { Icon(Icons.Filled.CheckBox, contentDescription = null, tint = actionMenuTextColor) },
                onClick = {
                    showMenu = false
                    onToggleSelect(result.messageId)
                }
            )
            DropdownMenuItem(
                text = { Text("删除", color = actionMenuDeleteColor) },
                leadingIcon = { Icon(Icons.Filled.Delete, contentDescription = null, tint = actionMenuDeleteColor) },
                onClick = {
                    showMenu = false
                    onDelete(result.messageId)
                }
            )
        }
    }
}

