package top.ponychat.companion.reply

import org.junit.Assert.assertEquals
import org.junit.Test

class RoleReplyTextSanitizerTest {
    @Test
    fun `replaces character prompt user placeholder with PonyChat username`() {
        assertEquals(
            "晚上好呀，System！",
            RoleReplyTextSanitizer.sanitize("晚上好呀，{{USER}}！", "System"),
        )
    }

    @Test
    fun `normalizes all role reply temperatures to celsius`() {
        assertEquals(
            "现在30°C，体感35°C，夜间25°C",
            RoleReplyTextSanitizer.sanitize(
                "现在86°F，体感95℉，夜间华氏 77 度",
                "System",
            ),
        )
    }
}
