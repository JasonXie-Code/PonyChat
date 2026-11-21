package top.ponychat.webview.ui.common

import androidx.compose.animation.core.*
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.painter.Painter
import androidx.compose.ui.layout.ContentScale
import coil.compose.AsyncImage
import coil.compose.AsyncImagePainter

/** Keep Coil's measurement, caching, gestures and failure callbacks intact. */
@Composable
fun SkeletonAsyncImage(
    model: Any?,
    contentDescription: String?,
    modifier: Modifier = Modifier,
    contentScale: ContentScale = ContentScale.Fit,
    placeholder: Painter? = null,
    error: Painter? = null,
    onSuccess: ((AsyncImagePainter.State.Success) -> Unit)? = null,
    onError: ((AsyncImagePainter.State.Error) -> Unit)? = null,
    onState: ((AsyncImagePainter.State) -> Unit)? = null,
) {
    var loading by remember(model) { mutableStateOf(model != null) }
    AsyncImage(
        model = model, contentDescription = contentDescription,
        modifier = modifier.loadingImageOverlay(loading), contentScale = contentScale,
        placeholder = placeholder, error = error,
        onLoading = { loading = true; onState?.invoke(it) },
        onSuccess = { loading = false; onSuccess?.invoke(it); onState?.invoke(it) },
        onError = { loading = false; onError?.invoke(it); onState?.invoke(it) },
    )
}

@Composable
fun Modifier.loadingImageOverlay(loading: Boolean): Modifier {
    if (!loading) return this
    val transition = rememberInfiniteTransition(label = "imageSkeleton")
    val phase by transition.animateFloat(-1f, 2f,
        infiniteRepeatable(tween(1400, easing = LinearEasing)), label = "imageShimmer")
    val color = MaterialTheme.colorScheme.onSurface
    return drawWithContent {
        drawContent()
        val x = phase * size.width
        drawRect(Brush.linearGradient(
            listOf(color.copy(alpha = 0.07f), color.copy(alpha = 0.17f), color.copy(alpha = 0.07f)),
            start = Offset(x - size.width, 0f), end = Offset(x + size.width, size.height),
        ))
    }
}
