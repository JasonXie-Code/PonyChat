package top.ponychat.webview.ui.chat

import top.ponychat.webview.data.model.Character
import top.ponychat.webview.data.model.ChatSettings
import top.ponychat.webview.data.model.MemoryItem
import top.ponychat.webview.data.model.Message
import top.ponychat.webview.data.model.QuickMessage
import top.ponychat.webview.data.model.QuotedMessage
import top.ponychat.webview.data.model.RelationshipPageContent
import top.ponychat.webview.data.model.StickerAsset

data class ChatUiState(
    val messages: List<Message> = emptyList(),
    val inputText: String = "",
    val isStreaming: Boolean = false,
    val error: String? = null,
    val character: Character? = null,
    val conversationId: String? = null,
    val isLoadingHistory: Boolean = false,
    val isLoadingMoreHistory: Boolean = false,
    /** 本地缓存已展示，正在后台静默拉取服务端最新数据 */
    val isBackgroundRefreshing: Boolean = false,
    val voiceState: VoiceState = VoiceState.Idle,
    val conversations: List<ConversationSummary> = emptyList(),
    val isLoadingConversations: Boolean = false,
    val chatSettings: ChatSettings = ChatSettings(),
    val mode: String = "normal",
    val isSummarizingContext: Boolean = false,
    val contextUsedTokens: Int = 0,
    val contextLimitTokens: Int = 64000,
    /** 游戏/锁分模式当前好感度 (0-100)，与 Web galgameScores 一致 */
    val galgameScore: Int? = null,
    /** 服务端持久：已向用户展示过满分庆祝弹窗 */
    val galgameVictoryCelebrationAck: Boolean = false,
    /** 游戏/锁分 SSE 分步生成时顶部栏副标题文案，非生成中为 null */
    val galgameStreamingStep: String? = null,
    /** 历史对话排序：timestamp(活跃时间) | created(创建时间) | length(对话字数) */
    val historySortField: String = "timestamp",
    /** 历史对话排序顺序：desc | asc */
    val historySortOrder: String = "desc",
    /** Galgame 进度保存失败时为 true，用于显示提示弹窗 */
    val galgameSaveFailed: Boolean = false,
    /** 错误调试信息（code/detail），用于快速定位线上问题 */
    val errorDebug: String? = null,
    /** 回复计时器和重试次数统计 */
    val replyTimer: Long = 0,
    val retryCount: Int = 0,
    val isTimerRunning: Boolean = false,
    /** 懒加载：当前最小已加载 sequence_number（初始 MAX，向上翻页时递减） */
    val minLoadedSeq: Int = Int.MAX_VALUE,
    /** 懒加载：是否还有更早的历史消息可加载 */
    val hasMoreHistory: Boolean = false,
    /** 今日配额已用尽（HTTP 429 quota_exceeded） */
    val quotaExceeded: Boolean = false,
    val quotaExceededMessage: String = "",
    /** 当前配额详情（调试面板展示用，由 loadQuotaForDebug 填充） */
    val quotaInfo: top.ponychat.webview.data.model.QuotaInfo? = null,
    /** 锁分模式实时生命体征（galgame_lock 专属，其他模式为空） */
    val lockCharVitals: Map<String, Int> = emptyMap(),
    val lockCharMood: Map<String, Int> = emptyMap(),
    val lockOrganFill: Map<String, Int> = emptyMap(),
    /** 锁分模式角色性别（"雌性"/"雄性"，决定器官面板展示子宫或精巢） */
    val lockCharGender: String = "",
    /** 锁分模式体征变化量（最近一次 AI 回复前后的差值，面板角标展示用） */
    val lockCharVitalsDelta: Map<String, Int> = emptyMap(),
    val lockCharMoodDelta: Map<String, Int> = emptyMap(),
    val lockOrganFillDelta: Map<String, Int> = emptyMap(),
    /** 消息导出分享模式 */
    val isExportMode: Boolean = false,
    val exportSelectedIds: Set<String> = emptySet(),
    val quotedMessage: QuotedMessage? = null,
    val quickMessages: List<QuickMessage> = emptyList(),
    val isLoadingQuickMessages: Boolean = false,
    val stickers: List<StickerAsset> = emptyList(),
    val isLoadingStickers: Boolean = false,
    val relationshipSnapshot: RelationshipSnapshot? = null,
    val relationshipStageOverride: String? = null,
    val hasLoadedRelationshipSnapshot: Boolean = false,
    val isLoadingRelationshipSnapshot: Boolean = false,
    val relationshipSnapshotError: String? = null
)

data class RelationshipSnapshot(
    val characterId: String,
    val conversationId: String?,
    val stageKey: String = "uncertain",
    val stageLabel: String,
    val conversationCount: Int,
    val currentMessageCount: Int,
    val totalMessageCount: Int,
    val memoryCount: Int,
    val relationshipMemories: List<MemoryItem> = emptyList(),
    val preferenceMemories: List<MemoryItem> = emptyList(),
    val episodeMemories: List<MemoryItem> = emptyList(),
    val activityMemories: List<MemoryItem> = emptyList(),
    val summaryMemories: List<MemoryItem> = emptyList(),
    val latestSummary: String = "",
    val updatedAt: String = "",
    val pageContent: RelationshipPageContent? = null,
    val pageUpdatedAtMs: Long = 0L
)

data class ConversationSummary(
    val id: String,
    val title: String,
    val updatedAt: String,
    val createdAt: String = "",
    val messageCount: Int,
    val totalChars: Int = 0
)

sealed class VoiceState {
    object Idle : VoiceState()
    object Listening : VoiceState()
    data class Partial(val text: String) : VoiceState()
    object Processing : VoiceState()
}
