package top.ponychat.webview.data.api

/** Keep missing files in the index so their positions never shift during a reread. */
internal object HistoryImageIndex {
    private val markdown = Regex("!\\[[^\\]]*]\\(([^)]+)\\)")
    private val data = Regex("data:image/[a-zA-Z0-9.+-]+;base64,[A-Za-z0-9+/=]+")
    private val local = Regex("file://[^\\s)]+/chat_images/[^\\s)]+")
    private val remote = Regex("/chat_images/[A-Za-z0-9_.-]+")

    fun urls(content: String): List<String> {
        val matches = markdown.findAll(content).map { it.range.first to it.groupValues[1].trim() }.toList()
        val remainder = content.replace(markdown) { " ".repeat(it.value.length) }
        val raw = data.findAll(remainder).map { it.range.first to it.value } +
            local.findAll(remainder).map { it.range.first to it.value }
        val loose = remainder.replace(data) { " ".repeat(it.value.length) }
            .replace(local) { " ".repeat(it.value.length) }
        return (matches.asSequence() + raw + remote.findAll(loose).map { it.range.first to it.value })
            .sortedBy { it.first }.map { it.second }
            .filter { it.startsWith("/chat_images/") || it.startsWith("file://") || it.startsWith("data:image/") }
            .distinct().take(4).toList()
    }
}
