package top.ponychat.companion.reply

import android.content.Context

data class CompanionSession(
    val apiBase: String,
    val username: String,
    val authToken: String,
    val characterId: String,
    val personalityStyle: String,
) {
    val isReady: Boolean
        get() = apiBase.startsWith("http") && username.isNotBlank() &&
            authToken.isNotBlank() && characterId.isNotBlank()
}

object CompanionSessionStore {
    private const val PREFERENCES = "companion_session"
    private const val KEY_API_BASE = "api_base"
    private const val KEY_USERNAME = "username"
    private const val KEY_AUTH_TOKEN = "auth_token"
    private const val KEY_CHARACTER_ID = "character_id"
    private const val KEY_PERSONALITY_STYLE = "personality_style"

    @Volatile
    var current: CompanionSession? = null
        private set

    @Synchronized
    fun initialize(context: Context) {
        if (current != null) return
        val preferences = context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)
        val restored = CompanionSession(
            apiBase = preferences.getString(KEY_API_BASE, "").orEmpty(),
            username = preferences.getString(KEY_USERNAME, "").orEmpty(),
            authToken = preferences.getString(KEY_AUTH_TOKEN, "").orEmpty(),
            characterId = preferences.getString(KEY_CHARACTER_ID, "").orEmpty(),
            personalityStyle = preferences.getString(KEY_PERSONALITY_STYLE, "canonical")
                .orEmpty()
                .ifBlank { "canonical" },
        )
        current = restored.takeIf(CompanionSession::isReady)
    }

    @Synchronized
    fun configure(context: Context, session: CompanionSession) {
        if (!session.isReady) {
            clear(context)
            return
        }
        val normalized = session.copy(
            apiBase = session.apiBase.trimEnd('/'),
            username = session.username.trim(),
            characterId = session.characterId.trim(),
            personalityStyle = session.personalityStyle.trim().ifBlank { "canonical" },
        )
        check(
            context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)
                .edit()
                .putString(KEY_API_BASE, normalized.apiBase)
                .putString(KEY_USERNAME, normalized.username)
                .putString(KEY_AUTH_TOKEN, normalized.authToken)
                .putString(KEY_CHARACTER_ID, normalized.characterId)
                .putString(KEY_PERSONALITY_STYLE, normalized.personalityStyle)
                .commit(),
        ) { "Unable to persist Companion session" }
        current = normalized
    }

    @Synchronized
    fun clear(context: Context) {
        context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE).edit().clear().commit()
        current = null
    }
}
