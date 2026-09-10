package top.ponychat.webview.ui.chat

import android.content.Context
import android.graphics.BitmapFactory
import android.net.Uri
import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import top.ponychat.webview.data.model.Message
import top.ponychat.webview.data.model.MessageAttachment
import java.io.File

internal fun buildImageMessageContent(text: String, imageUrls: List<String>): String {
    return buildString {
        if (text.isNotBlank()) {
            append(text)
            append("\n\n")
        }
        imageUrls.forEach { url ->
            append("![](")
            append(url)
            append(")\n")
        }
    }.trim()
}

private val chatImageMarkdownRegex = Regex("!\\[[^\\]]*\\]\\(([^)]+)\\)")

internal fun chatImageUrlsInContent(content: String): List<String> =
    chatImageMarkdownRegex.findAll(content)
        .mapNotNull { it.groupValues.getOrNull(1)?.trim()?.takeIf(String::isNotBlank) }
        .toList()

internal fun chatImageNeedsUpload(url: String): Boolean =
    !url.startsWith("/chat_images/") &&
        !url.startsWith("http://", ignoreCase = true) &&
        !url.startsWith("https://", ignoreCase = true) &&
        !url.startsWith("data:image/", ignoreCase = true)

internal suspend fun uploadPendingChatImages(
    context: Context,
    viewModel: ChatViewModel,
    imageUrls: List<String>,
    showErrors: Boolean = true,
    showPrompt: (String) -> Unit,
): List<String>? {
    val uploaded = mutableListOf<String>()
    for (url in imageUrls) {
        if (
            url.startsWith("/chat_images/") ||
            url.startsWith("http://", ignoreCase = true) ||
            url.startsWith("https://", ignoreCase = true) ||
            url.startsWith("data:image/", ignoreCase = true)
        ) {
            uploaded += url
            continue
        }
        val bytes = withContext(Dispatchers.IO) {
            loadChatImageBytesForUpload(context, url)
        }
        if (bytes == null || bytes.isEmpty()) {
            if (showErrors) showPrompt("读取图片失败，未发送")
            return null
        }
        val remoteUrl = viewModel.uploadChatImageForMessage(bytes).getOrElse { err ->
            Log.w("ChatScreen", "Chat image upload failed: ${err.message}", err)
            if (showErrors) showPrompt(err.message ?: "图片上传失败，请稍后重试")
            return null
        }
        rememberLocalChatImageRemote(context, url, remoteUrl)
        uploaded += remoteUrl
    }
    return uploaded
}

internal fun copyPickedStickerToCache(context: Context, uri: Uri): File? = runCatching {
    val ext = when (context.contentResolver.getType(uri)?.lowercase()) {
        "image/jpeg", "image/jpg" -> "jpg"
        "image/gif" -> "gif"
        "image/webp" -> "webp"
        else -> "png"
    }
    val file = File(context.cacheDir, "sticker_${System.currentTimeMillis()}.$ext")
    context.contentResolver.openInputStream(uri)?.use { input ->
        file.outputStream().use { output -> input.copyTo(output) }
    } ?: return@runCatching null
    file
}.getOrNull()

internal fun validateStickerAspectRatio(context: Context, uri: Uri): String? = runCatching {
    val opts = BitmapFactory.Options().apply { inJustDecodeBounds = true }
    context.contentResolver.openInputStream(uri)?.use { input ->
        BitmapFactory.decodeStream(input, null, opts)
    }
    val w = opts.outWidth
    val h = opts.outHeight
    if (w <= 0 || h <= 0) return@runCatching "无法读取图片尺寸"
    val ratio = w.toFloat() / h.toFloat()
    if (ratio < 0.5f || ratio > 2.0f) {
        "图片长宽比 ${"%.2f".format(ratio)} 超出允许范围（0.5-2.0），请裁剪后重新上传"
    } else {
        null
    }
}.getOrElse { "无法读取图片尺寸" }

internal fun stickerPreviewUrl(att: MessageAttachment): String? =
    att.url ?: att.assetId?.let { "/api/admin/assets/$it/file" }
        ?: att.userStickerId?.let { "/api/assets/stickers/$it/file" }

internal fun messagePreviewImages(context: Context, messages: List<Message>): List<String> =
    messages.flatMap { message ->
        val media = if (message.isUser()) {
            splitUserMessageMedia(message.content, context)
        } else {
            splitMessageMedia(message.content, context)
        }
        media.imageUrls + message.attachments.mapNotNull(::stickerPreviewUrl)
    }.map { localUrlForRemoteChatImage(context, it) ?: it }.distinct()

internal fun plainTextForMessage(msg: Message, mode: String): String {
    val fallback = when {
        msg.isUser() -> msg.content
        mode.startsWith("galgame") && msg.isAssistant() ->
            stripHtml(msg.displayContent?.trim()?.takeIf { it.isNotBlank() } ?: msg.content)
        else -> parseMessageContent(msg.content).mainContent.ifBlank { msg.content }
    }
    return msg.voiceState
        ?.readableText(fallback)
        ?.takeIf { it.isNotBlank() }
        ?: fallback
}
