package top.ponychat.webview.ui.chinesechess

import android.content.Context
import java.io.BufferedReader
import java.io.File
import java.io.FileOutputStream
import java.io.InputStreamReader
import java.io.OutputStreamWriter
import java.util.Locale
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit
import top.ponychat.webview.util.DebugLog

internal data class EleEyeResult(
    val move: Move,
    val rawMove: String,
    val infoLines: List<String>
)

internal object EleEyeEngine {
    private const val ENGINE_NAME = "libeleeye.so"
    private const val BOOK_ASSET = "eleeye/BOOK.DAT"
    private const val BOOK_FILE = "BOOK.DAT"

    fun openSession(context: Context): Session =
        Session(context.applicationContext)

    fun bestMove(
        context: Context,
        board: Board,
        side: Side,
        difficulty: Int,
        playStyle: ChessPlayStyle,
        plyCount: Int,
        maxMillis: Long = Long.MAX_VALUE
    ): EleEyeResult? {
        val session = openSession(context)
        return try {
            session.bestMove(
                board = board,
                side = side,
                difficulty = difficulty,
                playStyle = playStyle,
                plyCount = plyCount,
                maxMillis = maxMillis
            )
        } finally {
            session.close()
        }
    }

    class Session internal constructor(private val context: Context) : AutoCloseable {
        private val lines = LinkedBlockingQueue<String>()
        private var process: Process? = null
        private var writer: OutputStreamWriter? = null
        private var readerThread: Thread? = null
        internal var startCountForTest: Int = 0
            private set

        @Synchronized
        fun warmUp(): Boolean =
            ensureStarted()

        @Synchronized
        fun bestMove(
            board: Board,
            side: Side,
            difficulty: Int,
            playStyle: ChessPlayStyle,
            plyCount: Int,
            maxMillis: Long = Long.MAX_VALUE
        ): EleEyeResult? {
            val budgetMillis = if (maxMillis == Long.MAX_VALUE) {
                xiangqiComputeBudgetMillis(difficulty)
            } else {
                maxMillis.coerceAtMost(xiangqiComputeBudgetMillis(difficulty))
            }
            val goMillis = eleEyeSearchMillis(
                difficulty = difficulty,
                playStyle = playStyle,
                plyCount = plyCount,
                availableMillis = budgetMillis
            )
            if (goMillis < 40L) return null
            val fen = board.toEleEyeFen(side)
            val capturedLines = mutableListOf<String>()
            return try {
                if (!ensureStarted()) return null
                lines.clear()
                send("position fen $fen")
                send("go time $goMillis")
                val waitMillis = budgetMillis.coerceAtLeast(goMillis + 80L)
                val bestLine = readUntil(waitMillis, capturedLines) {
                    it.startsWith("bestmove ") || it.startsWith("nobestmove")
                } ?: run {
                    closeProcess(sendQuit = false)
                    return null
                }
                val rawMove = bestLine.split(Regex("\\s+")).getOrNull(1).orEmpty()
                val move = rawMove.toEleEyeMove() ?: return null
                DebugLog.d("ChineseChess", "EleEye bestmove $rawMove for $fen")
                EleEyeResult(move = move, rawMove = rawMove, infoLines = capturedLines.toList())
            } catch (error: Exception) {
                closeProcess(sendQuit = false)
                DebugLog.w("ChineseChess", "EleEye unavailable, fallback to local engine: ${error.message}", error)
                null
            }
        }

        @Synchronized
        override fun close() {
            closeProcess(sendQuit = true)
        }

        private fun ensureStarted(): Boolean {
            if (process?.isRunning() == true && writer != null) return true
            closeProcess(sendQuit = false)
            val engine = findEleEyeExecutable(context) ?: return false
            if (!engine.canExecute()) runCatching { engine.setExecutable(true) }
            val book = ensureEleEyeBookFile(context)
            return try {
                val startedProcess = ProcessBuilder(engine.absolutePath)
                    .redirectErrorStream(true)
                    .start()
                process = startedProcess
                startCountForTest += 1
                lines.clear()
                readerThread = Thread({
                    runCatching {
                        BufferedReader(InputStreamReader(startedProcess.inputStream)).useLines { sequence ->
                            sequence.forEach { lines.offer(it) }
                        }
                    }
                }, "EleEyeOutputReader-${System.identityHashCode(this)}").apply {
                    isDaemon = true
                    start()
                }
                writer = OutputStreamWriter(startedProcess.outputStream)
                val capturedLines = mutableListOf<String>()
                send("ucci")
                if (readUntil(1_200L, capturedLines) { it == "ucciok" } == null) {
                    closeProcess(sendQuit = false)
                    return false
                }
                send("setoption usemillisec true")
                send("setoption hashsize 16")
                send("setoption pruning large")
                send("setoption knowledge large")
                if (book != null) {
                    send("setoption usebook true")
                    send("setoption bookfiles ${book.absolutePath}")
                } else {
                    send("setoption usebook false")
                }
                DebugLog.d("ChineseChess", "EleEye session warmed up")
                true
            } catch (error: Exception) {
                closeProcess(sendQuit = false)
                DebugLog.w("ChineseChess", "EleEye startup failed: ${error.message}", error)
                false
            }
        }

        private fun send(command: String) {
            val currentWriter = writer ?: return
            currentWriter.write(command)
            currentWriter.write("\n")
            currentWriter.flush()
        }

        private fun readUntil(
            timeoutMs: Long,
            capturedLines: MutableList<String>,
            accepts: (String) -> Boolean
        ): String? {
            val deadline = System.currentTimeMillis() + timeoutMs.coerceAtLeast(1L)
            while (System.currentTimeMillis() < deadline) {
                val waitMs = (deadline - System.currentTimeMillis()).coerceAtLeast(1L)
                val line = lines.poll(waitMs.coerceAtMost(100L), TimeUnit.MILLISECONDS) ?: continue
                val trimmed = line.trim()
                capturedLines += trimmed
                if (accepts(trimmed)) return trimmed
            }
            return null
        }

        private fun closeProcess(sendQuit: Boolean) {
            if (sendQuit) runCatching { send("quit") }
            runCatching { writer?.close() }
            runCatching { process?.destroy() }
            runCatching { process?.waitFor(250L, TimeUnit.MILLISECONDS) }
            writer = null
            process = null
            readerThread = null
            lines.clear()
        }
    }

    private fun Process.isRunning(): Boolean =
        try {
            exitValue()
            false
        } catch (_: IllegalThreadStateException) {
            true
        }

    private fun ensureEleEyeBookFile(context: Context): File? =
        runCatching {
            val dir = File(context.filesDir, "eleeye")
            if (!dir.exists()) dir.mkdirs()
            val file = File(dir, BOOK_FILE)
            if (!file.isFile || file.length() < 90_000L) {
                context.assets.open(BOOK_ASSET).use { input ->
                    FileOutputStream(file).use { output -> input.copyTo(output) }
                }
            }
            file
        }.getOrNull()

    private fun findEleEyeExecutable(context: Context): File? {
        val nativeDir = File(context.applicationInfo.nativeLibraryDir)
        val direct = File(nativeDir, ENGINE_NAME)
        if (direct.isFile) return direct
        return nativeDir.listFiles()
            ?.asSequence()
            ?.map { File(it, ENGINE_NAME) }
            ?.firstOrNull { it.isFile }
    }
}

internal fun Board.toEleEyeFen(sideToMove: Side): String {
    val rows = map { row ->
        val builder = StringBuilder()
        var empty = 0
        for (piece in row) {
            if (piece == null) {
                empty += 1
            } else {
                if (empty > 0) {
                    builder.append(empty)
                    empty = 0
                }
                builder.append(piece.toEleEyeFenChar())
            }
        }
        if (empty > 0) builder.append(empty)
        builder.toString()
    }.joinToString("/")
    val side = if (sideToMove == Side.Red) "r" else "b"
    return "$rows $side - - 0 1"
}

internal fun Piece.toEleEyeFenChar(): Char {
    val lower = when (kind) {
        PieceKind.General -> 'k'
        PieceKind.Advisor -> 'a'
        PieceKind.Elephant -> 'e'
        PieceKind.Horse -> 'h'
        PieceKind.Rook -> 'r'
        PieceKind.Cannon -> 'c'
        PieceKind.Soldier -> 'p'
    }
    return if (side == Side.Red) lower.uppercaseChar() else lower
}

internal fun Move.toEleEyeMoveText(): String =
    "${from.toEleEyeCellText()}${to.toEleEyeCellText()}"

internal fun Cell.toEleEyeCellText(): String {
    val file = ('a'.code + x).toChar()
    val rank = 9 - y
    return "$file$rank"
}

internal fun String.toEleEyeMove(): Move? {
    val text = trim().lowercase(Locale.ROOT)
    if (text.length < 4) return null
    fun parseCell(offset: Int): Cell? {
        val x = text[offset] - 'a'
        val rank = text[offset + 1].digitToIntOrNull() ?: return null
        if (x !in 0..8 || rank !in 0..9) return null
        return Cell(x, 9 - rank)
    }
    val from = parseCell(0) ?: return null
    val to = parseCell(2) ?: return null
    return Move(from, to)
}

internal fun initialEleEyeFenForTest(side: String): String =
    initialBoard().toEleEyeFen(side.toChessPowerSideForTest())

internal fun eleEyeMoveRoundTripForTest(move: String): String? =
    move.toEleEyeMove()?.toEleEyeMoveText()

internal fun eleEyeBestMoveSmokeForTest(context: Context): String? =
    EleEyeEngine.bestMove(
        context = context.applicationContext,
        board = initialBoard(),
        side = Side.Red,
        difficulty = ChessPowerTier.Advanced.engineDifficulty,
        playStyle = ChessPlayStyle.Textbook,
        plyCount = 0
    )?.rawMove

internal fun xiangqiComputeBudgetMillisForTest(powerTier: String): Long =
    xiangqiComputeBudgetMillis(powerTier.toChessPowerTier().engineDifficulty)

internal fun xiangqiFlavorReplyLookaheadCountForTest(powerTier: String): Int =
    xiangqiFlavorReplyLookaheadCount(powerTier.toChessPowerTier().engineDifficulty)

internal fun xiangqiEleEyeSearchMillisForTest(
    powerTier: String,
    playStyle: String,
    plyCount: Int = 0
): Long {
    val tier = powerTier.toChessPowerTier()
    return eleEyeSearchMillis(
        difficulty = tier.engineDifficulty,
        playStyle = playStyle.toChessPlayStyle() ?: ChessPlayStyle.Textbook,
        plyCount = plyCount,
        availableMillis = xiangqiComputeBudgetMillis(tier.engineDifficulty)
    )
}

internal fun sparseBoardForTest(vararg pieces: Pair<Cell, Piece>): Board {
    val board = MutableList(10) { MutableList<Piece?>(9) { null } }
    for ((cell, piece) in pieces) {
        board[cell.y][cell.x] = piece
    }
    return board.map { it.toList() }
}

internal fun String?.toChessPowerSideForTest(): Side =
    if (this?.trim()?.lowercase(Locale.ROOT) == "black") Side.Black else Side.Red
