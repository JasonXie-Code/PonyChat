package top.ponychat.companion.reply

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Test

class CompanionRoleReplyRequestBuilderTest {
    @Test
    fun `messages is a json array rather than a quoted json string`() {
        val payload = JSONObject(
            CompanionRoleReplyRequestBuilder.build(
                session = CompanionSession(
                    apiBase = "https://example.test",
                    username = "System",
                    authToken = "token",
                    characterId = "muffins",
                    personalityStyle = "canonical",
                ),
                message = "  先聊聊今晚的事呗  ",
                timestampMs = 1234L,
                messageId = "msg_external_test",
            ),
        )

        val messages = payload.optJSONArray("messages")
        assertNotNull(messages)
        assertEquals(1, messages!!.length())
        assertEquals("先聊聊今晚的事呗", messages.getJSONObject(0).getString("content"))
        assertEquals("companion_external", messages.getJSONObject(0).getString("client_id"))
        assertEquals("normal", payload.getString("mode"))
    }
}
