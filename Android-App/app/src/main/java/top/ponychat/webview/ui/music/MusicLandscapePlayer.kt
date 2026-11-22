package top.ponychat.webview.ui.music

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
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

@Composable
internal fun MusicLandscapePlayer(
    state: MusicPlayerState,
    lines: List<MusicLyric>?,
    active: Int,
    notice: String?,
    error: Boolean,
    retryLyrics: () -> Unit,
    seek: (Long) -> Unit,
    togglePlayback: () -> Unit,
    close: () -> Unit,
    returnToPortrait: () -> Unit,
    swipeMotion: TrackSwipeMotion,
    artworkGestures: Modifier,
    modifier: Modifier = Modifier,
) {
    Column(modifier.widthIn(max = 1080.dp).fillMaxSize().padding(horizontal = 24.dp)) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            PonyIconButton(onClick = close, icon = Icons.Default.KeyboardArrowDown, contentDescription = "收起播放器")
            Text(
                if (state.playing) "正在播放" else "已暂停",
                Modifier.weight(1f),
                style = MaterialTheme.typography.titleMedium,
            )
            PonyIconButton(
                onClick = returnToPortrait,
                icon = Icons.Default.StayCurrentPortrait,
                contentDescription = "切回竖屏",
            )
        }
        val item = state.item
        if (item == null) {
            MusicMessage("还没有正在播放的歌曲", "返回曲库", close)
            return@Column
        }
        Row(
            Modifier.weight(1f).fillMaxWidth()
                .onSizeChanged { swipeMotion.stageHeight = it.height.toFloat() },
            horizontalArrangement = Arrangement.spacedBy(28.dp),
        ) {
            BoxWithConstraints(Modifier.weight(0.42f).fillMaxHeight(), contentAlignment = Alignment.Center) {
                val titleStyle = MaterialTheme.typography.titleLarge
                val albumStyle = MaterialTheme.typography.bodyMedium
                val textHeight = with(LocalDensity.current) {
                    titleStyle.lineHeight.toDp() + if (item.album.isNotBlank()) albumStyle.lineHeight.toDp() else 0.dp
                }
                val metadataHeight = maxOf(textHeight, 44.dp)
                val spacing = minOf(18.dp, maxHeight * 0.06f)
                val coverSize = minOf(maxWidth, (maxHeight - metadataHeight - spacing * 3).coerceAtLeast(0.dp), 320.dp)
                val groupWidth = maxOf(coverSize, minOf(maxWidth, 168.dp))
                Column(
                    Modifier.width(groupWidth).fillMaxHeight(),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.SpaceEvenly,
                ) {
                    Box(
                        Modifier.size(coverSize)
                            .then(artworkGestures).trackSwipeEdgeFade(swipeMotion),
                    ) {
                        MusicArtwork(
                            item.artwork,
                            Modifier.fillMaxSize().graphicsLayer { translationY = swipeMotion.offset },
                            corner = 22,
                        )
                    }
                    Row(
                        Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(12.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Column(Modifier.weight(1f)) {
                            Text(
                                item.title,
                                style = titleStyle,
                                fontWeight = FontWeight.Bold,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                            )
                            if (item.album.isNotBlank()) {
                                Text(
                                    item.album,
                                    style = albumStyle,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    maxLines = 1,
                                    overflow = TextOverflow.Ellipsis,
                                )
                            }
                        }
                        MusicPlayButton(state, togglePlayback, size = 44.dp)
                    }
                }
            }
            key(item.id) {
                var browsing by remember { mutableStateOf(false) }
                Box(
                    Modifier.weight(0.58f).fillMaxHeight().padding(top = 6.dp, bottom = 12.dp)
                        .trackSwipeEdgeFade(swipeMotion),
                    contentAlignment = Alignment.Center,
                ) {
                    Column(Modifier.widthIn(max = 400.dp).fillMaxSize()) {
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
    }
}
