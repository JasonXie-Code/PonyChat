package top.ponychat.webview.ui.doudizhu

import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.SmartToy
import androidx.compose.material3.Icon
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

@Composable
internal fun DoudizhuOpponentSeat(
    seat: DdzSeat,
    name: String,
    avatar: @Composable () -> Unit,
    cardCount: Int,
    score: Int,
    isLandlord: Boolean,
    isTurn: Boolean,
    isThinking: Boolean,
    isWinner: Boolean,
    reverse: Boolean,
    compact: Boolean,
    modifier: Modifier = Modifier
) {
    val pulse by rememberInfiniteTransition(label = "ddzThinking").animateFloat(
        initialValue = 0.45f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(tween(700), RepeatMode.Reverse),
        label = "ddzThinkingAlpha"
    )
    val seatShape = RoundedCornerShape(12.dp)
    val borderColor = if (isTurn) {
        Color(0xFFFFD45A).copy(alpha = if (isThinking) 0.84f + pulse * 0.16f else 1f)
    } else {
        Color(0xFFFFE6B2).copy(alpha = 0.26f)
    }
    val seatColor = if (isThinking) Color(0xFF3A2114) else Color(0xFF28150D)
    Surface(
        color = seatColor,
        shape = seatShape,
        border = BorderStroke(if (isTurn) 2.dp else 1.dp, borderColor),
        shadowElevation = if (isTurn) 8.dp else 2.dp,
        modifier = modifier.clip(seatShape)
    ) {
        Box(modifier = Modifier.fillMaxSize()) {
            OpponentSeatInfoMask(reverse = reverse, compact = compact, isThinking = isThinking)
            Row(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(horizontal = if (compact) 8.dp else 10.dp, vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                if (reverse) {
                    HiddenCardCount(count = cardCount, compact = compact)
                } else {
                    avatar()
                }
                Column(
                    modifier = Modifier.weight(1f),
                    horizontalAlignment = if (reverse) Alignment.End else Alignment.Start
                ) {
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(5.dp)
                    ) {
                        if (reverse && isLandlord) LandlordBadge()
                        Text(
                            text = name,
                            color = Color(0xFFFFEA70),
                            fontWeight = FontWeight.Black,
                            fontSize = if (compact) 13.sp else 15.sp,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis
                        )
                        if (!reverse && isLandlord) LandlordBadge()
                        if (isWinner) WinnerBadge()
                    }
                    Text(
                        text = if (isThinking) "思考中" else "$cardCount 张 · 胜 $score",
                        color = Color(0xFFFFF1D6).copy(alpha = 0.92f),
                        fontSize = 11.sp,
                        fontWeight = FontWeight.SemiBold,
                        maxLines = 1
                    )
                    Text(
                        text = when (seat) {
                            DdzSeat.Character -> "角色玩家"
                            DdzSeat.Robot -> "独立机器人"
                            DdzSeat.User -> "你"
                        },
                        color = Color(0xFFFFE6B2).copy(alpha = 0.70f),
                        fontSize = 10.sp,
                        maxLines = 1
                    )
                }
                if (reverse) {
                    avatar()
                } else {
                    HiddenCardCount(count = cardCount, compact = compact)
                }
            }
        }
    }
}

@Composable
private fun OpponentSeatInfoMask(reverse: Boolean, compact: Boolean, isThinking: Boolean) {
    val cardInset = if (compact) 38.dp else 52.dp
    val avatarCenterInset = if (compact) 31.dp else 37.dp
    val avatarDiameter = if (compact) 46.dp else 54.dp
    val maskColor = Color(0xFFFFE6B2).copy(alpha = if (isThinking) 0.11f else 0.08f)
    Canvas(modifier = Modifier.fillMaxSize()) {
        val start = if (reverse) cardInset.toPx() else avatarCenterInset.toPx()
        val end = if (reverse) size.width - avatarCenterInset.toPx() else size.width - cardInset.toPx()
        val height = avatarDiameter.toPx().coerceAtMost(size.height)
        val top = (size.height - height) / 2f
        drawRect(
            color = maskColor,
            topLeft = Offset(start, top),
            size = Size((end - start).coerceAtLeast(0f), height)
        )
    }
}

@Composable
private fun HiddenCardCount(count: Int, compact: Boolean) {
    Box(
        modifier = Modifier.size(
            width = if (compact) 48.dp else 58.dp,
            height = if (compact) 62.dp else 74.dp
        ),
        contentAlignment = Alignment.Center
    ) {
        DdzCardBack(modifier = Modifier.fillMaxSize())
        Text(
            text = count.toString(),
            color = Color.White,
            fontWeight = FontWeight.Black,
            fontSize = if (compact) 19.sp else 23.sp
        )
    }
}

@Composable
internal fun RobotAvatar(size: Dp) {
    Surface(
        shape = CircleShape,
        color = Color(0xFFE1EFE7),
        border = BorderStroke(2.dp, Color.White.copy(alpha = 0.65f)),
        shadowElevation = 3.dp,
        modifier = Modifier.size(size)
    ) {
        Box(contentAlignment = Alignment.Center, modifier = Modifier.fillMaxSize()) {
            Icon(
                Icons.Filled.SmartToy,
                contentDescription = "机器人",
                tint = Color(0xFF2E604E),
                modifier = Modifier.size(size * 0.56f)
            )
        }
    }
}

@Composable
internal fun LandlordBadge() {
    Text(
        text = "地主",
        color = Color.White,
        fontSize = 10.sp,
        fontWeight = FontWeight.Black,
        modifier = Modifier
            .clip(RoundedCornerShape(999.dp))
            .background(Color(0xFFD84524))
            .padding(horizontal = 6.dp, vertical = 2.dp)
    )
}

@Composable
internal fun WinnerBadge() {
    Text(
        text = "胜",
        color = Color(0xFF2C2520),
        fontSize = 10.sp,
        fontWeight = FontWeight.Black,
        modifier = Modifier
            .clip(RoundedCornerShape(999.dp))
            .background(Color(0xFFFFE34E))
            .padding(horizontal = 6.dp, vertical = 2.dp)
    )
}
