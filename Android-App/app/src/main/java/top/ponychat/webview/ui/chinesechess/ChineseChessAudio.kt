package top.ponychat.webview.ui.chinesechess

import android.content.Context
import android.media.AudioAttributes
import android.media.MediaPlayer
import android.media.SoundPool
import android.os.Handler
import android.os.Looper
import java.io.File
import kotlin.coroutines.resume
import kotlinx.coroutines.suspendCancellableCoroutine
import top.ponychat.webview.R
import top.ponychat.webview.audio.MobileVoiceEffect
import top.ponychat.webview.data.local.CachedVoiceAudio

internal const val XIANGQI_VOICE_TIMEOUT_MS = 30_000L
internal const val XIANGQI_FINAL_TEXT_HOLD_MS = 0L
internal const val XIANGQI_VOICE_MAX_PARALLEL_SYNTHESIS = 4

internal class XiangqiSfxPlayer(context: Context) {
    private val handler = Handler(Looper.getMainLooper())
    private val soundPool = SoundPool.Builder()
        .setMaxStreams(4)
        .setAudioAttributes(
            AudioAttributes.Builder()
                .setUsage(AudioAttributes.USAGE_GAME)
                .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                .build()
        )
        .build()
    private val pickupId: Int
    private val dropId: Int
    private val captureOneId: Int
    private val captureTwoId: Int
    private val checkId: Int
    private val checkedId: Int
    private val winId: Int
    private val loseId: Int

    init {
        val appContext = context.applicationContext
        pickupId = soundPool.load(appContext, R.raw.xiangqi_pickup, 1)
        dropId = soundPool.load(appContext, R.raw.xiangqi_drop, 1)
        captureOneId = soundPool.load(appContext, R.raw.xiangqi_capture_1, 1)
        captureTwoId = soundPool.load(appContext, R.raw.xiangqi_capture_2, 1)
        checkId = soundPool.load(appContext, R.raw.xiangqi_check, 1)
        checkedId = soundPool.load(appContext, R.raw.xiangqi_checked, 1)
        winId = soundPool.load(appContext, R.raw.xiangqi_win, 1)
        loseId = soundPool.load(appContext, R.raw.xiangqi_lose, 1)
    }

    fun playPickup() {
        playNow(pickupId, volume = 0.54f)
    }

    fun playSetupPiece() {
        playNow(dropId, volume = 0.42f)
    }

    fun playMove(isCapture: Boolean, givesCheck: Boolean, playerInCheck: Boolean) {
        val checkSoundId = if (playerInCheck) checkedId else checkId
        if (isCapture) {
            playNow(captureOneId, volume = 0.68f)
            handler.postDelayed({ playNow(captureTwoId, volume = 0.66f) }, 300L)
            if (givesCheck) {
                handler.postDelayed({ playNow(checkSoundId, volume = 0.72f) }, 560L)
            }
        } else {
            playNow(dropId, volume = 0.62f)
            if (givesCheck) {
                handler.postDelayed({ playNow(checkSoundId, volume = 0.72f) }, 260L)
            }
        }
    }

    fun playGameOver(playerWon: Boolean, delayMillis: Long) {
        val soundId = if (playerWon) winId else loseId
        val volume = if (playerWon) 0.74f else 0.72f
        handler.postDelayed({ playNow(soundId, volume = volume) }, delayMillis)
    }

    fun release() {
        handler.removeCallbacksAndMessages(null)
        soundPool.release()
    }

    private fun playNow(soundId: Int, volume: Float) {
        soundPool.play(soundId, volume, volume, 1, 0, 1f)
    }
}

internal class XiangqiVoicePlaybackController {
    private var player: MediaPlayer? = null
    private var effects: MobileVoiceEffect.PlaybackEffects? = null

    suspend fun play(audio: CachedVoiceAudio): Boolean = suspendCancellableCoroutine { cont ->
        stop()
        val file = File(audio.localFile)
        if (!file.exists() || file.length() <= 0L) {
            cont.resume(false)
            return@suspendCancellableCoroutine
        }
        runCatching {
            val nextPlayer = MediaPlayer()
            player = nextPlayer
            nextPlayer.apply {
                setDataSource(file.absolutePath)
                setOnCompletionListener {
                    if (cont.isActive) cont.resume(true)
                    stop()
                }
                setOnErrorListener { _, _, _ ->
                    if (cont.isActive) cont.resume(false)
                    stop()
                    true
                }
                prepare()
            }
            effects = MobileVoiceEffect.attachTo(nextPlayer)
            nextPlayer.start()
        }.getOrElse {
            stop()
            if (cont.isActive) cont.resume(false)
            return@suspendCancellableCoroutine
        }
        cont.invokeOnCancellation { stop() }
    }

    fun stop() {
        effects?.release()
        effects = null
        player?.let { active ->
            runCatching {
                if (active.isPlaying) active.stop()
            }
            runCatching { active.release() }
        }
        player = null
    }
}
