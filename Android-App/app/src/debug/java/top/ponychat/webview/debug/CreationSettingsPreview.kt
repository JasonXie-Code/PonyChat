package top.ponychat.webview.debug

import androidx.compose.runtime.*
import top.ponychat.webview.ui.creation.*

/** Uses the production composables with local sample data; no account or network writes. */
@Composable
internal fun CreationSettingsPreview() {
    var editing by remember { mutableStateOf(true) }
    var input by remember { mutableStateOf("") }
    var session by remember { mutableStateOf(CreationSession(
        id = "settings-preview", title = "雨夜里的旧书店",
        instructions = "用自然的角色口吻继续故事，温柔克制，保留开放式结尾。",
        contextLayout = listOf(
            CreationContextBlock("system", "system", "系统提示词", "按照角色设定和用户的创作指令直接回复。用户可以自由指定内容、语气、篇幅、视角和排版。\n默认像角色给用户发消息一样，用自然的纯文本直接回应，保持角色的口吻，按需要自然分段，动作或情绪描写需要时可以用普通文字或括号自然表达。\n直接输出回复正文，不包装成聊天气泡JSON。"),
            CreationContextBlock("character", "character", "角色设定", ""),
            CreationContextBlock("history", "history", "对话历史", ""),
            CreationContextBlock("instructions", "instructions", "创作指令", ""),
            CreationContextBlock("input", "input", "最新用户输入", "")
        ))) }
    if (editing) CreationSettings(session, { editing = false },
        usage = CreationContextUsage(18311, 65536)) { title, instructions, blocks ->
        session = session.copy(title = title, instructions = instructions, contextLayout = blocks)
        editing = false
    } else CreationChatContent("云杉", CreationUiState(session = session, input = input, loading = false),
        onBack = { editing = true }, onInput = { input = it }, onSend = {}, onRegenerate = {},
        onNew = {}, onLoad = {}, onContext = { editing = true }, onSettings = { editing = true })
}
