package top.ponychat.webview.ui.music

import androidx.activity.compose.BackHandler
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.animate
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.gestures.awaitTouchSlopOrCancellation
import androidx.compose.foundation.gestures.verticalDrag
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.layout.wrapContentHeight
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.PlaylistAdd
import androidx.compose.material.icons.automirrored.filled.QueueMusic
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.Favorite
import androidx.compose.material.icons.filled.FavoriteBorder
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.StayCurrentLandscape
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawWithCache
import androidx.compose.ui.graphics.BlendMode
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.CompositingStrategy
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.lerp
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.input.pointer.positionChange
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.CustomAccessibilityAction
import androidx.compose.ui.semantics.customActions
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.TextLayoutResult
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull
import top.ponychat.webview.CustomToast
import top.ponychat.webview.ui.common.PonyConfirmDialog
import top.ponychat.webview.ui.common.PonyIconButton
import top.ponychat.webview.ui.common.SystemNavigationBarColorEffect
import top.ponychat.webview.ui.theme.LocalFontScale
import top.ponychat.webview.ui.theme.Primary
import kotlin.math.abs

private const val LYRIC_PREVIEW_MIN_LINES = 2
private const val LYRIC_PREVIEW_MAX_LINES = 4

private data class LyricPreview(val index: Int, val lines: List<String>)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun MusicPlayerScreen(
    model: MusicPlayerViewModel,
    landscape: Boolean,
    onLandscapeChange: (Boolean) -> Unit,
    close: () -> Unit,
    openSearch: () -> Unit,
    openAlbum: (String) -> Unit,
) {
    val state by model.playerState.collectAsStateWithLifecycle()
    val lyrics by model.lyrics.collectAsStateWithLifecycle()
    val account by MusicAccountStore.state.collectAsStateWithLifecycle()
    val syncError by model.syncError.collectAsStateWithLifecycle()
    val library = account.library
    val scheme = MaterialTheme.colorScheme
    SystemNavigationBarColorEffect(color = scheme.background, restoreOnDispose = true)
    val item = state.item
    val favorite = item != null && item.id in library?.favorites.orEmpty()
    fun toggleFavorite() {
        if (item != null) model.updateLibrary(MusicCommand("favorite", songId = item.id, enabled = !favorite))
    }
    var showLyrics by rememberSaveable { mutableStateOf(false) }
    var showQueue by rememberSaveable { mutableStateOf(false) }
    var addSong by rememberSaveable { mutableStateOf(false) }
    var playbackErrorDismissed by rememberSaveable(item?.id, state.error) { mutableStateOf(false) }
    fun togglePlayback() {
        playbackErrorDismissed = false
        model.toggle()
    }
    LaunchedEffect(Unit) {
        model.connect()
        model.refreshLibrary()
    }

    val messages = CustomToast.current
    val scope = rememberCoroutineScope()
    val swipeMotion = remember { TrackSwipeMotion() }
    val swipe = if (item == null) Modifier else Modifier.swipeToChangeTrack(item.id, model, swipeMotion, scope)
    val artworkActions = if (item == null) Modifier else Modifier.semantics {
        customActions = listOf(
            CustomAccessibilityAction("下一首") { model.skipTrack(item.id, forward = true) },
            CustomAccessibilityAction("上一首") { model.skipTrack(item.id, forward = false) },
        )
    }
    LaunchedEffect(syncError) {
        syncError?.takeIf { it.mutation }?.let { messages.showSnackbar(it.message) }
    }
    BackHandler(enabled = showLyrics && !showQueue && !addSong) { showLyrics = false }
    val tint = MusicArtworkTint(item?.artwork, scheme.secondaryContainer)
    val currentLyrics = lyrics.takeIf { it.trackId == item?.id }
    val lines = currentLyrics?.lines
    val lyricsNotice = (currentLyrics?.status ?: item?.lyricsStatus)?.notice
    val activeLyric = lines?.indexOfLast { it.startMs <= state.positionMs } ?: -1
    val background = if (showLyrics || landscape) {
        Brush.verticalGradient(
            0f to lerp(tint, scheme.background, 0.26f),
            0.64f to lerp(tint, scheme.background, 0.84f),
            1f to scheme.background,
        )
    } else Brush.verticalGradient(listOf(tint, scheme.background, scheme.background))
    BoxWithConstraints(
        Modifier.fillMaxSize().background(background)
            .statusBarsPadding().navigationBarsPadding(),
    ) {
        if (landscape) {
            MusicLandscapePlayer(
                state = state,
                lines = lines,
                active = activeLyric,
                notice = lyricsNotice,
                error = currentLyrics?.failed == true,
                retryLyrics = model::retryLyrics,
                seek = model::seek,
                togglePlayback = ::togglePlayback,
                close = close,
                returnToPortrait = { onLandscapeChange(false) },
                swipeMotion = swipeMotion,
                artworkGestures = swipe.then(artworkActions),
                modifier = Modifier.align(Alignment.TopCenter),
            )
            return@BoxWithConstraints
        }
        val page = Modifier.align(Alignment.TopCenter).widthIn(max = 570.dp)
        if (showLyrics && item != null) {
            MusicLyricsPage(
                state = state,
                item = item,
                lines = lines,
                active = activeLyric,
                notice = lyricsNotice,
                error = currentLyrics?.failed == true,
                retry = model::retryLyrics,
                favorite = favorite,
                favoritesEnabled = library != null,
                onBack = { showLyrics = false },
                togglePlayback = ::togglePlayback,
                seek = model::seek,
                toggleFavorite = ::toggleFavorite,
                openQueue = { showQueue = true },
                modifier = page.fillMaxSize(),
            )
            return@BoxWithConstraints
        }
        val needsScroll = maxHeight < 530.dp || LocalFontScale.current > 1.35f
        val content = if (needsScroll) {
            page.fillMaxWidth().verticalScroll(rememberScrollState())
        } else {
            page.fillMaxSize().then(swipe)
        }
        Column(
            content.padding(start = 24.dp, end = 24.dp, bottom = 8.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                PonyIconButton(onClick = close, icon = Icons.Default.KeyboardArrowDown, contentDescription = "收起播放器")
                Text(
                    if (state.playing) "正在播放" else "已暂停",
                    Modifier.weight(1f),
                    style = MaterialTheme.typography.titleMedium,
                )
                if (item != null) {
                    PonyIconButton(
                        onClick = { onLandscapeChange(true) },
                        icon = Icons.Default.StayCurrentLandscape,
                        contentDescription = "横屏播放",
                    )
                    PonyIconButton(
                        onClick = { addSong = true },
                        enabled = library != null,
                        icon = Icons.AutoMirrored.Filled.PlaylistAdd,
                        contentDescription = "加到歌单",
                        tint = scheme.onSurfaceVariant,
                    )
                }
                PonyIconButton(onClick = openSearch, icon = Icons.Default.Search, contentDescription = "搜索音乐")
            }
            if (item == null) {
                MusicMessage("还没有正在播放的歌曲", "返回曲库", close)
                return@Column
            }
            val previewLines = remember(lines) { lines.orEmpty().filter { it.originalText.isNotBlank() } }
            val previewIndex = previewLines.indexOfLast { it.startMs <= state.positionMs }.coerceAtLeast(0)
            val lyricPreview = remember(previewLines, previewIndex) {
                val end = minOf(previewIndex + LYRIC_PREVIEW_MAX_LINES, previewLines.size)
                LyricPreview(previewIndex, previewLines.subList(previewIndex, end).map(MusicLyric::originalText))
            }
            val artworkStage = if (needsScroll) {
                Modifier.height(260.dp).then(swipe)
            } else {
                Modifier.weight(1f)
            }
            NowPlayingArtwork(
                trackId = item.id,
                artwork = item.artwork,
                preview = lyricPreview,
                lyricsNotice = if (currentLyrics?.failed == true) "歌词暂时加载失败" else lyricsNotice,
                motion = swipeMotion,
                modifier = artworkStage.then(artworkActions),
            ) { showLyrics = true }

            val titleStyle = MaterialTheme.typography.headlineSmall
            val subtitleStyle = MaterialTheme.typography.bodyLarge
            val metadataHeight = with(LocalDensity.current) {
                titleStyle.lineHeight.toDp() * 2 + subtitleStyle.lineHeight.toDp()
            } + 7.dp
            Row(
                Modifier.fillMaxWidth().padding(top = 15.dp).heightIn(min = metadataHeight),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(Modifier.weight(1f)) {
                    Text(item.title, style = titleStyle, fontWeight = FontWeight.Bold, maxLines = 2, overflow = TextOverflow.Ellipsis)
                    if (item.album.isNotBlank()) {
                        val albumId = item.albumId
                        Row(
                            Modifier.clickable(enabled = albumId != null, onClickLabel = "打开专辑") {
                                albumId?.let(openAlbum)
                            }.padding(vertical = 3.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Text(
                                item.album, Modifier.weight(1f, fill = false), color = scheme.onSurfaceVariant, style = subtitleStyle,
                                maxLines = 1, overflow = TextOverflow.Ellipsis,
                            )
                            if (albumId != null) {
                                Icon(
                                    Icons.AutoMirrored.Filled.KeyboardArrowRight, null,
                                    Modifier.size(18.dp), tint = scheme.onSurfaceVariant,
                                )
                            }
                        }
                    }
                }
                PonyIconButton(
                    enabled = library != null,
                    onClick = ::toggleFavorite,
                    icon = if (favorite) Icons.Default.Favorite else Icons.Default.FavoriteBorder,
                    contentDescription = if (favorite) "取消收藏" else "收藏",
                    size = 48.dp,
                    tint = if (favorite) Primary else scheme.onSurfaceVariant,
                )
            }
            MusicProgress(state, model::seek)
            Row(
                Modifier.fillMaxWidth().padding(top = 9.dp),
                horizontalArrangement = Arrangement.SpaceEvenly,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                val mode = state.mode
                PonyIconButton(
                    onClick = {
                        model.cyclePlaybackMode()?.let { next ->
                            scope.launch {
                                val previous = messages.currentSnackbarData
                                if (MusicPlaybackMode.entries.any { it.label == previous?.visuals?.message }) previous?.dismiss()
                                messages.showSnackbar(next.label)
                            }
                        }
                    },
                    icon = mode.icon,
                    contentDescription = "播放模式，${mode.label}",
                    size = 44.dp,
                    iconSize = 27.dp,
                    tint = if (mode == MusicPlaybackMode.SEQUENTIAL) scheme.onSurfaceVariant else Primary,
                )
                MusicPlayButton(state, ::togglePlayback, size = 66.dp)
                PonyIconButton(
                    onClick = { showQueue = true },
                    icon = Icons.AutoMirrored.Filled.QueueMusic,
                    contentDescription = "播放队列",
                    size = 44.dp,
                    iconSize = 27.dp,
                    tint = scheme.onSurfaceVariant,
                )
            }
        }
    }

    if (showQueue) {
        MusicQueueSheet(
            state = state,
            favorite = favorite,
            accountReady = library != null,
            onDismiss = { showQueue = false },
            onAddToPlaylist = { showQueue = false; addSong = true },
            onToggleFavorite = ::toggleFavorite,
            onOpenAlbum = { albumId -> showQueue = false; openAlbum(albumId) },
            onCycleMode = { model.cyclePlaybackMode() },
            onPlaySong = { songId -> model.playQueueItem(songId); showQueue = false },
            onMoveSong = model::moveQueueItem,
        )
    }
    if (addSong && item != null) AddSongDialog(item.id, library, model) { addSong = false }
    if (item != null && state.error && !playbackErrorDismissed && !showQueue && !addSong) {
        PonyConfirmDialog(
            title = "播放失败",
            message = "暂时无法播放这首歌",
            confirmText = "重试",
            dismissText = "关闭",
            onConfirm = ::togglePlayback,
            onDismiss = { playbackErrorDismissed = true },
        )
    }
}

internal class TrackSwipeMotion {
    var offset by mutableFloatStateOf(0f)
    val moving by derivedStateOf { offset != 0f }
    var stageHeight = 0f
    var settling = false

    suspend fun settle(model: MusicPlayerViewModel, trackId: String, forward: Boolean?) {
        if (forward != null && stageHeight > 0 && model.canSkipTrack(trackId, forward)) {
            val edge = if (forward) -stageHeight else stageHeight
            animateTo(edge, 150)
            if (model.skipTrack(trackId, forward)) {
                val changed = withTimeoutOrNull(350) {
                    model.playerState.first { it.item != null && it.item.id != trackId }
                }
                if (changed != null) offset = -edge
            }
        }
        animateTo(0f, 210)
    }

    private suspend fun animateTo(target: Float, durationMillis: Int) {
        animate(offset, target, animationSpec = tween(durationMillis, easing = FastOutSlowInEasing)) { value, _ ->
            offset = value
        }
    }
}

private fun Modifier.swipeToChangeTrack(
    trackId: String,
    model: MusicPlayerViewModel,
    motion: TrackSwipeMotion,
    scope: CoroutineScope,
) = pointerInput(trackId, model, motion) {
    val threshold = 52.dp.toPx()
    awaitEachGesture {
        val down = awaitFirstDown(requireUnconsumed = true)
        if (motion.settling) return@awaitEachGesture
        var distance = 0f
        var horizontal = false
        try {
            val start = awaitTouchSlopOrCancellation(down.id) { change, overSlop ->
                horizontal = horizontal || abs(overSlop.x) >= abs(overSlop.y)
                if (!horizontal) {
                    distance = overSlop.y
                    motion.offset = distance.coerceIn(-motion.stageHeight, motion.stageHeight)
                    change.consume()
                }
            } ?: return@awaitEachGesture
            val completed = verticalDrag(start.id) { change ->
                distance += change.positionChange().y
                motion.offset = distance.coerceIn(-motion.stageHeight, motion.stageHeight)
                change.consume()
            }
            val forward = when {
                completed && distance <= -threshold -> true
                completed && distance >= threshold -> false
                else -> null
            }
            motion.settling = true
            scope.launch {
                try {
                    motion.settle(model, trackId, forward)
                } finally {
                    motion.offset = 0f
                    motion.settling = false
                }
            }
        } finally {
            if (!motion.settling) motion.offset = 0f
        }
    }
}

internal fun Modifier.trackSwipeEdgeFade(motion: TrackSwipeMotion): Modifier = graphicsLayer {
    clip = true
    compositingStrategy = if (motion.moving) CompositingStrategy.Offscreen else CompositingStrategy.Auto
}.drawWithCache {
    val edge = (44.dp.toPx() / size.height.coerceAtLeast(1f)).coerceAtMost(0.25f)
    val mask = Brush.verticalGradient(
        0f to Color.Transparent,
        edge to Color.Black,
        (1f - edge) to Color.Black,
        1f to Color.Transparent,
    )
    onDrawWithContent {
        drawContent()
        if (motion.moving) drawRect(mask, blendMode = BlendMode.DstIn)
    }
}

@Composable
private fun NowPlayingArtwork(
    trackId: String,
    artwork: String?,
    preview: LyricPreview,
    lyricsNotice: String?,
    motion: TrackSwipeMotion,
    modifier: Modifier,
    openLyrics: () -> Unit,
) {
    BoxWithConstraints(
        modifier.fillMaxWidth().onSizeChanged { motion.stageHeight = it.height.toFloat() }.trackSwipeEdgeFade(motion),
        contentAlignment = Alignment.Center,
    ) {
        val currentStyle = MaterialTheme.typography.displaySmall
        val lyricPadding = PaddingValues(top = 16.dp, bottom = 8.dp)
        val lineHeight = with(LocalDensity.current) { currentStyle.lineHeight.toDp() }
        val paddingHeight = lyricPadding.calculateTopPadding() + lyricPadding.calculateBottomPadding()
        val minimumLyricsSpace = lineHeight * LYRIC_PREVIEW_MIN_LINES + paddingHeight
        val showPreview = maxHeight >= minimumLyricsSpace + 76.dp
        // Anchor the cover independently of the lyrics and use extra space below it for longer previews.
        val availableBesideCover = (maxHeight - minOf(maxWidth, 180.dp) - 8.dp).coerceAtLeast(minimumLyricsSpace)
        val reservedLyricsSpace = when {
            showPreview -> minOf(lineHeight * 3 + paddingHeight, availableBesideCover)
            maxHeight >= 120.dp -> 48.dp
            else -> 0.dp
        }
        val coverSize = minOf(maxWidth, 414.dp, (maxHeight - reservedLyricsSpace - 8.dp).coerceAtLeast(0.dp))
        val coverTop = (maxHeight - coverSize - reservedLyricsSpace).coerceAtLeast(0.dp) / 2
        val previewTop = coverTop + coverSize + if (showPreview) minOf(24.dp, coverTop) else 0.dp
        val maxLines = ((maxHeight - previewTop - paddingHeight) / lineHeight).toInt()
            .coerceIn(LYRIC_PREVIEW_MIN_LINES, LYRIC_PREVIEW_MAX_LINES)
        val lyricsSpace = if (showPreview) lineHeight * maxLines + paddingHeight else reservedLyricsSpace
        Box(
            Modifier.fillMaxSize().graphicsLayer { translationY = motion.offset },
        ) {
            if (coverSize > 0.dp) {
                MusicArtwork(artwork, Modifier.align(Alignment.TopCenter).offset(y = coverTop).size(coverSize), corner = 25)
            }
            if (lyricsSpace > 0.dp) {
                Box(Modifier.fillMaxWidth().height(lyricsSpace).offset(y = previewTop)) {
                    if (showPreview && preview.lines.isNotEmpty()) {
                        key(trackId) {
                            NowPlayingLyricPreview(
                                preview = preview,
                                currentStyle = currentStyle,
                                maxLines = maxLines,
                                modifier = Modifier.fillMaxSize()
                                    .clickable(onClickLabel = "查看完整歌词", onClick = openLyrics)
                                    .padding(top = lyricPadding.calculateTopPadding()),
                            )
                        }
                    } else if (lyricsNotice != null) {
                        Text(
                            lyricsNotice,
                            modifier = Modifier.fillMaxWidth()
                                .clickable(onClickLabel = "打开歌词页面", onClick = openLyrics)
                                .padding(top = if (showPreview) lyricPadding.calculateTopPadding() else 4.dp),
                            style = MaterialTheme.typography.bodyLarge,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    } else {
                        TextButton(onClick = openLyrics, modifier = Modifier.align(Alignment.TopStart)) { Text("查看歌词") }
                    }
                }
            }
        }
    }
}

@Composable
private fun NowPlayingLyricPreview(
    preview: LyricPreview,
    currentStyle: TextStyle,
    maxLines: Int,
    modifier: Modifier,
) {
    val colors = MaterialTheme.colorScheme
    val upcomingStyle = MaterialTheme.typography.headlineLarge.toSpanStyle().copy(
        fontWeight = FontWeight.Normal,
        color = colors.onSurfaceVariant,
    )
    var displayed by remember { mutableStateOf(preview) }
    var layout by remember { mutableStateOf<TextLayoutResult?>(null) }
    val offset = remember { Animatable(0f) }
    val edgeReveal = remember { Animatable(0f) }
    val fading by remember { derivedStateOf { offset.value != 0f || edgeReveal.value > 0f } }
    LaunchedEffect(preview) {
        edgeReveal.snapTo(0f)
        val previousLayout = layout
        var enterFromBelow = 0f
        if (preview.index == displayed.index + 1 && previousLayout != null) {
            val nextCueStart = displayed.lines.first().length + 1
            val lastLine = previousLayout.lineCount - 1
            // Use the measured row so a wrapped cue scrolls by all of its visible lines.
            if (nextCueStart < previousLayout.getLineEnd(lastLine, visibleEnd = true)) {
                val nextRow = previousLayout.getLineForOffset(nextCueStart)
                offset.animateTo(-previousLayout.getLineTop(nextRow), tween(230, easing = FastOutSlowInEasing))
                edgeReveal.snapTo(1f)
            } else {
                enterFromBelow = previousLayout.size.height.toFloat()
                offset.animateTo(-enterFromBelow, tween(140, easing = FastOutSlowInEasing))
            }
        }
        displayed = preview
        offset.snapTo(enterFromBelow)
        if (enterFromBelow > 0f) offset.animateTo(0f, tween(160, easing = FastOutSlowInEasing))
        if (edgeReveal.value > 0f) edgeReveal.animateTo(0f, tween(120, easing = FastOutSlowInEasing))
    }
    val text = remember(displayed, upcomingStyle) {
        buildAnnotatedString {
            append(displayed.lines.first())
            withStyle(upcomingStyle) {
                displayed.lines.drop(1).forEach { line ->
                    append('\n')
                    append(line)
                }
            }
        }
    }
    Box(
        modifier.graphicsLayer {
            clip = true
            compositingStrategy = if (fading) CompositingStrategy.Offscreen else CompositingStrategy.Auto
        }.drawWithCache {
            val edgeHeight = minOf(22.dp.toPx(), size.height / 3)
            val edge = edgeHeight / size.height.coerceAtLeast(1f)
            val mask = Brush.verticalGradient(
                0f to Color.Black,
                edge to Color.Transparent,
                (1f - edge) to Color.Transparent,
                1f to Color.Black,
            )
            onDrawWithContent {
                drawContent()
                val motionFade = (abs(offset.value) / edgeHeight.coerceAtLeast(1f)).coerceAtMost(1f)
                val strength = maxOf(motionFade, edgeReveal.value)
                if (strength > 0f) drawRect(mask, alpha = strength, blendMode = BlendMode.DstOut)
            }
        },
    ) {
        Text(
            text = text,
            // Measure the full line budget before clipping to the fixed viewport.
            modifier = Modifier.fillMaxWidth().wrapContentHeight(Alignment.Top, unbounded = true)
                .graphicsLayer { translationY = offset.value },
            style = currentStyle,
            color = colors.onSurface,
            maxLines = maxLines,
            overflow = TextOverflow.Ellipsis,
            onTextLayout = { layout = it },
        )
    }
}
