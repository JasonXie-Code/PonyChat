package top.ponychat.webview.ui.chinesechess

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class EleEyeInstrumentedTest {
    @Test
    fun packagedEleEyeReturnsBestMove() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val move = eleEyeBestMoveSmokeForTest(context)

        assertTrue(move.orEmpty().matches(Regex("[a-i][0-9][a-i][0-9]")))
    }

    @Test
    fun eleEyeSessionReusesOneResidentProcess() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val session = EleEyeEngine.openSession(context)
        try {
            assertTrue(session.warmUp())
            val startCountAfterWarmup = session.startCountForTest
            val first = session.bestMove(
                board = initialBoard(),
                side = Side.Red,
                difficulty = ChessPowerTier.Advanced.engineDifficulty,
                playStyle = ChessPlayStyle.Textbook,
                plyCount = 0
            )
            assertNotNull(first)
            val second = session.bestMove(
                board = initialBoard().applyMove(first!!.move),
                side = Side.Black,
                difficulty = ChessPowerTier.Advanced.engineDifficulty,
                playStyle = ChessPlayStyle.Textbook,
                plyCount = 1
            )
            assertNotNull(second)

            assertEquals(startCountAfterWarmup, session.startCountForTest)
        } finally {
            session.close()
        }
    }
}
