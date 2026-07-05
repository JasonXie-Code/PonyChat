package top.ponychat.webview.ui.chinesechess

import kotlin.math.abs
import kotlin.random.Random

internal data class RankedMove(
    val move: Move,
    val score: Int,
    val scoreDelta: Int,
    val isCapture: Boolean,
    val isCheck: Boolean,
    val winnerAfterMove: Side?,
    val practicalPenalty: Int,
    val piece: Piece?,
    val capturedPiece: Piece?
)

internal fun xiangqiComputeBudgetMillis(difficulty: Int): Long =
    when {
        difficulty >= 14 -> 3_000L
        difficulty >= 12 -> 2_000L
        difficulty >= 7 -> 1_000L
        else -> 500L
    }

internal fun xiangqiFlavorReplyLookaheadCount(difficulty: Int): Int =
    if (difficulty >= 7) 1 else 0

internal fun eleEyeSearchMillis(
    difficulty: Int,
    playStyle: ChessPlayStyle,
    plyCount: Int,
    availableMillis: Long = Long.MAX_VALUE
): Long {
    val base = when {
        difficulty >= 14 -> 500L
        difficulty >= 12 -> 360L
        difficulty >= 7 -> 220L
        else -> 80L
    }
    val openingBonus = if (plyCount <= 12) 40L else 0L
    val styleBonus = when (playStyle) {
        ChessPlayStyle.Textbook -> 80L
        ChessPlayStyle.Cautious -> 40L
        ChessPlayStyle.Attacking -> 20L
        ChessPlayStyle.Playful -> -20L
    }
    val desired = (base + openingBonus + styleBonus).coerceIn(40L, 650L)
    if (availableMillis == Long.MAX_VALUE) return desired
    val reserve = when {
        difficulty >= 14 -> 220L
        difficulty >= 12 -> 190L
        difficulty >= 7 -> 160L
        else -> 120L
    }
    return desired.coerceAtMost((availableMillis - reserve).coerceAtLeast(0L))
}

internal fun rankMoves(
    board: Board,
    side: Side,
    difficulty: Int,
    plyCount: Int = 0,
    deadlineMs: Long = Long.MAX_VALUE
): List<RankedMove> {
    val moves = orderedMoves(board, side)
    if (moves.isEmpty()) return emptyList()
    val replyLookahead = xiangqiFlavorReplyLookaheadCount(difficulty)
    val currentScore = board.scoreFor(side)
    return moves.map { move ->
        val next = board.applyMove(move)
        val nextTurn = side.opponent
        val winnerAfterMove = when {
            next.findGeneral(nextTurn) == null -> side
            next.legalMoves(nextTurn).isEmpty() -> side
            else -> null
        }
        val practicalPenalty = move.practicalPenalty(
            board = board,
            nextBoard = next,
            side = side,
            plyCount = plyCount,
            winnerAfterMove = winnerAfterMove
        )
        val replyPenalty = if (replyLookahead > 0 && hasXiangqiTime(deadlineMs, 8L)) {
            next.opponentReplyPenaltyFor(side, deadlineMs)
        } else {
            0
        }
        val score = next.scoreFor(side) +
            move.immediateFlavorBonus(board, next, side, winnerAfterMove) -
            replyPenalty -
            practicalPenalty
        RankedMove(
            move = move,
            score = score,
            scoreDelta = score - currentScore,
            isCapture = board.pieceAt(move.to) != null,
            isCheck = next.isInCheck(nextTurn),
            winnerAfterMove = winnerAfterMove,
            practicalPenalty = practicalPenalty,
            piece = board.pieceAt(move.from),
            capturedPiece = board.pieceAt(move.to)
        )
    }.sortedByDescending { it.score }
}

private fun hasXiangqiTime(deadlineMs: Long, reserveMillis: Long): Boolean =
    deadlineMs == Long.MAX_VALUE || System.currentTimeMillis() + reserveMillis < deadlineMs

private fun Move.immediateFlavorBonus(
    board: Board,
    nextBoard: Board,
    side: Side,
    winnerAfterMove: Side?
): Int {
    if (winnerAfterMove == side) return 100_000
    val moving = board.pieceAt(from) ?: return 0
    val captured = board.pieceAt(to)
    val captureBonus = captured?.let { capturedPiece ->
        val tradeMargin = capturedPiece.kind.value - moving.kind.value
        capturedPiece.kind.value + tradeMargin.coerceAtLeast(0) / 2
    } ?: 0
    val checkBonus = if (nextBoard.isInCheck(side.opponent)) 520 else 0
    val fromRank = from.rankFromHome(side)
    val toRank = to.rankFromHome(side)
    val advance = toRank - fromRank
    val center = 4 - abs(4 - to.x)
    val activityBonus = when (moving.kind) {
        PieceKind.Rook -> advance.coerceAtLeast(0) * 18 + center * 4
        PieceKind.Horse -> advance.coerceAtLeast(0) * 22 + center * 8
        PieceKind.Cannon -> advance.coerceAtLeast(0) * 12 + center * 7
        PieceKind.Soldier -> advance.coerceAtLeast(0) * 20 + if (to.isAcrossRiver(side)) 50 else 0
        PieceKind.Elephant -> center * 5
        PieceKind.Advisor -> if (to.x in 3..5 && toRank <= 2) 25 else 0
        PieceKind.General -> -80
    }
    val safetyBonus = when {
        nextBoard.attackCount(to, side.opponent) == 0 -> 35
        nextBoard.attackCount(to, side) >= nextBoard.attackCount(to, side.opponent) -> 15
        else -> 0
    }
    return captureBonus + checkBonus + activityBonus + safetyBonus
}

private fun Board.opponentReplyPenaltyFor(side: Side, deadlineMs: Long): Int {
    val opponent = side.opponent
    val beforeScore = scoreFor(side)
    var worstPenalty = 0
    val replies = orderedMoves(this, opponent).take(8)
    for (reply in replies) {
        if (!hasXiangqiTime(deadlineMs, 4L)) break
        val after = applyMove(reply)
        val opponentWins = after.findGeneral(side) == null || after.legalMoves(side).isEmpty()
        val captured = pieceAt(reply.to)
        val tacticalPenalty = when {
            opponentWins -> 30_000
            captured?.side == side -> captured.kind.value * 2
            after.isInCheck(side) -> 620
            else -> 0
        }
        val scoreDrop = (beforeScore - after.scoreFor(side)).coerceAtLeast(0)
        worstPenalty = maxOf(worstPenalty, scoreDrop + tacticalPenalty)
    }
    return worstPenalty / 2
}

internal fun stableXiangqiSeed(
    board: Board,
    side: Side,
    plyCount: Int,
    playStyle: ChessPlayStyle,
    varietyKey: String
): Int {
    var seed = 17
    seed = seed * 31 + side.ordinal
    seed = seed * 31 + plyCount
    seed = seed * 31 + playStyle.ordinal
    seed = seed * 31 + varietyKey.hashCode()
    for (y in 0..9) {
        for (x in 0..8) {
            val piece = board[y][x] ?: continue
            seed = seed * 31 + x
            seed = seed * 31 + y
            seed = seed * 31 + piece.side.ordinal
            seed = seed * 31 + piece.kind.ordinal
        }
    }
    return seed
}

internal fun List<RankedMove>.pickWith(rng: Random): RankedMove? =
    if (isEmpty()) null else this[rng.nextInt(size)]

internal fun RankedMove.isReasonablySafe(): Boolean =
    winnerAfterMove != null || (practicalPenalty <= 220 && scoreDelta > -700)

internal fun RankedMove.isActiveMove(side: Side): Boolean {
    val kind = piece?.kind ?: return false
    val fromRank = move.from.rankFromHome(side)
    val toRank = move.to.rankFromHome(side)
    val advances = toRank > fromRank
    return winnerAfterMove != null ||
        isCapture ||
        isCheck ||
        (advances && kind in setOf(PieceKind.Rook, PieceKind.Horse, PieceKind.Cannon, PieceKind.Soldier))
}

internal fun RankedMove.openingBookPriority(side: Side, playStyle: ChessPlayStyle): Int {
    val kind = piece?.kind ?: return 0
    if (winnerAfterMove == side) return 1000
    if (practicalPenalty >= 320 || scoreDelta < -700) return 0
    val fromRank = move.from.rankFromHome(side)
    val toRank = move.to.rankFromHome(side)
    val centerBonus = 4 - abs(4 - move.to.x)
    val base = when (kind) {
        PieceKind.Horse -> when {
            fromRank == 0 && toRank in 2..3 -> 150 + centerBonus * 4
            toRank > fromRank -> 80 + centerBonus * 3
            else -> 0
        }
        PieceKind.Soldier -> when {
            fromRank == 3 && toRank == 4 && move.to.x in listOf(2, 4, 6) -> 130 + centerBonus * 5
            toRank > fromRank -> 70 + centerBonus * 2
            else -> 0
        }
        PieceKind.Elephant -> if (playStyle == ChessPlayStyle.Cautious && fromRank <= 2 && toRank <= 4) 95 else 40
        PieceKind.Advisor -> if (playStyle == ChessPlayStyle.Cautious && toRank <= 2) 90 else 25
        PieceKind.Cannon -> when {
            toRank >= 6 -> -120
            toRank in 2..5 -> if (playStyle == ChessPlayStyle.Attacking) 105 else 55
            else -> 20
        }
        PieceKind.Rook -> when {
            toRank in 1..3 && playStyle == ChessPlayStyle.Attacking -> 95
            toRank in 1..2 -> 35
            else -> 0
        }
        PieceKind.General -> -500
    }
    val styleBonus = when (playStyle) {
        ChessPlayStyle.Attacking -> if (isActiveMove(side)) 35 else 0
        ChessPlayStyle.Cautious -> if (practicalPenalty <= 80 && !isCheck) 35 else 0
        ChessPlayStyle.Playful -> if (isCapture || isCheck) 20 else 0
        ChessPlayStyle.Textbook -> if (kind in setOf(PieceKind.Horse, PieceKind.Soldier, PieceKind.Elephant, PieceKind.Advisor)) 35 else 0
    }
    return (base + styleBonus).coerceAtLeast(0)
}

internal fun List<RankedMove>.openingBookCandidate(
    side: Side,
    playStyle: ChessPlayStyle,
    plyCount: Int
): RankedMove? {
    if (plyCount > 12) return null
    return mapNotNull { rankedMove ->
        val priority = rankedMove.openingBookPriority(side, playStyle)
        if (priority > 0) priority to rankedMove else null
    }
        .sortedWith(
            compareByDescending<Pair<Int, RankedMove>> { it.first }
                .thenByDescending { it.second.score }
        )
        .firstOrNull()
        ?.second
}

internal fun chooseAiMove(board: Board, side: Side, difficulty: Int, mistakeRate: Int): Move? {
    val ranked = rankMoves(board, side, difficulty)
    if (ranked.isEmpty()) return null

    val blunder = Random.nextInt(100) < mistakeRate
    val softness = ((20 - difficulty).coerceAtLeast(0) / 4).coerceIn(0, 5)
    val poolSize = when {
        blunder -> (2 + softness + mistakeRate / 12).coerceAtMost(ranked.size)
        else -> (1 + softness / 2).coerceAtMost(ranked.size)
    }.coerceAtLeast(1)
    val start = if (blunder && ranked.size > 1) 1 else 0
    val endExclusive = (start + poolSize).coerceAtMost(ranked.size)
    return ranked.subList(start, endExclusive).random().move
}

internal fun minimax(board: Board, sideToMove: Side, depth: Int, alphaStart: Int, betaStart: Int): Int {
    if (board.findGeneral(Side.Red) == null) return -100_000
    if (board.findGeneral(Side.Black) == null) return 100_000
    if (depth <= 0) return evaluate(board)
    val moves = orderedMoves(board, sideToMove).let { ordered ->
        if (depth >= 2) ordered.take(30) else ordered
    }
    if (moves.isEmpty()) {
        return if (sideToMove == Side.Red) -90_000 else 90_000
    }
    var alpha = alphaStart
    var beta = betaStart
    return if (sideToMove == Side.Red) {
        var best = Int.MIN_VALUE / 4
        for (move in moves) {
            best = maxOf(best, minimax(board.applyMove(move), sideToMove.opponent, depth - 1, alpha, beta))
            alpha = maxOf(alpha, best)
            if (beta <= alpha) break
        }
        best
    } else {
        var best = Int.MAX_VALUE / 4
        for (move in moves) {
            best = minOf(best, minimax(board.applyMove(move), sideToMove.opponent, depth - 1, alpha, beta))
            beta = minOf(beta, best)
            if (beta <= alpha) break
        }
        best
    }
}

internal fun evaluate(board: Board): Int {
    return board.scoreFor(Side.Red)
}

internal fun orderedMoves(board: Board, side: Side): List<Move> =
    board.legalMoves(side).sortedByDescending { move ->
        val moving = board.pieceAt(move.from)
        val captured = board.pieceAt(move.to)
        val next = board.applyMove(move)
        val captureScore = (captured?.kind?.value ?: 0) * 12 - (moving?.kind?.value ?: 0)
        val checkScore = if (next.isInCheck(side.opponent)) 850 else 0
        val centerScore = 4 - abs(4 - move.to.x)
        captureScore + checkScore + centerScore
    }

internal fun Board.scoreFor(side: Side): Int {
    val opening = isOpeningPhase()
    var score = 0
    for (y in 0..9) {
        for (x in 0..8) {
            val piece = this[y][x] ?: continue
            val cell = Cell(x, y)
            var value = piece.kind.value + piecePositionBonus(cell, piece, opening)
            val attackers = attackCount(cell, piece.side.opponent)
            if (attackers > 0) {
                val defenders = attackCount(cell, piece.side)
                val danger = when {
                    defenders == 0 -> piece.kind.value / 3
                    attackers > defenders -> piece.kind.value / 5
                    else -> piece.kind.value / 12
                }
                value -= danger
            }
            if (piece.kind == PieceKind.Cannon && opening && cell.rankFromHome(piece.side) >= 7) {
                val deepPenalty = if (attackCount(cell, piece.side) == 0) 280 else 180
                value -= deepPenalty
            }
            score += if (piece.side == side) value else -value
        }
    }
    score += (pseudoMoveCount(side) - pseudoMoveCount(side.opponent)) * 2
    score += kingSafetyScore(side) - kingSafetyScore(side.opponent)
    return score
}

internal fun Move.practicalPenalty(
    board: Board,
    nextBoard: Board,
    side: Side,
    plyCount: Int,
    winnerAfterMove: Side?
): Int {
    if (winnerAfterMove == side) return 0
    val moving = board.pieceAt(from) ?: return 0
    val captured = board.pieceAt(to)
    val opening = plyCount <= 10 || board.isOpeningPhase()
    val targetRank = to.rankFromHome(side)
    var penalty = 0
    if (opening && moving.kind == PieceKind.Cannon && targetRank >= 7) {
        penalty += if (captured?.kind == PieceKind.Horse) 460 else 260
    }
    if (opening && moving.kind in setOf(PieceKind.Cannon, PieceKind.Rook) && targetRank >= 6) {
        if (nextBoard.attackCount(to, side) == 0) penalty += 180
    }
    if (captured != null && nextBoard.attackCount(to, side.opponent) > nextBoard.attackCount(to, side)) {
        val tradeRisk = (moving.kind.value - captured.kind.value).coerceAtLeast(0)
        penalty += (tradeRisk + moving.kind.value / 5).coerceAtMost(360)
    }
    if (opening && moving.kind == PieceKind.General) penalty += 500
    return penalty
}

internal fun piecePositionBonus(cell: Cell, piece: Piece, opening: Boolean): Int {
    val rank = cell.rankFromHome(piece.side)
    val center = 4 - abs(4 - cell.x)
    return when (piece.kind) {
        PieceKind.General -> if (cell.x == 4 && rank == 0) 18 else 0
        PieceKind.Advisor -> if (cell.x in 3..5 && rank <= 2) 14 else -10
        PieceKind.Elephant -> center * 3 + if (rank <= 4) 10 else -20
        PieceKind.Horse -> center * 7 + rank.coerceAtMost(5) * 5 -
            if (rank == 0) 22 else 0 -
            if (cell.x == 0 || cell.x == 8) 16 else 0
        PieceKind.Rook -> center * 2 + if (rank > 0) 24 else 0 + rank * 2
        PieceKind.Cannon -> center * 5 + when {
            opening && rank >= 7 -> -170
            rank in 2..5 -> 22
            rank == 1 -> 10
            else -> 0
        }
        PieceKind.Soldier -> rank * 8 + if (rank >= 5) 42 else 0 + center * 3
    }
}

internal fun Board.kingSafetyScore(side: Side): Int {
    var score = 0
    if (isInCheck(side)) score -= 180
    val general = findGeneral(side) ?: return -2_000
    if (general.x != 4) score -= 18
    val palaceDefenders = listOf(
        Cell(3, if (side == Side.Red) 9 else 0),
        Cell(5, if (side == Side.Red) 9 else 0),
        Cell(3, if (side == Side.Red) 7 else 2),
        Cell(5, if (side == Side.Red) 7 else 2)
    ).count { pieceAt(it)?.side == side }
    score += palaceDefenders * 12
    return score
}

internal fun Board.pseudoMoveCount(side: Side): Int {
    var count = 0
    for (y in 0..9) {
        for (x in 0..8) {
            val piece = this[y][x] ?: continue
            if (piece.side == side) count += pseudoMovesFrom(Cell(x, y)).size
        }
    }
    return count
}

internal fun Board.attackCount(target: Cell, bySide: Side): Int {
    var count = 0
    for (y in 0..9) {
        for (x in 0..8) {
            val from = Cell(x, y)
            val piece = pieceAt(from) ?: continue
            if (piece.side == bySide && controlsCell(from, target, piece)) count += 1
        }
    }
    return count
}
