package top.ponychat.webview.ui.doudizhu

import android.content.Context
import android.media.AudioAttributes
import android.media.SoundPool
import android.util.Log
import java.util.Collections
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.withTimeoutOrNull
import kotlin.random.Random
import top.ponychat.webview.BuildConfig
import top.ponychat.webview.R

internal enum class DoudizhuSfxGroup {
    Deal,
    Single,
    Pair,
    Medium,
    Many
}

internal fun doudizhuCardSfxGroupForCount(cardCount: Int): DoudizhuSfxGroup? = when {
    cardCount <= 0 -> null
    cardCount == 1 -> DoudizhuSfxGroup.Single
    cardCount == 2 -> DoudizhuSfxGroup.Pair
    cardCount in 3..5 -> DoudizhuSfxGroup.Medium
    else -> DoudizhuSfxGroup.Many
}

internal class DoudizhuSfxPlayer(context: Context) {
    private val loadedSoundIds = Collections.synchronizedSet(mutableSetOf<Int>())
    private val loadLock = Any()
    private val ready = CompletableDeferred<Unit>()
    private val variantPicker = DoudizhuSfxVariantPicker()
    private val soundPool = SoundPool.Builder()
        .setMaxStreams(6)
        .setAudioAttributes(
            AudioAttributes.Builder()
                .setUsage(AudioAttributes.USAGE_GAME)
                .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                .build()
        )
        .build()

    private val dealIds: IntArray
    private val singleIds: IntArray
    private val pairIds: IntArray
    private val mediumIds: IntArray
    private val manyIds: IntArray
    private var loadedResultCount = 0

    init {
        soundPool.setOnLoadCompleteListener { _, sampleId, status ->
            if (status == 0) {
                loadedSoundIds += sampleId
            } else {
                Log.w(TAG, "load failed: sampleId=$sampleId status=$status")
            }
            synchronized(loadLock) {
                loadedResultCount += 1
                if (loadedResultCount >= DDZ_SFX_RESOURCE_COUNT && !ready.isCompleted) {
                    ready.complete(Unit)
                }
            }
        }
        val appContext = context.applicationContext
        dealIds = intArrayOf(
            soundPool.load(appContext, R.raw.doudizhu_deal_1, 1),
            soundPool.load(appContext, R.raw.doudizhu_deal_2, 1),
            soundPool.load(appContext, R.raw.doudizhu_deal_3, 1)
        )
        singleIds = intArrayOf(
            soundPool.load(appContext, R.raw.doudizhu_play_single_1, 1),
            soundPool.load(appContext, R.raw.doudizhu_play_single_2, 1)
        )
        pairIds = intArrayOf(
            soundPool.load(appContext, R.raw.doudizhu_play_pair_1, 1),
            soundPool.load(appContext, R.raw.doudizhu_play_pair_2, 1)
        )
        mediumIds = intArrayOf(
            soundPool.load(appContext, R.raw.doudizhu_play_medium_1, 1),
            soundPool.load(appContext, R.raw.doudizhu_play_medium_2, 1)
        )
        manyIds = intArrayOf(
            soundPool.load(appContext, R.raw.doudizhu_play_many_1, 1),
            soundPool.load(appContext, R.raw.doudizhu_play_many_2, 1)
        )
    }

    suspend fun awaitReady() {
        withTimeoutOrNull(DDZ_SFX_LOAD_TIMEOUT_MS) {
            ready.await()
        }
    }

    fun playDeal() {
        playVariant(DoudizhuSfxGroup.Deal, dealIds, volume = DDZ_DEAL_VOLUME)
    }

    fun playCards(cardCount: Int) {
        when (doudizhuCardSfxGroupForCount(cardCount)) {
            DoudizhuSfxGroup.Single -> playVariant(DoudizhuSfxGroup.Single, singleIds, volume = DDZ_SINGLE_VOLUME)
            DoudizhuSfxGroup.Pair -> playVariant(DoudizhuSfxGroup.Pair, pairIds, volume = DDZ_PAIR_VOLUME)
            DoudizhuSfxGroup.Medium -> playVariant(DoudizhuSfxGroup.Medium, mediumIds, volume = DDZ_MEDIUM_VOLUME)
            DoudizhuSfxGroup.Many -> playVariant(DoudizhuSfxGroup.Many, manyIds, volume = DDZ_MANY_VOLUME)
            DoudizhuSfxGroup.Deal,
            null -> Unit
        }
    }

    fun release() {
        loadedSoundIds.clear()
        soundPool.release()
    }

    private fun playVariant(group: DoudizhuSfxGroup, soundIds: IntArray, volume: Float) {
        if (soundIds.isEmpty()) return
        val soundId = soundIds[variantPicker.nextIndex(group, soundIds.size)]
        if (soundId == 0) return
        if (soundId !in loadedSoundIds) {
            Log.w(TAG, "play skipped before load: group=$group sampleId=$soundId")
            return
        }
        playNow(soundId, volume = volume)
        logDebug("played $group sampleId=$soundId volume=$volume")
    }

    private fun playNow(soundId: Int, volume: Float) {
        val streamId = soundPool.play(soundId, volume, volume, 1, 0, 1f)
        if (streamId == 0) {
            Log.w(TAG, "play returned 0: sampleId=$soundId")
        }
    }
}

internal class DoudizhuSfxVariantPicker(
    private val random: Random = Random.Default
) {
    private val lastIndexByGroup = mutableMapOf<DoudizhuSfxGroup, Int>()

    fun nextIndex(group: DoudizhuSfxGroup, size: Int): Int {
        if (size <= 1) return 0
        val lastIndex = lastIndexByGroup[group]
        val nextIndex = if (lastIndex == null || lastIndex !in 0 until size) {
            random.nextInt(size)
        } else {
            val candidate = random.nextInt(size - 1)
            if (candidate >= lastIndex) candidate + 1 else candidate
        }
        lastIndexByGroup[group] = nextIndex
        return nextIndex
    }
}

private const val TAG = "DoudizhuSfx"
private const val DDZ_SFX_RESOURCE_COUNT = 11
private const val DDZ_SFX_LOAD_TIMEOUT_MS = 1_000L
private const val DDZ_DEAL_VOLUME = 0.38f
private const val DDZ_SINGLE_VOLUME = 0.62f
private const val DDZ_PAIR_VOLUME = 0.64f
private const val DDZ_MEDIUM_VOLUME = 0.66f
private const val DDZ_MANY_VOLUME = 0.68f

private fun logDebug(message: String) {
    if (BuildConfig.DEBUG) {
        Log.d(TAG, message)
    }
}

internal fun DoudizhuSfxPlayer.playCardsIfHandShrank(
    previous: DdzGameState,
    next: DdzGameState,
    seat: DdzSeat
) {
    val play = next.lastPlay ?: return
    if (play.seat == seat && !play.pass && next.hand(seat).size < previous.hand(seat).size) {
        playCards(play.cards.size)
    }
}
