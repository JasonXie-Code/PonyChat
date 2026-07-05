package top.ponychat.webview.ui.chat

import android.Manifest
import android.app.Activity
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
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.input.pointer.PointerEventPass
import androidx.compose.ui.input.pointer.changedToDown
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.focus.focusRequester
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
import androidx.compose.ui.graphics.compositeOver
import androidx.compose.ui.graphics.drawscope.drawIntoCanvas
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.graphics.nativeCanvas
import androidx.compose.ui.graphics.toArgb
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.layout.positionInWindow
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.TextRange
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.input.OffsetMapping
import androidx.compose.ui.text.input.TextFieldValue
import androidx.compose.ui.text.input.TransformedText
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.compose.foundation.Canvas
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.drawscope.Stroke
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
import top.ponychat.webview.data.model.QuickMessage
import top.ponychat.webview.data.model.QuotedMessage
import top.ponychat.webview.data.model.StickerAsset
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.ui.character.CharacterAvatar
import top.ponychat.webview.ui.common.PonyAvatar
import top.ponychat.webview.ui.common.PonyButton
import top.ponychat.webview.ui.common.PonyButtonStyle
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


// ==================== 输入栏（Pony风格） ====================

internal val ChatInputBarVerticalUnit = 6.dp

// 常用Emoji列表
internal val emojiList = listOf(
    listOf("😀", "😃", "😄", "😁", "😆", "😅", "😂", "🙂", "😉", "😊", "😇", "😍", "😘", "😗", "😙", "😋", "😛", "😜", "😝", "🤑", "🤗", "🤔", "🤐", "😐", "😑", "😶", "😏", "😒", "🙄", "😬", "😌", "😔", "😪", "😴", "😷", "🤒", "🤕", "😵", "😎", "🤓", "😕", "😟", "🙁", "😮", "😯", "😲", "😳", "😦", "😧", "😨", "😰", "😥", "😢", "😭", "😱", "😖", "😣", "😞", "😓", "😩", "😫", "😤", "😡", "😠"),
    listOf("👋", "✋", "👌", "✌", "👈", "👉", "👆", "👇", "👍", "👎", "✊", "👊", "👏", "🙌", "👐", "🙏", "💪", "👀", "👁", "👅", "👄", "💋", "👂", "👃", "🖐", "🤚", "🖖", "🤙", "🤘", "🤞", "🤝", "💅", "🤳"),
    listOf("❤", "💛", "💚", "💙", "💜", "🖤", "💔", "💕", "💞", "💓", "💗", "💖", "💘", "💝", "💟", "✨", "⭐", "🌟", "💫", "🔥", "💥", "💢", "💦", "💧", "💤", "💨", "🎵", "🎶", "🎀", "🎁", "🎈", "🎉", "🎊", "✅", "❌", "❓", "❗", "💯", "🔴", "🟠", "🟡", "🟢", "🔵", "🟣", "⚫", "⚪"),
    listOf("🐶", "🐱", "🐭", "🐹", "🐰", "🦊", "🐻", "🐼", "🐨", "🐯", "🦁", "🐮", "🐷", "🐸", "🐵", "🙈", "🙉", "🙊", "🐔", "🐧", "🐦", "🐤", "🐣", "🐥", "🐺", "🐗", "🐴", "🐝", "🐛", "🦋", "🐌", "🐞", "🐜", "🐢", "🐍", "🐙", "🐠", "🐟", "🐬", "🐳", "🐋", "🐊", "🐘", "🐎", "🐖", "🐏", "🐑", "🐐", "🐕", "🐈", "🐓", "🐇", "🐁", "🐀"),
    listOf("🍏", "🍎", "🍐", "🍊", "🍋", "🍌", "🍉", "🍇", "🍓", "🍈", "🍒", "🍑", "🍍", "🍅", "🍆", "🌽", "🍞", "🧀", "🍳", "🍗", "🍖", "🌭", "🍔", "🍟", "🍕", "🥪", "🌮", "🌯", "🍜", "🍲", "🍛", "🍣", "🍱", "🍤", "🍙", "🍚", "🍘", "🍥", "🍢", "🍡", "🍧", "🍨", "🍦", "🍰", "🎂", "🍮", "🍭", "🍬", "🍫", "🍿", "🍩", "🍪", "☕", "🍵", "🍶", "🍺", "🍻", "🍷", "🍸", "🍹")
)

private class MentionTextVisualTransformation(
    private val mentionNames: Set<String>
) : VisualTransformation {
    override fun filter(text: AnnotatedString): TransformedText {
        val names = mentionNames.mapNotNull { it.trim().takeIf(String::isNotBlank) }
        if (names.isEmpty()) return TransformedText(text, OffsetMapping.Identity)
        val raw = text.text
        val builder = AnnotatedString.Builder()
        builder.append(text)
        val style = SpanStyle(fontWeight = FontWeight.Bold)
        names.forEach { name ->
            listOf("@$name", "＠$name").forEach { token ->
                var from = 0
                while (from <= raw.length) {
                    val start = raw.indexOf(token, from)
                    if (start < 0) break
                    val end = start + token.length
                    val boundary = end >= raw.length || raw[end].isWhitespace()
                    if (boundary) {
                        builder.addStyle(style, start, end)
                    }
                    from = start + 1
                }
            }
        }
        return TransformedText(builder.toAnnotatedString(), OffsetMapping.Identity)
    }
}

internal enum class MoreFunctionPage {
    Main,
    MiniGames,
    Companion
}

internal enum class MoreFunctionCustomIcon {
    ChineseChess,
    TicTacToe,
    Doudizhu
}

@Composable
fun ChatInputBar(
    modifier: Modifier = Modifier,
    text: String,
    onTextChange: (String) -> Unit,
    onSend: () -> Unit,
    isStreaming: Boolean,
    voiceState: VoiceState,
    imageAttachments: List<String>,
    onPickImage: () -> Unit,
    onPickCamera: () -> Unit,
    onRemoveAttachment: (Int) -> Unit,
    quickMessages: List<QuickMessage> = emptyList(),
    isLoadingQuickMessages: Boolean = false,
    stickers: List<StickerAsset> = emptyList(),
    isLoadingStickers: Boolean = false,
    onStickerSend: (StickerAsset) -> Unit = {},
    onStickerUpload: (Uri) -> Unit = {},
    onStickerDelete: (StickerAsset) -> Unit = {},
    onStickerPreview: (String) -> Unit = {},
    onLoadStickers: () -> Unit = {},
    onQuickMessageSend: (String) -> Unit = {},
    onQuickMessageAdd: (String, String) -> Unit = { _, _ -> },
    onQuickMessageUpdate: (QuickMessage) -> Unit = {},
    onQuickMessageDelete: (Int) -> Unit = {},
    quotedMessage: QuotedMessage? = null,
    onClearQuotedMessage: () -> Unit = {},
    selectedMentionNames: Set<String> = emptySet(),
    focusInputSignal: Int = 0,
    quotaExceeded: Boolean = false,
    supportsVision: Boolean = true,
    isCompanionActive: Boolean = false,
    isAgentCompanionActive: Boolean = false,
    isAgentAutoLooping: Boolean = false,
    showCompanionButton: Boolean = false,
    onProactiveTasksClick: () -> Unit = {},
    onShowPrompt: (String) -> Unit = {},
    onChineseChessClick: () -> Unit = {},
    onTicTacToeClick: () -> Unit = {},
    onDoudizhuClick: () -> Unit = {},
    mode: String = "normal",
    /** 外部点击触发的面板收起信号；数值变化时关闭表情/快捷回复/更多面板 */
    dismissPanelsSignal: Int = 0,
    /** 表情/更多面板展开时，回调面板区域当前像素高度（面板收起时为 0）*/
    onPanelHeightChanged: (Int) -> Unit = {},
    /** 面板显隐意图变化时立即通知父级，用于键盘/面板切换瞬间避免位移叠加。 */
    onPanelActiveChanged: (Boolean) -> Unit = {},
    /** 当前面板切回键盘时，先把父级底部避让保持在目标高度，避免输入栏先落回屏幕底部。 */
    onKeyboardHandoffRequested: (Int) -> Unit = {},
    /** 输入栏实际绘制内容的窗口顶部，用于父级计算消息列表底部遮挡。 */
    onInputBarVisualTopChanged: (Float) -> Unit = {},
    /** 输入框焦点变化；父级据此处理列表点击清焦点。 */
    onInputFocusChanged: (Boolean) -> Unit = {},
) {
    val isVoiceActive = voiceState !is VoiceState.Idle
    var showEmojiPicker by remember { mutableStateOf(false) }
    var showQuickMessagePanel by remember { mutableStateOf(false) }
    var showMorePanel by remember { mutableStateOf(false) }
    var moreFunctionPage by remember { mutableStateOf(MoreFunctionPage.Main) }
    var isInputFocused by remember { mutableStateOf(false) }
    var inputBarWindowOffset by remember { mutableStateOf(Offset.Zero) }
    var inputFieldWindowBounds by remember { mutableStateOf<Rect?>(null) }
    var sendButtonWindowBounds by remember { mutableStateOf<Rect?>(null) }
    var toolbarWindowBounds by remember { mutableStateOf<Rect?>(null) }
    var inputFieldValue by remember {
        mutableStateOf(TextFieldValue(text, selection = TextRange(text.length)))
    }
    val keyboardController = LocalSoftwareKeyboardController.current
    val focusManager = LocalFocusManager.current
    val inputFocusRequester = remember { FocusRequester() }
    val density = LocalDensity.current
    val scope = rememberCoroutineScope()
    val emojiPanelHeight = 255.dp
    val quickMessagePanelHeight = 280.dp
    val morePanelHeight = 280.dp
    fun panelHeightPx(emoji: Boolean, quick: Boolean, more: Boolean): Int {
        val height = when {
            emoji -> emojiPanelHeight
            quick -> quickMessagePanelHeight
            more -> morePanelHeight
            else -> 0.dp
        }
        return with(density) { height.roundToPx() }
    }
    val stickerPickerLauncher = rememberLauncherForActivityResult(ActivityResultContracts.PickVisualMedia()) { uri ->
        uri?.let(onStickerUpload)
    }
    fun setPanels(emoji: Boolean, quick: Boolean, more: Boolean) {
        showEmojiPicker = emoji
        showQuickMessagePanel = quick
        showMorePanel = more
        if (!more) moreFunctionPage = MoreFunctionPage.Main
        val active = emoji || quick || more
        onPanelActiveChanged(active)
        onPanelHeightChanged(panelHeightPx(emoji, quick, more))
    }
    fun hideKeyboardForPanelSwitch() {
        keyboardController?.hide()
        focusManager.clearFocus(force = true)
    }
    fun switchPanelsFromToolbar(emoji: Boolean, quick: Boolean, more: Boolean) {
        setPanels(emoji = emoji, quick = quick, more = more)
        hideKeyboardForPanelSwitch()
    }
    fun appendQuickMessageToInput(content: String) {
        val next = buildString {
            append(text)
            if (text.isNotEmpty() && text.last().isWhitespace().not()) append(' ')
            append(content)
        }
        onTextChange(next)
    }

    // 输入框获得焦点时隐藏所有底部面板
    LaunchedEffect(isInputFocused) {
        if (isInputFocused) {
            val activePanelHeightPx = panelHeightPx(showEmojiPicker, showQuickMessagePanel, showMorePanel)
            if (activePanelHeightPx > 0) {
                onKeyboardHandoffRequested(activePanelHeightPx)
            }
            setPanels(emoji = false, quick = false, more = false)
        }
    }
    LaunchedEffect(mode) {
        if (mode == "galgame" || mode == "galgame_lock") {
            setPanels(
                emoji = showEmojiPicker,
                quick = false,
                more = showMorePanel
            )
        }
    }
    LaunchedEffect(dismissPanelsSignal) {
        if (dismissPanelsSignal > 0) {
            setPanels(emoji = false, quick = false, more = false)
        }
    }
    LaunchedEffect(text) {
        if (text != inputFieldValue.text) {
            inputFieldValue = TextFieldValue(text, selection = TextRange(text.length))
        }
    }
    LaunchedEffect(focusInputSignal) {
        if (focusInputSignal > 0) {
            inputFocusRequester.requestFocus()
            delay(40)
            keyboardController?.show()
        }
    }
    val inputBarContainerColor = MaterialTheme.colorScheme.surfaceVariant
        .copy(alpha = 0.6f)
        .compositeOver(MaterialTheme.colorScheme.surface)
    val isDarkTheme = MaterialTheme.colorScheme.background.luminance() < 0.5f
    val inputFieldContainerColor = if (isDarkTheme) {
        MaterialTheme.colorScheme.background
            .copy(alpha = 0.58f)
            .compositeOver(inputBarContainerColor)
    } else {
        MaterialTheme.colorScheme.surfaceVariant
            .copy(alpha = 0.94f)
            .compositeOver(MaterialTheme.colorScheme.surface)
    }
    val inputFieldBorderColor = if (isInputFocused) {
        MaterialTheme.colorScheme.primary.copy(alpha = 0.38f)
    } else if (isDarkTheme) {
        MaterialTheme.colorScheme.outline.copy(alpha = 0.20f)
    } else {
        MaterialTheme.colorScheme.outline.copy(alpha = 0.36f)
    }
    val inputTextLineHeight = with(density) { 21.sp.toDp() }
    val inputFieldVerticalPadding = 10.5.dp
    val inputFieldMinHeight = inputTextLineHeight + inputFieldVerticalPadding * 2
    var inputLineCount by remember { mutableIntStateOf(1) }
    val inputFieldHeight = inputTextLineHeight * inputLineCount.coerceIn(1, 5) +
        inputFieldVerticalPadding * 2
    LaunchedEffect(isInputFocused) {
        onInputFocusChanged(isInputFocused)
    }

    Surface(
        color = inputBarContainerColor,
        shadowElevation = 2.dp,
        modifier = modifier
            .onGloballyPositioned { coords ->
                inputBarWindowOffset = coords.positionInWindow()
            }
            .pointerInput(isInputFocused) {
                awaitPointerEventScope {
                    while (true) {
                        val event = awaitPointerEvent(PointerEventPass.Initial)
                        val firstDown = event.changes.firstOrNull { it.changedToDown() }
                        val inputBounds = inputFieldWindowBounds
                        val sendBounds = sendButtonWindowBounds
                        val toolbarBounds = toolbarWindowBounds
                        if (firstDown != null && isInputFocused && inputBounds != null) {
                            val windowPosition = Offset(
                                inputBarWindowOffset.x + firstDown.position.x,
                                inputBarWindowOffset.y + firstDown.position.y
                            )
                            val keepKeyboard = inputBounds.contains(windowPosition) ||
                                sendBounds?.contains(windowPosition) == true ||
                                toolbarBounds?.contains(windowPosition) == true
                            if (!keepKeyboard) {
                                keyboardController?.hide()
                                focusManager.clearFocus(force = true)
                            }
                        }
                    }
                }
            }
    ) {
        Column(
            modifier = Modifier.onGloballyPositioned { coords ->
                onInputBarVisualTopChanged(coords.positionInWindow().y)
            }
        ) {
            // 多图附件预览（横向可滚动，每张可单独移除）
            if (imageAttachments.isNotEmpty()) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .horizontalScroll(rememberScrollState())
                        .padding(horizontal = 12.dp, vertical = 8.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    imageAttachments.forEachIndexed { idx, url ->
                        // 外层 padding 为溢出的删除按钮留出空间，使其不被裁剪
                        Box(modifier = Modifier.padding(top = 8.dp, end = 8.dp)) {
                            AsyncImage(
                                model = rememberThumbnailImageRequest(url),
                                contentDescription = "附件 ${idx + 1}",
                                contentScale = ContentScale.Crop,
                                modifier = Modifier
                                    .size(64.dp)
                                    .clip(RoundedCornerShape(8.dp))
                                    .background(MaterialTheme.colorScheme.surfaceVariant)
                            )
                            // 删除按钮悬浮在图片右上角，offset 使其半溢出图片边界
                            Box(
                                contentAlignment = Alignment.Center,
                                modifier = Modifier
                                    .size(20.dp)
                                    .align(Alignment.TopEnd)
                                    .offset(x = 8.dp, y = (-8).dp)
                                    .background(
                                        color = Color(0xFFE53935).copy(alpha = 0.92f),
                                        shape = CircleShape
                                    )
                                    .clickable { onRemoveAttachment(idx) }
                            ) {
                                Icon(
                                    Icons.Filled.Close,
                                    contentDescription = "移除图片 ${idx + 1}",
                                    tint = Color.White,
                                    modifier = Modifier.size(12.dp)
                                )
                            }
                        }
                    }
                }
            }
            // 语音识别状态提示
            AnimatedVisibility(
                visible = quotedMessage != null,
                enter = expandVertically() + fadeIn(),
                exit = shrinkVertically() + fadeOut()
            ) {
                quotedMessage?.let { quote ->
                    Surface(
                        color = MaterialTheme.colorScheme.surfaceVariant.copy(0.72f),
                        shape = RoundedCornerShape(10.dp),
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 12.dp, vertical = 6.dp)
                    ) {
                        Row(
                            modifier = Modifier.padding(start = 10.dp, top = 8.dp, end = 6.dp, bottom = 8.dp),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Box(
                                modifier = Modifier
                                    .width(3.dp)
                                    .height(34.dp)
                                    .clip(RoundedCornerShape(999.dp))
                                    .background(Primary)
                            )
                            Spacer(Modifier.width(9.dp))
                            Column(modifier = Modifier.weight(1f)) {
                                Text(
                                    text = "引用 ${quote.sender.ifBlank { if (quote.role == "user") "我" else "AI" }}",
                                    color = Primary,
                                    style = MaterialTheme.typography.labelSmall,
                                    fontWeight = FontWeight.SemiBold,
                                    maxLines = 1,
                                    overflow = TextOverflow.Ellipsis
                                )
                                Text(
                                    text = quote.content,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    style = MaterialTheme.typography.bodySmall,
                                    maxLines = 1,
                                    overflow = TextOverflow.Ellipsis
                                )
                            }
                            IconButton(onClick = onClearQuotedMessage, modifier = Modifier.size(30.dp)) {
                                Icon(
                                    Icons.Filled.Close,
                                    contentDescription = "取消引用",
                                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                                    modifier = Modifier.size(16.dp)
                                )
                            }
                        }
                    }
                }
            }

            AnimatedVisibility(
                visible = isVoiceActive,
                enter = slideInVertically() + fadeIn(),
                exit = slideOutVertically() + fadeOut()
            ) {
                Surface(
                    color = Primary.copy(0.08f),
                    shape = RoundedCornerShape(12.dp),
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 12.dp, vertical = 6.dp)
                ) {
                    Row(
                        modifier = Modifier.padding(horizontal = 14.dp, vertical = 10.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        StreamingDot()
                        Spacer(Modifier.width(10.dp))
                        Text(
                            text = when (voiceState) {
                                is VoiceState.Listening -> "正在聆听..."
                                is VoiceState.Partial -> voiceState.text.ifBlank { "正在聆听..." }
                                is VoiceState.Processing -> "处理中..."
                                else -> ""
                            },
                            color = Primary,
                            style = MaterialTheme.typography.bodySmall,
                            fontWeight = FontWeight.Medium
                        )
                    }
                }
            }

            // 主输入区域
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(start = 10.dp, end = 10.dp, top = ChatInputBarVerticalUnit, bottom = 0.dp)
            ) {
                // 输入框行
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.Bottom
                ) {
                    // 输入框（圆角胶囊风格，默认高度与发送按钮一致 42.dp）
                    Surface(
                        color = inputFieldContainerColor,
                        shape = RoundedCornerShape(22.dp),
                        border = BorderStroke(1.dp, inputFieldBorderColor),
                        tonalElevation = if (isDarkTheme) 0.dp else 1.dp,
                        modifier = Modifier
                            .weight(1f)
                            .height(inputFieldHeight)
                            .onGloballyPositioned { coords ->
                                val pos = coords.positionInWindow()
                                inputFieldWindowBounds = Rect(
                                    left = pos.x,
                                    top = pos.y,
                                    right = pos.x + coords.size.width,
                                    bottom = pos.y + coords.size.height
                                )
                            }
                    ) {
                        androidx.compose.foundation.text.BasicTextField(
                            value = inputFieldValue,
                            onValueChange = { value ->
                                inputFieldValue = value
                                onTextChange(value.text)
                            },
                            enabled = true,
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(horizontal = 16.dp, vertical = inputFieldVerticalPadding)
                                .focusRequester(inputFocusRequester)
                                .onFocusChanged { focusState ->
                                    isInputFocused = focusState.isFocused
                                },
                            textStyle = MaterialTheme.typography.titleSmall.copy(
                                color = MaterialTheme.colorScheme.onBackground,
                                lineHeight = 21.sp,
                                letterSpacing = 0.8.sp
                            ),
                            cursorBrush = SolidColor(MaterialTheme.colorScheme.onBackground),
                            maxLines = 5,
                            minLines = 1,
                            visualTransformation = remember(selectedMentionNames) {
                                MentionTextVisualTransformation(selectedMentionNames)
                            },
                            onTextLayout = { layoutResult ->
                                inputLineCount = if (text.isEmpty()) {
                                    1
                                } else {
                                    layoutResult.lineCount.coerceIn(1, 5)
                                }
                            },
                            decorationBox = { innerTextField ->
                                Box(
                                    contentAlignment = Alignment.CenterStart
                                ) {
                                    if (text.isEmpty() && isVoiceActive) {
                                        Text(
                                            "语音识别中...",
                                            color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.45f),
                                            style = MaterialTheme.typography.titleSmall.copy(
                                                lineHeight = 21.sp,
                                                letterSpacing = 0.8.sp
                                            )
                                        )
                                    }
                                    innerTextField()
                                }
                            }
                        )
                    }

                    Spacer(Modifier.width(8.dp))

                    // 圆形发送按钮；默认高度跟随单行输入框，空输入不可发送，但允许仅发送图片
                    val canSend = (text.isNotBlank() || imageAttachments.isNotEmpty()) &&
                        (mode == "normal" || !isStreaming) &&
                        (mode == "normal" || !quotaExceeded)
                    Surface(
                        onClick = { if (canSend) onSend() },
                        color = if (canSend) Primary else MaterialTheme.colorScheme.surfaceVariant,
                        shape = RoundedCornerShape(50),
                        modifier = Modifier
                            .size(inputFieldMinHeight)
                            .onGloballyPositioned { coords ->
                                val pos = coords.positionInWindow()
                                sendButtonWindowBounds = Rect(
                                    left = pos.x,
                                    top = pos.y,
                                    right = pos.x + coords.size.width,
                                    bottom = pos.y + coords.size.height
                                )
                            }
                    ) {
                        Box(contentAlignment = Alignment.Center, modifier = Modifier.fillMaxSize()) {
                            Icon(
                                Icons.Filled.ArrowUpward,
                                contentDescription = "发送",
                                tint = if (canSend) Color.White else MaterialTheme.colorScheme.onSurfaceVariant.copy(0.4f),
                                modifier = Modifier.size(20.dp)
                            )
                        }
                    }
                }

                // 底部工具栏
                val isGalgameMode = mode == "galgame" || mode == "galgame_lock"
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .onGloballyPositioned { coords ->
                            val pos = coords.positionInWindow()
                            toolbarWindowBounds = Rect(
                                left = pos.x,
                                top = pos.y,
                                right = pos.x + coords.size.width,
                                bottom = pos.y + coords.size.height
                            )
                        }
                        .padding(top = 0.dp, bottom = 0.dp),
                    horizontalArrangement = Arrangement.SpaceEvenly
                ) {
                    PonyToolIcon(
                        icon = Icons.Filled.Image,
                        tint = if (isGalgameMode || !supportsVision) MaterialTheme.colorScheme.onSurfaceVariant.copy(0.25f)
                               else MaterialTheme.colorScheme.onSurfaceVariant.copy(0.6f),
                        onClick = when {
                            isGalgameMode -> { { hideKeyboardForPanelSwitch(); onShowPrompt("当前模式不支持该功能") } }
                            supportsVision -> { { hideKeyboardForPanelSwitch(); onPickImage() } }
                            else -> { { hideKeyboardForPanelSwitch(); onShowPrompt("当前模型不支持图像识别") } }
                        }
                    )
                    PonyToolIcon(
                        icon = Icons.Filled.CameraAlt,
                        tint = if (isGalgameMode || !supportsVision) MaterialTheme.colorScheme.onSurfaceVariant.copy(0.25f)
                               else MaterialTheme.colorScheme.onSurfaceVariant.copy(0.6f),
                        onClick = when {
                            isGalgameMode -> { { hideKeyboardForPanelSwitch(); onShowPrompt("当前模式不支持该功能") } }
                            supportsVision -> { { hideKeyboardForPanelSwitch(); onPickCamera() } }
                            else -> { { hideKeyboardForPanelSwitch(); onShowPrompt("当前模型不支持图像识别") } }
                        }
                    )
                    PonyToolIcon(
                        icon = Icons.Filled.EmojiEmotions,
                        tint = if (showEmojiPicker) Primary else MaterialTheme.colorScheme.onSurfaceVariant.copy(0.6f),
                        onClick = {
                            val nextEmoji = !showEmojiPicker
                            switchPanelsFromToolbar(emoji = nextEmoji, quick = false, more = false)
                            if (nextEmoji && stickers.isEmpty()) onLoadStickers()
                        }
                    )
                    PonyToolIcon(
                        icon = Icons.Filled.Bolt,
                        tint = when {
                            isGalgameMode -> MaterialTheme.colorScheme.onSurfaceVariant.copy(0.25f)
                            showQuickMessagePanel -> Primary
                            else -> MaterialTheme.colorScheme.onSurfaceVariant.copy(0.6f)
                        },
                        onClick = if (isGalgameMode) {
                            { hideKeyboardForPanelSwitch(); onShowPrompt("当前模式不支持该功能") }
                        } else {
                            {
                                switchPanelsFromToolbar(
                                    emoji = false,
                                    quick = !showQuickMessagePanel,
                                    more = false
                                )
                            }
                        }
                    )
                    PonyToolIcon(
                        icon = Icons.Filled.AddCircleOutline,
                        tint = when {
                            isGalgameMode -> MaterialTheme.colorScheme.onSurfaceVariant.copy(0.25f)
                            showMorePanel -> Primary
                            else -> MaterialTheme.colorScheme.onSurfaceVariant.copy(0.6f)
                        },
                        onClick = if (isGalgameMode) {
                            { hideKeyboardForPanelSwitch(); onShowPrompt("当前模式不支持该功能") }
                        } else {
                            {
                                switchPanelsFromToolbar(
                                    emoji = false,
                                    quick = false,
                                    more = !showMorePanel
                                )
                            }
                        }
                    )
                }
            }

            val activePanelHeight = when {
                showEmojiPicker -> emojiPanelHeight
                showQuickMessagePanel -> quickMessagePanelHeight
                showMorePanel -> morePanelHeight
                else -> 0.dp
            }
            if (activePanelHeight > 0.dp) {
                Surface(
                    color = MaterialTheme.colorScheme.surfaceVariant,
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(activePanelHeight)
                ) {
                    when {
                        showEmojiPicker -> {
                            EmojiPickerPanel(
                                stickers = stickers,
                                isLoadingStickers = isLoadingStickers,
                                onEmojiSelected = { emoji ->
                                    onTextChange(text + emoji)
                                },
                                onStickerSelected = onStickerSend,
                                onStickerDelete = onStickerDelete,
                                onStickerPreview = onStickerPreview,
                                onUploadSticker = {
                                    stickerPickerLauncher.launch(
                                        PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)
                                    )
                                }
                            )
                        }
                        showQuickMessagePanel -> {
                            QuickMessagePanel(
                                quickMessages = quickMessages,
                                isLoading = isLoadingQuickMessages,
                                onSend = { content ->
                                    setPanels(emoji = false, quick = false, more = false)
                                    onQuickMessageSend(content)
                                },
                                onFill = { content ->
                                    appendQuickMessageToInput(content)
                                },
                                onAdd = onQuickMessageAdd,
                                onUpdate = onQuickMessageUpdate,
                                onDelete = onQuickMessageDelete
                            )
                        }
                        showMorePanel -> {
                            MoreFunctionPanel(
                                isCompanionActive = isCompanionActive,
                                showCompanionButton = showCompanionButton,
                                isAgentCompanionActive = isAgentCompanionActive,
                                isAgentAutoLooping = isAgentAutoLooping,
                                activePage = moreFunctionPage,
                                onBackToMain = { moreFunctionPage = MoreFunctionPage.Main },
                                onProactiveTasksClick = {
                                    onProactiveTasksClick()
                                    scope.launch {
                                        kotlinx.coroutines.delay(320)
                                        setPanels(emoji = false, quick = false, more = false)
                                    }
                                },
                                onOpenMiniGamesPage = {
                                    moreFunctionPage = MoreFunctionPage.MiniGames
                                },
                                onOpenCompanionPage = {
                                    moreFunctionPage = MoreFunctionPage.Companion
                                },
                                onCompanionClick = {
                                    setPanels(emoji = false, quick = false, more = false)
                                    onShowPrompt("功能开发中")
                                },
                                onAgentCompanionClick = {
                                    setPanels(emoji = false, quick = false, more = false)
                                    onShowPrompt("功能开发中")
                                },
                                onGameCompanionClick = {
                                    setPanels(emoji = false, quick = false, more = false)
                                    onShowPrompt("功能开发中")
                                },
                                onChineseChessClick = {
                                    setPanels(emoji = false, quick = false, more = false)
                                    onChineseChessClick()
                                },
                                onTicTacToeClick = {
                                    setPanels(emoji = false, quick = false, more = false)
                                    onTicTacToeClick()
                                },
                                onDoudizhuClick = {
                                    setPanels(emoji = false, quick = false, more = false)
                                    onDoudizhuClick()
                                },
                                onCompanionSettingsClick = {
                                    setPanels(emoji = false, quick = false, more = false)
                                    onShowPrompt("功能开发中")
                                }
                            )
                        }
                    }
                }
            }
        }
    }
}

// ── 更多功能面板（2 行 × 4 列卡片） ──────────────────────────────────────────

