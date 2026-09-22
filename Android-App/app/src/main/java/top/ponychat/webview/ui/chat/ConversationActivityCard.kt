package top.ponychat.webview.ui.chat

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import top.ponychat.webview.ui.theme.Primary

/** Shares the existing visible-only Agent poll; never infers a plan from model activity. */
@Composable
internal fun ConversationActivityContent(snapshot: AgentStatusSnapshot, mode: String) {
    val activity = snapshot.conversationActivity
    val now = (activity?.serverNowMs ?: 0L) + snapshot.elapsedSinceReceivedMs
    val expired = activity?.state in listOf("pending", "processing") &&
        (activity?.expiresAtMs ?: 0L) > 0 && now >= activity!!.expiresAtMs
    val state = if (mode != "normal") "unsupported" else if (expired) "expired" else activity?.state
    val headline = when (state) {
        "pending" -> "已安排，稍后补一句"
        "processing" -> "正在准备续聊"
        "none" -> "暂未安排续聊"
        "sent" -> "上次续聊已发出"
        "cancelled" -> "上次续聊已取消"
        "expired" -> "上次续聊已过期"
        "failed" -> "上次续聊未成功"
        "disabled" -> "自动续聊已关闭"
        "limit_reached" -> "续聊已暂停，等你回应"
        "unsupported" -> "当前模式不安排自动续聊"
        "no_conversation" -> "暂无当前对话的续聊信息"
        else -> if (activity == null && snapshot.notice != null && !snapshot.noticeIsError)
            "正在读取续聊状态…" else "续聊状态暂不可用"
    }
    val agents = snapshot.agents.ifEmpty { listOfNotNull(snapshot.agent) }.filter { it.mode == mode }
    val foreground = snapshot.agent?.takeIf { it.mode == mode && it.phase == "foreground" }
    val reply = when (foreground?.status) {
        "running" -> "正在处理回复"
        "success" -> "本轮已结束"
        "error", "timeout", "interrupted", "stale" -> "上次回复未正常结束"
        else -> "暂无运行记录"
    }
    Column(Modifier.fillMaxWidth().padding(horizontal = 12.dp)) {
        Text("对话动态", Modifier.padding(horizontal = 4.dp, vertical = 12.dp),
            style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Surface(shape = RoundedCornerShape(12.dp), modifier = Modifier.fillMaxWidth(),
            border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
            color = MaterialTheme.colorScheme.surface) {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text(headline, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold,
                    color = if (state in listOf("pending", "processing")) Primary else MaterialTheme.colorScheme.onSurface)
                if (state == "pending") {
                    val seconds = ((activity!!.dueAtMs - now).coerceAtLeast(0L) + 999) / 1000
                    ActivityRow("预计尝试", if (seconds == 0L) "已到计划时间，等待执行"
                        else if (seconds >= 60) "约 ${seconds / 60} 分 ${seconds % 60} 秒后" else "约 $seconds 秒后")
                }
                Text(when (state) {
                    "pending", "processing" -> if (activity?.cancelIfUserReplies == true)
                        "你先发新消息时，这次安排会取消。是否发出仍以执行结果为准。"
                        else "角色已安排续聊，是否发出仍以执行结果为准。"
                    "disabled" -> if (activity?.memoryEnabled == false) "开启记忆与主动消息后，角色可安排稍后续聊。"
                        else "开启主动消息后，角色可安排稍后续聊。"
                    "limit_reached" -> "连续主动续聊已达上限，收到你的新消息后再继续。"
                    "unsupported" -> "这里只显示当前模式的运行情况。"
                    "none" -> "目前没有已保存的续聊安排，后续会随对话变化。"
                    "sent", "cancelled", "expired", "failed" -> "目前没有新的续聊安排。"
                    else -> "暂时无法确认角色是否安排了稍后续聊。"
                }, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                HorizontalDivider()
                ActivityRow("当前回复", reply)
                if (mode == "normal") {
                    ActivityRow("主动消息", when (activity?.proactiveEnabled) { true -> "已开启"; false -> "已关闭"; null -> "未知" })
                    ActivityRow("记忆整理", when {
                        activity?.memoryEnabled == false -> "已关闭"
                        agents.any { it.phase == "background_memory" && it.status == "running" } -> "正在整理"
                        activity?.memoryEnabled == true -> "当前空闲"
                        else -> "未知"
                    })
                    if ((activity?.consecutiveLimit ?: 0) > 0) {
                        ActivityRow("连续续聊", "${activity!!.consecutiveCount} / ${activity.consecutiveLimit} 轮")
                    }
                }
                snapshot.notice?.let {
                    val text = if (snapshot.noticeIsError && activity != null)
                        "$it；有显示的数据为上次获取的状态" else it
                    Text(text, style = MaterialTheme.typography.bodySmall,
                        color = if (snapshot.noticeIsError) MaterialTheme.colorScheme.error
                            else MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        }
    }
}

@Composable
private fun ActivityRow(label: String, value: String) {
    Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        Text(label, Modifier.width(72.dp), style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(value, Modifier.weight(1f), style = MaterialTheme.typography.bodySmall)
    }
}
