package top.ponychat.webview.ui.chat

import android.util.Log
import android.Manifest
import android.content.ClipData
import android.content.ClipboardManager
import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
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
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.layout.positionInWindow
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
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
import top.ponychat.webview.ui.common.PonyTopBar
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

// ==================== 显示设置页面 ====================

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
fun ChatDisplaySettingsScreen(
    prefs: AppPreferences,
    onDismiss: () -> Unit,
    onThemeChanged: (Boolean) -> Unit = {},
    onSave: (AppPreferences) -> Unit,
    // 调试板块回调
    currentMode: String = "normal",
    currentGalgameScore: Int? = null,
    onDebugForceScore: (Int) -> Unit = {},
    onDebugAdjustScore: (Int) -> Unit = {},
    onDebugTriggerVictory: () -> Unit = {},
    onDebugTriggerError: (String) -> Unit = {},
    onDebugClearError: () -> Unit = {},
    onDebugInjectMessage: () -> Unit = {},
    onDebugInjectPendingUserAccept: () -> Unit = {},
    onDebugInjectTimedOutUserAccept: () -> Unit = {},
    onDebugAcceptPendingUsers: () -> Unit = {},
    onDebugInjectDelayedNormalSingle: () -> Unit = {},
    onDebugInjectDelayedNormalInstantTriple: () -> Unit = {},
    onDebugInjectDelayedNormalIntervalTriple: () -> Unit = {},
    onDebugInjectDelayedProactiveSingle: () -> Unit = {},
    onDebugInjectDelayedProactiveInstantTriple: () -> Unit = {},
    onDebugInjectDelayedProactiveIntervalTriple: () -> Unit = {},
    onDebugInjectLongPressSamples: () -> Unit = {},
    onDebugInjectImagePreviewSamples: () -> Unit = {},
    onDebugInjectVoiceMessage: () -> Unit = {},
    onDebugInjectUserVoiceMessage: () -> Unit = {},
    onDebugGenerateBackendVoice: () -> Unit = {},
    onDebugInjectVoiceCacheMissing: () -> Unit = {},
    onDebugInjectVoiceFailed: () -> Unit = {},
    onDebugResetVictory: () -> Unit = {},
    currentQuotaInfo: top.ponychat.webview.data.model.QuotaInfo? = null,
    onDebugLoadQuota: () -> Unit = {},
    onDebugSimulateQuotaExceeded: () -> Unit = {},
    onDebugClearQuotaExceeded: () -> Unit = {},
    onDebugForceSummarize: () -> Unit = {},
    onDebugShowUsageReminder: () -> Unit = {},
    onDebugCopyConvId: () -> Unit = {},
    onDebugPrintSnapshot: () -> Unit = {},
    onDebugClearCache: () -> Unit = {},
    debugRelationshipStage: String = "uncertain",
    debugRelationshipUsesOverride: Boolean = false,
    onDebugSetRelationshipStage: (String) -> Unit = {},
    onDebugUseServerRelationshipStage: () -> Unit = {},
    // 状态统计展示（功能 4）
    debugConversationId: String? = null,
    debugMessageCount: Int = 0,
    debugIsStreaming: Boolean = false,
    debugIsBackgroundRefreshing: Boolean = false,
) {
    // ── 重组诊断：若频繁出现说明 List<ModelInfo> 等不稳定参数导致无法 skip ──
    if (top.ponychat.webview.BuildConfig.DEBUG) {
        val settingsRecomposeCount = remember { intArrayOf(0) }
        SideEffect {
            settingsRecomposeCount[0]++
            Log.d("PERF_SETTINGS", "ChatDisplaySettingsScreen recomposed x${settingsRecomposeCount[0]}")
        }
    }
    var fontSize by remember { mutableStateOf<Float>(prefs.fontScale) }
    var isDarkTheme by remember { mutableStateOf<Boolean>(prefs.isDarkTheme) }
    var showTimestamp by remember { mutableStateOf<Boolean>(prefs.showTimestamp) }

    val density = LocalDensity.current
    val systemFontScale = LocalConfiguration.current.fontScale
    val effectiveScale = systemFontScale * fontSize
    val settingIconSize = 20.dp * effectiveScale
    val settingTopBarIconSize = 22.dp * effectiveScale
    CompositionLocalProvider(
        LocalDensity provides Density(density.density, effectiveScale),
        LocalFontScale provides effectiveScale
    ) {
        Scaffold(
            containerColor = MaterialTheme.colorScheme.background,
            topBar = {
                PonyTopBar(
                    title = "对话设置",
                    onNavigateBack = onDismiss,
                    iconSize = settingTopBarIconSize
                )
            }
        ) { paddingValues ->
            LazyColumn(
                modifier = Modifier
                    .padding(paddingValues)
            ) {
            // ==================== 显示设置 ====================
            item {
            SectionTitle("显示")
            SettingsCard {
                // 深色主题
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 16.dp, vertical = 12.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Icon(Icons.Filled.DarkMode, contentDescription = null, tint = Primary, modifier = Modifier.size(settingIconSize))
                    Spacer(Modifier.width(12.dp))
                    Text("深色主题", style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.onBackground, modifier = Modifier.weight(1f))
                    ScaledSwitch(
                        checked = isDarkTheme,
                        onCheckedChange = {
                            isDarkTheme = it
                            prefs.isDarkTheme = it
                            onThemeChanged(it)
                        },
                        colors = SwitchDefaults.colors(
                            checkedThumbColor = Color.White,
                            checkedTrackColor = Primary
                        )
                    )
                }
                CardDivider()
                // 字体大小
                Column(modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(Icons.Filled.FormatSize, contentDescription = null, tint = Primary, modifier = Modifier.size(settingIconSize))
                        Spacer(Modifier.width(12.dp))
                        Text("字体大小", style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.onBackground)
                    }
                    Spacer(Modifier.height(8.dp))
                    var sliderValue by remember { mutableFloatStateOf(fontSize) }
                    val haptic = LocalHapticFeedback.current
                    var lastFontStep by remember { mutableIntStateOf(((fontSize - 0.85f) * 20f).roundToInt()) }
                    Slider(
                        value = sliderValue,
                        onValueChange = { v ->
                            sliderValue = v
                            val step = ((v - 0.85f) * 20f).roundToInt()
                            if (step != lastFontStep) {
                                lastFontStep = step
                                haptic.performHapticFeedback(HapticFeedbackType.TextHandleMove)
                            }
                        },
                        onValueChangeFinished = {
                            fontSize = sliderValue
                            prefs.fontScale = sliderValue
                            // 直接保存并通知UI更新字体大小
                            onSave(prefs)
                        },
                        valueRange = 0.85f..1.25f,
                        steps = 7,
                        colors = SliderDefaults.colors(thumbColor = Primary, activeTrackColor = Primary)
                    )
                    Text(
                        text = when {
                            sliderValue < 0.95f -> "小"
                            sliderValue > 1.1f -> "大"
                            else -> "标准"
                        } + " (${(sliderValue * 100).toInt()}%)",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.bodySmall
                    )
                }
                CardDivider()
                // 显示时间戳
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 16.dp, vertical = 12.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Icon(Icons.Filled.Schedule, contentDescription = null, tint = Primary, modifier = Modifier.size(settingIconSize))
                    Spacer(Modifier.width(12.dp))
                    Text("显示时间戳", style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.onBackground, modifier = Modifier.weight(1f))
                    ScaledSwitch(
                        checked = showTimestamp,
                        onCheckedChange = {
                            showTimestamp = it
                            prefs.showTimestamp = it
                            onSave(prefs)
                        },
                        colors = SwitchDefaults.colors(
                            checkedThumbColor = Color.White,
                            checkedTrackColor = Primary
                        )
                    )
                }
            }

            } // end item 显示设置

            // ==================== 角色破限（仅开发者/管理员可见） ====================
            // ==================== 上下文管理（已隐藏） ====================

            // ==================== 调试板块 ====================
            if (prefs.debugMode) {
            item {
            Spacer(Modifier.height(24.dp))
                val debugOrange = Color(0xFFF97316)
                val debugRed = Color(0xFFEF4444)
                val isGalgame = currentMode.startsWith("galgame")

                SectionTitle("调试")
                Surface(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 12.dp),
                    shape = RoundedCornerShape(12.dp),
                    color = debugOrange.copy(alpha = 0.06f),
                    border = BorderStroke(1.dp, debugOrange.copy(alpha = 0.3f))
                ) {
                    Column {

                        // 1. 好感度分数强制覆盖（仅游戏模式显示）
                        if (isGalgame) {
                            var debugScoreInput by remember { mutableStateOf(currentGalgameScore?.toString() ?: "50") }
                            Column(modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp)) {
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    Icon(Icons.Filled.Favorite, contentDescription = null, tint = debugOrange, modifier = Modifier.size(settingIconSize))
                                    Spacer(Modifier.width(12.dp))
                                    Text("好感度分数", style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.onBackground, modifier = Modifier.weight(1f))
                                    Text("当前: ${currentGalgameScore ?: "--"}", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                }
                                Spacer(Modifier.height(8.dp))
                                Row(
                                    verticalAlignment = Alignment.CenterVertically,
                                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                                ) {
                                    OutlinedTextField(
                                        value = debugScoreInput,
                                        onValueChange = { if (it.length <= 3) debugScoreInput = it.filter { c -> c.isDigit() } },
                                        modifier = Modifier.width(80.dp),
                                        singleLine = true,
                                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                                        textStyle = MaterialTheme.typography.bodyMedium,
                                        colors = OutlinedTextFieldDefaults.colors(focusedBorderColor = debugOrange, unfocusedBorderColor = debugOrange.copy(alpha = 0.5f))
                                    )
                                    Button(
                                        onClick = { onDebugForceScore(debugScoreInput.toIntOrNull()?.coerceIn(0, 100) ?: 50) },
                                        colors = ButtonDefaults.buttonColors(containerColor = debugOrange),
                                        contentPadding = PaddingValues(horizontal = 12.dp, vertical = 8.dp)
                                    ) { Text("设置", style = MaterialTheme.typography.labelMedium) }
                                    OutlinedButton(
                                        onClick = { onDebugAdjustScore(-10) },
                                        border = BorderStroke(1.dp, debugOrange.copy(alpha = 0.5f)),
                                        contentPadding = PaddingValues(horizontal = 8.dp, vertical = 8.dp)
                                    ) { Text("-10", style = MaterialTheme.typography.labelMedium, color = debugOrange) }
                                    OutlinedButton(
                                        onClick = { onDebugAdjustScore(10) },
                                        border = BorderStroke(1.dp, debugOrange.copy(alpha = 0.5f)),
                                        contentPadding = PaddingValues(horizontal = 8.dp, vertical = 8.dp)
                                    ) { Text("+10", style = MaterialTheme.typography.labelMedium, color = debugOrange) }
                                }
                                Spacer(Modifier.height(4.dp))
                                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                    OutlinedButton(
                                        onClick = { onDebugForceScore(0) },
                                        border = BorderStroke(1.dp, debugRed.copy(alpha = 0.6f)),
                                        contentPadding = PaddingValues(horizontal = 10.dp, vertical = 6.dp)
                                    ) { Text("归零 (0)", style = MaterialTheme.typography.labelSmall, color = debugRed) }
                                    OutlinedButton(
                                        onClick = { onDebugForceScore(100) },
                                        border = BorderStroke(1.dp, Color(0xFFEAB308).copy(alpha = 0.8f)),
                                        contentPadding = PaddingValues(horizontal = 10.dp, vertical = 6.dp)
                                    ) { Text("满分 (100)", style = MaterialTheme.typography.labelSmall, color = Color(0xFFEAB308)) }
                                    OutlinedButton(
                                        onClick = onDebugTriggerVictory,
                                        border = BorderStroke(1.dp, Color(0xFF22C55E).copy(alpha = 0.8f)),
                                        contentPadding = PaddingValues(horizontal = 10.dp, vertical = 6.dp)
                                    ) { Text("预览胜利动画", style = MaterialTheme.typography.labelSmall, color = Color(0xFF22C55E)) }
                                }
                            }
                            HorizontalDivider(modifier = Modifier.padding(start = 48.dp), color = debugOrange.copy(alpha = 0.15f))
                        }

                        // 2. 显示消息 ID
                        var debugShowIds by remember { mutableStateOf(prefs.debugShowMessageIds) }
                        Row(
                            modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Icon(Icons.Filled.Tag, contentDescription = null, tint = debugOrange, modifier = Modifier.size(settingIconSize))
                            Spacer(Modifier.width(12.dp))
                            Column(modifier = Modifier.weight(1f)) {
                                Text("显示消息 ID", style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.onBackground)
                                Text("在气泡下方显示内部 UUID", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            }
                            ScaledSwitch(
                                checked = debugShowIds,
                                onCheckedChange = { debugShowIds = it; prefs.debugShowMessageIds = it; onSave(prefs) },
                                colors = SwitchDefaults.colors(checkedThumbColor = Color.White, checkedTrackColor = debugOrange)
                            )
                        }
                        HorizontalDivider(modifier = Modifier.padding(start = 48.dp), color = debugOrange.copy(alpha = 0.15f))

                        // 3. 禁用消息富文本渲染
                        var debugShowRaw by remember { mutableStateOf(prefs.debugShowRawContent) }
                        Row(
                            modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Icon(Icons.Filled.Code, contentDescription = null, tint = debugOrange, modifier = Modifier.size(settingIconSize))
                            Spacer(Modifier.width(12.dp))
                            Column(modifier = Modifier.weight(1f)) {
                                Text("禁用渲染/显示纯文本", style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.onBackground)
                                Text("跳过 Markdown 或剧情视图渲染，按纯文本展示", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            }
                            ScaledSwitch(
                                checked = debugShowRaw,
                                onCheckedChange = { debugShowRaw = it; prefs.debugShowRawContent = it; onSave(prefs) },
                                colors = SwitchDefaults.colors(checkedThumbColor = Color.White, checkedTrackColor = debugOrange)
                            )
                        }
                        HorizontalDivider(modifier = Modifier.padding(start = 48.dp), color = debugOrange.copy(alpha = 0.15f))

                        // 4. 禁用键盘弹起自动滚动
                        var debugDisableScroll by remember { mutableStateOf(prefs.debugDisableImeScroll) }
                        Row(
                            modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Icon(Icons.Filled.KeyboardArrowDown, contentDescription = null, tint = debugOrange, modifier = Modifier.size(settingIconSize))
                            Spacer(Modifier.width(12.dp))
                            Column(modifier = Modifier.weight(1f)) {
                                Text("禁用键盘弹起滚动", style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.onBackground)
                                Text("键盘弹出时不自动滚动到底部", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            }
                            ScaledSwitch(
                                checked = debugDisableScroll,
                                onCheckedChange = { debugDisableScroll = it; prefs.debugDisableImeScroll = it; onSave(prefs) },
                                colors = SwitchDefaults.colors(checkedThumbColor = Color.White, checkedTrackColor = debugOrange)
                            )
                        }
                        HorizontalDivider(modifier = Modifier.padding(start = 48.dp), color = debugOrange.copy(alpha = 0.15f))

                        // 5. 弱网收发调试
                        var debugWeakNetwork by remember { mutableStateOf(prefs.debugWeakNetworkCycle) }
                        Row(
                            modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Icon(Icons.Filled.NetworkCheck, contentDescription = null, tint = debugOrange, modifier = Modifier.size(settingIconSize))
                            Spacer(Modifier.width(12.dp))
                            Column(modifier = Modifier.weight(1f)) {
                                Text("弱网循环 5s/5s", style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.onBackground)
                                Text("开启后前 5 秒联网，随后 5 秒断网，循环模拟收发波动", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            }
                            ScaledSwitch(
                                checked = debugWeakNetwork,
                                onCheckedChange = {
                                    debugWeakNetwork = it
                                    prefs.debugWeakNetworkCycle = it
                                    onSave(prefs)
                                },
                                colors = SwitchDefaults.colors(checkedThumbColor = Color.White, checkedTrackColor = debugOrange)
                            )
                        }
                        HorizontalDivider(modifier = Modifier.padding(start = 48.dp), color = debugOrange.copy(alpha = 0.15f))

                        // 5. 关系页阶段预览调试
                        if (!isGalgame) {
                            var debugRelationshipStageLocal by remember(debugRelationshipStage, debugRelationshipUsesOverride) {
                                mutableStateOf(normalizeRelationshipStageKey(debugRelationshipStage))
                            }
                            Column(modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp)) {
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    Icon(Icons.Filled.People, contentDescription = null, tint = debugOrange, modifier = Modifier.size(settingIconSize))
                                    Spacer(Modifier.width(12.dp))
                                    Column(modifier = Modifier.weight(1f)) {
                                        Text("关系页阶段预览", style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.onBackground)
                                        Text("只切换当前 App 内存状态，不请求后端、不写服务器", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                    }
                                }
                                Spacer(Modifier.height(10.dp))
                                FlowRow(
                                    modifier = Modifier.fillMaxWidth(),
                                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                                    verticalArrangement = Arrangement.spacedBy(8.dp)
                                ) {
                                    FilterChip(
                                        selected = !debugRelationshipUsesOverride,
                                        onClick = {
                                            debugRelationshipStageLocal = normalizeRelationshipStageKey(debugRelationshipStage)
                                            onDebugUseServerRelationshipStage()
                                        },
                                        label = {
                                            Text(
                                                "当前",
                                                style = MaterialTheme.typography.labelSmall
                                            )
                                        },
                                        colors = FilterChipDefaults.filterChipColors(
                                            selectedContainerColor = debugOrange.copy(alpha = 0.16f),
                                            selectedLabelColor = debugOrange
                                        ),
                                        border = FilterChipDefaults.filterChipBorder(
                                            enabled = true,
                                            selected = !debugRelationshipUsesOverride,
                                            borderColor = debugOrange.copy(alpha = 0.35f),
                                            selectedBorderColor = debugOrange.copy(alpha = 0.65f)
                                        )
                                    )
                                    RELATIONSHIP_STAGE_KEYS.forEach { stageKey ->
                                        val selected = debugRelationshipUsesOverride && debugRelationshipStageLocal == stageKey
                                        FilterChip(
                                            selected = selected,
                                            onClick = {
                                                debugRelationshipStageLocal = stageKey
                                                onDebugSetRelationshipStage(stageKey)
                                            },
                                            label = {
                                                Text(
                                                    relationshipStageCn(stageKey),
                                                    style = MaterialTheme.typography.labelSmall
                                                )
                                            },
                                            colors = FilterChipDefaults.filterChipColors(
                                                selectedContainerColor = debugOrange.copy(alpha = 0.16f),
                                                selectedLabelColor = debugOrange
                                            ),
                                            border = FilterChipDefaults.filterChipBorder(
                                                enabled = true,
                                                selected = selected,
                                                borderColor = debugOrange.copy(alpha = 0.35f),
                                                selectedBorderColor = debugOrange.copy(alpha = 0.65f)
                                            )
                                        )
                                    }
                                }
                            }
                            HorizontalDivider(modifier = Modifier.padding(start = 48.dp), color = debugOrange.copy(alpha = 0.15f))
                        }

                        // 5. 普通对话保存调试
                        if (!isGalgame) {
                            var debugForceUserEdit by remember { mutableStateOf(prefs.debugForceAlwaysUserEdit) }
                            Row(
                                modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp),
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                Icon(Icons.Filled.Save, contentDescription = null, tint = debugOrange, modifier = Modifier.size(settingIconSize))
                                Spacer(Modifier.width(12.dp))
                                Column(modifier = Modifier.weight(1f)) {
                                    Text("普通对话保存强制 user_edit", style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.onBackground)
                                    Text("仅影响普通对话 saveConversation，绕过防误删检测", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                }
                                ScaledSwitch(
                                    checked = debugForceUserEdit,
                                    onCheckedChange = { debugForceUserEdit = it; prefs.debugForceAlwaysUserEdit = it; onSave(prefs) },
                                    colors = SwitchDefaults.colors(checkedThumbColor = Color.White, checkedTrackColor = debugOrange)
                                )
                            }
                            HorizontalDivider(modifier = Modifier.padding(start = 48.dp), color = debugOrange.copy(alpha = 0.15f))
                        }

                        // 6. 图片消息 UI 调试
                        if (!isGalgame) {
                            val imageBlue = Color(0xFF60A5FA)
                            Column(modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp)) {
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    Icon(Icons.Filled.Image, contentDescription = null, tint = imageBlue, modifier = Modifier.size(settingIconSize))
                                    Spacer(Modifier.width(12.dp))
                                    Column(modifier = Modifier.weight(1f)) {
                                        Text("图片消息", style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.onBackground)
                                        Text("注入用户/角色多图样例，验证缩略图左右对齐", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                    }
                                }
                                Spacer(Modifier.height(10.dp))
                                OutlinedButton(
                                    onClick = onDebugInjectImagePreviewSamples,
                                    border = BorderStroke(1.dp, imageBlue.copy(alpha = 0.7f)),
                                    contentPadding = PaddingValues(horizontal = 10.dp, vertical = 8.dp)
                                ) {
                                    Icon(Icons.Filled.PhotoLibrary, contentDescription = null, tint = imageBlue, modifier = Modifier.size(16.dp))
                                    Spacer(Modifier.width(6.dp))
                                    Text("图片布局样例", style = MaterialTheme.typography.labelSmall, color = imageBlue)
                                }
                            }
                            HorizontalDivider(modifier = Modifier.padding(start = 48.dp), color = debugOrange.copy(alpha = 0.15f))
                        }

                        // 7. 语音消息 UI 调试
                        if (!isGalgame) {
                            val voiceTeal = Color(0xFF14B8A6)
                            Column(modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp)) {
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    Icon(Icons.Filled.GraphicEq, contentDescription = null, tint = voiceTeal, modifier = Modifier.size(settingIconSize))
                                    Spacer(Modifier.width(12.dp))
                                    Column(modifier = Modifier.weight(1f)) {
                                        Text("语音消息", style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.onBackground)
                                        Text("注入本地样例，验证气泡、转文字和回退样式", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                    }
                                }
                                Spacer(Modifier.height(10.dp))
                                FlowRow(
                                    modifier = Modifier.fillMaxWidth(),
                                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                                    verticalArrangement = Arrangement.spacedBy(8.dp)
                                ) {
                                    OutlinedButton(
                                        onClick = onDebugInjectVoiceMessage,
                                        border = BorderStroke(1.dp, voiceTeal.copy(alpha = 0.7f)),
                                        contentPadding = PaddingValues(horizontal = 10.dp, vertical = 8.dp)
                                    ) {
                                        Icon(Icons.Filled.PlayArrow, contentDescription = null, tint = voiceTeal, modifier = Modifier.size(16.dp))
                                        Spacer(Modifier.width(6.dp))
                                        Text("语音气泡", style = MaterialTheme.typography.labelSmall, color = voiceTeal)
                                    }
                                    OutlinedButton(
                                        onClick = onDebugInjectUserVoiceMessage,
                                        border = BorderStroke(1.dp, MaterialTheme.colorScheme.primary.copy(alpha = 0.7f)),
                                        contentPadding = PaddingValues(horizontal = 10.dp, vertical = 8.dp)
                                    ) {
                                        Icon(Icons.Filled.Person, contentDescription = null, tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(16.dp))
                                        Spacer(Modifier.width(6.dp))
                                        Text("用户语音", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.primary)
                                    }
                                    OutlinedButton(
                                        onClick = onDebugGenerateBackendVoice,
                                        border = BorderStroke(1.dp, voiceTeal.copy(alpha = 0.7f)),
                                        contentPadding = PaddingValues(horizontal = 10.dp, vertical = 8.dp)
                                    ) {
                                        Icon(Icons.Filled.VolumeUp, contentDescription = null, tint = voiceTeal, modifier = Modifier.size(16.dp))
                                        Spacer(Modifier.width(6.dp))
                                        Text("后端语音", style = MaterialTheme.typography.labelSmall, color = voiceTeal)
                                    }
                                    OutlinedButton(
                                        onClick = onDebugInjectVoiceCacheMissing,
                                        border = BorderStroke(1.dp, debugOrange.copy(alpha = 0.55f)),
                                        contentPadding = PaddingValues(horizontal = 10.dp, vertical = 8.dp)
                                    ) {
                                        Icon(Icons.Filled.CloudOff, contentDescription = null, tint = debugOrange, modifier = Modifier.size(16.dp))
                                        Spacer(Modifier.width(6.dp))
                                        Text("缓存缺失", style = MaterialTheme.typography.labelSmall, color = debugOrange)
                                    }
                                    OutlinedButton(
                                        onClick = onDebugInjectVoiceFailed,
                                        border = BorderStroke(1.dp, debugRed.copy(alpha = 0.55f)),
                                        contentPadding = PaddingValues(horizontal = 10.dp, vertical = 8.dp)
                                    ) {
                                        Icon(Icons.Filled.ReportProblem, contentDescription = null, tint = debugRed, modifier = Modifier.size(16.dp))
                                        Spacer(Modifier.width(6.dp))
                                        Text("生成失败", style = MaterialTheme.typography.labelSmall, color = debugRed)
                                    }
                                }
                            }
                            HorizontalDivider(modifier = Modifier.padding(start = 48.dp), color = debugOrange.copy(alpha = 0.15f))
                        }

                        // 8. 会员配额调试
                        val quotaAmber = Color(0xFFF59E0B)
                        Column(modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp)) {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Icon(Icons.Filled.WorkspacePremium, contentDescription = null, tint = quotaAmber, modifier = Modifier.size(settingIconSize))
                                Spacer(Modifier.width(12.dp))
                                Text("会员配额", style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.onBackground, modifier = Modifier.weight(1f))
                                OutlinedButton(
                                    onClick = onDebugLoadQuota,
                                    border = BorderStroke(1.dp, quotaAmber.copy(alpha = 0.6f)),
                                    contentPadding = PaddingValues(horizontal = 10.dp, vertical = 4.dp)
                                ) { Text("刷新", style = MaterialTheme.typography.labelSmall, color = quotaAmber) }
                            }
                            Spacer(Modifier.height(8.dp))
                            // 配额信息展示卡
                            Surface(
                                color = quotaAmber.copy(alpha = 0.08f),
                                shape = androidx.compose.foundation.shape.RoundedCornerShape(8.dp),
                                modifier = Modifier.fillMaxWidth()
                            ) {
                                if (currentQuotaInfo != null) {
                                    Column(modifier = Modifier.padding(horizontal = 12.dp, vertical = 10.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                                        Row {
                                            Text("等级：", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                            Text(
                                                "${currentQuotaInfo.membershipLabel} (${currentQuotaInfo.membershipType})",
                                                style = MaterialTheme.typography.labelSmall,
                                                fontWeight = FontWeight.SemiBold,
                                                color = quotaAmber
                                            )
                                        }
                                        Row {
                                            Text("今日用量：", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                            Text(
                                                "${currentQuotaInfo.usedToday} / ${currentQuotaInfo.dailyLimit}（剩余 ${currentQuotaInfo.remaining}）",
                                                style = MaterialTheme.typography.labelSmall,
                                                color = MaterialTheme.colorScheme.onBackground
                                            )
                                        }
                                        if (!currentQuotaInfo.expireAt.isNullOrBlank()) {
                                            Row {
                                                Text("到期：", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                                Text(currentQuotaInfo.expireAt.take(10), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onBackground)
                                            }
                                        }
                                        // 用量进度条
                                        val qProgress = if (currentQuotaInfo.dailyLimit > 0)
                                            (currentQuotaInfo.usedToday.toFloat() / currentQuotaInfo.dailyLimit).coerceIn(0f, 1f)
                                        else 0f
                                        LinearProgressIndicator(
                                            progress = { qProgress },
                                            modifier = Modifier.fillMaxWidth().height(4.dp).clip(androidx.compose.foundation.shape.RoundedCornerShape(2.dp)),
                                            color = when {
                                                qProgress >= 0.9f -> Color(0xFFEF4444)
                                                qProgress >= 0.7f -> Color(0xFFF97316)
                                                else -> quotaAmber
                                            },
                                            trackColor = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.12f)
                                        )
                                    }
                                } else {
                                    Row(
                                        modifier = Modifier.padding(horizontal = 12.dp, vertical = 10.dp),
                                        verticalAlignment = Alignment.CenterVertically
                                    ) {
                                        Text("点击「刷新」从后端加载配额信息", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                    }
                                }
                            }
                            Spacer(Modifier.height(8.dp))
                            // 模拟/清除配额耗尽按钮
                            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                OutlinedButton(
                                    onClick = onDebugSimulateQuotaExceeded,
                                    modifier = Modifier.weight(1f),
                                    border = BorderStroke(1.dp, quotaAmber.copy(alpha = 0.7f)),
                                    contentPadding = PaddingValues(horizontal = 8.dp, vertical = 8.dp)
                                ) { Text("模拟积分耗尽", style = MaterialTheme.typography.labelSmall, color = quotaAmber) }
                                OutlinedButton(
                                    onClick = onDebugClearQuotaExceeded,
                                    modifier = Modifier.weight(1f),
                                    border = BorderStroke(1.dp, debugOrange.copy(alpha = 0.5f)),
                                    contentPadding = PaddingValues(horizontal = 8.dp, vertical = 8.dp)
                                ) { Text("清除配额状态", style = MaterialTheme.typography.labelSmall, color = debugOrange) }
                            }
                        }
                        HorizontalDivider(modifier = Modifier.padding(start = 48.dp), color = debugOrange.copy(alpha = 0.15f))

                        // 8. 预览危机援助提示
                        var showCrisisTestDialog by remember { mutableStateOf(false) }
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .clickable { showCrisisTestDialog = true }
                                .padding(horizontal = 16.dp, vertical = 14.dp),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Icon(
                                Icons.Filled.FavoriteBorder,
                                contentDescription = null,
                                tint = Color(0xFF22C55E),
                                modifier = Modifier.size(settingIconSize)
                            )
                            Spacer(Modifier.width(12.dp))
                            Column(modifier = Modifier.weight(1f)) {
                                Text(
                                    "预览危机援助提示",
                                    style = MaterialTheme.typography.titleSmall,
                                    color = MaterialTheme.colorScheme.onBackground
                                )
                                Text(
                                    "测试弹窗样式与内容",
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant
                                )
                            }
                            Icon(
                                Icons.Filled.ChevronRight,
                                contentDescription = null,
                                tint = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.4f),
                                modifier = Modifier.size(settingIconSize)
                            )
                        }
                        if (showCrisisTestDialog) {
                            CrisisHotlineDialog(onDismiss = { showCrisisTestDialog = false })
                        }
                        HorizontalDivider(modifier = Modifier.padding(start = 48.dp), color = debugOrange.copy(alpha = 0.15f))

                        // 9. 状态快照展示卡（功能 4）
                        Column(modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp)) {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Icon(Icons.Filled.Info, contentDescription = null, tint = debugOrange, modifier = Modifier.size(settingIconSize))
                                Spacer(Modifier.width(12.dp))
                                Text("当前状态", style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.onBackground)
                            }
                            Spacer(Modifier.height(8.dp))
                            Surface(
                                color = debugOrange.copy(alpha = 0.06f),
                                shape = RoundedCornerShape(8.dp),
                                modifier = Modifier.fillMaxWidth()
                            ) {
                                Column(
                                    modifier = Modifier.padding(horizontal = 12.dp, vertical = 10.dp),
                                    verticalArrangement = Arrangement.spacedBy(3.dp)
                                ) {
                                    @Composable
                                    fun StatRow(label: String, value: String, highlight: Boolean = false) {
                                        Row {
                                            Text(
                                                "$label：",
                                                style = MaterialTheme.typography.labelSmall,
                                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                                modifier = Modifier.width(96.dp)
                                            )
                                            Text(
                                                value,
                                                style = MaterialTheme.typography.labelSmall,
                                                fontWeight = if (highlight) FontWeight.SemiBold else FontWeight.Normal,
                                                color = if (highlight) debugOrange else MaterialTheme.colorScheme.onBackground
                                            )
                                        }
                                    }
                                    StatRow(
                                        "对话 ID",
                                        debugConversationId?.let {
                                            if (it.length > 28) it.take(12) + "…" + it.takeLast(8) else it
                                        } ?: "（空）"
                                    )
                                    StatRow("消息数量", "$debugMessageCount 条")
                                    StatRow("关系阶段", relationshipStageCn(debugRelationshipStage))
                                    StatRow("生成中", if (debugIsStreaming) "是" else "否", debugIsStreaming)
                                    StatRow("后台刷新", if (debugIsBackgroundRefreshing) "是" else "否", debugIsBackgroundRefreshing)
                                }
                            }
                        }
                        HorizontalDivider(modifier = Modifier.padding(start = 48.dp), color = debugOrange.copy(alpha = 0.15f))

                        // 11-14. 快捷操作按钮组
                        Column(modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp)) {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Icon(Icons.Filled.PlayArrow, contentDescription = null, tint = debugOrange, modifier = Modifier.size(settingIconSize))
                                Spacer(Modifier.width(12.dp))
                                Text("快捷操作", style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.onBackground)
                            }
                            Spacer(Modifier.height(10.dp))
                            // 复制对话 ID / 打印快照
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.spacedBy(8.dp)
                            ) {
                                OutlinedButton(
                                    onClick = onDebugCopyConvId,
                                    modifier = Modifier.weight(1f),
                                    border = BorderStroke(1.dp, debugOrange.copy(alpha = 0.5f)),
                                    contentPadding = PaddingValues(horizontal = 8.dp, vertical = 8.dp)
                                ) { Text("复制对话 ID", style = MaterialTheme.typography.labelSmall, color = debugOrange) }
                                OutlinedButton(
                                    onClick = onDebugPrintSnapshot,
                                    modifier = Modifier.weight(1f),
                                    border = BorderStroke(1.dp, debugOrange.copy(alpha = 0.5f)),
                                    contentPadding = PaddingValues(horizontal = 8.dp, vertical = 8.dp)
                                ) { Text("打印快照", style = MaterialTheme.typography.labelSmall, color = debugOrange) }
                            }
                            Spacer(Modifier.height(8.dp))
                            // 清除本地缓存
                            OutlinedButton(
                                onClick = onDebugClearCache,
                                modifier = Modifier.fillMaxWidth(),
                                border = BorderStroke(1.dp, debugRed.copy(alpha = 0.5f)),
                                contentPadding = PaddingValues(horizontal = 8.dp, vertical = 8.dp)
                            ) { Text("清除本地缓存（当前角色）", style = MaterialTheme.typography.labelSmall, color = debugRed) }
                            Spacer(Modifier.height(8.dp))
                            // 注入错误消息
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.spacedBy(8.dp)
                            ) {
                                OutlinedButton(
                                    onClick = { onDebugTriggerError("调试注入：模拟 AI 响应超时错误") },
                                    modifier = Modifier.weight(1f),
                                    border = BorderStroke(1.dp, debugRed.copy(alpha = 0.6f)),
                                    contentPadding = PaddingValues(horizontal = 8.dp, vertical = 8.dp)
                                ) { Text("注入错误", style = MaterialTheme.typography.labelSmall, color = debugRed) }
                                OutlinedButton(
                                    onClick = onDebugClearError,
                                    modifier = Modifier.weight(1f),
                                    border = BorderStroke(1.dp, debugOrange.copy(alpha = 0.5f)),
                                    contentPadding = PaddingValues(horizontal = 8.dp, vertical = 8.dp)
                                ) { Text("清除错误", style = MaterialTheme.typography.labelSmall, color = debugOrange) }
                            }
                            Spacer(Modifier.height(8.dp))
                            // 注入消息 & 胜利动画预览
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.spacedBy(8.dp)
                            ) {
                                OutlinedButton(
                                    onClick = onDebugInjectMessage,
                                    modifier = Modifier.weight(1f),
                                    border = BorderStroke(1.dp, debugOrange.copy(alpha = 0.5f)),
                                    contentPadding = PaddingValues(horizontal = 8.dp, vertical = 8.dp)
                                ) { Text("注入 AI 消息", style = MaterialTheme.typography.labelSmall, color = debugOrange) }
                                OutlinedButton(
                                    onClick = onDebugResetVictory,
                                    modifier = Modifier.weight(1f),
                                    border = BorderStroke(1.dp, Color(0xFF22C55E).copy(alpha = 0.6f)),
                                    contentPadding = PaddingValues(horizontal = 8.dp, vertical = 8.dp)
                                ) { Text("隐藏胜利预览", style = MaterialTheme.typography.labelSmall, color = Color(0xFF22C55E)) }
                            }
                            Spacer(Modifier.height(8.dp))
                            Text(
                                "发送指示器测试",
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                            Spacer(Modifier.height(6.dp))
                            FlowRow(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.spacedBy(8.dp),
                                verticalArrangement = Arrangement.spacedBy(8.dp)
                            ) {
                                OutlinedButton(
                                    onClick = onDebugInjectPendingUserAccept,
                                    border = BorderStroke(1.dp, debugOrange.copy(alpha = 0.5f)),
                                    contentPadding = PaddingValues(horizontal = 10.dp, vertical = 8.dp)
                                ) { Text("注入转圈", style = MaterialTheme.typography.labelSmall, color = debugOrange) }
                                OutlinedButton(
                                    onClick = onDebugInjectTimedOutUserAccept,
                                    border = BorderStroke(1.dp, debugOrange.copy(alpha = 0.5f)),
                                    contentPadding = PaddingValues(horizontal = 10.dp, vertical = 8.dp)
                                ) { Text("注入警示", style = MaterialTheme.typography.labelSmall, color = debugOrange) }
                                OutlinedButton(
                                    onClick = onDebugAcceptPendingUsers,
                                    border = BorderStroke(1.dp, Color(0xFF22C55E).copy(alpha = 0.6f)),
                                    contentPadding = PaddingValues(horizontal = 10.dp, vertical = 8.dp)
                                ) { Text("标记已接受", style = MaterialTheme.typography.labelSmall, color = Color(0xFF22C55E)) }
                            }
                            Spacer(Modifier.height(8.dp))
                            Text(
                                "延时消息滚动测试",
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                            Spacer(Modifier.height(6.dp))
                            FlowRow(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.spacedBy(8.dp),
                                verticalArrangement = Arrangement.spacedBy(8.dp)
                            ) {
                                OutlinedButton(
                                    onClick = onDebugInjectDelayedNormalSingle,
                                    border = BorderStroke(1.dp, debugOrange.copy(alpha = 0.5f)),
                                    contentPadding = PaddingValues(horizontal = 10.dp, vertical = 8.dp)
                                ) { Text("普通 1 条", style = MaterialTheme.typography.labelSmall, color = debugOrange) }
                                OutlinedButton(
                                    onClick = onDebugInjectDelayedNormalInstantTriple,
                                    border = BorderStroke(1.dp, debugOrange.copy(alpha = 0.5f)),
                                    contentPadding = PaddingValues(horizontal = 10.dp, vertical = 8.dp)
                                ) { Text("普通 3 条瞬发", style = MaterialTheme.typography.labelSmall, color = debugOrange) }
                                OutlinedButton(
                                    onClick = onDebugInjectDelayedNormalIntervalTriple,
                                    border = BorderStroke(1.dp, debugOrange.copy(alpha = 0.5f)),
                                    contentPadding = PaddingValues(horizontal = 10.dp, vertical = 8.dp)
                                ) { Text("普通 3 条间隔 3s", style = MaterialTheme.typography.labelSmall, color = debugOrange) }
                                OutlinedButton(
                                    onClick = onDebugInjectDelayedProactiveSingle,
                                    border = BorderStroke(1.dp, debugOrange.copy(alpha = 0.5f)),
                                    contentPadding = PaddingValues(horizontal = 10.dp, vertical = 8.dp)
                                ) { Text("主动 1 条", style = MaterialTheme.typography.labelSmall, color = debugOrange) }
                                OutlinedButton(
                                    onClick = onDebugInjectDelayedProactiveInstantTriple,
                                    border = BorderStroke(1.dp, debugOrange.copy(alpha = 0.5f)),
                                    contentPadding = PaddingValues(horizontal = 10.dp, vertical = 8.dp)
                                ) { Text("主动 3 条瞬发", style = MaterialTheme.typography.labelSmall, color = debugOrange) }
                                OutlinedButton(
                                    onClick = onDebugInjectDelayedProactiveIntervalTriple,
                                    border = BorderStroke(1.dp, debugOrange.copy(alpha = 0.5f)),
                                    contentPadding = PaddingValues(horizontal = 10.dp, vertical = 8.dp)
                                ) { Text("主动 3 条间隔 3s", style = MaterialTheme.typography.labelSmall, color = debugOrange) }
                            }
                            Spacer(Modifier.height(8.dp))
                            OutlinedButton(
                                onClick = onDebugInjectLongPressSamples,
                                modifier = Modifier.fillMaxWidth(),
                                border = BorderStroke(1.dp, debugOrange.copy(alpha = 0.5f)),
                                contentPadding = PaddingValues(horizontal = 8.dp, vertical = 8.dp)
                            ) { Text("注入长按菜单样例", style = MaterialTheme.typography.labelSmall, color = debugOrange) }
                            Spacer(Modifier.height(8.dp))
                            // 强制总结 / 剧情记忆折叠（调试用）
                            OutlinedButton(
                                onClick = onDebugForceSummarize,
                                modifier = Modifier.fillMaxWidth(),
                                border = BorderStroke(1.dp, Color(0xFF818CF8).copy(alpha = 0.6f)),
                                contentPadding = PaddingValues(horizontal = 8.dp, vertical = 8.dp)
                            ) {
                                Text(
                                    if (isGalgame) "强制折叠剧情记忆" else "强制生成上下文摘要",
                                    style = MaterialTheme.typography.labelSmall,
                                    color = Color(0xFF818CF8)
                                )
                            }
                            Spacer(Modifier.height(8.dp))
                            // 休息提醒弹窗预览
                            OutlinedButton(
                                onClick = onDebugShowUsageReminder,
                                modifier = Modifier.fillMaxWidth(),
                                border = BorderStroke(1.dp, debugOrange.copy(alpha = 0.5f)),
                                contentPadding = PaddingValues(horizontal = 8.dp, vertical = 8.dp)
                            ) {
                                Text(
                                    "预览休息提醒弹窗",
                                    style = MaterialTheme.typography.labelSmall,
                                    color = debugOrange
                                )
                            }
                        }
                    }
                }

                Spacer(Modifier.height(8.dp))
                Text(
                    "注意：调试板块的操作仅影响本地 UI 状态，部分更改不会保存到服务端",
                    style = MaterialTheme.typography.bodySmall,
                    color = debugOrange.copy(alpha = 0.7f),
                    modifier = Modifier.padding(horizontal = 24.dp)
                )
            } // end item 调试板块
            } // end if prefs.debugMode

            item { Spacer(Modifier.height(32.dp)) }
        } // end LazyColumn
    }
    }
}

// ==================== 设置页面公共组件 ====================

@Composable
private fun SectionTitle(text: String) {
    Text(
        text = text,
        style = MaterialTheme.typography.labelMedium,
        fontWeight = FontWeight.Medium,
        color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.6f),
        modifier = Modifier.padding(start = 24.dp, top = 8.dp, bottom = 8.dp)
    )
}

@Composable
private fun SettingsCard(content: @Composable ColumnScope.() -> Unit) {
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 12.dp),
        shape = RoundedCornerShape(12.dp),
        color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f),
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.12f))
    ) {
        Column(content = content)
    }
}

@Composable
private fun CardDivider() {
    HorizontalDivider(
        modifier = Modifier.padding(start = 48.dp),
        color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.1f)
    )
}
