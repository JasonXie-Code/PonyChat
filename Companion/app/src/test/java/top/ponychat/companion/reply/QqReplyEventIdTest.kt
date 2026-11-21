package top.ponychat.companion.reply

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Test

class QqReplyEventIdTest {
    @Test
    fun `same incoming snapshot is idempotent`() {
        val first = QqReplyEventId.create("Jason", "你好", "上一条\u001f你好")
        val second = QqReplyEventId.create("Jason", "你好", "上一条\u001f你好")
        assertEquals(first, second)
    }

    @Test
    fun `new occurrence changes event id even when text repeats`() {
        assertNotEquals(
            QqReplyEventId.create("Jason", "你好", "上一条\u001f你好"),
            QqReplyEventId.create("Jason", "你好", "上一条\u001f你好\u001f你好"),
        )
    }
}
