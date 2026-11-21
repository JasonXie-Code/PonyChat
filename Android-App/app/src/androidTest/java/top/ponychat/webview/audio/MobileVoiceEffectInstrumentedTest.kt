package top.ponychat.webview.audio

import android.media.MediaPlayer
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.assertArrayEquals
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class MobileVoiceEffectInstrumentedTest {
    @Test
    fun pcmProcessorLeavesAudioBytesUnchangedWhenDisabled() {
        val original = ByteArray(4096) { index ->
            (((index * 37) + (index / 3)) and 0xff).toByte()
        }
        val processed = original.copyOf()

        MobileVoiceEffect
            .newPcmProcessor(sampleRate = 24_000)
            .processPcm16InPlace(processed)

        assertArrayEquals(original, processed)
    }

    @Test
    fun playbackEffectsAttachIsNoopWhenDisabled() {
        val effects = MobileVoiceEffect.attachTo(MediaPlayer())
        effects.release()
    }
}
