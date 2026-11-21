package top.ponychat.webview.ui.chinesechess

internal const val XIANGQI_DIALOGUE_HISTORY_MAX_ENTRIES = 160
private const val XIANGQI_DIALOGUE_MEMORY_MAX_ENTRIES = 120
private const val XIANGQI_SALIENT_INTERACTION_MAX_ENTRIES = 48
private const val XIANGQI_RECENT_USER_MESSAGE_MAX_ENTRIES = 24

internal fun Board.toApiState(
    turn: Side,
    playerSide: Side,
    winner: Side?
): Map<String, Any?> {
    val pieces = mutableListOf<Map<String, Any?>>()
    val crossedSoldiers = mutableListOf<Map<String, Any?>>()
    for (y in 0..9) {
        for (x in 0..8) {
            val piece = this[y][x] ?: continue
            pieces += mapOf(
                "x" to x,
                "y" to y,
                "side" to piece.side.apiValue(),
                "kind" to piece.kind.name.lowercase(),
                "text" to piece.text
            )
            if (piece.kind == PieceKind.Soldier && Cell(x, y).isAcrossRiver(piece.side)) {
                crossedSoldiers += mapOf(
                    "x" to x,
                    "y" to y,
                    "side" to piece.side.apiValue(),
                    "text" to piece.text
                )
            }
        }
    }
    val redCrossed = crossedSoldiers.count { it["side"] == Side.Red.apiValue() }
    val blackCrossed = crossedSoldiers.count { it["side"] == Side.Black.apiValue() }
    return mapOf(
        "turn" to turn.apiValue(),
        "player_side" to playerSide.apiValue(),
        "character_side" to playerSide.opponent.apiValue(),
        "winner" to winner?.apiValue(),
        "player_in_check" to this.isInCheck(playerSide),
        "character_in_check" to this.isInCheck(playerSide.opponent),
        "crossed_soldiers" to mapOf(
            "red_count" to redCrossed,
            "black_count" to blackCrossed,
            "player_count" to if (playerSide == Side.Red) redCrossed else blackCrossed,
            "character_count" to if (playerSide.opponent == Side.Red) redCrossed else blackCrossed,
            "pieces" to crossedSoldiers
        ),
        "pieces" to pieces
    )
}

internal fun GameState.toEventContext(
    playerSide: Side,
    explicitEventType: String?
): Map<String, Any?> {
    val characterSide = playerSide.opponent
    val inferredEventType = explicitEventType ?: when {
        winner == characterSide -> "character_won"
        winner == playerSide -> "character_lost"
        winner == null && turn == characterSide && board.isInCheck(characterSide) -> "character_in_check"
        winner == null && turn == playerSide && board.isInCheck(playerSide) -> "player_in_check"
        else -> "normal"
    }
    val requiresSpecialReply = inferredEventType in setOf(
        "character_won",
        "character_lost",
        "character_in_check"
    )
    return mapOf(
        "event_type" to inferredEventType,
        "requires_special_reply" to requiresSpecialReply,
        "must_speak" to requiresSpecialReply,
        "must_not_move" to (winner != null),
        "player_side" to playerSide.apiValue(),
        "character_side" to characterSide.apiValue(),
        "turn" to turn.apiValue(),
        "winner" to winner?.apiValue(),
        "character_result" to when (winner) {
            null -> "ongoing"
            characterSide -> "won"
            else -> "lost"
        },
        "character_in_check" to (winner == null && board.isInCheck(characterSide)),
        "player_in_check" to (winner == null && board.isInCheck(playerSide)),
        "last_move" to lastMove?.let {
            mapOf(
                "from" to it.from.toApiMap(),
                "to" to it.to.toApiMap()
            )
        }
    )
}

internal fun xiangqiUserSurrenderContext(
    game: GameState,
    playerSide: Side,
    moveHistory: List<Map<String, Any?>>,
    userText: String
): Map<String, Any?> {
    val characterSide = playerSide.opponent
    val moveCount = moveHistory.size
    fun captureCount(actor: String): Int =
        moveHistory.count { entry ->
            val isCapture = when (val value = entry["is_capture"]) {
                is Boolean -> value
                is String -> value.equals("true", ignoreCase = true)
                else -> false
            }
            entry["actor"] == actor && isCapture
        }
    val userCaptures = captureCount("user")
    val characterCaptures = captureCount("character")
    val playerInCheck = game.board.isInCheck(playerSide)
    val characterInCheck = game.board.isInCheck(characterSide)
    val phase = when {
        moveCount == 0 -> "before_first_move"
        moveCount <= 4 -> "opening_very_early"
        moveCount <= 12 -> "opening"
        moveCount <= 30 -> "middle"
        else -> "late"
    }
    val pressureHint = when {
        playerInCheck -> "player_in_check"
        characterInCheck -> "character_in_check"
        characterCaptures >= userCaptures + 2 -> "character_ahead_by_captures"
        userCaptures >= characterCaptures + 2 -> "user_ahead_by_captures"
        moveCount <= 2 -> "very_early"
        else -> "ordinary"
    }
    val lastMove = moveHistory.lastOrNull().orEmpty()
    return mapOf(
        "requester" to "user",
        "result" to "player_resigned",
        "winner" to characterSide.apiValue(),
        "user_text" to userText.trim(),
        "move_count" to moveCount,
        "phase" to phase,
        "pressure_hint" to pressureHint,
        "player_in_check_before_resign" to playerInCheck,
        "character_in_check_before_resign" to characterInCheck,
        "user_capture_count" to userCaptures,
        "character_capture_count" to characterCaptures,
        "last_actor" to lastMove["actor"],
        "last_move_summary" to lastMove["move_summary"],
        "last_piece" to lastMove["piece"],
        "last_is_capture" to lastMove["is_capture"],
        "last_captured_piece" to lastMove["captured_piece"]
    )
}

internal fun xiangqiBuildGameMemoryRecord(
    gameId: String,
    game: GameState,
    playerSide: Side,
    moveHistory: List<Map<String, Any?>>,
    dialogueHistory: List<Map<String, Any?>>,
    completedReason: String
): Map<String, Any?> {
    val characterSide = playerSide.opponent
    val moveCount = moveHistory.size
    val winner = game.winner
    val characterResult = when (winner) {
        null -> "unfinished"
        characterSide -> "won"
        playerSide -> "lost"
        else -> "unknown"
    }
    val captureStats = xiangqiCaptureStatsForMemory(moveHistory)
    val userCaptured = captureStats["user_captured_character"] as Map<*, *>
    val characterCaptured = captureStats["character_captured_user"] as Map<*, *>
    val userCaptureText = xiangqiCaptureSummaryText(userCaptured)
    val characterCaptureText = xiangqiCaptureSummaryText(characterCaptured)
    val salientInteractions = xiangqiSalientInteractionFacts(
        dialogueHistory,
        limit = XIANGQI_SALIENT_INTERACTION_MAX_ENTRIES
    )
    val recentUserChallenges = xiangqiRecentUserChallengeTexts(dialogueHistory, limit = 8)
    val recentUserMessages = xiangqiRecentUserMessageTexts(
        dialogueHistory,
        limit = XIANGQI_RECENT_USER_MESSAGE_MAX_ENTRIES
    )
    val resultText = when (characterResult) {
        "won" -> "角色获胜"
        "lost" -> "用户获胜"
        "unfinished" -> "未分胜负就重新开始"
        else -> "结果不明"
    }
    val summary = "上一局用户执${playerSide.label}、角色执${characterSide.label}，共${moveCount}手，$resultText。用户吃了角色$userCaptureText；角色吃了用户$characterCaptureText。"
    return mapOf(
        "schema_version" to 1,
        "game_id" to gameId,
        "completed_reason" to completedReason,
        "player_side" to playerSide.apiValue(),
        "character_side" to characterSide.apiValue(),
        "winner" to winner?.apiValue(),
        "character_result" to characterResult,
        "move_count" to moveCount,
        "summary" to summary,
        "salient_interactions" to salientInteractions,
        "recent_user_challenges" to recentUserChallenges,
        "recent_user_messages" to recentUserMessages,
        "dialogue" to xiangqiDialogueForMemory(dialogueHistory),
        "capture_stats" to captureStats,
        "key_moments" to moveHistory
            .mapIndexed { index, entry -> index to entry }
            .filter { (_, entry) ->
                entry["is_capture"] == true || entry["is_check"] == true || entry["actor"] == "character"
            }
            .takeLast(12)
            .map { (index, entry) -> xiangqiCompactMoveForMemory(index, entry) },
        "moves" to moveHistory.mapIndexed { index, entry -> xiangqiCompactMoveForMemory(index, entry) }.takeLast(80),
        "ended_at_ms" to System.currentTimeMillis()
    )
}

private val XIANGQI_POSTGAME_RECALL_KEYWORDS = listOf(
    "输",
    "赢",
    "投降",
    "认输",
    "劝降",
    "赌",
    "惩罚",
    "下局",
    "再来",
    "服不服",
    "约定",
    "记得",
    "记住",
    "口令",
    "留言",
    "昵称",
    "答应",
    "承诺",
    "升级",
    "改成",
    "改为"
)

internal fun xiangqiRecentUserChallengeTexts(
    dialogueHistory: List<Map<String, Any?>>,
    limit: Int = 5
): List<String> {
    val seen = linkedSetOf<String>()
    for (entry in dialogueHistory.asReversed()) {
        if (entry["role"] != "user") continue
        val text = entry["text"]?.toString()?.trim().orEmpty()
        if (text.isBlank()) continue
        if (XIANGQI_POSTGAME_RECALL_KEYWORDS.none { keyword -> text.contains(keyword) }) continue
        seen += text.take(120)
        if (seen.size >= limit) break
    }
    return seen.toList().asReversed()
}

internal fun xiangqiRecentUserMessageTexts(
    dialogueHistory: List<Map<String, Any?>>,
    limit: Int = 12
): List<String> {
    val seen = linkedSetOf<String>()
    for (entry in dialogueHistory.asReversed()) {
        if (entry["role"] != "user") continue
        val text = entry["text"]?.toString()?.trim().orEmpty()
        if (text.isBlank()) continue
        seen += text.take(160)
        if (seen.size >= limit) break
    }
    return seen.toList().asReversed()
}

internal fun xiangqiSalientInteractionFacts(
    dialogueHistory: List<Map<String, Any?>>,
    limit: Int = 10
): List<Map<String, String>> {
    val selected = linkedSetOf<Int>()
    dialogueHistory.forEachIndexed { index, entry ->
        val role = entry["role"]?.toString()?.trim().orEmpty()
        val text = entry["text"]?.toString()?.trim().orEmpty()
        if (text.isBlank()) return@forEachIndexed
        val hasRecallKeyword = XIANGQI_POSTGAME_RECALL_KEYWORDS.any { keyword -> text.contains(keyword) }
        if (role == "user") {
            selected += index
            val next = dialogueHistory.getOrNull(index + 1)
            if (next?.get("role") == "character") {
                selected += index + 1
            }
        } else if (hasRecallKeyword) {
            selected += index
        }
    }
    return selected
        .sorted()
        .mapNotNull { index ->
            val entry = dialogueHistory[index]
            val role = entry["role"]?.toString()?.trim().orEmpty()
            val text = entry["text"]?.toString()?.trim().orEmpty()
            if (role.isBlank() || text.isBlank()) {
                null
            } else {
                mapOf(
                    "role" to role,
                    "text" to text.take(160)
                )
            }
        }
        .takeLast(limit)
}

internal fun xiangqiDialogueForMemory(
    dialogueHistory: List<Map<String, Any?>>,
    limit: Int = XIANGQI_DIALOGUE_MEMORY_MAX_ENTRIES
): List<Map<String, Any?>> =
    dialogueHistory.takeLast(limit).mapNotNull { entry ->
        val role = entry["role"]?.toString()?.trim().orEmpty()
        val text = entry["text"]?.toString()?.trim().orEmpty()
        if (role.isBlank() || text.isBlank()) {
            null
        } else {
            val result = mutableMapOf<String, Any?>(
                "role" to role,
                "text" to text.take(220)
            )
            entry["time_ms"]?.let { result["time_ms"] = it }
            result
        }
    }

internal fun xiangqiBuildPostgameReviewContext(
    gameId: String,
    snapshot: GameState,
    playerSide: Side,
    moveHistory: List<Map<String, Any?>>,
    dialogueHistory: List<Map<String, Any?>>,
    userMessage: String
): Map<String, Any?> {
    if (snapshot.winner == null) return emptyMap()
    val record = xiangqiBuildGameMemoryRecord(
        gameId = gameId,
        game = snapshot,
        playerSide = playerSide,
        moveHistory = moveHistory,
        dialogueHistory = dialogueHistory,
        completedReason = "finished"
    )
    val repeatedUserQuestionCount = userMessage
        .takeIf { it.isNotBlank() }
        ?.let { message ->
            dialogueHistory.count { entry ->
                entry["role"] == "user" && entry["text"]?.toString()?.trim() == message
            }
        }
        ?: 0
    val recentPostgameReplies = dialogueHistory
        .asReversed()
        .filter { it["role"] == "character" }
        .mapNotNull { it["text"]?.toString()?.takeIf(String::isNotBlank) }
        .take(4)
    return mapOf(
        "postgame_review" to mapOf(
            "game_id" to gameId,
            "winner" to snapshot.winner.apiValue(),
            "character_result" to record["character_result"],
            "move_count" to record["move_count"],
            "summary" to record["summary"],
            "salient_interactions" to record["salient_interactions"],
            "recent_user_challenges" to record["recent_user_challenges"],
            "recent_user_messages" to record["recent_user_messages"],
            "dialogue" to record["dialogue"],
            "last_move" to moveHistory.lastOrNull(),
            "key_moments" to record["key_moments"],
            "capture_stats" to record["capture_stats"],
            "repeated_user_question_count" to repeatedUserQuestionCount,
            "recent_postgame_replies" to recentPostgameReplies
        )
    )
}

internal fun xiangqiBuildCrossGameMemory(records: List<Map<String, Any?>>): Map<String, Any?> {
    val recent = records.takeLast(3)
    val latest = recent.lastOrNull()
    return mapOf(
        "schema_version" to 1,
        "completed_games_count" to records.size,
        "has_previous_game" to (latest != null),
        "latest_game" to latest,
        "recent_game_summaries" to recent.map { record ->
            mapOf(
                "game_id" to record["game_id"],
                "character_result" to record["character_result"],
                "move_count" to record["move_count"],
                "summary" to record["summary"],
                "capture_stats" to record["capture_stats"]
            )
        },
        "recent_games" to recent
    )
}

private fun xiangqiCaptureStatsForMemory(moveHistory: List<Map<String, Any?>>): Map<String, Any?> {
    fun emptyBucket(): MutableMap<String, Any?> = mutableMapOf(
        "total" to 0,
        "by_text" to mutableMapOf<String, Int>(),
        "by_kind" to mutableMapOf<String, Int>(),
        "events" to mutableListOf<Map<String, Any?>>()
    )
    val userCapturedCharacter = emptyBucket()
    val characterCapturedUser = emptyBucket()
    moveHistory.forEachIndexed { index, entry ->
        if (entry["is_capture"] != true) return@forEachIndexed
        val actor = entry["actor"]?.toString().orEmpty()
        val bucket = when (actor) {
            "user" -> userCapturedCharacter
            "character" -> characterCapturedUser
            else -> return@forEachIndexed
        }
        val text = entry["captured_piece"]?.toString()?.takeIf { it.isNotBlank() } ?: "未知"
        val kind = entry["captured_piece_kind"]?.toString()?.takeIf { it.isNotBlank() }
            ?: xiangqiInferPieceKindKey(text)
        bucket["total"] = (bucket["total"] as Int) + 1
        @Suppress("UNCHECKED_CAST")
        val byText = bucket["by_text"] as MutableMap<String, Int>
        @Suppress("UNCHECKED_CAST")
        val byKind = bucket["by_kind"] as MutableMap<String, Int>
        @Suppress("UNCHECKED_CAST")
        val events = bucket["events"] as MutableList<Map<String, Any?>>
        byText[text] = (byText[text] ?: 0) + 1
        byKind[kind] = (byKind[kind] ?: 0) + 1
        events += mapOf(
            "move_index" to index,
            "actor" to actor,
            "captured_piece" to text,
            "captured_piece_kind" to kind,
            "move_summary" to entry["move_summary"]
        )
    }
    return mapOf(
        "perspective" to "character",
        "user_captured_character" to userCapturedCharacter,
        "character_captured_user" to characterCapturedUser
    )
}

private fun xiangqiCaptureSummaryText(bucket: Map<*, *>): String {
    val total = bucket["total"] as? Int ?: 0
    if (total <= 0) return "0个子"
    val byText = bucket["by_text"] as? Map<*, *> ?: emptyMap<Any, Any>()
    return byText.entries.joinToString("、") { (piece, count) -> "${count}个$piece" }
}

private fun xiangqiCompactMoveForMemory(index: Int, entry: Map<String, Any?>): Map<String, Any?> =
    mapOf(
        "move_index" to index,
        "actor" to entry["actor"],
        "side" to entry["side"],
        "piece" to entry["piece"],
        "piece_kind" to entry["piece_kind"],
        "is_capture" to entry["is_capture"],
        "captured_piece" to entry["captured_piece"],
        "captured_piece_kind" to entry["captured_piece_kind"],
        "is_check" to entry["is_check"],
        "move_summary" to entry["move_summary"],
        "reply_text" to entry["reply_text"]
    )

private fun xiangqiInferPieceKindKey(text: String): String =
    when (text) {
        "将", "帅" -> "general"
        "士", "仕" -> "advisor"
        "象", "相" -> "elephant"
        "马" -> "horse"
        "车" -> "rook"
        "炮", "砲" -> "cannon"
        "兵", "卒" -> "soldier"
        else -> "unknown"
    }

internal fun Move.toHistoryMap(
    board: Board,
    side: Side,
    playerSide: Side,
    nextGame: GameState,
    actor: String,
    source: String,
    replyText: String?,
    recentRepeatedTerms: List<String> = emptyList()
): Map<String, Any?> {
    val moving = board.pieceAt(from)
    val captured = board.pieceAt(to)
    val isCheck = nextGame.board.isInCheck(nextGame.turn)
    val facts = toMoveFacts(
        piece = moving,
        sideFallback = side,
        playerSide = playerSide,
        capturedPiece = captured,
        isCheck = isCheck
    )
    val entry = mutableMapOf<String, Any?>(
        "actor" to actor,
        "side" to side.apiValue(),
        "side_label" to side.label,
        "piece" to moving?.text.orEmpty(),
        "piece_kind" to moving?.kind?.name?.lowercase().orEmpty(),
        "from" to from.toApiMap(),
        "to" to to.toApiMap(),
        "is_capture" to (captured != null),
        "captured_piece" to captured?.text,
        "captured_piece_kind" to captured?.kind?.name?.lowercase(),
        "captured_piece_side" to captured?.side?.apiValue(),
        "is_check" to isCheck,
        "notation" to facts.notation,
        "direction" to facts.direction,
        "river_event" to facts.riverEvent,
        "move_summary" to facts.moveSummary,
        "reply_hint" to facts.replyHint,
        "reply_text" to replyText.orEmpty(),
        "message" to nextGame.message,
        "source" to source
    )
    val cleanRepeatedTerms = recentRepeatedTerms
        .map { it.trim() }
        .filter { it.isNotBlank() }
        .distinct()
        .take(8)
    if (actor == "character" && cleanRepeatedTerms.isNotEmpty()) {
        entry["近期重复词"] = cleanRepeatedTerms
    }
    return entry
}

internal fun Move.toMoveFacts(
    piece: Piece?,
    sideFallback: Side,
    playerSide: Side,
    capturedPiece: Piece?,
    isCheck: Boolean
): MoveFacts {
    val side = piece?.side ?: sideFallback
    val pieceText = piece?.text.orEmpty()
    val direction = directionFromCharacterPerspective(playerSide)
    val riverEvent = riverEventFor(side)
    val directionOwnerPrefix = if (side == playerSide) "你的" else "我的"
    val moveWord = moveWordFor(piece?.kind, direction, directionOwnerPrefix)
    val captureText = capturedPiece?.let { "，吃掉${it.text}" }.orEmpty()
    val checkText = if (isCheck) "，形成将军" else ""
    val riverText = when (riverEvent) {
        "crossing" -> "并过河"
        "returning" -> "退回自己这边"
        "across" -> "在你那边"
        else -> ""
    }
    val riverClause = if (riverText.isBlank()) "" else "，$riverText"
    val notation = "${side.label}${pieceText}(${from.x},${from.y})->(${to.x},${to.y})"
    val summary = "${side.label}${pieceText}${moveWord}，从(${from.x},${from.y})到(${to.x},${to.y})$captureText$riverClause$checkText"
    val hint = "${pieceText}${moveWord}$captureText$riverClause$checkText"
    return MoveFacts(
        sideValue = side.apiValue(),
        sideLabel = side.label,
        pieceText = pieceText,
        notation = notation,
        direction = direction,
        riverEvent = riverEvent,
        moveSummary = summary,
        replyHint = hint
    )
}

internal fun Move.directionFromCharacterPerspective(playerSide: Side): String {
    val characterSide = playerSide.opponent
    val fromDisplay = from.toMoveFactDisplayCell(characterSide)
    val toDisplay = to.toMoveFactDisplayCell(characterSide)
    val dx = toDisplay.x - fromDisplay.x
    val dy = toDisplay.y - fromDisplay.y
    return when {
        dx == 0 && dy < 0 -> "forward"
        dx == 0 && dy > 0 -> "backward"
        dy == 0 && dx < 0 -> "left"
        dy == 0 && dx > 0 -> "right"
        dx < 0 && dy < 0 -> "left_forward"
        dx > 0 && dy < 0 -> "right_forward"
        dx < 0 && dy > 0 -> "left_backward"
        dx > 0 && dy > 0 -> "right_backward"
        else -> "sideways"
    }
}

private fun Cell.toMoveFactDisplayCell(perspective: Side): Cell =
    if (perspective == Side.Red) this else Cell(8 - x, 9 - y)

internal fun Move.riverEventFor(side: Side): String {
    val fromAcross = from.isAcrossRiver(side)
    val toAcross = to.isAcrossRiver(side)
    return when {
        !fromAcross && toAcross -> "crossing"
        fromAcross && !toAcross -> "returning"
        toAcross -> "across"
        else -> "home"
    }
}

internal fun Cell.isAcrossRiver(side: Side): Boolean =
    if (side == Side.Red) y <= 4 else y >= 5

internal fun moveWordFor(
    kind: PieceKind?,
    direction: String,
    ownerPrefix: String = ""
): String {
    val left = ownedDirection(ownerPrefix, "左边")
    val right = ownedDirection(ownerPrefix, "右边")
    val leftForward = ownedDirection(ownerPrefix, "左前方")
    val rightForward = ownedDirection(ownerPrefix, "右前方")
    val leftBackward = ownedDirection(ownerPrefix, "左后方")
    val rightBackward = ownedDirection(ownerPrefix, "右后方")
    val characterSideWord = when (direction) {
        "attack_user_right_wing" -> when (kind) {
            PieceKind.Horse -> "跳到$rightForward"
            PieceKind.Elephant -> "飞到$rightForward"
            PieceKind.Rook -> "走到$rightForward"
            PieceKind.Cannon -> "挪到$rightForward"
            PieceKind.Soldier -> "走到$rightForward"
            else -> "下到$rightForward"
        }
        "attack_user_left_wing" -> when (kind) {
            PieceKind.Horse -> "跳到$leftForward"
            PieceKind.Elephant -> "飞到$leftForward"
            PieceKind.Rook -> "走到$leftForward"
            PieceKind.Cannon -> "挪到$leftForward"
            PieceKind.Soldier -> "走到$leftForward"
            else -> "下到$leftForward"
        }
        "user_right_wing" -> when (kind) {
            PieceKind.Horse -> "跳到$right"
            PieceKind.Elephant -> "飞到$right"
            PieceKind.Rook -> "走到$right"
            PieceKind.Cannon -> "挪到$right"
            PieceKind.Soldier -> "走到$right"
            else -> "下到$right"
        }
        "user_left_wing" -> when (kind) {
            PieceKind.Horse -> "跳到$left"
            PieceKind.Elephant -> "飞到$left"
            PieceKind.Rook -> "走到$left"
            PieceKind.Cannon -> "挪到$left"
            PieceKind.Soldier -> "走到$left"
            else -> "下到$left"
        }
        "attack" -> when (kind) {
            PieceKind.Horse -> "往前跳"
            PieceKind.Elephant -> "往前飞"
            PieceKind.Rook -> "往前走"
            PieceKind.Cannon -> "往前挪"
            PieceKind.Soldier -> "往前走"
            else -> "往前走"
        }
        "retreat" -> when (kind) {
            PieceKind.Horse -> "往后跳撤退"
            PieceKind.Elephant -> "往后飞回去"
            PieceKind.Rook -> "往后撤退"
            PieceKind.Cannon -> "往后撤退"
            PieceKind.Soldier -> "往后退"
            else -> "往后撤退"
        }
        "side_left", "side_right", "sideways" -> "横着挪一下"
        else -> ""
    }
    if (characterSideWord.isNotBlank()) return characterSideWord

    return when (kind) {
        PieceKind.Horse -> when (direction) {
            "forward" -> "跳到前面"
            "backward" -> "跳回来"
            "left" -> "跳到$left"
            "right" -> "跳到$right"
            "left_forward" -> "跳到$leftForward"
            "right_forward" -> "跳到$rightForward"
            "left_backward" -> "跳到$leftBackward"
            "right_backward" -> "跳到$rightBackward"
            else -> "跳到旁边"
        }
        PieceKind.Elephant -> when (direction) {
            "backward" -> "回到后面"
            "left" -> "飞到$left"
            "right" -> "飞到$right"
            "left_forward" -> "飞到$leftForward"
            "right_forward" -> "飞到$rightForward"
            "left_backward" -> "飞到$leftBackward"
            "right_backward" -> "飞到$rightBackward"
            else -> "飞过去"
        }
        PieceKind.Rook -> when (direction) {
            "forward" -> "往前走"
            "backward" -> "退回来"
            "left" -> "往${left}走"
            "right" -> "往${right}走"
            else -> "横着走"
        }
        PieceKind.Cannon -> when (direction) {
            "forward" -> "往前挪"
            "backward" -> "退回来"
            "left" -> "往${left}挪"
            "right" -> "往${right}挪"
            else -> "挪到旁边"
        }
        PieceKind.Soldier -> when (direction) {
            "forward" -> "往前走"
            "backward" -> "退回来"
            "left" -> "往${left}走"
            "right" -> "往${right}走"
            else -> "横走"
        }
        PieceKind.General, PieceKind.Advisor -> when (direction) {
            "forward" -> "往前走"
            "backward" -> "退回来"
            "left" -> "往${left}挪"
            "right" -> "往${right}挪"
            else -> "挪到旁边"
        }
        null -> "移动"
    }
}

private fun ownedDirection(ownerPrefix: String, directionText: String): String {
    val owner = ownerPrefix.takeIf { it == "我的" || it == "你的" }.orEmpty()
    return if (owner.isBlank()) directionText else "$owner$directionText"
}

internal data class MoveFacts(
    val sideValue: String,
    val sideLabel: String,
    val pieceText: String,
    val notation: String,
    val direction: String,
    val riverEvent: String,
    val moveSummary: String,
    val replyHint: String
)
