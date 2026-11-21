package top.ponychat.webview.ui.creation

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import kotlinx.coroutines.launch
import kotlinx.coroutines.delay
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.layout.onSizeChanged
import top.ponychat.webview.ui.chat.ScrollToBottomFab
import androidx.compose.foundation.gestures.scrollBy
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewmodel.compose.viewModel
import top.ponychat.webview.data.model.Character
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.ui.chat.ChatInputBar
import top.ponychat.webview.ui.common.*
import top.ponychat.webview.ui.chat.VoiceState
import top.ponychat.webview.ui.chat.PonyStyleAvatar
import top.ponychat.webview.ui.chat.formatAssistantHeaderTime
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.compositeOver

@Composable
fun CreationChatScreen(character: Character, prefs: AppPreferences, onBack: () -> Unit,
    onCharacterProfile: () -> Unit = {}, onUserProfile: () -> Unit = {},
    onThemeChanged: (Boolean) -> Unit = {}, onFontScaleChanged: (Float) -> Unit = {}) {
    val id = character.id.orEmpty()
    val vm: CreationViewModel = viewModel(key = "creation-${prefs.username}-$id", factory = object : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST") override fun <T : ViewModel> create(modelClass: Class<T>): T = CreationViewModel(prefs, id) as T
    })
    val context = LocalContext.current
    DisposableEffect(context) {
        val activity = generateSequence(context) { (it as? android.content.ContextWrapper)?.baseContext }
            .filterIsInstance<android.app.Activity>().firstOrNull()
        val window = activity?.window
        val previous = window?.attributes?.softInputMode
        window?.setSoftInputMode(android.view.WindowManager.LayoutParams.SOFT_INPUT_ADJUST_NOTHING)
        onDispose { if (previous != null) window.setSoftInputMode(previous) }
    }
    val navigation = rememberNavController()
    var preferenceRevision by remember { mutableIntStateOf(0) }
    val appearance = remember(preferenceRevision) { Triple(prefs.isDarkTheme, prefs.fontScale, prefs.showTimestamp) }
    top.ponychat.webview.ui.theme.PonyChatTheme(darkTheme = appearance.first, fontScale = appearance.second) {
    NavHost(navController = navigation, startDestination = "conversation") {
        composable("conversation") {
            val state by vm.state.collectAsState()
            CreationStreamingHaptics(state.streamVibrating, prefs)
            CreationChatContent(character.name.orEmpty(), state, onBack, vm::input, { vm.send() }, { vm.send(true) },
                { vm.newSession() }, { vm.load(it) }, vm::stop,
                character.avatar.orEmpty(), prefs.avatar, prefs.username, prefs.effectiveApiBase(),
                { navigation.navigate("history") }, { navigation.navigate("settings") }, { navigation.navigate("settings") },
                onCharacterProfile, onUserProfile, { vm.deleteMessage(it) }, { navigation.navigate("edit/$it") },
                { vm.previousReplyVersion() }, { vm.nextReplyVersion() },
                onDisplaySettings = { navigation.navigate("display") }, showTimestamp = appearance.third,
                onContinue = { vm.continueStory() })
        }
        composable("display") {
            CreationDisplaySettings(prefs, { navigation.popBackStack() }) {
                preferenceRevision++; onThemeChanged(prefs.isDarkTheme); onFontScaleChanged(prefs.fontScale)
            }
        }
        composable("history") {
            val state by vm.state.collectAsState()
            CreationHistoryPage(state.history, state.session?.id, {
                if (state.session == null) vm.load()
                navigation.popBackStack()
            }, busy = state.deleting || state.saving || state.sending,
                error = state.error, onDelete = { vm.deleteSession(it) }) { id ->
                vm.load(id); navigation.popBackStack()
            }
        }
        composable("settings") {
            val state by vm.state.collectAsState()
            LaunchedEffect(state.session?.id) {
                while (true) { vm.refreshContextUsage().join(); delay(2000) }
            }
            state.session?.let { session ->
                CreationSettings(session, { navigation.popBackStack() }, state.error,
                    saving = state.saving, usage = state.contextUsage) { title, instructions, blocks ->
                    vm.configureAll(title, instructions, blocks) { navigation.popBackStack() }
                }
            }
        }
        composable("edit/{messageId}") { entry ->
            val state by vm.state.collectAsState()
            val messageId = entry.arguments?.getString("messageId")
            val message = state.session?.messages?.firstOrNull { it.id == messageId && it.role == "user" }
            CreationMessageEditor(message, state.sending || state.deleting || state.session?.busy == true, { navigation.popBackStack() }, error = state.error) { text ->
                if (message != null) {
                    vm.send(editMessageId = message.id, editedText = text, onSubmitted = { navigation.popBackStack() })
                }
            }
        }
    }
}

}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CreationChatContent(characterName: String, state: CreationUiState, onBack: () -> Unit,
    onInput: (String) -> Unit, onSend: () -> Unit, onRegenerate: () -> Unit, onNew: () -> Unit,
    onLoad: (String?) -> Unit, onStop: () -> Unit = {},
    characterAvatar: String = "", userAvatar: String = "", userName: String = "", apiBase: String = "",
    onHistory: () -> Unit = {}, onContext: () -> Unit = {}, onSettings: () -> Unit = {},
    onCharacterProfile: () -> Unit = {}, onUserProfile: () -> Unit = {},
    onDeleteMessage: (String) -> Unit = {}, onEditMessage: (String) -> Unit = {},
    onPreviousVersion: () -> Unit = {}, onNextVersion: () -> Unit = {}, onDisplaySettings: () -> Unit = {}, showTimestamp: Boolean = true,
    onContinue: () -> Unit = {}) {
    val feedback = creationHapticAction()
    CreationFailureFeedback(state, onRegenerate, onLoad)
    key(state.session?.id, state.loading) {
        val session = state.session
        // Start at the tail on the first layout, including after async history loading.
        val listState = rememberLazyListState(initialFirstVisibleItemIndex =
            if (state.loading || session?.messages.isNullOrEmpty()) 0 else session!!.messages.size + 1)
        val scope = rememberCoroutineScope()
        val tailThreshold = with(LocalDensity.current) { 240.dp.roundToPx() }
        var aligningReply by remember { mutableStateOf(false) }
        var dismissPanelsSignal by remember { mutableIntStateOf(0) }
        var inputPanelActive by remember { mutableStateOf(false) }
        var viewportHeight by remember { mutableIntStateOf(0) }
        var latestReplyHeight by remember { mutableIntStateOf(0) }
        val density = LocalDensity.current
        val imeInsets = WindowInsets.ime
        val navigationInsets = WindowInsets.navigationBars
        val imeExtraPx = (imeInsets.getBottom(density) - navigationInsets.getBottom(density)).coerceAtLeast(0)
        var retainImeViewport by remember { mutableStateOf(false) }
        LaunchedEffect(state.sending, aligningReply, imeExtraPx) {
            if ((state.sending || aligningReply) && imeExtraPx > 0) retainImeViewport = true
            else if (imeExtraPx == 0) retainImeViewport = false
        }
        val stableReplyViewport = state.sending || aligningReply || retainImeViewport
        val context = LocalContext.current
        var deleteTarget by remember(session?.id) { mutableStateOf<CreationMessage?>(null) }
        val inputBarColor = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = .6f)
            .compositeOver(MaterialTheme.colorScheme.surface)
        SystemNavigationBarColorEffect(color = inputBarColor)
        val busy = state.loading || state.sending || state.deleting || state.saving || state.switchingVersion || session?.busy == true
        val latestSending by rememberUpdatedState(state.sending || session?.busy == true)
        val latestAnchoredReply by rememberUpdatedState(state.alignReplyRequestId != null)
        LaunchedEffect(listState) {
            var previous: androidx.compose.foundation.lazy.LazyListLayoutInfo? = null
            var preservedAnchor: Pair<Int, Int>? = null
            var restoreJob: kotlinx.coroutines.Job? = null
            snapshotFlow { listState.layoutInfo }.collect { info ->
                val before = previous
                previous = info
                if (aligningReply) {
                    restoreJob?.cancel(); preservedAnchor = null
                    return@collect
                }
                if (before == null || before.viewportSize.height <= 0 || info.viewportSize.height <= 0 ||
                    before.viewportSize.height == info.viewportSize.height || state.loading) return@collect
                // Decide from the layout before the keyboard resized the viewport, not
                // from a near-bottom threshold or a previous follow-tail preference.
                val last = before.visibleItemsInfo.lastOrNull()
                val wasAtBottom = last?.index == before.totalItemsCount - 1 &&
                    last.offset + last.size + before.afterContentPadding <= before.viewportEndOffset
                if (latestSending || !wasAtBottom || (latestAnchoredReply &&
                    latestReplyHeight <= minOf(before.viewportSize.height, info.viewportSize.height))) {
                    val anchor = before.visibleItemsInfo.firstOrNull() ?: return@collect
                    if (preservedAnchor == null) preservedAnchor = anchor.index to anchor.offset
                    val target = preservedAnchor!!
                    restoreJob?.cancel()
                    restoreJob = scope.launch {
                        // IME viewport changes can arrive one frame before the reply is remeasured.
                        // Restore the same reading anchor after measurement, only for this resize.
                        repeat(3) {
                            withFrameNanos { }
                            val current = listState.layoutInfo.visibleItemsInfo.firstOrNull { it.index == target.first }
                            if (current != null) listState.scrollBy((current.offset - target.second).toFloat())
                        }
                        preservedAnchor = null
                    }
                } else {
                    // Like normal chat, re-anchor the tail on both IME opening and closing.
                    // The list clamps short content, preserving any unused space below it.
                    if (info.totalItemsCount > 0) listState.scrollToItem(info.totalItemsCount - 1)
                }
            }
        }
        val latestAlignmentRequest by rememberUpdatedState(state.alignReplyRequestId)
        LaunchedEffect(Unit) {
            // Settle the initial AndroidView measurement once; later tokens never trigger tail following.
            withFrameNanos { }; withFrameNanos { }
            if (latestAlignmentRequest == null && !state.loading && !session?.messages.isNullOrEmpty())
                listState.scrollToItem(session!!.messages.size + 1)
        }
        LaunchedEffect(state.alignReplyRequestId) {
            val requestId = state.alignReplyRequestId ?: return@LaunchedEffect
            val index = session?.messages?.indexOfLast { it.role == "assistant" && it.requestId == requestId } ?: -1
            if (index < 0 || state.loading) return@LaunchedEffect
            aligningReply = true
            try {
                withFrameNanos { }; withFrameNanos { }
                alignCreationReply(listState, index + 1)
            } finally { aligningReply = false }
        }
        Scaffold(topBar = {
            PonyTopBar(contentHeight = 56.dp) {
                PonyTopBarBackButton(onClick = onBack)
                Row(Modifier.weight(1f), verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    Box(Modifier.clickable(onClick = onCharacterProfile).semantics { contentDescription = "角色主页" }) {
                        PonyStyleAvatar(characterAvatar, characterName, apiBase, size = 36)
                    }
                    Column {
                        Text(characterName, maxLines = 1, style = MaterialTheme.typography.titleMedium)
                        Text("创造模式", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.primary)
                    }
                }
                PonyIconButton(onClick = { feedback(onHistory) }, enabled = !busy, icon = Icons.Default.History, contentDescription = "创作历史",
                    tint = MaterialTheme.colorScheme.onSurfaceVariant)
                PonyIconButton(onClick = { feedback(onNew) }, enabled = !busy, icon = Icons.Default.Add, contentDescription = "新建创作",
                    tint = MaterialTheme.colorScheme.onSurfaceVariant)
                IconButton(onClick = { feedback(onDisplaySettings) }) {
                    Icon(Icons.Filled.Settings, contentDescription = "对话设置",
                        tint = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        }, bottomBar = {
            Surface(modifier = Modifier.imePadding(), color = inputBarColor) {
                ChatInputBar(modifier = Modifier.fillMaxWidth().navigationBarsPadding(),
                    text = state.input, onTextChange = onInput, onSend = { feedback(onSend) },
                    isStreaming = busy, voiceState = VoiceState.Idle, imageAttachments = emptyList(),
                    onPickImage = {}, onPickCamera = {}, onRemoveAttachment = {},
                    allowEmptySend = session?.messages?.lastOrNull()?.role == "user",
                    mode = "creation", quotaExceeded = state.loading || session == null,
                    dismissPanelsSignal = dismissPanelsSignal, onPanelActiveChanged = { inputPanelActive = it },
                    showToolbar = true, onStopGeneration = if (state.sending) ({ feedback(onStop) }) else null,
                    onCreationContextClick = { feedback(onContext) }, onCreationSettingsClick = { feedback(onSettings) })
            }
        }) { padding ->
            // While a reply is being positioned/generated, the keyboard overlays a
            // stable message viewport. Hiding it must not resize/clamp the list.
            val ignoredIme = if (stableReplyViewport) with(density) { imeExtraPx.toDp() } else 0.dp
            val currentStable = rememberUpdatedState(stableReplyViewport)
            // Scaffold updates its padding during measurement. Read both that padding
            // and IME insets in the same phase, avoiding a one-frame height mismatch.
            val messagePadding = remember(padding, density, imeInsets, navigationInsets) {
                object : PaddingValues {
                    override fun calculateLeftPadding(layoutDirection: androidx.compose.ui.unit.LayoutDirection) = padding.calculateLeftPadding(layoutDirection)
                    override fun calculateRightPadding(layoutDirection: androidx.compose.ui.unit.LayoutDirection) = padding.calculateRightPadding(layoutDirection)
                    override fun calculateTopPadding() = padding.calculateTopPadding()
                    override fun calculateBottomPadding(): androidx.compose.ui.unit.Dp {
                        val extra = if (currentStable.value) with(density) {
                            (imeInsets.getBottom(this) - navigationInsets.getBottom(this)).coerceAtLeast(0).toDp()
                        } else 0.dp
                        return (padding.calculateBottomPadding() - extra).coerceAtLeast(0.dp)
                    }
                }
            }
            BoxWithConstraints(Modifier.fillMaxSize().padding(messagePadding)) {
                LazyColumn(Modifier.fillMaxSize().creationMessageTap {
                    if (inputPanelActive) dismissPanelsSignal++
                }.onSizeChanged { viewportHeight = it.height }, state = listState,
                    userScrollEnabled = !aligningReply,
                    contentPadding = PaddingValues(horizontal = 16.dp, vertical = 8.dp), verticalArrangement = Arrangement.spacedBy(18.dp)) {
                    item {
                        if (state.loading) CreationLoadingSkeleton()
                        if (session?.messages.isNullOrEmpty() && !state.loading) {
                            Column(Modifier.fillMaxWidth().padding(vertical = 52.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                                Icon(Icons.Default.AutoAwesome, null, tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(36.dp))
                                Spacer(Modifier.height(18.dp))
                                Text("让想象自由展开", style = MaterialTheme.typography.headlineSmall)
                                Text("和$characterName 一起写故事、聊想法，或创造一个新世界。", modifier = Modifier.padding(top = 12.dp),
                                    style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                PonyButton("设置你的创作风格", onClick = { feedback(onSettings) }, enabled = session != null,
                                    style = PonyButtonStyle.Secondary, modifier = Modifier.width(240.dp).padding(top = 20.dp))
                            }
                        }
                    }
                    items(if (state.loading) emptyList() else session?.messages.orEmpty(), key = { if (it.role == "assistant" && it.id == session?.messages?.lastOrNull()?.id) "current-reply" else it.id }) { message ->
                        if (message.role == "user") Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp, Alignment.End),
                            verticalAlignment = Alignment.Top) {
                            Box(Modifier.weight(1f, fill = false)
                                .clip(RoundedCornerShape(topStart = 16.dp, topEnd = 4.dp, bottomStart = 16.dp, bottomEnd = 16.dp))
                                .background(Brush.linearGradient(listOf(Color(0xFF6366F1), Color(0xFF4F46E5))))
                                .padding(horizontal = 14.dp, vertical = 10.dp)) {
                                CreationUserMessageText(message, busy,
                                    onDelete = { onDeleteMessage(message.id) }, onEdit = { onEditMessage(message.id) })
                            }
                            Box(Modifier.clickable(onClick = onUserProfile).semantics { contentDescription = "用户主页" }) {
                                PonyStyleAvatar(userAvatar, userName, apiBase, size = 40)
                            }
                        } else {
                            val latest = message.id == session?.messages?.lastOrNull()?.id
                            CreationAssistantMessage(message, latest, requireNotNull(session), busy || aligningReply, state.sending,
                                characterName, characterAvatar, apiBase,
                                modifier = Modifier.onSizeChanged { if (latest) latestReplyHeight = it.height },
                                minimumHeight = if (latest && state.alignReplyRequestId != null) maxHeight else 0.dp,
                                onProfile = onCharacterProfile, onDelete = { deleteTarget = message },
                                onRegenerate = onRegenerate, onPrevious = onPreviousVersion, onNext = onNextVersion,
                                showTimestamp = showTimestamp, onContinue = onContinue)
                        }
                    }

                    item {
                        if (state.sending && !state.loading && session?.messages?.lastOrNull()?.id?.startsWith("stream-") != true)
                            CreationReplySkeleton()
                        if (session?.outputTruncated == true) Text("本次回复达到长度上限，可以发送“继续”。", color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
                ScrollToBottomFab(listState, Modifier.align(Alignment.BottomEnd).padding(12.dp).padding(bottom = ignoredIme),
                    onScrollToBottom = {
                        scope.launch {
                            if (state.alignReplyRequestId != null && session?.messages?.lastOrNull()?.role == "assistant") {
                                val index = session.messages.size
                                listState.animateScrollToItem(index, (latestReplyHeight - viewportHeight).coerceAtLeast(0))
                            } else listState.animateScrollToItem((session?.messages?.size ?: 0) + 1)
                        }
                    }, tailDistanceThresholdPx = tailThreshold)
            }

        }
        deleteTarget?.let { target ->
            PonyConfirmDialog(title = "删除这条消息？", message = "只删除选中的这条消息，其余对话会保留。",
                confirmText = "确认删除", onConfirm = { deleteTarget = null; onDeleteMessage(target.id) },
                onDismiss = { deleteTarget = null }, actionStyle = PonyDialogActionStyle.Danger, confirmEnabled = !busy)
        }
    }
}
