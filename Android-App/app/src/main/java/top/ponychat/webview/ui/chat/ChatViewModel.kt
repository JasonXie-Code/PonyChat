package top.ponychat.webview.ui.chat
import android.app.Application
import android.content.SharedPreferences
import android.util.Log
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.ProcessLifecycleOwner
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.launch
import top.ponychat.webview.data.local.CachedVoiceAudio
import top.ponychat.webview.data.local.LocalCacheStore
import top.ponychat.webview.data.local.ChatVoiceCache
import top.ponychat.webview.data.model.*
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.data.repo.CharacterRepository
import top.ponychat.webview.data.repo.ChatDelta
import top.ponychat.webview.data.repo.ChatRepository
import top.ponychat.webview.data.api.SyncWebSocketManager
import top.ponychat.webview.util.ClientContextHelper
import top.ponychat.webview.util.DebugLog
import top.ponychat.webview.util.MessageVibrationHelper
import top.ponychat.webview.util.toUserMessage
class ChatViewModel(application: Application) : AndroidViewModel(application) {
    internal val TAG = "ChatViewModel"
    internal val androidApplication: Application = application
    internal val prefs = AppPreferences(application)
    internal val charRepo = CharacterRepository(prefs)
    internal val chatRepo = ChatRepository(prefs)
    internal val localCache = LocalCacheStore(application)
    internal val _state = MutableStateFlow(
        ChatUiState(
            mode = when (prefs.chatMode) {
                "galgame", "galgame_lock" -> prefs.chatMode
                else -> "normal"
            },
            chatSettings = ChatSettings(
                temperature = prefs.chatTemperature,
                maxTokens = prefs.chatMaxTokens,
                topP = prefs.chatTopP,
                repeatPenalty = prefs.chatRepeatPenalty,
                topK = prefs.chatTopK,
                reasoningEffort = prefs.reasoningEffort
            )
        )
    )
    val state: StateFlow<ChatUiState> = _state.asStateFlow()
    /** 计时器状态独立于本 state，避免每秒 tick 触发整页重组 */
    internal val _timerState = MutableStateFlow(Triple(0L, 0, false))
    val timerState: StateFlow<Triple<Long, Int, Boolean>> = _timerState.asStateFlow()
    internal var streamJob: Job? = null
    internal var autoSaveJob: Job? = null
    internal var historyLoadJob: Job? = null
    internal var conversationListJob: Job? = null
    internal var switchConversationJob: Job? = null
    internal var timerJob: Job? = null
    internal var currentJobId: String? = null
    private var lastQuickMessagesUsername: String = prefs.username
    private val prefsChangeListener = SharedPreferences.OnSharedPreferenceChangeListener { _, key ->
        if (key == "username") {
            val nextUsername = prefs.username
            if (nextUsername != lastQuickMessagesUsername) {
                lastQuickMessagesUsername = nextUsername
                _state.value = _state.value.copy(quickMessages = emptyList(), isLoadingQuickMessages = false)
                viewModelScope.launch { loadQuickMessages(force = true) }
            }
        }
    }
    // 连续使用时间追踪（合规：超过 2 小时提示休息）
    internal val _sessionStartMs = MutableStateFlow(0L)
    internal val _showUsageReminder = MutableStateFlow(false)
    val showUsageReminder: StateFlow<Boolean> = _showUsageReminder.asStateFlow()
    internal var usageReminderJob: Job? = null
    // 危机热线弹窗（后端检测到关键词时触发）
    internal val _showCrisisHotlineDialog = MutableStateFlow(false)
    val showCrisisHotlineDialog: StateFlow<Boolean> = _showCrisisHotlineDialog.asStateFlow()
    internal val _snackbarMessages = MutableSharedFlow<String>(extraBufferCapacity = 8)
    val snackbarMessages: SharedFlow<String> = _snackbarMessages.asSharedFlow()
    private var pendingSendFailurePromptCount: Int = 0
    private var pendingSendFailurePromptRoundStartedAtMs: Long = 0L
    private var pendingSendFailurePromptRoundStartSeq: Int? = null
    private var pendingSendFailureFlushJob: Job? = null
    internal fun queueSendFailurePrompt(trackNormalRound: Boolean = false) {
        if (trackNormalRound) {
            val roundStartedAt = lastNormalGenerationStartedAtMs
            val roundStartSeq = lastNormalGenerationStartSeq
            if (roundStartedAt > 0L || roundStartSeq != null) {
                if (hasSuccessfulNormalAssistantAfter(roundStartSeq, roundStartedAt)) {
                    if (pendingSendFailurePromptRoundStartedAtMs > 0L || pendingSendFailurePromptRoundStartSeq != null) {
                        clearPendingSendFailurePrompt("normal_reply_already_recovered")
                    }
                    return
                }
                if (pendingSendFailurePromptRoundStartedAtMs <= 0L) {
                    pendingSendFailurePromptRoundStartedAtMs = roundStartedAt
                    pendingSendFailurePromptRoundStartSeq = roundStartSeq
                }
            }
        }
        pendingSendFailurePromptCount += 1
        flushPendingSendFailurePrompt()
    }
    fun flushPendingSendFailurePrompt() {
        if (pendingSendFailurePromptCount <= 0) return
        if (pendingSendFailurePromptRoundStartedAtMs > 0L || pendingSendFailurePromptRoundStartSeq != null) {
            markNormalReplySucceeded("failure_prompt_flush_check")
            if (pendingSendFailurePromptCount <= 0) return
            schedulePendingSendFailureFlushAfterRecoveryCheck()
            return
        }
        emitPendingSendFailurePromptNow()
    }
    private fun emitPendingSendFailurePromptNow() {
        if (pendingSendFailurePromptCount <= 0) return
        if (_snackbarMessages.subscriptionCount.value <= 0) return
        if (!ProcessLifecycleOwner.get().lifecycle.currentState.isAtLeast(Lifecycle.State.STARTED)) return
        pendingSendFailurePromptCount = 0
        pendingSendFailurePromptRoundStartedAtMs = 0L
        pendingSendFailurePromptRoundStartSeq = null
        _snackbarMessages.tryEmit("发送失败")
    }
    private fun schedulePendingSendFailureFlushAfterRecoveryCheck() {
        if (pendingSendFailureFlushJob?.isActive == true) return
        pendingSendFailureFlushJob = viewModelScope.launch {
            try {
                if (_state.value.mode == "normal" && _state.value.character != null) {
                    refreshNewMessagesFromServer(allowWhileStreaming = true)
                    delay(1800L)
                    markNormalReplySucceeded("failure_prompt_recovery_check")
                    if (pendingSendFailurePromptCount <= 0) return@launch
                }
                emitPendingSendFailurePromptNow()
            } finally {
                pendingSendFailureFlushJob = null
            }
        }
    }
    private fun clearPendingSendFailurePrompt(reason: String) {
        if (pendingSendFailurePromptCount > 0) {
            DebugLog.d(TAG, "Clear pending send failure prompt: $reason")
        }
        pendingSendFailurePromptCount = 0
        pendingSendFailurePromptRoundStartedAtMs = 0L
        pendingSendFailurePromptRoundStartSeq = null
        pendingSendFailureFlushJob?.cancel()
        pendingSendFailureFlushJob = null
    }
    internal fun markNormalReplySucceeded(reason: String) {
        if (pendingSendFailurePromptRoundStartedAtMs <= 0L && pendingSendFailurePromptRoundStartSeq == null) return
        if (!hasSuccessfulNormalAssistantAfter(
                pendingSendFailurePromptRoundStartSeq,
                pendingSendFailurePromptRoundStartedAtMs
            )
        ) {
            return
        }
        clearPendingSendFailurePrompt(reason)
    }
    private fun hasSuccessfulNormalAssistantAfter(startSeq: Int?, startedAt: Long): Boolean {
        if (startSeq == null && startedAt <= 0L) return false
        val lowerBound = (startedAt - 1500L).coerceAtLeast(0L)
        fun arrivedAfter(seq: Int?, timestamp: Long?): Boolean {
            return when {
                startSeq != null && seq != null -> seq > startSeq
                startedAt > 0L -> (timestamp ?: 0L) >= lowerBound
                else -> false
            }
        }
        return _state.value.messages.any { message ->
            message.isAssistant() &&
                !message.isStreaming &&
                !message.isError &&
                arrivedAfter(message.sequenceNumber, message.timestamp)
        } || sentMessages.any { message ->
            message.role == "assistant" &&
                message.isHidden != true &&
                arrivedAfter(message.sequenceNumber, message.timestamp)
        }
    }
    internal val clientId = "single"
    internal var lastForegroundRefreshAt: Long = 0L
    internal var lastNetworkAvailableRefreshAt: Long = 0L
    internal var startTime: Long = 0L
    internal var currentRetryCount: Int = 0
    // 所有已发送给服务端的消息（用于构建 context）
    internal val sentMessages = mutableListOf<ChatMessage>()
    /** normal 模式回复轮次状态；连续消息合并与防抖由后端负责。 */
    internal var normalAssistantVisible = false
    internal var normalGenerationStarted = false
    internal var lastNormalGenerationStartedAtMs: Long = 0L
    internal var lastNormalGenerationStartSeq: Int? = null
    internal var replyRecoveryPollJob: Job? = null
    internal var normalAcceptedRecoveryJob: Job? = null
    internal val normalGenerationUserIds = mutableListOf<String>()
    internal val normalUploadingUserMessageIds = mutableSetOf<String>()
    internal val unconfirmedNormalUserKeys = mutableSetOf<String>()
    internal val deferredNormalReplyCharacterIds = mutableSetOf<String>()
    init {
        prefs.registerChangeListener(prefsChangeListener)
        // 后台刷新位置/天气缓存（有权限时才生效，无权限则静默跳过）
        viewModelScope.launch(Dispatchers.IO) {
            ClientContextHelper.refreshLocationAndWeather(getApplication())
        }
    }
    /**
     * @param listEntryMode 角色列表顶栏当前选中的模式；仅走「完整初始化」分支时才会写入 VM 与 prefs。
     * 若为 null（如 ChatScreen 兜底调用），完整初始化时沿用 [prefs.chatMode]。
     * 早退路径（同角色正在生成 / 已加载会话）仅在**当前 VM 模式与本次要进入的模式一致**时生效；
     * 若在列表中切换了 聊天/游戏/锁分 后再进同一角色，必须走完整初始化，否则会错显示上一模式的对话。
     */
    fun initWithCharacter(character: Character, listEntryMode: String? = null) {
        val incomingCharacterId = character.id?.takeIf { it.isNotBlank() }
        val currentState = _state.value
        val currentCharacterId = currentState.character?.id?.takeIf { it.isNotBlank() }
        val modeToApply = listEntryMode?.trim()?.takeIf { it.isNotEmpty() }?.let { m ->
            when (m) {
                "galgame", "galgame_lock" -> m
                else -> "normal"
            }
        } ?: prefs.chatMode.ifBlank { "normal" }.let { p ->
            when (p) {
                "galgame", "galgame_lock" -> p
                else -> "normal"
            }
        }
        // 同角色且正在生成：保留当前会话现场（用户消息 + AI 占位打字动画），
        // 避免「先清空再拉历史」把进行中的 UI 状态瞬间抹掉。
        // 尤其是游戏/锁分模式，生成完成前后端历史尚未落库，强制重载会看到「消息消失」。
        // 若列表侧切换了模式，不得早退，否则仍显示上一模式的对话。
        if (
            incomingCharacterId != null &&
            currentCharacterId == incomingCharacterId &&
            currentState.isStreaming &&
            currentState.mode == modeToApply
        ) {
            _state.value = currentState.copy(character = character)
            return
        }
        // 同角色且已加载完毕（非首次进入）：仅刷新角色对象，保留对话状态（含进行中的生成）。
        // 每个角色拥有独立的 ViewModel 实例，切换角色不会打断对方正在生成的回复。
        if (
            incomingCharacterId != null &&
            currentCharacterId == incomingCharacterId &&
            currentState.messages.isNotEmpty() &&
            !currentState.isLoadingHistory &&
            currentState.mode == modeToApply
        ) {
            _state.value = currentState.copy(character = character)
            if (!currentState.isStreaming) {
                if (modeToApply == "normal") refreshNewMessagesFromServer()
                else refreshConversationFromServer()
            }
            return
        }
        // 仅完整初始化时应用模式：禁止在早退之后由外部先于 setMode 再 init 导致 mode 与历史不一致。
        // 完整初始化前取消进行中的流式任务，防止旧模式（如 galgame）的响应写入新模式的消息列表
        streamJob?.cancel()
        streamJob = null
        resetNormalSendState()
        setMode(modeToApply)
        val current = _state.value
        _state.value = current.copy(
            character = character,
            isLoadingHistory = true,
            messages = emptyList(),
            inputText = "",
            isStreaming = false,
            error = null,
            conversationId = null,
            galgameScore = null,
            galgameVictoryCelebrationAck = false
        )
        sentMessages.clear()
        val characterId = character.id?.takeIf { it.isNotBlank() }
        if (characterId == null) {
            _state.value = _state.value.copy(
                isLoadingHistory = false,
                error = "角色数据异常：缺少角色 ID"
            )
            return
        }
        prefs.lastCharacterId = characterId
        // 完整进入聊天页本身已经启动历史加载。NavBackStackEntry 入场时可能随即派发 ON_RESUME，
        // 将这次初始化记入前台刷新节流，避免锁分/游戏模式刚进页又重复 reloadConversation。
        lastForegroundRefreshAt = System.currentTimeMillis()
        viewModelScope.launch { loadQuickMessages() }
        launchHistoryLoad(character)
    }
    fun setMode(mode: String) {
        val normalized = when (mode) {
            "galgame", "galgame_lock" -> mode
            else -> "normal"
        }
        prefs.chatMode = normalized
        _state.value = _state.value.copy(mode = normalized)
    }
    /** 切换模式并重新加载当前角色对话（与 Web 端切换游戏/锁分后重载一致） */
    fun setModeAndReload(mode: String) {
        setMode(mode)
        reloadConversation()
    }
    /** 重新加载当前角色对话（用于切换游戏/锁分模式后拉取对应数据） */
    fun reloadConversation() {
        if (_state.value.isStreaming) return
        val character = _state.value.character ?: return
        _state.value = _state.value.copy(isLoadingHistory = true, isBackgroundRefreshing = false)
        historyLoadJob?.cancel()
        historyLoadJob = viewModelScope.launch { loadConversationHistory(character) }
    }
    /** 当前会话可见时的静默补拉：用于 WS/HTTP/Worker 通知到达后同步最新服务端消息。 */
    fun refreshConversationFromServer(allowWhileStreaming: Boolean = false) {
        if (_state.value.isStreaming && !allowWhileStreaming) return
        val character = _state.value.character ?: return
        _state.value = _state.value.copy(isBackgroundRefreshing = true, error = null, errorDebug = null)
        historyLoadJob?.cancel()
        historyLoadJob = viewModelScope.launch { loadConversationHistory(character) }
    }
    /** 应用回到前台后的轻量恢复：游戏模式优先重拉，保存失败时自动再试一次同步。 */
    fun onForegroundResume() {
        if (_state.value.isStreaming) {
            startReplyRecoveryPolling("foreground_streaming", _state.value.mode, null, System.currentTimeMillis() - 1200L)
            viewModelScope.launch {
                delay(1800L)
                flushPendingSendFailurePrompt()
            }
            return
        }
        val now = System.currentTimeMillis()
        if (now - lastForegroundRefreshAt < 1800L) {
            viewModelScope.launch {
                delay(800L)
                flushPendingSendFailurePrompt()
            }
            return
        }
        lastForegroundRefreshAt = now
        if (_state.value.character == null) return
        // 普通模式：后台刷新位置/天气缓存（缓存未过期时内部直接返回，无额外开销）
        if (_state.value.mode == "normal") {
            viewModelScope.launch(Dispatchers.IO) {
                ClientContextHelper.refreshLocationAndWeather(getApplication())
            }
            SyncWebSocketManager.pullUndeliveredOnce(prefs, "chat_foreground_resume")
            // 优先增量补拉（有 conversationId 和 sequenceNumber 时），否则回退全量刷新
            refreshNewMessagesFromServer()
            // 延迟二次补拉：覆盖"列表摘要先到、messages 表稍后落库"的时序窗口
            viewModelScope.launch {
                delay(800L)
                refreshNewMessagesFromServer(allowWhileStreaming = _state.value.mode == "normal")
                delay(1000L)
                flushPendingSendFailurePrompt()
            }
            return
        }
        if (_state.value.galgameSaveFailed) {
            forceSaveNow("resume_retry")
        }
        reloadConversation()
        viewModelScope.launch {
            delay(800L)
            flushPendingSendFailurePrompt()
        }
    }
    /** 系统报告网络恢复时，主动补拉 outbox 与当前会话，弥补弱网下 WS/SSE 事件丢失。 */
    fun onNetworkAvailable() {
        val now = System.currentTimeMillis()
        if (now - lastNetworkAvailableRefreshAt < 2500L) return
        lastNetworkAvailableRefreshAt = now
        SyncWebSocketManager.pullUndeliveredOnce(prefs, "chat_net_available")
        if (_state.value.isStreaming) {
            startReplyRecoveryPolling("network_streaming", _state.value.mode, null, System.currentTimeMillis() - 1200L)
            return
        }
        if (_state.value.mode == "normal") {
            refreshNewMessagesFromServer()
        } else {
            refreshConversationFromServer()
        }
    }
    /** normal 模式按 sequence_number 增量补拉；缺少序号或接口失败时回退全量刷新。 */
    internal fun refreshNewMessagesFromServer(allowWhileStreaming: Boolean = false) {
        val character = _state.value.character ?: return
        val characterId = character.id?.takeIf { it.isNotBlank() } ?: return
        val username = prefs.username
        val conversationId = _state.value.conversationId?.takeIf { it.isNotBlank() }
        val startSeq = _state.value.messages.mapNotNull { it.sequenceNumber }.maxOrNull()
        if (conversationId == null) {
            refreshConversationFromServer(allowWhileStreaming = allowWhileStreaming)
            return
        }
        val initialSeq = startSeq ?: run {
            refreshConversationFromServer(allowWhileStreaming = allowWhileStreaming)
            return
        }
        _state.value = _state.value.copy(isBackgroundRefreshing = true, error = null, errorDebug = null)
        historyLoadJob?.cancel()
        historyLoadJob = viewModelScope.launch {
            val collected = mutableListOf<ChatMessage>()
            var afterSeq = initialSeq
            var ok = true
            var pages = 0
            while (pages < 5) {
                pages++
                val page = chatRepo.loadMessagesAfter(
                    username = username,
                    characterId = characterId,
                    conversationId = conversationId,
                    afterSeq = afterSeq,
                    limit = 100
                )
                if (page == null) {
                    ok = false
                    break
                }
                val batch = page.messages
                if (batch.isEmpty()) break
                collected.addAll(batch)
                afterSeq = page.maxSeq ?: batch.mapNotNull { it.sequenceNumber }.maxOrNull() ?: afterSeq
                if (!page.hasMore) break
            }
            if (!ok) {
                _state.value = _state.value.copy(isBackgroundRefreshing = false)
                refreshConversationFromServer(allowWhileStreaming = allowWhileStreaming)
                return@launch
            }
            if (collected.isEmpty()) {
                _state.value = _state.value.copy(isBackgroundRefreshing = false)
                return@launch
            }
            val deliverable = if (allowWhileStreaming && _state.value.mode == "normal" && _state.value.isStreaming) {
                collected.filterNot { msg ->
                    msg.role == "assistant" &&
                        effectiveVoiceState(msg)?.status?.equals("pending", ignoreCase = true) == true
                }
            } else {
                collected
            }
            if (deliverable.isEmpty()) {
                _state.value = _state.value.copy(isBackgroundRefreshing = false)
                return@launch
            }
            val uiSpeakerFallback = _state.value.messages
            val runtimeSpeakerFallback = sentMessages.toList()
            val collectedWithSpeakers = preserveChatMessageSpeakers(deliverable, runtimeSpeakerFallback)
            val serverUiMessages = visibleMessagesForUi(
                collectedWithSpeakers,
                username,
                characterId,
                "normal",
                conversationId,
                uiSpeakerFallback
            )
            val serverUiByKey = serverUiMessages.associateBy { uiMessageKey(it) }
            val existingUiKeys = _state.value.messages.map { uiMessageKey(it) }.toSet()
            val mergedUiMessages = orderedUiMessages(_state.value.messages.map { msg ->
                val authoritative = serverUiByKey[uiMessageKey(msg)]
                if (msg.isRetracted && authoritative?.isRetracted != true) msg else authoritative ?: msg
            } + serverUiMessages.filter { uiMessageKey(it) !in existingUiKeys })
            val serverRuntimeMessages = runtimeMessagesForClientWithLocalImages(collectedWithSpeakers, runtimeSpeakerFallback)
            val serverSentByKey = serverRuntimeMessages.associateBy { chatMessageKey(it) }
            val existingSentKeys = sentMessages.map { chatMessageKey(it) }.toSet()
            for (i in sentMessages.indices) {
                serverSentByKey[chatMessageKey(sentMessages[i])]?.let { authoritative ->
                    sentMessages[i] = authoritative
                }
            }
            val newSent = serverRuntimeMessages.filter { chatMessageKey(it) !in existingSentKeys }
            sentMessages.addAll(newSent)
            val orderedSent = orderedChatMessages(sentMessages.toList())
            sentMessages.clear()
            sentMessages.addAll(orderedSent)
            val currentState = _state.value
            val nextUiMessages = if (currentState.messages.isSameVisibleMessageListAs(mergedUiMessages)) {
                currentState.messages
            } else {
                mergedUiMessages
            }
            _state.value = currentState.copy(
                messages = nextUiMessages,
                isBackgroundRefreshing = false,
                error = null,
                errorDebug = null
            )
            if (serverUiMessages.any { it.isAssistant() && !it.isStreaming && !it.isError }) {
                markNormalUsersAcceptedByServer(acceptAllPendingOnServerSignal = true)
            }
            localCache.saveConversation(
                username = username,
                characterId = characterId,
                mode = "normal",
                conversationId = conversationId,
                messages = sentMessages.toList()
            )
            markNormalReplySucceeded("server_incremental_refresh")
        }
    }
    /** 将服务端/缓存 ChatMessage 转为 UI Message；游戏/锁分模式保留 displayContent、rawContent、galgameOptions */
    internal fun chatMessageToMessage(msg: ChatMessage): Message {
        val opts = parseGalgameOptionsFromPayload(msg.galgameOptions)
        // 后端持久化助手回合时把整段场景 HTML 放在 content；displayContent 常为空。
        // 统一灌入 displayContent，避免仅依赖 contentToShow 时漏掉 gal-scene-* 导致对白块无法从 HTML 解析。
        val c = msg.content.trim()
        val disp = msg.displayContent?.trim()?.takeIf { it.isNotBlank() }
        val hasGalMarkers: (String) -> Boolean = { s ->
            s.contains("galgame-scene-container") || s.contains("gal-scene-")
        }
        // displayContent 若被存成无结构片段（无 gal-*），仍以 content 中的完整场景 HTML 为准
        val effectiveDisplay = when {
            msg.role == "assistant" && hasGalMarkers(c) -> when {
                disp.isNullOrBlank() -> c
                hasGalMarkers(disp) -> disp
                else -> c
            }
            !disp.isNullOrBlank() -> disp
            else -> null
        }
        // 部分接口/历史只落 content 整包 JSON、raw 为空；重装拉历史后需能解析 scene，与 ChatScreen 中 effectiveRaw 一致
        val effectiveRaw = msg.rawContent?.trim()?.takeIf { it.isNotBlank() }
            ?: if (msg.role == "assistant" && c.startsWith("{")) c else null
        val restoredContent = restoreRemoteChatImagesForDisplay(getApplication(), msg.content)
        val normalizedContent = if (msg.attachments.orEmpty().isNotEmpty() && restoredContent.trim() == "[表情]") {
            ""
        } else {
            restoredContent
        }
        val messageTimestamp = msg.timestamp ?: System.currentTimeMillis()
        return Message(
            id = stableChatMessageId(
                role = msg.role,
                messageId = msg.messageId,
                sequenceNumber = msg.sequenceNumber,
                timestamp = messageTimestamp
            ),
            role = msg.role,
            content = normalizedContent,
            timestamp = messageTimestamp,
            generationDurationMs = msg.generationDurationMs,
            messageId = msg.messageId,
            sequenceNumber = msg.sequenceNumber,
            displayContent = effectiveDisplay,
            rawContent = effectiveRaw,
            sceneMetadata = null,
            galgameOptions = opts,
            quotedMessage = msg.quotedMessage,
            attachments = msg.attachments.orEmpty(),
            voiceState = ChatVoiceCache.hydrate(getApplication(), effectiveVoiceState(msg)),
            speakerCharacterId = msg.speakerCharacterId,
            speakerName = msg.speakerName,
            speakerAvatar = msg.speakerAvatar,
            isRetracted = msg.role == "user" && isRetractedUserMessageContent(normalizedContent)
        )
    }
    internal fun retractedOriginalContentForMessage(
        message: Message,
        username: String = prefs.username,
        characterId: String? = _state.value.character?.id,
        mode: String = _state.value.mode,
        conversationId: String? = _state.value.conversationId
    ): String? {
        if (!message.isUser() || !message.isRetracted) return null
        val charId = characterId?.takeIf { it.isNotBlank() } ?: return null
        val candidateIds = listOfNotNull(message.messageId, message.id).distinct()
        return candidateIds.firstNotNullOfOrNull { id ->
            localCache.loadRetractedMessageOriginal(username, charId, mode, conversationId, id)
        }
    }
    internal fun restoreRetractedOriginalContentForUi(
        message: Message,
        username: String,
        characterId: String,
        mode: String,
        conversationId: String?
    ): Message {
        val original = retractedOriginalContentForMessage(
            message = message,
            username = username,
            characterId = characterId,
            mode = mode,
            conversationId = conversationId
        ) ?: return message
        return if (original == message.content) message else message.copy(content = original)
    }
    fun restoreRetractedMessageInput(messageId: String) {
        if (messageId.isBlank()) return
        val message = _state.value.messages.firstOrNull { it.id == messageId || it.messageId == messageId } ?: return
        val content = retractedOriginalContentForMessage(message) ?: message.content
        _state.value = _state.value.copy(inputText = content)
    }
    internal fun visibleMessagesForUi(
        messages: List<ChatMessage>,
        username: String,
        characterId: String,
        mode: String,
        conversationId: String?,
        speakerFallbackMessages: List<Message> = emptyList()
    ): List<Message> {
        val locallyHidden = localCache.loadLocallyHiddenMessageIds(username, characterId, mode, conversationId)
        val visible = messages
            .filter {
                val msgId = it.messageId
                it.isHidden != true &&
                    !isContextSummaryPlaceholder(it) &&
                    (msgId == null || msgId !in locallyHidden)
            }
            .map { chatMessageToMessage(it) }
            .map { restoreRetractedOriginalContentForUi(it, username, characterId, mode, conversationId) }
        val mergedVisible = preserveUiMessageSpeakers(visible, speakerFallbackMessages)
        return orderedUiMessages(mergedVisible)
    }
    internal suspend fun saveVoiceAudioTransferAndAck(
        username: String,
        characterId: String?,
        conversationId: String?,
        messageId: String,
        voiceCacheKey: String?,
        transfer: VoiceAudioTransfer?,
    ): CachedVoiceAudio? {
        val key = voiceCacheKey?.takeIf { it.isNotBlank() } ?: return null
        val cached = withContext(Dispatchers.IO) {
            runCatching {
                ChatVoiceCache.save(getApplication(), key, transfer)
            }.onFailure { err ->
                Log.w(TAG, "voice audio save failed messageId=$messageId key=${key.take(16)}", err)
            }.getOrNull()
        } ?: return null
        val user = username.takeIf { it.isNotBlank() }
        val charId = characterId?.takeIf { it.isNotBlank() }
        val convId = conversationId?.takeIf { it.isNotBlank() }
        if (user != null && charId != null && convId != null && messageId.isNotBlank()) {
            runCatching {
                chatRepo.ackMessageVoiceAudio(
                    username = user,
                    characterId = charId,
                    conversationId = convId,
                    messageId = messageId,
                    voiceCacheKey = key
                ).onFailure { err ->
                    Log.w(TAG, "voice audio ack failed messageId=$messageId", err)
                }
            }.onFailure { err ->
                Log.w(TAG, "voice audio ack crashed messageId=$messageId", err)
            }
        }
        return cached
    }
    internal suspend fun upsertRealtimeAssistantParagraph(
        delta: ChatDelta.AssistantParagraph,
        paraId: String,
        isFirstPara: Boolean,
        characterId: String?,
    ) {
        var voiceState = delta.voiceState
        if (voiceState != null) {
            val cached = saveVoiceAudioTransferAndAck(
                username = prefs.username,
                characterId = characterId,
                conversationId = _state.value.conversationId,
                messageId = paraId,
                voiceCacheKey = voiceState.voiceCacheKey,
                transfer = delta.audioTransfer
            )
            voiceState = if (cached != null) {
                voiceState.copy(
                    localFile = cached.localFile,
                    durationMs = cached.durationMs,
                    waveform = voiceState.waveform.ifEmpty { cached.waveform }
                )
            } else {
                withContext(Dispatchers.IO) {
                    ChatVoiceCache.hydrate(getApplication(), voiceState) ?: voiceState
                }
            }
        }
        val newMsg = Message(
            id = paraId,
            role = "assistant",
            content = delta.content,
            timestamp = delta.timestamp ?: System.currentTimeMillis(),
            isStreaming = false,
            messageId = paraId,
            sequenceNumber = delta.sequenceNumber,
            generationDurationMs = if (isFirstPara) currentGenerationDurationMs() else null,
            voiceState = voiceState,
            speakerCharacterId = delta.speakerCharacterId,
            speakerName = delta.speakerName,
            speakerAvatar = delta.speakerAvatar,
            autoScrollBatchIndex = delta.index,
            autoScrollBatchTotal = delta.total,
            allowRealtimeAnimation = !delta.displayOverdue
        )
        val runtimeMessage = if (delta.content.isNotBlank() || voiceState != null) {
            ChatMessage(
                role = "assistant",
                content = delta.content,
                messageId = paraId,
                timestamp = newMsg.timestamp,
                sequenceNumber = delta.sequenceNumber,
                generationDurationMs = newMsg.generationDurationMs,
                voiceState = voiceState,
                speakerCharacterId = delta.speakerCharacterId,
                speakerName = delta.speakerName,
                speakerAvatar = delta.speakerAvatar
            )
        } else {
            null
        }
        upsertRealtimeAssistantMessage(newMsg, runtimeMessage)
    }
    internal fun upsertRuntimeAssistantMessage(msg: ChatMessage) {
        val key = chatMessageKey(msg)
        val existingIndex = sentMessages.indexOfFirst { chatMessageKey(it) == key }
        if (existingIndex >= 0) {
            sentMessages[existingIndex] = msg
            val ordered = orderedChatMessages(sentMessages.toList())
            sentMessages.clear()
            sentMessages.addAll(ordered)
            return
        }
        val seq = msg.sequenceNumber
        val ts = msg.timestamp
        val insertAt = sentMessages.indexOfFirst { existing ->
            val existingSeq = existing.sequenceNumber
            when {
                seq != null && existingSeq != null -> existingSeq > seq
                ts != null -> (existing.timestamp ?: Long.MAX_VALUE) > ts
                else -> false
            }
        }
        if (insertAt >= 0) {
            sentMessages.add(insertAt, msg)
        } else {
            sentMessages.add(msg)
        }
        val ordered = orderedChatMessages(sentMessages.toList())
        sentMessages.clear()
        sentMessages.addAll(ordered)
    }
    internal fun upsertRealtimeAssistantMessage(uiMessage: Message, runtimeMessage: ChatMessage?) {
        val key = uiMessageKey(uiMessage)
        val messages = _state.value.messages.toMutableList()
        val existingIndex = messages.indexOfFirst { uiMessageKey(it) == key }
        if (existingIndex >= 0) {
            messages[existingIndex] = uiMessage
        } else {
            messages.add(insertIndexForRealtimeMessage(messages, uiMessage), uiMessage)
        }
        _state.value = _state.value.copy(messages = orderedUiMessages(messages))
        if (runtimeMessage != null) {
            upsertRuntimeAssistantMessage(runtimeMessage)
        }
        if (
            _state.value.mode == "normal" &&
            uiMessage.isAssistant() &&
            !uiMessage.isStreaming &&
            !uiMessage.isError
        ) {
            markNormalUsersAcceptedByServer(acceptAllPendingOnServerSignal = true)
            markNormalReplySucceeded("realtime_assistant")
        }
        if (
            existingIndex < 0 &&
            _state.value.mode == "normal" &&
            uiMessage.isAssistant() &&
            !uiMessage.isStreaming &&
            !uiMessage.isError
        ) {
            MessageVibrationHelper.vibrateForMessage(getApplication(), prefs)
        }
    }
    fun applyVoiceMessageUpdate(update: MessageVoiceUpdate) {
        val messageId = update.messageId?.takeIf { it.isNotBlank() } ?: return
        val conversationId = update.conversationId?.takeIf { it.isNotBlank() }
        if (conversationId != null && _state.value.conversationId != null && conversationId != _state.value.conversationId) {
            return
        }
        val patch = update.patch ?: return
        val baseState = patch.toVoiceState()
        viewModelScope.launch {
            val cached = saveVoiceAudioTransferAndAck(
                username = prefs.username,
                characterId = update.characterId,
                conversationId = conversationId,
                messageId = messageId,
                voiceCacheKey = baseState.voiceCacheKey,
                transfer = patch.audioTransfer
            )
            val nextState = if (cached != null) {
                baseState.copy(
                    localFile = cached.localFile,
                    durationMs = cached.durationMs,
                    waveform = baseState.waveform.ifEmpty { cached.waveform }
                )
            } else {
                withContext(Dispatchers.IO) {
                    ChatVoiceCache.hydrate(getApplication(), baseState) ?: baseState
                }
            }
            if (conversationId != null && _state.value.conversationId != null && conversationId != _state.value.conversationId) {
                return@launch
            }
            applyVoiceStateToMessage(messageId, nextState)
        }
    }
    internal fun applyVoiceStateToMessage(messageId: String, voiceState: MessageVoiceState) {
        val messages = _state.value.messages.toMutableList()
        val idx = messages.indexOfFirst { it.messageId == messageId || it.id == messageId }
        if (idx >= 0) {
            messages[idx] = messages[idx].copy(voiceState = voiceState)
            _state.value = _state.value.copy(messages = messages)
        }
        val sentIdx = sentMessages.indexOfFirst { it.messageId == messageId }
        if (sentIdx >= 0) {
            val old = sentMessages[sentIdx]
            sentMessages[sentIdx] = old.copy(
                voiceState = voiceState,
                voiceStatus = voiceState.status,
                voiceId = voiceState.voiceId,
                voiceJobId = voiceState.voiceJobId,
                voiceCacheKey = voiceState.voiceCacheKey,
                ttsText = voiceState.ttsText,
                transcript = voiceState.transcript,
                textFragments = voiceState.textFragments,
                voiceError = voiceState.voiceError,
                voiceDurationMs = voiceState.durationMs,
                voiceLocalFile = voiceState.localFile,
                waveform = voiceState.waveform,
                voiceDebugPlayable = voiceState.debugPlayable
            )
        }
    }
    fun debugGenerateBackendVoiceForLastAssistant() {
        val character = _state.value.character ?: return
        val characterId = character.id?.takeIf { it.isNotBlank() } ?: return
        val conversationId = _state.value.conversationId?.takeIf { it.isNotBlank() } ?: return
        val target = _state.value.messages.lastOrNull {
            it.isAssistant() && !it.isStreaming && it.content.isNotBlank()
        } ?: run {
            _state.value = _state.value.copy(error = "没有可生成语音的角色消息")
            return
        }
        val messageId = target.messageId?.takeIf { it.isNotBlank() } ?: target.id
        val pendingState = MessageVoiceState(
            status = "pending",
            ttsText = target.content,
            transcript = target.content
        )
        applyVoiceStateToMessage(messageId, pendingState)
        viewModelScope.launch {
            val result = chatRepo.synthesizeMessageVoice(
                username = prefs.username,
                characterId = characterId,
                conversationId = conversationId,
                messageId = messageId,
                content = target.content
            )
            result.onSuccess { response ->
                val serverState = response.voiceState ?: pendingState.copy(
                    status = if (response.success) "ready" else "failed",
                    voiceError = response.error
                )
                val cached = saveVoiceAudioTransferAndAck(
                    username = prefs.username,
                    characterId = characterId,
                    conversationId = conversationId,
                    messageId = messageId,
                    voiceCacheKey = serverState.voiceCacheKey,
                    transfer = response.audioTransfer
                )
                val nextState = if (cached != null) {
                    serverState.copy(
                        localFile = cached.localFile,
                        durationMs = cached.durationMs,
                        waveform = serverState.waveform.ifEmpty { cached.waveform }
                    )
                } else {
                    withContext(Dispatchers.IO) {
                        ChatVoiceCache.hydrate(getApplication(), serverState) ?: serverState
                    }
                }
                applyVoiceStateToMessage(messageId, nextState)
            }.onFailure { err ->
                applyVoiceStateToMessage(
                    messageId,
                    pendingState.copy(status = "failed", voiceError = err.toUserMessage("语音生成失败"))
                )
                _state.value = _state.value.copy(error = err.toUserMessage("语音生成失败"))
            }
        }
    }
    internal suspend fun loadNormalConversationHistoryPage(character: Character, conversationIdForRequest: String?) {
        val username = prefs.username
        val characterId = character.id?.takeIf { it.isNotBlank() } ?: return
        val result = chatRepo.loadMessagesBefore(
            username = username,
            characterId = characterId,
            conversationId = conversationIdForRequest,
            beforeSeq = null,
            limit = NORMAL_HISTORY_INITIAL_LIMIT
        )
        if (result == null) {
            if (_state.value.messages.isNotEmpty()) {
                _state.value = _state.value.copy(isBackgroundRefreshing = false)
                return
            }
            val cached = localCache.loadLatestConversation(username, characterId, "normal")
            if (cached != null && cached.messages.isNotEmpty()) {
                val cachedMessages = latestCacheWindowForMode(cached.messages, "normal")
                val cachedCid = cached.conversationId ?: newConversationId()
                val uiMessages = visibleMessagesForUi(
                    cachedMessages,
                    username,
                    characterId,
                    "normal",
                    cachedCid,
                    _state.value.messages
                )
                val runtimeSpeakerFallback = sentMessages.toList()
                val runtimeMessages = runtimeMessagesForClientWithLocalImages(cachedMessages, runtimeSpeakerFallback)
                val mergedUiMessages = mergePendingNormalLocalUsers(uiMessages)
                val mergedRuntimeMessages = mergePendingNormalRuntimeUsers(runtimeMessages)
                sentMessages.clear()
                sentMessages.addAll(mergedRuntimeMessages)
                _state.value = _state.value.copy(
                    messages = mergedUiMessages,
                    conversationId = cachedCid,
                    isLoadingHistory = false,
                    isLoadingMoreHistory = false,
                    isBackgroundRefreshing = false,
                    minLoadedSeq = minSequenceOf(cachedMessages),
                    hasMoreHistory = cached.messages.size > cachedMessages.size,
                    error = "当前使用本地缓存，可到设置检查网络与服务器地址"
                )
                markNormalReplySucceeded("normal_cache_fallback")
            } else {
                _state.value = _state.value.copy(
                    isLoadingHistory = false,
                    isLoadingMoreHistory = false,
                    isBackgroundRefreshing = false,
                    error = null
                )
            }
            return
        }
        val cidNow = _state.value.conversationId
        val superseded = (!_state.value.isLoadingHistory && !_state.value.isBackgroundRefreshing) ||
            (cidNow != null && conversationIdForRequest != null && cidNow != conversationIdForRequest)
        if (superseded) {
            if (_state.value.isBackgroundRefreshing) {
                _state.value = _state.value.copy(isBackgroundRefreshing = false)
            }
            return
        }
        val runtimeSpeakerFallback = sentMessages.toList()
        val serverMessages = preserveChatMessageSpeakers(result.messages, runtimeSpeakerFallback)
        val stableCid = result.conversationId?.takeIf { it.isNotBlank() }
            ?: conversationIdForRequest?.takeIf { it.isNotBlank() }
            ?: newConversationId()
        val serverUiMessages = visibleMessagesForUi(
            serverMessages,
            username,
            characterId,
            "normal",
            stableCid,
            _state.value.messages
        )
        val uiMessages = mergePendingNormalLocalUsers(serverUiMessages)
        val serverRuntimeMessages = runtimeMessagesForClientWithLocalImages(serverMessages, runtimeSpeakerFallback)
        val runtimeMessages = mergePendingNormalRuntimeUsers(serverRuntimeMessages)
        sentMessages.clear()
        sentMessages.addAll(runtimeMessages)
        val currentState = _state.value
        val nextUiMessages = if (currentState.messages.isSameVisibleMessageListAs(uiMessages)) {
            currentState.messages
        } else {
            uiMessages
        }
        _state.value = currentState.copy(
            messages = nextUiMessages,
            conversationId = stableCid,
            isLoadingHistory = false,
            isLoadingMoreHistory = false,
            isBackgroundRefreshing = false,
            minLoadedSeq = minSequenceOf(serverMessages, result.minSeq),
            hasMoreHistory = result.hasMore,
            error = null,
            errorDebug = null
        )
        localCache.saveConversation(
            username = username,
            characterId = characterId,
            mode = "normal",
            conversationId = stableCid,
            messages = runtimeMessages
        )
        markNormalReplySucceeded("normal_history_load")
        val lastTs = serverMessages.lastOrNull()?.timestamp?.takeIf { it > 0L } ?: 0L
        if (lastTs > 0L) {
            val existingTs = prefs.getModeLastChatTime(characterId, "normal")
            if (lastTs > existingTs) prefs.setModeLastChatTime(characterId, "normal", lastTs)
        }
    }
    internal suspend fun loadConversationHistory(character: Character) {
        val username = prefs.username
        val characterId = character.id?.takeIf { it.isNotBlank() } ?: return
        val mode = _state.value.mode
        // 记录发起加载时的对话 ID，用于后续判断结果是否已过期
        val cidAtStart = _state.value.conversationId
        if (mode == "normal") {
            loadNormalConversationHistoryPage(character, cidAtStart)
            return
        }
        val result = charRepo.loadConversationDetail(username, characterId, mode = mode)
        result.fold(
            onSuccess = { detail ->
                // [过期加载守卫] 若 newConversation() 或 switchConversation() 在本次 HTTP 请求期间
                // 抢先执行，则本次加载结果已过期，直接丢弃，避免旧数据覆盖新会话状态。
                // 注意：isBackgroundRefreshing=true 说明缓存已展示、正等待服务端刷新结果，
                // 此时 isLoadingHistory=false 属于正常状态，不应被误判为「过期」。
                val cidNow = _state.value.conversationId
                val superseded = (!_state.value.isLoadingHistory && !_state.value.isBackgroundRefreshing) ||
                    (cidNow != null && cidAtStart != null && cidNow != cidAtStart)
                if (superseded) {
                    DebugLog.d(TAG, "[HistoryDebug] SERVER_RESP stale, discarded")
                    // 若结果被丢弃但仍处于后台刷新状态，需清除刷新标记，避免进度条永远不消失
                    if (_state.value.isBackgroundRefreshing) {
                        _state.value = _state.value.copy(isBackgroundRefreshing = false)
                    }
                    return@fold
                }
                val runtimeSpeakerFallback = sentMessages.toList()
                val serverMessages = preserveChatMessageSpeakers(detail.messages, runtimeSpeakerFallback)
                val usage = detail.usage
                val cid = detail.conversationId
                // 若后端无历史对话（cid == null），立即生成稳定 ID 供本会话所有 triggerAutoSave 复用，
                // 避免每次保存都用 null → "conv_${timestamp}" 产生大量碎片对话记录。
                val stableCid = cid ?: if (mode == "normal") newConversationId() else null
                DebugLog.d(TAG, "[HistoryDebug] loadConversationHistory SUCCESS: serverCid=$cid stableCid=$stableCid msgCount=${serverMessages.size} localMsgCount=${sentMessages.size} isBackgroundRefreshing=${_state.value.isBackgroundRefreshing}")
                // [后台刷新保护] 若当前处于「缓存已展示、等待服务端刷新」状态，且本机正在发送/生成，
                // sentMessages 可能包含服务端尚不知道的新内容，此时不应让服务端数据覆盖本地输入。
                // 没有本地在途消息时，服务端历史是权威数据；角色重置后服务端消息数会变少，也必须覆盖旧缓存。
                // 仅更新 UI 状态中的刷新标记，保持已有消息不变。
                val hasLocalInFlightMessages = _state.value.isStreaming
                if (_state.value.isBackgroundRefreshing && hasLocalInFlightMessages && sentMessages.size > serverMessages.size) {
                    DebugLog.d(TAG, "[HistoryDebug] skip server override: local=${sentMessages.size} server=${serverMessages.size}")
                    // 消息列表不覆盖，但仍应用服务端 score（避免 galgameScore 因缓存无 rawContent 而永久为 null）
                    val svrScore = if (mode == "galgame" || mode == "galgame_lock") detail.score else null
                    // 对于旧缓存消息缺少 rawContent 的情况，从服务端最后一条 AI 消息补全
                    val svrLastAi = serverMessages.lastOrNull { it.role == "assistant" }
                    val localMsgs = _state.value.messages.toMutableList()
                    val localLastAiIdx = localMsgs.indexOfLast { it.isAssistant() }
                    if (svrLastAi != null && localLastAiIdx >= 0) {
                        val localAi = localMsgs[localLastAiIdx]
                        val needsPatch = (localAi.rawContent == null && svrLastAi.rawContent != null)
                        if (needsPatch) {
                            localMsgs[localLastAiIdx] = localAi.copy(
                                rawContent = localAi.rawContent ?: svrLastAi.rawContent,
                                displayContent = localAi.displayContent ?: svrLastAi.displayContent
                            )
                            // 同步更新 sentMessages 中对应条目
                            val sentLastAiIdx = sentMessages.indexOfLast { it.role == "assistant" }
                            if (sentLastAiIdx >= 0) {
                                val sentAi = sentMessages[sentLastAiIdx]
                                sentMessages[sentLastAiIdx] = sentAi.copy(
                                    rawContent = sentAi.rawContent ?: svrLastAi.rawContent,
                                    displayContent = sentAi.displayContent ?: svrLastAi.displayContent
                                )
                            }
                            Log.d("GalDebug", "[skipOverride] patched rawContent from server")
                        }
                    }
                    _state.value = _state.value.copy(
                        isBackgroundRefreshing = false,
                        messages = localMsgs,
                        galgameScore = if (svrScore != null && _state.value.galgameScore == null) svrScore else _state.value.galgameScore,
                        galgameVictoryCelebrationAck = if (mode == "galgame" || mode == "galgame_lock") {
                            detail.victoryCelebrationAck
                        } else _state.value.galgameVictoryCelebrationAck
                    )
                    return@fold
                }
                val uiMessages = visibleMessagesForUi(
                    serverMessages,
                    username,
                    characterId,
                    mode,
                    stableCid,
                    _state.value.messages
                )
                val runtimeMessages = runtimeMessagesForClientWithLocalImages(serverMessages, runtimeSpeakerFallback)
                val nextUiMessagesForMode = if (mode == "normal") {
                    mergePendingNormalLocalUsers(uiMessages)
                } else {
                    uiMessages
                }
                val nextRuntimeMessagesForMode = if (mode == "normal") {
                    mergePendingNormalRuntimeUsers(runtimeMessages)
                } else {
                    runtimeMessages
                }
                sentMessages.clear()
                sentMessages.addAll(nextRuntimeMessagesForMode)
                val newScore = if (mode == "galgame" || mode == "galgame_lock") detail.score else null
                val lastSvrAsstMsg = serverMessages.lastOrNull { it.role == "assistant" }
                Log.d("GalDebug", "[historyServer] mode=$mode serverScore=${detail.score} newScore=$newScore" +
                    " lastMsgRawContentLen=${lastSvrAsstMsg?.rawContent?.length}" +
                    " lastMsgDisplayContentLen=${lastSvrAsstMsg?.displayContent?.length}")
                val normalMinSeq = if (mode == "normal") {
                    serverMessages.minOfOrNull { it.sequenceNumber ?: Int.MAX_VALUE } ?: Int.MAX_VALUE
                } else Int.MAX_VALUE
                val currentState = _state.value
                val nextUiMessages = if (currentState.messages.isSameVisibleMessageListAs(nextUiMessagesForMode)) {
                    currentState.messages
                } else {
                    nextUiMessagesForMode
                }
                _state.value = currentState.copy(
                    messages = nextUiMessages,
                    conversationId = stableCid,
                    isLoadingHistory = false,
                    isBackgroundRefreshing = false,
                    contextUsedTokens = usage?.totalTokens ?: 0,
                    contextLimitTokens = usage?.limitTokens?.takeIf { it > 0 } ?: 64000,
                    galgameScore = newScore,
                    galgameVictoryCelebrationAck = if (mode == "galgame" || mode == "galgame_lock") {
                        detail.victoryCelebrationAck
                    } else false,
                    lockCharVitals = if (mode == "galgame_lock") detail.charVitals ?: _state.value.lockCharVitals else _state.value.lockCharVitals,
                    lockCharMood   = if (mode == "galgame_lock") detail.charMood   ?: _state.value.lockCharMood   else _state.value.lockCharMood,
                    lockOrganFill  = if (mode == "galgame_lock") detail.organFill  ?: _state.value.lockOrganFill  else _state.value.lockOrganFill,
                    lockCharGender = if (mode == "galgame_lock") detail.characterGender?.takeIf { it.isNotBlank() } ?: _state.value.lockCharGender else _state.value.lockCharGender,
                    minLoadedSeq = normalMinSeq,
                    hasMoreHistory = false,
                    error = null,
                    errorDebug = null
                )
                checkAndAutoSummarize()
                localCache.saveConversation(
                    username = username,
                    characterId = characterId,
                    mode = mode,
                    conversationId = cid ?: _state.value.conversationId,
                    messages = if (mode == "normal") nextRuntimeMessagesForMode else serverMessages,
                    lockCharVitals = if (mode == "galgame_lock") detail.charVitals else null,
                    lockCharMood   = if (mode == "galgame_lock") detail.charMood   else null,
                    lockOrganFill  = if (mode == "galgame_lock") detail.organFill  else null,
                    lockCharGender = if (mode == "galgame_lock") detail.characterGender?.takeIf { it.isNotBlank() } else null
                )
                // 加载完服务端对话后立即更新模式专属时间戳，
                // 确保返回角色列表时无需等待 backfillModeTimestamps 异步扫描缓存。
                // 对话/游戏/锁分三种模式均适用。
                if (serverMessages.isNotEmpty()) {
                    val lastTs = serverMessages.lastOrNull()?.timestamp?.takeIf { it > 0L } ?: 0L
                    if (lastTs > 0L) {
                        val existingTs = prefs.getModeLastChatTime(characterId, mode)
                        if (lastTs > existingTs) prefs.setModeLastChatTime(characterId, mode, lastTs)
                    }
                }
                if (mode.startsWith("galgame")) {
                    warmupOtherGalgameModeCache(username, characterId, mode)
                }
            },
            onFailure = { err ->
                if (err is CancellationException) {
                    // 被 launchHistoryLoad / reloadConversation 取消时，不修改状态——
                    // 此时新的加载 Job 已启动并设置了自己的状态（如 isBackgroundRefreshing），
                    // 若在此处无条件清空会把新 Job 的标记位覆盖掉，导致服务端响应被误判为过期而丢弃。
                    return@fold
                }
                DebugLog.w(TAG, "Load history failed: ${err.message}", err)
                // 已通过本地缓存展示了消息（isBackgroundRefreshing=true）→ 静默失败，仅清除刷新标记
                if (_state.value.messages.isNotEmpty()) {
                    DebugLog.d(TAG, "[Cache] 后台刷新失败，保留已展示的本地缓存: ${err.message}")
                    _state.value = _state.value.copy(isBackgroundRefreshing = false)
                    return@fold
                }
                // 没有缓存展示 → 降级到本地缓存（旧兜底逻辑，首次安装、缓存被清等极端情况）
                val cached = localCache.loadLatestConversation(username, characterId, mode)
                if (cached != null && cached.messages.isNotEmpty()) {
                    val runtimeSpeakerFallback = sentMessages.toList()
                    val cachedMessages = preserveChatMessageSpeakers(cached.messages, runtimeSpeakerFallback)
                    val uiMessages = visibleMessagesForUi(
                        cachedMessages,
                        username,
                        characterId,
                        mode,
                        cached.conversationId,
                        _state.value.messages
                    )
                    val runtimeMessages = runtimeMessagesForClientWithLocalImages(cachedMessages, runtimeSpeakerFallback)
                    val nextUiMessagesForMode = if (mode == "normal") {
                        mergePendingNormalLocalUsers(uiMessages)
                    } else {
                        uiMessages
                    }
                    val nextRuntimeMessagesForMode = if (mode == "normal") {
                        mergePendingNormalRuntimeUsers(runtimeMessages)
                    } else {
                        runtimeMessages
                    }
                    sentMessages.clear()
                    sentMessages.addAll(nextRuntimeMessagesForMode)
                    val cachedCid = cached.conversationId
                        ?: if (mode == "normal") newConversationId() else null
                    _state.value = _state.value.copy(
                        messages = nextUiMessagesForMode,
                        conversationId = cachedCid,
                        isLoadingHistory = false,
                        isBackgroundRefreshing = false,
                        error = "当前使用本地缓存，可到设置检查网络与服务器地址",
                        galgameScore = if (mode == "galgame" || mode == "galgame_lock") parseScoreFromLastMessage(cachedMessages) else null,
                        galgameVictoryCelebrationAck = false,
                        errorDebug = err.message,
                        lockCharVitals = if (mode == "galgame_lock") cached.lockCharVitals ?: _state.value.lockCharVitals else _state.value.lockCharVitals,
                        lockCharMood   = if (mode == "galgame_lock") cached.lockCharMood   ?: _state.value.lockCharMood   else _state.value.lockCharMood,
                        lockOrganFill  = if (mode == "galgame_lock") cached.lockOrganFill  ?: _state.value.lockOrganFill  else _state.value.lockOrganFill,
                        lockCharGender = if (mode == "galgame_lock") cached.lockCharGender?.takeIf { it.isNotBlank() } ?: _state.value.lockCharGender else _state.value.lockCharGender
                    )
                    val cachedLastTs = cached.messages.lastOrNull()?.timestamp?.takeIf { it > 0L }
                        ?: cached.updatedAt.takeIf { it > 0L }
                    if (cachedLastTs != null && cachedLastTs > 0L) {
                        val existingTs = prefs.getModeLastChatTime(characterId, mode)
                        if (cachedLastTs > existingTs) prefs.setModeLastChatTime(characterId, mode, cachedLastTs)
                    }
                } else {
                    _state.value = _state.value.copy(isLoadingHistory = false, isBackgroundRefreshing = false, errorDebug = err.message)
                }
            }
        )
    }
    /** 从最后一条助手消息的 rawContent 解析 score.current，用于缓存恢复时补 API score 的空缺 */
    internal fun parseScoreFromLastMessage(messages: List<ChatMessage>): Int? {
        val last = messages.lastOrNull { it.role == "assistant" } ?: return null
        val raw = last.rawContent ?: return null
        return try {
            val json = org.json.JSONObject(raw)
            val scoreObj = json.optJSONObject("score") ?: return null
            scoreObj.optInt("current", -1).takeIf { it in 0..100 }
        } catch (e: Exception) {
            DebugLog.w(TAG, "parseScoreFromLastMessage: ${e.message}", e)
            null
        }
    }
    internal fun launchHistoryLoad(character: Character) {
        val username = prefs.username
        val characterId = character.id?.takeIf { it.isNotBlank() } ?: return
        historyLoadJob?.cancel()
        historyLoadJob = viewModelScope.launch {
            // ① 先从本地缓存瞬时展示，让用户无需等待网络即可看到上次的对话
            val cached = withContext(Dispatchers.IO) {
                localCache.loadLatestConversation(username, characterId, _state.value.mode)
            }
            DebugLog.d(TAG, "[HistoryDebug] launchHistoryLoad CACHE: msgCount=${cached?.messages?.size ?: 0}")
            if (cached != null && cached.messages.isNotEmpty() && _state.value.isLoadingHistory) {
                val mode = _state.value.mode
                val runtimeSpeakerFallback = sentMessages.toList()
                val cachedMessages = preserveChatMessageSpeakers(
                    latestCacheWindowForMode(cached.messages, mode),
                    runtimeSpeakerFallback
                )
                val uiMessages = visibleMessagesForUi(
                    cachedMessages,
                    username,
                    characterId,
                    mode,
                    cached.conversationId,
                    _state.value.messages
                )
                val runtimeMessages = runtimeMessagesForClientWithLocalImages(cachedMessages, runtimeSpeakerFallback)
                val nextUiMessagesForMode = if (mode == "normal") {
                    mergePendingNormalLocalUsers(uiMessages)
                } else {
                    uiMessages
                }
                val nextRuntimeMessagesForMode = if (mode == "normal") {
                    mergePendingNormalRuntimeUsers(runtimeMessages)
                } else {
                    runtimeMessages
                }
                sentMessages.clear()
                sentMessages.addAll(nextRuntimeMessagesForMode)
                val cachedCid = cached.conversationId ?: if (mode == "normal") newConversationId() else null
                val cachedScore = if (mode == "galgame" || mode == "galgame_lock") parseScoreFromLastMessage(cachedMessages) else null
                val lastAsstMsg = cachedMessages.lastOrNull { it.role == "assistant" }
                Log.d("GalDebug", "[historyCache] mode=$mode cachedScore=$cachedScore" +
                    " lastMsgRawContentLen=${lastAsstMsg?.rawContent?.length}" +
                    " lastMsgDisplayContentLen=${lastAsstMsg?.displayContent?.length}")
                _state.value = _state.value.copy(
                    messages = nextUiMessagesForMode,
                    conversationId = cachedCid,
                    isLoadingHistory = false,
                    isLoadingMoreHistory = false,
                    isBackgroundRefreshing = true,
                    galgameScore = cachedScore,
                    galgameVictoryCelebrationAck = false,
                    minLoadedSeq = if (mode == "normal") minSequenceOf(cachedMessages) else Int.MAX_VALUE,
                    hasMoreHistory = mode == "normal" && cached.messages.size > cachedMessages.size,
                    lockCharVitals = if (mode == "galgame_lock") cached.lockCharVitals ?: _state.value.lockCharVitals else _state.value.lockCharVitals,
                    lockCharMood   = if (mode == "galgame_lock") cached.lockCharMood   ?: _state.value.lockCharMood   else _state.value.lockCharMood,
                    lockOrganFill  = if (mode == "galgame_lock") cached.lockOrganFill  ?: _state.value.lockOrganFill  else _state.value.lockOrganFill,
                    lockCharGender = if (mode == "galgame_lock") cached.lockCharGender?.takeIf { it.isNotBlank() } ?: _state.value.lockCharGender else _state.value.lockCharGender,
                    error = null,
                    errorDebug = null
                )
                // 更新模式时间戳（与服务端成功路径对齐，确保角色列表时间顺序正确）
                val cachedLastTs = cachedMessages.lastOrNull()?.timestamp?.takeIf { it > 0L }
                    ?: cached.updatedAt.takeIf { it > 0L }
                if (cachedLastTs != null) {
                    val existingTs = prefs.getModeLastChatTime(characterId, mode)
                    if (cachedLastTs > existingTs) prefs.setModeLastChatTime(characterId, mode, cachedLastTs)
                }
                DebugLog.d(TAG, "[Cache] local cache displayed: ${uiMessages.size} messages, refreshing in background")
            }
            // ② 后台从服务端静默刷新（有缓存时用户无感知，无缓存时等结果再展示）
            loadConversationHistory(character)
        }
    }

    fun updateInput(text: String) {
        _state.value = _state.value.copy(inputText = text)
    }

    internal fun messageQuoteContent(message: Message): String {
        val raw = when {
            message.isAssistant() && !message.displayContent.isNullOrBlank() -> stripHtml(message.displayContent)
            else -> parseMessageContent(message.content).mainContent
        }.trim()
        return raw.ifBlank {
            val app = getApplication<Application>()
            val media = if (message.isUser()) {
                splitUserMessageMedia(message.content, app)
            } else {
                splitMessageMedia(message.content, app)
            }
            when {
                media.imageUrls.isNotEmpty() || media.text.contains("【图片】") -> "[图片]"
                message.attachments.orEmpty().any { it.type == "sticker" || it.type == "emoji_asset" } -> "[表情]"
                message.attachments.orEmpty().isNotEmpty() -> "[附件]"
                else -> message.content.trim()
            }
        }.replace(Regex("\\s+"), " ").take(240)
    }

    fun quoteMessage(message: Message) {
        if (_state.value.mode != "normal") return
        val character = _state.value.character
        val quotedSpeakerCharacterId = if (message.isAssistant()) {
            message.speakerCharacterId?.takeIf { it.isNotBlank() }
                ?: character?.id?.takeIf { it.isNotBlank() }
        } else {
            null
        }
        val quotedSpeakerName = if (message.isAssistant()) {
            message.speakerName?.takeIf { it.isNotBlank() }
                ?: character?.displayName()?.takeIf { it.isNotBlank() }
        } else {
            null
        }
        val sender = if (message.isUser()) {
            prefs.nickname.ifBlank { prefs.username }.ifBlank { "我" }
        } else {
            quotedSpeakerName ?: "AI"
        }
        val content = messageQuoteContent(message)
        if (content.isBlank()) return
        _state.value = _state.value.copy(
            quotedMessage = QuotedMessage(
                messageId = message.messageId ?: message.id,
                role = message.role,
                sender = sender,
                content = content,
                timestamp = message.timestamp,
                speakerCharacterId = quotedSpeakerCharacterId,
                speakerName = quotedSpeakerName,
                speakerAvatar = if (message.isAssistant()) {
                    message.speakerAvatar?.takeIf { it.isNotBlank() }
                        ?: character?.avatar?.takeIf { it.isNotBlank() }
                } else {
                    null
                }
            )
        )
    }

    fun clearQuotedMessage() {
        _state.value = _state.value.copy(quotedMessage = null)
    }

    fun sendQuickMessage(text: String) {
        val content = text.trim()
        if (content.isBlank()) return
        if (_state.value.mode.startsWith("galgame")) return
        if (_state.value.mode != "normal" && (_state.value.isStreaming || _state.value.quotaExceeded)) return
        _state.value = _state.value.copy(inputText = content)
        sendMessage()
    }

    fun loadQuickMessages(force: Boolean = false) {
        val username = prefs.username.takeIf { it.isNotBlank() } ?: return
        if (_state.value.isLoadingQuickMessages && !force) return
        val cached = localCache.loadQuickMessages(username)
        if (cached.isNotEmpty() && _state.value.quickMessages.isEmpty()) {
            _state.value = _state.value.copy(quickMessages = cached)
        }
        _state.value = _state.value.copy(isLoadingQuickMessages = true)
        viewModelScope.launch {
            chatRepo.loadQuickMessages(username)
                .onSuccess { messages ->
                    localCache.saveQuickMessages(username, messages)
                    _state.value = _state.value.copy(
                        quickMessages = messages,
                        isLoadingQuickMessages = false
                    )
                }
                .onFailure { e ->
                    DebugLog.w(TAG, "loadQuickMessages failed: ${e.message}", e)
                    val fallback = localCache.loadQuickMessages(username)
                    _state.value = _state.value.copy(
                        quickMessages = fallback.ifEmpty { _state.value.quickMessages },
                        isLoadingQuickMessages = false
                    )
                }
        }
    }

    fun addQuickMessage(title: String, content: String) {
        val username = prefs.username.takeIf { it.isNotBlank() } ?: return
        val body = content.trim()
        if (body.isBlank()) return
        viewModelScope.launch {
            chatRepo.addQuickMessage(username, title.trim(), body)
                .onSuccess { added ->
                    val next = (_state.value.quickMessages + added).sortedWith(
                        compareBy<QuickMessage> { it.sortOrder }.thenBy { it.id }
                    )
                    localCache.saveQuickMessages(username, next)
                    _state.value = _state.value.copy(
                        quickMessages = next
                    )
                }
                .onFailure { e ->
                    DebugLog.w(TAG, "addQuickMessage failed: ${e.message}", e)
                    _state.value = _state.value.copy(error = e.message ?: "添加快捷消息失败")
                }
        }
    }

    fun updateQuickMessage(message: QuickMessage) {
        val username = prefs.username.takeIf { it.isNotBlank() } ?: return
        if (message.content.isBlank() || message.id <= 0) return
        viewModelScope.launch {
            chatRepo.updateQuickMessage(message, username)
                .onSuccess {
                    val next = _state.value.quickMessages.map {
                        if (it.id == message.id) message else it
                    }.sortedWith(compareBy<QuickMessage> { it.sortOrder }.thenBy { it.id })
                    localCache.saveQuickMessages(username, next)
                    _state.value = _state.value.copy(
                        quickMessages = next
                    )
                }
                .onFailure { e ->
                    DebugLog.w(TAG, "updateQuickMessage failed: ${e.message}", e)
                    _state.value = _state.value.copy(error = e.message ?: "更新快捷消息失败")
                }
        }
    }

    fun deleteQuickMessage(messageId: Int) {
        val username = prefs.username.takeIf { it.isNotBlank() } ?: return
        if (messageId <= 0) return
        viewModelScope.launch {
            chatRepo.deleteQuickMessage(username, messageId)
                .onSuccess {
                    val next = _state.value.quickMessages.filterNot { it.id == messageId }
                    localCache.saveQuickMessages(username, next)
                    _state.value = _state.value.copy(
                        quickMessages = next
                    )
                }
                .onFailure { e ->
                    DebugLog.w(TAG, "deleteQuickMessage failed: ${e.message}", e)
                    _state.value = _state.value.copy(error = e.message ?: "删除快捷消息失败")
                }
        }
    }

    /**
     * 将本地压缩后的 JPEG 上传至 [POST /api/chat_images]，成功返回仅供当次处理的临时短 URL。
     */
    override fun onCleared() {
        super.onCleared()
        prefs.unregisterChangeListener(prefsChangeListener)
        streamJob?.cancel()
        autoSaveJob?.cancel()
        historyLoadJob?.cancel()
        conversationListJob?.cancel()
        switchConversationJob?.cancel()
    }
}
