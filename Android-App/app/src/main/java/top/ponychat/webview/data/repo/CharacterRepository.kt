package top.ponychat.webview.data.repo

import com.google.gson.Gson
import com.google.gson.JsonObject
import android.util.Log
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import top.ponychat.webview.data.api.NetworkClient
import top.ponychat.webview.data.model.*
import top.ponychat.webview.data.prefs.AppPreferences

/** 加载对话详情的返回：消息列表、用量、对话 ID；游戏/锁分模式时含 score 和体征 */
data class ConversationDetailResult(
    val messages: List<top.ponychat.webview.data.model.ChatMessage>,
    val usage: top.ponychat.webview.data.model.ConversationUsage?,
    val conversationId: String?,
    /** 游戏/锁分模式时当前好感度 (0-100) */
    val score: Int? = null,
    /** 锁分模式专属：生命体征初始值（用于初始加载时填充面板） */
    val charVitals:      Map<String, Int>? = null,
    val charMood:        Map<String, Int>? = null,
    val organFill:       Map<String, Int>? = null,
    /** 锁分模式：角色性别（决定器官面板展示子宫或精巢） */
    val characterGender: String?           = null,
    /** 服务端：是否已展示过满分庆祝弹窗 */
    val victoryCelebrationAck: Boolean     = false,
)

class CharacterRepository(private val prefs: AppPreferences) {

    private val TAG = "CharacterRepo"
    private val gson = Gson()

    private fun api() = NetworkClient.createApiService(prefs)

    private fun List<ChatMessage>.visibleForClient(): List<ChatMessage> =
        filter { it.isHidden != true }

    private fun ConversationDetailData.withVisibleMessages(): ConversationDetailData =
        copy(messages = messages.visibleForClient())

    suspend fun loadCharacters(username: String): Result<List<Character>> {
        val result = runCatching {
            val resp = api().loadCharacters(username, lazy = true)
            if (resp.isSuccessful) {
                resp.body()?.characters?.filter { it.isHidden != true && it.hidden != true } ?: emptyList()
            } else {
                throw Exception("加载角色失败 (${resp.code()})")
            }
        }
        return result
    }

    suspend fun loadConversationDetail(
        username: String,
        characterId: String,
        conversationId: String? = null,
        mode: String = "normal"
    ): Result<ConversationDetailResult> {
        return runCatching {
            val resp = api().getConversationDetail(username, characterId, conversationId, mode)
            if (resp.isSuccessful) {
                val body = resp.body()
                // 若指定了 conversationId，优先从列表中找精确匹配；否则取第一个（最新）
                val conv = body?.conversation
                    ?: if (conversationId != null)
                        body?.conversations?.firstOrNull { it.id == conversationId }
                            ?: body?.conversations?.firstOrNull()
                    else
                        body?.conversations?.firstOrNull()
                // 游戏/锁分模式：后端在顶层返回 messages，需优先使用
                val messages = (body?.messages?.takeIf { it.isNotEmpty() }
                    ?: conv?.messages ?: emptyList()).visibleForClient()
                val usage = body?.usage
                val cid = conv?.id?.takeIf { it.isNotBlank() }
                    ?: (if (mode == "galgame" || mode == "galgame_lock") characterId else null)
                val score = if (mode == "galgame" || mode == "galgame_lock") body?.score else null
                val charVitals      = if (mode == "galgame_lock") body?.charVitals else null
                val charMood        = if (mode == "galgame_lock") body?.charMood   else null
                val organFill       = if (mode == "galgame_lock") body?.organFill  else null
                val characterGender = if (mode == "galgame_lock") body?.characterGender?.takeIf { it.isNotBlank() } else null
                val victoryAck = (body?.victoryCelebrationAck ?: 0) != 0
                ConversationDetailResult(
                    messages, usage, cid, score, charVitals, charMood, organFill, characterGender,
                    victoryCelebrationAck = victoryAck,
                )
            } else {
                throw Exception("加载对话失败 (${resp.code()})")
            }
        }
    }

    suspend fun postGalgameVictoryAck(username: String, characterId: String, mode: String): Result<Unit> {
        return runCatching {
            val resp = api().postGalgameVictoryAck(
                mapOf(
                    "username" to username,
                    "character_id" to characterId,
                    "mode" to mode,
                )
            )
            if (!resp.isSuccessful) throw Exception("HTTP ${resp.code()}")
            val b = resp.body()
            val ok = b?.get("success") == true || b?.get("status") == "success"
            if (!ok) throw Exception(b?.get("message")?.toString() ?: "victory_ack failed")
        }
    }

    suspend fun getCharacterHall(search: String? = null): Result<List<Character>> {
        return runCatching {
            val resp = api().getCharacterHall(search, prefs.username.takeIf { it.isNotBlank() })
            if (resp.isSuccessful) {
                resp.body() ?: emptyList()
            } else {
                throw Exception("角色大厅加载失败 (${resp.code()})")
            }
        }
    }

    suspend fun getCharacterLikes(hallId: String, username: String): Result<CharacterLikeResponse> {
        return runCatching {
            val resp = api().getCharacterLikes(hallId, username)
            if (resp.isSuccessful) {
                resp.body() ?: CharacterLikeResponse()
            } else {
                throw Exception("点赞状态加载失败 (${resp.code()})")
            }
        }
    }

    suspend fun likeCharacter(hallId: String, username: String): Result<CharacterLikeResponse> {
        return runCatching {
            val resp = api().likeCharacter(hallId, username)
            if (resp.isSuccessful) {
                resp.body() ?: CharacterLikeResponse()
            } else {
                throw Exception("点赞失败 (${resp.code()})")
            }
        }
    }

    suspend fun uploadCharacterProfileImage(bytes: ByteArray): Result<String> {
        return runCatching {
            val body = bytes.toRequestBody("image/jpeg".toMediaType())
            val part = MultipartBody.Part.createFormData("file", "character_profile.jpg", body)
            val resp = api().uploadCharacterProfileImage(part)
            if (resp.isSuccessful) {
                resp.body()?.url?.takeIf { it.isNotBlank() } ?: throw Exception("上传响应为空")
            } else {
                throw Exception("图片上传失败 (${resp.code()})")
            }
        }
    }

    suspend fun uploadCharacterVoiceReferenceAudio(
        bytes: ByteArray,
        fileName: String,
        mimeType: String,
        transcript: String,
        characterId: String,
        voiceProfileId: String,
        voiceName: String
    ): Result<CharacterVoiceReferenceUploadResponse> {
        return runCatching {
            val cleanMime = mimeType.takeIf { it.isNotBlank() } ?: "audio/mpeg"
            val cleanName = fileName.takeIf { it.isNotBlank() } ?: "voice_reference"
            val body = bytes.toRequestBody(cleanMime.toMediaType())
            val part = MultipartBody.Part.createFormData("file", cleanName, body)
            val resp = api().uploadCharacterVoiceReferenceAudio(
                file = part,
                transcript = transcript.toRequestBody("text/plain".toMediaType()),
                characterId = characterId.toRequestBody("text/plain".toMediaType()),
                voiceProfileId = voiceProfileId.toRequestBody("text/plain".toMediaType()),
                voiceName = voiceName.toRequestBody("text/plain".toMediaType())
            )
            if (resp.isSuccessful) {
                resp.body() ?: throw Exception("上传响应为空")
            } else {
                throw Exception("参考音频上传失败 (${resp.code()})")
            }
        }
    }

    suspend fun designCharacterVoice(
        characterId: String,
        characterName: String,
        voiceId: String,
        instruct: String,
        action: String
    ): Result<CharacterVoiceDesignResponse> {
        return runCatching {
            val resp = api().designCharacterVoice(
                CharacterVoiceDesignRequest(
                    characterId = characterId,
                    characterName = characterName,
                    voiceId = voiceId,
                    instruct = instruct,
                    action = action
                )
            )
            if (resp.isSuccessful) {
                resp.body() ?: throw Exception("音色响应为空")
            } else {
                throw Exception("音色生成失败 (${resp.code()})")
            }
        }
    }

    /** 自动保存：把当前会话的消息回写给服务端（格式与后端 save_characters 一致） */
    @Suppress("UNUSED_PARAMETER")
    suspend fun saveConversation(
        username: String,
        characters: List<Character>,
        characterId: String,
        conversationId: String?,
        messages: List<top.ponychat.webview.data.model.ChatMessage>,
        saveIntent: String = "auto_sync"
    ): Result<Unit> {
        top.ponychat.webview.util.DebugLog.d(
            TAG,
            "[HistoryDebug] saveConversation skipped: server message history is authoritative " +
                "user=$username char=$characterId conv=${conversationId ?: "null"} msgCount=${messages.size} intent=$saveIntent"
        )
        return Result.success(Unit)
        /* legacy server conversation upload intentionally removed
        return runCatching {
            val req = SaveCharactersRequest(
                username = username,
                characters = characters,
                conversations = mapOf(characterId to listOf(payload)),
                partiallySyncedCharacters = listOf(characterId),
                saveIntent = saveIntent
            )
            val resp = legacySaveCharacters(req)
            if (!resp.isSuccessful) throw Exception("保存失败 (${resp.code()})")
            val body = resp.body()
            if (body != null && body.success == false) throw Exception(body.message ?: "保存失败")
            Unit
        }
        */
    }

    /**
     * 仅保存角色列表（不含对话）。
     *
     * @param deletedCharacterIds 本次明确删除的角色 ID 列表。
     *   若非空，使用 save_intent=user_edit 并传给后端，后端只删这些 ID（绕过数量差量保护）。
     *   若为空，使用 auto_sync，后端不执行任何删除。
     */
    suspend fun saveCharacters(
        username: String,
        characters: List<Character>,
        deletedCharacterIds: List<String> = emptyList()
    ): Result<Unit> {
        val hasExplicitDelete = deletedCharacterIds.isNotEmpty()
        return runCatching {
            val req = SaveCharactersRequest(
                username = username,
                characters = characters,
                conversations = null,
                deletedCharacters = if (hasExplicitDelete) deletedCharacterIds else null,
                saveIntent = if (hasExplicitDelete) "user_edit" else "auto_sync"
            )
            val resp = api().saveCharacters(req)
            if (!resp.isSuccessful) throw Exception("保存失败 (${resp.code()})")
            val body = resp.body()
            if (body != null && body.success == false) {
                throw Exception(body.message ?: "保存失败")
            }
            Unit
        }.also {
            if (it.isFailure) Log.w(TAG, "saveCharacters failed: ${it.exceptionOrNull()?.message}")
        }
    }

    /** 加载某角色的所有对话列表 */
    suspend fun loadAllConversations(
        username: String,
        characterId: String,
        mode: String = "normal"
    ): Result<List<ConversationDetailData>> {
        return runCatching {
            val resp = api().getConversationDetail(username, characterId, null, mode)
            if (resp.isSuccessful) {
                val body = resp.body()
                val convsCount = body?.conversations?.size ?: 0
                val hasSingle = body?.conversation != null
                top.ponychat.webview.util.DebugLog.d(TAG, "[HistoryDebug] API getConversationDetail: convsCount=$convsCount hasSingleConv=$hasSingle mode=$mode")
                when {
                    body?.conversations.isNullOrEmpty().not() -> {
                        val convs = body!!.conversations!!
                        top.ponychat.webview.util.DebugLog.d(TAG, "[HistoryDebug] API using body.conversations: ${convs.map { it.id.take(24) }}")
                        convs.map { it.withVisibleMessages() }
                    }
                    body?.conversation != null -> {
                        val conv = body.conversation
                        top.ponychat.webview.util.DebugLog.d(TAG, "[HistoryDebug] API using body.conversation (single): ${conv.id.take(24)}")
                        listOf(conv.withVisibleMessages())
                    }
                    (mode == "galgame" || mode == "galgame_lock") && !body?.messages.isNullOrEmpty() -> {
                        val msgs = body!!.messages!!.visibleForClient()
                        listOf(ConversationDetailData(id = characterId, messages = msgs))
                    }
                    else -> {
                        top.ponychat.webview.util.DebugLog.d(TAG, "[HistoryDebug] API returning emptyList (no convs, no single)")
                        emptyList()
                    }
                }
            } else {
                top.ponychat.webview.util.DebugLog.d(TAG, "[HistoryDebug] API getConversationDetail failed: code=${resp.code()}")
                throw Exception("加载对话列表失败 (${resp.code()})")
            }
        }
    }

    /** 删除某对话 */
    suspend fun deleteConversation(username: String, characterId: String, conversationId: String): Result<Unit> {
        return runCatching {
            api().deleteConversation(
                DeleteConversationRequest(username, characterId, conversationId)
            )
            Unit
        }.also { result ->
            if (result.isFailure) Log.w(TAG, "deleteConversation failed: ${result.exceptionOrNull()?.message}")
        }
    }

    suspend fun hideMessage(
        username: String,
        characterId: String,
        conversationId: String,
        messageId: String
    ): Result<Unit> {
        return runCatching {
            val resp = api().hideMessage(
                HideMessageRequest(
                    username = username,
                    characterId = characterId,
                    conversationId = conversationId,
                    messageId = messageId,
                    reason = "user_hide_message"
                )
            )
            if (!resp.isSuccessful) throw Exception("delete message failed (${resp.code()})")
            val body = resp.body()
            if (body != null && body.success == false) throw Exception(body.message ?: "delete message failed")
            Unit
        }.also { result ->
            if (result.isFailure) Log.w(TAG, "hideMessage failed: ${result.exceptionOrNull()?.message}")
        }
    }

    /** 更新用户资料（需传当前密码以通过后端验证） */
    suspend fun updateUserProfile(
        username: String,
        currentPassword: String,
        nickname: String?,
        bio: String?,
        personalSetting: String?,
        speciesPreset: String?,
        speciesCustom: String?,
        birthDate: String?,
        shareWithAi: Boolean?,
        avatarDataUrl: String?
    ): Result<Unit> {
        return runCatching {
            val resp = api().updateUserProfile(
                UpdateProfileRequest(
                    username = username,
                    currentPassword = currentPassword.ifBlank { null },
                    nickname = nickname,
                    bio = bio,
                    personalSetting = personalSetting,
                    speciesPreset = speciesPreset,
                    speciesCustom = speciesCustom,
                    birthDate = birthDate,
                    shareWithAi = shareWithAi,
                    avatar = avatarDataUrl
                )
            )
            if (!resp.isSuccessful) {
                val body = resp.errorBody()?.string() ?: ""
                val msg = try {
                    gson.fromJson(body, JsonObject::class.java)?.get("detail")?.takeIf { it.isJsonPrimitive }?.getAsString()
                } catch (e: Exception) {
                    top.ponychat.webview.util.DebugLog.w("CharRepo", "parse error body failed: ${e.message}", e)
                    null
                }
                throw Exception(msg ?: body.ifBlank { "保存失败" })
            }
            Unit
        }
    }

    suspend fun drawImage(
        prompt: String,
        resolution: String,
        aspectRatio: String,
        referenceImage: String? = null,
        contextMessages: List<DrawContextMessage> = emptyList()
    ): Result<String> {
        return runCatching {
            val resp = api().drawImage(
                DrawRequest(
                    prompt = prompt,
                    resolution = resolution,
                    aspectRatio = aspectRatio,
                    referenceImage = referenceImage,
                    contextMessages = contextMessages
                )
            )
            val body = resp.body() ?: throw Exception("绘图响应为空")
            val content = body.choices.firstOrNull()?.message?.content ?: ""
            if (content.isBlank()) throw Exception(body.error ?: "绘图失败：未返回内容")
            content
        }
    }

    suspend fun summarizeContext(
        username: String,
        characterId: String,
        mode: String,
        conversationId: String?,
        force: Boolean = false
    ): Result<Map<String, Any?>> {
        return runCatching {
            val body = mutableMapOf<String, Any?>(
                "username" to username,
                "character_id" to characterId,
                "mode" to mode,
                "conversation_id" to conversationId
            )
            if (force) body["force"] = true
            val resp = api().summarizeContext(body)
            if (!resp.isSuccessful) throw Exception("总结失败 (${resp.code()})")
            resp.body() ?: emptyMap()
        }
    }

    suspend fun resetGalgame(username: String, characterId: String, mode: String): Result<Unit> {
        return runCatching {
            val base = prefs.effectiveApiBase().trimEnd('/')
            val url = "$base/api/galgame/reset"
            val gameType = if (mode == "galgame_lock") "galgame_lock" else "galgame"
            val body = mapOf(
                "username" to username,
                "character_id" to characterId,
                "game_type" to gameType
            )
            val req = Request.Builder()
                .url(url)
                .post(gson.toJson(body).toRequestBody("application/json".toMediaType()))
                .addHeader("Content-Type", "application/json")
                .build()
            NetworkClient.okHttpClient.newCall(req).execute().use { _ -> Unit }
        }
    }

    suspend fun updateSecurity(
        username: String,
        currentPassword: String,
        newUsername: String?,
        newPassword: String?
    ): Result<String?> {
        return runCatching {
            val resp = api().updateSecurity(
                SecurityUpdateRequest(
                    username = username,
                    currentPassword = currentPassword,
                    newUsername = newUsername?.takeIf { it.isNotBlank() },
                    newPassword = newPassword?.takeIf { it.isNotBlank() }
                )
            )
            if (!resp.isSuccessful) throw Exception("安全设置更新失败 (${resp.code()})")
            val body = resp.body()
            if (body?.success != true) throw Exception(body?.message ?: "安全设置更新失败")
            body.authToken?.takeIf { it.isNotBlank() }?.let { prefs.authToken = it }
            body.username?.takeIf { it.isNotBlank() }
        }
    }

    /**
     * 从服务端加载用户设置（GET /api/user/settings），对齐 Web 端 auth.js 登录后读取设置的逻辑。
     * 返回 `settings` 字段的原始 Map，供功能级设置读取；大模型调用参数由后端统一管理。
     */
    suspend fun loadUserSettings(username: String): Result<Map<String, Any?>> {
        return runCatching {
            val resp = api().getSettings(username)
            if (!resp.isSuccessful) throw Exception("加载用户设置失败 (${resp.code()})")
            val body = resp.body() ?: emptyMap<String, Any?>()
            // Web 端结构：{ settings: {...}, username: "..." }
            @Suppress("UNCHECKED_CAST")
            (body["settings"] as? Map<String, Any?>) ?: body
        }
    }

    /**
     * 将本地设置同步到服务端（POST /api/user/settings），对齐 Web 端 settings.js saveSettingsToLocal 后的云端同步逻辑。
     * body 格式：{ username, settings: {...} }。不要从 App 同步大模型采样、推理或输出上限参数。
     */
    suspend fun saveUserSettings(username: String, settingsMap: Map<String, Any>): Result<Unit> {
        return runCatching {
            api().saveSettings(mapOf("username" to username, "settings" to settingsMap))
            Unit
        }.also {
            if (it.isFailure) Log.w(TAG, "saveUserSettings failed: ${it.exceptionOrNull()?.message}")
        }
    }
}
