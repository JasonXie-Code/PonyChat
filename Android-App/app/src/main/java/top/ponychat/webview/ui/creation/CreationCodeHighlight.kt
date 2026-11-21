package top.ponychat.webview.ui.creation

import android.text.SpannableString
import android.text.Spanned
import android.text.style.ForegroundColorSpan

/** A lightweight lexical theme; strings/comments are consumed before keyword matching. */
internal fun highlightCreationCode(code: String, language: String, dark: Boolean): CharSequence {
    val lang = language.lowercase().substringBefore(' ')
    if (lang in setOf("", "text", "plaintext", "plain")) return code
    val keywords = ("import from as def class return if elif else for while in not and or is lambda try except finally with " +
        "raise yield pass break continue async await function const let var new this public private protected static void " +
        "package fun val when object interface override suspend true false null None True False export default switch case " +
        "do throw catch extends implements select SELECT FROM WHERE INSERT INTO UPDATE DELETE JOIN ON AS AND OR").split(' ').toSet()
    val python = lang in setOf("python", "py", "bash", "sh", "shell", "yaml", "yml", "ruby", "rb")
    val pattern = Regex("\"\"\"[\\s\\S]*?\"\"\"|'''[\\s\\S]*?'''|\"(?:\\\\.|[^\"\\\\])*\"|'(?:\\\\.|[^'\\\\])*'|`(?:\\\\.|[^`\\\\])*`|/\\*[\\s\\S]*?\\*/|//[^\\n]*|" +
        (if (python) "#[^\\n]*|" else "") + "\\b\\d+(?:\\.\\d+)?(?:[eE][+-]?\\d+)?\\b|\\b[A-Za-z_][A-Za-z_0-9]*\\b")
    val output = SpannableString(code)
    pattern.findAll(code).forEach { match ->
        val token = match.value
        var next = match.range.last + 1
        while (next < code.length && code[next].isWhitespace()) next++
        val color = when {
            token.startsWith("//") || token.startsWith("/*") || (python && token.startsWith("#")) -> if (dark) 0xFF6A9955 else 0xFF008000
            token.startsWith('"') || token.startsWith('\'') || token.startsWith('`') -> if (dark) 0xFFCE9178 else 0xFFA31515
            token.first().isDigit() -> if (dark) 0xFFB5CEA8 else 0xFF098658
            token in keywords -> if (dark) 0xFFC586C0 else 0xFFAF00DB
            next < code.length && code[next] == '(' -> if (dark) 0xFFDCDCAA else 0xFF795E26
            token.first().isUpperCase() -> if (dark) 0xFF4EC9B0 else 0xFF267F99
            else -> return@forEach
        }
        output.setSpan(ForegroundColorSpan(color.toInt()), match.range.first, match.range.last + 1, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
    }
    return output
}
