package top.ponychat.webview.ui.chat

internal fun sceneInteractionLabel(value: String?): String = when (value) {
    "instant_messaging" -> "即时对话"
    "virtual_roleplay" -> "虚拟扮演"
    else -> "尚无识别记录"
}

/** Render older Agent-facing scene text with participant names; the stored evidence stays intact. */
internal fun objectiveSceneValue(value: String?, userName: String, characterName: String): String {
    if (value.isNullOrBlank()) return "未记录"
    val user = userName.trim().ifBlank { "用户" }
    val character = characterName.trim().ifBlank { "角色" }
    return Regex("你们|我们|你的|我的|你|我").replace(value.trim()) { match ->
        when (match.value) {
            "你们" -> "${user}与${character}"
            "我们" -> "${character}与${user}"
            "你的" -> "${user}的"
            "我的" -> "${character}的"
            "你" -> user
            else -> character
        }
    }
}
