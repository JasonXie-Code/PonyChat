package top.ponychat.webview.ui.chinesechess

import android.os.Build
import android.os.Bundle
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.SideEffect
import androidx.compose.ui.graphics.luminance
import androidx.core.view.WindowCompat
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.data.repo.ChatRepository
import top.ponychat.webview.data.repo.MinigameRepository
import top.ponychat.webview.ui.common.SystemNavigationBarColorEffect
import top.ponychat.webview.ui.theme.PonyChatTheme

class ChineseChessActivity : ComponentActivity() {
    companion object {
        const val EXTRA_CHARACTER_NAME = "character_name"
        const val EXTRA_CHARACTER_AVATAR = "character_avatar"
        const val EXTRA_CHARACTER_SUPPORTS_VOICE = "character_supports_voice"
        const val EXTRA_CHARACTER_ID = "character_id"
        const val EXTRA_CONVERSATION_ID = "conversation_id"
        const val EXTRA_USERNAME = "username"
        const val EXTRA_USER_NAME = "user_name"
        const val EXTRA_USER_AVATAR = "user_avatar"
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val prefs = AppPreferences(this)
        val characterName = intent.getStringExtra(EXTRA_CHARACTER_NAME)
            ?.takeIf { it.isNotBlank() }
            ?: "对手"
        val characterAvatar = intent.getStringExtra(EXTRA_CHARACTER_AVATAR).orEmpty()
        val characterSupportsVoice = intent.getBooleanExtra(EXTRA_CHARACTER_SUPPORTS_VOICE, false)
        val characterId = intent.getStringExtra(EXTRA_CHARACTER_ID).orEmpty()
        val conversationId = intent.getStringExtra(EXTRA_CONVERSATION_ID).orEmpty()
        val username = intent.getStringExtra(EXTRA_USERNAME)
            ?.takeIf { it.isNotBlank() }
            ?: prefs.username
        val userName = intent.getStringExtra(EXTRA_USER_NAME)
            ?.takeIf { it.isNotBlank() }
            ?: prefs.nickname.ifBlank { prefs.username }.ifBlank { "我" }
        val userAvatar = intent.getStringExtra(EXTRA_USER_AVATAR).orEmpty().ifBlank { prefs.avatar }
        val apiBase = prefs.effectiveApiBase()
        val minigameRepository = MinigameRepository(prefs)
        val chatRepository = ChatRepository(prefs)
        WindowCompat.setDecorFitsSystemWindows(window, false)
        window.statusBarColor = android.graphics.Color.TRANSPARENT
        window.setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_NOTHING)
        enableEdgeToEdge()
        setContent {
            PonyChatTheme(darkTheme = prefs.isDarkTheme, fontScale = prefs.fontScale) {
                val systemBarColor = MaterialTheme.colorScheme.surface
                val useDarkSystemIcons = systemBarColor.luminance() > 0.5f
                SideEffect {
                    val w = this@ChineseChessActivity.window
                    WindowCompat.getInsetsController(w, w.decorView)
                        .isAppearanceLightStatusBars = useDarkSystemIcons
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                        w.isStatusBarContrastEnforced = false
                    }
                }
                SystemNavigationBarColorEffect(
                    color = systemBarColor,
                    useDarkIcons = useDarkSystemIcons,
                    restoreOnDispose = true
                )
                ChineseChessScreen(
                    characterName = characterName,
                    characterAvatar = characterAvatar,
                    characterSupportsVoice = characterSupportsVoice,
                    username = username,
                    characterId = characterId,
                    conversationId = conversationId,
                    userName = userName,
                    userAvatar = userAvatar,
                    apiBase = apiBase,
                    minigameRepository = minigameRepository,
                    chatRepository = chatRepository,
                    onBack = { finish() }
                )
            }
        }
    }
}
