package top.ponychat.webview.data.api

import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.asSharedFlow

/**
 * 全局鉴权事件总线。
 * - force_logout：服务端推送"新登录顶下线"或 HTTP 返回 401，触发强制退出到登录页。
 * - upgrade_required：服务端返回 426，当前版本已停止支持，需要下载新版本。
 */
object AuthEventBus {

    private val _forceLogout = MutableSharedFlow<String>(extraBufferCapacity = 1)

    /** 订阅强制登出事件，reason 为原因字符串（如 "logged_in_elsewhere" / "token_expired"）*/
    val forceLogout: SharedFlow<String> = _forceLogout.asSharedFlow()

    fun emitForceLogout(reason: String) {
        _forceLogout.tryEmit(reason)
    }

    private val _upgradeRequired = MutableSharedFlow<Unit>(extraBufferCapacity = 1)

    /** 订阅版本升级提示事件（HTTP 426）*/
    val upgradeRequired: SharedFlow<Unit> = _upgradeRequired.asSharedFlow()

    fun emitUpgradeRequired() {
        _upgradeRequired.tryEmit(Unit)
    }
}
