package top.ponychat.webview.ui.creation

/** Adapt complete single-dollar math for Markwon, without modifying stored Markdown. */
internal fun creationMathMarkdown(source: String, streaming: Boolean = false): String {
    val out = StringBuilder(source.length)
    var i = 0
    while (i < source.length) {
        when {
            source[i] == '\\' && i + 1 < source.length -> {
                out.append(source, i, i + 2); i += 2
            }
            source[i] == '`' -> {
                var end = i + 1
                while (end < source.length && source[end] == '`') end++
                val marker = source.substring(i, end)
                val close = source.indexOf(marker, end)
                val stop = if (close < 0) source.length else close + marker.length
                out.append(source, i, stop); i = stop
            }
            source.startsWith("$$", i) -> {
                var end = i + 2
                while (end < source.length && source[end] == '$') end++
                val marker = source.substring(i, end)
                val close = source.indexOf(marker, end)
                if (close < 0 && streaming) {
                    out.append("公式生成中…")
                    break
                }
                val stop = if (close < 0) source.length else close + marker.length
                out.append(source, i, stop); i = stop
            }
            source[i] == '$' -> {
                var end = i + 1
                while (end < source.length && source[end] != '\n' && source[end] != '$' && source[end] != '`') {
                    end += if (source[end] == '\\' && end + 1 < source.length) 2 else 1
                }
                val body = source.substring(i + 1, end)
                val closed = end < source.length && source[end] == '$' && !source.startsWith("$$", end)
                val tight = body.isNotEmpty() && !body.first().isWhitespace() && !body.last().isWhitespace()
                val followedByDigit = end + 1 < source.length && source[end + 1].isDigit()
                // Bare amounts are currency. Letter variables, TeX commands and expressions are math.
                val mathematical = body.any { it.isLetter() || it in "\\^_=+*/<>{}" }
                if (streaming && end == source.length && body.isNotEmpty() &&
                    !body.first().isWhitespace() && mathematical &&
                    (!body.first().isDigit() || body.any { it in "\\^_=+*/<>{}" })) {
                    out.append("公式生成中…")
                    break
                }
                if (closed && tight && !followedByDigit && mathematical) {
                    out.append("$$").append(body).append("$$"); i = end + 1
                } else { out.append(source[i]); i++ }
            }
            else -> { out.append(source[i]); i++ }
        }
    }
    return out.toString()
}
