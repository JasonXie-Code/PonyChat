package top.ponychat.webview.ui.music

import android.app.Application
import android.content.ComponentName
import android.os.Bundle
import android.util.LruCache
import androidx.annotation.OptIn
import androidx.core.content.ContextCompat
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.MediaMetadata
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.session.MediaController
import androidx.media3.session.SessionResult
import androidx.media3.session.SessionToken
import com.google.common.util.concurrent.ListenableFuture
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull
import retrofit2.HttpException
import top.ponychat.webview.data.prefs.AppPreferences

internal data class MusicItem(
    val id: String,
    val title: String,
    val album: String,
    val albumId: String?,
    val artist: String,
    val artwork: String?,
    val durationMs: Long,
    val lyricsStatus: MusicLyricsStatus,
)

internal data class MusicPlayerState(
    val item: MusicItem? = null,
    val queue: List<MusicItem> = emptyList(),
    val durationMs: Long = 0,
    val positionMs: Long = 0,
    val playing: Boolean = false,
    val buffering: Boolean = false,
    val canSeek: Boolean = false,
    val shuffle: Boolean = false,
    val repeat: Int = Player.REPEAT_MODE_OFF,
    val error: Boolean = false,
    val ended: Boolean = false,
) {
    val mode get() = MusicPlaybackMode.fromPlayer(shuffle, repeat)
}

internal enum class MusicPlaybackMode(val label: String, val repeat: Int, val shuffle: Boolean = false) {
    LOOP("循环播放", Player.REPEAT_MODE_ALL),
    SEQUENTIAL("顺序播放", Player.REPEAT_MODE_OFF),
    SINGLE("单曲循环", Player.REPEAT_MODE_ONE),
    SHUFFLE("随机播放", Player.REPEAT_MODE_OFF, shuffle = true);

    fun next() = entries[(ordinal + 1) % entries.size]

    companion object {
        fun fromPlayer(shuffle: Boolean, repeat: Int): MusicPlaybackMode =
            if (shuffle) SHUFFLE else entries.firstOrNull { !it.shuffle && it.repeat == repeat } ?: SEQUENTIAL
    }
}

internal data class MusicCatalogState(
    val data: MusicCatalog? = null,
    val loading: Boolean = false,
    val error: Boolean = false,
)

internal data class MusicSyncIssue(val message: String, val mutation: Boolean)

internal data class MusicLyricsState(
    val trackId: String? = null,
    val lines: List<MusicLyric>? = null,
    val failed: Boolean = false,
    val status: MusicLyricsStatus? = null,
)

internal data class MusicResumeTarget(
    val song: MusicSong,
    val positionMs: Long,
    val snapshot: MusicResumeSnapshot? = null,
)

internal class MusicPlayerViewModel(application: Application) : AndroidViewModel(application) {
    private val prefs = AppPreferences(application)
    private val mutablePlayer = MutableStateFlow(MusicPlayerState())
    val playerState = mutablePlayer.asStateFlow()
    private val mutableLyrics = MutableStateFlow(MusicLyricsState())
    val lyrics = mutableLyrics.asStateFlow()
    private val lyricsCache = LruCache<String, MusicLyricsState>(8)
    private var lyricsJob: Job? = null
    private val mutableCatalog = MutableStateFlow(MusicCatalogState())
    val catalog = mutableCatalog.asStateFlow()
    private val mutableSyncError = MutableStateFlow<MusicSyncIssue?>(null)
    val syncError = mutableSyncError.asStateFlow()
    private val mutablePlayerError = MutableStateFlow<String?>(null)
    val playerError = mutablePlayerError.asStateFlow()
    private val mutableSyncing = MutableStateFlow(false)
    val syncing = mutableSyncing.asStateFlow()
    private var controller: MediaController? = null
    private var future: ListenableFuture<MediaController>? = null
    private var pendingCommand: ((MediaController) -> Unit)? = null
    private val removeLoginListener = prefs.observeAccountChanges {
        pendingCommand = null
        MusicAccountStore.activate(MusicAccount.current(prefs))
        mutableSyncError.value = null
    }
    private val listener = object : Player.Listener {
        override fun onEvents(player: Player, events: Player.Events) {
            publish(refreshQueue = events.containsAny(Player.EVENT_TIMELINE_CHANGED, Player.EVENT_SHUFFLE_MODE_ENABLED_CHANGED))
        }
    }

    init {
        viewModelScope.launch {
            while (isActive) {
                delay(250)
                val player = controller
                if (player?.isPlaying == true && mutablePlayer.subscriptionCount.value > 0) {
                    mutablePlayer.value = mutablePlayer.value.copy(positionMs = player.currentPosition.coerceAtLeast(0))
                }
            }
        }
    }

    fun connect() {
        if (future != null) return
        val context = getApplication<Application>()
        val token = SessionToken(context, ComponentName(context, MusicPlaybackService::class.java))
        val connection = MediaController.Builder(context, token)
            .setListener(object : MediaController.Listener {
                override fun onDisconnected(controller: MediaController) {
                    if (this@MusicPlayerViewModel.controller !== controller) return
                    this@MusicPlayerViewModel.controller = null
                    future = null
                    mutablePlayer.value = MusicPlayerState()
                    preloadLyrics(null)
                }
            })
            .buildAsync()
        future = connection
        connection.addListener({
            if (future !== connection) return@addListener
            try {
                val active = connection.get()
                controller = active
                active.addListener(listener)
                pendingCommand?.invoke(active)
                pendingCommand = null
                mutablePlayerError.value = null
                publish()
            } catch (_: Exception) {
                future = null
                mutablePlayerError.value = "无法连接播放器，请重试"
            }
        }, ContextCompat.getMainExecutor(context))
    }

    fun loadCatalog() {
        if (catalog.value.loading || catalog.value.data != null) return
        mutableCatalog.value = MusicCatalogState(loading = true)
        viewModelScope.launch {
            try {
                mutableCatalog.value = MusicCatalogState(MusicSite.api.catalog())
            } catch (error: CancellationException) {
                throw error
            } catch (_: Exception) {
                mutableCatalog.value = MusicCatalogState(error = true)
            }
        }
    }

    fun refreshLibrary() = sync()

    suspend fun awaitCurrentLyrics() {
        combine(playerState, lyrics) { playback, loaded ->
            val track = playback.item
            track?.lyricsStatus != MusicLyricsStatus.AVAILABLE ||
                (loaded.trackId == track.id && (loaded.lines != null || loaded.failed))
        }.first { it }
    }

    fun retryLyrics() = preloadLyrics(playerState.value.item, retry = true)

    private fun preloadLyrics(item: MusicItem?, retry: Boolean = false) {
        if (!retry && mutableLyrics.value.trackId == item?.id) return
        lyricsJob?.cancel()
        if (item == null || item.lyricsStatus != MusicLyricsStatus.AVAILABLE) {
            mutableLyrics.value = MusicLyricsState(item?.id, emptyList(), status = item?.lyricsStatus)
            return
        }
        val cached = lyricsCache.get(item.id)
        mutableLyrics.value = cached ?: MusicLyricsState(item.id)
        if (cached != null) return
        lyricsJob = viewModelScope.launch {
            val lyrics = try {
                withTimeoutOrNull(6_000) { MusicSite.api.lyrics(item.id) }
            } catch (failure: CancellationException) {
                throw failure
            } catch (_: Exception) {
                null
            }
            if (lyrics == null) {
                mutableLyrics.value = MusicLyricsState(item.id, failed = true)
            } else {
                val status = lyrics.resolvedStatus
                val lines = if (status == MusicLyricsStatus.AVAILABLE) lyrics.lines else emptyList()
                val loaded = MusicLyricsState(item.id, lines, status = status)
                lyricsCache.put(item.id, loaded)
                mutableLyrics.value = loaded
            }
        }
    }

    fun dismissSyncError(issue: MusicSyncIssue) {
        mutableSyncError.compareAndSet(issue, null)
    }

    fun updateLibrary(command: MusicCommand) = sync(command)

    fun createPlaylist(name: String, songId: String? = null) {
        updateLibrary(MusicCommand("createPlaylist", songId = songId, playlistId = newPlaylistId(), name = name))
    }

    private fun sync(command: MusicCommand? = null) {
        val account = MusicAccount.current(prefs)
        MusicAccountStore.activate(account)
        if (account == null || (command == null && syncing.value)) return
        mutableSyncError.value = null
        if (command == null) mutableSyncing.value = true
        viewModelScope.launch {
            try {
                if (command == null) MusicAccountStore.refresh(account)
                else MusicAccountStore.update(account, command)
            } catch (error: CancellationException) {
                throw error
            } catch (error: Exception) {
                if (MusicAccount.current(prefs) == account) {
                    val message = when ((error as? HttpException)?.code()) {
                        401 -> "登录已过期，请重新登录后同步"
                        404 -> "同步失败，歌单或同步接口暂不可用"
                        409 -> "收藏或歌单已达到上限"
                        else -> "同步失败，请检查网络后重试"
                    }
                    mutableSyncError.value = MusicSyncIssue(message, mutation = command != null)
                }
            } finally {
                if (command == null) mutableSyncing.value = false
            }
        }
    }

    fun play(
        songs: List<MusicSong>,
        albums: Map<String, MusicAlbum>,
        songId: String,
        startMs: Long = 0,
        shuffled: Boolean = false,
        resumeQueue: MusicResumeSnapshot? = null,
    ) {
        val items = songs.distinctBy(MusicSong::id).mapNotNull { it.mediaItem(albums[it.albumId]) }
        val index = items.indexOfFirst { it.mediaId == songId }
        if (index < 0) {
            mutablePlayerError.value = "这首歌暂时无法播放"
            return
        }
        mutablePlayerError.value = null
        val start = startMs.coerceAtLeast(0)
        val action: (MediaController) -> Unit = { player ->
            player.setMediaItems(items, index, start)
            if (resumeQueue != null) {
                restoreShuffleOrder(player, items, resumeQueue.shuffleIds)
                player.repeatMode = resumeQueue.repeat
            } else if (shuffled) player.repeatMode = Player.REPEAT_MODE_OFF
            player.shuffleModeEnabled = shuffled
            player.prepare()
            player.play()
        }
        val active = controller
        if (active == null) {
            pendingCommand = action
            connect()
        } else action(active)
    }

    @OptIn(UnstableApi::class)
    private fun restoreShuffleOrder(controller: MediaController, items: List<MediaItem>, shuffledIds: List<String>) {
        if (shuffledIds.isEmpty()) return
        val indices = items.withIndex().associate { it.value.mediaId to it.index }
        val order = shuffledIds.mapNotNull(indices::get).distinct()
        if (order.size != items.size) return
        setShuffleOrder(controller, order)
    }

    @OptIn(UnstableApi::class)
    private fun setShuffleOrder(controller: MediaController, order: List<Int>) {
        val args = Bundle().apply { putIntArray(MusicPlaybackService.SHUFFLE_ORDER, order.toIntArray()) }
        controller.sendCustomCommand(MusicPlaybackService.RESTORE_SHUFFLE_COMMAND, args)
    }

    fun resumeTarget(catalog: MusicCatalog, library: MyMusic, playback: MusicPlayerState): MusicResumeTarget? {
        if (!library.historyEnabled) return null
        val liveSong = playback.item?.takeUnless { playback.ended }?.id?.let(catalog.songsById::get)
        if (liveSong?.src != null) return MusicResumeTarget(liveSong, playback.positionMs)

        val finishedSong = playback.item?.id?.takeIf { playback.ended }
        val recent = library.history.firstOrNull {
            it.songId != finishedSong && it.positionMs > 0 && catalog.songsById[it.songId]?.src != null
        }
        val owner = MusicAccount.current(prefs)?.resumeOwner
        val snapshot = prefs.readMusicResume()?.takeIf {
            it.owner == owner && it.revision == library.historyRevision && it.savedAtMs >= (recent?.playedAtMs ?: 0L) &&
                it.songId != finishedSong
        }
        val savedSong = snapshot?.songId?.let(catalog.songsById::get)
        if (savedSong?.src != null) return MusicResumeTarget(savedSong, snapshot.positionMs, snapshot)
        return recent?.let { MusicResumeTarget(catalog.songsById.getValue(it.songId), it.positionMs) }
    }

    fun resume(catalog: MusicCatalog, target: MusicResumeTarget, albumSongs: List<MusicSong>) {
        val active = controller
        if (active?.currentMediaItem?.mediaId == target.song.id && active.playbackState != Player.STATE_ENDED) {
            if (active.playerError != null || active.playbackState == Player.STATE_IDLE) active.prepare()
            active.play()
            return
        }
        val savedQueue = target.snapshot
        val tracks = savedQueue?.songIds?.mapNotNull(catalog.songsById::get) ?: albumSongs
        play(
            tracks, catalog.albumsById, target.song.id, target.positionMs,
            shuffled = savedQueue?.shuffleIds?.isNotEmpty() == true,
            resumeQueue = savedQueue,
        )
    }

    fun toggle() {
        val active = controller ?: return
        if (active.playerError != null) {
            active.prepare()
            active.play()
        } else if (active.playWhenReady && active.playbackState != Player.STATE_ENDED) {
            active.pause()
        } else {
            if (active.playbackState == Player.STATE_ENDED) active.seekTo(0)
            active.play()
        }
    }

    @OptIn(UnstableApi::class)
    fun playNext(song: MusicSong, album: MusicAlbum?, onResult: (String) -> Unit) {
        val item = song.mediaItem(album)
        if (item == null) {
            onResult("这首歌暂时无法播放")
            return
        }
        val active = controller
        if (active == null) {
            connect()
            onResult("正在连接播放器，请稍后重试")
            return
        }
        val args = Bundle().apply {
            putBundle(MusicPlaybackService.PLAY_NEXT_ITEM, item.toBundleIncludeLocalConfiguration())
        }
        val request = active.sendCustomCommand(MusicPlaybackService.PLAY_NEXT_COMMAND, args)
        request.addListener({
            val result = runCatching { request.get() }.getOrNull()
            val message = if (result?.resultCode == SessionResult.RESULT_SUCCESS) {
                "已排到下一首"
            } else {
                "添加下一首失败，请重试"
            }
            onResult(message)
        }, ContextCompat.getMainExecutor(getApplication()))
    }

    fun canSkipTrack(trackId: String, forward: Boolean): Boolean =
        controller?.canSkipFrom(trackId, forward) == true

    fun skipTrack(trackId: String, forward: Boolean): Boolean {
        val player = controller ?: return false
        if (!player.canSkipFrom(trackId, forward)) return false
        if (forward) player.seekToNextMediaItem() else player.seekToPreviousMediaItem()
        if (player.playbackState == Player.STATE_IDLE) player.prepare()
        player.play()
        return true
    }

    private fun MediaController.canSkipFrom(trackId: String, forward: Boolean): Boolean {
        if (currentMediaItem?.mediaId != trackId || mediaItemCount < 2) return false
        return if (forward) {
            hasNextMediaItem() && isCommandAvailable(Player.COMMAND_SEEK_TO_NEXT_MEDIA_ITEM)
        } else {
            hasPreviousMediaItem() && isCommandAvailable(Player.COMMAND_SEEK_TO_PREVIOUS_MEDIA_ITEM)
        }
    }

    fun seek(positionMs: Long) { controller?.seekTo(positionMs.coerceAtLeast(0)) }

    fun seekTrack(trackId: String, positionMs: Long) {
        val player = controller ?: return
        if (player.currentMediaItem?.mediaId == trackId && player.isCurrentMediaItemSeekable &&
            player.isCommandAvailable(Player.COMMAND_SEEK_IN_CURRENT_MEDIA_ITEM)
        ) {
            seek(positionMs)
        }
    }

    fun cyclePlaybackMode(): MusicPlaybackMode? {
        val active = controller ?: return null
        val mode = MusicPlaybackMode.fromPlayer(active.shuffleModeEnabled, active.repeatMode).next()
        active.repeatMode = mode.repeat
        active.shuffleModeEnabled = mode.shuffle
        return mode
    }

    fun playQueueItem(songId: String) {
        val active = controller ?: return
        val index = (0 until active.mediaItemCount).firstOrNull { active.getMediaItemAt(it).mediaId == songId } ?: return
        active.seekToDefaultPosition(index)
        active.play()
    }

    @OptIn(UnstableApi::class)
    fun moveQueueItem(songId: String, targetId: String) {
        if (songId == targetId) return
        val active = controller ?: return
        val indices = (0 until active.mediaItemCount).associateBy { active.getMediaItemAt(it).mediaId }
        val from = indices[songId] ?: return
        val to = indices[targetId] ?: return
        if (active.shuffleModeEnabled) {
            val order = active.currentTimeline.musicShuffleIndices().toMutableList()
            val destination = order.indexOf(to)
            if (destination < 0 || !order.remove(from)) return
            order.add(destination, from)
            setShuffleOrder(active, order)
        } else {
            active.moveMediaItem(from, to)
        }
    }

    @OptIn(UnstableApi::class)
    private fun publish(refreshQueue: Boolean = true) {
        val active = controller ?: return
        val item = active.currentMediaItem?.toMusicItem()
        preloadLyrics(item)
        mutablePlayer.value = MusicPlayerState(
            item = item,
            queue = if (refreshQueue) {
                val order = if (active.shuffleModeEnabled) active.currentTimeline.musicShuffleIndices()
                else 0 until active.mediaItemCount
                order.map { active.getMediaItemAt(it).toMusicItem() }
            } else mutablePlayer.value.queue,
            durationMs = active.duration.takeIf { it != C.TIME_UNSET && it > 0 } ?: item?.durationMs ?: 0,
            positionMs = active.currentPosition.coerceAtLeast(0),
            playing = active.isPlaying,
            buffering = active.playbackState == Player.STATE_BUFFERING && active.playWhenReady,
            canSeek = active.isCurrentMediaItemSeekable,
            shuffle = active.shuffleModeEnabled,
            repeat = active.repeatMode,
            error = active.playerError != null,
            ended = active.playbackState == Player.STATE_ENDED,
        )
    }

    override fun onCleared() {
        removeLoginListener()
        controller?.removeListener(listener)
        val connection = future
        future = null
        if (connection != null) MediaController.releaseFuture(connection)
    }
}

private fun MusicSong.mediaItem(album: MusicAlbum?): MediaItem? {
    val uri = MusicSite.mediaUri(src) ?: return null
    val details = Bundle().apply {
        putLong("duration", ((duration ?: 0.0) * 1000).toLong())
        putString("lyricsStatus", resolvedLyricsStatus.apiValue)
        putString("albumId", albumId)
    }
    val metadata = MediaMetadata.Builder()
        .setTitle(title)
        .setArtist(artist ?: album?.title)
        .setAlbumTitle(album?.title)
        .setArtworkUri(MusicSite.mediaUri(album?.cover))
        .setExtras(details)
        .build()
    return MediaItem.Builder().setMediaId(id).setUri(uri).setMediaMetadata(metadata).build()
}

private fun MediaItem.toMusicItem() = MusicItem(
    id = mediaId,
    title = mediaMetadata.title?.toString().orEmpty(),
    album = mediaMetadata.albumTitle?.toString().orEmpty(),
    albumId = mediaMetadata.extras?.getString("albumId"),
    artist = mediaMetadata.artist?.toString().orEmpty(),
    artwork = mediaMetadata.artworkUri?.toString(),
    durationMs = mediaMetadata.extras?.getLong("duration") ?: 0,
    lyricsStatus = MusicLyricsStatus.fromApi(
        mediaMetadata.extras?.getString("lyricsStatus")
            ?: "available".takeIf { mediaMetadata.extras?.getBoolean("lyrics") == true },
    ),
)
