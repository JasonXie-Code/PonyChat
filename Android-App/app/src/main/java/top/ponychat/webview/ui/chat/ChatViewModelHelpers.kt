package top.ponychat.webview.ui.chat

import top.ponychat.webview.data.model.ChatMessage
import top.ponychat.webview.data.model.GalgameOptionItem
import top.ponychat.webview.data.model.Message
import top.ponychat.webview.data.model.MessageVoiceState
import top.ponychat.webview.util.ErrorFormatter

internal const val GALGAME_POLICY_ERROR_TEXT = "dialogue content violates policy"
internal const val TWO_HOURS_MS = 2 * 60 * 60 * 1000L
internal const val NORMAL_HISTORY_INITIAL_LIMIT = 50
internal const val NORMAL_HISTORY_PAGE_LIMIT = 50
internal const val RETRACTED_USER_MESSAGE_TEXT = "（撤回了消息）"

private val MARKDOWN_IMAGE_RE = Regex("!\\[[^\\]]*\\]\\([^\\)]*\\)")
private val DATA_URL_RE = Regex("data:image/[^;\\s]+;base64,[A-Za-z0-9+/=\\r\\n]+")
private val HTML_IMG_RE = Regex("<img\\b[^>]*>", setOf(RegexOption.IGNORE_CASE))
private val CHAT_IMAGE_URL_RE = Regex("/chat_images/[\\w.-]+")
private val LOCAL_CHAT_IMAGE_URL_RE = Regex("file://[^\\s)]+/chat_images/[^\\s)]+")
private val RETRACTED_USER_MESSAGE_TEXTS = setOf(RETRACTED_USER_MESSAGE_TEXT, "（撤回了一条消息）", "(撤回了消息)", "(撤回了一条消息)")

internal fun isRetractedUserMessageContent(content: String): Boolean {
    return content.trim() in RETRACTED_USER_MESSAGE_TEXTS
}

internal fun runtimeMessagesForClient(
    messages: List<ChatMessage>,
    speakerFallbackMessages: List<ChatMessage> = emptyList()
): List<ChatMessage> {
    return preserveChatMessageSpeakers(
        orderedChatMessages(messages.filterNot { isContextSummaryPlaceholder(it) }),
        speakerFallbackMessages
    )
}

private fun String?.nonBlankOrNull(): String? = this?.takeIf { it.isNotBlank() }

internal fun uiMessageKey(msg: Message): String {
    return msg.messageId?.takeIf { it.isNotBlank() } ?: msg.id
}

internal fun List<Message>.isSameVisibleMessageListAs(other: List<Message>): Boolean {
    if (size != other.size) return false
    return indices.all { idx ->
        val a = this[idx]
        val b = other[idx]
        uiMessageKey(a) == uiMessageKey(b) &&
            a.role == b.role &&
            a.content == b.content &&
            a.timestamp == b.timestamp &&
            a.isStreaming == b.isStreaming &&
            a.isError == b.isError &&
            a.generationDurationMs == b.generationDurationMs &&
            a.sequenceNumber == b.sequenceNumber &&
            a.displayContent == b.displayContent &&
            a.rawContent == b.rawContent &&
            a.galgameOptions == b.galgameOptions &&
            a.quotedMessage == b.quotedMessage &&
            a.attachments == b.attachments &&
            a.voiceState == b.voiceState &&
            a.speakerCharacterId == b.speakerCharacterId &&
            a.speakerName == b.speakerName &&
            a.speakerAvatar == b.speakerAvatar &&
            a.autoScrollBatchIndex == b.autoScrollBatchIndex &&
            a.autoScrollBatchTotal == b.autoScrollBatchTotal &&
            a.allowRealtimeAnimation == b.allowRealtimeAnimation &&
            a.isPendingServerAccept == b.isPendingServerAccept &&
            a.pendingServerAcceptStartedAt == b.pendingServerAcceptStartedAt &&
            a.isRetracted == b.isRetracted
    }
}

internal fun chatMessageKey(msg: ChatMessage): String {
    return msg.messageId?.takeIf { it.isNotBlank() }
        ?: "seq:${msg.sequenceNumber ?: -1}:${msg.role}:${msg.timestamp ?: 0L}"
}

internal fun Message.withSpeakerFallback(previous: Message?): Message {
    if (previous == null || role != "assistant") return this
    val nextSpeakerCharacterId = speakerCharacterId.nonBlankOrNull() ?: previous.speakerCharacterId.nonBlankOrNull()
    val nextSpeakerName = speakerName.nonBlankOrNull() ?: previous.speakerName.nonBlankOrNull()
    val nextSpeakerAvatar = speakerAvatar.nonBlankOrNull() ?: previous.speakerAvatar.nonBlankOrNull()
    if (
        nextSpeakerCharacterId == speakerCharacterId &&
        nextSpeakerName == speakerName &&
        nextSpeakerAvatar == speakerAvatar
    ) {
        return this
    }
    return copy(
        speakerCharacterId = nextSpeakerCharacterId,
        speakerName = nextSpeakerName,
        speakerAvatar = nextSpeakerAvatar
    )
}

internal fun ChatMessage.withSpeakerFallback(previous: ChatMessage?): ChatMessage {
    if (previous == null || role != "assistant") return this
    val nextSpeakerCharacterId = speakerCharacterId.nonBlankOrNull() ?: previous.speakerCharacterId.nonBlankOrNull()
    val nextSpeakerName = speakerName.nonBlankOrNull() ?: previous.speakerName.nonBlankOrNull()
    val nextSpeakerAvatar = speakerAvatar.nonBlankOrNull() ?: previous.speakerAvatar.nonBlankOrNull()
    if (
        nextSpeakerCharacterId == speakerCharacterId &&
        nextSpeakerName == speakerName &&
        nextSpeakerAvatar == speakerAvatar
    ) {
        return this
    }
    return copy(
        speakerCharacterId = nextSpeakerCharacterId,
        speakerName = nextSpeakerName,
        speakerAvatar = nextSpeakerAvatar
    )
}

private fun String.withoutChatImageRefs(): String =
    replace(MARKDOWN_IMAGE_RE, "")
        .replace(DATA_URL_RE, "")
        .replace(CHAT_IMAGE_URL_RE, "")
        .replace(LOCAL_CHAT_IMAGE_URL_RE, "")
        .trim()

private fun Message.withLocalMediaFallback(previous: Message?): Message {
    if (previous == null) return this
    val previousHasLocalImage = previous.content.contains("file://") && previous.content.contains("/chat_images/")
    val currentHasLocalImage = content.contains("file://") && content.contains("/chat_images/")
    if (
        previousHasLocalImage &&
        !currentHasLocalImage &&
        previous.content.withoutChatImageRefs() == content.withoutChatImageRefs()
    ) {
        return copy(content = previous.content)
    }
    return this
}

private fun ChatMessage.withLocalMediaFallback(previous: ChatMessage?): ChatMessage {
    if (previous == null) return this
    var next = this
    val previousHasLocalImage = previous.content.contains("file://") && previous.content.contains("/chat_images/")
    val currentHasLocalImage = content.contains("file://") && content.contains("/chat_images/")
    if (
        previousHasLocalImage &&
        !currentHasLocalImage &&
        previous.content.withoutChatImageRefs() == content.withoutChatImageRefs()
    ) {
        next = next.copy(content = previous.content)
    }

    val currentVoice = effectiveVoiceState(next)
    val previousVoice = effectiveVoiceState(previous)
    val previousLocalFile = previousVoice?.localFile?.takeIf { it.isNotBlank() }
    val voiceMatches = previousLocalFile != null &&
        (currentVoice?.localFile.isNullOrBlank()) &&
        (
            previousVoice.voiceCacheKey.isNullOrBlank() ||
                currentVoice?.voiceCacheKey.isNullOrBlank() ||
                previousVoice.voiceCacheKey == currentVoice?.voiceCacheKey
        )
    if (voiceMatches) {
        val mergedVoice = (currentVoice ?: previousVoice)?.copy(
            localFile = previousLocalFile,
            durationMs = currentVoice?.durationMs ?: previousVoice?.durationMs,
            waveform = currentVoice?.waveform?.takeIf { it.isNotEmpty() } ?: previousVoice?.waveform.orEmpty()
        )
        next = next.copy(
            voiceState = mergedVoice,
            voiceLocalFile = previousLocalFile
        )
    }
    return next
}

internal fun preserveUiMessageSpeakers(
    messages: List<Message>,
    fallbackMessages: List<Message>
): List<Message> {
    if (fallbackMessages.isEmpty()) return messages
    val fallbackByKey = fallbackMessages.associateBy { uiMessageKey(it) }
    return messages.map { message ->
        val fallback = fallbackByKey[uiMessageKey(message)]
        message.withSpeakerFallback(fallback).withLocalMediaFallback(fallback)
    }
}

internal fun preserveChatMessageSpeakers(
    messages: List<ChatMessage>,
    fallbackMessages: List<ChatMessage>
): List<ChatMessage> {
    if (fallbackMessages.isEmpty()) return messages
    val fallbackByKey = fallbackMessages.associateBy { chatMessageKey(it) }
    return messages.map { message ->
        val fallback = fallbackByKey[chatMessageKey(message)]
        message.withSpeakerFallback(fallback).withLocalMediaFallback(fallback)
    }
}

internal fun orderedUiMessages(messages: List<Message>): List<Message> {
    return messages.sortedWith { a, b ->
        val aSeq = a.sequenceNumber
        val bSeq = b.sequenceNumber
        when {
            a.timestamp != b.timestamp -> a.timestamp.compareTo(b.timestamp)
            aSeq != null && bSeq != null && aSeq != bSeq -> aSeq.compareTo(bSeq)
            else -> uiMessageKey(a).compareTo(uiMessageKey(b))
        }
    }
}

internal fun orderedChatMessages(messages: List<ChatMessage>): List<ChatMessage> {
    return messages.sortedWith { a, b ->
        val aSeq = a.sequenceNumber
        val bSeq = b.sequenceNumber
        val aTs = a.timestamp ?: 0L
        val bTs = b.timestamp ?: 0L
        when {
            aTs != bTs -> aTs.compareTo(bTs)
            aSeq != null && bSeq != null && aSeq != bSeq -> aSeq.compareTo(bSeq)
            else -> chatMessageKey(a).compareTo(chatMessageKey(b))
        }
    }
}

internal fun insertIndexForRealtimeMessage(messages: List<Message>, msg: Message): Int {
    val ts = msg.timestamp.takeIf { it > 0L } ?: return messages.size
    val tsIndex = messages.indexOfFirst { existing ->
        existing.timestamp > ts && !existing.isStreaming
    }
    if (tsIndex >= 0) return tsIndex
    val seq = msg.sequenceNumber ?: return messages.size
    val seqIndex = messages.indexOfFirst { existing ->
        existing.timestamp == msg.timestamp &&
            existing.sequenceNumber != null &&
            existing.sequenceNumber > seq
    }
    return if (seqIndex >= 0) seqIndex else messages.size
}

internal fun minSequenceOf(messages: List<ChatMessage>, fallback: Int? = null): Int {
    return fallback ?: messages.mapNotNull { it.sequenceNumber }.minOrNull() ?: Int.MAX_VALUE
}

internal fun latestCacheWindowForMode(messages: List<ChatMessage>, mode: String): List<ChatMessage> {
    if (mode.startsWith("galgame") || messages.size <= NORMAL_HISTORY_INITIAL_LIMIT) return messages
    return messages.takeLast(NORMAL_HISTORY_INITIAL_LIMIT)
}

internal fun isContextSummaryPlaceholder(msg: ChatMessage): Boolean {
    if (msg.role != "user") return false
    val content = msg.content.trimStart()
    return content.startsWith("[以下是本对话之前内容的摘要") ||
        (content.contains("本对话之前内容的摘要") && content.contains("请根据此记忆继续对话"))
}

internal fun parseGalgameOptionsFromPayload(payload: List<Any>?): List<GalgameOptionItem> {
    if (payload.isNullOrEmpty()) return emptyList()
    return payload.mapNotNull { item ->
        when (item) {
            is Map<*, *> -> {
                val label = (item["label"] ?: item["text"])?.toString()?.trim() ?: return@mapNotNull null
                if (label.isBlank()) return@mapNotNull null
                GalgameOptionItem(
                    label = label,
                    type = (item["type"]?.toString()?.trim() ?: "dialogue").lowercase(),
                    tone = item["tone"]?.toString()?.trim() ?: ""
                )
            }
            is String -> if (item.isNotBlank()) GalgameOptionItem(label = item) else null
            else -> null
        }
    }
}

internal fun sortConversations(
    list: List<ConversationSummary>,
    field: String,
    order: String
): List<ConversationSummary> {
    val desc = order == "desc"
    return when (field) {
        "created" -> if (desc) list.sortedByDescending { it.createdAt } else list.sortedBy { it.createdAt }
        "length" -> if (desc) list.sortedByDescending { it.totalChars } else list.sortedBy { it.totalChars }
        else -> if (desc) list.sortedByDescending { it.updatedAt } else list.sortedBy { it.updatedAt }
    }
}

internal fun conversationTextCharsFromChatMessage(messages: List<ChatMessage>): Int {
    return messages.sumOf { visibleTextLength(it.content) }
}

internal fun visibleTextLength(rawContent: String): Int {
    if (rawContent.isBlank()) return 0
    val withoutMarkdownImages = MARKDOWN_IMAGE_RE.replace(rawContent, " ")
    val withoutDataUrl = DATA_URL_RE.replace(withoutMarkdownImages, " ")
    val withoutHtmlImg = HTML_IMG_RE.replace(withoutDataUrl, " ")
    return withoutHtmlImg.trim().length
}

internal fun debugSummarizeSkippedMessage(reason: String): String = when (reason) {
    "not_enough_turns" -> "剧情记忆条目不足，未执行折叠"
    "not_enough_messages" -> "消息数量不足，未生成摘要"
    "no_new_messages_since_last_summary" -> "上次摘要后没有新消息"
    "nothing_to_summarize" -> "没有可总结的消息"
    "tiered_fold_failed" -> "剧情记忆折叠失败"
    "refusal_detected" -> "摘要模型未返回可用内容"
    "invalid_summary_template" -> "摘要内容无效，未落库"
    else -> if (reason.isBlank()) "未执行总结" else "未执行总结：$reason"
}

internal fun buildGalgameDisplayHtml(scene: Map<String, Any?>): String {
    val sb = StringBuilder()
    (scene["env"]?.toString()?.trim())?.takeIf { it.isNotBlank() }?.let { sb.append("<div class=\"gal-scene-env\">$it</div>") }
    (scene["body_state"]?.toString()?.trim())?.takeIf { it.isNotBlank() }?.let { sb.append("<div class=\"gal-scene-body\">$it</div>") }
    (scene["thoughts"]?.toString()?.trim())?.takeIf { it.isNotBlank() }?.let { sb.append("<div class=\"gal-scene-thought\">$it</div>") }
    (scene["third_party_dialogue"]?.toString()?.trim())?.takeIf { it.isNotBlank() && !it.equals("null", true) && !it.equals("none", true) }?.let { sb.append("<div class=\"gal-scene-third-party\">$it</div>") }
    (scene["response"]?.toString()?.trim())?.takeIf { it.isNotBlank() }?.let { sb.append("<div class=\"gal-scene-speech\">$it</div>") }
    val time = scene["time"]?.toString()?.trim()
    val loc = scene["location"]?.toString()?.trim()
    if (!time.isNullOrBlank() || !loc.isNullOrBlank()) {
        sb.append("<div class=\"gal-tags-container\">")
        if (!time.isNullOrBlank()) sb.append("<span class=\"gal-time-tag\">$time</span>")
        if (!loc.isNullOrBlank()) sb.append("<span class=\"gal-loc-tag\">$loc</span>")
        sb.append("</div>")
    }
    return if (sb.isNotEmpty()) "<div class=\"galgame-scene-container\">$sb</div>" else ""
}

internal fun galgameChunkStepLabel(field: String): String = when (field) {
    "env" -> "环境描写"
    "body_state" -> "身体描写"
    "thoughts" -> "心理描写"
    "third_party" -> "其他发言"
    "response" -> "角色回复"
    else -> "Generating"
}

internal fun parseErrorForDisplay(raw: String?): Pair<String, String?> {
    val parsed = ErrorFormatter.format(raw, fallback = "消息发送失败，请稍后重试")
    return parsed.userMessage to parsed.developerMessage
}

internal fun effectiveVoiceState(msg: ChatMessage): MessageVoiceState? {
    val hasTopLevelVoice = !msg.voiceStatus.isNullOrBlank() ||
        !msg.voiceId.isNullOrBlank() ||
        !msg.voiceJobId.isNullOrBlank() ||
        !msg.voiceCacheKey.isNullOrBlank() ||
        !msg.ttsText.isNullOrBlank() ||
        !msg.transcript.isNullOrBlank() ||
        !msg.voiceError.isNullOrBlank() ||
        msg.textFragments?.isNotEmpty() == true ||
        msg.voiceDurationMs != null ||
        !msg.voiceLocalFile.isNullOrBlank() ||
        msg.waveform?.isNotEmpty() == true ||
        msg.voiceDebugPlayable == true
    val topLevel = if (hasTopLevelVoice) {
        MessageVoiceState(
            status = msg.voiceStatus?.takeIf { it.isNotBlank() } ?: "disabled",
            voiceId = msg.voiceId,
            voiceJobId = msg.voiceJobId,
            voiceCacheKey = msg.voiceCacheKey,
            ttsText = msg.ttsText,
            transcript = msg.transcript,
            textFragments = msg.textFragments.orEmpty(),
            voiceError = msg.voiceError,
            durationMs = msg.voiceDurationMs,
            localFile = msg.voiceLocalFile,
            waveform = msg.waveform.orEmpty(),
            debugPlayable = msg.voiceDebugPlayable == true
        )
    } else {
        null
    }
    val nested = msg.voiceState
    val merged = when {
        nested != null && topLevel != null -> nested.copy(
            status = nested.status.ifBlank { topLevel.status },
            voiceId = nested.voiceId ?: topLevel.voiceId,
            voiceJobId = nested.voiceJobId ?: topLevel.voiceJobId,
            voiceCacheKey = nested.voiceCacheKey ?: topLevel.voiceCacheKey,
            ttsText = nested.ttsText ?: topLevel.ttsText,
            transcript = nested.transcript ?: topLevel.transcript,
            textFragments = nested.textFragments.ifEmpty { topLevel.textFragments },
            voiceError = nested.voiceError ?: topLevel.voiceError,
            durationMs = nested.durationMs ?: topLevel.durationMs,
            localFile = nested.localFile ?: topLevel.localFile,
            waveform = nested.waveform.ifEmpty { topLevel.waveform },
            debugPlayable = nested.debugPlayable || topLevel.debugPlayable
        )
        nested != null -> nested
        else -> topLevel
    }
    return merged?.takeIf {
        !it.status.equals("disabled", ignoreCase = true) ||
            !it.ttsText.isNullOrBlank() ||
            !it.transcript.isNullOrBlank() ||
            it.textFragments.isNotEmpty()
    }
}

private fun debugVoiceWaveform(seed: Int, bucketCount: Int = 72): List<Float> {
    val pattern = listOf(0.16f, 0.38f, 0.72f, 0.48f, 0.9f, 0.28f, 1f, 0.58f, 0.24f, 0.8f)
    return List(bucketCount) { index ->
        val envelope = when {
            index < bucketCount / 7 -> 0.42f
            index > bucketCount * 6 / 7 -> 0.34f
            (index + seed) % 17 in 0..3 -> 0.62f
            else -> 1f
        }
        (pattern[(index + seed * 3) % pattern.size] * envelope).coerceIn(0.08f, 1f)
    }
}

internal fun buildDebugAssistantVoiceMessages(now: Long): List<Message> {
    data class VoiceDebugSample(
        val suffix: String,
        val durationMs: Long,
        val transcript: String,
        val fragments: List<String>
    )

    val samples = listOf(
        VoiceDebugSample(
            suffix = "short",
            durationMs = 2_200L,
            transcript = "嗯，我在。",
            fragments = emptyList()
        ),
        VoiceDebugSample(
            suffix = "middle",
            durationMs = 18_000L,
            transcript = "当然可以呀，我就在这里陪你。今天想先聊点轻松的，还是让我听你慢慢说？",
            fragments = listOf("（她的声音放得很轻，像是怕打断你的思路。）")
        ),
        VoiceDebugSample(
            suffix = "max",
            durationMs = 60_000L,
            transcript = "这是一条六十秒上限的语音样例，用来确认气泡在最长状态下仍然只占一行，并且不会继续增长。",
            fragments = listOf("（语音时长达到上限，气泡宽度也停在最大值。）")
        )
    )

    return samples.mapIndexed { index, sample ->
        val id = "debug_voice_${sample.suffix}_$now"
        Message(
            id = id,
            role = "assistant",
            content = (listOf(sample.transcript) + sample.fragments).joinToString("\n"),
            timestamp = now + index,
            messageId = id,
            voiceState = MessageVoiceState(
                status = "ready",
                voiceId = "twilight-soft",
                voiceJobId = "debug-job-${sample.suffix}-$now",
                voiceCacheKey = "debug:voice:${sample.suffix}:$now",
                ttsText = sample.transcript,
                transcript = sample.transcript,
                textFragments = sample.fragments,
                durationMs = sample.durationMs,
                localFile = "debug://voice-sample-${sample.suffix}.mp3",
                waveform = debugVoiceWaveform(index + 1),
                debugPlayable = true
            )
        )
    }
}

internal fun buildDebugUserVoiceMessages(now: Long): List<Message> {
    data class UserVoiceDebugSample(
        val suffix: String,
        val durationMs: Long,
        val transcript: String
    )

    val samples = listOf(
        UserVoiceDebugSample(
            suffix = "short",
            durationMs = 2_800L,
            transcript = "我发一条短语音。"
        ),
        UserVoiceDebugSample(
            suffix = "middle",
            durationMs = 18_000L,
            transcript = "这是我这边发送的一条中等长度语音，用来确认用户端气泡、波形和时长都在右侧正确展示。"
        ),
        UserVoiceDebugSample(
            suffix = "max",
            durationMs = 60_000L,
            transcript = "这是一条用户端六十秒上限语音样例，用来确认最长语音气泡不会换行，波形长度会跟着气泡宽度增长。"
        )
    )

    return samples.mapIndexed { index, sample ->
        val id = "debug_user_voice_${sample.suffix}_$now"
        Message(
            id = id,
            role = "user",
            content = sample.transcript,
            timestamp = now + index,
            messageId = id,
            voiceState = MessageVoiceState(
                status = "ready",
                voiceId = "user-debug",
                voiceJobId = "debug-user-job-${sample.suffix}-$now",
                voiceCacheKey = "debug:user-voice:${sample.suffix}:$now",
                ttsText = sample.transcript,
                transcript = sample.transcript,
                durationMs = sample.durationMs,
                localFile = "debug://user-voice-sample-${sample.suffix}.mp3",
                waveform = debugVoiceWaveform(index + 9),
                debugPlayable = true
            )
        )
    }
}

internal fun buildDebugVoiceCacheMissingMessage(now: Long): Message {
    val transcript = "这条消息的服务端语音状态是 ready，但本地音频缓存不存在，所以应当退回文字展示。"
    return Message(
        id = "debug_voice_missing_$now",
        role = "assistant",
        content = transcript,
        timestamp = now,
        messageId = "debug_voice_missing_$now",
        voiceState = MessageVoiceState(
            status = "ready",
            voiceId = "twilight-soft",
            voiceCacheKey = "debug:missing:$now",
            ttsText = transcript,
            transcript = transcript,
            durationMs = 5200L,
            debugPlayable = false
        )
    )
}

internal fun buildDebugVoiceFailedMessage(now: Long): Message {
    val content = "语音生成暂不可用，当前消息保留为普通文字。"
    return Message(
        id = "debug_voice_failed_$now",
        role = "assistant",
        content = content,
        timestamp = now,
        messageId = "debug_voice_failed_$now",
        voiceState = MessageVoiceState(
            status = "failed",
            ttsText = content,
            transcript = content,
            voiceError = "voice_service_unavailable"
        )
    )
}
