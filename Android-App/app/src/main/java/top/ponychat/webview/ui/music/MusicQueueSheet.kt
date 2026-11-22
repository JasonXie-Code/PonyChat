package top.ponychat.webview.ui.music

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.automirrored.filled.PlaylistAdd
import androidx.compose.material.icons.filled.Album
import androidx.compose.material.icons.filled.DragHandle
import androidx.compose.material.icons.filled.ExpandLess
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material.icons.filled.Favorite
import androidx.compose.material.icons.filled.FavoriteBorder
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.semantics.CustomAccessibilityAction
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.customActions
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import sh.calvin.reorderable.ReorderableItem
import sh.calvin.reorderable.rememberReorderableLazyListState

private const val QUEUE_PREVIEW_SIZE = 4

@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun MusicQueueSheet(
    state: MusicPlayerState,
    favorite: Boolean,
    accountReady: Boolean,
    onDismiss: () -> Unit,
    onAddToPlaylist: () -> Unit,
    onToggleFavorite: () -> Unit,
    onOpenAlbum: (String) -> Unit,
    onCycleMode: () -> Unit,
    onPlaySong: (String) -> Unit,
    onMoveSong: (String, String) -> Unit,
) {
    val colors = MaterialTheme.colorScheme
    val current = state.item
    val albumId = current?.albumId
    val currentIndex = state.queue.indexOfFirst { it.id == current?.id }
    val previewStart = remember(current?.id) { currentIndex.coerceAtLeast(0) }
        .coerceAtMost((state.queue.size - QUEUE_PREVIEW_SIZE).coerceAtLeast(0))
    var expanded by remember { mutableStateOf(false) }
    val rows = if (expanded) state.queue else state.queue.drop(previewStart).take(QUEUE_PREVIEW_SIZE)
    val listState = rememberLazyListState()
    val reorderState = rememberReorderableLazyListState(listState) { from, to ->
        onMoveSong(from.key as String, to.key as String)
    }
    LaunchedEffect(expanded) {
        listState.scrollToItem(if (expanded) currentIndex.coerceAtLeast(0) else 0)
    }

    ModalBottomSheet(
        onDismissRequest = onDismiss,
        sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
        containerColor = colors.surfaceContainerLow,
        sheetMaxWidth = 570.dp,
    ) {
        BoxWithConstraints(Modifier.fillMaxWidth().padding(start = 16.dp, end = 16.dp, bottom = 14.dp)) {
            val listHeight = minOf(maxHeight * 0.56f, if (expanded) 420.dp else 304.dp)
            Column(verticalArrangement = Arrangement.spacedBy(14.dp)) {
                if (current != null) {
                    Row(
                        Modifier.fillMaxWidth().padding(bottom = 3.dp),
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        QueueShortcut(
                            "加到歌单", Icons.AutoMirrored.Filled.PlaylistAdd,
                            accountReady, Modifier.weight(1f), onClick = onAddToPlaylist,
                        )
                        QueueShortcut(
                            "查看专辑", Icons.Default.Album, albumId != null, Modifier.weight(1f),
                            onClick = { albumId?.let(onOpenAlbum) },
                        )
                        QueueShortcut(
                            if (favorite) "已收藏" else "收藏歌曲",
                            if (favorite) Icons.Default.Favorite else Icons.Default.FavoriteBorder,
                            accountReady, Modifier.weight(1f),
                            tint = if (favorite) colors.primary else colors.onSurface,
                            onClick = onToggleFavorite,
                        )
                    }
                }

                Surface(shape = RoundedCornerShape(18.dp), color = colors.surfaceContainer) {
                    Column(Modifier.fillMaxWidth().padding(top = 14.dp, bottom = 4.dp)) {
                        QueueHeading(current, state.mode, onOpenAlbum, onCycleMode)
                        if (rows.isEmpty()) {
                            MusicMessage("播放列表为空")
                        } else {
                            LazyColumn(state = listState, modifier = Modifier.heightIn(max = listHeight)) {
                                itemsIndexed(rows, key = { _, song -> song.id }) { index, song ->
                                    val selected = song.id == current?.id
                                    ReorderableItem(reorderState, key = song.id, enabled = !selected) { dragging ->
                                        val canMove = !selected && rows.size > 1
                                        val grip = if (canMove) {
                                            Modifier.draggableHandle().semantics {
                                                customActions = buildList {
                                                    rows.getOrNull(index - 1)?.let { previous ->
                                                        add(CustomAccessibilityAction("上移") { onMoveSong(song.id, previous.id); true })
                                                    }
                                                    rows.getOrNull(index + 1)?.let { next ->
                                                        add(CustomAccessibilityAction("下移") { onMoveSong(song.id, next.id); true })
                                                    }
                                                }
                                            }
                                        } else Modifier
                                        QueueSongRow(song, selected, state.playing, dragging, grip) { onPlaySong(song.id) }
                                    }
                                }
                            }
                        }
                        if (state.queue.size > QUEUE_PREVIEW_SIZE) {
                            TextButton(
                                onClick = { expanded = !expanded },
                                modifier = Modifier.align(Alignment.CenterHorizontally).padding(top = 2.dp),
                            ) {
                                Text(if (expanded) "收起" else "查看全部 · ${state.queue.size} 首")
                                Icon(
                                    if (expanded) Icons.Default.ExpandLess else Icons.Default.ExpandMore,
                                    null, Modifier.padding(start = 3.dp).size(18.dp),
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun QueueShortcut(
    title: String,
    icon: ImageVector,
    enabled: Boolean,
    modifier: Modifier,
    tint: Color = MaterialTheme.colorScheme.onSurface,
    onClick: () -> Unit,
) {
    val colors = MaterialTheme.colorScheme
    Column(
        modifier.clip(RoundedCornerShape(14.dp)).clickable(enabled = enabled, role = Role.Button, onClick = onClick)
            .padding(vertical = 4.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(7.dp),
    ) {
        Box(
            Modifier.size(51.dp).background(colors.surfaceContainer, CircleShape),
            contentAlignment = Alignment.Center,
        ) {
            Icon(icon, null, Modifier.size(24.dp), tint = tint.copy(alpha = if (enabled) 1f else 0.38f))
        }
        Text(
            title,
            style = MaterialTheme.typography.labelMedium,
            color = colors.onSurfaceVariant.copy(alpha = if (enabled) 1f else 0.38f),
        )
    }
}

@Composable
private fun QueueHeading(current: MusicItem?, mode: MusicPlaybackMode, onOpenAlbum: (String) -> Unit, onCycleMode: () -> Unit) {
    val colors = MaterialTheme.colorScheme
    val albumId = current?.albumId
    Row(
        Modifier.fillMaxWidth().padding(start = 16.dp, end = 13.dp, bottom = 9.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Text("播放列表", style = MaterialTheme.typography.headlineSmall)
            if (!current?.album.isNullOrBlank()) {
                Row(
                    Modifier.clip(RoundedCornerShape(6.dp))
                        .clickable(enabled = albumId != null, onClickLabel = "打开专辑") { albumId?.let(onOpenAlbum) }
                        .padding(vertical = 5.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        current?.album.orEmpty(), Modifier.weight(1f, fill = false),
                        style = MaterialTheme.typography.bodySmall, color = colors.onSurfaceVariant,
                        maxLines = 1, overflow = TextOverflow.Ellipsis,
                    )
                    if (albumId != null) {
                        Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, null, Modifier.size(16.dp), tint = colors.onSurfaceVariant)
                    }
                }
            }
        }
        Surface(
            onClick = onCycleMode,
            shape = CircleShape,
            color = colors.secondaryContainer,
            contentColor = colors.onSecondaryContainer,
        ) {
            Row(
                Modifier.padding(horizontal = 10.dp, vertical = 7.dp),
                horizontalArrangement = Arrangement.spacedBy(5.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(mode.icon, null, Modifier.size(17.dp))
                Text(mode.label, style = MaterialTheme.typography.labelSmall)
            }
        }
    }
}

@Composable
private fun QueueSongRow(
    song: MusicItem,
    selected: Boolean,
    playing: Boolean,
    dragging: Boolean,
    grip: Modifier,
    onClick: () -> Unit,
) {
    val colors = MaterialTheme.colorScheme
    Row(
        Modifier.fillMaxWidth().heightIn(min = 62.dp)
            .background(if (dragging) colors.surfaceContainerHighest else Color.Transparent)
            .clickable(onClickLabel = "播放这首歌", onClick = onClick)
            .padding(start = 16.dp, end = 7.dp, top = 6.dp, bottom = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(3.dp)) {
            Text(
                song.title,
                color = if (selected) colors.primary else colors.onSurface,
                style = MaterialTheme.typography.titleMedium,
                fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Normal,
                maxLines = 1, overflow = TextOverflow.Ellipsis,
            )
            val credit = listOf(song.artist, song.album).filter(String::isNotBlank).distinct().joinToString(" · ")
            if (credit.isNotEmpty()) {
                Text(
                    credit, style = MaterialTheme.typography.bodySmall, color = colors.onSurfaceVariant,
                    maxLines = 1, overflow = TextOverflow.Ellipsis,
                )
            }
        }
        Box(Modifier.size(48.dp).then(grip), contentAlignment = Alignment.Center) {
            if (selected) MusicPlaybackIndicator(playing)
            else Icon(
                Icons.Default.DragHandle, "拖动调整 ${song.title} 的顺序",
                Modifier.size(24.dp), tint = colors.onSurfaceVariant,
            )
        }
    }
}
