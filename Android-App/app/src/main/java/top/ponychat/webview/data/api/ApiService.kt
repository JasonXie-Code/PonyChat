package top.ponychat.webview.data.api

import okhttp3.MultipartBody
import okhttp3.ResponseBody
import retrofit2.Response
import retrofit2.http.*
import top.ponychat.webview.data.model.*

interface ApiService {

    @GET("api/agent/status")
    suspend fun getAgentStatus(
        @Query("character_id") characterId: String,
        @Query("mode") mode: String,
        @Query("conversation_id") conversationId: String? = null,
    ): Response<AgentStatusResponse>

    // ==================== 认证 ====================

    @POST("api/auth/login")
    suspend fun login(@Body request: LoginRequest): Response<LoginResponse>

    @POST("api/auth/register")
    suspend fun register(@Body request: RegisterRequest): Response<ApiResponse>

    // ==================== 用户 ====================

    @GET("api/user/profile")
    suspend fun getProfile(@Query("username") username: String): Response<ProfileResponse>

    @GET("api/user/usage")
    suspend fun getUserUsage(@Query("username") username: String): Response<Map<String, Any>>

    @GET("api/user/quota")
    suspend fun getUserQuota(@Query("username") username: String): Response<Map<String, Any>>

    @GET("api/user/settings")
    suspend fun getSettings(@Query("username") username: String): Response<Map<String, Any>>

    /** Web 端调用：POST { username, settings: {...} } 同步用户设置到服务端 */
    @POST("api/user/settings")
    suspend fun saveSettings(@Body body: Map<String, @JvmSuppressWildcards Any>): Response<ApiResponse>

    // ==================== 角色 ====================

    @GET("api/quick-messages")
    suspend fun getQuickMessages(@Query("username") username: String): Response<QuickMessageListResponse>

    @POST("api/quick-messages")
    suspend fun addQuickMessage(@Body request: QuickMessageCreateRequest): Response<QuickMessage>

    @PUT("api/quick-messages/{messageId}")
    suspend fun updateQuickMessage(
        @Path("messageId") messageId: Int,
        @Body request: QuickMessageUpdateRequest
    ): Response<Map<String, Any?>>

    @HTTP(method = "DELETE", path = "api/quick-messages/{messageId}", hasBody = true)
    suspend fun deleteQuickMessage(
        @Path("messageId") messageId: Int,
        @Body request: QuickMessageDeleteRequest
    ): Response<Map<String, Any?>>

    @GET("api/load_characters")
    suspend fun loadCharacters(
        @Query("username") username: String,
        @Query("lazy") lazy: Boolean = true
    ): Response<LoadCharactersResponse>

    @POST("api/save_characters")
    suspend fun saveCharacters(@Body request: SaveCharactersRequest): Response<ApiResponse>

    // ==================== 角色大厅 ====================

    @GET("api/character-hall")
    suspend fun getCharacterHall(
        @Query("search") search: String? = null,
        @Query("username") username: String? = null
    ): Response<List<Character>>

    @GET("api/character-hall/{hallId}/likes")
    suspend fun getCharacterLikes(
        @Path("hallId") hallId: String,
        @Query("username") username: String
    ): Response<CharacterLikeResponse>

    @POST("api/character-hall/{hallId}/like")
    suspend fun likeCharacter(
        @Path("hallId") hallId: String,
        @Query("username") username: String
    ): Response<CharacterLikeResponse>

    // ==================== 对话 ====================

    @GET("api/conversation/detail")
    suspend fun getConversationDetail(
        @Query("username") username: String,
        @Query("character_id") characterId: String,
        @Query("conversation_id") conversationId: String? = null,
        @Query("mode") mode: String? = null
    ): Response<ConversationDetailResponse>

    @POST("api/galgame/victory_ack")
    suspend fun postGalgameVictoryAck(
        @Body body: Map<String, @JvmSuppressWildcards Any>
    ): Response<Map<String, Any?>>

    // ==================== 聊天（长耗时单次 JSON 响应，见 [ChatRepository.sendMessage]） ====================

    /** 返回 ResponseBody（大 body 读入；实际为单次 JSON，见 ChatRepository） */
    @POST("api/chat")
    @Streaming
    suspend fun sendChat(@Body request: ChatRequest): Response<ResponseBody>

    /** 聊天前上传图片，返回临时 /chat_images/... 转运引用（multipart 字段名 file） */
    @Multipart
    @POST("api/chat_images")
    suspend fun uploadChatImage(
        @Part file: MultipartBody.Part
    ): Response<ChatImageUploadResponse>

    /** 上传角色主页封面/相册图片，返回可长期访问的 /chat_images/... 地址 */
    @Multipart
    @POST("api/admin/characters/upload-profile-image")
    suspend fun uploadCharacterProfileImage(
        @Part file: MultipartBody.Part
    ): Response<ChatImageUploadResponse>

    /** 上传角色音色参考音频，返回 PonyChat 后端保存的 /character_voice_assets/... 短 URL */
    @Multipart
    @POST("api/character_voice/reference_audio")
    suspend fun uploadCharacterVoiceReferenceAudio(
        @Part file: MultipartBody.Part,
        @Part("transcript") transcript: okhttp3.RequestBody,
        @Part("character_id") characterId: okhttp3.RequestBody,
        @Part("voice_profile_id") voiceProfileId: okhttp3.RequestBody,
        @Part("voice_name") voiceName: okhttp3.RequestBody
    ): Response<CharacterVoiceReferenceUploadResponse>

    @POST("api/character_voice/design")
    suspend fun designCharacterVoice(
        @Body request: CharacterVoiceDesignRequest
    ): Response<CharacterVoiceDesignResponse>

    // ==================== 对话删除 ====================

    @POST("api/conversation/delete")
    suspend fun deleteConversation(@Body request: DeleteConversationRequest): Response<ApiResponse>

    // ==================== 角色数据重置（对话+陪玩，不含游戏/锁分） ====================

    @POST("api/messages/hide")
    suspend fun hideMessage(@Body request: HideMessageRequest): Response<ApiResponse>

    @POST("api/messages/voice/synthesize")
    suspend fun synthesizeMessageVoice(
        @Body body: Map<String, @JvmSuppressWildcards Any?>
    ): Response<VoiceSynthesizeResponse>

    @POST("api/messages/voice/ack")
    suspend fun ackMessageVoiceAudio(
        @Body body: Map<String, @JvmSuppressWildcards Any?>
    ): Response<ApiResponse>

    @POST("api/character/reset_chat")
    suspend fun resetCharacterChat(@Body request: ResetCharacterChatRequest): Response<ResetCharacterChatResponse>

    // ==================== 用户资料更新 ====================

    @POST("api/user/profile")
    suspend fun updateUserProfile(@Body request: UpdateProfileRequest): Response<ApiResponse>

    @POST("api/draw")
    suspend fun drawImage(@Body request: DrawRequest): Response<DrawResponse>

    @POST("api/conversation/summarize_context")
    suspend fun summarizeContext(@Body body: Map<String, @JvmSuppressWildcards Any?>): Response<Map<String, Any?>>

    // ==================== 小游戏 ====================

    @POST("api/minigames/xiangqi/prepare")
    suspend fun prepareXiangqi(@Body request: XiangqiPrepareRequest): Response<XiangqiPrepareResponse>

    @POST("api/minigames/xiangqi/execute")
    suspend fun executeXiangqi(@Body request: XiangqiExecuteRequest): Response<XiangqiExecuteResponse>

    @POST("api/minigames/xiangqi/memory")
    suspend fun commitXiangqiMemory(@Body request: XiangqiMemoryCommitRequest): Response<Map<String, Any?>>

    @POST("api/user/security-update")
    suspend fun updateSecurity(@Body request: SecurityUpdateRequest): Response<ApiResponse>

    // ==================== 网络探测 ====================

    @GET("api/connection-info")
    suspend fun getConnectionInfo(): Response<ConnectionInfo>

    @GET("api/status")
    suspend fun getStatus(): Response<Map<String, Any>>

    // ==================== 角色大厅添加 ====================

    @POST("api/character-hall/{hallId}/add")
    suspend fun addCharacterFromHall(
        @Path("hallId") hallId: String,
        @Query("username") username: String
    ): Response<Map<String, Any?>>

    // ==================== 角色大厅编辑（发布者编辑大厅版本） ====================

    @PUT("api/character-hall/{hallId}")
    suspend fun editHallCharacter(
        @Path("hallId") hallId: String,
        @Query("username") username: String,
        @Body body: Map<String, @JvmSuppressWildcards Any?>
    ): Response<Map<String, Any?>>

    // ==================== 角色发布/取消发布 ====================

    @POST("api/characters/{characterId}/publish")
    suspend fun publishCharacter(
        @Path("characterId") characterId: String,
        @Query("username") username: String
    ): Response<Map<String, Any?>>

    @DELETE("api/characters/{characterId}/unpublish")
    suspend fun unpublishCharacter(
        @Path("characterId") characterId: String,
        @Query("username") username: String
    ): Response<ApiResponse>

    @POST("api/chat/cancel")
    suspend fun cancelChat(@Body body: Map<String, String>): Response<ApiResponse>

    @POST("api/chat/sticker")
    suspend fun sendStickerChat(@Body request: ChatRequest): Response<Map<String, Any?>>

    @GET("api/assets/stickers")
    suspend fun getStickers(
        @Query("source") source: String = "all",
        @Query("category") category: String = "all",
        @Query("page") page: Int = 1,
        @Query("page_size") pageSize: Int = 60
    ): Response<StickerListResponse>

    @Multipart
    @POST("api/assets/stickers/upload")
    suspend fun uploadSticker(
        @Part file: MultipartBody.Part,
        @Part("name") name: okhttp3.RequestBody,
        @Part("intro") intro: okhttp3.RequestBody,
        @Part("detail") detail: okhttp3.RequestBody,
        @Part("image_text") imageText: okhttp3.RequestBody,
        @Part("custom_tags") customTags: okhttp3.RequestBody
    ): Response<StickerSaveResponse>

    @POST("api/assets/stickers/save")
    suspend fun saveSticker(@Body request: StickerSaveRequest): Response<StickerSaveResponse>

    @DELETE("api/assets/stickers/{stickerId}")
    suspend fun deleteSticker(@Path("stickerId") stickerId: String): Response<ApiResponse>

    // ==================== 推送 outbox（未送达 / ACK） ====================

    @GET("api/messages/undelivered")
    suspend fun getUndeliveredMessages(): Response<Map<String, Any?>>

    @POST("api/messages/ack")
    suspend fun ackOutbox(@Body body: Map<String, @JvmSuppressWildcards Any>): Response<Map<String, Any?>>

    // ==================== 长期记忆 ====================

    @GET("api/memory")
    suspend fun getMemories(
        @Query("username") username: String,
        @Query("character_id") characterId: String,
        @Query("memory_type") memoryType: String? = null,
        @Query("layer") layer: Int? = null
    ): Response<top.ponychat.webview.data.model.MemoryListResponse>

    @POST("api/memory")
    suspend fun addMemory(
        @Body request: top.ponychat.webview.data.model.AddMemoryRequest
    ): Response<top.ponychat.webview.data.model.MemoryItem>

    @PUT("api/memory/{memoryId}")
    suspend fun updateMemory(
        @Path("memoryId") memoryId: Int,
        @Body request: top.ponychat.webview.data.model.UpdateMemoryRequest
    ): Response<Map<String, @JvmSuppressWildcards Any>>

    @HTTP(method = "DELETE", path = "api/memory/{memoryId}", hasBody = true)
    suspend fun deleteMemory(
        @Path("memoryId") memoryId: Int,
        @Body request: top.ponychat.webview.data.model.DeleteMemoryRequest
    ): Response<Map<String, @JvmSuppressWildcards Any>>

    // ==================== 关系状态 ====================

    @GET("api/relationship/state")
    suspend fun getRelationshipState(
        @Query("username") username: String,
        @Query("character_id") characterId: String
    ): Response<top.ponychat.webview.data.model.RelationshipStateResponse>

    @POST("api/relationship/refresh")
    suspend fun refreshRelationshipState(
        @Body request: top.ponychat.webview.data.model.RelationshipRefreshRequest
    ): Response<top.ponychat.webview.data.model.RelationshipStateResponse>

    @POST("api/relationship/state")
    suspend fun updateRelationshipControl(
        @Body request: top.ponychat.webview.data.model.RelationshipControlRequest
    ): Response<top.ponychat.webview.data.model.RelationshipStateResponse>

    // ==================== 陪玩历史 ====================

    @GET("api/companion/sessions")
    suspend fun getCompanionSessions(
        @Query("username") username: String,
        @Query("character_id") characterId: String,
        @Query("limit") limit: Int = 50
    ): Response<top.ponychat.webview.data.model.CompanionSessionsResponse>

    @GET("api/companion/sessions/{sessionId}/messages")
    suspend fun getCompanionSessionMessages(
        @Path("sessionId") sessionId: String,
        @Query("username") username: String
    ): Response<top.ponychat.webview.data.model.CompanionSessionMessagesResponse>

    @DELETE("api/companion/sessions/{sessionId}")
    suspend fun deleteCompanionSession(
        @Path("sessionId") sessionId: String,
        @Query("username") username: String
    ): Response<top.ponychat.webview.data.model.ApiResponse>

    // ==================== 消息全文搜索 ====================

    @GET("api/messages/search")
    suspend fun searchMessages(
        @Query("username") username: String,
        @Query("character_id") characterId: String,
        @Query("query") query: String,
        @Query("sender") sender: String = "all",
        @Query("date_from") dateFrom: Long? = null,
        @Query("date_to") dateTo: Long? = null,
        @Query("limit") limit: Int = 20,
        @Query("offset") offset: Int = 0
    ): Response<top.ponychat.webview.data.model.MessageSearchResponse>

    @GET("api/messages/count")
    suspend fun countVisibleMessages(
        @Query("username") username: String,
        @Query("character_id") characterId: String
    ): Response<top.ponychat.webview.data.model.MessageCountResponse>

    // ==================== 版本更新 ====================

    @GET("api/app/version")
    suspend fun getAppVersion(): Response<top.ponychat.webview.data.model.AppVersionResponse>

    // ==================== 分页加载消息 ====================

    @GET("api/conversation/messages")
    suspend fun getConversationMessagesPaged(
        @Query("username") username: String,
        @Query("character_id") characterId: String,
        @Query("conversation_id") conversationId: String? = null,
        @Query("before_seq") beforeSeq: Int? = null,
        @Query("after_seq") afterSeq: Int? = null,
        @Query("sender") sender: String = "all",
        @Query("date_from") dateFrom: Long? = null,
        @Query("date_to") dateTo: Long? = null,
        @Query("limit") limit: Int = 50,
        @Query("message_id") messageId: String? = null,
    ): Response<top.ponychat.webview.data.model.PagedMessagesResponse>

    // ==================== 定时任务 ====================

    @GET("api/proactive/tasks")
    suspend fun listProactiveTasks(
        @Query("character_id") characterId: String,
        @Query("include_auto") includeAuto: Boolean = false
    ): Response<top.ponychat.webview.data.model.ProactiveTaskListResponse>

    @POST("api/proactive/tasks")
    suspend fun createProactiveTask(
        @Body body: top.ponychat.webview.data.model.ProactiveTaskRequest
    ): Response<top.ponychat.webview.data.model.ProactiveTaskMutationResponse>

    @PUT("api/proactive/tasks/{taskId}")
    suspend fun updateProactiveTask(
        @Path("taskId") taskId: String,
        @Body body: top.ponychat.webview.data.model.ProactiveTaskRequest
    ): Response<top.ponychat.webview.data.model.ProactiveTaskMutationResponse>

    @DELETE("api/proactive/tasks/{taskId}")
    suspend fun deleteProactiveTask(
        @Path("taskId") taskId: String
    ): Response<top.ponychat.webview.data.model.ProactiveTaskMutationResponse>
}
