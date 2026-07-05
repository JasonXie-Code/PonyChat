package top.ponychat.webview.data.local

import android.content.Context
import android.media.MediaCodec
import android.media.MediaExtractor
import android.media.MediaFormat
import android.media.MediaMetadataRetriever
import android.util.Base64
import top.ponychat.webview.data.model.MessageVoiceState
import top.ponychat.webview.data.model.VoiceAudioTransfer
import java.io.File
import java.nio.ByteOrder
import java.security.MessageDigest
import kotlin.math.pow
import kotlin.math.sqrt

data class CachedVoiceAudio(
    val localFile: String,
    val durationMs: Long,
    val mime: String,
    val waveform: List<Float>
)

object ChatVoiceCache {
    private const val PREFS = "ponychat_voice_audio_cache"

    fun hydrate(context: Context, state: MessageVoiceState?): MessageVoiceState? {
        if (state == null) return null
        if (!state.localFile.isNullOrBlank() || state.debugPlayable) return state
        val key = state.voiceCacheKey?.takeIf { it.isNotBlank() } ?: return state
        val cached = find(context, key) ?: return state
        return state.copy(
            localFile = cached.localFile,
            durationMs = cached.durationMs,
            waveform = state.waveform.ifEmpty { cached.waveform }
        )
    }

    fun find(context: Context, voiceCacheKey: String): CachedVoiceAudio? {
        val key = voiceCacheKey.trim()
        if (key.isBlank()) return null
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val path = prefs.getString("${key}.path", null)
        val file = path?.let { File(it) } ?: fileFor(context, key, "audio/mpeg")
        if (!file.exists() || file.length() <= 0L) return null
        val duration = prefs.getLong("${key}.duration_ms", 0L)
            .takeIf { it > 0L }
            ?: readDurationMs(file.absolutePath)
        val waveform = parseWaveform(prefs.getString("${key}.waveform", null))
            .ifEmpty { readWaveform(file.absolutePath) }
        return CachedVoiceAudio(
            localFile = file.absolutePath,
            durationMs = duration.coerceAtLeast(1000L),
            mime = prefs.getString("${key}.mime", null) ?: "audio/mpeg",
            waveform = waveform
        )
    }

    fun save(context: Context, voiceCacheKey: String, transfer: VoiceAudioTransfer?): CachedVoiceAudio? {
        val data = transfer?.dataBase64?.takeIf { it.isNotBlank() } ?: return null
        val bytes = runCatching { Base64.decode(data, Base64.DEFAULT) }.getOrNull() ?: return null
        if (bytes.isEmpty()) return null
        return saveBytes(context, voiceCacheKey, bytes, transfer.mime ?: "audio/mpeg")
    }

    fun saveBytes(context: Context, voiceCacheKey: String, bytes: ByteArray, mime: String): CachedVoiceAudio? {
        val key = voiceCacheKey.trim()
        if (key.isBlank() || bytes.isEmpty()) return null
        val file = fileFor(context, key, mime)
        file.parentFile?.mkdirs()
        file.writeBytes(bytes)
        val duration = readDurationMs(file.absolutePath).coerceAtLeast(1000L)
        val waveform = readWaveform(file.absolutePath)
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit()
            .putString("${key}.path", file.absolutePath)
            .putString("${key}.mime", mime)
            .putLong("${key}.duration_ms", duration)
            .putString("${key}.waveform", waveform.joinToString(",") { "%.3f".format(java.util.Locale.US, it) })
            .apply()
        return CachedVoiceAudio(file.absolutePath, duration, mime, waveform)
    }

    private fun fileFor(context: Context, voiceCacheKey: String, mime: String): File {
        val ext = when {
            mime.contains("wav", ignoreCase = true) -> "wav"
            mime.contains("mp4", ignoreCase = true) || mime.contains("aac", ignoreCase = true) -> "m4a"
            else -> "mp3"
        }
        return File(File(context.cacheDir, "chat_voice").also { it.mkdirs() }, "${sha256(voiceCacheKey)}.$ext")
    }

    private fun readDurationMs(path: String): Long {
        return runCatching {
            val retriever = MediaMetadataRetriever()
            try {
                retriever.setDataSource(path)
                retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION)?.toLongOrNull() ?: 0L
            } finally {
                retriever.release()
            }
        }.getOrDefault(0L)
    }

    private fun parseWaveform(raw: String?): List<Float> {
        if (raw.isNullOrBlank()) return emptyList()
        return raw.split(',')
            .mapNotNull { it.toFloatOrNull() }
            .filter { it.isFinite() && it >= 0f }
            .map { it.coerceIn(0f, 1f) }
    }

    private fun readWaveform(path: String, bucketCount: Int = 72): List<Float> {
        return runCatching {
            val extractor = MediaExtractor()
            try {
                extractor.setDataSource(path)
                val trackIndex = (0 until extractor.trackCount).firstOrNull { index ->
                    extractor.getTrackFormat(index)
                        .getString(MediaFormat.KEY_MIME)
                        ?.startsWith("audio/") == true
                } ?: return@runCatching emptyList()
                val format = extractor.getTrackFormat(trackIndex)
                val mime = format.getString(MediaFormat.KEY_MIME) ?: return@runCatching emptyList()
                extractor.selectTrack(trackIndex)
                val codec = MediaCodec.createDecoderByType(mime)
                val info = MediaCodec.BufferInfo()
                val sums = DoubleArray(bucketCount)
                val counts = IntArray(bucketCount)
                var sampleRate = format.getInteger(MediaFormat.KEY_SAMPLE_RATE).coerceAtLeast(1)
                var channels = format.getInteger(MediaFormat.KEY_CHANNEL_COUNT).coerceAtLeast(1)
                val durationUs = runCatching { format.getLong(MediaFormat.KEY_DURATION) }.getOrDefault(0L)
                    .coerceAtLeast(1L)
                try {
                    codec.configure(format, null, null, 0)
                    codec.start()
                    var inputEnded = false
                    var outputEnded = false
                    while (!outputEnded) {
                        if (!inputEnded) {
                            val inIndex = codec.dequeueInputBuffer(10_000)
                            if (inIndex >= 0) {
                                val input = codec.getInputBuffer(inIndex)
                                val sampleSize = if (input != null) extractor.readSampleData(input, 0) else -1
                                if (sampleSize < 0) {
                                    codec.queueInputBuffer(
                                        inIndex,
                                        0,
                                        0,
                                        0L,
                                        MediaCodec.BUFFER_FLAG_END_OF_STREAM
                                    )
                                    inputEnded = true
                                } else {
                                    val pts = extractor.sampleTime.coerceAtLeast(0L)
                                    codec.queueInputBuffer(inIndex, 0, sampleSize, pts, 0)
                                    extractor.advance()
                                }
                            }
                        }
                        when (val outIndex = codec.dequeueOutputBuffer(info, 10_000)) {
                            MediaCodec.INFO_OUTPUT_FORMAT_CHANGED -> {
                                val outFormat = codec.outputFormat
                                sampleRate = outFormat.getInteger(MediaFormat.KEY_SAMPLE_RATE).coerceAtLeast(1)
                                channels = outFormat.getInteger(MediaFormat.KEY_CHANNEL_COUNT).coerceAtLeast(1)
                            }
                            MediaCodec.INFO_TRY_AGAIN_LATER -> Unit
                            else -> if (outIndex >= 0) {
                                val output = codec.getOutputBuffer(outIndex)
                                if (output != null && info.size > 1) {
                                    output.position(info.offset)
                                    output.limit(info.offset + info.size)
                                    output.order(ByteOrder.LITTLE_ENDIAN)
                                    val shorts = output.asShortBuffer()
                                    val frameCount = (shorts.remaining() / channels).coerceAtLeast(0)
                                    for (frame in 0 until frameCount) {
                                        var peak = 0
                                        for (ch in 0 until channels) {
                                            val value = kotlin.math.abs(shorts.get().toInt())
                                            if (value > peak) peak = value
                                        }
                                        val frameUs = info.presentationTimeUs +
                                            (frame * 1_000_000.0 / sampleRate).toLong()
                                        val bucket = ((frameUs * bucketCount) / durationUs)
                                            .toInt()
                                            .coerceIn(0, bucketCount - 1)
                                        val normalized = peak / 32768.0
                                        sums[bucket] += normalized * normalized
                                        counts[bucket] += 1
                                    }
                                }
                                if ((info.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM) != 0) {
                                    outputEnded = true
                                }
                                codec.releaseOutputBuffer(outIndex, false)
                            }
                        }
                    }
                } finally {
                    runCatching { codec.stop() }
                    runCatching { codec.release() }
                }
                val rms = List(bucketCount) { index ->
                    if (counts[index] > 0) sqrt(sums[index] / counts[index]).toFloat() else 0f
                }
                normalizeWaveform(rms)
            } finally {
                extractor.release()
            }
        }.getOrDefault(emptyList())
    }

    private fun normalizeWaveform(values: List<Float>): List<Float> {
        val max = values.maxOrNull()?.takeIf { it > 0.001f } ?: return emptyList()
        return values.map { value ->
            (value / max).coerceIn(0f, 1f).toDouble().pow(0.72).toFloat()
        }
    }

    private fun sha256(value: String): String {
        val digest = MessageDigest.getInstance("SHA-256").digest(value.toByteArray(Charsets.UTF_8))
        return digest.joinToString("") { "%02x".format(it) }.take(32)
    }
}
