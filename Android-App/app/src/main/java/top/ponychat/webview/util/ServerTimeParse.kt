package top.ponychat.webview.util

import android.os.Build
import java.text.ParsePosition
import java.text.SimpleDateFormat
import java.util.Locale
import java.util.TimeZone

/**
 * 将服务端返回的时间字符串解析为 epoch 毫秒（按设备默认时区理解无时区字符串），
 * 用于主动消息等与「通知到达时刻」区分的排序时间。
 */
object ServerTimeParse {

    fun parseFlexibleToEpochMs(s: String?): Long {
        if (s.isNullOrBlank()) return 0L
        val t = s.trim()
        if (Build.VERSION.SDK_INT >= 26) {
            runCatching {
                java.time.OffsetDateTime.parse(t).toInstant().toEpochMilli()
            }.getOrNull()?.let { return it }
            runCatching {
                val norm = if (t.length >= 19 && t[4] == '-' && t[10] == ' ') t.replace(" ", "T").take(19) else t.take(19)
                java.time.LocalDateTime.parse(norm)
                    .atZone(java.time.ZoneId.systemDefault())
                    .toInstant()
                    .toEpochMilli()
            }.getOrNull()?.let { return it }
        }
        val patterns = arrayOf(
            "yyyy-MM-dd HH:mm:ss.SSS",
            "yyyy-MM-dd HH:mm:ss",
            "yyyy-MM-dd'T'HH:mm:ss.SSS",
            "yyyy-MM-dd'T'HH:mm:ss",
        )
        for (p in patterns) {
            val df = SimpleDateFormat(p, Locale.US)
            df.timeZone = TimeZone.getDefault()
            val pos = ParsePosition(0)
            val d = df.parse(t, pos)
            if (d != null && pos.index > 0) return d.time
        }
        return 0L
    }
}
