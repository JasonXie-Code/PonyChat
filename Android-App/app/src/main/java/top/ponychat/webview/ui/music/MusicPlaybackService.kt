package top.ponychat.webview.ui.music

import android.app.PendingIntent
import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import androidx.annotation.OptIn
import androidx.media3.common.AudioAttributes
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.ShuffleOrder.DefaultShuffleOrder
import androidx.media3.session.MediaSession
import androidx.media3.session.MediaSessionService
import androidx.media3.session.SessionCommand
import androidx.media3.session.SessionResult
import com.google.common.util.concurrent.Futures
import com.google.common.util.concurrent.ListenableFuture
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import retrofit2.HttpException
import top.ponychat.webview.MainActivity
import top.ponychat.webview.data.prefs.AppPreferences
import java.util.UUID
import kotlin.random.Random

@OptIn(UnstableApi::class)
class MusicPlaybackService : MediaSessionService() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private lateinit var player: ExoPlayer
    private lateinit var session: MediaSession
    private lateinit var prefs: AppPreferences
    private var removeLoginListener: (() -> Unit)? = null
    private var account: MusicAccount? = null
    private var currentPlay: TrackedPlay? = null
    private val pending = linkedMapOf<String, MusicCommand>()
    private var lastTick = 0L
    private var wasPlaying = false
    private var lastSyncAttempt = 0L
    private var checkpointJob: Job? = null
    private var syncJob: Job? = null
    private var lastResumeSave = 0L

    override fun onCreate() {
        super.onCreate()
        prefs = AppPreferences(this)
        account = MusicAccount.current(prefs)
        MusicAccountStore.activate(account)
        removeLoginListener = prefs.observeAccountChanges(::handleAccountChange)

        player = ExoPlayer.Builder(this)
            .setAudioAttributes(
                AudioAttributes.Builder().setUsage(C.USAGE_MEDIA).setContentType(C.AUDIO_CONTENT_TYPE_MUSIC).build(),
                true,
            )
            .setHandleAudioBecomingNoisy(true)
            .setWakeMode(C.WAKE_MODE_LOCAL)
            .build()
        val openPlayer = PendingIntent.getActivity(
            this, 601,
            Intent(this, MainActivity::class.java).setAction(OPEN_PLAYER),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        session = MediaSession.Builder(this, player)
            .setSessionActivity(openPlayer)
            .setCallback(PlaybackSessionCallback())
            .build()
        MusicSpeechInterruption.pause = { player.pause() }
        player.addListener(object : Player.Listener {
            override fun onMediaItemTransition(mediaItem: MediaItem?, reason: Int) {
                val finished = reason == Player.MEDIA_ITEM_TRANSITION_REASON_AUTO ||
                    reason == Player.MEDIA_ITEM_TRANSITION_REASON_REPEAT
                currentPlay?.let { checkpoint(it, force = true, complete = finished) }
                currentPlay = mediaItem?.let { startPlay(it.mediaId) }
                if (currentPlay != null) startTracking()
                wasPlaying = false
                lastTick = SystemClock.elapsedRealtime()
            }

            override fun onIsPlayingChanged(isPlaying: Boolean) {
                val active = currentPlay ?: return
                if (isPlaying && active.completed) {
                    currentPlay = startPlay(active.songId)
                } else {
                    sample()
                    if (!isPlaying) checkpoint(active, force = true)
                }
                wasPlaying = isPlaying
                lastTick = SystemClock.elapsedRealtime()
            }

            override fun onPlaybackStateChanged(playbackState: Int) {
                if (playbackState == Player.STATE_ENDED) {
                    sample()
                    currentPlay?.let { checkpoint(it, force = true, complete = true) }
                }
            }

            override fun onPositionDiscontinuity(
                oldPosition: Player.PositionInfo,
                newPosition: Player.PositionInfo,
                reason: Int,
            ) {
                if (reason == Player.DISCONTINUITY_REASON_SEEK && oldPosition.mediaItemIndex == newPosition.mediaItemIndex) {
                    currentPlay?.let {
                        it.positionMs = newPosition.positionMs
                        if (!player.isPlaying) checkpoint(it, force = true)
                    }
                }
            }

            override fun onEvents(player: Player, events: Player.Events) {
                if (events.containsAny(
                        Player.EVENT_TIMELINE_CHANGED, Player.EVENT_MEDIA_ITEM_TRANSITION,
                        Player.EVENT_PLAYBACK_STATE_CHANGED, Player.EVENT_PLAY_WHEN_READY_CHANGED,
                        Player.EVENT_POSITION_DISCONTINUITY, Player.EVENT_SHUFFLE_MODE_ENABLED_CHANGED,
                        Player.EVENT_REPEAT_MODE_CHANGED,
                    )
                ) saveQueueForResume()
            }
        })
    }

    private inner class PlaybackSessionCallback : MediaSession.Callback {
        override fun onConnect(session: MediaSession, controller: MediaSession.ControllerInfo): MediaSession.ConnectionResult {
            val defaults = super.onConnect(session, controller)
            if (!defaults.isAccepted || !isOwnController(controller)) return defaults
            val commands = defaults.availableSessionCommands.buildUpon()
                .add(PLAY_NEXT_COMMAND).add(RESTORE_SHUFFLE_COMMAND).build()
            return MediaSession.ConnectionResult.accept(commands, defaults.availablePlayerCommands)
        }

        override fun onCustomCommand(
            session: MediaSession,
            controller: MediaSession.ControllerInfo,
            command: SessionCommand,
            args: Bundle,
        ): ListenableFuture<SessionResult> {
            if (command != PLAY_NEXT_COMMAND && command != RESTORE_SHUFFLE_COMMAND) {
                return super.onCustomCommand(session, controller, command, args)
            }
            if (!isOwnController(controller)) {
                return Futures.immediateFuture(SessionResult(SessionResult.RESULT_ERROR_PERMISSION_DENIED))
            }
            if (command == RESTORE_SHUFFLE_COMMAND) {
                val order = args.getIntArray(SHUFFLE_ORDER)
                if (order == null || order.size != player.mediaItemCount ||
                    order.toSet() != player.mediaItemIndices.toSet()
                ) return Futures.immediateFuture(SessionResult(SessionResult.RESULT_ERROR_BAD_VALUE))
                player.setShuffleOrder(DefaultShuffleOrder(order, Random.nextLong()))
                return Futures.immediateFuture(SessionResult(SessionResult.RESULT_SUCCESS))
            }
            val item = args.getBundle(PLAY_NEXT_ITEM)?.let(MediaItem::fromBundle)
            if (item?.localConfiguration == null || item.mediaId.isBlank()) {
                return Futures.immediateFuture(SessionResult(SessionResult.RESULT_ERROR_BAD_VALUE))
            }
            enqueueNext(item)
            return Futures.immediateFuture(SessionResult(SessionResult.RESULT_SUCCESS))
        }

        private fun isOwnController(controller: MediaSession.ControllerInfo): Boolean =
            controller.packageName == packageName && controller.uid == applicationInfo.uid
    }

    private fun enqueueNext(item: MediaItem) {
        if (player.mediaItemCount == 0) {
            player.pause()
            player.addMediaItem(item)
            player.prepare()
            return
        }

        val shuffled = player.currentTimeline.musicShuffleIndices()
        val songIds = player.mediaItemIndices.map { player.getMediaItemAt(it).mediaId }
        val insertion = planMusicQueueInsertion(songIds, player.currentMediaItemIndex, item.mediaId, shuffled)
        val existingIndex = insertion.existingIndex
        if (existingIndex == null) {
            player.addMediaItem(insertion.nextIndex, item)
        } else if (existingIndex != insertion.nextIndex) {
            player.moveMediaItem(existingIndex, insertion.nextIndex)
        }
        if (existingIndex != insertion.nextIndex || shuffled != insertion.shuffleOrder) {
            player.setShuffleOrder(DefaultShuffleOrder(insertion.shuffleOrder.toIntArray(), Random.nextLong()))
        }
    }

    private fun startTracking() {
        if (checkpointJob?.isActive != true) {
            checkpointJob = scope.launch {
                while (isActive && currentPlay != null) {
                    delay(500)
                    sample()
                }
            }
        }
        if (syncJob?.isActive != true) {
            syncJob = scope.launch {
                while (isActive && (currentPlay != null || pending.isNotEmpty())) {
                    delay(750)
                    syncHistory()
                }
            }
        }
    }

    private fun handleAccountChange() {
        val previous = account
        account = MusicAccount.current(prefs)
        MusicAccountStore.activate(account)
        if (previous != account) {
            if (previous?.resumeOwner != account?.resumeOwner) prefs.writeMusicResume(null)
            checkpointJob?.cancel()
            syncJob?.cancel()
            currentPlay = null
            pending.clear()
            player.pause()
            player.clearMediaItems()
        }
    }

    private fun startPlay(songId: String) = TrackedPlay(
        songId = songId,
        revision = MusicAccountStore.library(account)?.historyRevision,
    )

    private fun sample() {
        val now = SystemClock.elapsedRealtime()
        if (player.isPlaying && now - lastResumeSave >= RESUME_SAVE_INTERVAL_MS) saveQueueForResume()
        val active = currentPlay
        if (active != null && !active.completed) {
            if (wasPlaying) active.listenedMs += (now - lastTick).coerceIn(0, 1000)
            if (player.currentMediaItem?.mediaId == active.songId) active.positionMs = player.currentPosition.coerceAtLeast(0)
            checkpoint(active)
        }
        lastTick = now
        wasPlaying = player.isPlaying
    }

    private val Player.mediaItemIndices get() = 0 until mediaItemCount

    private fun saveQueueForResume() {
        lastResumeSave = SystemClock.elapsedRealtime()
        val currentAccount = account ?: return
        val library = MusicAccountStore.library(currentAccount) ?: return
        val songId = player.currentMediaItem?.mediaId ?: return
        val playbackRevision = currentPlay?.revision
        if (!library.historyEnabled || player.playbackState == Player.STATE_ENDED ||
            (playbackRevision != null && playbackRevision != library.historyRevision)
        ) {
            prefs.writeMusicResume(null)
            return
        }
        val position = player.currentPosition
        if (position <= 0 || (player.duration > 0 && position >= player.duration - 1500)) return
        val songIds = player.mediaItemIndices.map { player.getMediaItemAt(it).mediaId }
        prefs.writeMusicResume(
            MusicResumeSnapshot(
                currentAccount.resumeOwner, library.historyRevision, songId, songIds, position,
                System.currentTimeMillis(),
                if (player.shuffleModeEnabled) player.currentTimeline.musicShuffleIndices().map(songIds::get) else emptyList(),
                player.repeatMode,
            ),
        )
    }

    private fun checkpoint(active: TrackedPlay, force: Boolean = false, complete: Boolean = false) {
        if (active.completed) return
        active.completed = complete
        val library = MusicAccountStore.library(account) ?: return
        val revision = active.revision ?: library.historyRevision.also { active.revision = it }
        if (!library.historyEnabled || revision != library.historyRevision || active.listenedMs < MIN_LISTEN_MS) return
        if (active.savedAtMs >= 0 && !force && active.listenedMs - active.savedAtMs < CHECKPOINT_INTERVAL_MS) return

        val position = if (complete || (player.currentMediaItem?.mediaId == active.songId &&
                player.duration > 0 && active.positionMs >= player.duration - 1500)) 0L else active.positionMs
        if (position == active.lastQueuedPosition) return
        active.lastQueuedPosition = position
        active.savedAtMs = active.listenedMs
        pending[active.playId] = MusicCommand(
            action = "record", songId = active.songId, playId = active.playId,
            revision = revision, sequence = ++active.sequence, positionMs = position,
        )
        if (pending.size > 32) pending.remove(pending.keys.first())
    }

    private suspend fun syncHistory() {
        val currentAccount = account ?: return
        val now = SystemClock.elapsedRealtime()
        if (now - lastSyncAttempt < 4000) return
        val library = MusicAccountStore.library(currentAccount)
        if (library == null) {
            if (currentPlay == null) return
            lastSyncAttempt = now
            syncAttempt { MusicAccountStore.refresh(currentAccount) }
            return
        }
        val command = pending.values.firstOrNull() ?: return
        if (command.revision != library.historyRevision || !library.historyEnabled) {
            pending.remove(command.playId)
            return
        }
        lastSyncAttempt = now
        val handled = syncAttempt(discardRejected = true) { MusicAccountStore.update(currentAccount, command) }
        if (handled && account == currentAccount && pending[command.playId] == command) pending.remove(command.playId)
    }

    private suspend fun syncAttempt(discardRejected: Boolean = false, action: suspend () -> MyMusic?): Boolean {
        return try {
            action() != null
        } catch (error: CancellationException) {
            throw error
        } catch (error: HttpException) {
            discardRejected && error.code() in setOf(400, 404, 409, 422)
        } catch (_: Exception) {
            false
        }
    }

    override fun onGetSession(controllerInfo: MediaSession.ControllerInfo): MediaSession = session

    override fun onDestroy() {
        saveQueueForResume()
        MusicSpeechInterruption.pause = null
        removeLoginListener?.invoke()
        scope.cancel()
        session.release()
        player.release()
        super.onDestroy()
    }

    private class TrackedPlay(val songId: String, var revision: Long?) {
        val playId: String = UUID.randomUUID().toString()
        var sequence = 0L
        var listenedMs = 0L
        var positionMs = 0L
        var savedAtMs = -1L
        var lastQueuedPosition = -1L
        var completed = false
    }

    companion object {
        internal const val OPEN_PLAYER = "top.ponychat.webview.OPEN_MUSIC_PLAYER"
        internal val PLAY_NEXT_COMMAND = SessionCommand("top.ponychat.webview.PLAY_MUSIC_NEXT", Bundle.EMPTY)
        internal const val PLAY_NEXT_ITEM = "mediaItem"
        internal val RESTORE_SHUFFLE_COMMAND = SessionCommand("top.ponychat.webview.RESTORE_MUSIC_SHUFFLE", Bundle.EMPTY)
        internal const val SHUFFLE_ORDER = "shuffleOrder"
        private const val RESUME_SAVE_INTERVAL_MS = 10_000L
        private const val MIN_LISTEN_MS = 5000L
        private const val CHECKPOINT_INTERVAL_MS = 20_000L
    }
}

internal object MusicSpeechInterruption {
    var pause: (() -> Unit)? = null

    fun pauseMusic() {
        if (Looper.myLooper() == Looper.getMainLooper()) pause?.invoke()
        else Handler(Looper.getMainLooper()).post { pause?.invoke() }
    }
}
