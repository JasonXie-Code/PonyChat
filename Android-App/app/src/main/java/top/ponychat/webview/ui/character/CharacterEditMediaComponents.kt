package top.ponychat.webview.ui.character

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.AddPhotoAlternate
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.unit.dp
import coil.compose.AsyncImage
import top.ponychat.webview.ui.theme.ErrorColor
import top.ponychat.webview.ui.theme.Primary
import top.ponychat.webview.ui.theme.ScaledIcon as Icon

@Composable
internal fun ProfileCoverEditor(
    coverUrl: String,
    apiBase: String,
    isUploading: Boolean,
    enabled: Boolean,
    onPick: () -> Unit,
    onRemove: () -> Unit,
    onDisabledClick: () -> Unit
) {
    Column(modifier = Modifier.padding(horizontal = 16.dp, vertical = 10.dp)) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(132.dp)
                .clip(RoundedCornerShape(10.dp))
                .background(MaterialTheme.colorScheme.surface.copy(alpha = 0.8f))
                .clickable { if (enabled) onPick() else onDisabledClick() },
            contentAlignment = Alignment.Center
        ) {
            if (coverUrl.isNotBlank()) {
                AsyncImage(
                    model = resolveProfileImageModel(coverUrl, apiBase),
                    contentDescription = null,
                    contentScale = ContentScale.Crop,
                    modifier = Modifier.fillMaxSize()
                )
            } else {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Icon(Icons.Filled.AddPhotoAlternate, contentDescription = null, tint = Primary)
                    Spacer(Modifier.height(6.dp))
                    Text("上传封面图", color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
            if (isUploading) {
                Surface(color = Color.Black.copy(alpha = 0.35f), modifier = Modifier.fillMaxSize()) {
                    Box(contentAlignment = Alignment.Center) {
                        CircularProgressIndicator(color = Color.White, modifier = Modifier.size(26.dp), strokeWidth = 2.dp)
                    }
                }
            }
        }
        if (coverUrl.isNotBlank() && enabled) {
            TextButton(onClick = onRemove, modifier = Modifier.align(Alignment.End)) {
                Text("移除封面", color = ErrorColor)
            }
        }
    }
}

@Composable
internal fun ProfilePhotosEditor(
    photos: List<String>,
    apiBase: String,
    isUploading: Boolean,
    enabled: Boolean,
    onAdd: () -> Unit,
    onRemove: (Int) -> Unit,
    onDisabledClick: () -> Unit
) {
    Column(modifier = Modifier.padding(vertical = 10.dp)) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp, vertical = 2.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text("相册图片", color = MaterialTheme.colorScheme.onBackground, style = MaterialTheme.typography.titleSmall)
            Text("${photos.size}/12", color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodySmall)
        }
        Spacer(Modifier.height(8.dp))
        LazyRow(
            horizontalArrangement = Arrangement.spacedBy(10.dp),
            contentPadding = PaddingValues(horizontal = 16.dp)
        ) {
            item {
                Box(
                    modifier = Modifier
                        .size(width = 96.dp, height = 122.dp)
                        .clip(RoundedCornerShape(10.dp))
                        .background(MaterialTheme.colorScheme.surface.copy(alpha = 0.8f))
                        .clickable { if (enabled) onAdd() else onDisabledClick() },
                    contentAlignment = Alignment.Center
                ) {
                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                        Icon(Icons.Filled.Add, contentDescription = null, tint = Primary)
                        Text("添加", style = MaterialTheme.typography.labelMedium, color = Primary)
                    }
                    if (isUploading) {
                        CircularProgressIndicator(modifier = Modifier.size(22.dp), strokeWidth = 2.dp)
                    }
                }
            }
            itemsIndexed(photos) { index, url ->
                EditableAlbumPhoto(
                    model = resolveProfileImageModel(url, apiBase),
                    enabled = enabled,
                    onRemove = { onRemove(index) }
                )
            }
        }
    }
}

@Composable
private fun EditableAlbumPhoto(
    model: Any?,
    enabled: Boolean,
    onRemove: () -> Unit
) {
    val thumbHeight = 122.dp
    var aspectRatio by remember(model) { mutableFloatStateOf(96f / 122f) }
    val thumbWidth = (thumbHeight.value * aspectRatio.coerceIn(0.2f, 4f)).dp
    Box(
        modifier = Modifier
            .width(thumbWidth)
            .height(thumbHeight)
            .clip(RoundedCornerShape(10.dp))
            .background(Color.White),
        contentAlignment = Alignment.Center
    ) {
        AsyncImage(
            model = model,
            contentDescription = null,
            contentScale = ContentScale.Fit,
            onSuccess = { success ->
                val drawable = success.result.drawable
                val w = drawable.intrinsicWidth
                val h = drawable.intrinsicHeight
                if (w > 0 && h > 0) {
                    aspectRatio = (w.toFloat() / h.toFloat()).coerceIn(0.2f, 4f)
                }
            },
            modifier = Modifier.fillMaxSize()
        )
        if (enabled) {
            IconButton(
                onClick = onRemove,
                modifier = Modifier
                    .align(Alignment.TopEnd)
                    .size(30.dp)
                    .background(Color.Black.copy(alpha = 0.45f), CircleShape)
            ) {
                Icon(Icons.Filled.Close, contentDescription = "删除", tint = Color.White, modifier = Modifier.size(16.dp))
            }
        }
    }
}


private fun resolveProfileImageModel(url: String, apiBase: String): String {
    val trimmed = url.trim()
    if (trimmed.isBlank() || trimmed.startsWith("data:") || trimmed.startsWith("http://") || trimmed.startsWith("https://")) {
        return trimmed
    }
    val base = apiBase.trimEnd('/')
    return if (trimmed.startsWith("/")) "$base$trimmed" else "$base/$trimmed"
}

