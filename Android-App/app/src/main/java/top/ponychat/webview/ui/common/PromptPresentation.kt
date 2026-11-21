package top.ponychat.webview.ui.common

const val PROMPT_BUBBLE_MAX_CHARS = 28

fun shouldUsePromptDialog(message: String): Boolean {
    val text = message.trim()
    return text.contains('\n') || text.codePointCount(0, text.length) > PROMPT_BUBBLE_MAX_CHARS
}
