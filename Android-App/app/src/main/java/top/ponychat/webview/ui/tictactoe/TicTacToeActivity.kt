package top.ponychat.webview.ui.tictactoe

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Slider
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.core.view.WindowCompat
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import kotlin.math.roundToInt
import kotlin.random.Random
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.ui.common.SystemNavigationBarColorEffect
import top.ponychat.webview.ui.theme.PonyChatTheme

class TicTacToeActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val prefs = AppPreferences(this)
        WindowCompat.setDecorFitsSystemWindows(window, false)
        enableEdgeToEdge()
        setContent {
            PonyChatTheme(darkTheme = prefs.isDarkTheme, fontScale = prefs.fontScale) {
                SystemNavigationBarColorEffect(
                    color = MaterialTheme.colorScheme.background,
                    restoreOnDispose = true
                )
                TicTacToeScreen(onBack = { finish() })
            }
        }
    }
}

private enum class Mark(val label: String) {
    X("X"),
    O("O");

    val opponent: Mark
        get() = if (this == X) O else X

    val sideLabel: String
        get() = if (this == X) "X 方" else "O 方"
}

private data class MatchScore(
    val xWins: Int = 0,
    val oWins: Int = 0,
    val draws: Int = 0
) {
    fun add(result: RoundResult): MatchScore =
        when {
            result.winner == Mark.X -> copy(xWins = xWins + 1)
            result.winner == Mark.O -> copy(oWins = oWins + 1)
            result.isDraw -> copy(draws = draws + 1)
            else -> this
        }
}

private data class RoundResult(
    val winner: Mark? = null,
    val winningLine: List<Int> = emptyList(),
    val isDraw: Boolean = false
)

private data class HistoryEntry(
    val board: TicBoard,
    val turn: Mark,
    val message: String
)

private data class TicTacToeGame(
    val board: TicBoard = emptyBoard(),
    val turn: Mark = Mark.X,
    val history: List<HistoryEntry> = emptyList(),
    val message: String = "X 方先手",
    val winner: Mark? = null,
    val winningLine: List<Int> = emptyList(),
    val isDraw: Boolean = false,
    val score: MatchScore = MatchScore()
) {
    val isOver: Boolean
        get() = winner != null || isDraw

    fun handleTap(index: Int): TicTacToeGame {
        if (index !in board.indices) return this
        if (isOver) return copy(message = "本局已结束")
        if (board[index] != null) return copy(message = "这里已经落子")
        return applyMove(index)
    }

    fun applyMove(index: Int): TicTacToeGame {
        val nextBoard = board.toMutableList().also { it[index] = turn }
        val result = analyzeBoard(nextBoard)
        val nextHistory = history + HistoryEntry(board, turn, message)
        val nextScore = score.add(result)
        return when {
            result.winner != null -> copy(
                board = nextBoard,
                history = nextHistory,
                winner = result.winner,
                winningLine = result.winningLine,
                isDraw = false,
                score = nextScore,
                message = "${result.winner.sideLabel}胜"
            )
            result.isDraw -> copy(
                board = nextBoard,
                history = nextHistory,
                winner = null,
                winningLine = emptyList(),
                isDraw = true,
                score = nextScore,
                message = "平局"
            )
            else -> copy(
                board = nextBoard,
                turn = turn.opponent,
                history = nextHistory,
                winner = null,
                winningLine = emptyList(),
                isDraw = false,
                message = "${turn.opponent.sideLabel}行棋"
            )
        }
    }

    fun undo(aiEnabled: Boolean, playerMark: Mark): TicTacToeGame {
        if (history.isEmpty() || isOver) return this
        val stepCount = if (aiEnabled && turn == playerMark && history.size >= 2) 2 else 1
        val target = history[history.size - stepCount]
        return copy(
            board = target.board,
            turn = target.turn,
            history = history.dropLast(stepCount),
            message = target.message,
            winner = null,
            winningLine = emptyList(),
            isDraw = false
        )
    }

    fun newRound(): TicTacToeGame = TicTacToeGame(score = score)
}

private typealias TicBoard = List<Mark?>

private val winningLines = listOf(
    listOf(0, 1, 2),
    listOf(3, 4, 5),
    listOf(6, 7, 8),
    listOf(0, 3, 6),
    listOf(1, 4, 7),
    listOf(2, 5, 8),
    listOf(0, 4, 8),
    listOf(2, 4, 6)
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun TicTacToeScreen(onBack: () -> Unit) {
    var game by remember { mutableStateOf(TicTacToeGame()) }
    var difficulty by remember { mutableIntStateOf(9) }
    var mistakeRate by remember { mutableIntStateOf(12) }
    var aiEnabled by remember { mutableStateOf(true) }
    var playerMark by remember { mutableStateOf(Mark.X) }
    var aiThinking by remember { mutableStateOf(false) }

    LaunchedEffect(game.board, game.turn, game.winner, game.isDraw, difficulty, mistakeRate, aiEnabled, playerMark) {
        if (!aiEnabled || game.isOver || game.turn == playerMark) return@LaunchedEffect
        aiThinking = true
        delay(300)
        val move = withContext(Dispatchers.Default) {
            chooseAiMove(game.board, game.turn, difficulty, mistakeRate)
        }
        aiThinking = false
        if (move != null && !game.isOver && game.board.getOrNull(move) == null) {
            game = game.applyMove(move)
        }
    }

    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        topBar = {
            Surface(
                color = MaterialTheme.colorScheme.surface,
                shadowElevation = 2.dp,
                modifier = Modifier.statusBarsPadding()
            ) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(54.dp)
                        .padding(horizontal = 8.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                    Text(
                        text = "井字棋",
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.SemiBold,
                        modifier = Modifier.weight(1f),
                        textAlign = TextAlign.Center
                    )
                    IconButton(onClick = { game = game.newRound() }) {
                        Icon(Icons.Filled.Refresh, contentDescription = "新一局")
                    }
                }
            }
        }
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .navigationBarsPadding()
                .padding(horizontal = 14.dp, vertical = 12.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            StatusStrip(
                message = if (aiThinking) "${game.turn.sideLabel}思考中..." else game.message,
                winner = game.winner,
                isDraw = game.isDraw,
                aiEnabled = aiEnabled,
                playerMark = playerMark,
                onAiEnabledChange = { enabled ->
                    aiEnabled = enabled
                    game = TicTacToeGame(score = game.score)
                }
            )
            ScoreStrip(score = game.score)
            TicTacToeBoard(
                game = game,
                aiThinking = aiThinking,
                onCellTap = { index ->
                    if (aiThinking) return@TicTacToeBoard
                    if (aiEnabled && game.turn != playerMark) return@TicTacToeBoard
                    game = game.handleTap(index)
                },
                modifier = Modifier.fillMaxWidth()
            )
            ControlPanel(
                difficulty = difficulty,
                onDifficultyChange = { difficulty = it },
                mistakeRate = mistakeRate,
                onMistakeRateChange = { mistakeRate = it },
                aiEnabled = aiEnabled,
                playerMark = playerMark,
                onPlayerMarkChange = { mark ->
                    if (mark != playerMark) {
                        playerMark = mark
                        game = TicTacToeGame(score = game.score)
                    }
                },
                canUndo = game.history.isNotEmpty() && !game.isOver && !aiThinking,
                onUndo = {
                    game = game.undo(aiEnabled = aiEnabled, playerMark = playerMark)
                },
                onNewRound = {
                    game = game.newRound()
                },
                onResetScore = {
                    game = TicTacToeGame()
                }
            )
        }
    }
}

@Composable
private fun StatusStrip(
    message: String,
    winner: Mark?,
    isDraw: Boolean,
    aiEnabled: Boolean,
    playerMark: Mark,
    onAiEnabledChange: (Boolean) -> Unit
) {
    Surface(
        color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.54f),
        shape = RoundedCornerShape(10.dp),
        modifier = Modifier.fillMaxWidth()
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 12.dp, vertical = 9.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = when {
                        winner != null -> "${winner.sideLabel}胜"
                        isDraw -> "平局"
                        else -> message
                    },
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.SemiBold,
                    color = MaterialTheme.colorScheme.onSurface
                )
                Text(
                    text = if (aiEnabled) "你执 ${playerMark.label}，AI 执 ${playerMark.opponent.label}" else "双人轮流落子",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
            Text(
                text = "AI",
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            Switch(checked = aiEnabled, onCheckedChange = onAiEnabledChange)
        }
    }
}

@Composable
private fun ScoreStrip(score: MatchScore) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        ScorePill(
            title = "X",
            value = score.xWins,
            color = xColor(),
            modifier = Modifier.weight(1f)
        )
        ScorePill(
            title = "平",
            value = score.draws,
            color = MaterialTheme.colorScheme.tertiary,
            modifier = Modifier.weight(1f)
        )
        ScorePill(
            title = "O",
            value = score.oWins,
            color = oColor(),
            modifier = Modifier.weight(1f)
        )
    }
}

@Composable
private fun ScorePill(
    title: String,
    value: Int,
    color: Color,
    modifier: Modifier = Modifier
) {
    Surface(
        color = color.copy(alpha = 0.13f),
        shape = RoundedCornerShape(8.dp),
        modifier = modifier
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 12.dp, vertical = 8.dp),
            horizontalArrangement = Arrangement.Center,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(
                text = title,
                color = color,
                style = MaterialTheme.typography.labelLarge,
                fontWeight = FontWeight.Bold
            )
            Text(
                text = "  $value",
                color = MaterialTheme.colorScheme.onSurface,
                style = MaterialTheme.typography.labelLarge,
                fontWeight = FontWeight.SemiBold
            )
        }
    }
}

@Composable
private fun TicTacToeBoard(
    game: TicTacToeGame,
    aiThinking: Boolean,
    onCellTap: (Int) -> Unit,
    modifier: Modifier = Modifier
) {
    val boardShape = RoundedCornerShape(18.dp)
    val backgroundColor = MaterialTheme.colorScheme.surface
    val borderColor = MaterialTheme.colorScheme.outline.copy(alpha = 0.22f)
    val gridColor = MaterialTheme.colorScheme.outline.copy(alpha = 0.48f)
    val winColor = MaterialTheme.colorScheme.primary
    val xStroke = xColor()
    val oStroke = oColor()

    Box(
        modifier = modifier
            .aspectRatio(1f)
            .background(backgroundColor, boardShape)
            .border(1.dp, borderColor, boardShape)
            .padding(14.dp)
            .pointerInput(game.board, game.winner, game.isDraw, aiThinking) {
                detectTapGestures { offset ->
                    if (aiThinking || game.isOver) return@detectTapGestures
                    val cellSize = size.width / 3f
                    val col = (offset.x / cellSize).toInt().coerceIn(0, 2)
                    val row = (offset.y / cellSize).toInt().coerceIn(0, 2)
                    onCellTap(row * 3 + col)
                }
            }
    ) {
        Canvas(modifier = Modifier.fillMaxSize()) {
            val cell = size.width / 3f
            val gridStroke = size.minDimension * 0.018f
            val markStroke = size.minDimension * 0.035f
            val pad = cell * 0.22f

            for (i in 1..2) {
                val p = cell * i
                drawLine(
                    color = gridColor,
                    start = Offset(p, 0f),
                    end = Offset(p, size.height),
                    strokeWidth = gridStroke,
                    cap = StrokeCap.Round
                )
                drawLine(
                    color = gridColor,
                    start = Offset(0f, p),
                    end = Offset(size.width, p),
                    strokeWidth = gridStroke,
                    cap = StrokeCap.Round
                )
            }

            game.board.forEachIndexed { index, mark ->
                if (mark == null) return@forEachIndexed
                val row = index / 3
                val col = index % 3
                val left = col * cell
                val top = row * cell
                when (mark) {
                    Mark.X -> {
                        drawLine(
                            color = xStroke,
                            start = Offset(left + pad, top + pad),
                            end = Offset(left + cell - pad, top + cell - pad),
                            strokeWidth = markStroke,
                            cap = StrokeCap.Round
                        )
                        drawLine(
                            color = xStroke,
                            start = Offset(left + cell - pad, top + pad),
                            end = Offset(left + pad, top + cell - pad),
                            strokeWidth = markStroke,
                            cap = StrokeCap.Round
                        )
                    }
                    Mark.O -> {
                        drawCircle(
                            color = oStroke,
                            radius = cell * 0.28f,
                            center = Offset(left + cell / 2f, top + cell / 2f),
                            style = Stroke(width = markStroke)
                        )
                    }
                }
            }

            if (game.winningLine.size == 3) {
                val start = cellCenter(game.winningLine.first(), cell)
                val end = cellCenter(game.winningLine.last(), cell)
                drawLine(
                    color = winColor,
                    start = start,
                    end = end,
                    strokeWidth = markStroke * 0.72f,
                    cap = StrokeCap.Round
                )
            }
        }
    }
}

@Composable
private fun ControlPanel(
    difficulty: Int,
    onDifficultyChange: (Int) -> Unit,
    mistakeRate: Int,
    onMistakeRateChange: (Int) -> Unit,
    aiEnabled: Boolean,
    playerMark: Mark,
    onPlayerMarkChange: (Mark) -> Unit,
    canUndo: Boolean,
    onUndo: () -> Unit,
    onNewRound: () -> Unit,
    onResetScore: () -> Unit
) {
    Surface(
        color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.45f),
        shape = RoundedCornerShape(12.dp),
        modifier = Modifier.fillMaxWidth()
    ) {
        Column(
            modifier = Modifier.padding(horizontal = 12.dp, vertical = 12.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            MarkChoiceRow(
                selectedMark = playerMark,
                onMarkSelected = onPlayerMarkChange
            )
            LabeledSlider(
                title = "AI强度",
                valueLabel = difficulty.toString(),
                value = difficulty,
                valueRange = 1..9,
                enabled = aiEnabled,
                onValueChange = onDifficultyChange
            )
            LabeledSlider(
                title = "失误率",
                valueLabel = "$mistakeRate%",
                value = mistakeRate,
                valueRange = 0..45,
                enabled = aiEnabled,
                onValueChange = onMistakeRateChange
            )
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                OutlinedButton(
                    onClick = onUndo,
                    enabled = canUndo,
                    modifier = Modifier.weight(1f)
                ) {
                    Text("撤销")
                }
                Button(
                    onClick = onNewRound,
                    modifier = Modifier.weight(1f)
                ) {
                    Text("新一局")
                }
                TextButton(
                    onClick = onResetScore,
                    modifier = Modifier.weight(1f)
                ) {
                    Text("清比分")
                }
            }
        }
    }
}

@Composable
private fun MarkChoiceRow(
    selectedMark: Mark,
    onMarkSelected: (Mark) -> Unit
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Text(
            text = "执子",
            style = MaterialTheme.typography.labelLarge,
            fontWeight = FontWeight.SemiBold,
            color = MaterialTheme.colorScheme.onSurface,
            modifier = Modifier.weight(1f)
        )
        MarkChoiceButton(
            text = "X",
            selected = selectedMark == Mark.X,
            onClick = { onMarkSelected(Mark.X) },
            modifier = Modifier.weight(1f)
        )
        MarkChoiceButton(
            text = "O",
            selected = selectedMark == Mark.O,
            onClick = { onMarkSelected(Mark.O) },
            modifier = Modifier.weight(1f)
        )
    }
}

@Composable
private fun MarkChoiceButton(
    text: String,
    selected: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier
) {
    if (selected) {
        Button(onClick = onClick, modifier = modifier.height(40.dp)) {
            Text(text)
        }
    } else {
        TextButton(onClick = onClick, modifier = modifier.height(40.dp)) {
            Text(text)
        }
    }
}

@Composable
private fun LabeledSlider(
    title: String,
    valueLabel: String,
    value: Int,
    valueRange: IntRange,
    enabled: Boolean,
    onValueChange: (Int) -> Unit
) {
    Column(verticalArrangement = Arrangement.spacedBy(3.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(
                text = title,
                style = MaterialTheme.typography.labelLarge,
                fontWeight = FontWeight.SemiBold,
                color = if (enabled) MaterialTheme.colorScheme.onSurface else MaterialTheme.colorScheme.onSurfaceVariant
            )
            Text(
                text = valueLabel,
                style = MaterialTheme.typography.labelLarge,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                textAlign = TextAlign.End,
                modifier = Modifier.weight(1f)
            )
        }
        Slider(
            value = value.toFloat(),
            onValueChange = { onValueChange(it.roundToInt().coerceIn(valueRange.first, valueRange.last)) },
            valueRange = valueRange.first.toFloat()..valueRange.last.toFloat(),
            steps = (valueRange.last - valueRange.first - 1).coerceAtLeast(0),
            enabled = enabled
        )
    }
}

private fun emptyBoard(): TicBoard = List(9) { null }

private fun analyzeBoard(board: TicBoard): RoundResult {
    winningLines.forEach { line ->
        val first = board[line[0]]
        if (first != null && line.all { board[it] == first }) {
            return RoundResult(winner = first, winningLine = line)
        }
    }
    return if (board.all { it != null }) RoundResult(isDraw = true) else RoundResult()
}

private fun chooseAiMove(
    board: TicBoard,
    side: Mark,
    difficulty: Int,
    mistakeRate: Int
): Int? {
    val candidates = board.indices.filter { board[it] == null }
    if (candidates.isEmpty()) return null
    if (Random.nextInt(100) < mistakeRate) return candidates.random()

    val maxDepth = difficulty.coerceIn(1, 9)
    return candidates.maxByOrNull { index ->
        val next = board.toMutableList().also { it[index] = side }
        minimax(next, side.opponent, side, depth = 1, maxDepth = maxDepth)
    } ?: candidates.random()
}

private fun minimax(
    board: TicBoard,
    current: Mark,
    ai: Mark,
    depth: Int,
    maxDepth: Int
): Int {
    val result = analyzeBoard(board)
    if (result.winner == ai) return 100 - depth
    if (result.winner == ai.opponent) return depth - 100
    if (result.isDraw) return 0
    if (depth >= maxDepth) return heuristic(board, ai)

    val moves = board.indices.filter { board[it] == null }
    return if (current == ai) {
        moves.maxOf { index ->
            val next = board.toMutableList().also { it[index] = current }
            minimax(next, current.opponent, ai, depth + 1, maxDepth)
        }
    } else {
        moves.minOf { index ->
            val next = board.toMutableList().also { it[index] = current }
            minimax(next, current.opponent, ai, depth + 1, maxDepth)
        }
    }
}

private fun heuristic(board: TicBoard, ai: Mark): Int {
    var score = 0
    for (line in winningLines) {
        val aiCount = line.count { board[it] == ai }
        val otherCount = line.count { board[it] == ai.opponent }
        score += when {
            aiCount > 0 && otherCount == 0 -> aiCount * aiCount * 3
            otherCount > 0 && aiCount == 0 -> -otherCount * otherCount * 4
            else -> 0
        }
    }
    if (board[4] == ai) score += 3
    if (board[4] == ai.opponent) score -= 3
    listOf(0, 2, 6, 8).forEach {
        if (board[it] == ai) score += 1
        if (board[it] == ai.opponent) score -= 1
    }
    return score
}

private fun cellCenter(index: Int, cellSize: Float): Offset {
    val row = index / 3
    val col = index % 3
    return Offset(col * cellSize + cellSize / 2f, row * cellSize + cellSize / 2f)
}

@Composable
private fun xColor(): Color = Color(0xFFD65F5F)

@Composable
private fun oColor(): Color = Color(0xFF2F87A8)
