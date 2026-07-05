package top.ponychat.webview.data.prefs

import android.content.Context
import android.content.SharedPreferences
import androidx.core.content.edit
import java.net.URI

class AppPreferences(context: Context) {

    private val prefs: SharedPreferences =
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    init {
        // 从旧版本升级且已登录/有用户名：视为已完成首次引导，避免强弹一批权限
        if (!prefs.contains(KEY_INITIAL_STARTUP_PERMISSIONS_DONE)) {
            val returning = prefs.getString(KEY_AUTH_TOKEN, "")?.isNotEmpty() == true ||
                prefs.getString(KEY_USERNAME, "")?.isNotEmpty() == true
            if (returning) {
                prefs.edit { putBoolean(KEY_INITIAL_STARTUP_PERMISSIONS_DONE, true) }
            }
        }
    }

    companion object {
        private const val PREFS_NAME = "ponychat_prefs"
        private const val KEY_USERNAME = "username"
        private const val KEY_GENDER = "gender"
        private const val KEY_NICKNAME = "nickname"
        private const val KEY_AVATAR = "avatar"
        private const val KEY_USER_BIO = "user_bio"
        private const val KEY_LAN_URL = "last_lan_url"
        private const val KEY_WAN_URL = "wan_url"
        private const val KEY_THEME = "theme"
        private const val KEY_FONT_SCALE = "font_scale"
        private const val KEY_CHAT_MODE = "chat_mode"
        private const val KEY_LAST_CHARACTER_ID = "last_character_id"
        private const val KEY_LAST_CONVERSATION_ID = "last_conversation_id"
        private const val KEY_ROUTE_MODE = "route_mode"
        private const val KEY_WAN_URLS_CUSTOM = "wan_urls_custom"
        private const val KEY_CHAT_TEMPERATURE = "chat_temperature"
        private const val KEY_CHAT_MAX_TOKENS = "chat_max_tokens"
        private const val KEY_CHAT_TOP_P = "chat_top_p"
        private const val KEY_CHAT_REPEAT_PENALTY = "chat_repeat_penalty"
        private const val KEY_CHAT_TOP_K = "chat_top_k"
        private const val KEY_REASONING_EFFORT = "reasoning_effort"
        private const val KEY_AUTH_TOKEN = "auth_token"
        private const val KEY_ACTIVE_API_BASE = "active_api_base"
        private const val KEY_VOICE_LANG = "voice_lang"
        private const val KEY_SHOW_TIMESTAMP = "show_timestamp"
        private const val KEY_CHARACTER_SORT = "character_sort"
        private const val KEY_PINNED_CHARACTERS = "pinned_characters"
        private const val KEY_MY_PUBLISHED_HALL_NOTICE_DISMISSED = "my_published_hall_notice_dismissed"

        // 合规
        private const val KEY_AI_DISCLAIMER_SHOWN = "ai_disclaimer_shown"
        private const val KEY_MEMORY_ENABLED = "memory_enabled"
        private const val KEY_CRISIS_HOTLINE_ENABLED = "crisis_hotline_enabled"

        // 主动消息
        private const val KEY_PROACTIVE_MESSAGES_ENABLED = "proactive_messages_enabled"
        private const val KEY_PROACTIVE_FREQUENCY = "proactive_frequency"
        private const val KEY_MESSAGE_VIBRATION_ENABLED = "message_vibration_enabled"

        // 陪玩卡片
        private const val KEY_COMPANION_CARD_X = "companion_card_x"
        private const val KEY_COMPANION_CARD_Y = "companion_card_y"
        private const val KEY_COMPANION_CARD_WIDTH = "companion_card_width"
        private const val KEY_COMPANION_CARD_FONT_SIZE = "companion_card_font_size"
        private const val KEY_COMPANION_CARD_TEXT_COLOR = "companion_card_text_color"
        private const val KEY_COMPANION_CARD_MAX_CHARS = "companion_card_max_chars"
        private const val KEY_COMPANION_CARD_ALPHA = "companion_card_alpha"
        private const val KEY_COMPANION_VOICE_ENABLED = "companion_voice_enabled"

        // 会员等级缓存
        private const val KEY_MEMBERSHIP_TYPE = "membership_type"

        /** 角色卡未读条数 JSON：key = "charId#mode" → count */
        private const val KEY_UNREAD_MAP_JSON = "unread_map_json"
        private const val KEY_CHAT_IME_LIFT_PREFIX = "chat_ime_lift_px_"

        // 调试模式
        private const val KEY_DEBUG_MODE = "debug_mode"
        private const val KEY_DEBUG_SHOW_MESSAGE_IDS = "debug_show_message_ids"
        private const val KEY_DEBUG_DISABLE_IME_SCROLL = "debug_disable_ime_scroll"
        private const val KEY_DEBUG_SHOW_RAW_CONTENT = "debug_show_raw_content"
        private const val KEY_DEBUG_FORCE_ALWAYS_USER_EDIT = "debug_force_always_user_edit"
        private const val KEY_DEBUG_WEAK_NETWORK_CYCLE = "debug_weak_network_cycle"
        private const val KEY_DEBUG_WEAK_NETWORK_CYCLE_STARTED_AT = "debug_weak_network_cycle_started_at"

        /** 首次启动是否已完成「运行时权限批量申请」（不含无障碍与悬浮窗） */
        private const val KEY_INITIAL_STARTUP_PERMISSIONS_DONE = "initial_startup_permissions_done"

        /** 首次通知权限授权后是否已引导用户检查渠道设置（声音/振动/悬浮） */
        private const val KEY_NOTIFICATION_CHANNEL_GUIDE_DONE = "notification_channel_guide_done"

        /** 版本更新弹窗最后一次弹出的日期（格式：YYYY-MM-DD），用于每日最多弹一次的限流 */
        private const val KEY_UPDATE_DIALOG_LAST_DATE = "update_dialog_last_date"

        const val DEFAULT_WAN_URL = "https://www.ponychat.org"

        /** 固定公网域名。旧版多公网与内网直连配置不再参与 Android 端连接。 */
        val WAN_CANDIDATES_FOR_SPEED_TEST: List<String> = listOf(
            "https://www.ponychat.org"
        )

        /**
         * 去掉站点根末尾多余的 `/api`。
         * Retrofit [top.ponychat.webview.data.api.ApiService] 的路径已写成 `api/...`，
         * base 必须是 **站点根**（如 `https://192.168.x.x:5001`），若误填 `.../api` 会请求 `/api/api/...` 导致 404。
         */
        private fun stripTrailingApiPathSuffix(url: String): String {
            var u = url.trim().trimEnd('/')
            while (u.length > 4 && u.endsWith("/api", ignoreCase = true)) {
                u = u.dropLast(4).trimEnd('/')
            }
            return u
        }

        /**
         * 补全无 scheme 的 API 根地址，供 Retrofit/OkHttp 使用。
         * 用户常输入 `192.168.x.x:5001`；内网 TLS 代理固定为 5001 → 默认 **https**，其余端口默认 **http**。
         */
        fun normalizeApiBaseUrl(raw: String): String {
            val s = raw.trim()
            if (s.isEmpty()) return ""
            val resolved = if (s.startsWith("http://", ignoreCase = true) || s.startsWith("https://", ignoreCase = true)) {
                s.trimEnd('/')
            } else {
                val bare = bareHostPortToAbsoluteUrl(s) ?: s.trimEnd('/')
                bare.trimEnd('/')
            }
            return stripTrailingApiPathSuffix(resolved)
        }

        /**
         * 将完整 http(s) 站点根解析为「IPv4:端口」或「[IPv6]:端口」，供局域网偏好存储与输入框展示。
         */
        private fun absoluteHttpUrlToHostPort(absoluteUrl: String): String? {
            val s = absoluteUrl.trim().trimEnd('/')
            if (s.isEmpty()) return null
            return try {
                val uri = URI(s)
                val scheme = uri.scheme?.lowercase() ?: return null
                if (scheme != "http" && scheme != "https") return null
                val host = uri.host ?: return null
                val port = when {
                    uri.port > 0 -> uri.port
                    scheme == "https" -> 443
                    else -> 80
                }
                if (host.contains(':')) "[$host]:$port" else "$host:$port"
            } catch (_: Exception) {
                null
            }
        }

        /**
         * 将已保存的局域网配置（完整 URL 或 IP:端口）转为输入框展示的「IP:端口」（兼容旧版存完整 URL）。
         */
        fun lanStoredToHostPortInput(stored: String): String {
            val t = stored.trim()
            if (t.isEmpty()) return ""
            val abs = normalizeApiBaseUrl(t).trimEnd('/')
            if (abs.isEmpty()) return t
            return absoluteHttpUrlToHostPort(abs)
                ?: if (bareHostPortToAbsoluteUrl(t) != null) t.trimEnd('/') else t
        }

        /**
         * 将用户在局域网输入框中的内容规范为偏好存储形式（仅 IP:端口）。
         * 仍接受粘贴完整 http(s) 站点根，会拆解为 IP:端口。
         */
        fun normalizeLanInputToStored(raw: String): String {
            val t = raw.trim()
            if (t.isEmpty()) return ""
            val abs = normalizeApiBaseUrl(t).trimEnd('/')
            if (abs.isEmpty()) return t
            val hostPort = absoluteHttpUrlToHostPort(abs)
            if (hostPort != null) return hostPort
            return if (bareHostPortToAbsoluteUrl(t) != null) t.trimEnd('/') else t.trimEnd('/')
        }

        private fun bareHostPortToAbsoluteUrl(s: String): String? {
            if (s.startsWith("[")) {
                val closing = s.indexOf(']')
                if (closing <= 0 || closing >= s.length - 2 || s[closing + 1] != ':') return null
                val port = s.substring(closing + 2).toIntOrNull() ?: return null
                val host = s.substring(0, closing + 1)
                val scheme = if (port == 5001) "https" else "http"
                return "$scheme://$host:$port"
            }
            val idx = s.lastIndexOf(':')
            if (idx <= 0 || idx >= s.length - 1) return null
            val portStr = s.substring(idx + 1)
            if (!portStr.all { it.isDigit() }) return null
            val port = portStr.toIntOrNull() ?: return null
            val host = s.substring(0, idx)
            if (host.isBlank() || host.contains(' ')) return null
            val scheme = if (port == 5001) "https" else "http"
            return "$scheme://$host:$port"
        }
    }

    /** 兼容旧字段：Android 端不再使用自定义公网列表。 */
    var wanUrlsCustom: String
        get() = ""
        set(value) = prefs.edit { putString(KEY_WAN_URLS_CUSTOM, "") }

    /** 获取所有在用的公网地址（内置候选 + 用户自定义，去重） */
    fun allWanUrls(): List<String> {
        return listOf(DEFAULT_WAN_URL)
    }

    /**
     * 首次冷启动是否已展示过「相机/麦克风/位置/通知」批量引导。
     * 不含无障碍与悬浮窗；升级用户若已有账号会在 init 中自动置为 true。
     */
    var initialStartupPermissionsDone: Boolean
        get() = prefs.getBoolean(KEY_INITIAL_STARTUP_PERMISSIONS_DONE, false)
        set(value) = prefs.edit { putBoolean(KEY_INITIAL_STARTUP_PERMISSIONS_DONE, value) }

    var notificationChannelGuideDone: Boolean
        get() = prefs.getBoolean(KEY_NOTIFICATION_CHANNEL_GUIDE_DONE, false)
        set(value) = prefs.edit { putBoolean(KEY_NOTIFICATION_CHANNEL_GUIDE_DONE, value) }

    var myPublishedHallNoticeDismissed: Boolean
        get() = prefs.getBoolean(KEY_MY_PUBLISHED_HALL_NOTICE_DISMISSED, false)
        set(value) = prefs.edit { putBoolean(KEY_MY_PUBLISHED_HALL_NOTICE_DISMISSED, value) }

    /** 版本更新弹窗最后弹出的日期（"YYYY-MM-DD"，空字符串表示从未弹过） */
    var updateDialogLastDate: String
        get() = prefs.getString(KEY_UPDATE_DIALOG_LAST_DATE, "") ?: ""
        set(value) = prefs.edit { putString(KEY_UPDATE_DIALOG_LAST_DATE, value) }

    var aiDisclaimerShown: Boolean
        get() = prefs.getBoolean(KEY_AI_DISCLAIMER_SHOWN, false)
        set(value) = prefs.edit { putBoolean(KEY_AI_DISCLAIMER_SHOWN, value) }

    var memoryEnabled: Boolean
        get() = prefs.getBoolean(KEY_MEMORY_ENABLED, true)
        set(value) = prefs.edit { putBoolean(KEY_MEMORY_ENABLED, value) }

    var crisisHotlineEnabled: Boolean
        get() = prefs.getBoolean(KEY_CRISIS_HOTLINE_ENABLED, true)
        set(value) = prefs.edit { putBoolean(KEY_CRISIS_HOTLINE_ENABLED, value) }

    /** 角色主动消息总开关（默认开启） */
    var proactiveMessagesEnabled: Boolean
        get() = prefs.getBoolean(KEY_PROACTIVE_MESSAGES_ENABLED, true)
        set(value) = prefs.edit { putBoolean(KEY_PROACTIVE_MESSAGES_ENABLED, value) }

    /** 主动消息频率：low / normal / high（默认 normal） */
    var proactiveFrequency: String
        get() = prefs.getString(KEY_PROACTIVE_FREQUENCY, "normal") ?: "normal"
        set(value) = prefs.edit { putString(KEY_PROACTIVE_FREQUENCY, value) }

    /** 消息震动提醒：收到一个普通气泡或一个游戏/锁分回合时短震两下。 */
    var messageVibrationEnabled: Boolean
        get() = prefs.getBoolean(KEY_MESSAGE_VIBRATION_ENABLED, true)
        set(value) = prefs.edit { putBoolean(KEY_MESSAGE_VIBRATION_ENABLED, value) }

    var authToken: String
        get() = prefs.getString(KEY_AUTH_TOKEN, "") ?: ""
        set(value) = prefs.edit { putString(KEY_AUTH_TOKEN, value) }

    var username: String
        get() = prefs.getString(KEY_USERNAME, "") ?: ""
        set(value) = prefs.edit { putString(KEY_USERNAME, value) }

    var gender: String
        get() = prefs.getString(KEY_GENDER, "male") ?: "male"
        set(value) = prefs.edit { putString(KEY_GENDER, value) }

    var nickname: String
        get() = prefs.getString(KEY_NICKNAME, "") ?: ""
        set(value) = prefs.edit { putString(KEY_NICKNAME, value) }

    var avatar: String
        get() = prefs.getString(KEY_AVATAR, "") ?: ""
        set(value) = prefs.edit { putString(KEY_AVATAR, value) }

    var userBio: String
        get() = prefs.getString(KEY_USER_BIO, "") ?: ""
        set(value) = prefs.edit { putString(KEY_USER_BIO, value) }

    var lanUrl: String
        get() = ""
        set(value) = prefs.edit { putString(KEY_LAN_URL, "") }

    var wanUrl: String
        get() = DEFAULT_WAN_URL
        set(value) = prefs.edit { putString(KEY_WAN_URL, DEFAULT_WAN_URL) }

    var isDarkTheme: Boolean
        get() = prefs.getBoolean(KEY_THEME, true)
        set(value) = prefs.edit { putBoolean(KEY_THEME, value) }

    var fontScale: Float
        get() = prefs.getFloat(KEY_FONT_SCALE, 1.0f)
        set(value) = prefs.edit { putFloat(KEY_FONT_SCALE, value.coerceIn(0.85f, 1.25f)) }

    /** 聊天 / 游戏 / 锁分 模式，与后端 `mode` 字段一致。 */
    var chatMode: String
        get() = prefs.getString(KEY_CHAT_MODE, "normal") ?: "normal"
        set(value) {
            prefs.edit { putString(KEY_CHAT_MODE, value) }
        }

    var lastCharacterId: String
        get() = prefs.getString(KEY_LAST_CHARACTER_ID, "") ?: ""
        set(value) = prefs.edit { putString(KEY_LAST_CHARACTER_ID, value) }

    var lastConversationId: String
        get() = prefs.getString(KEY_LAST_CONVERSATION_ID, "") ?: ""
        set(value) = prefs.edit { putString(KEY_LAST_CONVERSATION_ID, value) }

    var routeMode: String
        get() = "wan"
        set(value) = prefs.edit { putString(KEY_ROUTE_MODE, "wan") }

    var activeApiBase: String
        get() = prefs.getString(KEY_ACTIVE_API_BASE, DEFAULT_WAN_URL) ?: DEFAULT_WAN_URL
        set(value) = prefs.edit {
            putString(KEY_ACTIVE_API_BASE, normalizeApiBaseUrl(value).ifBlank { DEFAULT_WAN_URL })
        }

    var voiceLang: String
        get() = prefs.getString(KEY_VOICE_LANG, "auto") ?: "auto"
        set(value) = prefs.edit { putString(KEY_VOICE_LANG, value.ifBlank { "auto" }) }

    var chatTemperature: Float
        get() = prefs.getFloat(KEY_CHAT_TEMPERATURE, 0.7f)
        set(value) = prefs.edit { putFloat(KEY_CHAT_TEMPERATURE, value.coerceIn(0f, 2f)) }

    var chatMaxTokens: Int
        get() = prefs.getInt(KEY_CHAT_MAX_TOKENS, 1024)
        set(value) = prefs.edit { putInt(KEY_CHAT_MAX_TOKENS, value.coerceIn(64, 8192)) }

    var chatTopP: Float
        get() = prefs.getFloat(KEY_CHAT_TOP_P, 0.9f)
        set(value) = prefs.edit { putFloat(KEY_CHAT_TOP_P, value.coerceIn(0f, 1f)) }

    var chatRepeatPenalty: Float
        get() = prefs.getFloat(KEY_CHAT_REPEAT_PENALTY, 1.1f)
        set(value) = prefs.edit { putFloat(KEY_CHAT_REPEAT_PENALTY, value.coerceIn(1f, 2f)) }

    var chatTopK: Int
        get() = prefs.getInt(KEY_CHAT_TOP_K, 40)
        set(value) = prefs.edit { putInt(KEY_CHAT_TOP_K, value.coerceIn(1, 200)) }

    var reasoningEffort: String
        get() = prefs.getString(KEY_REASONING_EFFORT, "medium") ?: "medium"
        set(value) = prefs.edit { putString(KEY_REASONING_EFFORT, value) }

    var showTimestamp: Boolean
        get() = prefs.getBoolean(KEY_SHOW_TIMESTAMP, true)
        set(value) = prefs.edit { putBoolean(KEY_SHOW_TIMESTAMP, value) }

    /** 角色列表排序方式：last_chat（最近对话，默认）/ name（名称）/ custom（服务端顺序） */
    var characterSort: String
        get() = prefs.getString(KEY_CHARACTER_SORT, "last_chat") ?: "last_chat"
        set(value) = prefs.edit { putString(KEY_CHARACTER_SORT, value) }

    /** 置顶角色 ID 集合（本地偏好，不同步服务端） */
    var pinnedCharacterIds: Set<String>
        get() = prefs.getStringSet(KEY_PINNED_CHARACTERS, emptySet()) ?: emptySet()
        set(value) = prefs.edit { putStringSet(KEY_PINNED_CHARACTERS, value) }

    // ==================== 模式专属最后对话时间 ====================

    /**
     * 读取指定角色在指定模式（normal / galgame / galgame_lock）下的最后对话毫秒时间戳。
     * 返回 0 表示该模式下从未对话过。
     */
    fun getModeLastChatTime(characterId: String, mode: String): Long =
        prefs.getLong("mlct_${mode}_${characterId}", 0L)

    /**
     * 记录指定角色在指定模式下的最后对话时间（默认当前时间）。
     * 在进入角色对话时调用，确保三种模式的排序互相独立。
     */
    fun setModeLastChatTime(characterId: String, mode: String, timeMs: Long = System.currentTimeMillis()) =
        prefs.edit { putLong("mlct_${mode}_${characterId}", timeMs) }

    /** 清除指定角色在指定模式下的时间戳（恢复为"无记录"状态）。 */
    fun clearModeLastChatTime(characterId: String, mode: String) =
        prefs.edit { remove("mlct_${mode}_${characterId}") }

    // ==================== 模式专属列表第二行摘要（无本地会话缓存时的回退）====================

    private fun modeLastChatSnippetKey(characterId: String, mode: String) = "mlcs_${mode}_${characterId}"

    /** 角色列表第二行：该模式下最近一条助手摘要的纯文本缓存（已去 MD/HTML）。 */
    fun getModeLastChatSnippet(characterId: String, mode: String): String =
        prefs.getString(modeLastChatSnippetKey(characterId, mode), "").orEmpty()

    fun setModeLastChatSnippet(characterId: String, mode: String, snippet: String) {
        val s = snippet.trim().take(400)
        prefs.edit {
            if (s.isEmpty()) remove(modeLastChatSnippetKey(characterId, mode))
            else putString(modeLastChatSnippetKey(characterId, mode), s)
        }
    }

    fun clearModeLastChatSnippet(characterId: String, mode: String) =
        prefs.edit { remove(modeLastChatSnippetKey(characterId, mode)) }

    /** 清空本地对话缓存时同步清除各模式下的列表摘要缓存（与 [LocalCacheStore.clearAll] 配合）。 */
    fun clearAllModeLastChatSnippets() {
        val keys = prefs.all.keys.filter { it.startsWith("mlcs_") }
        if (keys.isEmpty()) return
        prefs.edit {
            for (k in keys) remove(k)
        }
    }

    /** 清空本地对话缓存时同步清除摘要和最近对话时间，避免隐藏旧内容继续影响排序。 */
    fun clearAllModeLastChatState() {
        val keys = prefs.all.keys.filter { it.startsWith("mlcs_") || it.startsWith("mlct_") }
        if (keys.isEmpty()) return
        prefs.edit {
            for (k in keys) remove(k)
        }
    }

    /** 读取角色×模式未读条数（仅 >0 的条目会序列化）。 */
    fun readUnreadMap(): Map<String, Int> {
        val raw = prefs.getString(KEY_UNREAD_MAP_JSON, "") ?: return emptyMap()
        if (raw.isBlank()) return emptyMap()
        return try {
            val jo = org.json.JSONObject(raw)
            buildMap {
                val it = jo.keys()
                while (it.hasNext()) {
                    val k = it.next()
                    val v = jo.optInt(k, 0)
                    if (v > 0) put(k, v)
                }
            }
        } catch (_: Exception) {
            emptyMap()
        }
    }

    fun writeUnreadMap(map: Map<String, Int>) {
        val jo = org.json.JSONObject()
        for ((k, v) in map) {
            if (v > 0) jo.put(k, v)
        }
        prefs.edit { putString(KEY_UNREAD_MAP_JSON, jo.toString()) }
    }

    fun cachedChatImeLiftPx(windowKey: String): Int =
        prefs.getInt(KEY_CHAT_IME_LIFT_PREFIX + windowKey, 0).coerceAtLeast(0)

    fun setCachedChatImeLiftPx(windowKey: String, value: Int) {
        prefs.edit { putInt(KEY_CHAT_IME_LIFT_PREFIX + windowKey, value.coerceAtLeast(0)) }
    }

    /**
     * 回填迁移版本号：用于检测是否需要重新执行回填逻辑。
     * 每次更改回填算法时递增此版本号，触发全量重新校验。
     */
    var backfillVersion: Int
        get() = prefs.getInt("backfill_version", 0)
        set(v) = prefs.edit { putInt("backfill_version", v) }

    // ==================== 陪玩卡片 ====================

    /** 卡片上次拖动后的 X 坐标（像素），-1 表示使用默认位置 */
    var companionCardX: Int
        get() = prefs.getInt(KEY_COMPANION_CARD_X, -1)
        set(value) = prefs.edit { putInt(KEY_COMPANION_CARD_X, value) }

    /** 卡片上次拖动后的 Y 坐标（像素），-1 表示使用默认位置 */
    var companionCardY: Int
        get() = prefs.getInt(KEY_COMPANION_CARD_Y, -1)
        set(value) = prefs.edit { putInt(KEY_COMPANION_CARD_Y, value) }

    /** 卡片宽度档位：small / medium（默认）/ large */
    var companionCardWidth: String
        get() = prefs.getString(KEY_COMPANION_CARD_WIDTH, "medium") ?: "medium"
        set(value) = prefs.edit { putString(KEY_COMPANION_CARD_WIDTH, value) }

    /** 卡片字号档位：small / medium（默认）/ large / xlarge */
    var companionCardFontSize: String
        get() = prefs.getString(KEY_COMPANION_CARD_FONT_SIZE, "medium") ?: "medium"
        set(value) = prefs.edit { putString(KEY_COMPANION_CARD_FONT_SIZE, value) }

    /** 卡片文字颜色：white（默认）/ yellow / cyan */
    var companionCardTextColor: String
        get() = prefs.getString(KEY_COMPANION_CARD_TEXT_COLOR, "white") ?: "white"
        set(value) = prefs.edit { putString(KEY_COMPANION_CARD_TEXT_COLOR, value) }

    /** 卡片回复最大字数：10 / 20（默认）/ 30 / 40 / 50 */
    var companionCardMaxChars: Int
        get() = prefs.getInt(KEY_COMPANION_CARD_MAX_CHARS, 20)
        set(value) = prefs.edit { putInt(KEY_COMPANION_CARD_MAX_CHARS, value.coerceIn(10, 50)) }

    fun registerChangeListener(listener: SharedPreferences.OnSharedPreferenceChangeListener) =
        prefs.registerOnSharedPreferenceChangeListener(listener)

    fun unregisterChangeListener(listener: SharedPreferences.OnSharedPreferenceChangeListener) =
        prefs.unregisterOnSharedPreferenceChangeListener(listener)

    /** 卡片背景透明度 0-100（默认 80，对应约 87% 不透明） */
    var companionCardAlpha: Int
        get() = prefs.getInt(KEY_COMPANION_CARD_ALPHA, 80)
        set(value) = prefs.edit { putInt(KEY_COMPANION_CARD_ALPHA, value.coerceIn(10, 100)) }

    /** AI 语音播报开关（默认开启） */
    var companionVoiceEnabled: Boolean
        get() = prefs.getBoolean(KEY_COMPANION_VOICE_ENABLED, true)
        set(value) = prefs.edit { putBoolean(KEY_COMPANION_VOICE_ENABLED, value) }

    // ==================== 调试模式 ====================

    /** 调试模式总开关：开启后在对话设置中显示调试板块 */
    var debugMode: Boolean
        get() = prefs.getBoolean(KEY_DEBUG_MODE, false)
        set(value) = prefs.edit { putBoolean(KEY_DEBUG_MODE, value) }

    /** 在消息气泡下方显示消息内部 ID（调试用） */
    var debugShowMessageIds: Boolean
        get() = prefs.getBoolean(KEY_DEBUG_SHOW_MESSAGE_IDS, false)
        set(value) = prefs.edit { putBoolean(KEY_DEBUG_SHOW_MESSAGE_IDS, value) }

    /** 禁用键盘弹起时的自动滚动到底部 */
    var debugDisableImeScroll: Boolean
        get() = prefs.getBoolean(KEY_DEBUG_DISABLE_IME_SCROLL, false)
        set(value) = prefs.edit { putBoolean(KEY_DEBUG_DISABLE_IME_SCROLL, value) }

    /** 显示原始消息内容（不渲染 Markdown，直接展示纯文本） */
    var debugShowRawContent: Boolean
        get() = prefs.getBoolean(KEY_DEBUG_SHOW_RAW_CONTENT, false)
        set(value) = prefs.edit { putBoolean(KEY_DEBUG_SHOW_RAW_CONTENT, value) }

    /** 强制所有保存操作使用 user_edit 意图（绕过防误删检测） */
    var debugForceAlwaysUserEdit: Boolean
        get() = prefs.getBoolean(KEY_DEBUG_FORCE_ALWAYS_USER_EDIT, false)
        set(value) = prefs.edit { putBoolean(KEY_DEBUG_FORCE_ALWAYS_USER_EDIT, value) }

    /** 调试弱网：5 秒联网、5 秒断网循环。 */
    var debugWeakNetworkCycle: Boolean
        get() = prefs.getBoolean(KEY_DEBUG_WEAK_NETWORK_CYCLE, false)
        set(value) = prefs.edit {
            val wasEnabled = prefs.getBoolean(KEY_DEBUG_WEAK_NETWORK_CYCLE, false)
            putBoolean(KEY_DEBUG_WEAK_NETWORK_CYCLE, value)
            if (value && !wasEnabled) {
                putLong(KEY_DEBUG_WEAK_NETWORK_CYCLE_STARTED_AT, System.currentTimeMillis())
            }
        }

    fun isDebugWeakNetworkOffline(nowMs: Long = System.currentTimeMillis()): Boolean {
        if (!debugWeakNetworkCycle) return false
        val startedAt = prefs.getLong(KEY_DEBUG_WEAK_NETWORK_CYCLE_STARTED_AT, nowMs)
        val elapsed = (nowMs - startedAt).coerceAtLeast(0L)
        return ((elapsed / 5_000L) % 2L) == 1L
    }

    /** 上次从服务端获取的会员等级（free / pro / pro_plus / developer / admin）*/
    var membershipType: String
        get() = prefs.getString(KEY_MEMBERSHIP_TYPE, "free") ?: "free"
        set(value) = prefs.edit { putString(KEY_MEMBERSHIP_TYPE, value) }

    fun isLoggedIn() = username.isNotBlank()

    /**
     * 本地检测 authToken 是否仍有效（未过期）。
     * 解析 payload 中的 exp（秒），不做签名验证（签名验证在服务端）。
     * - 后端 PonyChat token 为两段：`payloadBase64.signatureBase64`，exp 在第一段；
     * - 若将来使用标准 JWT 三段：`header.payload.signature`，exp 在第二段。
     * 返回 false 表示 token 为空、格式错误或已过期，需重新登录。
     */
    fun isTokenValid(): Boolean {
        val token = authToken
        if (token.isBlank() || !token.contains('.')) return false
        return try {
            val parts = token.trim().split(".")
            val payloadB64 = when (parts.size) {
                2 -> parts[0]
                3 -> parts[1]
                else -> return false
            }
            val padding = "=".repeat((4 - payloadB64.length % 4) % 4)
            val payloadJson = String(
                android.util.Base64.decode(payloadB64 + padding, android.util.Base64.URL_SAFE),
                Charsets.UTF_8
            )
            val jo = org.json.JSONObject(payloadJson)
            if (!jo.has("exp")) return false
            val exp = jo.getLong("exp")
            System.currentTimeMillis() / 1000 < exp
        } catch (e: Exception) {
            false
        }
    }

    fun logout() {
        prefs.edit {
            remove(KEY_USERNAME)
            remove(KEY_GENDER)
            remove(KEY_NICKNAME)
            remove(KEY_AVATAR)
            remove(KEY_USER_BIO)
            remove(KEY_AUTH_TOKEN)
            remove(KEY_LAST_CHARACTER_ID)
            remove(KEY_LAST_CONVERSATION_ID)
            remove(KEY_MEMBERSHIP_TYPE)
        }
    }

    /** 重置显示与聊天相关设置为默认（保留登录、头像、昵称、服务器地址） */
    fun resetDisplayAndChatSettings() {
        prefs.edit {
            putBoolean(KEY_THEME, true)
            putFloat(KEY_FONT_SCALE, 1.0f)
            putString(KEY_ROUTE_MODE, "auto")
            putString(KEY_ACTIVE_API_BASE, "")
            putString(KEY_CHAT_MODE, "normal")
            putString(KEY_LAST_CHARACTER_ID, "")
            putString(KEY_LAST_CONVERSATION_ID, "")
            putFloat(KEY_CHAT_TEMPERATURE, 0.7f)
            putInt(KEY_CHAT_MAX_TOKENS, 1024)
            putFloat(KEY_CHAT_TOP_P, 0.9f)
            putFloat(KEY_CHAT_REPEAT_PENALTY, 1.1f)
            putInt(KEY_CHAT_TOP_K, 40)
            putString(KEY_REASONING_EFFORT, "medium")
            putBoolean(KEY_SHOW_TIMESTAMP, true)
            putString(KEY_VOICE_LANG, "auto")
        }
    }

    /** 获取当前有效 API Base URL（支持 auto / lan / wan 路由模式） */
    fun effectiveApiBase(): String {
        if (debugMode) {
            val override = normalizeApiBaseUrl(activeApiBase)
            if (override.isNotBlank() && override != DEFAULT_WAN_URL) return override
        }
        return DEFAULT_WAN_URL
    }
}
