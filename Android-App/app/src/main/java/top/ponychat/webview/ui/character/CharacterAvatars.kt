package top.ponychat.webview.ui.character

import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.ui.common.PonyAvatar

@Composable
fun UserAvatar(
    avatarUrl: String,
    name: String,
    apiBase: String = "",
    fallbackApiBase: String = "",
    size: Int = 40
) {
    PonyAvatar(
        avatarUrl = avatarUrl,
        name = name,
        apiBase = apiBase,
        fallbackApiBase = fallbackApiBase,
        size = size
    )
}

@Composable
fun CharacterAvatar(
    avatarUrl: String,
    name: String,
    apiBase: String = "",
    fallbackApiBase: String = "",
    size: Int = 48,
    modifier: Modifier = Modifier
) {
    PonyAvatar(
        avatarUrl = avatarUrl,
        name = name,
        apiBase = apiBase,
        fallbackApiBase = fallbackApiBase,
        size = size,
        modifier = modifier
    )
}

fun pickFallbackApiBase(activeBase: String, wanUrl: String, lanUrl: String): String {
    val active = AppPreferences.normalizeApiBaseUrl(activeBase).trimEnd('/')
    val wan = AppPreferences.normalizeApiBaseUrl(wanUrl).trimEnd('/')
    val lan = AppPreferences.normalizeApiBaseUrl(lanUrl).trimEnd('/')
    return when {
        active.isBlank() -> wan.ifBlank { lan }
        active == wan -> lan
        active == lan -> wan
        wan.isNotBlank() && wan != active -> wan
        lan.isNotBlank() && lan != active -> lan
        else -> ""
    }
}
