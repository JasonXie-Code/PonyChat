package top.ponychat.webview.ui.chat

import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.LinearGradient
import android.graphics.Paint
import android.graphics.Path
import android.graphics.PorterDuff
import android.graphics.PorterDuffXfermode
import android.graphics.Rect
import android.graphics.RectF
import android.graphics.Shader
import android.graphics.Typeface
import android.graphics.drawable.BitmapDrawable
import android.graphics.drawable.Drawable
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import android.text.Layout
import android.text.StaticLayout
import android.text.TextPaint
import coil.ImageLoader
import coil.request.ImageRequest
import coil.request.SuccessResult
import coil.size.Size
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import top.ponychat.webview.data.api.NetworkClient
import top.ponychat.webview.data.model.Character
import top.ponychat.webview.data.model.Message
import top.ponychat.webview.data.model.MessageAttachment
import top.ponychat.webview.ui.common.resolveAvatarUrlForApi
import java.io.File
import java.io.FileOutputStream
import kotlin.math.ceil
import kotlin.math.pow

/**
 * 基于 Android Canvas 将选中消息渲染为可分享的 Bitmap。
 * 设计风格与 App 内气泡一致：用户消息右对齐渐变蓝气泡 / 角色消息左对齐灰气泡 + 头像。
 * 末尾带 Outfit Bold 品牌水印。
 */
class ChatExportEngine(private val context: Context) {

    // ── 画布常量（以 3× 缩放模拟 xxhdpi 1080px 宽） ──
    private val CANVAS_W = 1080
    private val SCALE = 3f
    private fun dp(v: Float) = v * SCALE

    private val hPad       = dp(16f)
    private val topPad     = dp(24f)
    private val botPad     = dp(56f)   // watermark 留白
    private val avatarSz   = dp(40f)
    private val avGap      = dp(8f)
    private val bHPad      = dp(14f)
    private val bVPad      = dp(10f)
    private val msgGap     = dp(14f)
    private val nameH      = dp(15f)   // 名字标签高度
    private val nameGap    = dp(4f)    // 名字与气泡间距
    private val voiceBubbleH = dp(44f)
    private val voiceCardGap = dp(6f)
    private val voiceCardHPad = dp(12f)
    private val voiceCardVPad = dp(8f)
    private val voiceLabelGap = dp(2f)
    private val imageGap = dp(6f)
    private val imageGridMaxW = dp(360f * 0.94f - 96f)
    private val imageGridTile = (imageGridMaxW - imageGap) / 2f
    private val stickerMaxSide = dp(100f)
    private val imageCornerR = dp(12f)
    // 气泡限制在两侧头像列之间：左边 hPad+avatarSz+avGap，右边对称，再减去气泡内左右 padding
    private val avatarColW = hPad + avatarSz + avGap   // 单侧头像列宽
    private val maxBubbleW = CANVAS_W - 2 * avatarColW - 2 * bHPad
    private val maxVoiceBubbleW = maxBubbleW + bHPad * 2
    private val cornerR    = dp(16f)
    private val cornerSharp = dp(4f)
    private val voiceDurationMinMs = 1_000L
    private val voiceDurationMaxSeconds = 60
    private val voiceDurationMaxMs = voiceDurationMaxSeconds * 1_000L

    // 使用 NetworkClient.okHttpClient（含 auth 拦截器），确保头像 URL 带 token 能正常加载
    private val authImageLoader: ImageLoader by lazy {
        ImageLoader.Builder(context)
            .okHttpClient(NetworkClient.okHttpClient)
            .crossfade(false)
            .build()
    }

    // ── 颜色 ──
    private val C_BG       = Color.parseColor("#F8F9FA")
    private val C_AI_BG    = Color.parseColor("#EEEEF5")
    private val C_USER1    = Color.parseColor("#6366F1")
    private val C_USER2    = Color.parseColor("#4F46E5")
    private val C_TEXT     = Color.parseColor("#1F2937")
    private val C_WHITE    = Color.WHITE
    private val C_MUTED    = Color.parseColor("#9CA3AF")
    private val C_RETRACT  = Color.parseColor("#B0B0B0")
    private val C_AV_FB    = Color.parseColor("#818CF8")  // avatar fallback
    private val C_VOICE    = Color.parseColor("#14B8A6")
    private val C_VOICE_AI_BG = Color.parseColor("#E7F4F2")
    private val C_VOICE_CARD_BG = Color.parseColor("#F0F2F7")

    // ── Paint ──
    private val bgPaint = Paint().apply { color = C_BG; style = Paint.Style.FILL }
    private val aiBgPaint = Paint().apply { isAntiAlias = true; color = C_AI_BG; style = Paint.Style.FILL }
    private val avFbPaint = Paint().apply { isAntiAlias = true; color = C_AV_FB; style = Paint.Style.FILL }
    private val avTextPaint = TextPaint(Paint.ANTI_ALIAS_FLAG).apply {
        color = C_WHITE; textSize = dp(14f); textAlign = Paint.Align.CENTER
    }
    private val aiTextPaint  = TextPaint(Paint.ANTI_ALIAS_FLAG).apply { color = C_TEXT;    textSize = dp(14f) }
    private val userTextPaint = TextPaint(Paint.ANTI_ALIAS_FLAG).apply { color = C_WHITE;   textSize = dp(14f) }
    private val retractPaint  = TextPaint(Paint.ANTI_ALIAS_FLAG).apply { color = C_RETRACT; textSize = dp(13f); textSkewX = -0.25f }
    private val namePaint     = TextPaint(Paint.ANTI_ALIAS_FLAG).apply { color = C_MUTED;   textSize = dp(11f) }
    private val timePaint     = TextPaint(Paint.ANTI_ALIAS_FLAG).apply { color = C_MUTED;   textSize = dp(11f) }
    private val voiceLabelPaint = TextPaint(Paint.ANTI_ALIAS_FLAG).apply {
        color = C_VOICE
        textSize = dp(11f)
        typeface = Typeface.DEFAULT_BOLD
    }
    private val voiceTranscriptPaint = TextPaint(Paint.ANTI_ALIAS_FLAG).apply { color = C_TEXT; textSize = dp(13f) }
    private val voiceDurationPaint = TextPaint(Paint.ANTI_ALIAS_FLAG).apply {
        color = C_MUTED
        textSize = dp(15f)
        typeface = Typeface.DEFAULT_BOLD
        textAlign = Paint.Align.RIGHT
    }
    private val imagePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        isFilterBitmap = true
        isDither = true
    }
    private val imagePlaceholderPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#D8DCE6")
        style = Paint.Style.FILL
    }
    private val imagePlaceholderTextPaint = TextPaint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#6B7280")
        textSize = dp(12f)
        textAlign = Paint.Align.CENTER
        typeface = Typeface.DEFAULT_BOLD
    }
    private val imageOverlayPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.argb(130, 0, 0, 0)
        style = Paint.Style.FILL
    }
    private val imageOverlayTextPaint = TextPaint(Paint.ANTI_ALIAS_FLAG).apply {
        color = C_WHITE
        textSize = dp(22f)
        textAlign = Paint.Align.CENTER
        typeface = Typeface.DEFAULT_BOLD
    }

    // ── Outfit Bold 水印字体 ──
    private val outfitTypeface: Typeface by lazy {
        try { Typeface.createFromAsset(context.assets, "fonts/outfit-700.ttf") }
        catch (_: Exception) { Typeface.DEFAULT_BOLD }
    }
    private val watermarkPaint = TextPaint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#BEBEBE"); textSize = dp(15f); textAlign = Paint.Align.CENTER
    }

    private data class ExportBubbleInfo(
        val msg: Message,
        val layout: StaticLayout?,
        val bubbleW: Float,
        val bubbleH: Float,
        val showNameAndAvatar: Boolean,
        val speakerName: String? = null,
        val speakerAvatar: Bitmap? = null,
        val isVoice: Boolean = false,
        val durationMs: Long = 0L,
        val waveform: List<Float> = emptyList(),
        val transcriptLayout: StaticLayout? = null,
        val transcriptW: Float = 0f,
        val transcriptH: Float = 0f,
        val isImageGrid: Boolean = false,
        val imageKind: ExportImageKind = ExportImageKind.ChatImage,
        val imageBitmaps: List<Bitmap?> = emptyList(),
        val imageTotalCount: Int = 0,
    )

    private data class ExportSpeaker(
        val name: String,
        val avatarUrl: String
    )

    private enum class ExportImageKind {
        ChatImage,
        Sticker,
    }

    private data class ExportImageItem(
        val url: String,
    )

    private data class ExportImageGroup(
        val kind: ExportImageKind,
        val items: List<ExportImageItem>,
    )

    // ──────────────────────────────────────────────────────────────────────
    // PUBLIC API
    // ──────────────────────────────────────────────────────────────────────

    suspend fun generateBitmap(
        messages: List<Message>,
        character: Character,
        characterAvatarUrl: String,
        userAvatarUrl: String,
        userName: String,
        apiBase: String,
        allCharacters: List<Character> = emptyList()
    ): Bitmap = withContext(Dispatchers.IO) {
        watermarkPaint.typeface = outfitTypeface

        val charAv = loadAvatarCircle(characterAvatarUrl, apiBase)
        val userAv = loadAvatarCircle(userAvatarUrl, apiBase)
        val charactersById = allCharacters
            .mapNotNull { item -> item.id?.takeIf { it.isNotBlank() }?.let { it to item } }
            .toMap()
        val assistantAvatarCache = mutableMapOf<String, Bitmap?>()
        assistantAvatarCache[characterAvatarUrl] = charAv

        suspend fun loadAssistantAvatar(url: String): Bitmap? {
            if (url.isBlank()) return null
            if (assistantAvatarCache.containsKey(url)) return assistantAvatarCache[url]
            val bitmap = loadAvatarCircle(url, apiBase)
            assistantAvatarCache[url] = bitmap
            return bitmap
        }

        fun assistantSpeakerFor(msg: Message): ExportSpeaker {
            val speakerCharacter = msg.speakerCharacterId
                ?.takeIf { it.isNotBlank() }
                ?.let { charactersById[it] }
            return ExportSpeaker(
                name = msg.speakerName?.takeIf { it.isNotBlank() }
                    ?: speakerCharacter?.displayName()
                    ?: character.displayName(),
                avatarUrl = msg.speakerAvatar?.takeIf { it.isNotBlank() }
                    ?: speakerCharacter?.avatarUrl()
                    ?: characterAvatarUrl
            )
        }

        // 段落间距（同一条消息的相邻气泡）
        val paraGap = dp(6f)

        val bubbles = mutableListOf<ExportBubbleInfo>()
        for (msg in messages) {
            val avail = maxBubbleW.toInt().coerceAtLeast(200)
            val voiceState = msg.voiceState
            val textFallback = exportPlainText(msg)
            val media = if (msg.isUser()) {
                splitUserMessageMedia(textFallback, context)
            } else {
                splitMessageMedia(textFallback, context)
            }
            val imageGroups = messageExportImageGroups(msg, media)
            val speaker = if (msg.isAssistant()) assistantSpeakerFor(msg) else null
            val speakerAvatar = speaker?.let { loadAssistantAvatar(it.avatarUrl) }
            var hasLeadingMediaBlock = false
            fun addImageGroups() {
                var isFirstGroup = true
                imageGroups.forEach { group ->
                    bubbles.add(
                        buildImageGridBubble(
                            msg = msg,
                            group = group,
                            speakerName = speaker?.name,
                            speakerAvatar = speakerAvatar,
                            showNameAndAvatar = isFirstGroup,
                        )
                    )
                    isFirstGroup = false
                }
                if (imageGroups.isNotEmpty()) {
                    hasLeadingMediaBlock = true
                }
            }
            when {
                msg.isRetracted -> {
                    val layout = buildLayout("消息已撤回", retractPaint, avail)
                    val bW = measureContentWidth(layout).coerceAtMost(maxBubbleW) + bHPad * 2
                    val bH = layout.height.toFloat() + bVPad * 2
                    bubbles.add(
                        ExportBubbleInfo(
                            msg,
                            layout,
                            bW,
                            bH,
                            showNameAndAvatar = true,
                            speakerName = speaker?.name,
                            speakerAvatar = speakerAvatar,
                        )
                    )
                }
                voiceState != null -> {
                    addImageGroups()
                    val transcript = stripMarkdown(voiceState.readableText(textFallback))
                    val transcriptLayout = transcript.takeIf { it.isNotBlank() }?.let {
                        buildLayout(it, voiceTranscriptPaint, (maxVoiceBubbleW - voiceCardHPad * 2).toInt().coerceAtLeast(160))
                    }
                    val labelH = voiceLabelPaint.textSize + voiceLabelGap
                    val transcriptH = transcriptLayout?.let { voiceCardVPad * 2 + labelH + it.height.toFloat() } ?: 0f
                    val durationMs = estimatedExportVoiceDurationMs(transcript, voiceState.durationMs)
                    val durationSeconds = exportVoiceDurationSeconds(durationMs)
                    val durationProgress = (durationSeconds - 1) / (voiceDurationMaxSeconds - 1).toFloat()
                    val minVoiceW = dp(112f)
                    val voiceW = minVoiceW + (maxVoiceBubbleW - minVoiceW) * durationProgress
                    bubbles.add(
                        ExportBubbleInfo(
                            msg = msg,
                            layout = null,
                            bubbleW = voiceW,
                            bubbleH = voiceBubbleH,
                            showNameAndAvatar = !hasLeadingMediaBlock,
                            speakerName = speaker?.name,
                            speakerAvatar = speakerAvatar,
                            isVoice = true,
                            durationMs = durationMs,
                            waveform = voiceState.waveform,
                            transcriptLayout = transcriptLayout,
                            transcriptW = if (transcriptLayout != null) maxVoiceBubbleW else 0f,
                            transcriptH = transcriptH,
                        )
                    )
                }
                msg.isUser() -> {
                    addImageGroups()
                    val text = stripMarkdown(media.text.ifBlank { if (imageGroups.isEmpty()) textFallback else "" })
                    if (text.isNotBlank()) {
                        val layout = buildLayout(text, userTextPaint, avail)
                        val bW = measureContentWidth(layout).coerceAtMost(maxBubbleW) + bHPad * 2
                        val bH = layout.height.toFloat() + bVPad * 2
                        bubbles.add(ExportBubbleInfo(msg, layout, bW, bH, showNameAndAvatar = !hasLeadingMediaBlock))
                    }
                }
                else -> {
                    addImageGroups()
                    // AI 消息：按 \n\n+（两个及以上换行）分段，每段独立气泡
                    val fullText = stripMarkdown(media.text.ifBlank { if (imageGroups.isEmpty()) textFallback else "" })
                    val paragraphs = fullText.split(Regex("\\n{2,}"))
                        .map { it.trim() }.filter { it.isNotBlank() }
                    var isFirstAdded = true
                    paragraphs.forEach { para ->
                        val layout = buildLayout(para, aiTextPaint, avail)
                        val bW = measureContentWidth(layout).coerceAtMost(maxBubbleW) + bHPad * 2
                        val bH = layout.height.toFloat() + bVPad * 2
                        bubbles.add(
                            ExportBubbleInfo(
                                msg,
                                layout,
                                bW,
                                bH,
                                showNameAndAvatar = isFirstAdded && !hasLeadingMediaBlock,
                                speakerName = speaker?.name,
                                speakerAvatar = speakerAvatar,
                            )
                        )
                        isFirstAdded = false
                    }
                }
            }
        }

        // 每个气泡占用的纵向高度
        fun bubbleContentH(b: ExportBubbleInfo): Float =
            when {
                b.isVoice && b.transcriptLayout != null -> b.bubbleH + voiceCardGap + b.transcriptH
                else -> b.bubbleH
            }

        fun bubbleRowH(b: ExportBubbleInfo): Float =
            if (b.showNameAndAvatar) nameH + nameGap + maxOf(bubbleContentH(b), avatarSz)
            else bubbleContentH(b)

        // 相邻气泡之间的间距：同消息连续段 → paraGap；否则 → msgGap
        val gaps = bubbles.indices.map { i ->
            if (i == bubbles.lastIndex) 0f
            else if (!bubbles[i + 1].showNameAndAvatar) paraGap
            else msgGap
        }

        val totalH = (topPad + bubbles.mapIndexed { i, b -> bubbleRowH(b) + gaps[i] }.sum() + botPad).toInt()
        val bitmap = Bitmap.createBitmap(CANVAS_W, totalH, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(bitmap)
        canvas.drawRect(0f, 0f, CANVAS_W.toFloat(), totalH.toFloat(), bgPaint)

        var y = topPad
        for ((i, bubble) in bubbles.withIndex()) {
            if (bubble.isImageGrid) {
                if (bubble.msg.isUser()) {
                    drawUserImageRow(canvas, bubble, y, userAv, userName)
                } else {
                    drawAiImageRow(
                        canvas,
                        bubble,
                        y,
                        bubble.speakerAvatar ?: charAv,
                        bubble.speakerName ?: character.displayName()
                    )
                }
            } else if (bubble.isVoice) {
                if (bubble.msg.isUser()) {
                    drawUserVoiceRow(canvas, bubble, y, userAv, userName)
                } else {
                    drawAiVoiceRow(
                        canvas,
                        bubble,
                        y,
                        bubble.speakerAvatar ?: charAv,
                        bubble.speakerName ?: character.displayName()
                    )
                }
            } else if (bubble.msg.isUser()) {
                drawUserRow(
                    canvas,
                    bubble.layout!!,
                    bubble.bubbleW,
                    bubble.bubbleH,
                    y,
                    userAv,
                    userName,
                    bubble.showNameAndAvatar
                )
            } else {
                drawAiRow(
                    canvas,
                    bubble.layout!!,
                    bubble.bubbleW,
                    bubble.bubbleH,
                    y,
                    bubble.speakerAvatar ?: charAv,
                    bubble.speakerName ?: character.displayName(),
                    bubble.showNameAndAvatar
                )
            }
            y += bubbleRowH(bubble) + gaps[i]
        }

        // 水印
        canvas.drawText("PonyChat.org", CANVAS_W / 2f, totalH - dp(18f), watermarkPaint)
        bitmap
    }

    private fun buildImageGridBubble(
        msg: Message,
        group: ExportImageGroup,
        speakerName: String?,
        speakerAvatar: Bitmap?,
        showNameAndAvatar: Boolean,
    ): ExportBubbleInfo {
        val displayItems = group.items.take(4)
        val bitmaps = displayItems.map { loadExportImageBitmap(it.url, group.kind) }
        val (gridW, gridH) = measureImageGrid(group.kind, bitmaps, group.items.size)
        return ExportBubbleInfo(
            msg = msg,
            layout = null,
            bubbleW = gridW,
            bubbleH = gridH,
            showNameAndAvatar = showNameAndAvatar,
            speakerName = speakerName,
            speakerAvatar = speakerAvatar,
            isImageGrid = true,
            imageKind = group.kind,
            imageBitmaps = bitmaps,
            imageTotalCount = group.items.size,
        )
    }

    private fun messageExportImageGroups(msg: Message, media: MessageMedia): List<ExportImageGroup> {
        val stickerUrls = msg.attachments
            .filter { it.isStickerExportAttachment() }
            .mapNotNull { it.exportPreviewUrl()?.takeIf { url -> url.isNotBlank() } }
            .distinct()
        val stickerUrlSet = stickerUrls.toSet()
        val imageUrls = (media.imageUrls + msg.attachments
            .filterNot { it.isStickerExportAttachment() }
            .mapNotNull { it.exportPreviewUrl() })
            .filter { it.isNotBlank() && it !in stickerUrlSet }
            .distinct()

        return buildList {
            if (imageUrls.isNotEmpty()) {
                add(ExportImageGroup(ExportImageKind.ChatImage, imageUrls.map { ExportImageItem(it) }))
            }
            if (stickerUrls.isNotEmpty()) {
                add(ExportImageGroup(ExportImageKind.Sticker, stickerUrls.map { ExportImageItem(it) }))
            }
        }
    }

    private fun MessageAttachment.exportPreviewUrl(): String? =
        url ?: assetId?.let { "/api/admin/assets/$it/file" }
            ?: userStickerId?.let { "/api/assets/stickers/$it/file" }

    private fun MessageAttachment.isStickerExportAttachment(): Boolean =
        type == "sticker" || type == "emoji_asset"

    private fun measureImageGrid(
        kind: ExportImageKind,
        bitmaps: List<Bitmap?>,
        totalCount: Int,
    ): Pair<Float, Float> {
        val count = totalCount.coerceAtLeast(bitmaps.size).coerceAtLeast(1)
        if (kind == ExportImageKind.Sticker) {
            val shown = minOf(4, count)
            var maxW = 0f
            var totalH = 0f
            for (index in 0 until shown) {
                val (w, h) = measureStickerBitmap(bitmaps.getOrNull(index))
                maxW = maxOf(maxW, w)
                totalH += h
                if (index < shown - 1) totalH += imageGap
            }
            return maxW.coerceAtLeast(stickerMaxSide * 0.25f) to totalH.coerceAtLeast(stickerMaxSide * 0.25f)
        }
        if (count == 1) {
            return imageGridTile to imageGridTile
        }
        val shown = minOf(4, count)
        val rows = if (shown <= 2) 1 else 2
        return imageGridMaxW to (imageGridTile * rows + imageGap * (rows - 1))
    }

    private fun measureStickerBitmap(bitmap: Bitmap?): Pair<Float, Float> {
        val intrinsicW = bitmap?.width?.takeIf { it > 0 } ?: 1
        val intrinsicH = bitmap?.height?.takeIf { it > 0 } ?: 1
        val aspect = (intrinsicW.toFloat() / intrinsicH.toFloat()).coerceIn(0.25f, 4f)
        val width = if (aspect >= 1f) stickerMaxSide else stickerMaxSide * aspect
        val height = if (aspect >= 1f) stickerMaxSide / aspect else stickerMaxSide
        return width to height
    }

    private fun loadExportImageBitmap(imageUrl: String, kind: ExportImageKind): Bitmap? {
        return try {
            val original = loadOriginalPreviewBytes(context, imageUrl) ?: return null
            val reqSide = if (kind == ExportImageKind.Sticker) stickerMaxSide else imageGridTile
            decodeSampledBitmap(original.bytes, reqSide.toInt(), reqSide.toInt())
        } catch (_: Exception) {
            null
        }
    }

    private fun decodeSampledBitmap(bytes: ByteArray, reqW: Int, reqH: Int): Bitmap? {
        if (bytes.isEmpty()) return null
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeByteArray(bytes, 0, bytes.size, bounds)
        if (bounds.outWidth <= 0 || bounds.outHeight <= 0) return null
        val opts = BitmapFactory.Options().apply {
            inSampleSize = exportImageSampleSize(bounds.outWidth, bounds.outHeight, reqW, reqH)
            inPreferredConfig = Bitmap.Config.ARGB_8888
        }
        val decoded = BitmapFactory.decodeByteArray(bytes, 0, bytes.size, opts) ?: return null
        val maxEdge = maxOf(reqW, reqH).coerceAtLeast(1)
        val currentEdge = maxOf(decoded.width, decoded.height)
        if (currentEdge <= maxEdge) return decoded
        val scale = maxEdge.toFloat() / currentEdge.toFloat()
        val scaled = Bitmap.createScaledBitmap(
            decoded,
            (decoded.width * scale).toInt().coerceAtLeast(1),
            (decoded.height * scale).toInt().coerceAtLeast(1),
            true,
        )
        if (scaled !== decoded) decoded.recycle()
        return scaled
    }

    private fun exportImageSampleSize(srcW: Int, srcH: Int, reqW: Int, reqH: Int): Int {
        var sample = 1
        var halfW = srcW / 2
        var halfH = srcH / 2
        while (halfW / sample >= reqW && halfH / sample >= reqH) {
            sample *= 2
        }
        return sample.coerceAtLeast(1)
    }

    fun saveToPictures(bitmap: Bitmap): Uri? {
        val name = "PonyChat_${System.currentTimeMillis()}.png"
        return try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                val cv = ContentValues().apply {
                    put(MediaStore.Images.Media.DISPLAY_NAME, name)
                    put(MediaStore.Images.Media.MIME_TYPE, "image/png")
                    put(MediaStore.Images.Media.RELATIVE_PATH, Environment.DIRECTORY_PICTURES + "/PonyChat")
                    put(MediaStore.Images.Media.IS_PENDING, 1)
                }
                val uri = context.contentResolver.insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, cv) ?: return null
                context.contentResolver.openOutputStream(uri)?.use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }
                cv.clear(); cv.put(MediaStore.Images.Media.IS_PENDING, 0)
                context.contentResolver.update(uri, cv, null, null)
                uri
            } else {
                @Suppress("DEPRECATION")
                val dir = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_PICTURES).resolve("PonyChat")
                dir.mkdirs()
                val file = File(dir, name)
                FileOutputStream(file).use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }
                Uri.fromFile(file)
            }
        } catch (_: Exception) { null }
    }

    fun createShareIntent(uri: Uri): Intent = Intent(Intent.ACTION_SEND).apply {
        type = "image/png"
        putExtra(Intent.EXTRA_STREAM, uri)
        addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
    }

    // ──────────────────────────────────────────────────────────────────────
    // DRAWING HELPERS
    // ──────────────────────────────────────────────────────────────────────

    private fun drawAiRow(
        canvas: Canvas, layout: StaticLayout,
        bW: Float, bH: Float, rowY: Float,
        avBitmap: Bitmap?, charName: String,
        showNameAndAvatar: Boolean = true,
    ) {
        val bLeft = hPad + avatarSz + avGap

        if (showNameAndAvatar) {
            // 名字标签
            canvas.drawText(charName, bLeft, rowY + nameH, namePaint)
            // 头像（名字下方）
            val avTop = rowY + nameH + nameGap
            if (avBitmap != null) {
                canvas.drawBitmap(avBitmap, hPad, avTop, null)
            } else {
                canvas.drawCircle(hPad + avatarSz / 2, avTop + avatarSz / 2, avatarSz / 2, avFbPaint)
                val initial = charName.firstOrNull()?.toString() ?: "A"
                val ty = avTop + avatarSz / 2 - (avTextPaint.descent() + avTextPaint.ascent()) / 2
                canvas.drawText(initial, hPad + avatarSz / 2, ty, avTextPaint)
            }
            val bubbleY = rowY + nameH + nameGap
            drawRoundBubble(canvas, bLeft, bubbleY, bLeft + bW, bubbleY + bH, topLeftR = cornerSharp, paint = aiBgPaint)
            canvas.save()
            canvas.translate(bLeft + bHPad, bubbleY + bVPad)
            layout.draw(canvas)
            canvas.restore()
        } else {
            // 同消息后续段：不重复头像/名字，气泡直接从 rowY 开始，水平缩进与首段一致
            drawRoundBubble(canvas, bLeft, rowY, bLeft + bW, rowY + bH, topLeftR = cornerSharp, paint = aiBgPaint)
            canvas.save()
            canvas.translate(bLeft + bHPad, rowY + bVPad)
            layout.draw(canvas)
            canvas.restore()
        }
    }

    private fun drawUserRow(
        canvas: Canvas, layout: StaticLayout,
        bW: Float, bH: Float, rowY: Float,
        avBitmap: Bitmap?, userName: String,
        showNameAndAvatar: Boolean = true,
    ) {
        val avLeft  = CANVAS_W - hPad - avatarSz
        val bubbleY = if (showNameAndAvatar) rowY + nameH + nameGap else rowY
        val avTop   = bubbleY

        if (showNameAndAvatar) {
            // 名字标签（右对齐到头像左侧）
            namePaint.textAlign = Paint.Align.RIGHT
            canvas.drawText(userName, avLeft - avGap, rowY + nameH, namePaint)
            namePaint.textAlign = Paint.Align.LEFT

            // 用户头像（右侧）
            if (avBitmap != null) {
                canvas.drawBitmap(avBitmap, avLeft, avTop, null)
            } else {
                val userFbPaint = Paint().apply { isAntiAlias = true; color = C_USER1; style = Paint.Style.FILL }
                canvas.drawCircle(avLeft + avatarSz / 2, avTop + avatarSz / 2, avatarSz / 2, userFbPaint)
                val initial = userName.firstOrNull()?.toString() ?: "U"
                val ty = avTop + avatarSz / 2 - (avTextPaint.descent() + avTextPaint.ascent()) / 2
                canvas.drawText(initial, avLeft + avatarSz / 2, ty, avTextPaint)
            }
        }

        // 气泡（头像左侧）
        val bRight = avLeft - avGap
        val bLeft  = bRight - bW
        val gradPaint = Paint().apply {
            isAntiAlias = true; style = Paint.Style.FILL
            shader = LinearGradient(bLeft, 0f, bRight, 0f, C_USER1, C_USER2, Shader.TileMode.CLAMP)
        }
        drawRoundBubble(canvas, bLeft, bubbleY, bRight, bubbleY + bH, topRightR = cornerSharp, paint = gradPaint)
        canvas.save()
        canvas.translate(bLeft + bHPad, bubbleY + bVPad)
        layout.draw(canvas)
        canvas.restore()
    }

    private fun drawAiImageRow(
        canvas: Canvas,
        bubble: ExportBubbleInfo,
        rowY: Float,
        avBitmap: Bitmap?,
        charName: String,
    ) {
        val bLeft = hPad + avatarSz + avGap
        val imageY = if (bubble.showNameAndAvatar) rowY + nameH + nameGap else rowY
        if (bubble.showNameAndAvatar) {
            canvas.drawText(charName, bLeft, rowY + nameH, namePaint)
            if (avBitmap != null) {
                canvas.drawBitmap(avBitmap, hPad, imageY, null)
            } else {
                canvas.drawCircle(hPad + avatarSz / 2, imageY + avatarSz / 2, avatarSz / 2, avFbPaint)
                val initial = charName.firstOrNull()?.toString() ?: "A"
                val ty = imageY + avatarSz / 2 - (avTextPaint.descent() + avTextPaint.ascent()) / 2
                canvas.drawText(initial, hPad + avatarSz / 2, ty, avTextPaint)
            }
        }
        drawImageGrid(canvas, bubble, bLeft, imageY)
    }

    private fun drawUserImageRow(
        canvas: Canvas,
        bubble: ExportBubbleInfo,
        rowY: Float,
        avBitmap: Bitmap?,
        userName: String,
    ) {
        val avLeft = CANVAS_W - hPad - avatarSz
        val bRight = avLeft - avGap
        val imageY = if (bubble.showNameAndAvatar) rowY + nameH + nameGap else rowY
        if (bubble.showNameAndAvatar) {
            namePaint.textAlign = Paint.Align.RIGHT
            canvas.drawText(userName, bRight, rowY + nameH, namePaint)
            namePaint.textAlign = Paint.Align.LEFT
            if (avBitmap != null) {
                canvas.drawBitmap(avBitmap, avLeft, imageY, null)
            } else {
                val userFbPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = C_USER1; style = Paint.Style.FILL }
                canvas.drawCircle(avLeft + avatarSz / 2, imageY + avatarSz / 2, avatarSz / 2, userFbPaint)
                val initial = userName.firstOrNull()?.toString() ?: "U"
                val ty = imageY + avatarSz / 2 - (avTextPaint.descent() + avTextPaint.ascent()) / 2
                canvas.drawText(initial, avLeft + avatarSz / 2, ty, avTextPaint)
            }
        }
        drawImageGrid(canvas, bubble, bRight - bubble.bubbleW, imageY)
    }

    private fun drawImageGrid(canvas: Canvas, bubble: ExportBubbleInfo, left: Float, top: Float) {
        if (bubble.imageKind == ExportImageKind.Sticker) {
            drawStickerStrip(canvas, bubble, left, top)
            return
        }
        val shown = bubble.imageBitmaps.size.coerceAtLeast(1)
        if (bubble.imageTotalCount <= 1) {
            val rect = RectF(left, top, left + imageGridTile, top + imageGridTile)
            drawImageTile(canvas, bubble.imageBitmaps.firstOrNull(), rect, ExportImageKind.ChatImage)
            return
        }
        val displayCount = minOf(4, shown)
        for (slot in imageGridSlots(displayCount, bubble.msg.isUser())) {
            val rect = RectF(
                left + slot.col * (imageGridTile + imageGap),
                top + slot.row * (imageGridTile + imageGap),
                left + slot.col * (imageGridTile + imageGap) + imageGridTile,
                top + slot.row * (imageGridTile + imageGap) + imageGridTile,
            )
            drawImageTile(canvas, bubble.imageBitmaps.getOrNull(slot.imageIndex), rect, ExportImageKind.ChatImage)
            if (slot.imageIndex == 3 && bubble.imageTotalCount > 4) {
                drawRoundRectClipped(canvas, rect) {
                    canvas.drawRect(rect, imageOverlayPaint)
                    val label = "+${bubble.imageTotalCount - 4}"
                    val baseline = rect.centerY() - (imageOverlayTextPaint.descent() + imageOverlayTextPaint.ascent()) / 2
                    canvas.drawText(label, rect.centerX(), baseline, imageOverlayTextPaint)
                }
            }
        }
    }

    private data class ImageGridSlot(
        val imageIndex: Int,
        val row: Int,
        val col: Int,
    )

    private fun imageGridSlots(count: Int, isUser: Boolean): List<ImageGridSlot> {
        if (count <= 1) return listOf(ImageGridSlot(0, 0, 0))
        if (count == 2) {
            return if (isUser) {
                listOf(ImageGridSlot(1, 0, 0), ImageGridSlot(0, 0, 1))
            } else {
                listOf(ImageGridSlot(0, 0, 0), ImageGridSlot(1, 0, 1))
            }
        }
        val top = if (isUser) listOf(3, 2) else listOf(2, 3)
        val bottom = if (isUser) listOf(1, 0) else listOf(0, 1)
        return buildList {
            val topImages = top.filter { it < count }
            val topStartCol = if (isUser && topImages.size == 1) 1 else 0
            topImages.forEachIndexed { index, imageIndex ->
                add(ImageGridSlot(imageIndex, 0, topStartCol + index))
            }
            bottom.filter { it < count }.forEachIndexed { index, imageIndex ->
                add(ImageGridSlot(imageIndex, 1, index))
            }
        }
    }

    private fun drawStickerStrip(canvas: Canvas, bubble: ExportBubbleInfo, left: Float, top: Float) {
        val shown = bubble.imageBitmaps.size.coerceAtLeast(1)
        val displayCount = minOf(4, shown)
        var y = top
        for (index in 0 until displayCount) {
            val bitmap = bubble.imageBitmaps.getOrNull(index)
            val (w, h) = measureStickerBitmap(bitmap)
            val tileLeft = if (bubble.msg.isUser()) left + bubble.bubbleW - w else left
            val rect = RectF(tileLeft, y, tileLeft + w, y + h)
            drawImageTile(canvas, bitmap, rect, ExportImageKind.Sticker)
            if (index == 3 && bubble.imageTotalCount > 4) {
                drawRoundRectClipped(canvas, rect) {
                    canvas.drawRect(rect, imageOverlayPaint)
                    val label = "+${bubble.imageTotalCount - 4}"
                    val baseline = rect.centerY() - (imageOverlayTextPaint.descent() + imageOverlayTextPaint.ascent()) / 2
                    canvas.drawText(label, rect.centerX(), baseline, imageOverlayTextPaint)
                }
            }
            y += h + imageGap
        }
    }

    private fun drawImageTile(canvas: Canvas, bitmap: Bitmap?, rect: RectF, kind: ExportImageKind) {
        drawRoundRectClipped(canvas, rect) {
            if (bitmap != null && bitmap.width > 0 && bitmap.height > 0) {
                if (kind == ExportImageKind.Sticker) {
                    drawFitBitmap(canvas, bitmap, rect)
                } else {
                    val src = centerCropSource(bitmap, rect.width(), rect.height())
                    canvas.drawBitmap(bitmap, src, rect, imagePaint)
                }
            } else {
                canvas.drawRect(rect, imagePlaceholderPaint)
                val baseline = rect.centerY() - (imagePlaceholderTextPaint.descent() + imagePlaceholderTextPaint.ascent()) / 2
                val label = if (kind == ExportImageKind.Sticker) "表情" else "图片"
                canvas.drawText(label, rect.centerX(), baseline, imagePlaceholderTextPaint)
            }
        }
    }

    private fun drawRoundRectClipped(canvas: Canvas, rect: RectF, block: () -> Unit) {
        val path = Path().apply { addRoundRect(rect, imageCornerR, imageCornerR, Path.Direction.CW) }
        canvas.save()
        canvas.clipPath(path)
        block()
        canvas.restore()
    }

    private fun centerCropSource(bitmap: Bitmap, dstW: Float, dstH: Float): Rect {
        val srcRatio = bitmap.width.toFloat() / bitmap.height.toFloat()
        val dstRatio = dstW / dstH
        return if (srcRatio > dstRatio) {
            val cropW = (bitmap.height * dstRatio).toInt().coerceIn(1, bitmap.width)
            val left = (bitmap.width - cropW) / 2
            Rect(left, 0, left + cropW, bitmap.height)
        } else {
            val cropH = (bitmap.width / dstRatio).toInt().coerceIn(1, bitmap.height)
            val top = (bitmap.height - cropH) / 2
            Rect(0, top, bitmap.width, top + cropH)
        }
    }

    private fun drawFitBitmap(canvas: Canvas, bitmap: Bitmap, rect: RectF) {
        val srcRatio = bitmap.width.toFloat() / bitmap.height.toFloat()
        val dstRatio = rect.width() / rect.height()
        val dst = RectF(rect)
        if (srcRatio > dstRatio) {
            val height = rect.width() / srcRatio
            dst.top = rect.centerY() - height / 2f
            dst.bottom = dst.top + height
        } else {
            val width = rect.height() * srcRatio
            dst.left = rect.centerX() - width / 2f
            dst.right = dst.left + width
        }
        canvas.drawBitmap(bitmap, Rect(0, 0, bitmap.width, bitmap.height), dst, imagePaint)
    }

    private fun drawAiVoiceRow(
        canvas: Canvas,
        bubble: ExportBubbleInfo,
        rowY: Float,
        avBitmap: Bitmap?,
        charName: String,
    ) {
        val bLeft = hPad + avatarSz + avGap
        val bubbleY = if (bubble.showNameAndAvatar) rowY + nameH + nameGap else rowY
        if (bubble.showNameAndAvatar) {
            drawAssistantHeader(canvas, charName, formatMessageTime(bubble.msg.timestamp), bLeft, rowY + nameH)
            if (avBitmap != null) {
                canvas.drawBitmap(avBitmap, hPad, bubbleY, null)
            } else {
                canvas.drawCircle(hPad + avatarSz / 2, bubbleY + avatarSz / 2, avatarSz / 2, avFbPaint)
                val initial = charName.firstOrNull()?.toString() ?: "A"
                val ty = bubbleY + avatarSz / 2 - (avTextPaint.descent() + avTextPaint.ascent()) / 2
                canvas.drawText(initial, hPad + avatarSz / 2, ty, avTextPaint)
            }
        }

        drawVoiceBubble(
            canvas = canvas,
            l = bLeft,
            t = bubbleY,
            r = bLeft + bubble.bubbleW,
            b = bubbleY + bubble.bubbleH,
            isUser = false,
            waveform = bubble.waveform,
            durationMs = bubble.durationMs,
        )
        drawVoiceTranscriptCard(canvas, bubble, bLeft, bubbleY + bubble.bubbleH + voiceCardGap)
    }

    private fun drawUserVoiceRow(
        canvas: Canvas,
        bubble: ExportBubbleInfo,
        rowY: Float,
        avBitmap: Bitmap?,
        userName: String,
    ) {
        val avLeft = CANVAS_W - hPad - avatarSz
        val bRight = avLeft - avGap
        val bubbleY = if (bubble.showNameAndAvatar) rowY + nameH + nameGap else rowY
        if (bubble.showNameAndAvatar) {
            drawUserHeader(canvas, userName, formatMessageTime(bubble.msg.timestamp), bRight, rowY + nameH)
            if (avBitmap != null) {
                canvas.drawBitmap(avBitmap, avLeft, bubbleY, null)
            } else {
                val userFbPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = C_USER1; style = Paint.Style.FILL }
                canvas.drawCircle(avLeft + avatarSz / 2, bubbleY + avatarSz / 2, avatarSz / 2, userFbPaint)
                val initial = userName.firstOrNull()?.toString() ?: "U"
                val ty = bubbleY + avatarSz / 2 - (avTextPaint.descent() + avTextPaint.ascent()) / 2
                canvas.drawText(initial, avLeft + avatarSz / 2, ty, avTextPaint)
            }
        }

        val bLeft = bRight - bubble.bubbleW
        drawVoiceBubble(
            canvas = canvas,
            l = bLeft,
            t = bubbleY,
            r = bRight,
            b = bubbleY + bubble.bubbleH,
            isUser = true,
            waveform = bubble.waveform,
            durationMs = bubble.durationMs,
        )
        if (bubble.transcriptLayout != null) {
            drawVoiceTranscriptCard(
                canvas,
                bubble,
                bRight - bubble.transcriptW,
                bubbleY + bubble.bubbleH + voiceCardGap,
            )
        }
    }

    private fun drawAssistantHeader(
        canvas: Canvas,
        name: String,
        time: String,
        left: Float,
        baseline: Float,
    ) {
        namePaint.textAlign = Paint.Align.LEFT
        timePaint.textAlign = Paint.Align.LEFT
        canvas.drawText(name, left, baseline, namePaint)
        canvas.drawText(time, left + namePaint.measureText(name) + dp(8f), baseline, timePaint)
    }

    private fun drawUserHeader(
        canvas: Canvas,
        name: String,
        time: String,
        right: Float,
        baseline: Float,
    ) {
        namePaint.textAlign = Paint.Align.RIGHT
        timePaint.textAlign = Paint.Align.RIGHT
        canvas.drawText(name, right, baseline, namePaint)
        canvas.drawText(time, right - namePaint.measureText(name) - dp(8f), baseline, timePaint)
        namePaint.textAlign = Paint.Align.LEFT
        timePaint.textAlign = Paint.Align.LEFT
    }

    private fun drawVoiceBubble(
        canvas: Canvas,
        l: Float,
        t: Float,
        r: Float,
        b: Float,
        isUser: Boolean,
        waveform: List<Float>,
        durationMs: Long,
    ) {
        if (isUser) {
            val gradPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
                style = Paint.Style.FILL
                shader = LinearGradient(l, 0f, r, 0f, C_USER1, C_USER2, Shader.TileMode.CLAMP)
            }
            drawRoundBubble(canvas, l, t, r, b, topRightR = cornerSharp, paint = gradPaint)
        } else {
            val fill = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = C_VOICE_AI_BG; style = Paint.Style.FILL }
            val stroke = Paint(Paint.ANTI_ALIAS_FLAG).apply {
                color = colorWithAlpha(C_VOICE, 0.38f)
                style = Paint.Style.STROKE
                strokeWidth = dp(1f)
            }
            drawRoundBubble(canvas, l, t, r, b, topLeftR = cornerSharp, paint = fill)
            drawRoundBubble(canvas, l + dp(0.5f), t + dp(0.5f), r - dp(0.5f), b - dp(0.5f), topLeftR = cornerSharp, paint = stroke)
        }

        val accent = if (isUser) C_WHITE else C_VOICE
        val playCx = l + dp(23f)
        val playCy = t + (b - t) / 2f
        val playCirclePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = if (isUser) colorWithAlpha(C_WHITE, 0.22f) else C_VOICE
            style = Paint.Style.FILL
        }
        canvas.drawCircle(playCx, playCy, dp(11f), playCirclePaint)
        val trianglePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = if (isUser) C_WHITE else C_WHITE
            style = Paint.Style.FILL
        }
        val tri = Path().apply {
            moveTo(playCx - dp(3f), playCy - dp(5f))
            lineTo(playCx - dp(3f), playCy + dp(5f))
            lineTo(playCx + dp(5f), playCy)
            close()
        }
        canvas.drawPath(tri, trianglePaint)

        val durationLabel = "${exportVoiceDurationSeconds(durationMs)}\""
        val durationPaintColor = if (isUser) colorWithAlpha(C_WHITE, 0.92f) else C_MUTED
        voiceDurationPaint.color = durationPaintColor
        val durationRight = r - dp(11f)
        val durationBaseline = playCy - (voiceDurationPaint.descent() + voiceDurationPaint.ascent()) / 2f
        canvas.drawText(durationLabel, durationRight, durationBaseline, voiceDurationPaint)

        val waveLeft = l + dp(44f)
        val waveRight = durationRight - voiceDurationPaint.measureText(durationLabel) - dp(10f)
        val waveW = (waveRight - waveLeft).coerceAtLeast(dp(20f))
        val barW = dp(3f)
        val gap = dp(4f)
        val barCount = ((waveW + gap) / (barW + gap)).toInt().coerceIn(5, 36)
        val barsW = barCount * barW + (barCount - 1) * gap
        val startX = waveLeft + ((waveW - barsW) / 2f).coerceAtLeast(0f)
        val heights = exportVoiceBarHeights(barCount, waveform)
        val barPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = if (isUser) colorWithAlpha(C_WHITE, 0.84f) else colorWithAlpha(accent, 0.92f)
            style = Paint.Style.FILL
        }
        val maxBarH = dp(22f)
        heights.forEachIndexed { index, heightRatio ->
            val barH = (maxBarH * heightRatio).coerceAtLeast(dp(4f))
            val x = startX + index * (barW + gap)
            canvas.drawRoundRect(
                RectF(x, playCy - barH / 2f, x + barW, playCy + barH / 2f),
                barW / 2f,
                barW / 2f,
                barPaint,
            )
        }
    }

    private fun drawVoiceTranscriptCard(
        canvas: Canvas,
        bubble: ExportBubbleInfo,
        left: Float,
        top: Float,
    ) {
        val layout = bubble.transcriptLayout ?: return
        val rect = RectF(left, top, left + bubble.transcriptW, top + bubble.transcriptH)
        val fill = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = C_VOICE_CARD_BG; style = Paint.Style.FILL }
        val stroke = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = colorWithAlpha(C_VOICE, 0.22f)
            style = Paint.Style.STROKE
            strokeWidth = dp(1f)
        }
        canvas.drawRoundRect(rect, dp(10f), dp(10f), fill)
        canvas.drawRoundRect(rect, dp(10f), dp(10f), stroke)

        val labelBaseline = top + voiceCardVPad + voiceLabelPaint.textSize
        canvas.drawText("识别结果", left + voiceCardHPad, labelBaseline, voiceLabelPaint)
        canvas.save()
        canvas.translate(left + voiceCardHPad, labelBaseline + voiceLabelGap)
        layout.draw(canvas)
        canvas.restore()
    }

    private fun drawRoundBubble(
        canvas: Canvas, l: Float, t: Float, r: Float, b: Float,
        topLeftR: Float = cornerR, topRightR: Float = cornerR,
        paint: Paint
    ) {
        val radii = floatArrayOf(
            topLeftR, topLeftR,
            topRightR, topRightR,
            cornerR, cornerR,
            cornerR, cornerR
        )
        val path = Path().apply { addRoundRect(RectF(l, t, r, b), radii, Path.Direction.CW) }
        canvas.drawPath(path, paint)
    }

    // ──────────────────────────────────────────────────────────────────────
    // UTILITIES
    // ──────────────────────────────────────────────────────────────────────

    private fun buildLayout(text: String, paint: TextPaint, maxWidth: Int): StaticLayout {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            StaticLayout.Builder.obtain(text, 0, text.length, paint, maxWidth)
                .setAlignment(Layout.Alignment.ALIGN_NORMAL)
                .setLineSpacing(dp(1.5f), 1f)
                .setIncludePad(false)
                .build()
        } else {
            @Suppress("DEPRECATION")
            StaticLayout(text, paint, maxWidth, Layout.Alignment.ALIGN_NORMAL, 1f, dp(1.5f), false)
        }
    }

    private fun measureContentWidth(layout: StaticLayout): Float {
        var maxLineWidth = 0f
        for (i in 0 until layout.lineCount) {
            maxLineWidth = maxOf(maxLineWidth, layout.getLineWidth(i))
        }
        return ceil(maxLineWidth).coerceAtLeast(dp(8f))
    }

    private fun exportPlainText(msg: Message): String {
        val fallback = if (msg.isUser()) {
            msg.content
        } else {
            parseMessageContent(msg.content).mainContent.ifBlank { msg.content }
        }
        return msg.voiceState
            ?.readableText(fallback)
            ?.takeIf { it.isNotBlank() }
            ?: fallback
    }

    private fun estimatedExportVoiceDurationMs(text: String, explicitDurationMs: Long?): Long {
        explicitDurationMs?.takeIf { it > 0L }?.let { return it.coerceIn(voiceDurationMinMs, voiceDurationMaxMs) }
        val nonBlankChars = text.count { !it.isWhitespace() }.coerceAtLeast(8)
        return (nonBlankChars * 210L).coerceIn(1_800L, voiceDurationMaxMs)
    }

    private fun exportVoiceDurationSeconds(durationMs: Long): Int {
        val safeDuration = durationMs.coerceIn(voiceDurationMinMs, voiceDurationMaxMs)
        return ((safeDuration + 999L) / 1_000L).toInt().coerceIn(1, voiceDurationMaxSeconds)
    }

    private fun exportVoiceBarHeights(barCount: Int, waveform: List<Float>): List<Float> {
        val fallbackPattern = listOf(0.38f, 0.62f, 0.88f, 0.56f, 0.74f, 0.44f, 0.96f, 0.66f)
        val safeWave = waveform
            .filter { it.isFinite() && it >= 0f }
            .map { it.coerceIn(0f, 1f) }
        if (safeWave.isEmpty()) {
            return List(barCount) { index -> fallbackPattern[index % fallbackPattern.size] }
        }
        return List(barCount) { index ->
            val start = (index * safeWave.size / barCount).coerceIn(0, safeWave.lastIndex)
            val endExclusive = (((index + 1) * safeWave.size + barCount - 1) / barCount)
                .coerceIn(start + 1, safeWave.size)
            val amplitude = safeWave.subList(start, endExclusive).maxOrNull() ?: safeWave[start]
            val shaped = amplitude.toDouble().pow(0.72).toFloat()
            (0.18f + shaped * 0.82f).coerceIn(0.18f, 1f)
        }
    }

    private fun colorWithAlpha(color: Int, alpha: Float): Int =
        Color.argb(
            (alpha.coerceIn(0f, 1f) * 255).toInt(),
            Color.red(color),
            Color.green(color),
            Color.blue(color),
        )

    private fun stripMarkdown(text: String): String = text
        .replace(Regex("\\*{1,3}(.+?)\\*{1,3}"), "$1")
        .replace(Regex("_{1,2}(.+?)_{1,2}"), "$1")
        .replace(Regex("^#{1,6}\\s+", RegexOption.MULTILINE), "")
        .replace(Regex("`{1,3}[\\s\\S]*?`{1,3}"), "")
        .replace(Regex("^>\\s*", RegexOption.MULTILINE), "")
        .replace(Regex("!\\[.*?\\]\\(.*?\\)"), "")
        .replace(Regex("\\[(.+?)\\]\\(.*?\\)"), "$1")
        .trim()

    private suspend fun loadAvatarCircle(url: String, apiBase: String): Bitmap? {
        val fullUrl = resolveAvatarUrlForApi(url, apiBase) ?: return null
        return try {
            val request = ImageRequest.Builder(context)
                .data(fullUrl)
                .size(Size(avatarSz.toInt(), avatarSz.toInt()))
                .allowHardware(false)
                .build()
            val result = authImageLoader.execute(request)
            if (result !is SuccessResult) return null
            val bitmap = drawableToBitmap(result.drawable)
            cropToCircle(Bitmap.createScaledBitmap(bitmap, avatarSz.toInt(), avatarSz.toInt(), true))
        } catch (_: Exception) { null }
    }

    private fun drawableToBitmap(drawable: Drawable): Bitmap {
        if (drawable is BitmapDrawable) {
            drawable.bitmap?.let { return it }
        }
        val width = drawable.intrinsicWidth.takeIf { it > 0 } ?: avatarSz.toInt()
        val height = drawable.intrinsicHeight.takeIf { it > 0 } ?: avatarSz.toInt()
        val bitmap = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(bitmap)
        drawable.setBounds(0, 0, canvas.width, canvas.height)
        drawable.draw(canvas)
        return bitmap
    }

    private fun cropToCircle(src: Bitmap): Bitmap {
        val sz = minOf(src.width, src.height)
        val out = Bitmap.createBitmap(sz, sz, Bitmap.Config.ARGB_8888)
        val c = Canvas(out)
        val p = Paint(Paint.ANTI_ALIAS_FLAG)
        c.drawOval(RectF(0f, 0f, sz.toFloat(), sz.toFloat()), p)
        p.xfermode = PorterDuffXfermode(PorterDuff.Mode.SRC_IN)
        c.drawBitmap(src, 0f, 0f, p)
        return out
    }
}
