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

/** 100 分「胜利金」：深色亮金 [0xFFFFD700]；浅色见 [GalgameWinGoldLight]。 */
private val GalgameWinGoldDark = Color(0xFFFFD700)

/** 游戏/锁分模式进度条与好感度胶囊的前景分段色（App 内约定；主站网页体验版无 Galgame，勿再写「与 Web 一致」）。 */
internal fun galgameScoreToColor(score: Int, isDark: Boolean): Color {
    return when {
        score <= 0 -> Color(0xFF999999)    // 破裂/死亡 灰
        score >= 100 -> if (isDark) GalgameWinGoldDark else GalgameWinGoldLight
        score <= 20 -> Color(0xFF2196F3)   // 蓝色 冷淡/低分
        score <= 50 -> Color(0xFFFF9800)   // 橙色 普通/中分
        score >= 90 -> Color(0xFFD500F9)   // 紫色 极高分/热恋
        else -> AccentRose                 // 粉色 50-89
    }
}

/** 好感度胶囊心跳频率：按锚点分段线性映射
 *  1→40 BPM，30→50 BPM，60→65 BPM，80→100 BPM，99→140 BPM，100→120 BPM
 */
internal fun galgameScoreToHeartBpm(score: Int): Float {
    val safeScore = score.coerceIn(0, 100)
    fun lerpScore(startScore: Int, endScore: Int, startBpm: Float, endBpm: Float): Float {
        if (endScore <= startScore) return endBpm
        val ratio = (safeScore - startScore).toFloat() / (endScore - startScore).toFloat()
        return startBpm + (endBpm - startBpm) * ratio.coerceIn(0f, 1f)
    }
    return when {
        safeScore <= 0 -> 0f
        safeScore <= 1 -> 40f
        safeScore <= 30 -> lerpScore(1, 30, 40f, 50f)
        safeScore <= 60 -> lerpScore(30, 60, 50f, 65f)
        safeScore <= 80 -> lerpScore(60, 80, 65f, 100f)
        safeScore <= 99 -> lerpScore(80, 99, 100f, 140f)
        else -> 120f
    }
}

/** 分数进度条：轨道 + 前层填充（填充色见 [galgameScoreToColor]）。 */
@Composable
internal fun GalgameProgressBarRow(score: Int, modifier: Modifier = Modifier) {
    val safeScore = score.coerceIn(0, 100)
    val isDark = MaterialTheme.colorScheme.background.luminance() < 0.5f
    val fillColor = galgameScoreToColor(safeScore, isDark)
    Row(modifier = modifier.fillMaxWidth().height(3.dp)) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .fillMaxHeight()
                .background(Color.Black.copy(alpha = 0.2f), RoundedCornerShape(2.dp))
        ) {
            Box(
                modifier = Modifier
                    .fillMaxHeight()
                    .fillMaxWidth(safeScore / 100f)
                    .background(fillColor, RoundedCornerShape(0.dp, 2.dp, 2.dp, 0.dp))
                    .shadow(4.dp, RoundedCornerShape(2.dp), spotColor = fillColor.copy(alpha = 0.5f))
            )
        }
    }
}


/** 游戏/锁分模式开局界面（季节、时段、地点与自定义设定）。 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun GalgameStartScreen(
    characterName: String,
    mode: String = "galgame",
    onStartGame: (season: String, time: String, location: String, customSetting: String) -> Unit
) {
    val isLockMode = mode == "galgame_lock"

    val seasons = listOf("春天", "夏天", "秋天", "冬天")
    val timesOfDay = listOf("清晨", "上午", "中午", "下午", "傍晚", "夜晚", "深夜")
    val basePlaces = listOf("不限", "户外草地", "学校", "集市", "街道", "酒吧", "餐厅", "角色的家里客厅", "角色的卧室")
    val lockPlaces = listOf("密室", "废墟", "地下室", "牢房", "古堡", "森林深处", "停尸间", "废弃医院", "地牢", "禁闭室", "阁楼", "地下实验室")
    val locations = if (isLockMode) basePlaces + lockPlaces else basePlaces

    var selectedSeason by remember { mutableStateOf(seasons[0]) }
    var selectedTime by remember { mutableStateOf("中午") }
    var selectedLocation by remember { mutableStateOf(locations[0]) }
    var customSetting by remember { mutableStateOf("") }

    val isDark = MaterialTheme.colorScheme.background.luminance() < 0.5f

    // 模式配色：游戏模式蓝青渐变，锁分模式玫红琥珀渐变
    val accentStart = if (isLockMode) Color(0xFFE8537A) else Color(0xFF6366F1)
    val accentEnd   = if (isLockMode) Color(0xFFF5A623) else Color(0xFF06B6D4)
    val gradientBrush = Brush.horizontalGradient(listOf(accentStart, accentEnd))

    // 卡片背景色：深色用轻微透明的 surface，浅色提升 1dp elevation
    val cardElevation = if (isDark) 0.dp else 2.dp
    val dividerColor = MaterialTheme.colorScheme.outline.copy(alpha = 0.15f)
    val iconTint = if (isDark) accentStart.copy(alpha = 0.9f) else accentStart
    val labelColor = MaterialTheme.colorScheme.onSurfaceVariant
    val sectionTitleColor = MaterialTheme.colorScheme.onSurface

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 20.dp, vertical = 32.dp),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        // ── 顶部：图标 + 标题 + 副标题 ──────────────────────────────────
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            modifier = Modifier.padding(bottom = 28.dp)
        ) {
            // 圆形渐变图标背景
            Box(
                modifier = Modifier
                    .size(68.dp)
                    .background(
                        brush = Brush.radialGradient(
                            listOf(accentStart.copy(alpha = if (isDark) 0.18f else 0.12f),
                                   accentEnd.copy(alpha = if (isDark) 0.10f else 0.06f))
                        ),
                        shape = CircleShape
                    )
                    .then(
                        Modifier.background(Color.Transparent, CircleShape)
                    ),
                contentAlignment = Alignment.Center
            ) {
                // 渐变边框圆环
                Box(
                    modifier = Modifier
                        .size(68.dp)
                        .background(Color.Transparent, CircleShape)
                        .then(
                            if (isDark)
                                Modifier.background(
                                    brush = Brush.radialGradient(
                                        listOf(accentStart.copy(0.0f), accentStart.copy(0.0f))
                                    )
                                )
                            else Modifier
                        ),
                    contentAlignment = Alignment.Center
                ) {
                    Surface(
                        modifier = Modifier.size(68.dp),
                        shape = CircleShape,
                        color = Color.Transparent,
                        border = BorderStroke(
                            1.5.dp,
                            brush = gradientBrush
                        )
                    ) {}
                }
                Icon(
                    imageVector = if (isLockMode) Icons.Filled.Lock else Icons.Filled.Favorite,
                    contentDescription = null,
                    tint = accentStart,
                    modifier = Modifier.size(28.dp)
                )
            }

            Spacer(Modifier.height(14.dp))

            // 渐变标题文字
            Text(
                text = if (isLockMode) "锁分模式" else "开始游戏",
                style = MaterialTheme.typography.headlineMedium.copy(
                    brush = gradientBrush
                ),
                fontWeight = FontWeight.Bold
            )

            Spacer(Modifier.height(6.dp))

            // 副标题
            Text(
                text = if (isLockMode)
                    "与 $characterName 的命运之战 · 好感归零触发结局"
                else
                    "选择与 $characterName 相遇的时间和地点",
                style = MaterialTheme.typography.bodySmall,
                color = labelColor,
                textAlign = androidx.compose.ui.text.style.TextAlign.Center
            )
        }

        // ── 选项卡片 ──────────────────────────────────────────────────
        Card(
            modifier = Modifier.fillMaxWidth(),
            shape = RoundedCornerShape(16.dp),
            colors = CardDefaults.cardColors(
                containerColor = MaterialTheme.colorScheme.surface
            ),
            border = BorderStroke(1.dp, MaterialTheme.colorScheme.outline.copy(alpha = 0.18f)),
            elevation = CardDefaults.cardElevation(defaultElevation = cardElevation)
        ) {
            Column(
                modifier = Modifier.padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(0.dp)
            ) {
                // ── 时间设置区 ──
                Column(modifier = Modifier.padding(bottom = 14.dp)) {
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(6.dp),
                        modifier = Modifier.padding(bottom = 10.dp)
                    ) {
                        Icon(Icons.Filled.Schedule, contentDescription = null,
                            tint = iconTint, modifier = Modifier.size(17.dp))
                        Text("时间设置",
                            style = MaterialTheme.typography.labelLarge,
                            fontWeight = FontWeight.Medium,
                            color = sectionTitleColor)
                    }

                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(10.dp)
                    ) {
                        Column(modifier = Modifier.weight(1f), horizontalAlignment = Alignment.CenterHorizontally) {
                            Text("季节", style = MaterialTheme.typography.labelSmall,
                                color = labelColor, modifier = Modifier.padding(bottom = 6.dp))
                            WheelStringColumn(
                                items = seasons,
                                selectedItem = selectedSeason,
                                onItemSelected = { selectedSeason = it },
                                modifier = Modifier.fillMaxWidth(),
                                visibleItems = 3,
                                accentColor = accentStart
                            )
                        }
                        Column(modifier = Modifier.weight(1f), horizontalAlignment = Alignment.CenterHorizontally) {
                            Text("时段", style = MaterialTheme.typography.labelSmall,
                                color = labelColor, modifier = Modifier.padding(bottom = 6.dp))
                            WheelStringColumn(
                                items = timesOfDay,
                                selectedItem = selectedTime,
                                onItemSelected = { selectedTime = it },
                                modifier = Modifier.fillMaxWidth(),
                                visibleItems = 3,
                                accentColor = accentStart
                            )
                        }
                    }
                }

                HorizontalDivider(color = dividerColor)

                // ── 地点设置区 ──
                Column(modifier = Modifier.padding(top = 14.dp, bottom = 14.dp)) {
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(6.dp),
                        modifier = Modifier.padding(bottom = 10.dp)
                    ) {
                        Icon(Icons.Filled.LocationOn, contentDescription = null,
                            tint = iconTint, modifier = Modifier.size(17.dp))
                        Text("地点设置",
                            style = MaterialTheme.typography.labelLarge,
                            fontWeight = FontWeight.Medium,
                            color = sectionTitleColor)
                    }

                    WheelStringColumn(
                        items = locations,
                        selectedItem = selectedLocation,
                        onItemSelected = { selectedLocation = it },
                        modifier = Modifier.fillMaxWidth(),
                        visibleItems = 3,
                        accentColor = accentStart
                    )
                }

                HorizontalDivider(color = dividerColor)

                // ── 自定义开场设定 ──
                Column(modifier = Modifier.padding(top = 14.dp)) {
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(6.dp),
                        modifier = Modifier.padding(bottom = 10.dp)
                    ) {
                        Icon(Icons.Filled.Edit, contentDescription = null,
                            tint = iconTint, modifier = Modifier.size(17.dp))
                        Text("开场设定（可选）",
                            style = MaterialTheme.typography.labelLarge,
                            fontWeight = FontWeight.Medium,
                            color = sectionTitleColor)
                    }

                    OutlinedTextField(
                        value = customSetting,
                        onValueChange = { if (it.length <= 100) customSetting = it },
                        modifier = Modifier
                            .fillMaxWidth()
                            .heightIn(min = 88.dp),
                        placeholder = {
                            Text("描述相遇场景或补充特殊设定...",
                                style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.45f))
                        },
                        textStyle = MaterialTheme.typography.bodyMedium,
                        maxLines = 5,
                        colors = OutlinedTextFieldDefaults.colors(
                            focusedBorderColor = accentStart.copy(alpha = 0.7f),
                            unfocusedBorderColor = MaterialTheme.colorScheme.outline.copy(alpha = 0.4f),
                            focusedContainerColor = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.3f),
                            unfocusedContainerColor = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.15f)
                        )
                    )

                    Text(
                        text = "${customSetting.length}/100",
                        style = MaterialTheme.typography.labelSmall,
                        color = if (customSetting.length >= 85)
                            MaterialTheme.colorScheme.error
                        else
                            labelColor.copy(alpha = 0.5f),
                        modifier = Modifier
                            .align(Alignment.End)
                            .padding(top = 4.dp)
                    )
                }
            }
        }

        Spacer(Modifier.height(24.dp))

        // ── 开始按钮 ──────────────────────────────────────────────────
        Button(
            onClick = { onStartGame(selectedSeason, selectedTime, selectedLocation, customSetting) },
            modifier = Modifier
                .fillMaxWidth()
                .height(52.dp),
            shape = RoundedCornerShape(12.dp),
            colors = ButtonDefaults.buttonColors(containerColor = Color.Transparent),
            elevation = ButtonDefaults.buttonElevation(0.dp),
            contentPadding = PaddingValues(0.dp)
        ) {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .background(brush = gradientBrush, shape = RoundedCornerShape(12.dp)),
                contentAlignment = Alignment.Center
            ) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    Icon(
                        Icons.Filled.PlayArrow,
                        contentDescription = null,
                        tint = Color.White,
                        modifier = Modifier.size(22.dp)
                    )
                    Text(
                        text = if (isLockMode) "开始挑战" else "开始游戏",
                        style = MaterialTheme.typography.bodyLarge,
                        fontWeight = FontWeight.SemiBold,
                        color = Color.White
                    )
                }
            }
        }

        // ── 底部提示 ──
        Spacer(Modifier.height(12.dp))
        Text(
            text = if (isLockMode)
                "⚠ 锁分模式：最低1分直到角色死亡"
            else
                "提示：时间地点只是开场设定，不限制后续剧情走向",
            style = MaterialTheme.typography.labelSmall,
            color = if (isLockMode)
                MaterialTheme.colorScheme.error.copy(alpha = 0.82f)
            else
                labelColor.copy(alpha = 0.5f),
            textAlign = androidx.compose.ui.text.style.TextAlign.Center
        )

        Spacer(Modifier.height(56.dp))
    }
}

// ==================== 锁分模式生命体征面板 ====================

