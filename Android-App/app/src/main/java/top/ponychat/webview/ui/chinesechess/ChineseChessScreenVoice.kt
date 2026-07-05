package top.ponychat.webview.ui.chinesechess

import kotlinx.coroutines.Deferred
import top.ponychat.webview.data.local.CachedVoiceAudio

internal data class XiangqiPreparedVoiceBatch(
    val segments: List<String>,
    val voiceSentences: List<Map<String, String>>,
    val audioRequests: List<Deferred<CachedVoiceAudio?>>
) {
    fun slice(startIndex: Int, endIndex: Int): XiangqiPreparedVoiceBatch {
        val start = startIndex.coerceIn(0, segments.size)
        val end = endIndex.coerceIn(start, segments.size)
        val count = end - start
        return XiangqiPreparedVoiceBatch(
            segments = segments.drop(start).take(count),
            voiceSentences = voiceSentences.drop(start).take(count),
            audioRequests = audioRequests.drop(start).take(count)
        )
    }

    fun cancel() {
        audioRequests.forEach { it.cancel() }
    }
}
