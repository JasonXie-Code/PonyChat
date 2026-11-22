package top.ponychat.webview.ui.music

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.displayCutoutPadding
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.StayCurrentPortrait
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import top.ponychat.webview.ui.common.PonyIconButton
import top.ponychat.webview.ui.theme.LocalFontScale

@Composable
internal fun MusicLandscapePlayer(
    state: MusicPlayerState,
    lines: List<MusicLyric>?,
    active: Int,
    notice: String?,
    error: Boolean,
    retryLyrics: () -> Unit,
    seek: (Long) -> Unit,
    close: () -> Unit,
    returnToPortrait: () -> Unit,
    swipeMotion: TrackSwipeMotion,
    artworkGestures: Modifier,
    modifier: Modifier = Modifier,
) {
    val colors = MaterialTheme.colorScheme
    val orientationButtonSize = 44.dp
    val lyricsEndPadding = orientationButtonSize * LocalFontScale.current + 8.dp
    val item = state.item
    Box(
        modifier.widthIn(max = 1080.dp).fillMaxSize()
            .displayCutoutPadding().padding(start = 22.dp, top = 6.dp, end = 22.dp, bottom = 8.dp),
    ) {
        Row(
            Modifier.fillMaxSize()
                .onSizeChanged { swipeMotion.stageHeight = it.height.toFloat() },
            horizontalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            Column(Modifier.weight(0.31f).fillMaxHeight()) {
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    PonyIconButton(
                        onClick = close,
                        icon = Icons.Default.KeyboardArrowDown,
                        contentDescription = "收起播放器",
                        size = 44.dp,
                    )
                    Text(
                        if (state.playing) "正在播放" else "已暂停",
                        style = MaterialTheme.typography.titleMedium,
                    )
                }
                if (item != null) {
                    val titleStyle = MaterialTheme.typography.headlineLarge
                    val albumStyle = MaterialTheme.typography.bodyMedium
                    val metadataHeight = with(LocalDensity.current) {
                        titleStyle.lineHeight.toDp() * 2 + albumStyle.lineHeight.toDp()
                    } + 3.dp
                    val coverPadding = 8.dp
                    BoxWithConstraints(Modifier.weight(1f).fillMaxWidth()) {
                        val coverSize = minOf(maxWidth, (maxHeight - metadataHeight - coverPadding * 2).coerceAtLeast(0.dp), 244.dp)
                        val artworkInset = if (coverSize > 0.dp) (maxWidth - coverSize) / 2 else 0.dp
                        Column(Modifier.fillMaxSize().padding(start = artworkInset)) {
                            Box(
                                Modifier.weight(1f).fillMaxWidth().padding(vertical = coverPadding),
                                contentAlignment = Alignment.CenterStart,
                            ) {
                                if (coverSize > 0.dp) {
                                    Box(Modifier.size(coverSize).then(artworkGestures).trackSwipeEdgeFade(swipeMotion)) {
                                        MusicArtwork(
                                            item.artwork,
                                            Modifier.fillMaxSize().graphicsLayer { translationY = swipeMotion.offset },
                                            corner = 18,
                                        )
                                    }
                                }
                            }
                            Column(Modifier.fillMaxWidth().heightIn(min = metadataHeight)) {
                                Text(
                                    item.title,
                                    style = titleStyle,
                                    fontWeight = FontWeight.Bold,
                                    maxLines = 2,
                                    overflow = TextOverflow.Ellipsis,
                                )
                                if (item.album.isNotBlank()) {
                                    Text(
                                        item.album,
                                        modifier = Modifier.padding(top = 3.dp),
                                        style = albumStyle,
                                        color = colors.onSurfaceVariant,
                                        maxLines = 1,
                                        overflow = TextOverflow.Ellipsis,
                                    )
                                }
                            }
                        }
                    }
                }
            }
            Box(
                Modifier.weight(0.69f).fillMaxHeight().padding(end = lyricsEndPadding)
                    .trackSwipeEdgeFade(swipeMotion),
                contentAlignment = Alignment.Center,
            ) {
                if (item == null) {
                    MusicMessage("还没有正在播放的歌曲", "返回曲库", close)
                } else key(item.id) {
                    var browsing by remember { mutableStateOf(false) }
                    Column(Modifier.fillMaxSize()) {
                        MusicLyricsViewport(
                            lines = lines,
                            active = active,
                            notice = notice,
                            error = error,
                            retry = retryLyrics,
                            canSeek = state.canSeek,
                            seek = seek,
                            browsing = browsing,
                            onBrowsingChange = { browsing = it },
                            modifier = Modifier.weight(1f),
                            swipeMotion = swipeMotion,
                            compactSpacing = true,
                        )
                        if (browsing) {
                            TextButton(
                                onClick = { browsing = false },
                                modifier = Modifier.graphicsLayer { translationY = swipeMotion.offset },
                            ) { Text("回到当前歌词") }
                        }
                    }
                }
            }
        }
        PonyIconButton(
            onClick = returnToPortrait,
            icon = Icons.Default.StayCurrentPortrait,
            contentDescription = "切回竖屏",
            modifier = Modifier.align(Alignment.TopEnd).background(colors.surfaceVariant, CircleShape),
            size = orientationButtonSize,
        )
    }
}
