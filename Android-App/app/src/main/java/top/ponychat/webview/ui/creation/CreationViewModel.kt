package top.ponychat.webview.ui.creation

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.delay
import kotlinx.coroutines.withTimeout
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.launch
import top.ponychat.webview.data.prefs.AppPreferences
import java.util.UUID

data class CreationUiState(val session: CreationSession? = null, val history: List<CreationHistory> = emptyList(),
    val input: String = "", val loading: Boolean = true, val sending: Boolean = false, val error: String? = null,
    val deleting: Boolean = false, val saving: Boolean = false,
    val streamVibrating: Boolean = false,
    val stoppedSessionId: String? = null,
    val switchingVersion: Boolean = false, val alignReplyRequestId: String? = null,
    val contextUsage: CreationContextUsage? = null)

class CreationViewModel(private val prefs: AppPreferences, private val characterId: String,
    private val repository: CreationRepository = CreationRepository(prefs),
    private val loadTimeoutMillis: Long = 30_000L) : ViewModel() {
    private val mutable = MutableStateFlow(CreationUiState())
    val state = mutable.asStateFlow()
    private var retryId: String? = null
    private var retryText: String = ""
    private var retryRegenerate = false
    private var retryContinue = false
    private var stopped = false
    fun stop() {
        if (!mutable.value.sending) return
        stopped = true
        // A deliberate stop ends this attempt; regeneration needs a new scroll/request identity.
        retryId = null
        mutable.update { it.copy(streamVibrating = false, stoppedSessionId = it.session?.id, error = null) }
        repository.stop()
    }
    override fun onCleared() { repository.stop(); super.onCleared() }
    init {
        viewModelScope.launch {
            state.map { it.session to it.history }.distinctUntilChanged().collect { (snapshot, history) ->
                    val current = mutable.value
                    if (snapshot != null && !current.sending && !current.deleting && !current.switchingVersion) {
                        kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) {
                            repository.cache.save(snapshot)
                            repository.cache.saveHistory(characterId, history)
                        }
                    }
                }
        }
        load()
    }

    fun input(value: String) { mutable.update { it.copy(input = value) } }
    fun load(id: String? = null) = viewModelScope.launch {
        if (mutable.value.sending || mutable.value.deleting || mutable.value.saving) return@launch
        val cached = kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) {
            val history = repository.cache.history(characterId)
            val selected = id ?: prefs.getCreationSessionId(characterId).takeIf { saved -> history.any { it.id == saved } } ?: history.firstOrNull()?.id
            Pair(history, selected?.let(repository.cache::session))
        }
        mutable.update { it.copy(session = cached.second ?: it.session, history = if (cached.first.isNotEmpty()) cached.first else it.history,
            loading = cached.second == null && it.session == null, error = null, alignReplyRequestId = null) }
        try {
            val loaded = withTimeout(loadTimeoutMillis) {
                val history = repository.history(characterId)
                val selected = id ?: prefs.getCreationSessionId(characterId).takeIf { saved -> history.any { it.id == saved } }
                    ?: history.firstOrNull()?.id
                val session = selected?.let { repository.load(it) }
                if (session != null) prefs.setCreationSessionId(characterId, session.id)
                retryId = null
                mutable.update { it.copy(session = session, history = history,
                    loading = false, alignReplyRequestId = null, contextUsage = session?.contextUsage) }
                session
            }
            var session = loaded ?: return@launch
            while (session.busy) {
                delay(2000)
                session = repository.load(session.id)
                mutable.update { it.copy(session = session) }
            }
        } catch (e: TimeoutCancellationException) {
            mutable.update { it.copy(loading = false, error = if (it.session != null) "正在显示本地缓存，网络较慢，暂时未能同步会话。" else "会话加载超时，请检查网络后重试。") }
        } catch (e: CancellationException) { throw e }
        catch (e: Exception) { mutable.update { it.copy(loading = false, error = if (it.session != null)
            "正在显示本地缓存，暂时未能同步会话。联网后可以刷新，已缓存的内容仍可阅读。" else e.message) } }
    }

    fun newSession(clearInput: Boolean = true) = viewModelScope.launch {
        val state = mutable.value
        if (state.loading || state.sending || state.deleting || state.saving || state.session?.busy == true) return@launch
        mutable.update { it.copy(saving = true, error = null) }
        try {
            createSession(clearInput)
            runCatching { repository.history(characterId) }.onSuccess { history -> mutable.update { it.copy(history = history) } }
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) { mutable.update { it.copy(error = e.message) } }
        finally { mutable.update { it.copy(saving = false) } }
    }

    private suspend fun createSession(clearInput: Boolean): CreationSession {
        val session = repository.create(characterId)
        prefs.setCreationSessionId(characterId, session.id)
        retryId = null
        mutable.update { it.copy(session = session, input = if (clearInput) "" else it.input,
            error = null, alignReplyRequestId = null, contextUsage = session.contextUsage,
            history = listOf(CreationHistory(session.id, session.title)) + it.history.filterNot { item -> item.id == session.id }) }
        return session
    }

    fun configure(title: String, instructions: String, setting: String?, onSaved: () -> Unit) = viewModelScope.launch {
        if (mutable.value.deleting || mutable.value.saving || mutable.value.sending || mutable.value.session?.busy == true) return@launch
        val session = mutable.value.session ?: return@launch
        mutable.update { it.copy(saving = true, error = null) }
        try {
            val updated = repository.configure(session, title.ifBlank { "新的创作" }, instructions, setting)
            mutable.update { it.copy(session = updated, saving = false, error = null,
                history = it.history.map { item -> if (item.id == updated.id) item.copy(title = updated.title) else item }) }
            onSaved()
        } catch (e: Exception) { mutable.update { it.copy(saving = false, error = e.message) } }
    }

    fun configureAll(title: String, instructions: String, blocks: List<CreationContextBlock>,
        onSaved: () -> Unit) = viewModelScope.launch {
        if (mutable.value.deleting || mutable.value.saving || mutable.value.sending || mutable.value.session?.busy == true) return@launch
        var session = mutable.value.session ?: return@launch
        mutable.update { it.copy(saving = true, error = null) }
        try {
            if (title != session.title || instructions != session.instructions) {
                session = repository.configure(session, title.ifBlank { "新的创作" }, instructions, session.characterSetting)
                // Publish each accepted version so a later failed context save can be retried safely.
                val saved = session
                mutable.update { it.copy(session = saved,
                    history = it.history.map { item -> if (item.id == saved.id) item.copy(title = saved.title) else item }) }
            }
            if (blocks != session.contextLayout) session = repository.configureContext(session, blocks)
            mutable.update { it.copy(session = session, saving = false, error = null) }
            onSaved()
        } catch (e: CancellationException) {
            mutable.update { it.copy(saving = false) }; throw e
        } catch (e: Exception) { mutable.update { it.copy(saving = false, error = e.message) } }
    }

    fun configureContext(blocks: List<CreationContextBlock>, onSaved: () -> Unit) = viewModelScope.launch {
        if (mutable.value.deleting || mutable.value.saving || mutable.value.sending || mutable.value.session?.busy == true) return@launch
        val session = mutable.value.session ?: return@launch
        mutable.update { it.copy(saving = true, error = null) }
        try {
            val updated = repository.configureContext(session, blocks)
            mutable.update { it.copy(session = updated, saving = false, error = null) }
            onSaved()
        } catch (e: Exception) { mutable.update { it.copy(saving = false, error = e.message) } }
    }

    fun refreshContextUsage() = viewModelScope.launch {
        val session = mutable.value.session ?: return@launch
        try {
            val usage = repository.contextUsage(session.id)
            mutable.update { if (it.session?.id == session.id) it.copy(contextUsage = usage) else it }
        } catch (e: CancellationException) { throw e }
        catch (e: Exception) {
            mutable.update { if (it.session?.id == session.id) it.copy(
                contextUsage = it.contextUsage?.copy(contextLimit = null) ?: session.contextUsage) else it }
        }
    }

    fun previousReplyVersion() = selectReplyVersion(-1)

    fun nextReplyVersion() = selectReplyVersion(1)

    private fun selectReplyVersion(direction: Int) = viewModelScope.launch {
        val snapshot = mutable.value
        val session = snapshot.session ?: return@launch
        if (snapshot.loading || snapshot.sending || snapshot.deleting || snapshot.saving || snapshot.switchingVersion || session.busy) return@launch
        val index = session.selectedReplyVersion + direction
        val chosen = session.replyVersions.orEmpty().getOrNull(index) ?: return@launch
        if (chosen.incomplete || session.messages.lastOrNull()?.role != "assistant") return@launch
        val optimistic = session.copy(messages = session.messages.dropLast(1) + chosen,
            selectedReplyVersion = index, lastError = null)
        mutable.update { it.copy(session = optimistic, switchingVersion = true, error = null,
            alignReplyRequestId = chosen.requestId) }
        try {
            val updated = repository.selectReplyVersion(session, chosen.id)
            mutable.update { it.copy(session = updated, switchingVersion = false) }
            prefs.setModeLastChatSnippet(characterId, "creation", chosen.content)
        } catch (e: CancellationException) {
            mutable.update { it.copy(session = session, switchingVersion = false, alignReplyRequestId = session.messages.lastOrNull()?.requestId) }
            throw e
        } catch (e: Exception) {
            mutable.update { it.copy(session = session, switchingVersion = false,
                alignReplyRequestId = session.messages.lastOrNull()?.requestId, error = "切换版本失败，请重试或刷新会话。") }
        }
    }

    fun deleteSession(id: String) = viewModelScope.launch {
        val snapshot = mutable.value
        if (snapshot.loading || snapshot.sending || snapshot.deleting || snapshot.saving || snapshot.session?.busy == true) return@launch
        mutable.update { it.copy(deleting = true, error = null) }
        try {
            val target = snapshot.session?.takeIf { it.id == id } ?: repository.load(id)
            repository.deleteSession(target)
            mutable.update { it.copy(history = it.history.filterNot { item -> item.id == id },
                session = it.session?.takeUnless { current -> current.id == id }, deleting = false) }
            if (snapshot.session?.id == id) {
                prefs.setCreationSessionId(characterId, "")
                prefs.setModeLastChatSnippet(characterId, "creation", "")
            }
        } catch (e: CancellationException) { mutable.update { it.copy(deleting = false) }; throw e }
        catch (e: Exception) { mutable.update { it.copy(deleting = false, error = e.message ?: "删除会话失败，请重试") } }
    }

    fun deleteMessage(messageId: String) = viewModelScope.launch {
        val snapshot = mutable.value
        val session = snapshot.session ?: return@launch
        if (snapshot.loading || snapshot.sending || snapshot.deleting || session.busy) return@launch
        if (session.messages.none { it.id == messageId }) return@launch
        mutable.update { it.copy(session = session.copy(messages = session.messages.filterNot { m -> m.id == messageId }),
            deleting = true, error = null) }
        try {
            val updated = repository.deleteMessage(session, messageId)
            retryId = null
            mutable.update { if (it.session?.id == session.id) it.copy(session = updated, deleting = false, error = null) else it }
            prefs.setModeLastChatSnippet(characterId, "creation", updated.messages.lastOrNull { it.role == "assistant" }?.content.orEmpty())
        } catch (e: CancellationException) {
            mutable.update { if (it.session?.id == session.id) it.copy(session = session, deleting = false) else it }
            throw e
        } catch (e: Exception) {
            mutable.update { if (it.session?.id == session.id) it.copy(session = session, deleting = false,
                error = "删除未确认，消息已恢复显示。请重试或刷新会话。") else it }
        }
    }

    fun continueStory() = send(continueStory = true)

    fun send(regenerate: Boolean = false, editMessageId: String? = null, editedText: String? = null,
        continueStory: Boolean = false,
        onSubmitted: () -> Unit = {}) = viewModelScope.launch {
        val snapshot = mutable.value
        val existingSession = snapshot.session
        if (continueStory && (regenerate || editMessageId != null || existingSession?.messages?.lastOrNull()?.role != "assistant")) return@launch
        val effectiveRegenerate = regenerate || (!continueStory && editMessageId == null && editedText == null &&
            snapshot.input.isBlank() && existingSession?.messages?.lastOrNull()?.role == "user")
        val text = editedText ?: if (effectiveRegenerate || continueStory) "" else snapshot.input
        if (snapshot.loading || snapshot.sending || snapshot.deleting || snapshot.saving || snapshot.switchingVersion ||
            existingSession?.busy == true || (!effectiveRegenerate && !continueStory && text.isBlank())) return@launch
        val session = existingSession ?: run {
            if (effectiveRegenerate || editMessageId != null || snapshot.error != null) return@launch
            mutable.update { it.copy(saving = true) }
            try {
                createSession(clearInput = false)
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                mutable.update { it.copy(error = e.message ?: "新建创作失败，请重试。") }
                return@launch
            } finally {
                mutable.update { it.copy(saving = false) }
            }
        }
        val id = if (editMessageId == null && retryText == text && retryRegenerate == effectiveRegenerate && retryContinue == continueStory) retryId ?: UUID.randomUUID().toString()
            else UUID.randomUUID().toString()
        retryId = id; retryText = text; retryRegenerate = effectiveRegenerate; retryContinue = continueStory
        stopped = false
        val editIndex = session.messages.indexOfFirst { it.id == editMessageId && it.role == "user" }
        if (editMessageId != null && editIndex < 0) return@launch
        val optimistic = if (editMessageId != null) session.copy(messages = session.messages.take(editIndex) +
            session.messages[editIndex].copy(content = text, requestId = id))
            else if (effectiveRegenerate || continueStory || session.messages.any { it.requestId == id }) session else session.copy(
            messages = session.messages + CreationMessage("pending-$id", "user", text, System.currentTimeMillis(), id))
        fun withPlaceholder(base: CreationSession, content: String = ""): CreationSession {
            val transcript = if (effectiveRegenerate && base.messages.lastOrNull()?.role == "assistant") base.messages.dropLast(1)
                else base.messages.filterNot { it.role == "assistant" && it.requestId == id }
            return base.copy(messages = transcript + CreationMessage("stream-$id", "assistant", content,
                System.currentTimeMillis(), id, true), lastError = null,
                replyVersions = if (effectiveRegenerate) base.replyVersions.orEmpty() else emptyList())
        }
        mutable.update { it.copy(session = withPlaceholder(optimistic), sending = true, streamVibrating = false,
            input = if (editMessageId == null && !continueStory) "" else it.input, error = null, stoppedSessionId = null, alignReplyRequestId = id) }
        try {
            var submitted = false
            var received = ""
            var lastRender = 0L
            val updated = repository.stream(session, text, id, effectiveRegenerate, onSession = { accepted ->
                mutable.update { it.copy(session = withPlaceholder(accepted, received)) }
                if (!submitted) { submitted = true; viewModelScope.launch { onSubmitted() } }
            }, onDelta = { delta ->
                received += delta
                val now = System.currentTimeMillis()
                // Reparse the complete accumulated Markdown while tokens arrive, at up to 20 fps.
                if (now - lastRender >= 50) {
                    lastRender = now
                    val rendered = received
                    mutable.update { current ->
                        val base = current.session ?: session
                        current.copy(session = withPlaceholder(base, rendered),
                            streamVibrating = !stopped && rendered.isNotBlank())
                    }
                }
            }, editMessageId = editMessageId, continueStory = continueStory)
            mutable.update { it.copy(session = updated, sending = false, streamVibrating = false, contextUsage = updated.contextUsage?.copy(contextLimit = it.contextUsage?.contextLimit)) }
            retryId = null
            prefs.setModeLastChatTime(characterId, "creation")
            prefs.setModeLastChatSnippet(characterId, "creation", updated.messages.lastOrNull()?.content.orEmpty())
            runCatching { repository.history(characterId) }.onSuccess { history -> mutable.update { it.copy(history = history) } }
        } catch (e: CancellationException) { throw e }
        catch (e: Exception) {
            mutable.update { it.copy(streamVibrating = false) }
            var latest: CreationSession? = null
            repeat(8) {
                if (latest == null || latest?.busy == true) {
                    delay(150)
                    latest = runCatching { repository.load(session.id) }.getOrNull()
                }
            }
            mutable.update { it.copy(session = latest?.takeUnless { s -> s.busy } ?: it.session?.copy(busy = false),
                sending = false, input = it.input.ifBlank { if (stopped || editMessageId != null) "" else text },
                error = if (stopped) null else e.message) }
        } finally { mutable.update { it.copy(streamVibrating = false) } }
    }
}
