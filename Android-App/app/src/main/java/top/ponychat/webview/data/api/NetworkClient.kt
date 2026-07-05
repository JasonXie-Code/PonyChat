package top.ponychat.webview.data.api

import android.util.Log
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.Interceptor
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import top.ponychat.webview.BuildConfig
import top.ponychat.webview.data.prefs.AppPreferences
import java.io.IOException
import java.security.SecureRandom
import java.security.cert.X509Certificate
import java.util.concurrent.TimeUnit
import javax.net.ssl.SSLContext
import javax.net.ssl.TrustManager
import javax.net.ssl.X509TrustManager

object NetworkClient {

    private const val TAG = "NetworkClient"

    @Volatile
    private var prefsRef: AppPreferences? = null

    fun bindPreferences(prefs: AppPreferences) {
        prefsRef = prefs
    }

    private fun isRetryableStatus(code: Int): Boolean = code == 502 || code == 503 || code == 504

    private fun isSafeRetryMethod(method: String): Boolean {
        return method.equals("GET", true) ||
            method.equals("HEAD", true) ||
            method.equals("OPTIONS", true)
    }

    private fun rewriteToBase(request: Request, base: String): Request {
        val next = try {
            val src = request.url
            val dst = base.toHttpUrlOrNull() ?: return request
            src.newBuilder()
                .scheme(dst.scheme)
                .host(dst.host)
                .port(dst.port)
                .build()
        } catch (e: Exception) {
            top.ponychat.webview.util.DebugLog.w("NetworkClient", "rewriteToBase failed: ${e.message}", e)
            request.url
        }
        return if (next == request.url) request else request.newBuilder().url(next).build()
    }

    private val smartRouteInterceptor = Interceptor { chain ->
        chain.proceed(chain.request())
    }

    private val debugWeakNetworkInterceptor = Interceptor { chain ->
        if (prefsRef?.isDebugWeakNetworkOffline() == true) {
            throw IOException("debug_weak_network_offline_window")
        }
        chain.proceed(chain.request())
    }

    /** 信任所有证书（仅用于局域网自签名证书）——对公网 URL 仍做正常验证。供 WebSocket/JobPoll 等复用。 */
    internal val trustAllCerts: Array<TrustManager> = arrayOf(
        object : X509TrustManager {
            override fun checkClientTrusted(chain: Array<X509Certificate>, authType: String) = Unit
            override fun checkServerTrusted(chain: Array<X509Certificate>, authType: String) = Unit
            override fun getAcceptedIssuers(): Array<X509Certificate> = arrayOf()
        }
    )

    internal val sslContext: SSLContext = SSLContext.getInstance("TLS").apply {
        init(null, trustAllCerts, SecureRandom())
    }

    val okHttpClient: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(30, TimeUnit.SECONDS)
        .readTimeout(200, TimeUnit.SECONDS)  // 普通 REST 接口超时；总结上下文可能耗时 180s，留 20s 余量
        .writeTimeout(30, TimeUnit.SECONDS)
        .sslSocketFactory(sslContext.socketFactory, trustAllCerts[0] as X509TrustManager)
        .hostnameVerifier { _, _ -> true }
        .addInterceptor(debugWeakNetworkInterceptor)
        .addInterceptor(smartRouteInterceptor)
        .addInterceptor { chain ->
            val builder = chain.request().newBuilder()
                .addHeader("Accept", "application/json, text/event-stream")
                .addHeader("X-PonyChat-Client", "android")
                .addHeader("X-App-Version", BuildConfig.VERSION_CODE.toString())
                .addHeader("X-App-Version-Name", BuildConfig.VERSION_NAME)
            prefsRef?.authToken?.takeIf { it.isNotBlank() }?.let {
                builder.addHeader("X-Chat-Auth", it)
                builder.addHeader("Authorization", "Bearer $it")
            }
            chain.proceed(builder.build())
        }
        .addInterceptor { chain ->
            // 全局 401 拦截：token 被新登录作废后兜底触发强制登出
            // 全局 426 拦截：服务端要求升级 App
            val response = chain.proceed(chain.request())
            when (response.code) {
                401 -> if (prefsRef?.isLoggedIn() == true) {
                    Log.w(TAG, "收到 401，触发强制登出")
                    prefsRef?.logout()
                    AuthEventBus.emitForceLogout("token_expired")
                }
                426 -> {
                    Log.w(TAG, "收到 426，当前版本已停止支持，需要升级")
                    AuthEventBus.emitUpgradeRequired()
                }
            }
            response
        }
        .build()

    /**
     * 聊天长耗时 HTTP 连接：单次 [application/json] 响应，readTimeout=600s（与后端整轮分步/长推理一致）。
     * 对「无分块 body」而言，为整包下载上限时间。
     */
    val chatJsonResponseHttpClient: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(30, TimeUnit.SECONDS)
        .readTimeout(600, TimeUnit.SECONDS)
        .writeTimeout(30, TimeUnit.SECONDS)
        .sslSocketFactory(sslContext.socketFactory, trustAllCerts[0] as X509TrustManager)
        .hostnameVerifier { _, _ -> true }
        .addInterceptor(debugWeakNetworkInterceptor)
        .addInterceptor(smartRouteInterceptor)
        .addInterceptor { chain ->
            val req = chain.request()
            val b = req.newBuilder()
            if (req.header("Accept").isNullOrBlank()) {
                b.addHeader("Accept", "application/json")
            }
            b.addHeader("X-PonyChat-Client", "android")
                .addHeader("X-App-Version", BuildConfig.VERSION_CODE.toString())
                .addHeader("X-App-Version-Name", BuildConfig.VERSION_NAME)
            prefsRef?.authToken?.takeIf { it.isNotBlank() }?.let {
                b.addHeader("X-Chat-Auth", it)
                b.addHeader("Authorization", "Bearer $it")
            }
            chain.proceed(b.build())
        }
        .addInterceptor { chain ->
            val response = chain.proceed(chain.request())
            when (response.code) {
                401 -> if (prefsRef?.isLoggedIn() == true) {
                    Log.w(TAG, "聊天请求收到 401，触发强制登出")
                    prefsRef?.logout()
                    AuthEventBus.emitForceLogout("token_expired")
                }
                426 -> {
                    Log.w(TAG, "聊天请求收到 426，当前版本已停止支持，需要升级")
                    AuthEventBus.emitUpgradeRequired()
                }
            }
            response
        }
        .build()

    @Deprecated("已改为 [chatJsonResponseHttpClient] + JSON 体协议，勿在新代码使用")
    val streamingHttpClient: OkHttpClient get() = chatJsonResponseHttpClient

    fun resetConnectionPools(reason: String) {
        Log.i(TAG, "reset connection pools: $reason")
        okHttpClient.connectionPool.evictAll()
        chatJsonResponseHttpClient.connectionPool.evictAll()
    }

    private fun retrofitFor(baseUrl: String, client: OkHttpClient): ApiService {
        val trimmed = AppPreferences.normalizeApiBaseUrl(baseUrl).trim().trimEnd('/')
        require(trimmed.isNotBlank()) { "API baseUrl 不能为空" }
        val parsed = trimmed.toHttpUrlOrNull()
            ?: throw IllegalArgumentException("无效的 API 地址（需含 http 或 https）：$baseUrl")
        val url = parsed.toString().trimEnd('/') + "/"
        return Retrofit.Builder()
            .baseUrl(url)
            .client(client)
            .addConverterFactory(GsonConverterFactory.create())
            .build()
            .create(ApiService::class.java)
    }

    /** 根据 baseUrl 创建 ApiService（启用智能路由拦截） */
    fun createApiService(baseUrl: String): ApiService = retrofitFor(baseUrl, okHttpClient)

    /** 用 AppPreferences 中当前有效 URL 创建 ApiService */
    fun createApiService(prefs: AppPreferences): ApiService =
        createApiService(prefs.effectiveApiBase())

    /**
     * 直连指定 baseUrl（不走智能路由重写），用于测速/探测等避免干扰的场景。
     */
    fun createDirectApiService(
        baseUrl: String,
        connectTimeoutMs: Long = 2_500L,
        readTimeoutMs: Long = 3_500L
    ): ApiService {
        val directClient = OkHttpClient.Builder()
            .connectTimeout(connectTimeoutMs, TimeUnit.MILLISECONDS)
            .readTimeout(readTimeoutMs, TimeUnit.MILLISECONDS)
            .writeTimeout(4_000L, TimeUnit.MILLISECONDS)
            .sslSocketFactory(sslContext.socketFactory, trustAllCerts[0] as X509TrustManager)
            .hostnameVerifier { _, _ -> true }
            .addInterceptor { chain ->
                val req = chain.request().newBuilder()
                    .addHeader("Accept", "application/json, text/event-stream")
                    .build()
                chain.proceed(req)
            }
            .build()
        return retrofitFor(baseUrl, directClient)
    }

    /** 创建信任自签名证书的 OkHttpClient（供 WebSocket、JobPoll 等使用，解决局域网 HTTPS 证书问题） */
    fun createTrustAllClient(
        connectTimeoutSec: Long = 30,
        readTimeoutSec: Long = 120,
        writeTimeoutSec: Long = 30,
        pingIntervalSec: Long = 0
    ): OkHttpClient {
        val builder = OkHttpClient.Builder()
            .connectTimeout(connectTimeoutSec, TimeUnit.SECONDS)
            .readTimeout(readTimeoutSec, TimeUnit.SECONDS)
            .writeTimeout(writeTimeoutSec, TimeUnit.SECONDS)
            .sslSocketFactory(sslContext.socketFactory, trustAllCerts[0] as X509TrustManager)
            .hostnameVerifier { _, _ -> true }
            .addInterceptor(debugWeakNetworkInterceptor)
        if (pingIntervalSec > 0) builder.pingInterval(pingIntervalSec, TimeUnit.SECONDS)
        return builder.build()
    }
}
