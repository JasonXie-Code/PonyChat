package top.ponychat.webview.ui.settings

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AdminPanelSettings
import androidx.compose.material.icons.filled.ChatBubbleOutline
import androidx.compose.material.icons.filled.Code
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.WorkspacePremium
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import top.ponychat.webview.data.model.QuotaInfo
import top.ponychat.webview.ui.theme.Primary

/** 上下文用量表格：仅输入/输出（服务端已合并主对话与陪玩） */
@Composable
internal fun ContextUsageTable(
    inputTokens: Long,
    outputTokens: Long
) {
    val mergedTotalTokens = inputTokens + outputTokens
    val inputCost = inputTokens / 1_000_000.0 * 2.0
    val outputCost = outputTokens / 1_000_000.0 * 10.0
    val totalCost = inputCost + outputCost

    val surfaceVariant = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.6f)
    val borderColor = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.15f)
    val headerColor = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.9f)
    val headerStyle = MaterialTheme.typography.labelMedium
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(8.dp))
            .background(surfaceVariant)
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.8f))
                .padding(horizontal = 12.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text("指标", style = headerStyle, fontWeight = FontWeight.SemiBold, color = headerColor, modifier = Modifier.weight(2f))
            Text("Token 数", style = headerStyle, fontWeight = FontWeight.SemiBold, color = headerColor, modifier = Modifier.weight(2.5f), textAlign = TextAlign.End)
            Text("费用 (¥)", style = headerStyle, fontWeight = FontWeight.SemiBold, color = headerColor, modifier = Modifier.weight(1.8f), textAlign = TextAlign.End)
        }
        HorizontalDivider(color = borderColor, thickness = 1.dp)
        listOf(
            Triple("输入", inputTokens, inputCost),
            Triple("输出", outputTokens, outputCost)
        ).forEach { (label, value, cost) ->
            ContextUsageTableRow(label, value, cost)
        }
        HorizontalDivider(color = borderColor, thickness = 1.dp)
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f))
                .padding(horizontal = 12.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(
                "合计",
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.SemiBold,
                color = MaterialTheme.colorScheme.onBackground,
                modifier = Modifier.weight(2f)
            )
            Text(
                String.format("%,d", mergedTotalTokens),
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.SemiBold,
                color = Primary,
                modifier = Modifier.weight(2.5f),
                textAlign = TextAlign.End
            )
            Text(
                formatCost(totalCost),
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.SemiBold,
                color = Primary,
                modifier = Modifier.weight(1.8f),
                textAlign = TextAlign.End
            )
        }
    }
}

private fun formatCost(cost: Double): String =
    if (cost < 0.01 && cost > 0) String.format("¥%.4f", cost) else String.format("¥%.2f", cost)

@Composable
private fun ContextUsageTableRow(label: String, value: Long, cost: Double) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 12.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Text(
            label,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurface,
            modifier = Modifier.weight(2f)
        )
        Text(
            String.format("%,d", value),
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            fontWeight = FontWeight.Medium,
            modifier = Modifier.weight(2.5f),
            textAlign = TextAlign.End
        )
        Text(
            formatCost(cost),
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            fontWeight = FontWeight.Medium,
            modifier = Modifier.weight(1.8f),
            textAlign = TextAlign.End
        )
    }
}

@Composable
internal fun MembershipCard(
    quotaInfo: QuotaInfo?,
    isLoading: Boolean,
    fallbackMembershipType: String = "free"
) {
    val tierKey = quotaInfo?.membershipType
        ?: if (!isLoading) fallbackMembershipType else null
    val accentColor = when (tierKey) {
        "pro" -> Color(0xFFD97706)
        "pro_plus" -> Color(0xFF7C3AED)
        "developer" -> Color(0xFF10B981)
        "admin" -> Color(0xFF0EA5E9)
        else -> Color(0xFF6B7280)
    }
    val tierIcon = when (tierKey) {
        "pro", "pro_plus" -> Icons.Filled.WorkspacePremium
        "developer" -> Icons.Filled.Code
        "admin" -> Icons.Filled.AdminPanelSettings
        else -> Icons.Filled.Person
    }
    val tierLabel = when (tierKey) {
        "pro" -> "Pro"
        "pro_plus" -> "Pro+"
        "developer" -> "开发者"
        "admin" -> "管理员"
        "free" -> "免费用户"
        null -> "—"
        else -> tierKey
    }

    SettingsScreenCard {
        Column(modifier = Modifier.padding(horizontal = 16.dp, vertical = 14.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(
                    tierIcon,
                    contentDescription = null,
                    tint = accentColor,
                    modifier = Modifier.size(22.dp)
                )
                Spacer(Modifier.width(10.dp))
                Text(
                    "订阅等级",
                    style = MaterialTheme.typography.titleSmall,
                    color = MaterialTheme.colorScheme.onBackground,
                    modifier = Modifier.weight(1f)
                )
                if (isLoading) {
                    CircularProgressIndicator(
                        modifier = Modifier.size(16.dp),
                        strokeWidth = 2.dp,
                        color = accentColor
                    )
                } else {
                    Surface(
                        shape = RoundedCornerShape(20.dp),
                        color = accentColor.copy(alpha = 0.15f)
                    ) {
                        Text(
                            text = tierLabel,
                            style = MaterialTheme.typography.labelMedium,
                            fontWeight = FontWeight.SemiBold,
                            color = accentColor,
                            modifier = Modifier.padding(horizontal = 10.dp, vertical = 4.dp)
                        )
                    }
                }
            }

            if (!isLoading && quotaInfo?.expireAt != null && tierKey != null && tierKey != "free") {
                Spacer(Modifier.height(6.dp))
                Text(
                    "到期：${quotaInfo.expireAt.take(10)}",
                    style = MaterialTheme.typography.bodySmall,
                    color = accentColor.copy(alpha = 0.8f)
                )
            }

            Spacer(Modifier.height(14.dp))
            HorizontalDivider(color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.1f))
            Spacer(Modifier.height(12.dp))

            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(
                    Icons.Filled.ChatBubbleOutline,
                    contentDescription = null,
                    tint = Primary,
                    modifier = Modifier.size(20.dp)
                )
                Spacer(Modifier.width(10.dp))
                Text(
                    "今日积分",
                    style = MaterialTheme.typography.titleSmall,
                    color = MaterialTheme.colorScheme.onBackground,
                    modifier = Modifier.weight(1f)
                )
                if (!isLoading && quotaInfo != null) {
                    Text(
                        "${quotaInfo.usedToday} / ${quotaInfo.dailyLimit} 分",
                        style = MaterialTheme.typography.labelMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }

            if (!isLoading && quotaInfo != null) {
                Spacer(Modifier.height(8.dp))
                val progress = if (quotaInfo.dailyLimit > 0) {
                    (quotaInfo.usedToday.toFloat() / quotaInfo.dailyLimit).coerceIn(0f, 1f)
                } else {
                    0f
                }
                val animatedProgress by animateFloatAsState(
                    targetValue = progress,
                    animationSpec = tween(600),
                    label = "quota_progress"
                )
                val barColor = when {
                    progress >= 0.9f -> Color(0xFFEF4444)
                    progress >= 0.7f -> Color(0xFFF97316)
                    else -> Primary
                }
                LinearProgressIndicator(
                    progress = { animatedProgress },
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(6.dp)
                        .clip(RoundedCornerShape(3.dp)),
                    color = barColor,
                    trackColor = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.12f)
                )
                Spacer(Modifier.height(6.dp))
                Text(
                    text = if (quotaInfo.remaining > 0) {
                        "今日剩余 ${quotaInfo.remaining} 分"
                    } else {
                        "今日积分已用完"
                    },
                    style = MaterialTheme.typography.bodySmall,
                    color = if (quotaInfo.remaining > 0) {
                        MaterialTheme.colorScheme.onSurfaceVariant.copy(0.7f)
                    } else {
                        Color(0xFFEF4444)
                    }
                )
            } else if (isLoading) {
                Spacer(Modifier.height(8.dp))
                LinearProgressIndicator(
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(6.dp)
                        .clip(RoundedCornerShape(3.dp)),
                    color = Primary,
                    trackColor = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.12f)
                )
            }
        }
    }
}
