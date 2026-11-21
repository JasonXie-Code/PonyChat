# -*- coding: utf-8 -*-
from pathlib import Path

p = Path(r"p:/PonyChat/app/app/src/main/java/top/ponychat/webview/ui/chat/ChatScreen.kt")
t = p.read_text(encoding="utf-8")
start = t.index("fun parseMessageContent(raw: String): ParsedMessageContent {")
end = t.index("private fun parseGalgameScore", start)
new = r'''/** DeepSeek 等模型使用的 `think` 围栏（\u0060 = `） */
private val THINK_FENCE = "\u0060think\u0060"

/** 去掉 think / `<thinking>` 思维块（含未闭合尾部），所有模式均不展示思维链。 */
fun stripThinkBlocksForDisplay(raw: String): String {
    var s = Regex("<think(?:ing)?>[\\s\\S]*?</think(?:ing)?>", RegexOption.IGNORE_CASE).replace(raw, "")
    val openThink = s.lastIndexOf(THINK_FENCE, ignoreCase = true)
    val openThinking = s.lastIndexOf("<thinking>", ignoreCase = true)
    val openIdx = maxOf(openThink, openThinking)
    if (openIdx >= 0) {
        val isThinkingTag = openIdx == openThinking && openThinking >= openThink
        val tagLen = if (isThinkingTag) 10 else THINK_FENCE.length
        val afterOpen = s.substring(openIdx + tagLen)
        val hasClose =
            afterOpen.contains(THINK_FENCE, ignoreCase = true) || afterOpen.contains("</thinking>", ignoreCase = true)
        if (!hasClose) s = s.substring(0, openIdx)
    }
    return s.trim()
}

fun parseMessageContent(raw: String): ParsedMessageContent {
    val main = stripThinkBlocksForDisplay(raw)
    return ParsedMessageContent(thinkContent = null, mainContent = main, isThinkStreaming = false)
}

'''
t2 = t[:start] + new + t[end:]
p.write_text(t2, encoding="utf-8")
print("ok")
