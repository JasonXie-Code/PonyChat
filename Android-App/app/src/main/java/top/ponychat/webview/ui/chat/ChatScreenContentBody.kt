package top.ponychat.webview.ui.chat

import android.util.Log
import android.Manifest
import android.app.Activity
import android.content.ClipData
import android.content.ClipboardManager
import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.Settings as AndroidSettings
import android.provider.MediaStore
import android.view.View
import android.view.ViewTreeObserver
import android.view.WindowManager
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.ImageDecoder
import android.util.Base64
import android.text.method.LinkMovementMethod
import android.util.TypedValue
import android.widget.TextView
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.*
import androidx.compose.animation.core.*
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.gestures.animateScrollBy
import androidx.compose.foundation.gestures.scrollBy
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.gestures.draggable
import androidx.compose.foundation.gestures.rememberDraggableState
import androidx.compose.foundation.gestures.Orientation
import androidx.compose.foundation.gestures.rememberTransformableState
import androidx.compose.foundation.gestures.transformable
import androidx.compose.ui.input.nestedscroll.NestedScrollConnection
import androidx.compose.ui.input.nestedscroll.NestedScrollSource
import androidx.compose.ui.input.nestedscroll.nestedScroll
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.Velocity
import kotlinx.coroutines.withTimeoutOrNull
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.Chat
import androidx.compose.material.icons.automirrored.filled.Subject
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.material3.AssistChipDefaults
import androidx.compose.material3.TextFieldDefaults
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.pointer.PointerEventPass
import androidx.compose.ui.input.pointer.changedToDown
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.Density
import androidx.compose.ui.draw.BlurredEdgeTreatment
import androidx.compose.ui.draw.blur
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.RectangleShape
import androidx.compose.ui.graphics.compositeOver
import androidx.compose.ui.graphics.luminance
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.layout.positionInWindow
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.compose.foundation.Canvas
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.drawscope.withTransform
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogWindowProvider
import androidx.compose.ui.window.DialogProperties
import androidx.compose.ui.zIndex
import androidx.core.content.ContextCompat
import androidx.core.graphics.drawable.toBitmap
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsAnimationCompat
import androidx.core.view.WindowInsetsCompat as ViewWindowInsetsCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import coil.compose.AsyncImage
import coil.imageLoader
import coil.request.ImageRequest
import io.noties.markwon.Markwon
import io.noties.markwon.ext.strikethrough.StrikethroughPlugin
import io.noties.markwon.ext.tables.TablePlugin
import io.noties.markwon.linkify.LinkifyPlugin
import kotlin.math.max
import kotlin.math.roundToInt
import kotlinx.coroutines.delay
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.FlowPreview
import kotlinx.coroutines.flow.debounce
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import top.ponychat.webview.BackendStreamingVoiceBridge
import top.ponychat.webview.CompanionService
import top.ponychat.webview.CustomToast
import top.ponychat.webview.data.api.SyncWebSocketManager
import top.ponychat.webview.data.model.Character
import top.ponychat.webview.data.model.GalgameOptionItem
import top.ponychat.webview.data.model.ModelInfo
import top.ponychat.webview.data.model.Message
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.ui.character.CharacterAvatar
import top.ponychat.webview.ui.common.PonyAvatar
import top.ponychat.webview.ui.common.PonyPromptBubble
import top.ponychat.webview.ui.common.SystemNavigationBarColorEffect
import top.ponychat.webview.ui.common.WheelStringColumn
import top.ponychat.webview.ui.common.resolveAvatarUrlForApi
import top.ponychat.webview.ui.settings.CrisisHotlineDialog
import top.ponychat.webview.ui.theme.*
import top.ponychat.webview.util.ChatCompletionSource
import top.ponychat.webview.util.ChatEventBus
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.text.input.KeyboardType
import java.io.ByteArrayOutputStream
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Date
import java.util.Locale


@OptIn(
    ExperimentalMaterial3Api::class,
    ExperimentalFoundationApi::class,
    ExperimentalLayoutApi::class,
    kotlinx.coroutines.FlowPreview::class
)
@Composable
internal fun ChatScreenContentBody(
    viewModel: ChatViewModel,
    character: Character,
    allCharacters: List<Character> = emptyList(),
    prefs: AppPreferences,
    onNavigateBack: () -> Unit,
    onNavigateToEditCharacter: () -> Unit = {},
    onNavigateToCharacterProfile: (Character) -> Unit = {},
    characterHome: @Composable (() -> Unit) -> Unit,
    onNavigateToSettings: () -> Unit = {},
    onNavigateToProactiveTasks: () -> Unit = {},
    onNavigateToHistory: () -> Unit = {},
    onThemeChanged: (Boolean) -> Unit = {}
) {
    val state by viewModel.state.collectAsState()
    // 加载遮罩：不再绑定 conversationId 作为 key——当 conversationId 从 null 变为服务端值时，
    // remember(key) 会销毁旧 State 并创建新 State，AnimatedVisibility 在切换瞬间产生 1-2 帧空白闪烁。
    // 只用角色 + 模式作为生命周期 key，避免 conversationId 从 null 变为服务端值时重建遮罩。
    // 不在组合正文里写 State；Compose 会在 key 变化时自然创建新状态。
    val loadingOverlayScopeKey = "${character.id.orEmpty()}#${state.mode}"
    var initialLoadingOverlayDismissed by remember(loadingOverlayScopeKey) { mutableStateOf(false) }
    var showLoadingOverlay by remember(loadingOverlayScopeKey) { mutableStateOf(true) }
    LaunchedEffect(state.isLoadingHistory, initialLoadingOverlayDismissed, showLoadingOverlay) {
        if (state.isLoadingHistory && !showLoadingOverlay && !initialLoadingOverlayDismissed) {
            showLoadingOverlay = true
        }
    }

    val listInitialAnchorReady = remember(character.id, state.mode) { booleanArrayOf(false) }
    if ((state.isLoadingHistory || state.messages.isEmpty()) && listInitialAnchorReady[0]) {
        listInitialAnchorReady[0] = false
    }
    if (!listInitialAnchorReady[0] && !state.isLoadingHistory && state.messages.isNotEmpty()) {
        listInitialAnchorReady[0] = true
    }
    val listStateKey = "${character.id.orEmpty()}#${state.mode}#${if (listInitialAnchorReady[0]) "anchored" else "loading"}"
    val listInitialIndex = if (listInitialAnchorReady[0]) state.messages.lastIndex.coerceAtLeast(0) else 0
    val listState = key(listStateKey) {
        rememberLazyListState(initialFirstVisibleItemIndex = listInitialIndex)
    }
    val imeSync = rememberImeSyncState(enabled = !prefs.debugDisableImeScroll)
    val imeBottomState = imeSync.imeBottomPx
    val imeTargetBottomState = imeSync.imeTargetBottomPx
    val imeAnimatingState = imeSync.isImeAnimating
    /** 键盘系统 IME 显隐动画未结束前不执行 LazyColumn 跟滚，避免与 ADJUST_NOTHING + graphicsLayer 平移叠加导致闪动（普通/Galgame/锁分同逻辑）。 */
    suspend fun awaitImeNotAnimating() {
        if (prefs.debugDisableImeScroll) return
        var n = 0
        val cap = 4000 / 16
        while (imeAnimatingState.value && n < cap) {
            delay(16)
            n++
        }
    }
    // ── 重组诊断：仅 DEBUG 构建生效，用于定位滑动卡顿来源 ──
    if (top.ponychat.webview.BuildConfig.DEBUG) {
        val chatScreenRecomposeCount = remember { intArrayOf(0) }
        // 记录上一次 state 快照，用于差分比较
        val prevStateRef = remember { arrayOfNulls<top.ponychat.webview.ui.chat.ChatUiState>(1) }
        SideEffect {
            chatScreenRecomposeCount[0]++
            val cur = state
            val prev = prevStateRef[0]
            val changedFields = if (prev == null) "(首次)" else buildString {
                if (prev.messages !== cur.messages) {
                    val lastPrev = prev.messages.lastOrNull()
                    val lastCur  = cur.messages.lastOrNull()
                    append("msgs(${prev.messages.size}->${cur.messages.size}")
                    if (lastPrev?.rawContent?.length != lastCur?.rawContent?.length)
                        append(" lastRaw:${lastPrev?.rawContent?.length}->${lastCur?.rawContent?.length}")
                    if (lastPrev?.displayContent?.length != lastCur?.displayContent?.length)
                        append(" lastDisplay:${lastPrev?.displayContent?.length}->${lastCur?.displayContent?.length}")
                    append(")")
                }
                if (prev.isStreaming        != cur.isStreaming)        append(" streaming(${prev.isStreaming}->${cur.isStreaming})")
                if (prev.isBackgroundRefreshing != cur.isBackgroundRefreshing) append(" bgRefr(${prev.isBackgroundRefreshing}->${cur.isBackgroundRefreshing})")
                if (prev.galgameScore       != cur.galgameScore)       append(" gScore(${prev.galgameScore}->${cur.galgameScore})")
                if (prev.replyTimer         != cur.replyTimer)         append(" timer(${prev.replyTimer}->${cur.replyTimer})")
                if (prev.isTimerRunning     != cur.isTimerRunning)     append(" timerRun(${prev.isTimerRunning}->${cur.isTimerRunning})")
                if (prev.inputText          != cur.inputText)          append(" input")
                if (prev.mode               != cur.mode)               append(" mode(${prev.mode}->${cur.mode})")
                if (prev.chatSettings       != cur.chatSettings)       append(" settings")
                if (prev.contextUsedTokens  != cur.contextUsedTokens)  append(" tokens(${prev.contextUsedTokens}->${cur.contextUsedTokens})")
                if (prev.galgameSaveFailed  != cur.galgameSaveFailed)  append(" saveFailed")
                if (prev.lockCharVitals     != cur.lockCharVitals)     append(" vitals")
                if (prev.lockCharMood       != cur.lockCharMood)       append(" mood")
                if (prev.lockOrganFill      != cur.lockOrganFill)      append(" organFill")
                if (prev.error              != cur.error)              append(" error")
                if (prev.voiceState         != cur.voiceState)         append(" voiceState")
                if (prev.conversations      != cur.conversations)      append(" convList")
                if (prev.isLoadingHistory   != cur.isLoadingHistory)   append(" loadHist")
                if (prev.conversationId     != cur.conversationId)     append(" convId")
                if (prev.quotaExceeded      != cur.quotaExceeded)      append(" quota")
                if (isEmpty()) append("(其他字段)")
            }
            Log.d("PERF_RECOMPOSE", "ChatScreen #${chatScreenRecomposeCount[0]}  msgs=${cur.messages.size}  streaming=${cur.isStreaming}  changed=$changedFields")
            prevStateRef[0] = cur
        }
    }


    // 记录「需要播放进场动画」的新消息 ID 集合。
    // 只有初始加载完成后新增的消息才会进入此集合；历史消息、滚动回视窗的旧消息不做动画。
    val pendingAnimationIds = remember(state.conversationId) { mutableSetOf<String>() }
    // 已见消息 ID 集合，用来检测哪些是新增消息；对话切换时随 conversationId 重置。
    val knownMsgIds = remember(state.conversationId) { mutableSetOf<String>() }
    // 初始加载是否已完成（BooleanArray 避免修改时触发重组）
    val initialLoadDone = remember(state.conversationId) { BooleanArray(1) { false } }
    val knownMsgCount = remember(state.conversationId) { IntArray(1) { 0 } }

    if (!initialLoadDone[0] && !state.isLoadingHistory && state.messages.isNotEmpty()) {
        // 首次加载完成：把当前所有消息登记为「已知」，但不加入 pending（历史消息不动画）
        knownMsgIds.addAll(state.messages.map { it.stableChatItemKey() })
        initialLoadDone[0] = true
        knownMsgCount[0] = state.messages.size
    } else if (initialLoadDone[0]) {
        // 加载完成后只有真正追加到尾部的新消息才播放进场动画。
        // Galgame 回复落地、后台刷新会替换本地占位消息的 key；这类同长度更新只登记为已知，
        // 避免上一条用户消息和本次角色消息被当成新 item 短暂重放发送动画。
        val previousCount = knownMsgCount[0]
        val appendedAtTail = state.messages.size > previousCount
        for ((index, msg) in state.messages.withIndex()) {
            val msgKey = msg.stableChatItemKey()
            if (knownMsgIds.add(msgKey)) {
                if (
                    appendedAtTail &&
                    index >= previousCount &&
                    !state.isLoadingHistory &&
                    !state.isBackgroundRefreshing &&
                    msg.allowRealtimeAnimation
                ) {
                    pendingAnimationIds.add(msgKey)
                }
            }
        }
        knownMsgCount[0] = state.messages.size
    }

    // 用户主动上滑后停止流式自动跟随；到达底部时自动重置
    val userScrolledUpState = remember { mutableStateOf(false) }
    // 仅记录当前是否有手指按在消息列表上；是否真正“脱离自动跟随”取决于有没有实际拖动
    val listTouchActiveState = remember { mutableStateOf(false) }
    // 当前回复期间，只要用户真实拖动过消息列表，就暂停自动跟随；下一条用户消息或显式回到底部再恢复。
    val listAutoFollowSuppressedState = remember(state.conversationId) { mutableStateOf(false) }
    // 游戏/锁分模式下，AI 回复会先插入 streaming 占位气泡；
    // 只有等最终内容落地后再对齐，才能避免长消息把视口再次顶偏。
    val pendingGalgameAutoScrollAssistantIdState = remember(state.conversationId) { mutableStateOf<String?>(null) }
    val context = LocalContext.current
    val coroutineScope = rememberCoroutineScope()
    val snackbarHostState = CustomToast.current
    val showUsageReminder by viewModel.showUsageReminder.collectAsState()
    val showCrisisHotlineDialog by viewModel.showCrisisHotlineDialog.collectAsState()
    val showPrompt: (String) -> Unit = remember(coroutineScope, snackbarHostState) {
        { msg ->
            coroutineScope.launch {
                snackbarHostState.showSnackbar(msg)
            }
        }
    }
    // 游戏/锁分模式：动态测量好感度胶囊高度，用于滚动定位
    val capsuleHeightPxState = remember { mutableIntStateOf(0) }
    val galgameTopAnchorGapPx = with(LocalDensity.current) { 8.dp.roundToPx() }
    // 这些坐标由 Scaffold 主体更新，滚动 effect 用它们避开输入栏/键盘遮挡。
    val lastAILayoutBottomPx = remember { mutableFloatStateOf(0f) }
    val inputBarLayoutTopPx = remember { mutableFloatStateOf(0f) }
    val inputBarHeightPx = remember { mutableFloatStateOf(0f) }
    val lazyColumnTopPx = remember { mutableFloatStateOf(0f) }
    val listEffectiveViewportEndPxState = remember { mutableIntStateOf(Int.MAX_VALUE) }
    val scrollNaturalBottomPaddingPx = with(LocalDensity.current) { 8.dp.toPx().roundToInt() }
    val scrollBottomAnchorTolerancePx = with(LocalDensity.current) { 2.dp.toPx() }

    // 退出聊天界面时：若上一轮请求失败，移除顶部错误提示与本轮失败配对的用户/助手气泡（与再次发送时的清理一致）
    DisposableEffect(Unit) {
        onDispose {
            viewModel.clearFailedChatRoundIfNeeded()
        }
    }

    val lifecycleOwnerChat = LocalLifecycleOwner.current
    val activeCharId = character.id?.takeIf { it.isNotBlank() }.orEmpty()
    val activeMode = state.mode
    val activeConversationId = state.conversationId.orEmpty()
    val latestStateForLifecycle = rememberUpdatedState(state)
    val foregroundResumeAutoFollowSnapshotState = remember(activeCharId, activeMode) {
        mutableStateOf<ForegroundResumeAutoFollowSnapshot?>(null)
    }
    val foregroundResumeAutoFollowTickState = remember(activeCharId, activeMode) {
        mutableIntStateOf(0)
    }
    fun currentLifecycleEffectiveViewportEndPx(): Int? =
        listEffectiveViewportEndPxState.intValue
            .takeIf { it in 1 until Int.MAX_VALUE }

    DisposableEffect(activeCharId, activeMode, activeConversationId, lifecycleOwnerChat) {
        val obs = LifecycleEventObserver { _, e ->
            when (e) {
                Lifecycle.Event.ON_RESUME -> {
                    if (activeCharId.isNotBlank()) {
                        foregroundResumeAutoFollowSnapshotState.value
                            ?.takeIf { snapshot ->
                                snapshot.characterId == activeCharId &&
                                    snapshot.mode == activeMode &&
                                    (
                                        snapshot.conversationId.isBlank() ||
                                            activeConversationId.isBlank() ||
                                            snapshot.conversationId == activeConversationId
                                        ) &&
                                    snapshot.wasLastMessageVisible
                            }
                            ?.let { snapshot ->
                                foregroundResumeAutoFollowSnapshotState.value = snapshot.copy(
                                    resumeRequestedAtMs = System.currentTimeMillis()
                                )
                                foregroundResumeAutoFollowTickState.intValue += 1
                                Log.d(
                                    "GalScroll",
                                    "foreground-resume follow requested count=${snapshot.messageCount} last=${snapshot.lastMessageKey?.take(8)}"
                                )
                            }
                        ChatEventBus.setActiveChat(activeCharId, activeMode)
                        SyncWebSocketManager.setActiveChat(activeCharId, activeMode, activeConversationId)
                        ChatEventBus.markRead(activeCharId, activeMode)
                        viewModel.onForegroundResume()
                    }
                }
                Lifecycle.Event.ON_PAUSE -> {
                    val curState = latestStateForLifecycle.value
                    foregroundResumeAutoFollowSnapshotState.value =
                        if (activeCharId.isNotBlank() && curState.messages.isNotEmpty()) {
                            ForegroundResumeAutoFollowSnapshot(
                                characterId = activeCharId,
                                mode = activeMode,
                                conversationId = activeConversationId,
                                messageCount = curState.messages.size,
                                lastMessageKey = curState.messages.lastOrNull()?.stableChatItemKey(),
                                wasLastMessageVisible = listState.canSeeLastItem(currentLifecycleEffectiveViewportEndPx()),
                                pausedAtMs = System.currentTimeMillis(),
                            )
                        } else {
                            null
                        }
                    foregroundResumeAutoFollowSnapshotState.value?.let { snapshot ->
                        Log.d(
                            "GalScroll",
                            "foreground-pause snapshot visible=${snapshot.wasLastMessageVisible} count=${snapshot.messageCount} last=${snapshot.lastMessageKey?.take(8)}"
                        )
                    }
                    ChatEventBus.clearActiveChat()
                    SyncWebSocketManager.clearActiveChat(activeCharId, activeMode, activeConversationId)
                }
                else -> {}
            }
        }
        lifecycleOwnerChat.lifecycle.addObserver(obs)
        if (lifecycleOwnerChat.lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED) && activeCharId.isNotBlank()) {
            // 这里只补登记当前可见会话；进入页面的历史加载由 initWithCharacter 负责。
            // conversationId 落定会重建此 effect，若在这里触发前台恢复会造成一次额外加载。
            ChatEventBus.setActiveChat(activeCharId, activeMode)
            SyncWebSocketManager.setActiveChat(activeCharId, activeMode, activeConversationId)
            ChatEventBus.markRead(activeCharId, activeMode)
        }
        onDispose {
            lifecycleOwnerChat.lifecycle.removeObserver(obs)
            ChatEventBus.clearActiveChat()
            SyncWebSocketManager.clearActiveChat(activeCharId, activeMode, activeConversationId)
        }
    }

    LaunchedEffect(viewModel) {
        launch {
            viewModel.snackbarMessages.collect { msg ->
                snackbarHostState.showSnackbar(msg)
            }
        }
        delay(80)
        viewModel.flushPendingSendFailurePrompt()
    }

    ChatScreenUsageReminderDialog(
        visible = showUsageReminder,
        onDismiss = { viewModel.dismissUsageReminder() }
    )

    if (showCrisisHotlineDialog) {
        CrisisHotlineDialog(onDismiss = { viewModel.dismissCrisisHotlineDialog() })
    }

    // 用户在底部附近时才自动跟随滚动，避免流式阶段频繁滚动导致卡顿
    val isNearBottomState = remember {
        derivedStateOf {
            val layoutInfo = listState.layoutInfo
            val totalItems = layoutInfo.totalItemsCount
            if (totalItems == 0) true
            else {
                val lastVisible = layoutInfo.visibleItemsInfo.lastOrNull()?.index ?: -1
                lastVisible >= totalItems - 2
            }
        }
    }
    // 生命周期日志：辅助排查锁屏/解锁、切后台等场景下的滚动异常
    DisposableEffect(lifecycleOwnerChat) {
        val observer = androidx.lifecycle.LifecycleEventObserver { _, event ->
            Log.d("GalScroll", "lifecycle: $event | mode=${state.mode} streaming=${state.isStreaming} pendingId=${pendingGalgameAutoScrollAssistantIdState.value} userScrolledUp=${userScrolledUpState.value} isNearBottom=${isNearBottomState.value}")
        }
        lifecycleOwnerChat.lifecycle.addObserver(observer)
        onDispose { lifecycleOwnerChat.lifecycle.removeObserver(observer) }
    }

    // 实时监听 WebSocket 推送的主动消息：追加到当前对话（若 conversationId 匹配）并自动滚到底部
    LaunchedEffect(activeCharId, activeMode, viewModel, listState) {
        if (activeCharId.isBlank()) return@LaunchedEffect
        ChatEventBus.completedFlow.collect { event ->
            if (
                event.characterId == activeCharId &&
                event.mode == activeMode &&
                event.source != ChatCompletionSource.FOREGROUND
            ) {
                val shouldFollowIncoming = if (activeMode == "normal") {
                    isNearBottomState.value &&
                        !listTouchActiveState.value &&
                        !listAutoFollowSuppressedState.value
                } else {
                    isNearBottomState.value
                }
                ChatEventBus.markRead(activeCharId, activeMode)
                if (shouldFollowIncoming && !activeMode.startsWith("galgame")) {
                    listAutoFollowSuppressedState.value = false
                    userScrolledUpState.value = false
                }
                if (activeMode == "normal") {
                    viewModel.refreshNormalMessageDelivery(event)
                } else {
                    viewModel.refreshConversationFromServer()
                }
            }
        }
    }

    LaunchedEffect(activeCharId, activeMode, viewModel) {
        if (activeCharId.isBlank()) return@LaunchedEffect
        ChatEventBus.networkAvailableFlow.collect {
            viewModel.onNetworkAvailable()
        }
    }

    LaunchedEffect(activeCharId, activeMode, viewModel) {
        if (activeCharId.isBlank() || activeMode != "normal") return@LaunchedEffect
        top.ponychat.webview.data.api.SyncWebSocketManager.messageUpdateFlow.collect { update ->
            val updateCharId = update.characterId?.takeIf { it.isNotBlank() }
            if (updateCharId == null || updateCharId == activeCharId) {
                viewModel.applyVoiceMessageUpdate(update)
            }
        }
    }

    var voiceBridge by remember { mutableStateOf<BackendStreamingVoiceBridge?>(null) }
    val showDisplaySettingsState = rememberSaveable { mutableStateOf(false) }
    val pendingImages = remember { mutableStateListOf<String>() }
    var previewImageUrl by remember { mutableStateOf<String?>(null) }
    var previewImages by remember { mutableStateOf<List<String>>(emptyList()) }
    var previewIndex by remember { mutableIntStateOf(0) }
    // 跟踪字体大小、时间戳变化，用于触发UI更新
    var currentFontScale by remember { mutableFloatStateOf(prefs.fontScale) }
    var currentShowTimestamp by remember { mutableStateOf(prefs.showTimestamp) }
    // 调试开关响应式状态（SharedPreferences 无响应性，需用 state 驱动 UI 更新）
    var currentDebugShowMessageIds by remember { mutableStateOf(prefs.debugShowMessageIds) }
    var currentDebugShowRawContent by remember { mutableStateOf(prefs.debugShowRawContent) }
    // 加载超时标志：30s 内未完成加载时置为 true，触发返回角色列表
    var loadFailed by remember { mutableStateOf(false) }
    // 进入聊天页时优先展示本地缓存：遮罩只等待本地首帧可定位，不再等待后台服务端刷新结束。
    val canDismissOverlay = !state.isLoadingHistory
    LaunchedEffect(canDismissOverlay, state.conversationId, listState) {
        if (canDismissOverlay) {
            // 遮罩已揭开时（正常对话中 canDismissOverlay 反复变化），不重复执行滚动逻辑。
            // 例如：非 galgame 下 canDismissOverlay 在对话中途从 false 变 true 时，若不 guard
            // 会重复执行 scrollBy(100_000f) 瞬移。
            if (!showLoadingOverlay) return@LaunchedEffect
            // 策略：
            //   1. 若有消息：等待 LazyColumn 完成初帧布局（visibleItemsInfo 非空 = items 已测量渲染），
            //      而非依赖固定 200ms——保证所有机型/长对话下 scrollBy 调用时列表已就绪
            //   2. 若无消息：500ms 短等后直接揭开（无内容需要滚动）
            //   3. 滚到绝对底部，再追加 300ms，确保 MarkdownText/图片等重型内容稳定后才揭开遮罩
            if (state.messages.isNotEmpty()) {
                withTimeoutOrNull(2000) {
                    snapshotFlow { listState.layoutInfo.visibleItemsInfo.isNotEmpty() }
                        .first { it }
                }
                delay(50)
                awaitImeNotAnimating()
                val isGalgameMode = state.mode.startsWith("galgame")
                val isWaitingOnGalgameTyping = isGalgameMode &&
                    state.isStreaming &&
                    state.messages.lastOrNull()?.let { it.isAssistant() && it.content.isBlank() } == true
                if (isGalgameMode && !isWaitingOnGalgameTyping) {
                    if (state.galgameScore != null && capsuleHeightPxState.intValue == 0) {
                        withTimeoutOrNull(500) {
                            snapshotFlow { capsuleHeightPxState.intValue }.first { it > 0 }
                        }
                    }
                    chatScrollToLastAssistantInGalgame(
                        listState = listState,
                        messages = state.messages,
                        topAnchorPx = capsuleHeightPxState.intValue + galgameTopAnchorGapPx,
                        awaitImeNotAnimating = { awaitImeNotAnimating() },
                        animated = false,
                    )
                } else {
                    chatScrollToBottomAndRepair(
                        listState = listState,
                        lastMessageId = state.messages.lastOrNull()?.stableChatItemKey(),
                        naturalBottomPaddingPx = scrollNaturalBottomPaddingPx,
                        bottomAnchorTolerancePx = scrollBottomAnchorTolerancePx,
                        reason = "initial-presentation",
                        settleDelayMs = 16L,
                        effectiveViewportEndOffsetPx = listEffectiveViewportEndPxState.intValue
                            .takeIf { it in 1 until Int.MAX_VALUE },
                        expectedItemCount = state.messages.size,
                    )
                }
                // 等待最后一个 item 真正进入 visibleItemsInfo（= LazyColumn 已 compose 底部内容）。
                // 固定 delay 不可靠：游戏/锁分模式的 AI 回复结构复杂，滚入视口后仍需 composition pass，
                // 用 snapshotFlow 响应式等待确保最后一条消息渲染完成后再揭开遮罩。
                withTimeoutOrNull(3000) {
                    snapshotFlow {
                        val info = listState.layoutInfo
                        val lastVisible = info.visibleItemsInfo.lastOrNull()
                        lastVisible != null && lastVisible.index >= info.totalItemsCount - 1
                    }.first { it }
                }
            } else {
                delay(500)
            }
            // 最终 300ms 缓冲：确保布局完全静止后再揭开遮罩，防止看到任何中间态
            delay(300)
            initialLoadingOverlayDismissed = true
            showLoadingOverlay = false
        } else {
            // 兜底超时：30s 仍未完成加载，不强制揭开遮罩（避免显示残留的中间态对话），
            // 而是返回角色列表并通过全局自定义提示告知用户加载失败
            delay(30_000)
            loadFailed = true
        }
    }
    // 加载超时处理：全局自定义提示后返回角色列表（全局 host 在导航后仍可显示）
    LaunchedEffect(loadFailed) {
        if (loadFailed) {
            showPrompt("加载失败")
            onNavigateBack()
        }
    }
    // 普通对话模式中，当 MessageBubble 内部串行步骤
    // （renderAsMarkdown → showActionBarDelayed → fadeIn）全部完成后，
    // 通过 onActionBarVisible 回调触发滚到底部。

    val awaitIme: suspend () -> Unit = suspend { awaitImeNotAnimating() }
    val scrollToLastAssistantInGalgame: suspend (Boolean) -> Unit = { animated ->
        chatScrollToLastAssistantInGalgame(
            listState,
            state.messages,
            capsuleHeightPxState.intValue + galgameTopAnchorGapPx,
            awaitIme,
            animated
        )
    }

    ChatForegroundResumeFollow(
        listState = listState, state = state,
        activeCharId = activeCharId, activeMode = activeMode, activeConversationId = activeConversationId,
        foregroundResumeAutoFollowSnapshotState = foregroundResumeAutoFollowSnapshotState,
        foregroundResumeAutoFollowTickState = foregroundResumeAutoFollowTickState,
        listTouchActiveState = listTouchActiveState,
        listAutoFollowSuppressedState = listAutoFollowSuppressedState,
        userScrolledUpState = userScrolledUpState,
        showLoadingOverlay = showLoadingOverlay,
        scrollNaturalBottomPaddingPx = scrollNaturalBottomPaddingPx,
        scrollBottomAnchorTolerancePx = scrollBottomAnchorTolerancePx,
        currentLifecycleEffectiveViewportEndPx = { currentLifecycleEffectiveViewportEndPx() },
        isForeground = { lifecycleOwnerChat.lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED) },
        awaitImeNotAnimating = { awaitImeNotAnimating() },
        scrollToLastAssistantInGalgame = { scrollToLastAssistantInGalgame(it) },
    )

    // ── 陪玩：悬浮窗 + 屏幕截图 ──────────────────────────────────────────────
    val isCompanionActive by CompanionService.isRunning.collectAsState()
    val isAgentCompanionActive by CompanionService.isAgentRunning.collectAsState()
    val isAgentAutoLooping by CompanionService.isAutoLooping.collectAsState()

    val screenCaptureLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (result.resultCode == Activity.RESULT_OK && result.data != null) {
            val serviceIntent = Intent(context, CompanionService::class.java).apply {
                action = CompanionService.ACTION_START
                putExtra(CompanionService.EXTRA_RESULT_CODE, result.resultCode)
                putExtra(CompanionService.EXTRA_RESULT_DATA, result.data)
                putExtra(CompanionService.EXTRA_CHARACTER_ID, character.id)
                putExtra(CompanionService.EXTRA_CHARACTER_NAME, character.name)
                putExtra(CompanionService.EXTRA_CHARACTER_PERSONALITY, character.profilePersonality.orEmpty())
                putExtra(CompanionService.EXTRA_AUTH_TOKEN, prefs.authToken)
                putExtra(CompanionService.EXTRA_API_BASE, prefs.effectiveApiBase())
                putExtra(CompanionService.EXTRA_USERNAME, prefs.username)
                putExtra(CompanionService.EXTRA_AVATAR_URL,
                    resolveAvatarUrlForApi(character.avatarUrl(), prefs.effectiveApiBase()))
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(serviceIntent)
            } else {
                context.startService(serviceIntent)
            }
        }
    }

    // 陪玩需要 RECORD_AUDIO（长按语音输入）；授权后直接发起录屏请求
    val recordAudioForCompanionLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestPermission()
    ) { granted ->
        if (!granted) {
            showPrompt("麦克风权限已拒绝，长按语音功能将不可用")
        }
        val projManager = context.getSystemService(Context.MEDIA_PROJECTION_SERVICE)
            as android.media.projection.MediaProjectionManager
        screenCaptureLauncher.launch(projManager.createScreenCaptureIntent())
    }

    fun startCompanion() {
        val chVision = (state.character ?: character).effectiveSupportsVision()
        if (!chVision) {
            showPrompt("当前角色已关闭识图能力")
            return
        }
        if (!AndroidSettings.canDrawOverlays(context)) {
            val intent = Intent(
                AndroidSettings.ACTION_MANAGE_OVERLAY_PERMISSION,
                Uri.parse("package:${context.packageName}")
            )
            context.startActivity(intent)
            showPrompt("请授予「显示在其他应用上层」权限后再开启聊天陪玩")
            return
        }
        val hasAudio = ContextCompat.checkSelfPermission(
            context, Manifest.permission.RECORD_AUDIO
        ) == PackageManager.PERMISSION_GRANTED
        if (!hasAudio) {
            recordAudioForCompanionLauncher.launch(Manifest.permission.RECORD_AUDIO)
            return
        }
        val projManager = context.getSystemService(Context.MEDIA_PROJECTION_SERVICE)
            as android.media.projection.MediaProjectionManager
        screenCaptureLauncher.launch(projManager.createScreenCaptureIntent())
    }

    fun stopCompanion() {
        context.startService(
            Intent(context, CompanionService::class.java).apply { action = CompanionService.ACTION_STOP }
        )
    }

    // ── 操作陪玩（Agent 模式）：复用录屏权限流程，额外需要无障碍服务 ──────────

    val agentScreenCaptureLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (result.resultCode == Activity.RESULT_OK && result.data != null) {
            val serviceIntent = Intent(context, CompanionService::class.java).apply {
                action = CompanionService.ACTION_START
                putExtra(CompanionService.EXTRA_RESULT_CODE, result.resultCode)
                putExtra(CompanionService.EXTRA_RESULT_DATA, result.data)
                putExtra(CompanionService.EXTRA_CHARACTER_ID, character.id)
                putExtra(CompanionService.EXTRA_CHARACTER_NAME, character.name)
                putExtra(CompanionService.EXTRA_CHARACTER_PERSONALITY, character.profilePersonality.orEmpty())
                putExtra(CompanionService.EXTRA_AUTH_TOKEN, prefs.authToken)
                putExtra(CompanionService.EXTRA_API_BASE, prefs.effectiveApiBase())
                putExtra(CompanionService.EXTRA_USERNAME, prefs.username)
                putExtra(CompanionService.EXTRA_AVATAR_URL,
                    resolveAvatarUrlForApi(character.avatarUrl(), prefs.effectiveApiBase()))
                putExtra(CompanionService.EXTRA_AGENT_MODE, true)
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(serviceIntent)
            } else {
                context.startService(serviceIntent)
            }
        }
    }

    val recordAudioForAgentLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestPermission()
    ) { granted ->
        if (!granted) {
            showPrompt("麦克风权限已拒绝，语音功能将不可用")
        }
        val projManager = context.getSystemService(Context.MEDIA_PROJECTION_SERVICE)
            as android.media.projection.MediaProjectionManager
        agentScreenCaptureLauncher.launch(projManager.createScreenCaptureIntent())
    }

    fun startAgentCompanion() {
        val chVisionAgent = (state.character ?: character).effectiveSupportsVision()
        if (!chVisionAgent) {
            showPrompt("当前角色已关闭识图能力")
            return
        }
        // 检查无障碍服务是否已开启
        if (!top.ponychat.webview.AgentAccessibilityService.isEnabled.value) {
            val intent = Intent(android.provider.Settings.ACTION_ACCESSIBILITY_SETTINGS)
            context.startActivity(intent)
            showPrompt("请在无障碍设置中开启「PonyChat 操作陪玩」，再返回开启操作陪玩")
            return
        }
        if (!android.provider.Settings.canDrawOverlays(context)) {
            val intent = Intent(
                android.provider.Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                Uri.parse("package:${context.packageName}")
            )
            context.startActivity(intent)
            showPrompt("请授予「显示在其他应用上层」权限后再开启操作陪玩")
            return
        }
        val hasAudio = ContextCompat.checkSelfPermission(
            context, Manifest.permission.RECORD_AUDIO
        ) == PackageManager.PERMISSION_GRANTED
        if (!hasAudio) {
            recordAudioForAgentLauncher.launch(Manifest.permission.RECORD_AUDIO)
            return
        }
        val projManager = context.getSystemService(Context.MEDIA_PROJECTION_SERVICE)
            as android.media.projection.MediaProjectionManager
        agentScreenCaptureLauncher.launch(projManager.createScreenCaptureIntent())
    }

    fun stopAgentCompanion() {
        context.startService(
            Intent(context, CompanionService::class.java).apply { action = CompanionService.ACTION_STOP }
        )
    }

    val imagePickerLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.PickMultipleVisualMedia(maxItems = 4)
    ) { uris ->
        val remaining = 4 - pendingImages.size
        if (remaining <= 0 || uris.isEmpty()) return@rememberLauncherForActivityResult
        coroutineScope.launch {
            for (uri in uris.take(remaining)) {
                if (pendingImages.size >= 4) break
                val localImageUrl = withContext(Dispatchers.IO) {
                    saveLocalChatImageFromUri(context, uri)
                }
                if (!localImageUrl.isNullOrBlank()) {
                    pendingImages.add(localImageUrl)
                } else {
                    showPrompt("图片本地保存失败，未加入消息")
                }
            }
        }
    }
    var pendingCameraUri by remember { mutableStateOf<Uri?>(null) }
    val takePictureLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.TakePicture()
    ) { success ->
        val u = pendingCameraUri
        pendingCameraUri = null
        if (u == null) return@rememberLauncherForActivityResult
        if (success) {
            markPonyChatCameraImageReady(context, u)
            coroutineScope.launch {
                val localImageUrl = withContext(Dispatchers.IO) {
                    saveLocalChatImageFromUri(context, u)
                }
                withContext(Dispatchers.Main) {
                    if (!localImageUrl.isNullOrBlank()) {
                        pendingImages.add(localImageUrl)
                    } else {
                        showPrompt("图片本地保存失败，未加入消息")
                    }
                }
            }
        } else {
            deletePonyChatCameraImage(context, u)
        }
    }
    val cameraPermissionLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestPermission()
    ) { granted ->
        if (granted && pendingImages.size < 4) {
            val uri = createPonyChatCameraImageUriForTakePicture(context)
            if (uri == null) {
                showPrompt("无法创建图片文件")
            } else {
                pendingCameraUri = uri
                takePictureLauncher.launch(uri)
            }
        }
    }
    val onPickChatCamera: () -> Unit = pick@{
        if (pendingImages.size >= 4) {
            showPrompt("最多 4 张图片")
            return@pick
        }
        val granted = ContextCompat.checkSelfPermission(
            context, Manifest.permission.CAMERA
        ) == PackageManager.PERMISSION_GRANTED
        if (granted) {
            val uri = createPonyChatCameraImageUriForTakePicture(context)
            if (uri == null) {
                showPrompt("无法创建图片文件")
            } else {
                pendingCameraUri = uri
                takePictureLauncher.launch(uri)
            }
        } else {
            cameraPermissionLauncher.launch(Manifest.permission.CAMERA)
        }
    }

    LaunchedEffect(character) {
        if (viewModel.state.value.character?.id != character.id) {
            viewModel.initWithCharacter(character)
        }
    }

    ChatScreenScrollLaunchedEffects(
        listState = listState,
        state = state,
        isNearBottom = isNearBottomState,
        userScrolledUpState = userScrolledUpState,
        listTouchActiveState = listTouchActiveState,
        listAutoFollowSuppressedState = listAutoFollowSuppressedState,

        capsuleHeightPxState = capsuleHeightPxState,
        listEffectiveViewportEndPxState = listEffectiveViewportEndPxState,
        naturalBottomPaddingPx = scrollNaturalBottomPaddingPx,
        bottomAnchorTolerancePx = scrollBottomAnchorTolerancePx,
        initialPresentationSettled = !showLoadingOverlay,
        scrollToLastAssistantInGalgame = scrollToLastAssistantInGalgame,
    )

    // 游戏/锁分模式好感度：优先用 state.galgameScore（API 返回）
    val galgameScore = if (state.mode.startsWith("galgame")) state.galgameScore else null
    val showGalgameCapsuleAndBar = state.mode.startsWith("galgame") && galgameScore != null && state.messages.isNotEmpty()
    val isGalgameBroken = state.mode.startsWith("galgame") && (galgameScore ?: 100) <= 0
    LaunchedEffect(galgameScore, state.mode, state.messages.size) {
        if (state.mode.startsWith("galgame")) {
            android.util.Log.d("GalDebug", "[ChatScreen] galgameScore=$galgameScore mode=${state.mode}" +
                " msgCount=${state.messages.size} showBar=$showGalgameCapsuleAndBar" +
                " isStreaming=${state.isStreaming} isLoadingHistory=${state.isLoadingHistory}")
        }
    }

    // 胜利庆祝：分数 100 且服务端未 victory_ack 时弹出；展示时 POST 持久化（重装同账号不重复）
    var showVictoryCelebration by remember(character.id) { mutableStateOf(false) }
    var victoryCelebrationPreviewOnly by remember(character.id) { mutableStateOf(false) }
    LaunchedEffect(galgameScore, state.galgameVictoryCelebrationAck) {
        if (galgameScore == null || galgameScore < 100) {
            showVictoryCelebration = false
            victoryCelebrationPreviewOnly = false
            return@LaunchedEffect
        }
        if (!state.galgameVictoryCelebrationAck) {
            delay(800)
            victoryCelebrationPreviewOnly = false
            showVictoryCelebration = true
        }
    }
    LaunchedEffect(showVictoryCelebration) {
        if (showVictoryCelebration && !victoryCelebrationPreviewOnly) {
            viewModel.postGalgameVictoryAck()
        }
    }
    if (showVictoryCelebration) {
        VictoryCelebrationOverlay(
            characterName = character.displayName(),
            onContinue = {
                showVictoryCelebration = false
                victoryCelebrationPreviewOnly = false
            },
            onRestart = {
                showVictoryCelebration = false
                victoryCelebrationPreviewOnly = false
                viewModel.resetGalgameProgress()
            }
        )
    }

    // 锁分模式：生命体征面板（叠加层在 Box 内渲染，见下方 CompositionLocalProvider 块）
    var showVitalsPanel by remember { mutableStateOf(false) }

    // 聊天页底部导航栏颜色与输入栏背景保持一致，避免底部出现透明/黑色断层。
    val chatBottomBarColor = MaterialTheme.colorScheme.surfaceVariant
        .copy(alpha = 0.6f)
        .compositeOver(MaterialTheme.colorScheme.surface)
    val bottomInsetOverlayActiveState = remember { mutableStateOf(false) }
    val chatNavigationBarColor = if (bottomInsetOverlayActiveState.value) {
        chatBottomBarColor
    } else {
        MaterialTheme.colorScheme.background
    }
    val useDarkNavBarIcons = chatNavigationBarColor.luminance() > 0.5f
    SystemNavigationBarColorEffect(
        color = chatNavigationBarColor,
        useDarkIcons = useDarkNavBarIcons
    )
    val chatActivity = context as? Activity

    // 为了让“对话内容 <-> 键盘”严格 1:1 同步位移，聊天页禁用系统 adjustResize，
    // 避免系统重布局与 ImeScrollHandler 手动增量补偿叠加产生过冲/欠冲。
    DisposableEffect(chatActivity) {
        if (chatActivity == null) return@DisposableEffect onDispose { }
        val window = chatActivity.window
        val previousMode = window.attributes.softInputMode
        val stableStateFlags = previousMode and (
            WindowManager.LayoutParams.SOFT_INPUT_MASK_STATE
        )
        window.setSoftInputMode(stableStateFlags or WindowManager.LayoutParams.SOFT_INPUT_ADJUST_NOTHING)
        onDispose {
            window.setSoftInputMode(previousMode)
        }
    }

    CompositionLocalProvider(
        LocalDebugSettings provides DebugSettings(
            showMessageIds = currentDebugShowMessageIds,
            showRawContent = currentDebugShowRawContent
        )
    ) {
    // Box 包裹 Scaffold + 叠加层，使叠加层与 Scaffold 同处 Activity 窗口 Compose 树内，
    // 通过 Z 层叠显示，彻底绕开 Dialog 窗口的 MIUI 导航栏干扰。
    Box(modifier = Modifier.fillMaxSize()) {

    ChatScreenScaffoldMain(
        viewModel = viewModel,
        character = character,
        allCharacters = allCharacters,
        prefs = prefs,
        state = state,
        listState = listState,
        imeBottomState = imeBottomState,
        imeTargetBottomState = imeTargetBottomState,
        imeAnimatingState = imeAnimatingState,
        pendingAnimationIds = pendingAnimationIds,
        lastAILayoutBottomPx = lastAILayoutBottomPx,
        lazyColumnTopPx = lazyColumnTopPx,
        inputBarLayoutTopPx = inputBarLayoutTopPx,
        inputBarHeightPx = inputBarHeightPx,
        listEffectiveViewportEndPxState = listEffectiveViewportEndPxState,
        userScrolledUpState = userScrolledUpState,
        listTouchActiveState = listTouchActiveState,
        listAutoFollowSuppressedState = listAutoFollowSuppressedState,
        capsuleHeightPxState = capsuleHeightPxState,
        voiceBridge = voiceBridge,
        showDisplaySettingsState = showDisplaySettingsState,
        pendingImages = pendingImages,
        currentFontScale = currentFontScale,
        currentShowTimestamp = currentShowTimestamp,
        galgameScore = galgameScore,
        showGalgameCapsuleAndBar = showGalgameCapsuleAndBar,
        isGalgameBroken = isGalgameBroken,
        showLoadingOverlay = showLoadingOverlay,
        bottomInsetOverlayActiveState = bottomInsetOverlayActiveState,
        coroutineScope = coroutineScope,
        context = context,
        showPrompt = showPrompt,
        onNavigateBack = onNavigateBack,
        onNavigateToEditCharacter = onNavigateToEditCharacter,
        onNavigateToCharacterProfile = onNavigateToCharacterProfile,
        characterHome = characterHome,
        onNavigateToSettings = onNavigateToSettings,
        onNavigateToProactiveTasks = onNavigateToProactiveTasks,
        onNavigateToHistory = onNavigateToHistory,
        awaitImeNotAnimating = awaitIme,
        imagePickerLauncher = imagePickerLauncher,
        onPickCamera = onPickChatCamera,
        isCompanionActive = isCompanionActive,
        isAgentCompanionActive = isAgentCompanionActive,
        isAgentAutoLooping = isAgentAutoLooping,
        onOpenImagePreview = { gallery, idx, url ->
            previewImages = gallery
            previewIndex = idx
            previewImageUrl = url
        },
        onOpenVitalsPanel = { showVitalsPanel = true },
    )

    if (bottomInsetOverlayActiveState.value) {
        // Edge-to-edge gesture navigation keeps the system bar transparent on some devices.
        // Paint the bottom inset while the input bar, IME, or bottom panels own that space.
        Box(
            modifier = Modifier
                .align(Alignment.BottomCenter)
                .fillMaxWidth()
                .windowInsetsBottomHeight(WindowInsets.navigationBars)
                .background(MaterialTheme.colorScheme.surfaceVariant)
        )
    }

    ChatScreenImagePreviewOverlay(
        previewImageUrl = previewImageUrl,
        previewImages = previewImages,
        previewIndex = previewIndex,
        onDismiss = { previewImageUrl = null },
        coroutineScope = coroutineScope,
        context = context,
    )

    ChatScreenDisplaySettingsAndVitalsOverlays(
        showDisplaySettingsState = showDisplaySettingsState,
        chatNavigationBarColor = chatNavigationBarColor,
        chatUseDarkNavigationBarIcons = useDarkNavBarIcons,
        showVitalsPanel = showVitalsPanel,
        onDismissVitals = { showVitalsPanel = false },
        prefs = prefs,
        state = state,
        galgameScore = galgameScore,
        viewModel = viewModel,
        onThemeChanged = onThemeChanged,
        onPrefsSavedFromDisplaySettings = { updatedPrefs ->
            currentFontScale = updatedPrefs.fontScale
            currentShowTimestamp = updatedPrefs.showTimestamp
            currentDebugShowMessageIds = updatedPrefs.debugShowMessageIds
            currentDebugShowRawContent = updatedPrefs.debugShowRawContent
        },
        onDebugTriggerVictory = {
            victoryCelebrationPreviewOnly = true
            showVictoryCelebration = true
        },
        onDebugResetVictory = {
            showVictoryCelebration = false
            victoryCelebrationPreviewOnly = false
        },
    )

    } // end Box
    } // end CompositionLocalProvider(LocalDebugSettings)
}
