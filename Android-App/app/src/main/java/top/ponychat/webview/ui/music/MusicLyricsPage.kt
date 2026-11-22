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
import androidx.compose.foundation.layout.Spacer
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
import androidx.compose.ui.draw.drawWithCache
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.BlendMode
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.CompositingStrategy
import androidx.compose.ui.graphics.drawscope.scale
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.lerp
import androidx.compose.ui.input.nestedscroll.NestedScrollConnection
import androidx.compose.ui.input.nestedscroll.NestedScrollSource
import androidx.compose.ui.input.nestedscroll.nestedScroll
import androidx.compose.ui.layout.findRootCoordinates
import androidx.compose.ui.layout.layout
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.positionInRoot
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.text
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.drawText
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Constraints
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.unit.constrainHeight
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
    onViewportReady: () -> Unit,
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
                onViewportReady = onViewportReady,
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
    compactSpacing: Boolean = false,
    onViewportReady: () -> Unit = {},
) {
    var focusOffset by remember { mutableIntStateOf(0) }
    val ready = focusOffset > 0
    val notifyReady by rememberUpdatedState(onViewportReady)
    LaunchedEffect(ready) {
        if (ready) notifyReady()
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
        // Measure the anchor on the fixed viewport, outside the cover's swipe animation.
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
                ready -> {
                    val focus = with(LocalDensity.current) { focusOffset.toDp() }
                    val inset = if (compactSpacing) 6.dp else 26.dp
                    TimedLyricsList(
                        lines = lines,
                        active = active,
                        canSeek = canSeek,
                        seek = seek,
                        browsing = browsing,
                        onBrowsingChange = onBrowsingChange,
                        focusOffset = focusOffset,
                        padding = PaddingValues(
                            top = (focus - inset).coerceAtLeast(0.dp),
                            bottom = (viewportHeight - focus - inset).coerceAtLeast(0.dp),
                        ),
                        compactSpacing = compactSpacing,
                    )
                }
            }
        }
    }
}

@Composable
private fun TimedLyricsList(
    lines: List<MusicLyric>,
    active: Int,
    canSeek: Boolean,
    seek: (Long) -> Unit,
    browsing: Boolean,
    onBrowsingChange: (Boolean) -> Unit,
    focusOffset: Int,
    padding: PaddingValues,
    compactSpacing: Boolean,
) {
    val list = rememberLazyListState(initialFirstVisibleItemIndex = active.coerceIn(lines.indices))
    var requestedLine by remember { mutableStateOf<Int?>(null) }
    var settledLine by remember { mutableStateOf<Int?>(null) }
    val currentFocusOffset by rememberUpdatedState(focusOffset)
    val selectedLine by remember {
        derivedStateOf {
            val layout = list.layoutInfo
            val focus = layout.viewportStartOffset + currentFocusOffset
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
        if (!canSeek) return
        requestedLine = index
        changeBrowsing(false)
        seek(lines[index].startMs)
    }

    val targetLine = (requestedLine ?: active).coerceIn(lines.indices)
    LaunchedEffect(browsing, targetLine) {
        if (browsing) return@LaunchedEffect
        list.animateScrollToItem(targetLine)
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

    LazyColumn(
        state = list,
        modifier = Modifier.fillMaxSize().nestedScroll(scroll).lyricsViewportFade(),
        contentPadding = padding,
        verticalArrangement = Arrangement.spacedBy(if (compactSpacing) 5.dp else 9.dp),
    ) {
        itemsIndexed(lines, key = { index, _ -> index }) { index, lyric ->
            LyricLine(
                lyric = lyric,
                active = index == (requestedLine ?: active),
                guide = browsing && (settledLine ?: selectedLine) == index,
                showTime = browsing && settledLine == index,
                canSeek = canSeek,
                seek = { jumpToLine(index) },
                compactSpacing = compactSpacing,
            )
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
    compactSpacing: Boolean,
) {
    val colors = MaterialTheme.colorScheme
    val shape = RoundedCornerShape(12.dp)
    val lyricStyle = MaterialTheme.typography.titleLarge
    val lyricLineHeight = if (compactSpacing) lyricStyle.lineHeight else 30.sp
    val translationStyle = if (compactSpacing) MaterialTheme.typography.bodyMedium
        else MaterialTheme.typography.bodyLarge.copy(lineHeight = 23.sp)
    val verticalPadding = if (compactSpacing) 6.dp else 10.dp
    Row(
        Modifier.fillMaxWidth().clip(shape)
            .background(if (guide) colors.primary.copy(alpha = 0.11f) else Color.Transparent)
            .clickable(enabled = canSeek, onClickLabel = "跳到 ${formatMusicTime(lyric.startMs)}", onClick = seek)
            .padding(start = 3.dp, top = verticalPadding, bottom = verticalPadding, end = 7.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            Modifier.width(2.dp).height(24.dp).clip(RoundedCornerShape(2.dp))
                .background(if (active || guide) colors.primary else Color.Transparent),
        )
        val main = lyric.originalText
        val translation = lyric.zh?.takeIf { it.isNotBlank() && it != main }
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(if (compactSpacing) 3.dp else 5.dp)) {
            AnimatedLyricText(
                value = main,
                style = lyricStyle.copy(lineHeight = lyricLineHeight),
                active = active,
                normalColor = if (guide) colors.onSurface else colors.onSurfaceVariant,
                activeColor = colors.onSurface,
            )
            if (translation != null) Text(
                translation,
                style = translationStyle,
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

@Composable
private fun AnimatedLyricText(
    value: String,
    style: TextStyle,
    active: Boolean,
    normalColor: Color,
    activeColor: Color,
) {
    val emphasis = animateFloatAsState(
        targetValue = if (active) 1f else 0f,
        animationSpec = tween(LYRIC_TRANSITION_MS),
        label = "lyric emphasis",
    )
    val measurer = rememberTextMeasurer(cacheSize = 2)
    val lyric = remember(value) { AnnotatedString(value) }
    val plainStyle = style.copy(fontWeight = FontWeight.Normal)
    val boldStyle = style.copy(
        fontWeight = FontWeight.Bold,
        fontSize = style.fontSize * ACTIVE_LYRIC_SCALE,
        lineHeight = style.lineHeight * ACTIVE_LYRIC_SCALE,
    )
    fun measure(width: Int, emphasized: Boolean) = measurer.measure(
        lyric,
        style = if (emphasized) boldStyle else plainStyle,
        constraints = Constraints.fixedWidth(width),
    )
    Spacer(Modifier.fillMaxWidth()
        .semantics { text = lyric }
        .layout { child, constraints ->
            val width = constraints.maxWidth
            val plainHeight = measure(width, emphasized = false).size.height
            val boldHeight = measure(width, emphasized = true).size.height
            val height = constraints.constrainHeight(
                (plainHeight + (boldHeight - plainHeight) * emphasis.value).roundToInt(),
            )
            val content = child.measure(Constraints.fixed(width, height))
            layout(width, height) { content.placeRelative(0, 0) }
        }
        .drawWithCache {
            val width = size.width.roundToInt()
            val plain = measure(width, emphasized = false)
            val bold = measure(width, emphasized = true)
            val rtl = layoutDirection == LayoutDirection.Rtl
            val pivot = Offset(if (rtl) size.width else 0f, 0f)
            val plainWidth = (0 until plain.lineCount).maxOfOrNull { index ->
                if (rtl) size.width - plain.getLineLeft(index) else plain.getLineRight(index)
            } ?: 0f
            onDrawBehind {
                val fraction = emphasis.value
                val fontScale = 1f + (ACTIVE_LYRIC_SCALE - 1f) * fraction
                val plainScale = minOf(fontScale, size.width / plainWidth.coerceAtLeast(1f),
                    size.height / plain.size.height.coerceAtLeast(1))
                val boldScale = minOf(fontScale / ACTIVE_LYRIC_SCALE,
                    size.height / bold.size.height.coerceAtLeast(1))
                // Keep one layout visible and switch when the wrapped bold version can be
                // drawn at the same size. Both versions fit the space assigned to this row.
                val useBold = fraction == 1f || (fraction > 0f && boldScale * ACTIVE_LYRIC_SCALE >= plainScale)
                val scale = if (useBold) boldScale else plainScale
                scale(scale, scale, pivot) {
                    drawText(if (useBold) bold else plain, color = lerp(normalColor, activeColor, fraction))
                }
            }
        },
    )
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
