package top.ponychat.webview.ui.music

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.QueueMusic
import androidx.compose.material.icons.filled.Favorite
import androidx.compose.material.icons.filled.FavoriteBorder
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.BlendMode
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.CompositingStrategy
import androidx.compose.ui.graphics.TransformOrigin
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.nestedscroll.NestedScrollConnection
import androidx.compose.ui.input.nestedscroll.NestedScrollSource
import androidx.compose.ui.input.nestedscroll.nestedScroll
import androidx.compose.ui.layout.findRootCoordinates
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.positionInRoot
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.delay
import top.ponychat.webview.ui.common.PonyIconButton
import top.ponychat.webview.ui.common.PonyTopBarBackButton
import top.ponychat.webview.ui.theme.LocalFontScale
import kotlin.math.abs
import kotlin.math.roundToInt

private const val LYRIC_FOCUS_FRACTION = 1f / 3f
private const val ACTIVE_LYRIC_SCALE = 1.5f
private const val LYRIC_TRANSITION_MS = 240

@Composable
internal fun MusicLyricsPage(
    state: MusicPlayerState,
    item: MusicItem,
    lines: List<MusicLyric>?,
    active: Int,
    notice: String?,
    error: Boolean,
    retry: () -> Unit,
    favorite: Boolean,
    favoritesEnabled: Boolean,
    onBack: () -> Unit,
    togglePlayback: () -> Unit,
    seek: (Long) -> Unit,
    toggleFavorite: () -> Unit,
    openQueue: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val colors = MaterialTheme.colorScheme
    key(item.id) {
        var browsing by remember { mutableStateOf(false) }

        Column(
            modifier.fillMaxSize().padding(horizontal = 22.dp),
        ) {
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                PonyTopBarBackButton(onClick = onBack, contentDescription = "返回封面")
                Text("歌词", Modifier.weight(1f), style = MaterialTheme.typography.titleMedium)
                PonyIconButton(
                    onClick = openQueue,
                    icon = Icons.AutoMirrored.Filled.QueueMusic,
                    contentDescription = "播放队列",
                )
            }
            LyricsTrackHeader(state, item, togglePlayback)
            MusicLyricsViewport(
                lines = lines,
                active = active,
                notice = notice,
                error = error,
                retry = retry,
                canSeek = state.canSeek,
                seek = seek,
                browsing = browsing,
                onBrowsingChange = { browsing = it },
                modifier = Modifier.weight(1f),
            )
            Row(
                Modifier.fillMaxWidth().padding(bottom = 6.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Row(Modifier.weight(1f), verticalAlignment = Alignment.CenterVertically) {
                    if (browsing && !lines.isNullOrEmpty()) {
                        TextButton(onClick = { browsing = false }) { Text("回到当前歌词") }
                    }
                }
                PonyIconButton(
                    onClick = toggleFavorite,
                    icon = if (favorite) Icons.Default.Favorite else Icons.Default.FavoriteBorder,
                    contentDescription = if (favorite) "取消收藏" else "收藏",
                    enabled = favoritesEnabled,
                    tint = if (favorite) colors.primary else colors.onSurfaceVariant,
                )
            }
        }
    }
}

@Composable
internal fun MusicLyricsViewport(
    lines: List<MusicLyric>?,
    active: Int,
    notice: String?,
    error: Boolean,
    retry: () -> Unit,
    canSeek: Boolean,
    seek: (Long) -> Unit,
    browsing: Boolean,
    onBrowsingChange: (Boolean) -> Unit,
    modifier: Modifier = Modifier,
    swipeMotion: TrackSwipeMotion? = null,
) {
    val list = rememberLazyListState()
    var positioned by remember { mutableStateOf(false) }
    var requestedLine by remember { mutableStateOf<Int?>(null) }
    var settledLine by remember { mutableStateOf<Int?>(null) }
    var focusOffset by remember { mutableIntStateOf(0) }
    val selectedLine by remember {
        derivedStateOf {
            val layout = list.layoutInfo
            val focus = layout.viewportStartOffset + focusOffset
            layout.visibleItemsInfo.minByOrNull { lyric -> abs(lyric.offset + lyric.size / 2f - focus) }?.index
        }
    }
    val changeBrowsing by rememberUpdatedState(onBrowsingChange)
    val scroll = remember {
        object : NestedScrollConnection {
            override fun onPreScroll(available: Offset, source: NestedScrollSource): Offset {
                if (source == NestedScrollSource.UserInput && available.y != 0f) changeBrowsing(true)
                return Offset.Zero
            }
        }
    }
    LaunchedEffect(browsing, list.isScrollInProgress) {
        // Anchor the selected line before adding its time button so text reflow can't move the selection.
        settledLine = if (browsing && !list.isScrollInProgress) selectedLine else null
    }
    fun jumpToLine(index: Int) {
        val lyric = lines?.getOrNull(index) ?: return
        if (!canSeek) return
        requestedLine = index
        changeBrowsing(false)
        seek(lyric.startMs)
    }

    val targetLine = requestedLine ?: active.coerceAtLeast(0)
    LaunchedEffect(browsing, targetLine, lines?.size, focusOffset) {
        if (browsing || lines.isNullOrEmpty() || focusOffset == 0) return@LaunchedEffect
        if (positioned) list.animateScrollToItem(targetLine)
        else {
            list.scrollToItem(targetLine)
            positioned = true
        }
    }
    LaunchedEffect(active, requestedLine) {
        if (requestedLine != null && requestedLine == active) requestedLine = null
    }
    LaunchedEffect(requestedLine) {
        if (requestedLine != null) {
            delay(1600)
            requestedLine = null
        }
    }

    BoxWithConstraints(
        modifier.fillMaxWidth().onGloballyPositioned { coordinates ->
            val height = coordinates.size.height
            val screenFocus = coordinates.findRootCoordinates().size.height * LYRIC_FOCUS_FRACTION
            focusOffset = (screenFocus - coordinates.positionInRoot().y)
                .coerceIn(height * 0.15f, height * 0.5f)
                .roundToInt()
        },
    ) {
        // Keep the scroll anchor in a fixed viewport while the lyrics are moving with the cover.
        val viewportHeight = maxHeight
        val slide = if (swipeMotion == null) Modifier else Modifier.graphicsLayer { translationY = swipeMotion.offset }
        Box(Modifier.fillMaxSize().then(slide)) {
            when {
                error -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    MusicMessage("歌词加载失败", "重试", retry)
                }
                notice != null || lines?.isEmpty() == true -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    MusicMessage(notice ?: "这首歌的歌词正在补充")
                }
                lines == null -> CircularProgressIndicator(Modifier.align(Alignment.Center))
                else -> {
                    val focus = with(LocalDensity.current) { focusOffset.toDp() }
                    val topSpace = (focus - 26.dp).coerceAtLeast(0.dp)
                    val bottomSpace = (viewportHeight - focus - 26.dp).coerceAtLeast(0.dp)
                    LazyColumn(
                        state = list,
                        modifier = Modifier.fillMaxSize().nestedScroll(scroll).lyricsViewportFade(),
                        contentPadding = PaddingValues(top = topSpace, bottom = bottomSpace),
                        verticalArrangement = Arrangement.spacedBy(9.dp),
                    ) {
                        itemsIndexed(lines, key = { index, _ -> index }) { index, lyric ->
                            LyricLine(
                                lyric = lyric,
                                active = index == (requestedLine ?: active),
                                guide = browsing && (settledLine ?: selectedLine) == index,
                                showTime = browsing && settledLine == index,
                                canSeek = canSeek,
                                seek = { jumpToLine(index) },
                                modifier = Modifier.animateItem(
                                    fadeInSpec = null,
                                    placementSpec = if (browsing) null else tween(LYRIC_TRANSITION_MS),
                                    fadeOutSpec = null,
                                ),
                            )
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun LyricsTrackHeader(state: MusicPlayerState, item: MusicItem, togglePlayback: () -> Unit) {
    val colors = MaterialTheme.colorScheme
    Row(
        Modifier.fillMaxWidth().padding(top = 8.dp, bottom = 14.dp),
        horizontalArrangement = Arrangement.spacedBy(14.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        MusicArtwork(item.artwork, Modifier.size(64.dp), corner = 12)
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(3.dp)) {
            Text(
                item.title,
                style = MaterialTheme.typography.titleLarge,
                fontWeight = FontWeight.SemiBold,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
            )
            val subtitle = item.artist.ifBlank { item.album }
            if (subtitle.isNotBlank()) Text(
                subtitle,
                style = MaterialTheme.typography.bodyMedium,
                color = colors.onSurfaceVariant,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
        MusicPlayButton(state, togglePlayback, size = 48.dp)
    }
}

@Composable
private fun LyricLine(
    lyric: MusicLyric,
    active: Boolean,
    guide: Boolean,
    showTime: Boolean,
    canSeek: Boolean,
    seek: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val colors = MaterialTheme.colorScheme
    val shape = RoundedCornerShape(12.dp)
    val targetScale = if (active) ACTIVE_LYRIC_SCALE else 1f
    val lyricScale = animateFloatAsState(
        targetValue = targetScale,
        animationSpec = tween(LYRIC_TRANSITION_MS),
        label = "lyric size",
    )
    val lyricStyle = MaterialTheme.typography.titleLarge
    val textStart = if (LocalLayoutDirection.current == LayoutDirection.Rtl) 1f else 0f
    Row(
        modifier.fillMaxWidth().clip(shape)
            .background(if (guide) colors.primary.copy(alpha = 0.11f) else Color.Transparent)
            .clickable(enabled = canSeek, onClickLabel = "跳到 ${formatMusicTime(lyric.startMs)}", onClick = seek)
            .padding(start = 3.dp, top = 10.dp, bottom = 10.dp, end = 7.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            Modifier.width(2.dp).height(24.dp).clip(RoundedCornerShape(2.dp))
                .background(if (active || guide) colors.primary else Color.Transparent),
        )
        val main = lyric.originalText
        val translation = lyric.zh?.takeIf { it.isNotBlank() && it != main }
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(5.dp)) {
            Text(
                main,
                // Measure the final typography once so the text cannot rewrap on animation frames.
                modifier = Modifier.fillMaxWidth().clipToBounds().graphicsLayer {
                    val scale = lyricScale.value / targetScale
                    scaleX = scale
                    scaleY = scale
                    // A shrinking line must stay clear of the translation below it.
                    alpha = if (active) 1f else 1f - (scale - 1f) * 0.7f
                    transformOrigin = TransformOrigin(textStart, 0f)
                },
                style = lyricStyle.copy(fontSize = lyricStyle.fontSize * targetScale, lineHeight = 30.sp * targetScale),
                fontWeight = if (active) FontWeight.Bold else FontWeight.Normal,
                color = if (active || guide) colors.onSurface else colors.onSurfaceVariant,
            )
            if (translation != null) Text(
                translation,
                style = MaterialTheme.typography.bodyLarge.copy(lineHeight = 23.sp),
                color = colors.onSurfaceVariant,
            )
        }
        if (showTime && canSeek) {
            TextButton(
                onClick = seek,
                modifier = Modifier.width(62.dp * LocalFontScale.current),
                contentPadding = PaddingValues(horizontal = 4.dp),
            ) {
                Text(formatMusicTime(lyric.startMs), style = MaterialTheme.typography.labelMedium, maxLines = 1)
                Icon(Icons.Default.PlayArrow, "跳到此句", Modifier.size(16.dp))
            }
        }
    }
}

private fun Modifier.lyricsViewportFade(): Modifier = graphicsLayer {
    compositingStrategy = CompositingStrategy.Offscreen
}.drawWithContent {
    drawContent()
    drawRect(
        brush = Brush.verticalGradient(
            0f to Color.Transparent,
            0.08f to Color.Black,
            0.91f to Color.Black,
            1f to Color.Transparent,
        ),
        blendMode = BlendMode.DstIn,
    )
}
