package top.ponychat.companion.overlay

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
import android.graphics.PixelFormat
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.Binder
import android.os.IBinder
import android.provider.Settings
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.ViewConfiguration
import android.view.WindowManager
import android.widget.LinearLayout
import android.widget.Button
import android.widget.TextView
import top.ponychat.companion.R
import top.ponychat.companion.android.DeviceProvisioningPolicy
import kotlin.math.roundToInt

class AgentStatusOverlayService : Service() {
    private val localBinder = Binder()
    private lateinit var windowManager: WindowManager
    private var overlayView: View? = null
    private var layoutParams: WindowManager.LayoutParams? = null
    private var minimized = false
    private var dotView: View? = null
    private lateinit var goalView: TextView
    private lateinit var summaryView: TextView
    private lateinit var planView: TextView
    private lateinit var detailView: TextView
    private lateinit var modelView: TextView
    private lateinit var dragHandle: View
    private lateinit var controlsView: LinearLayout
    private var passAgentInputThrough = false
    private val stateListener: (AgentOverlayState) -> Unit = { render(it) }

    override fun onCreate() {
        super.onCreate()
        isRunning = true
        createNotificationChannel()
        startForeground(NOTIFICATION_ID, buildNotification())
        windowManager = getSystemService(WINDOW_SERVICE) as WindowManager
        showOverlayIfAllowed()
        AgentOverlayController.subscribe(stateListener)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        showOverlayIfAllowed()
        return START_STICKY
    }

    override fun onBind(intent: Intent?): IBinder = localBinder

    override fun onDestroy() {
        isRunning = false
        AgentOverlayController.unsubscribe(stateListener)
        overlayView?.let { runCatching { windowManager.removeView(it) } }
        overlayView = null
        dotView = null
        super.onDestroy()
    }

    private fun showOverlayIfAllowed() {
        if (!DeviceProvisioningPolicy.isProvisioned(this)) {
            stopSelf()
            return
        }
        if (overlayView != null || !Settings.canDrawOverlays(this)) return
        val prefs = overlayPreferences()
        minimized = prefs.getBoolean(KEY_MINIMIZED, false)
        val params = WindowManager.LayoutParams(
            if (minimized) dp(DOT_SIZE_DP) else dp(330),
            if (minimized) dp(DOT_SIZE_DP) else WindowManager.LayoutParams.WRAP_CONTENT,
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
            } else {
                @Suppress("DEPRECATION")
                WindowManager.LayoutParams.TYPE_PHONE
            },
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL or
                WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
            PixelFormat.TRANSLUCENT,
        ).apply {
            gravity = Gravity.TOP or Gravity.START
            x = prefs.getInt(if (minimized) KEY_DOT_X else KEY_X, dp(16))
            y = prefs.getInt(if (minimized) KEY_DOT_Y else KEY_Y, dp(96))
        }
        layoutParams = params
        overlayView = (if (minimized) buildDot() else buildOverlay()).also { view ->
            windowManager.addView(view, params)
            if (minimized) {
                attachDotGesture(view, params)
            } else {
                attachDrag(dragHandle, view, params)
            }
        }
        render(AgentOverlayController.state)
    }

    private fun buildOverlay(): View {
        val card = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(15), dp(12), dp(15), dp(13))
            background = GradientDrawable().apply {
                // 70% 不透明度：保留清晰文字，同时可透过约 30% 的后台内容。
                setColor(Color.argb(179, 20, 20, 38))
                cornerRadius = dp(18).toFloat()
                setStroke(dp(1), Color.parseColor("#706C63FF"))
            }
            elevation = dp(12).toFloat()
        }
        val header = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
        }
        dragHandle = header
        header.addView(TextView(this).apply {
            text = "●"
            textSize = 13f
            setTextColor(Color.parseColor("#79E6BF"))
        })
        header.addView(TextView(this).apply {
            text = "  Companion Agent"
            textSize = 15f
            setTextColor(Color.WHITE)
            setTypeface(typeface, android.graphics.Typeface.BOLD)
        }, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        header.addView(TextView(this).apply {
            text = "收起"
            textSize = 12f
            gravity = Gravity.CENTER
            setTextColor(Color.WHITE)
            contentDescription = "收起悬浮窗"
            isClickable = true
            isFocusable = true
            background = GradientDrawable().apply {
                setColor(Color.parseColor("#66554F8E"))
                cornerRadius = dp(10).toFloat()
                setStroke(dp(1), Color.parseColor("#8E86C7"))
            }
            setOnClickListener { minimizeOverlay() }
        }, LinearLayout.LayoutParams(dp(64), dp(34)))
        card.addView(header)

        goalView = textView(17f, Color.WHITE, bold = true).also {
            it.setPadding(0, dp(12), 0, dp(4))
            card.addView(it)
        }
        summaryView = textView(13f, Color.parseColor("#DAD8EA")).also { card.addView(it) }
        planView = textView(12f, Color.parseColor("#C8C4E8")).also {
            it.setPadding(0, dp(10), 0, dp(8))
            it.background = GradientDrawable().apply {
                setColor(Color.parseColor("#22FFFFFF"))
                cornerRadius = dp(10).toFloat()
            }
            card.addView(it)
        }
        detailView = textView(11f, Color.parseColor("#AAA7C2")).also {
            it.setPadding(0, dp(8), 0, 0)
            card.addView(it)
        }
        controlsView = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.END
            visibility = View.GONE
            setPadding(0, dp(10), 0, 0)
        }
        controlsView.addView(controlButton("停止").apply {
            setOnClickListener { AgentOverlayController.stopAfterUser(this@AgentStatusOverlayService) }
        })
        controlsView.addView(controlButton("继续").apply {
            setOnClickListener { AgentOverlayController.continueAfterUser(this@AgentStatusOverlayService) }
        })
        card.addView(controlsView)
        modelView = textView(10f, Color.parseColor("#85819E")).also {
            it.gravity = Gravity.END
            it.setPadding(0, dp(6), 0, 0)
            card.addView(it)
        }
        return card
    }

    private fun buildDot(): View = CompanionDotView(this).apply {
        dotView = this
        contentDescription = "Companion 悬浮圆点，拖动可移动，单击展开"
        background = GradientDrawable().apply {
            shape = GradientDrawable.OVAL
            setColor(Color.parseColor("#8B72FF"))
            setStroke(dp(2), Color.parseColor("#BDB1FF"))
        }
        elevation = dp(12).toFloat()
    }

    private class CompanionDotView(context: Context) : View(context) {
        private val starPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = Color.WHITE
            style = Paint.Style.FILL
        }
        private val starPath = Path()

        override fun onDraw(canvas: Canvas) {
            super.onDraw(canvas)
            val centerX = width / 2f
            val centerY = height / 2f
            val radius = minOf(width, height) * 0.24f
            val inset = radius * 0.36f
            starPath.reset()
            starPath.moveTo(centerX, centerY - radius)
            starPath.cubicTo(
                centerX + inset * 0.15f,
                centerY - inset,
                centerX + inset,
                centerY - inset * 0.15f,
                centerX + radius,
                centerY,
            )
            starPath.cubicTo(
                centerX + inset,
                centerY + inset * 0.15f,
                centerX + inset * 0.15f,
                centerY + inset,
                centerX,
                centerY + radius,
            )
            starPath.cubicTo(
                centerX - inset * 0.15f,
                centerY + inset,
                centerX - inset,
                centerY + inset * 0.15f,
                centerX - radius,
                centerY,
            )
            starPath.cubicTo(
                centerX - inset,
                centerY - inset * 0.15f,
                centerX - inset * 0.15f,
                centerY - inset,
                centerX,
                centerY - radius,
            )
            starPath.close()
            canvas.drawPath(starPath, starPaint)
        }
    }

    private fun textView(size: Float, color: Int, bold: Boolean = false) = TextView(this).apply {
        textSize = size
        setTextColor(color)
        if (bold) setTypeface(typeface, android.graphics.Typeface.BOLD)
        setLineSpacing(0f, 1.08f)
    }

    private fun controlButton(label: String) = Button(this).apply {
        text = label
        textSize = 12f
        isAllCaps = false
        setTextColor(Color.WHITE)
        backgroundTintList = android.content.res.ColorStateList.valueOf(
            if (label == "继续") Color.parseColor("#8B72FF") else Color.parseColor("#554F6E"),
        )
        minWidth = dp(76)
    }

    private fun render(state: AgentOverlayState) {
        if (overlayView == null) return
        overlayView?.visibility = if (state.overlayVisible) View.VISIBLE else View.GONE
        if (!state.overlayVisible) return
        updateInputPassthrough(state.agentInputActive)
        if (minimized) {
            dotView?.contentDescription =
                "Companion ${AgentOverlayPresentation.progressLabel(state)}，拖动可移动，单击展开"
            return
        }
        goalView.text = state.goal
        summaryView.text = state.decisionSummary
        planView.text = AgentOverlayPresentation.planLines(state).joinToString("\n")
        detailView.text = buildString {
            if (state.action.isNotBlank()) append("动作：${state.action}")
            if (state.verification.isNotBlank()) {
                if (isNotEmpty()) append("\n")
                append("验证：${state.verification}")
            }
        }
        detailView.visibility = if (detailView.text.isNullOrBlank()) View.GONE else View.VISIBLE
        controlsView.visibility = if (state.userPaused) View.VISIBLE else View.GONE
        modelView.text = if (passAgentInputThrough) {
            "模型 · ${state.model}  ｜ Agent 操作穿透中"
        } else {
            "模型 · ${state.model}  ｜ 拖动标题栏改变位置"
        }
    }

    private fun updateInputPassthrough(enabled: Boolean) {
        val shouldPassThrough = enabled && !minimized
        if (passAgentInputThrough == shouldPassThrough) return
        val view = overlayView ?: return
        val params = layoutParams ?: return
        passAgentInputThrough = shouldPassThrough
        params.flags = if (shouldPassThrough) {
            params.flags or WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE
        } else {
            params.flags and WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE.inv()
        }
        windowManager.updateViewLayout(view, params)
    }

    private fun attachDrag(handle: View, window: View, params: WindowManager.LayoutParams) {
        var initialX = 0
        var initialY = 0
        var initialTouchX = 0f
        var initialTouchY = 0f
        handle.setOnTouchListener { _, event ->
            when (event.actionMasked) {
                MotionEvent.ACTION_DOWN -> {
                    AgentOverlayController.pauseForUser(this)
                    if (!AgentOverlayController.beginUserInteraction()) return@setOnTouchListener false
                    initialX = params.x
                    initialY = params.y
                    initialTouchX = event.rawX
                    initialTouchY = event.rawY
                    true
                }
                MotionEvent.ACTION_MOVE -> {
                    val maxX = (resources.displayMetrics.widthPixels - window.width).coerceAtLeast(0)
                    val maxY = (resources.displayMetrics.heightPixels - window.height).coerceAtLeast(0)
                    params.x = (initialX + event.rawX - initialTouchX).roundToInt().coerceIn(0, maxX)
                    params.y = (initialY + event.rawY - initialTouchY).roundToInt().coerceIn(0, maxY)
                    windowManager.updateViewLayout(window, params)
                    true
                }
                MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                    overlayPreferences().edit()
                        .putInt(KEY_X, params.x)
                        .putInt(KEY_Y, params.y)
                        .apply()
                    AgentOverlayController.endUserInteraction()
                    true
                }
                else -> false
            }
        }
    }

    private fun attachDotGesture(window: View, params: WindowManager.LayoutParams) {
        var initialX = 0
        var initialY = 0
        val gesture = OverlayPointerGesture(
            ViewConfiguration.get(this).scaledTouchSlop.toFloat(),
        )
        window.setOnTouchListener { _, event ->
            when (event.actionMasked) {
                MotionEvent.ACTION_DOWN -> {
                    AgentOverlayController.pauseForUser(this)
                    if (!AgentOverlayController.beginUserInteraction()) return@setOnTouchListener false
                    initialX = params.x
                    initialY = params.y
                    gesture.start(event.rawX, event.rawY)
                    true
                }
                MotionEvent.ACTION_MOVE -> {
                    gesture.move(event.rawX, event.rawY)
                    val maxX = (resources.displayMetrics.widthPixels - window.width).coerceAtLeast(0)
                    val maxY = (resources.displayMetrics.heightPixels - window.height).coerceAtLeast(0)
                    params.x = (initialX + gesture.deltaX).roundToInt().coerceIn(0, maxX)
                    params.y = (initialY + gesture.deltaY).roundToInt().coerceIn(0, maxY)
                    windowManager.updateViewLayout(window, params)
                    true
                }
                MotionEvent.ACTION_UP -> {
                    val isClick = gesture.finish(event.rawX, event.rawY)
                    saveDotPosition(params)
                    AgentOverlayController.endUserInteraction()
                    if (isClick) restoreOverlay()
                    true
                }
                MotionEvent.ACTION_CANCEL -> {
                    gesture.cancel()
                    saveDotPosition(params)
                    AgentOverlayController.endUserInteraction()
                    true
                }
                else -> false
            }
        }
    }

    private fun minimizeOverlay() {
        val params = layoutParams ?: return
        overlayPreferences().edit()
            .putInt(KEY_X, params.x)
            .putInt(KEY_Y, params.y)
            .putInt(KEY_DOT_X, params.x)
            .putInt(KEY_DOT_Y, params.y)
            .putBoolean(KEY_MINIMIZED, true)
            .apply()
        recreateOverlay()
    }

    private fun restoreOverlay() {
        layoutParams?.let(::saveDotPosition)
        overlayPreferences().edit().putBoolean(KEY_MINIMIZED, false).apply()
        recreateOverlay()
    }

    private fun saveDotPosition(params: WindowManager.LayoutParams) {
        overlayPreferences().edit()
            .putInt(KEY_DOT_X, params.x)
            .putInt(KEY_DOT_Y, params.y)
            .apply()
    }

    private fun recreateOverlay() {
        overlayView?.let { runCatching { windowManager.removeView(it) } }
        overlayView = null
        layoutParams = null
        dotView = null
        passAgentInputThrough = false
        showOverlayIfAllowed()
    }

    private fun overlayPreferences() = createDeviceProtectedStorageContext()
        .getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    private fun buildNotification(): Notification = Notification.Builder(this, CHANNEL_ID)
        .setSmallIcon(R.drawable.ic_companion)
        .setContentTitle("Companion Agent 正在运行")
        .setContentText("任务计划与执行状态悬浮窗已启用")
        .setOngoing(true)
        .build()

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val channel = NotificationChannel(
            CHANNEL_ID,
            "Companion Agent 状态",
            NotificationManager.IMPORTANCE_LOW,
        )
        getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
    }

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).roundToInt()

    companion object {
        @Volatile
        internal var isRunning = false

        private const val CHANNEL_ID = "companion_agent_status"
        private const val NOTIFICATION_ID = 2201
        private const val PREFS_NAME = "agent_overlay"
        private const val KEY_X = "x"
        private const val KEY_Y = "y"
        private const val KEY_DOT_X = "dot_x"
        private const val KEY_DOT_Y = "dot_y"
        private const val KEY_MINIMIZED = "minimized"
        private const val DOT_SIZE_DP = 52
    }
}
