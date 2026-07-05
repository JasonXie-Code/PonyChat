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

internal data class ImeSyncState(
    val imeBottomPx: State<Int>,
    val imeTargetBottomPx: State<Int>,
    val isImeAnimating: State<Boolean>,
)

@Composable
internal fun rememberImeSyncState(enabled: Boolean): ImeSyncState {
    if (!enabled) {
        return ImeSyncState(
            imeBottomPx = remember { mutableIntStateOf(0) },
            imeTargetBottomPx = remember { mutableIntStateOf(0) },
            isImeAnimating = remember { mutableStateOf(false) },
        )
    }
    val view = LocalView.current
    val lifecycleOwner = LocalLifecycleOwner.current
    val bottomState = remember { mutableIntStateOf(0) }
    val targetBottomState = remember { mutableIntStateOf(0) }
    val animatingState = remember { mutableStateOf(false) }
    // 使用 View 层 WindowInsetsAnimationCompat.Callback，完全脱离 Compose composition 阶段：
    //   - onProgress 由系统在主线程每帧回调，不触发任何 Compose recomposition
    //   - bottomState.intValue 更新仅触发读取它的 graphicsLayer 重绘（draw phase），开销极小
    //   - (imeBottom - navBottom) 仅统计键盘在导航栏以上的可见高度，避免 content 多移动一个导航栏距离
    //   - runningAnimations 中有 IME 类型时标记 isImeAnimating，供跟滚协程暂停，避免与手动平移叠加闪动
    //
    // 补充：解锁屏幕 / 从后台恢复时，输入法有时不经 insets 动画直接显示，onProgress 不会跑，
    // ime 高度会卡在 0（聊天页为 ADJUST_NOTHING，系统也不会代为重布局）。用全局布局监听 +
    // ON_RESUME 后 post 再读 root insets，与动画路径双轨同步同一 state。
    DisposableEffect(view, lifecycleOwner) {
        val imeTypeMask = ViewWindowInsetsCompat.Type.ime()
        val navBarFallbackPx = runCatching {
            val resources = view.context.resources
            val resId = resources.getIdentifier("navigation_bar_height", "dimen", "android")
            if (resId > 0) resources.getDimensionPixelSize(resId) else 0
        }.getOrDefault(0)
        var stableNavBottomPx = navBarFallbackPx

        fun imeVisibleBottomAboveNav(imeBottom: Int, rawNavBottom: Int): Int {
            if (rawNavBottom > 0) {
                stableNavBottomPx = rawNavBottom
            }
            val navBottomForIme = if (imeBottom > 0) {
                max(rawNavBottom, stableNavBottomPx)
            } else {
                rawNavBottom
            }
            return (imeBottom - navBottomForIme).coerceAtLeast(0)
        }

        // 将 IME 高度写入 Compose State，不受动画状态限制时直接写。
        // sync 路径（GlobalLayout / ON_RESUME）在 animatingState=true 时被拦截，
        // 防止与 onProgress 逐帧值互相覆盖。
        fun pushImeBottomFromInsets(insets: ViewWindowInsetsCompat, logTag: String, force: Boolean = false) {
            val imeBottom = insets.getInsets(imeTypeMask).bottom
            val navBottom = insets.getInsets(ViewWindowInsetsCompat.Type.navigationBars()).bottom
            val visible = imeVisibleBottomAboveNav(imeBottom, navBottom)
            if (!force && animatingState.value) {
                android.util.Log.v("KBD_DBG", "$logTag skip-during-anim visible=$visible")
                return
            }
            if (bottomState.intValue != visible) {
                bottomState.intValue = visible
                android.util.Log.d("ImeMove", "$logTag ime=$imeBottom  nav=$navBottom  applied=$visible")
            }
            if (targetBottomState.intValue != visible) {
                targetBottomState.intValue = visible
            }
        }
        fun syncImeBottomFromRootInsets() {
            ViewCompat.getRootWindowInsets(view)?.let { pushImeBottomFromInsets(it, "sync:      ") }
        }

        val insetsHost: View = (view.context as? Activity)?.window?.decorView ?: view.rootView
        syncImeBottomFromRootInsets()

        // GlobalLayout：用于解锁/切回后台等无动画场景下键盘已显示时同步高度。
        // 当 onPrepare 触发后 animatingState=true，此处会被自动拦截，不会与 onProgress 冲突。
        val layoutListener = ViewTreeObserver.OnGlobalLayoutListener { syncImeBottomFromRootInsets() }
        view.viewTreeObserver.addOnGlobalLayoutListener(layoutListener)

        val callback = object : WindowInsetsAnimationCompat.Callback(DISPATCH_MODE_STOP) {
            // onPrepare 在动画开始、布局提交之前触发——这是正确的拦截点。
            // 它比 GlobalLayout、onStart 更早，在此将 animatingState 置 true，
            // GlobalLayout 的 guard 就能在第一帧 onProgress 出现之前拦住 sync 路径，
            // 消除"sync 写入最终值 → onProgress 首帧归零"导致的视觉大跳。
            override fun onPrepare(animation: WindowInsetsAnimationCompat) {
                if ((animation.typeMask and imeTypeMask) != 0) {
                    animatingState.value = true
                    android.util.Log.d("KBD_DBG", "IME onPrepare: guard up, currentBottom=${bottomState.intValue}")
                }
            }
            override fun onStart(
                animation: WindowInsetsAnimationCompat,
                bounds: WindowInsetsAnimationCompat.BoundsCompat
            ): WindowInsetsAnimationCompat.BoundsCompat {
                val isIme = (animation.typeMask and imeTypeMask) != 0
                if (isIme) {
                    val navBottom = ViewCompat.getRootWindowInsets(view)
                        ?.getInsets(ViewWindowInsetsCompat.Type.navigationBars())
                        ?.bottom
                        ?: 0
                    val targetVisible = if (bottomState.intValue > 0) {
                        0
                    } else {
                        imeVisibleBottomAboveNav(bounds.upperBound.bottom, navBottom)
                    }
                    if (targetBottomState.intValue != targetVisible) {
                        targetBottomState.intValue = targetVisible
                    }
                }
                android.util.Log.d("KBD_DBG", "IME onStart: isIme=$isIme durationMs=${animation.durationMillis} boundsUpper=${bounds.upperBound.bottom} currentBottom=${bottomState.intValue}")
                return super.onStart(animation, bounds)
            }
            override fun onProgress(
                insets: ViewWindowInsetsCompat,
                runningAnimations: MutableList<WindowInsetsAnimationCompat>
            ): ViewWindowInsetsCompat {
                val imeBottom = insets.getInsets(imeTypeMask).bottom
                val navBottom = insets.getInsets(ViewWindowInsetsCompat.Type.navigationBars()).bottom
                val visible = imeVisibleBottomAboveNav(imeBottom, navBottom)
                val prevVisible = bottomState.intValue
                // animatingState 已在 onPrepare 置 true，此处仅更新实际高度值
                bottomState.intValue = visible
                if (kotlin.math.abs(visible - prevVisible) > 10) {
                    android.util.Log.d("KBD_DBG", "IME onProgress: applied=$visible(prev=$prevVisible)")
                }
                android.util.Log.v("ImeMove", "onProgress: ime=$imeBottom  nav=$navBottom  applied=$visible")
                return insets
            }
            override fun onEnd(animation: WindowInsetsAnimationCompat) {
                val isIme = (animation.typeMask and imeTypeMask) != 0
                if (isIme) {
                    animatingState.value = false
                }
                // force=true：动画结束后用最终 insets 对齐，消除插值残差
                ViewCompat.getRootWindowInsets(view)?.let { insets ->
                    val imeBottom = insets.getInsets(imeTypeMask).bottom
                    val navBottom = insets.getInsets(ViewWindowInsetsCompat.Type.navigationBars()).bottom
                    val visible = imeVisibleBottomAboveNav(imeBottom, navBottom)
                    android.util.Log.d("KBD_DBG", "IME onEnd: isIme=$isIme finalBottom=$visible(prev=${bottomState.intValue})")
                    if (targetBottomState.intValue != visible) {
                        targetBottomState.intValue = visible
                    }
                    pushImeBottomFromInsets(insets, "onEnd:     ", force = true)
                }
            }
        }
        ViewCompat.setWindowInsetsAnimationCallback(view, callback)
        val resumeObserver = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_RESUME) {
                // 解锁后键盘若已显示，系统有时不会再次派发 insets 动画；requestApplyInsets + 双次 post 对齐晚到一帧的 IME 高度。
                view.post {
                    ViewCompat.requestApplyInsets(insetsHost)
                    syncImeBottomFromRootInsets()
                }
                view.post { syncImeBottomFromRootInsets() }
            }
        }
        lifecycleOwner.lifecycle.addObserver(resumeObserver)
        onDispose {
            if (view.viewTreeObserver.isAlive) {
                view.viewTreeObserver.removeOnGlobalLayoutListener(layoutListener)
            }
            ViewCompat.setWindowInsetsAnimationCallback(view, null)
            lifecycleOwner.lifecycle.removeObserver(resumeObserver)
        }
    }
    return ImeSyncState(
        imeBottomPx = bottomState,
        imeTargetBottomPx = targetBottomState,
        isImeAnimating = animatingState
    )
}
