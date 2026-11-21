package top.ponychat.webview.ui.common

import org.junit.Assert.*
import org.junit.Test

class PromptPresentationTest {
    @Test fun shortFeedbackStaysInBubble() {
        assertFalse(shouldUsePromptDialog("已加入下载"))
        assertFalse(shouldUsePromptDialog("好".repeat(28)))
        assertFalse(shouldUsePromptDialog("😀".repeat(28)))
    }
    @Test fun longAndMultilineFeedbackUsesDialog() {
        assertTrue(shouldUsePromptDialog("好".repeat(29)))
        assertTrue(shouldUsePromptDialog("第一段\n第二段"))
        assertTrue(shouldUsePromptDialog("DeepSeek 单次请求超过 30 秒未返回，服务暂不可用，请等待修复。"))
    }
}
