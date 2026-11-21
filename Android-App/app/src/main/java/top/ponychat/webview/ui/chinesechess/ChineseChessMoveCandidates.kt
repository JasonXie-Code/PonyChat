package top.ponychat.webview.ui.chinesechess

import android.content.Context
import java.util.Locale
import kotlin.math.abs
import kotlin.random.Random
import top.ponychat.webview.data.model.XiangqiEntryCard
import top.ponychat.webview.data.model.XiangqiExecuteMove
import top.ponychat.webview.data.model.XiangqiMoveCandidate
import top.ponychat.webview.data.model.XiangqiPoint

internal fun buildMoveCandidates(
    board: Board,
    side: Side,
    playerSide: Side,
    difficulty: Int,
    mistakeRate: Int,
    plyCount: Int = 0,
    userInstruction: String = "",
    recentMoves: List<Map<String, Any?>> = emptyList(),
    entryCard: XiangqiEntryCard? = null,
    varietyKey: String = "",
    context: Context? = null,
    eleEyeSession: EleEyeEngine.Session? = null
): List<XiangqiMoveCandidate> {
    val playStyle = entryCard.playStyle()
    val deadlineMs = System.currentTimeMillis() + xiangqiComputeBudgetMillis(difficulty)
    val rankedRaw = rankMoves(board, side, difficulty, plyCount, deadlineMs)
    val ranked = rankedRaw
        .filterNot { it.isRepeatedCheckPattern(recentMoves, side) }
        .ifEmpty { rankedRaw.filterNot { it.isCheck && it.winnerAfterMove == null } }
        .ifEmpty { rankedRaw }
    if (ranked.isEmpty()) return emptyList()
    val rng = Random(stableXiangqiSeed(board, side, plyCount, playStyle, varietyKey))
    val remainingMs = (deadlineMs - System.currentTimeMillis()).coerceAtLeast(0L)
    val eleEyeResult = when {
        remainingMs < 60L -> null
        eleEyeSession != null -> eleEyeSession.bestMove(
            board = board,
            side = side,
            difficulty = difficulty,
            playStyle = playStyle,
            plyCount = plyCount,
            maxMillis = remainingMs
        )
        context != null -> EleEyeEngine.bestMove(
            context = context,
            board = board,
            side = side,
            difficulty = difficulty,
            playStyle = playStyle,
            plyCount = plyCount,
            maxMillis = remainingMs
        )
        else -> null
    }
    val eleEyeRanked = eleEyeResult?.move?.let { engineMove ->
        ranked.firstOrNull { it.move == engineMove }
    }
    val rankedByEngine = eleEyeRanked?.let { engineBest ->
        listOf(engineBest) + ranked.filterNot { it.move == engineBest.move }
    } ?: ranked
    val picked = mutableListOf<Pair<String, RankedMove>>()
    fun add(tag: String, move: RankedMove?) {
        if (move == null) return
        if (picked.none { it.second.move == move.move }) picked += tag to move
    }
    val userRequested = findUserRequestedMove(ranked, side, userInstruction)
    add("user_requested", userRequested)
    val novelty = if (playStyle == ChessPlayStyle.Playful && plyCount <= 10) {
        ranked.playfulOpeningNoveltyCandidate(side, rng)
    } else {
        null
    }
    add("novelty", novelty)
    val bookMove = if (playStyle == ChessPlayStyle.Textbook && plyCount <= 12) {
        eleEyeRanked ?: ranked.openingBookCandidate(side, playStyle, plyCount)
    } else {
        ranked.openingBookCandidate(side, playStyle, plyCount)
    }
    add("book", bookMove)
    add("best", eleEyeRanked ?: rankedByEngine.firstOrNull())
    add(
        "solid",
        rankedByEngine.firstOrNull { it.winnerAfterMove == side }
            ?: rankedByEngine.firstOrNull { it.practicalPenalty <= 80 && !it.isCheck && it.scoreDelta > -260 }
            ?: rankedByEngine.firstOrNull { it.practicalPenalty <= 160 && it.scoreDelta > -420 }
    )
    add(
        "active",
        rankedByEngine.firstOrNull { it.isActiveMove(side) && it.practicalPenalty < 260 && it.move != rankedByEngine.first().move }
            ?: rankedByEngine.firstOrNull { it.isActiveMove(side) && it.practicalPenalty < 320 }
    )
    add("good", rankedByEngine.drop(1).firstOrNull { it.isReasonablySafe() } ?: rankedByEngine.drop(1).firstOrNull() ?: rankedByEngine.firstOrNull())
    val risky = rankedByEngine.firstOrNull {
        (it.isCapture || it.isCheck) &&
            it.move != rankedByEngine.first().move &&
            it.practicalPenalty < 260
    }
        ?: rankedByEngine.getOrNull((rankedByEngine.size / 2).coerceAtMost(rankedByEngine.lastIndex))
    add("risky", risky)
    val safePoolSize = when {
        difficulty >= 14 -> 3
        difficulty >= 7 -> 5
        else -> 8
    }.coerceAtMost(rankedByEngine.size).coerceAtLeast(1)
    val randomSafePool = rankedByEngine
        .take(safePoolSize)
        .filter { it.isReasonablySafe() && picked.none { pickedMove -> pickedMove.second.move == it.move } }
        .ifEmpty { rankedByEngine.take(safePoolSize).filter { pickedMove -> picked.none { it.second.move == pickedMove.move } } }
    add("random_safe", randomSafePool.pickWith(rng))
    val blunderOffset = (1 + mistakeRate / 12).coerceAtMost((rankedByEngine.size - 1).coerceAtLeast(0))
    add("blunder", rankedByEngine.getOrNull(rankedByEngine.lastIndex - blunderOffset / 2) ?: rankedByEngine.lastOrNull())
    val remaining = rankedByEngine.filter { rankedMove ->
        rankedMove.practicalPenalty < 260 && picked.none { it.second.move == rankedMove.move }
    }.ifEmpty {
        rankedByEngine.filter { rankedMove -> picked.none { it.second.move == rankedMove.move } }
    }
    add("random", remaining.pickWith(rng) ?: rankedByEngine.pickWith(rng))
    return picked.take(8).mapIndexed { index, (tag, rankedMove) ->
        rankedMove.toCandidate(
            id = "c${index + 1}",
            tag = tag,
            board = board,
            playerSide = playerSide
        )
    }
}

internal fun extractXiangqiMoveNotation(text: String): String? {
    val normalized = normalizeXiangqiNotation(text)
    val pattern = Regex("[将帅士仕象相马車车炮砲兵卒][一二三四五六七八九1-9][平进退][一二三四五六七八九1-9]")
    return pattern.find(normalized)?.value
}

internal fun Move.xiangqiNotationVariants(piece: Piece): Set<String> {
    val side = piece.side
    val fromFile = from.fileNumberForSide(side)
    val targetValue = notationTargetValue(piece.kind, side)
    val action = when {
        to.y == from.y -> "平"
        (to.y - from.y) * side.forward > 0 -> "进"
        else -> "退"
    }
    val pieces = when (piece.kind) {
        PieceKind.General -> listOf(piece.text, "将", "帅")
        PieceKind.Advisor -> listOf(piece.text, "士", "仕")
        PieceKind.Elephant -> listOf(piece.text, "象", "相")
        PieceKind.Horse -> listOf("马")
        PieceKind.Rook -> listOf("车")
        PieceKind.Cannon -> listOf("炮")
        PieceKind.Soldier -> listOf(piece.text, "兵", "卒")
    }.distinct()
    val fromNumbers = listOf(fromFile.toString(), xiangqiNumberText(fromFile))
    val targetNumbers = listOf(targetValue.toString(), xiangqiNumberText(targetValue))
    return pieces.flatMap { pieceText ->
        fromNumbers.flatMap { fromText ->
            targetNumbers.map { targetText ->
                normalizeXiangqiNotation("$pieceText$fromText$action$targetText")
            }
        }
    }.toSet()
}

internal fun Move.notationTargetValue(kind: PieceKind, side: Side): Int =
    if (to.y == from.y || kind in setOf(PieceKind.Horse, PieceKind.Elephant, PieceKind.Advisor)) {
        to.fileNumberForSide(side)
    } else {
        abs(to.y - from.y).coerceIn(1, 9)
    }

internal fun Cell.fileNumberForSide(side: Side): Int =
    if (side == Side.Red) 9 - x else x + 1

internal fun xiangqiNumberText(value: Int): String =
    "一二三四五六七八九".getOrNull(value - 1)?.toString() ?: value.toString()

internal fun normalizeXiangqiNotation(value: String): String {
    val numberMap = mapOf(
        '１' to '1',
        '２' to '2',
        '３' to '3',
        '４' to '4',
        '５' to '5',
        '６' to '6',
        '７' to '7',
        '８' to '8',
        '９' to '9',
        '壹' to '一',
        '贰' to '二',
        '貳' to '二',
        '叁' to '三',
        '參' to '三',
        '肆' to '四',
        '伍' to '五',
        '陆' to '六',
        '陸' to '六',
        '柒' to '七',
        '捌' to '八',
        '玖' to '九'
    )
    return value
        .map { numberMap[it] ?: it }
        .joinToString("")
        .replace("車", "车")
        .replace("砲", "炮")
        .replace("進", "进")
        .replace("後", "后")
        .replace(Regex("\\s+"), "")
}

internal fun RankedMove.isRepeatedCheckPattern(recentMoves: List<Map<String, Any?>>, side: Side): Boolean {
    if (!isCheck || winnerAfterMove != null) return false
    val movingKind = piece?.kind?.name?.lowercase().orEmpty()
    if (movingKind.isBlank()) return false
    val sameSideMoves = recentMoves
        .filter { it["side"] == side.apiValue() }
        .takeLast(4)
    val recentChecks = sameSideMoves.filter { it["is_check"] == true }
    val sameKindChecks = recentChecks.count { it["piece_kind"] == movingKind }
    val sideHasJustRepeatedChecks = sameSideMoves.takeLast(2).size == 2 &&
        sameSideMoves.takeLast(2).all { it["is_check"] == true }
    return sameKindChecks >= 2 || (sideHasJustRepeatedChecks && sameKindChecks >= 1)
}

internal fun findUserRequestedMove(ranked: List<RankedMove>, side: Side, instruction: String): RankedMove? {
    val text = instruction.trim()
    if (text.isBlank()) return null
    if (text.hasMoveCommandNegation()) return null
    findExactRequestedNotationMove(ranked, side, text)?.let { return it }
    findDirectedRequestedMove(ranked, side, text)?.let { return it }
    return findCaptureRequestedMove(ranked, side, text)
}

internal fun findExactRequestedNotationMove(ranked: List<RankedMove>, side: Side, text: String): RankedMove? {
    val notation = extractXiangqiMoveNotation(text) ?: return null
    val beforeNotation = normalizeXiangqiNotation(text).substringBefore(notation)
    if (beforeNotation.indicatesUserMoveSubject() && !beforeNotation.hasRoleMoveSubject()) return null
    return ranked.firstOrNull { rankedMove ->
        val moving = rankedMove.piece ?: return@firstOrNull false
        moving.side == side && rankedMove.move.xiangqiNotationVariants(moving).any { it == notation }
    }
}

internal data class UserMoveDirective(
    val moverKinds: Set<PieceKind> = emptySet(),
    val targetKinds: Set<PieceKind> = emptySet(),
    val requireCapture: Boolean = false,
    val requireCheck: Boolean = false,
    val targetCenterFile: Boolean = false,
    val direction: RequestedMoveDirection? = null
)

internal enum class RequestedMoveDirection {
    Forward,
    Retreat,
    Sideways
}

internal fun findDirectedRequestedMove(ranked: List<RankedMove>, side: Side, text: String): RankedMove? {
    val directive = parseUserMoveDirective(text) ?: return null
    return ranked
        .filter { rankedMove ->
            val moving = rankedMove.piece
            moving?.side == side &&
                (directive.moverKinds.isEmpty() || moving.kind in directive.moverKinds) &&
                (!directive.requireCapture || rankedMove.capturedPiece?.side == side.opponent) &&
                (directive.targetKinds.isEmpty() || rankedMove.capturedPiece?.kind in directive.targetKinds) &&
                (!directive.requireCheck || rankedMove.isCheck) &&
                (!directive.targetCenterFile || rankedMove.move.to.x == 4) &&
                directive.direction.matches(rankedMove.move, side)
        }
        .maxWithOrNull(
            compareBy<RankedMove> { if (it.winnerAfterMove == side) 1 else 0 }
                .thenBy { it.centerFileDirectivePriority(side) }
                .thenBy { it.score }
                .thenBy { it.scoreDelta }
        )
}

internal fun parseUserMoveDirective(rawText: String): UserMoveDirective? {
    val text = normalizeXiangqiNotation(rawText)
    val actionIndex = text.firstMoveActionIndex()
    val beforeAction = if (actionIndex >= 0) text.substring(0, actionIndex) else text
    val afterAction = if (actionIndex >= 0) text.substring(actionIndex + 1) else ""
    if (beforeAction.indicatesUserMoveSubject() && !beforeAction.hasRoleMoveSubject()) return null

    val roleDirected = beforeAction.hasRoleMoveSubject() ||
        text.hasRoleMoveSubject() ||
        text.startsWithAny(listOf("用", "把", "走", "下", "出", "跳", "飞", "退", "进", "平", "帮我", "给我")) ||
        text.containsAny(centerFileDirectiveWords) ||
        text.contains("将我") ||
        text.contains("将军") ||
        text.contains("收回") ||
        text.contains("撤回")
    if (!roleDirected) return null

    val moverKinds = beforeAction.pieceKindsMentioned()
        .ifEmpty {
            if (beforeAction.isBlank() || beforeAction == text) text.pieceKindsMentioned() else emptySet()
        }
    val targetKinds = afterAction.pieceKindsMentioned()
    if (targetKinds.any { afterAction.mentionsRoleOwnedTarget(it) }) return null

    val direction = when {
        text.containsAny(retreatActionWords) -> RequestedMoveDirection.Retreat
        text.containsAny(sidewaysActionWords) -> RequestedMoveDirection.Sideways
        text.containsAny(forwardActionWords) -> RequestedMoveDirection.Forward
        else -> null
    }
    val targetCenterFile = text.containsAny(centerFileDirectiveWords)
    val requireCapture = text.containsAny(captureActionWords) && direction != RequestedMoveDirection.Retreat
    val requireCheck = text.containsAny(checkActionWords)

    if (moverKinds.isEmpty() && targetKinds.isEmpty() && !requireCapture && !requireCheck && !targetCenterFile && direction == null) {
        return null
    }
    return UserMoveDirective(
        moverKinds = moverKinds,
        targetKinds = targetKinds,
        requireCapture = requireCapture,
        requireCheck = requireCheck,
        targetCenterFile = targetCenterFile,
        direction = direction
    )
}

internal fun RequestedMoveDirection?.matches(move: Move, side: Side): Boolean =
    when (this) {
        null -> true
        RequestedMoveDirection.Forward -> (move.to.y - move.from.y) * side.forward > 0
        RequestedMoveDirection.Retreat -> (move.to.y - move.from.y) * side.forward < 0
        RequestedMoveDirection.Sideways -> move.to.y == move.from.y
    }

internal val checkActionWords = listOf("将我", "将军", "将一下", "将一军")
internal val retreatActionWords = listOf("收回", "退回", "撤回", "撤退", "回去", "回来", "后退", "往后")
internal val forwardActionWords = listOf("往前", "向前", "前进", "压上", "冲上", "进攻", "推进")
internal val sidewaysActionWords = listOf("横", "平", "旁边", "左", "右")
internal val centerFileDirectiveWords = listOf("中间", "中路", "中线", "中宫", "中心", "当头炮", "当中炮", "中炮")

internal fun RankedMove.centerFileDirectivePriority(side: Side): Int {
    if (piece?.kind != PieceKind.Cannon || move.to.x != 4) return 0
    return when (move.from.fileNumberForSide(side)) {
        2 -> 3
        8 -> 2
        else -> 1
    }
}

internal fun String.firstMoveActionIndex(): Int =
    (captureActionWords + checkActionWords + retreatActionWords + forwardActionWords + sidewaysActionWords)
        .map { indexOf(it) }
        .filter { it >= 0 }
        .minOrNull() ?: -1

internal fun String.pieceKindsMentioned(): Set<PieceKind> =
    PieceKind.entries.filter { mentionsPieceKind(it) }.toSet()

internal fun String.containsAny(words: List<String>): Boolean =
    words.any { contains(it) }

internal fun findCaptureRequestedMove(ranked: List<RankedMove>, side: Side, instruction: String): RankedMove? {
    val text = instruction.trim()
    if (text.hasMoveCommandNegation()) return null
    val captureVerb = captureActionWords.map { text.indexOf(it) }.filter { it >= 0 }.minOrNull()
        ?: return null
    val beforeVerb = text.substring(0, captureVerb)
    val afterVerb = text.substring(captureVerb + 1)
    if (beforeVerb.indicatesUserCaptureSubject() && !beforeVerb.hasRoleCaptureSubject()) return null
    val beforeKinds = PieceKind.entries.filter { beforeVerb.mentionsPieceKind(it) }
    val afterKinds = PieceKind.entries.filter { afterVerb.mentionsPieceKind(it) }
    val targetKindsFromBefore = afterKinds.isEmpty() &&
        beforeKinds.isNotEmpty() &&
        text.looksLikeTargetOnlyCaptureRequest()
    val moverKinds = if (targetKindsFromBefore) emptyList() else beforeKinds
    val targetKinds = when {
        afterKinds.isNotEmpty() -> afterKinds
        targetKindsFromBefore -> beforeKinds
        else -> emptyList()
    }
    if (targetKinds.isEmpty()) return null
    if (moverKinds.isEmpty() && !text.looksLikeRoleCaptureRequest()) return null
    if (targetKinds.any { text.mentionsRoleOwnedTarget(it) }) return null
    return ranked
        .filter { rankedMove ->
            val moving = rankedMove.piece
            val captured = rankedMove.capturedPiece
            moving?.side == side &&
                captured?.side == side.opponent &&
                (moverKinds.isEmpty() || moving.kind in moverKinds) &&
                captured.kind in targetKinds
        }
        .maxWithOrNull(compareBy<RankedMove> { it.score }.thenBy { it.scoreDelta })
}

internal val captureActionWords = listOf("吃", "打", "拿", "捉", "收")

internal fun String.hasMoveCommandNegation(): Boolean =
    listOf(
        "别吃", "不要吃", "先别吃", "不能吃", "不许吃",
        "别打", "不要打", "先别打", "不能打", "不许打",
        "别拿", "不要拿", "先别拿",
        "别捉", "不要捉", "别收", "不要收",
        "别将", "不要将", "不能将", "不许将",
        "别退", "不要退", "别撤", "不要撤"
    ).any { contains(it) }

internal fun String.indicatesUserCaptureSubject(): Boolean =
    listOf("我", "我的", "我方", "我这边", "让我").any { contains(it) }

internal fun String.indicatesUserMoveSubject(): Boolean =
    listOf("我", "我的", "我方", "我这边", "让我", "我要", "我想", "我来", "我用").any { contains(it) }

internal fun String.looksLikeRoleCaptureRequest(): Boolean =
    startsWithAny(captureActionWords) ||
        hasRoleCaptureSubject() ||
        looksLikeTargetOnlyCaptureRequest()

internal fun String.hasRoleCaptureSubject(): Boolean =
    listOf("你", "你的", "你方", "你这边", "帮我").any { contains(it) }

internal fun String.hasRoleMoveSubject(): Boolean =
    listOf("你", "你的", "你方", "你这边", "让你", "叫你", "帮我", "给我").any { contains(it) }

internal fun String.looksLikeTargetOnlyCaptureRequest(): Boolean =
    listOf("想不想", "要不要", "能不能", "敢不敢", "可不可以", "可以不可以", "好不好", "能吃", "吃吗").any { contains(it) }

internal fun String.startsWithAny(words: List<String>): Boolean =
    words.any { startsWith(it) }

internal fun String.mentionsRoleOwnedTarget(kind: PieceKind): Boolean =
    pieceKindMentionWords(kind).any { word ->
        contains("你的$word") || contains("你这边的$word") || contains("你方$word")
    }

internal fun String.mentionsPieceKind(kind: PieceKind): Boolean =
    pieceKindMentionWords(kind).any { contains(it) }

internal fun pieceKindMentionWords(kind: PieceKind): List<String> =
    when (kind) {
        PieceKind.General -> listOf("将", "帅", "老将", "将帅")
        PieceKind.Advisor -> listOf("士", "仕")
        PieceKind.Elephant -> listOf("象", "相")
        PieceKind.Horse -> listOf("马")
        PieceKind.Rook -> listOf("车", "車")
        PieceKind.Cannon -> listOf("炮", "砲")
        PieceKind.Soldier -> listOf("兵", "卒")
    }

internal data class TacticalExplanation(
    val reason: String = "",
    val caution: String = ""
)

internal fun Board.tacticalExplanationFor(
    move: Move,
    side: Side,
    playerSide: Side,
    capturedPiece: Piece?,
    isCheck: Boolean
): TacticalExplanation {
    val moving = pieceAt(move.from) ?: return TacticalExplanation()
    val nextBoard = applyMove(move)
    val rawBeforeThreats = attackersOf(move.from, side.opponent)
    val ignoredBeforeThreats = rawBeforeThreats.filter { (from, attacker) ->
        isRoutineOpeningCannonHorseThreat(
            attackerCell = from,
            attacker = attacker,
            targetCell = move.from,
            target = moving
        )
    }
    val beforeThreats = rawBeforeThreats - ignoredBeforeThreats.toSet()
    val afterThreats = nextBoard.attackersOf(move.to, side.opponent)
    val beforeTargets = attackedOpponentPiecesFrom(move.from, moving)
        .map { it.first to it.second.kind }
        .toSet()
    val afterTargets = nextBoard.attackedOpponentPiecesFrom(move.to, moving)
        .filterNot { it.first == move.to }
        .filterNot { target -> capturedPiece != null && target.first == move.to }
    val newTargets = afterTargets.filterNot { it.first to it.second.kind in beforeTargets }
    val beforeProtectedOwn = defendedOwnPiecesFrom(move.from, moving)
        .map { it.first to it.second.kind }
        .toSet()
    val newProtectedOwn = nextBoard.defendedOwnPiecesFrom(move.to, moving)
        .filterNot { it.first to it.second.kind in beforeProtectedOwn }
        .filter { target -> nextBoard.attackersOf(target.first, side.opponent).isNotEmpty() }
    val meaningfulNewProtectedOwn = newProtectedOwn
        .filter { (_, piece) -> piece.kind.isMeaningfulProtectionTarget() }
    val incidentalProtectedOwn = newProtectedOwn - meaningfulNewProtectedOwn.toSet()
    val generalGuardReason = nextBoard.generalGuardReasonFor(
        move = move,
        moving = moving,
        playerSide = playerSide
    )
    val protectedOwnForReason = if (generalGuardReason.isNotBlank()) {
        meaningfulNewProtectedOwn
    } else {
        meaningfulNewProtectedOwn
    }

    val reasons = mutableListOf<String>()
    if (capturedPiece != null) {
        reasons += "吃掉${capturedPiece.roleScopedName(playerSide)}"
    }
    if (isCheck) {
        reasons += "形成将军"
    }
    if (generalGuardReason.isNotBlank()) {
        reasons += generalGuardReason
    }
    if (protectedOwnForReason.isNotEmpty()) {
        reasons += "护住${protectedOwnForReason.toRoleScopedPieceList(playerSide)}"
    }
    if (protectedOwnForReason.isEmpty() && generalGuardReason.isBlank() && beforeThreats.isNotEmpty() && afterThreats.isEmpty()) {
        val attackers = beforeThreats.toRoleScopedPieceList(playerSide)
        reasons += "避开${attackers}，让它吃不到${moving.roleScopedName(playerSide)}"
    } else if (protectedOwnForReason.isEmpty() && generalGuardReason.isBlank() && beforeThreats.isNotEmpty() && afterThreats.size < beforeThreats.size) {
        val attackers = beforeThreats.toRoleScopedPieceList(playerSide)
        reasons += "减少${attackers}对${moving.roleScopedName(playerSide)}的压力"
    }
    if (newTargets.isNotEmpty()) {
        reasons += "形成对${newTargets.toRoleScopedPieceList(playerSide)}的攻击"
    }
    if (reasons.isEmpty()) {
        val beforeDefenders = attackersOf(move.from, side).size
        val afterDefenders = nextBoard.attackersOf(move.to, side).size
        if (afterDefenders > beforeDefenders && afterDefenders > 0) {
            reasons += "换到更有照应的位置"
        }
    }

    val caution = when {
        ignoredBeforeThreats.isNotEmpty() && beforeThreats.isEmpty() ->
            "规则上${ignoredBeforeThreats.toRoleScopedPieceList(playerSide)}能隔子打到底线马，但这是开局常见的弱威胁；不要把这步说成躲开你的炮或为了躲炮。"
        generalGuardReason.isNotBlank() && incidentalProtectedOwn.isNotEmpty() ->
            "这步的防守重点是$generalGuardReason；不要说成主要为了保护${incidentalProtectedOwn.toRoleScopedPieceList(playerSide)}。"
        protectedOwnForReason.isEmpty() && incidentalProtectedOwn.isNotEmpty() ->
            "这步只是顺带照到${incidentalProtectedOwn.toRoleScopedPieceList(playerSide)}；不要说成主要为了保护这些低价值或贴身防守棋子。"
        beforeThreats.isEmpty() ->
            "没有发现${side.opponent.sideOwnerName(playerSide)}棋子正在威胁这枚${moving.text}，不要说这步是在躲开某个具体棋子。"
        afterThreats.isNotEmpty() ->
            "这枚${moving.text}移动后仍可能被${afterThreats.toRoleScopedPieceList(playerSide)}攻击，不要说它已经完全安全。"
        protectedOwnForReason.isNotEmpty() && beforeThreats.isNotEmpty() ->
            "这步同时让${moving.text}离开攻击线，但棋面提示的重点是保护${protectedOwnForReason.toRoleScopedPieceList(playerSide)}，不要只说成躲开${beforeThreats.toRoleScopedPieceList(playerSide)}。"
        else -> ""
    }
    return TacticalExplanation(
        reason = reasons.take(2).joinToString("，"),
        caution = caution
    )
}

private fun PieceKind.isMeaningfulProtectionTarget(): Boolean =
    this in setOf(PieceKind.Rook, PieceKind.Horse, PieceKind.Cannon)

private fun Board.generalGuardReasonFor(
    move: Move,
    moving: Piece,
    playerSide: Side
): String {
    val general = findGeneral(moving.side) ?: return ""
    val generalName = Piece(moving.side, PieceKind.General).roleScopedName(playerSide)
    val targetRank = move.to.rankFromHome(moving.side)
    return when (moving.kind) {
        PieceKind.Elephant ->
            if (move.to.x == general.x && targetRank == 2) {
                "守住${generalName}前面的中路"
            } else {
                ""
            }
        PieceKind.Advisor ->
            if (move.to.x in 3..5 && targetRank <= 2 && abs(move.to.x - general.x) <= 1 && abs(move.to.y - general.y) <= 1) {
                "护住${generalName}身边"
            } else {
                ""
            }
        else -> ""
    }
}

private fun Board.isRoutineOpeningCannonHorseThreat(
    attackerCell: Cell,
    attacker: Piece,
    targetCell: Cell,
    target: Piece
): Boolean {
    if (!isOpeningPhase()) return false
    if (attacker.kind != PieceKind.Cannon || target.kind != PieceKind.Horse) return false
    if (targetCell.rankFromHome(target.side) != 0) return false
    if (attackerCell.x != targetCell.x && attackerCell.y != targetCell.y) return false
    return true
}

private fun List<RankedMove>.playfulOpeningNoveltyCandidate(side: Side, rng: Random): RankedMove? =
    playfulOpeningNoveltyPool(side).pickWith(rng)

private fun List<RankedMove>.playfulOpeningNoveltyPool(side: Side): List<RankedMove> {
    fun priority(rankedMove: RankedMove): Int {
        val piece = rankedMove.piece ?: return 0
        if (rankedMove.winnerAfterMove == side) return 1000
        if (rankedMove.scoreDelta < -1600) return 0
        val fromRank = rankedMove.move.from.rankFromHome(side)
        val toRank = rankedMove.move.to.rankFromHome(side)
        return when (piece.kind) {
            PieceKind.General -> when {
                fromRank == 0 && toRank == 1 && rankedMove.move.from.x == 4 -> 330
                fromRank <= 1 && toRank > fromRank -> 220
                else -> 0
            }
            PieceKind.Soldier -> when {
                fromRank == 3 && toRank == 4 && rankedMove.move.from.x == 4 -> 310
                fromRank == 3 && toRank == 4 && rankedMove.move.from.x in setOf(0, 8) -> 285
                fromRank == 3 && toRank == 4 && rankedMove.move.from.x in setOf(2, 6) -> 260
                else -> 0
            }
            else -> 0
        }
    }
    return mapNotNull { rankedMove ->
        val score = priority(rankedMove)
        if (score > 0) score to rankedMove else null
    }
        .sortedWith(
            compareByDescending<Pair<Int, RankedMove>> { it.first }
                .thenBy { abs(4 - it.second.move.from.x) }
                .thenByDescending { it.second.scoreDelta }
        )
        .map { it.second }
}

internal fun Board.attackersOf(target: Cell, bySide: Side): List<Pair<Cell, Piece>> {
    val attackers = mutableListOf<Pair<Cell, Piece>>()
    for (y in 0..9) {
        for (x in 0..8) {
            val from = Cell(x, y)
            val piece = pieceAt(from) ?: continue
            if (piece.side == bySide && controlsCell(from, target, piece)) {
                attackers += from to piece
            }
        }
    }
    return attackers
}

internal fun Board.attackedOpponentPiecesFrom(from: Cell, piece: Piece): List<Pair<Cell, Piece>> {
    val targets = mutableListOf<Pair<Cell, Piece>>()
    for (y in 0..9) {
        for (x in 0..8) {
            val target = Cell(x, y)
            val targetPiece = pieceAt(target) ?: continue
            if (targetPiece.side != piece.side && controlsCell(from, target, piece)) {
                targets += target to targetPiece
            }
        }
    }
    return targets
}

internal fun Board.defendedOwnPiecesFrom(from: Cell, piece: Piece): List<Pair<Cell, Piece>> {
    val targets = mutableListOf<Pair<Cell, Piece>>()
    for (y in 0..9) {
        for (x in 0..8) {
            val target = Cell(x, y)
            if (target == from) continue
            val targetPiece = pieceAt(target) ?: continue
            if (targetPiece.side == piece.side && controlsCell(from, target, piece)) {
                targets += target to targetPiece
            }
        }
    }
    return targets
}

internal fun Pair<Cell, Piece>.roleScopedPieceName(playerSide: Side): String =
    "${second.side.sideOwnerName(playerSide)}${first.pieceLocationLabel(second)}${second.casualPieceName()}"

internal fun Piece.roleScopedName(playerSide: Side): String =
    "${side.sideOwnerName(playerSide)}$text"

internal fun Side.sideOwnerName(playerSide: Side): String =
    if (this == playerSide) "你的" else "我的"

internal fun Cell.pieceLocationLabel(piece: Piece): String =
    if (piece.kind == PieceKind.Soldier && x == 4) "中路" else ""

internal fun Piece.casualPieceName(): String =
    if (kind == PieceKind.Soldier) "小兵" else text

internal fun List<Pair<Cell, Piece>>.toRoleScopedPieceList(playerSide: Side, limit: Int = 2): String {
    val names = distinctBy { it.first to it.second.side to it.second.kind }
        .take(limit)
        .map { it.roleScopedPieceName(playerSide) }
    return names.joinToString("、")
}

internal fun pieceSpeechFlavor(piece: Piece?, tag: String): String {
    val base = when (piece?.kind) {
        PieceKind.General -> "可以表现成大胆、慌张或调皮地把将帅挪出来；别写成标准棋谱讲解。"
        PieceKind.Advisor -> "可以说补身边、贴过去、挡一下，重点是贴身防守或顺手吃子。"
        PieceKind.Elephant -> "可以说飞回来、补中路、挡一挡，若是守帅/将要说清守的是将帅。"
        PieceKind.Horse -> "可以说跳出去、绕一下、蹦到那里，语气可轻快但要匹配坐标事实。"
        PieceKind.Rook -> "可以说拉出来、横过去、贴上去、冲一下；优势时可更得意，受压时可像找补。"
        PieceKind.Cannon -> "可以说架过去、移开炮口、换条线、隔着打；不要默认说为了躲开开局弱炮威胁。"
        PieceKind.Soldier -> "可以说探路、拱一步、偷跑一格、去你那边玩；连续推兵时要换说法。"
        null -> "只说移动事实，不要补出具体战术因果。"
    }
    val tagHint = when (tag) {
        "novelty" -> "这还是趣味/新手味候选，可带一点整活、试探或坐不住。"
        "risky" -> "这是冒险候选，说法可带不确定、赌一下或逞强。"
        "solid" -> "这是稳健候选，说法可带先稳住、补一下、收一口气。"
        "active" -> "这是主动候选，说法可更兴奋或有压迫感。"
        "user_requested" -> "这是用户建议的候选，若选择它要先接住用户的话，而不是像系统执行命令。"
        "blunder" -> "这是可能看错的候选，若选择它不要过度自信。"
        else -> ""
    }
    return listOf(base, tagHint).filter { it.isNotBlank() }.joinToString(" ")
}

internal fun RankedMove.toSpeechHooks(
    facts: MoveFacts,
    tactical: TacticalExplanation,
    tag: String
): Map<String, String> {
    val hooks = linkedMapOf(
        "plain_fact" to facts.replyHint,
        "piece_voice" to pieceSpeechFlavor(piece, tag),
        "avoid_default_phrases" to "内部风格提醒：“哇/嘿嘿/那我/好凶/顺便/躲开/再说/将你一军/换一手/瞄到”等是容易复用的口癖清单，只用于生成前避让；角色台词不能提到这份清单或表演自己在避开某个词，本轮换开头、动词和收尾。"
    )
    val tacticalFact = tactical.reason.ifBlank {
        "没有明确战术理由时，只能说棋子事实、试探、找位置或角色情绪；不要编造保护/牵制/躲避。"
    }
    hooks["tactical_fact"] = tacticalFact
    if (tactical.caution.isNotBlank()) {
        hooks["tactical_limit"] = tactical.caution
    }
    val emotionHint = when {
        winnerAfterMove != null -> "这手会结束棋局，情绪应按胜负结果明显变化。"
        isCheck && isCapture -> "这手又吃子又将军，可以更兴奋、得意或突然认真。"
        isCheck -> "这手形成将军，可以更有压迫感或调皮地提醒用户正在被逼。"
        capturedPiece != null -> "这手能吃到你的${capturedPiece.text}，可以自然高兴、得意、松一口气或开玩笑。"
        tag == "novelty" -> "这手不一定标准，可以像角色临时冒出新点子。"
        tag == "solid" -> "这手偏稳，可以表达先喘口气、补一下或不冒险。"
        tag == "risky" -> "这手偏冒险，可以表达赌一下、试试看或嘴硬。"
        else -> "普通走子也要承接本局情绪，不要像每步重新开场。"
    }
    hooks["emotion_hint"] = emotionHint
    hooks["relationship_hook"] = "如果用户刚聊天、求饶、挑衅或连续追问，要先接用户的话，再把这手棋说出来。"
    return hooks
}

internal fun RankedMove.toCandidate(
    id: String,
    tag: String,
    board: Board,
    playerSide: Side
): XiangqiMoveCandidate {
    val qualityNote = when (tag) {
        "user_requested" -> "用户刚才要求的合法走法；这是用户请求，不是强制命令，角色可按性格和棋局选择是否接受"
        "book" -> "接近常见开局思路的走法"
        "best" -> "评分较高的走法"
        "solid" -> "稳健保守的走法"
        "active" -> "主动进攻或出子的走法"
        "good" -> "普通稳一点的走法"
        "risky" -> "比较冒一点的走法"
        "novelty" -> "调皮或新手会尝试的合法趣味开局，不一定标准但有角色感"
        "random_safe" -> "带一点随机但不太离谱的走法"
        "blunder" -> "合法但可能看错的走法"
        else -> "普通可走的一步"
    }
    val facts = move.toMoveFacts(
        piece = piece,
        sideFallback = piece?.side ?: Side.Black,
        playerSide = playerSide,
        capturedPiece = capturedPiece,
        isCheck = isCheck
    )
    val side = piece?.side ?: Side.Black
    val tactical = board.tacticalExplanationFor(
        move = move,
        side = side,
        playerSide = playerSide,
        capturedPiece = capturedPiece,
        isCheck = isCheck
    )
    val tacticalNote = tactical.reason.takeIf { it.isNotBlank() }?.let { "；棋面提示：$it" }.orEmpty()
    val cautionNote = tactical.caution.takeIf { it.isNotBlank() }?.let { "；限制：$it" }.orEmpty()
    val note = "$qualityNote；${facts.moveSummary}$tacticalNote$cautionNote"
    return XiangqiMoveCandidate(
        id = id,
        qualityTag = tag,
        move = XiangqiExecuteMove(
            from = XiangqiPoint(move.from.x, move.from.y),
            to = XiangqiPoint(move.to.x, move.to.y),
            piece = piece?.text.orEmpty(),
            notation = facts.notation,
            intent = facts.replyHint,
            confidence = when (tag) {
                "user_requested" -> 0.68
                "book" -> 0.86
                "best" -> 0.9
                "solid" -> 0.82
                "active" -> 0.78
                "good" -> 0.75
                "risky" -> 0.58
                "novelty" -> 0.46
                "random_safe" -> 0.5
                "blunder" -> 0.28
                else -> 0.45
            }
        ),
        score = score,
        scoreDelta = scoreDelta,
        isCapture = isCapture,
        isCheck = isCheck,
        isTerminalWin = winnerAfterMove != null,
        resultAfterMove = winnerAfterMove?.let { "${it.apiValue()}_wins" } ?: "ongoing",
        capturedPiece = capturedPiece?.text,
        side = facts.sideValue,
        direction = facts.direction,
        riverEvent = facts.riverEvent,
        moveSummary = facts.moveSummary,
        replyHint = facts.replyHint,
        tacticalReason = tactical.reason,
        tacticalCaution = tactical.caution,
        speechHooks = toSpeechHooks(
            facts = facts,
            tactical = tactical,
            tag = tag
        ),
        note = note
    )
}

internal fun userRequestedBoardForTest(scenario: String): Board =
    when (scenario) {
        "horse_capture_soldier" -> sparseBoardForTest(
            Cell(4, 0) to Piece(Side.Black, PieceKind.General),
            Cell(4, 9) to Piece(Side.Red, PieceKind.General),
            Cell(4, 5) to Piece(Side.Red, PieceKind.Soldier),
            Cell(2, 2) to Piece(Side.Black, PieceKind.Horse),
            Cell(3, 4) to Piece(Side.Red, PieceKind.Soldier)
        )
        "cannon_check" -> sparseBoardForTest(
            Cell(4, 0) to Piece(Side.Black, PieceKind.General),
            Cell(4, 9) to Piece(Side.Red, PieceKind.General),
            Cell(3, 2) to Piece(Side.Black, PieceKind.Cannon),
            Cell(4, 5) to Piece(Side.Red, PieceKind.Soldier)
        )
        "rook_retreat" -> sparseBoardForTest(
            Cell(4, 0) to Piece(Side.Black, PieceKind.General),
            Cell(4, 9) to Piece(Side.Red, PieceKind.General),
            Cell(4, 5) to Piece(Side.Black, PieceKind.Rook)
        )
        else -> initialBoard()
    }

internal fun userRequestedMoveForTest(instruction: String, side: String, scenario: String): String? {
    val parsedSide = side.toChessPowerSideForTest()
    val board = userRequestedBoardForTest(scenario)
    val ranked = rankMoves(board, parsedSide, difficulty = 8)
    return findUserRequestedMove(ranked, parsedSide, instruction)?.move?.toEleEyeMoveText()
}

internal fun userRequestedPieceKindForTest(instruction: String, side: String, scenario: String): PieceKind? {
    val parsedSide = side.toChessPowerSideForTest()
    val board = userRequestedBoardForTest(scenario)
    val ranked = rankMoves(board, parsedSide, difficulty = 8)
    return findUserRequestedMove(ranked, parsedSide, instruction)?.piece?.kind
}

internal fun generalFlyingLineTacticalReasonForTest(): String {
    val board = sparseBoardForTest(
        Cell(4, 0) to Piece(Side.Black, PieceKind.General),
        Cell(4, 3) to Piece(Side.Black, PieceKind.Soldier),
        Cell(4, 9) to Piece(Side.Red, PieceKind.General)
    )
    return board.tacticalExplanationFor(
        move = Move(Cell(4, 0), Cell(4, 1)),
        side = Side.Black,
        playerSide = Side.Red,
        capturedPiece = null,
        isCheck = false
    ).reason
}

internal fun openingCannonHorseThreatTextForTest(): Pair<String, String> {
    val explanation = initialBoard().tacticalExplanationFor(
        move = Move(Cell(7, 9), Cell(6, 7)),
        side = Side.Red,
        playerSide = Side.Red,
        capturedPiece = null,
        isCheck = false
    )
    return explanation.reason to explanation.caution
}

internal fun centralElephantGuardTextForTest(): Pair<String, String> {
    val board = sparseBoardForTest(
        Cell(4, 0) to Piece(Side.Black, PieceKind.General),
        Cell(6, 0) to Piece(Side.Black, PieceKind.Rook),
        Cell(4, 9) to Piece(Side.Red, PieceKind.General),
        Cell(2, 9) to Piece(Side.Red, PieceKind.Elephant),
        Cell(6, 5) to Piece(Side.Red, PieceKind.Soldier)
    )
    val explanation = board.tacticalExplanationFor(
        move = Move(Cell(2, 9), Cell(4, 7)),
        side = Side.Red,
        playerSide = Side.Black,
        capturedPiece = null,
        isCheck = false
    )
    return explanation.reason to explanation.caution
}

internal fun rookAdvanceIncidentalAdvisorProtectionTextForTest(): Pair<String, String> {
    val board = sparseBoardForTest(
        Cell(4, 0) to Piece(Side.Black, PieceKind.General),
        Cell(4, 5) to Piece(Side.Black, PieceKind.Rook),
        Cell(4, 9) to Piece(Side.Red, PieceKind.General),
        Cell(4, 8) to Piece(Side.Red, PieceKind.Advisor),
        Cell(0, 9) to Piece(Side.Red, PieceKind.Rook)
    )
    val explanation = board.tacticalExplanationFor(
        move = Move(Cell(0, 9), Cell(0, 8)),
        side = Side.Red,
        playerSide = Side.Black,
        capturedPiece = null,
        isCheck = false
    )
    return explanation.reason to explanation.caution
}

internal fun playfulOpeningNoveltyMovesForTest(side: String): List<String> {
    val parsedSide = side.toChessPowerSideForTest()
    return rankMoves(initialBoard(), parsedSide, difficulty = 3, plyCount = 0)
        .playfulOpeningNoveltyPool(parsedSide)
        .map { it.move.toEleEyeMoveText() }
}

internal fun playfulOpeningCandidateTagsForTest(varietyKey: String): List<String> =
    buildMoveCandidates(
        board = initialBoard(),
        side = Side.Red,
        playerSide = Side.Black,
        difficulty = 3,
        mistakeRate = 34,
        plyCount = 0,
        entryCard = XiangqiEntryCard(
            powerTier = "novice",
            chessStyle = mapOf("play_style" to "playful"),
            speech = mapOf("playfulness" to 5)
        ),
        varietyKey = varietyKey
    ).map { it.qualityTag }

internal fun XiangqiMoveCandidate.toMove(): Move =
    Move(
        from = Cell(move.from.x, move.from.y),
        to = Cell(move.to.x, move.to.y)
    )
