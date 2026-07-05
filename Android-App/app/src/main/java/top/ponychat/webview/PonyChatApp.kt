package top.ponychat.webview

import android.app.Application
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import coil.ImageLoader
import coil.ImageLoaderFactory
import coil.decode.GifDecoder
import coil.decode.ImageDecoderDecoder
import coil.disk.DiskCache
import coil.memory.MemoryCache
import top.ponychat.webview.data.api.NetworkClient
import top.ponychat.webview.data.api.SyncWebSocketManager
import top.ponychat.webview.data.api.NetworkQualityCenter
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.util.ChatEventBus
import top.ponychat.webview.util.DebugLog
import top.ponychat.webview.util.NotificationTrace
import android.media.AudioAttributes
import android.media.RingtoneManager
import android.provider.Settings

class PonyChatApp : Application(), ImageLoaderFactory {

    lateinit var prefs: AppPreferences
        private set

    override fun onCreate() {
        super.onCreate()
        val previousExceptionHandler = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { thread, throwable ->
            DebugLog.e("Uncaught", "thread=${thread.name} ${throwable.message}", throwable)
            @Suppress("DEPRECATION")
            previousExceptionHandler?.uncaughtException(thread, throwable)
        }
        prefs = AppPreferences(this)
        ChatEventBus.attach(prefs)
        NetworkClient.bindPreferences(prefs)
        NetworkQualityCenter.start(prefs)
        createNotificationChannels()
        if (prefs.isLoggedIn()) {
            NotificationTrace.log("app_onCreate", "cold_logged_in bind+conn_svc")
            SyncWebSocketManager.bindNotificationContext(this)
            Handler(Looper.getMainLooper()).post {
                ConnectionService.start(this)
            }
        }
    }

    override fun newImageLoader(): ImageLoader {
        // 复用 NetworkClient 的 trustAllCerts + hostnameVerifier，使 Coil 能正常加载
        // 局域网 HTTPS 自签名证书下的 /chat_images/ 图片（默认 OkHttpClient 会 SSL 握手失败）
        val coilHttpClient = okhttp3.OkHttpClient.Builder()
            .sslSocketFactory(
                NetworkClient.sslContext.socketFactory,
                NetworkClient.trustAllCerts[0] as javax.net.ssl.X509TrustManager
            )
            .hostnameVerifier { _, _ -> true }
            .build()

        return ImageLoader.Builder(this)
            .okHttpClient(coilHttpClient)
            .components {
                if (Build.VERSION.SDK_INT >= 28) {
                    add(ImageDecoderDecoder.Factory())
                } else {
                    add(GifDecoder.Factory())
                }
            }
            .memoryCache {
                MemoryCache.Builder(this)
                    .maxSizePercent(0.25)
                    .build()
            }
            .diskCache {
                DiskCache.Builder()
                    .directory(cacheDir.resolve("coil_image_cache"))
                    .maxSizeBytes(100L * 1024 * 1024)
                    .build()
            }
            .crossfade(false)
            .build()
    }

    private fun createNotificationChannels() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val nm = getSystemService(NOTIFICATION_SERVICE) as NotificationManager
            // 系统当前「默认通知铃声」；若为 null 则回退到平台常量，避免渠道被创建为静音
            val soundUri = RingtoneManager.getActualDefaultRingtoneUri(this, RingtoneManager.TYPE_NOTIFICATION)
                ?: Settings.System.DEFAULT_NOTIFICATION_URI
            val attrs = AudioAttributes.Builder()
                .setUsage(AudioAttributes.USAGE_NOTIFICATION)
                .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                .build()
            // IMPORTANCE_MAX（API 34+）更易触发/heads-up；已存在频道不会自动升级，故使用新 channel id
            val importance = if (Build.VERSION.SDK_INT >= 34) {
                NotificationManager.IMPORTANCE_MAX
            } else {
                NotificationManager.IMPORTANCE_HIGH
            }
            val roleMessages = NotificationChannel(
                "ai_message_v3",
                "角色消息",
                importance
            ).apply {
                description = "管理角色新消息的通知"
                setSound(soundUri, attrs)
                enableVibration(true)
                vibrationPattern = longArrayOf(0L, 140L, 80L, 140L)
                enableLights(true)
                lightColor = android.graphics.Color.parseColor("#6366F1")
                lockscreenVisibility = Notification.VISIBILITY_PUBLIC
                setShowBadge(true)
                setBypassDnd(false)
            }
            nm.createNotificationChannel(roleMessages)
            NotificationTrace.log("channel", "ai_message_v3 importance=$importance")
        }
    }
}
