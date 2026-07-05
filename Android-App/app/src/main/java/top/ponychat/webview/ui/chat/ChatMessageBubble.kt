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
import android.media.MediaPlayer
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
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.*
import androidx.compose.animation.core.*
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.Image
import androidx.compose.foundation.gestures.animateScrollBy
import androidx.compose.foundation.gestures.scrollBy
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
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
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.geometry.CornerRadius
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
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogWindowProvider
import androidx.compose.ui.window.DialogProperties
import androidx.compose.ui.window.Popup
import androidx.compose.ui.window.PopupPositionProvider
import androidx.compose.ui.unit.IntRect
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.platform.LocalClipboardManager
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
import coil.compose.AsyncImagePainter
import coil.compose.rememberAsyncImagePainter
import coil.imageLoader
import coil.request.ImageRequest
import io.noties.markwon.Markwon
import io.noties.markwon.ext.strikethrough.StrikethroughPlugin
import io.noties.markwon.ext.tables.TablePlugin
import io.noties.markwon.linkify.LinkifyPlugin
import kotlin.math.max
import kotlin.math.min
import kotlin.math.pow
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
import top.ponychat.webview.audio.MobileVoiceEffect
import top.ponychat.webview.data.model.Character
import top.ponychat.webview.data.model.GalgameOptionItem
import top.ponychat.webview.data.model.ModelInfo
import top.ponychat.webview.data.model.Message
import top.ponychat.webview.data.model.MessageVoiceState
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.ui.character.CharacterAvatar
import top.ponychat.webview.ui.common.PonyAvatar
import top.ponychat.webview.ui.common.PonyPromptBubble
import top.ponychat.webview.ui.common.WheelStringColumn
import top.ponychat.webview.ui.common.adaptivePopupMenuBorder
import top.ponychat.webview.ui.common.adaptivePopupMenuContainerColor
import top.ponychat.webview.ui.common.adaptivePopupMenuContentColor
import top.ponychat.webview.ui.common.adaptivePopupMenuDangerColor
import top.ponychat.webview.ui.common.resolveAvatarUrlForApi
import top.ponychat.webview.ui.settings.CrisisHotlineDialog
import top.ponychat.webview.ui.theme.*
import top.ponychat.webview.util.ChatEventBus
import androidx.compose.ui.text.TextLayoutResult
import java.io.ByteArrayOutputStream
import java.io.File
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Date
import java.util.Locale


// ==================== 消息气泡 ====================

@Composable
internal fun LastAssistantMessageBubble(
    viewModel: ChatViewModel,
    message: Message,
    characterName: String,
    characterAvatarUrl: String,
    userAvatarUrl: String,
    userName: String = "我",
    apiBase: String,
    mode: String,
    isOverallLast: Boolean,
    isStreaming: Boolean,
    showTimestamp: Boolean,
    timestampNow: Long = System.currentTimeMillis(),
    validMentionNames: Set<String> = emptySet(),
    onNavigateToEditCharacter: () -> Unit,
    onMentionCharacter: (() -> Unit)? = null,
    onNavigateToSettings: () -> Unit,
    onCopy: () -> Unit,
    onDelete: () -> Unit,
    onEdit: ((String) -> Unit)?,
    onSelectOption: ((String) -> Unit)?,
    onFillOption: ((String) -> Unit)?,
    onImagePreview: ((String) -> Unit)?,
    onRegenerate: (() -> Unit)?,
    onActionBarVisible: (suspend () -> Unit)? = null,
    revealGradually: Boolean = false,
    onParagraphRevealed: (() -> Unit)? = null,
    onVoiceTranscriptLayout: ((Float) -> Unit)? = null,
    onVoiceTranscriptOpened: (() -> Unit)? = null,
    isVoiceTranscriptVisible: Boolean = false,
    onVoiceTranscriptVisibilityChange: (Boolean) -> Unit = {},
    onQuote: (() -> Unit)? = null,
    onJumpToQuotedMessage: ((String) -> Unit)? = null,
    onRetract: (() -> Unit)? = null,
    onRetractEdit: (() -> Unit)? = null,
    activeSelectionKey: String? = null,
    onActiveSelectionKeyChange: (String?) -> Unit = {},
    onContextActionTriggered: () -> Unit = {}
) {
    val timerState by viewModel.timerState.collectAsState()
    val (replyTimer, retryCount, isTimerRunning) = timerState
    MessageBubble(
        message = message,
        characterName = characterName,
        characterAvatarUrl = characterAvatarUrl,
        userAvatarUrl = userAvatarUrl,
        userName = userName,
        apiBase = apiBase,
        mode = mode,
        isLast = isOverallLast,
        isStreaming = isStreaming,
        showTimestamp = showTimestamp,
        timestampNow = timestampNow,
        validMentionNames = validMentionNames,
        // isTimerRunning=false 时传 0L：timerState 每秒仍更新，但不在气泡上显示计时
        // 避免 replyTimer 每秒变化强制 MessageBubble 重组（每个 streaming 轮 4-N 次）
        replyTimer = if (isTimerRunning) replyTimer else 0L,
        retryCount = retryCount,
        isTimerRunning = isTimerRunning,
        onNavigateToEditCharacter = onNavigateToEditCharacter,
        onMentionCharacter = onMentionCharacter,
        onNavigateToSettings = onNavigateToSettings,
        onCopy = onCopy,
        onDelete = onDelete,
        onEdit = onEdit,
        onSelectOption = onSelectOption,
        onFillOption = onFillOption,
        onImagePreview = onImagePreview,
        onRegenerate = onRegenerate,
        onActionBarVisible = onActionBarVisible,
        revealGradually = revealGradually,
        onParagraphRevealed = onParagraphRevealed,
        onVoiceTranscriptLayout = onVoiceTranscriptLayout,
        onVoiceTranscriptOpened = onVoiceTranscriptOpened,
        isVoiceTranscriptVisible = isVoiceTranscriptVisible,
        onVoiceTranscriptVisibilityChange = onVoiceTranscriptVisibilityChange,
        onQuote = onQuote,
        onJumpToQuotedMessage = onJumpToQuotedMessage,
        onRetract = onRetract,
        onRetractEdit = onRetractEdit,
        activeSelectionKey = activeSelectionKey,
        onActiveSelectionKeyChange = onActiveSelectionKeyChange,
        onContextActionTriggered = onContextActionTriggered
    )
}

@OptIn(ExperimentalFoundationApi::class, ExperimentalLayoutApi::class)
@Suppress("UNUSED_PARAMETER")
@Composable
fun MessageBubble(
    message: Message,
    characterName: String,
    characterAvatarUrl: String,
    userAvatarUrl: String,
    userName: String = "我",
    apiBase: String,
    mode: String = "normal",
    isLast: Boolean = false,
    isStreaming: Boolean = false,
    showTimestamp: Boolean = true,
    timestampNow: Long = System.currentTimeMillis(),
    validMentionNames: Set<String> = emptySet(),
    replyTimer: Long = 0,
    retryCount: Int = 0,
    isTimerRunning: Boolean = false,
    onNavigateToEditCharacter: () -> Unit = {},
    onMentionCharacter: (() -> Unit)? = null,
    onNavigateToSettings: () -> Unit = {},
    onCopy: () -> Unit,
    onDelete: () -> Unit,
    onEdit: ((String) -> Unit)? = null,
    onSelectOption: ((String) -> Unit)? = null,
    onFillOption: ((String) -> Unit)? = null,
    onImagePreview: ((String) -> Unit)? = null,
    onRegenerate: (() -> Unit)? = null,
    /** streaming 结束后，操作栏淡入动画完成后回调，用于触发滚到底部 */
    onActionBarVisible: (suspend () -> Unit)? = null,
    /** 新消息首次出现时逐段延迟展开气泡，模拟打字节奏；历史消息为 false */
    revealGradually: Boolean = false,
    /** 每次新段落展开后回调，用于外层触发跟随滚动 */
    onParagraphRevealed: (() -> Unit)? = null,
    /** 语音识别结果卡片布局变化后回调，外层据此避让底部输入栏。 */
    onVoiceTranscriptLayout: ((Float) -> Unit)? = null,
    /** 语音识别结果展开时回调，外层重置本次避让状态。 */
    onVoiceTranscriptOpened: (() -> Unit)? = null,
    isVoiceTranscriptVisible: Boolean = false,
    onVoiceTranscriptVisibilityChange: (Boolean) -> Unit = {},
    onQuote: (() -> Unit)? = null,
    onJumpToQuotedMessage: ((String) -> Unit)? = null,
    /** 用户消息撤回回调；仅 2 分钟内的用户消息可用，由外部传入 null 表示不支持 */
    onRetract: (() -> Unit)? = null,
    onRetractEdit: (() -> Unit)? = null,
    activeSelectionKey: String? = null,
    onActiveSelectionKeyChange: (String?) -> Unit = {},
    onRetryPendingAccept: (() -> Unit)? = null,
    onContextActionTriggered: () -> Unit = {}
) {
    val isUser = message.isUser()
    val haptic = LocalHapticFeedback.current
    val context = LocalContext.current
    val clipboardManager = LocalClipboardManager.current
    val debugSettings = LocalDebugSettings.current
    val actionMenuTextColor = actionMenuContentColor()
    val actionMenuDeleteColor = actionMenuDangerColor()
    // 游戏/锁分模式：助手优先展示 displayContent；若其缺少场景 HTML 或 content 含完整 gal-*（服务端/重装后仅有 content 时常见），须用 content，否则整段不渲染。
    val contentToShow = remember(message, mode, message.content, message.displayContent) {
        if (!message.isAssistant() || !mode.startsWith("galgame")) {
            message.content
        } else {
            val c = message.content.trim()
            val d = message.displayContent?.trim()?.takeIf { it.isNotBlank() }
            val hasGalHtml: (String) -> Boolean = { s ->
                s.contains("gal-scene-") || s.contains("galgame-scene-container")
            }
            when {
                d != null && hasGalHtml(d) -> d
                hasGalHtml(c) -> c
                d != null -> d
                else -> c
            }
        }
    }
    val parsed = remember(contentToShow) { parseMessageContent(contentToShow) }
    // 游戏/锁分模式：优先用消息自带的 galgameOptions，否则从 rawContent（整块 JSON）或 content 解析 suggested_options
    val galOptions = remember(message, mode) {
        if (!mode.startsWith("galgame") || !message.isAssistant()) return@remember emptyList<GalgameOption>()
        if (message.galgameOptions.isNotEmpty()) {
            message.galgameOptions.map { GalgameOption(label = it.label, type = it.type, tone = it.tone) }
        } else {
            val fromHtml = parseGalgameOptions(message.content)
            if (fromHtml.isNotEmpty()) fromHtml
            else message.rawContent?.trim()?.takeIf { it.isNotBlank() }?.let { parseGalgameOptions(it) } ?: emptyList()
        }
    }
    val galgameParsedOverride = remember(message, contentToShow) {
        if (!message.isAssistant()) return@remember null
        // 重装/历史接口有时只回 content 整包 JSON、rawContent 空：用 content 作 JSON 兜底，否则无对白可解析
        val effectiveRaw = message.rawContent?.trim()?.takeIf { it.isNotBlank() }
            ?: message.content.trim().takeIf { it.startsWith("{") }
        val fromMeta = buildGalgameParsedFromMetadata(effectiveRaw)
        // 勿只看 contentToShow：若 displayContent 为无标签片段而完整 HTML 在 content 中，会漏解析对白（重装后从服务端拉取常见）
        val htmlSource = sequenceOf(contentToShow, message.content, message.displayContent.orEmpty())
            .map { it.trim() }
            .firstOrNull { it.contains("gal-scene-") || it.contains("galgame-scene-container") }
        val fromHtml = htmlSource?.let { parseGalgameFromHtml(it) }
        val result = when {
            fromMeta != null && fromHtml != null -> (fromMeta.toMutableMap()).apply { fromHtml.forEach { k, v -> if (v.isNotBlank()) put(k, v) } }
            fromMeta != null -> fromMeta
            fromHtml != null -> fromHtml
            else -> null
        }
        result
    }
    LaunchedEffect(message.id, message.isStreaming, isLast) {
        if (message.isStreaming || !isLast) return@LaunchedEffect
        delay(350)
        onActionBarVisible?.invoke()
    }
    val stickerAttachments = remember(message.attachments) {
        message.attachments.filter { it.type == "sticker" || it.type == "emoji_asset" }
    }
    var showContentActionMenu by remember(message.id) { mutableStateOf(false) }
    var contentActionMenuPosition by remember(message.id) { mutableStateOf(IntOffset.Zero) }
    fun openContentActionMenu(topLeft: Offset, size: IntSize) {
        onContextActionTriggered()
        haptic.performHapticFeedback(HapticFeedbackType.LongPress)
        contentActionMenuPosition = IntOffset(
            (topLeft.x + size.width / 2f).roundToInt(),
            (topLeft.y + size.height / 2f).roundToInt()
        )
        showContentActionMenu = true
    }
    @Composable
    fun PendingAcceptIndicatorAnchor(modifier: Modifier = Modifier) {
        if (mode == "normal" && message.isUser() && message.isPendingServerAccept && !message.isRetracted) {
            PendingUserMessageAcceptIndicator(
                startedAt = message.pendingServerAcceptStartedAt.takeIf { it > 0L } ?: message.timestamp,
                onRetry = onRetryPendingAccept,
                modifier = modifier
            )
        }
    }
    @Composable
    fun ChatMediaThumb(
        model: String,
        contentDescription: String,
        contentScale: ContentScale,
        fixedSize: Dp? = null,
    ) {
        var thumbTopLeft by remember(model) { mutableStateOf(Offset.Zero) }
        var thumbSize by remember(model) { mutableStateOf(IntSize.Zero) }
        val painter = rememberAsyncImagePainter(rememberThumbnailImageRequest(model))
        val drawable = (painter.state as? AsyncImagePainter.State.Success)?.result?.drawable
        val width: Dp
        val height: Dp
        if (fixedSize != null) {
            width = fixedSize
            height = fixedSize
        } else {
            val intrinsicW = drawable?.intrinsicWidth?.takeIf { it > 0 } ?: 1
            val intrinsicH = drawable?.intrinsicHeight?.takeIf { it > 0 } ?: 1
            val aspect = (intrinsicW.toFloat() / intrinsicH.toFloat()).coerceIn(0.25f, 4f)
            val maxSide = 100.dp
            width = if (aspect >= 1f) maxSide else maxSide * aspect
            height = if (aspect >= 1f) maxSide / aspect else maxSide
        }
        Box(
            modifier = Modifier
                .size(width = width, height = height)
                .clip(RoundedCornerShape(16.dp))
                .onGloballyPositioned { coords ->
                    thumbTopLeft = coords.positionInWindow()
                    thumbSize = coords.size
                }
                .combinedClickable(
                    onClick = { onImagePreview?.invoke(model) },
                    onLongClick = { openContentActionMenu(thumbTopLeft, thumbSize) }
                )
        ) {
            Image(
                painter = painter,
                contentDescription = contentDescription,
                contentScale = contentScale,
                modifier = Modifier.fillMaxSize()
            )
        }
    }
    @Composable
    fun StickerAttachmentStrip(horizontalAlignment: Alignment.Horizontal) {
        if (stickerAttachments.isEmpty()) return
        Column(horizontalAlignment = horizontalAlignment) {
            stickerAttachments.forEach { att ->
                val stickerUrl = att.url ?: att.assetId?.let { "/api/admin/assets/$it/file" }
                    ?: att.userStickerId?.let { "/api/assets/stickers/$it/file" }
                if (!stickerUrl.isNullOrBlank()) {
                    ChatMediaThumb(
                        model = stickerUrl,
                        contentDescription = att.name.ifBlank { "表情" },
                        contentScale = ContentScale.Fit
                    )
                }
            }
        }
    }
    @Composable
    fun MessageImageGrid(
        urls: List<String>,
        horizontalAlignment: Alignment.Horizontal,
        modifier: Modifier = Modifier,
        contentDescription: String,
    ) {
        if (urls.isEmpty()) return
        val useSquareGrid = mode == "normal"
        val horizontalSpacing = if (useSquareGrid) 6.dp else 4.dp
        val verticalSpacing = horizontalSpacing
        val displayUrls = if (useSquareGrid) urls.take(4) else urls
        val thumbSide = if (useSquareGrid) {
            val configuration = LocalConfiguration.current
            val maxBubbleWidth = (configuration.screenWidthDp.dp * 0.94f - 96.dp).coerceAtLeast(168.dp)
            (maxBubbleWidth - horizontalSpacing) / 2f
        } else {
            null
        }
        val rowArrangement = if (horizontalAlignment == Alignment.End) {
            Arrangement.End
        } else {
            Arrangement.Start
        }
        Row(
            modifier = modifier.fillMaxWidth(),
            horizontalArrangement = rowArrangement
        ) {
            if (thumbSide != null) {
                val gridWidth = thumbSide * 2f + horizontalSpacing
                val isUserSide = horizontalAlignment == Alignment.End
                @Composable
                fun SquareImageRow(rowUrls: List<String>, alignSingleToEnd: Boolean) {
                    val arrangement = when {
                        rowUrls.size <= 1 && alignSingleToEnd -> Arrangement.End
                        rowUrls.size <= 1 -> Arrangement.Start
                        else -> Arrangement.spacedBy(horizontalSpacing)
                    }
                    Row(
                        modifier = Modifier.width(gridWidth),
                        horizontalArrangement = arrangement
                    ) {
                        rowUrls.forEach { url ->
                            ChatMediaThumb(
                                model = url,
                                contentDescription = contentDescription,
                                contentScale = ContentScale.Crop,
                                fixedSize = thumbSide
                            )
                        }
                    }
                }
                val rows = if (displayUrls.size <= 2) {
                    listOf(if (isUserSide) displayUrls.reversed() else displayUrls)
                } else if (isUserSide) {
                    listOf(
                        listOfNotNull(displayUrls.getOrNull(3), displayUrls.getOrNull(2)),
                        listOfNotNull(displayUrls.getOrNull(1), displayUrls.getOrNull(0))
                    )
                } else {
                    listOf(
                        listOfNotNull(displayUrls.getOrNull(2), displayUrls.getOrNull(3)),
                        listOfNotNull(displayUrls.getOrNull(0), displayUrls.getOrNull(1))
                    )
                }
                Column(
                    modifier = Modifier.width(gridWidth),
                    verticalArrangement = Arrangement.spacedBy(verticalSpacing)
                ) {
                    rows.forEach { rowUrls ->
                        SquareImageRow(rowUrls, alignSingleToEnd = isUserSide)
                    }
                }
            } else {
                FlowRow(
                    horizontalArrangement = Arrangement.spacedBy(horizontalSpacing, horizontalAlignment),
                    verticalArrangement = Arrangement.spacedBy(verticalSpacing),
                    modifier = Modifier.widthIn(max = 212.dp)
                ) {
                    displayUrls.forEach { url ->
                        ChatMediaThumb(
                            model = url,
                            contentDescription = contentDescription,
                            contentScale = ContentScale.Crop
                        )
                    }
                }
            }
        }
    }
    MessageContentActionMenu(
        expanded = showContentActionMenu,
        positionInWindow = contentActionMenuPosition,
        onDismissRequest = { showContentActionMenu = false },
        onQuote = onQuote,
        onDelete = onDelete,
        mode = mode,
        actionMenuTextColor = actionMenuTextColor,
        actionMenuDeleteColor = actionMenuDeleteColor
    )
    // ==================== 用户消息（94% 宽居中块内右对齐，与 AI 消息块左右边距对称） ====================
    if (isUser) {
        // ── 已撤回：仅显示一行居中提示，不渲染原始内容 ──
        if (message.isRetracted) {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(vertical = 6.dp),
                contentAlignment = Alignment.Center
            ) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.Center
                ) {
                    Text(
                        text = "你撤回了一条消息",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.55f)
                    )
                    if (onRetractEdit != null) {
                        Spacer(Modifier.width(8.dp))
                        Text(
                            text = "重新编辑",
                            style = MaterialTheme.typography.bodySmall.copy(fontWeight = FontWeight.Bold),
                            color = MaterialTheme.colorScheme.primary,
                            modifier = Modifier.clickable { onRetractEdit() }
                        )
                    }
                }
            }
            return
        }
        // ── 正常用户消息 ──
        Box(
            modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
            contentAlignment = Alignment.Center
        ) {
            Box(modifier = Modifier.fillMaxWidth(0.94f)) {
                // remember key 用 (id, 长度)：避免对 200KB base64 内容做 O(n) equals 比较
                val userDisplayContent = remember(
                    message.id,
                    message.content,
                    message.voiceState,
                    debugSettings.showRawContent
                ) {
                    val voice = message.voiceState
                    if (voice != null && !voice.hasLocalAudio() && !debugSettings.showRawContent) {
                        voice.readableText(message.content).takeIf { it.isNotBlank() } ?: message.content
                    } else {
                        message.content
                    }
                }
                val media = remember(message.id, userDisplayContent, context) {
                    splitUserMessageMedia(userDisplayContent, context)
                }
                val hasImages = media.imageUrls.isNotEmpty()
                val hasText = media.text.isNotBlank() || (!hasImages && userDisplayContent.isNotBlank())
                val playableUserVoiceState = message.voiceState
                    ?.takeIf { it.hasLocalAudio() && !message.isStreaming && !debugSettings.showRawContent }
                Column(
                    // start = 48dp 与右侧头像区（40dp头像 + 8dp间距）对称，
                    // 使用户气泡左边界对齐角色头像右侧，适用所有模式。
                    modifier = Modifier.fillMaxWidth().padding(start = 48.dp),
                    horizontalAlignment = Alignment.End
                ) {
                    if (hasImages) {
                        MessageImageGrid(
                            urls = media.imageUrls,
                            horizontalAlignment = Alignment.End,
                            contentDescription = "发送图片",
                            modifier = Modifier
                                .padding(bottom = 6.dp, end = 48.dp)
                        )
                    }
                    // 时间戳 + 名字：与左侧角色消息（名字 + 时间戳）形成镜像。
                    // padding(end=48dp) 保证内容右边界精准对齐气泡右边界
                    // 右 48dp = 头像40dp + 间距8dp，与气泡行右侧保留区一致，不受字体缩放影响。
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        modifier = Modifier.padding(bottom = 4.dp, end = 48.dp),
                    ) {
                        if (showTimestamp) {
                            Text(
                                text = formatMessageTime(message.timestamp, timestampNow),
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.7f)
                            )
                            Spacer(Modifier.width(8.dp))
                        }
                        Text(
                            text = userName,
                            style = MaterialTheme.typography.labelSmall.copy(fontWeight = FontWeight.Medium),
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                    Row(verticalAlignment = Alignment.Top) {
                        val userBubbleShape = RoundedCornerShape(topStart = 16.dp, topEnd = 4.dp, bottomStart = 16.dp, bottomEnd = 16.dp)
                        // 长按弹出菜单（撤回/复制/删除）
                        var showBubbleMenu by remember { mutableStateOf(false) }
                        var bubbleMenuPosition by remember(message.id) { mutableStateOf(IntOffset.Zero) }
                        val isRetractable by produceState(
                            initialValue = System.currentTimeMillis() - message.timestamp < 120_000L,
                            key1 = message.id
                        ) {
                            val remaining = 120_000L - (System.currentTimeMillis() - message.timestamp)
                            if (remaining > 0) { delay(remaining); value = false }
                        }
                        if (playableUserVoiceState != null) {
                            Box(modifier = Modifier.weight(1f, fill = false)) {
                                UserVoiceMessageBubble(
                                    message = message,
                                    voiceState = playableUserVoiceState,
                                    actionMenuTextColor = actionMenuTextColor,
                                    actionMenuDeleteColor = actionMenuDeleteColor,
                                    isRetractable = isRetractable,
                                    onRetract = onRetract,
                                    onDelete = onDelete,
                                    onQuote = onQuote,
                                    mode = mode,
                                    onVoiceTranscriptLayout = onVoiceTranscriptLayout,
                                    onVoiceTranscriptOpened = onVoiceTranscriptOpened,
                                    showTranscript = isVoiceTranscriptVisible,
                                    onVoiceTranscriptVisibilityChange = onVoiceTranscriptVisibilityChange,
                                    onContextActionTriggered = onContextActionTriggered
                                )
                                PendingAcceptIndicatorAnchor(
                                    Modifier
                                        .align(Alignment.BottomStart)
                                        .offset(x = (-32).dp, y = 2.dp)
                                )
                            }
                        } else if (stickerAttachments.isNotEmpty()) {
                            Box(modifier = Modifier.weight(1f, fill = false)) {
                                StickerAttachmentStrip(Alignment.End)
                                PendingAcceptIndicatorAnchor(
                                    Modifier
                                        .align(Alignment.BottomStart)
                                        .offset(x = (-32).dp, y = 2.dp)
                                )
                            }
                        } else if (hasText) {
                            // 有文字：渲染文字气泡（图片已在上方展示过，气泡内只留文字）
                            val bubbleText = media.text.ifBlank { userDisplayContent }
                            val selectionKey = "user:${message.id}:0"
                            var textLayoutResult by remember(message.id, bubbleText) { mutableStateOf<TextLayoutResult?>(null) }
                            var longPressCharOffset by remember(message.id, bubbleText) { mutableStateOf(-1) }
                            var selectionRange by remember(message.id, bubbleText) { mutableStateOf<IntRange?>(null) }
                            val isSelectingText = activeSelectionKey == selectionKey && selectionRange != null
                            Box(modifier = Modifier.weight(1f, fill = false)) {
                                Box(
                                    modifier = Modifier
                                        .shadow(4.dp, userBubbleShape, spotColor = Color(0xFF6366F1).copy(alpha = 0.2f))
                                        .clip(userBubbleShape)
                                        .background(
                                            brush = androidx.compose.ui.graphics.Brush.linearGradient(
                                                colors = listOf(Color(0xFF6366F1), Color(0xFF4F46E5))
                                            )
                                        )
                                        .padding(horizontal = 14.dp, vertical = 10.dp)
                                ) {
                                    Column {
                                        message.quotedMessage?.let { quote ->
                                            var quoteCardTopLeft by remember(message.id, quote.messageId) { mutableStateOf(Offset.Zero) }
                                            var quoteCardSize by remember(message.id, quote.messageId) { mutableStateOf(IntSize.Zero) }
                                            Surface(
                                                color = Color.White.copy(alpha = 0.14f),
                                                shape = RoundedCornerShape(8.dp),
                                                modifier = Modifier
                                                    .fillMaxWidth()
                                                    .padding(bottom = 8.dp)
                                                    .onGloballyPositioned { coords ->
                                                        quoteCardTopLeft = coords.positionInWindow()
                                                        quoteCardSize = coords.size
                                                    }
                                                    .combinedClickable(
                                                        onClick = {},
                                                        onLongClick = { openContentActionMenu(quoteCardTopLeft, quoteCardSize) }
                                                    )
                                            ) {
                                                Box(
                                                    modifier = Modifier.padding(start = 9.dp, top = 6.dp, bottom = 6.dp, end = 4.dp),
                                                ) {
                                                    Column(
                                                        modifier = Modifier
                                                            .fillMaxWidth()
                                                            .padding(end = 28.dp)
                                                    ) {
                                                        Text(
                                                            text = quote.sender.ifBlank { if (quote.role == "user") "我" else characterName },
                                                            color = Color.White.copy(alpha = 0.82f),
                                                            style = MaterialTheme.typography.labelSmall,
                                                            fontWeight = FontWeight.SemiBold,
                                                            maxLines = 1,
                                                            overflow = TextOverflow.Ellipsis
                                                        )
                                                        Text(
                                                            text = quote.content,
                                                            color = Color.White.copy(alpha = 0.72f),
                                                            style = MaterialTheme.typography.bodySmall,
                                                            maxLines = 2,
                                                            overflow = TextOverflow.Ellipsis
                                                        )
                                                    }
                                                    val targetMessageId = quote.messageId
                                                    if (!targetMessageId.isNullOrBlank() && onJumpToQuotedMessage != null) {
                                                        Box(
                                                            modifier = Modifier
                                                                .align(Alignment.TopEnd)
                                                                .width(28.dp)
                                                                .height(24.dp)
                                                                .clickable { onJumpToQuotedMessage(targetMessageId) },
                                                            contentAlignment = Alignment.TopCenter
                                                        ) {
                                                            Icon(
                                                                imageVector = Icons.Filled.ArrowUpward,
                                                                contentDescription = "跳转到引用消息",
                                                                tint = Color.White.copy(alpha = 0.8f),
                                                                modifier = Modifier.size(16.dp)
                                                            )
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                        SelectableMessageText(
                                            text = bubbleText,
                                            validMentionNames = validMentionNames,
                                            color = if (message.isError) ErrorColor else Color.White,
                                            style = MaterialTheme.typography.bodyMedium.copy(lineHeight = 22.sp),
                                            selectionRange = if (isSelectingText) selectionRange else null,
                                            onSelectionRangeChange = { selectionRange = it },
                                            onCopySelection = { selected ->
                                                clipboardManager.setText(AnnotatedString(selected))
                                                selectionRange = null
                                                onActiveSelectionKeyChange(null)
                                            },
                                            onCancelSelection = {
                                                selectionRange = null
                                                onActiveSelectionKeyChange(null)
                                            },
                                            onTextLayout = { textLayoutResult = it },
                                            onLongPress = { offset, windowOffset ->
                                                onContextActionTriggered()
                                                haptic.performHapticFeedback(HapticFeedbackType.LongPress)
                                                onActiveSelectionKeyChange(null)
                                                selectionRange = null
                                                longPressCharOffset = textLayoutResult?.getOffsetForPosition(offset) ?: -1
                                                bubbleMenuPosition = IntOffset(windowOffset.x.roundToInt(), windowOffset.y.roundToInt())
                                                showBubbleMenu = true
                                            }
                                        )
                                    }
                                }
                                PendingAcceptIndicatorAnchor(
                                    Modifier
                                        .align(Alignment.BottomStart)
                                        .offset(x = (-32).dp, y = 2.dp)
                                )
                                FingerAnchoredDropdownMenu(
                                    expanded = showBubbleMenu,
                                    onDismissRequest = { showBubbleMenu = false },
                                    positionInWindow = bubbleMenuPosition
                                ) {
                                    if (isRetractable && onRetract != null) {
                                        DropdownMenuItem(
                                            text = { Text("撤回", color = actionMenuTextColor) },
                                            leadingIcon = {
                                                @Suppress("DEPRECATION")
                                                Icon(Icons.Filled.Undo, contentDescription = null, tint = actionMenuTextColor)
                                            },
                                            onClick = { showBubbleMenu = false; onRetract() }
                                        )
                                    }
                                    DropdownMenuItem(
                                        text = { Text("复制", color = actionMenuTextColor) },
                                        leadingIcon = { Icon(Icons.Filled.ContentCopy, contentDescription = null, tint = actionMenuTextColor) },
                                        onClick = { showBubbleMenu = false; onCopy() }
                                    )
                                    if (onQuote != null && mode == "normal") {
                                        DropdownMenuItem(
                                            text = { Text("引用", color = actionMenuTextColor) },
                                            leadingIcon = { Icon(Icons.Filled.FormatQuote, contentDescription = null, tint = actionMenuTextColor) },
                                            onClick = { showBubbleMenu = false; onQuote() }
                                        )
                                    }
                                    DropdownMenuItem(
                                        text = { Text("选择", color = actionMenuTextColor) },
                                        leadingIcon = { Icon(Icons.Filled.FormatColorText, contentDescription = null, tint = actionMenuTextColor) },
                                        onClick = {
                                            showBubbleMenu = false
                                            val charOff = longPressCharOffset
                                            selectionRange = if (charOff >= 0) {
                                                findSentenceBounds(bubbleText, charOff)
                                            } else {
                                                0 until bubbleText.length
                                            }
                                            onActiveSelectionKeyChange(selectionKey)
                                        }
                                    )
                                    DropdownMenuItem(
                                        text = { Text("删除", color = actionMenuDeleteColor) },
                                        leadingIcon = { Icon(Icons.Filled.Delete, contentDescription = null, tint = actionMenuDeleteColor) },
                                        onClick = { showBubbleMenu = false; onDelete() }
                                    )
                                }
                            }
                        } else {
                            Box(
                                modifier = Modifier
                                    .weight(1f, fill = false)
                                    .height(40.dp)
                            ) {
                                PendingAcceptIndicatorAnchor(
                                    Modifier
                                        .align(Alignment.BottomStart)
                                        .offset(x = (-32).dp, y = 2.dp)
                                )
                            }
                        }
                        Spacer(Modifier.width(8.dp))
                        Box(modifier = Modifier.clickable { onNavigateToSettings() }) {
                            PonyStyleAvatar(
                                avatarUrl = userAvatarUrl,
                                name = userName,
                                apiBase = apiBase,
                                size = 40
                            )
                        }
                    }
                    // 调试：显示消息 ID
                    if (debugSettings.showMessageIds && message.id.isNotBlank()) {
                        Text(
                            text = "ID: ${message.id}",
                            style = MaterialTheme.typography.labelSmall.copy(fontFamily = androidx.compose.ui.text.font.FontFamily.Monospace),
                            color = Color(0xFFF97316).copy(alpha = 0.7f),
                            modifier = Modifier.padding(end = 48.dp, top = 2.dp)
                        )
                    }
                }
            }
        }
    } else {
        Box(modifier = Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
            Column(
                modifier = Modifier
                    .fillMaxWidth(0.94f)
                    .padding(vertical = 4.dp)
            ) {
                if (mode.startsWith("galgame")) {
                    // ==================== AI 消息 - 游戏/锁分模式（全宽，无气泡，头像+名字同行居中） ====================
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(10.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Box(modifier = Modifier.clickable { onNavigateToEditCharacter() }) {
                            PonyStyleAvatar(
                                avatarUrl = characterAvatarUrl,
                                name = characterName,
                                apiBase = apiBase,
                                size = 40
                            )
                        }
                        Row(
                            modifier = Modifier.weight(1f),
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Text(
                                text = characterName,
                                style = MaterialTheme.typography.labelSmall.copy(fontWeight = FontWeight.Medium),
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                            if (showTimestamp) {
                                val timeLabel = formatAssistantHeaderTime(message.timestamp, timestampNow)
                                val durationLabel = formatGenerationDuration(message.generationDurationMs)
                                Text(
                                    text = if (durationLabel != null) "$timeLabel $durationLabel" else timeLabel,
                                    style = MaterialTheme.typography.labelSmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.7f)
                                )
                            }
                            if (isLast && message.isAssistant()) {
                                if (isTimerRunning && mode != "normal") {
                                    Text(
                                        text = "${replyTimer / 1000}s",
                                        style = MaterialTheme.typography.labelSmall,
                                        color = Primary
                                    )
                                }
                            }
                        }
                    }
                    Spacer(Modifier.height(6.dp))

                    // 内容区：全宽，无气泡背景
                    Column(modifier = Modifier.fillMaxWidth()) {
                        Box(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(start = 0.dp, end = 4.dp, top = 10.dp, bottom = 10.dp)
                        ) {
                            if (message.isStreaming && message.content.isEmpty()) {
                                GeminiTypingIndicator()
                            } else {
                                Column(modifier = Modifier.fillMaxWidth()) {
                                    StickerAttachmentStrip(Alignment.Start)
                                    val finalContent = if (message.isAssistant()) contentToShow
                                        else (parsed.mainContent.ifBlank { message.content })
                                    val media = remember(message.id, finalContent, context) {
                                        splitMessageMedia(finalContent, context)
                                    }

                                    if (media.imageUrls.isNotEmpty()) {
                                        MessageImageGrid(
                                            urls = media.imageUrls,
                                            horizontalAlignment = Alignment.Start,
                                            contentDescription = "助手图片",
                                            modifier = Modifier.padding(bottom = 6.dp)
                                        )
                                    }

                                    if (!debugSettings.showRawContent) {
                                        GalgameSceneView(
                                            content = media.text.ifBlank { finalContent },
                                            textColor = if (message.isError) ErrorColor else MaterialTheme.colorScheme.onBackground,
                                            parsedOverride = galgameParsedOverride
                                        )
                                    } else if (finalContent.isNotBlank()) {
                                        val displayText = media.text.ifBlank { finalContent }
                                        val contentColor = if (message.isError) ErrorColor else MaterialTheme.colorScheme.onBackground
                                        Text(
                                            text = displayText,
                                            color = contentColor,
                                            style = MaterialTheme.typography.bodyMedium.copy(
                                                fontFamily = androidx.compose.ui.text.font.FontFamily.Monospace,
                                                lineHeight = 20.sp
                                            ),
                                            modifier = Modifier.fillMaxWidth()
                                        )
                                    }

                                    if (debugSettings.showMessageIds && message.id.isNotBlank()) {
                                        Text(
                                            text = "ID: ${message.id}",
                                            style = MaterialTheme.typography.labelSmall.copy(
                                                fontFamily = androidx.compose.ui.text.font.FontFamily.Monospace
                                            ),
                                            color = Color(0xFFF97316).copy(alpha = 0.7f),
                                            modifier = Modifier.padding(top = 4.dp)
                                        )
                                    }
                                }
                            }
                        }

                        // 流式进度指示器
                        if (message.isStreaming && message.content.isNotEmpty()) {
                            Row(
                                verticalAlignment = Alignment.CenterVertically,
                                modifier = Modifier.padding(top = 6.dp, start = 0.dp)
                            ) {
                                GeminiStreamingIndicator()
                                Spacer(Modifier.width(6.dp))
                                Text("正在输入...", style = MaterialTheme.typography.labelSmall, color = Secondary)
                            }
                        }

                        // Galgame 选项
                        AnimatedVisibility(
                            visible = galOptions.isNotEmpty() && isLast && !isStreaming && onSelectOption != null,
                            enter = expandVertically(tween(200)) + fadeIn(tween(180)),
                            exit = shrinkVertically(tween(180)) + fadeOut(tween(150))
                        ) {
                            Column(modifier = Modifier.fillMaxWidth()) {
                                Spacer(Modifier.height(10.dp))
                                Column(
                                    modifier = Modifier.fillMaxWidth(),
                                    verticalArrangement = Arrangement.spacedBy(6.dp)
                                ) {
                                    galOptions.forEach { opt ->
                                        val isAction = opt.type.equals("action", ignoreCase = true) || opt.type.contains("动作")
                                        val typeText = if (isAction) "动作" else "对话"
                                        val optionColor = if (isAction) Color(0xFF7C4DFF) else AccentRose
                                        SwipeToFillChip(
                                            text = opt.label,
                                            onClick = { onSelectOption?.invoke(opt.label) },
                                            onSwipeToFill = { onFillOption?.invoke(opt.label) },
                                            onLongClick = {
                                                haptic.performHapticFeedback(HapticFeedbackType.LongPress)
                                                onFillOption?.invoke(opt.label)
                                            },
                                            chipColor = MaterialTheme.colorScheme.surface.copy(0.9f),
                                            border = BorderStroke(1.dp, optionColor.copy(alpha = 0.35f)),
                                            content = {
                                                Row(
                                                    modifier = Modifier
                                                        .fillMaxWidth()
                                                        .padding(horizontal = 14.dp, vertical = 12.dp),
                                                    verticalAlignment = Alignment.Top,
                                                    horizontalArrangement = Arrangement.spacedBy(10.dp)
                                                ) {
                                                    Text(
                                                        text = "→",
                                                        color = optionColor.copy(0.85f),
                                                        style = MaterialTheme.typography.bodySmall,
                                                        fontWeight = FontWeight.Bold
                                                    )
                                                    Text(
                                                        text = opt.label,
                                                        color = MaterialTheme.colorScheme.onBackground,
                                                        style = MaterialTheme.typography.bodySmall.copy(lineHeight = 20.sp),
                                                        modifier = Modifier.weight(1f)
                                                    )
                                                    Surface(
                                                        shape = RoundedCornerShape(4.dp),
                                                        color = optionColor.copy(alpha = 0.15f)
                                                    ) {
                                                        Text(
                                                            text = typeText,
                                                            style = MaterialTheme.typography.labelSmall,
                                                            color = optionColor,
                                                            fontWeight = FontWeight.Medium,
                                                            modifier = Modifier.padding(horizontal = 5.dp, vertical = 2.dp)
                                                        )
                                                    }
                                                }
                                            }
                                        )
                                    }
                                }
                            }
                        }
                    }
                } else {
                    // ==================== AI 消息 - 普通对话模式（左对齐气泡，镜像用户消息结构） ====================
                    // 气泡行：头像(40dp) + 间距(8dp) + 气泡；end=48dp 预留对侧头像位置
                    // 普通模式下按 \n\n 分段，每段一个独立气泡（更贴近真人发消息的自然感）。
                    // 每段均独立显示名字、时间戳、头像，对等处理。
                    val assistantBubbleShape = RoundedCornerShape(topStart = 4.dp, topEnd = 16.dp, bottomStart = 16.dp, bottomEnd = 16.dp)

                    val rawFinalContent = parsed.mainContent.ifBlank { message.content }
                    val playableVoiceState = message.voiceState
                        ?.takeIf { it.hasLocalAudio() && !message.isStreaming && !debugSettings.showRawContent }
                    val finalContent = remember(
                        message.id,
                        rawFinalContent,
                        message.voiceState,
                        playableVoiceState,
                        debugSettings.showRawContent
                    ) {
                        val voice = message.voiceState
                        if (voice != null && playableVoiceState == null && !voice.hasLocalAudio() && !debugSettings.showRawContent) {
                            voice.readableText(rawFinalContent).takeIf { it.isNotBlank() } ?: rawFinalContent
                        } else {
                            rawFinalContent
                        }
                    }
                    val media = remember(message.id, finalContent, context) {
                        splitMessageMedia(finalContent, context)
                    }
                    val displayText = if (finalContent.isNotBlank()) media.text.ifBlank { finalContent } else ""

                    if (playableVoiceState != null) {
                        AssistantVoiceMessageBlock(
                            message = message,
                            voiceState = playableVoiceState,
                            characterName = characterName,
                            characterAvatarUrl = characterAvatarUrl,
                            apiBase = apiBase,
                            showTimestamp = showTimestamp,
                            timestampNow = timestampNow,
                            actionMenuTextColor = actionMenuTextColor,
                            actionMenuDeleteColor = actionMenuDeleteColor,
                            onNavigateToEditCharacter = onNavigateToEditCharacter,
                            onMentionCharacter = onMentionCharacter,
                            onDelete = onDelete,
                            onQuote = onQuote,
                            mode = mode,
                            onVoiceTranscriptLayout = onVoiceTranscriptLayout,
                            onVoiceTranscriptOpened = onVoiceTranscriptOpened,
                            showTranscript = isVoiceTranscriptVisible,
                            onVoiceTranscriptVisibilityChange = onVoiceTranscriptVisibilityChange,
                            onContextActionTriggered = onContextActionTriggered
                        )
                    } else {

                    // 流式输出中或 rawContent 调试模式时不拆分，保持原样
                    val paragraphs = remember(message.id, displayText, message.isStreaming, debugSettings.showRawContent) {
                        if (message.isStreaming || debugSettings.showRawContent || displayText.isBlank()) {
                            listOf(displayText)
                        } else {
                            displayText.split(Regex("\\n{2,}"))
                                .map { it.trim() }
                                .filter { it.isNotBlank() }
                                .ifEmpty { listOf(displayText) }
                        }
                    }

                    // 打字节奏模拟：新消息到达时逐段展开气泡。
                    val canReveal = revealGradually && !message.isStreaming && paragraphs.size > 1
                    var revealedCount by remember(message.id) {
                        mutableIntStateOf(if (canReveal) 1 else paragraphs.size)
                    }
                    LaunchedEffect(message.id) {
                        while (revealedCount < paragraphs.size) {
                            val prevLen = paragraphs[revealedCount - 1].length
                            val baseMs = (prevLen / 50.0 * 5_000.0).toLong().coerceIn(1_000L, 12_000L)
                            val jitter = 0.8 + kotlin.random.Random.nextDouble() * 0.4
                            delay((baseMs * jitter).toLong())
                            revealedCount++
                            onParagraphRevealed?.invoke()
                        }
                    }

                    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                        paragraphs.forEachIndexed { idx, paraText ->
                            var showParaMenu by remember(message.id, idx) { mutableStateOf(false) }
                            var menuPosition by remember(message.id, idx) { mutableStateOf(IntOffset.Zero) }
                            var textLayoutResult by remember(message.id, idx) { mutableStateOf<TextLayoutResult?>(null) }
                            var longPressCharOffset by remember(message.id, idx) { mutableStateOf(-1) }
                            var selectionRange by remember(message.id, idx, paraText) { mutableStateOf<IntRange?>(null) }
                            val selectionKey = "assistant:${message.id}:$idx"
                            val isSelectingPara = activeSelectionKey == selectionKey && selectionRange != null
                            AnimatedVisibility(
                                visible = idx < revealedCount,
                                enter = fadeIn(tween(350)) + slideInHorizontally(
                                    animationSpec = tween(350, easing = FastOutSlowInEasing)
                                ) { -36 }
                            ) {
                                Column {
                                    if (idx == 0 && media.imageUrls.isNotEmpty()) {
                                        MessageImageGrid(
                                            urls = media.imageUrls,
                                            horizontalAlignment = Alignment.Start,
                                            contentDescription = "助手图片",
                                            modifier = Modifier
                                                .padding(bottom = 6.dp, start = 48.dp, end = 48.dp)
                                        )
                                    }
                                    // ── 名字 + 时间戳（每段独立显示） ──
                                    Row(
                                        verticalAlignment = Alignment.CenterVertically,
                                        modifier = Modifier.padding(bottom = 4.dp, start = 48.dp),
                                    ) {
                                        Text(
                                            text = characterName,
                                            style = MaterialTheme.typography.labelSmall.copy(fontWeight = FontWeight.Medium),
                                            color = MaterialTheme.colorScheme.onSurfaceVariant
                                        )
                                        if (showTimestamp) {
                                            Spacer(Modifier.width(8.dp))
                                            val timeLabel = formatMessageTime(message.timestamp, timestampNow)
                                            Text(
                                                text = timeLabel,
                                                style = MaterialTheme.typography.labelSmall,
                                                color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.7f)
                                            )
                                        }
                                        // 计时器只在最后一段末尾显示
                                        if (isLast && message.isAssistant() && idx == paragraphs.lastIndex) {
                                            if (isTimerRunning && mode != "normal") {
                                                Spacer(Modifier.width(8.dp))
                                                Text(
                                                    text = "${replyTimer / 1000}s",
                                                    style = MaterialTheme.typography.labelSmall,
                                                    color = Primary
                                                )
                                            }
                                        }
                                    }
                                    // ── 气泡行：每段都显示头像 ──
                                    Row(
                                        modifier = Modifier
                                            .fillMaxWidth()
                                            .padding(end = 48.dp),
                                        verticalAlignment = Alignment.Top
                                    ) {
                                        val avatarModifier = if (mode == "normal" && onMentionCharacter != null) {
                                            Modifier.combinedClickable(
                                                onClick = onNavigateToEditCharacter,
                                                onLongClick = onMentionCharacter
                                            )
                                        } else {
                                            Modifier.clickable { onNavigateToEditCharacter() }
                                        }
                                        Box(modifier = avatarModifier) {
                                            PonyStyleAvatar(
                                                avatarUrl = characterAvatarUrl,
                                                name = characterName,
                                                apiBase = apiBase,
                                                size = 40
                                            )
                                        }
                                        Spacer(Modifier.width(8.dp))
                                        // 每段独立的气泡菜单锚点，菜单从长按点位置弹出
                                        val showStickerContent = idx == 0 && stickerAttachments.isNotEmpty()
                                        val showTypingBubble = idx == 0 && message.isStreaming && message.content.isEmpty()
                                        val showTextBubble = paraText.isNotBlank() || showTypingBubble ||
                                            (debugSettings.showMessageIds && message.id.isNotBlank() && idx == paragraphs.lastIndex)
                                        if (showStickerContent) {
                                            Box(modifier = Modifier.weight(1f, fill = false)) {
                                                StickerAttachmentStrip(Alignment.Start)
                                            }
                                        } else if (showTextBubble) {
                                            Box(modifier = Modifier.weight(1f, fill = false)) {
                                            Surface(
                                                shape = assistantBubbleShape,
                                                color = MaterialTheme.colorScheme.surfaceVariant,
                                                shadowElevation = 1.dp,
                                                tonalElevation = 0.dp
                                            ) {
                                                if (idx == 0 && message.isStreaming && message.content.isEmpty()) {
                                                    Box(modifier = Modifier.padding(horizontal = 14.dp, vertical = 12.dp)) {
                                                        GeminiTypingIndicator()
                                                    }
                                                } else {
                                                    Column(modifier = Modifier.padding(horizontal = 14.dp, vertical = 10.dp)) {
                                                        if (paraText.isNotBlank()) {
                                                            val contentColor = if (message.isError) ErrorColor else MaterialTheme.colorScheme.onSurface
                                                            val textStyle = if (debugSettings.showRawContent) {
                                                                MaterialTheme.typography.bodyMedium.copy(
                                                                        fontFamily = androidx.compose.ui.text.font.FontFamily.Monospace,
                                                                        lineHeight = 20.sp
                                                                )
                                                            } else {
                                                                MaterialTheme.typography.bodyMedium.copy(lineHeight = 22.sp)
                                                            }
                                                            SelectableMessageText(
                                                                text = paraText,
                                                                validMentionNames = validMentionNames,
                                                                color = contentColor,
                                                                style = textStyle,
                                                                selectionRange = if (isSelectingPara) selectionRange else null,
                                                                onSelectionRangeChange = { selectionRange = it },
                                                                onCopySelection = { selected ->
                                                                    clipboardManager.setText(AnnotatedString(selected))
                                                                    selectionRange = null
                                                                    onActiveSelectionKeyChange(null)
                                                                },
                                                                onCancelSelection = {
                                                                    selectionRange = null
                                                                    onActiveSelectionKeyChange(null)
                                                                },
                                                                onTextLayout = { textLayoutResult = it },
                                                                onLongPress = { offset, windowOffset ->
                                                                    onContextActionTriggered()
                                                                    haptic.performHapticFeedback(HapticFeedbackType.LongPress)
                                                                    onActiveSelectionKeyChange(null)
                                                                    selectionRange = null
                                                                    menuPosition = IntOffset(windowOffset.x.roundToInt(), windowOffset.y.roundToInt())
                                                                    longPressCharOffset = textLayoutResult?.getOffsetForPosition(offset) ?: -1
                                                                    showParaMenu = true
                                                                }
                                                            )
                                                        }

                                                        // 调试 ID 只在最后一个气泡显示
                                                        if (debugSettings.showMessageIds && message.id.isNotBlank() && idx == paragraphs.lastIndex) {
                                                            Text(
                                                                text = "ID: ${message.id}",
                                                                style = MaterialTheme.typography.labelSmall.copy(
                                                                    fontFamily = androidx.compose.ui.text.font.FontFamily.Monospace
                                                                ),
                                                                color = Color(0xFFF97316).copy(alpha = 0.7f),
                                                                modifier = Modifier.padding(top = 4.dp)
                                                            )
                                                        }
                                                    }
                                                }
                                            }
                                            FingerAnchoredDropdownMenu(
                                                expanded = showParaMenu,
                                                onDismissRequest = { showParaMenu = false },
                                                positionInWindow = menuPosition
                                            ) {
                                                DropdownMenuItem(
                                                    text = { Text("复制", color = actionMenuTextColor) },
                                                    leadingIcon = { Icon(Icons.Filled.ContentCopy, contentDescription = null, tint = actionMenuTextColor) },
                                                    onClick = {
                                                        showParaMenu = false
                                                        clipboardManager.setText(AnnotatedString(paraText))
                                                    }
                                                )
                                                if (onQuote != null && mode == "normal") {
                                                    DropdownMenuItem(
                                                        text = { Text("引用", color = actionMenuTextColor) },
                                                        leadingIcon = { Icon(Icons.Filled.FormatQuote, contentDescription = null, tint = actionMenuTextColor) },
                                                        onClick = { showParaMenu = false; onQuote() }
                                                    )
                                                }
                                                DropdownMenuItem(
                                                    text = { Text("选择", color = actionMenuTextColor) },
                                                    leadingIcon = { Icon(Icons.Filled.FormatColorText, contentDescription = null, tint = actionMenuTextColor) },
                                                    onClick = {
                                                        showParaMenu = false
                                                        val charOff = longPressCharOffset
                                                        val range = if (charOff >= 0) {
                                                            findSentenceBounds(paraText, charOff)
                                                        } else {
                                                            0 until paraText.length
                                                        }
                                                        selectionRange = range
                                                        onActiveSelectionKeyChange(selectionKey)
                                                    }
                                                )
                                                DropdownMenuItem(
                                                    text = { Text("删除", color = actionMenuDeleteColor) },
                                                    leadingIcon = { Icon(Icons.Filled.Delete, contentDescription = null, tint = actionMenuDeleteColor) },
                                                    onClick = { showParaMenu = false; onDelete() }
                                                )
                                            }
                                            }
                                        } else {
                                            Spacer(Modifier.weight(1f))
                                        }
                                    }
                                }
                            }
                        }
                    }
                    }
                }
            }
        }
    }
}

@Composable
private fun PendingUserMessageAcceptIndicator(
    startedAt: Long,
    onRetry: (() -> Unit)?,
    modifier: Modifier = Modifier
) {
    var timedOut by remember(startedAt) {
        mutableStateOf(System.currentTimeMillis() - startedAt >= 10_000L)
    }
    LaunchedEffect(startedAt) {
        val remaining = 10_000L - (System.currentTimeMillis() - startedAt)
        if (remaining > 0L) {
            timedOut = false
            delay(remaining)
            timedOut = true
        } else {
            timedOut = true
        }
    }
    val isDark = MaterialTheme.colorScheme.background.luminance() < 0.5f
    val tint = if (isDark) Color.White else Color(0xFF4F46E5)
    val clickableModifier = if (timedOut && onRetry != null) {
        Modifier.clickable { onRetry() }
    } else {
        Modifier
    }
    Box(
        modifier = modifier
            .size(30.dp)
            .then(clickableModifier),
        contentAlignment = Alignment.Center
    ) {
        if (timedOut) {
            Icon(
                imageVector = Icons.Filled.Warning,
                contentDescription = "重新发送",
                tint = tint,
                modifier = Modifier.size(20.dp)
            )
        } else {
            CircularProgressIndicator(
                modifier = Modifier.size(18.dp),
                color = tint,
                strokeWidth = 2.dp
            )
        }
    }
}
