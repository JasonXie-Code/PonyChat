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

/** 锁分模式体征面板：点击好感度胶囊后弹出，分区展示 char_vitals / char_mood / organ_fill */
@Composable
internal fun LockVitalsPanelDialog(
    charVitals: Map<String, Int>,
    charMood: Map<String, Int>,
    organFill: Map<String, Int>,
    charGender: String = "",
    charVitalsDelta: Map<String, Int> = emptyMap(),
    charMoodDelta: Map<String, Int> = emptyMap(),
    organFillDelta: Map<String, Int> = emptyMap(),
    onDismiss: () -> Unit
) {
    // 不使用 Dialog 窗口：叠加层直接在 Activity 的 Compose 树内渲染，
    // 彻底绕开 MIUI 对 Dialog 窗口的 contrastEnforced 异步重置问题。
    // Surface 的 #22273d 背景天然覆盖导航栏区域，无需任何窗口 API 操作。
    val isDark = MaterialTheme.colorScheme.background.luminance() < 0.5f

        val coroutineScope = rememberCoroutineScope()
        val scrollState = rememberScrollState()
        val configuration = LocalConfiguration.current
        val density = LocalDensity.current
        val screenHeightPx = with(density) { configuration.screenHeightDp.dp.toPx() }
        val dismissThresholdPx = screenHeightPx / 5f
        val navBarHeightPx = WindowInsets.navigationBars.getBottom(density)
        // 面板高度 = 78% 屏幕高 + 导航栏高，使 Surface 背景能覆盖导航栏区域
        val panelHeightDp = configuration.screenHeightDp.dp * 0.78f +
            with(density) { navBarHeightPx.toDp() }
        val panelHeightPx = with(density) { panelHeightDp.toPx() }

        val localView = LocalView.current

        // 初始值为面板高度（屏幕外底部），入场时动画至 0
        val sheetOffsetY = remember { Animatable(panelHeightPx) }
        LaunchedEffect(Unit) {
            sheetOffsetY.animateTo(0f, spring(stiffness = Spring.StiffnessMediumLow))
        }

        // 出场：先向下滑出再触发 onDismiss
        fun doAnimatedDismiss() {
            coroutineScope.launch {
                sheetOffsetY.animateTo(panelHeightPx, tween(durationMillis = 240))
                onDismiss()
            }
        }
        BackHandler { doAnimatedDismiss() }

        // 导航栏颜色随抽屉位置精准同步：
        //   offset < threshold（抽屉顶端高于导航栏上沿）→ 显示抽屉背景色
        //   offset ≥ threshold（抽屉顶端滑至导航栏以下）→ 恢复聊天背景色
        // 入场/出场/拖拽三条路径均由同一 snapshotFlow 处理，时机精确到每一帧。
        val drawerNavBarColor = MaterialTheme.colorScheme.surfaceColorAtElevation(6.dp).toArgb()
        val drawerUseDarkIcons = MaterialTheme.colorScheme.surfaceColorAtElevation(6.dp).luminance() > 0.5f
        // 在 effects 执行前（remember 阶段）捕获展开前的颜色，确保值正确
        val prevNavBarColor = remember {
            (localView.context as? Activity)?.window?.navigationBarColor
                ?: android.graphics.Color.TRANSPARENT
        }
        val prevLightNavIcons = remember {
            (localView.context as? Activity)?.window?.let {
                WindowInsetsControllerCompat(it, it.decorView).isAppearanceLightNavigationBars
            } ?: false
        }
        val prevNavigationBarContrastEnforced = remember {
            (localView.context as? Activity)?.window?.let {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                    it.isNavigationBarContrastEnforced
                } else {
                    false
                }
            } ?: false
        }
        val colorSwitchThresholdPx = panelHeightPx - navBarHeightPx
        fun applyNavBarForOffset(offset: Float) {
            val activity = localView.context as? Activity ?: return
            val win = activity.window
            val insetsCtrl = WindowInsetsControllerCompat(win, win.decorView)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                win.isNavigationBarContrastEnforced = false
            }
            if (offset < colorSwitchThresholdPx) {
                win.navigationBarColor = drawerNavBarColor
                insetsCtrl.isAppearanceLightNavigationBars = drawerUseDarkIcons
            } else {
                win.navigationBarColor = prevNavBarColor
                insetsCtrl.isAppearanceLightNavigationBars = prevLightNavIcons
            }
        }
        LaunchedEffect(
            colorSwitchThresholdPx,
            drawerNavBarColor,
            drawerUseDarkIcons,
            prevNavBarColor,
            prevLightNavIcons
        ) {
            snapshotFlow { sheetOffsetY.value }
                .collect { offset ->
                    applyNavBarForOffset(offset)
                }
        }
        // 兜底清理：组合树移除时确保颜色一定恢复
        val lifecycleOwner = LocalLifecycleOwner.current
        DisposableEffect(
            localView,
            lifecycleOwner,
            colorSwitchThresholdPx,
            drawerNavBarColor,
            drawerUseDarkIcons,
            prevNavBarColor,
            prevLightNavIcons,
            prevNavigationBarContrastEnforced
        ) {
            val resumeObserver = LifecycleEventObserver { _, event ->
                if (event == Lifecycle.Event.ON_RESUME) {
                    localView.post { applyNavBarForOffset(sheetOffsetY.value) }
                }
            }
            lifecycleOwner.lifecycle.addObserver(resumeObserver)
            onDispose {
                lifecycleOwner.lifecycle.removeObserver(resumeObserver)
                val activity = localView.context as? Activity ?: return@onDispose
                activity.window.navigationBarColor = prevNavBarColor
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                    activity.window.isNavigationBarContrastEnforced = prevNavigationBarContrastEnforced
                }
                WindowInsetsControllerCompat(activity.window, activity.window.decorView)
                    .isAppearanceLightNavigationBars = prevLightNavIcons
            }
        }

        // 当列表到顶时将下拉溢出量转为面板偏移；上划时优先回弹面板再滚动列表
        val nestedScrollConnection = remember(coroutineScope, scrollState, dismissThresholdPx) {
            object : NestedScrollConnection {
                override fun onPreScroll(available: Offset, source: NestedScrollSource): Offset {
                    val delta = available.y
                    return if (delta < 0 && sheetOffsetY.value > 0) {
                        val newOffset = (sheetOffsetY.value + delta).coerceAtLeast(0f)
                        val consumed = newOffset - sheetOffsetY.value
                        coroutineScope.launch { sheetOffsetY.snapTo(newOffset) }
                        Offset(0f, consumed)
                    } else Offset.Zero
                }

                override fun onPostScroll(
                    consumed: Offset,
                    available: Offset,
                    source: NestedScrollSource
                ): Offset {
                    // 仅手指直接拖拽到顶后的溢出量才驱动卡片下移；
                    // fling 到顶的剩余速度不移动卡片，保证快速下滑只滚内容不晃卡片
                    return if (available.y > 0 && scrollState.value == 0
                        && source == NestedScrollSource.UserInput
                    ) {
                        val newOffset = (sheetOffsetY.value + available.y).coerceIn(0f, screenHeightPx)
                        coroutineScope.launch { sheetOffsetY.snapTo(newOffset) }
                        available
                    } else Offset.Zero
                }

                override suspend fun onPreFling(available: Velocity): Velocity {
                    // 列表已在顶部时：直接用速度或偏移量判断是否关闭
                    return if (sheetOffsetY.value > 0) {
                        if (sheetOffsetY.value >= dismissThresholdPx || available.y > 800f) {
                            sheetOffsetY.animateTo(panelHeightPx, tween(durationMillis = 240))
                            onDismiss()
                        } else {
                            sheetOffsetY.animateTo(0f, spring(stiffness = Spring.StiffnessMediumLow))
                        }
                        available
                    } else Velocity.Zero
                }

                // 内容未在顶部时 fling 结束后的处理：
                // 此路径说明用户第一次快速下划，意图是"先滚到顶部"，不应触发关闭。
                // 关闭逻辑只在内容已到顶部时（onPreFling / draggable.onDragStopped）生效。
                override suspend fun onPostFling(consumed: Velocity, available: Velocity): Velocity {
                    if (sheetOffsetY.value > 0f) {
                        sheetOffsetY.animateTo(0f, spring(stiffness = Spring.StiffnessMediumLow))
                    }
                    return Velocity.Zero
                }
            }
        }

        Box(
            modifier = Modifier
                .fillMaxSize()
                .clickable(
                    indication = null,
                    interactionSource = remember { MutableInteractionSource() }
                ) { doAnimatedDismiss() },
            contentAlignment = Alignment.BottomCenter
        ) {
            Surface(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(panelHeightDp)
                    .offset { IntOffset(x = 0, y = sheetOffsetY.value.roundToInt()) }
                    .nestedScroll(nestedScrollConnection)
                    .clickable(
                        indication = null,
                        interactionSource = remember { MutableInteractionSource() }
                    ) { /* 阻止点击穿透 */ },
                shape = RoundedCornerShape(topStart = 24.dp, topEnd = 24.dp),
                color = MaterialTheme.colorScheme.surface,
                tonalElevation = 6.dp,
                shadowElevation = 16.dp
            ) {
                Column(
                    modifier = Modifier
                        .fillMaxSize()
                        .navigationBarsPadding()
                ) {
                    // 拖拽把手 — 支持直接拖拽关闭
                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(top = 10.dp, bottom = 6.dp)
                            .draggable(
                                state = rememberDraggableState { delta ->
                                    coroutineScope.launch {
                                        sheetOffsetY.snapTo(
                                            (sheetOffsetY.value + delta).coerceAtLeast(0f)
                                        )
                                    }
                                },
                                orientation = Orientation.Vertical,
                                onDragStopped = { velocity ->
                                    coroutineScope.launch {
                                        if (sheetOffsetY.value >= dismissThresholdPx || velocity > 800f) {
                                            sheetOffsetY.animateTo(panelHeightPx, tween(durationMillis = 240))
                                            onDismiss()
                                        } else {
                                            sheetOffsetY.animateTo(
                                                0f,
                                                spring(stiffness = Spring.StiffnessMediumLow)
                                            )
                                        }
                                    }
                                }
                            ),
                        contentAlignment = Alignment.Center
                    ) {
                        Box(
                            modifier = Modifier
                                .width(40.dp)
                                .height(4.dp)
                                .background(
                                    MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.3f),
                                    RoundedCornerShape(2.dp)
                                )
                        )
                    }

                    // 可滚动内容区（使用提升的 scrollState 供 nestedScroll 感知位置）
                    Column(
                        modifier = Modifier
                            .weight(1f)
                            .verticalScroll(scrollState)
                            .padding(start = 16.dp, end = 16.dp, top = 4.dp, bottom = 12.dp),
                        verticalArrangement = Arrangement.spacedBy(4.dp)
                    ) {
                        // 生命体征分区
                        VitalsSectionHeader(
                            title = "生命体征",
                            accentColor = Color(0xFF2196F3),
                            bgColor = Color(0xFF2196F3).copy(alpha = if (isDark) 0.12f else 0.07f)
                        )
                        val vitalsFields = listOf(
                            Triple("consciousness", "意识",  false),
                            Triple("stamina",       "体力",  false),
                            Triple("oxygen",        "血氧",  false),
                            Triple("blood_loss",    "失血",  true),
                            Triple("infection",     "感染",  true),
                            Triple("pain",          "疼痛",  true)
                        )
                        // 失血下方插入束缚感：数据在 char_vitals.restraint（与后端一致）；旧存档可能仍在 char_mood
                        vitalsFields.take(4).forEach { (key, label, isReverse) ->
                            val value = charVitals[key]
                            VitalBarRow(
                                label = label,
                                value = value,
                                isReverse = isReverse,
                                delta = charVitalsDelta[key]
                            )
                        }
                        VitalBarRow(
                            label = "束缚感",
                            value = charVitals["restraint"] ?: charMood["restraint"],
                            isReverse = true,
                            delta = charVitalsDelta["restraint"] ?: charMoodDelta["restraint"]
                        )
                        vitalsFields.drop(4).forEach { (key, label, isReverse) ->
                            val value = charVitals[key]
                            VitalBarRow(
                                label = label,
                                value = value,
                                isReverse = isReverse,
                                delta = charVitalsDelta[key]
                            )
                        }
                        // 体温双向危险（低温/高温均致命），单独处理
                        VitalBarRow(
                            label = "体温",
                            value = charVitals["body_temp"],
                            isReverse = false,
                            isBiDirectional = true,
                            delta = charVitalsDelta["body_temp"]
                        )
                        // 口渴/脱水（高值危险），紧跟体温之后
                        VitalBarRow(
                            label = "口渴",
                            value = charVitals["thirst"],
                            isReverse = true,
                            delta = charVitalsDelta["thirst"]
                        )

                        Spacer(Modifier.height(8.dp))

                        // 情绪状态分区
                        VitalsSectionHeader(
                            title = "情绪状态",
                            accentColor = Color(0xFF80E060),
                            bgColor = Color(0xFF80E060).copy(alpha = if (isDark) 0.12f else 0.07f),
                            titleColor = Color(0xFF80E060)
                        )
                        // 情绪量表：50=正常基准，0/100=两极——两端均显示警告色
                        val moodFields = listOf(
                            "arousal"     to "性兴奋",
                            "pleasure"    to "愉悦",
                            "shyness"     to "害羞",
                            "courage"     to "勇气",
                            "curiosity"   to "好奇",
                            "nervousness" to "紧张",
                            "fear"        to "恐惧",
                            "anger"       to "愤怒",
                            "sadness"     to "悲伤",
                            "submission"  to "顺从",
                            "despair"     to "绝望"
                        )
                        moodFields.forEach { (key, label) ->
                            val value = charMood[key]
                            VitalBarRow(
                                label = label,
                                value = value,
                                isReverse = false,
                                isBiDirectional = true,
                                delta = charMoodDelta[key]
                            )
                        }

                        Spacer(Modifier.height(8.dp))

                        // 器官内容物分区
                        VitalsSectionHeader(
                            title = "器官内容物",
                            accentColor = Color(0xFFFF7043),
                            bgColor = Color(0xFFFF7043).copy(alpha = if (isDark) 0.12f else 0.07f)
                        )
                        // 根据角色性别决定显示子宫/精巢；首轮性别未知时不显示该行
                        val genderOrganField: Pair<String, String>? = when {
                            charGender.isBlank() -> null
                            charGender in listOf("雄性", "male", "男") -> "testicles" to "精巢"
                            else -> "womb" to "子宫"
                        }
                        val organFields = buildList {
                            add(Triple("stomach",   "胃部", true))
                            add(Triple("bladder",   "膀胱", true))
                            genderOrganField?.let { add(Triple(it.first, it.second, true)) }
                            add(Triple("rectum",    "直肠", true))
                            add(Triple("lung_fill", "肺部", true))
                        }
                        organFields.forEach { (key, label, isReverse) ->
                            val value = organFill[key]
                            VitalBarRow(
                                label = label,
                                value = value,
                                isReverse = isReverse,
                                delta = organFillDelta[key]
                            )
                        }

                        Spacer(Modifier.height(8.dp))
                        VitalsSectionHeader(
                            title = "体内器具",
                            accentColor = Color(0xFFF06292),
                            bgColor = Color(0xFFF06292).copy(alpha = if (isDark) 0.14f else 0.10f)
                        )
                        val plugFields = buildList {
                            // isReverse=true：与失血等同——数值越高越危险（≥85 红、≥60 橙）
                            add(Triple("urethral_plug", "尿道塞", true))
                            add(Triple("anal_plug", "肛塞", true))
                            add(Triple("mouth_plug", "口塞", true))
                            // 阴道塞与子宫同一规则：仅明确雌性时显示；性别未知或雄性不显示
                            if (genderOrganField?.first == "womb") {
                                add(Triple("vaginal_plug", "阴道塞", true))
                            }
                        }
                        plugFields.forEach { (key, label, isReverse) ->
                            val value = organFill[key]
                            VitalBarRow(
                                label = label,
                                value = value,
                                isReverse = isReverse,
                                delta = organFillDelta[key]
                            )
                        }

                        Spacer(Modifier.height(4.dp))
                    }
                }
            }
        }
}

// ==================== 聊天主界面 ====================

/** 键盘可用高度 + 是否处于系统 IME 插入/移除动画中（用于与自动滚动解耦，避免与 graphicsLayer 平移打架闪屏） */
