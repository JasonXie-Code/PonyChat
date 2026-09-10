package top.ponychat.webview
import android.app.Activity
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
class CompanionService : Service() {
    companion object {
        const val ACTION_START = "companion.START"
        const val ACTION_STOP = "companion.STOP"
        const val EXTRA_RESULT_CODE = "result_code"
        const val EXTRA_RESULT_DATA = "result_data"
        const val EXTRA_CHARACTER_ID = "character_id"
        const val EXTRA_CHARACTER_NAME = "character_name"
        const val EXTRA_CHARACTER_PERSONALITY = "character_personality"
        const val EXTRA_AUTH_TOKEN = "auth_token"
        const val EXTRA_API_BASE = "api_base"
        const val EXTRA_USERNAME = "username"
        const val EXTRA_AVATAR_URL = "avatar_url"
        /** 操作陪玩模式标志：true 时 AI 会返回触控操作指令并由 AgentAccessibilityService 执行 */
        const val EXTRA_AGENT_MODE = "agent_mode"
        const val CHANNEL_ID = "companion_channel"
        const val NOTIFY_ID = 8001
        const val TAG = "CompanionService"
        internal const val TAP_WINDOW_MS = 800L
        internal const val LONG_PRESS_MS = 1000L
        internal const val DRAG_THRESHOLD_PX = 10
        val _isRunning = MutableStateFlow(false)
        val isRunning: StateFlow<Boolean> = _isRunning.asStateFlow()
        /** 操作陪玩（Agent 模式）是否活跃 */
        internal val _isAgentRunning = MutableStateFlow(false)
        val isAgentRunning: StateFlow<Boolean> = _isAgentRunning.asStateFlow()
        /** 操作陪玩自动循环是否进行中（供 UI 反映状态） */
        val _isAutoLooping = MutableStateFlow(false)
        val isAutoLooping: StateFlow<Boolean> = _isAutoLooping.asStateFlow()
        /** 自动循环安全上限：最多连续执行 N 步，防止 AI 陷入死循环 */
        const val MAX_AGENT_LOOP_STEPS = 15
        /** 每步操作执行后等待 UI 刷新的延迟（ms） */
        const val AGENT_LOOP_STEP_DELAY_MS = 900L
    }
    // ── 对话消息 ──────────────────────────────────────────────────────────────
    internal data class CompanionMessage(val isUser: Boolean, val text: String)
    internal val conversationHistory = mutableListOf<CompanionMessage>()
    // ── 系统服务 ──────────────────────────────────────────────────────────────
    internal var mediaProjection: MediaProjection? = null
    internal var imageReader: ImageReader? = null
    internal var virtualDisplay: VirtualDisplay? = null
    internal lateinit var windowManager: WindowManager
    internal var floatingButtonView: View? = null
    internal val serviceScope = CoroutineScope(Dispatchers.IO + SupervisorJob())
    internal val mainHandler = Handler(Looper.getMainLooper())
    internal var isCapturing = false
    // ── 弹幕卡片 ─────────────────────────────────────────────────────────────
    internal var currentCardView: View? = null
    internal var currentCardContentTv: TextView? = null
    /** agent 模式下显示在卡片顶部的任务状态行（普通模式下隐藏） */
    internal var currentCardStatusTv: TextView? = null
    internal var autoHideRunnable: Runnable? = null
    // ── 半屏对话卡片 ──────────────────────────────────────────────────────────
    internal var chatDialogView: View? = null
    internal var identityChooserView: View? = null
    internal var chatMessagesLayout: LinearLayout? = null
    internal var chatScrollView: ScrollView? = null
    internal var chatInputEt: EditText? = null
    // ── 语音识别 ─────────────────────────────────────────────────────────────
    internal var voiceBridge: BackendStreamingVoiceBridge? = null
    /** Classic 模式预热连接：服务启动时提前建立 ASR WS 握手，用户长按时零延迟接管 */
    internal var prewarmBridge: BackendStreamingVoiceBridge? = null
    internal var isRecording = false
    /** onPartial 时预先拍摄的屏幕截图，供 onFinal 触发请求时直接使用，避免串行等待 */
    @Volatile internal var preCapturedBitmap: Bitmap? = null
    internal var recordingAnimator: ValueAnimator? = null
    internal var recordingHaloView: View? = null
    internal var recordingHaloDrawable: GradientDrawable? = null
    internal var captureScaleView: View? = null
    internal var isChatDialogOpening = false
    // ── 手势状态（悬浮按钮） ──────────────────────────────────────────────────
    internal var tapCount = 0
    internal var btnHasMoved = false
    internal var longPressRunnable: Runnable? = null
    /** 标记本次触摸中长按已触发，用于区分「长按后松手」和「单击停止录音」 */
    internal var longPressTriggered = false
    internal val processTapsRunnable = Runnable {
        val count = tapCount
        tapCount = 0
        when (count) {
            1 -> {
                if (isAgentMode) {
                    // 操作陪玩：单击 = 开始循环（或停止正在进行的循环）
                    if (autoLoopJob?.isActive == true) {
                        stopAgentLoop("用户单击中断")
                    } else {
                        startAgentLoop(agentLoopTask)
                    }
                } else {
                    triggerCapture()
                }
            }
            2 -> openChatDialog()
        }
    }
    // ── 基础参数 ─────────────────────────────────────────────────────────────
    internal var characterId = ""
    internal var characterName = ""
    internal var characterPersonality = ""
    internal var personalityStyle = "canonical"
    internal var authToken = ""
    internal var apiBase = ""
    internal var username = ""
    internal var avatarUrl = ""
    /** 操作陪玩模式：AI 除聊天外还会下发 tap/swipe 指令并自动执行 */
    internal var isAgentMode = false
    /** 聊天陪玩使用经典管道（模型大厅 LLM + 阿里云 ASR/TTS），即所有非操作陪玩场景 */
    internal val isClassicMode: Boolean get() = !isAgentMode
    /**
     * Classic 模式"通话"状态：进入后 ASR 会话持续开启，VAD 自动检测每句话，
     * onFinal 触发 LLM+TTS，对话结束后继续监听，直到用户单击挂断。
     * 类似视频电话：长按接通，单击挂断。
     */
    internal var isCallMode = false
    /** 当前通话 ASR 是否至少收到过 [BackendStreamingVoiceBridge.Callback.onStarted]（用于区分「从未握手成功」与「会话中意外断开」） */
    internal var callModeAsrEverStarted = false
    /** 通话模式下用户正在说话（onPartial 已触发，onFinal 尚未到来），此期间不向 TTS 入队新句子 */
    @Volatile internal var isUserSpeaking = false
    // ── 操作陪玩自动循环 ──────────────────────────────────────────────────────
    /** 当前自动循环的协程 Job，非 null 且 active 即表示正在循环 */
    internal var autoLoopJob: kotlinx.coroutines.Job? = null
    /** 本次循环已执行步数（含首步） */
    internal var autoLoopStepCount = 0
    /** 用户本次给出的任务描述，贯穿整个循环 */
    internal var agentLoopTask = ""
    /** 上一轮有实质操作内容的任务描述，供"重新点/再试一次"类指令回溯 */
    internal var lastMeaningfulTask = ""
    /** 本次循环的操作历史摘要列表，传给决策模型作为上下文 */
    internal val agentStepHistory = mutableListOf<String>()
    /**
     * executeAgentAction 执行后回写本次操作类型（"tap"/"swipe"/"none"），
     * 供循环逻辑判断是否继续。
     */
    internal var lastAgentActionType = "none"
    /** 最近一次 tap 的归一化坐标，用于生成带坐标的步骤历史 */
    internal var lastTapNx = -1f
    internal var lastTapNy = -1f
    /** 最近一次 swipe 的归一化坐标 */
    internal var lastSwipeFx = -1f
    internal var lastSwipeFy = -1f
    internal var lastSwipeTx = -1f
    internal var lastSwipeTy = -1f
    /** 最近一次 system action 的操作名 */
    internal var lastSystemAction = ""
    /** 最近一次 launch 的 App 名称及结果（"相册" 或 "相册-FAIL"） */
    internal var lastLaunchApp = ""
    /** 最近一次 long_press 的归一化坐标 */
    internal var lastLongPressNx = -1f
    internal var lastLongPressNy = -1f
    /** 最近一次 input_text 的内容（截断20字）；失败时追加 -FAIL 供下一步决策参考 */
    internal var lastInputText = ""
    /** 最近一次 failed 动作的原因说明 */
    internal var lastFailedReason = ""
    /** 最近一次 wait 动作的等待毫秒数（由 executeAgentAction 写入，agentLoopStep 使用后清零） */
    internal var lastWaitMs = 0L
    // ── Plan-and-Execute ─────────────────────────────────────────────────────
    /** 当前任务的规划步骤列表（空列表 = 未规划 / 单步兼容模式） */
    internal var agentPlan: List<String> = emptyList()
    /** 当前正在执行的计划步骤索引（0-based） */
    internal var agentPlanStepIndex: Int = 0
    /** 当前计划步骤内已执行的操作历史（步骤完成后清空；全局历史仍保留在 agentStepHistory） */
    internal val agentCurrentStepHistory = mutableListOf<String>()
    /** 卡住检测：最近 4 步动作标识，用于检测 AAA 和 ABAB 两种卡死模式 */
    internal val recentStepDescs = ArrayDeque<String>()
    /** 上一步执行前的截图缩略图（40×70px），用于下步开始时对比界面是否有变化 */
    internal var prevStepThumbnail: Bitmap? = null
    internal var ttsBridge: CompanionTtsBridge? = null
    /** 聊天陪玩模式（非 agent）：Qwen-Omni-Realtime 实时桥接 */
    internal var streamingBubbleTv: TextView? = null   // 当前流式气泡的 TextView（主线程）
    internal var streamingBubbleRow: View? = null      // 流式气泡的容器行，取消时整行移除
    internal var pendingUserBubbleTv: TextView? = null // 当前生成轮次的用户气泡，合并文字时更新
    internal var generatingJob: kotlinx.coroutines.Job? = null // 当前 AI 生成协程（仅 agent 模式使用）
    /**
     * 当前正在执行的 /api/companion/stream OkHttp Call。
     * 用户打断时调用 cancel() 强制关闭网络连接，使阻塞的 readUtf8Line() 立即抛 IOException，
     * 从而彻底终止旧的 SSE 流式循环，防止打断后 AI 继续把剩余句子推入 TTS 队列。
     */
    @Volatile internal var currentStreamingCall: okhttp3.Call? = null
    // ── 主动发言 ─────────────────────────────────────────────────────────────
    internal var proactiveRunnable: Runnable? = null  // 待执行的主动发言定时器
    internal var proactiveAttempted = false           // 本轮已发过主动消息，防止连续自言自语
    /** 用户无响应时连续主动发言次数；≥2 后保持沉默，用户说话时清零 */
    internal var proactiveConsecutiveCount = 0
    /** 上次用户或 AI 有活动的时间戳（用于判断是否真正空闲才发追加） */
    internal var lastActivityTimeMs: Long = 0L
    internal var screenWidth = 0
    internal var screenHeight = 0
    internal var screenDensity = 0
    internal var companionStartTime = 0L
    internal val captureWidth get() = if (isAgentMode) screenWidth else screenWidth / 2
    internal val captureHeight get() = if (isAgentMode) screenHeight else screenHeight / 2
    internal val httpClient = top.ponychat.webview.data.api.NetworkClient.createTrustAllClient(
        connectTimeoutSec = 30,
        readTimeoutSec = 30
    )
    // ── 生命周期 ──────────────────────────────────────────────────────────────
    override fun onCreate() {
        super.onCreate()
        windowManager = getSystemService(WINDOW_SERVICE) as WindowManager
        val metrics = DisplayMetrics()
        @Suppress("DEPRECATION")
        windowManager.defaultDisplay.getRealMetrics(metrics)
        screenWidth = metrics.widthPixels
        screenHeight = metrics.heightPixels
        screenDensity = metrics.densityDpi
        createNotificationChannel()
    }
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            stopSelf()
            return START_NOT_STICKY
        }
        _isRunning.value = true
        characterId = intent?.getStringExtra(EXTRA_CHARACTER_ID) ?: ""
        characterName = intent?.getStringExtra(EXTRA_CHARACTER_NAME) ?: ""
        characterPersonality = intent?.getStringExtra(EXTRA_CHARACTER_PERSONALITY) ?: ""
        authToken = intent?.getStringExtra(EXTRA_AUTH_TOKEN) ?: ""
        apiBase = intent?.getStringExtra(EXTRA_API_BASE) ?: ""
        username = intent?.getStringExtra(EXTRA_USERNAME) ?: ""
        avatarUrl = intent?.getStringExtra(EXTRA_AVATAR_URL) ?: ""
        isAgentMode = intent?.getBooleanExtra(EXTRA_AGENT_MODE, false) ?: false
        _isAgentRunning.value = isAgentMode
        ttsBridge = CompanionTtsBridge(apiBase, authToken).also { bridge ->
            // 通话模式下由 TTS 驱动卡片更新：每句开始合成时将该句文字写入卡片，
            // 而非随 SSE 流式 token 实时刷新，保证卡片内容与 AI 正在说的话一致。
            bridge.onSentenceStarted = { sentenceText ->
                mainHandler.post {
                    // 不限于通话模式：开场问候常在 isCallMode=false 时播放，否则卡片不会随 TTS 出现
                    if (chatDialogView == null) {
                        showOrUpdateCompanionCardOnMain(sentenceText)
                    }
                }
            }
            // 所有句子播放完毕（非被打断）→ 卡片消失，表示 AI 说完了
            // 不限制 isCallMode：问候语在进入通话模式前也可能在播，同样需要在播完后消失
            bridge.onAllDone = {
                mainHandler.post {
                    dismissCard()
                    // TTS 播完后安排下一轮主动发言（仅通话模式；截图模式下用户已退出录音，不自言自语）
                    // 连续主动发言 ≥2 次无用户响应时保持沉默，用户说话后自动恢复
                    if (isClassicMode && isCallMode && _isRunning.value
                        && proactiveRunnable == null && generatingJob?.isActive != true
                        && proactiveConsecutiveCount < 2) {
                        lastActivityTimeMs = System.currentTimeMillis()
                        val delayMs = if (proactiveAttempted) {
                            (15_000L..30_000L).random()  // 刚主动发过，多等一会儿，避免连续自言自语
                        } else {
                            (4_000L..8_000L).random()    // 正常回复后模拟换气再接一句
                        }
                        proactiveAttempted = false  // 重置，允许下一轮
                        proactiveRunnable = Runnable {
                            proactiveRunnable = null
                            // 发言前再检查：
                            // 1. 用户若已说话（sendUserText 会更新 lastActivityTimeMs），则静默丢弃
                            // 2. LLM 仍在生成中，则丢弃
                            // 3. TTS 仍在播放中（流式输出句间隙误触发 onAllDone），则丢弃
                            val idleMs = System.currentTimeMillis() - lastActivityTimeMs
                            val ttsIdle = ttsBridge?.isCurrentlySpeaking != true
                            if (idleMs >= delayMs * 3 / 4
                                && generatingJob?.isActive != true
                                && ttsIdle) {
                                sendProactiveAiMessage("followup")
                            }
                        }.also { mainHandler.postDelayed(it, delayMs) }
                    }
                }
            }
        }
        val resultCode = intent?.getIntExtra(EXTRA_RESULT_CODE, Activity.RESULT_CANCELED)
            ?: return START_NOT_STICKY
        val resultData: Intent? = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            intent.getParcelableExtra(EXTRA_RESULT_DATA, Intent::class.java)
        } else {
            @Suppress("DEPRECATION")
            intent.getParcelableExtra(EXTRA_RESULT_DATA)
        }
        if (resultData == null) return START_NOT_STICKY
        companionStartTime = System.currentTimeMillis()
        // 后台刷新位置/天气缓存（有权限时生效，无权限静默跳过）
        serviceScope.launch { ClientContextHelper.refreshLocationAndWeather(applicationContext) }
        // Android 10 (Q/API29) 起 startForeground 需要传入服务类型，否则后台麦克风访问会被系统拒绝。
        // FOREGROUND_SERVICE_TYPE_MICROPHONE 常量在 API 30 (R) 才加入，需分版本处理。
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            startForeground(
                NOTIFY_ID, buildNotification(),
                ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION or
                ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE
            )
        } else if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(
                NOTIFY_ID, buildNotification(),
                ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION
            )
        } else {
            startForeground(NOTIFY_ID, buildNotification())
        }
        val projManager = getSystemService(MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
        mediaProjection = projManager.getMediaProjection(resultCode, resultData)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            mediaProjection!!.registerCallback(object : MediaProjection.Callback() {
                override fun onStop() {
                    virtualDisplay?.release()
                    virtualDisplay = null
                    imageReader?.close()
                    imageReader = null
                    stopSelf()
                }
            }, mainHandler)
        }
        setupImageReader()
        showFloatingButton()
        // 旧 HTTP 路径，延迟 2s 发送问候
        mainHandler.postDelayed({ sendProactiveAiMessage("greeting") }, 2000L)
        if (isClassicMode) {
            // 聊天陪玩经典模式：预热 ASR WebSocket 连接——建立连接但不开麦克风，
            // 用户长按时直接跳过握手延迟开始录音，第一句话不会被吞。
            prewarmCallSession()
        }
        return START_STICKY
    }
    override fun onDestroy() {
        _isRunning.value = false
        _isAgentRunning.value = false
        _isAutoLooping.value = false
        isCallMode = false   // 防止 voiceBridge.release() 触发 onEnded 后再次重连
        callModeAsrEverStarted = false
        autoLoopJob?.cancel()
        autoLoopJob = null
        super.onDestroy()
        if (characterId.isNotBlank() && username.isNotBlank()) {
            val durationSec = ((System.currentTimeMillis() - companionStartTime) / 1000).toInt()
            val endBody = JSONObject().apply {
                put("character_id", characterId)
                put("personality_style", personalityStyle)
                put("username", username)
                put("duration_seconds", durationSec)
            }.toString()
            val endRequest = Request.Builder()
                .url("${apiBase.trimEnd('/')}/api/companion/end")
                .addHeader("X-Chat-Auth", authToken)
                .post(endBody.toRequestBody("application/json".toMediaTypeOrNull()))
                .build()
            Thread {
                try { httpClient.newCall(endRequest).execute().close() } catch (_: Exception) {}
            }.start()
        }
        prewarmBridge?.release()
        prewarmBridge = null
        voiceBridge?.release()
        voiceBridge = null
        ttsBridge?.release()
        ttsBridge = null
        recordingAnimator?.cancel()
        serviceScope.cancel()
        proactiveRunnable?.let { mainHandler.removeCallbacks(it) }
        autoHideRunnable?.let { mainHandler.removeCallbacks(it) }
        mainHandler.removeCallbacks(processTapsRunnable)
        longPressRunnable?.let { mainHandler.removeCallbacks(it) }
        mainHandler.post {
            try { floatingButtonView?.let { windowManager.removeView(it) } } catch (_: Exception) {}
            try { currentCardView?.let { windowManager.removeView(it) } } catch (_: Exception) {}
            try { chatDialogView?.let { windowManager.removeView(it) } } catch (_: Exception) {}
            try { identityChooserView?.let { windowManager.removeView(it) } } catch (_: Exception) {}
        }
        virtualDisplay?.release()
        mediaProjection?.stop()
        imageReader?.close()
    }
    override fun onBind(intent: Intent?): IBinder? = null
    // ── 截图准备 ──────────────────────────────────────────────────────────────
    internal fun setupImageReader() {
        imageReader?.close()
        virtualDisplay?.release()
        imageReader = ImageReader.newInstance(captureWidth, captureHeight, PixelFormat.RGBA_8888, 2)
        virtualDisplay = mediaProjection?.createVirtualDisplay(
            "CompanionCapture",
            captureWidth, captureHeight, screenDensity,
            DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
            imageReader!!.surface, null, null
        )
    }
    // ── 悬浮按钮 ──────────────────────────────────────────────────────────────
    internal fun showFloatingButton() {
        if (!Settings.canDrawOverlays(this)) return
        val size = dpToPx(56)
        val container = FrameLayout(this)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
            // 根因修复：缩放动画过程中按“整颗按钮”做圆形裁剪，避免子视图在过渡帧露出方形边缘
            container.outlineProvider = object : ViewOutlineProvider() {
                override fun getOutline(view: View, outline: Outline) {
                    outline.setOval(0, 0, view.width, view.height)
                }
            }
            container.clipToOutline = true
        }
        val defaultBg = GradientDrawable().apply {
            shape = GradientDrawable.OVAL
            setColor(Color.parseColor("#CC1A1A2E"))
            setStroke(dpToPx(2), Color.parseColor("#886C63E4"))
        }
        container.background = defaultBg
        val contentLayer = FrameLayout(this).apply {
            id = android.R.id.content
        }
        container.addView(
            contentLayer,
            FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT
            )
        )
        captureScaleView = contentLayer
        val label = TextView(this).apply {
            id = android.R.id.text1
            text = characterName.take(2).ifEmpty { "玩" }
            textSize = 14f
            setTextColor(Color.WHITE)
            gravity = Gravity.CENTER
        }
        contentLayer.addView(label, FrameLayout.LayoutParams(
            FrameLayout.LayoutParams.MATCH_PARENT,
            FrameLayout.LayoutParams.MATCH_PARENT
        ).apply { gravity = Gravity.CENTER })
        val avatarIv = ImageView(this).apply {
            id = android.R.id.icon
            scaleType = ImageView.ScaleType.CENTER_CROP
            visibility = View.INVISIBLE
            // 强制圆形裁剪，避免缩放/重绘时出现方形边缘
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
                outlineProvider = object : ViewOutlineProvider() {
                    override fun getOutline(view: View, outline: Outline) {
                        outline.setOval(0, 0, view.width, view.height)
                    }
                }
                clipToOutline = true
            }
        }
        contentLayer.addView(avatarIv, FrameLayout.LayoutParams(size, size))
        // 录音可视化光环层：始终覆盖在最上层，避免被头像遮挡导致“有录音但看不到动画”
        val haloDrawable = GradientDrawable().apply {
            shape = GradientDrawable.OVAL
            setColor(Color.TRANSPARENT)
            setStroke(dpToPx(2), Color.argb(0, 0xEE, 0x22, 0x22))
        }
        val haloView = View(this).apply {
            background = haloDrawable
            visibility = View.GONE
            alpha = 0f
            isClickable = false
            isFocusable = false
        }
        container.addView(
            haloView,
            FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT
            )
        )
        recordingHaloView = haloView
        recordingHaloDrawable = haloDrawable
        val params = WindowManager.LayoutParams(
            size, size,
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE,
            PixelFormat.TRANSLUCENT
        ).apply {
            gravity = Gravity.TOP or Gravity.END
            x = dpToPx(12)
            y = screenHeight / 3
        }

        if (avatarUrl.isNotBlank()) {
            serviceScope.launch {
                try {
                    val req = Request.Builder().url(avatarUrl).build()
                    val resp = httpClient.newCall(req).execute()
                    if (resp.isSuccessful) {
                        val bytes = resp.body?.bytes()
                        if (bytes != null) {
                            val raw = BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
                            if (raw != null) {
                                val circular = makeCircularBitmap(raw, size)
                                mainHandler.post {
                                    avatarIv.setImageBitmap(circular)
                                    avatarIv.visibility = View.VISIBLE
                                    label.visibility = View.GONE
                                    container.background = GradientDrawable().apply {
                                        shape = GradientDrawable.OVAL
                                        setColor(Color.TRANSPARENT)
                                        setStroke(dpToPx(2), Color.parseColor("#AA6C63E4"))
                                    }
                                }
                            }
                        }
                    }
                } catch (_: Exception) {}
            }
        }

        // ── 触摸手势：单击截图 / 双击对话 / 三击退出 / 长按1s震动开始语音(松手继续录) / 录音中单击停止 / 拖动移位 ──
        var downRawX = 0f; var downRawY = 0f
        var initParamX = 0; var initParamY = 0

        container.setOnTouchListener { _, event ->
            when (event.action) {
                MotionEvent.ACTION_DOWN -> {
                    downRawX = event.rawX; downRawY = event.rawY
                    initParamX = params.x; initParamY = params.y
                    btnHasMoved = false
                    longPressTriggered = false
                    // 非录音状态才安排长按（录音中单击处理见 ACTION_UP）
                    if (!isRecording) {
                        longPressRunnable?.let { mainHandler.removeCallbacks(it) }
                        longPressRunnable = Runnable {
                            if (!btnHasMoved) {
                                longPressTriggered = true
                                triggerVibration()
                                startVoiceInput()
                            }
                        }.also { mainHandler.postDelayed(it, LONG_PRESS_MS) }
                    }
                    true
                }
                MotionEvent.ACTION_MOVE -> {
                    val dx = (event.rawX - downRawX).toInt()
                    val dy = (event.rawY - downRawY).toInt()
                    if (abs(dx) > DRAG_THRESHOLD_PX || abs(dy) > DRAG_THRESHOLD_PX) {
                        btnHasMoved = true
                        longPressRunnable?.let { mainHandler.removeCallbacks(it) }
                        params.x = (initParamX - dx).coerceAtLeast(0)
                        params.y = (initParamY + dy).coerceIn(0, screenHeight - size)
                        try { windowManager.updateViewLayout(container, params) } catch (_: Exception) {}
                    }
                    true
                }
                MotionEvent.ACTION_UP -> {
                    longPressRunnable?.let { mainHandler.removeCallbacks(it) }
                    if (isRecording) {
                        if (longPressTriggered) {
                            // 刚通过长按触发了录音，此次松手不做任何操作，让用户自由说话后再单击停止
                            longPressTriggered = false
                        } else if (!btnHasMoved) {
                            // 录音中的单击 → 停止录音
                            if (isAgentMode) {
                                voiceBridge?.stop()
                            } else {
                                // Classic 通话模式：单击 = 挂断
                                exitCallMode()
                            }
                        }
                    } else if (!btnHasMoved) {
                        mainHandler.removeCallbacks(processTapsRunnable)
                        tapCount++
                        if (tapCount >= 3) {
                            tapCount = 0
                            stopSelf()
                        } else {
                            mainHandler.postDelayed(processTapsRunnable, TAP_WINDOW_MS)
                        }
                    }
                    true
                }
                else -> false
            }
        }

        windowManager.addView(container, params)
        floatingButtonView = container
    }

    internal fun makeCircularBitmap(src: Bitmap, sizePx: Int): Bitmap {
        val output = Bitmap.createBitmap(sizePx, sizePx, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(output)
        val paint = Paint(Paint.ANTI_ALIAS_FLAG)
        val scaled = Bitmap.createScaledBitmap(src, sizePx, sizePx, true)
        paint.shader = BitmapShader(scaled, Shader.TileMode.CLAMP, Shader.TileMode.CLAMP)
        val radius = sizePx / 2f
        canvas.drawRoundRect(RectF(0f, 0f, sizePx.toFloat(), sizePx.toFloat()), radius, radius, paint)
        if (scaled != src) scaled.recycle()
        return output
    }

    internal fun updateButtonState(loading: Boolean) {
        mainHandler.post {
            val lbl = floatingButtonView?.findViewById<TextView?>(android.R.id.text1) ?: return@post
            if (lbl.visibility == View.VISIBLE) {
                lbl.text = if (loading) "…" else characterName.take(2).ifEmpty { "玩" }
            }
            // 录音时只用描边动画体现状态，不改背景色（避免遮挡头像）
            if (!isRecording) {
                (floatingButtonView?.background as? GradientDrawable)?.setColor(
                    if (loading) Color.parseColor("#CC6C63E4") else Color.parseColor("#CC1A1A2E")
                )
            }
        }
    }

    /**
     * 语音模式光环动画。
     * @param fast true = 用户正在说话（快速脉冲），false = 等待中（慢速脉冲）
     */
    internal fun startRecordingAnimation(fast: Boolean = true) {
        recordingAnimator?.cancel()
        recordingHaloView?.visibility = View.VISIBLE
        recordingAnimator = ValueAnimator.ofFloat(0f, 1f).apply {
            duration = if (fast) 400L else 900L   // 说话时快，等待时慢
            repeatCount = ValueAnimator.INFINITE
            repeatMode = ValueAnimator.REVERSE
            addUpdateListener { anim ->
                val t = anim.animatedValue as Float
                // 说话时描边更粗、更亮；等待时细一些、暗一些
                val strokeMin = if (fast) dpToPx(3) else dpToPx(2)
                val strokeMax = if (fast) dpToPx(5) else dpToPx(3)
                val strokePx = strokeMin + ((strokeMax - strokeMin) * t).toInt()
                val alphaMin = if (fast) 0xBB else 0x66
                val alphaMax = if (fast) 0xFF else 0xAA
                val alpha = (alphaMin + ((alphaMax - alphaMin) * t).toInt()).coerceIn(0, 255)
                recordingHaloDrawable?.setStroke(strokePx, Color.argb(alpha, 0xEE, 0x22, 0x22))
                recordingHaloView?.alpha = if (fast) 0.6f + 0.3f * t else 0.3f + 0.3f * t
            }
            start()
        }
    }

    /** 结束录音动画，恢复默认描边 */
    internal fun stopRecordingAnimation() {
        recordingAnimator?.cancel()
        recordingAnimator = null
        mainHandler.post {
            recordingHaloDrawable?.setStroke(dpToPx(2), Color.argb(0, 0xEE, 0x22, 0x22))
            recordingHaloView?.alpha = 0f
            recordingHaloView?.visibility = View.GONE
        }
    }

    // ── 截图 → API → 弹幕/对话框 ─────────────────────────────────────────────

    internal fun triggerCapture() {
        if (isCapturing) return
        isCapturing = true

        val btn = floatingButtonView ?: run { isCapturing = false; return }
        val animTarget = captureScaleView ?: btn

        // ① 快速缩小到 20%（110ms，加速插值器 → 下压打击感）
        animTarget.animate()
            .scaleX(0.2f).scaleY(0.2f)
            .setDuration(110)
            .setInterpolator(AccelerateInterpolator(1.8f))
            .withLayer()
            .withEndAction {
                // ② 按钮已缩到极小，此时截图几乎不遮挡内容
                serviceScope.launch {
                    val bitmap = captureScreen()

                    // ③ 拿到截图后立即弹回（不等 API 返回，先还原按钮）
                    mainHandler.post {
                        animTarget.animate()
                            .scaleX(1f).scaleY(1f)
                            .setDuration(220)
                            // 根因修复：回弹阶段禁用 overshoot，避免 scale > 1 触发方形边缘瑕疵
                            .setInterpolator(DecelerateInterpolator(1.5f))
                            .withLayer()
                            .start()
                    }

                    // ④ 调 API、展示结果
                    try {
                        if (isAgentMode) {
                            // 操作陪玩：旧 HTTP 路径
                            if (bitmap != null) {
                                val reaction = sendToBackend(bitmap)
                                if (!reaction.isNullOrBlank()) {
                                    speakIfNotRecording(reaction)
                                    withContext(Dispatchers.Main) {
                                        conversationHistory.add(CompanionMessage(isUser = false, text = reaction))
                                        if (chatDialogView != null) {
                                            appendMessageToDialog(isUser = false, text = reaction)
                                        } else {
                                            showCompanionCard(reaction)
                                        }
                                    }
                                }
                            }
                        } else {
                            // 聊天陪玩经典模式：旧 frame 端点 + TTS
                            if (bitmap != null) {
                                val reaction = sendToBackend(bitmap)
                                if (!reaction.isNullOrBlank()) {
                                    speakIfNotRecording(reaction)
                                    withContext(Dispatchers.Main) {
                                        conversationHistory.add(CompanionMessage(isUser = false, text = reaction))
                                        if (chatDialogView != null) appendMessageToDialog(isUser = false, text = reaction)
                                        else showCompanionCard(reaction)
                                    }
                                }
                            }
                        }
                    } catch (e: Exception) {
                        Log.w(TAG, "Capture cycle failed: ${e.message}")
                    } finally {
                        isCapturing = false
                    }
                }
            }
            .start()
    }

    internal fun captureScreen(): Bitmap? {
        return try {
            // 动画缩小已提供足够等待时间；此处只需短暂等待 VirtualDisplay 刷新缓冲
            Thread.sleep(30)
            val image: Image = imageReader?.acquireLatestImage() ?: return null
            val plane = image.planes[0]
            val rowStride = plane.rowStride
            val pixelStride = plane.pixelStride
            val bmp = Bitmap.createBitmap(rowStride / pixelStride, captureHeight, Bitmap.Config.ARGB_8888)
            bmp.copyPixelsFromBuffer(plane.buffer)
            image.close()
            if (bmp.width > captureWidth) {
                val cropped = Bitmap.createBitmap(bmp, 0, 0, captureWidth, captureHeight)
                bmp.recycle()
                cropped
            } else bmp
        } catch (e: Exception) {
            Log.w(TAG, "captureScreen failed: ${e.message}")
            null
        }
    }

    internal suspend fun sendToBackend(bitmap: Bitmap): String? = withContext(Dispatchers.IO) {
        try {
            val baos = ByteArrayOutputStream()
            bitmap.compress(Bitmap.CompressFormat.JPEG, 55, baos)
            bitmap.recycle()
            val b64 = Base64.encodeToString(baos.toByteArray(), Base64.NO_WRAP)
            val maxChars = AppPreferences(applicationContext).companionCardMaxChars
            val ctx = ClientContextHelper.buildContext(applicationContext)
            val bodyJson = JSONObject().apply {
                put("image_base64", b64)
                put("character_id", characterId)
                put("username", username)
                put("max_chars", maxChars)
                put("client_context", JSONObject().apply {
                    ctx.timeIso?.let { put("time_iso", it) }
                    ctx.deviceModel?.let { put("device_model", it) }
                    ctx.osVersion?.let { put("os_version", it) }
                    ctx.battery?.let { put("battery", it) }
                    ctx.network?.let { put("network", it) }
                    ctx.locationName?.let { put("location_name", it) }
                    ctx.weatherDesc?.let { put("weather_desc", it) }
                    ctx.temperature?.let { put("temperature", it) }
                    ctx.osFlavor?.let { put("os_flavor", it) }
                    ctx.navMode?.let { put("nav_mode", it) }
                })
            }.toString()
            val request = Request.Builder()
                .url("${apiBase.trimEnd('/')}/api/companion/frame")
                .addHeader("X-Chat-Auth", authToken)
                .post(bodyJson.toRequestBody("application/json".toMediaTypeOrNull()))
                .build()
            val resp = httpClient.newCall(request).execute()
            if (!resp.isSuccessful) return@withContext null
            val json = JSONObject(resp.body?.string() ?: return@withContext null)
            if (json.getString("status") == "ok") json.optString("reaction") else null
        } catch (e: Exception) {
            Log.w(TAG, "sendToBackend failed: ${e.message}")
            null
        }
    }

    // ── 文字/语音 → 截图 + API → 对话框 ─────────────────────────────────────

    internal fun sendUserText(text: String, openDialogIfNeeded: Boolean = true) {
        // 如果 AI 还在生成上一条回复，取消它并将两次用户输入合并后重新生成
        if (generatingJob?.isActive == true) {
            generatingJob!!.cancel()
            generatingJob = null
            currentStreamingCall?.cancel()
            currentStreamingCall = null
            // 从历史中取出上一条用户消息，与本次合并
            val prevText = if (conversationHistory.lastOrNull()?.isUser == true)
                conversationHistory.removeLast().text else ""
            val combinedText = if (prevText.isNotEmpty()) "$prevText $text" else text
            // 主线程：更新用户气泡文字，移除未完成的流式 AI 气泡
            mainHandler.post {
                pendingUserBubbleTv?.text = combinedText
                streamingBubbleRow?.let { row -> (row.parent as? ViewGroup)?.removeView(row) }
                streamingBubbleTv = null
                streamingBubbleRow = null
            }
            ttsBridge?.stop()
            // 以合并文字重新进入正常生成流程（此时 generatingJob == null，不会再次触发取消逻辑）
            conversationHistory.add(CompanionMessage(isUser = true, text = combinedText))
            generatingJob = serviceScope.launch {
                val bitmap = captureScreen()
                val reaction = sendTextToBackendStreaming(combinedText, bitmap)
                withContext(Dispatchers.Main) {
                    streamingBubbleTv = null
                    streamingBubbleRow = null
                    generatingJob = null
                    pendingUserBubbleTv = null
                    if (!reaction.isNullOrBlank()) {
                        conversationHistory.add(CompanionMessage(isUser = false, text = reaction))
                        // 通话模式 + 语音关闭：TTS 不播，在此一次性显示全文（10s 消失）
                        val voiceOn = isCallMode && AppPreferences(applicationContext).companionVoiceEnabled
                        if (chatDialogView == null && !voiceOn) showOrUpdateCompanionCardOnMain(reaction)
                    }
                }
            }
            return
        }

        // 用户主动说话：取消主动发言计时器，重置本轮已尝试标记，清零连续计数
        lastActivityTimeMs = System.currentTimeMillis()
        proactiveRunnable?.let { mainHandler.removeCallbacks(it) }
        proactiveRunnable = null
        proactiveAttempted = false
        proactiveConsecutiveCount = 0

        // 操作陪玩模式：用户输入即为新任务描述，触发自动循环
        // onFinal 回调在 OkHttp 线程，所有 UI 操作必须 post 到主线程
        if (isAgentMode) {
            ttsBridge?.stop()
            mainHandler.post {
                agentLoopTask = text
                conversationHistory.add(CompanionMessage(isUser = true, text = text))
                if (chatDialogView != null) appendMessageToDialog(isUser = true, text = text, animate = true)
                else if (openDialogIfNeeded) openChatDialog()
                startAgentLoop(text)
            }
            return
        }

        conversationHistory.add(CompanionMessage(isUser = true, text = text))
        // 语音输入场景不自动打开对话框；文字输入仍保持原交互。
        if (chatDialogView == null) {
            if (openDialogIfNeeded) {
                // 根因修复：当对话框尚未打开时，openChatDialog() 会完整渲染历史（含刚加入的这条消息），
                // 不能再 append 一次，否则会出现「同一条用户消息重复两次」。
                openChatDialog()
            }
        } else {
            appendMessageToDialog(isUser = true, text = text, animate = true)
        }

        // 聊天陪玩经典模式：模型大厅 LLM + TTS
        // 优先使用 onPartial 阶段预截的图，避免在关键路径上等待截图+压缩
        val readyBitmap = preCapturedBitmap.also { preCapturedBitmap = null }
        generatingJob = serviceScope.launch {
            val bitmap = readyBitmap ?: captureScreen()
            val reaction = sendTextToBackendStreaming(text, bitmap)
            withContext(Dispatchers.Main) {
                streamingBubbleTv = null
                streamingBubbleRow = null
                generatingJob = null
                pendingUserBubbleTv = null
                if (!reaction.isNullOrBlank()) {
                    conversationHistory.add(CompanionMessage(isUser = false, text = reaction))
                    // 通话模式 + 语音关闭：TTS 不播，在此一次性显示全文（10s 消失）
                    val voiceOn = isCallMode && AppPreferences(applicationContext).companionVoiceEnabled
                    if (chatDialogView == null && !voiceOn) showOrUpdateCompanionCardOnMain(reaction)
                }
            }
        }
    }


    /**
     * 首 token 到达时调用：在对话气泡列表末尾添加助手气泡，返回 TextView 供后续流式更新。
     * 必须在主线程调用。initialText 为首个 token 的内容。
     */
    internal fun addStreamingAssistantBubble(container: LinearLayout, initialText: String): TextView {
        val bubbleBg = GradientDrawable().apply {
            cornerRadius = dpToPx(14).toFloat()
            setColor(Color.parseColor("#44FFFFFF"))
        }
        val tv = TextView(this).apply {
            text = initialText
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
            gravity = Gravity.START
            layoutParams = rowLp
            alpha = 0f
        }
        row.addView(tv)
        container.addView(row)
        streamingBubbleRow = row  // 保存容器行，取消时整行移除
        row.animate().alpha(1f).setDuration(140).setInterpolator(LinearInterpolator()).start()
        scrollToBottom()
        return tv
    }

    /**
     * 流式版本：通过 /api/companion/stream SSE 端点获取 AI 回复。
     * 每收到 delta 即更新对话气泡和弹幕卡片；遇句末标点则立即触发 TTS。
     * bitmap 会在压缩完成后立即 recycle。
     */
    internal suspend fun sendTextToBackendStreaming(
        text: String,
        bitmap: Bitmap? = null,
        proactiveHint: String = "",
        stepHistory: List<String> = emptyList(),
        suppressReaction: Boolean = false,
        uiElements: List<String> = emptyList(),
    ): String? =
        withContext(Dispatchers.IO) {
            try {
                val maxChars = AppPreferences(applicationContext).companionCardMaxChars
                val b64 = bitmap?.let { bmp ->
                    val baos = ByteArrayOutputStream()
                    val jpegQuality = if (isAgentMode) 65 else 80
                    // classic 陪玩：短边限制 720px，保证文字清晰可读；quality=80 兼顾画质与传输大小
                    val minSide = 720
                    val toCompress = if (!isAgentMode && minOf(bmp.width, bmp.height) > minSide) {
                        val scale = minSide.toFloat() / minOf(bmp.width, bmp.height)
                        val scaled = Bitmap.createScaledBitmap(
                            bmp, (bmp.width * scale).toInt(), (bmp.height * scale).toInt(), true
                        )
                        bmp.recycle()
                        scaled
                    } else bmp
                    toCompress.compress(Bitmap.CompressFormat.JPEG, jpegQuality, baos)
                    toCompress.recycle()
                    Base64.encodeToString(baos.toByteArray(), Base64.NO_WRAP)
                } ?: ""
                val ctx = ClientContextHelper.buildContext(applicationContext)
                val bodyJson = JSONObject().apply {
                    put("image_base64", b64)
                    put("character_id", characterId)
                    put("personality_style", personalityStyle)
                    put("username", username)
                    put("max_chars", maxChars)
                    put("user_text", text)
                    if (proactiveHint.isNotEmpty()) put("proactive_hint", proactiveHint)
                    if (stepHistory.isNotEmpty()) put("agent_step_history", org.json.JSONArray(stepHistory))
                    if (suppressReaction) put("skip_reaction", true)
                    if (uiElements.isNotEmpty()) put("ui_elements", org.json.JSONArray(uiElements))
                    // Plan-and-Execute：注入当前步骤上下文
                    if (isAgentMode && agentPlan.isNotEmpty()) {
                        val currentStep = agentPlan.getOrNull(agentPlanStepIndex) ?: ""
                        if (currentStep.isNotEmpty()) {
                            put("current_plan_step", currentStep)
                            put("plan_total", agentPlan.size)
                            put("plan_step_index", agentPlanStepIndex)
                        }
                    }
                    put("client_context", JSONObject().apply {
                        ctx.timeIso?.let { put("time_iso", it) }
                        ctx.deviceModel?.let { put("device_model", it) }
                        ctx.osVersion?.let { put("os_version", it) }
                        ctx.battery?.let { put("battery", it) }
                        ctx.network?.let { put("network", it) }
                        ctx.locationName?.let { put("location_name", it) }
                        ctx.weatherDesc?.let { put("weather_desc", it) }
                        ctx.temperature?.let { put("temperature", it) }
                        ctx.osFlavor?.let { put("os_flavor", it) }
                        ctx.navMode?.let { put("nav_mode", it) }
                    })
                }.toString()
                // 操作陪玩模式走 agent_action 端点，普通聊天陪玩走 stream 端点
                val endpoint = if (isAgentMode) "agent_action" else "stream"
                val request = Request.Builder()
                    .url("${apiBase.trimEnd('/')}/api/companion/$endpoint")
                    .addHeader("X-Chat-Auth", authToken)
                    .post(bodyJson.toRequestBody("application/json".toMediaTypeOrNull()))
                    .build()

                val call = httpClient.newCall(request)
                currentStreamingCall = call
                val response = call.execute()
                currentStreamingCall = null
                if (!response.isSuccessful) return@withContext null
                val source = response.body?.source() ?: return@withContext null

                val fullBuf = StringBuilder()
                val sentenceBuf = StringBuilder()
                val sentenceEnders = charArrayOf('。', '！', '？', '!', '?', '…')
                var firstToken = true
                var lastSpokenText = ""   // 去重：避免 done 的 remaining 与已播句子重复
                // 通话模式 + 语音开启：卡片由 TTS onSentenceStarted/onAllDone 回调驱动，不做流式实时更新
                // 通话模式 + 语音关闭：TTS 不播，走流式更新 + 10s 定时器，保证用户能看到文字
                val callModeVoice = isCallMode && AppPreferences(applicationContext).companionVoiceEnabled

                while (!source.exhausted()) {
                    val line = source.readUtf8Line() ?: break
                    if (!line.startsWith("data: ")) continue
                    val data = line.removePrefix("data: ").trim()
                    if (data.isEmpty()) continue

                    try {
                        val json = JSONObject(data)
                        if (json.optBoolean("done")) {
                            // 播报剩余未推送的句子（未以标点结尾的尾段）
                            val remaining = sentenceBuf.toString().trim()
                            // 若 remaining 与上一句已播内容相同（去除尾部标点后），则跳过，避免重复播报
                            val remainingCore = remaining.trimEnd(*sentenceEnders)
                            val lastCore = lastSpokenText.trimEnd(*sentenceEnders)
                            if (remaining.isNotEmpty() && remainingCore != lastCore) {
                                speakIfNotRecording(remaining)
                            }
                            // 操作陪玩：执行 AI 下发的触控操作指令
                            if (isAgentMode) {
                                json.optJSONObject("action")?.let { action ->
                                    executeAgentAction(action)
                                }
                            }
                            val reaction = json.optString("reaction").ifEmpty { fullBuf.toString() }
                            return@withContext reaction.ifEmpty { null }
                        }
                        if (json.has("error")) return@withContext null

                        val delta = json.optString("d")
                        if (delta.isNotEmpty()) {
                            fullBuf.append(delta)
                            sentenceBuf.append(delta)
                            val accumulated = fullBuf.toString()

                            if (firstToken) {
                                firstToken = false
                                // 首 token：对话框创建气泡，弹幕卡片更新内容
                                // agent 模式：若卡片已由 showAgentLoopStatusCard 创建则更新 contentTv；
                                // 若卡片不存在则跳过（避免 windowManager.addView 触发窗口树重建，
                                // 导致紧随其后的 executeAgentAction → doInputText 看到 rootInActiveWindow == null）
                                // 通话模式 + 语音开启：卡片由 TTS 回调驱动，跳过流式实时更新
                                // 通话模式 + 语音关闭：允许流式更新（用户需要看字幕）
                                mainHandler.post {
                                    if (chatDialogView != null) {
                                        chatMessagesLayout?.let { container ->
                                            streamingBubbleTv = addStreamingAssistantBubble(container, accumulated)
                                        }
                                    } else if (!isAgentMode && !callModeVoice || currentCardView != null && !callModeVoice) {
                                        showOrUpdateCompanionCardOnMain(accumulated)
                                    }
                                }
                            } else {
                                // 后续 token：更新气泡或卡片文字
                                // 通话模式 + 语音开启：卡片由 TTS 回调驱动，跳过流式实时更新
                                mainHandler.post {
                                    if (chatDialogView != null) {
                                        streamingBubbleTv?.text = accumulated
                                        scrollToBottom()
                                    } else if (!isAgentMode && !callModeVoice || currentCardView != null && !callModeVoice) {
                                        showOrUpdateCompanionCardOnMain(accumulated)
                                    }
                                }
                            }

                            // 遇句末标点 → TTS 播报当前句
                            if (delta.any { c -> c in sentenceEnders }) {
                                val sentence = sentenceBuf.toString().trim()
                                sentenceBuf.clear()
                                // 过滤纯标点/空白句（如"！！"被分成"当然听得到啦！"+"！"，后者无需播报）
                                val coreLen = sentence.count { c -> c !in sentenceEnders && !c.isWhitespace() }
                                if (coreLen == 0) {
                                    // 纯标点，丢弃
                                } else if (coreLen < 6) {
                                    // 有效字符不足6个（如 "Jason！"、"好！"）：放回缓冲区和下一句拼合，
                                    // 避免 TTS 合成极短音频（< 0.3s）难以被感知
                                    sentenceBuf.insert(0, sentence)
                                } else {
                                    lastSpokenText = sentence
                                    speakIfNotRecording(sentence)
                                }
                            }
                        }
                    } catch (_: Exception) {}
                }
                fullBuf.toString().ifEmpty { null }
            } catch (e: Exception) {
                Log.w(TAG, "sendTextToBackendStreaming failed: ${e.message}")
                null
            }
        }

    /**
     * 执行 AI 下发的触控操作指令（操作陪玩模式专用）。
     * 指令格式（JSON）：
     *   tap:   {"type":"tap", "x":0.5, "y":0.3}  —— 归一化坐标 [0,1]
     *   swipe: {"type":"swipe","from_x":0.5,"from_y":0.8,"to_x":0.5,"to_y":0.2,"duration_ms":400}
     *   none:  {"type":"none"}  —— 仅聊天，无需操作
     * 坐标为归一化值，执行前乘以屏幕真实宽高。
     */
    internal fun speakIfNotRecording(text: String) {
        if (!AppPreferences(applicationContext).companionVoiceEnabled) return
        // 通话模式下用户正在说话时，丢弃本次 TTS 请求，避免 AI 抢话
        if (isUserSpeaking) return
        ttsBridge?.speak(text)
    }

    /**
     * 主动发言：AI 不等用户输入，自主说一句话（问候或延续对话）。
     * hint = "greeting"（开场问候）/ "followup"（对话间隙主动延续）。
     * 若当前正在生成则跳过（不打断用户已发起的对话）。
     */
    internal fun sendProactiveAiMessage(hint: String) {
        // 服务已销毁时（三击/通知栏停止）不再发起任何主动消息
        if (!_isRunning.value) return

        // 操作陪玩 或 聊天陪玩经典模式：旧 HTTP 路径
        if (generatingJob?.isActive == true) return
        generatingJob = serviceScope.launch {
            val bitmap = if (hint == "greeting") null else captureScreen()
            val reaction = sendTextToBackendStreaming("", bitmap, proactiveHint = hint)
            withContext(Dispatchers.Main) {
                streamingBubbleTv = null
                streamingBubbleRow = null
                generatingJob = null
                pendingUserBubbleTv = null
                if (!reaction.isNullOrBlank()) {
                    conversationHistory.add(CompanionMessage(isUser = false, text = reaction))
                    if (chatDialogView == null) showOrUpdateCompanionCardOnMain(reaction)
                    proactiveAttempted = true
                    proactiveConsecutiveCount++  // 累计连续主动发言次数，用户说话时清零
                }
            }
        }
    }

    // ── 语音输入 ──────────────────────────────────────────────────────────────

    internal fun startVoiceInput() {
        isRecording = true
        // 清除长按前可能积累的点击计数，避免录音结束后意外触发截图/对话
        mainHandler.removeCallbacks(processTapsRunnable)
        tapCount = 0
        startRecordingAnimation(fast = false)  // 进入语音模式：慢速等待脉冲，说话后切快速

        if (checkSelfPermission(android.Manifest.permission.RECORD_AUDIO)
            != android.content.pm.PackageManager.PERMISSION_GRANTED
        ) {
            Log.w(TAG, "RECORD_AUDIO 权限未授予")
            abortVoiceInput()
            return
        }

        if (isClassicMode) {
            // 聊天陪玩经典模式：进入持续通话模式（VAD 驱动多轮对话，类似视频电话）
            isCallMode = true
            startCallSession()
            return
        }

        // 操作陪玩模式：使用 DashScope Qwen-ASR-Realtime，单次识别
        val wsUrl = buildSpeechWsUrl() ?: run {
            Log.w(TAG, "无法构建语音识别 WS URL")
            abortVoiceInput()
            return
        }
        voiceBridge?.release()
        preCapturedBitmap?.recycle()
        preCapturedBitmap = null
        voiceBridge = BackendStreamingVoiceBridge(object : BackendStreamingVoiceBridge.Callback {
            override fun onStarted() {}
            override fun onPartial(text: String) {
                ttsBridge?.stop()
                if (preCapturedBitmap == null) {
                    serviceScope.launch(Dispatchers.IO) {
                        if (preCapturedBitmap == null) preCapturedBitmap = captureScreen()
                    }
                }
            }
            override fun onFinal(text: String) {
                if (text.isNotBlank()) mainHandler.post { sendUserText(text.trim(), openDialogIfNeeded = false) }
            }
            override fun onError(code: String, message: String?) {
                Log.w(TAG, "VoiceBridge 错误: $code $message")
            }
            override fun onEnded(reason: String, text: String?) {
                preCapturedBitmap?.recycle()
                preCapturedBitmap = null
                mainHandler.post {
                    isRecording = false
                    stopRecordingAnimation()
                    updateButtonState(false)
                }
            }
        })
        voiceBridge?.start(wsUrl, null)
    }

    /**
     * Classic 通话模式：建立 ASR 会话，持续监听麦克风。
     * - VAD（400ms 静音）自动切句，每句触发 onFinal → LLM + TTS
     * - 用户说话（onPartial）：停止 TTS + 切快速脉冲 + 后台预截图
     * - 每句处理完后：切慢速脉冲，继续等待下一句
     * - ASR 意外断开（网络抖动）：500ms 后自动重连
     * - 单击悬浮按钮挂断：调用 exitCallMode()
     */
    /**
     * 通话模式 ASR 回调（pre-warm 和正式通话共用同一套逻辑）。
     * 回调中所有字段均为 CompanionService 实例变量，创建时机不影响行为。
     * pre-warm 阶段 BackendStreamingVoiceBridge 内部会压制 onStarted，
     * 直到用户长按触发 activateRecording() 后才真正开麦 + 触发此回调。
     */
    internal fun makeCallModeCallback() = object : BackendStreamingVoiceBridge.Callback {
        override fun onStarted() {
            callModeAsrEverStarted = true
            // ASR 就绪后才渲染慢速脉冲（避免连接期间就看到光环）
            mainHandler.post { if (isCallMode) startRecordingAnimation(fast = false) }
        }

        override fun onPartial(text: String) {
            // 用户开口：停止 TTS + 强制关闭流式 HTTP 请求 + 取消 LLM 协程 + 清理未完成气泡 + 切快速脉冲
            isUserSpeaking = true
            ttsBridge?.stop()
            // 关键：cancel OkHttp Call 使阻塞的 readUtf8Line() 立即抛 IOException，
            // 防止旧 SSE 循环在 onFinal 后继续把剩余句子压入 TTS 队列
            currentStreamingCall?.cancel()
            currentStreamingCall = null

            val activeJob = generatingJob
            if (activeJob?.isActive == true) {
                activeJob.cancel()
                generatingJob = null
                mainHandler.post {
                    streamingBubbleRow?.let { row ->
                        (row.parent as? ViewGroup)?.removeView(row)
                    }
                    streamingBubbleTv = null
                    streamingBubbleRow = null
                    if (conversationHistory.lastOrNull()?.isUser == true) {
                        conversationHistory.removeLastOrNull()
                    }
                }
            }

            mainHandler.post {
                if (isCallMode) {
                    startRecordingAnimation(fast = true)
                    dismissCard()
                }
            }
            if (preCapturedBitmap == null) {
                serviceScope.launch(Dispatchers.IO) {
                    if (preCapturedBitmap == null) preCapturedBitmap = captureScreen()
                }
            }
        }

        override fun onFinal(text: String) {
            // 用户说完：解除"正在说话"标志，允许 AI 新回复的 TTS 正常播放
            isUserSpeaking = false
            // 在主线程串行化，防止 DashScope 重复推送 final 时竞态
            mainHandler.post {
                if (isCallMode) startRecordingAnimation(fast = false)
                if (text.isNotBlank()) sendUserText(text.trim(), openDialogIfNeeded = false)
            }
        }

        override fun onError(code: String, message: String?) {
            Log.w(TAG, "[通话模式] VoiceBridge 错误: $code $message")
            val fatal = code == "not_configured" || code == "dashscope_connect_failed"
                || code == "dashscope_session_aborted"
            if (fatal && isCallMode) {
                mainHandler.post {
                    voiceBridge?.release()
                    voiceBridge = null
                    exitCallMode()
                }
            }
        }

        override fun onEnded(reason: String, text: String?) {
            isUserSpeaking = false
            preCapturedBitmap?.recycle()
            preCapturedBitmap = null
            // 仅在已成功建立 ASR 会话后，才把意外 end 视为网络抖动并重连；从未 started 的 end 多为握手失败，避免重连风暴。
            if (isCallMode && _isRunning.value && callModeAsrEverStarted) {
                Log.i(TAG, "[通话模式] ASR 会话结束 reason=$reason，500ms 后自动重连")
                callModeAsrEverStarted = false
                mainHandler.postDelayed({ startCallSession() }, 500L)
            } else {
                callModeAsrEverStarted = false
                mainHandler.post {
                    isRecording = false
                    stopRecordingAnimation()
                    updateButtonState(false)
                }
            }
        }
    }

    /**
     * 服务启动时（isClassicMode）提前建立 ASR WebSocket 握手，但不开麦克风。
     * 使用真正的通话回调：预热模式下 onStarted 被内部压制，
     * 用户长按调用 activateRecording() 后立即触发 onStarted + 开录。
     */
    internal fun prewarmCallSession() {
        val wsUrl = buildSpeechWsUrl() ?: return
        prewarmBridge?.release()
        prewarmBridge = BackendStreamingVoiceBridge(makeCallModeCallback()).also {
            it.prewarm(wsUrl, null)
        }
        Log.i(TAG, "[Classic] ASR 预热连接已启动")
    }

    /**
     * Classic 通话会话主入口：
     * - 若预热连接已就绪（握手完成）：直接激活录音，零额外延迟
     * - 否则（预热尚未完成或已超时）：正常建立新连接
     * - 自动重连时亦走此函数，每次重连后同步启动下一轮预热供后续使用
     */
    internal fun startCallSession() {
        if (!isCallMode || !_isRunning.value) return
        callModeAsrEverStarted = false
        val wsUrl = buildSpeechWsUrl() ?: run { exitCallMode(); return }
        preCapturedBitmap?.recycle()
        preCapturedBitmap = null

        val prewarmed = prewarmBridge?.takeIf { it.isPrewarmed() }
        prewarmBridge = null

        if (prewarmed != null) {
            // 握手已完成：接管预热连接，立即开录，onStarted 在 activateRecording() 内触发
            Log.i(TAG, "[Classic] 复用预热连接，零延迟开录")
            voiceBridge?.release()
            voiceBridge = prewarmed
            prewarmed.activateRecording()
        } else {
            // 预热未完成或已失效：正常建立新连接
            voiceBridge?.release()
            voiceBridge = BackendStreamingVoiceBridge(makeCallModeCallback()).also {
                it.start(wsUrl, null)
            }
            if (prewarmBridge == null) {
                // 仍未完成的旧预热（连接中途超时），取消即可
            }
        }
    }

    /**
     * 退出 classic 通话模式（挂断）。
     * 停止 ASR、TTS、进行中的 LLM 生成和录音动画，清理预截图缓存。
     */
    internal fun exitCallMode() {
        isCallMode = false
        callModeAsrEverStarted = false
        isUserSpeaking = false
        ttsBridge?.stop()
        generatingJob?.cancel()
        generatingJob = null
        currentStreamingCall?.cancel()
        currentStreamingCall = null
        voiceBridge?.stop()
        preCapturedBitmap?.recycle()
        preCapturedBitmap = null
        mainHandler.post {
            isRecording = false
            stopRecordingAnimation()
            updateButtonState(false)
        }
        Log.i(TAG, "[通话模式] 已挂断")
    }

    /** 陪玩语音：走阿里云 NLS 实时 ASR（与后端已配置的 NLS Token 一致）；DashScope ASR 需单独 Key，易未就绪。 */
    internal fun buildSpeechWsUrl(): String? = try {
        val base = apiBase.trimEnd('/')
        val url = java.net.URL(base)
        val scheme = if (url.protocol == "https") "wss" else "ws"
        val portPart = if (url.port > 0 && url.port != 80 && url.port != 443) ":${url.port}" else ""
        "$scheme://${url.host}$portPart/ws/speech/aliyun"
    } catch (_: Exception) { null }

    /** 语音输入无法启动时，短暂闪烁动画后恢复正常状态 */
    internal fun abortVoiceInput() {
        mainHandler.postDelayed({
            isRecording = false
            stopRecordingAnimation()
            updateButtonState(false)
        }, 600)
    }

    /** 短震动反馈（60ms），用于长按开始录音时提示用户 */
    @Suppress("DEPRECATION")
    internal fun triggerVibration() {
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                val v = getSystemService(VIBRATOR_SERVICE) as? Vibrator
                v?.vibrate(VibrationEffect.createOneShot(60, VibrationEffect.DEFAULT_AMPLITUDE))
            } else {
                val v = getSystemService(VIBRATOR_SERVICE) as? Vibrator
                v?.vibrate(60)
            }
        } catch (_: Exception) {}
    }

    // ── 弹幕卡片 ─────────────────────────────────────────────────────────────

    /** 从任意线程安全调用：将卡片显示/更新任务 post 到主线程。 */
    // ── 工具 ─────────────────────────────────────────────────────────────────

    internal fun dpToPx(dp: Int): Int =
        (dp * resources.displayMetrics.density + 0.5f).toInt()
}
