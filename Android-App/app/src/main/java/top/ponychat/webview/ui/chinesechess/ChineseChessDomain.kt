package top.ponychat.webview.ui.chinesechess

import java.util.Locale
import top.ponychat.webview.data.model.XiangqiCharacterReply
import top.ponychat.webview.data.model.XiangqiEntryCard
import top.ponychat.webview.data.model.XiangqiExecuteMove
import top.ponychat.webview.data.model.XiangqiMoveCandidate

internal enum class Side {
    Red,
    Black;

    val opponent: Side
        get() = if (this == Red) Black else Red

    val forward: Int
        get() = if (this == Red) -1 else 1

    val label: String
        get() = if (this == Red) "红方" else "黑方"
}

internal fun Side.apiValue(): String = if (this == Side.Red) "red" else "black"

internal enum class ChessPowerTier(
    val apiValue: String,
    val label: String,
    val engineDifficulty: Int,
    val engineMistakeRate: Int
) {
    Novice("novice", "新手", 3, 34),
    Junior("junior", "初级", 8, 18),
    Intermediate("intermediate", "中级", 12, 8),
    Advanced("advanced", "高级", 16, 0)
}

internal fun String?.toChessPowerTier(): ChessPowerTier =
    when (this?.trim()?.lowercase()) {
        "novice", "newbie", "beginner", "新手" -> ChessPowerTier.Novice
        "junior", "basic", "初级" -> ChessPowerTier.Junior
        "intermediate", "medium", "中级" -> ChessPowerTier.Intermediate
        "advanced", "expert", "高级" -> ChessPowerTier.Advanced
        else -> ChessPowerTier.Junior
    }

internal fun XiangqiEntryCard?.powerTier(): ChessPowerTier =
    this?.powerTier.toChessPowerTier()

internal enum class ChessPlayStyle(
    val apiValue: String,
    val label: String
) {
    Attacking("attacking", "进攻型"),
    Cautious("cautious", "谨慎型"),
    Playful("playful", "调皮型"),
    Textbook("textbook", "教科书型")
}

internal fun String?.toChessPlayStyle(): ChessPlayStyle? {
    val normalized = this
        ?.trim()
        ?.lowercase(Locale.ROOT)
        ?.replace("-", "_")
        ?.replace(" ", "_")
        ?: return null
    return when (normalized) {
        "attacking", "attack", "active", "aggressive", "进攻型", "攻击型", "主动型" -> ChessPlayStyle.Attacking
        "cautious", "careful", "defensive", "solid", "safe", "谨慎型", "防守型", "稳健型" -> ChessPlayStyle.Cautious
        "playful", "tricky", "chaotic", "random", "mischievous", "调皮型", "乱下型", "整活型" -> ChessPlayStyle.Playful
        "textbook", "book", "bookish", "standard", "classical", "教科书型", "棋谱型", "标准型" -> ChessPlayStyle.Textbook
        else -> null
    }
}

internal fun Any?.asXiangqiInt(default: Int): Int =
    when (this) {
        is Number -> toInt()
        is String -> trim().toIntOrNull() ?: default
        else -> default
    }

internal fun Any?.asXiangqiIntOrNull(): Int? =
    when (this) {
        is Number -> toInt()
        is String -> trim().toIntOrNull()
        else -> null
    }

internal fun XiangqiEntryCard?.playStyle(): ChessPlayStyle {
    val style = this?.chessStyle.orEmpty()
    val explicitStyle = sequenceOf("play_style", "opening_style", "style")
        .mapNotNull { style[it]?.toString().toChessPlayStyle() }
        .firstOrNull()
    if (explicitStyle != null) return explicitStyle

    val speech = this?.speech.orEmpty()
    val attackBias = style["attack_bias"].asXiangqiInt(3)
    val defenseBias = style["defense_bias"].asXiangqiInt(3)
    val riskTolerance = style["risk_tolerance"].asXiangqiInt(3)
    val playfulness = speech["playfulness"].asXiangqiInt(3)
    return when {
        playfulness >= 4 && riskTolerance >= 3 -> ChessPlayStyle.Playful
        attackBias >= 4 && attackBias >= defenseBias -> ChessPlayStyle.Attacking
        defenseBias >= 4 && defenseBias > attackBias -> ChessPlayStyle.Cautious
        else -> ChessPlayStyle.Textbook
    }
}

internal fun xiangqiCandidateTagOrderForTest(
    powerTier: String?,
    playStyle: String?,
    configuredTags: List<String> = emptyList()
): List<String> =
    xiangqiCandidateTagOrder(
        powerTier = powerTier.toChessPowerTier(),
        playStyle = playStyle.toChessPlayStyle() ?: ChessPlayStyle.Textbook,
        configuredTags = configuredTags
    )

internal fun xiangqiCandidateTagOrder(
    powerTier: ChessPowerTier,
    playStyle: ChessPlayStyle,
    configuredTags: List<String>
): List<String> {
    val styleOrder = when (powerTier) {
        ChessPowerTier.Novice -> when (playStyle) {
            ChessPlayStyle.Attacking -> listOf("random_safe", "active", "risky", "good", "random", "blunder", "best", "book")
            ChessPlayStyle.Cautious -> listOf("random_safe", "solid", "good", "random", "blunder", "best", "risky", "book")
            ChessPlayStyle.Playful -> listOf("novelty", "random_safe", "random", "blunder", "risky", "good", "active", "best", "book")
            ChessPlayStyle.Textbook -> listOf("random_safe", "good", "book", "solid", "random", "blunder", "best", "risky")
        }
        ChessPowerTier.Junior -> when (playStyle) {
            ChessPlayStyle.Attacking -> listOf("active", "risky", "good", "best", "random_safe", "random", "blunder", "book")
            ChessPlayStyle.Cautious -> listOf("solid", "good", "best", "random_safe", "book", "random", "risky", "blunder")
            ChessPlayStyle.Playful -> listOf("novelty", "random_safe", "good", "risky", "random", "active", "blunder", "best", "book")
            ChessPlayStyle.Textbook -> listOf("book", "good", "best", "solid", "random_safe", "risky", "random", "blunder")
        }
        ChessPowerTier.Intermediate -> when (playStyle) {
            ChessPlayStyle.Attacking -> listOf("active", "best", "risky", "good", "book", "solid", "random_safe", "random", "blunder")
            ChessPlayStyle.Cautious -> listOf("solid", "best", "good", "book", "random_safe", "risky", "random", "blunder")
            ChessPlayStyle.Playful -> listOf("good", "active", "random_safe", "risky", "best", "book", "random", "blunder")
            ChessPlayStyle.Textbook -> listOf("book", "best", "good", "solid", "active", "random_safe", "risky", "random", "blunder")
        }
        ChessPowerTier.Advanced -> when (playStyle) {
            ChessPlayStyle.Attacking -> listOf("active", "best", "risky", "good", "book", "solid", "random_safe", "random", "blunder")
            ChessPlayStyle.Cautious -> listOf("solid", "best", "book", "good", "active", "random_safe", "risky", "random", "blunder")
            ChessPlayStyle.Playful -> listOf("best", "active", "good", "random_safe", "risky", "book", "random", "blunder")
            ChessPlayStyle.Textbook -> listOf("book", "best", "solid", "good", "active", "random_safe", "risky", "random", "blunder")
        }
    }
    val configured = configuredTags
        .map { it.trim() }
        .filter { it.isNotBlank() }
    return (styleOrder.take(3) + configured + styleOrder).distinct()
}

internal fun XiangqiEntryCard?.preferredCandidateTags(): List<String> {
    val configured = this?.executionPolicy?.get("prefer_candidate_tags")
    val tags = (configured as? List<*>)
        ?.mapNotNull { it?.toString()?.trim()?.takeIf(String::isNotBlank) }
        .orEmpty()
    return xiangqiCandidateTagOrder(powerTier(), playStyle(), tags)
}

internal fun XiangqiEntryCard?.userRequestAffinity(): Int {
    val policy = this?.executionPolicy.orEmpty()
    return sequenceOf(
        "user_request_affinity",
        "user_directive_affinity",
        "suggestion_affinity",
        "compliance_bias"
    )
        .mapNotNull { policy[it].asXiangqiIntOrNull() }
        .firstOrNull()
        ?.coerceIn(0, 5)
        ?: 3
}

internal fun List<XiangqiMoveCandidate>.orderedForPolicy(entryCard: XiangqiEntryCard?): List<XiangqiMoveCandidate> {
    if (size <= 1) return this
    val order = entryCard.preferredCandidateTags()
    val userRequestPriority = when (entryCard.userRequestAffinity()) {
        5 -> -5
        4 -> 5
        3 -> 35
        2 -> 35
        1 -> order.size * 10 + 5
        else -> order.size * 10 + 8
    }
    return sortedWith(
        compareBy<XiangqiMoveCandidate> {
            when (it.qualityTag) {
                "user_requested" -> userRequestPriority
                else -> order.indexOf(it.qualityTag).let { index ->
                    when {
                        index < 0 -> order.size * 10 + 10
                        index < 3 -> index * 10
                        else -> index * 10 + 10
                    }
                }
            }
        }.thenBy { it.id }
    )
}

internal fun List<XiangqiMoveCandidate>.fallbackCandidate(entryCard: XiangqiEntryCard?): XiangqiMoveCandidate? =
    orderedForPolicy(entryCard).firstOrNull()

private fun xiangqiMoveKey(fromX: Int, fromY: Int, toX: Int, toY: Int): String =
    "$fromX,$fromY->$toX,$toY"

internal fun XiangqiMoveCandidate.moveKey(): String =
    xiangqiMoveKey(move.from.x, move.from.y, move.to.x, move.to.y)

private fun Any?.xiangqiPointPair(): Pair<Int, Int>? {
    val raw = this as? Map<*, *> ?: return null
    val x = when (val value = raw["x"]) {
        is Number -> value.toInt()
        is String -> value.toIntOrNull()
        else -> null
    } ?: return null
    val y = when (val value = raw["y"]) {
        is Number -> value.toInt()
        is String -> value.toIntOrNull()
        else -> null
    } ?: return null
    return x to y
}

internal fun Map<String, Any?>.historyMoveKey(): String? {
    val from = this["from"].xiangqiPointPair() ?: return null
    val to = this["to"].xiangqiPointPair() ?: return null
    return xiangqiMoveKey(from.first, from.second, to.first, to.second)
}

private fun String?.xiangqiPieceKindKey(): String? {
    val clean = this?.trim().orEmpty()
    if (clean.isBlank()) return null
    return when (clean.lowercase(Locale.ROOT)) {
        "general", "king", "将", "帅" -> "general"
        "advisor", "guard", "士", "仕" -> "advisor"
        "elephant", "bishop", "象", "相" -> "elephant"
        "horse", "knight", "马" -> "horse"
        "rook", "chariot", "车", "車" -> "rook"
        "cannon", "炮", "砲" -> "cannon"
        "soldier", "pawn", "兵", "卒" -> "soldier"
        else -> clean
    }
}

private fun XiangqiMoveCandidate.pieceKindKey(): String? =
    move.piece.xiangqiPieceKindKey()

private fun Map<String, Any?>.historyPieceKindKey(): String? =
    this["piece_kind"]?.toString().xiangqiPieceKindKey()
        ?: this["piece"]?.toString().xiangqiPieceKindKey()

private fun Map<String, Any?>.historyCapturedPieceKindKey(): String? =
    this["captured_piece_kind"]?.toString().xiangqiPieceKindKey()
        ?: this["captured_piece"]?.toString().xiangqiPieceKindKey()

internal fun xiangqiSameHistoryMoveRepeatCount(
    currentMove: Map<String, Any?>?,
    recentMoves: List<Map<String, Any?>>
): Int {
    val moveToCompare = currentMove ?: return 0
    val currentKey = moveToCompare.historyMoveKey() ?: return 0
    val currentPieceKind = moveToCompare.historyPieceKindKey()
    return recentMoves.count { move ->
        move.historyMoveKey() == currentKey &&
            (currentPieceKind == null || move.historyPieceKindKey() == currentPieceKind)
    }
}

internal fun List<XiangqiMoveCandidate>.withoutRecentlyUndoneMoves(
    recentlyUndoneMoves: List<Map<String, Any?>>
): List<XiangqiMoveCandidate> {
    if (size <= 1 || recentlyUndoneMoves.isEmpty()) return this
    val blockedKeys = recentlyUndoneMoves
        .mapNotNull { it.historyMoveKey() }
        .toSet()
    val withoutExactRepeat = if (blockedKeys.isEmpty()) {
        this
    } else {
        filterNot { it.moveKey() in blockedKeys }.ifEmpty { this }
    }
    val blockedPieceKinds = recentlyUndoneMoves
        .mapNotNull { it.historyPieceKindKey() }
        .toSet()
    if (blockedPieceKinds.isEmpty()) return withoutExactRepeat
    return withoutExactRepeat
        .filterNot { it.pieceKindKey() in blockedPieceKinds }
        .ifEmpty { withoutExactRepeat }
}

internal fun xiangqiOrderedCandidateTagsForTest(
    powerTier: String?,
    playStyle: String?,
    candidateTags: List<String>,
    speech: Map<String, Any?> = emptyMap(),
    relationship: Map<String, Any?> = emptyMap(),
    chessStyle: Map<String, Any?> = emptyMap(),
    executionPolicy: Map<String, Any?> = emptyMap()
): List<String> {
    val resolvedChessStyle = mapOf("play_style" to playStyle) + chessStyle
    val resolvedExecutionPolicy = mapOf(
        "prefer_candidate_tags" to xiangqiCandidateTagOrderForTest(powerTier, playStyle)
    ) + executionPolicy
    val card = XiangqiEntryCard(
        powerTier = powerTier,
        relationship = relationship,
        speech = speech,
        chessStyle = resolvedChessStyle,
        executionPolicy = resolvedExecutionPolicy
    )
    return candidateTags.mapIndexed { index, tag ->
        XiangqiMoveCandidate(
            id = "c${index + 1}",
            qualityTag = tag,
            move = XiangqiExecuteMove()
        )
    }.orderedForPolicy(card).map { it.qualityTag }
}

internal enum class PieceKind(
    val redText: String,
    val blackText: String,
    val value: Int
) {
    General("帅", "将", 10000),
    Advisor("仕", "士", 120),
    Elephant("相", "象", 120),
    Horse("马", "马", 270),
    Rook("车", "车", 600),
    Cannon("炮", "炮", 300),
    Soldier("兵", "卒", 70);

    fun text(side: Side): String = if (side == Side.Red) redText else blackText
}

internal data class Piece(val side: Side, val kind: PieceKind) {
    val text: String = kind.text(side)
}

internal data class Cell(val x: Int, val y: Int)

internal data class Move(val from: Cell, val to: Cell)

internal data class HistoryEntry(
    val board: Board,
    val turn: Side,
    val message: String,
    val lastMove: Move?
)

internal data class TapResult(
    val game: GameState,
    val move: Move? = null
)

internal enum class XiangqiUndoRequester {
    User,
    Character
}

internal data class XiangqiPendingUndoRequest(
    val requester: XiangqiUndoRequester,
    val steps: Int,
    val reason: String = "",
    val waitingForResponse: Boolean = false
)

internal enum class XiangqiUndoDecision {
    Approve,
    Reject,
    Request
}

internal data class GameState(
    val board: Board = initialBoard(),
    val turn: Side = Side.Red,
    val selected: Cell? = null,
    val targets: Set<Cell> = emptySet(),
    val history: List<HistoryEntry> = emptyList(),
    val message: String = "红方行棋",
    val winner: Side? = null,
    val lastMove: Move? = null
)

internal typealias Board = List<List<Piece?>>

private val xiangqiHighValuePieceKinds = setOf("rook", "horse", "cannon")

private fun PieceKind.xiangqiKindKey(): String = name.lowercase(Locale.ROOT)

private fun xiangqiHighValuePieceLabel(kind: String): String =
    when (kind) {
        "rook" -> "车"
        "horse" -> "马"
        "cannon" -> "炮"
        else -> kind
    }

internal fun xiangqiCharacterMaterialPressureContext(
    board: Board,
    playerSide: Side,
    moveHistory: List<Map<String, Any?>>
): Map<String, Any?> {
    val characterSide = playerSide.opponent
    val remainingByKind = xiangqiHighValuePieceKinds.associateWith { kind ->
        board.sumOf { row ->
            row.count { piece ->
                piece?.side == characterSide && piece.kind.xiangqiKindKey() == kind
            }
        }
    }
    val remainingHighValueCount = remainingByKind.values.sum()
    val lastMove = moveHistory.lastOrNull().orEmpty()
    val lastCapturedKind = lastMove.historyCapturedPieceKindKey()
    val lastCapturedHighValue = lastMove["actor"] == "user" &&
        lastMove["is_capture"] == true &&
        lastCapturedKind in xiangqiHighValuePieceKinds
    val lowHighValueMaterial = remainingHighValueCount <= 2
    if (!lastCapturedHighValue && !lowHighValueMaterial) return emptyMap()

    val reason = when {
        lastCapturedHighValue && lowHighValueMaterial -> "recent_high_value_loss_and_low_remaining_material"
        lastCapturedHighValue -> "recent_high_value_loss"
        else -> "low_remaining_high_value_material"
    }
    val severity = when {
        remainingHighValueCount <= 1 -> "high"
        lastCapturedKind == "rook" -> "high"
        lowHighValueMaterial -> "high"
        else -> "medium"
    }
    return mapOf(
        "active" to true,
        "severity" to severity,
        "reason" to reason,
        "remaining_high_value_count" to remainingHighValueCount,
        "remaining_high_value_pieces" to remainingByKind.mapKeys { (kind, _) ->
            xiangqiHighValuePieceLabel(kind)
        },
        "recent_lost_piece" to if (lastCapturedHighValue) {
            mapOf(
                "piece" to (lastMove["captured_piece"] ?: xiangqiHighValuePieceLabel(lastCapturedKind.orEmpty())),
                "kind" to lastCapturedKind,
                "move_summary" to lastMove["move_summary"]
            )
        } else {
            null
        }
    )
}

internal fun xiangqiCharacterMaterialMomentumContext(
    board: Board,
    playerSide: Side,
    moveHistory: List<Map<String, Any?>>
): Map<String, Any?> {
    val userSide = playerSide
    val remainingUserPieces = board.sumOf { row ->
        row.count { piece -> piece?.side == userSide && piece.kind != PieceKind.General }
    }
    val remainingUserHighValueByKind = xiangqiHighValuePieceKinds.associateWith { kind ->
        board.sumOf { row ->
            row.count { piece ->
                piece?.side == userSide && piece.kind.xiangqiKindKey() == kind
            }
        }
    }
    val lastMove = moveHistory.lastOrNull().orEmpty()
    val lastCapturedKind = lastMove.historyCapturedPieceKindKey()
    val capturedUserHighValue = lastMove["actor"] == "character" &&
        lastMove["is_capture"] == true &&
        lastCapturedKind in xiangqiHighValuePieceKinds
    val userPiecesAreFew = remainingUserPieces <= 5
    if (!capturedUserHighValue && !userPiecesAreFew) return emptyMap()

    val reason = when {
        capturedUserHighValue && userPiecesAreFew -> "recent_user_high_value_capture_and_user_low_material"
        capturedUserHighValue -> "recent_user_high_value_capture"
        else -> "user_low_material"
    }
    val severity = when {
        remainingUserPieces <= 3 -> "high"
        lastCapturedKind == "rook" -> "high"
        remainingUserHighValueByKind.values.sum() <= 1 -> "high"
        else -> "medium"
    }
    return mapOf(
        "active" to true,
        "severity" to severity,
        "reason" to reason,
        "user_remaining_piece_count" to remainingUserPieces,
        "user_remaining_high_value_pieces" to remainingUserHighValueByKind.mapKeys { (kind, _) ->
            xiangqiHighValuePieceLabel(kind)
        },
        "recent_captured_user_piece" to if (capturedUserHighValue) {
            mapOf(
                "piece" to (lastMove["captured_piece"] ?: xiangqiHighValuePieceLabel(lastCapturedKind.orEmpty())),
                "kind" to lastCapturedKind,
                "move_summary" to lastMove["move_summary"]
            )
        } else {
            null
        }
    )
}

internal fun XiangqiCharacterReply?.visibleSegments(action: String): List<String> {
    if (this == null || action == "move_silent") return emptyList()
    val structured = listOf(
        reactionText.trim(),
        moveReasonText.trim(),
        casualChatText.trim()
    ).filter { it.isNotBlank() }
    if (structured.isNotEmpty()) return structured
    return listOf(text.trim()).filter { it.isNotBlank() }
}

internal data class XiangqiMovePresentation(
    val preMoveSegments: List<String>,
    val postMoveSegments: List<String>
) {
    val allSegments: List<String>
        get() = preMoveSegments + postMoveSegments
}

internal fun XiangqiCharacterReply?.movePresentation(action: String): XiangqiMovePresentation {
    if (this == null || action == "move_silent") {
        return XiangqiMovePresentation(emptyList(), emptyList())
    }
    val preMove = listOf(reactionText.trim()).filter { it.isNotBlank() }
    val postMove = listOf(
        moveReasonText.trim(),
        casualChatText.trim()
    ).filter { it.isNotBlank() }
    if (preMove.isNotEmpty() || postMove.isNotEmpty()) {
        return XiangqiMovePresentation(preMove, postMove)
    }
    return XiangqiMovePresentation(
        preMoveSegments = listOf(text.trim()).filter { it.isNotBlank() },
        postMoveSegments = emptyList()
    )
}

internal fun List<String>.mergedReplyText(): String =
    joinToString(" ") { it.trim() }.trim()

internal fun XiangqiCharacterReply?.voiceSentencesForSegments(segments: List<String>): List<Map<String, String>> {
    if (this == null || segments.isEmpty()) return emptyList()
    return segments.map { text ->
        mapOf(
            "text" to text,
            "emotion_prompt" to xiangqiVoiceEmotionPrompt(text, emotion, styleTags)
        )
    }
}

internal fun xiangqiUndoDecision(action: String): XiangqiUndoDecision? =
    when (action.trim().lowercase()) {
        "approve_undo", "accept_undo", "allow_undo" -> XiangqiUndoDecision.Approve
        "reject_undo", "deny_undo", "decline_undo" -> XiangqiUndoDecision.Reject
        "request_undo", "ask_undo" -> XiangqiUndoDecision.Request
        else -> null
    }

internal fun xiangqiIsResignAction(action: String): Boolean =
    action.trim().lowercase() in setOf("resign", "surrender", "concede")

private val xiangqiUserSurrenderRegex = Regex(
    "(我|我方|我这边).{0,18}(认输|投降|服输|弃局|不下了)|我输了|^(认输|投降|服输|弃局|不下了)$"
)

private val xiangqiRoleSurrenderRegex = Regex(
    "(你|你的|你方|你这边|对手|角色|她|他).{0,18}(认输|投降|服输|弃局)|认输吧|投降吧|服输吧"
)

internal fun xiangqiLooksLikeUserSurrender(text: String): Boolean {
    val clean = text.trim().trimEnd('。', '！', '!', '？', '?')
    val userIntent = xiangqiUserSurrenderRegex.containsMatchIn(clean)
    if (!userIntent) return false
    val roleOnlyIntent = xiangqiRoleSurrenderRegex.containsMatchIn(clean) &&
        !Regex("(我|我方|我这边).{0,18}(认输|投降|服输|弃局|不下了)|我输了").containsMatchIn(clean)
    return !roleOnlyIntent
}

private val xiangqiUndoPersuasionRegex = Regex(
    "(悔棋|重走|走错|下错|点错|手滑|撤回|退一步|让一步|重新走|重新下|这步不算|刚才那步)"
)

private val xiangqiUndoControlTexts = setOf(
    "同意悔棋",
    "拒绝悔棋",
    "我不同意悔棋"
)

internal fun xiangqiLooksLikeUndoPersuasion(text: String): Boolean =
    text.trim().trimEnd('。', '！', '!', '？', '?') !in xiangqiUndoControlTexts &&
        xiangqiUndoPersuasionRegex.containsMatchIn(text)

internal fun xiangqiLatestUndoPersuasion(dialogueHistory: List<Map<String, Any?>>): String =
    dialogueHistory.asReversed()
        .firstOrNull { entry ->
            val role = (entry["role"] ?: entry["actor"]).toString()
            val text = (entry["text"] ?: entry["content"] ?: entry["reply_text"]).toString()
            role == "user" && xiangqiLooksLikeUndoPersuasion(text)
        }
        ?.let { entry -> (entry["text"] ?: entry["content"] ?: entry["reply_text"]).toString().trim() }
        .orEmpty()

internal fun xiangqiCharacterUndoRequestFromUi(
    ui: Map<String, Any?>,
    fallbackReason: String = ""
): XiangqiPendingUndoRequest? {
    val raw = ui["undo_request"] as? Map<*, *> ?: return null
    val requester = raw["requester"]?.toString()?.trim()?.lowercase()
    if (requester != "character") return null
    val rawSteps = raw["steps"]
    val steps = when (rawSteps) {
        is Number -> rawSteps.toInt()
        is String -> rawSteps.toIntOrNull()
        else -> null
    }?.coerceIn(1, 2) ?: 1
    val reason = listOf(
        raw["reason"]?.toString(),
        raw["message"]?.toString(),
        fallbackReason
    ).firstOrNull { !it.isNullOrBlank() }?.trim().orEmpty()
    return XiangqiPendingUndoRequest(
        requester = XiangqiUndoRequester.Character,
        steps = steps,
        reason = reason,
        waitingForResponse = false
    )
}

internal fun xiangqiUndoDecisionForTest(action: String): String? =
    xiangqiUndoDecision(action)?.name

internal fun xiangqiLatestUndoPersuasionForTest(messages: List<String>): String =
    xiangqiLatestUndoPersuasion(messages.map { mapOf<String, Any?>("role" to "user", "text" to it) })

internal fun xiangqiCharacterUndoStepsForTest(ui: Map<String, Any?>): Int? =
    xiangqiCharacterUndoRequestFromUi(ui)?.steps

internal fun xiangqiOpponentBubbleTextForTest(
    characterMoveThinking: Boolean,
    characterSegmentActive: Boolean,
    characterMessage: String
): String {
    if (characterMessage.isBlank()) return ""
    return if (characterMoveThinking && !characterSegmentActive) "" else characterMessage
}

internal fun xiangqiOpponentSideTextForTest(
    side: String,
    isThinking: Boolean,
    thinkingDotCount: Int = 1
): String =
    opponentSideText(side.toChessPowerSideForTest(), isThinking, thinkingDotCount)

internal fun xiangqiPieceRadiusScaleForTest(): Double {
    val metrics = boardMetrics(width = 840f, height = 1000f)
    return (metrics.pieceRadius / metrics.cell).toDouble()
}

internal fun xiangqiTapSamePieceDeselectsForTest(): Boolean {
    val firstTap = GameState().handleTapResult(Cell(0, 9)).game
    val secondTap = firstTap.handleTapResult(Cell(0, 9)).game
    return firstTap.selected == Cell(0, 9) &&
        secondTap.selected == null &&
        secondTap.targets.isEmpty() &&
        secondTap.message == "红方行棋"
}

internal fun xiangqiShouldCarryUserInstructionForTest(text: String): Boolean =
    shouldCarryUserInstruction(text)

internal fun shouldCarryUserInstruction(text: String): Boolean {
    val clean = text.trim()
    if (clean.isBlank()) return false
    val compact = clean.replace(Regex("\\s+"), "")
    val deferred = Regex("等一下|等下|待会儿?|一会儿?|下回合|下一回合|下一手|下一步|下一次|下次|下步|等轮到你|轮到你|你走的时候|你再|之后|然后你|然后")
        .containsMatchIn(compact)
    val immediate = Regex("(现在|马上|立刻|立即|赶紧|快点|快|先|直接).{0,12}(走|下|动|行棋|出招|把|用)|你先走|你先下|你先来|该你走|该你下")
        .containsMatchIn(compact)
    if (immediate && !deferred) return false

    val hasRoleSubject = Regex("你|你的|帮我|替我|请你|让你").containsMatchIn(compact)
    val hasPiece = Regex("车|马|炮|砲|象|相|士|仕|将|帅|卒|兵|棋").containsMatchIn(compact)
    val hasMoveAction = Regex("走|下|动|行棋|出招|吃|打|拿|捉|收|兑|将|躲|挡|退|进|平|移|放|跳|撤").containsMatchIn(compact)
    val hasImperativeMarker = Regex("把|用|帮我|替我|请你|让你|给我").containsMatchIn(compact)
    val asksBoardFact = Regex("哪个|哪颗|哪枚|哪一个|谁|什么|哪里|哪边|为什么|怎么|有没有|是不是").containsMatchIn(compact)

    if (!hasRoleSubject || !hasPiece || !hasMoveAction) return false
    if (asksBoardFact && !hasImperativeMarker && !deferred) return false
    return deferred || hasImperativeMarker
}

internal fun opponentSideText(side: Side, isThinking: Boolean, thinkingDotCount: Int): String =
    if (isThinking) {
        "正在思考${".".repeat(thinkingDotCount.coerceIn(1, 3))}"
    } else {
        "执${side.label}"
    }

internal fun xiangqiVoiceEmotionPrompt(
    text: String,
    emotion: String,
    styleTags: List<String>
): String {
    val signal = (listOf(emotion) + styleTags + listOf(text))
        .joinToString(" ")
        .lowercase(Locale.ROOT)
    return when {
        signal.contains("aggrieved") ||
            signal.contains("sad") ||
            signal.contains("委屈") ||
            signal.contains("心疼") ||
            signal.contains("欺负") ->
            "委屈一点，语速稍慢，停顿轻。"
        signal.contains("angry") ||
            signal.contains("annoyed") ||
            signal.contains("生气") ||
            signal.contains("哼") ->
            "有点不服气，中速，收尾轻一点。"
        signal.contains("nervous") ||
            signal.contains("scared") ||
            signal.contains("紧张") ||
            signal.contains("将军") ||
            signal.contains("躲") ->
            "稍紧张，中速偏快，短停顿。"
        signal.contains("playful") ||
            signal.contains("cute") ||
            signal.contains("teasing") ||
            signal.contains("撒娇") ||
            signal.contains("调皮") ||
            signal.contains("嘿嘿") ||
            signal.contains("嘛") ->
            "轻快，带一点笑意，尾音自然上扬。"
        signal.contains("smug") ||
            signal.contains("confident") ||
            signal.contains("得意") ||
            signal.contains("赢") ->
            "轻快得意，中速，语调上扬。"
        signal.contains("thinking") ||
            signal.contains("思考") ||
            signal.contains("看一下") ->
            "思考感，中速，短停顿。"
        else ->
            "自然口语，中速，轻微起伏。"
    }
}

internal fun followupDelayMillis(text: String): Long =
    (text.trim().length * 333L).coerceAtLeast(0L)

private const val XIANGQI_MESSAGE_PANEL_MAX_UNITS = 60

internal fun xiangqiMessagePanelSegments(
    text: String,
    maxUnits: Int = XIANGQI_MESSAGE_PANEL_MAX_UNITS
): List<String> {
    val clean = text.trim()
    if (clean.isBlank()) return emptyList()
    if (xiangqiPanelDisplayUnits(clean) <= maxUnits) return listOf(clean)

    val clauses = mutableListOf<String>()
    val current = StringBuilder()
    clean.forEach { char ->
        current.append(char)
        if (char.isXiangqiPanelBreakChar()) {
            clauses += current.toString()
            current.clear()
        }
    }
    if (current.isNotEmpty()) clauses += current.toString()

    val panels = mutableListOf<String>()
    val bucket = StringBuilder()
    fun flushBucket() {
        val panel = bucket.toString().trim()
        if (panel.isNotBlank()) panels += panel
        bucket.clear()
    }

    clauses.forEach { clause ->
        val trimmedClause = clause.trim()
        if (trimmedClause.isBlank()) return@forEach
        if (xiangqiPanelDisplayUnits(trimmedClause) > maxUnits) {
            flushBucket()
            panels += trimmedClause.xiangqiHardWrapPanel(maxUnits)
            return@forEach
        }
        val candidate = bucket.toString() + trimmedClause
        if (bucket.isNotEmpty() && xiangqiPanelDisplayUnits(candidate) > maxUnits) {
            flushBucket()
        }
        bucket.append(trimmedClause)
    }
    flushBucket()
    return panels.ifEmpty { listOf(clean) }
}

internal fun List<String>.xiangqiMessagePanelSegments(): List<String> =
    flatMap { xiangqiMessagePanelSegments(it) }

private fun String.xiangqiHardWrapPanel(maxUnits: Int): List<String> {
    val panels = mutableListOf<String>()
    val bucket = StringBuilder()
    var bucketUnits = 0
    forEach { char ->
        val charUnits = char.xiangqiPanelDisplayUnits()
        if (bucket.isNotEmpty() && bucketUnits + charUnits > maxUnits) {
            panels += bucket.toString().trim()
            bucket.clear()
            bucketUnits = 0
        }
        bucket.append(char)
        bucketUnits += charUnits
    }
    val last = bucket.toString().trim()
    if (last.isNotBlank()) panels += last
    return panels
}

private fun xiangqiPanelDisplayUnits(text: String): Int =
    text.sumOf { it.xiangqiPanelDisplayUnits() }

private fun Char.xiangqiPanelDisplayUnits(): Int =
    when {
        isWhitespace() -> 1
        code <= 0x007F -> 1
        else -> 2
    }

private fun Char.isXiangqiPanelBreakChar(): Boolean =
    this in setOf('，', '。', '！', '？', '；', '、', '：', ',', '.', '!', '?', ';', ':', '～', '~', '…')
