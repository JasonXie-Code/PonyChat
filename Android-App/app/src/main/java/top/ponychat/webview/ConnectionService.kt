package top.ponychat.webview

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkRequest
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import androidx.core.app.NotificationCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.ProcessLifecycleOwner
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import top.ponychat.webview.data.api.SyncWebSocketManager
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.util.ChatEventBus
import top.ponychat.webview.util.DebugLog
import top.ponychat.webview.util.NotificationTrace

/**
 * 登录后常驻前台服务，保活 WebSocket，便于后台/锁屏时接收推送。
 */
class ConnectionService : Service() {

    private val serviceJob = SupervisorJob()
    private val scope = CoroutineScope(serviceJob + Dispatchers.Main.immediate)
    private var networkCallback: ConnectivityManager.NetworkCallback? = null
    private var screenReceiver: BroadcastReceiver? = null
    private var wakeLock: PowerManager.WakeLock? = null
    private var keepAliveJob: Job? = null

    private val processObserver = LifecycleEventObserver { _, event ->
        val prefs = (application as? PonyChatApp)?.prefs ?: return@LifecycleEventObserver
        if (!prefs.isLoggedIn()) return@LifecycleEventObserver
        when (event) {
            Lifecycle.Event.ON_START -> {
                refreshWakeLock("proc_ON_START")
                NotificationTrace.log("lifecycle", "ON_START pull+nudge")
                SyncWebSocketManager.pullUndeliveredOnce(prefs, "proc_ON_START")
                SyncWebSocketManager.nudgeReconnect()
            }
            // 切后台立即补拉：用户刚安装后发消息即按 Home，WS 可能尚未推完，依赖 HTTP outbox 补未读与通知
            Lifecycle.Event.ON_STOP -> {
                refreshWakeLock("proc_ON_STOP")
                NotificationTrace.log("lifecycle", "ON_STOP pull")
                SyncWebSocketManager.pullUndeliveredOnce(prefs, "proc_ON_STOP")
            }
            else -> Unit
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        ProcessLifecycleOwner.get().lifecycle.addObserver(processObserver)
        registerScreenReceiver()
        val cm = getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        val cb = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) {
                val prefs = (application as? PonyChatApp)?.prefs ?: return
                if (!prefs.isLoggedIn()) return
                refreshWakeLock("network_available")
                NotificationTrace.log("network", "onAvailable pull+nudge")
                SyncWebSocketManager.nudgeReconnect()
                SyncWebSocketManager.pullUndeliveredOnce(prefs, "net_available")
                ChatEventBus.notifyNetworkAvailable()
            }
        }
        networkCallback = cb
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
                cm.registerDefaultNetworkCallback(cb)
            } else {
                @Suppress("DEPRECATION")
                cm.registerNetworkCallback(NetworkRequest.Builder().build(), cb)
            }
        } catch (e: Exception) {
            DebugLog.w("ConnectionService", "registerNetworkCallback: ${e.message}", e)
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val prefs = (application as PonyChatApp).prefs
        if (!prefs.isLoggedIn()) {
            stopSelf()
            return START_NOT_STICKY
        }
        startForeground(NOTIFICATION_ID, buildNotification())
        NotificationTrace.log("conn_svc", "onStartCommand startForeground+ws_start")
        refreshWakeLock("svc_start")
        SyncWebSocketManager.bindNotificationContext(applicationContext)
        SyncWebSocketManager.start(prefs, applicationContext)
        ensureKeepAliveLoop(prefs)
        // 兜底：尽快 + 稍后各拉一次（新安装首次登录时 WS 连接较慢，短延迟可显著减少「切后台无通知」）
        scope.launch(Dispatchers.IO) {
            delay(400)
            refreshWakeLock("svc_delay400")
            SyncWebSocketManager.pullUndeliveredOnce(prefs, "svc_delay400")
        }
        scope.launch(Dispatchers.IO) {
            delay(2500)
            refreshWakeLock("svc_delay2500")
            SyncWebSocketManager.pullUndeliveredOnce(prefs, "svc_delay2500")
        }
        return START_STICKY
    }

    override fun onTaskRemoved(rootIntent: Intent?) {
        super.onTaskRemoved(rootIntent)
        val prefs = (application as? PonyChatApp)?.prefs ?: return
        if (!prefs.isLoggedIn()) return
        refreshWakeLock("task_removed")
        NotificationTrace.log("conn_svc", "onTaskRemoved keep ws alive")
        SyncWebSocketManager.start(prefs, applicationContext)
        SyncWebSocketManager.pullUndeliveredOnce(prefs, "task_removed")
    }

    override fun onDestroy() {
        try {
            val cm = getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
            networkCallback?.let { cm.unregisterNetworkCallback(it) }
        } catch (_: Exception) {
        }
        networkCallback = null
        try {
            screenReceiver?.let { unregisterReceiver(it) }
        } catch (_: Exception) {
        }
        screenReceiver = null
        keepAliveJob?.cancel()
        keepAliveJob = null
        ProcessLifecycleOwner.get().lifecycle.removeObserver(processObserver)
        releaseWakeLock("destroy")
        NotificationTrace.log("conn_svc", "onDestroy stop ws")
        SyncWebSocketManager.stop()
        serviceJob.cancel()
        super.onDestroy()
    }

    private fun registerScreenReceiver() {
        if (screenReceiver != null) return
        val receiver = object : BroadcastReceiver() {
            override fun onReceive(context: Context?, intent: Intent?) {
                val prefs = (application as? PonyChatApp)?.prefs ?: return
                if (!prefs.isLoggedIn()) return
                when (intent?.action) {
                    Intent.ACTION_SCREEN_OFF -> {
                        refreshWakeLock("screen_off")
                        NotificationTrace.log("screen", "OFF pull+ensure_ws")
                        SyncWebSocketManager.start(prefs, applicationContext)
                        SyncWebSocketManager.pullUndeliveredOnce(prefs, "screen_off")
                    }
                    Intent.ACTION_SCREEN_ON,
                    Intent.ACTION_USER_PRESENT -> {
                        refreshWakeLock(intent.action?.substringAfterLast('.').orEmpty())
                        NotificationTrace.log("screen", "${intent.action} pull+nudge")
                        SyncWebSocketManager.start(prefs, applicationContext)
                        SyncWebSocketManager.nudgeReconnect()
                        SyncWebSocketManager.pullUndeliveredOnce(prefs, "screen_on")
                    }
                }
            }
        }
        screenReceiver = receiver
        val filter = IntentFilter().apply {
            addAction(Intent.ACTION_SCREEN_OFF)
            addAction(Intent.ACTION_SCREEN_ON)
            addAction(Intent.ACTION_USER_PRESENT)
        }
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                registerReceiver(receiver, filter, Context.RECEIVER_NOT_EXPORTED)
            } else {
                @Suppress("DEPRECATION")
                registerReceiver(receiver, filter)
            }
        } catch (e: Exception) {
            screenReceiver = null
            DebugLog.w("ConnectionService", "registerScreenReceiver: ${e.message}", e)
        }
    }

    private fun ensureKeepAliveLoop(prefs: AppPreferences) {
        if (keepAliveJob?.isActive == true) return
        keepAliveJob = scope.launch(Dispatchers.IO) {
            delay(KEEP_ALIVE_FIRST_DELAY_MS)
            var tick = 1
            while (isActive && prefs.isLoggedIn()) {
                refreshWakeLock("keepalive_$tick")
                NotificationTrace.log("conn_svc", "keepalive tick=$tick pull+ensure_ws")
                SyncWebSocketManager.bindNotificationContext(applicationContext)
                SyncWebSocketManager.start(prefs, applicationContext)
                SyncWebSocketManager.pullUndeliveredOnce(prefs, "svc_keepalive_$tick")
                tick++
                delay(KEEP_ALIVE_PULL_EVERY_MS)
            }
        }
    }

    private fun refreshWakeLock(reason: String) {
        try {
            val lock = wakeLock ?: run {
                val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
                pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, WAKE_LOCK_TAG).apply {
                    setReferenceCounted(false)
                    wakeLock = this
                }
            }
            lock.acquire(WAKE_LOCK_TIMEOUT_MS)
            NotificationTrace.log("wake_lock", "refresh reason=$reason held=${lock.isHeld} timeoutMs=$WAKE_LOCK_TIMEOUT_MS")
        } catch (e: Exception) {
            DebugLog.w("ConnectionService", "refreshWakeLock($reason): ${e.message}", e)
        }
    }

    private fun releaseWakeLock(reason: String) {
        try {
            wakeLock?.takeIf { it.isHeld }?.release()
            NotificationTrace.log("wake_lock", "release reason=$reason")
        } catch (e: Exception) {
            DebugLog.w("ConnectionService", "releaseWakeLock($reason): ${e.message}", e)
        } finally {
            wakeLock = null
        }
    }

    private fun buildNotification(): Notification {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val ch = NotificationChannel(
                CHANNEL_ID,
                "保持在线",
                NotificationManager.IMPORTANCE_MIN
            ).apply { description = "保持与服务器同步，便于接收消息" }
            val nm = getSystemService(NOTIFICATION_SERVICE) as NotificationManager
            nm.createNotificationChannel(ch)
        }
        val intent = Intent(this, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_SINGLE_TOP
        }
        val pi = PendingIntent.getActivity(
            this, 0, intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.mipmap.ic_launcher)
            .setContentTitle(getString(R.string.app_name))
            .setContentText("保持在线同步")
            .setPriority(NotificationCompat.PRIORITY_MIN)
            .setOngoing(true)
            .setContentIntent(pi)
            .build()
    }

    companion object {
        private const val CHANNEL_ID = "ponychat_connection"
        private const val NOTIFICATION_ID = 9101
        private const val KEEP_ALIVE_FIRST_DELAY_MS = 30_000L
        private const val KEEP_ALIVE_PULL_EVERY_MS = 60_000L
        private const val WAKE_LOCK_TIMEOUT_MS = KEEP_ALIVE_PULL_EVERY_MS + 45_000L
        private const val WAKE_LOCK_TAG = "PonyChat:ConnectionService"

        fun start(context: Context) {
            val prefs = AppPreferences(context.applicationContext)
            if (!prefs.isLoggedIn()) return
            val i = Intent(context, ConnectionService::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(i)
            } else {
                context.startService(i)
            }
        }

        fun stop(context: Context) {
            try {
                context.stopService(Intent(context, ConnectionService::class.java))
            } catch (e: Exception) {
                DebugLog.w("ConnectionService", "stop: ${e.message}", e)
            }
        }
    }
}
