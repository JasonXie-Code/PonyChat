package top.ponychat.webview.ui.chinesechess

import kotlin.math.abs

internal fun GameState.handleTap(cell: Cell): GameState = handleTapResult(cell).game

internal fun GameState.handleTapResult(cell: Cell): TapResult {
    if (winner != null) return TapResult(this)
    val piece = board.pieceAt(cell)
    val selectedCell = selected
    if (selectedCell == null) {
        val next = if (piece?.side == turn) {
            val moves = board.legalMovesFrom(cell).map { it.to }.toSet()
            copy(selected = cell, targets = moves, message = "${piece.side.label}选择${piece.text}")
        } else {
            copy(message = "${turn.label}行棋")
        }
        return TapResult(next)
    }
    if (piece?.side == turn) {
        if (selectedCell == cell) {
            return TapResult(copy(selected = null, targets = emptySet(), message = "${turn.label}行棋"))
        }
        val moves = board.legalMovesFrom(cell).map { it.to }.toSet()
        return TapResult(copy(selected = cell, targets = moves, message = "${piece.side.label}选择${piece.text}"))
    }
    val move = Move(selectedCell, cell)
    return if (move.to in targets) {
        TapResult(applyMove(move), move)
    } else {
        TapResult(copy(selected = null, targets = emptySet(), message = "非法走法"))
    }
}

internal fun GameState.applyMove(move: Move): GameState {
    val movingPiece = board.pieceAt(move.from) ?: return this
    val nextBoard = board.applyMove(move)
    val nextTurn = turn.opponent
    val nextLegal = nextBoard.legalMoves(nextTurn)
    val nextWinner = when {
        nextBoard.findGeneral(nextTurn) == null -> turn
        nextLegal.isEmpty() -> turn
        else -> null
    }
    val check = nextBoard.isInCheck(nextTurn)
    val message = when {
        nextWinner != null -> "${turn.label}${movingPiece.text}胜出"
        check -> "${turn.label}${movingPiece.text}将军"
        else -> "${nextTurn.label}行棋"
    }
    return copy(
        board = nextBoard,
        turn = nextTurn,
        selected = null,
        targets = emptySet(),
        history = history + HistoryEntry(board, turn, this.message, lastMove),
        message = message,
        winner = nextWinner,
        lastMove = move
    )
}

internal fun GameState.undo(aiEnabled: Boolean): GameState {
    val steps = if (aiEnabled && history.size >= 2) 2 else 1
    return undoSteps(steps)
}

internal fun GameState.undoSteps(steps: Int): GameState {
    val safeSteps = steps.coerceIn(0, history.size)
    var current = this
    repeat(safeSteps) {
        val entry = current.history.lastOrNull() ?: return@repeat
        current = current.copy(
            board = entry.board,
            turn = entry.turn,
            selected = null,
            targets = emptySet(),
            history = current.history.dropLast(1),
            message = entry.message,
            winner = null,
            lastMove = entry.lastMove
        )
    }
    return current
}

internal fun initialBoard(): Board {
    fun row(vararg pieces: Piece?): List<Piece?> = pieces.toList()
    fun black(kind: PieceKind) = Piece(Side.Black, kind)
    fun red(kind: PieceKind) = Piece(Side.Red, kind)
    val empty = row(null, null, null, null, null, null, null, null, null)
    return listOf(
        row(black(PieceKind.Rook), black(PieceKind.Horse), black(PieceKind.Elephant), black(PieceKind.Advisor), black(PieceKind.General), black(PieceKind.Advisor), black(PieceKind.Elephant), black(PieceKind.Horse), black(PieceKind.Rook)),
        empty,
        row(null, black(PieceKind.Cannon), null, null, null, null, null, black(PieceKind.Cannon), null),
        row(black(PieceKind.Soldier), null, black(PieceKind.Soldier), null, black(PieceKind.Soldier), null, black(PieceKind.Soldier), null, black(PieceKind.Soldier)),
        empty,
        empty,
        row(red(PieceKind.Soldier), null, red(PieceKind.Soldier), null, red(PieceKind.Soldier), null, red(PieceKind.Soldier), null, red(PieceKind.Soldier)),
        row(null, red(PieceKind.Cannon), null, null, null, null, null, red(PieceKind.Cannon), null),
        empty,
        row(red(PieceKind.Rook), red(PieceKind.Horse), red(PieceKind.Elephant), red(PieceKind.Advisor), red(PieceKind.General), red(PieceKind.Advisor), red(PieceKind.Elephant), red(PieceKind.Horse), red(PieceKind.Rook))
    )
}

internal fun openingPieceOrder(playerSide: Side): List<Cell> {
    val board = initialBoard()
    fun cellsOf(vararg kinds: PieceKind): List<Cell> {
        val wanted = kinds.toSet()
        val result = mutableListOf<Cell>()
        for (y in 0..9) {
            for (x in 0..8) {
                val piece = board[y][x] ?: continue
                if (piece.kind in wanted) result += Cell(x, y)
            }
        }
        return result.sortedWith(
            compareBy<Cell> { if (board[it.y][it.x]?.side == playerSide) 1 else 0 }
                .thenBy { it.y }
                .thenBy { it.x }
        )
    }
    return buildList {
        addAll(cellsOf(PieceKind.General, PieceKind.Advisor, PieceKind.Elephant))
        addAll(cellsOf(PieceKind.Rook, PieceKind.Horse, PieceKind.Cannon))
        addAll(cellsOf(PieceKind.Soldier))
    }.distinct()
}

internal fun Board.pieceAt(cell: Cell): Piece? =
    if (cell.x in 0..8 && cell.y in 0..9) this[cell.y][cell.x] else null

internal fun Board.applyMove(move: Move): Board {
    val mutable = map { it.toMutableList() }.toMutableList()
    val piece = mutable[move.from.y][move.from.x]
    mutable[move.from.y][move.from.x] = null
    mutable[move.to.y][move.to.x] = piece
    return mutable.map { it.toList() }
}

internal fun Cell.toApiMap(): Map<String, Int> = mapOf("x" to x, "y" to y)

internal fun Board.legalMoves(side: Side): List<Move> {
    val moves = mutableListOf<Move>()
    for (y in 0..9) {
        for (x in 0..8) {
            val piece = this[y][x] ?: continue
            if (piece.side == side) {
                moves += legalMovesFrom(Cell(x, y))
            }
        }
    }
    return moves
}

internal fun Board.legalMovesFrom(cell: Cell): List<Move> {
    val piece = pieceAt(cell) ?: return emptyList()
    return pseudoMovesFrom(cell).filter { move ->
        val next = applyMove(move)
        !next.isInCheck(piece.side)
    }
}

internal fun Board.pseudoMovesFrom(cell: Cell): List<Move> {
    val piece = pieceAt(cell) ?: return emptyList()
    return when (piece.kind) {
        PieceKind.General -> generalMoves(cell, piece)
        PieceKind.Advisor -> advisorMoves(cell, piece)
        PieceKind.Elephant -> elephantMoves(cell, piece)
        PieceKind.Horse -> horseMoves(cell, piece)
        PieceKind.Rook -> rookMoves(cell, piece)
        PieceKind.Cannon -> cannonMoves(cell, piece)
        PieceKind.Soldier -> soldierMoves(cell, piece)
    }
}

internal fun Board.addIfAvailable(result: MutableList<Move>, from: Cell, to: Cell, side: Side) {
    if (to.x !in 0..8 || to.y !in 0..9) return
    val target = pieceAt(to)
    if (target?.side != side) result += Move(from, to)
}

internal fun Board.generalMoves(cell: Cell, piece: Piece): List<Move> {
    val result = mutableListOf<Move>()
    val palaceRows = if (piece.side == Side.Red) 7..9 else 0..2
    val steps = listOf(Cell(1, 0), Cell(-1, 0), Cell(0, 1), Cell(0, -1))
    steps.forEach { step ->
        val to = Cell(cell.x + step.x, cell.y + step.y)
        if (to.x in 3..5 && to.y in palaceRows) addIfAvailable(result, cell, to, piece.side)
    }
    var y = cell.y + piece.side.forward
    while (y in 0..9) {
        val target = pieceAt(Cell(cell.x, y))
        if (target != null) {
            if (target.kind == PieceKind.General && target.side != piece.side) {
                result += Move(cell, Cell(cell.x, y))
            }
            break
        }
        y += piece.side.forward
    }
    return result
}

internal fun Board.advisorMoves(cell: Cell, piece: Piece): List<Move> {
    val result = mutableListOf<Move>()
    val palaceRows = if (piece.side == Side.Red) 7..9 else 0..2
    listOf(Cell(1, 1), Cell(1, -1), Cell(-1, 1), Cell(-1, -1)).forEach { step ->
        val to = Cell(cell.x + step.x, cell.y + step.y)
        if (to.x in 3..5 && to.y in palaceRows) addIfAvailable(result, cell, to, piece.side)
    }
    return result
}

internal fun Board.elephantMoves(cell: Cell, piece: Piece): List<Move> {
    val result = mutableListOf<Move>()
    listOf(Cell(2, 2), Cell(2, -2), Cell(-2, 2), Cell(-2, -2)).forEach { step ->
        val to = Cell(cell.x + step.x, cell.y + step.y)
        val eye = Cell(cell.x + step.x / 2, cell.y + step.y / 2)
        val staysHome = if (piece.side == Side.Red) to.y in 5..9 else to.y in 0..4
        if (staysHome && pieceAt(eye) == null) addIfAvailable(result, cell, to, piece.side)
    }
    return result
}

internal fun Board.horseMoves(cell: Cell, piece: Piece): List<Move> {
    val result = mutableListOf<Move>()
    val candidates = listOf(
        Cell(1, 2) to Cell(0, 1),
        Cell(-1, 2) to Cell(0, 1),
        Cell(1, -2) to Cell(0, -1),
        Cell(-1, -2) to Cell(0, -1),
        Cell(2, 1) to Cell(1, 0),
        Cell(2, -1) to Cell(1, 0),
        Cell(-2, 1) to Cell(-1, 0),
        Cell(-2, -1) to Cell(-1, 0)
    )
    candidates.forEach { (step, leg) ->
        if (pieceAt(Cell(cell.x + leg.x, cell.y + leg.y)) == null) {
            addIfAvailable(result, cell, Cell(cell.x + step.x, cell.y + step.y), piece.side)
        }
    }
    return result
}

internal fun Board.rookMoves(cell: Cell, piece: Piece): List<Move> =
    scanLines(cell, piece.side, cannon = false)

internal fun Board.cannonMoves(cell: Cell, piece: Piece): List<Move> =
    scanLines(cell, piece.side, cannon = true)

internal fun Board.scanLines(cell: Cell, side: Side, cannon: Boolean): List<Move> {
    val result = mutableListOf<Move>()
    val directions = listOf(Cell(1, 0), Cell(-1, 0), Cell(0, 1), Cell(0, -1))
    directions.forEach { dir ->
        var x = cell.x + dir.x
        var y = cell.y + dir.y
        var screenFound = false
        while (x in 0..8 && y in 0..9) {
            val to = Cell(x, y)
            val target = pieceAt(to)
            if (!cannon) {
                if (target == null) {
                    result += Move(cell, to)
                } else {
                    if (target.side != side) result += Move(cell, to)
                    break
                }
            } else {
                if (!screenFound) {
                    if (target == null) {
                        result += Move(cell, to)
                    } else {
                        screenFound = true
                    }
                } else if (target != null) {
                    if (target.side != side) result += Move(cell, to)
                    break
                }
            }
            x += dir.x
            y += dir.y
        }
    }
    return result
}

internal fun Board.soldierMoves(cell: Cell, piece: Piece): List<Move> {
    val result = mutableListOf<Move>()
    addIfAvailable(result, cell, Cell(cell.x, cell.y + piece.side.forward), piece.side)
    val crossedRiver = if (piece.side == Side.Red) cell.y <= 4 else cell.y >= 5
    if (crossedRiver) {
        addIfAvailable(result, cell, Cell(cell.x - 1, cell.y), piece.side)
        addIfAvailable(result, cell, Cell(cell.x + 1, cell.y), piece.side)
    }
    return result
}

internal fun Board.findGeneral(side: Side): Cell? {
    for (y in 0..9) {
        for (x in 0..8) {
            val piece = this[y][x]
            if (piece?.side == side && piece.kind == PieceKind.General) return Cell(x, y)
        }
    }
    return null
}

internal fun Board.isInCheck(side: Side): Boolean {
    val general = findGeneral(side) ?: return true
    for (y in 0..9) {
        for (x in 0..8) {
            val piece = this[y][x] ?: continue
            if (piece.side != side) {
                if (pseudoMovesFrom(Cell(x, y)).any { it.to == general }) return true
            }
        }
    }
    return false
}

internal fun Board.controlsCell(from: Cell, target: Cell, piece: Piece): Boolean {
    if (from == target || target.x !in 0..8 || target.y !in 0..9) return false
    val dx = target.x - from.x
    val dy = target.y - from.y
    return when (piece.kind) {
        PieceKind.General -> {
            val palaceRows = if (piece.side == Side.Red) 7..9 else 0..2
            val palaceStep = target.x in 3..5 && target.y in palaceRows && abs(dx) + abs(dy) == 1
            val targetPiece = pieceAt(target)
            palaceStep ||
                (targetPiece?.kind == PieceKind.General && targetPiece.side != piece.side && dx == 0 && isPathClear(from, target))
        }
        PieceKind.Advisor -> {
            val palaceRows = if (piece.side == Side.Red) 7..9 else 0..2
            target.x in 3..5 && target.y in palaceRows && abs(dx) == 1 && abs(dy) == 1
        }
        PieceKind.Elephant -> {
            val staysHome = if (piece.side == Side.Red) target.y in 5..9 else target.y in 0..4
            val eye = Cell(from.x + dx / 2, from.y + dy / 2)
            staysHome && abs(dx) == 2 && abs(dy) == 2 && pieceAt(eye) == null
        }
        PieceKind.Horse -> {
            val valid = (abs(dx) == 1 && abs(dy) == 2) || (abs(dx) == 2 && abs(dy) == 1)
            val leg = if (abs(dx) == 2) Cell(from.x + dx / 2, from.y) else Cell(from.x, from.y + dy / 2)
            valid && pieceAt(leg) == null
        }
        PieceKind.Rook -> (dx == 0 || dy == 0) && isPathClear(from, target)
        PieceKind.Cannon -> (dx == 0 || dy == 0) && screensBetween(from, target) == 1
        PieceKind.Soldier -> {
            val forward = dy == piece.side.forward && dx == 0
            val sideways = from.isAcrossRiver(piece.side) && dy == 0 && abs(dx) == 1
            forward || sideways
        }
    }
}

internal fun Board.isPathClear(from: Cell, to: Cell): Boolean = screensBetween(from, to) == 0

internal fun Board.screensBetween(from: Cell, to: Cell): Int {
    val stepX = (to.x - from.x).coerceIn(-1, 1)
    val stepY = (to.y - from.y).coerceIn(-1, 1)
    if (from.x != to.x && from.y != to.y) return Int.MAX_VALUE
    var x = from.x + stepX
    var y = from.y + stepY
    var count = 0
    while (x != to.x || y != to.y) {
        if (pieceAt(Cell(x, y)) != null) count += 1
        x += stepX
        y += stepY
    }
    return count
}

internal fun Board.isOpeningPhase(): Boolean = countPieces() >= 28

internal fun Board.countPieces(): Int {
    var count = 0
    for (row in this) {
        for (piece in row) {
            if (piece != null) count += 1
        }
    }
    return count
}

internal fun Cell.rankFromHome(side: Side): Int =
    if (side == Side.Red) 9 - y else y
