package top.ponychat.webview.ui.music

import android.graphics.Color as AndroidColor
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.selection.selectableGroup
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.FormatListNumbered
import androidx.compose.material.icons.filled.MusicNote
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Repeat
import androidx.compose.material.icons.filled.RepeatOne
import androidx.compose.material.icons.filled.Shuffle
import androidx.compose.material.icons.filled.SkipNext
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilledIconButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.IconButtonDefaults
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Slider
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.lerp
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.setProgress
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.unit.dp
import androidx.core.graphics.drawable.toBitmap
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import coil.compose.AsyncImage
import coil.imageLoader
import coil.request.ImageRequest
import coil.request.SuccessResult
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import top.ponychat.webview.ui.common.PonyIconButton
import top.ponychat.webview.ui.common.PonyAlertDialog
import top.ponychat.webview.ui.common.PonyConfirmDialog
import top.ponychat.webview.ui.common.PonyTextField
import top.ponychat.webview.ui.theme.Primary
import java.util.Locale
import java.util.UUID
import kotlin.math.abs
import kotlin.math.sin

internal data class MusicArtworkPalette(val tint: Color, val glowColors: List<Color>)

@Composable
internal fun rememberMusicArtworkPalette(url: String?, base: Color): MusicArtworkPalette {
    val context = LocalContext.current
    val hues by produceState<List<Int>>(emptyList(), url) {
        value = emptyList()
        if (url == null) return@produceState
        val result = context.imageLoader.execute(
            ImageRequest.Builder(context).data(url).size(32).allowHardware(false).build()
        ) as? SuccessResult ?: return@produceState
        value = withContext(Dispatchers.Default) {
            val bitmap = result.drawable.toBitmap(width = 32, height = 32)
            val buckets = FloatArray(12)
            val hsv = FloatArray(3)
            for (y in 0 until bitmap.height) {
                for (x in 0 until bitmap.width) {
                    val pixel = bitmap.getPixel(x, y)
                    if (AndroidColor.alpha(pixel) < 180) continue
                    AndroidColor.colorToHSV(pixel, hsv)
                    if (hsv[1] < 0.22f || hsv[2] < 0.28f) continue
                    val bucket = (hsv[0] / 30).toInt().coerceIn(buckets.indices)
                    buckets[bucket] += hsv[1] * hsv[2]
                }
            }
            buildList {
                for (bucket in buckets.indices.sortedByDescending { buckets[it] }) {
                    if (size == 3 || buckets[bucket] < 5f) break
                    // Neighboring hue buckets would produce nearly identical lights.
                    if (none { abs(it - bucket) !in 2..10 }) add(bucket)
                }
            }
        }
    }
    val scheme = MaterialTheme.colorScheme
    val tint = hues.firstOrNull()?.let { Color.hsv(it * 30f + 15f, 0.61f, 0.76f) } ?: scheme.primary
    val animated by animateColorAsState(lerp(base, tint, 0.22f), label = "musicArtworkTint")
    val fallback = listOf(scheme.primary, scheme.tertiary, scheme.secondary)
    val glows = List(fallback.size) { index ->
        hues.getOrNull(index)?.let { Color.hsv(it * 30f + 15f, 0.55f, 0.94f) } ?: fallback[index]
    }
    return MusicArtworkPalette(animated, glows)
}

@Composable
internal fun MusicTabs(labels: List<String>, selected: String, onSelect: (String) -> Unit) {
    Row(Modifier.selectableGroup(), horizontalArrangement = Arrangement.spacedBy(18.dp)) {
        labels.forEach { label ->
            val active = label == selected
            Column(
                Modifier.height(44.dp).selectable(active, role = Role.Tab) { onSelect(label) }
                    .padding(horizontal = 3.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.Center,
            ) {
                Text(
                    label,
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = if (active) FontWeight.Bold else FontWeight.Medium,
                    color = if (active) MaterialTheme.colorScheme.onSurface else MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Box(
                    Modifier.padding(top = 5.dp).width(19.dp).height(3.dp).clip(RoundedCornerShape(3.dp))
                        .background(if (active) MaterialTheme.colorScheme.primary else Color.Transparent),
                )
            }
        }
    }
}

@Composable
internal fun MusicArtwork(url: String?, modifier: Modifier = Modifier, corner: Int = 12) {
    Box(
        modifier.clip(RoundedCornerShape(corner.dp)).background(
            Brush.linearGradient(listOf(MaterialTheme.colorScheme.primaryContainer, MaterialTheme.colorScheme.tertiaryContainer))
        ),
        contentAlignment = Alignment.Center,
    ) {
        Icon(Icons.Default.MusicNote, null, tint = MaterialTheme.colorScheme.onPrimaryContainer)
        if (url != null) {
            AsyncImage(model = url, contentDescription = null, modifier = Modifier.matchParentSize(), contentScale = ContentScale.Crop)
        }
    }
}

@Composable
internal fun MusicMiniPlayer(model: MusicPlayerViewModel, openPlayer: () -> Unit) {
    val state by model.playerState.collectAsStateWithLifecycle()
    val item = state.item ?: return
    val duration = state.durationMs
    val canSeek = state.canSeek && duration > 0
    var seekPreview by remember(item.id, canSeek) { mutableStateOf<Float?>(null) }
    var subtitleAtDragStart by remember(item.id) { mutableStateOf(item.album) }
    val progress = seekPreview ?: if (duration > 0) {
        (state.positionMs.toFloat() / duration).coerceIn(0f, 1f)
    } else 0f
    val subtitle = when {
        state.error -> "播放失败"
        state.buffering -> "正在缓冲"
        else -> item.album
    }
    val latestSubtitle by rememberUpdatedState(subtitle)
    val latestDuration by rememberUpdatedState(duration)
    val rtl = LocalLayoutDirection.current == LayoutDirection.Rtl
    val seekGesture = if (!canSeek) Modifier else Modifier.pointerInput(item.id, rtl) {
        val trackInset = 12.dp.toPx()
        fun positionFor(x: Float): Float {
            val trackWidth = (size.width - 2 * trackInset).coerceAtLeast(1f)
            val fraction = ((x - trackInset) / trackWidth).coerceIn(0f, 1f)
            return if (rtl) 1f - fraction else fraction
        }
        detectHorizontalDragGestures(
            onDragStart = { offset ->
                subtitleAtDragStart = latestSubtitle
                seekPreview = positionFor(offset.x)
            },
            onHorizontalDrag = { change, _ -> seekPreview = positionFor(change.position.x) },
            onDragEnd = {
                seekPreview?.let { model.seekTrack(item.id, (it * latestDuration).toLong()) }
                seekPreview = null
            },
            onDragCancel = { seekPreview = null },
        )
    }
    Surface(
        color = MaterialTheme.colorScheme.secondaryContainer,
        contentColor = MaterialTheme.colorScheme.onSecondaryContainer,
        shape = RoundedCornerShape(15.dp),
        modifier = Modifier.fillMaxWidth().padding(horizontal = 10.dp, vertical = 5.dp).then(seekGesture),
    ) {
        Column {
            Row(
                Modifier.fillMaxWidth().clickable(onClick = openPlayer).padding(start = 9.dp, top = 4.dp, bottom = 4.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(9.dp),
            ) {
                MusicArtwork(item.artwork, Modifier.size(38.dp), corner = 8)
                Column(Modifier.weight(1f)) {
                    Text(item.title, style = MaterialTheme.typography.titleSmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    val subtitleStyle = MaterialTheme.typography.labelSmall
                    Box(Modifier.fillMaxWidth()) {
                        val scrubbing = seekPreview != null
                        Text(
                            if (scrubbing) subtitleAtDragStart else subtitle,
                            modifier = if (scrubbing) Modifier.alpha(0f).clearAndSetSemantics {} else Modifier,
                            style = subtitleStyle,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                        )
                        if (scrubbing) {
                            val current = formatMusicTime((progress * duration).toLong()).padStart(5, '0')
                            val total = formatMusicTime(duration).padStart(5, '0')
                            Text("$current/$total", Modifier.matchParentSize(), style = subtitleStyle, maxLines = 1)
                        }
                    }
                }
                IconButton(onClick = model::toggle) {
                    if (state.buffering) CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
                    else Icon(
                        if (state.playing) Icons.Default.Pause else Icons.Default.PlayArrow,
                        when { state.error -> "重试播放"; state.playing -> "暂停"; else -> "播放" },
                    )
                }
                PonyIconButton(
                    onClick = { model.skipTrack(item.id, forward = true) },
                    icon = Icons.Default.SkipNext,
                    contentDescription = "下一首",
                )
            }
            if (duration > 0) {
                LinearProgressIndicator(
                    progress = { progress },
                    modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp).semantics {
                        contentDescription = "迷你播放器播放进度"
                        if (canSeek) setProgress { value ->
                            model.seekTrack(item.id, (value.coerceIn(0f, 1f) * duration).toLong())
                            true
                        }
                    },
                )
            }
        }
    }
}

@Composable
internal fun MusicPlayerIssueDialog(model: MusicPlayerViewModel) {
    val current by model.playerError.collectAsStateWithLifecycle()
    val issue = current ?: return
    val dismiss = { model.resolvePlayerIssue(issue) }
    when (issue) {
        MusicPlayerIssue.CONNECTION -> PonyConfirmDialog(
            title = "播放失败",
            message = issue.message,
            confirmText = "重试",
            dismissText = "关闭",
            onConfirm = { model.resolvePlayerIssue(issue, retry = true) },
            onDismiss = dismiss,
        )
        MusicPlayerIssue.UNPLAYABLE -> PonyAlertDialog(
            title = "播放失败",
            message = issue.message,
            onDismiss = dismiss,
            confirmButton = { TextButton(onClick = dismiss) { Text("关闭") } },
        )
    }
}

@Composable
internal fun MusicMessage(message: String, action: String? = null, onClick: () -> Unit = {}) {
    Column(
        Modifier.fillMaxWidth().padding(vertical = 26.dp, horizontal = 22.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(message, color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodyMedium)
        if (action != null) TextButton(onClick = onClick) { Text(action) }
    }
}

@Composable
internal fun PlaylistNameDialog(
    initial: String?,
    onDismiss: () -> Unit,
    onSave: (String) -> Unit,
) {
    var name by rememberSaveable(initial) { mutableStateOf(initial.orEmpty()) }
    val saveName = { if (name.isNotBlank()) onSave(name.trim()) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(if (initial == null) "新建歌单" else "重命名歌单") },
        text = {
            PonyTextField(
                value = name,
                onValueChange = { name = it.take(80) },
                label = "歌单名称",
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
                keyboardActions = KeyboardActions(onDone = { saveName() }),
                trailingIcon = if (name.isNotEmpty()) {
                    { PonyIconButton(onClick = { name = "" }, icon = Icons.Default.Close, contentDescription = "清空名称") }
                } else null,
            )
        },
        confirmButton = { TextButton(enabled = name.isNotBlank(), onClick = saveName) { Text("保存") } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("取消") } },
    )
}

@Composable
internal fun AddSongDialog(songId: String, library: MyMusic?, model: MusicPlayerViewModel, onDismiss: () -> Unit) {
    var create by rememberSaveable { mutableStateOf(false) }
    if (create) {
        PlaylistNameDialog(null, onDismiss) { name ->
            model.createPlaylist(name, songId)
            onDismiss()
        }
        return
    }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("添加到歌单") },
        text = {
            androidx.compose.foundation.lazy.LazyColumn(Modifier.heightIn(max = 320.dp)) {
                item {
                    TextButton(onClick = { create = true }, enabled = library != null) {
                        Icon(Icons.Default.Add, null)
                        Text("新建歌单", Modifier.padding(start = 8.dp))
                    }
                }
                items(library?.playlists.orEmpty().size) { index ->
                    val playlist = library?.playlists?.get(index) ?: return@items
                    val added = songId in playlist.songIds
                    TextButton(enabled = !added, onClick = {
                        model.updateLibrary(MusicCommand("addSong", songId = songId, playlistId = playlist.id))
                        onDismiss()
                    }) {
                        Text(playlist.name, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        if (added) Text(" · 已添加")
                    }
                }
                if (library == null) item { Text("账号同步未就绪，请刷新「我的音乐」") }
            }
        },
        confirmButton = { TextButton(onClick = onDismiss) { Text("关闭") } },
    )
}

@Composable
internal fun MusicProgress(state: MusicPlayerState, seek: (Long) -> Unit) {
    var drag by remember(state.item?.id) { mutableStateOf<Float?>(null) }
    val duration = state.durationMs
    val progress = drag ?: if (duration > 0) (state.positionMs.toFloat() / duration).coerceIn(0f, 1f) else 0f
    Slider(
        value = progress,
        enabled = state.canSeek && duration > 0,
        onValueChange = { drag = it },
        onValueChangeFinished = {
            drag?.let { seek((it * duration).toLong()) }
            drag = null
        },
        modifier = Modifier.fillMaxWidth().semantics { contentDescription = "播放进度" },
    )
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
        Text(formatMusicTime((progress * duration).toLong()), style = MaterialTheme.typography.labelSmall)
        Text(formatMusicTime(duration), style = MaterialTheme.typography.labelSmall)
    }
}

@Composable
internal fun MusicPlayButton(state: MusicPlayerState, toggle: () -> Unit, size: Dp) {
    val label = when {
        state.error -> "重试播放"
        state.buffering -> "缓冲中，暂停"
        state.playing -> "暂停"
        else -> "播放"
    }
    FilledIconButton(
        onClick = toggle,
        modifier = Modifier.size(size).semantics { contentDescription = label },
        shape = CircleShape,
        colors = IconButtonDefaults.filledIconButtonColors(containerColor = Primary, contentColor = Color.White),
    ) {
        if (state.buffering) CircularProgressIndicator(Modifier.size(size * 0.4f), color = Color.White, strokeWidth = 2.dp)
        else Icon(if (state.playing) Icons.Default.Pause else Icons.Default.PlayArrow, null, Modifier.size(size * 0.52f))
    }
}

internal fun newPlaylistId() = UUID.randomUUID().toString()

internal fun formatMusicTime(ms: Long): String {
    val seconds = ms.coerceAtLeast(0) / 1000
    return String.format(Locale.ROOT, "%d:%02d", seconds / 60, seconds % 60)
}

internal val MusicPlaybackMode.icon: ImageVector
    get() = when (this) {
        MusicPlaybackMode.LOOP -> Icons.Default.Repeat
        MusicPlaybackMode.SEQUENTIAL -> Icons.Default.FormatListNumbered
        MusicPlaybackMode.SINGLE -> Icons.Default.RepeatOne
        MusicPlaybackMode.SHUFFLE -> Icons.Default.Shuffle
    }

@Composable
internal fun MusicPlaybackIndicator(playing: Boolean) {
    val phase = if (playing) {
        val transition = rememberInfiniteTransition(label = "musicPlayback")
        transition.animateFloat(
            0f, (2 * Math.PI).toFloat(),
            infiniteRepeatable(tween(850, easing = LinearEasing)),
            label = "wavePhase",
        )
    } else null
    val color = MaterialTheme.colorScheme.primary
    Canvas(
        Modifier.size(19.dp).semantics { contentDescription = if (playing) "正在播放" else "当前曲目，已暂停" },
    ) {
        val barWidth = 2.5.dp.toPx()
        val gap = 2.6.dp.toPx()
        val left = (size.width - 3 * barWidth - 2 * gap) / 2
        repeat(3) { index ->
            val wave = phase?.let { 0.55f + 0.26f * sin(it.value + index * 1.7f) }
                ?: if (index == 1) 0.72f else 0.43f
            val height = size.height * wave
            drawRoundRect(
                color,
                topLeft = Offset(left + index * (barWidth + gap), (size.height - height) / 2),
                size = Size(barWidth, height),
                cornerRadius = CornerRadius(barWidth / 2),
            )
        }
    }
}
