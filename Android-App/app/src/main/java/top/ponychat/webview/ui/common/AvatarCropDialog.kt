package top.ponychat.webview.ui.common

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.util.Base64
import java.io.ByteArrayOutputStream
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import top.ponychat.webview.ui.theme.Primary

/**
 * 头像裁剪：输出 1:1、512px，与 [cropAvatarBitmap] 算法一致。
 * 单指拖动 = 平移取景，双指捏合 = 缩放（同管理端 Web：滚轮/双指）。
 */
@Composable
fun AvatarCropDialog(
    source: Bitmap,
    onDismiss: () -> Unit,
    onConfirm: (String) -> Unit
) {
    var zoom by remember { mutableFloatStateOf(1f) }
    var offsetX by remember { mutableFloatStateOf(0f) }
    var offsetY by remember { mutableFloatStateOf(0f) }
    var boxPx by remember { mutableFloatStateOf(320f) }

    val previewBitmap = remember(zoom, offsetX, offsetY) {
        cropAvatarBitmap(source, zoom, offsetX, offsetY)
    }

    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = MaterialTheme.colorScheme.surface,
        title = { Text("裁剪头像", color = MaterialTheme.colorScheme.onBackground) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(
                    "单指拖动调整位置，双指捏合缩放",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .heightIn(max = 320.dp)
                        .aspectRatio(1f)
                        .onSizeChanged { boxPx = it.width.toFloat().coerceAtLeast(1f) }
                        .clip(RoundedCornerShape(10.dp))
                        .background(MaterialTheme.colorScheme.surfaceVariant)
                        .pointerInput(boxPx) {
                            detectTransformGestures { _, pan, zoomChange, _ ->
                                zoom = (zoom * zoomChange).coerceIn(1f, 3f)
                                val d = 2.5f / boxPx
                                offsetX = (offsetX - pan.x * d).coerceIn(-1f, 1f)
                                offsetY = (offsetY - pan.y * d).coerceIn(-1f, 1f)
                            }
                        },
                    contentAlignment = Alignment.Center
                ) {
                    Image(
                        bitmap = previewBitmap.asImageBitmap(),
                        contentDescription = "裁剪预览",
                        modifier = Modifier.fillMaxSize(),
                        contentScale = ContentScale.Fit
                    )
                }
                Text(
                    "1:1 比例 · 缩放 ${"%.2f".format(zoom)}×",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        },
        confirmButton = {
            TextButton(onClick = { onConfirm(bitmapToAvatarDataUrl(previewBitmap)) }) {
                Text("确定", color = Primary, fontWeight = FontWeight.Bold)
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) {
                Text("取消", color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    )
}

private fun cropAvatarBitmap(source: Bitmap, zoom: Float, offsetX: Float, offsetY: Float): Bitmap {
    val safeZoom = zoom.coerceIn(1f, 3f)
    val cropSize = (minOf(source.width, source.height) / safeZoom).toInt().coerceAtLeast(64)
    val maxLeft = source.width - cropSize
    val maxTop = source.height - cropSize
    val left = ((maxLeft / 2f) + offsetX.coerceIn(-1f, 1f) * (maxLeft / 2f)).toInt().coerceIn(0, maxLeft.coerceAtLeast(0))
    val top = ((maxTop / 2f) + offsetY.coerceIn(-1f, 1f) * (maxTop / 2f)).toInt().coerceIn(0, maxTop.coerceAtLeast(0))
    val cropped = Bitmap.createBitmap(source, left, top, cropSize, cropSize)
    return Bitmap.createScaledBitmap(cropped, 512, 512, true)
}

fun bitmapToAvatarDataUrl(bitmap: Bitmap): String {
    val w = bitmap.width
    val h = bitmap.height
    val out = ByteArrayOutputStream()
    if (w <= 0 || h <= 0) {
        bitmap.compress(Bitmap.CompressFormat.JPEG, 90, out)
    } else {
        val flat = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(flat)
        canvas.drawColor(Color.WHITE)
        canvas.drawBitmap(bitmap, 0f, 0f, null)
        flat.compress(Bitmap.CompressFormat.JPEG, 90, out)
        flat.recycle()
    }
    val b64 = Base64.encodeToString(out.toByteArray(), Base64.NO_WRAP)
    return "data:image/jpeg;base64,$b64"
}
