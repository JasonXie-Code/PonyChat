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

// Galgame 场景配色：深色维持原风格，浅色提高文字/标签可读性
@androidx.compose.runtime.Immutable
private data class GalgamePalette(
    val env: Color,
    val envBorder: Color,
    val thought: Color,
    val thoughtBorder: Color,
    val bodyState: Color,
    val bodyBorder: Color,
    val thirdParty: Color,
    val thirdBorder: Color,
    val tagTimeBg: Color,
    val tagTime: Color,
    val tagLocBg: Color,
    val tagLoc: Color,
    val tagRelBg: Color,
    val tagRel: Color,
    val tagMoodBg: Color,
    val tagMood: Color
)

/** 浅色：仅用于 Galgame「身体描写」折叠区块描边（场景正文语义），与好感度 UI 的满分金无关。 */
private val GalgameLightBodySceneBorder = Color(0xFFD97706).copy(alpha = 0.5f)

/** 浅色：好感度 100 分/胜利态金。 */
internal val GalgameWinGoldLight = Color(0xFFE6C200)

@Composable
private fun rememberGalgamePalette(): GalgamePalette {
    val isDark = MaterialTheme.colorScheme.background.luminance() < 0.5f
    return remember(isDark) {
        if (isDark) {
            GalgamePalette(
                env = Color(0xFF8AB4FF),
                envBorder = Color(0xFF6FA8FF).copy(alpha = 0.55f),
                thought = Color(0xFF81C784),
                thoughtBorder = Color(0xFF4CAF50).copy(alpha = 0.6f),
                bodyState = Color(0xFFFFD95E),
                bodyBorder = Color(0xFFFFD666).copy(alpha = 0.58f),
                thirdParty = Color(0xFFB0B7C3),
                thirdBorder = Color(0xFFB0B7C3).copy(alpha = 0.5f),
                tagTimeBg = Color(0xFF2196F3).copy(alpha = 0.2f),
                tagTime = Color(0xFF42A5F5),
                tagLocBg = Color(0xFF4CAF50).copy(alpha = 0.2f),
                tagLoc = Color(0xFF66BB6A),
                tagRelBg = Color(0xFFE91E63).copy(alpha = 0.2f),
                tagRel = Color(0xFFF06292),
                tagMoodBg = Color(0xFFFFC107).copy(alpha = 0.2f),
                tagMood = Color(0xFFFFCA28)
            )
        } else {
            GalgamePalette(
                env = Color(0xFF1D4ED8),
                envBorder = Color(0xFF3B82F6).copy(alpha = 0.5f),
                thought = Color(0xFF166534),
                thoughtBorder = Color(0xFF16A34A).copy(alpha = 0.5f),
                bodyState = Color(0xFF92400E),
                bodyBorder = GalgameLightBodySceneBorder,
                thirdParty = Color(0xFF475569),
                thirdBorder = Color(0xFF64748B).copy(alpha = 0.5f),
                tagTimeBg = Color(0xFFE0F2FE),
                tagTime = Color(0xFF0369A1),
                tagLocBg = Color(0xFFDCFCE7),
                tagLoc = Color(0xFF166534),
                tagRelBg = Color(0xFFFCE7F3),
                tagRel = Color(0xFFBE185D),
                tagMoodBg = Color(0xFFFEF3C7),
                tagMood = Color(0xFF92400E)
            )
        }
    }
}

@Composable
fun GalgameSceneView(
    content: String,
    textColor: Color,
    /** 若不为空则直接使用（由 displayContent/HTML 或 rawContent 解析；无有效 raw 时无结构化覆盖），与 Web 一致 */
    parsedOverride: Map<String, String>? = null
) {
    // ── 重组诊断：Map<String,String>? 是不稳定类型，若此处频繁重组说明 GalgameSceneView 无法被 skip ──
    if (top.ponychat.webview.BuildConfig.DEBUG) {
        val sceneRecomposeCount = remember { intArrayOf(0) }
        // 用于测量每次重组的组合阶段耗时（从函数体开始到 SideEffect 触发）
        val composeStartNs = remember { longArrayOf(0L) }
        composeStartNs[0] = System.nanoTime()
        SideEffect {
            sceneRecomposeCount[0]++
            val n = sceneRecomposeCount[0]
            val elapsedMs = (System.nanoTime() - composeStartNs[0]) / 1_000_000f
            if (n <= 3 || n % 10 == 0 || elapsedMs > 5f) {
                Log.d("PERF_GALGAME", "GalgameSceneView x$n  contentLen=${content.length}  hasParsedOverride=${parsedOverride != null}  composeMs=${String.format("%.2f", elapsedMs)}")
            }
        }
    }
    val galgamePalette = rememberGalgamePalette()
    val parsed = remember(content, parsedOverride) {
        parsedOverride ?: when {
            content.contains("gal-scene-") || content.contains("galgame-scene-container") -> parseGalgameFromHtml(content)
            else -> parseGalgameFields(content)
        }
    }
    if (parsed == null) {
        MarkdownText(text = content, textColor = textColor, modifier = Modifier.fillMaxWidth())
        return
    }

    // 一次性预计算所有区块的 AnnotatedString，减少 6 个 remember 为 1 个
    val annotations = remember(parsed) {
        val keys = arrayOf("score_delta_reason", "env", "body_state", "thought", "third_party", "dialogue", "text")
        val result = HashMap<String, AnnotatedString>(keys.size)
        for (k in keys) {
            parsed[k]?.takeIf { it.isNotBlank() }?.let { result[k] = parseSimpleMarkdown(it) }
        }
        result
    }

    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        annotations["score_delta_reason"]?.let { a ->
            GalgameCollapsibleSection(title = "分数变化理由", annotated = a)
        }
        annotations["env"]?.let { a ->
            GalgameColoredSection(title = "环境描写", annotated = a,
                textColor = galgamePalette.env, borderColor = galgamePalette.envBorder)
        }
        annotations["body_state"]?.let { a ->
            GalgameColoredSection(title = "身体描写", annotated = a,
                textColor = galgamePalette.bodyState, borderColor = galgamePalette.bodyBorder)
        }
        annotations["thought"]?.let { a ->
            GalgameColoredSection(title = "心理描写", annotated = a,
                textColor = galgamePalette.thought, borderColor = galgamePalette.thoughtBorder)
        }
        annotations["third_party"]?.let { a ->
            GalgameColoredSection(title = "第三者发言", annotated = a,
                textColor = galgamePalette.thirdParty, borderColor = galgamePalette.thirdBorder,
                italic = true)
        }
        annotations["dialogue"]?.let { a ->
            Text(
                text = a,
                color = textColor,
                fontSize = AppFontSizes.defaultBody.sp,
                lineHeight = (AppFontSizes.defaultBody * 1.5f).sp,
                modifier = Modifier.fillMaxWidth()
            )
        }
        GalgameTagsRow(parsed = parsed, palette = galgamePalette)
        parsed["memory_tags"]?.takeIf { it.isNotBlank() }?.let { section ->
            GalgameCollapsibleSectionItems(title = "记忆标签", body = section)
        }
        parsed["more_state"]?.takeIf { it.isNotBlank() }?.let { section ->
            GalgameCollapsibleSectionItems(title = "更多状态", body = section)
        }
        parsed["event_flags"]?.takeIf { it.isNotBlank() }?.let { section ->
            GalgameCollapsibleSectionItems(title = "事件标记", body = section)
        }
        annotations["text"]?.let { a ->
            Text(
                text = a,
                color = textColor,
                fontSize = AppFontSizes.defaultBody.sp,
                lineHeight = (AppFontSizes.defaultBody * 1.5f).sp,
                modifier = Modifier.fillMaxWidth()
            )
        }
    }
}

// 关系阶段/心情英文→中文映射（与 Web message-ui.js relationshipStageMap / moodMap 一致）
private val RELATIONSHIP_STAGE_MAP = mapOf(
    "stranger" to "陌生", "familiar" to "熟悉", "acquaintance" to "熟人",
    "ambiguous" to "暧昧期", "lover" to "恋人"
)
private val MOOD_MAP = mapOf(
    "calm" to "平静", "happy" to "开心", "shy" to "害羞", "jealous" to "吃醋",
    "cold" to "冷淡", "horny" to "欲望高涨", "angry" to "生气"
)

/** 时间/地点/关系/心情标签行（2×2 网格、圆角 12dp、padding 4dp×10dp；与 galgame 场景 HTML 中标签区结构对应）。 */
@Composable
private fun GalgameTagsRow(parsed: Map<String, String>, palette: GalgamePalette) {
    val TAG_MAX_LEN = 8
    fun clampTag(raw: String) = raw.take(TAG_MAX_LEN)
    val time = parsed["time"].orEmpty().trim()
    val location = parsed["location"].orEmpty().trim()
    val relationshipStageRaw = parsed["relationship_stage"].orEmpty().trim()
    val relationshipStage = RELATIONSHIP_STAGE_MAP[relationshipStageRaw.lowercase()] ?: relationshipStageRaw
    val moodRaw = parsed["mood"].orEmpty().trim()
    val mood = MOOD_MAP[moodRaw.lowercase()] ?: moodRaw
    if (time.isBlank() && location.isBlank() && relationshipStage.isBlank() && mood.isBlank()) return
    Column(verticalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Box(Modifier.weight(1f)) {
                if (time.isNotBlank()) {
                    GalgameTagChip(
                        text = clampTag(time),
                        backgroundColor = palette.tagTimeBg,
                        contentColor = palette.tagTime,
                        icon = Icons.Filled.Schedule,
                        modifier = Modifier.fillMaxWidth()
                    )
                }
            }
            Box(Modifier.weight(1f)) {
                if (location.isNotBlank()) {
                    GalgameTagChip(
                        text = clampTag(location),
                        backgroundColor = palette.tagLocBg,
                        contentColor = palette.tagLoc,
                        icon = Icons.Filled.LocationOn,
                        modifier = Modifier.fillMaxWidth()
                    )
                }
            }
        }
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Box(Modifier.weight(1f)) {
                if (relationshipStage.isNotBlank()) {
                    GalgameTagChip(
                        text = clampTag(relationshipStage),
                        backgroundColor = palette.tagRelBg,
                        contentColor = palette.tagRel,
                        icon = Icons.Filled.People,
                        modifier = Modifier.fillMaxWidth()
                    )
                }
            }
            Box(Modifier.weight(1f)) {
                if (mood.isNotBlank()) {
                    GalgameTagChip(
                        text = clampTag(mood),
                        backgroundColor = palette.tagMoodBg,
                        contentColor = palette.tagMood,
                        icon = Icons.Filled.EmojiEmotions,
                        modifier = Modifier.fillMaxWidth()
                    )
                }
            }
        }
    }
}

@Composable
private fun GalgameTagChip(
    text: String,
    backgroundColor: Color,
    contentColor: Color,
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    modifier: Modifier = Modifier
) {
    val shape = RoundedCornerShape(12.dp)
    Row(
        modifier = modifier
            .background(backgroundColor, shape)
            .border(1.dp, contentColor.copy(alpha = 0.35f), shape)
            .padding(horizontal = 10.dp, vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(4.dp)
    ) {
        Icon(
            imageVector = icon,
            contentDescription = null,
            tint = contentColor,
            modifier = Modifier.size(16.dp)
        )
        Text(
            text = text,
            style = MaterialTheme.typography.bodyMedium,
            color = contentColor,
            maxLines = 1
        )
    }
}

/**
 * 回到底部浮动按钮——独立 Composable。
 * 内部维护 debounced 可见状态，其变化仅触发此 Composable 重组，不会波及 ChatScreen。
 */

private fun parseSimpleMarkdown(text: String): AnnotatedString = buildAnnotatedString {
    var i = 0
    val len = text.length
    while (i < len) {
        when {
            i + 3 < len && text[i] == '*' && text[i + 1] == '*' -> {
                val close = text.indexOf("**", i + 2)
                if (close > i + 2) {
                    withStyle(SpanStyle(fontWeight = FontWeight.Bold)) {
                        append(text.substring(i + 2, close))
                    }
                    i = close + 2
                } else { append(text[i]); i++ }
            }
            text[i] == '*' -> {
                val close = text.indexOf('*', i + 1)
                if (close > i + 1 && !(close + 1 < len && text[close + 1] == '*')) {
                    withStyle(SpanStyle(fontStyle = FontStyle.Italic)) {
                        append(text.substring(i + 1, close))
                    }
                    i = close + 1
                } else { append(text[i]); i++ }
            }
            i + 3 < len && text[i] == '~' && text[i + 1] == '~' -> {
                val close = text.indexOf("~~", i + 2)
                if (close > i + 2) {
                    withStyle(SpanStyle(textDecoration = TextDecoration.LineThrough)) {
                        append(text.substring(i + 2, close))
                    }
                    i = close + 2
                } else { append(text[i]); i++ }
            }
            else -> { append(text[i]); i++ }
        }
    }
}

/** 带彩色边框且可折叠的场景区块（环境/身体/心理/第三者，与 Web 折叠行为对齐） */
@Composable
private fun GalgameColoredSection(
    title: String,
    annotated: AnnotatedString,
    textColor: Color,
    borderColor: Color,
    italic: Boolean = false,
    initiallyCollapsed: Boolean = false,
    showBody: Boolean = true
) {
    var collapsed by remember { mutableStateOf(initiallyCollapsed) }
    Column(modifier = Modifier
        .fillMaxWidth()
        .border(1.dp, borderColor, RoundedCornerShape(8.dp))
        .clickable { collapsed = !collapsed }
        .padding(horizontal = 10.dp, vertical = 8.dp)
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(
                text = title,
                style = MaterialTheme.typography.labelSmall,
                color = textColor.copy(alpha = 0.7f)
            )
            Icon(
                imageVector = if (collapsed) Icons.Filled.KeyboardArrowDown else Icons.Filled.KeyboardArrowUp,
                contentDescription = null,
                tint = textColor.copy(alpha = 0.7f),
                modifier = Modifier.size(16.dp)
            )
        }
        if (!collapsed && showBody) {
            Text(
                text = annotated,
                color = textColor,
                fontSize = AppFontSizes.defaultBodySmall.sp,
                fontStyle = if (italic) FontStyle.Italic else FontStyle.Normal,
                lineHeight = (AppFontSizes.defaultBodySmall * 1.5f).sp,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(top = 4.dp)
            )
        }
    }
}

/** 可折叠的场景区块（分数变化理由等） */
@Composable
private fun GalgameCollapsibleSection(title: String, annotated: AnnotatedString) {
    var collapsed by remember { mutableStateOf(true) }
    Column(modifier = Modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .clickable { collapsed = !collapsed }
                .padding(vertical = 4.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(
                text = title,
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            Icon(
                if (collapsed) Icons.Filled.KeyboardArrowDown else Icons.Filled.KeyboardArrowUp,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.size(16.dp)
            )
        }
        if (!collapsed) {
            Text(
                text = annotated,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                fontSize = AppFontSizes.defaultCaption.sp,
                lineHeight = (AppFontSizes.defaultCaption * 1.5f).sp,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(bottom = 4.dp)
            )
        }
        HorizontalDivider(color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.1f))
    }
}

/**
 * 可折叠的列表型场景区块（记忆标签 / 更多状态 / 事件标记）。
 * 原始字符串按换行拆分后用原生 Column+Text 渲染，解决 MarkdownText 对
 * 多行列表排版不整齐（行首对齐偏移）及性能开销问题。
 */
@Composable
private fun GalgameCollapsibleSectionItems(title: String, body: String) {
    val items = remember(body) {
        body.split("\n").map { it.trim().removePrefix("• ").removePrefix("- ").trim() }
            .filter { it.isNotBlank() }
    }
    val isEventFlagsSection = title == "事件标记"
    if (items.isEmpty()) return
    var collapsed by remember { mutableStateOf(true) }
    Column(modifier = Modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .clickable { collapsed = !collapsed }
                .padding(vertical = 4.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    text = title,
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                Spacer(Modifier.width(4.dp))
                Text(
                    text = "(${items.size})",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.55f)
                )
            }
            Icon(
                if (collapsed) Icons.Filled.KeyboardArrowDown else Icons.Filled.KeyboardArrowUp,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.size(16.dp)
            )
        }
        if (!collapsed) {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(bottom = 4.dp),
                verticalArrangement = Arrangement.spacedBy(3.dp)
            ) {
                items.forEach { item ->
                    val eventLine = if (isEventFlagsSection) {
                        val idx = item.indexOf(':')
                        if (idx > 0) {
                            val keyPart = item.substring(0, idx + 1).trimEnd()
                            val rawValue = item.substring(idx + 1).trim()
                            Triple(keyPart, rawValue, rawValue == "是" || rawValue == "否")
                        } else null
                    } else null
                    Row(
                        verticalAlignment = Alignment.Top,
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Text(
                            text = "•",
                            color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.7f),
                            style = MaterialTheme.typography.bodySmall.copy(fontSize = AppFontSizes.defaultCaption.sp),
                            modifier = Modifier.padding(end = 6.dp)
                        )
                        Text(
                            text = if (eventLine != null && eventLine.third) {
                                buildAnnotatedString {
                                    append(eventLine.first)
                                    append(" ")
                                    withStyle(
                                        style = SpanStyle(
                                            color = if (eventLine.second == "是") Color(0xFF4CAF50) else Color(0xFFE53935)
                                        )
                                    ) {
                                        append(eventLine.second)
                                    }
                                }
                            } else buildAnnotatedString { append(item) },
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            style = MaterialTheme.typography.bodySmall.copy(
                                fontSize = AppFontSizes.defaultCaption.sp,
                                lineHeight = 18.sp
                            ),
                            modifier = Modifier.weight(1f)
                        )
                    }
                }
            }
        }
        HorizontalDivider(color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.1f))
    }
}

// 保留兼容旧代码的 GalgameSection（不再使用但保持编译）
@Composable
private fun GalgameSection(
    title: String,
    body: String
) {
    val annotated: AnnotatedString = remember(body) { parseSimpleMarkdown(body) }
    GalgameCollapsibleSection(title = title, annotated = annotated)
}

private fun parseGalgameFields(content: String): Map<String, String>? {
    return try {
        val j0 = org.json.JSONObject(content)
        val json = j0.optJSONObject("data") ?: j0
        fun eventFlagLabel(key: String): String = when (key.trim()) {
            "first_handhold" -> "首次牵手"
            "confessed" -> "已告白"
            "first_hug" -> "首次拥抱"
            "first_kiss" -> "首次接吻"
            "physical_intimacy" -> "亲密行为"
            "exclusive_confirmed" -> "确认专属关系"
            "trust_broken" -> "信任破裂"
            "relationship_public" -> "关系公开"
            "captivity_established" -> "拘禁关系成立"
            "coercion_explicit" -> "明确胁迫"
            "violence_inflicted" -> "造成暴力伤害"
            "torture_inflicted" -> "发生折磨虐待"
            "bloodshed_occurred" -> "出现血腥场面"
            "injury_persistent" -> "伤势持续存在"
            "corpse_present" -> "场景出现尸体"
            "escape_attempted" -> "尝试逃脱"
            else -> key
        }
        val memoryTags = json.optJSONArray("memory_tags")?.let { arr ->
            buildString {
                for (i in 0 until arr.length()) {
                    val v = arr.optString(i).trim()
                    if (v.isNotBlank()) append("• ").append(v).append('\n')
                }
            }.trim()
        }.orEmpty()
        val eventFlags = json.optJSONObject("event_flags")?.let { flags ->
            flags.keys().asSequence().joinToString("\n") { key ->
                val raw = flags.opt(key)
                val value = when (raw) {
                    is Boolean -> if (raw) "是" else "否"
                    else -> raw?.toString().orEmpty()
                }
                "• ${eventFlagLabel(key)}: $value"
            }
        }.orEmpty()
        // 更多状态：优先取顶层 more_state 字符串，否则从 6 个子字段合成（与 Web buildMoreStateRows 对齐）
        fun buildMoreState(src: org.json.JSONObject): String {
            val direct = src.optString("more_state").trim()
            if (direct.isNotBlank()) return direct
            val labels = listOf(
                "character_race"   to "角色种族",
                "character_gender" to "角色性别",
                "character_outfit" to "角色衣着",
                "character_pose"   to "角色姿势",
                "character_position" to "角色位置",
                "character_action" to "角色动作",
                "player_race"      to "玩家种族",
                "player_gender"    to "玩家性别",
                "player_outfit"    to "玩家衣着",
                "player_pose"      to "玩家姿势",
                "player_position"  to "玩家位置",
                "player_action"    to "玩家动作"
            )
            return labels.mapNotNull { (key, label) ->
                val v = src.optString(key).trim()
                if (v.isNotBlank()) "• $label: $v" else null
            }.joinToString("\n")
        }

        val scene = json.optJSONObject("scene")
        if (scene != null) {
            return mapOf(
                "time" to scene.optString("time"),
                "location" to scene.optString("location"),
                "relationship_stage" to json.optString("relationship_stage"),
                "mood" to json.optString("mood"),
                "env" to scene.optString("env"),
                "body_state" to scene.optString("body_state"),
                "thought" to scene.optString("thoughts"),
                "third_party" to scene.optString("third_party_dialogue").let { if (it.isNullOrBlank() || it.equals("null", true) || it.equals("none", true)) "" else it },
                "dialogue" to scene.optString("response"),
                "memory_tags" to memoryTags,
                "more_state" to buildMoreState(json),
                "event_flags" to eventFlags,
                "score_delta_reason" to json.optString("score_delta_reason"),
                "text" to json.optString("text")
            )
        }
        mapOf(
            "time" to json.optString("time"),
            "location" to json.optString("location"),
            "relationship_stage" to json.optString("relationship_stage"),
            "mood" to json.optString("mood"),
            "env" to json.optString("env"),
            "body_state" to json.optString("body_state"),
            "thought" to json.optString("thought"),
            "third_party" to json.optString("third_party"),
            "dialogue" to json.optString("dialogue"),
            "memory_tags" to memoryTags,
            "more_state" to buildMoreState(json),
            "event_flags" to eventFlags,
            "score_delta_reason" to json.optString("score_delta_reason"),
            "text" to json.optString("text")
        )
    } catch (_: Exception) {
        null
    }
}

/** 从 galgame 场景 HTML（gal-scene-* / galgame-scene-container）中提取各区块文本，供本端展示与折叠逻辑使用。 */
internal fun parseGalgameFromHtml(content: String): Map<String, String>? {
    if (!content.contains("gal-scene-") && !content.contains("galgame-scene-container")) return null
    val map = mutableMapOf<String, String>()
    val blockRegex = Regex("""<div\s+class="([^"]*gal-scene-[^"]*)"[^>]*>([\s\S]*?)</div>""", setOf(RegexOption.IGNORE_CASE))
    blockRegex.findAll(content).forEach { match ->
        val className = match.groupValues[1]
        var text = match.groupValues[2]
            .replace(Regex("""<[^>]+>"""), " ")
            .replace("&quot;", "\"")
            .replace("&amp;", "&")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&#39;", "'")
            .trim()
        when {
            className.contains("gal-scene-env") -> map["env"] = text
            className.contains("gal-scene-thought") -> map["thought"] = text
            className.contains("gal-scene-speech") -> map["dialogue"] = text
            className.contains("gal-scene-body-state") -> map["body_state"] = text
            className.contains("gal-scene-third-party") -> map["third_party"] = text
        }
    }
    val timeTag = Regex("""<span\s+class="[^"]*gal-time-tag[^"]*"[^>]*>[\s\S]*?<span\s+class="gal-tag-text"[^>]*>([^<]*)</span>""").find(content)
    val locTag = Regex("""<span\s+class="[^"]*gal-loc-tag[^"]*"[^>]*>[\s\S]*?<span\s+class="gal-tag-text"[^>]*>([^<]*)</span>""").find(content)
    val relTag = Regex("""<span\s+class="[^"]*gal-rel-tag[^"]*"[^>]*>[\s\S]*?<span\s+class="gal-tag-text"[^>]*>([^<]*)</span>""").find(content)
    val moodTag = Regex("""<span\s+class="[^"]*gal-mood-tag[^"]*"[^>]*>[\s\S]*?<span\s+class="gal-tag-text"[^>]*>([^<]*)</span>""").find(content)
    timeTag?.groupValues?.getOrNull(1)?.trim()?.let { if (it.isNotBlank()) map["time"] = it }
    locTag?.groupValues?.getOrNull(1)?.trim()?.let { if (it.isNotBlank()) map["location"] = it }
    relTag?.groupValues?.getOrNull(1)?.trim()?.let { if (it.isNotBlank()) map["relationship_stage"] = it }
    moodTag?.groupValues?.getOrNull(1)?.trim()?.let { if (it.isNotBlank()) map["mood"] = it }
    val scoreReason = Regex("""<div\s+class="gal-score-reason"[^>]*>([\s\S]*?)</div>""").find(content)
    scoreReason?.groupValues?.getOrNull(1)?.let { raw ->
        val t = raw.replace(Regex("""<[^>]+>"""), " ").replace("&quot;", "\"").trim()
        if (t.isNotBlank()) map["score_delta_reason"] = t
    }
    val memoryTagsDiv = Regex("""<div\s+class="gal-memory-tags"[^>]*>([\s\S]*?)</div>""").find(content)
    memoryTagsDiv?.groupValues?.getOrNull(1)?.let { raw ->
        val tags = Regex("""<span\s+class="gal-memory-tag-item"[^>]*>([^<]*)</span>""").findAll(raw).map { it.groupValues[1].trim() }.filter { it.isNotBlank() }
        val joined = tags.joinToString("\n") { "• $it" }
        if (joined.isNotBlank()) map["memory_tags"] = joined
    }
    if (map.isEmpty()) return null
    return map
}

/** 从 [rawContent] 整包 JSON 构建场景解析结果；服务端不再下发 sceneMetadata。 */
internal fun buildGalgameParsedFromMetadata(rawContent: String?): Map<String, String>? {
    val raw = rawContent?.trim()?.takeIf { it.isNotBlank() } ?: return null
    return parseGalgameFields(raw)
}

// ==================== 胜利庆祝 ====================

/**
 * 纸屑粒子。坐标、速度均以"画布归一化"单位（0-1）表示，动画周期 CONFETTI_CYCLE_MS。
 * 炮口粒子：从左下/右下角射出，受重力弧线下落，循环后重置。
 * 飘落粒子：从顶部随机位置缓缓飘落，带左右摇摆。
 *
 * @param x0   初始归一化 X
 * @param y0   初始归一化 Y
 * @param vx   每周期归一化 X 速度（+ 向右）
 * @param vy   每周期归一化 Y 速度（- 向上）
 * @param grav 每周期² 的重力加速度（向下为正）
 * @param sway 横向正弦摆动幅度（归一化，飘落粒子用）
 * @param delay 相位延迟 0-1（错开出发时间）
 * @param w    粒子宽度 px
 * @param h    粒子高度 px
 * @param rotOffset 初始旋转角度 deg
 * @param rotSpeed  每周期旋转角速度 deg
 * @param color 颜色
 * @param isCircle 是否画圆形
 */
