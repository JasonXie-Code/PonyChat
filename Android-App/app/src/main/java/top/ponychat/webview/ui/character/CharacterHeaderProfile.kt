package top.ponychat.webview.ui.character

import android.content.SharedPreferences
import androidx.compose.runtime.*
import kotlinx.coroutines.delay
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.data.repo.AuthRepository

/** Refresh the list header without requiring a visit to the profile screen. */
@Composable
internal fun rememberHeaderAvatar(prefs: AppPreferences): String {
    var avatar by remember(prefs) { mutableStateOf(prefs.avatar) }
    DisposableEffect(prefs) {
        val listener = SharedPreferences.OnSharedPreferenceChangeListener { _, _ -> avatar = prefs.avatar }
        prefs.registerOnChangeListener(listener)
        onDispose { prefs.unregisterOnChangeListener(listener) }
    }
    val username = prefs.username
    LaunchedEffect(username) {
        if (username.isBlank()) return@LaunchedEffect
        repeat(2) { attempt ->
            val result = AuthRepository(prefs).getProfile(username)
            if (prefs.username != username) return@LaunchedEffect
            result.getOrNull()?.let { profile ->
                prefs.avatar = profile.avatar.orEmpty()
                prefs.nickname = profile.nickname.orEmpty().ifBlank { username }
                prefs.userBio = profile.bio.orEmpty()
                avatar = prefs.avatar
                return@LaunchedEffect
            }
            if (attempt == 0) delay(1500)
        }
    }
    return avatar
}
