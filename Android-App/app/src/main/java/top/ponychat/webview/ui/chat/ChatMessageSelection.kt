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


// ==================== 文字选择辅助 ====================

/**
 * 从 [offset] 位置向两侧扩展，找到所在句子的首尾下标（左闭右开区间）。
 * 句子边界以中英文句末标点或换行为准。
 */
internal fun findSentenceBounds(text: String, offset: Int): IntRange {
    if (text.isEmpty()) return 0..0
    val clampedOffset = offset.coerceIn(0, text.lastIndex)
    val enders = setOf('。', '！', '？', '!', '?', '.', '\n', '…', '；', ';')

    // 向左找到上一个句尾标点后的位置（即本句起点）
    var start = clampedOffset
    while (start > 0 && text[start - 1] !in enders) start--
    // 跳过句首空白
    while (start < text.length && text[start].isWhitespace()) start++

    // 向右找到本句的句尾标点（含标点本身）
    var end = clampedOffset
    while (end < text.lastIndex && text[end] !in enders) end++
    if (end < text.length && text[end] in enders) end++ // 包含句末标点

    return if (start < end) start until end else clampedOffset until (clampedOffset + 1).coerceAtMost(text.length)
}

private fun normalizedSelectionRange(text: String, range: IntRange?): IntRange? {
    if (text.isEmpty() || range == null) return null
    val start = range.first.coerceIn(0, text.length)
    val endExclusive = (range.last + 1).coerceIn(0, text.length)
    val normalizedStart = min(start, endExclusive)
    val normalizedEnd = max(start, endExclusive)
    return if (normalizedStart < normalizedEnd) normalizedStart until normalizedEnd else null
}

private fun selectionFromOffsets(text: String, anchor: Int, moving: Int): IntRange? {
    if (text.isEmpty()) return null
    val a = anchor.coerceIn(0, text.length)
    val b = moving.coerceIn(0, text.length)
    val start = min(a, b)
    val end = max(a, b)
    return if (start < end) start until end else start until (start + 1).coerceAtMost(text.length)
}

private fun fingerMenuPositionProvider(positionInWindow: IntOffset): PopupPositionProvider =
    object : PopupPositionProvider {
        override fun calculatePosition(
            anchorBounds: IntRect,
            windowSize: IntSize,
            layoutDirection: androidx.compose.ui.unit.LayoutDirection,
            popupContentSize: IntSize
        ): IntOffset {
            val x = positionInWindow.x.coerceIn(0, (windowSize.width - popupContentSize.width).coerceAtLeast(0))
            val y = positionInWindow.y.coerceIn(0, (windowSize.height - popupContentSize.height).coerceAtLeast(0))
            return IntOffset(x, y)
        }
    }

private fun selectionToolbarPositionProvider(
    handleCenterInWindow: IntOffset,
    handleClearancePx: Int
): PopupPositionProvider =
    object : PopupPositionProvider {
        override fun calculatePosition(
            anchorBounds: IntRect,
            windowSize: IntSize,
            layoutDirection: androidx.compose.ui.unit.LayoutDirection,
            popupContentSize: IntSize
        ): IntOffset {
            val maxX = (windowSize.width - popupContentSize.width).coerceAtLeast(0)
            val maxY = (windowSize.height - popupContentSize.height).coerceAtLeast(0)
            val x = (handleCenterInWindow.x - popupContentSize.width / 2).coerceIn(0, maxX)
            val belowY = handleCenterInWindow.y + handleClearancePx
            val aboveY = handleCenterInWindow.y - handleClearancePx - popupContentSize.height
            val y = if (belowY + popupContentSize.height <= windowSize.height) {
                belowY
            } else {
                aboveY.coerceIn(0, maxY)
            }
            return IntOffset(x, y)
        }
    }

@Composable
private fun actionMenuContainerColor(): Color =
    adaptivePopupMenuContainerColor()

@Composable
internal fun actionMenuContentColor(): Color =
    adaptivePopupMenuContentColor()

@Composable
internal fun actionMenuDangerColor(): Color =
    adaptivePopupMenuDangerColor()

@Composable
private fun actionMenuBorder(): BorderStroke? =
    adaptivePopupMenuBorder()

@Composable
internal fun FingerAnchoredDropdownMenu(
    expanded: Boolean,
    positionInWindow: IntOffset,
    onDismissRequest: () -> Unit,
    content: @Composable ColumnScope.() -> Unit
) {
    if (!expanded) return
    Popup(
        popupPositionProvider = remember(positionInWindow) { fingerMenuPositionProvider(positionInWindow) },
        onDismissRequest = onDismissRequest
    ) {
        Surface(
            shape = RoundedCornerShape(12.dp),
            color = actionMenuContainerColor(),
            border = actionMenuBorder(),
            tonalElevation = 3.dp,
            shadowElevation = 6.dp
        ) {
            Column(
                modifier = Modifier.width(168.dp),
                content = content
            )
        }
    }
}

@Composable
internal fun MessageContentActionMenu(
    expanded: Boolean,
    positionInWindow: IntOffset,
    onDismissRequest: () -> Unit,
    onQuote: (() -> Unit)?,
    onDelete: () -> Unit,
    mode: String,
    actionMenuTextColor: Color,
    actionMenuDeleteColor: Color,
) {
    FingerAnchoredDropdownMenu(
        expanded = expanded,
        onDismissRequest = onDismissRequest,
        positionInWindow = positionInWindow
    ) {
        if (onQuote != null && mode == "normal") {
            DropdownMenuItem(
                text = { Text("引用", color = actionMenuTextColor) },
                leadingIcon = { Icon(Icons.Filled.FormatQuote, contentDescription = null, tint = actionMenuTextColor) },
                onClick = {
                    onDismissRequest()
                    onQuote()
                }
            )
        }
        DropdownMenuItem(
            text = { Text("删除", color = actionMenuDeleteColor) },
            leadingIcon = { Icon(Icons.Filled.Delete, contentDescription = null, tint = actionMenuDeleteColor) },
            onClick = {
                onDismissRequest()
                onDelete()
            }
        )
    }
}


private fun Char.isMentionTokenTerminator(): Boolean =
    isWhitespace() || this in setOf(
        ',', '.', '?', '!', ';', ':',
        '，', '。', '？', '！', '；', '：', '、',
        ')', ']', '}', '）', '】', '》', '」', '』',
        '"', '\'', '”', '’', '…'
    )

private fun styledMentionText(text: String, validMentionNames: Set<String>): AnnotatedString {
    if (text.isBlank() || validMentionNames.isEmpty()) return AnnotatedString(text)
    val builder = AnnotatedString.Builder(text)
    val mentionStyle = SpanStyle(fontWeight = FontWeight.Bold)
    validMentionNames
        .asSequence()
        .map { it.trim() }
        .filter { it.isNotBlank() }
        .distinct()
        .sortedByDescending { it.length }
        .forEach { name ->
            listOf("@$name", "＠$name").forEach { token ->
                var from = 0
                while (from <= text.length) {
                    val start = text.indexOf(token, from)
                    if (start < 0) break
                    val end = start + token.length
                    val boundary = end >= text.length || text[end].isMentionTokenTerminator()
                    if (boundary) {
                        builder.addStyle(mentionStyle, start, end)
                    }
                    from = start + 1
                }
            }
        }
    return builder.toAnnotatedString()
}

@Composable
internal fun SelectableMessageText(
    text: String,
    validMentionNames: Set<String>,
    color: Color,
    style: TextStyle,
    selectionRange: IntRange?,
    onSelectionRangeChange: (IntRange?) -> Unit,
    onCopySelection: (String) -> Unit,
    onCancelSelection: () -> Unit,
    modifier: Modifier = Modifier,
    onTextLayout: ((TextLayoutResult) -> Unit)? = null,
    onLongPress: ((localOffset: Offset, windowOffset: Offset) -> Unit)? = null
) {
    var layoutResult by remember(text) { mutableStateOf<TextLayoutResult?>(null) }
    var textWindowTopLeft by remember(text) { mutableStateOf(Offset.Zero) }
    val selection = normalizedSelectionRange(text, selectionRange)
    val density = LocalDensity.current
    val selectionColor = MaterialTheme.colorScheme.primary.copy(alpha = 0.24f)
    val handleColor = MaterialTheme.colorScheme.primary
    val toolbarBackground = MaterialTheme.colorScheme.inverseSurface
    val toolbarText = MaterialTheme.colorScheme.inverseOnSurface
    val handleTouchSize = 28.dp
    val handleTouchRadiusPx = with(density) { handleTouchSize.toPx() / 2f }
    val handleStemPx = with(density) { 18.dp.toPx() }
    val handleDotPx = with(density) { 5.dp.toPx() }
    val displayText = remember(text, validMentionNames) {
        styledMentionText(text, validMentionNames)
    }

    fun handlePoint(layout: TextLayoutResult, offset: Int): Offset {
        val safeOffset = offset.coerceIn(0, text.length)
        val lineOffset = if (safeOffset == text.length && text.isNotEmpty()) safeOffset - 1 else safeOffset
        val line = layout.getLineForOffset(lineOffset.coerceIn(0, text.lastIndex.coerceAtLeast(0)))
        val x = layout.getHorizontalPosition(safeOffset, true)
        return Offset(x, layout.getLineBottom(line))
    }

    fun updateStartHandle(layout: TextLayoutResult, target: Offset, current: IntRange) {
        val endExclusive = current.last + 1
        val newStart = layout.getOffsetForPosition(target)
        onSelectionRangeChange(selectionFromOffsets(text, endExclusive, newStart))
    }

    fun updateEndHandle(layout: TextLayoutResult, target: Offset, current: IntRange) {
        val newEndExclusive = layout.getOffsetForPosition(target)
        onSelectionRangeChange(selectionFromOffsets(text, current.first, newEndExclusive))
    }

    Box(modifier = modifier) {
        Text(
            text = displayText,
            color = color,
            style = style,
            modifier = Modifier
                .onGloballyPositioned { coords ->
                    textWindowTopLeft = coords.positionInWindow()
                }
                .drawBehind {
                    val layout = layoutResult ?: return@drawBehind
                    val activeSelection = selection ?: return@drawBehind
                    val start = activeSelection.first
                    val endExclusive = activeSelection.last + 1
                    val startLine = layout.getLineForOffset(start.coerceIn(0, text.lastIndex.coerceAtLeast(0)))
                    val endLineOffset = (endExclusive - 1).coerceIn(0, text.lastIndex.coerceAtLeast(0))
                    val endLine = layout.getLineForOffset(endLineOffset)
                    for (line in startLine..endLine) {
                        val lineStart = layout.getLineStart(line)
                        val lineEnd = layout.getLineEnd(line, visibleEnd = true)
                        val segmentStart = max(start, lineStart)
                        val segmentEnd = min(endExclusive, lineEnd)
                        if (segmentStart >= segmentEnd) continue
                        val left = if (segmentStart <= lineStart) {
                            layout.getLineLeft(line)
                        } else {
                            layout.getHorizontalPosition(segmentStart, true)
                        }
                        val right = if (segmentEnd >= lineEnd) {
                            layout.getLineRight(line)
                        } else {
                            layout.getHorizontalPosition(segmentEnd, true)
                        }
                        val x = min(left, right)
                        val width = kotlin.math.abs(right - left).coerceAtLeast(1f)
                        drawRoundRect(
                            color = selectionColor,
                            topLeft = Offset(x, layout.getLineTop(line)),
                            size = Size(width, layout.getLineBottom(line) - layout.getLineTop(line)),
                            cornerRadius = CornerRadius(4.dp.toPx(), 4.dp.toPx())
                        )
                    }
                }
                .then(
                    if (onLongPress == null) {
                        Modifier
                    } else {
                        Modifier.pointerInput(text) {
                            detectTapGestures(onLongPress = { offset ->
                                onLongPress(offset, textWindowTopLeft + offset)
                            })
                        }
                    }
                ),
            onTextLayout = {
                layoutResult = it
                onTextLayout?.invoke(it)
            }
        )

        val layout = layoutResult
        val activeSelection = selection
        if (layout != null && activeSelection != null) {
            val startPoint = handlePoint(layout, activeSelection.first)
            val endPoint = handlePoint(layout, activeSelection.last + 1)
            val toolbarHandleClearancePx = handleTouchRadiusPx.roundToInt() + with(density) { 6.dp.roundToPx() }
            val lowerHandlePoint = if (startPoint.y > endPoint.y) startPoint else endPoint
            val toolbarAnchorInWindow = IntOffset(
                (textWindowTopLeft.x + lowerHandlePoint.x).roundToInt(),
                (textWindowTopLeft.y + lowerHandlePoint.y).roundToInt()
            )
            val latestLayout by rememberUpdatedState(layout)
            val latestSelection by rememberUpdatedState(activeSelection)
            val latestStartPoint by rememberUpdatedState(startPoint)
            val latestEndPoint by rememberUpdatedState(endPoint)

            Popup(
                popupPositionProvider = remember(toolbarAnchorInWindow, toolbarHandleClearancePx) {
                    selectionToolbarPositionProvider(toolbarAnchorInWindow, toolbarHandleClearancePx)
                }
            ) {
                Row(
                    modifier = Modifier
                        .zIndex(2f)
                        .clip(RoundedCornerShape(999.dp))
                        .background(toolbarBackground)
                        .padding(horizontal = 4.dp, vertical = 2.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    TextButton(
                        onClick = {
                            val selectedText = text.substring(activeSelection.first, activeSelection.last + 1)
                            onCopySelection(selectedText)
                        },
                        contentPadding = PaddingValues(horizontal = 10.dp, vertical = 2.dp)
                    ) {
                        Text("复制", color = toolbarText, style = MaterialTheme.typography.labelMedium)
                    }
                    TextButton(
                        onClick = onCancelSelection,
                        contentPadding = PaddingValues(horizontal = 10.dp, vertical = 2.dp)
                    ) {
                        Text("取消", color = toolbarText, style = MaterialTheme.typography.labelMedium)
                    }
                }
            }

            Box(
                modifier = Modifier
                    .offset {
                        IntOffset(
                            (startPoint.x - handleTouchRadiusPx).roundToInt(),
                            (startPoint.y - handleTouchRadiusPx).roundToInt()
                        )
                    }
                    .size(handleTouchSize)
                    .zIndex(3f)
                    .drawBehind {
                        drawLine(
                            color = handleColor,
                            start = Offset(size.width / 2f, size.height / 2f - handleStemPx),
                            end = Offset(size.width / 2f, size.height / 2f),
                            strokeWidth = 2.dp.toPx()
                        )
                        drawCircle(handleColor, radius = handleDotPx, center = Offset(size.width / 2f, size.height / 2f))
                    }
                    .pointerInput(text) {
                        awaitEachGesture {
                            val down = awaitFirstDown(requireUnconsumed = false)
                            down.consume()
                            while (true) {
                                val event = awaitPointerEvent()
                                val change = event.changes.firstOrNull { it.id == down.id } ?: break
                                if (!change.pressed) break
                                val currentLayout = latestLayout
                                val currentSelection = latestSelection
                                val currentStartPoint = latestStartPoint
                                val target = Offset(
                                    currentStartPoint.x - handleTouchRadiusPx + change.position.x,
                                    currentStartPoint.y - handleTouchRadiusPx + change.position.y
                                )
                                updateStartHandle(currentLayout, target, currentSelection)
                                change.consume()
                            }
                        }
                    }
            )

            Box(
                modifier = Modifier
                    .offset {
                        IntOffset(
                            (endPoint.x - handleTouchRadiusPx).roundToInt(),
                            (endPoint.y - handleTouchRadiusPx).roundToInt()
                        )
                    }
                    .size(handleTouchSize)
                    .zIndex(3f)
                    .drawBehind {
                        drawLine(
                            color = handleColor,
                            start = Offset(size.width / 2f, size.height / 2f - handleStemPx),
                            end = Offset(size.width / 2f, size.height / 2f),
                            strokeWidth = 2.dp.toPx()
                        )
                        drawCircle(handleColor, radius = handleDotPx, center = Offset(size.width / 2f, size.height / 2f))
                    }
                    .pointerInput(text) {
                        awaitEachGesture {
                            val down = awaitFirstDown(requireUnconsumed = false)
                            down.consume()
                            while (true) {
                                val event = awaitPointerEvent()
                                val change = event.changes.firstOrNull { it.id == down.id } ?: break
                                if (!change.pressed) break
                                val currentLayout = latestLayout
                                val currentSelection = latestSelection
                                val currentEndPoint = latestEndPoint
                                val target = Offset(
                                    currentEndPoint.x - handleTouchRadiusPx + change.position.x,
                                    currentEndPoint.y - handleTouchRadiusPx + change.position.y
                                )
                                updateEndHandle(currentLayout, target, currentSelection)
                                change.consume()
                            }
                        }
                    }
            )
        }
    }
}

