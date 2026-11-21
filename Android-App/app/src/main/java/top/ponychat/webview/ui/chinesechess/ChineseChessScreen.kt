package top.ponychat.webview.ui.chinesechess
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Deferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withPermit
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import top.ponychat.webview.data.local.CachedVoiceAudio
import top.ponychat.webview.data.local.ChatVoiceCache
import top.ponychat.webview.data.model.XiangqiEntryCard
import top.ponychat.webview.data.model.XiangqiExecuteRequest
import top.ponychat.webview.data.model.XiangqiMemoryCommitRequest
import top.ponychat.webview.data.model.XiangqiPrepareRequest
import top.ponychat.webview.data.repo.ChatRepository
import top.ponychat.webview.data.repo.MinigameRepository
import top.ponychat.webview.ui.common.PonyTopBar
import top.ponychat.webview.ui.common.PonyTopBarBackButton
import top.ponychat.webview.util.ClientContextHelper
import top.ponychat.webview.util.DebugLog
import java.util.UUID
import kotlin.math.min
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun ChineseChessScreen(
    characterName: String,
    characterAvatar: String,
    characterSupportsVoice: Boolean,
    username: String,
    characterId: String,
    conversationId: String,
    userName: String,
    userAvatar: String,
    apiBase: String,
    minigameRepository: MinigameRepository,
    chatRepository: ChatRepository,
    onBack: () -> Unit
) {
    val localContext = LocalContext.current
    var game by remember { mutableStateOf(GameState()) }
    val scope = rememberCoroutineScope()
    val aiEnabled = true
    var gameId by remember { mutableStateOf(UUID.randomUUID().toString()) }
    var playerSide by remember { mutableStateOf(Side.Red) }
    var boardPerspective by remember { mutableStateOf(Side.Red) }
    var aiThinking by remember { mutableStateOf(false) }
    var characterMoveThinking by remember { mutableStateOf(false) }
    var userInput by remember { mutableStateOf("") }
    var messageComposerExpanded by remember { mutableStateOf(false) }
    var voiceReplyEnabled by remember { mutableStateOf(false) }
    var voiceUnavailableForGame by remember { mutableStateOf(false) }
    var characterMessage by remember { mutableStateOf("") }
    var characterMessageVersion by remember { mutableStateOf(0) }
    var characterPresentationJob by remember { mutableStateOf<Job?>(null) }
    var characterSegmentActive by remember { mutableStateOf(false) }
    var characterStopAfterCurrentVersion by remember { mutableStateOf<Int?>(null) }
    var setupRunId by remember { mutableStateOf(0) }
    var setupDone by remember { mutableStateOf(false) }
    var prepareCompleted by remember { mutableStateOf(false) }
    var setupVisibleCells by remember { mutableStateOf<Set<Cell>>(emptySet()) }
    var setupAnimationEnabled by remember { mutableStateOf(true) }
    var setupAnimationSkipped by remember { mutableStateOf(false) }
    var entryCard by remember { mutableStateOf<XiangqiEntryCard?>(null) }
    var fixedDisplayedPowerTier by remember { mutableStateOf<ChessPowerTier?>(null) }
    var openingStepCompleted by remember { mutableStateOf(false) }
    var moveHistory by remember { mutableStateOf<List<Map<String, Any?>>>(emptyList()) }
    var dialogueHistory by remember { mutableStateOf<List<Map<String, Any?>>>(emptyList()) }
    var pendingUserInstruction by remember { mutableStateOf("") }
    var pendingUndoRequest by remember { mutableStateOf<XiangqiPendingUndoRequest?>(null) }
    var userUndoRequestCount by remember { mutableStateOf(0) }
    var recentlyUndoneUserMoves by remember { mutableStateOf<List<Map<String, Any?>>>(emptyList()) }
    var recentlyUndoneCharacterMoves by remember { mutableStateOf<List<Map<String, Any?>>>(emptyList()) }
    var completedGameRecords by remember { mutableStateOf<List<Map<String, Any?>>>(emptyList()) }
    val committedMemoryGameIds = remember { mutableSetOf<String>() }
    var dismissedGameOverDialogGameId by remember { mutableStateOf<String?>(null) }
    val powerTier = entryCard.powerTier()
    val displayedPowerTier = fixedDisplayedPowerTier ?: entryCard?.powerTier()
    val difficulty = powerTier.engineDifficulty
    val mistakeRate = powerTier.engineMistakeRate
    val sfxPlayer = remember { XiangqiSfxPlayer(localContext.applicationContext) }
    val voicePlayer = remember { XiangqiVoicePlaybackController() }
    val eleEyeSession = remember { EleEyeEngine.openSession(localContext.applicationContext) }
    LaunchedEffect(Unit) { ClientContextHelper.refreshLocationAndWeather(localContext.applicationContext) }
    LaunchedEffect(Unit) { withContext(Dispatchers.IO) { eleEyeSession.warmUp() } }
    fun currentGameMemoryRecord(reason: String): Map<String, Any?>? {
        if (moveHistory.isEmpty() && dialogueHistory.isEmpty() && game.winner == null) return null
        return xiangqiBuildGameMemoryRecord(
            gameId = gameId,
            game = game,
            playerSide = playerSide,
            moveHistory = moveHistory,
            dialogueHistory = dialogueHistory,
            completedReason = reason
        )
    }
    fun commitXiangqiMemoryRecord(record: Map<String, Any?>, reason: String) {
        if (username.isBlank() || characterId.isBlank() || conversationId.isBlank()) return
        val recordId = record["game_id"]?.toString()?.takeIf { it.isNotBlank() } ?: return
        if (!committedMemoryGameIds.add(recordId)) return
        val appContext = localContext.applicationContext
        CoroutineScope(Dispatchers.IO).launch {
            val request = XiangqiMemoryCommitRequest(
                username = username,
                characterId = characterId,
                conversationId = conversationId,
                characterName = characterName,
                userName = userName,
                reason = reason,
                gameRecord = record,
                clientContext = ClientContextHelper.buildContext(appContext)
            )
            minigameRepository.commitXiangqiMemory(request).onFailure { error ->
                DebugLog.w("ChineseChess", "象棋记忆写回失败: ${error.message}", error)
            }
        }
    }
    DisposableEffect(Unit) {
        onDispose {
            currentGameMemoryRecord("exit")?.let { record ->
                commitXiangqiMemoryRecord(record, "exit")
            }
            characterPresentationJob?.cancel()
            voicePlayer.stop()
            sfxPlayer.release()
            eleEyeSession.close()
        }
    }
    fun cancelCharacterPresentation(clear: Boolean = true) {
        characterPresentationJob?.cancel()
        characterPresentationJob = null
        characterSegmentActive = false
        characterStopAfterCurrentVersion = null
        voicePlayer.stop()
        characterMessageVersion += 1
        if (clear) {
            characterMessage = ""
        }
    }
    fun setCharacterMessageNow(text: String) {
        cancelCharacterPresentation(clear = false)
        characterMessage = text
    }
    fun playMoveSfx(before: GameState, after: GameState, move: Move) {
        val isCapture = before.board.pieceAt(move.to) != null
        val checkedSide = after.turn.takeIf { after.winner == null && after.board.isInCheck(it) }
        sfxPlayer.playMove(
            isCapture = isCapture,
            givesCheck = checkedSide != null,
            playerInCheck = checkedSide == playerSide
        )
        after.winner?.let { winner ->
            sfxPlayer.playGameOver(
                playerWon = winner == playerSide,
                delayMillis = if (isCapture) 760L else 520L
            )
        }
    }
    fun finishCurrentCharacterSegmentThenStopQueue() {
        val job = characterPresentationJob
        if (job?.isActive == true && characterSegmentActive && characterMessage.isNotBlank()) {
            characterStopAfterCurrentVersion = characterMessageVersion
        } else {
            cancelCharacterPresentation(clear = true)
        }
    }
    suspend fun waitForCharacterPresentationStopAfterCurrent() {
        val version = characterStopAfterCurrentVersion ?: return
        while (characterMessageVersion == version && characterPresentationJob?.isActive == true) {
            delay(40L)
        }
    }
    suspend fun waitForCharacterPresentationIdle() {
        while (characterPresentationJob?.isActive == true) {
            delay(40L)
        }
    }
    fun disableVoiceForCurrentGame(reason: String) {
        DebugLog.w("ChineseChess", "本局象棋语音已降级为纯文本: $reason")
        voiceUnavailableForGame = true
        voiceReplyEnabled = false
        voicePlayer.stop()
    }
    fun canUseXiangqiVoice(): Boolean =
        voiceReplyEnabled &&
            characterSupportsVoice &&
            !voiceUnavailableForGame &&
            characterId.isNotBlank()
    suspend fun synthesizeXiangqiVoiceSegment(
        text: String,
        voiceSentence: Map<String, String>?,
        version: Int,
        index: Int
    ): CachedVoiceAudio? {
        if (username.isBlank() || characterId.isBlank()) return null
        val messageId = "xiangqi_${gameId.take(8)}_${version}_${index}_${UUID.randomUUID().toString().take(8)}"
        val requestConversationId = conversationId.ifBlank { "xiangqi-$gameId" }
        val response = withTimeoutOrNull(XIANGQI_VOICE_TIMEOUT_MS) {
            chatRepository.synthesizeMessageVoice(
                username = username,
                characterId = characterId,
                conversationId = requestConversationId,
                messageId = messageId,
                content = text,
                voiceSentences = listOfNotNull(voiceSentence)
            ).getOrElse { error ->
                DebugLog.w("ChineseChess", "象棋语音生成失败: ${error.message}", error)
                null
            }
        } ?: return null
        if (!response.success) {
            DebugLog.w("ChineseChess", "象棋语音生成返回失败: ${response.error ?: response.message ?: "unknown"}")
            return null
        }
        val cacheKey = response.voiceState?.voiceCacheKey?.takeIf { it.isNotBlank() } ?: return null
        val cached = withContext(Dispatchers.IO) {
            ChatVoiceCache.save(localContext.applicationContext, cacheKey, response.audioTransfer)
                ?: ChatVoiceCache.find(localContext.applicationContext, cacheKey)
        } ?: return null
        if (conversationId.isNotBlank()) {
            chatRepository.ackMessageVoiceAudio(
                username = username,
                characterId = characterId,
                conversationId = conversationId,
                messageId = messageId,
                voiceCacheKey = cacheKey
            ).onFailure { error ->
                DebugLog.w("ChineseChess", "象棋语音缓存 ACK 失败: ${error.message}", error)
            }
        }
        return cached
    }
    fun displaySegmentsWithVoiceSentences(
        segments: List<String>,
        voiceSentences: List<Map<String, String>>
    ): Pair<List<String>, List<Map<String, String>>> {
        val displaySegments = mutableListOf<String>()
        val displayVoiceSentences = mutableListOf<Map<String, String>>()
        segments.forEachIndexed { index, rawText ->
            val text = rawText.trim()
            if (text.isBlank()) return@forEachIndexed
            val emotionPrompt = voiceSentences.getOrNull(index)
                ?.get("emotion_prompt")
                ?.trim()
                .orEmpty()
            xiangqiMessagePanelSegments(text).forEach { panelText ->
                displaySegments += panelText
                displayVoiceSentences += mapOf(
                    "text" to panelText,
                    "emotion_prompt" to emotionPrompt
                )
            }
        }
        return displaySegments to displayVoiceSentences
    }
    fun prepareXiangqiVoiceBatch(
        segments: List<String>,
        voiceSentences: List<Map<String, String>>
    ): XiangqiPreparedVoiceBatch? {
        if (!canUseXiangqiVoice()) return null
        val (displaySegments, displayVoiceSentences) = displaySegmentsWithVoiceSentences(segments, voiceSentences)
        if (displaySegments.isEmpty()) return null
        val version = characterMessageVersion
        val synthesisLimiter = Semaphore(XIANGQI_VOICE_MAX_PARALLEL_SYNTHESIS)
        val audioRequests = displaySegments.mapIndexed { index, text ->
            scope.async {
                synthesisLimiter.withPermit {
                    synthesizeXiangqiVoiceSegment(
                        text = text,
                        voiceSentence = displayVoiceSentences.getOrNull(index),
                        version = version,
                        index = index
                    )
                }
            }
        }
        DebugLog.d(
            "ChineseChess",
            "象棋语音整轮预生成: version=$version scheduled=${audioRequests.size}"
        )
        return XiangqiPreparedVoiceBatch(
            segments = displaySegments,
            voiceSentences = displayVoiceSentences,
            audioRequests = audioRequests
        )
    }
    suspend fun waitSegmentDisplay(version: Int, baseMs: Long, finalExtraMs: Long): Boolean {
        var elapsed = 0L
        while (elapsed < baseMs && characterMessageVersion == version) {
            val step = min(80L, baseMs - elapsed)
            delay(step)
            elapsed += step
        }
        if (characterMessageVersion != version) return false
        if (characterStopAfterCurrentVersion == version) return false
        var extraElapsed = 0L
        while (extraElapsed < finalExtraMs && characterMessageVersion == version) {
            if (characterStopAfterCurrentVersion == version) return false
            val step = min(80L, finalExtraMs - extraElapsed)
            delay(step)
            extraElapsed += step
        }
        return characterMessageVersion == version
    }
    suspend fun showTextSegments(
        version: Int,
        segments: List<String>,
        startIndex: Int = 0,
        firstAlreadyVisible: Boolean = false,
        finalHoldMs: Long = XIANGQI_FINAL_TEXT_HOLD_MS
    ) {
        for (index in startIndex until segments.size) {
            if (characterMessageVersion != version) return
            if (characterStopAfterCurrentVersion == version) {
                characterMessage = ""
                return
            }
            val text = segments[index]
            characterSegmentActive = true
            if (!(firstAlreadyVisible && index == startIndex)) {
                characterMessage = text
            }
            val completed = waitSegmentDisplay(
                version = version,
                baseMs = followupDelayMillis(text),
                finalExtraMs = if (index == segments.lastIndex) finalHoldMs else 0L
            )
            characterSegmentActive = false
            if (!completed || characterStopAfterCurrentVersion == version) {
                if (characterMessageVersion == version) characterMessage = ""
                return
            }
        }
        if (characterMessageVersion == version) {
            characterMessage = ""
        }
    }
    suspend fun showVoiceSegments(
        version: Int,
        segments: List<String>,
        voiceSentences: List<Map<String, String>>,
        finalHoldMs: Long = XIANGQI_FINAL_TEXT_HOLD_MS,
        preparedAudioRequests: List<Deferred<CachedVoiceAudio?>> = emptyList()
    ) = coroutineScope {
        val synthesisLimiter = Semaphore(XIANGQI_VOICE_MAX_PARALLEL_SYNTHESIS)
        val audioRequests = MutableList<Deferred<CachedVoiceAudio?>?>(segments.size) { index ->
            preparedAudioRequests.getOrNull(index)
        }
        fun synthesizeSegment(index: Int): Deferred<CachedVoiceAudio?> = async {
            synthesisLimiter.withPermit {
                synthesizeXiangqiVoiceSegment(
                    text = segments[index],
                    voiceSentence = voiceSentences.getOrNull(index),
                    version = version,
                    index = index
                )
            }
        }
        fun cancelVoiceSyntheses() {
            audioRequests.forEach { it?.cancel() }
        }
        fun scheduleAllVoiceSyntheses() {
            if (!voiceReplyEnabled || characterMessageVersion != version) return
            var scheduledCount = 0
            for (index in segments.indices) {
                if (audioRequests[index] == null) {
                    audioRequests[index] = synthesizeSegment(index)
                    scheduledCount += 1
                }
            }
            if (scheduledCount > 0 || preparedAudioRequests.isNotEmpty()) {
                DebugLog.d(
                    "ChineseChess",
                    "象棋语音整轮合成队列: version=$version prepared=${preparedAudioRequests.size.coerceAtMost(segments.size)} scheduled=$scheduledCount total=${segments.size}"
                )
            }
        }
        scheduleAllVoiceSyntheses()
        for ((index, text) in segments.withIndex()) {
            if (characterMessageVersion != version) {
                cancelVoiceSyntheses()
                return@coroutineScope
            }
            if (characterStopAfterCurrentVersion == version) {
                cancelVoiceSyntheses()
                characterMessage = ""
                return@coroutineScope
            }
            if (!voiceReplyEnabled) {
                cancelVoiceSyntheses()
                showTextSegments(
                    version = version,
                    segments = segments,
                    startIndex = index,
                    firstAlreadyVisible = false,
                    finalHoldMs = finalHoldMs
                )
                return@coroutineScope
            }
            val audioRequest = audioRequests[index] ?: synthesizeSegment(index).also {
                audioRequests[index] = it
            }
            val audio = audioRequest.await()
            if (characterMessageVersion != version) {
                cancelVoiceSyntheses()
                return@coroutineScope
            }
            if (!voiceReplyEnabled) {
                cancelVoiceSyntheses()
                showTextSegments(
                    version = version,
                    segments = segments,
                    startIndex = index,
                    firstAlreadyVisible = false,
                    finalHoldMs = finalHoldMs
                )
                return@coroutineScope
            }
            if (audio == null) {
                disableVoiceForCurrentGame("voice_prepare_timeout_or_failed")
                cancelVoiceSyntheses()
                showTextSegments(
                    version = version,
                    segments = segments,
                    startIndex = index,
                    firstAlreadyVisible = false,
                    finalHoldMs = finalHoldMs
                )
                return@coroutineScope
            }
            characterSegmentActive = true
            characterMessage = text
            val played = voicePlayer.play(audio)
            characterSegmentActive = false
            if (characterMessageVersion != version) {
                cancelVoiceSyntheses()
                return@coroutineScope
            }
            if (characterStopAfterCurrentVersion == version) {
                cancelVoiceSyntheses()
                characterSegmentActive = false
                characterMessage = ""
                return@coroutineScope
            }
            if (!played) {
                if (voiceReplyEnabled) {
                    disableVoiceForCurrentGame("voice_playback_failed")
                }
                showTextSegments(
                    version = version,
                    segments = segments,
                    startIndex = index,
                    firstAlreadyVisible = true,
                    finalHoldMs = finalHoldMs
                )
                cancelVoiceSyntheses()
                return@coroutineScope
            }
            if (characterMessageVersion == version) {
                characterMessage = ""
            }
        }
        if (finalHoldMs > 0L) {
            delay(finalHoldMs)
        }
        if (characterMessageVersion == version) {
            characterMessage = ""
        }
        cancelVoiceSyntheses()
    }
    fun showCharacterSegments(
        segments: List<String>,
        voiceSentences: List<Map<String, String>> = emptyList(),
        preparedVoiceBatch: XiangqiPreparedVoiceBatch? = null
    ) {
        val cleanSegments = preparedVoiceBatch?.segments
        val cleanVoiceSentences = preparedVoiceBatch?.voiceSentences
        val (displaySegments, displayVoiceSentences) = if (cleanSegments != null && cleanVoiceSentences != null) {
            cleanSegments to cleanVoiceSentences
        } else {
            displaySegmentsWithVoiceSentences(segments, voiceSentences)
        }
        cancelCharacterPresentation(clear = true)
        if (displaySegments.isEmpty()) {
            preparedVoiceBatch?.cancel()
            return
        }
        val version = characterMessageVersion
        characterPresentationJob = scope.launch {
            try {
                val canUseVoice = canUseXiangqiVoice()
                if (canUseVoice) {
                    showVoiceSegments(
                        version = version,
                        segments = displaySegments,
                        voiceSentences = displayVoiceSentences,
                        preparedAudioRequests = preparedVoiceBatch?.audioRequests.orEmpty()
                    )
                } else {
                    preparedVoiceBatch?.cancel()
                    showTextSegments(version, displaySegments)
                }
            } finally {
                preparedVoiceBatch?.cancel()
                characterSegmentActive = false
                if (characterStopAfterCurrentVersion == version) {
                    characterStopAfterCurrentVersion = null
                }
                if (characterMessageVersion == version) {
                    characterPresentationJob = null
                }
            }
        }
    }
    suspend fun showCharacterSegmentsNow(
        segments: List<String>,
        voiceSentences: List<Map<String, String>> = emptyList(),
        finalHoldMs: Long = XIANGQI_FINAL_TEXT_HOLD_MS,
        preparedVoiceBatch: XiangqiPreparedVoiceBatch? = null
    ): Boolean {
        val cleanSegments = preparedVoiceBatch?.segments
        val cleanVoiceSentences = preparedVoiceBatch?.voiceSentences
        val (displaySegments, displayVoiceSentences) = if (cleanSegments != null && cleanVoiceSentences != null) {
            cleanSegments to cleanVoiceSentences
        } else {
            displaySegmentsWithVoiceSentences(segments, voiceSentences)
        }
        if (displaySegments.isEmpty()) {
            preparedVoiceBatch?.cancel()
            return true
        }
        cancelCharacterPresentation(clear = true)
        val version = characterMessageVersion
        return try {
            val canUseVoice = canUseXiangqiVoice()
            if (canUseVoice) {
                showVoiceSegments(
                    version = version,
                    segments = displaySegments,
                    voiceSentences = displayVoiceSentences,
                    finalHoldMs = finalHoldMs,
                    preparedAudioRequests = preparedVoiceBatch?.audioRequests.orEmpty()
                )
            } else {
                preparedVoiceBatch?.cancel()
                showTextSegments(version, displaySegments, finalHoldMs = finalHoldMs)
            }
            characterMessageVersion == version
        } finally {
            preparedVoiceBatch?.cancel()
            characterSegmentActive = false
            if (characterStopAfterCurrentVersion == version) {
                characterStopAfterCurrentVersion = null
            }
        }
    }
    fun appendDialogue(
        role: String,
        text: String,
        recentRepeatedTerms: List<String> = emptyList()
    ) {
        val clean = text.trim()
        if (clean.isBlank()) return
        val cleanRepeatedTerms = recentRepeatedTerms
            .map { it.trim() }
            .filter { it.isNotBlank() }
            .distinct()
            .take(8)
        val entry = mutableMapOf<String, Any?>(
            "role" to role,
            "text" to clean,
            "time_ms" to System.currentTimeMillis()
        )
        if (role == "character" && cleanRepeatedTerms.isNotEmpty()) {
            entry["近期重复词"] = cleanRepeatedTerms
        }
        dialogueHistory = (dialogueHistory + entry).takeLast(XIANGQI_DIALOGUE_HISTORY_MAX_ENTRIES)
    }
    fun crossGameMemory(): Map<String, Any?> {
        val currentRecord = currentGameMemoryRecord(if (game.winner != null) "finished" else "in_progress")
        val records = if (game.winner != null && currentRecord != null) {
            (completedGameRecords.filterNot { it["game_id"] == gameId } + currentRecord).takeLast(6)
        } else {
            completedGameRecords
        }
        val memory = xiangqiBuildCrossGameMemory(records).toMutableMap()
        if (currentRecord != null) {
            memory["current_game"] = currentRecord
        }
        return memory
    }
    fun postgameReviewContext(snapshot: GameState, userMessage: String): Map<String, Any?> {
        return xiangqiBuildPostgameReviewContext(
            gameId = gameId,
            snapshot = snapshot,
            playerSide = playerSide,
            moveHistory = moveHistory,
            dialogueHistory = dialogueHistory,
            userMessage = userMessage
        )
    }
    fun rememberCurrentGameBeforeReset(completedReason: String) {
        if (moveHistory.isEmpty() && game.winner == null) return
        val record = xiangqiBuildGameMemoryRecord(
            gameId = gameId,
            game = game,
            playerSide = playerSide,
            moveHistory = moveHistory,
            dialogueHistory = dialogueHistory,
            completedReason = completedReason
        )
        completedGameRecords = (completedGameRecords
            .filterNot { it["game_id"] == gameId } + record)
            .takeLast(6)
        commitXiangqiMemoryRecord(record, completedReason)
    }
    fun startFreshGame(
        side: Side,
        animateSetup: Boolean = true,
        completedReason: String = "restarted"
    ) {
        rememberCurrentGameBeforeReset(completedReason)
        playerSide = side
        game = GameState()
        gameId = UUID.randomUUID().toString()
        boardPerspective = side
        setupDone = false
        setupVisibleCells = emptySet()
        setupAnimationEnabled = animateSetup
        setupAnimationSkipped = false
        openingStepCompleted = false
        moveHistory = emptyList()
        dialogueHistory = emptyList()
        pendingUserInstruction = ""
        pendingUndoRequest = null
        userUndoRequestCount = 0
        recentlyUndoneUserMoves = emptyList()
        recentlyUndoneCharacterMoves = emptyList()
        dismissedGameOverDialogGameId = null
        voiceUnavailableForGame = false
        setCharacterMessageNow("")
        setupRunId += 1
    }
    fun userUndoStepCount(): Int {
        if (game.history.isEmpty()) return 0
        return if (moveHistory.lastOrNull()?.get("actor") == "character" && game.history.size >= 2) 2 else 1
    }
    fun applyUndoSteps(steps: Int) {
        val dropCount = steps.coerceIn(0, min(game.history.size, moveHistory.size))
        if (dropCount <= 0) return
        game = game.undoSteps(dropCount)
        moveHistory = moveHistory.dropLast(dropCount)
        pendingUserInstruction = ""
    }
    fun userMovesInUndoWindow(steps: Int): List<Map<String, Any?>> {
        val dropCount = steps.coerceIn(0, moveHistory.size)
        if (dropCount <= 0) return emptyList()
        return moveHistory.takeLast(dropCount).filter { it["actor"] == "user" }
    }
    fun finishGameByResignation(winner: Side, playerWon: Boolean) {
        game = game.copy(
            selected = null,
            targets = emptySet(),
            winner = winner,
            message = "${winner.label}胜"
        )
        pendingUndoRequest = null
        pendingUserInstruction = ""
        sfxPlayer.playGameOver(playerWon = playerWon, delayMillis = 180L)
    }
    fun applyRecordedMove(
        move: Move,
        actor: String,
        source: String,
        fallbackMessage: String? = null,
        displayMessage: Boolean = true,
        recentRepeatedTerms: List<String> = emptyList()
    ) {
        val before = game
        val legal = before.board.legalMoves(before.turn)
        if (move !in legal) return
        val nextGame = before.applyMove(move)
        game = nextGame
        playMoveSfx(before, nextGame, move)
        moveHistory = moveHistory + move.toHistoryMap(
            board = before.board,
            side = before.turn,
            playerSide = playerSide,
            nextGame = nextGame,
            actor = actor,
            source = source,
            replyText = fallbackMessage.takeIf { actor == "character" },
            recentRepeatedTerms = recentRepeatedTerms
        )
        if (displayMessage && fallbackMessage != null) {
            setCharacterMessageNow(fallbackMessage)
        }
        if (actor == "character" && recentlyUndoneCharacterMoves.isNotEmpty()) {
            recentlyUndoneCharacterMoves = emptyList()
        }
    }
    suspend fun runCharacterStep(
        userMessage: String = "",
        forceMove: Boolean = false,
        eventType: String? = null,
        allowMove: Boolean = true,
        eventContextExtras: Map<String, Any?> = emptyMap()
    ): Boolean {
        if (aiThinking) return false
        val runPresentationVersion = characterMessageVersion
        val effectiveUserMessage = userMessage.trim()
        val snapshot = game
        val snapshotGameId = gameId
        val snapshotPlayerSide = playerSide
        if (snapshot.winner != null && effectiveUserMessage.isBlank() && eventType == null) return false
        val characterTurn = snapshot.turn != snapshotPlayerSide
        if (forceMove && !characterTurn) return false
        val resolvedEventType = eventType
            ?: if (snapshot.winner != null && effectiveUserMessage.isNotBlank()) "postgame_chat" else null
        val shouldShowMoveThinking = allowMove && forceMove && characterTurn && snapshot.winner == null
        aiThinking = true
        characterMoveThinking = shouldShowMoveThinking
        try {
            val candidates = if (allowMove && characterTurn && snapshot.winner == null) {
                withContext(Dispatchers.Default) {
                    buildMoveCandidates(
                        board = snapshot.board,
                        side = snapshot.turn,
                        playerSide = snapshotPlayerSide,
                        difficulty = difficulty,
                        mistakeRate = mistakeRate,
                        plyCount = snapshot.history.size,
                        userInstruction = effectiveUserMessage,
                        recentMoves = moveHistory,
                        entryCard = entryCard,
                        varietyKey = "$snapshotGameId:$characterId:$characterName",
                        context = localContext.applicationContext,
                        eleEyeSession = eleEyeSession
                    )
                }
            } else {
                emptyList()
            }
            val undoAvoidanceMoves = if (allowMove && characterTurn) recentlyUndoneCharacterMoves else emptyList()
            val playableCandidates = candidates.withoutRecentlyUndoneMoves(undoAvoidanceMoves)
            val orderedCandidates = playableCandidates.orderedForPolicy(entryCard)
            val undoAvoidanceContext = if (undoAvoidanceMoves.isNotEmpty()) {
                mapOf(
                    "must_not_repeat_undone_move" to true,
                    "recently_undone_character_moves" to undoAvoidanceMoves
                )
            } else {
                emptyMap()
            }
            val materialPressureContext = xiangqiCharacterMaterialPressureContext(
                board = snapshot.board,
                playerSide = snapshotPlayerSide,
                moveHistory = moveHistory
            ).takeIf { it.isNotEmpty() }?.let {
                mapOf("character_material_pressure" to it)
            }.orEmpty()
            val materialMomentumContext = xiangqiCharacterMaterialMomentumContext(
                board = snapshot.board,
                playerSide = snapshotPlayerSide,
                moveHistory = moveHistory
            ).takeIf { it.isNotEmpty() }?.let {
                mapOf("character_material_momentum" to it)
            }.orEmpty()
            val request = XiangqiExecuteRequest(
                username = username,
                characterId = characterId.takeIf { it.isNotBlank() },
                conversationId = conversationId.takeIf { it.isNotBlank() },
                gameId = snapshotGameId,
                characterName = characterName,
                userName = userName,
                playerSide = snapshotPlayerSide.apiValue(),
                turn = snapshot.turn.apiValue(),
                boardState = snapshot.board.toApiState(
                    turn = snapshot.turn,
                    playerSide = snapshotPlayerSide,
                    winner = snapshot.winner
                ),
                moveHistory = moveHistory.takeLast(24),
                dialogueHistory = dialogueHistory.takeLast(24),
                moveCandidates = orderedCandidates,
                userMessage = effectiveUserMessage,
                eventContext = snapshot.toEventContext(
                    playerSide = snapshotPlayerSide,
                    explicitEventType = resolvedEventType
                ) + postgameReviewContext(snapshot, effectiveUserMessage) + materialPressureContext + materialMomentumContext + undoAvoidanceContext + eventContextExtras,
                entryCard = entryCard,
                gameMemory = crossGameMemory(),
                voiceReplyEnabled = voiceReplyEnabled,
                clientContext = ClientContextHelper.buildContext(localContext.applicationContext)
            )
            val response = minigameRepository.executeXiangqi(request).getOrElse { error ->
                DebugLog.w("ChineseChess", "执行步骤失败，使用本地候选兜底: ${error.message}", error)
                null
            }
            val result = response?.result
            val action = result?.action.orEmpty()
            val characterReply = result?.characterReply
            val recentRepeatedTerms = result?.recentRepeatedTerms.orEmpty()
            val undoDecision = xiangqiUndoDecision(action)
            val selected = if (allowMove && (action == "move" || action == "move_silent")) {
                orderedCandidates.firstOrNull { it.id == result?.selectedMoveId }
            } else {
                null
            }
            val fallbackCandidate = if (allowMove && selected == null && forceMove && orderedCandidates.isNotEmpty()) {
                orderedCandidates.fallbackCandidate(entryCard) ?: orderedCandidates.first()
            } else {
                null
            }
            val moveCandidate = selected ?: fallbackCandidate
            val movePresentation = moveCandidate?.let { characterReply.movePresentation(action) }
            val replySegments = movePresentation?.allSegments ?: characterReply.visibleSegments(action)
            val voiceSentences = characterReply.voiceSentencesForSegments(replySegments)
            val replyText = replySegments.mergedReplyText()
            if (characterMessageVersion != runPresentationVersion) return false
            if (gameId != snapshotGameId || playerSide != snapshotPlayerSide) return false
            if (game.board != snapshot.board || game.turn != snapshot.turn) return false
            val preparedReplyVoiceBatch = prepareXiangqiVoiceBatch(replySegments, voiceSentences)
            if (replyText.isNotBlank()) {
                appendDialogue("character", replyText, recentRepeatedTerms)
            }
            if (resolvedEventType == "user_undo_request") {
                val undoRequest = pendingUndoRequest
                if (undoRequest?.requester == XiangqiUndoRequester.User) {
                    if (undoDecision == XiangqiUndoDecision.Approve) {
                        val undoneUserMoves = userMovesInUndoWindow(undoRequest.steps)
                        pendingUndoRequest = null
                        applyUndoSteps(undoRequest.steps)
                        if (undoneUserMoves.isNotEmpty()) {
                            recentlyUndoneUserMoves = (recentlyUndoneUserMoves + undoneUserMoves).takeLast(6)
                        }
                    } else {
                        pendingUndoRequest = null
                    }
                }
                showCharacterSegments(
                    segments = replySegments,
                    voiceSentences = voiceSentences,
                    preparedVoiceBatch = preparedReplyVoiceBatch
                )
                return true
            }
            if (xiangqiIsResignAction(action)) {
                if (snapshot.winner == null) {
                    finishGameByResignation(
                        winner = snapshotPlayerSide,
                        playerWon = true
                    )
                }
                showCharacterSegments(
                    segments = replySegments,
                    voiceSentences = voiceSentences,
                    preparedVoiceBatch = preparedReplyVoiceBatch
                )
                return true
            }
            val uiCharacterUndoRequest = result?.ui
                ?.let { xiangqiCharacterUndoRequestFromUi(it, replyText) }
            val characterUndoRequest = uiCharacterUndoRequest
                ?: if (undoDecision == XiangqiUndoDecision.Request) {
                    XiangqiPendingUndoRequest(
                        requester = XiangqiUndoRequester.Character,
                        steps = 1,
                        reason = replyText,
                        waitingForResponse = false
                    )
                } else {
                    null
                }
            if (
                characterUndoRequest != null &&
                pendingUndoRequest == null &&
                moveHistory.lastOrNull()?.get("actor") == "character"
            ) {
                pendingUndoRequest = characterUndoRequest.copy(
                    steps = characterUndoRequest.steps.coerceIn(1, game.history.size)
                )
                showCharacterSegments(
                    segments = replySegments,
                    voiceSentences = voiceSentences,
                    preparedVoiceBatch = preparedReplyVoiceBatch
                )
                return true
            }
            if (moveCandidate != null) {
                val move = moveCandidate.toMove()
                val visibleReply = when {
                    action == "move_silent" -> ""
                    replyText.isNotBlank() -> replyText
                    else -> ""
                }
                val preMoveSegments = movePresentation?.preMoveSegments.orEmpty()
                val postMoveSegments = movePresentation?.postMoveSegments.orEmpty()
                val preMoveVoiceSentences = characterReply.voiceSentencesForSegments(preMoveSegments)
                val postMoveVoiceSentences = characterReply.voiceSentencesForSegments(postMoveSegments)
                val preDisplayCount = displaySegmentsWithVoiceSentences(
                    preMoveSegments,
                    preMoveVoiceSentences
                ).first.size
                val prePreparedVoiceBatch = preparedReplyVoiceBatch?.slice(0, preDisplayCount)
                val postPreparedVoiceBatch = preparedReplyVoiceBatch?.let {
                    it.slice(preDisplayCount, it.segments.size)
                }
                if (preMoveSegments.isNotEmpty()) {
                    val canContinue = showCharacterSegmentsNow(
                        segments = preMoveSegments,
                        voiceSentences = preMoveVoiceSentences,
                        finalHoldMs = 0L,
                        preparedVoiceBatch = prePreparedVoiceBatch
                    )
                    if (!canContinue) {
                        preparedReplyVoiceBatch?.cancel()
                        return false
                    }
                } else {
                    cancelCharacterPresentation(clear = true)
                }
                if (gameId != snapshotGameId || playerSide != snapshotPlayerSide) {
                    preparedReplyVoiceBatch?.cancel()
                    return false
                }
                if (game.board != snapshot.board || game.turn != snapshot.turn) {
                    preparedReplyVoiceBatch?.cancel()
                    return false
                }
                applyRecordedMove(
                    move = move,
                    actor = "character",
                    source = if (selected != null) "model_candidate" else "local_fallback",
                    fallbackMessage = visibleReply,
                    displayMessage = false,
                    recentRepeatedTerms = recentRepeatedTerms
                )
                if (uiCharacterUndoRequest != null && pendingUndoRequest == null) {
                    pendingUndoRequest = uiCharacterUndoRequest.copy(
                        steps = uiCharacterUndoRequest.steps.coerceIn(1, game.history.size)
                    )
                }
                showCharacterSegments(
                    segments = postMoveSegments,
                    voiceSentences = postMoveVoiceSentences,
                    preparedVoiceBatch = postPreparedVoiceBatch
                )
            } else {
                showCharacterSegments(
                    segments = replySegments,
                    voiceSentences = voiceSentences,
                    preparedVoiceBatch = preparedReplyVoiceBatch
                )
            }
            return true
        } finally {
            aiThinking = false
            characterMoveThinking = false
        }
    }
    fun surrenderUser(userText: String = "认输投降") {
        if (!setupDone || !openingStepCompleted || aiThinking || game.winner != null) return
        val cleanUserText = userText.trim().ifBlank { "认输投降" }
        val surrenderContext = xiangqiUserSurrenderContext(
            game = game,
            playerSide = playerSide,
            moveHistory = moveHistory,
            userText = cleanUserText
        )
        cancelCharacterPresentation(clear = true)
        userInput = ""
        messageComposerExpanded = false
        appendDialogue("user", cleanUserText)
        finishGameByResignation(
            winner = playerSide.opponent,
            playerWon = false
        )
        scope.launch {
            runCharacterStep(
                userMessage = cleanUserText,
                forceMove = false,
                eventType = "user_resigned",
                allowMove = false,
                eventContextExtras = mapOf(
                    "must_not_move" to true,
                    "must_speak" to true,
                    "requires_special_reply" to true,
                    "surrender" to surrenderContext
                )
            )
        }
    }
    fun requestUserUndo() {
        if (game.history.isEmpty() || game.winner != null || pendingUndoRequest != null) return
        val steps = userUndoStepCount()
        if (steps <= 0) return
        val persuasion = xiangqiLatestUndoPersuasion(dialogueHistory)
        val undoRequestNumber = userUndoRequestCount + 1
        userUndoRequestCount = undoRequestNumber
        cancelCharacterPresentation(clear = true)
        pendingUserInstruction = ""
        pendingUndoRequest = XiangqiPendingUndoRequest(
            requester = XiangqiUndoRequester.User,
            steps = steps,
            reason = persuasion.ifBlank {
                if (steps >= 2) "撤回双方刚才各走的一步" else "撤回刚才这一步"
            },
            waitingForResponse = true
        )
        scope.launch {
            while (aiThinking && pendingUndoRequest?.requester == XiangqiUndoRequester.User) {
                delay(50L)
            }
            val request = pendingUndoRequest ?: return@launch
            if (request.requester != XiangqiUndoRequester.User) return@launch
            val lastActor = moveHistory.lastOrNull()?.get("actor")?.toString().orEmpty()
            val recentCharacterReplies = dialogueHistory.asReversed()
                .mapNotNull { entry ->
                    val role = (entry["role"] ?: entry["actor"]).toString()
                    val text = (entry["text"] ?: entry["content"] ?: entry["reply_text"]).toString().trim()
                    if (role in setOf("character", "assistant") && text.isNotBlank()) text else null
                }
                .take(4)
                .asReversed()
            val userMoveToUndo = userMovesInUndoWindow(request.steps).lastOrNull()
            val sameUserMoveRepeatCount = xiangqiSameHistoryMoveRepeatCount(
                currentMove = userMoveToUndo,
                recentMoves = recentlyUndoneUserMoves
            )
            val userMessageForRequest = persuasion.ifBlank {
                if (lastActor == "character") {
                    "我想申请悔棋，撤回你和我刚才各走的一步。"
                } else {
                    "我想申请悔棋，撤回我刚才这一步。"
                }
            }
            val handled = runCharacterStep(
                userMessage = userMessageForRequest,
                forceMove = false,
                eventType = "user_undo_request",
                allowMove = false,
                eventContextExtras = mapOf(
                    "must_not_move" to true,
                    "must_speak" to true,
                    "requires_special_reply" to true,
                    "undo_request" to mapOf(
                        "requester" to "user",
                        "steps" to request.steps,
                        "last_actor" to lastActor,
                        "reason" to request.reason,
                        "case" to if (lastActor == "character") "after_character_moved" else "before_character_moved",
                        "request_number" to undoRequestNumber,
                        "recent_character_replies" to recentCharacterReplies,
                        "user_move_to_undo" to userMoveToUndo,
                        "recently_undone_user_moves" to recentlyUndoneUserMoves.takeLast(6),
                        "same_user_move_repeat_count" to sameUserMoveRepeatCount,
                        "repeated_same_user_move_after_undo" to (sameUserMoveRepeatCount > 0),
                        "progression_hint" to if (sameUserMoveRepeatCount > 0) {
                            "用户曾经悔棋撤回过同一手，这次又走回同一手后申请悔棋；回应需要递进或转折，不能像第一次一样复读。"
                        } else {
                            ""
                        }
                    )
                )
            )
            if (handled && pendingUndoRequest == null && game.winner == null && game.turn != playerSide) {
                waitForCharacterPresentationStopAfterCurrent()
                waitForCharacterPresentationIdle()
                delay(240L)
                if (pendingUndoRequest == null && game.winner == null && game.turn != playerSide) {
                    runCharacterStep(forceMove = true)
                }
            }
        }
    }
    LaunchedEffect(setupRunId) {
        val setupSide = playerSide
        setupDone = false
        setupVisibleCells = emptySet()
        setupAnimationSkipped = false
        setCharacterMessageNow("")
        if (!setupAnimationEnabled) {
            setupDone = true
            return@LaunchedEffect
        }
        val order = openingPieceOrder(setupSide)
        order.forEachIndexed { index, cell ->
            delay(if (index == 0) 90L else 180L)
            setupVisibleCells = setupVisibleCells + cell
            if (!setupAnimationSkipped) {
                sfxPlayer.playSetupPiece()
            }
        }
        setupDone = true
    }
    LaunchedEffect(Unit) {
        val initialPlayerSide = playerSide
        prepareCompleted = false
        val request = XiangqiPrepareRequest(
            username = username,
            characterId = characterId.takeIf { it.isNotBlank() },
            conversationId = conversationId.takeIf { it.isNotBlank() },
            characterName = characterName,
            userName = userName,
            playerSide = initialPlayerSide.apiValue(),
            gameMemory = crossGameMemory(),
            voiceReplyEnabled = voiceReplyEnabled,
            clientContext = ClientContextHelper.buildContext(localContext.applicationContext)
        )
        minigameRepository.prepareXiangqi(request).fold(
            onSuccess = { response ->
                entryCard = response.entryCard
                if (fixedDisplayedPowerTier == null) {
                    fixedDisplayedPowerTier = response.entryCard?.powerTier()
                }
                prepareCompleted = true
            },
            onFailure = { error ->
                DebugLog.w("ChineseChess", "准备步骤失败，使用默认开局: ${error.message}", error)
                prepareCompleted = true
            }
        )
    }
    LaunchedEffect(gameId, setupDone, prepareCompleted, openingStepCompleted, pendingUndoRequest, playerSide, game.turn, game.winner) {
        if (!setupDone) return@LaunchedEffect
        if (!prepareCompleted) return@LaunchedEffect
        if (openingStepCompleted) return@LaunchedEffect
        if (pendingUndoRequest != null) return@LaunchedEffect
        if (!aiEnabled || game.winner != null) return@LaunchedEffect
        waitForCharacterPresentationStopAfterCurrent()
        waitForCharacterPresentationIdle()
        delay(180)
        if (openingStepCompleted || pendingUndoRequest != null || game.winner != null) return@LaunchedEffect
        val characterHasFirstMove = playerSide == Side.Black && game.turn != playerSide
        val userHasFirstMove = playerSide == Side.Red && game.turn == playerSide
        val handled = when {
            characterHasFirstMove -> runCharacterStep(
                forceMove = true,
                eventType = "opening_first_move",
                allowMove = true,
                eventContextExtras = mapOf(
                    "must_speak" to true,
                    "opening" to mapOf(
                        "kind" to "character_red_first_move",
                        "character_side" to "red",
                        "player_side" to "black"
                    )
                )
            )
            userHasFirstMove -> runCharacterStep(
                forceMove = false,
                eventType = "opening_chat",
                allowMove = false,
                eventContextExtras = mapOf(
                    "must_not_move" to true,
                    "must_speak" to true,
                    "opening" to mapOf(
                        "kind" to "character_black_waiting",
                        "character_side" to "black",
                        "player_side" to "red"
                    )
                )
            )
            else -> true
        }
        if (handled) {
            openingStepCompleted = true
        }
    }
    LaunchedEffect(game.board, game.turn, game.winner, difficulty, mistakeRate, aiEnabled, playerSide, setupDone, prepareCompleted, pendingUndoRequest, openingStepCompleted) {
        if (!setupDone) return@LaunchedEffect
        if (!prepareCompleted) return@LaunchedEffect
        if (!openingStepCompleted) return@LaunchedEffect
        if (pendingUndoRequest != null) return@LaunchedEffect
        if (!aiEnabled || game.winner != null || game.turn == playerSide) return@LaunchedEffect
        val instruction = pendingUserInstruction.trim()
        waitForCharacterPresentationStopAfterCurrent()
        waitForCharacterPresentationIdle()
        delay(240)
        if (pendingUndoRequest != null) return@LaunchedEffect
        val didRun = runCharacterStep(userMessage = instruction, forceMove = true)
        if (didRun && instruction.isNotBlank() && pendingUserInstruction == instruction) {
            pendingUserInstruction = ""
        }
    }
    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        topBar = {
            PonyTopBar(
                contentHeight = 54.dp,
                shadowElevation = 2.dp,
                horizontalPadding = 8.dp
            ) {
                PonyTopBarBackButton(onClick = onBack)
                Text(
                    text = "中国象棋",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                    modifier = Modifier.weight(1f),
                    textAlign = TextAlign.Center
                )
                Spacer(modifier = Modifier.size(48.dp))
            }
        },
        bottomBar = {
            ChessBattleBottomBar(
                name = userName,
                avatarUrl = userAvatar,
                apiBase = apiBase,
                playerSide = playerSide,
                messageExpanded = messageComposerExpanded,
                userInput = userInput,
                onUserInputChange = { userInput = it },
                onToggleMessage = { messageComposerExpanded = !messageComposerExpanded },
                onSend = {
                    val text = userInput.trim()
                    if (text.isNotEmpty() && openingStepCompleted) {
                        if (xiangqiLooksLikeUserSurrender(text) && game.winner == null && pendingUndoRequest == null) {
                            surrenderUser(text)
                            return@ChessBattleBottomBar
                        }
                        cancelCharacterPresentation(clear = true)
                        appendDialogue("user", text)
                        val sendVersion = characterMessageVersion
                        val shouldCarryInstruction = game.turn == playerSide &&
                            shouldCarryUserInstruction(text)
                        if (shouldCarryInstruction) {
                            pendingUserInstruction = text
                        }
                        userInput = ""
                        messageComposerExpanded = false
                        scope.launch {
                            while (aiThinking && characterMessageVersion == sendVersion) {
                                delay(50L)
                            }
                            if (characterMessageVersion == sendVersion) {
                                runCharacterStep(userMessage = text, forceMove = game.turn != playerSide)
                            }
                        }
                    }
                },
                canUndo = setupDone && openingStepCompleted && game.history.isNotEmpty() && game.winner == null && pendingUndoRequest == null,
                onUndo = {
                    requestUserUndo()
                },
                canSurrender = setupDone && openingStepCompleted && !aiThinking && game.winner == null && pendingUndoRequest == null,
                onSurrender = {
                    surrenderUser()
                },
                onRestart = {
                    startFreshGame(playerSide, completedReason = "menu_restart")
                },
                onFlipBoard = {
                    setupAnimationSkipped = true
                    boardPerspective = boardPerspective.opponent
                },
                onPlayerSideChange = { side ->
                    if (side != playerSide) {
                        startFreshGame(side, animateSetup = true, completedReason = "side_changed")
                    }
                }
            )
        }
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(top = padding.calculateTopPadding())
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 14.dp, vertical = 12.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            OpponentPanel(
                name = characterName,
                avatarUrl = characterAvatar,
                apiBase = apiBase,
                side = playerSide.opponent,
                powerTier = displayedPowerTier,
                message = game.message,
                isThinking = characterMoveThinking,
                winner = game.winner,
                bubbleText = xiangqiOpponentBubbleTextForTest(
                    characterMoveThinking = characterMoveThinking,
                    characterSegmentActive = characterSegmentActive,
                    characterMessage = characterMessage
                ),
                supportsVoice = characterSupportsVoice && !voiceUnavailableForGame && characterId.isNotBlank(),
                voiceReplyEnabled = voiceReplyEnabled,
                onVoiceReplyToggle = {
                    if (voiceReplyEnabled) {
                        voiceReplyEnabled = false
                        voicePlayer.stop()
                    } else if (!voiceUnavailableForGame) {
                        voiceReplyEnabled = true
                    }
                }
            )
            Box(modifier = Modifier.fillMaxWidth()) {
                XiangqiBoard(
                    game = game,
                    perspective = boardPerspective,
                    aiThinking = aiThinking,
                    visiblePieces = if (setupDone || setupAnimationSkipped || !setupAnimationEnabled) null else setupVisibleCells,
                    onCellTap = { cell ->
                        if (!setupDone) return@XiangqiBoard
                        if (!openingStepCompleted) return@XiangqiBoard
                        if (pendingUndoRequest != null) return@XiangqiBoard
                        if (aiThinking) return@XiangqiBoard
                        if (aiEnabled && game.turn != playerSide) return@XiangqiBoard
                        val before = game
                        val tappedOwnPiece = before.board.pieceAt(cell)?.side == before.turn
                        val result = before.handleTapResult(cell)
                        game = result.game
                        if (result.move == null && tappedOwnPiece && result.game.selected == cell) {
                            sfxPlayer.playPickup()
                        }
                        result.move?.let { move ->
                            playMoveSfx(before, result.game, move)
                            finishCurrentCharacterSegmentThenStopQueue()
                            moveHistory = moveHistory + move.toHistoryMap(
                                board = before.board,
                                side = before.turn,
                                playerSide = playerSide,
                                nextGame = result.game,
                                actor = "user",
                                source = "tap",
                                replyText = null
                            )
                            if (result.game.winner == playerSide) {
                                scope.launch {
                                    waitForCharacterPresentationStopAfterCurrent()
                                    runCharacterStep(eventType = "character_lost")
                                }
                            }
                        }
                    },
                    modifier = Modifier.fillMaxWidth()
                )

                val winnerDialog = game.winner?.takeIf { dismissedGameOverDialogGameId != gameId }
                val undoRequestDialog = pendingUndoRequest
                if (winnerDialog != null || undoRequestDialog != null) {
                    Box(
                        modifier = Modifier
                            .matchParentSize()
                            .background(Color.Black.copy(alpha = 0.42f))
                            .pointerInput(Unit) {
                                detectTapGestures { }
                            }
                    )
                    Box(
                        modifier = Modifier
                            .matchParentSize()
                            .padding(horizontal = 22.dp),
                        contentAlignment = Alignment.Center
                    ) {
                        if (undoRequestDialog != null) {
                            XiangqiUndoRequestDialog(
                                request = undoRequestDialog,
                                characterName = characterName,
                                onCancel = {
                                    if (undoRequestDialog.requester == XiangqiUndoRequester.User) {
                                        pendingUndoRequest = null
                                    }
                                },
                                onApprove = {
                                    if (undoRequestDialog.requester == XiangqiUndoRequester.Character) {
                                        val undoHistoryCount = undoRequestDialog.steps.coerceAtLeast(1).coerceAtMost(moveHistory.size)
                                        val undoneCharacterMoves = moveHistory
                                            .takeLast(undoHistoryCount)
                                            .filter { it["actor"] == "character" }
                                        val carriedInstruction = pendingUserInstruction.trim()
                                        pendingUndoRequest = null
                                        applyUndoSteps(undoRequestDialog.steps)
                                        if (undoneCharacterMoves.isNotEmpty()) {
                                            recentlyUndoneCharacterMoves = (recentlyUndoneCharacterMoves + undoneCharacterMoves)
                                                .takeLast(4)
                                            pendingUserInstruction = carriedInstruction
                                        }
                                        appendDialogue("user", "同意悔棋")
                                    }
                                },
                                onReject = {
                                    if (undoRequestDialog.requester == XiangqiUndoRequester.Character) {
                                        pendingUndoRequest = null
                                        appendDialogue("user", "拒绝悔棋")
                                        scope.launch {
                                            runCharacterStep(
                                                userMessage = "我不同意悔棋。",
                                                forceMove = false,
                                                eventType = "character_undo_rejected",
                                                allowMove = false,
                                                eventContextExtras = mapOf(
                                                    "must_not_move" to true,
                                                    "undo_request" to mapOf(
                                                        "requester" to "character",
                                                        "decision" to "rejected",
                                                        "reason" to undoRequestDialog.reason
                                                    )
                                                )
                                            )
                                        }
                                    }
                                }
                            )
                        } else if (winnerDialog != null) {
                            XiangqiGameOverDialog(
                                winner = winnerDialog,
                                playerSide = playerSide,
                                onDismiss = {
                                    dismissedGameOverDialogGameId = gameId
                                },
                                onNewGame = {
                                    startFreshGame(playerSide.opponent, completedReason = "next_game_after_result")
                                }
                            )
                        }
                    }
                }
            }
        }
    }
}
