package top.ponychat.webview.util

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.location.Geocoder
import android.location.LocationManager
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.os.BatteryManager
import android.os.Build
import android.provider.Settings
import android.util.Log
import androidx.core.content.ContextCompat
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import top.ponychat.webview.data.model.ClientContext
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.TimeUnit

/**
 * 单例：负责收集客户端环境信息，供聊天/陪玩请求注入 AI 上下文。
 *
 * - 时间：每次请求实时获取，无需缓存
 * - 设备型号/OS：静态，应用生命周期内不变
 * - 电量/网络：每次同步读取（极快，无需缓存）
 * - 位置：需要 ACCESS_COARSE_LOCATION 权限；缓存 5 分钟；无权限则跳过
 * - 天气：依赖位置；使用 Open-Meteo 免费 API；缓存 30 分钟
 */
object ClientContextHelper {

    private const val TAG = "ClientContextHelper"
    private const val WEATHER_CACHE_MS = 30 * 60 * 1000L  // 30 分钟
    private const val LOCATION_CACHE_MS = 5 * 60 * 1000L  // 5 分钟
    private const val PRECIPITATION_EPSILON_MM = 0.05

    @Volatile private var cachedLocationName: String? = null
    @Volatile private var cachedWeatherDesc: String? = null
    @Volatile private var cachedTemperature: Int? = null
    @Volatile private var cachedLat: Double? = null
    @Volatile private var cachedLon: Double? = null
    @Volatile private var locationCacheTime: Long = 0
    @Volatile private var weatherCacheTime: Long = 0

    private val deviceModel: String by lazy {
        val manufacturer = Build.MANUFACTURER.replaceFirstChar { it.uppercaseChar() }
        val model = Build.MODEL
        if (model.startsWith(manufacturer, ignoreCase = true)) model else "$manufacturer $model"
    }

    private val osVersion: String by lazy { "Android ${Build.VERSION.RELEASE}" }

    /**
     * 检测厂商定制 UI 系统版本，优先顺序：HyperOS > MIUI > OneUI > ColorOS > EMUI > FuntouchOS > AOSP
     * 使用反射读取 SystemProperties，避免直接依赖私有 API。
     */
    private val osFlavor: String? by lazy {
        fun sysProp(key: String): String? = try {
            (Class.forName("android.os.SystemProperties")
                .getMethod("get", String::class.java)
                .invoke(null, key) as? String)
                ?.takeIf { it.isNotBlank() }
        } catch (_: Exception) { null }

        val mfr = Build.MANUFACTURER.lowercase()
        when {
            // 小米 HyperOS（优先于 MIUI 判断）
            sysProp("ro.mi.os.version.name") != null ->
                "HyperOS ${sysProp("ro.mi.os.version.name")}"
            // 小米 MIUI
            (mfr == "xiaomi" || mfr == "redmi" || mfr == "poco") &&
                    sysProp("ro.miui.ui.version.name") != null ->
                "MIUI ${sysProp("ro.miui.ui.version.name")}"
            // 三星 OneUI
            sysProp("ro.build.version.oneui") != null -> {
                val v = sysProp("ro.build.version.oneui") ?: ""
                val major = v.toIntOrNull()?.div(10000) ?: ""
                "OneUI ${major}"
            }
            // OPPO/Realme/OnePlus ColorOS
            mfr in listOf("oppo", "realme", "oneplus") ->
                sysProp("ro.build.version.oplusrom.display")
                    ?.let { "ColorOS $it" }
                    ?: "ColorOS"
            // Vivo OriginOS / FuntouchOS
            mfr == "vivo" ->
                sysProp("ro.vivo.os.version")?.let { "OriginOS $it" } ?: "OriginOS"
            // 华为 EMUI / HarmonyOS
            mfr in listOf("huawei", "honor") ->
                sysProp("ro.build.version.emui")?.let { "EMUI/HarmonyOS $it" } ?: "EMUI/HarmonyOS"
            // 其他 AOSP
            else -> null
        }
    }

    /**
     * 检测导航方式：gesture（全面屏手势） / 2button / 3button
     * Settings.Secure navigation_mode: 0=3键, 1=2键, 2=手势
     * 部分厂商用 navigation_gesture_enabled: 1=手势
     */
    private fun getNavMode(context: Context): String {
        return try {
            val mode = Settings.Secure.getInt(context.contentResolver, "navigation_mode", -1)
            when (mode) {
                2 -> "gesture"
                1 -> "2button"
                0 -> "3button"
                else -> {
                    // 小米等厂商备用字段
                    val gestureOn = Settings.Secure.getInt(
                        context.contentResolver, "navigation_gesture_enabled", 0
                    )
                    if (gestureOn == 1) "gesture" else "3button"
                }
            }
        } catch (_: Exception) { "gesture" }
    }

    private val httpClient: OkHttpClient by lazy {
        OkHttpClient.Builder()
            .connectTimeout(10, TimeUnit.SECONDS)
            .readTimeout(15, TimeUnit.SECONDS)
            .build()
    }

    // ── 对外接口 ────────────────────────────────────────────────────────────────

    /**
     * 立即同步返回环境上下文。
     * 时间/设备/电量/网络始终实时；位置/天气来自缓存（可能为 null）。
     */
    fun buildContext(context: Context): ClientContext {
        val df = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ssXXX", Locale.getDefault())
        return ClientContext(
            timeIso = df.format(Date()),
            deviceModel = deviceModel,
            osVersion = osVersion,
            battery = getBatteryLevel(context),
            network = getNetworkType(context),
            locationName = cachedLocationName,
            weatherDesc = cachedWeatherDesc,
            temperature = cachedTemperature,
            osFlavor = osFlavor,
            navMode = getNavMode(context)
        )
    }

    /**
     * 后台刷新位置和天气缓存（挂起函数，IO dispatcher）。
     * 需要 ACCESS_COARSE_LOCATION 权限；未授权时静默跳过。
     * 缓存未过期时直接返回，不发起新请求。
     */
    suspend fun refreshLocationAndWeather(context: Context) = withContext(Dispatchers.IO) {
        try {
            val now = System.currentTimeMillis()
            val needLocation = (now - locationCacheTime) > LOCATION_CACHE_MS
            val needWeather = (now - weatherCacheTime) > WEATHER_CACHE_MS
            if (!needLocation && !needWeather) return@withContext

            val hasPermission = ContextCompat.checkSelfPermission(
                context, Manifest.permission.ACCESS_COARSE_LOCATION
            ) == PackageManager.PERMISSION_GRANTED
            if (!hasPermission) return@withContext

            val location = getLastKnownLocation(context) ?: return@withContext
            val lat = location.latitude
            val lon = location.longitude

            if (needLocation) {
                cachedLat = lat
                cachedLon = lon
                locationCacheTime = now
                cachedLocationName = reverseGeocode(context, lat, lon)
                Log.d(TAG, "位置已更新: ${cachedLocationName ?: "($lat, $lon)"}")
            }

            if (needWeather) {
                val (desc, temp) = fetchWeather(lat, lon)
                cachedWeatherDesc = desc
                cachedTemperature = temp
                weatherCacheTime = now
                Log.d(TAG, "天气已更新: $desc ${temp}°C")
            }
        } catch (e: Exception) {
            Log.w(TAG, "refreshLocationAndWeather failed: ${e.message}")
        }
    }

    // ── 私有实现 ────────────────────────────────────────────────────────────────

    private fun getLastKnownLocation(context: Context): android.location.Location? {
        return try {
            val lm = context.getSystemService(Context.LOCATION_SERVICE) as LocationManager
            listOf(
                LocationManager.NETWORK_PROVIDER,
                LocationManager.GPS_PROVIDER,
                LocationManager.PASSIVE_PROVIDER
            ).mapNotNull { provider ->
                try {
                    if (ContextCompat.checkSelfPermission(
                            context, Manifest.permission.ACCESS_COARSE_LOCATION
                        ) == PackageManager.PERMISSION_GRANTED
                    ) lm.getLastKnownLocation(provider) else null
                } catch (e: Exception) { null }
            }.maxByOrNull { it.time }
        } catch (e: Exception) { null }
    }

    @Suppress("DEPRECATION")
    private fun reverseGeocode(context: Context, lat: Double, lon: Double): String? {
        return try {
            if (!Geocoder.isPresent()) return null
            val geocoder = Geocoder(context, Locale.CHINA)
            val addrs = geocoder.getFromLocation(lat, lon, 1)
            formatAddress(addrs?.firstOrNull())
        } catch (e: Exception) {
            Log.w(TAG, "reverseGeocode failed: ${e.message}")
            null
        }
    }

    private fun formatAddress(address: android.location.Address?): String? {
        if (address == null) return null
        val parts = listOfNotNull(
            address.adminArea,
            address.subAdminArea?.takeIf { it != address.adminArea && it.isNotBlank() },
            address.locality?.takeIf { it.isNotBlank() }
        )
        return parts.filter { it.isNotBlank() }.joinToString("").takeIf { it.isNotBlank() }
    }

    private fun fetchWeather(lat: Double, lon: Double): Pair<String?, Int?> {
        return try {
            val url = "https://api.open-meteo.com/v1/forecast" +
                    "?latitude=$lat&longitude=$lon" +
                    "&current=temperature_2m,weather_code,precipitation,rain,showers,cloud_cover&timezone=auto"
            val req = Request.Builder().url(url).get().build()
            val resp = httpClient.newCall(req).execute()
            if (!resp.isSuccessful) return Pair(null, null)
            val body = resp.body?.string() ?: return Pair(null, null)
            val json = JSONObject(body)
            val current = json.optJSONObject("current") ?: return Pair(null, null)
            val tempVal = current.optDouble("temperature_2m", Double.NaN)
            val temp = if (tempVal.isNaN()) null else tempVal.toInt()
            val code = current.optInt("weather_code", -1)
            val precipitation = current.optNullableDouble("precipitation")
            val rain = current.optNullableDouble("rain")
            val showers = current.optNullableDouble("showers")
            val cloudCover = current.optNullableDouble("cloud_cover")
            val desc = normalizeWeatherDescription(code, precipitation, rain, showers, cloudCover)
            Pair(desc, temp)
        } catch (e: Exception) {
            Log.w(TAG, "fetchWeather failed: ${e.message}")
            Pair(null, null)
        }
    }

    private fun JSONObject.optNullableDouble(name: String): Double? {
        val value = optDouble(name, Double.NaN)
        return if (value.isNaN()) null else value
    }

    private fun normalizeWeatherDescription(
        code: Int,
        precipitation: Double?,
        rain: Double?,
        showers: Double?,
        cloudCover: Double?
    ): String? {
        val hasMeasuredPrecipitation = listOfNotNull(precipitation, rain, showers)
            .any { it > PRECIPITATION_EPSILON_MM }
        return if (isRainOrThunderCode(code) && !hasMeasuredPrecipitation) {
            cloudCoverToChinese(cloudCover) ?: "多云"
        } else {
            weatherCodeToChinese(code)
        }
    }

    private fun isRainOrThunderCode(code: Int): Boolean = code in 51..67 || code in 80..82 || code in 95..99

    private fun cloudCoverToChinese(cloudCover: Double?): String? = when {
        cloudCover == null -> null
        cloudCover >= 90.0 -> "阴"
        cloudCover >= 20.0 -> "多云"
        else -> "晴"
    }

    private fun weatherCodeToChinese(code: Int): String? = when (code) {
        0 -> "晴"
        1 -> "晴间多云"
        2 -> "多云"
        3 -> "阴"
        45, 48 -> "雾"
        51, 53, 55 -> "毛毛雨"
        56, 57 -> "冻雨"
        61 -> "小雨"
        63 -> "中雨"
        65 -> "大雨"
        66, 67 -> "冻雨"
        71 -> "小雪"
        73 -> "中雪"
        75 -> "大雪"
        77 -> "雪粒"
        80 -> "阵雨"
        81, 82 -> "强阵雨"
        85, 86 -> "阵雪"
        95 -> "雷雨"
        96, 99 -> "强雷雨"
        else -> null
    }

    private fun getBatteryLevel(context: Context): Int? {
        return try {
            val bm = context.getSystemService(Context.BATTERY_SERVICE) as BatteryManager
            val level = bm.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY)
            if (level in 0..100) level else null
        } catch (e: Exception) { null }
    }

    private fun getNetworkType(context: Context): String? {
        return try {
            val cm = context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
            val network = cm.activeNetwork ?: return null
            val caps = cm.getNetworkCapabilities(network) ?: return null
            when {
                caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> "WiFi"
                caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) -> "移动网络"
                caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) -> "以太网"
                else -> null
            }
        } catch (e: Exception) { null }
    }
}
