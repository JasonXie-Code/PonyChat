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
import androidx.compose.ui.graphics.Path
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


@Composable
internal fun MoreFunctionPanel(
    isCompanionActive: Boolean,
    showCompanionButton: Boolean,
    isAgentCompanionActive: Boolean,
    isAgentAutoLooping: Boolean = false,
    activePage: MoreFunctionPage,
    onBackToMain: () -> Unit,
    onProactiveTasksClick: () -> Unit,
    onOpenMiniGamesPage: () -> Unit,
    onOpenCompanionPage: () -> Unit,
    onCompanionClick: () -> Unit,
    onAgentCompanionClick: () -> Unit,
    onGameCompanionClick: () -> Unit,
    onChineseChessClick: () -> Unit,
    onTicTacToeClick: () -> Unit,
    onDoudizhuClick: () -> Unit,
    onCompanionSettingsClick: () -> Unit
) {
    // 定义 8 个卡片槽位，null 表示空位
    data class FuncItem(
        val icon: androidx.compose.ui.graphics.vector.ImageVector? = null,
        val customIcon: MoreFunctionCustomIcon? = null,
        val label: String,
        val active: Boolean = false,
        val enabled: Boolean = true,
        val onClick: () -> Unit
    )

    val mainItems: List<FuncItem?> = listOf(
        FuncItem(
            icon = Icons.Filled.NotificationsActive,
            label = "定时任务",
            onClick = onProactiveTasksClick
        ),
        FuncItem(
            icon = Icons.Filled.SportsEsports,
            label = "小游戏",
            onClick = onOpenMiniGamesPage
        ),
        FuncItem(
            icon = Icons.Filled.Reviews,
            label = "陪玩",
            active = isCompanionActive || isAgentCompanionActive || isAgentAutoLooping,
            enabled = showCompanionButton,
            onClick = onOpenCompanionPage
        ),
        null, null,
        null, null, null
    )

    val companionItems: List<FuncItem?> = listOf(
        FuncItem(
            icon = Icons.Filled.Reviews,
            label = if (isCompanionActive && !isAgentCompanionActive) "关闭聊天陪玩" else "聊天陪玩",
            active = isCompanionActive && !isAgentCompanionActive,
            enabled = showCompanionButton,
            onClick = onCompanionClick
        ),
        FuncItem(
            icon = Icons.Filled.TouchApp,
            label = when {
                isAgentAutoLooping -> "执行中…"
                isAgentCompanionActive -> "关闭操作陪玩"
                else -> "操作陪玩"
            },
            active = isAgentCompanionActive || isAgentAutoLooping,
            enabled = showCompanionButton,
            onClick = onAgentCompanionClick
        ),
        FuncItem(
            icon = Icons.Filled.SportsEsports,
            label = "游戏陪玩",
            active = false,
            enabled = true,
            onClick = onGameCompanionClick
        ),
        FuncItem(
            icon = Icons.Filled.Settings,
            label = "陪玩设置",
            active = false,
            enabled = true,
            onClick = onCompanionSettingsClick
        )
    )

    val miniGameItems: List<FuncItem?> = listOf(
        FuncItem(
            customIcon = MoreFunctionCustomIcon.ChineseChess,
            label = "中国象棋",
            active = false,
            enabled = true,
            onClick = onChineseChessClick
        ),
        FuncItem(
            customIcon = MoreFunctionCustomIcon.Doudizhu,
            label = "斗地主",
            active = false,
            enabled = true,
            onClick = onDoudizhuClick
        ),
        FuncItem(
            customIcon = MoreFunctionCustomIcon.TicTacToe,
            label = "井字棋",
            active = false,
            enabled = true,
            onClick = onTicTacToeClick
        )
    )

    Surface(
        color = MaterialTheme.colorScheme.surfaceVariant.copy(0.4f),
        modifier = Modifier.fillMaxWidth()
    ) {
        Column(
            modifier = Modifier.padding(horizontal = 16.dp, vertical = 16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            AnimatedContent(
                targetState = activePage,
                label = "more-function-page",
                transitionSpec = {
                    val forward = targetState.ordinal > initialState.ordinal
                    (fadeIn(tween(140)) + slideInHorizontally { if (forward) it / 4 else -it / 4 })
                        .togetherWith(fadeOut(tween(100)) + slideOutHorizontally { if (forward) -it / 4 else it / 4 })
                }
            ) { page ->
                Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    if (page != MoreFunctionPage.Main) {
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .height(34.dp),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            IconButton(
                                onClick = onBackToMain,
                                modifier = Modifier.size(34.dp)
                            ) {
                                Icon(
                                    Icons.AutoMirrored.Filled.ArrowBack,
                                    contentDescription = "返回",
                                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                                    modifier = Modifier.size(20.dp)
                                )
                            }
                            Spacer(Modifier.width(4.dp))
                            Text(
                                text = when (page) {
                                    MoreFunctionPage.MiniGames -> "小游戏"
                                    MoreFunctionPage.Companion -> "陪玩"
                                    MoreFunctionPage.Main -> ""
                                },
                                style = MaterialTheme.typography.titleSmall,
                                fontWeight = FontWeight.SemiBold,
                                color = MaterialTheme.colorScheme.onSurface
                            )
                        }
                    }
                    val items = when (page) {
                        MoreFunctionPage.Main -> mainItems
                        MoreFunctionPage.MiniGames -> miniGameItems
                        MoreFunctionPage.Companion -> companionItems
                    }
                    for (row in 0..1) {
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.spacedBy(12.dp)
                        ) {
                            for (col in 0..3) {
                                val idx = row * 4 + col
                                val item = items.getOrNull(idx)
                                Box(modifier = Modifier.weight(1f)) {
                                    if (item != null) {
                                        MoreFuncCard(
                                            icon = item.icon,
                                            customIcon = item.customIcon,
                                            label = item.label,
                                            active = item.active,
                                            enabled = item.enabled,
                                            onClick = item.onClick
                                        )
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
private fun MoreFuncCard(
    icon: androidx.compose.ui.graphics.vector.ImageVector?,
    customIcon: MoreFunctionCustomIcon? = null,
    label: String,
    active: Boolean = false,
    enabled: Boolean = true,
    onClick: () -> Unit
) {
    val iconBg = when {
        active -> Primary
        enabled -> MaterialTheme.colorScheme.surface
        else -> MaterialTheme.colorScheme.surfaceVariant.copy(0.5f)
    }
    val iconTint = when {
        active -> Color.White
        enabled -> MaterialTheme.colorScheme.onSurface
        else -> MaterialTheme.colorScheme.onSurface.copy(0.3f)
    }
    val labelColor = if (enabled)
        MaterialTheme.colorScheme.onSurface.copy(0.7f)
    else
        MaterialTheme.colorScheme.onSurface.copy(0.3f)

    Column(
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(6.dp)
    ) {
        Surface(
            onClick = { if (enabled) onClick() },
            color = iconBg,
            shape = RoundedCornerShape(14.dp),
            shadowElevation = if (enabled) 1.dp else 0.dp,
            modifier = Modifier
                .fillMaxWidth()
                .aspectRatio(1f)
        ) {
            Box(contentAlignment = Alignment.Center, modifier = Modifier.fillMaxSize()) {
                when (customIcon) {
                    MoreFunctionCustomIcon.ChineseChess -> {
                        ChineseChessPieceIcon(
                            tint = iconTint,
                            modifier = Modifier.size(31.dp)
                        )
                    }
                    MoreFunctionCustomIcon.TicTacToe -> {
                        TicTacToeGridIcon(
                            tint = iconTint,
                            modifier = Modifier.size(31.dp)
                        )
                    }
                    MoreFunctionCustomIcon.Doudizhu -> {
                        DoudizhuClubIcon(
                            tint = Color.White,
                            modifier = Modifier.size(31.dp)
                        )
                    }
                    null -> {
                        icon?.let {
                            Icon(
                                imageVector = it,
                                contentDescription = label,
                                tint = iconTint,
                                modifier = Modifier.size(28.dp)
                            )
                        }
                    }
                }
            }
        }
        Text(
            text = label,
            style = MaterialTheme.typography.labelSmall,
            color = labelColor,
            maxLines = 1,
            textAlign = TextAlign.Center,
            modifier = Modifier.fillMaxWidth()
        )
    }
}

@Composable
private fun DoudizhuClubIcon(
    tint: Color,
    modifier: Modifier = Modifier
) {
    Canvas(modifier = modifier) {
        val d = size.minDimension
        val cx = size.width / 2f
        val cy = size.height / 2f
        val radius = d * 0.18f
        drawCircle(
            color = tint,
            radius = radius,
            center = Offset(cx, cy - d * 0.23f)
        )
        drawCircle(
            color = tint,
            radius = radius,
            center = Offset(cx - d * 0.20f, cy + d * 0.02f)
        )
        drawCircle(
            color = tint,
            radius = radius,
            center = Offset(cx + d * 0.20f, cy + d * 0.02f)
        )
        drawRect(
            color = tint,
            topLeft = Offset(cx - d * 0.075f, cy + d * 0.03f),
            size = Size(d * 0.15f, d * 0.29f)
        )
        val base = Path().apply {
            moveTo(cx - d * 0.18f, cy + d * 0.36f)
            cubicTo(cx - d * 0.11f, cy + d * 0.28f, cx - d * 0.07f, cy + d * 0.20f, cx - d * 0.04f, cy + d * 0.12f)
            lineTo(cx + d * 0.04f, cy + d * 0.12f)
            cubicTo(cx + d * 0.07f, cy + d * 0.20f, cx + d * 0.11f, cy + d * 0.28f, cx + d * 0.18f, cy + d * 0.36f)
            close()
        }
        drawPath(path = base, color = tint)
    }
}

@Composable
private fun ChineseChessPieceIcon(
    tint: Color,
    modifier: Modifier = Modifier
) {
    Canvas(modifier = modifier) {
        val stroke = size.minDimension * 0.09f
        drawCircle(
            color = tint,
            radius = size.minDimension / 2f - stroke / 2f,
            style = Stroke(width = stroke)
        )
        drawCircle(
            color = tint,
            radius = size.minDimension * 0.35f,
            style = Stroke(width = stroke * 0.58f)
        )
        drawIntoCanvas { canvas ->
            val paint = android.graphics.Paint(android.graphics.Paint.ANTI_ALIAS_FLAG).apply {
                color = tint.toArgb()
                textAlign = android.graphics.Paint.Align.CENTER
                typeface = android.graphics.Typeface.create(
                    android.graphics.Typeface.DEFAULT,
                    android.graphics.Typeface.BOLD
                )
                textSize = 14.sp.toPx()
            }
            val metrics = paint.fontMetrics
            val baseline = center.y - (metrics.ascent + metrics.descent) / 2f
            canvas.nativeCanvas.drawText("象", center.x, baseline, paint)
        }
    }
}

@Composable
private fun TicTacToeGridIcon(
    tint: Color,
    modifier: Modifier = Modifier
) {
    Canvas(modifier = modifier) {
        val stroke = size.minDimension * 0.08f
        val cell = size.minDimension / 3f
        for (i in 1..2) {
            val p = cell * i
            drawLine(
                color = tint,
                start = Offset(p, 0f),
                end = Offset(p, size.height),
                strokeWidth = stroke,
                cap = StrokeCap.Round
            )
            drawLine(
                color = tint,
                start = Offset(0f, p),
                end = Offset(size.width, p),
                strokeWidth = stroke,
                cap = StrokeCap.Round
            )
        }
        val markStroke = stroke * 0.74f
        val pad = cell * 0.26f
        drawLine(
            color = tint,
            start = Offset(pad, pad),
            end = Offset(cell - pad, cell - pad),
            strokeWidth = markStroke,
            cap = StrokeCap.Round
        )
        drawLine(
            color = tint,
            start = Offset(cell - pad, pad),
            end = Offset(pad, cell - pad),
            strokeWidth = markStroke,
            cap = StrokeCap.Round
        )
        drawCircle(
            color = tint,
            radius = cell * 0.22f,
            center = Offset(cell * 2.5f, cell * 1.5f),
            style = Stroke(width = markStroke)
        )
    }
}

