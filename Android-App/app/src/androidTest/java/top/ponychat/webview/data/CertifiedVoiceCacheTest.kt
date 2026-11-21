package top.ponychat.webview.data

import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Test
import top.ponychat.webview.data.local.ChatVoiceCache
import top.ponychat.webview.data.local.LocalCacheStore
import top.ponychat.webview.data.model.Character
import top.ponychat.webview.data.model.ChatMessage
import top.ponychat.webview.data.model.MessageVoiceState
import java.io.File
import java.util.UUID

class CertifiedVoiceCacheTest {
    @Test fun removesCustomVoiceButPreservesCertifiedGuestAndUserMessages() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val cache = LocalCacheStore(context)
        val username = "voice-test-${UUID.randomUUID()}"
        val custom = Character(id = "custom", name = "普通角色", voiceAvailable = false, voiceEnabled = true)
        val certified = Character(id = "certified", name = "认证角色", voiceAvailable = true)
        val customKey = "$username-custom"
        val certifiedKey = "$username-certified"
        val customAudio = requireNotNull(ChatVoiceCache.saveBytes(context, customKey, byteArrayOf(1, 2, 3), "audio/mpeg"))
        val certifiedAudio = requireNotNull(ChatVoiceCache.saveBytes(context, certifiedKey, byteArrayOf(4, 5, 6), "audio/mpeg"))
        try {
            cache.saveConversation(username, "custom", "normal", "conv", listOf(
                ChatMessage(role = "assistant", content = "保留文字", messageId = "custom-msg", timestamp = 1,
                    voiceState = MessageVoiceState(status = "ready", voiceCacheKey = customKey, localFile = customAudio.localFile)),
                ChatMessage(role = "assistant", content = "认证角色客串", messageId = "guest-msg", timestamp = 2,
                    speakerCharacterId = "certified", voiceState = MessageVoiceState(status = "ready", voiceCacheKey = certifiedKey, localFile = certifiedAudio.localFile)),
                ChatMessage(role = "user", content = "用户语音转录", messageId = "user-msg", timestamp = 3,
                    voiceState = MessageVoiceState(status = "ready", localFile = certifiedAudio.localFile))
            ))
            cache.saveCharacters(username, listOf(custom, certified))
            val messages = requireNotNull(cache.loadConversation(username, "custom", "normal", "conv")).messages
            assertEquals(listOf("保留文字", "认证角色客串", "用户语音转录"), messages.map { it.content })
            assertNull(messages[0].voiceState)
            assertNotNull(messages[1].voiceState)
            assertNotNull(messages[2].voiceState)
            assertFalse(File(customAudio.localFile).exists())
            assertTrue(File(certifiedAudio.localFile).exists())
            assertFalse(custom.supportsCharacterVoice())
            assertTrue(certified.supportsCharacterVoice())
        } finally {
            cache.clearForCharacter(username, "custom")
            ChatVoiceCache.remove(context, customKey, customAudio.localFile)
            ChatVoiceCache.remove(context, certifiedKey, certifiedAudio.localFile)
        }
    }
}
