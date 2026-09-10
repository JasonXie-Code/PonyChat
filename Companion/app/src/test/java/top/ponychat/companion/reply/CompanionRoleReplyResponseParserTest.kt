package top.ponychat.companion.reply

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Test

class CompanionRoleReplyResponseParserTest {
    @Test
    fun parsesNormalChatParagraphsWithoutChangingPersistedText() {
        val reply = CompanionRoleReplyResponseParser.parse(
            """{
                "protocol":"ponychat_chat_v1",
                "events":[
                    {"type":"accepted","conversation_id":"normal_user_xiaodai"},
                    {"type":"assistant_paragraph","content":"葡萄确实很好吃呀，","display_delay_ms":0},
                    {"type":"assistant_paragraph","content":"酸酸甜甜的","display_delay_ms":2150},
                    {"type":"done"}
                ]
            }""".trimIndent(),
        )

        requireNotNull(reply)
        assertEquals("normal_user_xiaodai", reply.conversationId)
        assertEquals(
            listOf(
                CompanionRoleReplyPart("葡萄确实很好吃呀，", 0),
                CompanionRoleReplyPart("酸酸甜甜的", 2150),
            ),
            reply.parts,
        )
        assertEquals("葡萄确实很好吃呀，\n酸酸甜甜的", reply.displayText)
    }

    @Test
    fun returnsNullWhenNormalPipelineChoosesNoReply() {
        assertNull(
            CompanionRoleReplyResponseParser.parse(
                """{"events":[{"type":"accepted"},{"type":"no_reply"},{"type":"done"}]}""",
            ),
        )
    }

    @Test
    fun reportsSafeServerEventError() {
        val error = assertThrows(CompanionRoleReplyException::class.java) {
            CompanionRoleReplyResponseParser.parse(
                """{"events":[{"type":"error","message":"model_error"}]}""",
            )
        }

        assertEquals("普通对话接口失败: model_error", error.message)
    }

    @Test
    fun rejectsMalformedResponseWithoutEchoingIt() {
        val error = assertThrows(CompanionRoleReplyException::class.java) {
            CompanionRoleReplyResponseParser.parse("not-json-secret")
        }

        assertEquals("普通对话接口响应格式无效", error.message)
    }

    @Test
    fun rejectsSuccessfulEnvelopeWithoutReplyEvent() {
        val error = assertThrows(CompanionRoleReplyException::class.java) {
            CompanionRoleReplyResponseParser.parse(
                """{"events":[{"type":"accepted"},{"type":"done"}]}""",
            )
        }

        assertEquals("普通对话接口未返回角色消息", error.message)
    }
}
