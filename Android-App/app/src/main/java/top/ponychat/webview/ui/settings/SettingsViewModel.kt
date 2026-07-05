package top.ponychat.webview.ui.settings

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import top.ponychat.webview.data.local.LocalCacheStore
import top.ponychat.webview.data.local.LocalStorageStats
import top.ponychat.webview.data.api.NetworkQualityCenter
import top.ponychat.webview.data.model.QuotaInfo
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.data.repo.AuthRepository
import top.ponychat.webview.data.repo.CharacterRepository
import top.ponychat.webview.util.DebugLog
import top.ponychat.webview.util.toUserMessage

data class UserUsageStats(
    val inputTokens: Long = 0,
    val outputTokens: Long = 0,
    val totalTokens: Long = 0
)

data class SettingsUiState(
    val nickname: String = "",
    val bio: String = "",
    val personalSetting: String = "",
    val speciesPreset: String = "人类",
    val speciesCustom: String = "",
    val birthDate: String = "",
    val shareWithAi: Boolean = true,
    val avatar: String = "",
    val networkType: String = "未知",
    val pingMs: Long? = null,
    val recommendation: String? = null,
    val isTestingNetwork: Boolean = false,
    val isSaving: Boolean = false,
    val saveError: String? = null,
    val saveSuccess: String? = null,
    val usageStats: UserUsageStats? = null,
    val isLoadingUsage: Boolean = false,
    val quotaInfo: QuotaInfo? = null,
    val isLoadingQuota: Boolean = false,
    val storageStats: LocalStorageStats? = null,
    val isLoadingStorage: Boolean = false
)

class SettingsViewModel(application: Application) : AndroidViewModel(application) {

    private val _uiState = MutableStateFlow(SettingsUiState())
    val uiState: StateFlow<SettingsUiState> = _uiState.asStateFlow()

    private lateinit var prefs: AppPreferences
    private lateinit var authRepo: AuthRepository
    private lateinit var charRepo: CharacterRepository
    private var syncObserverAttached = false
    private var networkObserverAttached = false

    fun init(prefs: AppPreferences) {
        if (::prefs.isInitialized) return
        this.prefs = prefs
        this.authRepo = AuthRepository(prefs)
        this.charRepo = CharacterRepository(prefs)
        _uiState.value = _uiState.value.copy(
            nickname = prefs.nickname,
            bio = prefs.userBio,
            avatar = prefs.avatar
        )
        attachSyncObserver()
        attachNetworkObserver()
    }

    fun resetSettings() {
        if (!::prefs.isInitialized) return
        prefs.resetDisplayAndChatSettings()
    }

    fun clearCache() {
        LocalCacheStore(getApplication()).clearAll()
        prefs.clearAllModeLastChatState()
        _uiState.value = _uiState.value.copy(storageStats = LocalStorageStats())
    }

    fun loadStorageStats() {
        if (!::prefs.isInitialized || prefs.username.isBlank()) return
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(isLoadingStorage = true)
            val stats = kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) {
                LocalCacheStore(getApplication()).getStorageStats(prefs.username)
            }
            _uiState.value = _uiState.value.copy(storageStats = stats, isLoadingStorage = false)
        }
    }

    fun loadUserUsage() {
        // 与 loadQuota 一致：不以本地 isTokenValid 拦截；服务端鉴权，避免误判导致用量/订阅永不拉取
        if (!::prefs.isInitialized || prefs.username.isBlank() || prefs.authToken.isBlank()) return
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(isLoadingUsage = true)
            authRepo.getUserUsage(prefs.username).onSuccess { usage ->
                val inp = (usage["input_tokens"] as? Number)?.toLong() ?: 0L
                val out = (usage["output_tokens"] as? Number)?.toLong() ?: 0L
                val total = (usage["total_tokens"] as? Number)?.toLong() ?: (inp + out)
                _uiState.value = _uiState.value.copy(
                    usageStats = UserUsageStats(
                        inputTokens = inp,
                        outputTokens = out,
                        totalTokens = total
                    ),
                    isLoadingUsage = false
                )
            }.onFailure {
                _uiState.value = _uiState.value.copy(usageStats = null, isLoadingUsage = false)
            }
        }
    }

    fun loadQuota() {
        if (!::prefs.isInitialized || prefs.username.isBlank() || prefs.authToken.isBlank()) return
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(isLoadingQuota = true)
            runCatching {
                authRepo.getUserQuota(prefs.username)
            }.onSuccess { result ->
                result.onSuccess { data ->
                    val rawType = data["membership_type"] ?: data["membershipType"]
                    val mType = when (rawType) {
                        is String -> rawType.trim().ifBlank { "free" }
                        null -> "free"
                        else -> rawType.toString().trim().ifBlank { "free" }
                    }
                    val rawLabel = data["membership_label"] ?: data["membershipLabel"]
                    val mLabel = when (rawLabel) {
                        is String -> rawLabel.ifBlank { "免费" }
                        null -> "免费"
                        else -> rawLabel.toString().ifBlank { "免费" }
                    }
                    val info = QuotaInfo(
                        membershipType  = mType,
                        membershipLabel = mLabel,
                        dailyLimit      = (data["daily_limit"]  as? Number)?.toInt() ?: 100,
                        usedToday       = (data["used_today"]   as? Number)?.toInt() ?: 0,
                        remaining       = (data["remaining"]    as? Number)?.toInt() ?: 100,
                        expireAt        = (data["expire_at"] ?: data["expireAt"]) as? String
                    )
                    // 缓存会员等级到本地，供其他页面（如角色编辑页）直接读取
                    prefs.membershipType = info.membershipType
                    _uiState.value = _uiState.value.copy(quotaInfo = info, isLoadingQuota = false)
                }.onFailure {
                    _uiState.value = _uiState.value.copy(isLoadingQuota = false)
                }
            }.onFailure {
                _uiState.value = _uiState.value.copy(isLoadingQuota = false)
            }
        }
    }

    fun loadProfile() {
        if (!::prefs.isInitialized) return
        viewModelScope.launch {
            authRepo.getProfile(prefs.username)
                .onSuccess { profile ->
                    // Gson 会绕过 Kotlin null-safety，后端若返回 null 字段则 JVM 层面实际为 null，
                    // 用 ?: 兜底避免 NullPointerException 触发 "加载资料失败"。
                    val safeNickname = profile.nickname ?: prefs.username
                    val safeAvatar   = profile.avatar   ?: ""
                    val safeBio      = profile.bio      ?: ""
                    val safePersonal = profile.personalSetting ?: ""
                    val safePreset   = profile.speciesPreset.takeIf { it.isNotBlank() } ?: "人类"
                    val safeCustom   = profile.speciesCustom ?: ""
                    prefs.nickname = safeNickname
                    prefs.avatar   = safeAvatar
                    prefs.userBio  = safeBio
                    _uiState.value = _uiState.value.copy(
                        nickname       = safeNickname,
                        bio            = safeBio,
                        personalSetting = safePersonal,
                        speciesPreset  = safePreset,
                        speciesCustom  = safeCustom,
                        birthDate      = profile.birthDate.orEmpty(),
                        shareWithAi    = profile.shareWithAi,
                        avatar         = safeAvatar
                    )
                }
                .onFailure { err ->
                    DebugLog.w("SettingsVM", "getProfile failed: ${err.message}", err)
                }
            detectNetworkQuality()
            loadUserUsage()
            loadQuota()
            loadStorageStats()
        }
    }

    fun detectNetworkQuality() {
        if (!::prefs.isInitialized) return
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(isTestingNetwork = true)
            val snapshot = NetworkQualityCenter.testNow(prefs)
            val connected = snapshot.pingMs != null
            _uiState.value = if (connected) {
                _uiState.value.copy(
                    networkType = snapshot.networkType,
                    pingMs = snapshot.pingMs,
                    isTestingNetwork = false,
                    saveError = null
                )
            } else {
                _uiState.value.copy(
                    networkType = snapshot.networkType,
                    pingMs = null,
                    isTestingNetwork = false,
                    saveError = "网络连接失败"
                )
            }
        }
    }

    /** 先发现 LAN 地址再全量测速，与 detectNetworkQuality 行为完全一致。 */
    fun refreshLanAndTest() = detectNetworkQuality()

    fun saveProfile(
        currentPassword: String,
        nickname: String,
        bio: String,
        personalSetting: String,
        speciesPreset: String,
        speciesCustom: String,
        birthDate: String,
        shareWithAi: Boolean,
        avatarDataUrl: String?
    ) {
        if (!::prefs.isInitialized) return
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(isSaving = true, saveError = null, saveSuccess = null)
            charRepo.updateUserProfile(
                username = prefs.username,
                currentPassword = currentPassword,
                // 发送实际值（包括空字符串），让用户能清空各字段。
                // 后端对 null 的语义是"不更新"，对 "" 是"显式清空"。
                // nickname 为空时后端 get_profile 会用 username 兜底展示。
                nickname = nickname.trim(),
                bio = bio,
                personalSetting = personalSetting,
                speciesPreset = speciesPreset.ifBlank { "人类" },
                speciesCustom = speciesCustom,
                birthDate = birthDate,
                shareWithAi = shareWithAi,
                avatarDataUrl = avatarDataUrl
            )
                .onSuccess {
                    prefs.nickname = nickname.ifBlank { prefs.username }
                    prefs.userBio = bio
                    if (!avatarDataUrl.isNullOrBlank()) {
                        prefs.avatar = avatarDataUrl
                    }
                    _uiState.value = _uiState.value.copy(
                        isSaving = false,
                        nickname = nickname,
                        bio = bio,
                        personalSetting = personalSetting,
                        speciesPreset = speciesPreset,
                        speciesCustom = speciesCustom,
                        birthDate = birthDate,
                        shareWithAi = shareWithAi,
                        saveSuccess = "资料已保存"
                    )
                    // 3秒后清除成功提示
                    kotlinx.coroutines.delay(3000)
                    _uiState.value = _uiState.value.copy(saveSuccess = null)
                }
                .onFailure { err ->
                    DebugLog.w("SettingsVM", "saveProfile failed: ${err.message}", err)
                    _uiState.value = _uiState.value.copy(
                        isSaving = false,
                        saveError = err.toUserMessage("保存失败，请稍后重试")
                    )
                }
        }
    }

    fun showSaveError(message: String) {
        _uiState.value = _uiState.value.copy(saveError = message)
    }

    fun updateSecurity(currentPassword: String, newUsername: String, newPassword: String) {
        if (!::prefs.isInitialized) return
        if (currentPassword.isBlank()) {
            _uiState.value = _uiState.value.copy(saveError = "请输入当前密码")
            return
        }
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(isSaving = true, saveError = null, saveSuccess = null)
            charRepo.updateSecurity(
                username = prefs.username,
                currentPassword = currentPassword,
                newUsername = newUsername.trim(),
                newPassword = newPassword.trim()
            ).onSuccess { maybeNewUsername ->
                if (!maybeNewUsername.isNullOrBlank() && maybeNewUsername != prefs.username) {
                    prefs.username = maybeNewUsername
                }
                _uiState.value = _uiState.value.copy(
                    isSaving = false,
                    saveSuccess = "安全设置已更新"
                )
            }.onFailure { err ->
                DebugLog.w("SettingsVM", "updateSecurity failed: ${err.message}", err)
                _uiState.value = _uiState.value.copy(
                    isSaving = false,
                    saveError = err.toUserMessage("安全设置更新失败，请稍后重试")
                )
            }
        }
    }

    /** 将 AI 后端调度相关设置同步到服务端，供后端调度器读取 */
    fun syncAiBackendSettings(memoryEnabled: Boolean, proactiveEnabled: Boolean, frequency: String) {
        if (!::charRepo.isInitialized) return
        val username = prefs.username.takeIf { it.isNotBlank() } ?: return
        val effectiveProactiveEnabled = memoryEnabled && proactiveEnabled
        viewModelScope.launch {
            charRepo.saveUserSettings(
                username,
                mapOf(
                    "memory_enabled" to memoryEnabled,
                    "proactive_messages_enabled" to effectiveProactiveEnabled,
                    "proactive_frequency" to frequency,
                )
            ).onFailure { DebugLog.w("SettingsVM", "syncAiBackendSettings failed: ${it.message}") }
        }
    }

    private fun attachSyncObserver() {
        // 单设备模式：不再订阅多端同步
    }

    private fun attachNetworkObserver() {
        if (networkObserverAttached) return
        networkObserverAttached = true
        viewModelScope.launch {
            NetworkQualityCenter.state.collectLatest { s ->
                _uiState.value = _uiState.value.copy(
                    networkType = s.networkType,
                    pingMs = s.pingMs
                )
            }
        }
    }
}
