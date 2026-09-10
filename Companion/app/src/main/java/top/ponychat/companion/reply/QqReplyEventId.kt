package top.ponychat.companion.reply

import java.security.MessageDigest

object QqReplyEventId {
    fun create(sender: String, message: String, incomingSignature: String): String {
        val payload = "$sender\u001e$message\u001e$incomingSignature"
        return sha256(payload)
    }

    fun messageFingerprint(sender: String, message: String): String =
        sha256("${sender.trim()}\u001e${message.trim()}")

    private fun sha256(value: String): String = MessageDigest.getInstance("SHA-256")
        .digest(value.toByteArray(Charsets.UTF_8))
        .joinToString("") { "%02x".format(it) }
}
