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

// ==================== 历史对话页面 ====================

private val TAB_CHAT = 0
private val TAB_COMPANION = 1


@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ConversationHistoryScreen(
    viewModel: ChatViewModel,
    character: Character,
    prefs: AppPreferences,
    onNavigateBack: () -> Unit,
    onNavigateToMemory: (() -> Unit)? = null,
    onNavigateToMessagePosition: (sequenceNumber: Int) -> Unit = {}
) {
    var selectedTab by remember { mutableIntStateOf(TAB_CHAT) }
    val scope = rememberCoroutineScope()
    val snackbarHostState = CustomToast.current
    val showPrompt: (String) -> Unit = remember(scope, snackbarHostState) {
        { message ->
            scope.launch { snackbarHostState.showSnackbar(message) }
        }
    }

    // 重置确认弹窗状态
    var showResetDialog by remember { mutableStateOf(false) }
    var isResetting by remember { mutableStateOf(false) }
    var resetMessage by remember { mutableStateOf("") }
    var historyResetVersion by remember { mutableIntStateOf(0) }
    val characterId = character.id ?: ""
    var normalVisibleMessageCount by remember(characterId) { mutableIntStateOf(0) }

    LaunchedEffect(characterId, historyResetVersion) {
        if (characterId.isBlank()) {
            normalVisibleMessageCount = 0
            return@LaunchedEffect
        }
        runCatching {
            val api = NetworkClient.createApiService(prefs)
            val resp = api.countVisibleMessages(
                username = prefs.username,
                characterId = characterId
            )
            if (resp.isSuccessful) {
                normalVisibleMessageCount = resp.body()?.total ?: 0
            }
        }
    }

    // 消息多选删除状态（搜索/浏览界面）已移至 MessageSearchTab 内部管理

    if (showResetDialog) {
        PonyDangerCountdownConfirmDialog(
            title = "重置角色内容",
            message = "将清除与「${character.displayName()}」的所有对话记录、对话记忆和陪玩记录。\n\n游戏/锁分内容不受影响。\n\n此操作不可撤销。",
            confirmText = "确认重置",
            isLoading = isResetting,
            onDismiss = { showResetDialog = false },
            onConfirm = {
                isResetting = true
                scope.launch {
                    try {
                        val api = NetworkClient.createApiService(prefs)
                        val resp = api.resetCharacterChat(
                            ResetCharacterChatRequest(
                                username = prefs.username,
                                characterId = character.id ?: ""
                            )
                        )
                        if (resp.isSuccessful) {
                            historyResetVersion++
                            viewModel.applyNormalResetLocally(resp.body()?.conversationId)
                            viewModel.reloadConversation()
                            showResetDialog = false
                            isResetting = false
                            onNavigateBack()
                        } else {
                            resetMessage = "重置失败 (${resp.code()})"
                        }
                    } catch (e: Exception) {
                        resetMessage = "网络错误，请重试"
                    } finally {
                        isResetting = false
                        showResetDialog = false
                    }
                }
            }
        )
    }

    if (resetMessage.isNotEmpty()) {
        LaunchedEffect(resetMessage) {
            kotlinx.coroutines.delay(2000)
            resetMessage = ""
        }
    }

    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        topBar = {
            PonyTopBar(containerColor = MaterialTheme.colorScheme.background) {
                IconButton(onClick = onNavigateBack) {
                    Icon(
                        Icons.AutoMirrored.Filled.ArrowBack,
                        contentDescription = "返回",
                        tint = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
                Spacer(Modifier.width(4.dp))
                Row(
                    modifier = Modifier.weight(1f),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    CharacterAvatar(
                        avatarUrl = character.avatarUrl(),
                        name = character.displayName(),
                        apiBase = prefs.effectiveApiBase(),
                        size = 28
                    )
                    Spacer(Modifier.width(10.dp))
                    Column {
                        Text(
                            if (selectedTab == TAB_CHAT) {
                                "搜索消息 · 共${normalVisibleMessageCount}条"
                            } else {
                                "陪玩记录"
                            },
                            style = MaterialTheme.typography.titleMedium,
                            fontWeight = FontWeight.SemiBold,
                            color = MaterialTheme.colorScheme.onBackground
                        )
                        Text(
                            character.displayName(),
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis
                        )
                    }
                }
                var showMoreMenu by remember { mutableStateOf(false) }
                Box {
                    IconButton(onClick = { showMoreMenu = true }) {
                        Icon(
                            Icons.Filled.MoreVert,
                            contentDescription = "更多",
                            tint = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                    DropdownMenu(
                        expanded = showMoreMenu,
                        onDismissRequest = { showMoreMenu = false },
                        modifier = Modifier.widthIn(min = 200.dp),
                        shape = RoundedCornerShape(12.dp),
                        containerColor = historyActionMenuContainerColor(),
                        border = historyActionMenuBorder(),
                        tonalElevation = 2.dp
                    ) {
                        DropdownMenuItem(
                            text = { Text("分享对话", color = historyActionMenuContentColor()) },
                            leadingIcon = {
                                Icon(
                                    Icons.Filled.Share,
                                    contentDescription = null,
                                    tint = historyActionMenuContentColor()
                                )
                            },
                            onClick = {
                                showMoreMenu = false
                                viewModel.enterExportMode()
                                onNavigateBack()
                            }
                        )
                        if (onNavigateToMemory != null) {
                            DropdownMenuItem(
                                text = { Text("长期记忆", color = historyActionMenuContentColor()) },
                                leadingIcon = {
                                    Icon(
                                        Icons.Filled.AutoStories,
                                        contentDescription = null,
                                        tint = historyActionMenuContentColor()
                                    )
                                },
                                onClick = {
                                    showMoreMenu = false
                                    onNavigateToMemory()
                                }
                            )
                        }
                        DropdownMenuItem(
                            text = {
                                Text("重置角色", color = historyActionMenuDangerColor())
                            },
                            leadingIcon = {
                                Icon(
                                    Icons.Filled.DeleteSweep,
                                    contentDescription = null,
                                    tint = historyActionMenuDangerColor()
                                )
                            },
                            onClick = {
                                showMoreMenu = false
                                showResetDialog = true
                            }
                        )
                    }
                }
            }
        },
        bottomBar = {
            Surface(
                modifier = Modifier.fillMaxWidth(),
                color = MaterialTheme.colorScheme.surface,
                shadowElevation = 4.dp
            ) {
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .navigationBarsPadding()
                ) {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(58.dp)
                            .align(Alignment.TopCenter)
                            .padding(horizontal = 20.dp, vertical = 2.dp),
                        horizontalArrangement = Arrangement.SpaceEvenly
                    ) {
                        CompactHistoryNavItem(
                            selected = selectedTab == TAB_CHAT,
                            icon = Icons.Filled.Search,
                            label = "搜索",
                            onClick = { selectedTab = TAB_CHAT }
                        )
                        CompactHistoryNavItem(
                            selected = selectedTab == TAB_COMPANION,
                            icon = Icons.Filled.VideogameAsset,
                            label = "陪玩",
                            onClick = { selectedTab = TAB_COMPANION }
                        )
                    }
                }
            }
        }
    ) { innerPadding ->
        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
        ) {
            when (selectedTab) {
                TAB_CHAT -> MessageSearchTab(
                    viewModel = viewModel,
                    character = character,
                    prefs = prefs,
                    resetVersion = historyResetVersion,
                    onNavigateToMessagePosition = onNavigateToMessagePosition,
                    onPrompt = showPrompt,
                    onVisibleMessageDeleted = { deletedCount ->
                        normalVisibleMessageCount = (normalVisibleMessageCount - deletedCount).coerceAtLeast(0)
                    }
                )
                TAB_COMPANION -> Box(
                    modifier = Modifier.fillMaxSize(),
                    contentAlignment = androidx.compose.ui.Alignment.Center
                ) {
                    androidx.compose.material3.Text(
                        text = "功能开发中",
                        style = androidx.compose.material3.MaterialTheme.typography.bodyLarge,
                        color = androidx.compose.material3.MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.5f)
                    )
                }
            }
        }
    }
}

