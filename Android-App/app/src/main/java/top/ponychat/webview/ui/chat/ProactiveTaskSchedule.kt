package top.ponychat.webview.ui.chat

import top.ponychat.webview.data.model.ProactiveTask
import top.ponychat.webview.data.model.ProactiveTaskRequest
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Date
import java.util.Locale

internal fun ProactiveTask.toRequest(enabled: Boolean = this.enabled): ProactiveTaskRequest =
    ProactiveTaskRequest(
        characterId = characterId,
        conversationId = conversationId,
        title = title,
        taskType = taskType,
        scheduleType = scheduleType,
        dueAtMs = dueAtMs,
        intervalSeconds = intervalSeconds,
        timeOfDay = timeOfDay,
        timezone = timezone,
        days = days,
        jitterMinutes = jitterMinutes,
        prompt = prompt,
        style = style,
        enabled = enabled
    )

internal fun ProactiveTask.taskTypeLabel(): String =
    when (taskType) {
        "morning_wakeup" -> "早安叫醒"
        "night_goodnight" -> "晚安提醒"
        "reminder" -> "提醒"
        "timer" -> "计时器"
        "appointment" -> "预约"
        "life_share" -> "生活日常"
        else -> "定时任务"
    }

internal fun ProactiveTask.scheduleTypeLabel(): String =
    when (scheduleType) {
        "daily" -> "每日 ${timeOfDay.ifBlank { "--:--" }}"
        "weekly" -> "每周 ${timeOfDay.ifBlank { "--:--" }}"
        "monthly" -> "每月 ${days.firstOrNull()?.let { "${it}日" } ?: ""} ${timeOfDay.ifBlank { "--:--" }}"
        "interval" -> "每 ${intervalSeconds / 60} 分钟"
        else -> "一次性"
    }

internal fun formatTaskTime(task: ProactiveTask): String {
    if (task.dueAtMs <= 0) return "待定"
    return SimpleDateFormat("MM-dd HH:mm", Locale.getDefault()).format(Date(task.dueAtMs))
}

internal fun todayDateText(): String =
    SimpleDateFormat("yyyy-MM-dd", Locale.getDefault()).format(Date())

internal fun parseDateTimeMs(dateText: String, timeText: String): Long? =
    runCatching {
        SimpleDateFormat("yyyy-MM-dd HH:mm", Locale.getDefault()).apply {
            isLenient = false
        }.parse("$dateText $timeText")?.time
    }.getOrNull()

internal fun normalizeTimeOfDay(value: String): String {
    val parts = value.trim().split(":")
    if (parts.size != 2) return ""
    val hour = parts[0].toIntOrNull() ?: return ""
    val minute = parts[1].toIntOrNull() ?: return ""
    if (hour !in 0..23 || minute !in 0..59) return ""
    return "%02d:%02d".format(hour, minute)
}

internal fun Int.toPonyWeekday(): Int =
    when (this) {
        Calendar.MONDAY -> 0
        Calendar.TUESDAY -> 1
        Calendar.WEDNESDAY -> 2
        Calendar.THURSDAY -> 3
        Calendar.FRIDAY -> 4
        Calendar.SATURDAY -> 5
        else -> 6
    }

internal fun String.defaultTaskTitle(): String =
    when (this) {
        "once" -> "单次提醒"
        "daily" -> "每日提醒"
        "weekly" -> "每周提醒"
        "monthly" -> "每月提醒"
        "interval" -> "间隔提醒"
        else -> "定时任务"
    }

internal fun String.shortLabel(): String =
    when (this) {
        "once" -> "单次"
        "daily" -> "每日"
        "weekly" -> "每周"
        "monthly" -> "每月"
        "interval" -> "间隔"
        else -> ""
    }
