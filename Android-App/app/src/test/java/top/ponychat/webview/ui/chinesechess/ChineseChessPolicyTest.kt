package top.ponychat.webview.ui.chinesechess

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import top.ponychat.webview.data.model.XiangqiExecuteMove
import top.ponychat.webview.data.model.XiangqiMoveCandidate
import top.ponychat.webview.data.model.XiangqiPoint

class ChineseChessPolicyTest {
    @Test
    fun playfulNoviceStartsFromOpeningNovelty() {
        val order = xiangqiCandidateTagOrderForTest(
            powerTier = "novice",
            playStyle = "playful"
        )

        assertEquals(listOf("novelty", "random_safe", "random"), order.take(3))
    }

    @Test
    fun playfulOpeningNoveltyIncludesGeneralAndSoldierMoves() {
        val redMoves = playfulOpeningNoveltyMovesForTest("red")
        val blackMoves = playfulOpeningNoveltyMovesForTest("black")

        assertTrue(redMoves.contains("e0e1"))
        assertTrue(blackMoves.contains("e9e8"))
        assertTrue(redMoves.any { it in setOf("a3a4", "c3c4", "e3e4", "g3g4", "i3i4") })
        assertTrue(blackMoves.any { it in setOf("a6a5", "c6c5", "e6e5", "g6g5", "i6i5") })
        assertTrue(playfulOpeningCandidateTagsForTest("pinkie-opening").contains("novelty"))
    }

    @Test
    fun textbookAdvancedPrefersBookThenBest() {
        val order = xiangqiCandidateTagOrderForTest(
            powerTier = "advanced",
            playStyle = "textbook"
        )

        assertEquals(listOf("book", "best", "solid"), order.take(3))
    }

    @Test
    fun advancedStylesProduceDifferentPriorities() {
        val attacking = xiangqiCandidateTagOrderForTest(
            powerTier = "advanced",
            playStyle = "attacking"
        )
        val cautious = xiangqiCandidateTagOrderForTest(
            powerTier = "advanced",
            playStyle = "cautious"
        )

        assertEquals("active", attacking.first())
        assertEquals("solid", cautious.first())
        assertNotEquals(attacking.take(3), cautious.take(3))
    }

    @Test
    fun legacyConfiguredTagsAreMergedBehindStyleLead() {
        val order = xiangqiCandidateTagOrderForTest(
            powerTier = "junior",
            playStyle = "attacking",
            configuredTags = listOf("good", "best", "random")
        )

        assertEquals(listOf("active", "risky", "good", "best", "random"), order.take(5))
    }

    @Test
    fun userRequestedMoveDoesNotOverrideCharacterPolicyOrder() {
        assertEquals(
            listOf("solid", "good", "user_requested", "blunder"),
            xiangqiOrderedCandidateTagsForTest(
                powerTier = "junior",
                playStyle = "cautious",
                candidateTags = listOf("user_requested", "blunder", "solid", "good")
            )
        )
    }

    @Test
    fun highUserRequestAffinityPrefersUserRequestsSooner() {
        assertEquals(
            listOf("solid", "user_requested", "good", "blunder"),
            xiangqiOrderedCandidateTagsForTest(
                powerTier = "junior",
                playStyle = "cautious",
                candidateTags = listOf("user_requested", "blunder", "solid", "good"),
                executionPolicy = mapOf("user_request_affinity" to 4)
            )
        )
    }

    @Test
    fun lowUserRequestAffinityKeepsOwnPlanFirst() {
        assertEquals(
            listOf("active", "risky", "good", "blunder", "user_requested"),
            xiangqiOrderedCandidateTagsForTest(
                powerTier = "junior",
                playStyle = "attacking",
                candidateTags = listOf("user_requested", "active", "risky", "good", "blunder"),
                executionPolicy = mapOf("user_request_affinity" to 1)
            )
        )
    }

    @Test
    fun explicitUserRequestAffinityOverridesPersonalityGuess() {
        assertEquals(
            listOf("user_requested", "active", "risky"),
            xiangqiOrderedCandidateTagsForTest(
                powerTier = "junior",
                playStyle = "attacking",
                candidateTags = listOf("active", "risky", "user_requested"),
                executionPolicy = mapOf("user_request_affinity" to 5)
            )
        )
    }

    @Test
    fun initialBoardConvertsToEleEyeFen() {
        assertEquals(
            "rheakaehr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RHEAKAEHR r - - 0 1",
            initialEleEyeFenForTest("red")
        )
        assertEquals(
            "rheakaehr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RHEAKAEHR b - - 0 1",
            initialEleEyeFenForTest("black")
        )
    }

    @Test
    fun eleEyeCoordinateRoundTripUsesLogicalBoard() {
        assertEquals("c3c4", eleEyeMoveRoundTripForTest("c3c4"))
        assertEquals("h9g7", eleEyeMoveRoundTripForTest("h9g7"))
    }

    @Test
    fun localComputeBudgetMatchesPowerTier() {
        assertEquals(500L, xiangqiComputeBudgetMillisForTest("novice"))
        assertEquals(1_000L, xiangqiComputeBudgetMillisForTest("junior"))
        assertEquals(2_000L, xiangqiComputeBudgetMillisForTest("intermediate"))
        assertEquals(3_000L, xiangqiComputeBudgetMillisForTest("advanced"))
    }

    @Test
    fun flavorLayerOnlyUsesShallowReplyLookahead() {
        assertEquals(0, xiangqiFlavorReplyLookaheadCountForTest("novice"))
        assertEquals(1, xiangqiFlavorReplyLookaheadCountForTest("junior"))
        assertEquals(1, xiangqiFlavorReplyLookaheadCountForTest("intermediate"))
        assertEquals(1, xiangqiFlavorReplyLookaheadCountForTest("advanced"))
    }

    @Test
    fun longOpponentMessageSplitsIntoStableTwoLinePanels() {
        val text = "你这一步有点厉害，我得先把这里看清楚，再换一个更稳的位置，免得我的棋子一下子被你抓住。"
        val panels = xiangqiMessagePanelSegments(text, maxUnits = 34)

        assertTrue(panels.size > 1)
        assertEquals(text, panels.joinToString(""))
        assertEquals(
            followupDelayMillis(text),
            panels.sumOf { followupDelayMillis(it) }
        )
    }

    @Test
    fun xiangqiFinalTextDoesNotAddExtraHoldTime() {
        assertEquals(0L, XIANGQI_FINAL_TEXT_HOLD_MS)
    }

    @Test
    fun defaultOpponentPanelSplitFitsTwoLineBubbleConservatively() {
        val text = "不过特丽克西可不会让你白吃！我用象飞过去，把你的炮也吃掉，一换一，不亏！"
        val panels = xiangqiMessagePanelSegments(text)

        assertTrue(panels.size > 1)
        assertEquals(text, panels.joinToString(""))
        assertTrue(panels.all { it.length <= 30 })
    }

    @Test
    fun eleEyeSearchTimeStaysInsideLocalBudget() {
        listOf("novice", "junior", "intermediate", "advanced").forEach { tier ->
            val budget = xiangqiComputeBudgetMillisForTest(tier)
            val searchMillis = xiangqiEleEyeSearchMillisForTest(tier, "textbook")

            assertTrue("EleEye search for $tier should be positive", searchMillis > 0L)
            assertTrue("EleEye search for $tier should leave overhead", searchMillis < budget)
        }
    }

    @Test
    fun forwardMoveFactsDoNotBakeInPressureWording() {
        assertEquals("往前走", moveWordFor(PieceKind.Rook, "attack"))
        assertEquals("往前挪", moveWordFor(PieceKind.Cannon, "attack"))
        assertEquals("往前跳", moveWordFor(PieceKind.Horse, "attack"))
    }

    @Test
    fun moveFactsUseCharacterSeatedPerspectiveForDirections() {
        val redHorseToOwnLeft = Move(Cell(1, 9), Cell(0, 7)).toMoveFacts(
            piece = Piece(Side.Red, PieceKind.Horse),
            sideFallback = Side.Red,
            playerSide = Side.Black,
            capturedPiece = null,
            isCheck = false
        )
        val blackHorseToOwnLeft = Move(Cell(7, 0), Cell(8, 2)).toMoveFacts(
            piece = Piece(Side.Black, PieceKind.Horse),
            sideFallback = Side.Black,
            playerSide = Side.Red,
            capturedPiece = null,
            isCheck = false
        )
        val userRookToRoleLeft = Move(Cell(4, 0), Cell(3, 0)).toMoveFacts(
            piece = Piece(Side.Black, PieceKind.Rook),
            sideFallback = Side.Black,
            playerSide = Side.Black,
            capturedPiece = null,
            isCheck = false
        )
        val redRookForward = Move(Cell(0, 9), Cell(0, 8)).toMoveFacts(
            piece = Piece(Side.Red, PieceKind.Rook),
            sideFallback = Side.Red,
            playerSide = Side.Black,
            capturedPiece = null,
            isCheck = false
        )

        assertEquals("left_forward", redHorseToOwnLeft.direction)
        assertEquals("马跳到我的左前方", redHorseToOwnLeft.replyHint)
        assertEquals("left_forward", blackHorseToOwnLeft.direction)
        assertEquals("马跳到我的左前方", blackHorseToOwnLeft.replyHint)
        assertEquals("车往你的左边走", userRookToRoleLeft.replyHint)
        assertEquals("车往前走", redRookForward.replyHint)
    }

    @Test
    fun thinkingStateKeepsActiveVoiceSegmentVisible() {
        assertEquals(
            "",
            xiangqiOpponentBubbleTextForTest(
                characterMoveThinking = true,
                characterSegmentActive = false,
                characterMessage = "上一句旧文本"
            )
        )
        assertEquals(
            "我先想一下这步。",
            xiangqiOpponentBubbleTextForTest(
                characterMoveThinking = true,
                characterSegmentActive = true,
                characterMessage = "我先想一下这步。"
            )
        )
        assertEquals(
            "走这里。",
            xiangqiOpponentBubbleTextForTest(
                characterMoveThinking = false,
                characterSegmentActive = false,
                characterMessage = "走这里。"
            )
        )
        assertEquals("执黑方", xiangqiOpponentSideTextForTest("black", isThinking = false))
        assertEquals("正在思考.", xiangqiOpponentSideTextForTest("black", isThinking = true, thinkingDotCount = 1))
        assertEquals("正在思考..", xiangqiOpponentSideTextForTest("black", isThinking = true, thinkingDotCount = 2))
        assertEquals("正在思考...", xiangqiOpponentSideTextForTest("black", isThinking = true, thinkingDotCount = 3))
    }

    @Test
    fun pieceRadiusIsScaledUpAndSamePieceTapDeselects() {
        assertEquals(0.418, xiangqiPieceRadiusScaleForTest(), 0.0001)
        assertTrue(xiangqiTapSamePieceDeselectsForTest())
    }

    @Test
    fun onlyMoveDirectivesCarryIntoNextCharacterTurn() {
        assertEquals(false, xiangqiShouldCarryUserInstructionForTest("你哪个棋子在看我的士"))
        assertEquals(false, xiangqiShouldCarryUserInstructionForTest("我的马有车保护着呢"))
        assertEquals(false, xiangqiShouldCarryUserInstructionForTest("你现在先走一步，把炮放到中间"))
        assertEquals(true, xiangqiShouldCarryUserInstructionForTest("等一下你把炮放到中间，做一个当头炮"))
        assertEquals(true, xiangqiShouldCarryUserInstructionForTest("用你的马吃我的兵"))
        assertEquals(true, xiangqiShouldCarryUserInstructionForTest("把你的车收回去"))
    }

    @Test
    fun userDirectiveCanResolveLegalRoleMove() {
        assertEquals(
            "b7e7",
            userRequestedMoveForTest("帮我走炮二平五", "black", "initial")
        )
        assertEquals(
            "c7d5",
            userRequestedMoveForTest("用你的马吃我的兵", "black", "horse_capture_soldier")
        )
        assertEquals(
            "c7d5",
            userRequestedMoveForTest("帮我用你的马吃我的兵", "black", "horse_capture_soldier")
        )
        assertEquals(
            "d7e7",
            userRequestedMoveForTest("用你的炮将我", "black", "cannon_check")
        )
        val retreatMove = userRequestedMoveForTest("把你的车收回去", "black", "rook_retreat")
        assertTrue(retreatMove?.startsWith("e4e") == true)
        assertEquals(
            null,
            userRequestedMoveForTest("我用马吃你的兵", "black", "horse_capture_soldier")
        )
    }

    @Test
    fun naturalUserDirectivesResolveToRequestedBoardTargets() {
        val centerCannonDirectives = listOf(
            "等一下你把炮放到中间，做一个当头炮",
            "等下你做个当中炮",
            "轮到你把炮放到中路",
            "你下一手把炮放到中间",
            "把你的炮放到中心"
        )
        centerCannonDirectives.forEach { directive ->
            assertEquals(
                directive,
                "b7e7",
                userRequestedMoveForTest(directive, "black", "initial")
            )
        }

        assertEquals(
            "c7d5",
            userRequestedMoveForTest("下一手用你的马吃我的兵", "black", "horse_capture_soldier")
        )
        assertEquals(
            "d7e7",
            userRequestedMoveForTest("轮到你用炮将我一下", "black", "cannon_check")
        )
        assertNotNull(userRequestedMoveForTest("下一次你走兵", "black", "initial"))
        assertTrue(xiangqiShouldCarryUserInstructionForTest("下一次你走兵"))
        assertNotNull(userRequestedMoveForTest("你悔棋一下，然后走兵", "black", "initial"))
        assertTrue(xiangqiShouldCarryUserInstructionForTest("你悔棋一下，然后走兵"))
        assertEquals(
            PieceKind.Soldier,
            userRequestedPieceKindForTest("你悔棋一下，然后走兵", "black", "initial")
        )
        val retreatMove = userRequestedMoveForTest("等一下把你的车收回去", "black", "rook_retreat")
        assertTrue(retreatMove?.startsWith("e4e") == true)
        assertEquals(
            null,
            userRequestedMoveForTest("等一下我把炮放到中间", "black", "initial")
        )
    }

    @Test
    fun undoDecisionAndPersuasionAreRecognized() {
        assertEquals("Approve", xiangqiUndoDecisionForTest("approve_undo"))
        assertEquals("Reject", xiangqiUndoDecisionForTest("reject_undo"))
        assertEquals("Request", xiangqiUndoDecisionForTest("request_undo"))
        assertEquals(null, xiangqiUndoDecisionForTest("move"))
        assertTrue(xiangqiIsResignAction("resign"))
        assertTrue(xiangqiIsResignAction("SURRENDER"))
        assertTrue(!xiangqiIsResignAction("chat_only"))
        assertTrue(xiangqiLooksLikeUserSurrender("我认输投降"))
        assertTrue(xiangqiLooksLikeUserSurrender("你赢了，我认输"))
        assertTrue(!xiangqiLooksLikeUserSurrender("你认输投降吧"))
        assertEquals(
            "刚才手滑点错了，让我重走一下",
            xiangqiLatestUndoPersuasionForTest(
                listOf(
                    "你下一手用炮",
                    "刚才手滑点错了，让我重走一下",
                    "普通聊天"
                )
            )
        )
        assertEquals(
            "刚才点错了，让我撤回这步",
            xiangqiLatestUndoPersuasionForTest(
                listOf(
                    "刚才点错了，让我撤回这步",
                    "同意悔棋",
                    "拒绝悔棋"
                )
            )
        )
    }

    @Test
    fun repeatedUserUndoSameMoveIsCountedByPieceAndRoute() {
        val current = mapOf<String, Any?>(
            "actor" to "user",
            "piece_kind" to "soldier",
            "from" to mapOf("x" to 0, "y" to 6),
            "to" to mapOf("x" to 0, "y" to 5)
        )
        val sameMove = mapOf<String, Any?>(
            "actor" to "user",
            "piece" to "兵",
            "from" to mapOf("x" to 0, "y" to 6),
            "to" to mapOf("x" to 0, "y" to 5)
        )
        val sameRouteDifferentPiece = mapOf<String, Any?>(
            "actor" to "user",
            "piece_kind" to "rook",
            "from" to mapOf("x" to 0, "y" to 6),
            "to" to mapOf("x" to 0, "y" to 5)
        )
        val differentMove = mapOf<String, Any?>(
            "actor" to "user",
            "piece_kind" to "soldier",
            "from" to mapOf("x" to 2, "y" to 6),
            "to" to mapOf("x" to 2, "y" to 5)
        )

        assertEquals(
            1,
            xiangqiSameHistoryMoveRepeatCount(
                currentMove = current,
                recentMoves = listOf(sameMove, sameRouteDifferentPiece, differentMove)
            )
        )
    }

    @Test
    fun userSurrenderContextDescribesTimingAndPressure() {
        val early = xiangqiUserSurrenderContext(
            game = GameState(),
            playerSide = Side.Red,
            moveHistory = emptyList(),
            userText = "认输投降"
        )
        assertEquals("before_first_move", early["phase"])
        assertEquals("very_early", early["pressure_hint"])
        assertEquals(0, early["move_count"])

        val checkedBoard = sparseBoardForTest(
            Cell(4, 0) to Piece(Side.Black, PieceKind.General),
            Cell(4, 9) to Piece(Side.Red, PieceKind.General),
            Cell(4, 5) to Piece(Side.Black, PieceKind.Rook)
        )
        val checked = xiangqiUserSurrenderContext(
            game = GameState(board = checkedBoard, turn = Side.Red),
            playerSide = Side.Red,
            moveHistory = listOf(
                mapOf(
                    "actor" to "character",
                    "is_capture" to true,
                    "piece" to "车",
                    "captured_piece" to "炮",
                    "move_summary" to "黑方车往前走，形成将军"
                )
            ),
            userText = "我认输"
        )
        assertEquals("player_in_check", checked["pressure_hint"])
        assertEquals(true, checked["player_in_check_before_resign"])
        assertEquals("character", checked["last_actor"])
        assertEquals("炮", checked["last_captured_piece"])
    }

    @Test
    fun generalFlyingLineDoesNotProtectOwnSoldier() {
        val reason = generalFlyingLineTacticalReasonForTest()

        assertTrue(!reason.contains("护住"))
        assertTrue(!reason.contains("小兵"))
    }

    @Test
    fun openingCannonHorseLineIsNotTreatedAsDodgeReason() {
        val (reason, caution) = openingCannonHorseThreatTextForTest()

        assertTrue(!reason.contains("躲"))
        assertTrue(!reason.contains("避开"))
        assertTrue(!reason.contains("炮"))
        assertTrue(caution.contains("开局常见的弱威胁"))
        assertTrue(caution.contains("不要把这步说成躲开你的炮"))
    }

    @Test
    fun centralElephantGuardPrioritizesGeneralOverSoldier() {
        val (reason, caution) = centralElephantGuardTextForTest()

        assertTrue(reason.contains("帅"))
        assertTrue(reason.contains("中路"))
        assertTrue(!reason.contains("小兵"))
        assertTrue(caution.contains("不要说成主要为了保护"))
        assertTrue(caution.contains("小兵"))
    }

    @Test
    fun incidentalAdvisorProtectionIsNotUsedAsMovePurpose() {
        val (reason, caution) = rookAdvanceIncidentalAdvisorProtectionTextForTest()

        assertTrue(!reason.contains("护住"))
        assertTrue(!reason.contains("保护"))
        assertTrue(!reason.contains("仕"))
        assertTrue(caution.contains("顺带照到"))
        assertTrue(caution.contains("不要说成主要为了保护"))
        assertTrue(caution.contains("仕"))
    }

    @Test
    fun crossGameMemoryKeepsCaptureLedgerForLastGame() {
        val record = xiangqiBuildGameMemoryRecord(
            gameId = "game-1",
            game = GameState(winner = Side.Red),
            playerSide = Side.Red,
            moveHistory = listOf(
                mapOf(
                    "actor" to "user",
                    "side" to "red",
                    "piece" to "兵",
                    "piece_kind" to "soldier",
                    "is_capture" to true,
                    "captured_piece" to "卒",
                    "captured_piece_kind" to "soldier",
                    "move_summary" to "红方兵往前走，吃掉卒"
                ),
                mapOf(
                    "actor" to "character",
                    "side" to "black",
                    "piece" to "炮",
                    "piece_kind" to "cannon",
                    "is_capture" to true,
                    "captured_piece" to "马",
                    "captured_piece_kind" to "horse",
                    "move_summary" to "黑方炮平过去，吃掉马"
                )
            ),
            dialogueHistory = listOf(
                mapOf("role" to "user", "text" to "上一局我吃了你一个卒")
            ),
            completedReason = "next_game_after_result"
        )
        val memory = xiangqiBuildCrossGameMemory(listOf(record))
        val latest = memory["latest_game"] as Map<*, *>
        val stats = latest["capture_stats"] as Map<*, *>
        val userCaptured = stats["user_captured_character"] as Map<*, *>
        val byKind = userCaptured["by_kind"] as Map<*, *>

        assertEquals(true, memory["has_previous_game"])
        assertEquals("lost", latest["character_result"])
        assertEquals(1, byKind["soldier"])
        assertTrue((latest["summary"] as String).contains("用户吃了角色1个卒"))
    }

    @Test
    fun recentUserChallengeTextsCollectsPostgameRecallHooks() {
        val challenges = xiangqiRecentUserChallengeTexts(
            listOf(
                mapOf("role" to "user", "text" to "我先走炮"),
                mapOf("role" to "character", "text" to "好呀。"),
                mapOf("role" to "user", "text" to "你投降吧，我觉得你输定了"),
                mapOf("role" to "user", "text" to "那你准备把屁股翘高吧，你要输了"),
                mapOf("role" to "user", "text" to "这步走这里")
            )
        )

        assertEquals(
            listOf(
                "你投降吧，我觉得你输定了",
                "那你准备把屁股翘高吧，你要输了"
            ),
            challenges
        )
    }

    @Test
    fun gameMemoryRecordKeepsFullDialogueSalientInteractions() {
        val record = xiangqiBuildGameMemoryRecord(
            gameId = "game-wager",
            game = GameState(winner = Side.Red),
            playerSide = Side.Red,
            moveHistory = emptyList(),
            dialogueHistory = listOf(
                mapOf("role" to "user", "text" to "普通走棋"),
                mapOf("role" to "user", "text" to "谁输了就要答应赢家一个很具体的要求"),
                mapOf("role" to "character", "text" to "好呀好呀，我记住这个赌注啦。"),
                mapOf("role" to "user", "text" to "刚才那句赌注你可别忘了")
            ),
            completedReason = "game_over"
        )
        val salient = record["salient_interactions"] as List<*>
        val challenges = record["recent_user_challenges"] as List<*>

        assertTrue(salient.any { (it as Map<*, *>)["text"] == "谁输了就要答应赢家一个很具体的要求" })
        assertTrue(salient.any { (it as Map<*, *>)["text"] == "好呀好呀，我记住这个赌注啦。" })
        assertTrue(challenges.contains("谁输了就要答应赢家一个很具体的要求"))
        assertTrue(challenges.contains("刚才那句赌注你可别忘了"))
    }

    @Test
    fun gameMemoryRecordKeepsEarlyCasualChatBeyondRecentWindow() {
        val filler = (1..36).flatMap { index ->
            listOf(
                mapOf("role" to "character", "text" to "第${index}轮普通棋评"),
                mapOf("role" to "character", "text" to "第${index}轮补充说明")
            )
        }
        val dialogueHistory = listOf(
            mapOf("role" to "user", "text" to "这局的口令是星星饼干，结束后你要记得。"),
            mapOf("role" to "character", "text" to "记住了，星星饼干，我会把它写进这局的小笔记里。")
        ) + filler + listOf(
            mapOf("role" to "user", "text" to "刚才那个口令还在吗？")
        )

        val record = xiangqiBuildGameMemoryRecord(
            gameId = "game-casual",
            game = GameState(winner = Side.Red),
            playerSide = Side.Red,
            moveHistory = emptyList(),
            dialogueHistory = dialogueHistory,
            completedReason = "game_over"
        )
        val salient = record["salient_interactions"] as List<*>
        val userMessages = record["recent_user_messages"] as List<*>
        val dialogue = record["dialogue"] as List<*>

        assertTrue(salient.any { (it as Map<*, *>)["text"] == "这局的口令是星星饼干，结束后你要记得。" })
        assertTrue(salient.any { (it as Map<*, *>)["text"] == "记住了，星星饼干，我会把它写进这局的小笔记里。" })
        assertTrue(userMessages.contains("这局的口令是星星饼干，结束后你要记得。"))
        assertTrue(dialogue.any { (it as Map<*, *>)["text"] == "这局的口令是星星饼干，结束后你要记得。" })
    }

    @Test
    fun postgameReviewContextExposesSalientCasualChat() {
        val context = xiangqiBuildPostgameReviewContext(
            gameId = "game-postgame",
            snapshot = GameState(winner = Side.Red),
            playerSide = Side.Red,
            moveHistory = emptyList(),
            dialogueHistory = listOf(
                mapOf("role" to "user", "text" to "输的人给赢家写一句胜利留言。"),
                mapOf("role" to "character", "text" to "好，我记下来了，胜利留言要写得认真一点。"),
                mapOf("role" to "user", "text" to "现在还记得留言这件事吗？")
            ),
            userMessage = "现在还记得留言这件事吗？"
        )
        val review = context["postgame_review"] as Map<*, *>
        val salient = review["salient_interactions"] as List<*>
        val userMessages = review["recent_user_messages"] as List<*>

        assertEquals("lost", review["character_result"])
        assertTrue(salient.any { (it as Map<*, *>)["text"] == "输的人给赢家写一句胜利留言。" })
        assertTrue(salient.any { (it as Map<*, *>)["text"] == "好，我记下来了，胜利留言要写得认真一点。" })
        assertTrue(userMessages.contains("现在还记得留言这件事吗？"))
    }

    @Test
    fun gameMemoryRecordKeepsCasualChatAndUpgradedWager() {
        val dialogueHistory = listOf(
            mapOf("role" to "user", "text" to "内容A：这局的口令是星星饼干，结束后你要记得。"),
            mapOf("role" to "character", "text" to "记住了，星星饼干，我会把它写进这局的小笔记里。"),
            mapOf("role" to "user", "text" to "赌注B：输的人给赢家写一句胜利留言。"),
            mapOf("role" to "character", "text" to "好，胜利留言这件事我也记下了。"),
            mapOf("role" to "character", "text" to "这几步我先认真算，不然笔记会很难看。"),
            mapOf("role" to "user", "text" to "你还记得星星饼干吗？"),
            mapOf("role" to "character", "text" to "当然记得，星星饼干是这局的口令。"),
            mapOf("role" to "user", "text" to "赌注升级为C：输的人写三句胜利留言，并叫赢家一次棋盘老师。"),
            mapOf("role" to "character", "text" to "收到，赌注从一句留言升级成三句留言加一次棋盘老师。")
        )
        val userWonRecord = xiangqiBuildGameMemoryRecord(
            gameId = "game-abc-user-won",
            game = GameState(winner = Side.Red),
            playerSide = Side.Red,
            moveHistory = emptyList(),
            dialogueHistory = dialogueHistory,
            completedReason = "game_over"
        )
        val characterWonRecord = xiangqiBuildGameMemoryRecord(
            gameId = "game-abc-character-won",
            game = GameState(winner = Side.Black),
            playerSide = Side.Red,
            moveHistory = emptyList(),
            dialogueHistory = dialogueHistory,
            completedReason = "game_over"
        )
        val salient = userWonRecord["salient_interactions"] as List<*>
        val userMessages = userWonRecord["recent_user_messages"] as List<*>

        assertEquals("lost", userWonRecord["character_result"])
        assertEquals("won", characterWonRecord["character_result"])
        assertTrue(salient.any { (it as Map<*, *>)["text"] == "内容A：这局的口令是星星饼干，结束后你要记得。" })
        assertTrue(salient.any { (it as Map<*, *>)["text"] == "赌注B：输的人给赢家写一句胜利留言。" })
        assertTrue(salient.any { (it as Map<*, *>)["text"] == "赌注升级为C：输的人写三句胜利留言，并叫赢家一次棋盘老师。" })
        assertTrue(salient.any { (it as Map<*, *>)["text"] == "收到，赌注从一句留言升级成三句留言加一次棋盘老师。" })
        assertTrue(userMessages.contains("你还记得星星饼干吗？"))
        assertTrue(userMessages.contains("赌注升级为C：输的人写三句胜利留言，并叫赢家一次棋盘老师。"))
    }

    @Test
    fun postgameReviewContextKeepsUpgradedWagerForWinnerBranch() {
        val context = xiangqiBuildPostgameReviewContext(
            gameId = "game-abc-character-won",
            snapshot = GameState(winner = Side.Black),
            playerSide = Side.Red,
            moveHistory = emptyList(),
            dialogueHistory = listOf(
                mapOf("role" to "user", "text" to "内容A：这局的口令是星星饼干，结束后你要记得。"),
                mapOf("role" to "character", "text" to "记住了，星星饼干，我会把它写进这局的小笔记里。"),
                mapOf("role" to "user", "text" to "赌注B：输的人给赢家写一句胜利留言。"),
                mapOf("role" to "character", "text" to "好，胜利留言这件事我也记下了。"),
                mapOf("role" to "user", "text" to "赌注升级为C：输的人写三句胜利留言，并叫赢家一次棋盘老师。"),
                mapOf("role" to "character", "text" to "收到，赌注从一句留言升级成三句留言加一次棋盘老师。")
            ),
            userMessage = "你赢了，现在赌注是什么？"
        )
        val review = context["postgame_review"] as Map<*, *>
        val salient = review["salient_interactions"] as List<*>

        assertEquals("won", review["character_result"])
        assertTrue(salient.any { (it as Map<*, *>)["text"] == "赌注B：输的人给赢家写一句胜利留言。" })
        assertTrue(salient.any { (it as Map<*, *>)["text"] == "赌注升级为C：输的人写三句胜利留言，并叫赢家一次棋盘老师。" })
        assertTrue(salient.any { (it as Map<*, *>)["text"] == "收到，赌注从一句留言升级成三句留言加一次棋盘老师。" })
    }

    @Test
    fun gameMemoryRecordKeepsCharacterOwnedOneSoldierBoast() {
        val record = xiangqiBuildGameMemoryRecord(
            gameId = "game-one-soldier",
            game = GameState(winner = Side.Red),
            playerSide = Side.Red,
            moveHistory = emptyList(),
            dialogueHistory = listOf(
                mapOf("role" to "user", "text" to "你打算就用这一个兵赢我吗"),
                mapOf("role" to "character", "text" to "是啊，试试才知道"),
                mapOf("role" to "character", "text" to "呜呜，还是输了")
            ),
            completedReason = "game_over"
        )
        val salient = record["salient_interactions"] as List<*>
        val challenges = record["recent_user_challenges"] as List<*>

        assertTrue(salient.any {
            val entry = it as Map<*, *>
            entry["role"] == "user" && entry["text"] == "你打算就用这一个兵赢我吗"
        })
        assertTrue(salient.any {
            val entry = it as Map<*, *>
            entry["role"] == "character" && entry["text"] == "是啊，试试才知道"
        })
        assertTrue(challenges.contains("你打算就用这一个兵赢我吗"))
    }

    @Test
    fun gameMemoryRecordKeepsFullExamSeedForPostgameAndNormalRecall() {
        val quietMoves: List<Map<String, Any?>> = (1..20).map { index ->
            mapOf(
                "actor" to if (index % 2 == 0) "character" else "user",
                "side" to if (index % 2 == 0) "black" else "red",
                "piece" to if (index % 2 == 0) "卒" else "兵",
                "piece_kind" to "soldier",
                "move_summary" to "第${index}手普通走子"
            )
        }
        val moveHistory = quietMoves + listOf(
            mapOf(
                "actor" to "user",
                "side" to "red",
                "piece" to "兵",
                "piece_kind" to "soldier",
                "is_capture" to true,
                "captured_piece" to "卒",
                "captured_piece_kind" to "soldier",
                "move_summary" to "第21手红方兵吃掉黑方卒"
            ),
            mapOf(
                "actor" to "user",
                "side" to "red",
                "piece" to "马",
                "piece_kind" to "horse",
                "is_capture" to true,
                "captured_piece" to "卒",
                "captured_piece_kind" to "soldier",
                "move_summary" to "第22手红方马吃掉黑方卒"
            ),
            mapOf(
                "actor" to "character",
                "side" to "black",
                "piece" to "炮",
                "piece_kind" to "cannon",
                "is_capture" to true,
                "captured_piece" to "马",
                "captured_piece_kind" to "horse",
                "move_summary" to "第23手黑方炮吃掉红方马"
            ),
            mapOf(
                "actor" to "user",
                "side" to "red",
                "piece" to "炮",
                "piece_kind" to "cannon",
                "is_capture" to true,
                "is_check" to true,
                "captured_piece" to "炮",
                "captured_piece_kind" to "cannon",
                "move_summary" to "第24手红方炮平中路，吃掉黑方炮并形成杀棋"
            )
        )
        val dialogueHistory = listOf(
            mapOf("role" to "user", "text" to "这局谁输了，就给赢家写一张胜利留言，这个就是赌注。"),
            mapOf("role" to "character", "text" to "好呀，我记住啦，输了就给赢家写胜利留言。"),
            mapOf("role" to "user", "text" to "你投降吧，我觉得你输定了。"),
            mapOf("role" to "character", "text" to "我才不投降呢，这局我还要反击。"),
            mapOf("role" to "user", "text" to "刚才那个赌注你可别忘了。"),
            mapOf("role" to "character", "text" to "记着呢，愿赌服输我也会认的。"),
            mapOf("role" to "character", "text" to "哎呀，我看漏了中路，愿赌服输。")
        )

        val record = xiangqiBuildGameMemoryRecord(
            gameId = "exam-game-1",
            game = GameState(winner = Side.Red),
            playerSide = Side.Red,
            moveHistory = moveHistory,
            dialogueHistory = dialogueHistory,
            completedReason = "game_over"
        )
        val stats = record["capture_stats"] as Map<*, *>
        val userCaptured = stats["user_captured_character"] as Map<*, *>
        val userByText = userCaptured["by_text"] as Map<*, *>
        val userByKind = userCaptured["by_kind"] as Map<*, *>
        val characterCaptured = stats["character_captured_user"] as Map<*, *>
        val characterByKind = characterCaptured["by_kind"] as Map<*, *>
        val moments = record["key_moments"] as List<*>
        val moves = record["moves"] as List<*>
        val dialogue = record["dialogue"] as List<*>
        val salient = record["salient_interactions"] as List<*>
        val challenges = record["recent_user_challenges"] as List<*>

        assertEquals("exam-game-1", record["game_id"])
        assertEquals("red", record["player_side"])
        assertEquals("black", record["character_side"])
        assertEquals("red", record["winner"])
        assertEquals("lost", record["character_result"])
        assertEquals(24, record["move_count"])
        assertTrue((record["summary"] as String).contains("上一局用户执红方、角色执黑方，共24手，用户获胜"))
        assertEquals(3, userCaptured["total"])
        assertEquals(2, userByText["卒"])
        assertEquals(1, userByText["炮"])
        assertEquals(2, userByKind["soldier"])
        assertEquals(1, userByKind["cannon"])
        assertEquals(1, characterCaptured["total"])
        assertEquals(1, characterByKind["horse"])
        assertTrue(moments.any { (it as Map<*, *>)["move_summary"] == "第24手红方炮平中路，吃掉黑方炮并形成杀棋" })
        assertEquals(24, moves.size)
        assertEquals(dialogueHistory, dialogue)
        assertTrue(salient.any { (it as Map<*, *>)["text"] == "这局谁输了，就给赢家写一张胜利留言，这个就是赌注。" })
        assertTrue(salient.any { (it as Map<*, *>)["text"] == "好呀，我记住啦，输了就给赢家写胜利留言。" })
        assertTrue(salient.any { (it as Map<*, *>)["text"] == "你投降吧，我觉得你输定了。" })
        assertTrue(salient.any { (it as Map<*, *>)["text"] == "我才不投降呢，这局我还要反击。" })
        assertTrue(challenges.contains("这局谁输了，就给赢家写一张胜利留言，这个就是赌注。"))
        assertTrue(challenges.contains("你投降吧，我觉得你输定了。"))
        assertTrue(challenges.contains("刚才那个赌注你可别忘了。"))
    }

    @Test
    fun crossGameMemoryKeepsLatestAndPreviousGameOrder() {
        val firstRecord = xiangqiBuildGameMemoryRecord(
            gameId = "game-a",
            game = GameState(winner = Side.Red),
            playerSide = Side.Red,
            moveHistory = listOf(
                mapOf(
                    "actor" to "user",
                    "side" to "red",
                    "piece" to "兵",
                    "piece_kind" to "soldier",
                    "is_capture" to true,
                    "captured_piece" to "卒",
                    "captured_piece_kind" to "soldier",
                    "move_summary" to "第一局红方兵吃掉黑方卒"
                )
            ),
            dialogueHistory = listOf(
                mapOf("role" to "user", "text" to "这局谁输了，就给赢家写一张胜利留言，这个就是赌注。"),
                mapOf("role" to "character", "text" to "好呀，我记住啦，输了就给赢家写胜利留言。")
            ),
            completedReason = "game_over"
        )
        val secondRecord = xiangqiBuildGameMemoryRecord(
            gameId = "game-b",
            game = GameState(winner = Side.Red),
            playerSide = Side.Black,
            moveHistory = listOf(
                mapOf(
                    "actor" to "character",
                    "side" to "red",
                    "piece" to "车",
                    "piece_kind" to "rook",
                    "is_capture" to true,
                    "captured_piece" to "马",
                    "captured_piece_kind" to "horse",
                    "move_summary" to "第二局红方车吃掉黑方马"
                )
            ),
            dialogueHistory = listOf(
                mapOf("role" to "user", "text" to "下局你让我先手，记住了吗？"),
                mapOf("role" to "character", "text" to "记住啦，下局再说。")
            ),
            completedReason = "next_game_after_result"
        )

        val memory = xiangqiBuildCrossGameMemory(listOf(firstRecord, secondRecord))
        val latest = memory["latest_game"] as Map<*, *>
        val summaries = memory["recent_game_summaries"] as List<*>
        val recentGames = memory["recent_games"] as List<*>
        val firstRecent = recentGames[0] as Map<*, *>
        val secondRecent = recentGames[1] as Map<*, *>
        val firstStats = firstRecent["capture_stats"] as Map<*, *>
        val firstUserCaptured = firstStats["user_captured_character"] as Map<*, *>
        val firstUserByKind = firstUserCaptured["by_kind"] as Map<*, *>
        val secondStats = secondRecent["capture_stats"] as Map<*, *>
        val secondCharacterCaptured = secondStats["character_captured_user"] as Map<*, *>
        val secondCharacterByKind = secondCharacterCaptured["by_kind"] as Map<*, *>
        val firstSalient = firstRecent["salient_interactions"] as List<*>

        assertEquals(2, memory["completed_games_count"])
        assertEquals(true, memory["has_previous_game"])
        assertEquals("game-b", latest["game_id"])
        assertEquals("won", latest["character_result"])
        assertEquals(2, summaries.size)
        assertEquals("game-a", (summaries[0] as Map<*, *>)["game_id"])
        assertEquals("game-b", (summaries[1] as Map<*, *>)["game_id"])
        assertEquals("game-a", firstRecent["game_id"])
        assertEquals("game-b", secondRecent["game_id"])
        assertEquals(1, firstUserByKind["soldier"])
        assertEquals(1, secondCharacterByKind["horse"])
        assertTrue(firstSalient.any { (it as Map<*, *>)["text"] == "这局谁输了，就给赢家写一张胜利留言，这个就是赌注。" })
        assertTrue((firstRecent["summary"] as String).contains("用户获胜"))
        assertTrue((secondRecent["summary"] as String).contains("角色获胜"))
    }

    @Test
    fun apiStateCountsCrossedSoldiersBySide() {
        val board = sparseBoardForTest(
            Cell(4, 0) to Piece(Side.Black, PieceKind.General),
            Cell(4, 9) to Piece(Side.Red, PieceKind.General),
            Cell(0, 3) to Piece(Side.Black, PieceKind.Soldier),
            Cell(8, 5) to Piece(Side.Black, PieceKind.Soldier),
            Cell(2, 4) to Piece(Side.Red, PieceKind.Soldier),
            Cell(6, 6) to Piece(Side.Red, PieceKind.Soldier)
        )

        val crossed = board.toApiState(
            turn = Side.Red,
            playerSide = Side.Red,
            winner = null
        )["crossed_soldiers"] as Map<*, *>

        assertEquals(1, crossed["black_count"])
        assertEquals(1, crossed["red_count"])
        assertEquals(1, crossed["player_count"])
        assertEquals(1, crossed["character_count"])
    }

    @Test
    fun characterUndoRequestUiIsParsed() {
        assertEquals(
            1,
            xiangqiCharacterUndoStepsForTest(
                mapOf<String, Any?>(
                    "undo_request" to mapOf(
                        "requester" to "character",
                        "steps" to 1,
                        "reason" to "刚才那步我想收回来"
                    )
                )
            )
        )
        assertEquals(
            null,
            xiangqiCharacterUndoStepsForTest(
                mapOf<String, Any?>(
                    "undo_request" to mapOf(
                        "requester" to "user",
                        "steps" to 1
                    )
                )
            )
        )
    }

    @Test
    fun recentlyUndoneCharacterMoveIsExcludedFromRetryCandidates() {
        val undone = mapOf<String, Any?>(
            "actor" to "character",
            "piece_kind" to "horse",
            "from" to mapOf("x" to 7, "y" to 0),
            "to" to mapOf("x" to 8, "y" to 2)
        )
        val repeated = XiangqiMoveCandidate(
            id = "horse_repeat",
            qualityTag = "best",
            move = XiangqiExecuteMove(
                from = XiangqiPoint(7, 0),
                to = XiangqiPoint(8, 2),
                piece = "马"
            )
        )
        val sameKindAlternative = XiangqiMoveCandidate(
            id = "horse_other_side",
            qualityTag = "book",
            move = XiangqiExecuteMove(
                from = XiangqiPoint(1, 0),
                to = XiangqiPoint(2, 2),
                piece = "马"
            )
        )
        val alternative = XiangqiMoveCandidate(
            id = "rook_alternative",
            qualityTag = "good",
            move = XiangqiExecuteMove(
                from = XiangqiPoint(0, 0),
                to = XiangqiPoint(0, 1),
                piece = "车"
            )
        )

        val filtered = listOf(repeated, sameKindAlternative, alternative)
            .withoutRecentlyUndoneMoves(listOf(undone))

        assertEquals(listOf("rook_alternative"), filtered.map { it.id })
    }

    @Test
    fun recentlyUndonePieceKindFallsBackWhenNoOtherKindExists() {
        val undone = mapOf<String, Any?>(
            "actor" to "character",
            "piece" to "马",
            "from" to mapOf("x" to 7, "y" to 0),
            "to" to mapOf("x" to 8, "y" to 2)
        )
        val sameKindAlternative = XiangqiMoveCandidate(
            id = "horse_other_side",
            qualityTag = "book",
            move = XiangqiExecuteMove(
                from = XiangqiPoint(1, 0),
                to = XiangqiPoint(2, 2),
                piece = "马"
            )
        )

        val filtered = listOf(sameKindAlternative).withoutRecentlyUndoneMoves(listOf(undone))

        assertEquals(listOf("horse_other_side"), filtered.map { it.id })
    }

    @Test
    fun characterFeelsPressureAfterLosingHighValuePiece() {
        val board = sparseBoardForTest(
            Cell(4, 0) to Piece(Side.Black, PieceKind.General),
            Cell(4, 9) to Piece(Side.Red, PieceKind.General),
            Cell(1, 0) to Piece(Side.Black, PieceKind.Horse),
            Cell(7, 2) to Piece(Side.Black, PieceKind.Cannon)
        )
        val context = xiangqiCharacterMaterialPressureContext(
            board = board,
            playerSide = Side.Red,
            moveHistory = listOf(
                mapOf(
                    "actor" to "user",
                    "is_capture" to true,
                    "captured_piece" to "车",
                    "captured_piece_kind" to "rook",
                    "move_summary" to "红方炮吃掉黑方车"
                )
            )
        )

        assertEquals(true, context["active"])
        assertEquals("high", context["severity"])
        assertEquals(2, context["remaining_high_value_count"])
        assertEquals("recent_high_value_loss_and_low_remaining_material", context["reason"])
    }

    @Test
    fun playfulCharacterStillReceivesMaterialPressureSignal() {
        val board = sparseBoardForTest(
            Cell(4, 0) to Piece(Side.Black, PieceKind.General),
            Cell(4, 9) to Piece(Side.Red, PieceKind.General),
            Cell(1, 0) to Piece(Side.Black, PieceKind.Horse)
        )
        val context = xiangqiCharacterMaterialPressureContext(
            board = board,
            playerSide = Side.Red,
            moveHistory = listOf(
                mapOf(
                    "actor" to "user",
                    "is_capture" to true,
                    "captured_piece" to "车",
                    "captured_piece_kind" to "rook"
                )
            )
        )

        assertEquals(true, context["active"])
        assertEquals("high", context["severity"])
        assertEquals("recent_high_value_loss_and_low_remaining_material", context["reason"])
    }

    @Test
    fun characterFeelsMomentumAfterCapturingUserHighValuePiece() {
        val board = sparseBoardForTest(
            Cell(4, 0) to Piece(Side.Black, PieceKind.General),
            Cell(4, 9) to Piece(Side.Red, PieceKind.General),
            Cell(1, 9) to Piece(Side.Red, PieceKind.Horse),
            Cell(7, 2) to Piece(Side.Black, PieceKind.Cannon)
        )
        val context = xiangqiCharacterMaterialMomentumContext(
            board = board,
            playerSide = Side.Red,
            moveHistory = listOf(
                mapOf(
                    "actor" to "character",
                    "is_capture" to true,
                    "captured_piece" to "车",
                    "captured_piece_kind" to "rook",
                    "move_summary" to "黑方炮吃掉红方车"
                )
            )
        )

        assertEquals(true, context["active"])
        assertEquals("high", context["severity"])
        assertEquals("recent_user_high_value_capture_and_user_low_material", context["reason"])
        assertEquals(1, context["user_remaining_piece_count"])
    }

    @Test
    fun moveCandidatesCarrySpeechHooksForReplyVariety() {
        val candidates = buildMoveCandidates(
            board = initialBoard(),
            side = Side.Black,
            playerSide = Side.Red,
            difficulty = 2,
            mistakeRate = 25,
            plyCount = 1,
            varietyKey = "speech-hooks-test"
        )

        assertTrue(candidates.isNotEmpty())
        val hooks = candidates.first().speechHooks
        assertTrue(hooks["plain_fact"].orEmpty().isNotBlank())
        assertTrue(hooks["piece_voice"].orEmpty().contains("可以"))
        assertTrue(hooks["avoid_default_phrases"].orEmpty().contains("内部风格提醒"))
        assertTrue(hooks["avoid_default_phrases"].orEmpty().contains("只用于生成前避让"))
        assertTrue(hooks["avoid_default_phrases"].orEmpty().contains("不能提到这份清单"))
        assertTrue(hooks["avoid_default_phrases"].orEmpty().contains("那我"))
        assertTrue(hooks["avoid_default_phrases"].orEmpty().contains("嘿嘿"))
        assertTrue(hooks["avoid_default_phrases"].orEmpty().contains("将你一军"))
        assertTrue(hooks["avoid_default_phrases"].orEmpty().contains("瞄到"))
        assertTrue(candidates.any { it.speechHooks["emotion_hint"].orEmpty().isNotBlank() })
    }

    @Test
    fun characterMoveHistoryCarriesRecentRepeatedTerms() {
        val before = GameState()
        val move = Move(Cell(0, 6), Cell(0, 5))
        val after = before.applyMove(move)

        val history = move.toHistoryMap(
            board = before.board,
            side = Side.Red,
            playerSide = Side.Black,
            nextGame = after,
            actor = "character",
            source = "model_candidate",
            replyText = "嘿嘿，我先拱一下。",
            recentRepeatedTerms = listOf("嘿嘿", "我先")
        )

        assertEquals(listOf("嘿嘿", "我先"), history["近期重复词"])
    }
}
