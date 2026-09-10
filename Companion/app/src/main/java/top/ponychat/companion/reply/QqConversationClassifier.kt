package top.ponychat.companion.reply

enum class QqConversationKind { PRIVATE, GROUP, UNKNOWN }

data class QqNotificationEnvelope(
    val packageName: String,
    val sender: String,
    val text: String,
    val conversationTitle: String? = null,
    val isGroupConversation: Boolean? = null,
)

object QqConversationClassifier {
    private const val QQ_PACKAGE = "com.tencent.mobileqq"
    private val PRIVATE_UNREAD_SUFFIX = Regex("[（(]\\d+条新消息[）)]$")

    fun classify(envelope: QqNotificationEnvelope): QqConversationKind = when {
        envelope.packageName != QQ_PACKAGE -> QqConversationKind.UNKNOWN
        envelope.sender.isBlank() || envelope.text.isBlank() -> QqConversationKind.UNKNOWN
        QqProtectedConversation.shouldPause(
            envelope.sender,
            envelope.conversationTitle.orEmpty(),
            envelope.text,
        ) -> QqConversationKind.UNKNOWN
        envelope.isGroupConversation == true -> QqConversationKind.GROUP
        !envelope.conversationTitle.isNullOrBlank() -> QqConversationKind.GROUP
        envelope.isGroupConversation == false -> QqConversationKind.PRIVATE
        else -> QqConversationKind.UNKNOWN
    }

    fun canVerifyInForeground(envelope: QqNotificationEnvelope): Boolean =
        envelope.packageName == QQ_PACKAGE &&
            envelope.sender.isNotBlank() &&
            envelope.text.isNotBlank() &&
            envelope.isGroupConversation != true &&
            envelope.conversationTitle.isNullOrBlank() &&
            !QqProtectedConversation.shouldPause(envelope.sender, envelope.text)

    fun foregroundVerificationSender(envelope: QqNotificationEnvelope): String =
        envelope.sender.trim().replace(PRIVATE_UNREAD_SUFFIX, "").trim()
}

object QqProtectedConversation {
    private val protectedSenders = setOf(
        "QQ安全中心",
        "腾讯安全中心",
        "腾讯客服",
        "QQ团队",
        "QQ钱包",
        "QQ支付",
    )
    private val protectedSignals = listOf(
        "风险设备",
        "风险提醒",
        "账号风险",
        "账号安全",
        "安全隐患",
        "异常登录",
        "下线处理",
        "修改密码",
        "登录保护",
        "短信验证码",
        "动态验证码",
        "支付密码",
        "设备存在外挂",
    )

    fun shouldPause(sender: String, vararg context: String): Boolean {
        val normalizedSender = sender.trim()
        if (protectedSenders.any { normalizedSender.equals(it, ignoreCase = true) }) return true
        return context.any { value -> protectedSignals.any(value::contains) }
    }
}
