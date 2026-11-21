package top.ponychat.webview.ui.creation

import org.junit.Assert.*
import org.junit.Test

class CreationMarkdownBlocksTest {
    @Test fun tableWaitsForBoundaryWhileProseContinuesStreaming() {
        val table = "| A | B |\n| --- | --- |\n| 1 | 2 |"
        val pending = creationMarkdownBlocks("开头\n\n$table", true)
        assertEquals("开头\n", pending.first().text)
        assertTrue(pending.last().pending)
        val closed = creationMarkdownBlocks("开头\n\n$table\n\n后文", true)
        assertFalse(closed.first { it.kind == CreationBlockKind.Table }.pending)
        assertEquals(table, closed.first { it.kind == CreationBlockKind.Table }.text)
        assertEquals("\n后文", closed.last().text)
    }
    @Test fun partialHeaderAndSeparatorDoNotFlashAsProse() {
        for (text in listOf("| A |", "| A |\n", "| A |\n| --")) {
            assertTrue(creationMarkdownBlocks(text, true).single().pending)
        }
    }
    @Test fun codeBecomesVisibleAsSoonAsItsClosingFenceArrives() {
        val open = "```kotlin\nval x = 1"
        assertTrue(creationMarkdownBlocks(open, true).single().pending)
        val closed = creationMarkdownBlocks("$open\n```\n后文", true)
        assertEquals("val x = 1", closed.first().text)
        assertFalse(closed.first().pending)
        assertEquals("kotlin", closed.first().language)
    }
    @Test fun stoppedStreamDisplaysUnclosedBlocksWithoutDiscardingContent() {
        assertFalse(creationMarkdownBlocks("```\n未结束", false).single().pending)
        assertEquals("未结束", creationMarkdownBlocks("```\n未结束", false).single().text)
        assertFalse(creationMarkdownBlocks("| A |\n| --- |\n| 内容 |", false).single().pending)
    }
    @Test fun codePipesAndEscapedPipesStayInOneCell() {
        assertEquals(listOf("`a|b`", "x\\|y"), creationTableCells("| `a|b` | x\\|y |"))
    }
    @Test fun longerFenceAndIndentedCodeAreRecognized() {
        val block = creationMarkdownBlocks("````text\n```\n内容\n````", true).single()
        assertEquals("```\n内容", block.text)
        assertFalse(block.pending)
        assertEquals(CreationBlockKind.Code, creationMarkdownBlocks("    print(1)", false).single().kind)
    }
}
