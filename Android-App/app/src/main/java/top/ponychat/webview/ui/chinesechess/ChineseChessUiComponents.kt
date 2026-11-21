package top.ponychat.webview.ui.chinesechess

import android.graphics.Typeface
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.VolumeUp
import androidx.compose.material.icons.filled.ArrowUpward
import androidx.compose.material.icons.filled.ChatBubbleOutline
import androidx.compose.material.icons.filled.MoreHoriz
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.drawIntoCanvas
import androidx.compose.ui.graphics.nativeCanvas
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Popup
import androidx.compose.ui.window.PopupProperties
import kotlinx.coroutines.delay
import kotlin.math.roundToInt
import top.ponychat.webview.ui.common.PonyAvatar

@Composable
internal fun ChessPowerTierBadge(tier: ChessPowerTier) {
    val color = when (tier) {
        ChessPowerTier.Novice -> Color(0xFF2FA866)
        ChessPowerTier.Junior -> Color(0xFF6B5CFF)
        ChessPowerTier.Intermediate -> Color(0xFFD04747)
        ChessPowerTier.Advanced -> Color(0xFFC89118)
    }
    Surface(
        color = color,
        shape = RoundedCornerShape(999.dp)
    ) {
        Text(
            text = tier.label,
            style = MaterialTheme.typography.labelSmall,
            fontWeight = FontWeight.SemiBold,
            color = Color.White,
            maxLines = 1,
            modifier = Modifier.padding(horizontal = 8.dp, vertical = 2.dp)
        )
    }
}

@Composable
internal fun OpponentPanel(
    name: String,
    avatarUrl: String,
    apiBase: String,
    side: Side,
    powerTier: ChessPowerTier?,
    message: String,
    isThinking: Boolean,
    winner: Side?,
    bubbleText: String,
    supportsVoice: Boolean,
    voiceReplyEnabled: Boolean,
    onVoiceReplyToggle: () -> Unit
) {
    val bubbleVerticalPadding = 9.dp
    val bubbleTwoLineHeight = with(LocalDensity.current) { (24.sp * 2).toDp() } + bubbleVerticalPadding * 2
    var thinkingDotCount by remember { mutableStateOf(1) }
    LaunchedEffect(isThinking) {
        if (!isThinking) {
            thinkingDotCount = 1
            return@LaunchedEffect
        }
        thinkingDotCount = 1
        while (true) {
            delay(420L)
            thinkingDotCount = if (thinkingDotCount >= 3) 1 else thinkingDotCount + 1
        }
    }
    Surface(
        color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.54f),
        shape = RoundedCornerShape(12.dp),
        modifier = Modifier.fillMaxWidth()
    ) {
        Column(
            modifier = Modifier.padding(horizontal = 12.dp, vertical = 10.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(10.dp)
            ) {
                PonyAvatar(
                    avatarUrl = avatarUrl,
                    name = name,
                    apiBase = apiBase,
                    size = 42
                )
                Column(modifier = Modifier.weight(1f)) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(7.dp)
                    ) {
                        Text(
                            text = name,
                            style = MaterialTheme.typography.titleSmall,
                            fontWeight = FontWeight.SemiBold,
                            color = MaterialTheme.colorScheme.onSurface,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                            modifier = Modifier.weight(1f, fill = false)
                        )
                        if (powerTier != null) {
                            ChessPowerTierBadge(powerTier)
                        }
                    }
                    Text(
                        text = opponentSideText(side, isThinking, thinkingDotCount),
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
                Text(
                    text = winner?.let { "${it.label}胜" } ?: message,
                    style = MaterialTheme.typography.labelMedium,
                    color = if (winner == Side.Red) RedPiece else MaterialTheme.colorScheme.onSurfaceVariant,
                    textAlign = TextAlign.End
                )
            }
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(10.dp)
            ) {
                Surface(
                    color = MaterialTheme.colorScheme.surface,
                    shape = RoundedCornerShape(
                        topStart = 4.dp,
                        topEnd = 14.dp,
                        bottomStart = 14.dp,
                        bottomEnd = 14.dp
                    ),
                    modifier = Modifier
                        .weight(1f)
                        .height(bubbleTwoLineHeight)
                ) {
                    Text(
                        text = bubbleText,
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurface,
                        minLines = 2,
                        maxLines = 2,
                        overflow = TextOverflow.Clip,
                        modifier = Modifier.padding(horizontal = 12.dp, vertical = bubbleVerticalPadding)
                    )
                }
                if (supportsVoice) {
                    Surface(
                        onClick = onVoiceReplyToggle,
                        color = if (voiceReplyEnabled) {
                            MaterialTheme.colorScheme.primary.copy(alpha = 0.18f)
                        } else {
                            Color.Transparent
                        },
                        shape = RoundedCornerShape(12.dp),
                        modifier = Modifier.size(44.dp)
                    ) {
                        Box(contentAlignment = Alignment.Center, modifier = Modifier.fillMaxSize()) {
                            Icon(
                                imageVector = Icons.AutoMirrored.Filled.VolumeUp,
                                contentDescription = if (voiceReplyEnabled) "关闭角色语音回复" else "开启角色语音回复",
                                tint = if (voiceReplyEnabled) {
                                    MaterialTheme.colorScheme.primary
                                } else {
                                    MaterialTheme.colorScheme.onSurfaceVariant
                                },
                                modifier = Modifier.size(23.dp)
                            )
                        }
                    }
                }
            }
        }
    }
}

@Composable
internal fun XiangqiGameOverDialog(
    winner: Side,
    playerSide: Side,
    onDismiss: () -> Unit,
    onNewGame: () -> Unit,
    modifier: Modifier = Modifier
) {
    val playerWon = winner == playerSide
    Surface(
        color = MaterialTheme.colorScheme.surface,
        shape = RoundedCornerShape(14.dp),
        modifier = modifier.fillMaxWidth()
    ) {
        Column(
            modifier = Modifier.padding(horizontal = 18.dp, vertical = 16.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp)
        ) {
            Text(
                text = if (playerWon) "你赢了" else "${winner.label}胜",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
                color = MaterialTheme.colorScheme.onSurface
            )
            Text(
                text = "下一局换你执${playerSide.opponent.label}",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(10.dp)
            ) {
                XiangqiDialogActionButton(
                    text = "关闭",
                    onClick = onDismiss,
                    primary = false,
                    modifier = Modifier.weight(1f)
                )
                XiangqiDialogActionButton(
                    text = "再来一局",
                    onClick = onNewGame,
                    primary = true,
                    modifier = Modifier.weight(1f)
                )
            }
        }
    }
}

@Composable
internal fun XiangqiUndoRequestDialog(
    request: XiangqiPendingUndoRequest,
    characterName: String,
    onCancel: () -> Unit,
    onApprove: () -> Unit,
    onReject: () -> Unit,
    modifier: Modifier = Modifier
) {
    val isCharacterRequest = request.requester == XiangqiUndoRequester.Character
    val title = if (isCharacterRequest) "${characterName}申请悔棋" else "申请悔棋"
    val subtitle = if (isCharacterRequest) {
        request.reason.ifBlank { "撤回刚才那一步" }
    } else {
        "请再给我一次机会"
    }
    Surface(
        color = MaterialTheme.colorScheme.surface,
        shape = RoundedCornerShape(14.dp),
        modifier = modifier.fillMaxWidth()
    ) {
        Column(
            modifier = Modifier.padding(horizontal = 18.dp, vertical = 16.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp)
        ) {
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(
                    text = title,
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                    color = MaterialTheme.colorScheme.onSurface
                )
                Text(
                    text = subtitle,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 3,
                    overflow = TextOverflow.Ellipsis
                )
            }
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(10.dp)
            ) {
                if (isCharacterRequest) {
                    XiangqiDialogActionButton(
                        text = "拒绝",
                        onClick = onReject,
                        primary = false,
                        modifier = Modifier.weight(1f)
                    )
                    XiangqiDialogActionButton(
                        text = "同意",
                        onClick = onApprove,
                        primary = true,
                        modifier = Modifier.weight(1f)
                    )
                } else {
                    XiangqiDialogActionButton(
                        text = "取消",
                        onClick = onCancel,
                        primary = false,
                        modifier = Modifier.weight(1f)
                    )
                }
            }
        }
    }
}

@Composable
private fun XiangqiDialogActionButton(
    text: String,
    onClick: () -> Unit,
    primary: Boolean,
    modifier: Modifier = Modifier
) {
    Surface(
        onClick = onClick,
        color = if (primary) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.surfaceVariant,
        shape = RoundedCornerShape(8.dp),
        modifier = modifier
    ) {
        Text(
            text = text,
            style = MaterialTheme.typography.labelLarge,
            fontWeight = if (primary) FontWeight.SemiBold else FontWeight.Medium,
            color = if (primary) MaterialTheme.colorScheme.onPrimary else MaterialTheme.colorScheme.onSurface,
            textAlign = TextAlign.Center,
            modifier = Modifier.padding(horizontal = 12.dp, vertical = 10.dp)
        )
    }
}

@Composable
internal fun ChessBattleBottomBar(
    name: String,
    avatarUrl: String,
    apiBase: String,
    playerSide: Side,
    messageExpanded: Boolean,
    userInput: String,
    onUserInputChange: (String) -> Unit,
    onToggleMessage: () -> Unit,
    onSend: () -> Unit,
    canUndo: Boolean,
    onUndo: () -> Unit,
    canSurrender: Boolean,
    onSurrender: () -> Unit,
    onRestart: () -> Unit,
    onFlipBoard: () -> Unit,
    onPlayerSideChange: (Side) -> Unit
) {
    var moreExpanded by remember { mutableStateOf(false) }
    val density = LocalDensity.current
    val menuPositionProvider = remember(density) {
        AboveAnchorMenuPositionProvider(
            verticalGapPx = with(density) { 6.dp.roundToPx() },
            screenMarginPx = with(density) { 8.dp.roundToPx() }
        )
    }
    Surface(
        color = MaterialTheme.colorScheme.surface,
        shadowElevation = 8.dp,
        modifier = Modifier.fillMaxWidth()
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .imePadding()
                .navigationBarsPadding()
                .padding(horizontal = 14.dp, vertical = 8.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(4.dp)
            ) {
                Box {
                    IconButton(onClick = { moreExpanded = true }) {
                        Icon(Icons.Filled.MoreHoriz, contentDescription = "更多")
                    }
                    if (moreExpanded) {
                        Popup(
                            popupPositionProvider = menuPositionProvider,
                            onDismissRequest = { moreExpanded = false },
                            properties = PopupProperties(focusable = true)
                        ) {
                            Surface(
                                color = MaterialTheme.colorScheme.surface,
                                shape = RoundedCornerShape(4.dp),
                                shadowElevation = 8.dp,
                                modifier = Modifier.width(144.dp)
                            ) {
                                Column(modifier = Modifier.padding(vertical = 4.dp)) {
                                    DropdownMenuItem(
                                        text = { Text("重新开始") },
                                        onClick = {
                                            moreExpanded = false
                                            onRestart()
                                        }
                                    )
                                    DropdownMenuItem(
                                        text = { Text("调转方向") },
                                        onClick = {
                                            moreExpanded = false
                                            onFlipBoard()
                                        }
                                    )
                                    DropdownMenuItem(
                                        text = { Text("申请悔棋") },
                                        enabled = canUndo,
                                        onClick = {
                                            moreExpanded = false
                                            onUndo()
                                        }
                                    )
                                    DropdownMenuItem(
                                        text = { Text("认输投降") },
                                        enabled = canSurrender,
                                        onClick = {
                                            moreExpanded = false
                                            onSurrender()
                                        }
                                    )
                                    HorizontalDivider()
                                    DropdownMenuItem(
                                        text = { Text("我执${playerSide.opponent.label}") },
                                        onClick = {
                                            moreExpanded = false
                                            onPlayerSideChange(playerSide.opponent)
                                        }
                                    )
                                }
                            }
                        }
                    }
                }
                IconButton(
                    onClick = onToggleMessage
                ) {
                    Icon(
                        Icons.Filled.ChatBubbleOutline,
                        contentDescription = "消息",
                        tint = if (messageExpanded) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurface
                    )
                }
                Spacer(modifier = Modifier.weight(1f))
                Column(horizontalAlignment = Alignment.End) {
                    Text(
                        text = name,
                        style = MaterialTheme.typography.titleSmall,
                        fontWeight = FontWeight.SemiBold,
                        color = MaterialTheme.colorScheme.onSurface,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis
                    )
                    Text(
                        text = "执${playerSide.label}",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
                Spacer(modifier = Modifier.width(10.dp))
                PonyAvatar(
                    avatarUrl = avatarUrl,
                    name = name,
                    apiBase = apiBase,
                    size = 40
                )
            }
            if (messageExpanded) {
                HorizontalDivider(color = MaterialTheme.colorScheme.outline.copy(alpha = 0.12f))
                ChessMessageComposer(
                    userInput = userInput,
                    onUserInputChange = onUserInputChange,
                    onSend = onSend
                )
            }
        }
    }
}

@Composable
internal fun ChessMessageComposer(
    userInput: String,
    onUserInputChange: (String) -> Unit,
    onSend: () -> Unit
) {
    val inputBarContainerColor = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.6f)
    val inputFieldContainerColor = MaterialTheme.colorScheme.background.copy(alpha = 0.58f)
    val canSend = userInput.isNotBlank()
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.Bottom,
        horizontalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        Surface(
            color = inputFieldContainerColor,
            shape = RoundedCornerShape(22.dp),
            tonalElevation = 0.dp,
            modifier = Modifier
                .weight(1f)
                .height(44.dp)
        ) {
            BasicTextField(
                value = userInput,
                onValueChange = onUserInputChange,
                singleLine = true,
                textStyle = MaterialTheme.typography.titleSmall.copy(
                    color = MaterialTheme.colorScheme.onBackground,
                    lineHeight = 21.sp
                ),
                cursorBrush = SolidColor(MaterialTheme.colorScheme.primary),
                modifier = Modifier
                    .fillMaxSize()
                    .padding(horizontal = 16.dp, vertical = 11.dp),
                decorationBox = { innerTextField ->
                    Box(contentAlignment = Alignment.CenterStart) {
                        if (userInput.isEmpty()) {
                            Text(
                                text = "发消息给角色...",
                                color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.45f),
                                style = MaterialTheme.typography.titleSmall
                            )
                        }
                        innerTextField()
                    }
                }
            )
        }
        Surface(
            onClick = { if (canSend) onSend() },
            color = if (canSend) MaterialTheme.colorScheme.primary else inputBarContainerColor,
            shape = RoundedCornerShape(50),
            modifier = Modifier.size(44.dp)
        ) {
            Box(contentAlignment = Alignment.Center, modifier = Modifier.fillMaxSize()) {
                Icon(
                    Icons.Filled.ArrowUpward,
                    contentDescription = "发送",
                    tint = if (canSend) Color.White else MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.42f),
                    modifier = Modifier.size(20.dp)
                )
            }
        }
    }
}

@Composable
internal fun XiangqiBoard(
    game: GameState,
    perspective: Side,
    aiThinking: Boolean,
    visiblePieces: Set<Cell>? = null,
    onCellTap: (Cell) -> Unit,
    modifier: Modifier = Modifier
) {
    val density = LocalDensity.current
    val previousMoveColor = PreviousMovePath
    val targetAppear = remember { Animatable(1f) }
    val lastMoveReveal = remember { Animatable(1f) }
    val highlightTransition = rememberInfiniteTransition(label = "xiangqiBoardHighlights")
    val selectedPulse by highlightTransition.animateFloat(
        initialValue = 0f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = 1280, easing = FastOutSlowInEasing),
            repeatMode = RepeatMode.Reverse
        ),
        label = "selectedPulse"
    )
    val previousMovePulse by highlightTransition.animateFloat(
        initialValue = 0f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = 1480, easing = FastOutSlowInEasing),
            repeatMode = RepeatMode.Reverse
        ),
        label = "previousMovePulse"
    )
    LaunchedEffect(game.selected, game.targets) {
        if (game.targets.isEmpty()) {
            targetAppear.snapTo(1f)
        } else {
            targetAppear.snapTo(0f)
            targetAppear.animateTo(
                targetValue = 1f,
                animationSpec = tween(durationMillis = 190, easing = FastOutSlowInEasing)
            )
        }
    }
    LaunchedEffect(game.lastMove) {
        if (game.lastMove == null) {
            lastMoveReveal.snapTo(1f)
        } else {
            lastMoveReveal.snapTo(0f)
            lastMoveReveal.animateTo(
                targetValue = 1f,
                animationSpec = tween(durationMillis = 340, easing = FastOutSlowInEasing)
            )
        }
    }
    val pieceTextPaint = remember {
        android.graphics.Paint(android.graphics.Paint.ANTI_ALIAS_FLAG).apply {
            textAlign = android.graphics.Paint.Align.CENTER
            typeface = Typeface.create(Typeface.SERIF, Typeface.BOLD)
        }
    }
    val riverTextPaint = remember {
        android.graphics.Paint(android.graphics.Paint.ANTI_ALIAS_FLAG).apply {
            textAlign = android.graphics.Paint.Align.CENTER
            typeface = Typeface.create(Typeface.SERIF, Typeface.BOLD)
        }
    }

    Box(
        modifier = modifier
            .aspectRatio(0.84f)
            .background(BoardOuter, RoundedCornerShape(10.dp))
            .border(1.dp, BoardLine.copy(alpha = 0.28f), RoundedCornerShape(10.dp))
            .pointerInput(game.board, game.selected, aiThinking, perspective, visiblePieces) {
                detectTapGestures { offset ->
                    val cell = boardCellAt(offset, size.width.toFloat(), size.height.toFloat(), perspective)
                    if (cell != null) onCellTap(cell)
                }
            }
    ) {
        Canvas(Modifier.fillMaxSize()) {
            val metrics = boardMetrics(size.width, size.height)
            val lineStroke = with(density) { 1.3.dp.toPx() }
            val palaceStroke = with(density) { 1.1.dp.toPx() }
            val riverTextSize = metrics.cell * 0.38f
            val pieceTextSize = metrics.pieceRadius * 1.03f

            drawRoundRect(
                color = BoardFill,
                cornerRadius = androidx.compose.ui.geometry.CornerRadius(22f, 22f)
            )

            for (row in 0..9) {
                val y = metrics.y(row)
                drawLine(
                    color = BoardLine,
                    start = Offset(metrics.x(0), y),
                    end = Offset(metrics.x(8), y),
                    strokeWidth = lineStroke,
                    cap = StrokeCap.Round
                )
            }
            for (col in 0..8) {
                val x = metrics.x(col)
                drawLine(
                    color = BoardLine,
                    start = Offset(x, metrics.y(0)),
                    end = Offset(x, metrics.y(if (col == 0 || col == 8) 9 else 4)),
                    strokeWidth = lineStroke,
                    cap = StrokeCap.Round
                )
                drawLine(
                    color = BoardLine,
                    start = Offset(x, metrics.y(if (col == 0 || col == 8) 0 else 5)),
                    end = Offset(x, metrics.y(9)),
                    strokeWidth = lineStroke,
                    cap = StrokeCap.Round
                )
            }
            listOf(0, 7).forEach { top ->
                drawLine(BoardLine, Offset(metrics.x(3), metrics.y(top)), Offset(metrics.x(5), metrics.y(top + 2)), palaceStroke)
                drawLine(BoardLine, Offset(metrics.x(5), metrics.y(top)), Offset(metrics.x(3), metrics.y(top + 2)), palaceStroke)
            }

            drawIntoCanvas { canvas ->
                riverTextPaint.textSize = riverTextSize
                riverTextPaint.color = BoardLine.copy(alpha = 0.44f).toArgbCompat()
                val riverBase = metrics.y(4) + metrics.cell * 0.66f
                canvas.nativeCanvas.drawText("楚河", metrics.x(2), riverBase, riverTextPaint)
                canvas.nativeCanvas.drawText("汉界", metrics.x(6), riverBase, riverTextPaint)
            }

            game.lastMove?.let { lastMove ->
                val reveal = lastMoveReveal.value.coerceIn(0f, 1f)
                val fromCenter = metrics.center(lastMove.from.toDisplayCell(perspective))
                val toCenter = metrics.center(lastMove.to.toDisplayCell(perspective))
                val moveDelta = toCenter - fromCenter
                val moveDistance = moveDelta.getDistance()
                val fromRingRadius = metrics.pieceRadius * 0.82f
                val toRingRadius = metrics.pieceRadius * 0.58f
                val lineStart = if (moveDistance > fromRingRadius + toRingRadius) {
                    fromCenter + moveDelta * (fromRingRadius / moveDistance)
                } else {
                    fromCenter
                }
                val lineEnd = if (moveDistance > fromRingRadius + toRingRadius) {
                    toCenter - moveDelta * (toRingRadius / moveDistance)
                } else {
                    toCenter
                }
                val animatedLineEnd = lineStart + (lineEnd - lineStart) * reveal
                drawLine(
                    color = previousMoveColor,
                    start = lineStart,
                    end = lineEnd,
                    strokeWidth = lineStroke * 1.7f,
                    cap = StrokeCap.Round
                )
                if (reveal > 0f) {
                    drawLine(
                        color = previousMoveColor,
                        start = lineStart,
                        end = animatedLineEnd,
                        strokeWidth = lineStroke * 2.05f,
                        cap = StrokeCap.Round
                    )
                }
                drawLine(
                    color = PreviousMoveFlash.copy(alpha = (1f - reveal) * 0.48f),
                    start = lineStart,
                    end = animatedLineEnd,
                    strokeWidth = lineStroke * 3.2f,
                    cap = StrokeCap.Round
                )
                drawCircle(
                    color = previousMoveColor.copy(alpha = 0.22f + previousMovePulse * 0.14f),
                    radius = metrics.pieceRadius * (0.58f + previousMovePulse * 0.12f),
                    center = fromCenter
                )
                drawCircle(
                    color = previousMoveColor,
                    radius = metrics.pieceRadius * 0.82f,
                    center = fromCenter,
                    style = Stroke(width = lineStroke * 2.3f)
                )
                drawCircle(
                    color = previousMoveColor.copy(alpha = 0.68f),
                    radius = metrics.pieceRadius * 0.58f,
                    center = toCenter,
                    style = Stroke(width = lineStroke * 1.7f)
                )
                if (reveal < 1f) {
                    drawCircle(
                        color = PreviousMoveFlash.copy(alpha = (1f - reveal) * 0.72f),
                        radius = metrics.pieceRadius * (0.58f + reveal * 0.56f),
                        center = toCenter,
                        style = Stroke(width = lineStroke * (2.2f - reveal * 0.7f))
                    )
                }
            }

            game.selected?.let { selected ->
                val center = metrics.center(selected.toDisplayCell(perspective))
                drawCircle(
                    color = SelectGold.copy(alpha = 0.28f + (1f - selectedPulse) * 0.12f),
                    radius = metrics.pieceRadius * (1.16f + selectedPulse * 0.18f),
                    center = center
                )
                drawCircle(
                    color = SelectGold.copy(alpha = 0.16f),
                    radius = metrics.pieceRadius * (1.34f + selectedPulse * 0.08f),
                    center = center,
                    style = Stroke(width = lineStroke * (1.0f + selectedPulse * 0.45f))
                )
            }

            for (y in 0..9) {
                for (x in 0..8) {
                    if (visiblePieces != null && Cell(x, y) !in visiblePieces) continue
                    val piece = game.board[y][x] ?: continue
                    val center = metrics.center(Cell(x, y).toDisplayCell(perspective))
                    val isRed = piece.side == Side.Red
                    drawCircle(
                        color = PieceShadow,
                        radius = metrics.pieceRadius,
                        center = center + Offset(0f, metrics.pieceRadius * 0.08f)
                    )
                    drawCircle(
                        color = PieceFill,
                        radius = metrics.pieceRadius,
                        center = center
                    )
                    drawCircle(
                        color = if (isRed) RedPiece else BlackPiece,
                        radius = metrics.pieceRadius * 0.82f,
                        center = center,
                        style = Stroke(width = lineStroke * 1.6f)
                    )
                    drawIntoCanvas { canvas ->
                        pieceTextPaint.textSize = pieceTextSize
                        pieceTextPaint.color = (if (isRed) RedPiece else BlackPiece).toArgbCompat()
                        val base = center.y - (pieceTextPaint.ascent() + pieceTextPaint.descent()) / 2f
                        canvas.nativeCanvas.drawText(piece.text, center.x, base, pieceTextPaint)
                    }
                }
            }

            val targetProgress = targetAppear.value.coerceIn(0f, 1f)
            game.targets.forEach { target ->
                val center = metrics.center(target.toDisplayCell(perspective))
                val targetPiece = game.board.pieceAt(target)
                if (targetPiece == null) {
                    drawCircle(
                        color = TargetGreen.copy(alpha = 0.18f * targetProgress),
                        radius = metrics.pieceRadius * (0.30f + targetProgress * 0.12f),
                        center = center,
                        style = Stroke(width = lineStroke * 1.0f)
                    )
                    drawCircle(
                        color = TargetGreen.copy(alpha = 0.58f + targetProgress * 0.24f),
                        radius = metrics.pieceRadius * (0.08f + targetProgress * 0.12f),
                        center = center
                    )
                } else {
                    drawCircle(
                        color = CaptureRed.copy(alpha = 0.84f * targetProgress),
                        radius = metrics.pieceRadius * (1.08f + targetProgress * 0.10f),
                        center = center,
                        style = Stroke(width = lineStroke * (1.35f + targetProgress * 0.45f))
                    )
                }
            }
            game.selected?.let { selected ->
                val center = metrics.center(selected.toDisplayCell(perspective))
                drawCircle(
                    color = SelectGold.copy(alpha = 0.70f + selectedPulse * 0.20f),
                    radius = metrics.pieceRadius * (0.96f + selectedPulse * 0.04f),
                    center = center,
                    style = Stroke(width = lineStroke * (1.8f + selectedPulse * 0.35f))
                )
                drawCircle(
                    color = PreviousMoveGlow.copy(alpha = 0.20f * (1f - selectedPulse)),
                    radius = metrics.pieceRadius * (1.10f + selectedPulse * 0.16f),
                    center = center,
                    style = Stroke(width = lineStroke * 0.9f)
                )
            }
        }
    }
}

internal fun Color.toArgbCompat(): Int =
    android.graphics.Color.argb(
        (alpha * 255).roundToInt().coerceIn(0, 255),
        (red * 255).roundToInt().coerceIn(0, 255),
        (green * 255).roundToInt().coerceIn(0, 255),
        (blue * 255).roundToInt().coerceIn(0, 255)
    )

internal val BoardOuter = Color(0xFF8B5E34)
internal val BoardFill = Color(0xFFE7C987)
internal val BoardLine = Color(0xFF4D2D1B)
internal val PieceFill = Color(0xFFFFF3D3)
internal val PieceShadow = Color(0x66000000)
internal val RedPiece = Color(0xFFB3261E)
internal val BlackPiece = Color(0xFF26231F)
internal val SelectGold = Color(0xFFFFE8C8)
internal val TargetGreen = Color(0xFF1B8E5A)
internal val CaptureRed = Color(0xFFD13A32)
internal val PreviousMovePath = Color.White
internal val PreviousMoveFlash = Color.White
internal val PreviousMoveGlow = Color(0xFFFFF2DC)
