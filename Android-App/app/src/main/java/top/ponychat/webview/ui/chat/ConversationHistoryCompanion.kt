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

// ==================== 陪玩 Tab ====================

@Composable
internal fun CompanionHistoryTab(
    prefs: AppPreferences,
    character: Character
) {
    val scope = rememberCoroutineScope()
    var sessions by remember { mutableStateOf<List<CompanionSessionSummary>>(emptyList()) }
    var isLoading by remember { mutableStateOf(true) }
    var expandedId by remember { mutableStateOf<String?>(null) }
    var pendingDeleteSessionId by remember { mutableStateOf<String?>(null) }
    // 详情消息缓存 id->messages
    val messagesCache = remember { mutableStateMapOf<String, List<CompanionMessage>>() }

    val username = prefs.username
    val characterId = character.id ?: ""

    fun reload() {
        isLoading = true
        scope.launch {
            try {
                val api = NetworkClient.createApiService(prefs)
                val resp = api.getCompanionSessions(username, characterId)
                if (resp.isSuccessful) {
                    sessions = resp.body()?.sessions ?: emptyList()
                }
            } catch (_: Exception) {}
            isLoading = false
        }
    }

    LaunchedEffect(characterId) { reload() }

    // 删除确认
    if (pendingDeleteSessionId != null) {
        val sid = pendingDeleteSessionId!!
        AlertDialog(
            onDismissRequest = { pendingDeleteSessionId = null },
            containerColor = MaterialTheme.colorScheme.surface,
            title = { Text("删除陪玩记录", color = MaterialTheme.colorScheme.onBackground) },
            text = { Text("确认删除这次陪玩记录？此操作不可撤销。", color = MaterialTheme.colorScheme.onSurface) },
            confirmButton = {
                TextButton(onClick = {
                    scope.launch {
                        try {
                            val api = NetworkClient.createApiService(prefs)
                            api.deleteCompanionSession(sid, username)
                            sessions = sessions.filter { it.id != sid }
                            messagesCache.remove(sid)
                            if (expandedId == sid) expandedId = null
                        } catch (_: Exception) {}
                    }
                    pendingDeleteSessionId = null
                }) { Text("删除", color = ErrorColor, fontWeight = FontWeight.Bold) }
            },
            dismissButton = {
                TextButton(onClick = { pendingDeleteSessionId = null }) {
                    Text("取消", color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        )
    }

    Box(modifier = Modifier.fillMaxSize()) {
        when {
            isLoading -> {
                Column(
                    modifier = Modifier.align(Alignment.Center),
                    horizontalAlignment = Alignment.CenterHorizontally
                ) {
                    CircularProgressIndicator(color = Primary, modifier = Modifier.size(36.dp))
                    Spacer(Modifier.height(16.dp))
                    Text("加载陪玩记录中…", color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.bodySmall)
                }
            }
            sessions.isEmpty() -> {
                Column(
                    modifier = Modifier.align(Alignment.Center).padding(32.dp),
                    horizontalAlignment = Alignment.CenterHorizontally
                ) {
                    Icon(
                        Icons.Filled.VideogameAsset,
                        contentDescription = null,
                        modifier = Modifier.size(52.dp),
                        tint = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.4f)
                    )
                    Spacer(Modifier.height(14.dp))
                    Text("暂无陪玩记录",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.bodyMedium,
                        fontWeight = FontWeight.Medium)
                    Spacer(Modifier.height(4.dp))
                    Text("每次结束陪玩后会自动保存记录",
                        color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.6f),
                        style = MaterialTheme.typography.bodySmall)
                }
            }
            else -> {
                LazyColumn(modifier = Modifier.fillMaxSize()) {
                    item {
                        Text(
                            "${sessions.size} 次陪玩记录",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.6f),
                            modifier = Modifier.padding(horizontal = 20.dp, vertical = 10.dp)
                        )
                    }
                    items(items = sessions, key = { it.id }) { session ->
                        CompanionSessionItem(
                            session = session,
                            expanded = expandedId == session.id,
                            messages = messagesCache[session.id],
                            onToggle = {
                                if (expandedId == session.id) {
                                    expandedId = null
                                } else {
                                    expandedId = session.id
                                    if (!messagesCache.containsKey(session.id)) {
                                        scope.launch {
                                            try {
                                                val api = NetworkClient.createApiService(prefs)
                                                val r = api.getCompanionSessionMessages(session.id, username)
                                                if (r.isSuccessful) {
                                                    messagesCache[session.id] = r.body()?.messages ?: emptyList()
                                                }
                                            } catch (_: Exception) {}
                                        }
                                    }
                                }
                            },
                            onDeleteRequest = { pendingDeleteSessionId = session.id }
                        )
                    }
                    item { Spacer(Modifier.height(24.dp)) }
                }
            }
        }
    }
}

// ==================== 陪玩会话条目 ====================

@Composable
private fun CompanionSessionItem(
    session: CompanionSessionSummary,
    expanded: Boolean,
    messages: List<CompanionMessage>?,
    onToggle: () -> Unit,
    onDeleteRequest: () -> Unit
) {
    val chevronRotation by animateFloatAsState(
        targetValue = if (expanded) 180f else 0f,
        animationSpec = tween(200),
        label = "chevron"
    )

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .background(MaterialTheme.colorScheme.background)
    ) {
        // 条目头部（可点击展开/收起）
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .clickable(onClick = onToggle)
                .padding(start = 20.dp, end = 8.dp, top = 12.dp, bottom = 12.dp)
        ) {
            Row(
                modifier = Modifier.fillMaxWidth().padding(end = 32.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                // 图标
                Box(
                    modifier = Modifier
                        .size(38.dp)
                        .clip(RoundedCornerShape(10.dp))
                        .background(Primary.copy(0.10f)),
                    contentAlignment = Alignment.Center
                ) {
                    Icon(
                        Icons.Filled.VideogameAsset,
                        contentDescription = null,
                        tint = Primary,
                        modifier = Modifier.size(18.dp)
                    )
                }
                Spacer(Modifier.width(14.dp))
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = formatCompanionTitle(session.endedAt),
                        color = MaterialTheme.colorScheme.onBackground,
                        style = MaterialTheme.typography.bodyMedium,
                        fontWeight = FontWeight.Medium,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis
                    )
                    Spacer(Modifier.height(3.dp))
                    Row(
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Text(
                            text = formatDuration(session.durationSeconds),
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.7f)
                        )
                        Text("·", style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.4f))
                        Text(
                            "${session.frameCount} 张截图",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.7f)
                        )
                        Text("·", style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.4f))
                        Text(
                            formatRelativeTime(session.endedAt),
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.7f)
                        )
                    }
                }
                Icon(
                    Icons.Filled.KeyboardArrowDown,
                    contentDescription = if (expanded) "收起" else "展开",
                    tint = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.5f),
                    modifier = Modifier.size(20.dp).rotate(chevronRotation)
                )
            }
            // 删除按钮
            IconButton(
                onClick = onDeleteRequest,
                modifier = Modifier.align(Alignment.CenterEnd).size(36.dp)
            ) {
                Icon(
                    Icons.Filled.Delete,
                    contentDescription = "删除",
                    tint = MaterialTheme.colorScheme.error.copy(0.7f),
                    modifier = Modifier.size(18.dp)
                )
            }
        }

        // 展开后的消息列表
        AnimatedVisibility(
            visible = expanded,
            enter = expandVertically(tween(220)) + fadeIn(tween(220)),
            exit = shrinkVertically(tween(200)) + fadeOut(tween(180))
        ) {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .background(MaterialTheme.colorScheme.surfaceVariant.copy(0.25f))
                    .padding(horizontal = 16.dp, vertical = 8.dp)
            ) {
                if (messages == null) {
                    // 加载中
                    Row(
                        modifier = Modifier.fillMaxWidth().padding(16.dp),
                        horizontalArrangement = Arrangement.Center,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        CircularProgressIndicator(color = Primary, modifier = Modifier.size(20.dp), strokeWidth = 2.dp)
                        Spacer(Modifier.width(10.dp))
                        Text("加载消息中…", style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                } else if (messages.isEmpty()) {
                    Text(
                        "（无消息记录）",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.5f),
                        modifier = Modifier.padding(16.dp)
                    )
                } else {
                    messages.forEach { msg ->
                        CompanionMessageBubble(msg)
                        Spacer(Modifier.height(6.dp))
                    }
                    Spacer(Modifier.height(4.dp))
                }
            }
        }

        HorizontalDivider(
            color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.08f),
            modifier = Modifier.padding(start = 56.dp)
        )
    }
}

@Composable
private fun CompanionMessageBubble(msg: CompanionMessage) {
    val isUser = msg.role == "user"

    // 截图描述卡片（用户侧）
    if (isUser && msg.content.startsWith("[📸]")) {
        val description = msg.content.removePrefix("[📸]").trim()
        CompanionImageDescCard(description = description)
        return
    }
    // 尚未生成描述的截图占位符
    if (isUser && msg.content.startsWith("[帧#")) {
        CompanionImageDescCard(description = "")
        return
    }

    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = if (isUser) Arrangement.Start else Arrangement.End
    ) {
        if (!isUser) Spacer(Modifier.width(40.dp))
        Surface(
            shape = RoundedCornerShape(
                topStart = if (isUser) 4.dp else 12.dp,
                topEnd = if (isUser) 12.dp else 4.dp,
                bottomStart = 12.dp,
                bottomEnd = 12.dp
            ),
            color = if (isUser)
                MaterialTheme.colorScheme.surfaceVariant.copy(0.7f)
            else
                Primary.copy(alpha = 0.12f),
            modifier = Modifier.widthIn(max = 280.dp)
        ) {
            Text(
                text = msg.content,
                style = MaterialTheme.typography.bodySmall,
                color = if (isUser)
                    MaterialTheme.colorScheme.onSurfaceVariant
                else
                    MaterialTheme.colorScheme.onBackground,
                modifier = Modifier.padding(horizontal = 12.dp, vertical = 7.dp)
            )
        }
        if (isUser) Spacer(Modifier.width(40.dp))
    }
}

/**
 * 截图内容描述折叠卡片。
 * description 为空时显示"暂无描述"，非空时默认折叠、点击展开查看全文。
 */
@Composable
private fun CompanionImageDescCard(description: String) {
    var expanded by remember { mutableStateOf(false) }
    val chevronRotation by animateFloatAsState(
        targetValue = if (expanded) 180f else 0f,
        animationSpec = tween(200),
        label = "imgChevron"
    )
    val hasDesc = description.isNotBlank()

    Row(modifier = Modifier.fillMaxWidth()) {
        Surface(
            shape = RoundedCornerShape(topStart = 4.dp, topEnd = 12.dp, bottomStart = 12.dp, bottomEnd = 12.dp),
            color = MaterialTheme.colorScheme.surfaceVariant.copy(0.55f),
            modifier = Modifier
                .widthIn(min = 140.dp, max = 260.dp)
                .then(if (hasDesc) Modifier.clickable { expanded = !expanded } else Modifier)
        ) {
            Column(modifier = Modifier.padding(horizontal = 12.dp, vertical = 8.dp)) {
                // 标题行：相机图标 + "截图内容" + 展开箭头
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(5.dp)
                ) {
                    Icon(
                        Icons.Filled.PhotoCamera,
                        contentDescription = null,
                        modifier = Modifier.size(13.dp),
                        tint = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.65f)
                    )
                    Text(
                        text = "截图内容",
                        style = MaterialTheme.typography.labelSmall,
                        fontWeight = FontWeight.SemiBold,
                        color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.75f),
                        modifier = Modifier.weight(1f)
                    )
                    if (hasDesc) {
                        Icon(
                            Icons.Filled.KeyboardArrowDown,
                            contentDescription = if (expanded) "收起" else "展开",
                            tint = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.45f),
                            modifier = Modifier.size(15.dp).rotate(chevronRotation)
                        )
                    }
                }
                // 展开区域
                AnimatedVisibility(
                    visible = hasDesc && expanded,
                    enter = expandVertically(tween(200)) + fadeIn(tween(180)),
                    exit = shrinkVertically(tween(180)) + fadeOut(tween(140))
                ) {
                    Column {
                        Spacer(Modifier.height(6.dp))
                        HorizontalDivider(
                            color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.12f)
                        )
                        Spacer(Modifier.height(6.dp))
                        Text(
                            text = description,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            lineHeight = 18.sp
                        )
                    }
                }
                // 无描述时显示提示
                if (!hasDesc) {
                    Spacer(Modifier.height(3.dp))
                    Text(
                        text = "（描述生成中…）",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.45f)
                    )
                }
            }
        }
        Spacer(Modifier.width(40.dp))
    }
}

// ==================== 工具函数 ====================

private fun formatDuration(seconds: Int): String {
    return when {
        seconds < 60 -> "${seconds}秒"
        seconds < 3600 -> "${seconds / 60}分钟"
        else -> "${seconds / 3600}小时${(seconds % 3600) / 60}分钟"
    }
}

private fun formatCompanionTitle(endedAt: String): String {
    return try {
        val sdf = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", Locale.getDefault())
        sdf.isLenient = true
        val date = sdf.parse(endedAt.take(19)) ?: return "陪玩记录"
        SimpleDateFormat("M月d日 HH:mm", Locale.getDefault()).format(date) + " 的陪玩"
    } catch (_: Exception) {
        "陪玩记录"
    }
}

private fun formatRelativeTime(isoDateTime: String): String {
    return try {
        val sdf = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", Locale.getDefault())
        sdf.isLenient = true
        val date = sdf.parse(isoDateTime.take(19)) ?: return isoDateTime
        val diffMs = System.currentTimeMillis() - date.time
        val diffSec = diffMs / 1000
        when {
            diffSec < 60 -> "刚刚"
            diffSec < 3600 -> "${diffSec / 60}分钟前"
            diffSec < 86400 -> "${diffSec / 3600}小时前"
            diffSec < 86400 * 30 -> "${diffSec / 86400}天前"
            else -> SimpleDateFormat("M月d日", Locale.getDefault()).format(date)
        }
    } catch (_: Exception) {
        isoDateTime
    }
}

