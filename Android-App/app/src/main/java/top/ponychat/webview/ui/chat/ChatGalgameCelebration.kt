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

private data class ConfettiParticle(
    val x0: Float, val y0: Float,
    val vx: Float, val vy: Float,
    val grav: Float,
    val sway: Float,
    val delay: Float,
    val w: Float, val h: Float,
    val rotOffset: Float, val rotSpeed: Float,
    val color: Color,
    val isCircle: Boolean
)

private const val CONFETTI_CYCLE_MS = 3200

/** 生成礼炮 + 飘落纸屑粒子集合 */
private fun buildConfettiParticles(rng: java.util.Random): List<ConfettiParticle> {
    val colors = listOf(
        Color(0xFFFF4D6D), Color(0xFFFF9F1C), Color(0xFFFFD600),
        Color(0xFF2EC4B6), Color(0xFF3D9EE3), Color(0xFF9B5DE5),
        Color(0xFFFF85A1), Color(0xFF43E97B), Color(0xFFFA8231),
        Color(0xFFF9CA24), Color(0xFF6C5CE7), Color(0xFF00CEC9)
    )
    fun rColor() = colors[rng.nextInt(colors.size)]
    fun rFloat(lo: Float, hi: Float) = lo + rng.nextFloat() * (hi - lo)

    val list = mutableListOf<ConfettiParticle>()

    // ── 左侧礼炮：从 (0.04, 0.92) 向右上方喷射，扇形展开 ──────────────
    // 角度范围：仰角 35-80 度（从水平向上量），向右偏
    repeat(40) { _ ->
        val angleDeg = 35f + rFloat(0f, 45f)           // 仰角 35-80°
        val angleRad = Math.toRadians(angleDeg.toDouble()).toFloat()
        val speed = rFloat(0.90f, 1.45f)                // 初速（归一化/周期）
        val delay = rFloat(0f, 0.18f)                   // 礼炮粒子集中在前 18% 时间爆出
        val isCircle = rng.nextFloat() < 0.25f
        val w = if (isCircle) rFloat(15f, 30f) else rFloat(18f, 36f)
        val h = if (isCircle) w else rFloat(12f, 21f)
        list += ConfettiParticle(
            x0 = 0.04f, y0 = 0.92f,
            vx = speed * kotlin.math.cos(angleRad),
            vy = -speed * kotlin.math.sin(angleRad),
            grav = 1.60f,   // 重力，使粒子在 ~0.5 周期到达顶点后弧线下落
            sway = 0f,
            delay = delay,
            w = w, h = h,
            rotOffset = rFloat(0f, 360f),
            rotSpeed = rFloat(180f, 540f) * if (rng.nextBoolean()) 1f else -1f,
            color = rColor(),
            isCircle = isCircle
        )
    }

    // ── 右侧礼炮：从 (0.96, 0.92) 向左上方喷射 ───────────────────────
    repeat(40) { _ ->
        val angleDeg = 35f + rFloat(0f, 45f)
        val angleRad = Math.toRadians(angleDeg.toDouble()).toFloat()
        val speed = rFloat(0.90f, 1.45f)
        val delay = rFloat(0f, 0.18f)
        val isCircle = rng.nextFloat() < 0.25f
        val w = if (isCircle) rFloat(15f, 30f) else rFloat(18f, 36f)
        val h = if (isCircle) w else rFloat(12f, 21f)
        list += ConfettiParticle(
            x0 = 0.96f, y0 = 0.92f,
            vx = -speed * kotlin.math.cos(angleRad),   // 向左
            vy = -speed * kotlin.math.sin(angleRad),
            grav = 1.60f,
            sway = 0f,
            delay = delay,
            w = w, h = h,
            rotOffset = rFloat(0f, 360f),
            rotSpeed = rFloat(180f, 540f) * if (rng.nextBoolean()) 1f else -1f,
            color = rColor(),
            isCircle = isCircle
        )
    }

    // ── 持续飘落彩带：从顶部随机位置缓缓下落，带横向摆动 ─────────────
    repeat(35) {
        val isCircle = false  // 飘落的都是彩带/纸片
        val w = rFloat(15f, 42f)
        val h = rFloat(9f, 24f)
        list += ConfettiParticle(
            x0 = rFloat(0.02f, 0.98f),
            y0 = -0.05f,        // 从屏幕上方开始
            vx = rFloat(-0.015f, 0.015f),
            vy = rFloat(0.30f, 0.55f),  // 缓慢向下（归一化/周期）
            grav = 0f,
            sway = rFloat(0.03f, 0.10f),  // 左右摆动幅度
            delay = rFloat(0f, 1f),       // 全程分散出发
            w = w, h = h,
            rotOffset = rFloat(0f, 360f),
            rotSpeed = rFloat(90f, 270f) * if (it % 2 == 0) 1f else -1f,
            color = rColor(),
            isCircle = isCircle
        )
    }

    return list
}

@Composable
internal fun VictoryCelebrationOverlay(
    characterName: String,
    onContinue: () -> Unit,
    onRestart: () -> Unit
) {
    val rng = remember { java.util.Random(42L) }
    val particles = remember { buildConfettiParticles(rng) }

    // 主时间轴：线性 0→1，周期 CONFETTI_CYCLE_MS
    val infiniteTransition = rememberInfiniteTransition(label = "confetti")
    val timeAnim by infiniteTransition.animateFloat(
        initialValue = 0f, targetValue = 1f,
        animationSpec = infiniteRepeatable(tween(CONFETTI_CYCLE_MS, easing = LinearEasing)),
        label = "confetti_t"
    )
    // 独立的"摆动"时间轴，周期短一些，用于飘落彩带的 sway
    val swayAnim by infiniteTransition.animateFloat(
        initialValue = 0f, targetValue = (2f * Math.PI.toFloat()),
        animationSpec = infiniteRepeatable(tween(1800, easing = LinearEasing)),
        label = "sway_t"
    )

    // 亲密度胶囊光辉脉冲
    val glowPulse by infiniteTransition.animateFloat(
        initialValue = 0.45f, targetValue = 1f,
        animationSpec = infiniteRepeatable(tween(900, easing = FastOutSlowInEasing), RepeatMode.Reverse),
        label = "glow_pulse"
    )

    val isDark = MaterialTheme.colorScheme.background.luminance() < 0.5f
    val cardBg = if (isDark) Color(0xFF2A0817) else Color(0xFFFFF0F5)

    var visible by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) { delay(60); visible = true }
    val cardScale by animateFloatAsState(
        targetValue = if (visible) 1f else 0.70f,
        animationSpec = spring(dampingRatio = Spring.DampingRatioMediumBouncy, stiffness = Spring.StiffnessMediumLow),
        label = "card_scale"
    )
    val overlayAlpha by animateFloatAsState(
        targetValue = if (visible) 1f else 0f,
        animationSpec = tween(220),
        label = "overlay_alpha"
    )

    Dialog(
        onDismissRequest = onContinue,
        properties = DialogProperties(usePlatformDefaultWidth = false, dismissOnBackPress = true, dismissOnClickOutside = false)
    ) {
        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(Color.Transparent),
            contentAlignment = Alignment.Center
        ) {
            // ── 纸屑 / 彩带层 ────────────────────────────────────────────
            Canvas(modifier = Modifier.fillMaxSize()) {
                val W = size.width
                val H = size.height

                particles.forEach { p ->
                    // 计算该粒子在当前帧的相位（delay 使粒子错开出发）
                    val localT = ((timeAnim - p.delay + 1f) % 1f)  // 0-1

                    val x: Float
                    val y: Float
                    val alpha: Float

                    if (p.grav > 0f) {
                        // 礼炮粒子：抛物线运动
                        // localT=0 刚出炮口，localT→1 到达炮口下方（下一轮重置）
                        val t = localT  // 0-1 对应整个周期
                        x = p.x0 * W + p.vx * t * W
                        y = p.y0 * H + p.vy * t * H + 0.5f * p.grav * t * t * H

                        // 超出屏幕外则透明
                        alpha = if (x < -20f || x > W + 20f || y > H + 20f) 0f
                        else if (y > H * 0.85f) (1f - ((y - H * 0.85f) / (H * 0.15f))).coerceIn(0f, 1f)
                        else 0.88f
                    } else {
                        // 飘落粒子：匀速下落 + 正弦横向摆动
                        val t = localT
                        val swayX = p.sway * kotlin.math.sin((swayAnim + p.delay * (2f * Math.PI.toFloat())).toDouble()).toFloat()
                        x = (p.x0 + p.vx * t + swayX) * W
                        y = (p.y0 + p.vy * t) * H

                        alpha = when {
                            y < -10f || y > H + 10f -> 0f
                            y > H * 0.80f -> (1f - ((y - H * 0.80f) / (H * 0.20f))).coerceIn(0f, 1f)
                            else -> 0.85f
                        }
                    }

                    if (alpha <= 0f) return@forEach

                    val rotation = p.rotOffset + p.rotSpeed * localT

                    withTransform({
                        translate(x, y)
                        rotate(rotation, pivot = Offset.Zero)
                    }) {
                        if (p.isCircle) {
                            drawCircle(
                                color = p.color.copy(alpha = alpha),
                                radius = p.w / 2f,
                                center = Offset.Zero
                            )
                        } else {
                            drawRect(
                                color = p.color.copy(alpha = alpha),
                                topLeft = Offset(-p.w / 2f, -p.h / 2f),
                                size = Size(p.w, p.h)
                            )
                        }
                    }
                }
            }

            // ── 庆祝卡片 ─────────────────────────────────────────────────
            Surface(
                modifier = Modifier
                    .fillMaxWidth(0.88f)
                    .graphicsLayer { scaleX = cardScale; scaleY = cardScale; alpha = overlayAlpha },
                shape = RoundedCornerShape(28.dp),
                color = cardBg,
                shadowElevation = 24.dp
            ) {
                Column(
                    modifier = Modifier.padding(horizontal = 28.dp, vertical = 32.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(14.dp)
                ) {
                    Text(
                        "恭喜达成完美结局！",
                        style = MaterialTheme.typography.headlineSmall,
                        fontWeight = FontWeight.Bold,
                        color = if (isDark) Color(0xFFFFD6E8) else Color(0xFF7A0040),
                        textAlign = TextAlign.Center
                    )
                    Text(
                        "你与 $characterName 的羁绊达到了最深的程度",
                        style = MaterialTheme.typography.bodyMedium,
                        color = if (isDark) Color(0xFFFFADD0) else Color(0xFFA03060),
                        textAlign = TextAlign.Center
                    )
                    Box(
                        contentAlignment = Alignment.Center,
                        modifier = Modifier.drawBehind {
                            // 径向渐变辉光：从粉色核心渐变到透明，产生真实光晕
                            val cx = size.width / 2f
                            val cy = size.height / 2f
                            val glowColor = Color(0xFFFF4DA6)
                            val radius = maxOf(size.width, size.height) * 1.1f
                            drawCircle(
                                brush = Brush.radialGradient(
                                    0f    to glowColor.copy(alpha = glowPulse * 0.24f),
                                    0.35f to glowColor.copy(alpha = glowPulse * 0.13f),
                                    0.65f to glowColor.copy(alpha = glowPulse * 0.04f),
                                    1f    to Color.Transparent,
                                    center = Offset(cx, cy),
                                    radius = radius
                                ),
                                radius = radius,
                                center = Offset(cx, cy)
                            )
                        }
                    ) {
                        Row(
                            verticalAlignment = Alignment.Bottom,
                            horizontalArrangement = Arrangement.Center,
                            modifier = Modifier
                                .background(
                                    Color(0xFFFF4DA6).copy(alpha = if (isDark) 0.22f else 0.45f),
                                    RoundedCornerShape(14.dp)
                                )
                                .padding(horizontal = 22.dp, vertical = 10.dp)
                        ) {
                            val labelColor = if (isDark) Color(0xFFFFB3D4) else Color(0xFFB03070)
                            val valueColor = if (isDark) Color(0xFFFFD600) else GalgameWinGoldLight
                            Text("亲密度 ", style = MaterialTheme.typography.bodyLarge, color = labelColor)
                            Text(
                                "100",
                                style = MaterialTheme.typography.headlineMedium,
                                color = valueColor,
                                fontWeight = FontWeight.ExtraBold
                            )
                            Text(" / 100", style = MaterialTheme.typography.bodyLarge, color = labelColor)
                        }
                    }
                    Spacer(Modifier.height(4.dp))
                    Row(
                        horizontalArrangement = Arrangement.spacedBy(10.dp),
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Button(
                            onClick = onContinue,
                            colors = ButtonDefaults.buttonColors(containerColor = AccentRose),
                            modifier = Modifier.weight(1f),
                            shape = RoundedCornerShape(12.dp)
                        ) {
                            Icon(Icons.Filled.Favorite, contentDescription = null, modifier = Modifier.size(16.dp))
                            Spacer(Modifier.width(6.dp))
                            Text("继续陪伴")
                        }
                        Button(
                            onClick = onRestart,
                            modifier = Modifier.weight(1f),
                            shape = RoundedCornerShape(12.dp),
                            colors = ButtonDefaults.buttonColors(
                                containerColor = Color(0xFF2196F3),
                                contentColor = Color.White
                            )
                        ) {
                            Icon(Icons.Filled.Refresh, contentDescription = null, modifier = Modifier.size(16.dp), tint = Color.White)
                            Spacer(Modifier.width(6.dp))
                            Text("重新开始", color = Color.White)
                        }
                    }
                }
            }
        }
    }
}

