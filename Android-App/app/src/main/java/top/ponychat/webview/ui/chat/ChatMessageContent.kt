package top.ponychat.webview.ui.chat

import android.content.ContentValues
import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.ImageDecoder
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import android.util.Base64
import android.util.Log
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.platform.LocalContext
import coil.imageLoader
import coil.request.ImageRequest
import androidx.core.content.FileProvider
import androidx.core.graphics.drawable.toBitmap
import okhttp3.Request
import top.ponychat.webview.data.api.NetworkClient
import top.ponychat.webview.data.prefs.AppPreferences
import java.io.ByteArrayOutputStream
import java.io.File
import java.text.SimpleDateFormat
import java.time.LocalDate
import java.time.temporal.ChronoUnit
import java.util.Calendar
import java.util.Date
import java.util.Locale
import kotlin.math.max
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

// ==================== 消息内容解析 ====================

/** 思维链已从展示层移除：thinkContent / isThinkStreaming 恒为 null/false，仅保留字段以减轻调用方改动。 */
data class ParsedMessageContent(
    val thinkContent: String?,
    val mainContent: String,
    val isThinkStreaming: Boolean = false
)

data class GalgameOption(
    val label: String,
    val type: String = "",
    val tone: String = ""
)

data class MessageMedia(
    val imageUrls: List<String>,
    val text: String
) {
    val imageUrl: String? get() = imageUrls.firstOrNull()
}

/** 格式化消息时间戳，与 Web 端 .msg-timestamp 一致 */
fun formatMessageTime(timestampMs: Long, nowMs: Long = System.currentTimeMillis()): String {
    val date = Date(timestampMs)
    val diff = nowMs - timestampMs
    val nowCal = Calendar.getInstance().apply { timeInMillis = nowMs }
    val targetCal = Calendar.getInstance().apply { time = date }
    val sameYear = nowCal.get(Calendar.YEAR) == targetCal.get(Calendar.YEAR)
    val dayDiff = localDayDiff(nowCal, targetCal)
    return when {
        dayDiff == 0L && diff in -60_000 until 60_000 -> "刚刚"
        dayDiff == 0L && diff in 60_000 until 3600_000 -> "${diff / 60_000}分钟前"
        dayDiff == 0L -> SimpleDateFormat("HH:mm", Locale.getDefault()).format(date)
        dayDiff == 1L -> "昨天 " + SimpleDateFormat("HH:mm", Locale.getDefault()).format(date)
        sameYear -> SimpleDateFormat("M.d HH:mm", Locale.getDefault()).format(date)
        else -> SimpleDateFormat("yyyy.M.d HH:mm", Locale.getDefault()).format(date)
    }
}

/** AI 消息头部时间：今天 HH:mm / 昨天 HH:mm / yyyy.M.d HH:mm */
fun formatAssistantHeaderTime(timestampMs: Long, nowMs: Long = System.currentTimeMillis()): String {
    val date = Date(timestampMs)
    val now = Calendar.getInstance().apply { timeInMillis = nowMs }
    val target = Calendar.getInstance().apply { time = date }
    val sameYear = now.get(Calendar.YEAR) == target.get(Calendar.YEAR)
    val dayDiff = localDayDiff(now, target)
    return when {
        dayDiff == 0L -> SimpleDateFormat("HH:mm", Locale.getDefault()).format(date)
        dayDiff == 1L -> "昨天 " + SimpleDateFormat("HH:mm", Locale.getDefault()).format(date)
        sameYear -> SimpleDateFormat("M.d HH:mm", Locale.getDefault()).format(date)
        else -> SimpleDateFormat("yyyy.M.d HH:mm", Locale.getDefault()).format(date)
    }
}

private fun localDayDiff(now: Calendar, target: Calendar): Long {
    val nowDate = now.toLocalDate()
    val targetDate = target.toLocalDate()
    return ChronoUnit.DAYS.between(targetDate, nowDate)
}

private fun Calendar.toLocalDate(): LocalDate {
    return LocalDate.of(
        get(Calendar.YEAR),
        get(Calendar.MONTH) + 1,
        get(Calendar.DAY_OF_MONTH)
    )
}

internal fun formatGenerationDuration(durationMs: Long?): String? {
    if (durationMs == null || durationMs <= 0L) return null
    val safe = durationMs.coerceAtLeast(0L)
    val sec = ((safe + 500L) / 1000L).coerceAtLeast(1L)
    return "${sec}s"
}

/** DeepSeek 等模型使用的 `think` 围栏（\u0060 = `） */
private val THINK_FENCE = "\u0060think\u0060"

/** 去掉 think / `<thinking>` 思维块（含未闭合尾部），所有模式均不展示思维链。 */
fun stripThinkBlocksForDisplay(raw: String): String {
    var s = Regex("<think(?:ing)?>[\\s\\S]*?(?:</think(?:ing)?>|$)", RegexOption.IGNORE_CASE).replace(raw, "")
    s = Regex("```[ \\t]*think(?:ing)?[^\\n\\r]*[\\r\\n]+[\\s\\S]*?(?:```|$)", RegexOption.IGNORE_CASE).replace(s, "")
    val openThink = s.lastIndexOf(THINK_FENCE, ignoreCase = true)
    val openThinkTag = s.lastIndexOf("<think>", ignoreCase = true)
    val openThinking = s.lastIndexOf("<thinking>", ignoreCase = true)
    val openIdx = maxOf(openThink, openThinkTag, openThinking)
    if (openIdx >= 0) {
        val tagLen = when (openIdx) {
            openThinking -> 10
            openThinkTag -> 7
            else -> THINK_FENCE.length
        }
        val afterOpen = s.substring(openIdx + tagLen)
        val hasClose =
            afterOpen.contains(THINK_FENCE, ignoreCase = true) ||
                afterOpen.contains("</think>", ignoreCase = true) ||
                afterOpen.contains("</thinking>", ignoreCase = true)
        if (!hasClose) s = s.substring(0, openIdx)
    }
    return s.trim()
}

fun parseMessageContent(raw: String): ParsedMessageContent {
    val main = stripThinkBlocksForDisplay(raw)
    return ParsedMessageContent(thinkContent = null, mainContent = main, isThinkStreaming = false)
}

@Suppress("unused")
private fun parseGalgameScore(content: String): Int? {
    return try {
        val json = org.json.JSONObject(content)
        val scoreObj = json.optJSONObject("score") ?: return null
        scoreObj.optInt("current")
    } catch (_: Exception) {
        null
    }
}

internal fun parseGalgameOptions(content: String): List<GalgameOption> {
    return try {
        val json = org.json.JSONObject(content)
        val arr = json.optJSONArray("suggested_options") ?: return emptyList()
        buildList {
            for (i in 0 until arr.length()) {
                val item = arr.optJSONObject(i) ?: continue
                val label = item.optString("label").trim()
                if (label.isNotBlank()) {
                    add(
                        GalgameOption(
                            label = label,
                            type = item.optString("type").trim(),
                            tone = item.optString("tone").trim()
                        )
                    )
                }
            }
        }
    } catch (_: Exception) {
        emptyList()
    }
}

/** 去掉 HTML 标签并还原常见实体，用于游戏/锁分模式复制可见文本 */
internal fun stripHtml(html: String): String {
    if (html.isBlank()) return html
    return html
        .replace(Regex("""<[^>]+>"""), " ")
        .replace("&quot;", "\"")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&#39;", "'")
        .replace(Regex("\\s+"), " ")
        .trim()
}

// ── 图片性能调试日志 ─────────────────────────────────────────────────────────────────────
internal const val IMG_PERF_TAG = "ImgPerf"

// ── 进程级全局缓存，不受 composition 生命周期限制 ─────────────────────────────────────────
// LazyColumn item 离开视口后 composition 被销毁，remember 缓存随之失效；
// 滚回来时若没有全局缓存，Base64.decode() 和 regex 都会在主线程重跑，导致掉帧。

// _b64FileCache：base64 data URL → 磁盘文件路径映射；最大 500 条
// Coil 从 File 加载比从 ByteArray 加载高效：File 走完整 memory+disk cache 链路，
// ByteArray 每次 Coil memory cache miss 后都需重新 BitmapFactory.decode。
private val _b64FileCache: android.util.LruCache<Long, java.io.File> = android.util.LruCache(500)
private var _b64CacheDir: java.io.File? = null

private fun getB64CacheDir(context: Context): java.io.File {
    _b64CacheDir?.let { return it }
    val dir = java.io.File(context.cacheDir, "b64_img_cache")
    if (!dir.exists()) dir.mkdirs()
    _b64CacheDir = dir
    return dir
}

// _mediaCache：缓存 splitMessageMedia 解析结果；最大 300 条消息
private val _mediaCache: android.util.LruCache<Long, MessageMedia> = android.util.LruCache(300)
internal const val LOCAL_IMAGE_REMOTE_PREFS = "ponychat_local_image_remote"

/** 把 (len, hash) 两个 Int 压缩成一个 Long 作为缓存 key */
private fun contentCacheKey(len: Int, hash: Int): Long =
    len.toLong().shl(32).or(hash.toLong().and(0xFFFFFFFFL))
// ─────────────────────────────────────────────────────────────────────────────────────────

/**
 * 将 base64 data URL 解码并写入磁盘缓存文件，返回 File。
 * 线程安全：可在任意线程调用，文件写入使用 .tmp 原子重命名。
 */
internal fun decodeB64ToFile(dataUrl: String, context: Context): java.io.File? {
    val len = dataUrl.length
    val hash = dataUrl.hashCode()
    val key = contentCacheKey(len, hash)
    _b64FileCache.get(key)?.let { if (it.exists()) {
        Log.d(IMG_PERF_TAG, "b64→file cache HIT: ${len / 1024}KB dataUrl → ${it.name}")
        return it
    } }
    val t0 = System.nanoTime()
    return try {
        val b64 = dataUrl.substringAfter("base64,", "")
        if (b64.isEmpty()) return null
        val bytes = Base64.decode(b64, Base64.DEFAULT)
        val decodeMs = (System.nanoTime() - t0) / 1_000_000
        val ext = when {
            dataUrl.startsWith("data:image/png")  -> "png"
            dataUrl.startsWith("data:image/gif")  -> "gif"
            dataUrl.startsWith("data:image/webp") -> "webp"
            else -> "jpg"
        }
        val dir = getB64CacheDir(context)
        val file = java.io.File(dir, "${len}_${hash}.$ext")
        if (!file.exists()) {
            val tmp = java.io.File(dir, "${len}_${hash}.tmp")
            tmp.writeBytes(bytes)
            tmp.renameTo(file)
            val totalMs = (System.nanoTime() - t0) / 1_000_000
            Log.d(IMG_PERF_TAG, "b64→file WRITE: ${len / 1024}KB dataUrl → ${bytes.size / 1024}KB $ext, decode=${decodeMs}ms, total=${totalMs}ms")
        } else {
            Log.d(IMG_PERF_TAG, "b64→file EXIST: ${len / 1024}KB dataUrl → ${file.name}, decode=${decodeMs}ms")
        }
        _b64FileCache.put(key, file)
        file
    } catch (e: Exception) {
        Log.w(IMG_PERF_TAG, "b64→file FAIL: ${len / 1024}KB dataUrl, err=${e.message}")
        null
    }
}

/**
 * 为 Coil 返回最优的 model 对象：
 * - 普通 URL：原样返回字符串
 * - base64 data URL：优先返回已缓存的磁盘 File（Coil 走完整 cache 链路），
 *   未缓存时回退为 ByteArray（保证首次同步加载不阻塞）
 */
private fun imageModelForCoil(urlOrDataUrl: String, context: Context? = null): Any {
    localChatImageFile(urlOrDataUrl)?.let { file ->
        if (file.exists()) return file
    }
    if (urlOrDataUrl.startsWith("/chat_images/") && context != null) {
        localForRemoteChatImage(context, urlOrDataUrl)?.let { return it }
        Log.w(IMG_PERF_TAG, "local chat image missing for $urlOrDataUrl; skip server fetch")
        return android.graphics.drawable.ColorDrawable(android.graphics.Color.TRANSPARENT)
    }
    if (urlOrDataUrl.startsWith("/chat_images/")) {
        Log.w(IMG_PERF_TAG, "local chat image has no context for $urlOrDataUrl; skip server fetch")
        return android.graphics.drawable.ColorDrawable(android.graphics.Color.TRANSPARENT)
    }
    if (urlOrDataUrl.startsWith("/") && context != null) {
        val base = AppPreferences(context).effectiveApiBase().trimEnd('/')
        return "$base$urlOrDataUrl"
    }
    if (!urlOrDataUrl.startsWith("data:")) return urlOrDataUrl
    val len  = urlOrDataUrl.length
    val hash = urlOrDataUrl.hashCode()
    val key  = contentCacheKey(len, hash)
    _b64FileCache.get(key)?.let { if (it.exists()) {
        Log.d(IMG_PERF_TAG, "Coil model: FILE cache hit (${it.name})")
        return it
    } }
    if (context != null) {
        decodeB64ToFile(urlOrDataUrl, context)?.let {
            Log.d(IMG_PERF_TAG, "Coil model: FILE on-demand decode (${it.name})")
            return it
        }
    }
    Log.d(IMG_PERF_TAG, "Coil model: BYTE fallback (${len / 1024}KB)")
    return try {
        val b64 = urlOrDataUrl.substringAfter("base64,", "")
        if (b64.isEmpty()) urlOrDataUrl else Base64.decode(b64, Base64.DEFAULT)
    } catch (_: Exception) { urlOrDataUrl }
}

private fun localChatImageFile(url: String): File? {
    if (!url.startsWith("file://", ignoreCase = true)) return null
    return runCatching { File(Uri.parse(url).path ?: return null) }.getOrNull()
}

private fun isMissingLocalChatImage(url: String): Boolean {
    val file = localChatImageFile(url) ?: return false
    return !file.exists()
}

private fun chatImageDir(context: Context): File =
    File(context.filesDir, "chat_images").also { if (!it.exists()) it.mkdirs() }

private fun extensionFromMime(mimeType: String?): String {
    return when ((mimeType ?: "").substringBefore(";").lowercase()) {
        "image/png", "image/apng" -> "png"
        "image/gif" -> "gif"
        "image/webp" -> "webp"
        else -> "jpg"
    }
}

internal fun saveLocalChatImageBytes(context: Context, bytes: ByteArray, extension: String = "jpg"): String? {
    if (bytes.isEmpty()) return null
    return runCatching {
        val safeExt = extension.lowercase().replace(Regex("[^a-z0-9]"), "").ifBlank { "jpg" }
        val file = File(chatImageDir(context), "chat_${System.currentTimeMillis()}_${bytes.contentHashCode()}.$safeExt")
        val tmp = File(file.parentFile, "${file.name}.tmp")
        tmp.writeBytes(bytes)
        if (!tmp.renameTo(file)) {
            file.writeBytes(bytes)
            tmp.delete()
        }
        Uri.fromFile(file).toString()
    }.getOrNull()
}

internal fun saveLocalChatImageFromUri(context: Context, uri: Uri): String? {
    return runCatching {
        val bitmap = decodeBitmapForChatSendFromUri(context, uri) ?: return null
        try {
            saveLocalChatImageBytes(context, bitmapToJpegBytesForUpload(bitmap), "jpg")
        } finally {
            bitmap.recycle()
        }
    }.getOrNull()
}

internal fun rememberLocalChatImageRemote(context: Context, localUrl: String, remoteUrl: String,
                                         synchronous: Boolean = false): Boolean {
    if (localUrl.isBlank() || remoteUrl.isBlank()) return false
    val edit = context.getSharedPreferences(LOCAL_IMAGE_REMOTE_PREFS, Context.MODE_PRIVATE)
        .edit()
        .putString(localUrl, remoteUrl)
    if (synchronous) return edit.commit()
    edit.apply()
    return true
}

internal fun loadChatImageBytesForUpload(context: Context, imageUrl: String): ByteArray? {
    return loadOriginalPreviewBytes(context, imageUrl)?.bytes
}

private fun remoteForLocalChatImage(context: Context, localUrl: String): String? {
    return context.getSharedPreferences(LOCAL_IMAGE_REMOTE_PREFS, Context.MODE_PRIVATE)
        .getString(localUrl, null)
        ?.takeIf { it.isNotBlank() }
}

private fun localForRemoteChatImage(context: Context, remoteUrl: String): File? {
    if (!remoteUrl.startsWith("/chat_images/")) return null
    val prefs = context.getSharedPreferences(LOCAL_IMAGE_REMOTE_PREFS, Context.MODE_PRIVATE)
    prefs.all.entries.forEach { (localUrl, value) ->
        if (value == remoteUrl) {
            localChatImageFile(localUrl)?.let { file ->
                if (file.exists() && file.length() > 0L) return file
            }
        }
    }
    return null
}

internal fun localUrlForRemoteChatImage(context: Context, remoteUrl: String): String? {
    if (!remoteUrl.startsWith("/chat_images/")) return null
    val prefs = context.getSharedPreferences(LOCAL_IMAGE_REMOTE_PREFS, Context.MODE_PRIVATE)
    prefs.all.entries.forEach { (localUrl, value) ->
        if (value == remoteUrl) {
            localChatImageFile(localUrl)?.let { file ->
                if (file.exists() && file.length() > 0L) return localUrl
            }
        }
    }
    return null
}

internal fun restoreRemoteChatImagesForDisplay(context: Context, content: String): String {
    if (!content.contains("/chat_images/")) return content
    return content.replace(_MD_IMAGE_REGEX) { match ->
        val url = match.groupValues.getOrNull(1)?.trim().orEmpty()
        val localUrl = localUrlForRemoteChatImage(context, url) ?: return@replace match.value
        match.value.replace(url, localUrl)
    }
}

private fun isMissingLocalChatImageForDisplay(context: Context?, url: String): Boolean {
    if (url.startsWith("file://", ignoreCase = true)) {
        return isMissingLocalChatImage(url)
    }
    if (url.startsWith("/chat_images/")) {
        return context == null || localForRemoteChatImage(context, url) == null
    }
    return false
}

internal fun replaceLocalChatImagesForServer(context: Context, content: String): String {
    if (!content.contains("file://")) return content
    return content.replace(_MD_IMAGE_REGEX) { match ->
        val url = match.groupValues.getOrNull(1)?.trim().orEmpty()
        val remote = remoteForLocalChatImage(context, url)
        if (remote.isNullOrBlank()) "" else "![]($remote)"
    }
}

/**
 * 全屏预览用 ImageRequest：加载完整高清版。
 * memoryCacheKey / diskCacheKey 以内容 hash 为键，跨重组保持缓存命中。
 */
@Composable
internal fun rememberChatImageRequest(urlOrDataUrl: String): ImageRequest {
    val context = LocalContext.current
    val resolvedUrl = rememberResolvedChatImageUrl(urlOrDataUrl)
    val len = resolvedUrl.length
    val hash = resolvedUrl.hashCode()
    return remember(context, resolvedUrl) {
        val cacheKey = if (resolvedUrl.startsWith("data:")) "base64_${len}_${hash}" else resolvedUrl
        val urlShort = resolvedUrl.takeLast(60)
        ImageRequest.Builder(context)
            .data(imageModelForCoil(resolvedUrl, context))
            .memoryCacheKey(cacheKey)
            .diskCacheKey(cacheKey)
            .listener(
                onError = { _, result ->
                    val t = result.throwable
                    Log.e(IMG_PERF_TAG, "Coil FULL ERR: ...${urlShort} → " +
                        "${t.javaClass.simpleName}: ${t.message}")
                }
            )
            .build()
    }
}

/**
 * 聊天列表缩略图 ImageRequest：目标尺寸最大 360×360 px（约 120dp @3x）。
 * Coil 据此推算 inSampleSize，对大图解码速度提升显著、内存占用同比下降。
 * 全屏预览使用独立的 [rememberChatImageRequest]，可按需加载完整高清版。
 */
@Composable
internal fun rememberThumbnailImageRequest(urlOrDataUrl: String): ImageRequest {
    val context = LocalContext.current
    val resolvedUrl = rememberResolvedChatImageUrl(urlOrDataUrl)
    val len = resolvedUrl.length
    val hash = resolvedUrl.hashCode()
    return remember(context, resolvedUrl) {
        val cacheKey = if (resolvedUrl.startsWith("data:")) "thumb_${len}_${hash}" else "thumb_$resolvedUrl"
        val urlShort = resolvedUrl.takeLast(60)
        ImageRequest.Builder(context)
            .data(imageModelForCoil(resolvedUrl, context))
            .size(360, 360)
            .precision(coil.size.Precision.INEXACT)
            .scale(coil.size.Scale.FILL)
            .memoryCacheKey(cacheKey)
            .diskCacheKey(cacheKey)
            .crossfade(false)
            .listener(
                onError = { _, result ->
                    val t = result.throwable
                    Log.e(IMG_PERF_TAG, "Coil THUMB ERR: ...${urlShort} → " +
                        "${t.javaClass.simpleName}: ${t.message}")
                }
            )
            .build()
    }
}

private const val CHAT_SEND_MAX_IMAGE_EDGE_PX = 2048
private const val CHAT_SEND_JPEG_QUALITY = 90

private inline fun <T> withBitmapOnWhiteBackground(bitmap: Bitmap, block: (Bitmap) -> T): T {
    val w = bitmap.width
    val h = bitmap.height
    if (w <= 0 || h <= 0) return block(bitmap)
    val flat = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888)
    return try {
        val canvas = Canvas(flat)
        canvas.drawColor(Color.WHITE)
        canvas.drawBitmap(bitmap, 0f, 0f, null)
        block(flat)
    } finally {
        flat.recycle()
    }
}

internal fun resizeBitmapForChatSend(bitmap: Bitmap): Bitmap {
    val srcW = bitmap.width
    val srcH = bitmap.height
    if (srcW <= 0 || srcH <= 0) return bitmap
    val longEdge = max(srcW, srcH)
    if (longEdge <= CHAT_SEND_MAX_IMAGE_EDGE_PX) return bitmap
    val scale = CHAT_SEND_MAX_IMAGE_EDGE_PX.toFloat() / longEdge.toFloat()
    val dstW = (srcW * scale).toInt().coerceAtLeast(1)
    val dstH = (srcH * scale).toInt().coerceAtLeast(1)
    return Bitmap.createScaledBitmap(bitmap, dstW, dstH, true)
}

internal fun bitmapToChatDataUrl(bitmap: Bitmap): String {
    val out = ByteArrayOutputStream()
    withBitmapOnWhiteBackground(bitmap) { flat ->
        flat.compress(Bitmap.CompressFormat.JPEG, CHAT_SEND_JPEG_QUALITY, out)
    }
    val b64 = Base64.encodeToString(out.toByteArray(), Base64.NO_WRAP)
    return "data:image/jpeg;base64,$b64"
}

/** 与发消息/上传共用同一套压缩参数，供 multipart 上传使用 */
internal fun bitmapToJpegBytesForUpload(bitmap: Bitmap): ByteArray {
    val out = ByteArrayOutputStream()
    withBitmapOnWhiteBackground(bitmap) { flat ->
        flat.compress(Bitmap.CompressFormat.JPEG, CHAT_SEND_JPEG_QUALITY, out)
    }
    return out.toByteArray()
}

/**
 * 从相册 URI 读取图片并缩放到长边 <= [CHAT_SEND_MAX_IMAGE_EDGE_PX]。
 * 调用方负责在适当时机 [Bitmap.recycle]（若与入参非同一对象）。
 *
 * 关键修复：inJustDecodeBounds=true 时 BitmapFactory.decodeStream 始终返回 null，
 * 这是 Android API 的正常行为，不能用 `?: return null` 来判断流是否打开成功。
 * 改为独立的 streamOpened 标记来区分"打不开流"和"成功读完 bounds"。
 */
internal fun decodeBitmapForChatSendFromUri(context: Context, uri: Uri): Bitmap? {
    val resolver = context.contentResolver

    val boundOpt = BitmapFactory.Options().apply { inJustDecodeBounds = true }
    val streamOpened = resolver.openInputStream(uri)?.use { stream ->
        BitmapFactory.decodeStream(stream, null, boundOpt)
        true
    } ?: false
    if (!streamOpened) return null

    val srcW = boundOpt.outWidth
    val srcH = boundOpt.outHeight

    if (srcW <= 0 || srcH <= 0) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            return runCatching {
                val source = ImageDecoder.createSource(resolver, uri)
                val decoded = ImageDecoder.decodeBitmap(source) { decoder, info, _ ->
                    val longEdge = max(info.size.width, info.size.height)
                    if (longEdge > CHAT_SEND_MAX_IMAGE_EDGE_PX * 2) {
                        decoder.setTargetSampleSize(longEdge / (CHAT_SEND_MAX_IMAGE_EDGE_PX * 2))
                    }
                    decoder.allocator = ImageDecoder.ALLOCATOR_SOFTWARE
                }
                val resized = resizeBitmapForChatSend(decoded)
                if (resized !== decoded) decoded.recycle()
                resized
            }.getOrNull()
        }
        return null
    }

    val maxEdge = max(srcW, srcH)
    var sample = 1
    while (maxEdge / sample > CHAT_SEND_MAX_IMAGE_EDGE_PX * 2) sample *= 2

    val decodeOpt = BitmapFactory.Options().apply {
        inSampleSize = sample
        inPreferredConfig = Bitmap.Config.ARGB_8888
    }
    val decoded = resolver.openInputStream(uri)?.use { stream ->
        BitmapFactory.decodeStream(stream, null, decodeOpt)
    } ?: return null

    val resized = resizeBitmapForChatSend(decoded)
    if (resized !== decoded) decoded.recycle()
    return resized
}

/**
 * 从相册 URI 读取图片，压缩到长边 <= [CHAT_SEND_MAX_IMAGE_EDGE_PX]，返回 data URL（旧路径兼容）。
 */
internal fun loadChatImageDataUrlFromUri(context: Context, uri: Uri): String? {
    val resized = decodeBitmapForChatSendFromUri(context, uri) ?: return null
    return try {
        val dataUrl = bitmapToChatDataUrl(resized)
        dataUrl
    } finally {
        resized.recycle()
    }
}

internal suspend fun savePreviewImageToGallery(
    context: Context,
    imageUrl: String
): Boolean = withContext(Dispatchers.IO) {
    try {
        if (imageUrl.isBlank()) return@withContext false
        loadOriginalPreviewBytes(context, imageUrl)?.let { original ->
            return@withContext saveImageBytesToGallery(
                context = context,
                bytes = original.bytes,
                mimeType = original.mimeType,
                extension = original.extension
            )
        }

        val request = ImageRequest.Builder(context)
            .data(imageModelForCoil(imageUrl, context))
            .allowHardware(false)
            .build()
        val result = context.imageLoader.execute(request)
        val drawable = result.drawable ?: return@withContext false
        val bitmap = drawable.toBitmap(config = Bitmap.Config.ARGB_8888)
        val fileName = "PonyChat_${System.currentTimeMillis()}.jpg"

        val resolver = context.contentResolver
        val values = ContentValues().apply {
            put(MediaStore.Images.Media.DISPLAY_NAME, fileName)
            put(MediaStore.Images.Media.MIME_TYPE, "image/jpeg")
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                put(
                    MediaStore.Images.Media.RELATIVE_PATH,
                    "${Environment.DIRECTORY_PICTURES}/PonyChat"
                )
                put(MediaStore.Images.Media.IS_PENDING, 1)
            }
        }
        val uri = resolver.insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values)
            ?: return@withContext false

        val ok = resolver.openOutputStream(uri)?.use { out ->
            withBitmapOnWhiteBackground(bitmap) { flat ->
                flat.compress(Bitmap.CompressFormat.JPEG, 95, out)
            }
        } == true

        if (!ok) {
            resolver.delete(uri, null, null)
            return@withContext false
        }

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            val done = ContentValues().apply {
                put(MediaStore.Images.Media.IS_PENDING, 0)
            }
            resolver.update(uri, done, null, null)
        }
        true
    } catch (_: Exception) {
        false
    }
}

internal data class OriginalImageBytes(
    val bytes: ByteArray,
    val mimeType: String,
    val extension: String,
)

private fun imageMimeAndExtension(mimeType: String?): Pair<String, String> {
    val normalized = (mimeType ?: "").substringBefore(";").trim().lowercase()
    return when (normalized) {
        "image/gif" -> "image/gif" to "gif"
        "image/webp" -> "image/webp" to "webp"
        "image/png", "image/apng" -> normalized.ifBlank { "image/png" } to "png"
        "image/jpeg", "image/jpg" -> "image/jpeg" to "jpg"
        else -> "image/jpeg" to "jpg"
    }
}

private fun imageMimeAndExtensionFromFile(file: File): Pair<String, String> {
    return when (file.extension.lowercase()) {
        "png" -> "image/png" to "png"
        "webp" -> "image/webp" to "webp"
        "gif" -> "image/gif" to "gif"
        else -> "image/jpeg" to "jpg"
    }
}

private fun absoluteImageUrl(context: Context, imageUrl: String): String {
    return if (imageUrl.startsWith("/")) {
        AppPreferences(context).effectiveApiBase().trimEnd('/') + imageUrl
    } else {
        imageUrl
    }
}

internal fun loadOriginalPreviewBytes(context: Context, imageUrl: String): OriginalImageBytes? {
    if (imageUrl.startsWith("data:image/", ignoreCase = true)) {
        val header = imageUrl.substringBefore(",", "")
        val body = imageUrl.substringAfter(",", "")
        if (body.isBlank()) return null
        val mime = header.substringAfter("data:", "").substringBefore(";")
        val (safeMime, ext) = imageMimeAndExtension(mime)
        val bytes = Base64.decode(body, Base64.DEFAULT)
        return OriginalImageBytes(bytes, safeMime, ext)
    }

    localChatImageFile(imageUrl)?.let { file ->
        if (!file.exists() || file.length() <= 0L) return null
        val (mime, ext) = imageMimeAndExtensionFromFile(file)
        return OriginalImageBytes(file.readBytes(), mime, ext)
    }

    if (imageUrl.startsWith("/chat_images/")) {
        val file = localForRemoteChatImage(context, imageUrl) ?: return null
        val (mime, ext) = imageMimeAndExtensionFromFile(file)
        return OriginalImageBytes(file.readBytes(), mime, ext)
    }

    val url = absoluteImageUrl(context, imageUrl)
    if (!url.startsWith("http://") && !url.startsWith("https://")) return null
    val request = Request.Builder().url(url).get().build()
    NetworkClient.okHttpClient.newCall(request).execute().use { response ->
        if (!response.isSuccessful) return null
        val body = response.body ?: return null
        val bytes = body.bytes()
        if (bytes.isEmpty()) return null
        val (mime, ext) = imageMimeAndExtension(body.contentType()?.toString())
        return OriginalImageBytes(bytes, mime, ext)
    }
}

private fun saveImageBytesToGallery(
    context: Context,
    bytes: ByteArray,
    mimeType: String,
    extension: String,
): Boolean {
    val resolver = context.contentResolver
    val fileName = "PonyChat_${System.currentTimeMillis()}.$extension"
    val values = ContentValues().apply {
        put(MediaStore.Images.Media.DISPLAY_NAME, fileName)
        put(MediaStore.Images.Media.MIME_TYPE, mimeType)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            put(MediaStore.Images.Media.RELATIVE_PATH, "${Environment.DIRECTORY_PICTURES}/PonyChat")
            put(MediaStore.Images.Media.IS_PENDING, 1)
        }
    }
    val uri = resolver.insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values) ?: return false
    val ok = resolver.openOutputStream(uri)?.use { out ->
        out.write(bytes)
        true
    } == true
    if (!ok) {
        resolver.delete(uri, null, null)
        return false
    }
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
        resolver.update(
            uri,
            ContentValues().apply { put(MediaStore.Images.Media.IS_PENDING, 0) },
            null,
            null,
        )
    }
    return true
}

/** 全尺寸拍照（TakePicture）日志标签 */
private const val CHAT_CAMERA_TAG = "ChatCamera"

/**
 * 为 [androidx.activity.result.contract.ActivityResultContracts.TakePicture] 创建全尺寸输出 [Uri]。
 *
 * 这里使用 FileProvider 指向 App 私有外部 Pictures 目录，而不是直接把相机写入 MediaStore。
 * 原因：部分系统相机对 MediaStore pending Uri 写入不稳定，可能导致回调失败或生成空文件。
 * 拍照成功后再由 [markPonyChatCameraImageReady] 复制到系统相册 `Pictures/PonyChat/`。
 */
internal fun createPonyChatCameraImageUriForTakePicture(context: Context): Uri? {
    val name = "PonyChat_${SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(Date())}.jpg"
    return try {
        val dir = File(context.getExternalFilesDir(Environment.DIRECTORY_PICTURES), "camera_capture")
        if (!dir.exists()) dir.mkdirs()
        val file = File(dir, name)
        FileProvider.getUriForFile(context, "${context.packageName}.fileprovider", file)
    } catch (e: Exception) {
        Log.w(CHAT_CAMERA_TAG, "createCameraUri: ${e.message}")
        null
    }
}

/** 将已拍好的 FileProvider 全尺寸照片复制到系统相册。 */
internal fun markPonyChatCameraImageReady(context: Context, uri: Uri) {
    try {
        val name = "PonyChat_${SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(Date())}.jpg"
        val resolver = context.contentResolver
        val values = ContentValues().apply {
            put(MediaStore.Images.Media.DISPLAY_NAME, name)
            put(MediaStore.Images.Media.MIME_TYPE, "image/jpeg")
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                put(
                    MediaStore.Images.Media.RELATIVE_PATH,
                    "${Environment.DIRECTORY_PICTURES}/PonyChat"
                )
                put(MediaStore.Images.Media.IS_PENDING, 1)
            }
        }
        val galleryUri = resolver.insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values)
            ?: return
        val ok = resolver.openInputStream(uri)?.use { input ->
            resolver.openOutputStream(galleryUri)?.use { output ->
                input.copyTo(output)
            }
        } != null
        if (!ok) {
            resolver.delete(galleryUri, null, null)
            return
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            val done = ContentValues().apply { put(MediaStore.Images.Media.IS_PENDING, 0) }
            resolver.update(galleryUri, done, null, null)
        }
    } catch (e: Exception) {
        Log.w(CHAT_CAMERA_TAG, "markReady: ${e.message}")
    }
}

/** 用户取消拍照或需要丢弃临时文件时删除 FileProvider 背后的文件。 */
internal fun deletePonyChatCameraImage(context: Context, uri: Uri) {
    try {
        context.contentResolver.delete(uri, null, null)
    } catch (e: Exception) {
        Log.w(CHAT_CAMERA_TAG, "delete: ${e.message}")
    }
}

// 预编译正则，避免每次调用 splitMessageMedia 都重新编译（原因：Regex() 本身是 O(pattern) 的编译过程）
private val _MD_IMAGE_REGEX       = Regex("!\\[[^\\]]*\\]\\(([^)]+)\\)")
private val _DATA_IMAGE_REGEX     = Regex("data:image/[a-zA-Z0-9.+-]+;base64,[A-Za-z0-9+/=]+")
private val _CHAT_IMAGE_URL_REGEX = Regex("/chat_images/[\\w.-]+")
private val _LOCAL_FILE_IMAGE_REGEX = Regex("file://[^\\s)]+/chat_images/[^\\s)]+")

internal fun splitMessageMedia(content: String, context: Context? = null): MessageMedia {
    val len  = content.length
    val hash = content.hashCode()
    val key  = contentCacheKey(len, hash)
    val cacheable = !content.contains("/chat_images/")

    if (cacheable) {
        _mediaCache.get(key)?.let { return it }
    }

    fun cache(m: MessageMedia): MessageMedia {
        if (cacheable) _mediaCache.put(key, m)
        return m
    }

    if (!content.contains("data:image/") && !content.contains("![") && !content.contains("/chat_images/") && !content.contains("file://")) {
        return cache(MessageMedia(imageUrls = emptyList(), text = content))
    }
    if (content.startsWith("data:image/") && !content.contains('\n') && len > 20) {
        return cache(MessageMedia(imageUrls = listOf(content), text = ""))
    }
    if (content.startsWith("/chat_images/") && !content.contains('\n')) {
        return if (isMissingLocalChatImageForDisplay(context, content)) {
            cache(MessageMedia(imageUrls = emptyList(), text = "【图片】"))
        } else {
            cache(MessageMedia(imageUrls = listOf(content), text = ""))
        }
    }
    val mdImages       = _MD_IMAGE_REGEX.findAll(content)
        .map { it.groupValues[1].trim() }.filter { it.isNotBlank() }.toList()
    val dataImages     = _DATA_IMAGE_REGEX.findAll(content).map { it.value }.toList()
    val localFileUrls  = _LOCAL_FILE_IMAGE_REGEX.findAll(content).map { it.value }.toList()
    val looseContent = content
        .replace(_MD_IMAGE_REGEX, "")
        .replace(_DATA_IMAGE_REGEX, "")
        .replace(_LOCAL_FILE_IMAGE_REGEX, "")
    val chatImageUrls  = _CHAT_IMAGE_URL_REGEX.findAll(looseContent).map { it.value }.toList()
    var missingLocalCount = 0
    val imageUrls = (mdImages + dataImages + chatImageUrls + localFileUrls)
        .distinct()
        .filter { url ->
            if (isMissingLocalChatImageForDisplay(context, url)) {
                missingLocalCount += 1
                false
            } else {
                true
            }
        }
    val baseText = content
        .replace(_MD_IMAGE_REGEX, "")
        .replace(_DATA_IMAGE_REGEX, "")
        .replace(_LOCAL_FILE_IMAGE_REGEX, "")
        .replace(_CHAT_IMAGE_URL_REGEX, "")
        .trim()
    val text = if (missingLocalCount > 0) {
        (listOf(baseText).filter { it.isNotBlank() } + List(missingLocalCount) { "【图片】" })
            .joinToString("\n")
    } else {
        baseText
    }
    return cache(MessageMedia(imageUrls = imageUrls, text = text))
}

internal fun splitUserMessageMedia(content: String, context: Context? = null): MessageMedia {
    return splitMessageMedia(content, context)
}
