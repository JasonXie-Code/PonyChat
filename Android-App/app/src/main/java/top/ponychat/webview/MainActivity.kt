package top.ponychat.webview

import android.Manifest
import android.app.AlertDialog
import android.app.NotificationManager
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ActivityInfo
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.HandlerThread
import android.provider.Settings
import android.util.Log
import android.view.FrameMetrics
import android.view.Window
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import top.ponychat.webview.data.api.ProactiveNavTarget
import top.ponychat.webview.util.ClientContextHelper
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.core.content.ContextCompat
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.key
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.compositionLocalOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.zIndex
import androidx.compose.ui.unit.dp
import top.ponychat.webview.BuildConfig
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.device.CompanionRuntimeClient
import top.ponychat.webview.device.CompanionRuntimeState
import top.ponychat.webview.device.LocalCompanionRuntimeState
import top.ponychat.webview.device.LocalCompanionRuntimeReady
import top.ponychat.webview.device.LocalDeviceExperience
import top.ponychat.webview.device.shouldUseDeviceExperience
import top.ponychat.webview.device.statusText
import top.ponychat.webview.util.NotificationTrace
import top.ponychat.webview.ui.common.PonyPromptBubble
import top.ponychat.webview.ui.common.SystemNavigationBarColorEffect
import top.ponychat.webview.ui.theme.PonyChatTheme

val CustomToast = compositionLocalOf<SnackbarHostState> { error("No SnackbarHostState provided") }

open class MainActivity : ComponentActivity() {

    private lateinit var prefs: AppPreferences
    private val companionRuntimeClient by lazy { CompanionRuntimeClient(applicationContext) }

    companion object {
        // 120Hz 帧预算 = 1_000_000_000 / 120 = 8_333_333 ns
        private const val FRAME_BUDGET_NS = 8_333_333L
        // 超过 2 倍预算（≈ 16.7ms）才记 WARN，减少日志噪音
        private const val FRAME_WARN_NS   = FRAME_BUDGET_NS * 2
        // 超过 4 倍预算（≈ 33ms）记 ERROR，属于严重卡顿
        private const val FRAME_ERROR_NS  = FRAME_BUDGET_NS * 4
        private const val TAG_FRAME = "PERF_FRAME"
    }

    private val frameMetricsThread by lazy { HandlerThread("FrameMetrics").also { it.start() } }
    private val frameMetricsHandler by lazy { Handler(frameMetricsThread.looper) }
    private var frameMetricsAdded = false
    private val frameMetricsListener by lazy {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
            Window.OnFrameMetricsAvailableListener { _, frameMetrics, _ ->
                val total   = frameMetrics.getMetric(FrameMetrics.TOTAL_DURATION)
                if (total < FRAME_WARN_NS) return@OnFrameMetricsAvailableListener

                val input   = frameMetrics.getMetric(FrameMetrics.INPUT_HANDLING_DURATION)
                val anim    = frameMetrics.getMetric(FrameMetrics.ANIMATION_DURATION)
                val layout  = frameMetrics.getMetric(FrameMetrics.LAYOUT_MEASURE_DURATION)
                val draw    = frameMetrics.getMetric(FrameMetrics.DRAW_DURATION)
                val sync    = frameMetrics.getMetric(FrameMetrics.SYNC_DURATION)
                val gpu     = frameMetrics.getMetric(FrameMetrics.COMMAND_ISSUE_DURATION)
                val swap    = frameMetrics.getMetric(FrameMetrics.SWAP_BUFFERS_DURATION)
                val delay   = frameMetrics.getMetric(FrameMetrics.UNKNOWN_DELAY_DURATION)

                // 找出耗时最长的阶段，给出精准诊断
                val phases = mapOf(
                    "input"  to input,
                    "anim"   to anim,
                    "layout" to layout,   // Compose recomposition + measure/layout 都在这里
                    "draw"   to draw,     // Compose draw phase（graphicsLayer 等）
                    "sync"   to sync,
                    "gpu"    to gpu,
                    "swap"   to swap,
                    "delay"  to delay
                )
                val worst = phases.maxByOrNull { it.value }
                val diagnosis = when {
                    layout > FRAME_BUDGET_NS -> "CPU-Compose重组/布局"
                    draw   > FRAME_BUDGET_NS -> "CPU-Compose绘制"
                    gpu    > FRAME_BUDGET_NS -> "GPU渲染"
                    input  > FRAME_BUDGET_NS -> "输入事件处理"
                    anim   > FRAME_BUDGET_NS -> "动画计算"
                    delay  > FRAME_BUDGET_NS -> "调度延迟(线程竞争)"
                    sync   > FRAME_BUDGET_NS -> "同步/上传"
                    else                     -> "未知(${worst?.key})"
                }

                fun ns2ms(ns: Long) = "%.2f".format(ns / 1_000_000.0)
                val msg = buildString {
                    append("掉帧 ${ns2ms(total)}ms [${ns2ms(FRAME_BUDGET_NS)}ms预算] → 原因:$diagnosis")
                    append(" | layout=${ns2ms(layout)} draw=${ns2ms(draw)}")
                    append(" gpu=${ns2ms(gpu)} anim=${ns2ms(anim)}")
                    append(" input=${ns2ms(input)} delay=${ns2ms(delay)}")
                    append(" sync=${ns2ms(sync)} swap=${ns2ms(swap)}")
                }
                if (total >= FRAME_ERROR_NS) Log.e(TAG_FRAME, msg)
                else                         Log.w(TAG_FRAME, msg)
            }
        } else null
    }

    // 位置权限请求（非首次批量流程时，补请求位置）
    private val locationPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        if (granted) {
            lifecycleScope.launch(Dispatchers.IO) {
                ClientContextHelper.refreshLocationAndWeather(applicationContext)
            }
        }
    }

    /** Android 13+：单独补请求通知权限 */
    private val notificationPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        NotificationTrace.log("perm", "POST_NOTIFICATIONS single_request granted=$granted")
        if (granted) maybeGuideNotificationChannelSettings()
    }

    /**
     * 首次启动：相机、麦克风、粗略位置、通知（Android 13+）一次性申请。
     * 不含无障碍与悬浮窗设置（悬浮窗仍在使用陪玩等功能时按需引导）。
     */
    private val initialPermissionsLauncher = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { result ->
        val post = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            result[Manifest.permission.POST_NOTIFICATIONS]
        } else null
        val summary = result.entries.joinToString { "${it.key.substringAfterLast('.')}=${it.value}" }
        NotificationTrace.log("perm", "initial_bundle POST=$post summary=[$summary]")
        if (result[Manifest.permission.ACCESS_COARSE_LOCATION] == true) {
            lifecycleScope.launch(Dispatchers.IO) {
                ClientContextHelper.refreshLocationAndWeather(applicationContext)
            }
        }
        prefs.initialStartupPermissionsDone = true
        if (post == true) maybeGuideNotificationChannelSettings()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = AppPreferences(this)
        // A notification is a one-shot navigation event, not recreation state.
        consumeChatNavigationIntent(intent, allowNavigation = savedInstanceState == null)
        if (!prefs.initialStartupPermissionsDone) {
            NotificationTrace.log("perm", "onCreate launch initial_permission_bundle")
            initialPermissionsLauncher.launch(buildInitialRuntimePermissions())
        } else {
            NotificationTrace.log("perm", "onCreate initial_permissions_done warm path")
            requestLocationAndNotificationsIfMissing()
        }

        WindowCompat.setDecorFitsSystemWindows(window, false)
        window.statusBarColor = android.graphics.Color.TRANSPARENT
        window.navigationBarColor = android.graphics.Color.TRANSPARENT
        enableEdgeToEdge()
        // 状态栏图标明暗在 setContent 内随应用内 darkTheme 同步（见 SideEffect）

        // 帧耗时监控：仅 DEBUG 包，120Hz 下超过 16.7ms（2帧预算）即打印各阶段耗时
        if (BuildConfig.DEBUG && Build.VERSION.SDK_INT >= Build.VERSION_CODES.N && !frameMetricsAdded) {
            frameMetricsListener?.let {
                window.addOnFrameMetricsAvailableListener(it, frameMetricsHandler)
                frameMetricsAdded = true
            }
        }

        setContent {
            var darkTheme by remember { mutableStateOf(prefs.isDarkTheme) }
            var fontScale by remember { mutableFloatStateOf(prefs.fontScale) }
            val snackbarHostState = remember { SnackbarHostState() }
            val runtimeState by companionRuntimeClient.state.collectAsState()
            val enteredFromDeviceHome = this@MainActivity is DeviceHomeActivity
            val deviceExperience = shouldUseDeviceExperience(
                enteredFromDeviceHome,
                resources.getBoolean(R.bool.device_home_enabled),
            )
            LaunchedEffect(deviceExperience) {
                requestedOrientation = if (deviceExperience) {
                    ActivityInfo.SCREEN_ORIENTATION_PORTRAIT
                } else {
                    ActivityInfo.SCREEN_ORIENTATION_PORTRAIT
                }
                WindowCompat.getInsetsController(window, window.decorView).apply {
                    if (deviceExperience) {
                        systemBarsBehavior =
                            WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
                        hide(WindowInsetsCompat.Type.systemBars())
                    } else {
                        show(WindowInsetsCompat.Type.systemBars())
                    }
                }
            }

            // 与应用主题一致：浅色主题用深色状态栏图标，深色主题用浅色图标（勿跟系统 uiMode 写死）
            SideEffect {
                val w = this@MainActivity.window
                WindowCompat.getInsetsController(w, w.decorView).isAppearanceLightStatusBars = !darkTheme
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                    w.isNavigationBarContrastEnforced = false
                }
            }

            PonyChatTheme(darkTheme = darkTheme, fontScale = fontScale) {
                SystemNavigationBarColorEffect(
                    color = MaterialTheme.colorScheme.background,
                    restoreOnDispose = false
                )
                CompositionLocalProvider(
                    CustomToast provides snackbarHostState,
                    LocalDeviceExperience provides deviceExperience,
                    LocalCompanionRuntimeReady provides (runtimeState is CompanionRuntimeState.Ready),
                    LocalCompanionRuntimeState provides runtimeState,
                ) {
                    Box(modifier = Modifier.fillMaxSize()) {
                        Surface(
                            modifier = Modifier.fillMaxSize(),
                            color = MaterialTheme.colorScheme.background
                        ) {
                            if (!enteredFromDeviceHome && runtimeState is CompanionRuntimeState.Detecting) {
                                RuntimeDetectionScreen()
                            } else {
                                key(deviceExperience) {
                                    AppNavigation(
                                        prefs = prefs,
                                        isDeviceExperience = deviceExperience,
                                        isCompanionRuntimeReady = runtimeState is CompanionRuntimeState.Ready,
                                        companionRuntimeStatus = runtimeState.statusText(),
                                        onThemeChanged = { isDark ->
                                            darkTheme = isDark
                                            prefs.isDarkTheme = isDark
                                        },
                                        onFontScaleChanged = { scale ->
                                            fontScale = scale
                                            prefs.fontScale = scale
                                        },
                                    )
                                }
                            }
                        }
                        SnackbarHost(
                            hostState = snackbarHostState,
                            modifier = Modifier
                                .align(Alignment.BottomCenter)
                                .zIndex(100f)
                                .navigationBarsPadding()
                                .padding(bottom = 80.dp)
                        ) { data ->
                            PonyPromptBubble(message = data.visuals.message)
                        }
                    }
                }
            }
        }
    }

    private fun buildInitialRuntimePermissions(): Array<String> {
        val list = mutableListOf(
            Manifest.permission.CAMERA,
            Manifest.permission.RECORD_AUDIO,
            Manifest.permission.ACCESS_COARSE_LOCATION,
        )
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            list.add(Manifest.permission.POST_NOTIFICATIONS)
        }
        return list.toTypedArray()
    }

    /**
     * 首次通知权限授权后（或渠道重建后），检测「角色消息」渠道实际生效的 importance。
     * 国产定制系统（MIUI / ColorOS / EMUI）经常在渠道创建时悄悄降级：即便声明
     * IMPORTANCE_HIGH，悬浮通知、声音、振动仍默认关闭，必须引导用户手动去设置页开启。
     */
    private fun maybeGuideNotificationChannelSettings() {
        if (prefs.notificationChannelGuideDone) return
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val nm = getSystemService(NotificationManager::class.java) ?: return
        val channel = nm.getNotificationChannel("ai_message_v3")
        val needsGuide = channel == null ||
            channel.importance < NotificationManager.IMPORTANCE_HIGH ||
            !channel.shouldVibrate() ||
            channel.sound == null
        NotificationTrace.log("channel_guide", "importance=${channel?.importance} vibrate=${channel?.shouldVibrate()} needsGuide=$needsGuide")
        prefs.notificationChannelGuideDone = true
        if (!needsGuide) return
        // 稍微延迟，避免与权限弹窗同帧冲突
        android.os.Handler(mainLooper).postDelayed({
            if (!isFinishing && !isDestroyed) showNotificationChannelGuideDialog()
        }, 800)
    }

    /** 弹出说明对话框，引导用户打开系统渠道设置（声音 / 振动 / 悬浮提示）。 */
    private fun showNotificationChannelGuideDialog() {
        AlertDialog.Builder(this)
            .setTitle("开启消息提醒")
            .setMessage("为了在 AI 回复完成或发来消息时即时收到提醒，请在接下来的通知设置页中开启「声音」「振动」和「悬浮通知」。")
            .setPositiveButton("立即设置") { _, _ -> openNotificationChannelSettings() }
            .setNegativeButton("稍后手动设置", null)
            .setCancelable(true)
            .show()
    }

    /** 跳转到「角色消息」渠道的系统通知设置页；若不支持则回退到应用级通知设置。 */
    private fun openNotificationChannelSettings() {
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                startActivity(Intent(Settings.ACTION_CHANNEL_NOTIFICATION_SETTINGS).apply {
                    putExtra(Settings.EXTRA_APP_PACKAGE, packageName)
                    putExtra(Settings.EXTRA_CHANNEL_ID, "ai_message_v3")
                    addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                })
                return
            }
        } catch (_: Exception) { }
        try {
            startActivity(Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).apply {
                putExtra(Settings.EXTRA_APP_PACKAGE, packageName)
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            })
        } catch (_: Exception) { }
    }

    /** 非首次启动：与旧版行为一致，对仍未授予的位置/通知单独补请求 */
    private fun requestLocationAndNotificationsIfMissing() {
        NotificationTrace.log("perm", "warm_start check loc+post if missing")
        if (ContextCompat.checkSelfPermission(
                this,
                Manifest.permission.ACCESS_COARSE_LOCATION
            ) != PackageManager.PERMISSION_GRANTED
        ) {
            locationPermissionLauncher.launch(Manifest.permission.ACCESS_COARSE_LOCATION)
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(
                this,
                Manifest.permission.POST_NOTIFICATIONS
            ) != PackageManager.PERMISSION_GRANTED
        ) {
            notificationPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
    }

    /** App 已在前台时用户点击通知（FLAG_ACTIVITY_SINGLE_TOP），通过此回调更新目标 */
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        consumeChatNavigationIntent(intent)
    }

    private fun consumeChatNavigationIntent(intent: Intent?, allowNavigation: Boolean = true) {
        val characterId = intent?.getStringExtra("open_character_id")?.takeIf { it.isNotBlank() }
        val mode = intent?.getStringExtra("open_mode")
        intent?.removeExtra("open_character_id")
        intent?.removeExtra("open_mode")
        if (allowNavigation && characterId != null) {
            ProactiveNavTarget.set(characterId, mode)
        }
    }

    override fun onStart() {
        super.onStart()
        companionRuntimeClient.setOverlayVisible(false)
        companionRuntimeClient.connect()
    }

    override fun onStop() {
        companionRuntimeClient.setOverlayVisible(true)
        // 须在 super.onStop() 之前注销：部分系统/OEM 在 super 后 Window 已卸下监听器，
        // 再 remove 会抛 IllegalArgumentException（listener was never added / 已不在集合中）。
        if (BuildConfig.DEBUG && Build.VERSION.SDK_INT >= Build.VERSION_CODES.N && frameMetricsAdded) {
            frameMetricsListener?.let { listener ->
                try {
                    window.removeOnFrameMetricsAvailableListener(listener)
                } catch (_: IllegalArgumentException) {
                    // 已移除或窗口状态不一致时忽略，避免进程随 Activity stop 崩溃
                }
            }
            frameMetricsAdded = false
            frameMetricsThread.quitSafely()
        }
        super.onStop()
    }

    override fun onDestroy() {
        companionRuntimeClient.disconnect()
        super.onDestroy()
    }
}

@androidx.compose.runtime.Composable
private fun RuntimeDetectionScreen() {
    Column(
        modifier = Modifier.fillMaxSize(),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        CircularProgressIndicator()
        Text(
            text = "正在准备 PonyChat…",
            modifier = Modifier.padding(top = 16.dp),
            color = MaterialTheme.colorScheme.onBackground,
        )
    }
}
