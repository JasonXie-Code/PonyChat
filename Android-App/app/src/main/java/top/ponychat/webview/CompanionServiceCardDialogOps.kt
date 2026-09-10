package top.ponychat.webview

import android.app.Activity
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.pm.ServiceInfo
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.BitmapShader
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Outline
import android.graphics.Paint
import android.graphics.PixelFormat
import android.graphics.RectF
import android.graphics.Shader
import android.graphics.drawable.GradientDrawable
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.Image
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.VibrationEffect
import android.os.Vibrator
import android.content.pm.PackageManager
import android.provider.Settings
import android.text.InputType
import android.util.Base64
import android.util.DisplayMetrics
import android.util.Log
import android.animation.Animator
import android.animation.AnimatorListenerAdapter
import android.animation.ValueAnimator
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import android.view.ViewOutlineProvider
import android.view.WindowManager
import android.view.animation.AccelerateInterpolator
import android.view.animation.DecelerateInterpolator
import android.view.animation.LinearInterpolator
import android.view.inputmethod.InputMethodManager
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.util.ClientContextHelper
import androidx.core.app.NotificationCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import kotlin.math.abs

internal fun CompanionService.showCompanionCard(text: String) {
    mainHandler.post { showOrUpdateCompanionCardOnMain(text) }
}

/**
 * 直接在主线程调用：显示或更新弹幕卡片，无嵌套 mainHandler.post。
 * 可从已在主线程的代码（如 mainHandler.post lambda）中直接调用。
 */
internal fun CompanionService.showOrUpdateCompanionCardOnMain(text: String) {
        // 服务已在销毁中（onDestroy 第一行置 false），不再创建/更新卡片
        // 这同时拦截了 mainHandler.post 队列里已入队但晚于 onDestroy 执行的回调
        if (!CompanionService._isRunning.value) return
        if (!Settings.canDrawOverlays(this)) return

        if (currentCardView != null) {
            currentCardContentTv?.text = text
            // agent 循环结束后，隐藏状态行，卡片恢复单行显示
            if (!CompanionService._isAutoLooping.value) {
                currentCardStatusTv?.text = ""
                currentCardStatusTv?.visibility = View.GONE
            }
            autoHideRunnable?.let { mainHandler.removeCallbacks(it) }
            scheduleAutoHide()
            return
        }

        val prefs = AppPreferences(applicationContext)
        val textColor = when (prefs.companionCardTextColor) {
            "yellow" -> Color.parseColor("#FFE57F")
            "cyan"   -> Color.parseColor("#80DEEA")
            else     -> Color.WHITE
        }
        val textSizeSp = when (prefs.companionCardFontSize) {
            "small"  -> 12f
            "large"  -> 16f
            "xlarge" -> 18f
            else     -> 14f
        }
        val cardWidthPx = when (prefs.companionCardWidth) {
            "small" -> dpToPx(200)
            "large" -> dpToPx(320)
            else    -> dpToPx(260)
        }
        val bgAlpha = (prefs.companionCardAlpha * 255 / 100).coerceIn(25, 255)

        val container = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dpToPx(12), dpToPx(10), dpToPx(12), dpToPx(12))
            background = GradientDrawable().apply {
                setColor(Color.argb(bgAlpha, 0, 0, 0))
                cornerRadius = dpToPx(14).toFloat()
            }
            alpha = 0f
        }
        val titleTv = TextView(this).apply {
            this.text = "💬 $characterName"
            textSize = 11f
            setTextColor(Color.parseColor("#99FFFFFF"))
        }
        val divider = View(this).apply { setBackgroundColor(Color.parseColor("#33FFFFFF")) }
        val statusTv = TextView(this).apply {
            this.text = ""
            textSize = 11f
            setTextColor(Color.parseColor("#BBFFFFFF"))
            visibility = View.GONE
        }
        val contentTv = TextView(this).apply {
            this.text = text
            textSize = textSizeSp
            setTextColor(textColor)
            maxLines = 5
            setLineSpacing(0f, 1.2f)
        }
        val dividerLp = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, dpToPx(1))
            .apply { setMargins(0, dpToPx(6), 0, dpToPx(8)) }
        val statusLp = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT)
            .apply { setMargins(0, 0, 0, dpToPx(4)) }
        container.addView(titleTv)
        container.addView(divider, dividerLp)
        container.addView(statusTv, statusLp)
        container.addView(contentTv)
        currentCardStatusTv = statusTv
        currentCardContentTv = contentTv

        val savedX = prefs.companionCardX
        val savedY = prefs.companionCardY
        val initX = if (savedX >= 0) savedX else dpToPx(16)
        val initY = if (savedY >= 0) savedY else screenHeight / 4

        val cardParams = WindowManager.LayoutParams(
            cardWidthPx,
            WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE,
            PixelFormat.TRANSLUCENT
        ).apply {
            gravity = Gravity.TOP or Gravity.START
            x = initX; y = initY
        }
        currentCardView = container

        var downRawX = 0f; var downRawY = 0f
        var initPx = 0; var initPy = 0
        var hasDragged = false

        container.setOnTouchListener { _, event ->
            when (event.action) {
                MotionEvent.ACTION_DOWN -> {
                    downRawX = event.rawX; downRawY = event.rawY
                    initPx = cardParams.x; initPy = cardParams.y
                    hasDragged = false; true
                }
                MotionEvent.ACTION_MOVE -> {
                    val dx = (event.rawX - downRawX).toInt()
                    val dy = (event.rawY - downRawY).toInt()
                    if (abs(dx) > 8 || abs(dy) > 8) {
                        hasDragged = true
                        cardParams.x = (initPx + dx).coerceIn(0, (screenWidth - cardWidthPx).coerceAtLeast(0))
                        cardParams.y = (initPy + dy).coerceIn(0, screenHeight - dpToPx(80))
                        try { windowManager.updateViewLayout(container, cardParams) } catch (_: Exception) {}
                    }
                    true
                }
                MotionEvent.ACTION_UP -> {
                    if (hasDragged) {
                        prefs.companionCardX = cardParams.x
                        prefs.companionCardY = cardParams.y
                    } else {
                        openChatDialog()
                    }
                    true
                }
                else -> false
            }
        }

        windowManager.addView(container, cardParams)
        container.animate()
            .alpha(1f)
            .setDuration(220)
            .setInterpolator(LinearInterpolator())
            .start()
        scheduleAutoHide()
}

internal fun CompanionService.scheduleAutoHide() {
    // Agent 循环进行中时不自动隐藏卡片，避免 removeViewImmediate 触发窗口树重建，
    // 导致 executeAgentAction → doInputText 看到 rootInActiveWindow == null。
    // 循环结束（CompanionService._isAutoLooping = false 后）才恢复正常 auto-hide。
    if (CompanionService._isAutoLooping.value) return
    // 先取消旧定时器，防止多次调用积累多个 Runnable 导致卡片提前消失
    autoHideRunnable?.let { mainHandler.removeCallbacks(it) }
    autoHideRunnable = null
    // 语音开启时：由 CompanionTtsBridge.onAllDone 在音频播完后触发消失，不设定时器。
    // 这同时覆盖问候语场景（进入通话模式前）和通话中场景。
    if (AppPreferences(applicationContext).companionVoiceEnabled) return
    // 语音关闭：10 秒后自动消失
    autoHideRunnable = Runnable { dismissCard() }.also {
        mainHandler.postDelayed(it, 10_000L)
    }
}

internal fun CompanionService.dismissCard() {
    autoHideRunnable?.let { mainHandler.removeCallbacks(it) }
    autoHideRunnable = null
    val view = currentCardView ?: return
    currentCardView = null
    currentCardContentTv = null
    currentCardStatusTv = null
    // 根因：Overlay 窗口做 alpha 淡出 + removeView 在部分机型会闪一帧。
    // 直接移除窗口，避免窗口级重绘闪烁。
    view.animate().setListener(null)
    view.animate().cancel()
    try { windowManager.removeViewImmediate(view) } catch (_: Exception) {
        try { windowManager.removeView(view) } catch (_: Exception) {}
    }
}

// ── 半屏对话卡片 ──────────────────────────────────────────────────────────

internal fun CompanionService.openChatDialog() {
    if (chatDialogView != null || isChatDialogOpening) return
    if (!Settings.canDrawOverlays(this)) return
    isChatDialogOpening = true

    mainHandler.post {
        if (chatDialogView != null) {
            isChatDialogOpening = false
            return@post
        }
        val prefs = AppPreferences(applicationContext)
        val bgAlpha = (prefs.companionCardAlpha * 255 / 100).coerceIn(210, 255)
        val cardHeight = screenHeight / 2

        // ── 根布局 ───────────────────────────────────────────────────────
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            alpha = 0f
            background = GradientDrawable().apply {
                setColor(Color.argb(bgAlpha, 8, 8, 24))
                // 卡片贴顶部：上角平，下角圆
                cornerRadii = floatArrayOf(
                    0f, 0f, 0f, 0f,
                    dpToPx(20).toFloat(), dpToPx(20).toFloat(),
                    dpToPx(20).toFloat(), dpToPx(20).toFloat()
                )
            }
            clipToOutline = true
            outlineProvider = android.view.ViewOutlineProvider.BACKGROUND
        }

        // ── 标题栏 ───────────────────────────────────────────────────────
        val header = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            setPadding(dpToPx(18), dpToPx(14), dpToPx(14), dpToPx(10))
            gravity = Gravity.CENTER_VERTICAL
        }
        val identityBlock = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
        }
        identityBlock.addView(TextView(this).apply {
            text = characterName
            textSize = 15f
            setTextColor(Color.WHITE)
        })
        identityBlock.addView(TextView(this).apply {
            val summary = characterPersonality.trim().take(24)
            text = listOf(summary, currentPersonalityStyleLabel())
                .filter { it.isNotBlank() }
                .joinToString(" · ")
            textSize = 10f
            maxLines = 1
            setTextColor(Color.parseColor("#88FFFFFF"))
        })
        val roleBtn = TextView(this).apply {
            text = "换角色"
            textSize = 12f
            setTextColor(Color.parseColor("#FFB7B0FF"))
            setPadding(dpToPx(8), dpToPx(5), dpToPx(8), dpToPx(5))
            setOnClickListener { showCompanionCharacterMenu(this) }
        }
        val styleBtn = TextView(this).apply {
            text = "个性"
            textSize = 12f
            setTextColor(Color.parseColor("#FFB7B0FF"))
            setPadding(dpToPx(8), dpToPx(5), dpToPx(8), dpToPx(5))
            setOnClickListener { showCompanionPersonalityMenu() }
        }
        val closeBtn = TextView(this).apply {
            text = "✕"
            textSize = 17f
            setTextColor(Color.parseColor("#88FFFFFF"))
            setPadding(dpToPx(10), dpToPx(4), dpToPx(6), dpToPx(4))
            setOnClickListener { closeChatDialog() }
        }
        header.addView(identityBlock)
        header.addView(roleBtn)
        header.addView(styleBtn)
        header.addView(closeBtn)

        val topDivider = View(this).apply {
            setBackgroundColor(Color.parseColor("#22FFFFFF"))
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, dpToPx(1)
            )
        }

        // ── 消息滚动区 ───────────────────────────────────────────────────
        val scrollView = ScrollView(this).apply {
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f
            )
            clipToPadding = false
        }
        val messagesLayout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dpToPx(14), dpToPx(10), dpToPx(14), dpToPx(10))
        }
        scrollView.addView(messagesLayout)
        chatMessagesLayout = messagesLayout
        chatScrollView = scrollView

        // 注入已有历史
        conversationHistory.forEach { addMessageBubble(messagesLayout, it.isUser, it.text, animate = false) }

        // ── 输入栏 ───────────────────────────────────────────────────────
        val inputBar = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            setPadding(dpToPx(8), dpToPx(8), dpToPx(8), dpToPx(10))
            gravity = Gravity.CENTER_VERTICAL
            setBackgroundColor(Color.parseColor("#18FFFFFF"))
        }

        val editText = EditText(this).apply {
            hint = "和${characterName}说点什么…"
            setHintTextColor(Color.parseColor("#66FFFFFF"))
            setTextColor(Color.WHITE)
            textSize = 14f
            background = null
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_MULTI_LINE
            maxLines = 3
            isSingleLine = false
            layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
            setPadding(dpToPx(4), dpToPx(6), dpToPx(4), dpToPx(6))
        }
        chatInputEt = editText

        val sendBtn = TextView(this).apply {
            text = "发送"
            textSize = 14f
            setTextColor(Color.parseColor("#FF6C63E4"))
            setPadding(dpToPx(12), dpToPx(6), dpToPx(8), dpToPx(6))
            setOnClickListener {
                val msg = editText.text.toString().trim()
                if (msg.isNotBlank()) {
                    editText.setText("")
                    sendUserText(msg)
                }
            }
        }

        inputBar.addView(editText)
        inputBar.addView(sendBtn)

        root.addView(header)
        root.addView(topDivider)
        root.addView(scrollView)
        root.addView(inputBar)

        val dialogParams = WindowManager.LayoutParams(
            WindowManager.LayoutParams.MATCH_PARENT,
            cardHeight,
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            // 去掉 FLAG_NOT_FOCUSABLE 使输入框可聚焦
            WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL or
                    WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
            PixelFormat.TRANSLUCENT
        ).apply {
            gravity = Gravity.TOP
            softInputMode = WindowManager.LayoutParams.SOFT_INPUT_ADJUST_NOTHING
        }

        chatDialogView = root
        windowManager.addView(root, dialogParams)
        isChatDialogOpening = false

        // 淡入
        root.animate().alpha(1f).setDuration(220).setInterpolator(LinearInterpolator()).start()

        // 滚动到底 + 弹出键盘
        scrollToBottom()
        mainHandler.postDelayed({
            editText.requestFocus()
            val imm = getSystemService(android.content.Context.INPUT_METHOD_SERVICE) as InputMethodManager
            imm.showSoftInput(editText, InputMethodManager.SHOW_IMPLICIT)
        }, 300)
    }
}

internal fun CompanionService.closeChatDialog() {
    dismissCompanionIdentityChooser()
    val view = chatDialogView ?: return
    chatDialogView = null
    isChatDialogOpening = false
    chatMessagesLayout = null
    chatScrollView = null
    val et = chatInputEt
    chatInputEt = null
    // 收键盘
    if (et != null) {
        val imm = getSystemService(android.content.Context.INPUT_METHOD_SERVICE) as InputMethodManager
        imm.hideSoftInputFromWindow(et.windowToken, 0)
    }
    // 同上：避免 Overlay 窗口淡出时闪烁
    view.animate().setListener(null)
    view.animate().cancel()
    try { windowManager.removeViewImmediate(view) } catch (_: Exception) {
        try { windowManager.removeView(view) } catch (_: Exception) {}
    }
}

internal fun CompanionService.addMessageBubble(container: LinearLayout, isUser: Boolean, text: String, animate: Boolean = true): TextView {
    val bubbleBg = GradientDrawable().apply {
        cornerRadius = dpToPx(14).toFloat()
        setColor(
            if (isUser) Color.parseColor("#CC6C63E4")
            else Color.parseColor("#44FFFFFF")
        )
    }
    val tv = TextView(this).apply {
        this.text = text
        textSize = 13f
        setTextColor(Color.WHITE)
        maxWidth = (screenWidth * 0.72).toInt()
        setPadding(dpToPx(12), dpToPx(8), dpToPx(12), dpToPx(8))
        setLineSpacing(0f, 1.25f)
        background = bubbleBg
    }
    val rowLp = LinearLayout.LayoutParams(
        LinearLayout.LayoutParams.MATCH_PARENT,
        LinearLayout.LayoutParams.WRAP_CONTENT
    ).apply { setMargins(0, dpToPx(3), 0, dpToPx(3)) }
    val row = LinearLayout(this).apply {
        orientation = LinearLayout.HORIZONTAL
        gravity = if (isUser) Gravity.END else Gravity.START
        layoutParams = rowLp
        alpha = if (animate) 0f else 1f
    }
    row.addView(tv)
    container.addView(row)
    if (animate) {
        row.animate().alpha(1f).setDuration(140).setInterpolator(LinearInterpolator()).start()
    }
    return tv
}

internal fun CompanionService.appendMessageToDialog(isUser: Boolean, text: String, animate: Boolean = true) {
    mainHandler.post {
        chatMessagesLayout?.let { container ->
            val tv = addMessageBubble(container, isUser, text, animate = animate)
            if (isUser) pendingUserBubbleTv = tv
        }
        scrollToBottom()
    }
}

internal fun CompanionService.scrollToBottom() {
    mainHandler.postDelayed({
        chatScrollView?.fullScroll(View.FOCUS_DOWN)
    }, 80)
}

// ── 通知 ─────────────────────────────────────────────────────────────────
