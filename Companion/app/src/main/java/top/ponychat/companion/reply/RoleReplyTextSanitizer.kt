package top.ponychat.companion.reply

object RoleReplyTextSanitizer {
    private val userTokens = listOf("{{USER}}", "{{user}}", "<USER>", "<user>")
    private val fahrenheitAfter = Regex(
        "(-?\\d+(?:\\.\\d+)?)\\s*(?:°\\s*F|℉|华氏度?)",
        RegexOption.IGNORE_CASE,
    )
    private val fahrenheitBefore = Regex(
        "华氏\\s*(-?\\d+(?:\\.\\d+)?)\\s*度?",
        RegexOption.IGNORE_CASE,
    )

    fun sanitize(raw: String, appUsername: String): String {
        val personalized = userTokens.fold(raw.trim()) { text, token ->
            text.replace(token, appUsername)
        }
        return normalizeCelsius(personalized)
    }

    private fun normalizeCelsius(text: String): String {
        val trailingNormalized = fahrenheitAfter.replace(text, ::fahrenheitToCelsius)
        return fahrenheitBefore.replace(trailingNormalized, ::fahrenheitToCelsius)
    }

    private fun fahrenheitToCelsius(match: MatchResult): String {
        val fahrenheit = match.groupValues[1].toDoubleOrNull() ?: return match.value
        val rounded = kotlin.math.round(((fahrenheit - 32.0) * 5.0 / 9.0) * 10.0) / 10.0
        val value = if (rounded % 1.0 == 0.0) rounded.toInt().toString() else rounded.toString()
        return "$value°C"
    }
}
