package top.ponychat.webview.ui.auth

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import top.ponychat.webview.data.model.UserInfo
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.ConnectionService
import top.ponychat.webview.data.api.SyncWebSocketManager
import top.ponychat.webview.util.NotificationTrace
import top.ponychat.webview.data.repo.AuthRepository
import top.ponychat.webview.util.DebugLog
import top.ponychat.webview.util.toUserMessage
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Locale

data class AuthState(
    val isLoading: Boolean = false,
    val error: String? = null,
    val success: Boolean = false
)

class AuthViewModel(application: Application) : AndroidViewModel(application) {

    private val prefs = AppPreferences(application)
    private val repo = AuthRepository(prefs)

    private val _loginState = MutableStateFlow(AuthState())
    val loginState: StateFlow<AuthState> = _loginState.asStateFlow()

    private val _registerState = MutableStateFlow(AuthState())
    val registerState: StateFlow<AuthState> = _registerState.asStateFlow()

    fun login(username: String, password: String, onSuccess: (UserInfo) -> Unit) {
        if (username.isBlank() || password.isBlank()) {
            _loginState.value = AuthState(error = "请填写用户名和密码")
            return
        }
        viewModelScope.launch {
            _loginState.value = AuthState(isLoading = true)
            val result = repo.login(username.trim(), password)
            result.fold(
                onSuccess = { loginResp ->
                    val user = loginResp.user ?: return@fold
                    loginResp.authToken?.takeIf { it.isNotBlank() }?.let { prefs.authToken = it }
                    prefs.username = user.username
                    prefs.gender = user.gender
                    // 登录成功后主动拉取用户资料（头像、昵称等）
                    repo.getProfile(user.username).onSuccess { profile ->
                        prefs.nickname = profile.nickname
                        prefs.avatar = profile.avatar
                        prefs.userBio = profile.bio.orEmpty()
                    }
                    NotificationTrace.log("auth", "login_ok bind_ctx+pull+conn_svc")
                    SyncWebSocketManager.bindNotificationContext(getApplication())
                    // 登录成功即刻补拉（不等服务 onStart），缓解新安装后首条回复仅存在 outbox、列表未读滞后
                    SyncWebSocketManager.pullUndeliveredOnce(prefs, "auth_login")
                    ConnectionService.start(getApplication())
                    _loginState.value = AuthState(success = true)
                    onSuccess(user)
                },
                onFailure = { err ->
                    DebugLog.w("AuthVM", "login failed: ${err.message}", err)
                    _loginState.value = AuthState(error = err.toUserMessage("登录失败，请稍后重试"))
                }
            )
        }
    }

    fun register(
        username: String,
        password: String,
        confirmPassword: String,
        gender: String,
        birthDate: String,
        inviteCode: String,
        avatar: String? = null,
        onSuccess: () -> Unit
    ) {
        if (username.isBlank() || password.isBlank() || birthDate.isBlank() || inviteCode.isBlank()) {
            _registerState.value = AuthState(error = "请填写所有必填项")
            return
        }
        val name = username.trim()
        val usernameRegex = Regex("^[a-zA-Z0-9_\\u4e00-\\u9fa5]{2,20}$")
        if (!usernameRegex.matches(name)) {
            _registerState.value = AuthState(error = "用户名需为2-20位，支持字母/数字/中文/下划线")
            return
        }
        if (password != confirmPassword) {
            _registerState.value = AuthState(error = "两次密码不一致")
            return
        }
        if (password.length < 4) {
            _registerState.value = AuthState(error = "密码不少于4位")
            return
        }
        if (!isAdult(birthDate)) {
            _registerState.value = AuthState(error = "未满18岁禁止注册")
            return
        }
        viewModelScope.launch {
            _registerState.value = AuthState(isLoading = true)
            val result = repo.register(
                username = name,
                password = password,
                gender = gender,
                birthDate = birthDate,
                inviteCode = inviteCode.trim(),
                avatar = avatar
            )
            result.fold(
                onSuccess = {
                    _registerState.value = AuthState(success = true)
                    onSuccess()
                },
                onFailure = { err ->
                    DebugLog.w("AuthVM", "register failed: ${err.message}", err)
                    _registerState.value = AuthState(error = err.toUserMessage("注册失败，请稍后重试"))
                }
            )
        }
    }

    fun clearLoginError() {
        _loginState.value = _loginState.value.copy(error = null)
    }

    /** 退出登录时调用，清除上次登录留下的 success=true，防止返回登录页时 LoadingOverlay 误显示 */
    fun clearLoginState() {
        _loginState.value = AuthState()
    }

    fun clearRegisterError() {
        _registerState.value = _registerState.value.copy(error = null)
    }

    private fun isAdult(birthDate: String): Boolean {
        return try {
            val parser = SimpleDateFormat("yyyy-MM-dd", Locale.US)
            parser.isLenient = false
            val birth = parser.parse(birthDate) ?: return false
            val b = Calendar.getInstance().apply { time = birth }
            val t = Calendar.getInstance()
            var age = t.get(Calendar.YEAR) - b.get(Calendar.YEAR)
            if (
                t.get(Calendar.MONTH) < b.get(Calendar.MONTH) ||
                (t.get(Calendar.MONTH) == b.get(Calendar.MONTH) && t.get(Calendar.DAY_OF_MONTH) < b.get(Calendar.DAY_OF_MONTH))
            ) {
                age--
            }
            age >= 18
        } catch (e: Exception) {
            DebugLog.w("AuthVM", "isAdult parse birthDate failed: ${e.message}", e)
            false
        }
    }
}
