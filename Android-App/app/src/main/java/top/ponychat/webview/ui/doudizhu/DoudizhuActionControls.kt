package top.ponychat.webview.ui.doudizhu

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

@Composable
internal fun ActionWord(text: String, color: Color, compact: Boolean, modifier: Modifier = Modifier) {
    Surface(
        color = Color.Black.copy(alpha = 0.42f),
        shape = RoundedCornerShape(999.dp),
        modifier = modifier
    ) {
        Text(
            text = text,
            color = color,
            fontSize = if (compact) 18.sp else 22.sp,
            fontWeight = FontWeight.Black,
            modifier = Modifier.padding(horizontal = 14.dp, vertical = 4.dp)
        )
    }
}

@Composable
internal fun DoudizhuActionDock(
    game: DdzGameState,
    canPlaySelection: Boolean,
    actionSecondsLeft: Int,
    actionsEnabled: Boolean,
    aiThinkingSeat: DdzSeat?,
    compact: Boolean,
    onCallLandlord: () -> Unit,
    onPassLandlord: () -> Unit,
    onHint: () -> Unit,
    onPlay: () -> Unit,
    onPass: () -> Unit,
    onNewRound: () -> Unit,
    modifier: Modifier = Modifier
) {
    Box(
        modifier = modifier,
        contentAlignment = Alignment.Center
    ) {
        when (game.phase) {
            DdzPhase.Bidding -> {
                if (actionsEnabled) {
                    ClockPill(
                        text = actionSecondsLeft.coerceAtLeast(0).toString(),
                        compact = compact,
                        modifier = Modifier
                            .align(Alignment.Center)
                            .offset(x = clockOffset(buttonCount = 2, buttonGap = 18.dp, compact = compact))
                    )
                }
                Row(
                    horizontalArrangement = Arrangement.spacedBy(18.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    modifier = Modifier.align(Alignment.Center)
                ) {
                    ArcadeButton(
                        text = "不叫",
                        primary = Color(0xFF2EB9E8),
                        secondary = Color(0xFF0B73BD),
                        enabled = actionsEnabled,
                        compact = compact,
                        onClick = onPassLandlord
                    )
                    ArcadeButton(
                        text = "叫地主",
                        primary = Color(0xFFD18400),
                        secondary = Color(0xFF8A4A00),
                        enabled = actionsEnabled,
                        compact = compact,
                        onClick = onCallLandlord
                    )
                }
            }
            DdzPhase.Playing -> {
                val showUserActions = actionsEnabled && game.turn == DdzSeat.User && game.winner == null && aiThinkingSeat == null
                if (showUserActions) {
                    ClockPill(
                        text = actionSecondsLeft.coerceAtLeast(0).toString(),
                        compact = compact,
                        modifier = Modifier
                            .align(Alignment.Center)
                            .offset(x = clockOffset(buttonCount = 3, buttonGap = 12.dp, compact = compact))
                    )
                    Row(
                        horizontalArrangement = Arrangement.spacedBy(12.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        modifier = Modifier.align(Alignment.Center)
                    ) {
                        ArcadeButton(
                            text = "不出",
                            primary = Color(0xFF2EB9E8),
                            secondary = Color(0xFF0B73BD),
                            enabled = game.activeCombo != null,
                            compact = compact,
                            onClick = onPass
                        )
                        ArcadeButton(
                            text = "提示",
                            primary = Color(0xFF776BFF),
                            secondary = Color(0xFF3D35B6),
                            enabled = true,
                            compact = compact,
                            onClick = onHint
                        )
                        ArcadeButton(
                            text = "出牌",
                            primary = Color(0xFFD18400),
                            secondary = Color(0xFF8A4A00),
                            enabled = canPlaySelection,
                            compact = compact,
                            onClick = onPlay
                        )
                    }
                }
            }
            DdzPhase.RoundOver -> ArcadeButton(
                text = "再来一局",
                primary = Color(0xFFD18400),
                secondary = Color(0xFF8A4A00),
                enabled = true,
                compact = compact,
                onClick = onNewRound
            )
        }
    }
}

private fun clockOffset(buttonCount: Int, buttonGap: Dp, compact: Boolean): Dp {
    val buttonWidth = if (compact) 94.dp else 110.dp
    val clockSize = if (compact) 48.dp else 58.dp
    val clockGap = if (compact) 14.dp else 18.dp
    val buttonsWidth = buttonWidth * buttonCount + buttonGap * (buttonCount - 1)
    return -(buttonsWidth / 2f + clockSize / 2f + clockGap)
}

@Composable
private fun ArcadeButton(
    text: String,
    primary: Color,
    secondary: Color,
    enabled: Boolean,
    compact: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    textColor: Color = Color.White
) {
    val fontScale = LocalDensity.current.fontScale.coerceAtLeast(1f)
    val baseFontSize = when {
        text.length >= 4 -> if (compact) 14f else 17f
        text.length >= 3 -> if (compact) 15f else 18f
        else -> if (compact) 16f else 19f
    }
    val buttonFontSize = (baseFontSize / fontScale).sp
    Button(
        onClick = onClick,
        enabled = enabled,
        colors = ButtonDefaults.buttonColors(
            containerColor = primary,
            contentColor = textColor,
            disabledContainerColor = Color(0xFF6F5639).copy(alpha = 0.82f),
            disabledContentColor = Color.White.copy(alpha = 0.72f)
        ),
        elevation = ButtonDefaults.buttonElevation(defaultElevation = 6.dp, pressedElevation = 2.dp),
        shape = RoundedCornerShape(999.dp),
        border = BorderStroke(
            2.dp,
            if (enabled) secondary.copy(alpha = 0.95f) else Color(0xFFFFD28A).copy(alpha = 0.46f)
        ),
        contentPadding = PaddingValues(horizontal = if (compact) 10.dp else 14.dp, vertical = 0.dp),
        modifier = modifier
            .width(if (compact) 94.dp else 110.dp)
            .height(if (compact) 42.dp else 48.dp)
    ) {
        Text(
            text = text,
            fontSize = buttonFontSize,
            lineHeight = buttonFontSize,
            fontWeight = FontWeight.Black,
            maxLines = 1,
            overflow = TextOverflow.Clip,
            softWrap = false,
            textAlign = TextAlign.Center
        )
    }
}

@Composable
private fun ClockPill(text: String, compact: Boolean, modifier: Modifier = Modifier) {
    Surface(
        color = Color(0xFFFFF6D5),
        shape = CircleShape,
        border = BorderStroke(3.dp, Color(0xFFE58019)),
        shadowElevation = 6.dp,
        modifier = modifier.size(if (compact) 48.dp else 58.dp)
    ) {
        Box(contentAlignment = Alignment.Center, modifier = Modifier.fillMaxSize()) {
            Text(
                text = text,
                color = Color(0xFF2C2520),
                fontWeight = FontWeight.Black,
                fontSize = if (compact) 20.sp else 24.sp
            )
        }
    }
}
