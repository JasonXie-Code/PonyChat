package top.ponychat.webview.ui.common

/**
 * 统一解析头像 URL。
 *
 * 兼容以下输入：
 * - data URI
 * - http/https 绝对地址
 * - /api/... 相对后端根路径
 * - user_data/... / character_data/...（自动补 /api 前缀）
 * - 其他普通相对路径（拼接到 apiBase 下）
 */
/**
 * 解析头像 URL。
 *
 * 后端头像路由（system.py，无 /api 前缀）：
 *   GET /user_data/{username}/avatars/{filename}
 *   GET /character_data/avatars/{filename}
 *
 * 其他 API 路由（characters.py 等，带 /api 前缀）：
 *   GET /api/...
 */
fun resolveAvatarUrlForApi(rawAvatarUrl: String?, apiBase: String): String? {
    val base = apiBase.trim().trimEnd('/')
    val normalized = rawAvatarUrl?.trim().orEmpty()
    val lower = normalized.lowercase()
    return when {
        normalized.isBlank() -> null
        normalized.equals("null", ignoreCase = true) -> null
        // 服务端约定：default.png / assets/default.png 返回 JSON 占位，客户端应显示首字母
        lower == "default.png" || lower.endsWith("/default.png") || lower.endsWith("assets/default.png") -> null
        // data URI 直接使用
        normalized.startsWith("data:") -> normalized
        // 绝对 HTTP 地址直接使用
        normalized.startsWith("http://", ignoreCase = true) ||
            normalized.startsWith("https://", ignoreCase = true) -> normalized
        base.isBlank() -> null
        // 已经是 /api/... 相对路径
        normalized.startsWith("/api/") -> "$base$normalized"
        // 头像相对路径（system.py 路由无 /api 前缀，直接拼根路径）
        normalized.startsWith("user_data/") || normalized.startsWith("character_data/") -> "$base/$normalized"
        normalized.startsWith("/user_data/") || normalized.startsWith("/character_data/") -> "$base$normalized"
        // 其他以 / 开头的路径
        normalized.startsWith("/") -> "$base$normalized"
        // 包含路径分隔符且看起来是图片路径（含 avatars/ 或图片扩展名）
        normalized.contains('/') && (lower.contains("avatars/") || isLikelyImagePath(lower)) -> "$base/$normalized"
        // 其余情况（emoji / 纯文本等）不生成 URL，回退到首字母
        else -> null
    }
}

private fun isLikelyImagePath(pathLower: String): Boolean =
    pathLower.endsWith(".png") || pathLower.endsWith(".jpg") ||
        pathLower.endsWith(".jpeg") || pathLower.endsWith(".webp") ||
        pathLower.endsWith(".gif")
