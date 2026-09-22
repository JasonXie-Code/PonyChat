package top.ponychat.webview.ui.chat
import android.util.Log
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.EnterTransition
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeOut
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.scrollBy
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.Image
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.MutableFloatState
import androidx.compose.runtime.MutableIntState
import androidx.compose.runtime.MutableState
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.State
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshots.SnapshotStateList
import androidx.compose.runtime.withFrameNanos
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.PointerEventPass
import androidx.compose.ui.input.pointer.changedToDown
import androidx.compose.ui.input.pointer.changedToDownIgnoreConsumed
import androidx.compose.ui.input.pointer.changedToUpIgnoreConsumed
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.layout
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.positionInWindow
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.platform.LocalViewConfiguration
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.zIndex
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import androidx.activity.compose.BackHandler
import top.ponychat.webview.BackendStreamingVoiceBridge
import top.ponychat.webview.data.model.Character
import top.ponychat.webview.data.model.Message
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.ui.common.PonyDialogOption
import top.ponychat.webview.ui.common.PonyOptionDialog
import top.ponychat.webview.ui.theme.LocalFontScale
import top.ponychat.webview.ui.theme.Primary
import kotlin.math.max
import kotlin.math.roundToInt
import kotlin.math.abs
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.ui.unit.Density
@OptIn(
    ExperimentalMaterial3Api::class,
    ExperimentalFoundationApi::class,
    ExperimentalLayoutApi::class,
)
@Composable
internal fun ChatScreenScaffoldMain(
    viewModel: ChatViewModel,
    character: Character,
    allCharacters: List<Character> = emptyList(),
    prefs: AppPreferences,
    state: ChatUiState,
    listState: LazyListState,
    imeBottomState: State<Int>,
    imeTargetBottomState: State<Int>,
    imeAnimatingState: State<Boolean>,
    pendingAnimationIds: MutableSet<String>,
    lastAILayoutBottomPx: MutableFloatState,
    lazyColumnTopPx: MutableFloatState,
    inputBarLayoutTopPx: MutableFloatState,
    inputBarHeightPx: MutableFloatState,
    listEffectiveViewportEndPxState: MutableIntState,
    userScrolledUpState: MutableState<Boolean>,
    listTouchActiveState: MutableState<Boolean>,
    listAutoFollowSuppressedState: MutableState<Boolean>,
    capsuleHeightPxState: MutableIntState,
    voiceBridge: BackendStreamingVoiceBridge?,
    showDisplaySettingsState: MutableState<Boolean>,
    pendingImages: SnapshotStateList<String>,
    currentFontScale: Float,
    currentShowTimestamp: Boolean,
    galgameScore: Int?,
    showGalgameCapsuleAndBar: Boolean,
    isGalgameBroken: Boolean,
    showLoadingOverlay: Boolean,
    bottomInsetOverlayActiveState: MutableState<Boolean>,
    coroutineScope: kotlinx.coroutines.CoroutineScope,
    context: Context,
    showPrompt: (String) -> Unit,
    onNavigateBack: () -> Unit,
    onNavigateToEditCharacter: () -> Unit,
    onNavigateToCharacterProfile: (Character) -> Unit,
    characterHome: @Composable (() -> Unit) -> Unit,
    onNavigateToSettings: () -> Unit,
    onNavigateToProactiveTasks: () -> Unit,
    onNavigateToHistory: () -> Unit,
    awaitImeNotAnimating: suspend () -> Unit,
    imagePickerLauncher: androidx.activity.result.ActivityResultLauncher<PickVisualMediaRequest>,
    /** 聊天内拍照：由上层创建 MediaStore Uri + [androidx.activity.result.contract.ActivityResultContracts.TakePicture] */
    onPickCamera: () -> Unit,
    isCompanionActive: Boolean,
    isAgentCompanionActive: Boolean,
    isAgentAutoLooping: Boolean,
    onOpenImagePreview: (List<String>, Int, String) -> Unit,
    onOpenVitalsPanel: () -> Unit,
) {
    val focusManager = LocalFocusManager.current
    val haptic = LocalHapticFeedback.current
    val keyboardController = LocalSoftwareKeyboardController.current
    val viewConfiguration = LocalViewConfiguration.current
    val configuration = LocalConfiguration.current
    val imeLiftCacheWindowKey = remember(
        configuration.orientation,
        configuration.screenWidthDp,
        configuration.screenHeightDp,
    ) {
        "${configuration.orientation}_${configuration.screenWidthDp}x${configuration.screenHeightDp}"
    }
    var isUploadingChatImages by remember { mutableStateOf(false) }
    val dismissKeyboard: () -> Unit = {
        focusManager.clearFocus(force = true)
        keyboardController?.hide()
    }
    val dismissInputPanelsSignal = remember { mutableIntStateOf(0) }
    // 表情/更多面板展开高度（px）；同时用于全局点击判断，避免点击面板自身被当作外部点击。
    val panelExtraPxState = remember { mutableIntStateOf(0) }
    val inputPanelActiveState = remember { mutableStateOf(false) }
    val listBottomSurfaceDismissSnapState = remember(state.conversationId) { mutableStateOf(false) }
    val inputFocusedState = remember(state.conversationId) { mutableStateOf(false) }
    val keyboardHandoffLiftPxState = remember { mutableIntStateOf(0) }
    val cachedImeLiftPxState = remember(imeLiftCacheWindowKey) {
        mutableIntStateOf(prefs.cachedChatImeLiftPx(imeLiftCacheWindowKey))
    }
    val settledImeLiftPxState = remember(imeLiftCacheWindowKey) {
        mutableIntStateOf(cachedImeLiftPxState.intValue)
    }
    val restingInputBarHeightPxState = remember { mutableIntStateOf(0) }
    val panelTargetPx = panelExtraPxState.intValue.coerceAtLeast(0)
    val panelLiftPx = panelTargetPx
    val keyboardHandoffLiftPx = keyboardHandoffLiftPxState.intValue
    LaunchedEffect(
        imeAnimatingState.value,
        imeBottomState.value,
    ) {
        if (!imeAnimatingState.value && imeBottomState.value > 0) {
            val stableImeLiftPx = imeBottomState.value
            delay(140)
            if (
                imeAnimatingState.value ||
                imeBottomState.value != stableImeLiftPx ||
                imeBottomState.value <= 0
            ) {
                return@LaunchedEffect
            }
            settledImeLiftPxState.intValue = stableImeLiftPx
            val cachedImeLiftPx = cachedImeLiftPxState.intValue
            if (
                cachedImeLiftPx == 0 ||
                stableImeLiftPx < cachedImeLiftPx - 2 ||
                stableImeLiftPx > cachedImeLiftPx + 2
            ) {
                cachedImeLiftPxState.intValue = stableImeLiftPx
                prefs.setCachedChatImeLiftPx(imeLiftCacheWindowKey, stableImeLiftPx)
            }
        }
    }
    fun currentTrustedImeLiftPx(): Int {
        val targetImeBottomPx = imeTargetBottomState.value
        val currentImeBottomPx = imeBottomState.value
        val cachedImeBottomPx = cachedImeLiftPxState.intValue
        val settledImeBottomPx = settledImeLiftPxState.intValue
        return when {
            // 键盘开始关闭时，底部输入栏和消息列表应立即归位。
            // 系统 IME 仍会继续派发递减的 onProgress 高度，但聊天界面不跟随这个下降动画。
            targetImeBottomPx <= 0 -> 0
            targetImeBottomPx > 0 && cachedImeBottomPx > 0 -> cachedImeBottomPx
            targetImeBottomPx > 0 && settledImeBottomPx > 0 ->
                minOf(settledImeBottomPx, targetImeBottomPx)
            targetImeBottomPx > 0 -> currentImeBottomPx
            imeAnimatingState.value -> currentImeBottomPx
            currentImeBottomPx > 0 -> currentImeBottomPx
            else -> 0
        }.coerceAtLeast(0)
    }
    fun currentBottomSurfaceLiftPx(): Int =
        maxOf(
            panelTargetPx,
            keyboardHandoffLiftPxState.intValue,
            currentTrustedImeLiftPx(),
        ).coerceAtLeast(0)
    val bottomSurfaceLiftPxForFrame = currentBottomSurfaceLiftPx()
    val inputBarLayoutLiftPxForFrame =
        (bottomSurfaceLiftPxForFrame - panelLiftPx).coerceAtLeast(0)
    LaunchedEffect(
        imeAnimatingState.value,
        imeBottomState.value,
        imeTargetBottomState.value,
        inputFocusedState.value,
        keyboardHandoffLiftPx,
    ) {
        val trustedImeLiftPx = currentTrustedImeLiftPx()
        val keyboardSettledGone =
            !imeAnimatingState.value &&
                imeBottomState.value == 0 &&
                imeTargetBottomState.value == 0 &&
                !inputFocusedState.value
        val keyboardSettledOpen =
            !imeAnimatingState.value &&
                imeBottomState.value > 0 &&
                imeTargetBottomState.value > 0
        val keyboardHasTakenOver =
            trustedImeLiftPx >= (keyboardHandoffLiftPx - 2).coerceAtLeast(0)
        if (
            keyboardHandoffLiftPx > 0 &&
            (keyboardHasTakenOver || keyboardSettledGone || keyboardSettledOpen)
        ) {
            keyboardHandoffLiftPxState.intValue = 0
        }
    }
    LaunchedEffect(
        panelTargetPx,
        inputPanelActiveState.value,
        imeAnimatingState.value,
        imeBottomState.value,
        imeTargetBottomState.value,
        keyboardHandoffLiftPx,
    ) {
        val keyboardGone =
            imeBottomState.value == 0 &&
                imeTargetBottomState.value == 0 &&
                keyboardHandoffLiftPx == 0 &&
                !imeAnimatingState.value
        val keyboardSettledOpen =
            panelTargetPx == 0 &&
                !inputPanelActiveState.value &&
                imeBottomState.value > 0 &&
                imeTargetBottomState.value > 0 &&
                keyboardHandoffLiftPx == 0 &&
                !imeAnimatingState.value
        val bottomSurfaceGone =
            panelTargetPx == 0 &&
                !inputPanelActiveState.value &&
                keyboardGone
        if (bottomSurfaceGone || keyboardSettledOpen) {
            listBottomSurfaceDismissSnapState.value = false
        }
    }
    fun requestImmediateListDropForBottomSurfaceDismiss(currentPanelLiftPx: Int) {
        val hasRaisedBottomSurface =
            currentPanelLiftPx > 0 ||
                inputPanelActiveState.value ||
                imeBottomState.value > 0 ||
                imeTargetBottomState.value > 0 ||
                keyboardHandoffLiftPxState.intValue > 0
        if (hasRaisedBottomSurface) {
            listBottomSurfaceDismissSnapState.value = true
        }
    }
    fun hasRaisedBottomSurfaceForGesture(): Boolean =
        panelExtraPxState.intValue > 0 ||
            inputPanelActiveState.value ||
            imeBottomState.value > 0 ||
            imeTargetBottomState.value > 0 ||
            keyboardHandoffLiftPxState.intValue > 0
    fun hasInputFocusOrRaisedBottomSurfaceForGesture(): Boolean =
        inputFocusedState.value || hasRaisedBottomSurfaceForGesture()
    var timestampNow by remember { mutableStateOf(System.currentTimeMillis()) }
    LaunchedEffect(Unit) {
        while (true) {
            delay(15_000L)
            timestampNow = System.currentTimeMillis()
        }
    }
    var mentionPickerVisible by remember(state.conversationId) { mutableStateOf(false) }
    var selectedMentionCharacters by remember(state.conversationId) { mutableStateOf<List<Character>>(emptyList()) }
    var focusInputSignal by remember(state.conversationId) { mutableIntStateOf(0) }
    val mentionCandidates = remember(character, allCharacters, state.messages) {
        recentMentionCandidates(character, allCharacters, state.messages)
    }
    val activeMentionCharacters = remember(state.inputText, selectedMentionCharacters) {
        findMentionTargetMatches(state.inputText, selectedMentionCharacters)
    }
    fun appendMentionFromAvatar(target: Character) {
        if (state.mode != "normal") return
        val targetId = target.id?.takeIf { it.isNotBlank() } ?: return
        if (target.displayName().isBlank()) return
        val alreadySelected = selectedMentionCharacters.any { it.id == targetId }
        val nextInput = appendMentionTokenIfMissing(state.inputText, target)
        if (alreadySelected && nextInput == state.inputText) return
        selectedMentionCharacters = buildList {
            selectedMentionCharacters.forEach { existing ->
                if (existing.id != targetId) add(existing)
            }
            add(target)
        }
        if (nextInput != state.inputText) {
            viewModel.updateInput(nextInput)
        }
        mentionPickerVisible = false
        if (!hasRaisedBottomSurfaceForGesture()) {
            focusInputSignal += 1
        }
        haptic.performHapticFeedback(HapticFeedbackType.LongPress)
    }
    val mentionPickerBottomInsetPx = run {
        val inputExtra = (
            inputBarHeightPx.floatValue.roundToInt() -
                restingInputBarHeightPxState.intValue
        ).coerceAtLeast(0)
        val visualImeBottom = if (panelTargetPx > 0) {
            0
        } else {
            max(imeBottomState.value, keyboardHandoffLiftPx)
        }
        (visualImeBottom + panelTargetPx + inputExtra).coerceAtLeast(0)
    }
    val mentionPickerBottomInsetDp = with(LocalDensity.current) {
        mentionPickerBottomInsetPx.toDp()
    }
    LaunchedEffect(state.mode, state.conversationId) {
        mentionPickerVisible = false
        selectedMentionCharacters = emptyList()
    }
    BackHandler(enabled = mentionPickerVisible) {
        mentionPickerVisible = false
    }
    val mentionPickerVisibleState = rememberUpdatedState(mentionPickerVisible)
    var isExporting by remember { mutableStateOf(false) }
    var showExportOptions by remember { mutableStateOf(false) }
    BackHandler(enabled = state.isExportMode) { viewModel.exitExportMode() }
    // 游戏/锁分开始界面（messages 为空）时永不显示输入栏
    val showInputBar = !isGalgameBroken &&
        (!state.mode.startsWith("galgame") || state.messages.isNotEmpty())
    val relationshipPagerEnabled = state.mode == "normal" && !state.isExportMode
    val relationshipPagerState = rememberChatSidePager(relationshipPagerEnabled) {
        dismissKeyboard()
        dismissInputPanelsSignal.intValue += 1
    }
    val relationshipPageProgress by remember(relationshipPagerState, relationshipPagerEnabled) {
        derivedStateOf {
            if (!relationshipPagerEnabled) {
                0f
            } else {
                abs((relationshipPagerState.currentPage - CHAT_PAGE) + relationshipPagerState.currentPageOffsetFraction)
                    .coerceIn(0f, 1f)
            }
        }
    }
    val relationshipInputVisibleFraction =
        (1f - relationshipPageProgress).coerceIn(0f, 1f)
    val relationshipRestingInputHeightPx = remember(
        restingInputBarHeightPxState.intValue,
        inputBarHeightPx.floatValue
    ) {
        restingInputBarHeightPxState.intValue
            .takeIf { it > 0 }
            ?: inputBarHeightPx.floatValue.roundToInt().coerceAtLeast(0)
    }
    val relationshipVisibleInputHeightPxForFrame =
        (relationshipRestingInputHeightPx * relationshipInputVisibleFraction).roundToInt()
            .coerceIn(0, relationshipRestingInputHeightPx)
    val relationshipHiddenInputHeightPxForFrame =
        (relationshipRestingInputHeightPx - relationshipVisibleInputHeightPxForFrame)
            .coerceAtLeast(0)
    val previousRelationshipHiddenInputHeightPxState = remember(state.conversationId) {
        mutableIntStateOf(relationshipHiddenInputHeightPxForFrame)
    }
    val inputBarVisibleForFrame = showInputBar && (
        relationshipVisibleInputHeightPxForFrame > 0 ||
            relationshipRestingInputHeightPx == 0
    )
    val bottomInsetOverlayActiveForFrame =
        inputBarVisibleForFrame ||
            panelTargetPx > 0 ||
            inputPanelActiveState.value ||
            imeAnimatingState.value ||
            imeBottomState.value > 0 ||
            imeTargetBottomState.value > 0 ||
            keyboardHandoffLiftPxState.intValue > 0
    SideEffect {
        bottomInsetOverlayActiveState.value = bottomInsetOverlayActiveForFrame
    }
    SideEffect {
        if (!relationshipPagerEnabled) {
            previousRelationshipHiddenInputHeightPxState.intValue =
                relationshipHiddenInputHeightPxForFrame
            return@SideEffect
        }
        val previousHiddenHeight = previousRelationshipHiddenInputHeightPxState.intValue
        val hiddenHeightDelta = relationshipHiddenInputHeightPxForFrame - previousHiddenHeight
        if (hiddenHeightDelta != 0 && listState.layoutInfo.totalItemsCount > 0) {
            val firstVisibleItemIndex = listState.firstVisibleItemIndex
            val requestedScrollOffset =
                listState.firstVisibleItemScrollOffset - hiddenHeightDelta
            val targetScrollOffset = if (firstVisibleItemIndex == 0) {
                requestedScrollOffset.coerceAtLeast(0)
            } else {
                requestedScrollOffset
            }
            // 关系页切换时，底部栏可见高度变化应结算进 LazyListState，
            // 让列表真正向上/向下取相邻消息，而不是移动外层容器裁剪当前画面。
            listState.requestScrollToItem(
                firstVisibleItemIndex,
                targetScrollOffset,
            )
        }
        previousRelationshipHiddenInputHeightPxState.intValue =
            relationshipHiddenInputHeightPxForFrame
    }
    val relationshipPagerUserScrollEnabled =
        relationshipPagerEnabled &&
            !mentionPickerVisible &&
            !showDisplaySettingsState.value
    LaunchedEffect(
        relationshipPagerEnabled,
        state.conversationId,
        state.messages.size
    ) {
        if (relationshipPagerEnabled) {
            viewModel.loadRelationshipSnapshot()
        }
    }
    // 实际生成图片并分享
    val doExportAsImage: () -> Unit = {
        showExportOptions = false
        coroutineScope.launch {
            isExporting = true
            try {
                val engine = ChatExportEngine(context)
                val selectedMsgs = state.messages.filter { it.id in state.exportSelectedIds }
                if (selectedMsgs.isNotEmpty()) {
                    val bitmap = engine.generateBitmap(
                        messages = selectedMsgs,
                        character = character,
                        characterAvatarUrl = character.avatarUrl(),
                        userAvatarUrl = prefs.avatar,
                        userName = prefs.nickname.ifBlank { prefs.username },
                        apiBase = prefs.effectiveApiBase(),
                        allCharacters = allCharacters
                    )
                    val uri = engine.saveToPictures(bitmap)
                    if (uri != null) {
                        showPrompt("图片已保存到相册")
                        context.startActivity(Intent.createChooser(engine.createShareIntent(uri), "分享聊天记录"))
                    } else {
                        showPrompt("保存失败，请检查相册权限")
                    }
                }
            } catch (e: Exception) {
                showPrompt("生成失败：${e.message}")
            } finally {
                isExporting = false
                viewModel.exitExportMode()
            }
        }
    }
    // 格式化为纯文本并复制到剪贴板
    val doExportAsText: () -> Unit = {
        showExportOptions = false
        val selectedMsgs = state.messages.filter { it.id in state.exportSelectedIds }
        val userName = prefs.nickname.ifBlank { prefs.username }
        val charName = character.displayName()
        val charactersById = allCharacters
            .mapNotNull { item -> item.id?.takeIf { it.isNotBlank() }?.let { it to item } }
            .toMap()
        val text = buildString {
            selectedMsgs.forEach { msg ->
                if (msg.isRetracted) return@forEach
                val name = if (msg.isUser()) {
                    userName
                } else {
                    msg.speakerName?.takeIf { it.isNotBlank() }
                        ?: msg.speakerCharacterId?.takeIf { it.isNotBlank() }?.let { charactersById[it]?.displayName() }
                        ?: charName
                }
                val time = formatAssistantHeaderTime(msg.timestamp)
                append("$name $time\n")
                val content = plainTextForMessage(msg, state.mode)
                append(content.trim())
                append("\n\n")
            }
        }.trim()
        val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        clipboard.setPrimaryClip(ClipData.newPlainText("聊天记录", text))
        showPrompt("已复制为纯文本")
        viewModel.exitExportMode()
    }
    // 点击顶部栏导出按钮：仅打开选项框
    val onExportTrigger: () -> Unit = { showExportOptions = true }
    // ── 导出方式选择框 ──
    if (showExportOptions) {
        val selectedCount = state.exportSelectedIds.size
        PonyOptionDialog(
            title = "导出 $selectedCount 条消息",
            onDismiss = { showExportOptions = false },
            options = listOf(
                PonyDialogOption(
                    title = "导出为图片",
                    subtitle = "保存到相册，可直接分享",
                    icon = Icons.Filled.Image,
                    iconTint = Primary,
                    onClick = doExportAsImage
                ),
                PonyDialogOption(
                    title = "复制为纯文本",
                    subtitle = "昵称 时间 / 消息内容，复制到剪贴板",
                    icon = Icons.Filled.ContentCopy,
                    iconTint = MaterialTheme.colorScheme.onSurfaceVariant,
                    onClick = doExportAsText
                )
            )
        )
    }
    var preferencesExit by remember { mutableStateOf<(() -> Unit)?>(null) }
    Scaffold(
    modifier = Modifier
        .fillMaxSize(),
    containerColor = MaterialTheme.colorScheme.background,
    topBar = {
        ChatScreenTopBar(
            state = state,
            character = character,
            prefs = prefs,
            isExporting = isExporting,
            onBack = back@{
                    preferencesExit?.let { it(); return@back }
                    voiceBridge?.stop()
                    onNavigateBack()
            },
            onCancelExport = viewModel::exitExportMode,
            onExport = onExportTrigger,
            onOpenCharacterEdit = onNavigateToEditCharacter,
            onResetGalgameProgress = viewModel::resetGalgameProgress,
            onOpenHistory = onNavigateToHistory,
            onOpenDisplaySettings = { showDisplaySettingsState.value = true }
        )
    },
    bottomBar = {
        val galgameBroken = state.mode.startsWith("galgame") && (state.galgameScore ?: 100) <= 0
        if (galgameBroken) {
            GalgameBrokenBottomBar(
                characterName = character.displayName(),
                isDeath = state.mode == "galgame_lock",
                onResetGalgameProgress = viewModel::resetGalgameProgress
            )
        }
    }
) { paddingValues ->
    PersonalPreferencesHost(prefs, character.id.orEmpty(), character.displayName(), state.mode,
        paddingValues.calculateTopPadding(), { preferencesExit = it }, viewModel::relationshipControlChanged) { openPreferences ->
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(top = paddingValues.calculateTopPadding())
            .navigationBarsPadding()
    ) {
        // 游戏/锁分模式：分数进度条（贴顶部栏底）
        // zIndex(10f)：键盘升起时消息 Box 通过 graphicsLayer 上移，视觉上进入进度条区域；
        // 进度条使用高 zIndex 确保始终绘制在消息层之上，避免文字覆盖进度条。
        if (showGalgameCapsuleAndBar && galgameScore != null) {
            GalgameProgressBarRow(score = galgameScore, modifier = Modifier.zIndex(10f))
        }
        ChatScreenStatusBanners(
            error = state.error,
            errorDebug = state.errorDebug,
            quotaExceeded = state.quotaExceeded,
            quotaExceededMessage = state.quotaExceededMessage,
            galgameSaveFailed = state.galgameSaveFailed,
            onClearError = viewModel::clearError,
            onClearQuotaExceeded = viewModel::clearQuotaExceeded,
            onDismissGalgameSaveFailed = viewModel::dismissGalgameSaveFailedDialog
        )
        val density = LocalDensity.current
        val effectiveFontScale = LocalConfiguration.current.fontScale * currentFontScale
        // 表情/更多面板按键盘同款逻辑参与视觉位移，但不参与父级布局占高。
        var activeSelectionKey by remember { mutableStateOf<String?>(null) }
        val contextActionTick = remember(state.conversationId) { mutableIntStateOf(0) }
        val markContextActionTriggered: () -> Unit = {
            contextActionTick.intValue += 1
        }
        CompositionLocalProvider(
            LocalDensity provides Density(density.density, effectiveFontScale),
            LocalFontScale provides effectiveFontScale
        ) {
        HorizontalPager(
            state = relationshipPagerState,
            beyondViewportPageCount = 1,
            userScrollEnabled = relationshipPagerUserScrollEnabled,
            modifier = Modifier
                .weight(1f)
                .fillMaxWidth()
        ) { relationshipPage ->
        if (relationshipPage == CHAT_PAGE) {
        val visibleInputHeightPx = inputBarHeightPx.floatValue.roundToInt()
        Box(
            modifier = Modifier
                .fillMaxSize()
                .onGloballyPositioned { coords ->
                    lazyColumnTopPx.floatValue = coords.positionInWindow().y
                }
        ) {
        val lastAssistantMessageId = remember(state.messages) {
            state.messages.lastOrNull { it.isAssistant() }?.stableChatItemKey()
        }
        // 操作栏只对整体最后一条消息显示（无论是 AI 还是用户消息）
        val lastOverallMessageId = remember(state.messages) {
            state.messages.lastOrNull()?.stableChatItemKey()
        }
        val voiceTranscriptAutoFollowSuppressionActive = remember(state.conversationId) {
            mutableStateOf(false)
        }
        val voiceTranscriptAutoFollowSuppressionTick = remember(state.conversationId) {
            mutableIntStateOf(0)
        }
        fun shouldSkipListAutoFollow(): Boolean =
            listTouchActiveState.value || listAutoFollowSuppressedState.value
        fun suppressListAutoFollowForUserDrag() {
            voiceTranscriptAutoFollowSuppressionActive.value = false
            listAutoFollowSuppressedState.value = true
            Log.d("GalScroll", "autoFollow suppressed by manual list drag")
        }
        val inputExtraPx = (visibleInputHeightPx - relationshipRestingInputHeightPx)
            .coerceAtLeast(0)
        val listDropsBottomSurfaceForDismiss = listBottomSurfaceDismissSnapState.value
        val bottomSurfaceLiftPx = when {
            listDropsBottomSurfaceForDismiss -> 0
            else -> bottomSurfaceLiftPxForFrame
        }
        val rawScrollObstructionPx = (bottomSurfaceLiftPx + inputExtraPx)
            .coerceAtLeast(0)
        val paddingObstructionPx = (bottomSurfaceLiftPx + inputExtraPx)
            .coerceAtLeast(0)
        val previousBottomObstructionPxState = remember(state.conversationId) {
            mutableIntStateOf(rawScrollObstructionPx)
        }
        val scrollObstructionPx = rawScrollObstructionPx
        val engagedBottomCompensationPxState = remember(state.conversationId) {
            mutableIntStateOf(0)
        }
        val pendingBottomCompensationPxState = remember(state.conversationId) {
            mutableIntStateOf(0)
        }
        val pendingBottomRevertPxState = remember(state.conversationId) {
            mutableIntStateOf(0)
        }
        val bottomCompensationRequestTickState = remember(state.conversationId) {
            mutableIntStateOf(0)
        }
        LaunchedEffect(relationshipPagerState.currentPage, relationshipPagerEnabled) {
            if (!relationshipPagerEnabled) return@LaunchedEffect
            panelExtraPxState.intValue = 0
            inputPanelActiveState.value = false
            keyboardHandoffLiftPxState.intValue = 0
            listBottomSurfaceDismissSnapState.value = false
        }
        val compensatedBottomPaddingPx = (engagedBottomCompensationPxState.intValue + pendingBottomCompensationPxState.intValue)
            .coerceAtLeast(0)
        val bottomPaddingPx = if (state.mode == "normal") {
            compensatedBottomPaddingPx
        } else {
            max(paddingObstructionPx, engagedBottomCompensationPxState.intValue)
        }
        val bottomObstructionPadding = with(LocalDensity.current) { bottomPaddingPx.toDp() }
        val bottomSurfacePadding = with(LocalDensity.current) { paddingObstructionPx.toDp() }
        val bottomAnchorTolerancePx = with(LocalDensity.current) { 2.dp.toPx() }
        val naturalBottomPaddingPx = with(LocalDensity.current) { 8.dp.toPx() }
        val maxPreservedBottomBreathingGapPx = with(LocalDensity.current) { 40.dp.toPx() }
        val bottomCompensationDeltaPxForFrame =
            scrollObstructionPx - previousBottomObstructionPxState.intValue
        val pendingRisePxForFrame = pendingBottomCompensationPxState.intValue
        val pendingRevertPxForFrame = pendingBottomRevertPxState.intValue
        val engagedBottomCompensationPxForFrame = engagedBottomCompensationPxState.intValue
        val activeBottomCompensationPxForFrame = (
            engagedBottomCompensationPxForFrame +
                pendingRisePxForFrame -
                pendingRevertPxForFrame
            ).coerceAtLeast(0)
        val hasPendingBottomCompensationForFrame =
            pendingRisePxForFrame > 0 || pendingRevertPxForFrame > 0
        val shouldSettleUnappliedObstructionForFrame =
            bottomCompensationDeltaPxForFrame == 0 &&
                scrollObstructionPx > 0 &&
                activeBottomCompensationPxForFrame == 0 &&
                !hasPendingBottomCompensationForFrame
        fun computeBottomRiseCompensationPx(obstructionDeltaPx: Int): Int {
            if (obstructionDeltaPx <= 0 || lastOverallMessageId == null) return 0
            if (activeBottomCompensationPxForFrame > 0) {
                return obstructionDeltaPx
            }
            val visibleContentBottom = listState.layoutInfo.visibleItemsInfo
                .maxOfOrNull { it.offset + it.size }
                ?.let { lazyColumnTopPx.floatValue + it.toFloat() }
                ?: 0f
            val obstructionTopFromHeight = lazyColumnTopPx.floatValue +
                (listState.layoutInfo.viewportEndOffset - scrollObstructionPx).toFloat()
            val inputTopPx = inputBarLayoutTopPx.floatValue.takeIf { it > 0f }
            val obstructionTop = if (inputTopPx != null) {
                minOf(inputTopPx, obstructionTopFromHeight)
            } else {
                obstructionTopFromHeight
            }
            // 底部遮挡升起时只按当前帧可见内容的底部判断遮挡。
            // 如果复用历史帧中更靠下的底部坐标，用户停在历史消息时会被误判为“仍在底部”，
            // 从而把列表多推一个键盘高度，形成输入栏上方的大块空白。
            // 同时要把底部限制在本次遮挡升起前的可见边界内：
            // 已经被旧底部栏裁掉、用户看不到的内容不属于“新遮挡盖住的内容”。
            val preChangeVisibleBottom = obstructionTop + obstructionDeltaPx.toFloat()
            val baselineContentBottom = minOf(visibleContentBottom, preChangeVisibleBottom)
            val preChangeBreathingGapPx = (preChangeVisibleBottom - baselineContentBottom)
                .coerceAtLeast(0f)
            val preservedBreathingGapPx = when {
                preChangeBreathingGapPx <= maxPreservedBottomBreathingGapPx ->
                    max(naturalBottomPaddingPx, preChangeBreathingGapPx)
                else -> naturalBottomPaddingPx
            }
            val desiredContentBottom = baselineContentBottom + preservedBreathingGapPx
            if (
                obstructionTop <= 0f ||
                baselineContentBottom <= 0f ||
                desiredContentBottom + bottomAnchorTolerancePx < obstructionTop
            ) {
                return 0
            }
            val overlapPx = desiredContentBottom - obstructionTop
            return overlapPx.roundToInt().coerceIn(0, obstructionDeltaPx)
        }
        val frameRiseCompensationPx = when {
            bottomCompensationDeltaPxForFrame > 0 ->
                computeBottomRiseCompensationPx(bottomCompensationDeltaPxForFrame)
            shouldSettleUnappliedObstructionForFrame ->
                computeBottomRiseCompensationPx(scrollObstructionPx)
            else -> 0
        }
        val framePendingRiseReductionPx = if (bottomCompensationDeltaPxForFrame < 0) {
            minOf(-bottomCompensationDeltaPxForFrame, pendingRisePxForFrame)
        } else {
            0
        }
        val frameRevertCompensationPx = if (bottomCompensationDeltaPxForFrame < 0) {
            minOf(
                -bottomCompensationDeltaPxForFrame - framePendingRiseReductionPx,
                engagedBottomCompensationPxForFrame,
            )
        } else {
            0
        }
        val visualBottomCompensationPxForFrame = (
            pendingRisePxForFrame -
                framePendingRiseReductionPx +
                frameRiseCompensationPx
            ).coerceAtLeast(0)
        val isWaitingOnGalgameTyping =
            state.mode.startsWith("galgame") &&
                state.isStreaming &&
                state.messages.lastOrNull()?.let { it.isAssistant() && it.content.isBlank() } == true
        val galgameTopAnchorPx = with(LocalDensity.current) {
            (capsuleHeightPxState.intValue + 8.dp.roundToPx()).coerceAtLeast(0)
        }
        val minimumGalgameTailReservePx = with(LocalDensity.current) { 104.dp.roundToPx() }
        val galgameTailAnchorPaddingPx by remember(
            state.mode,
            state.messages,
            state.isStreaming,
            lastAssistantMessageId,
            galgameTopAnchorPx,
            minimumGalgameTailReservePx,
            isWaitingOnGalgameTyping,
        ) {
            derivedStateOf {
                if (!state.mode.startsWith("galgame") || isWaitingOnGalgameTyping || lastAssistantMessageId == null) {
                    0
                } else {
                    val info = listState.layoutInfo
                    val lastAssistantIndex = state.messages.indexOfLast { it.isAssistant() }
                    val lastAssistantItem = info.visibleItemsInfo.find { item ->
                        item.key == lastAssistantMessageId || item.index == lastAssistantIndex
                    }
                    val measuredNeededPx = lastAssistantItem
                        ?.let { item -> info.viewportEndOffset - item.size - galgameTopAnchorPx }
                        ?: 0
                    max(measuredNeededPx, minimumGalgameTailReservePx).coerceAtLeast(0) / 5
                }
            }
        }
        val galgameTailAnchorPadding = with(LocalDensity.current) {
            galgameTailAnchorPaddingPx.toDp()
        }
        val effectiveViewportEndPx = run {
            val layoutInfo = listState.layoutInfo
            (layoutInfo.viewportEndOffset - paddingObstructionPx)
                .coerceIn(layoutInfo.viewportStartOffset, layoutInfo.viewportEndOffset)
        }
        SideEffect {
            listEffectiveViewportEndPxState.intValue = effectiveViewportEndPx
        }
        fun currentEffectiveViewportEndPx(): Int? =
            listEffectiveViewportEndPxState.intValue
                .takeIf { it in 1 until Int.MAX_VALUE }
        suspend fun scrollToBottomAndRepair(reason: String, animated: Boolean = false) {
            if (shouldSkipListAutoFollow()) return
            chatScrollToBottomAndRepair(
                listState = listState,
                lastMessageId = lastOverallMessageId,
                naturalBottomPaddingPx = naturalBottomPaddingPx.roundToInt(),
                bottomAnchorTolerancePx = bottomAnchorTolerancePx,
                reason = reason,
                animated = animated,
                effectiveViewportEndOffsetPx = currentEffectiveViewportEndPx(),
                expectedItemCount = state.messages.size,
                shouldSkipRepair = { shouldSkipListAutoFollow() },
            )
        }
        fun dismissRaisedBottomSurfaceForListTap() {
            requestImmediateListDropForBottomSurfaceDismiss(
                panelExtraPxState.intValue.coerceAtLeast(0)
            )
            dismissKeyboard()
            dismissInputPanelsSignal.intValue += 1
        }
        val voiceTranscriptBottomPx = remember(state.conversationId) { mutableFloatStateOf(0f) }
        val voiceTranscriptScrollTick = remember(state.conversationId) { mutableIntStateOf(0) }
        val voiceTranscriptAutoScrollSuppressed = remember(state.conversationId) { mutableStateOf(false) }
        val voiceTranscriptSafeGapPx = with(LocalDensity.current) { 14.dp.toPx() }
        fun releaseVoiceTranscriptAutoFollowSuppression() {
            if (!voiceTranscriptAutoFollowSuppressionActive.value) return
            voiceTranscriptAutoFollowSuppressionActive.value = false
            if (!listTouchActiveState.value) {
                listAutoFollowSuppressedState.value = false
            }
        }
        val onVoiceTranscriptOpened: () -> Unit = {
            voiceTranscriptAutoScrollSuppressed.value = false
            voiceTranscriptScrollTick.intValue = 0
            voiceTranscriptAutoFollowSuppressionActive.value = true
            voiceTranscriptAutoFollowSuppressionTick.intValue += 1
            listAutoFollowSuppressedState.value = true
        }
        LaunchedEffect(voiceTranscriptAutoFollowSuppressionTick.intValue) {
            if (voiceTranscriptAutoFollowSuppressionTick.intValue == 0) return@LaunchedEffect
            delay(700)
            releaseVoiceTranscriptAutoFollowSuppression()
        }
        val visibleVoiceTranscriptIds = remember(state.conversationId) { mutableStateMapOf<String, Boolean>() }
        DisposableEffect(state.conversationId) {
            onDispose { stopActiveChatVoicePlayback() }
        }
        LaunchedEffect(state.conversationId, state.messages) {
            val liveIds = state.messages.map { it.id }.toSet()
            visibleVoiceTranscriptIds.keys
                .filter { it !in liveIds }
                .toList()
                .forEach { visibleVoiceTranscriptIds.remove(it) }
        }
        val requestVoiceTranscriptSpace: (Float) -> Unit = { transcriptBottomInWindow ->
            if (
                !voiceTranscriptAutoScrollSuppressed.value &&
                !listTouchActiveState.value &&
                transcriptBottomInWindow.isFinite() &&
                transcriptBottomInWindow > 0f
            ) {
                voiceTranscriptBottomPx.floatValue = transcriptBottomInWindow
                voiceTranscriptScrollTick.intValue += 1
            }
        }
        LaunchedEffect(voiceTranscriptScrollTick.intValue) {
            if (voiceTranscriptScrollTick.intValue == 0) return@LaunchedEffect
            try {
                delay(48)
                if (voiceTranscriptAutoScrollSuppressed.value || listTouchActiveState.value) {
                    return@LaunchedEffect
                }
                awaitImeNotAnimating()
                if (voiceTranscriptAutoScrollSuppressed.value || listTouchActiveState.value) {
                    return@LaunchedEffect
                }
                val currentInputTopPx = inputBarLayoutTopPx.floatValue
                val listViewportBottomPx = lazyColumnTopPx.floatValue +
                    listState.layoutInfo.viewportEndOffset.toFloat()
                val visibleBottomPx = if (currentInputTopPx > 0f && currentInputTopPx < listViewportBottomPx) {
                    currentInputTopPx
                } else {
                    listViewportBottomPx
                }
                val overlapPx = voiceTranscriptBottomPx.floatValue + voiceTranscriptSafeGapPx - visibleBottomPx
                if (overlapPx > 1f) {
                    listState.scrollBy(overlapPx)
                }
            } finally {
                releaseVoiceTranscriptAutoFollowSuppression()
            }
        }
        SideEffect {
            fun markObserved() {
                previousBottomObstructionPxState.intValue = scrollObstructionPx
            }
            if (
                (!shouldSettleUnappliedObstructionForFrame &&
                    bottomCompensationDeltaPxForFrame == 0) ||
                lastOverallMessageId == null
            ) {
                markObserved()
                return@SideEffect
            }
            if (bottomCompensationDeltaPxForFrame < 0) {
                if (framePendingRiseReductionPx > 0) {
                    pendingBottomCompensationPxState.intValue =
                        (pendingBottomCompensationPxState.intValue - framePendingRiseReductionPx)
                            .coerceAtLeast(0)
                }
                if (frameRevertCompensationPx > 0) {
                    // Do the actual LazyList scroll from LaunchedEffect after the visual frame.
                    // Dispatching raw deltas from SideEffect can race LazyColumn's pending
                    // composition/layout work and trip Compose Runtime internal checks.
                    pendingBottomRevertPxState.intValue += frameRevertCompensationPx
                    bottomCompensationRequestTickState.intValue += 1
                }
                markObserved()
                if (
                    scrollObstructionPx == 0 &&
                    paddingObstructionPx == 0 &&
                    framePendingRiseReductionPx == 0 &&
                    frameRevertCompensationPx == 0
                ) {
                    engagedBottomCompensationPxState.intValue = 0
                }
                return@SideEffect
            }
            if (frameRiseCompensationPx <= 0) {
                markObserved()
                return@SideEffect
            }
            pendingBottomRevertPxState.intValue = 0
            pendingBottomCompensationPxState.intValue += frameRiseCompensationPx
            bottomCompensationRequestTickState.intValue += 1
            markObserved()
        }
        LaunchedEffect(bottomCompensationRequestTickState.intValue) {
            if (bottomCompensationRequestTickState.intValue <= 0) {
                return@LaunchedEffect
            }
            // 只有上移避让需要先显示一帧 graphicsLayer 视觉位移，再结算真实滚动。
            // 回退不能把整条 LazyColumn 先向下视觉平移，否则顶部会露出未渲染区域形成空白。
            if (pendingBottomCompensationPxState.intValue > 0) {
                withFrameNanos { }
            }
            var pass = 0
            var stalledFrames = 0
            while (
                pendingBottomRevertPxState.intValue > 0 ||
                pendingBottomCompensationPxState.intValue > 0
            ) {
                if (pass > 0) {
                    withFrameNanos { }
                }
                var madeProgress = false
                val pendingRevertPx = minOf(
                    pendingBottomRevertPxState.intValue,
                    engagedBottomCompensationPxState.intValue,
                )
                if (pendingRevertPx > 0) {
                    val consumedPx = listState.dispatchRawDelta(-pendingRevertPx.toFloat())
                    val actualRevertPx = abs(consumedPx).roundToInt()
                        .coerceIn(0, pendingRevertPx)
                    if (actualRevertPx > 0) {
                        engagedBottomCompensationPxState.intValue =
                            (engagedBottomCompensationPxState.intValue - actualRevertPx)
                                .coerceAtLeast(0)
                        pendingBottomRevertPxState.intValue =
                            (pendingBottomRevertPxState.intValue - actualRevertPx)
                                .coerceAtLeast(0)
                        madeProgress = true
                    }
                } else {
                    pendingBottomRevertPxState.intValue = 0
                }
                val pendingRisePx = pendingBottomCompensationPxState.intValue
                if (pendingRisePx > 0 && scrollObstructionPx > 0) {
                    val consumedPx = listState.dispatchRawDelta(pendingRisePx.toFloat())
                    val actualRisePx = consumedPx.roundToInt().coerceIn(0, pendingRisePx)
                    if (actualRisePx > 0) {
                        engagedBottomCompensationPxState.intValue += actualRisePx
                        pendingBottomCompensationPxState.intValue =
                            (pendingRisePx - actualRisePx).coerceAtLeast(0)
                        madeProgress = true
                    }
                } else if (scrollObstructionPx <= 0) {
                    pendingBottomCompensationPxState.intValue = 0
                    madeProgress = true
                }
                if (
                    pendingBottomRevertPxState.intValue <= 0 &&
                    pendingBottomCompensationPxState.intValue <= 0
                ) {
                    return@LaunchedEffect
                }
                if (madeProgress) {
                    stalledFrames = 0
                } else {
                    stalledFrames += 1
                    if (
                        stalledFrames >= 2 &&
                        scrollObstructionPx == 0 &&
                        paddingObstructionPx == 0 &&
                        pendingBottomRevertPxState.intValue > 0
                    ) {
                        // 遮挡已经完全消失但列表无法继续向下消费位移时，
                        // 直接清掉已接合补偿账本，避免底部永久留下空白。
                        pendingBottomRevertPxState.intValue = 0
                        engagedBottomCompensationPxState.intValue = 0
                        stalledFrames = 0
                    } else if (stalledFrames >= 8) {
                        // 当前布局帧无法继续消费；保留 pending，
                        // 后续遮挡或列表内容变化会继续并入同一笔补偿账本。
                        return@LaunchedEffect
                    }
                }
                pass += 1
            }
        }
        fun dismissRaisedBottomSurfaceForListDrag() {
            requestImmediateListDropForBottomSurfaceDismiss(
                panelExtraPxState.intValue.coerceAtLeast(0)
            )
            dismissKeyboard()
            dismissInputPanelsSignal.intValue += 1
        }
        // 供非最后条目的 onImagePreview 回调读取当前最新消息列表，
        // 避免在 remember{} lambda 里捕获每 80ms 变化的 state.messages 快照。
        val latestMessagesState = rememberUpdatedState(state.messages)
        // 提升到 items lambda 外：避免每条消息重组时重复调用 character.displayName() 等方法。
        // character/prefs 在对话生命周期内几乎不变，remember 使结果在重组间保持稳定引用。
        val msgCharacterName = remember(character) { character.displayName() }
        val msgCharacterAvatarUrl = remember(character) { character.avatarUrl() }
        val msgUserAvatarUrl = remember(prefs) { prefs.avatar }
        val msgUserName = remember(prefs) { prefs.nickname.ifBlank { prefs.username }.ifBlank { "我" } }
        val msgApiBase = remember(prefs) { prefs.effectiveApiBase() }
        val validMentionNames = remember(character, allCharacters) {
            (allCharacters.map { it.displayName() } + character.displayName())
                .map { it.trim() }
                .filter { it.isNotBlank() }
                .toSet()
        }
        val jumpToQuotedMessage: (String) -> Unit = remember(viewModel, latestMessagesState, state.isLoadingMoreHistory) {
            { targetMessageId ->
                coroutineScope.launch {
                    val loaded = viewModel.ensureMessageLoaded(targetMessageId)
                    if (!loaded) {
                        showPrompt("引用的消息没有找到")
                        return@launch
                    }
                    var targetIndex = -1
                    repeat(10) {
                        targetIndex = latestMessagesState.value.indexOfFirst { it.id == targetMessageId || it.messageId == targetMessageId }
                        if (targetIndex >= 0) return@repeat
                        delay(16)
                    }
                    if (targetIndex >= 0) {
                        val listIndex = targetIndex + if (state.isLoadingMoreHistory && latestMessagesState.value.isNotEmpty()) 1 else 0
                        listState.animateScrollToItem(listIndex)
                    } else {
                        showPrompt("引用的消息没有找到")
                    }
                }
            }
        }
        ChatHistoryPaginationEffect(listState, state, viewModel::loadMoreHistory)
        LazyColumn(
            state = listState,
            modifier = Modifier
                .fillMaxSize()
                .graphicsLayer {
                    // 键盘/底部面板升起时，消息内容先和底部栏使用同一帧高度做向上视觉位移；
                    // 下一帧再通过 LazyListState 结算成真实滚动，避免底部栏先动、消息后一帧追赶。
                    // 收起回退不做向下视觉位移，否则 LazyColumn 顶部会露出未渲染区域。
                    translationY = -visualBottomCompensationPxForFrame.toFloat()
                }
                .pointerInput(viewConfiguration) {
                    val touchSlop = viewConfiguration.touchSlop
                    awaitEachGesture {
                        val downEvent = awaitPointerEvent(PointerEventPass.Initial)
                        val firstDown = downEvent.changes.firstOrNull { it.changedToDownIgnoreConsumed() }
                            ?: return@awaitEachGesture
                        listTouchActiveState.value = true
                        voiceTranscriptAutoScrollSuppressed.value = true
                        val startPosition = firstDown.position
                        val contextActionTickAtDown = contextActionTick.intValue
                        var movedForScroll = false
                        var dismissedForDrag = false
                        while (true) {
                            val event = awaitPointerEvent(PointerEventPass.Initial)
                            val activeChange = event.changes.firstOrNull { it.pressed }
                            if (activeChange == null) break
                            val movedBeyondSlop =
                                (activeChange.position - startPosition).getDistance() > touchSlop
                            if (movedBeyondSlop && !movedForScroll) {
                                movedForScroll = true
                                suppressListAutoFollowForUserDrag()
                            }
                            if (
                                !dismissedForDrag &&
                                !mentionPickerVisibleState.value &&
                                contextActionTick.intValue == contextActionTickAtDown &&
                                hasInputFocusOrRaisedBottomSurfaceForGesture() &&
                                movedBeyondSlop
                            ) {
                                dismissRaisedBottomSurfaceForListDrag()
                                dismissedForDrag = true
                            }
                        }
                        listTouchActiveState.value = false
                    }
                }
                .pointerInput(viewConfiguration) {
                        val touchSlop = viewConfiguration.touchSlop
                        awaitEachGesture {
                            val downEvent = awaitPointerEvent(PointerEventPass.Final)
                            val firstDown = downEvent.changes.firstOrNull { it.changedToDownIgnoreConsumed() }
                                ?: return@awaitEachGesture
                            val startPosition = firstDown.position
                            val contextActionTickAtDown = contextActionTick.intValue
                            var moved = false
                            var released = false
                        while (true) {
                            val event = awaitPointerEvent(PointerEventPass.Final)
                            event.changes.forEach { change ->
                                if ((change.position - startPosition).getDistance() > touchSlop) {
                                    if (!moved) {
                                        suppressListAutoFollowForUserDrag()
                                    }
                                    moved = true
                                }
                                if (change.changedToUpIgnoreConsumed()) {
                                    released = true
                                }
                            }
                            if (event.changes.none { it.pressed }) break
                        }
                        if (
                            released &&
                            !moved &&
                            !mentionPickerVisibleState.value &&
                            contextActionTick.intValue == contextActionTickAtDown &&
                            hasInputFocusOrRaisedBottomSurfaceForGesture()
                        ) {
                            dismissRaisedBottomSurfaceForListTap()
                        }
                    }
                }
                .pointerInput(activeSelectionKey) {
                    awaitPointerEventScope {
                        while (true) {
                            val event = awaitPointerEvent(PointerEventPass.Final)
                            if (activeSelectionKey != null && event.changes.any { it.changedToDown() && !it.isConsumed }) {
                                activeSelectionKey = null
                            }
                        }
                    }
                },
            contentPadding = PaddingValues(
                start = 4.dp,
                top = 8.dp,
                end = 4.dp,
                bottom = 8.dp + bottomObstructionPadding + galgameTailAnchorPadding
            ),
            verticalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            // 懒加载：列表顶部加载指示器
            if (state.isLoadingMoreHistory && state.messages.isNotEmpty()) {
                item(key = "__load_more_indicator__") {
                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(vertical = 8.dp),
                        contentAlignment = Alignment.Center
                    ) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(24.dp),
                            strokeWidth = 2.dp
                        )
                    }
                }
            }
            // GalgameStartScreen 已移至 LazyColumn 外层 Box，以避免 imePadding 动画期间
            // LazyColumn 持续跟随滚动的问题
            items(
                items = state.messages,
                key = { it.stableChatItemKey() },
                contentType = { if (it.isAssistant()) "assistant" else "user" }
            ) { msg ->
                ChatMessageListItem(
                    msg = msg,
                    state = state,
                    character = character,
                    allCharacters = allCharacters,
                    viewModel = viewModel,
                    context = context,
                    pendingAnimationIds = pendingAnimationIds,
                    lastAssistantMessageId = lastAssistantMessageId,
                    lastOverallMessageId = lastOverallMessageId,
                    msgCharacterName = msgCharacterName,
                    msgCharacterAvatarUrl = msgCharacterAvatarUrl,
                    msgUserAvatarUrl = msgUserAvatarUrl,
                    msgUserName = msgUserName,
                    msgApiBase = msgApiBase,
                    currentShowTimestamp = currentShowTimestamp,
                    timestampNow = timestampNow,
                    validMentionNames = validMentionNames,
                    lastAILayoutBottomPx = lastAILayoutBottomPx,
                    isGalgameBroken = isGalgameBroken,
                    latestMessagesState = latestMessagesState,
                    visibleVoiceTranscriptIds = visibleVoiceTranscriptIds,
                    activeSelectionKey = activeSelectionKey,
                    onActiveSelectionKeyChange = { activeSelectionKey = it },
                    onNavigateToCharacterProfile = onNavigateToCharacterProfile,
                    onNavigateToSettings = onNavigateToSettings,
                    onOpenImagePreview = onOpenImagePreview,
                    messagePreviewImages = { messages -> messagePreviewImages(context, messages) },
                    plainTextForMessage = { message -> plainTextForMessage(message, state.mode) },
                    requestVoiceTranscriptSpace = requestVoiceTranscriptSpace,
                    onVoiceTranscriptOpened = onVoiceTranscriptOpened,
                    onJumpToQuotedMessage = jumpToQuotedMessage,
                    onMentionCharacterFromAvatar = ::appendMentionFromAvatar,
                    onContextActionTriggered = markContextActionTriggered,
                    showPrompt = showPrompt,
                )
            }
        }
        MentionCharacterPickerPanel(
            visible = mentionPickerVisible,
            modifier = Modifier.matchParentSize().zIndex(4f),
                candidates = mentionCandidates,
                apiBase = msgApiBase,
                bottomInset = mentionPickerBottomInsetDp,
                onDismiss = { mentionPickerVisible = false },
                onSelect = { picked ->
                    mentionPickerVisible = false
                    selectedMentionCharacters = buildList {
                        selectedMentionCharacters.forEach { existing ->
                            if (existing.id != picked.id) add(existing)
                        }
                        add(picked)
                    }
                    viewModel.updateInput(replaceLastMentionTrigger(state.inputText, picked.displayName()))
                    focusInputSignal += 1
                }
        )
        // 游戏/锁分模式开始界面：独立的 verticalScroll+imePadding 容器，
        // 避免在 LazyColumn item 内因 imePadding 动画导致每帧跟随滚动的问题
        if (state.messages.isEmpty() && !state.isLoadingHistory && state.mode.startsWith("galgame")) {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .verticalScroll(rememberScrollState())
                    .imePadding()
            ) {
                GalgameStartScreen(
                    characterName = character.displayName(),
                    mode = state.mode,
                    onStartGame = { season, time, location, customSetting ->
                        viewModel.sendGalgameStartMessage(
                            season = season,
                            time = time,
                            location = location,
                            customPrompt = customSetting
                        )
                    }
                )
            }
        }
        val inputBarGapFillPx = inputBarLayoutLiftPxForFrame
        if (inputBarGapFillPx > 0) {
            Box(
                modifier = Modifier
                    .align(Alignment.BottomCenter)
                    .fillMaxWidth()
                    .height(with(density) { inputBarGapFillPx.toDp() })
                    .background(MaterialTheme.colorScheme.surfaceVariant)
                    .zIndex(1f)
            )
        }

        // 回到底部悬浮按钮（独立 Composable，其内部 debounced state 变化不会触发 ChatScreen 级重组）
        ScrollToBottomFab(
            listState = listState,
            modifier = Modifier
                .align(Alignment.BottomEnd)
                .padding(end = 12.dp, bottom = 12.dp + bottomSurfacePadding)
                .zIndex(2f),
            onScrollToBottom = {
                listAutoFollowSuppressedState.value = false
                userScrolledUpState.value = false
                coroutineScope.launch {
                    awaitImeNotAnimating()
                    scrollToBottomAndRepair("fab", animated = true)
                }
            }
        )
            // 游戏/锁分模式：好感度胶囊（仅展示，不响应点击）
            if (showGalgameCapsuleAndBar && galgameScore != null) {
                Box(
                    modifier = Modifier
                        .align(Alignment.TopCenter)
                        .zIndex(2f)
                        .onGloballyPositioned { capsuleHeightPxState.intValue = it.size.height }
                ) {
                    GalgameScoreCapsule(
                        score = galgameScore,
                        onClick = if (state.mode == "galgame_lock") {
                            {
                                focusManager.clearFocus()
                                keyboardController?.hide()
                                onOpenVitalsPanel()
                            }
                        } else null
                    )
                }
            }
            // 加载遮罩：覆盖整个列表区域，防止用户看到滚动中间态；淡出避免突变闪烁
            androidx.compose.animation.AnimatedVisibility(
                visible = showLoadingOverlay,
                enter = EnterTransition.None,
                exit = fadeOut(tween(200))
            ) {
                Box(
                    modifier = Modifier
                        .fillMaxSize()
                        .background(MaterialTheme.colorScheme.surface)
                        .zIndex(5f),
                    contentAlignment = Alignment.Center
                ) {
                    CircularProgressIndicator(color = Primary)
                }
            }
        } // end chat page Box
        } else if (relationshipPage == CHARACTER_HOME_PAGE) {
            characterHome {
                coroutineScope.launch { relationshipPagerState.animateScrollToPage(CHAT_PAGE) }
            }
        } else {
            ChatRelationshipPanel(
                character = character,
                prefs = prefs,
                state = state,
                onRefresh = { viewModel.loadRelationshipSnapshot(force = true) },
                modifier = Modifier.fillMaxSize()
            )
        }
        } // end HorizontalPager
        } // end CompositionLocalProvider (fontScale)
        ChatScreenInputHost(
            onPersonalPreferencesClick = openPreferences,
            showInputBar = showInputBar,
            density = density,
            effectiveFontScale = effectiveFontScale,
            state = state,
            character = character,
            prefs = prefs,
            viewModel = viewModel,
            context = context,
            activeSelectionKey = activeSelectionKey,
            onActiveSelectionKeyChange = { activeSelectionKey = it },
            panelTargetPx = panelTargetPx,
            inputBarHeightPx = inputBarHeightPx,
            restingInputBarHeightPxState = restingInputBarHeightPxState,
            relationshipRestingInputHeightPx = relationshipRestingInputHeightPx,
            relationshipVisibleInputHeightPxForFrame = relationshipVisibleInputHeightPxForFrame,
            panelLiftPx = panelLiftPx,
            inputBarLayoutLiftPxForFrame = inputBarLayoutLiftPxForFrame,
            focusInputSignal = focusInputSignal,
            mentionPickerVisible = mentionPickerVisible,
            onMentionPickerVisibleChange = { mentionPickerVisible = it },
            dismissPanelsSignal = dismissInputPanelsSignal.intValue,
            panelExtraPxState = panelExtraPxState,
            inputPanelActiveState = inputPanelActiveState,
            keyboardHandoffLiftPxState = keyboardHandoffLiftPxState,
            imeBottomState = imeBottomState,
            inputBarLayoutTopPx = inputBarLayoutTopPx,
            inputFocusedState = inputFocusedState,
            isUploadingChatImages = isUploadingChatImages,
            onUploadingChatImagesChange = { isUploadingChatImages = it },
            activeMentionCharacters = activeMentionCharacters,
            onClearSelectedMentionCharacters = { selectedMentionCharacters = emptyList() },
            pendingImages = pendingImages,
            coroutineScope = coroutineScope,
            imagePickerLauncher = imagePickerLauncher,
            onPickCamera = onPickCamera,
            isCompanionActive = isCompanionActive,
            isAgentCompanionActive = isAgentCompanionActive,
            isAgentAutoLooping = isAgentAutoLooping,
            onNavigateToProactiveTasks = onNavigateToProactiveTasks,
            onOpenImagePreview = onOpenImagePreview,
            showPrompt = showPrompt,
        )
    }
    }
}
}
