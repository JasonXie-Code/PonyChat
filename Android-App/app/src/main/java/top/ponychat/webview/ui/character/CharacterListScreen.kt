package top.ponychat.webview.ui.character

import android.content.Context
import android.os.Build
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.animate
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.derivedStateOf
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.input.pointer.PointerEventPass
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.input.pointer.positionChange
import androidx.compose.ui.input.pointer.positionChangeIgnoreConsumed
import androidx.compose.ui.input.nestedscroll.NestedScrollConnection
import androidx.compose.ui.input.nestedscroll.NestedScrollSource
import androidx.compose.ui.input.nestedscroll.nestedScroll
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.Velocity
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import sh.calvin.reorderable.ReorderableItem
import sh.calvin.reorderable.rememberReorderableLazyListState
import top.ponychat.webview.data.local.LocalCacheStore
import top.ponychat.webview.data.model.Character
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.ui.common.LoadingOverlay
import top.ponychat.webview.ui.common.PonyAlertDialog
import top.ponychat.webview.ui.common.PonyAvatar
import top.ponychat.webview.ui.common.PonyDangerCountdownConfirmDialog
import top.ponychat.webview.ui.common.PonyTopBar
import top.ponychat.webview.ui.common.PonyTopSearchBar
import top.ponychat.webview.ui.common.SystemNavigationBarColorEffect
import top.ponychat.webview.util.formatErrorForDisplay
import top.ponychat.webview.ui.common.adaptivePopupMenuAccentColor
import top.ponychat.webview.ui.common.adaptivePopupMenuBorder
import top.ponychat.webview.ui.common.adaptivePopupMenuContainerColor
import top.ponychat.webview.ui.common.adaptivePopupMenuContentColor
import top.ponychat.webview.ui.common.adaptivePopupMenuDangerColor
import top.ponychat.webview.ui.common.adaptivePopupMenuIsDarkTheme
import top.ponychat.webview.ui.common.getAvatarColor
import top.ponychat.webview.ui.common.resolveAvatarUrlForApi
import top.ponychat.webview.ui.theme.*
import top.ponychat.webview.util.GalgameNotificationPreview
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Locale
import kotlin.math.abs
import kotlin.math.exp
import kotlin.math.ln

@Composable
private fun actionMenuIsDarkTheme(): Boolean =
    adaptivePopupMenuIsDarkTheme()

@Composable
private fun actionMenuContainerColor(): Color =
    adaptivePopupMenuContainerColor()

@Composable
private fun actionMenuContentColor(): Color =
    adaptivePopupMenuContentColor()

@Composable
private fun actionMenuMutedColor(): Color =
    actionMenuContentColor().copy(alpha = 0.62f)

@Composable
private fun actionMenuAccentColor(): Color =
    adaptivePopupMenuAccentColor()

@Composable
private fun actionMenuDangerColor(): Color =
    adaptivePopupMenuDangerColor()

@Composable
private fun actionMenuDividerColor(): Color =
    actionMenuContentColor().copy(alpha = if (actionMenuIsDarkTheme()) 0.18f else 0.10f)

@Composable
private fun actionMenuBorder(): BorderStroke? =
    adaptivePopupMenuBorder()

@OptIn(ExperimentalMaterial3Api::class, ExperimentalFoundationApi::class)
@Composable
fun CharacterListScreen(
    viewModel: CharacterViewModel,
    prefs: AppPreferences,
    onCharacterSelected: (Character, String) -> Unit,
    onNavigateToSettings: () -> Unit,
    onNavigateToHall: () -> Unit = {},
    onNavigateToCreate: () -> Unit = {},
    onNavigateToEdit: (Character) -> Unit = {},
    showDeviceHomeAction: Boolean = false,
    onNavigateToDeviceHome: () -> Unit = {},
) {
    val state by viewModel.state.collectAsState()
    val context = LocalContext.current
    val snackbarHostState = top.ponychat.webview.CustomToast.current
    val activeApiBase = prefs.effectiveApiBase()
    val fallbackApiBase = pickFallbackApiBase(activeApiBase, prefs.wanUrl, prefs.lanUrl)
    val scope = rememberCoroutineScope()
    var searchQuery by remember { mutableStateOf("") }
    var showTopMenu by remember { mutableStateOf(false) }
    var showQrScan by remember { mutableStateOf(false) }
    var qrScanResult by remember { mutableStateOf<String?>(null) }
    var selectedMode by remember {
        mutableStateOf(
            when (prefs.chatMode.ifBlank { "normal" }) {
                "normal", "galgame", "galgame_lock" -> prefs.chatMode.ifBlank { "normal" }
                else -> "normal"
            }
        )
    }
    // 每次从聊天页返回或切换模式时递增，强制排序重算（prefs 时间戳不是 Snapshot State，无法被 derivedStateOf 自动感知）
    var sortRevision by remember { mutableIntStateOf(0) }
    // 从设置页返回时刷新排序/置顶偏好
    val lifecycleOwner = LocalLifecycleOwner.current
    DisposableEffect(lifecycleOwner) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_RESUME) {
                sortRevision++
                viewModel.refreshPrefsState()
                // 静默刷新角色列表，确保从聊天页返回后 lastChatTime 立即更新
                viewModel.loadMyCharacters(silent = true)
            }
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose { lifecycleOwner.lifecycle.removeObserver(observer) }
    }

    val bottomNavigationColor = MaterialTheme.colorScheme.surface
    SystemNavigationBarColorEffect(
        color = bottomNavigationColor,
        useDarkIcons = bottomNavigationColor.luminance() > 0.5f
    )

    LaunchedEffect(selectedMode) {
        sortRevision++
        val isGalgameMode = selectedMode == "galgame" || selectedMode == "galgame_lock"
        viewModel.loadMyCharacters(silent = true, resetGalgameFetch = isGalgameMode)
    }

    // 模式专属时间戳映射：角色 stableId → 毫秒时间戳。
    // 作为 Compose State 派生，确保 backfillRevision / sortRevision 变化后 LazyColumn 条目能感知到
    // SharedPreferences 中的最新值并触发重组（直接在 items lambda 里读 prefs 不受 snapshot 系统追踪）。
    val modeLastChatMsMap by remember(state.characters, sortRevision, state.backfillRevision, state.listEventRevision, selectedMode) {
        derivedStateOf {
            state.characters.associate { c ->
                c.stableId() to prefs.getModeLastChatTime(c.stableId(), selectedMode)
            }
        }
    }
    val localCache = remember { LocalCacheStore(context.applicationContext) }
    /** 当前模式下各角色最近一条助手摘要（无消息则为空 → 卡片回退简介行） */
    var modeListSubtitleMap by remember { mutableStateOf<Map<String, String>>(emptyMap()) }
    LaunchedEffect(state.characters, sortRevision, state.backfillRevision, state.listEventRevision, selectedMode) {
        val u = prefs.username.trim()
        val chars = state.characters
        modeListSubtitleMap = if (u.isEmpty() || chars.isEmpty()) {
            emptyMap()
        } else {
            withContext(Dispatchers.IO) {
                chars.associate { c ->
                    val id = c.stableId()
                    val conv = localCache.loadLatestConversation(u, id, selectedMode)
                    val fromConv = GalgameNotificationPreview
                        .listRowSnippetFromLastAssistant(conv?.messages.orEmpty(), selectedMode)
                        .trim()
                    val fromPrefs = GalgameNotificationPreview.stripMarkdownForListPreview(
                        prefs.getModeLastChatSnippet(id, selectedMode).trim(),
                    )
                    id to fromPrefs.ifBlank { fromConv }
                }
            }
        }
    }
    // 排序 + 置顶后的列表
    // modeLastChatMsMap 变化（回填完成或模式切换）时同步触发重算，确保排序与展示时间戳始终一致
    val displayedChars by remember(
        state.characters, state.characterSort, state.pinnedCharacterIds, searchQuery,
        selectedMode, sortRevision, state.backfillRevision, state.listEventRevision, modeLastChatMsMap,
        modeListSubtitleMap,
    ) {
        derivedStateOf {
            val allChars = state.characters
            val pinned = state.pinnedCharacterIds

            // 模式专属排序 key：唯一来源是本地 prefs 里的模式专属时间戳（由 ChatViewModel 在每次对话
            // 结束时立即写入，或由 backfillModeTimestamps 从对话详情 API 拉取后写入）。
            // 无本地时间 → Long.MIN_VALUE（排到未对话组末尾）。
            // 不再使用 character.lastChatTime（= conversations.updated_at），该字段会被
            // auto_summarizer 后台任务刷新为当前时间，不可信。
            fun modeLastChatKey(c: top.ponychat.webview.data.model.Character): Long {
                return modeLastChatMsMap[c.stableId()]?.takeIf { it > 0L } ?: Long.MIN_VALUE
            }

            // 按排序方式排列所有角色
            val sorted = when (state.characterSort) {
                "name" -> allChars.sortedBy { it.displayName() }
                "last_chat" -> allChars.sortedWith(compareByDescending { c -> modeLastChatKey(c) })
                else -> allChars // manual/手动排序：保持 state.characters 中经拖拽调整后的顺序
            }

            // 置顶组始终按模式专属时间降序
            val pinnedGroup = sorted.filter { it.stableId() in pinned }
                .sortedWith(compareByDescending { c -> modeLastChatKey(c) })
            val normalGroup = sorted.filter { it.stableId() !in pinned }

            val orderedChars = pinnedGroup + normalGroup

            // 搜索过滤
            if (searchQuery.isBlank()) orderedChars
            else orderedChars.filter {
                val id = it.stableId()
                val sub = modeListSubtitleMap[id].orEmpty()
                it.displayName().contains(searchQuery, ignoreCase = true) ||
                    it.displayDescription().contains(searchQuery, ignoreCase = true) ||
                    sub.contains(searchQuery, ignoreCase = true)
            }
        }
    }
    val isInitialCharacterLoading = !state.hasLoadedCharacters && state.characters.isEmpty()

    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        topBar = {
            PonyTopBar(horizontalPadding = 0.dp) {
                Row(
                    modifier = Modifier
                        .weight(1f)
                        .padding(start = 14.dp, end = 10.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        modifier = Modifier
                            .weight(1f)
                            .clickable { onNavigateToSettings() }
                    ) {
                        UserAvatar(
                            avatarUrl = prefs.avatar,
                            name = viewModel.nickname.ifBlank { viewModel.username },
                            apiBase = activeApiBase,
                            fallbackApiBase = fallbackApiBase,
                            size = 38
                        )
                        Spacer(Modifier.width(10.dp))
                        Column {
                            Text(
                                text = viewModel.nickname.ifBlank { viewModel.username },
                                style = MaterialTheme.typography.titleSmall.copy(lineHeight = 17.sp),
                                fontWeight = FontWeight.Medium,
                                color = MaterialTheme.colorScheme.onBackground,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis
                            )
                            Text(
                                text = prefs.userBio.ifBlank { "暂无简介" },
                                style = MaterialTheme.typography.labelSmall.copy(lineHeight = 13.sp),
                                color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.5f),
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis
                            )
                        }
                    }
                    Box {
                        IconButton(
                            onClick = { showTopMenu = true },
                            modifier = Modifier.semantics { contentDescription = "更多选项" }
                        ) {
                            Icon(
                                Icons.Filled.Add,
                                contentDescription = null,
                                tint = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.6f),
                                modifier = Modifier.size(24.dp)
                            )
                        }
                        DropdownMenu(
                            expanded = showTopMenu,
                            onDismissRequest = { showTopMenu = false },
                            modifier = Modifier.widthIn(min = 200.dp),
                            shape = RoundedCornerShape(12.dp),
                            containerColor = actionMenuContainerColor(),
                            border = actionMenuBorder(),
                            tonalElevation = 2.dp
                        ) {
                            if (showDeviceHomeAction) {
                                DropdownMenuItem(
                                    text = { Text("返回大屏", color = actionMenuContentColor()) },
                                    leadingIcon = {
                                        Icon(
                                            Icons.Filled.Tv,
                                            contentDescription = null,
                                            tint = actionMenuContentColor(),
                                        )
                                    },
                                    onClick = {
                                        showTopMenu = false
                                        onNavigateToDeviceHome()
                                    },
                                )
                            }
                            DropdownMenuItem(
                                text = { Text("创建角色", color = actionMenuContentColor()) },
                                leadingIcon = { Icon(Icons.Filled.PersonAdd, contentDescription = null, tint = actionMenuContentColor()) },
                                onClick = { showTopMenu = false; onNavigateToCreate() }
                            )
                            DropdownMenuItem(
                                text = { Text("角色大厅", color = actionMenuContentColor()) },
                                leadingIcon = { Icon(Icons.Filled.Groups, contentDescription = null, tint = actionMenuContentColor()) },
                                onClick = { showTopMenu = false; onNavigateToHall() }
                            )
                            DropdownMenuItem(
                                text = { Text("扫一扫", color = actionMenuContentColor()) },
                                leadingIcon = { Icon(Icons.Filled.QrCodeScanner, contentDescription = null, tint = actionMenuContentColor()) },
                                onClick = { showTopMenu = false; showQrScan = true }
                            )
                            DropdownMenuItem(
                                text = { Text("刷新数据", color = actionMenuContentColor()) },
                                leadingIcon = { Icon(Icons.Filled.Refresh, contentDescription = null, tint = actionMenuContentColor()) },
                                onClick = { showTopMenu = false; viewModel.loadMyCharacters() }
                            )
                        }
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
                    // 在“底栏顶部 ~ 系统导航栏顶部”的可视区域内居中对齐内容
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(58.dp)
                            .align(Alignment.TopCenter)
                            .padding(horizontal = 20.dp, vertical = 2.dp),
                        horizontalArrangement = Arrangement.SpaceEvenly
                    ) {
                        val canUseLockMode =
                            prefs.membershipType == "developer" || prefs.membershipType == "admin"
                        CompactModeNavItem(
                            selected = selectedMode == "normal",
                            icon = Icons.Filled.ChatBubbleOutline,
                            label = "聊天",
                            onClick = {
                                selectedMode = "normal"
                                prefs.chatMode = "normal"
                            }
                        )
                        CompactModeNavItem(
                            selected = selectedMode == "galgame" || selectedMode == "galgame_lock",
                            icon = Icons.Filled.SportsEsports,
                            label = if (selectedMode == "galgame_lock") "锁分" else "游戏",
                            onClick = {
                                selectedMode = "galgame"
                                prefs.chatMode = "galgame"
                            },
                            onLongClick = {
                                if (!canUseLockMode) {
                                    scope.launch {
                                        snackbarHostState.showSnackbar("锁分模式需要开发者或管理员账号")
                                    }
                                } else {
                                    selectedMode = "galgame_lock"
                                    prefs.chatMode = "galgame_lock"
                                    vibrateForOneSecond(context)
                                    scope.launch { snackbarHostState.showSnackbar("已切换锁分模式") }
                                }
                            }
                        )
                    }
                }
            }
        },
    ) { paddingValues ->
        val lazyListState = rememberLazyListState()
        val density = LocalDensity.current
        val pullRefreshMaxHeight = 76.dp
        val pullRefreshMaxPx = with(density) { pullRefreshMaxHeight.toPx() }
        val pullRefreshDampingStartPx = pullRefreshMaxPx * 0.5f
        val pullRefreshTriggerPx = pullRefreshMaxPx * 0.7f
        val pullRefreshDampingScalePx = ((pullRefreshMaxPx - pullRefreshDampingStartPx) * 0.75f)
            .coerceAtLeast(1f)
        val pullRefreshDragMaxPx = pullRefreshMaxPx * 3f
        var pullRefreshOffsetPx by remember { mutableFloatStateOf(0f) }
        var pullRefreshDragDistancePx by remember { mutableFloatStateOf(0f) }
        var pullRefreshReadyHapticFired by remember { mutableStateOf(false) }
        var pullRefreshBackJob by remember { mutableStateOf<Job?>(null) }
        var pullRefreshBackGeneration by remember { mutableIntStateOf(0) }
        val isPullRefreshing = state.isRefreshingAllChats
        fun pullRefreshOffsetForDrag(dragDistancePx: Float): Float {
            val drag = dragDistancePx.coerceAtLeast(0f)
            if (drag <= pullRefreshDampingStartPx) {
                return drag.coerceAtMost(pullRefreshMaxPx)
            }
            val extraDrag = drag - pullRefreshDampingStartPx
            val dampedExtra = pullRefreshDampingScalePx *
                ln((1f + extraDrag / pullRefreshDampingScalePx).toDouble()).toFloat()
            return (pullRefreshDampingStartPx + dampedExtra).coerceAtMost(pullRefreshMaxPx)
        }
        fun pullRefreshDragForOffset(offsetPx: Float): Float {
            val offset = offsetPx.coerceIn(0f, pullRefreshMaxPx)
            if (offset <= pullRefreshDampingStartPx) return offset
            val extraOffset = offset - pullRefreshDampingStartPx
            val rawExtra = pullRefreshDampingScalePx *
                (exp((extraOffset / pullRefreshDampingScalePx).toDouble()).toFloat() - 1f)
            return (pullRefreshDampingStartPx + rawExtra).coerceIn(0f, pullRefreshDragMaxPx)
        }
        fun setPullRefreshOffset(
            nextOffset: Float,
            allowReadyHaptic: Boolean = true,
            syncDragDistance: Boolean = true
        ) {
            val previousOffset = pullRefreshOffsetPx
            val next = nextOffset.coerceIn(0f, pullRefreshMaxPx)
            pullRefreshOffsetPx = next
            if (syncDragDistance) {
                pullRefreshDragDistancePx = pullRefreshDragForOffset(next)
            }
            if (
                allowReadyHaptic &&
                !pullRefreshReadyHapticFired &&
                previousOffset < pullRefreshTriggerPx &&
                next >= pullRefreshTriggerPx
            ) {
                vibrateBriefly(context)
                pullRefreshReadyHapticFired = true
            }
            if (next <= 0f) {
                pullRefreshDragDistancePx = 0f
                pullRefreshReadyHapticFired = false
            }
        }
        fun applyPullRefreshDelta(deltaY: Float): Float {
            if (deltaY == 0f) return 0f
            val previousOffset = pullRefreshOffsetPx
            pullRefreshDragDistancePx = (pullRefreshDragDistancePx + deltaY)
                .coerceIn(0f, pullRefreshDragMaxPx)
            setPullRefreshOffset(
                pullRefreshOffsetForDrag(pullRefreshDragDistancePx),
                syncDragDistance = false
            )
            return pullRefreshOffsetPx - previousOffset
        }
        fun cancelPullRefreshBackAnimation() {
            val job = pullRefreshBackJob ?: return
            pullRefreshBackGeneration += 1
            job.cancel()
            pullRefreshBackJob = null
        }
        fun startPullRefreshBackAnimation() {
            val generation = pullRefreshBackGeneration + 1
            pullRefreshBackGeneration = generation
            pullRefreshBackJob?.cancel()
            pullRefreshBackJob = scope.launch {
                val startOffset = pullRefreshOffsetPx
                if (startOffset <= 0f) return@launch
                try {
                    animate(
                        initialValue = startOffset,
                        targetValue = 0f,
                        animationSpec = tween(durationMillis = 300)
                    ) { value, _ ->
                        if (generation == pullRefreshBackGeneration) {
                            setPullRefreshOffset(value.coerceAtLeast(0f), allowReadyHaptic = false)
                        }
                    }
                    if (generation == pullRefreshBackGeneration) {
                        setPullRefreshOffset(0f, allowReadyHaptic = false)
                    }
                } finally {
                    if (generation == pullRefreshBackGeneration) {
                        pullRefreshBackJob = null
                    }
                }
            }
        }
        fun finishPullRefreshGesture() {
            if (pullRefreshOffsetPx <= 0f) {
                pullRefreshReadyHapticFired = false
                return
            }
            val shouldRefresh =
                pullRefreshOffsetPx >= pullRefreshTriggerPx && !isPullRefreshing && !state.isLoading
            if (shouldRefresh) {
                viewModel.refreshAllChatContent { success ->
                    if (!success) {
                        scope.launch { snackbarHostState.showSnackbar("刷新失败") }
                    }
                }
            }
            startPullRefreshBackAnimation()
        }
        val pullRefreshConnection = remember(
            lazyListState,
            pullRefreshTriggerPx,
            pullRefreshMaxPx,
            isPullRefreshing,
            state.isLoading,
            context,
            viewModel,
            scope,
            snackbarHostState
        ) {
            object : NestedScrollConnection {
                override fun onPreScroll(available: Offset, source: NestedScrollSource): Offset {
                    if (available.y >= 0f || pullRefreshOffsetPx <= 0f) return Offset.Zero
                    val consumedY = applyPullRefreshDelta(available.y)
                    return Offset(0f, consumedY)
                }

                override fun onPostScroll(
                    consumed: Offset,
                    available: Offset,
                    source: NestedScrollSource
                ): Offset {
                    if (source != NestedScrollSource.UserInput) return Offset.Zero
                    val canPull = !state.isLoading &&
                        (lazyListState.isAtRefreshTop() || pullRefreshOffsetPx > 0f)
                    if (!canPull || available.y <= 0f) return Offset.Zero
                    cancelPullRefreshBackAnimation()
                    applyPullRefreshDelta(available.y)
                    return Offset(0f, available.y)
                }

                override suspend fun onPreFling(available: Velocity): Velocity {
                    if (pullRefreshOffsetPx <= 0f) return Velocity.Zero
                    finishPullRefreshGesture()
                    return Velocity.Zero
                }

                override suspend fun onPostFling(consumed: Velocity, available: Velocity): Velocity {
                    if (pullRefreshOffsetPx > 0f) {
                        finishPullRefreshGesture()
                    }
                    return Velocity.Zero
                }
            }
        }
        val pullRefreshPointerModifier = Modifier.pointerInput(
            lazyListState,
            pullRefreshTriggerPx,
            pullRefreshMaxPx,
            isPullRefreshing,
            state.isLoading,
            context,
            viewModel,
            scope,
            snackbarHostState
        ) {
            awaitEachGesture {
                val down = awaitFirstDown(
                    requireUnconsumed = false,
                    pass = PointerEventPass.Initial
                )
                var activePointerId = down.id
                var totalDragY = 0f
                var totalDragX = 0f
                var pulling = pullRefreshOffsetPx > 0f

                try {
                    while (true) {
                        val event = awaitPointerEvent(PointerEventPass.Initial)
                        val change = event.changes.firstOrNull { it.id == activePointerId }
                            ?: event.changes.firstOrNull { it.pressed }?.also { activePointerId = it.id }
                            ?: break
                        if (!change.pressed) break

                        val delta = change.positionChangeIgnoreConsumed()
                        totalDragY += delta.y
                        totalDragX += delta.x

                        if (!pulling) {
                            val verticalEnough = totalDragY > 2f && totalDragY > abs(totalDragX) * 0.5f
                            pulling = verticalEnough && lazyListState.isAtRefreshTop() &&
                                !state.isLoading
                        }

                        if (pulling) {
                            when {
                                delta.y > 0f -> {
                                    cancelPullRefreshBackAnimation()
                                    applyPullRefreshDelta(delta.y)
                                    change.consume()
                                }
                                delta.y < 0f && pullRefreshOffsetPx > 0f -> {
                                    cancelPullRefreshBackAnimation()
                                    applyPullRefreshDelta(delta.y)
                                    change.consume()
                                }
                            }
                        }
                    }
                } finally {
                    if (pulling || pullRefreshOffsetPx > 0f) {
                        finishPullRefreshGesture()
                    }
                }
            }
        }
        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(paddingValues)
                .nestedScroll(pullRefreshConnection)
                .then(pullRefreshPointerModifier)
        ) {
            val isManualSort = state.characterSort == "manual"
            val reorderableLazyListState = rememberReorderableLazyListState(lazyListState) { from, to ->
                viewModel.reorderCharacters(from.key as String, to.key as String)
            }
            PullRefreshIndicator(
                maxHeight = pullRefreshMaxHeight,
                triggerPx = pullRefreshTriggerPx,
                offsetPxProvider = { pullRefreshOffsetPx },
                isRefreshing = isPullRefreshing
            )
            LazyColumn(
                state = lazyListState,
                modifier = Modifier
                    .fillMaxSize()
                    .graphicsLayer { translationY = pullRefreshOffsetPx }
            ) {
                // 搜索栏
                item {
                    PonyTopSearchBar(
                        value = searchQuery,
                        onValueChange = { searchQuery = it },
                        placeholder = "搜索角色...",
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 12.dp, vertical = 8.dp)
                    )
                }

            // 错误提示
            state.error?.let { err ->
                item {
                    Card(
                        modifier = Modifier.fillMaxWidth().padding(16.dp),
                        colors = CardDefaults.cardColors(containerColor = ErrorColor.copy(0.12f)),
                        shape = RoundedCornerShape(8.dp)
                    ) {
                        Row(
                            modifier = Modifier.padding(12.dp),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Icon(Icons.Filled.Warning, contentDescription = null, tint = ErrorColor)
                            Spacer(Modifier.width(8.dp))
                            Text(
                                formatErrorForDisplay(err),
                                color = ErrorColor,
                                style = MaterialTheme.typography.bodySmall
                            )
                            Spacer(Modifier.weight(1f))
                            TextButton(onClick = { viewModel.clearError() }) {
                                Text("关闭", color = ErrorColor)
                            }
                        }
                    }
                }
            }

            // 操作结果提示
            if (state.actionMessage != null) {
                item {
                    Surface(color = Primary.copy(0.12f), modifier = Modifier.fillMaxWidth()) {
                        Text(
                            state.actionMessage ?: "",
                            color = Primary,
                            style = MaterialTheme.typography.bodySmall,
                            modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp)
                        )
                    }
                }
            }

            // 空状态
            if (displayedChars.isEmpty() && state.hasLoadedCharacters && !state.isLoading) {
                item {
                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(top = 80.dp),
                        contentAlignment = Alignment.Center
                    ) {
                        Column(horizontalAlignment = Alignment.CenterHorizontally) {
                            Icon(
                                Icons.Filled.Person,
                                contentDescription = null,
                                modifier = Modifier.size(64.dp),
                                tint = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.4f)
                            )
                            Spacer(Modifier.height(12.dp))
                            Text(
                                "还没有角色，点击右上角+创建",
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                style = MaterialTheme.typography.bodyMedium
                            )
                        }
                    }
                }
            }

            // 角色列表（手动排序模式下支持拖拽）
            items(
                items = displayedChars,
                key = { it.stableId() }
            ) { character ->
                val isPinned = character.stableId() in state.pinnedCharacterIds
                val canDrag = isManualSort && !isPinned
                ReorderableItem(
                    state = reorderableLazyListState,
                    key = character.stableId(),
                    enabled = canDrag
                ) { isDragging ->
                    val dragHandleModifier = if (canDrag) Modifier.draggableHandle() else Modifier
                    CharacterCard(
                        character = character,
                        apiBase = activeApiBase,
                        fallbackApiBase = fallbackApiBase,
                        isOwned = true,
                        isPinned = isPinned,
                        showDragHandle = canDrag,
                        dragHandleModifier = dragHandleModifier,
                        isDragging = isDragging,
                        unreadCount = state.unreadMap["${character.stableId()}#$selectedMode"] ?: 0,
                        modeLastChatMs = modeLastChatMsMap[character.stableId()] ?: 0L,
                        listSubtitleLine = modeListSubtitleMap[character.stableId()].orEmpty(),
                        currentUsername = prefs.username.trim(),
                        onClick = { onCharacterSelected(character, selectedMode) },
                        onEdit = { onNavigateToEdit(character) },
                        onDelete = { viewModel.deleteCharacter(character) },
                        onDuplicate = { viewModel.duplicateCharacter(character) },
                        onAddFromHall = null,
                        onTogglePublish = { viewModel.togglePublish(character) },
                        onTogglePin = {
                            if (isPinned) viewModel.unpinCharacter(character.stableId())
                            else viewModel.pinCharacter(character.stableId())
                        }
                    )
                }
                }
            }
            LoadingOverlay(visible = state.isLoading || isInitialCharacterLoading, message = "加载中…")
        }
    }

    QrCodeScanDialog(
        visible = showQrScan,
        onDismiss = { showQrScan = false },
        onDecoded = { text ->
            showQrScan = false
            qrScanResult = text
        }
    )
    val clipboardManager = LocalClipboardManager.current
    qrScanResult?.let { result ->
        PonyAlertDialog(
            title = "扫描结果",
            onDismiss = { qrScanResult = null },
            content = {
                val scroll = rememberScrollState()
                Text(
                    result,
                    color = MaterialTheme.colorScheme.onSurface,
                    style = MaterialTheme.typography.bodyMedium,
                    modifier = Modifier
                        .verticalScroll(scroll)
                        .heightIn(max = 360.dp)
                )
            },
            dismissButton = {
                TextButton(
                    onClick = {
                        clipboardManager.setText(AnnotatedString(result))
                        scope.launch { snackbarHostState.showSnackbar("已复制到剪贴板") }
                    }
                ) {
                    Text("复制", color = MaterialTheme.colorScheme.primary, fontWeight = FontWeight.Medium)
                }
            },
            confirmButton = {
                TextButton(onClick = { qrScanResult = null }) {
                    Text("确定", color = Primary, fontWeight = FontWeight.Medium)
                }
            }
        )
    }

    // ==================== 删除确认对话框 ====================
    state.deletingCharacter?.let { char ->
        PonyDangerCountdownConfirmDialog(
            title = "删除角色",
            message = "确认删除「${char.displayName()}」？此操作不可撤销。",
            confirmText = "删除",
            onConfirm = { viewModel.confirmDelete() },
            onDismiss = { viewModel.cancelDelete() }
        )
    }
}

@Composable
private fun Icon(
    imageVector: ImageVector,
    contentDescription: String?,
    modifier: Modifier = Modifier,
    tint: Color = LocalContentColor.current
) {
    ScaledIcon(
        imageVector = imageVector,
        contentDescription = contentDescription,
        modifier = modifier,
        tint = tint
    )
}



