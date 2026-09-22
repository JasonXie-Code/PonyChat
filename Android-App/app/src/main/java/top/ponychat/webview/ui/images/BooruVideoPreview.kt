@file:androidx.annotation.OptIn(androidx.media3.common.util.UnstableApi::class)

package top.ponychat.webview.ui.images

import android.content.Context
import android.graphics.Matrix
import android.os.Build
import android.view.TextureView
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.viewinterop.AndroidView
import androidx.media3.common.MediaItem
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.common.VideoSize
import androidx.media3.exoplayer.DefaultLoadControl
import androidx.media3.exoplayer.DefaultRenderersFactory
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.mediacodec.MediaCodecSelector
import androidx.media3.datasource.DefaultDataSource
import androidx.media3.datasource.HttpDataSource
import androidx.media3.datasource.cache.CacheDataSource
import androidx.media3.datasource.cache.LeastRecentlyUsedCacheEvictor
import androidx.media3.datasource.cache.SimpleCache
import androidx.media3.database.StandaloneDatabaseProvider
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import java.io.File

private object BooruMediaCache {
    @Volatile private var cache: SimpleCache? = null
    @Synchronized fun get(context: Context): SimpleCache = cache ?: SimpleCache(
        File(context.applicationContext.cacheDir, "booru-video"),
        LeastRecentlyUsedCacheEvictor(192L * 1024 * 1024),
        StandaloneDatabaseProvider(context.applicationContext),
    ).also { cache = it }
}

internal fun createBooruPlayer(context: Context, preview: Boolean = false): ExoPlayer {
    val renderers = DefaultRenderersFactory(context).setEnableDecoderFallback(true)
    // Goldfish can reject valid WebM dimensions or never render a frame.
    // Real phones retain hardware priority and decoder fallback.
    if (Build.HARDWARE in setOf("ranchu", "goldfish")) {
        renderers.setMediaCodecSelector { mime, secure, tunneling ->
            MediaCodecSelector.DEFAULT.getDecoderInfos(mime, secure, tunneling)
                .sortedBy { if (it.softwareOnly) 0 else 1 }
        }
    }
    return ExoPlayer.Builder(context, renderers)
        .setMediaSourceFactory(DefaultMediaSourceFactory(CacheDataSource.Factory()
            .setCache(BooruMediaCache.get(context))
            .setUpstreamDataSourceFactory(DefaultDataSource.Factory(context))
            .setFlags(CacheDataSource.FLAG_IGNORE_CACHE_ON_ERROR)))
        .setLoadControl(DefaultLoadControl.Builder()
            .setBufferDurationsMs(if (preview) 500 else 1500, if (preview) 1500 else 5000, 250, 500)
            .setTargetBufferBytes((if (preview) 1 else 4) * 1024 * 1024).build())
        .build().also { player ->
            player.addListener(object : Player.Listener {
                override fun onPlaybackStateChanged(state: Int) {
                    if (state == Player.STATE_READY) player.repeatMode =
                        if (player.duration in 1L..9999L) Player.REPEAT_MODE_ONE else Player.REPEAT_MODE_OFF
                }
            })
        }
}

/** Only composed for visible cards; disposing releases decoder and buffers. */
@Composable
internal fun BooruVideoPreview(url: String, modifier: Modifier, playing: Boolean, onError: (String) -> Unit) {
    val reportError = rememberUpdatedState(onError)
    AndroidView(
        modifier = modifier,
        factory = { context ->
            BooruVideoTexture(context).also { texture ->
                texture.decoder = createBooruPlayer(context, preview = true).apply {
                    volume = 0f
                    addListener(object : Player.Listener {
                        override fun onPlayerError(error: PlaybackException) {
                            val http = generateSequence<Throwable>(error) { it.cause }
                                .filterIsInstance<HttpDataSource.InvalidResponseCodeException>().firstOrNull()
                            reportError.value(when {
                                http?.responseCode == 404 -> "图源文件已失效"
                                http != null -> "图源暂时无法访问"
                                error.errorCode in 2000..2999 -> "网络加载失败"
                                else -> "视频暂时无法播放"
                            })
                        }
                        override fun onVideoSizeChanged(videoSize: VideoSize) { texture.fitVideo(videoSize) }
                    })
                    setVideoTextureView(texture)
                    setMediaItem(MediaItem.fromUri(url))
                    prepare()
                    playWhenReady = playing
                }
            }
        },
        update = { it.decoder?.playWhenReady = playing },
        onRelease = { it.decoder?.release(); it.decoder = null },
    )
}

/** TextureView fills its bounds by default; apply a centered fit transform. */
internal class BooruVideoTexture(context: Context) : TextureView(context) {
    var decoder: ExoPlayer? = null
    private var video = VideoSize.UNKNOWN
    init { isOpaque = false }
    fun fitVideo(size: VideoSize = video) {
        video = size
        if (width <= 0 || height <= 0 || size.width <= 0 || size.height <= 0) return
        val aspect = size.width * size.pixelWidthHeightRatio / size.height
        val viewAspect = width.toFloat() / height
        val scaleX = if (aspect < viewAspect) aspect / viewAspect else 1f
        val scaleY = if (aspect > viewAspect) viewAspect / aspect else 1f
        setTransform(Matrix().apply { setScale(scaleX, scaleY, width / 2f, height / 2f) })
    }
    override fun onSizeChanged(w: Int, h: Int, oldw: Int, oldh: Int) {
        super.onSizeChanged(w, h, oldw, oldh)
        fitVideo()
    }
}
