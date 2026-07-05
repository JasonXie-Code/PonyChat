package top.ponychat.webview.ui.common

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.util.Base64
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.painter.ColorPainter
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage
import coil.request.CachePolicy
import coil.request.ImageRequest

// ==================== 头像颜色（马卡龙色系） ====================

/** 根据首字符生成头像背景色（与所有 AvatarPlaceholder 保持一致） */
fun getAvatarColor(char: String): Color {
    val colors = listOf(
        Color(0xFFB8A9C9), // 薰衣草紫
        Color(0xFF98D4BB), // 薄荷绿
        Color(0xFFE8A598), // 蜜桃珊瑚
        Color(0xFF89B8D4), // 雾霾蓝
        Color(0xFFE8B4B8), // 玫瑰粉
        Color(0xFFC4B896), // 燕麦黄
        Color(0xFFB8C5E8), // 长春花蓝
        Color(0xFF9CAF88), // 鼠尾草绿
        Color(0xFFD4A5A5), // 豆沙粉
        Color(0xFFA8C8E0), // 粉青蓝
        Color(0xFFC4B5D4), // 淡丁香
        Color(0xFF7EB8A8), // 海沫绿
    )
    val hash = char.hashCode().let { if (it < 0) -it else it }
    return colors[hash % colors.size]
}

// ==================== 头像缓存 Key ====================

/**
 * 生成 Coil 缓存 Key：忽略协议/域名/端口差异，只用路径部分；
 * 确保 LAN/WAN 切换时仍命中同一缓存条目。
 */
fun buildAvatarCacheKey(rawAvatarUrl: String): String {
    val cleaned = rawAvatarUrl.trim().substringBefore('?')
    return when {
        cleaned.isBlank() -> "avatar:empty"
        cleaned.startsWith("data:") -> "avatar:data:${cleaned.hashCode()}"
        cleaned.startsWith("http://") || cleaned.startsWith("https://") -> {
            val noProto = cleaned.removePrefix("http://").removePrefix("https://")
            val slashAt = noProto.indexOf('/')
            val pathOnly = if (slashAt >= 0) noProto.substring(slashAt) else noProto
            "avatar:path:$pathOnly"
        }
        else -> "avatar:path:$cleaned"
    }
}

fun decodeImageDataUri(rawAvatarUrl: String): Bitmap? {
    val cleaned = rawAvatarUrl.trim()
    if (!cleaned.startsWith("data:", ignoreCase = true)) return null
    val commaAt = cleaned.indexOf(',')
    if (commaAt < 0) return null
    val metadata = cleaned.substring(0, commaAt).lowercase()
    if (!metadata.contains(";base64")) return null
    val payload = cleaned.substring(commaAt + 1)
    val bytes = runCatching { Base64.decode(payload, Base64.DEFAULT) }.getOrNull()
        ?: return null
    return BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
}

// ==================== 统一头像组件 ====================

/**
 * 统一头像组件，用于 App 内所有需要展示头像的地方。
 *
 * 逻辑：
 * 1. 解析 avatarUrl → 优先使用 apiBase，失败后尝试 fallbackApiBase
 * 2. 使用带 cache key 的 Coil AsyncImage 加载
 * 3. 加载中：马卡龙色占位
 * 4. 加载失败（主/备都失败）：首字符 + 马卡龙色
 *
 * @param avatarUrl   原始头像路径（可以是相对路径、data URI、http 绝对地址、空）
 * @param name        显示名称，用于首字符占位和 contentDescription
 * @param apiBase     主 API 地址（如 http://192.168.1.x:8765）
 * @param fallbackApiBase 备用 API 地址，默认空（不重试）
 * @param size        头像尺寸（dp），默认 40
 * @param modifier    额外 Modifier
 */
@Composable
fun PonyAvatar(
    avatarUrl: String,
    name: String,
    apiBase: String = "",
    fallbackApiBase: String = "",
    size: Int = 40,
    modifier: Modifier = Modifier
) {
    val sizeDp = size.dp
    val context = LocalContext.current

    val firstChar = name.firstOrNull()?.toString() ?: "?"
    val avatarColor = remember(firstChar) { getAvatarColor(firstChar) }
    val cacheKey = remember(avatarUrl) { buildAvatarCacheKey(avatarUrl) }
    val dataUriBitmap = remember(avatarUrl) { decodeImageDataUri(avatarUrl) }

    val primaryUrl = remember(avatarUrl, apiBase) { resolveAvatarUrlForApi(avatarUrl, apiBase) }
    val secondaryUrl = remember(avatarUrl, apiBase, fallbackApiBase) {
        val fallback = resolveAvatarUrlForApi(avatarUrl, fallbackApiBase)
        if (fallback.isNullOrBlank() || fallback == primaryUrl) null else fallback
    }

    // loadAttempt: 0 = 用主地址，1 = 用备用地址
    var loadAttempt by remember(avatarUrl, apiBase, fallbackApiBase) { mutableIntStateOf(0) }
    val currentUrl = if (loadAttempt == 0) primaryUrl else secondaryUrl
    val canRetry = loadAttempt == 0 && !secondaryUrl.isNullOrBlank()
    var forcePlaceholder by remember(avatarUrl, apiBase, fallbackApiBase) { mutableStateOf(false) }

    val baseModifier = modifier
        .size(sizeDp)
        .clip(CircleShape)
        .background(avatarColor)

    if (dataUriBitmap != null) {
        Image(
            bitmap = dataUriBitmap.asImageBitmap(),
            contentDescription = name,
            contentScale = ContentScale.Crop,
            modifier = baseModifier
        )
    } else if (currentUrl != null && !forcePlaceholder) {
        // 用 remember 缓存 ImageRequest，只在 URL 或 cacheKey 变化时才重建。
        // 若每次重组都构造新对象，Coil 会把它识别为"新请求"并重播 crossfade 动画，
        // 导致流式输出期间（每 80ms 重组一次）头像不断闪烁。
        val imageRequest = remember(currentUrl, cacheKey) {
            ImageRequest.Builder(context)
                .data(currentUrl)
                .crossfade(150)
                .memoryCacheKey(cacheKey)
                .diskCacheKey(cacheKey)
                .placeholderMemoryCacheKey(cacheKey)
                .memoryCachePolicy(CachePolicy.ENABLED)
                .diskCachePolicy(CachePolicy.ENABLED)
                .build()
        }
        AsyncImage(
            model = imageRequest,
            contentDescription = name,
            contentScale = ContentScale.Crop,
            placeholder = ColorPainter(avatarColor),
            error = ColorPainter(avatarColor),
            onError = {
                if (canRetry) loadAttempt = 1 else forcePlaceholder = true
            },
            modifier = baseModifier
        )
    } else {
        // 首字符占位（与 CharacterAvatar 字号公式一致：size * 0.4f）
        Box(
            modifier = baseModifier,
            contentAlignment = Alignment.Center
        ) {
            Text(
                text = firstChar,
                fontSize = (size * 0.4f).sp,
                fontWeight = FontWeight.Bold,
                color = Color.White
            )
        }
    }
}
