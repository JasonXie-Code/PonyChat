package top.ponychat.webview.data.local

import android.content.Context
import androidx.core.content.edit
import com.google.gson.Gson
import com.google.gson.JsonElement
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import com.google.gson.reflect.TypeToken
import top.ponychat.webview.data.model.ChatMessage
import top.ponychat.webview.data.model.Character
import top.ponychat.webview.data.model.QuickMessage
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.util.DebugLog
import top.ponychat.webview.util.GalgameNotificationPreview

data class CachedConversation(
    val conversationId: String?,
    val updatedAt: Long,
    val messages: List<ChatMessage>,
    val messageCount: Int = messages.size,
    val maxSeq: Int = messages.maxOfOrNull { it.sequenceNumber ?: 0 } ?: messages.size,
    val version: Int = 1,
    // 锁分模式体征数据：进入对话时即可还原，无需等待服务端响应
    val lockCharVitals: Map<String, Int>? = null,
    val lockCharMood: Map<String, Int>? = null,
    val lockOrganFill: Map<String, Int>? = null,
    val lockCharGender: String? = null
)

class LocalCacheStore(context: Context) {

    private val appContext = context.applicationContext
    private val prefs = appContext.getSharedPreferences("ponychat_local_cache", Context.MODE_PRIVATE)
    private val appPrefs by lazy { AppPreferences(appContext) }
    private val gson = Gson()

    private fun rootKey(username: String, characterId: String, mode: String): String {
        return "conv_${username}_${characterId}_$mode"
    }

    private fun localHiddenKey(
        username: String,
        characterId: String,
        mode: String,
        conversationId: String?
    ): String {
        val convKey = conversationId?.ifBlank { "__latest" } ?: "__latest"
        return "local_hidden_${username}_${characterId}_${mode}_$convKey"
    }

    private fun retractedOriginalKey(
        username: String,
        characterId: String,
        mode: String,
        conversationId: String?,
        messageId: String
    ): String {
        val convKey = conversationId?.ifBlank { "__latest" } ?: "__latest"
        return "retracted_original_${username}_${characterId}_${mode}_${convKey}_$messageId"
    }

    private fun conversationKeyParts(username: String, key: String): Pair<String, String>? {
        val prefix = "conv_${username}_"
        if (!key.startsWith(prefix)) return null
        val suffixPart = key.removePrefix(prefix)
        return listOf("galgame_lock", "galgame", "normal").firstNotNullOfOrNull { mode ->
            val suffix = "_$mode"
            suffixPart
                .takeIf { it.endsWith(suffix) }
                ?.removeSuffix(suffix)
                ?.takeIf { it.isNotBlank() }
                ?.let { it to mode }
        }
    }

    private fun localHiddenKeyParts(username: String, key: String): Pair<String, String>? {
        val prefix = "local_hidden_${username}_"
        if (!key.startsWith(prefix)) return null
        val suffixPart = key.removePrefix(prefix)
        return listOf("galgame_lock", "galgame", "normal").firstNotNullOfOrNull { mode ->
            val marker = "_${mode}_"
            val markerIndex = suffixPart.indexOf(marker)
            if (markerIndex <= 0) null else suffixPart.substring(0, markerIndex) to mode
        }
    }

    private fun readMap(key: String): MutableMap<String, CachedConversation> {
        val raw = prefs.getString(key, null) ?: return mutableMapOf()
        return try {
            val type = TypeToken.getParameterized(
                Map::class.java,
                String::class.java,
                CachedConversation::class.java
            ).type
            val parsed = gson.fromJson<Map<String, CachedConversation>>(raw, type)
            parsed?.toMutableMap() ?: mutableMapOf()
        } catch (e: Exception) {
            DebugLog.w("LocalCache", "readMap parse failed for $key: ${e.message}", e)
            mutableMapOf()
        }
    }

    private fun writeMap(key: String, data: MutableMap<String, CachedConversation>) {
        prefs.edit {
            if (data.isEmpty()) remove(key) else putString(key, gson.toJson(data))
        }
    }

    private fun isVisibleCharacter(character: Character): Boolean =
        character.isHidden != true && character.hidden != true

    private fun isContextSummaryPlaceholder(msg: ChatMessage): Boolean {
        if (msg.role != "user") return false
        val content = msg.content.trimStart()
        return content.startsWith("[以下是本对话之前内容的摘要") ||
            (content.contains("本对话之前内容的摘要") && content.contains("请根据此记忆继续对话"))
    }

    private fun isNewerConversation(a: CachedConversation, b: CachedConversation): Boolean {
        return when {
            a.updatedAt != b.updatedAt -> a.updatedAt > b.updatedAt
            a.maxSeq != b.maxSeq -> a.maxSeq > b.maxSeq
            else -> a.messageCount > b.messageCount
        }
    }

    private fun isVisibleMessage(msg: ChatMessage, locallyHidden: Set<String> = emptySet()): Boolean {
        val msgId = msg.messageId
        return msg.isHidden != true &&
            !isContextSummaryPlaceholder(msg) &&
            (msgId == null || msgId !in locallyHidden)
    }

    private fun contentHasLocalChatImage(content: String): Boolean =
        content.contains("file://") && content.contains("/chat_images/")

    private fun contentWithoutChatImageRefs(content: String): String =
        content
            .replace(Regex("!\\[[^\\]]*\\]\\(([^)]*/chat_images/[^)]*)\\)"), "")
            .replace(Regex("file://[^\\s)]+/chat_images/[^\\s)]+"), "")
            .replace(Regex("/chat_images/[\\w.-]+"), "")
            .trim()

    private fun ChatMessage.withLocalImageFallback(previous: ChatMessage?): ChatMessage {
        if (previous == null) return this
        if (!contentHasLocalChatImage(previous.content)) return this
        if (contentHasLocalChatImage(content)) return this
        if (contentWithoutChatImageRefs(previous.content) != contentWithoutChatImageRefs(content)) return this
        return copy(content = previous.content)
    }

    private fun mergeLocalImageMessages(
        incoming: List<ChatMessage>,
        existing: CachedConversation?
    ): List<ChatMessage> {
        if (existing == null || existing.messages.isEmpty()) return incoming
        val previousById = existing.messages
            .mapNotNull { msg -> msg.messageId?.takeIf { it.isNotBlank() }?.let { it to msg } }
            .toMap()
        if (previousById.isEmpty()) return incoming
        return incoming.map { msg ->
            val previous = msg.messageId?.takeIf { it.isNotBlank() }?.let { previousById[it] }
            msg.withLocalImageFallback(previous)
        }
    }

    private fun conversationWithMessages(
        conversation: CachedConversation,
        messages: List<ChatMessage>
    ): CachedConversation =
        conversation.copy(
            messages = messages,
            messageCount = messages.size,
            maxSeq = messages.maxOfOrNull { it.sequenceNumber ?: 0 } ?: messages.size
        )

    private fun visibleMessages(
        username: String,
        characterId: String,
        mode: String,
        conversation: CachedConversation
    ): List<ChatMessage> {
        val locallyHidden = loadLocallyHiddenMessageIds(username, characterId, mode, conversation.conversationId)
        return conversation.messages.filter { isVisibleMessage(it, locallyHidden) }
    }

    private fun sanitizeConversation(
        username: String,
        characterId: String,
        mode: String,
        conversation: CachedConversation
    ): CachedConversation {
        val visible = visibleMessages(username, characterId, mode, conversation)
        return if (
            visible.size == conversation.messages.size &&
            conversation.messageCount == visible.size &&
            conversation.maxSeq == (visible.maxOfOrNull { it.sequenceNumber ?: 0 } ?: visible.size)
        ) {
            conversation
        } else {
            conversationWithMessages(conversation, visible)
        }
    }

    private fun sanitizeConversationMap(
        username: String,
        characterId: String,
        mode: String,
        source: MutableMap<String, CachedConversation>
    ): Pair<MutableMap<String, CachedConversation>, Boolean> {
        var changed = false
        val sanitized = linkedMapOf<String, CachedConversation>()
        source.forEach { (convKey, conversation) ->
            val clean = sanitizeConversation(username, characterId, mode, conversation)
            if (clean.messages.isEmpty() && convKey != "__latest") {
                changed = true
                return@forEach
            }
            if (clean != conversation) changed = true
            sanitized[convKey] = clean
        }

        val latest = sanitized
            .filterKeys { it != "__latest" }
            .values
            .maxWithOrNull { a, b ->
                when {
                    a.updatedAt != b.updatedAt -> a.updatedAt.compareTo(b.updatedAt)
                    a.maxSeq != b.maxSeq -> a.maxSeq.compareTo(b.maxSeq)
                    else -> a.messageCount.compareTo(b.messageCount)
                }
            }
        if (latest == null) {
            val latestOnly = sanitized["__latest"]?.takeIf { it.messages.isNotEmpty() }
            if (latestOnly == null && sanitized.remove("__latest") != null) changed = true
        } else if (sanitized["__latest"] != latest) {
            sanitized["__latest"] = latest
            changed = true
        }
        return sanitized.toMutableMap() to changed
    }

    private fun updateLatestSnippet(
        username: String,
        characterId: String,
        mode: String,
        conversation: CachedConversation?
    ) {
        val snippet = conversation
            ?.let { GalgameNotificationPreview.listRowSnippetFromLastAssistant(visibleMessages(username, characterId, mode, it), mode) }
            .orEmpty()
        if (snippet.isBlank()) appPrefs.clearModeLastChatSnippet(characterId, mode)
        else appPrefs.setModeLastChatSnippet(characterId, mode, snippet)
    }

    fun saveConversation(
        username: String,
        characterId: String,
        mode: String,
        conversationId: String?,
        messages: List<ChatMessage>,
        lockCharVitals: Map<String, Int>? = null,
        lockCharMood: Map<String, Int>? = null,
        lockOrganFill: Map<String, Int>? = null,
        lockCharGender: String? = null
    ) {
        val key = rootKey(username, characterId, mode)
        val map = sanitizeConversationMap(username, characterId, mode, readMap(key)).first
        // 优先使用消息本身的时间戳，避免仅因"重新拉取历史"把 updatedAt 写成当前时间，
        // 进而导致角色列表里大量条目显示同一时刻。
        val convKey = conversationId?.ifBlank { "__latest" } ?: "__latest"
        val existingForKey = map[convKey]
        val existingForLatest = map["__latest"]?.takeIf { it.conversationId == conversationId }
        val mergedMessages = mergeLocalImageMessages(
            mergeLocalImageMessages(messages, existingForKey),
            existingForLatest
        )
        val locallyHidden = loadLocallyHiddenMessageIds(username, characterId, mode, conversationId)
        val visibleInput = mergedMessages.filter { isVisibleMessage(it, locallyHidden) }
        val latestMsgTs = visibleInput
            .mapNotNull { it.timestamp }
            .filter { it > 0L }
            .maxOrNull()
        val now = latestMsgTs ?: System.currentTimeMillis()
        val entry = CachedConversation(
            conversationId = conversationId,
            updatedAt = now,
            messages = visibleInput,
            lockCharVitals = lockCharVitals,
            lockCharMood = lockCharMood,
            lockOrganFill = lockOrganFill,
            lockCharGender = lockCharGender
        )
        if (entry.messages.isEmpty()) {
            map.remove(convKey)
            if (map["__latest"]?.conversationId == conversationId || convKey == "__latest") {
                map.remove("__latest")
                map
                    .filterKeys { it != "__latest" }
                    .values
                    .maxByOrNull { it.updatedAt }
                    ?.let { map["__latest"] = it }
            }
            writeMap(key, map)
            updateLatestSnippet(username, characterId, mode, map["__latest"])
            return
        }
        if (existingForKey != null && isNewerConversation(existingForKey, entry)) {
            val latest = map["__latest"] ?: map.values.maxWithOrNull { a, b ->
                when {
                    a.updatedAt != b.updatedAt -> a.updatedAt.compareTo(b.updatedAt)
                    a.maxSeq != b.maxSeq -> a.maxSeq.compareTo(b.maxSeq)
                    else -> a.messageCount.compareTo(b.messageCount)
                }
            }
            updateLatestSnippet(username, characterId, mode, latest)
            return
        }
        map[convKey] = entry
        val currentLatest = map["__latest"]
        if (currentLatest == null || isNewerConversation(entry, currentLatest) || currentLatest.conversationId == conversationId) {
            map["__latest"] = entry
        }
        writeMap(key, map)
        updateLatestSnippet(username, characterId, mode, map["__latest"])
    }

    fun loadLocallyHiddenMessageIds(
        username: String,
        characterId: String,
        mode: String,
        conversationId: String?
    ): Set<String> {
        return prefs.getStringSet(localHiddenKey(username, characterId, mode, conversationId), emptySet())
            ?.filter { it.isNotBlank() }
            ?.toSet()
            ?: emptySet()
    }

    fun hideMessageLocally(
        username: String,
        characterId: String,
        mode: String,
        conversationId: String?,
        messageId: String
    ) {
        if (messageId.isBlank()) return
        val key = localHiddenKey(username, characterId, mode, conversationId)
        val next = loadLocallyHiddenMessageIds(username, characterId, mode, conversationId).toMutableSet()
        next.add(messageId)
        prefs.edit { putStringSet(key, next) }

        val cached = loadConversation(username, characterId, mode, conversationId ?: "")
        if (cached != null) {
            val visible = cached.messages.filter {
                val msgId = it.messageId
                it.isHidden != true &&
                    !isContextSummaryPlaceholder(it) &&
                    (msgId == null || msgId !in next)
            }
            val snippet = GalgameNotificationPreview.listRowSnippetFromLastAssistant(visible, mode)
            if (snippet.isBlank()) appPrefs.clearModeLastChatSnippet(characterId, mode)
            else appPrefs.setModeLastChatSnippet(characterId, mode, snippet)
        }
    }

    fun saveRetractedMessageOriginal(
        username: String,
        characterId: String,
        mode: String,
        conversationId: String?,
        messageId: String,
        content: String
    ) {
        if (messageId.isBlank()) return
        prefs.edit {
            putString(retractedOriginalKey(username, characterId, mode, conversationId, messageId), content)
            if (!conversationId.isNullOrBlank()) {
                putString(retractedOriginalKey(username, characterId, mode, null, messageId), content)
            }
        }
    }

    fun loadRetractedMessageOriginal(
        username: String,
        characterId: String,
        mode: String,
        conversationId: String?,
        messageId: String
    ): String? {
        if (messageId.isBlank()) return null
        prefs.getString(retractedOriginalKey(username, characterId, mode, conversationId, messageId), null)?.let {
            return it
        }
        return if (!conversationId.isNullOrBlank()) {
            prefs.getString(retractedOriginalKey(username, characterId, mode, null, messageId), null)
        } else {
            null
        }
    }

    fun loadLatestConversation(username: String, characterId: String, mode: String): CachedConversation? {
        val key = rootKey(username, characterId, mode)
        val map = readMap(key)
        val clean = sanitizeConversationMap(username, characterId, mode, map).first
        return clean["__latest"] ?: clean.values.maxByOrNull { it.updatedAt }
    }

    fun loadConversation(
        username: String,
        characterId: String,
        mode: String,
        conversationId: String
    ): CachedConversation? {
        val key = rootKey(username, characterId, mode)
        val map = readMap(key)
        val clean = sanitizeConversationMap(username, characterId, mode, map).first
        return clean[conversationId] ?: clean["__latest"]
    }

    fun loadConversationList(username: String, characterId: String, mode: String): List<CachedConversation> {
        val key = rootKey(username, characterId, mode)
        val map = readMap(key)
        val clean = sanitizeConversationMap(username, characterId, mode, map).first
        return clean
            .filterKeys { it != "__latest" }
            .values
            .sortedByDescending { it.updatedAt }
    }

    fun removeConversation(username: String, characterId: String, mode: String, conversationId: String) {
        val key = rootKey(username, characterId, mode)
        val map = readMap(key)
        map.remove(conversationId)
        prefs.edit { remove(localHiddenKey(username, characterId, mode, conversationId)) }
        val latest = map
            .filterKeys { it != "__latest" }
            .values
            .maxByOrNull { it.updatedAt }
        if (latest == null) {
            map.remove("__latest")
        } else {
            map["__latest"] = latest
        }
        writeMap(key, map)
        if (latest == null) {
            appPrefs.clearModeLastChatSnippet(characterId, mode)
        } else {
            updateLatestSnippet(username, characterId, mode, latest)
        }
    }

    fun saveCharacters(username: String, characters: List<Character>) {
        val key = "characters_$username"
        val visibleCharacters = characters.filter { isVisibleCharacter(it) }
        prefs.edit {
            putString(key, gson.toJson(visibleCharacters))
        }
    }

    fun loadCharacters(username: String): List<Character> {
        val key = "characters_$username"
        val raw = prefs.getString(key, null) ?: return emptyList()
        return try {
            val type = TypeToken.getParameterized(List::class.java, Character::class.java).type
            val parsed = gson.fromJson<List<Character>>(raw, type) ?: emptyList()
            parsed.filter { isVisibleCharacter(it) }
        } catch (e: Exception) {
            DebugLog.w("LocalCache", "loadCharacters parse failed: ${e.message}", e)
            emptyList()
        }
    }

    fun saveQuickMessages(username: String, messages: List<QuickMessage>) {
        val user = username.trim()
        if (user.isBlank()) return
        val sorted = messages.sortedWith(compareBy<QuickMessage> { it.sortOrder }.thenBy { it.id })
        prefs.edit {
            putString("quick_messages_$user", gson.toJson(sorted))
        }
    }

    fun loadQuickMessages(username: String): List<QuickMessage> {
        val user = username.trim()
        if (user.isBlank()) return emptyList()
        val raw = prefs.getString("quick_messages_$user", null) ?: return emptyList()
        return try {
            val type = TypeToken.getParameterized(List::class.java, QuickMessage::class.java).type
            gson.fromJson<List<QuickMessage>>(raw, type)
                ?.sortedWith(compareBy<QuickMessage> { it.sortOrder }.thenBy { it.id })
                ?: emptyList()
        } catch (e: Exception) {
            DebugLog.w("LocalCache", "loadQuickMessages parse failed: ${e.message}", e)
            emptyList()
        }
    }

    fun saveCharacterHall(characters: List<Character>) {
        val visibleCharacters = characters.filter { isVisibleCharacter(it) }
        prefs.edit {
            putString("character_hall_cache", gson.toJson(visibleCharacters))
        }
    }

    fun loadCharacterHall(): List<Character> {
        val raw = prefs.getString("character_hall_cache", null) ?: return emptyList()
        return try {
            val type = TypeToken.getParameterized(List::class.java, Character::class.java).type
            val parsed = gson.fromJson<List<Character>>(raw, type) ?: emptyList()
            parsed.filter { isVisibleCharacter(it) }
        } catch (e: Exception) {
            DebugLog.w("LocalCache", "loadCharacterHall parse failed: ${e.message}", e)
            emptyList()
        }
    }

    /** 清除指定角色+模式下的所有本地对话缓存（含 __latest 指针）。 */
    fun clearForCharacterMode(username: String, characterId: String, mode: String) {
        val key = rootKey(username, characterId, mode)
        prefs.edit {
            remove(key)
            prefs.all.keys
                .filter { it.startsWith("local_hidden_${username}_${characterId}_${mode}_") }
                .forEach { remove(it) }
        }
        appPrefs.clearModeLastChatSnippet(characterId, mode)
        appPrefs.clearModeLastChatTime(characterId, mode)
    }

    /** 清除指定角色所有模式下的本地对话缓存。用于删除角色后移除本机残留内容。 */
    fun clearForCharacter(username: String, characterId: String) {
        listOf("normal", "galgame", "galgame_lock").forEach { mode ->
            clearForCharacterMode(username, characterId, mode)
        }
    }

    /** 服务端角色列表刷新成功后，移除已不再可见角色的本地对话缓存。 */
    fun pruneCachesToVisibleCharacters(username: String, visibleCharacterIds: Set<String>) {
        val removedPairs = linkedSetOf<Pair<String, String>>()
        val keys = prefs.all.keys.toList()
        prefs.edit {
            for (key in keys) {
                val convParts = conversationKeyParts(username, key)
                if (convParts != null && convParts.first !in visibleCharacterIds) {
                    remove(key)
                    removedPairs.add(convParts)
                    continue
                }
                val hiddenParts = localHiddenKeyParts(username, key)
                if (hiddenParts != null && hiddenParts.first !in visibleCharacterIds) {
                    remove(key)
                    removedPairs.add(hiddenParts)
                }
            }
        }
        removedPairs.forEach { (characterId, mode) ->
            appPrefs.clearModeLastChatSnippet(characterId, mode)
            appPrefs.clearModeLastChatTime(characterId, mode)
        }
    }

    /** 清空所有本地对话/角色大厅缓存（用于「清空缓存并刷新」） */
    fun clearAll() {
        prefs.edit { clear() }
    }

    private fun readIntField(obj: JsonObject, vararg names: String): Int {
        for (name in names) {
            val value = obj.get(name) ?: continue
            val parsed = runCatching {
                when {
                    value.isJsonPrimitive && value.asJsonPrimitive.isNumber -> value.asInt
                    value.isJsonPrimitive && value.asJsonPrimitive.isString -> value.asString.toIntOrNull() ?: 0
                    else -> 0
                }
            }.getOrDefault(0)
            if (parsed > 0) return parsed
        }
        return 0
    }

    private fun countMessagesInConversationElement(element: JsonElement): Int {
        if (element.isJsonArray) return element.asJsonArray.size()
        val obj = element.takeIf { it.isJsonObject }?.asJsonObject ?: return 0
        val messagesSize = obj.get("messages")
            ?.takeIf { it.isJsonArray }
            ?.asJsonArray
            ?.size()
            ?: 0
        val messageCount = readIntField(obj, "messageCount", "message_count")
        return maxOf(messagesSize, messageCount)
    }

    private fun countMessagesInConversationCache(raw: String): Int {
        val root = JsonParser.parseString(raw)
        val directCount = countMessagesInConversationElement(root)
        if (directCount > 0) return directCount

        val map = root.takeIf { it.isJsonObject }?.asJsonObject ?: return 0
        var nonLatestTotal = 0
        map.entrySet()
            .filter { it.key != "__latest" }
            .forEach { (_, element) ->
                nonLatestTotal += countMessagesInConversationElement(element)
            }
        if (nonLatestTotal > 0) return nonLatestTotal
        return map.get("__latest")?.let { countMessagesInConversationElement(it) } ?: 0
    }

    private fun countMessagesInConversationMap(map: Map<String, CachedConversation>): Int {
        val nonLatestTotal = map
            .filterKeys { it != "__latest" }
            .values
            .sumOf { it.messages.size }
        if (nonLatestTotal > 0) return nonLatestTotal
        return map["__latest"]?.messages?.size ?: 0
    }

    /** 统计本地缓存的角色数、消息数与估算占用字节 */
    fun getStorageStats(username: String): LocalStorageStats {
        val visibleCharacterIds = loadCharacters(username)
            .mapNotNull { it.id?.takeIf { id -> id.isNotBlank() } }
            .toSet()
        val cachedCharacterCount = visibleCharacterIds.size
        val conversationCharacterIds = mutableSetOf<String>()
        var totalMessages = 0
        var totalBytes = 0L
        val convPrefix = "conv_${username}_"
        val knownModeSuffixes = listOf("_galgame_lock", "_galgame", "_normal")
        for ((key, value) in prefs.all.toMap()) {
            val strValue = value as? String ?: continue
            if (key.startsWith(convPrefix)) {
                val suffixPart = key.removePrefix(convPrefix)
                val mode = knownModeSuffixes.firstOrNull { suffix -> suffixPart.endsWith(suffix) }
                val characterId = mode?.let { suffixPart.removeSuffix(it) }
                val cleanMode = mode?.removePrefix("_")
                if (!characterId.isNullOrBlank() && !cleanMode.isNullOrBlank()) {
                    if (visibleCharacterIds.isNotEmpty() && characterId !in visibleCharacterIds) {
                        clearForCharacterMode(username, characterId, cleanMode)
                        continue
                    }
                    conversationCharacterIds.add(characterId)
                    val (clean, changed) = sanitizeConversationMap(username, characterId, cleanMode, readMap(key))
                    if (changed) writeMap(key, clean)
                    if (clean.isNotEmpty()) {
                        totalBytes += gson.toJson(clean).toByteArray(Charsets.UTF_8).size.toLong()
                        totalMessages += countMessagesInConversationMap(clean)
                    }
                } else {
                    totalBytes += strValue.toByteArray(Charsets.UTF_8).size.toLong()
                    try {
                        totalMessages += countMessagesInConversationCache(strValue)
                    } catch (_: Exception) {}
                }
            } else {
                totalBytes += strValue.toByteArray(Charsets.UTF_8).size.toLong()
            }
        }
        val characterCount = maxOf(cachedCharacterCount, conversationCharacterIds.size)
        return LocalStorageStats(characterCount, totalMessages, totalBytes)
    }
}

data class LocalStorageStats(
    val characterCount: Int = 0,
    val totalMessageCount: Int = 0,
    val estimatedSizeBytes: Long = 0L
)
