package top.ponychat.webview.ui.character

import android.app.Application
import top.ponychat.webview.util.DebugLog
import top.ponychat.webview.util.toUserMessage
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.Job
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import com.google.gson.Gson
import top.ponychat.webview.data.api.NetworkClient
import top.ponychat.webview.data.local.LocalCacheStore
import top.ponychat.webview.data.model.Character
import top.ponychat.webview.data.model.CharacterLikeResponse
import top.ponychat.webview.data.model.CharacterVoiceDesignResponse
import top.ponychat.webview.data.model.CharacterVoiceReferenceUploadResponse
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.data.repo.CharacterRepository
import top.ponychat.webview.util.ChatEventBus
import java.util.UUID

data class CharacterListState(
    val isLoading: Boolean = false,
    val isRefreshingAllChats: Boolean = false,
    val hasLoadedCharacters: Boolean = false,
    val hasLoadedHallCharacters: Boolean = false,
    val characters: List<Character> = emptyList(),
    val hallCharacters: List<Character> = emptyList(),
    val error: String? = null,
    val selectedTab: Int = 0,
    val editingCharacter: Character? = null,
    val deletingCharacter: Character? = null,
    val actionMessage: String? = null,
    /** 当前排序方式：last_chat / name / custom */
    val characterSort: String = "last_chat",
    /** 本地置顶角色 ID 集合 */
    val pinnedCharacterIds: Set<String> = emptySet(),
    /** 回填完成计数：每次 backfillModeTimestamps 完成后 +1，触发 Compose 重新排序 */
    val backfillRevision: Int = 0,
    /** 远端/前台聊天完成事件计数，用于立即重算「最近对话」排序 */
    val listEventRevision: Int = 0,
    /** 角色×模式未读条数，key 与 [ChatEventBus] 一致：`charId#mode` */
    val unreadMap: Map<String, Int> = emptyMap(),
)

private data class RefreshAllChatContentResult(
    val characters: List<Character>,
    val hasFailure: Boolean
)

class CharacterViewModel(application: Application) : AndroidViewModel(application) {


    private val prefs = AppPreferences(application)
    private val repo = CharacterRepository(prefs)
    private val localCache = LocalCacheStore(application)
    private var pendingReorderSaveJob: Job? = null
    private val characterSaveMutex = Mutex()
    private var characterLoadSeq = 0L
    private var latestVisibleCharacterLoadSeq = 0L
    private var hallLoadSeq = 0L
    private var characterListEpoch = 0L
    private var unsyncedCharacterListEpoch = 0L
    private var refreshAllChatContentJob: Job? = null
    private var lastRefreshAllChatContentStartMs = 0L
    private var visibleCharactersUsername = prefs.username

    // 记录本次会话已尝试从服务端拉取对话时间戳的 "${charId}_${mode}" 集合，
    // 防止每次 backfillModeTimestamps 重复发起 API 请求（只需首次 fetch 一次即可填充本地缓存）
    // galgame 相关的 key 可通过 resetGalgameFetch=true 重置，normal 模式不重置（同一会话内不需要重拉）
    private val fetchAttempted = mutableSetOf<String>()

    private val _state = MutableStateFlow(CharacterListState())
    val state: StateFlow<CharacterListState> = _state.asStateFlow()

    init {
        _state.value = _state.value.copy(
            characterSort = prefs.characterSort,
            pinnedCharacterIds = prefs.pinnedCharacterIds
        )
        loadMyCharacters()
        viewModelScope.launch {
            ChatEventBus.completedFlow.collect { ev ->
                prefs.setModeLastChatTime(ev.characterId, ev.mode, ev.timestamp)
                _state.value = _state.value.copy(
                    listEventRevision = _state.value.listEventRevision + 1
                )
            }
        }
        viewModelScope.launch {
            ChatEventBus.unreadCounts.collect { m ->
                _state.value = _state.value.copy(unreadMap = m)
            }
        }
    }

    private fun markCharacterListMutation(needsSave: Boolean): Long {
        characterListEpoch += 1
        if (needsSave) unsyncedCharacterListEpoch = characterListEpoch
        return characterListEpoch
    }

    private fun canApplyCharacterLoad(
        requestSeq: Long,
        startedEpoch: Long,
        startedUnsyncedEpoch: Long,
        username: String
    ): Boolean {
        return requestSeq == characterLoadSeq &&
            prefs.username == username &&
            startedEpoch == characterListEpoch &&
            startedUnsyncedEpoch == 0L &&
            unsyncedCharacterListEpoch == 0L
    }

    private fun finishSkippedCharacterLoad(silent: Boolean, requestSeq: Long) {
        if (!silent && requestSeq == latestVisibleCharacterLoadSeq) {
            val current = _state.value
            _state.value = current.copy(
                isLoading = false,
                hasLoadedCharacters = current.hasLoadedCharacters || current.characters.isNotEmpty()
            )
        }
    }

    fun resetForAccountChange() {
        pendingReorderSaveJob?.cancel()
        pendingReorderSaveJob = null
        refreshAllChatContentJob?.cancel()
        refreshAllChatContentJob = null
        characterLoadSeq += 1
        latestVisibleCharacterLoadSeq = characterLoadSeq
        hallLoadSeq += 1
        characterListEpoch += 1
        unsyncedCharacterListEpoch = 0L
        fetchAttempted.clear()
        visibleCharactersUsername = prefs.username
        _state.value = CharacterListState(
            characterSort = prefs.characterSort,
            pinnedCharacterIds = prefs.pinnedCharacterIds
        )
    }

    fun loadMyCharacters(silent: Boolean = false, resetGalgameFetch: Boolean = false) {
        val username = prefs.username
        if (username.isBlank()) {
            visibleCharactersUsername = ""
            if (!silent) {
                _state.value = _state.value.copy(
                    isLoading = false,
                    hasLoadedCharacters = true,
                    characters = emptyList()
                )
            }
            return
        }
        // 允许调用方请求重置 galgame fetch 缓存（如切换模式时），以便重新尝试补填
        if (resetGalgameFetch) {
            fetchAttempted.removeAll { it.endsWith("_galgame") || it.endsWith("_galgame_lock") }
        }

        val requestSeq = ++characterLoadSeq
        if (!silent) latestVisibleCharacterLoadSeq = requestSeq
        val startedEpoch = characterListEpoch
        val startedUnsyncedEpoch = unsyncedCharacterListEpoch
        val sameVisibleAccount = visibleCharactersUsername == username
        if (!sameVisibleAccount) {
            visibleCharactersUsername = username
            _state.value = _state.value.copy(
                hasLoadedCharacters = false,
                characters = emptyList(),
                error = null,
                editingCharacter = null,
                deletingCharacter = null,
                actionMessage = null
            )
        }

        viewModelScope.launch {
            val visibleAtStart = if (sameVisibleAccount) _state.value.characters else emptyList()
            val cachedAtStart = withContext(Dispatchers.IO) { localCache.loadCharacters(username) }
            val fallbackAtStart = visibleAtStart.ifEmpty { cachedAtStart }
            if (!silent) {
                visibleCharactersUsername = username
                _state.value = _state.value.copy(
                    isLoading = true,
                    error = null,
                    hasLoadedCharacters = _state.value.hasLoadedCharacters || cachedAtStart.isNotEmpty() || visibleAtStart.isNotEmpty(),
                    characters = when {
                        visibleAtStart.isNotEmpty() -> visibleAtStart
                        cachedAtStart.isNotEmpty() -> cachedAtStart
                        else -> emptyList()
                    }
                )
                if (cachedAtStart.isNotEmpty()) {
                    backfillModeTimestamps(cachedAtStart)
                }
            } else if (_state.value.characters.isEmpty() && cachedAtStart.isNotEmpty()) {
                visibleCharactersUsername = username
                _state.value = _state.value.copy(
                    hasLoadedCharacters = true,
                    characters = cachedAtStart
                )
                backfillModeTimestamps(cachedAtStart)
            }
            val result = repo.loadCharacters(username)
            result.fold(
                onSuccess = { chars ->
                    if (!canApplyCharacterLoad(requestSeq, startedEpoch, startedUnsyncedEpoch, username)) {
                        DebugLog.d("CharVM", "Skip stale character load seq=$requestSeq")
                        finishSkippedCharacterLoad(silent, requestSeq)
                        return@fold
                    }
                    if (chars.isEmpty() && fallbackAtStart.isNotEmpty()) {
                        DebugLog.w("CharVM", "loadCharacters returned empty; keep cached characters (${fallbackAtStart.size})")
                        _state.value = _state.value.copy(
                            isLoading = false,
                            hasLoadedCharacters = true,
                            characters = fallbackAtStart,
                            error = if (silent) _state.value.error else "服务端暂未返回角色，已显示本地缓存"
                        )
                        backfillModeTimestamps(fallbackAtStart)
                        return@fold
                    }
                    localCache.saveCharacters(username, chars)
                    localCache.pruneCachesToVisibleCharacters(username, chars.mapNotNull { it.id?.takeIf { id -> id.isNotBlank() } }.toSet())
                    visibleCharactersUsername = username
                    _state.value = _state.value.copy(
                        isLoading = false,
                        hasLoadedCharacters = true,
                        characters = chars,
                        error = null
                    )
                    // 后台补填：对尚无模式专属时间戳的角色，从本地对话缓存回填 updatedAt
                    backfillModeTimestamps(chars)
                },
                onFailure = { err ->
                    DebugLog.w("CharVM", "loadCharacters failed: ${err.message}", err)
                    if (!canApplyCharacterLoad(requestSeq, startedEpoch, startedUnsyncedEpoch, username)) {
                        finishSkippedCharacterLoad(silent, requestSeq)
                        return@fold
                    }
                    if (!silent) {
                        val cached = cachedAtStart
                        if (cached.isNotEmpty()) {
                            visibleCharactersUsername = username
                            _state.value = _state.value.copy(
                                isLoading = false,
                                hasLoadedCharacters = true,
                                characters = cached,
                                error = "当前使用本地缓存，可到设置检查网络与服务器地址"
                            )
                            // 网络失败时仍补填时间戳，确保缓存角色列表能正确显示时间和排序
                            backfillModeTimestamps(cached)
                        } else {
                            _state.value = _state.value.copy(
                                isLoading = false,
                                hasLoadedCharacters = true,
                                error = err.toUserMessage("加载角色列表失败")
                            )
                        }
                    } else {
                        // silent 模式（从其他界面返回）网络失败：用当前已有角色列表补填，
                        // 确保在网络不可用时也能将本地缓存中的新消息时间戳反映到排序上
                        val current = _state.value.characters.ifEmpty { cachedAtStart }
                        if (_state.value.characters.isEmpty() && current.isNotEmpty()) {
                            _state.value = _state.value.copy(
                                hasLoadedCharacters = true,
                                characters = current
                            )
                        }
                        if (current.isNotEmpty()) backfillModeTimestamps(current)
                    }
                }
            )
        }
    }

    fun refreshAllChatContent(onFinished: (Boolean) -> Unit = {}) {
        val username = prefs.username
        if (username.isBlank()) {
            onFinished(false)
            return
        }
        if (refreshAllChatContentJob?.isActive == true || _state.value.isRefreshingAllChats) return
        val now = System.currentTimeMillis()
        if (now - lastRefreshAllChatContentStartMs < 1200L) return
        lastRefreshAllChatContentStartMs = now

        refreshAllChatContentJob = viewModelScope.launch {
            var result: RefreshAllChatContentResult? = null
            var callbackSuccess = false
            try {
                _state.value = _state.value.copy(isRefreshingAllChats = true, error = null)

                val currentChars = _state.value.characters
                result = withContext(Dispatchers.IO) {
                    var hasFailure = false
                    val cachedAtStart = localCache.loadCharacters(username)
                    val fallbackChars = currentChars.ifEmpty { cachedAtStart }
                    val freshChars = repo.loadCharacters(username).fold(
                        onSuccess = { chars ->
                            if (chars.isNotEmpty()) {
                                localCache.saveCharacters(username, chars)
                                localCache.pruneCachesToVisibleCharacters(
                                    username,
                                    chars.mapNotNull { it.id?.takeIf { id -> id.isNotBlank() } }.toSet()
                                )
                                chars
                            } else {
                                fallbackChars
                            }
                        },
                        onFailure = { err ->
                            hasFailure = true
                            DebugLog.w("CharVM", "refreshAllChatContent loadCharacters failed: ${err.message}", err)
                            fallbackChars
                        }
                    )

                    val modes = listOf("normal", "galgame", "galgame_lock")
                    for (character in freshChars) {
                        val charId = character.id?.takeIf { it.isNotBlank() } ?: continue
                        for (mode in modes) {
                            repo.loadConversationDetail(username, charId, mode = mode).fold(
                                onSuccess = { detail ->
                                    if (detail.messages.isNotEmpty()) {
                                        val apiTs = detail.messages
                                            .mapNotNull { it.timestamp }
                                            .filter { it > 0L }
                                            .maxOrNull() ?: 0L
                                        if (apiTs > 0L) {
                                            prefs.setModeLastChatTime(charId, mode, apiTs)
                                        }
                                        localCache.saveConversation(
                                            username = username,
                                            characterId = charId,
                                            mode = mode,
                                            conversationId = detail.conversationId,
                                            messages = detail.messages,
                                            lockCharVitals = detail.charVitals,
                                            lockCharMood = detail.charMood,
                                            lockOrganFill = detail.organFill,
                                            lockCharGender = detail.characterGender
                                        )
                                    } else {
                                        localCache.clearForCharacterMode(username, charId, mode)
                                    }
                                },
                                onFailure = { err ->
                                    hasFailure = true
                                    DebugLog.w(
                                        "CharVM",
                                        "refreshAllChatContent $mode failed $charId: ${err.message}",
                                        err
                                    )
                                }
                            )
                        }
                    }
                    RefreshAllChatContentResult(freshChars, hasFailure)
                }
                callbackSuccess = result?.hasFailure == false
            } catch (t: Throwable) {
                DebugLog.e("CharVM", "refreshAllChatContent crashed: ${t.message}", t)
                callbackSuccess = false
            } finally {
                val finalResult = result
                val current = _state.value
                _state.value = current.copy(
                    isRefreshingAllChats = false,
                    characters = finalResult?.characters ?: current.characters,
                    backfillRevision = current.backfillRevision + if (finalResult != null) 1 else 0,
                    listEventRevision = current.listEventRevision + if (finalResult != null) 1 else 0
                )
                refreshAllChatContentJob = null
                onFinished(callbackSuccess)
            }
        }
    }

    /**
     * 后台补填模式专属最后对话时间。每次加载角色列表后都完整执行一遍，确保排序与展示即时正确。
     *
     * 时间戳来源（唯一真实源头）：消息的 timestamp 字段。
     *   1. 本地缓存有消息 → 取消息列表中最大的 timestamp，比现有值更新时才覆盖
     *   2. 本地缓存无消息 且 existing==0（从未记录）→ 通过对话详情 API 拉取并写入本地缓存与时间戳
     *   3. 本地缓存无消息 且 existing>0（仅有完成事件/未读等、尚未拉过会话）→ 用 `msgfill_` 键
     *      本会话内最多尝试一次详情 API，成功后写入缓存（列表第二行摘要随 LocalCacheStore.saveConversation 一并写入）
     *
     * 完成后递增 backfillRevision，通知 Compose 重新排序 + 刷新时间戳展示。
     */
    private fun backfillModeTimestamps(characters: List<Character>) {
        val username = prefs.username
        if (username.isBlank()) return
        viewModelScope.launch(kotlinx.coroutines.Dispatchers.IO) {
            val modes = listOf("normal", "galgame", "galgame_lock")
            for (character in characters) {
                val charId = character.id?.takeIf { it.isNotBlank() } ?: continue
                for (mode in modes) {
                    val existing = prefs.getModeLastChatTime(charId, mode)
                    val conv = localCache.loadLatestConversation(username, charId, mode)
                    if (conv != null && conv.messages.isNotEmpty()) {
                        // 本地缓存有消息：仅使用消息时间戳，避免回退到“缓存写入时间”造成全角色同一时刻
                        val cacheTs = conv.messages
                            .mapNotNull { it.timestamp }
                            .filter { it > 0L }
                            .maxOrNull() ?: 0L
                        if (cacheTs > existing) {
                            prefs.setModeLastChatTime(charId, mode, cacheTs)
                        }
                    } else {
                        val fetchKeyNever = "${charId}_${mode}"
                        val fetchKeyRefill = "msgfill_${charId}_${mode}"
                        val shouldFetchNever = existing == 0L && fetchKeyNever !in fetchAttempted
                        val shouldFetchRefill =
                            existing > 0L && fetchKeyRefill !in fetchAttempted
                        if (shouldFetchNever || shouldFetchRefill) {
                            if (shouldFetchNever) fetchAttempted.add(fetchKeyNever)
                            if (shouldFetchRefill) fetchAttempted.add(fetchKeyRefill)
                            runCatching {
                                val detail = repo.loadConversationDetail(username, charId, mode = mode).getOrNull()
                                if (detail != null && detail.messages.isNotEmpty()) {
                                    val apiTs = detail.messages
                                        .mapNotNull { it.timestamp }
                                        .filter { it > 0L }
                                        .maxOrNull() ?: 0L
                                    if (apiTs > 0L) {
                                        prefs.setModeLastChatTime(charId, mode, apiTs)
                                        localCache.saveConversation(
                                            username = username,
                                            characterId = charId,
                                            mode = mode,
                                            conversationId = detail.conversationId,
                                            messages = detail.messages
                                        )
                                    }
                                } else if (detail != null) {
                                    localCache.clearForCharacterMode(username, charId, mode)
                                }
                            }.onFailure { e ->
                                DebugLog.w("CharVM", "backfill $mode ts failed $charId: ${e.message}")
                            }
                        }
                    }
                }
            }
            _state.value = _state.value.copy(backfillRevision = _state.value.backfillRevision + 1)
        }
    }

    fun loadCharacterHall(search: String? = null, silent: Boolean = false) {
        val requestSeq = ++hallLoadSeq
        viewModelScope.launch {
            if (!silent) {
                _state.value = _state.value.copy(isLoading = true, error = null)
            }
            val result = repo.getCharacterHall(search)
            result.fold(
                onSuccess = { chars ->
                    if (requestSeq != hallLoadSeq) {
                        DebugLog.d("CharVM", "Skip stale hall load seq=$requestSeq")
                        return@fold
                    }
                    localCache.saveCharacterHall(chars)
                    _state.value = _state.value.copy(
                        isLoading = if (silent) _state.value.isLoading else false,
                        hasLoadedHallCharacters = true,
                        hallCharacters = chars,
                        error = null
                    )
                },
                onFailure = { err ->
                    DebugLog.w("CharVM", "loadCharacterHall failed: ${err.message}", err)
                    if (requestSeq != hallLoadSeq) return@fold
                    val cached = localCache.loadCharacterHall()
                    if (cached.isNotEmpty()) {
                        if (!silent) {
                            _state.value = _state.value.copy(
                                isLoading = false,
                                hasLoadedHallCharacters = true,
                                hallCharacters = cached,
                                error = "当前使用本地缓存，可到设置检查网络与服务器地址"
                            )
                        }
                    } else {
                        if (!silent) {
                            _state.value = _state.value.copy(
                                isLoading = false,
                                hasLoadedHallCharacters = true,
                                error = err.toUserMessage("加载角色广场失败")
                            )
                        }
                    }
                }
            )
        }
    }

    fun loadCharacterLikes(
        hallId: String,
        onResult: (CharacterLikeResponse) -> Unit,
        onError: (String) -> Unit = {}
    ) {
        val username = prefs.username
        if (hallId.isBlank() || username.isBlank()) return
        viewModelScope.launch {
            repo.getCharacterLikes(hallId, username).fold(
                onSuccess = { stats ->
                    mergeHallLikeStats(hallId, stats)
                    onResult(stats)
                },
                onFailure = { err ->
                    DebugLog.w("CharVM", "loadCharacterLikes failed: ${err.message}", err)
                    onError(err.toUserMessage("加载点赞状态失败"))
                }
            )
        }
    }

    fun likeCharacter(
        hallId: String,
        onResult: (CharacterLikeResponse) -> Unit,
        onError: (String) -> Unit = {}
    ) {
        val username = prefs.username
        if (hallId.isBlank() || username.isBlank()) return
        viewModelScope.launch {
            repo.likeCharacter(hallId, username).fold(
                onSuccess = { stats ->
                    mergeHallLikeStats(hallId, stats)
                    onResult(stats)
                },
                onFailure = { err ->
                    DebugLog.w("CharVM", "likeCharacter failed: ${err.message}", err)
                    onError(err.toUserMessage("点赞失败"))
                }
            )
        }
    }

    private fun mergeHallLikeStats(hallId: String, stats: CharacterLikeResponse) {
        val updatedHall = _state.value.hallCharacters.map { c ->
            if (c.id == hallId) c.copy(likeCount = stats.likeCount, likedToday = stats.likedToday) else c
        }
        _state.value = _state.value.copy(hallCharacters = updatedHall)
    }

    private fun optimisticHallCopy(character: Character, username: String, pendingId: String): Character =
        character.copy(
            id = pendingId,
            isPublic = false,
            publishedAt = "",
            hallId = null,
            sourceId = character.id,
            originalId = character.id,
            owner = username,
            ownerRaw = username,
            addedFrom = character.ownerRaw?.takeIf { it.isNotBlank() }
                ?: character.publicOwner?.takeIf { it.isNotBlank() }
                ?: character.owner?.takeIf { it.isNotBlank() }
                ?: "",
            contentHash = character.contentHash,
            sourceContentHash = character.contentHash,
            canEdit = false
        )

    private fun decodeAddedCharacter(body: Map<String, Any?>?): Character? {
        val raw = body?.get("character") ?: return null
        return runCatching {
            Gson().fromJson(Gson().toJsonTree(raw), Character::class.java)
        }.getOrNull()
    }

    private fun appendOrReplaceLocalCharacter(character: Character, replaceId: String? = null) {
        val current = _state.value.characters
        val next = when {
            replaceId != null && current.any { it.id == replaceId } ->
                current.map { if (it.id == replaceId) character else it }
            current.any { it.id == character.id } ->
                current.map { if (it.id == character.id) character else it }
            character.sourceId?.isNotBlank() == true && current.any { it.sourceId == character.sourceId } ->
                current.map { if (it.sourceId == character.sourceId) character else it }
            else -> current + character
        }
        _state.value = _state.value.copy(characters = next)
        localCache.saveCharacters(prefs.username, next)
    }

    private fun removeLocalCharacterById(characterId: String) {
        val next = _state.value.characters.filter { it.id != characterId }
        _state.value = _state.value.copy(characters = next)
        localCache.saveCharacters(prefs.username, next)
    }

    private fun bumpHallAddCount(hallId: String, delta: Int) {
        val next = _state.value.hallCharacters.map { hall ->
            if (hall.id == hallId) {
                hall.copy(timesAdded = ((hall.timesAdded ?: 0) + delta).coerceAtLeast(0))
            } else {
                hall
            }
        }
        _state.value = _state.value.copy(hallCharacters = next)
    }

    fun uploadCharacterProfileImage(
        bytes: ByteArray,
        onResult: (String) -> Unit,
        onError: (String) -> Unit = {}
    ) {
        viewModelScope.launch {
            repo.uploadCharacterProfileImage(bytes).fold(
                onSuccess = onResult,
                onFailure = { err ->
                    DebugLog.w("CharVM", "uploadCharacterProfileImage failed: ${err.message}", err)
                    onError(err.toUserMessage("图片上传失败"))
                }
            )
        }
    }

    fun uploadCharacterVoiceReferenceAudio(
        bytes: ByteArray,
        fileName: String,
        mimeType: String,
        transcript: String,
        characterId: String,
        voiceProfileId: String,
        voiceName: String,
        onResult: (CharacterVoiceReferenceUploadResponse) -> Unit,
        onError: (String) -> Unit = {}
    ) {
        viewModelScope.launch {
            repo.uploadCharacterVoiceReferenceAudio(
                bytes = bytes,
                fileName = fileName,
                mimeType = mimeType,
                transcript = transcript,
                characterId = characterId,
                voiceProfileId = voiceProfileId,
                voiceName = voiceName
            ).fold(
                onSuccess = onResult,
                onFailure = { err ->
                    DebugLog.w("CharVM", "uploadCharacterVoiceReferenceAudio failed: ${err.message}", err)
                    onError(err.toUserMessage("参考音频上传失败"))
                }
            )
        }
    }

    fun designCharacterVoice(
        characterId: String,
        characterName: String,
        voiceId: String,
        instruct: String,
        action: String,
        onResult: (CharacterVoiceDesignResponse) -> Unit,
        onError: (String) -> Unit = {}
    ) {
        viewModelScope.launch {
            repo.designCharacterVoice(
                characterId = characterId,
                characterName = characterName,
                voiceId = voiceId,
                instruct = instruct,
                action = action
            ).fold(
                onSuccess = onResult,
                onFailure = { err ->
                    DebugLog.w("CharVM", "designCharacterVoice failed: ${err.message}", err)
                    onError(err.toUserMessage("音色生成失败"))
                }
            )
        }
    }

    fun selectTab(tab: Int) {
        _state.value = _state.value.copy(selectedTab = tab)
        if (tab == 1 && _state.value.hallCharacters.isEmpty()) {
            loadCharacterHall()
        }
    }

    fun clearError() {
        _state.value = _state.value.copy(error = null)
    }

    fun clearActionMessage() {
        _state.value = _state.value.copy(actionMessage = null)
    }

    // ==================== 角色 CRUD ====================

    /** 创建新角色 */
    fun createCharacter(name: String, bio: String, prompt: String, preview: String = "") {
        val newChar = Character(
            id = UUID.randomUUID().toString(),
            name = name,
            description = bio,
            bio = bio,
            avatar = "",
            prompt = prompt,
            preview = preview,
            instruction = "",
            tags = emptyList(),
            isDefault = false,
            isPublic = false,
            jailbreak = false
        )
        val newList = _state.value.characters + newChar
        val mutationEpoch = markCharacterListMutation(needsSave = true)
        _state.value = _state.value.copy(characters = newList)
        saveCharacterList(newList, "角色已创建", mutationEpoch = mutationEpoch)
    }

    /** 进入编辑状态 */
    fun startEdit(character: Character) {
        _state.value = _state.value.copy(editingCharacter = character)
    }

    /** 取消编辑 */
    fun cancelEdit() {
        _state.value = _state.value.copy(editingCharacter = null)
    }

    /** 保存编辑后的角色 */
    fun saveEditedCharacter(original: Character, name: String, bio: String, prompt: String, preview: String = "") {
        if (original.isEditBlockedFor(prefs.username)) {
            _state.value = _state.value.copy(actionMessage = "此角色不可编辑")
            return
        }
        val updated = original.copy(
            name = name,
            bio = bio,
            description = bio,
            prompt = prompt,
            preview = preview,
            instruction = "",
            jailbreak = false
        )
        val newList = _state.value.characters.map { if (it.id == original.id) updated else it }
        val mutationEpoch = markCharacterListMutation(needsSave = true)
        _state.value = _state.value.copy(characters = newList, editingCharacter = null)
        saveCharacterList(newList, "角色已保存", mutationEpoch = mutationEpoch)
    }

    /** 创建新角色（全功能版本） */
    fun createCharacterFull(
        name: String,
        bio: String,
        prompt: String,
        preview: String = "",
        avatar: String = "",
        profileCover: String = "",
        profilePhotos: List<String> = emptyList(),
        profileGender: String = "",
        profileSpecies: String = "",
        profileAge: String = "",
        profilePersonality: String = "",
        profileInterests: String = "",
        profileIntro: String = "",
        profileMbti: String = "",
        voiceEnabled: Boolean = false,
        voiceId: String = "",
        voiceInstruct: String = "",
        voiceDecisionPolicy: String = "director",
        voiceSourceMode: String = "voice_id",
        voiceBaseVoiceId: String = "",
        voiceReferenceAudioUrl: String = "",
        voiceReferenceText: String = "",
        voiceProfileId: String = "",
        voiceCloneStatus: String = "",
        tags: List<String> = emptyList(),
        jailbreak: Boolean = false
    ) {
        val newChar = Character(
            id = UUID.randomUUID().toString(),
            name = name,
            description = bio,
            bio = bio,
            avatar = avatar,
            prompt = prompt,
            preview = preview,
            profileCover = profileCover,
            profilePhotos = profilePhotos,
            profileGender = profileGender,
            profileSpecies = profileSpecies,
            profileAge = profileAge,
            profilePersonality = profilePersonality,
            profileInterests = profileInterests,
            profileIntro = profileIntro,
            profileMbti = profileMbti,
            voiceEnabled = voiceEnabled,
            voiceId = voiceId,
            voiceInstruct = voiceInstruct,
            voiceDecisionPolicy = voiceDecisionPolicy,
            voiceSourceMode = voiceSourceMode,
            voiceBaseVoiceId = voiceBaseVoiceId,
            voiceReferenceAudioUrl = voiceReferenceAudioUrl,
            voiceReferenceText = voiceReferenceText,
            voiceProfileId = voiceProfileId,
            voiceCloneStatus = voiceCloneStatus,
            instruction = "",
            tags = tags,
            isDefault = false,
            isPublic = false,
            jailbreak = jailbreak
        )
        val newList = _state.value.characters + newChar
        val mutationEpoch = markCharacterListMutation(needsSave = true)
        _state.value = _state.value.copy(characters = newList)
        saveCharacterList(newList, "角色已创建", mutationEpoch = mutationEpoch)
    }

    /** 保存编辑后的角色（全功能版本） */
    fun saveEditedCharacterFull(
        original: Character,
        name: String,
        bio: String,
        prompt: String,
        preview: String = "",
        avatar: String = "",
        profileCover: String = "",
        profilePhotos: List<String> = emptyList(),
        profileGender: String = "",
        profileSpecies: String = "",
        profileAge: String = "",
        profilePersonality: String = "",
        profileInterests: String = "",
        profileIntro: String = "",
        profileMbti: String = "",
        voiceEnabled: Boolean = false,
        voiceId: String = "",
        voiceInstruct: String = "",
        voiceDecisionPolicy: String = "director",
        voiceSourceMode: String = "voice_id",
        voiceBaseVoiceId: String = "",
        voiceReferenceAudioUrl: String = "",
        voiceReferenceText: String = "",
        voiceProfileId: String = "",
        voiceCloneStatus: String = "",
        tags: List<String> = emptyList(),
        jailbreak: Boolean = false
    ) {
        if (original.isEditBlockedFor(prefs.username)) {
            _state.value = _state.value.copy(actionMessage = "此角色不可编辑")
            return
        }
        val updated = original.copy(
            name = name,
            bio = bio,
            description = bio,
            prompt = prompt,
            preview = preview,
            instruction = "",
            avatar = avatar,
            profileCover = profileCover,
            profilePhotos = profilePhotos,
            profileGender = profileGender,
            profileSpecies = profileSpecies,
            profileAge = profileAge,
            profilePersonality = profilePersonality,
            profileInterests = profileInterests,
            profileIntro = profileIntro,
            profileMbti = profileMbti,
            voiceEnabled = voiceEnabled,
            voiceId = voiceId,
            voiceInstruct = voiceInstruct,
            voiceDecisionPolicy = voiceDecisionPolicy,
            voiceSourceMode = voiceSourceMode,
            voiceBaseVoiceId = voiceBaseVoiceId,
            voiceReferenceAudioUrl = voiceReferenceAudioUrl,
            voiceReferenceText = voiceReferenceText,
            voiceProfileId = voiceProfileId,
            voiceCloneStatus = voiceCloneStatus,
            tags = tags,
            jailbreak = jailbreak
        )
        val newList = _state.value.characters.map { if (it.id == original.id) updated else it }
        val mutationEpoch = markCharacterListMutation(needsSave = true)
        _state.value = _state.value.copy(characters = newList, editingCharacter = null)
        saveCharacterList(newList, "角色已保存", mutationEpoch = mutationEpoch)
    }

    /** 复制角色 */
    fun duplicateCharacter(character: Character) {
        val username = prefs.username.trim()
        val copy = character.copy(
            id = UUID.randomUUID().toString(),
            name = "${character.displayName()} 的副本",
            isPublic = false,
            publishedAt = "",
            contentHash = null,
            hallId = null,
            sourceId = null,
            originalId = null,
            sourceContentHash = null,
            latestSourceContentHash = null,
            officialSourceId = null,
            isOfficialReference = false,
            owner = username,
            ownerRaw = username,
            publicOwner = username,
            addedFrom = username,
            canEdit = true,
            instruction = "",
            jailbreak = false
        )
        val newList = _state.value.characters + copy
        val mutationEpoch = markCharacterListMutation(needsSave = true)
        _state.value = _state.value.copy(characters = newList)
        saveCharacterList(newList, "已复制角色", mutationEpoch = mutationEpoch)
    }

    /** 请求删除角色（弹出确认对话框） */
    fun deleteCharacter(character: Character) {
        _state.value = _state.value.copy(deletingCharacter = character)
    }

    /** 取消删除 */
    fun cancelDelete() {
        _state.value = _state.value.copy(deletingCharacter = null)
    }

    /** 确认删除 */
    fun confirmDelete() {
        val target = _state.value.deletingCharacter ?: return
        val newList = _state.value.characters.filter { it.id != target.id }
        val mutationEpoch = markCharacterListMutation(needsSave = true)
        _state.value = _state.value.copy(characters = newList, deletingCharacter = null)
        val deletedId = target.id?.takeIf { it.isNotBlank() }
        deletedId?.let { prefs.pinnedCharacterIds = prefs.pinnedCharacterIds - it }
        saveCharacterList(
            newList,
            "角色已删除",
            deletedCharacterIds = listOfNotNull(deletedId),
            mutationEpoch = mutationEpoch
        )
    }

    /** 从角色大厅添加角色到我的列表 */
    fun addCharacterFromHall(character: Character) {
        val username = prefs.username
        val charId = character.id ?: return
        val pendingId = "hall_pending_$charId"
        viewModelScope.launch {
            appendOrReplaceLocalCharacter(optimisticHallCopy(character, username, pendingId))
            bumpHallAddCount(charId, 1)
            _state.value = _state.value.copy(isLoading = true)
            try {
                val api = NetworkClient.createApiService(prefs)
                val resp = api.addCharacterFromHall(charId, username)
                if (resp.isSuccessful) {
                    val body = resp.body()
                    val status = body?.get("status") as? String
                    if (status == "already_exists") {
                        removeLocalCharacterById(pendingId)
                        bumpHallAddCount(charId, -1)
                        loadMyCharacters(silent = true)
                        _state.value = _state.value.copy(isLoading = false, actionMessage = "该角色已在你的角色列表中")
                    } else {
                        val added = decodeAddedCharacter(body)
                            ?: optimisticHallCopy(character, username, pendingId).copy(id = pendingId)
                        appendOrReplaceLocalCharacter(
                            added.copy(
                                sourceId = added.sourceId?.takeIf { it.isNotBlank() } ?: charId,
                                originalId = added.originalId?.takeIf { it.isNotBlank() } ?: charId,
                                contentHash = added.contentHash?.takeIf { it.isNotBlank() } ?: character.contentHash,
                                sourceContentHash = added.sourceContentHash?.takeIf { it.isNotBlank() } ?: character.contentHash
                            ),
                            replaceId = pendingId
                        )
                        _state.value = _state.value.copy(isLoading = false)
                        loadMyCharacters(silent = true)
                        loadCharacterHall(silent = true)
                        _state.value = _state.value.copy(actionMessage = "已添加「${character.displayName()}」到我的角色")
                    }
                    kotlinx.coroutines.delay(2000)
                    _state.value = _state.value.copy(actionMessage = null)
                } else {
                    removeLocalCharacterById(pendingId)
                    bumpHallAddCount(charId, -1)
                    val errorBody = resp.errorBody()?.string()
                    val errorMsg = try {
                        val json = org.json.JSONObject(errorBody ?: "{}")
                        json.optString("detail", "添加失败")
                    } catch (_: Exception) {
                        "添加失败"
                    }
                    val displayMsg = when {
                        errorMsg.contains("not found", ignoreCase = true) -> "角色不存在或已下架"
                        else -> errorMsg
                    }
                    _state.value = _state.value.copy(isLoading = false, actionMessage = displayMsg)
                    kotlinx.coroutines.delay(2000)
                    _state.value = _state.value.copy(actionMessage = null)
                }
            } catch (e: Exception) {
                removeLocalCharacterById(pendingId)
                bumpHallAddCount(charId, -1)
                DebugLog.w("CharVM", "addCharacterFromHall failed: ${e.message}", e)
                _state.value = _state.value.copy(isLoading = false, error = "添加角色失败: ${e.message}")
            }
        }
    }

    /** 批量从角色大厅添加角色到我的列表（最多10个） */
    fun addCharactersFromHall(characters: List<Character>) {
        if (characters.isEmpty()) return
        val username = prefs.username
        val validChars = characters.filter { !it.id.isNullOrBlank() }.take(10)
        if (validChars.isEmpty()) return

        viewModelScope.launch {
            val pendingIds = validChars.associate { character ->
                val hallId = character.id.orEmpty()
                val pendingId = "hall_pending_$hallId"
                appendOrReplaceLocalCharacter(optimisticHallCopy(character, username, pendingId))
                bumpHallAddCount(hallId, 1)
                hallId to pendingId
            }
            _state.value = _state.value.copy(isLoading = true)
            var successCount = 0
            var skipCount = 0
            var failCount = 0

            try {
                val api = NetworkClient.createApiService(prefs)
                for (character in validChars) {
                    try {
                        val resp = api.addCharacterFromHall(character.id!!, username)
                        if (resp.isSuccessful) {
                            val body = resp.body()
                            val status = body?.get("status") as? String
                            if (status == "already_exists") {
                                pendingIds[character.id!!]?.let { removeLocalCharacterById(it) }
                                bumpHallAddCount(character.id!!, -1)
                                skipCount++
                            } else {
                                val added = decodeAddedCharacter(body)
                                    ?: optimisticHallCopy(character, username, pendingIds[character.id!!] ?: "hall_pending_${character.id}")
                                appendOrReplaceLocalCharacter(
                                    added.copy(
                                        sourceId = added.sourceId?.takeIf { it.isNotBlank() } ?: character.id,
                                        originalId = added.originalId?.takeIf { it.isNotBlank() } ?: character.id,
                                        contentHash = added.contentHash?.takeIf { it.isNotBlank() } ?: character.contentHash,
                                        sourceContentHash = added.sourceContentHash?.takeIf { it.isNotBlank() } ?: character.contentHash
                                    ),
                                    replaceId = pendingIds[character.id!!]
                                )
                                successCount++
                            }
                        } else {
                            pendingIds[character.id!!]?.let { removeLocalCharacterById(it) }
                            bumpHallAddCount(character.id!!, -1)
                            failCount++
                        }
                    } catch (e: Exception) {
                        DebugLog.w("CharVM", "addCharacterFromHall batch item failed: ${e.message}", e)
                        pendingIds[character.id!!]?.let { removeLocalCharacterById(it) }
                        bumpHallAddCount(character.id!!, -1)
                        failCount++
                    }
                }

                loadMyCharacters(silent = true)
                loadCharacterHall(silent = true)

                val message = buildString {
                    if (successCount > 0) append("添加成功 $successCount 个")
                    if (skipCount > 0) {
                        if (isNotEmpty()) append("，")
                        append("已存在 $skipCount 个")
                    }
                    if (failCount > 0) {
                        if (isNotEmpty()) append("，")
                        append("添加失败 $failCount 个")
                    }
                    if (isEmpty() && validChars.isNotEmpty()) {
                        append("操作完成")
                    }
                }
                _state.value = _state.value.copy(isLoading = false, actionMessage = message)
                kotlinx.coroutines.delay(3000)
                _state.value = _state.value.copy(actionMessage = null)
            } catch (e: Exception) {
                DebugLog.w("CharVM", "addCharactersFromHall failed: ${e.message}", e)
                _state.value = _state.value.copy(isLoading = false, error = "批量添加失败: ${e.message}")
            }
        }
    }

    /** 将本地角色内容同步到已发布的大厅副本（发布者专用） */
    fun syncHallFromLocal(hallCharacter: Character) {
        val hallId = hallCharacter.id ?: return
        val username = prefs.username
        val local = _state.value.characters.firstOrNull { it.hallId == hallId }
        if (local == null) {
            viewModelScope.launch {
                _state.value = _state.value.copy(actionMessage = "找不到对应的本地角色，请先在角色列表确认发布状态")
                kotlinx.coroutines.delay(2500)
                _state.value = _state.value.copy(actionMessage = null)
            }
            return
        }

        viewModelScope.launch {
            _state.value = _state.value.copy(isLoading = true)
            try {
                val api = NetworkClient.createApiService(prefs)
                val gson = Gson()
                val charPayload = gson.toJsonTree(local).asJsonObject
                val resp = api.editHallCharacter(hallId, username, mapOf("character" to charPayload))
                if (resp.isSuccessful) {
                    loadMyCharacters(silent = true)
                    loadCharacterHall()
                    _state.value = _state.value.copy(actionMessage = "已同步「${hallCharacter.displayName()}」到大厅")
                } else {
                    val detail = try {
                        org.json.JSONObject(resp.errorBody()?.string() ?: "{}").optString("detail", "同步失败")
                    } catch (_: Exception) {
                        "同步失败"
                    }
                    val msg = when (detail) {
                        "duplicate_content" -> "大厅中已存在内容完全相同的角色"
                        else -> detail
                    }
                    _state.value = _state.value.copy(isLoading = false, actionMessage = msg)
                }
                kotlinx.coroutines.delay(2500)
                _state.value = _state.value.copy(actionMessage = null)
            } catch (e: Exception) {
                DebugLog.w("CharVM", "syncHallFromLocal failed: ${e.message}", e)
                _state.value = _state.value.copy(isLoading = false, actionMessage = "同步失败: ${e.message}")
                kotlinx.coroutines.delay(2500)
                _state.value = _state.value.copy(actionMessage = null)
            }
        }
    }

    /** 从角色大厅下架自己发布的角色（删除大厅副本，保留本地角色） */
    fun unpublishFromHall(hallCharacter: Character) {
        val hallId = hallCharacter.id ?: return
        val username = prefs.username

        viewModelScope.launch {
            _state.value = _state.value.copy(isLoading = true)
            try {
                val api = NetworkClient.createApiService(prefs)
                val resp = api.unpublishCharacter(hallId, username)
                if (resp.isSuccessful) {
                    val newList = _state.value.characters.map { c ->
                        if (c.hallId == hallId) {
                            c.copy(isPublic = false, publishedAt = "", hallId = null)
                        } else {
                            c
                        }
                    }
                    markCharacterListMutation(needsSave = false)
                    localCache.saveCharacters(username, newList)
                    _state.value = _state.value.copy(
                        isLoading = false,
                        characters = newList,
                        actionMessage = "已从大厅下架「${hallCharacter.displayName()}」"
                    )
                    loadCharacterHall()
                } else {
                    _state.value = _state.value.copy(isLoading = false, actionMessage = "下架失败")
                }
                kotlinx.coroutines.delay(2500)
                _state.value = _state.value.copy(actionMessage = null)
            } catch (e: Exception) {
                DebugLog.w("CharVM", "unpublishFromHall failed: ${e.message}", e)
                _state.value = _state.value.copy(isLoading = false, actionMessage = "下架失败: ${e.message}")
                kotlinx.coroutines.delay(2500)
                _state.value = _state.value.copy(actionMessage = null)
            }
        }
    }

    /** 发布角色到大厅 / 取消发布 */
    fun togglePublish(character: Character) {
        val charId = character.id ?: return
        val username = prefs.username
        val isCurrentlyPublic = character.isPublic

        viewModelScope.launch {
            _state.value = _state.value.copy(isLoading = true)
            try {
                val api = NetworkClient.createApiService(prefs)
                if (isCurrentlyPublic) {
                    // 取消发布：用 hallId 优先，回退用 charId
                    val targetId = character.hallId?.takeIf { it.isNotBlank() } ?: charId
                    val resp = api.unpublishCharacter(targetId, username)
                    if (resp.isSuccessful) {
                        val updated = character.copy(isPublic = false, publishedAt = "", hallId = null)
                        val newList = _state.value.characters.map { if (it.id == charId) updated else it }
                        markCharacterListMutation(needsSave = false)
                        localCache.saveCharacters(username, newList)
                        _state.value = _state.value.copy(
                            isLoading = false,
                            characters = newList,
                            actionMessage = "已取消发布"
                        )
                    } else {
                        _state.value = _state.value.copy(isLoading = false, error = "取消发布失败")
                    }
                } else {
                    // 发布到大厅
                    val resp = api.publishCharacter(charId, username)
                    if (resp.isSuccessful) {
                        val body = resp.body()
                        val newHallId = body?.get("hallId") as? String
                        val now = java.time.Instant.now().toString()
                        val updated = character.copy(
                            isPublic = true,
                            publishedAt = now,
                            hallId = newHallId
                        )
                        val newList = _state.value.characters.map { if (it.id == charId) updated else it }
                        markCharacterListMutation(needsSave = false)
                        localCache.saveCharacters(username, newList)
                        _state.value = _state.value.copy(
                            isLoading = false,
                            characters = newList,
                            actionMessage = "已发布到角色大厅"
                        )
                    } else {
                        val errBody = resp.errorBody()?.string()
                        val detail = try {
                            org.json.JSONObject(errBody ?: "{}").optString("detail", "发布失败")
                        } catch (_: Exception) { "发布失败" }
                        val msg = when (detail) {
                            "already_published" -> "该角色已发布到大厅"
                            "duplicate_content" -> "大厅中已存在内容完全相同的角色"
                            else -> detail
                        }
                        _state.value = _state.value.copy(isLoading = false, actionMessage = msg)
                    }
                }
                kotlinx.coroutines.delay(2000)
                _state.value = _state.value.copy(actionMessage = null)
            } catch (e: Exception) {
                DebugLog.w("CharVM", "togglePublish failed: ${e.message}", e)
                _state.value = _state.value.copy(isLoading = false, error = "发布操作失败: ${e.message}")
            }
        }
    }

    private fun saveCharacterList(
        characters: List<Character>,
        successMessage: String,
        deletedCharacterIds: List<String> = emptyList(),
        mutationEpoch: Long,
        showSuccessMessage: Boolean = true
    ) {
        val username = prefs.username
        viewModelScope.launch {
            val result = characterSaveMutex.withLock {
                repo.saveCharacters(username, characters, deletedCharacterIds)
            }
            result
                .onSuccess {
                    if (mutationEpoch == characterListEpoch) {
                        localCache.saveCharacters(username, characters)
                        deletedCharacterIds.forEach { deletedId ->
                            localCache.clearForCharacter(username, deletedId)
                        }
                        if (unsyncedCharacterListEpoch == mutationEpoch) {
                            unsyncedCharacterListEpoch = 0L
                        }
                        if (showSuccessMessage) {
                            _state.value = _state.value.copy(actionMessage = successMessage)
                            kotlinx.coroutines.delay(2000)
                            _state.value = _state.value.copy(actionMessage = null)
                        }
                        loadMyCharacters(silent = true)
                    }
                }
                .onFailure { err ->
                    DebugLog.w("CharVM", "saveCharacterList failed: ${err.message}", err)
                    if (unsyncedCharacterListEpoch == mutationEpoch) {
                        unsyncedCharacterListEpoch = 0L
                    }
                    _state.value = _state.value.copy(error = "保存失败: ${err.message}")
                }
        }
    }

    val username: String get() = prefs.username
    val nickname: String get() = prefs.nickname.ifBlank { prefs.username }

    /** 设置角色列表排序方式（保存到偏好并更新状态） */
    fun setCharacterSort(sort: String) {
        prefs.characterSort = sort
        _state.value = _state.value.copy(characterSort = sort)
    }

    /** 置顶角色 */
    fun pinCharacter(characterId: String) {
        val newPinned = prefs.pinnedCharacterIds + characterId
        prefs.pinnedCharacterIds = newPinned
        _state.value = _state.value.copy(pinnedCharacterIds = newPinned)
    }

    /** 取消置顶角色 */
    fun unpinCharacter(characterId: String) {
        val newPinned = prefs.pinnedCharacterIds - characterId
        prefs.pinnedCharacterIds = newPinned
        _state.value = _state.value.copy(pinnedCharacterIds = newPinned)
    }

    /**
     * 拖拽排序：将 fromKey 的角色移动到 toKey 的位置。
     * 仅对非置顶角色生效，并在 800ms 防抖后静默保存到后端。
     */
    fun reorderCharacters(fromKey: String, toKey: String) {
        val pinnedIds = _state.value.pinnedCharacterIds
        if (fromKey in pinnedIds || toKey in pinnedIds) return

        val chars = _state.value.characters.toMutableList()
        val fromIdx = chars.indexOfFirst { it.stableId() == fromKey }
        val toIdx = chars.indexOfFirst { it.stableId() == toKey }
        if (fromIdx < 0 || toIdx < 0) return

        chars.add(toIdx, chars.removeAt(fromIdx))
        val mutationEpoch = markCharacterListMutation(needsSave = true)
        _state.value = _state.value.copy(characters = chars)

        // 防抖：拖拽结束 800ms 后才静默保存，避免频繁网络请求
        pendingReorderSaveJob?.cancel()
        pendingReorderSaveJob = viewModelScope.launch {
            delay(800)
            saveCharacterList(
                characters = chars,
                successMessage = "",
                mutationEpoch = mutationEpoch,
                showSuccessMessage = false
            )
        }
    }

    /** 从 prefs 重新加载排序和置顶偏好（从设置页返回时调用） */
    fun refreshPrefsState() {
        val sort = prefs.characterSort
        val pinned = prefs.pinnedCharacterIds
        if (sort != _state.value.characterSort || pinned != _state.value.pinnedCharacterIds) {
            _state.value = _state.value.copy(characterSort = sort, pinnedCharacterIds = pinned)
        }
    }
}
