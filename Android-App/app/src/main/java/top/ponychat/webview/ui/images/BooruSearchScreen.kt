@file:androidx.annotation.OptIn(androidx.media3.common.util.UnstableApi::class)

package top.ponychat.webview.ui.images

import android.content.Intent
import android.net.Uri
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.common.PlaybackException
import androidx.media3.common.VideoSize
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.OpenInNew
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import coil.compose.AsyncImage
import coil.compose.AsyncImagePainter
import coil.request.ImageRequest
import androidx.compose.foundation.lazy.grid.rememberLazyGridState
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import top.ponychat.webview.data.api.NetworkClient
import top.ponychat.webview.data.model.BooruImage
import top.ponychat.webview.data.model.BooruSearchRequest
import top.ponychat.webview.data.model.BooruSearchResponse
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.ui.chat.ChatScreenImagePreviewOverlay
import top.ponychat.webview.ui.common.*
import top.ponychat.webview.ui.theme.Primary
import top.ponychat.webview.ui.theme.ponyNeutralContainerColors
import top.ponychat.webview.util.formatErrorForDisplay

private data class Choice(val value: String, val label: String)

private val ratingChoices = listOf(
    Choice("safe", "安全"), Choice("suggestive", "暗示"), Choice("questionable", "擦边"),
    Choice("explicit", "成人"), Choice("semi-grimdark", "轻暗黑"),
    Choice("grimdark", "暗黑"), Choice("grotesque", "血腥"),
)
private val sortChoices = listOf(
    Choice("time", "时间"), Choice("score", "评分"), Choice("random", "随机"),
)

@Composable
fun BooruSearchScreen(
    prefs: AppPreferences,
    onNavigateBack: () -> Unit,
    searchOverride: (suspend (BooruSearchRequest) -> BooruSearchResponse)? = null,
) {
    val context = LocalContext.current
    val keyboard = LocalSoftwareKeyboardController.current
    val scope = rememberCoroutineScope()
    val images = remember { mutableStateListOf<BooruImage>() }
    var query by rememberSaveable { mutableStateOf("") }
    var mode by rememberSaveable { mutableStateOf("natural") }
    var rating by rememberSaveable { mutableStateOf("safe") }
    var sort by rememberSaveable { mutableStateOf("score") }
    var page by rememberSaveable { mutableIntStateOf(1) }
    var isLoading by remember { mutableStateOf(false) }
    var canLoadMore by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }
    var playingVideo by remember { mutableStateOf<BooruImage?>(null) }
    var previewImageUrl by remember { mutableStateOf<String?>(null) }
    var previewImages by remember { mutableStateOf<List<String>>(emptyList()) }
    var previewIndex by remember { mutableIntStateOf(0) }
    var showFilters by rememberSaveable { mutableStateOf(true) }
    var appliedRequest by remember { mutableStateOf<BooruSearchRequest?>(null) }

    suspend fun request(targetPage: Int, append: Boolean) {
        val trimmed = query.trim()
        if ((!append && trimmed.isBlank()) || isLoading) return
        isLoading = true
        error = null
        try {
            val body = if (append) {
                appliedRequest?.copy(page = targetPage) ?: return
            } else BooruSearchRequest(prefs.username, trimmed, mode, rating, sort, targetPage)
            val result = if (searchOverride != null) searchOverride(body) else withContext(Dispatchers.IO) {
                val response = NetworkClient.createApiService(prefs).searchBooru(body)
                if (!response.isSuccessful) {
                    val raw = response.errorBody()?.string().orEmpty()
                    val detail = runCatching { JSONObject(raw).optString("detail") }.getOrNull()
                    throw IllegalStateException(detail?.takeIf(String::isNotBlank) ?: "搜索失败（HTTP ${response.code()}）")
                }
                response.body() ?: throw IllegalStateException("搜索服务返回了空数据")
            }
            if (!append) images.clear()
            val known = images.asSequence().map { it.id }.toHashSet()
            val newImages = result.images.filter { known.add(it.id) }
            images.addAll(newImages)
            canLoadMore = result.hasMore && targetPage < 1000
            rating = result.rating
            // Reuse the resolved tags and submitted filters across pages, including
            // when the user edits filter fields and returns without submitting.
            appliedRequest = body.copy(query = result.tags.joinToString(", "), mode = "tags", rating = result.rating)
            page = targetPage
        } catch (cause: Exception) {
            error = formatErrorForDisplay(cause.message ?: "搜索失败")
            canLoadMore = false
        } finally {
            isLoading = false
        }
    }

    fun submit() {
        if (query.isBlank()) return
        keyboard?.hide()
        showFilters = false
        canLoadMore = true
        scope.launch { request(1, append = false) }
    }

    val navigationColor = MaterialTheme.colorScheme.background
    SystemNavigationBarColorEffect(
        navigationColor,
        navigationColor.red + navigationColor.green + navigationColor.blue > 1.5f,
    )
    if (showFilters) {
        BooruFilterScreen(
            query, { query = it }, mode, { mode = it }, rating, { rating = it }, sort, { sort = it },
            isLoading,
            onBack = { if (images.isEmpty()) onNavigateBack() else showFilters = false },
            onSubmit = ::submit,
        )
    } else {
        BooruResultsScreen(
            images, isLoading, error, onNavigateBack,
            page = page,
            canLoadMore = canLoadMore,
            playbackEnabled = playingVideo == null,
            onOpenFilters = { showFilters = true },
            onLoadMore = { scope.launch { request(page + 1, append = true) } },
            onImageClick = { image ->
                if (booruOpenTarget(image.video) == BooruOpenTarget.VideoPlayer) {
                    playingVideo = image
                } else {
                    previewImages = images.filterNot { it.video }.map { it.imageUrl }
                    previewIndex = previewImages.indexOf(image.imageUrl).coerceAtLeast(0)
                    previewImageUrl = image.imageUrl
                }
            },
        )
    }
    playingVideo?.let { video ->
        WebmPlayerDialog(
            video,
            onDismiss = { playingVideo = null },
            onOpenPost = { runCatching { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(video.url))) } },
        )
    }
    ChatScreenImagePreviewOverlay(
        previewImageUrl = previewImageUrl,
        previewImages = previewImages,
        previewIndex = previewIndex,
        onDismiss = {
            previewImageUrl = null
            previewImages = emptyList()
        },
        coroutineScope = scope,
        context = context,
    )
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun BooruFilterScreen(
    query: String, onQueryChange: (String) -> Unit,
    mode: String, onModeChange: (String) -> Unit,
    rating: String, onRatingChange: (String) -> Unit,
    sort: String, onSortChange: (String) -> Unit,
    isLoading: Boolean, onBack: () -> Unit, onSubmit: () -> Unit,
) {
    val focusManager = LocalFocusManager.current
    val keyboard = LocalSoftwareKeyboardController.current
    Scaffold(
        modifier = Modifier.pointerInput(focusManager, keyboard) {
            detectTapGestures(onTap = {
                focusManager.clearFocus(force = true)
                keyboard?.hide()
            })
        },
        topBar = { PonyTopBar(title = "搜索与筛选", onNavigateBack = onBack) },
        containerColor = MaterialTheme.colorScheme.background,
    ) { padding ->
        Column(
            Modifier.fillMaxSize().padding(padding).verticalScroll(rememberScrollState())
                .padding(horizontal = 16.dp, vertical = 18.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            FilterSection("搜索方式") {
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    PonyChoiceChip("自然语言", mode == "natural") { onModeChange("natural") }
                    PonyChoiceChip("标签", mode == "tags") { onModeChange("tags") }
                }
            }
            FilterSection(if (mode == "natural") "描述想找的图片" else "输入英文标签") {
                PonyTopSearchBar(
                    value = query,
                    onValueChange = onQueryChange,
                    placeholder = if (mode == "natural") "例如：紫悦在图书馆看书" else "多个标签用逗号分隔",
                    modifier = Modifier.fillMaxWidth(),
                )
            }
            if (mode == "tags") {
                FilterSection("图片等级") {
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(9.dp), verticalArrangement = Arrangement.spacedBy(9.dp)) {
                        ratingChoices.forEach { choice ->
                            PonyChoiceChip(choice.label, rating == choice.value) { onRatingChange(choice.value) }
                        }
                    }
                }
            }
            FilterSection("排序方式") {
                FlowRow(horizontalArrangement = Arrangement.spacedBy(9.dp), verticalArrangement = Arrangement.spacedBy(9.dp)) {
                    sortChoices.forEach { choice ->
                        PonyChoiceChip(choice.label, sort == choice.value) { onSortChange(choice.value) }
                    }
                }
            }
            val neutral = ponyNeutralContainerColors(strong = true)
            Surface(color = neutral.container, shape = RoundedCornerShape(14.dp), border = BorderStroke(1.dp, neutral.border)) {
                Text(
                    "结果将混合展示 Derpibooru 与 Twibooru 的图片、GIF 和 WebM 视频。",
                    Modifier.padding(14.dp),
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            PonyButton(
                text = "开始找图",
                onClick = onSubmit,
                enabled = query.isNotBlank(),
                isLoading = isLoading,
                icon = { Icon(Icons.Filled.Search, contentDescription = null, modifier = Modifier.size(20.dp)) },
            )
        }
    }
}

@Composable
private fun FilterSection(title: String, content: @Composable () -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(title, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
        content()
    }
}

@Composable
private fun PonyChoiceChip(label: String, selected: Boolean, onClick: (() -> Unit)? = null) {
    val neutral = ponyNeutralContainerColors(strong = true)
    Surface(
        modifier = Modifier.then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier),
        shape = RoundedCornerShape(18.dp),
        color = if (selected) Primary else neutral.container,
        border = BorderStroke(1.dp, if (selected) Primary else neutral.border),
    ) {
        Text(
            label,
            Modifier.padding(horizontal = 15.dp, vertical = 8.dp),
            color = if (selected) Color.White else MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelLarge,
        )
    }
}

@Composable
private fun BooruResultsScreen(
    images: List<BooruImage>, isLoading: Boolean, error: String?,
    onBack: () -> Unit, onOpenFilters: () -> Unit, onLoadMore: () -> Unit,
    page: Int,
    canLoadMore: Boolean,
    onImageClick: (BooruImage) -> Unit,
    playbackEnabled: Boolean,
) {
    val gridState = rememberLazyGridState()
    val visibleKeys by remember { derivedStateOf {
        gridState.layoutInfo.visibleItemsInfo.map { it.key }.toSet()
    } }
    val loadingState = rememberUpdatedState(isLoading)
    val moreState = rememberUpdatedState(canLoadMore)
    val shouldLoadMore by remember { derivedStateOf {
        val layout = gridState.layoutInfo
        val lastVisible = layout.visibleItemsInfo.lastOrNull()?.index ?: -1
        shouldLoadNextBooruPage(lastVisible, layout.totalItemsCount, moreState.value, loadingState.value)
    } }
    LaunchedEffect(shouldLoadMore, page, error, playbackEnabled) {
        if (shouldLoadMore && error == null && images.isNotEmpty() && playbackEnabled) onLoadMore()
    }
    val owner = LocalLifecycleOwner.current
    var foreground by remember { mutableStateOf(owner.lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED)) }
    DisposableEffect(owner) {
        val observer = LifecycleEventObserver { _, _ ->
            foreground = owner.lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED)
        }
        owner.lifecycle.addObserver(observer)
        onDispose { owner.lifecycle.removeObserver(observer) }
    }
    Scaffold(
        topBar = {
            PonyTopBar(title = "呆站找图", onNavigateBack = onBack) {
                PonyIconButton(
                    onClick = onOpenFilters,
                    icon = Icons.Filled.Tune,
                    contentDescription = "搜索条件",
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        },
        containerColor = MaterialTheme.colorScheme.background,
    ) { padding ->
        LazyVerticalGrid(
            state = gridState,
            columns = GridCells.Fixed(2),
            modifier = Modifier.fillMaxSize().padding(padding),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            error?.let {
                item(span = { GridItemSpan(maxLineSpan) }) {
                    Surface(
                        Modifier.fillMaxWidth().padding(8.dp),
                        color = MaterialTheme.colorScheme.errorContainer,
                        shape = RoundedCornerShape(12.dp),
                    ) {
                        Column(Modifier.padding(12.dp)) {
                            Text(it, color = MaterialTheme.colorScheme.onErrorContainer)
                            if (images.isNotEmpty()) TextButton(onClick = onLoadMore, enabled = !isLoading) {
                                Text("重试加载")
                            }
                        }
                    }
                }
            }
            if (images.isEmpty()) {
                item(span = { GridItemSpan(maxLineSpan) }) {
                    Box(Modifier.fillMaxWidth().height(260.dp), contentAlignment = Alignment.Center) {
                        if (isLoading) CircularProgressIndicator(color = Primary)
                        else Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(12.dp)) {
                            Text("没有找到结果", color = MaterialTheme.colorScheme.onSurfaceVariant)
                            Box(Modifier.width(190.dp)) {
                                PonyButton("修改搜索条件", onOpenFilters, style = PonyButtonStyle.Secondary, height = 44.dp)
                            }
                        }
                    }
                }
            }
            items(images, key = { it.id }) { image ->
                BooruImageCard(image, image.id in visibleKeys, foreground && playbackEnabled) { onImageClick(image) }
            }
            if (images.isNotEmpty() && isLoading) {
                item(span = { GridItemSpan(maxLineSpan) }) {
                    Box(Modifier.fillMaxWidth().padding(16.dp), contentAlignment = Alignment.Center) {
                        CircularProgressIndicator(color = Primary)
                    }
                }
            }
        }
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun BooruImageCard(image: BooruImage, active: Boolean, playing: Boolean, onClick: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var sharing by remember { mutableStateOf(false) }
    var ready by remember(image.id) { mutableStateOf(false) }
    LaunchedEffect(active, image.id) {
        ready = false
        if (active) {
            delay(200)
            ready = true
        }
    }
    val loadMedia = active && ready
    var useOriginal by remember(image.imageUrl, image.previewUrl) { mutableStateOf(false) }
    val mediaUrl = if (useOriginal) image.imageUrl else image.previewUrl?.takeIf { it.isNotBlank() } ?: image.imageUrl
    // Bound decoding to the card size while retaining animated image decoders.
    val thumbnail = remember(mediaUrl) {
        ImageRequest.Builder(context).data(mediaUrl).size(512, 512).build()
    }
    Card(
        modifier = Modifier.padding(horizontal = 4.dp).fillMaxWidth().combinedClickable(
            onClick = onClick,
            onLongClickLabel = "分享",
            onLongClick = {
                if (!sharing) scope.launch {
                    sharing = true
                    try { shareBooruMedia(context, image) } finally { sharing = false }
                }
            },
        ),
        shape = RoundedCornerShape(12.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
    ) {
        Box(Modifier.fillMaxWidth().aspectRatio(1f).background(if (image.video) Color.Black else MaterialTheme.colorScheme.surfaceVariant)) {
            var loadFailed by remember(image.imageUrl) { mutableStateOf(false) }
            var failureText by remember(image.imageUrl) { mutableStateOf("媒体加载失败") }
            var retry by remember(image.imageUrl) { mutableIntStateOf(0) }
            key(mediaUrl, retry) {
            if (image.video && loadMedia) {
                BooruVideoPreview(mediaUrl, Modifier.fillMaxSize(), playing) {
                    if (mediaUrl != image.imageUrl) useOriginal = true
                    else { failureText = it; loadFailed = true }
                }
            } else if (image.video) {
                Column(
                    Modifier.align(Alignment.Center),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    Icon(
                        Icons.Filled.PlayCircle,
                        contentDescription = "播放视频",
                        tint = Primary,
                        modifier = Modifier.size(52.dp),
                    )
                    Text("WebM 视频", style = MaterialTheme.typography.labelMedium)
                }
            } else if (loadMedia) AsyncImage(
                model = thumbnail,
                contentDescription = image.tags.take(3).joinToString(", "),
                modifier = Modifier.fillMaxSize(),
                contentScale = ContentScale.Crop,
                onState = {
                    if (it is AsyncImagePainter.State.Error && mediaUrl != image.imageUrl) useOriginal = true
                    else loadFailed = it is AsyncImagePainter.State.Error
                },
            )
            }
            if (loadFailed) {
                Column(Modifier.align(Alignment.Center), horizontalAlignment = Alignment.CenterHorizontally) {
                    Icon(Icons.Filled.BrokenImage, contentDescription = null, tint = MaterialTheme.colorScheme.onSurfaceVariant)
                    Text(failureText, style = MaterialTheme.typography.labelSmall)
                    TextButton(onClick = { loadFailed = false; retry++ }) { Text("重试", color = Primary) }
                }
            }
            MediaBadge(image.source, Modifier.align(Alignment.TopStart))
            MediaBadge("★ ${image.score}", Modifier.align(Alignment.BottomEnd))
            if (sharing) CircularProgressIndicator(Modifier.align(Alignment.Center), color = Primary)
        }
        Column(Modifier.padding(8.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(image.rating, style = MaterialTheme.typography.labelSmall, color = Primary)
                Spacer(Modifier.width(6.dp))
                if (image.video) Text("视频", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.tertiary)
                else if (image.animated) Text("动图", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.tertiary)
            }
            BooruActionButtons(image, Modifier.align(Alignment.End))
        }
    }
}

internal fun shouldLoadNextBooruPage(
    lastVisibleIndex: Int,
    totalItemsCount: Int,
    canLoadMore: Boolean,
    isLoading: Boolean,
    prefetchDistance: Int = 4,
): Boolean = canLoadMore && !isLoading && totalItemsCount > 0 &&
    lastVisibleIndex >= totalItemsCount - prefetchDistance - 1

internal enum class BooruOpenTarget { ImagePreview, VideoPlayer }

internal fun booruOpenTarget(video: Boolean): BooruOpenTarget =
    if (video) BooruOpenTarget.VideoPlayer else BooruOpenTarget.ImagePreview

@Composable
private fun BooruActionButtons(image: BooruImage, modifier: Modifier = Modifier) {
    val context = LocalContext.current
    Row(modifier, horizontalArrangement = Arrangement.spacedBy(4.dp)) {
        TextButton(onClick = { downloadBooruMedia(context, image) }, contentPadding = PaddingValues(6.dp),
            colors = ButtonDefaults.textButtonColors(contentColor = Primary)) {
            Icon(Icons.Filled.Download, null, Modifier.size(16.dp))
            Spacer(Modifier.width(3.dp))
            Text("下载", style = MaterialTheme.typography.labelMedium)
        }
        TextButton(onClick = { runCatching { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(image.url))) } },
            contentPadding = PaddingValues(6.dp), colors = ButtonDefaults.textButtonColors(contentColor = Primary)) {
            Icon(Icons.AutoMirrored.Filled.OpenInNew, null, Modifier.size(16.dp))
            Spacer(Modifier.width(3.dp))
            Text("来源", style = MaterialTheme.typography.labelMedium)
        }
    }
}

@Composable
private fun MediaBadge(text: String, modifier: Modifier) {
    Surface(modifier.padding(6.dp), color = Color.Black.copy(alpha = 0.68f), shape = RoundedCornerShape(6.dp)) {
        Text(text, Modifier.padding(horizontal = 6.dp, vertical = 3.dp), color = Color.White, style = MaterialTheme.typography.labelSmall)
    }
}

@Composable
private fun WebmPlayerDialog(image: BooruImage, onDismiss: () -> Unit, onOpenPost: () -> Unit) {
    var player by remember(image.imageUrl) { mutableStateOf<ExoPlayer?>(null) }
    var failed by remember { mutableStateOf(false) }
    var isPlaying by remember { mutableStateOf(true) }
    var duration by remember { mutableIntStateOf(1) }
    var position by remember { mutableIntStateOf(0) }
    var resumePlayback by remember(image.imageUrl) { mutableStateOf(false) }
    val lifecycleOwner = LocalLifecycleOwner.current
    DisposableEffect(lifecycleOwner, player) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_PAUSE) {
                resumePlayback = player?.playWhenReady == true
                player?.pause()
            } else if (event == Lifecycle.Event.ON_RESUME) {
                player?.let { current ->
                    if (resumePlayback) current.play()
                    else current.seekTo(current.currentPosition)
                }
            }
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose { lifecycleOwner.lifecycle.removeObserver(observer) }
    }
    LaunchedEffect(player, isPlaying) {
        while (player != null) {
            position = player?.currentPosition?.toInt() ?: position
            duration = player?.duration?.toInt()?.coerceAtLeast(1) ?: duration
            delay(400)
        }
    }
    Dialog(onDismissRequest = onDismiss, properties = DialogProperties(usePlatformDefaultWidth = false, decorFitsSystemWindows = false)) {
        Surface(color = Color.Black, modifier = Modifier.fillMaxSize()) {
            Box(Modifier.fillMaxSize()) {
                AndroidView(
                    modifier = Modifier.fillMaxSize(),
                    factory = { context ->
                        BooruVideoTexture(context).also { texture ->
                            val decoder = createBooruPlayer(context)
                            player = decoder
                            texture.decoder = decoder
                            decoder.addListener(object : Player.Listener {
                                override fun onVideoSizeChanged(videoSize: VideoSize) { texture.fitVideo(videoSize) }
                                override fun onPlayerError(error: PlaybackException) { failed = true }
                                override fun onIsPlayingChanged(playing: Boolean) { isPlaying = playing }
                            })
                            decoder.setVideoTextureView(texture)
                            decoder.setMediaItem(MediaItem.fromUri(image.imageUrl))
                            decoder.prepare()
                            decoder.play()
                        }
                    },
                )
                Row(
                    Modifier.fillMaxWidth().background(Color.Black.copy(alpha = 0.62f)).padding(top = 28.dp, end = 8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    PonyIconButton(onClick = onDismiss, icon = Icons.Filled.Close, contentDescription = "关闭视频", tint = Color.White)
                    Text(image.source, color = Color.White, fontWeight = FontWeight.SemiBold)
                }
                if (failed) Text("视频加载失败", color = Color.White, modifier = Modifier.align(Alignment.Center))
                Column(
                    Modifier.align(Alignment.BottomCenter).fillMaxWidth().background(Color.Black.copy(alpha = 0.72f))
                        .navigationBarsPadding().padding(horizontal = 12.dp, vertical = 8.dp),
                ) {
                    Slider(
                        value = position.coerceIn(0, duration).toFloat(),
                        onValueChange = { position = it.toInt(); player?.seekTo(position.toLong()) },
                        valueRange = 0f..duration.toFloat(),
                        colors = SliderDefaults.colors(thumbColor = Primary, activeTrackColor = Primary),
                    )
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        PonyIconButton(
                            onClick = {
                                if (player?.isPlaying == true) player?.pause() else player?.play()
                                isPlaying = player?.isPlaying == true
                            },
                            icon = if (isPlaying) Icons.Filled.Pause else Icons.Filled.PlayArrow,
                            contentDescription = if (isPlaying) "暂停" else "播放",
                            tint = Color.White,
                        )
                        Text("${formatTime(position)} / ${formatTime(duration)}", color = Color.White, style = MaterialTheme.typography.labelMedium)
                        Spacer(Modifier.weight(1f))
                        BooruActionButtons(image)
                    }
                }
            }
        }
    }
    DisposableEffect(image.imageUrl) { onDispose {
        player?.release()
        player = null
    } }
}

private fun formatTime(milliseconds: Int): String {
    val seconds = milliseconds.coerceAtLeast(0) / 1000
    return "%d:%02d".format(seconds / 60, seconds % 60)
}
