package top.ponychat.webview.audio

import android.media.MediaPlayer
import android.media.audiofx.Equalizer
import android.media.audiofx.LoudnessEnhancer
import android.util.Log
import kotlin.math.abs
import kotlin.math.exp
import kotlin.math.max
import kotlin.math.min

/**
 * Client-side "mobile microphone" treatment for TTS playback.
 *
 * The processing code is retained for rollback/comparison, but disabled by
 * default so Android plays the clean audio returned by the voice service.
 */
object MobileVoiceEffect {
    private const val TAG = "MobileVoiceEffect"
    private const val ENABLED = false

    fun attachTo(player: MediaPlayer): PlaybackEffects {
        if (!ENABLED) return PlaybackEffects()
        val sessionId = runCatching { player.audioSessionId }.getOrDefault(0)
        if (sessionId == 0) return PlaybackEffects()
        val equalizer = runCatching {
            Equalizer(0, sessionId).apply {
                enabled = false
                configurePhoneMicCurve(this)
                enabled = true
            }
        }.onFailure {
            Log.d(TAG, "Equalizer unavailable: ${it.message}")
        }.getOrNull()
        val loudness = runCatching {
            LoudnessEnhancer(sessionId).apply {
                setTargetGain(320)
                enabled = true
            }
        }.onFailure {
            Log.d(TAG, "LoudnessEnhancer unavailable: ${it.message}")
        }.getOrNull()
        return PlaybackEffects(equalizer, loudness)
    }

    fun newPcmProcessor(sampleRate: Int): PcmProcessor = PcmProcessor(sampleRate.coerceAtLeast(8_000), enabled = ENABLED)

    private fun configurePhoneMicCurve(eq: Equalizer) {
        val range = eq.bandLevelRange
        val minLevel = range.getOrNull(0)?.toInt() ?: -1500
        val maxLevel = range.getOrNull(1)?.toInt() ?: 1500
        for (band in 0 until eq.numberOfBands) {
            val centerHz = eq.getCenterFreq(band.toShort()) / 1000
            val gain = when {
                centerHz < 180 -> -1200
                centerHz < 350 -> -700
                centerHz < 900 -> 250
                centerHz < 2600 -> 650
                centerHz < 4200 -> 350
                centerHz < 6800 -> -300
                else -> -900
            }.coerceIn(minLevel, maxLevel)
            runCatching { eq.setBandLevel(band.toShort(), gain.toShort()) }
        }
    }

    class PlaybackEffects(
        private val equalizer: Equalizer? = null,
        private val loudness: LoudnessEnhancer? = null,
    ) {
        fun release() {
            runCatching { loudness?.enabled = false }
            runCatching { loudness?.release() }
            runCatching { equalizer?.enabled = false }
            runCatching { equalizer?.release() }
        }
    }

    class PcmProcessor(sampleRate: Int, private val enabled: Boolean = ENABLED) {
        private val hpAlpha = exp((-2.0 * Math.PI * 180.0) / sampleRate).toFloat()
        private val lpAlpha = (1f - exp((-2.0 * Math.PI * 5200.0) / sampleRate).toFloat()).coerceIn(0.01f, 1f)
        private var prevInput = 0f
        private var prevHighPass = 0f
        private var lowPass = 0f

        fun processPcm16InPlace(bytes: ByteArray, length: Int = bytes.size) {
            if (!enabled) return
            val safeLength = min(length, bytes.size) and -2
            var offset = 0
            while (offset < safeLength) {
                val sample = ((bytes[offset + 1].toInt() shl 8) or (bytes[offset].toInt() and 0xff)).toShort()
                val x = sample / 32768f
                val highPassed = hpAlpha * (prevHighPass + x - prevInput)
                prevInput = x
                prevHighPass = highPassed
                lowPass += lpAlpha * (highPassed - lowPass)

                var y = lowPass * 1.18f
                val sign = kotlin.math.sign(y)
                if (abs(y) > 0.34f) {
                    y = 0.34f * sign + (y - 0.34f * sign) * 0.42f
                }
                y = softClip(y * 1.25f)
                val out = (y.coerceIn(-0.98f, 0.98f) * 32767f).toInt()
                    .coerceIn(Short.MIN_VALUE.toInt(), Short.MAX_VALUE.toInt())
                bytes[offset] = (out and 0xff).toByte()
                bytes[offset + 1] = ((out shr 8) and 0xff).toByte()
                offset += 2
            }
        }

        private fun softClip(value: Float): Float {
            val x = value.coerceIn(-2.0f, 2.0f)
            val amount = min(1f, max(0f, abs(x)))
            return x * (1.5f - 0.5f * amount * amount)
        }
    }
}
