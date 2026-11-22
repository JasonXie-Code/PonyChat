package top.ponychat.webview.ui.music

import androidx.annotation.OptIn
import androidx.media3.common.C
import androidx.media3.common.Player
import androidx.media3.common.Timeline
import androidx.media3.common.util.UnstableApi

@OptIn(UnstableApi::class)
internal fun Timeline.musicShuffleIndices(): List<Int> = buildList {
    var index = getFirstWindowIndex(true)
    while (index != C.INDEX_UNSET) {
        add(index)
        index = getNextWindowIndex(index, Player.REPEAT_MODE_OFF, true)
    }
}

internal data class MusicQueueInsertion(
    val existingIndex: Int?,
    val nextIndex: Int,
    val shuffleOrder: List<Int>,
)

internal fun planMusicQueueInsertion(
    songIds: List<String>,
    currentIndex: Int,
    requestedId: String,
    shuffleOrder: List<Int>,
): MusicQueueInsertion {
    val existing = ((currentIndex + 1) until songIds.size).firstOrNull { songIds[it] == requestedId }
        ?: (0 until currentIndex).firstOrNull { songIds[it] == requestedId }
    val nextIndex = if (existing != null && existing < currentIndex) currentIndex else currentIndex + 1

    // Keep the current item in place and remap the shuffle order after inserting or moving another item.
    val requestedIndex = existing ?: songIds.size
    val oldIndices = songIds.indices.toMutableList()
    if (existing != null) oldIndices.removeAt(existing)
    oldIndices.add(nextIndex, requestedIndex)
    val newIndexByOldIndex = IntArray(oldIndices.size)
    oldIndices.forEachIndexed { newIndex, oldIndex -> newIndexByOldIndex[oldIndex] = newIndex }

    val shuffled = shuffleOrder.toMutableList()
    if (existing != null) shuffled.remove(existing)
    shuffled.add(shuffled.indexOf(currentIndex) + 1, requestedIndex)
    return MusicQueueInsertion(existing, nextIndex, shuffled.map { newIndexByOldIndex[it] })
}
