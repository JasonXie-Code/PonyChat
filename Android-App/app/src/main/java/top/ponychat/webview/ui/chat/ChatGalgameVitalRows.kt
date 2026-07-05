package top.ponychat.webview.ui.chat

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
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
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlin.math.abs

@Composable
internal fun VitalsSectionHeader(
    title: String,
    accentColor: Color,
    bgColor: Color,
    titleColor: Color = accentColor
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(8.dp))
            .background(bgColor)
            .padding(vertical = 8.dp, horizontal = 10.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Box(
            modifier = Modifier
                .width(3.dp)
                .height(16.dp)
                .background(accentColor, RoundedCornerShape(2.dp))
        )
        Spacer(Modifier.width(8.dp))
        Text(
            title,
            style = MaterialTheme.typography.labelLarge,
            fontWeight = FontWeight.SemiBold,
            color = titleColor
        )
    }
}

@Composable
internal fun VitalBarRow(
    label: String,
    value: Int?,
    isReverse: Boolean,
    isBiDirectional: Boolean = false,
    delta: Int? = null
) {
    val safeValue = value ?: 0
    val progress = safeValue / 100f
    val dangerLevel = when {
        isBiDirectional -> {
            val deviation = abs(safeValue - 50)
            when {
                deviation >= 45 -> 2
                deviation >= 35 -> 1
                else -> 0
            }
        }
        isReverse -> when {
            safeValue >= 85 -> 2
            safeValue >= 60 -> 1
            else -> 0
        }
        else -> when {
            safeValue <= 15 -> 2
            safeValue <= 30 -> 1
            else -> 0
        }
    }
    val barColor = when (dangerLevel) {
        2 -> Color(0xFFEF5350)
        1 -> Color(0xFFFFB300)
        else -> Color(0xFF66BB6A)
    }
    val rowBg = if (dangerLevel == 2) Color(0xFFEF5350).copy(alpha = 0.08f) else Color.Transparent
    val barStartPadding = 90.dp
    val showDelta = delta != null && delta != 0

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(6.dp))
            .background(rowBg)
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(10.dp)
                .padding(start = barStartPadding),
            contentAlignment = Alignment.BottomStart
        ) {
            if (showDelta) {
                val deltaColor = if (delta!! > 0) Color(0xFF4CAF50) else Color(0xFFEF5350)
                val deltaText = if (delta > 0) "+$delta" else "$delta"
                Text(
                    text = deltaText,
                    fontSize = 7.sp,
                    fontWeight = FontWeight.Bold,
                    color = deltaColor,
                    lineHeight = 8.sp,
                    modifier = Modifier
                        .background(deltaColor.copy(alpha = 0.13f), RoundedCornerShape(3.dp))
                        .padding(horizontal = 2.dp, vertical = 0.dp)
                )
            }
        }

        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(start = 8.dp, end = 8.dp, top = 0.dp, bottom = 1.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(
                label,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.width(48.dp)
            )
            Text(
                if (value != null) "$safeValue" else "--",
                style = MaterialTheme.typography.bodySmall,
                fontWeight = FontWeight.Medium,
                color = barColor,
                modifier = Modifier.width(28.dp),
                textAlign = TextAlign.End
            )
            Spacer(Modifier.width(6.dp))
            LinearProgressIndicator(
                progress = { progress },
                modifier = Modifier
                    .weight(1f)
                    .height(6.dp)
                    .clip(RoundedCornerShape(3.dp)),
                color = barColor,
                trackColor = barColor.copy(alpha = 0.18f),
                strokeCap = StrokeCap.Round
            )
            Spacer(Modifier.width(6.dp))
            val iconTint = when (dangerLevel) {
                2 -> Color(0xFFEF5350)
                1 -> Color(0xFFFFB300)
                else -> Color(0xFF66BB6A)
            }
            Icon(
                imageVector = when (dangerLevel) {
                    2 -> Icons.Filled.Warning
                    1 -> Icons.Filled.Warning
                    else -> Icons.Filled.CheckCircle
                },
                contentDescription = null,
                tint = iconTint.copy(alpha = if (dangerLevel == 0) 0.55f else 0.9f),
                modifier = Modifier.size(14.dp)
            )
        }
    }
}
