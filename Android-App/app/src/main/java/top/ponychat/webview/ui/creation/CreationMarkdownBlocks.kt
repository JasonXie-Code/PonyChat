package top.ponychat.webview.ui.creation

internal enum class CreationBlockKind { Prose, Table, Code, Diagram }
internal data class CreationMarkdownBlock(val start: Int, val kind: CreationBlockKind,
    val text: String, val pending: Boolean = false, val language: String = "")

/** Completed structural blocks stay stable while only the unfinished tail changes. */
internal fun creationMarkdownBlocks(text: String, streaming: Boolean): List<CreationMarkdownBlock> {
    val lines = text.split('\n')
    val result = mutableListOf<CreationMarkdownBlock>()
    val prose = mutableListOf<String>()
    var proseStart = 0
    var index = 0
    fun flush() {
        if (prose.any { it.isNotBlank() }) result += CreationMarkdownBlock(proseStart, CreationBlockKind.Prose, prose.joinToString("\n"))
        prose.clear()
    }
    while (index < lines.size) {
        val line = lines[index]
        val fence = Regex("^ {0,3}(`{3,}|~{3,})(.*)$").matchEntire(line)
        val separator = lines.getOrNull(index + 1)?.let(::creationTableCells)
        val table = '|' in line && separator != null && separator.isNotEmpty() &&
            separator.all { Regex(":?-{3,}:?").matches(it.trim()) }
        when {
            fence != null -> {
                flush()
                val start = index
                val marker = fence.groupValues[1]
                val close = Regex("^ {0,3}${Regex.escape(marker.first().toString())}{${marker.length},} *$")
                index++
                val body = mutableListOf<String>()
                while (index < lines.size && !close.matches(lines[index])) body += lines[index++]
                val closed = index < lines.size
                if (closed) index++
                val language = fence.groupValues[2].trim()
                val kind = if (language.equals("mermaid", ignoreCase = true)) CreationBlockKind.Diagram else CreationBlockKind.Code
                result += CreationMarkdownBlock(start, kind, body.joinToString("\n"),
                    pending = streaming && !closed, language = language)
            }
            table -> {
                flush()
                val start = index
                index += 2
                while (index < lines.size && lines[index].isNotBlank() && '|' in lines[index]) index++
                val atStreamTail = index >= lines.size || (index == lines.lastIndex && lines[index].isBlank() && !text.endsWith("\n\n"))
                result += CreationMarkdownBlock(start, CreationBlockKind.Table, lines.subList(start, index).joinToString("\n"),
                    pending = streaming && atStreamTail)
            }
            streaming && line.trimStart().startsWith("|") &&
                (index == lines.lastIndex || (index == lines.lastIndex - 1 &&
                    lines.last().all { it in " |:-" })) -> {
                flush()
                result += CreationMarkdownBlock(index, CreationBlockKind.Table, lines.drop(index).joinToString("\n"), pending = true)
                index = lines.size
            }
            (index == 0 || lines[index - 1].isBlank()) &&
                (line.startsWith("    ") || line.startsWith('\t')) && line.isNotBlank() -> {
                flush()
                val start = index
                val body = mutableListOf<String>()
                while (index < lines.size && (lines[index].startsWith("    ") || lines[index].startsWith('\t') || lines[index].isBlank())) {
                    val raw = lines[index++]
                    body += if (raw.startsWith('\t')) raw.removePrefix("\t") else raw.removePrefix("    ")
                }
                result += CreationMarkdownBlock(start, CreationBlockKind.Code, body.joinToString("\n"),
                    pending = streaming && index == lines.size)
            }
            else -> { if (prose.isEmpty()) proseStart = index; prose += line; index++ }
        }
    }
    flush()
    return result
}

/** Pipes in escaped text or inline code are cell content, not column separators. */
internal fun creationTableCells(line: String): List<String> {
    val cells = mutableListOf<String>()
    val cell = StringBuilder()
    var escaped = false
    var ticks = 0
    var index = 0
    while (index < line.length) {
        val ch = line[index]
        when {
            escaped -> { cell.append(ch); escaped = false; index++ }
            ch == '\\' -> { cell.append(ch); escaped = true; index++ }
            ch == '`' -> {
                var end = index
                while (end < line.length && line[end] == '`') end++
                val count = end - index
                if (ticks == 0) ticks = count else if (ticks == count) ticks = 0
                cell.append(line.substring(index, end)); index = end
            }
            ch == '|' && ticks == 0 -> { cells += cell.toString().trim(); cell.clear(); index++ }
            else -> { cell.append(ch); index++ }
        }
    }
    cells += cell.toString().trim()
    if (cells.firstOrNull().isNullOrEmpty() && line.trimStart().startsWith("|")) cells.removeAt(0)
    if (cells.lastOrNull().isNullOrEmpty() && line.trimEnd().endsWith("|")) cells.removeAt(cells.lastIndex)
    return cells
}
