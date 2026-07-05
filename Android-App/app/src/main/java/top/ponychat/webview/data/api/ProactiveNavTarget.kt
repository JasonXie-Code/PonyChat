package top.ponychat.webview.data.api

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * 通知点击导航目标。
 * MainActivity 收到携带 open_character_id / open_mode extra 的 Intent 后写入此单例；
 * AppNavigation 观察并跳转到对应角色的聊天页（按 mode 初始化），跳转完成后清空。
 */
object ProactiveNavTarget {

    data class Target(val characterId: String, val mode: String)

    private val _target = MutableStateFlow<Target?>(null)
    val target: StateFlow<Target?> = _target.asStateFlow()

    /** 兼容旧调用：仅传角色 ID 时 mode 默认 normal */
    fun set(characterId: String?, mode: String? = null) {
        val id = characterId?.takeIf { it.isNotBlank() } ?: return
        _target.value = Target(id, mode?.takeIf { it.isNotBlank() } ?: "normal")
    }

    fun clear() {
        _target.value = null
    }
}
