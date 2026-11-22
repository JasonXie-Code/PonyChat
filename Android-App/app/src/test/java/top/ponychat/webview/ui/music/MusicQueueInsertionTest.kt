package top.ponychat.webview.ui.music

import org.junit.Assert.assertEquals
import org.junit.Test

class MusicQueueInsertionTest {
    @Test
    fun upcomingSongMovesDirectlyAfterCurrentInBothOrders() {
        val plan = planMusicQueueInsertion(listOf("a", "b", "c", "d"), 1, "d", listOf(2, 3, 0, 1))

        assertEquals(MusicQueueInsertion(3, 2, listOf(3, 0, 1, 2)), plan)
    }

    @Test
    fun movingEarlierSongRemapsCurrentIndexWithoutChangingOtherShuffleNeighbors() {
        val plan = planMusicQueueInsertion(listOf("a", "b", "c", "d"), 2, "a", listOf(0, 3, 2, 1))

        assertEquals(MusicQueueInsertion(0, 2, listOf(3, 1, 2, 0)), plan)
    }

    @Test
    fun replayingCurrentSongQueuesOneNewOccurrenceAndMultipleTapsReuseIt() {
        val first = planMusicQueueInsertion(listOf("a", "b", "c"), 1, "b", listOf(0, 2, 1))
        val repeated = planMusicQueueInsertion(listOf("a", "b", "b", "c"), 1, "b", first.shuffleOrder)

        assertEquals(MusicQueueInsertion(null, 2, listOf(0, 3, 1, 2)), first)
        assertEquals(MusicQueueInsertion(2, 2, first.shuffleOrder), repeated)
    }
}
