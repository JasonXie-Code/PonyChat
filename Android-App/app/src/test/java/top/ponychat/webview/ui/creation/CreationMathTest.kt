package top.ponychat.webview.ui.creation

import org.junit.Assert.assertEquals
import org.junit.Test

class CreationMathTest {
    @Test fun incompleteFormulaHasStableStreamingPlaceholder() {
        val tex = "\\frac{1}{1+\\frac{1}{x}}+\\sqrt{x^2+y^2}"
        for (length in 1..tex.length) {
            assertEquals("前文 公式生成中…", creationMathMarkdown("前文 $" + tex.take(length), true))
            assertEquals("前文\n公式生成中…", creationMathMarkdown("前文\n$$\n" + tex.take(length), true))
        }
        assertEquals("$$\n$tex\n$$", creationMathMarkdown("$$\n$tex\n$$", true))
        assertEquals("$" + tex, creationMathMarkdown("$" + tex, false))
        for (literal in listOf("金额 $5", "金额 $5 USD", "金额 $5 和 $10", "代码 `$" + tex, "\\$" + tex)) {
            assertEquals(literal, creationMathMarkdown(literal, true))
        }
    }

    @Test fun inlineFormulaAndMultipleVariables() {
        assertEquals("压强 $$" + "P = \\rho gh" + "$$。$$" + "x" + "$$ 与 $$" + "y^2" + "$$",
            creationMathMarkdown("压强 $" + "P = \\rho gh" + "$。$" + "x" + "$ 与 $" + "y^2" + "$"))
    }

    @Test fun existingMathAndCodeAreUntouched() {
        listOf("$$" + "x^2" + "$$", "$$\nx^2\n$$", "`$" + "x" + "$`",
            "``$" + "x" + "$``", "```text\n$" + "x" + "$\n```",
            "\\$" + "x" + "\\$", "`unfinished $" + "x" + "$").forEach {
            assertEquals(it, creationMathMarkdown(it))
        }
    }

    @Test fun currencyAndUnfinishedStreamStayLiteral() {
        listOf("价格 $5 和 $10", "$12.50", "$5$", "$5 to $10", "$ x$", "\$x $",
            "$" + "P = \\rho gh", "\$x\ny$", "\$x$10").forEach {
            assertEquals(it, creationMathMarkdown(it))
        }
    }

    @Test fun completedFormulaRendersBeforeStreamEnds() {
        val complete = "$" + "P = \\rho gh" + "$"
        assertEquals("$$" + "P = \\rho gh" + "$$ 后续还在输出", creationMathMarkdown(complete + " 后续还在输出"))
        assertEquals("代码 `$" + "x" + "$`，公式 $$" + "x" + "$$",
            creationMathMarkdown("代码 `$" + "x" + "$`，公式 $" + "x" + "$"))
    }
}
