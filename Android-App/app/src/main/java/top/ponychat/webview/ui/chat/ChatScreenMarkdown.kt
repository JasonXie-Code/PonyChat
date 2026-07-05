package top.ponychat.webview.ui.chat

import android.util.Log
import android.Manifest
import android.app.Activity
import android.content.ClipData
import android.content.ClipboardManager
import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.Settings as AndroidSettings
import android.provider.MediaStore
import android.view.View
import android.view.ViewTreeObserver
import android.view.WindowManager
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.ImageDecoder
import android.util.Base64
import android.text.method.LinkMovementMethod
import android.util.TypedValue
import android.widget.TextView
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.*
import androidx.compose.animation.core.*
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.gestures.animateScrollBy
import androidx.compose.foundation.gestures.scrollBy
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.gestures.draggable
import androidx.compose.foundation.gestures.rememberDraggableState
import androidx.compose.foundation.gestures.Orientation
import androidx.compose.foundation.gestures.rememberTransformableState
import androidx.compose.foundation.gestures.transformable
import androidx.compose.ui.input.nestedscroll.NestedScrollConnection
import androidx.compose.ui.input.nestedscroll.NestedScrollSource
import androidx.compose.ui.input.nestedscroll.nestedScroll
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.Velocity
import kotlinx.coroutines.withTimeoutOrNull
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.Chat
import androidx.compose.material.icons.automirrored.filled.Subject
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.material3.AssistChipDefaults
import androidx.compose.material3.TextFieldDefaults
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.pointer.PointerEventPass
import androidx.compose.ui.input.pointer.changedToDown
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.Density
import androidx.compose.ui.draw.BlurredEdgeTreatment
import androidx.compose.ui.draw.blur
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.RectangleShape
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.graphics.toArgb
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.layout.positionInWindow
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.compose.foundation.Canvas
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.drawscope.withTransform
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogWindowProvider
import androidx.compose.ui.window.DialogProperties
import androidx.compose.ui.zIndex
import androidx.core.content.ContextCompat
import androidx.core.graphics.drawable.toBitmap
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsAnimationCompat
import androidx.core.view.WindowInsetsCompat as ViewWindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import coil.compose.AsyncImage
import coil.imageLoader
import coil.request.ImageRequest
import io.noties.markwon.Markwon
import io.noties.markwon.ext.strikethrough.StrikethroughPlugin
import io.noties.markwon.ext.tables.TablePlugin
import io.noties.markwon.linkify.LinkifyPlugin
import kotlin.math.max
import kotlin.math.roundToInt
import kotlinx.coroutines.delay
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.FlowPreview
import kotlinx.coroutines.flow.debounce
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import top.ponychat.webview.BackendStreamingVoiceBridge
import top.ponychat.webview.CompanionService
import top.ponychat.webview.CustomToast
import top.ponychat.webview.data.model.Character
import top.ponychat.webview.data.model.GalgameOptionItem
import top.ponychat.webview.data.model.ModelInfo
import top.ponychat.webview.data.model.Message
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.ui.character.CharacterAvatar
import top.ponychat.webview.ui.common.PonyAvatar
import top.ponychat.webview.ui.common.PonyPromptBubble
import top.ponychat.webview.ui.common.WheelStringColumn
import top.ponychat.webview.ui.common.resolveAvatarUrlForApi
import top.ponychat.webview.ui.settings.CrisisHotlineDialog
import top.ponychat.webview.ui.theme.*
import top.ponychat.webview.util.ChatEventBus
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.text.input.KeyboardType
import java.io.ByteArrayOutputStream
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Date
import java.util.Locale

// ==================== Markdown 渲染组件 ====================

/**
 * 进程级 Markwon 实例缓存。
 * Markwon.builder().build() 每次需初始化 4 个插件，在 120Hz 设备上耗时约 5-10ms。
 * LazyColumn 每次将 item 滚出后销毁组合，滚回时重新组合，触发重复初始化。
 * 缓存键：(isDark: Boolean, codeSizePx: Int) —— 两个维度决定了渲染样式，其余颜色由 isDark 推算。
 */
private object MarkwonCache {
    private val cache = HashMap<Long, Markwon>(8)

    private fun key(isDark: Boolean, codeSizePx: Int): Long =
        (if (isDark) (1L shl 32) else 0L) or (codeSizePx.toLong() and 0xFFFFFFFFL)

    fun get(
        context: android.content.Context,
        isDark: Boolean,
        codeSizePx: Int,
        codeBlockBg: Int, codeBlockText: Int,
        inlineCodeBg: Int, inlineCodeText: Int,
    ): Markwon = synchronized(cache) {
        val k = key(isDark, codeSizePx)
        val hit = cache.containsKey(k)
        if (top.ponychat.webview.BuildConfig.DEBUG) {
            if (!hit) android.util.Log.d("PERF_MARKWON", "MISS isDark=$isDark codeSizePx=$codeSizePx → building Markwon")
            else android.util.Log.v("PERF_MARKWON", "HIT isDark=$isDark codeSizePx=$codeSizePx")
        }
        cache.getOrPut(k) {
            Markwon.builder(context.applicationContext)
                .usePlugin(StrikethroughPlugin.create())
                .usePlugin(TablePlugin.create(context.applicationContext))
                .usePlugin(LinkifyPlugin.create())
                .usePlugin(object : io.noties.markwon.AbstractMarkwonPlugin() {
                    override fun configureTheme(builder: io.noties.markwon.core.MarkwonTheme.Builder) {
                        builder
                            .codeBlockBackgroundColor(codeBlockBg)
                            .codeBlockTextColor(codeBlockText)
                            .codeBackgroundColor(inlineCodeBg)
                            .codeTextColor(inlineCodeText)
                            .codeBlockTypeface(android.graphics.Typeface.MONOSPACE)
                            .codeTypeface(android.graphics.Typeface.MONOSPACE)
                            .codeTextSize(codeSizePx)
                            .codeBlockMargin((8 * context.resources.displayMetrics.density).toInt())
                    }
                })
                .build()
        }
    }
}

/**
 * 进程级 Markdown → Spanned 渲染缓存。
 * markwon.toMarkdown(text) 是最昂贵的调用（~5-10ms/次），对于相同文本无需重复解析。
 * LazyColumn 滚出再滚回时，Composable 重建但文本不变，缓存命中可省去全部解析开销。
 */
private object MarkdownSpannedCache {
    private val cache = object : LinkedHashMap<Int, android.text.Spanned>(128, 0.75f, true) {
        override fun removeEldestEntry(eldest: MutableMap.MutableEntry<Int, android.text.Spanned>): Boolean = size > 300
    }

    fun getOrParse(markwon: Markwon, processedText: String): android.text.Spanned {
        val key = processedText.hashCode()
        synchronized(cache) { cache[key]?.let { return it } }
        val spanned = markwon.toMarkdown(processedText)
        synchronized(cache) { cache[key] = spanned }
        return spanned
    }
}

@Composable
fun MarkdownText(
    text: String,
    textColor: Color,
    modifier: Modifier = Modifier,
    fontSize: Float = AppFontSizes.defaultBody
) {
    val context = LocalContext.current
    val density = LocalDensity.current
    val sizePx = with(density) { fontSize.sp.toPx() }
    val codeSizePx = with(density) { (fontSize * 0.9f).sp.toPx().toInt() }
    val colorArgb = textColor.toArgb()
    val linkColor = MaterialTheme.colorScheme.primary.toArgb()
    val isDark = MaterialTheme.colorScheme.background.luminance() < 0.5f
    val codeBlockBg = if (isDark) android.graphics.Color.parseColor("#1E1B2E")
        else android.graphics.Color.parseColor("#F1F5F9")
    val codeBlockText = if (isDark) android.graphics.Color.parseColor("#E2E8F0")
        else android.graphics.Color.parseColor("#1E293B")
    val inlineCodeBg = if (isDark) android.graphics.Color.parseColor("#252D3A")
        else android.graphics.Color.parseColor("#E2E8F0")
    val inlineCodeText = if (isDark) android.graphics.Color.parseColor("#F87171")
        else android.graphics.Color.parseColor("#DC2626")

    // 从进程级缓存获取 Markwon 实例，避免每次 item 滚入视口时重复 build（~5-10ms/次）
    val markwon = remember(isDark, codeSizePx) {
        MarkwonCache.get(context, isDark, codeSizePx, codeBlockBg, codeBlockText, inlineCodeBg, inlineCodeText)
    }
    AndroidView(
        modifier = modifier,
        factory = { ctx ->
            TextView(ctx).apply {
                setTextSize(TypedValue.COMPLEX_UNIT_PX, sizePx)
                setTextColor(colorArgb)
                movementMethod = LinkMovementMethod.getInstance()
                setLinkTextColor(linkColor)
                setSpannableFactory(io.noties.markwon.utils.NoCopySpannableFactory.getInstance())
            }
        },
        // onReset: LazyColumn item 滚出后 View 可被同 contentType 的新 item 复用，
        // 跳过 factory 重建（~3-5ms），仅走 update 路径。
        onReset = { view ->
            view.text = ""
            view.tag = null
        },
        update = { view ->
            view.setTextSize(TypedValue.COMPLEX_UNIT_PX, sizePx)
            view.setTextColor(colorArgb)
            view.setLinkTextColor(linkColor)
            if (view.tag as? String != text) {
                view.tag = text
                val processed = text.replace(
                    Regex("([\"'\\u2018-\\u201F])(\\*+)(?=\\S)"),
                    "$1 $2"
                )
                val spanned = MarkdownSpannedCache.getOrParse(markwon, processed)
                markwon.setParsedMarkdown(view, spanned)
            }
        }
    )
}

// ==================== 代码块分段渲染 ====================

private sealed class MarkdownSegment {
    data class TextSegment(val text: String) : MarkdownSegment()
    data class CodeBlockSegment(val language: String, val code: String) : MarkdownSegment()
}

private val CODE_FENCE_PATTERN = Regex("""```([^\n]*)\n([\s\S]*?)```""")

private fun parseMarkdownSegments(text: String): List<MarkdownSegment> {
    val result = mutableListOf<MarkdownSegment>()
    var lastEnd = 0
    for (match in CODE_FENCE_PATTERN.findAll(text)) {
        if (match.range.first > lastEnd) {
            val before = text.substring(lastEnd, match.range.first)
            if (before.isNotBlank()) result.add(MarkdownSegment.TextSegment(before))
        }
        result.add(MarkdownSegment.CodeBlockSegment(
            language = match.groupValues[1].trim(),
            code = match.groupValues[2]
        ))
        lastEnd = match.range.last + 1
    }
    if (lastEnd < text.length) {
        val after = text.substring(lastEnd)
        if (after.isNotBlank()) result.add(MarkdownSegment.TextSegment(after))
    }
    return result.ifEmpty { listOf(MarkdownSegment.TextSegment(text)) }
}

@Composable
private fun CodeBlockView(
    language: String,
    code: String,
    modifier: Modifier = Modifier
) {
    val isDark = MaterialTheme.colorScheme.background.luminance() < 0.5f
    val bgColor = if (isDark) Color(0xFF1E1B2E) else Color(0xFFF1F5F9)
    val headerBg = if (isDark) Color(0xFF2D2A3E) else Color(0xFFE2E8F0)
    val codeTextColor = if (isDark) Color(0xFFE2E8F0) else Color(0xFF1E293B)
    val labelColor = if (isDark) Color(0xFF94A3B8) else Color(0xFF64748B)
    val context = LocalContext.current
    var copied by remember { mutableStateOf(false) }
    LaunchedEffect(copied) {
        if (copied) {
            delay(2000)
            copied = false
        }
    }
    Surface(
        modifier = modifier.fillMaxWidth(),
        shape = RoundedCornerShape(8.dp),
        color = bgColor
    ) {
        Column {
            // 顶部标题栏：左侧语言名，右侧复制按钮
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .background(headerBg, RoundedCornerShape(topStart = 8.dp, topEnd = 8.dp))
                    .padding(horizontal = 12.dp, vertical = 6.dp),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    text = language.ifEmpty { "code" },
                    style = MaterialTheme.typography.labelSmall.copy(
                        fontFamily = androidx.compose.ui.text.font.FontFamily.Monospace
                    ),
                    color = labelColor
                )
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    modifier = Modifier
                        .clip(RoundedCornerShape(4.dp))
                        .clickable {
                            val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                            clipboard.setPrimaryClip(ClipData.newPlainText("code", code.trimEnd('\n')))
                            copied = true
                        }
                        .padding(horizontal = 6.dp, vertical = 2.dp)
                ) {
                    Icon(
                        imageVector = if (copied) Icons.Filled.Check else Icons.Filled.ContentCopy,
                        contentDescription = if (copied) "已复制" else "复制",
                        tint = if (copied) Color(0xFF4ADE80) else labelColor,
                        modifier = Modifier.size(12.dp)
                    )
                    Spacer(Modifier.width(4.dp))
                    Text(
                        text = if (copied) "已复制" else "复制",
                        style = MaterialTheme.typography.labelSmall,
                        color = if (copied) Color(0xFF4ADE80) else labelColor
                    )
                }
            }
            // 代码内容区（支持横向滚动，防止长行溢出）
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .horizontalScroll(rememberScrollState())
                    .padding(horizontal = 12.dp, vertical = 10.dp)
            ) {
                Text(
                    text = code.trimEnd('\n'),
                    style = MaterialTheme.typography.bodySmall.copy(
                        fontFamily = androidx.compose.ui.text.font.FontFamily.Monospace,
                        lineHeight = 20.sp
                    ),
                    color = codeTextColor
                )
            }
        }
    }
}

@Composable
fun MarkdownWithCodeBlocks(
    text: String,
    textColor: Color,
    modifier: Modifier = Modifier,
    fontSize: Float = AppFontSizes.defaultBody
) {
    val segments = remember(text) { parseMarkdownSegments(text) }
    if (segments.size == 1 && segments[0] is MarkdownSegment.TextSegment) {
        MarkdownText(text = text, textColor = textColor, modifier = modifier, fontSize = fontSize)
        return
    }
    Column(modifier = modifier, verticalArrangement = Arrangement.spacedBy(4.dp)) {
        segments.forEach { seg ->
            when (seg) {
                is MarkdownSegment.TextSegment -> {
                    if (seg.text.isNotBlank()) {
                        MarkdownText(
                            text = seg.text.trim('\n'),
                            textColor = textColor,
                            modifier = Modifier.fillMaxWidth(),
                            fontSize = fontSize
                        )
                    }
                }
                is MarkdownSegment.CodeBlockSegment -> {
                    CodeBlockView(
                        language = seg.language,
                        code = seg.code,
                        modifier = Modifier.fillMaxWidth()
                    )
                }
            }
        }
    }
}
