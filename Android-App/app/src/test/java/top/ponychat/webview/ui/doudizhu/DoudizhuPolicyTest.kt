package top.ponychat.webview.ui.doudizhu

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.random.Random

class DoudizhuPolicyTest {
    @Test
    fun deckHasFiftyFourUniqueCards() {
        val deck = doudizhuDeck()

        assertEquals(54, deck.size)
        assertEquals(54, deck.map { it.id }.distinct().size)
        assertTrue(deck.any { it.rank == DdzRank.SmallJoker })
        assertTrue(deck.any { it.rank == DdzRank.BigJoker })
    }

    @Test
    fun dealSplitsThreeHandsAndBottomCards() {
        val game = doudizhuNewGame(random = Random(3))

        assertEquals(17, game.hand(DdzSeat.User).size)
        assertEquals(17, game.hand(DdzSeat.Character).size)
        assertEquals(17, game.hand(DdzSeat.Robot).size)
        assertEquals(3, game.bottomCards.size)
        val allIds = DdzSeat.values().flatMap { game.hand(it) }.map { it.id } + game.bottomCards.map { it.id }
        assertEquals(54, allIds.distinct().size)
    }

    @Test
    fun rocketBeatsBombAndBombBeatsNormalCards() {
        val deck = doudizhuDeck()
        val rocket = deck.filter { it.rank == DdzRank.SmallJoker || it.rank == DdzRank.BigJoker }
        val bomb = deck.filter { it.rank == DdzRank.Four }
        val pair = deck.filter { it.rank == DdzRank.Ace }.take(2)

        val rocketCombo = doudizhuAnalyze(rocket)
        val bombCombo = doudizhuAnalyze(bomb)
        val pairCombo = doudizhuAnalyze(pair)

        assertEquals(DdzComboKind.Rocket, rocketCombo?.kind)
        assertEquals(DdzComboKind.Bomb, bombCombo?.kind)
        assertTrue(doudizhuCanBeat(rocketCombo!!, bombCombo))
        assertTrue(doudizhuCanBeat(bombCombo!!, pairCombo))
    }

    @Test
    fun straightsRejectTwoAndJokers() {
        val deck = doudizhuDeck()
        val legal = listOf(DdzRank.Three, DdzRank.Four, DdzRank.Five, DdzRank.Six, DdzRank.Seven)
            .map { rank -> deck.first { it.rank == rank } }
        val illegal = listOf(DdzRank.Ten, DdzRank.Jack, DdzRank.Queen, DdzRank.King, DdzRank.Ace, DdzRank.Two)
            .map { rank -> deck.first { it.rank == rank } }

        assertEquals(DdzComboKind.Straight, doudizhuAnalyze(legal)?.kind)
        assertEquals(null, doudizhuAnalyze(illegal))
    }

    @Test
    fun pairSequenceMustMatchLengthToBeat() {
        val deck = doudizhuDeck()
        fun pair(rank: DdzRank) = deck.filter { it.rank == rank }.take(2)
        val threePairSeq = pair(DdzRank.Three) + pair(DdzRank.Four) + pair(DdzRank.Five)
        val higherThreePairSeq = pair(DdzRank.Four) + pair(DdzRank.Five) + pair(DdzRank.Six)
        val fourPairSeq = pair(DdzRank.Four) + pair(DdzRank.Five) + pair(DdzRank.Six) + pair(DdzRank.Seven)

        val active = doudizhuAnalyze(threePairSeq)
        val higher = doudizhuAnalyze(higherThreePairSeq)
        val longer = doudizhuAnalyze(fourPairSeq)

        assertEquals(DdzComboKind.PairSequence, active?.kind)
        assertTrue(doudizhuCanBeat(higher!!, active))
        assertFalse(doudizhuCanBeat(longer!!, active))
    }

    @Test
    fun fourWithPairIsRecognizedAsFourTwoSingles() {
        val fourKingsWithPair = rankCards(DdzRank.King, 4) + rankCards(DdzRank.Three, 2)

        val combo = doudizhuAnalyze(fourKingsWithPair)

        assertEquals(DdzComboKind.FourTwoSingles, combo?.kind)
        assertEquals(DdzRank.King.weight, combo?.major)
        assertEquals(6, combo?.cardCount)
    }

    @Test
    fun candidatesIncludeFourWithPairAsFourTwoSingles() {
        val fourKingsWithPair = rankCards(DdzRank.King, 4) + rankCards(DdzRank.Three, 2)

        val candidates = doudizhuGenerateCandidates(fourKingsWithPair)

        assertTrue(candidates.any { candidate ->
            candidate.combo.kind == DdzComboKind.FourTwoSingles &&
                candidate.cards.map { it.id }.toSet() == fourKingsWithPair.map { it.id }.toSet()
        })
    }

    @Test
    fun hintCanBeatActiveSingleWhenPossible() {
        val deck = doudizhuDeck()
        val active = doudizhuAnalyze(listOf(deck.first { it.rank == DdzRank.Nine }))
        val hand = listOf(DdzRank.Three, DdzRank.Jack, DdzRank.Ace)
            .map { rank -> deck.first { it.rank == rank } }

        val hint = doudizhuHint(hand, active)

        assertNotNull(hint)
        assertEquals(DdzComboKind.Single, hint?.combo?.kind)
        assertTrue(doudizhuCanBeat(hint!!.combo, active))
    }

    @Test
    fun displayCardsPlaceLargestCardsFirst() {
        val displayCards = doudizhuDisplayCards(cards(DdzRank.Three, DdzRank.Seven, DdzRank.Four, DdzRank.Two))

        assertEquals(
            listOf(DdzRank.Two, DdzRank.Seven, DdzRank.Four, DdzRank.Three),
            displayCards.map { it.rank }
        )
    }

    @Test
    fun landlordWinAddsTwoPointsToLandlordOnly() {
        val userHand = cards(DdzRank.Three)
        val game = DdzGameState(
            phase = DdzPhase.Playing,
            hands = mapOf(
                DdzSeat.User to userHand,
                DdzSeat.Character to cards(DdzRank.Four),
                DdzSeat.Robot to cards(DdzRank.Five)
            ),
            landlord = DdzSeat.User,
            turn = DdzSeat.User
        )

        val result = game.playUserCards(userHand.map { it.id }.toSet())

        assertEquals(DdzPhase.RoundOver, result.phase)
        assertEquals(setOf(DdzSeat.User), result.winners)
        assertEquals(2, result.score.userWins)
        assertEquals(0, result.score.characterWins)
        assertEquals(0, result.score.robotWins)
    }

    @Test
    fun farmerWinAddsOnePointToEachFarmer() {
        val userHand = cards(DdzRank.Three)
        val game = DdzGameState(
            phase = DdzPhase.Playing,
            hands = mapOf(
                DdzSeat.User to userHand,
                DdzSeat.Character to cards(DdzRank.Four),
                DdzSeat.Robot to cards(DdzRank.Five)
            ),
            landlord = DdzSeat.Robot,
            turn = DdzSeat.User
        )

        val result = game.playUserCards(userHand.map { it.id }.toSet())

        assertEquals(DdzPhase.RoundOver, result.phase)
        assertEquals(setOf(DdzSeat.User, DdzSeat.Character), result.winners)
        assertEquals(1, result.score.userWins)
        assertEquals(1, result.score.characterWins)
        assertEquals(0, result.score.robotWins)
    }

    @Test
    fun aiDoesNotBeatFarmerPartnerUnlessItCanGoOut() {
        val active = doudizhuAnalyze(cards(DdzRank.King))!!
        val hand = cards(DdzRank.Three, DdzRank.Four, DdzRank.Ace)
        val context = aiContext(
            seat = DdzSeat.Robot,
            landlord = DdzSeat.User,
            lastPlaySeat = DdzSeat.Character,
            hands = mapOf(
                DdzSeat.User to cards(DdzRank.Two, DdzRank.SmallJoker),
                DdzSeat.Character to cards(DdzRank.Queen),
                DdzSeat.Robot to hand
            )
        )

        val pass = doudizhuChooseAiPlay(hand, active, context)
        val winningHand = cards(DdzRank.Ace)
        val winningPlay = doudizhuChooseAiPlay(
            hand = winningHand,
            active = active,
            context = context.copy(hands = context.hands + (DdzSeat.Robot to winningHand))
        )

        assertEquals(null, pass)
        assertNotNull(winningPlay)
        assertEquals(1, winningPlay?.cards?.size)
    }

    @Test
    fun aiLetsPartnerTakeWinningResponseWhenThereIsOnePassLeft() {
        val active = doudizhuAnalyze(cards(DdzRank.Queen))!!
        val hand = cards(DdzRank.Three, DdzRank.Four, DdzRank.Ace)
        val partnerHand = cards(DdzRank.King)
        val context = aiContext(
            seat = DdzSeat.Robot,
            landlord = DdzSeat.User,
            lastPlaySeat = DdzSeat.User,
            hands = mapOf(
                DdzSeat.User to cards(DdzRank.Two, DdzRank.SmallJoker),
                DdzSeat.Character to partnerHand,
                DdzSeat.Robot to hand
            ),
            passCount = 0
        )

        val play = doudizhuChooseAiPlay(hand, active, context)

        assertEquals(null, play)
    }

    @Test
    fun aiBombsUrgentLandlordEndgameWhenNoNormalResponseExists() {
        val active = doudizhuAnalyze(cards(DdzRank.Ace))!!
        val bombHand = rankCards(DdzRank.Three, 4) + cards(
            DdzRank.Four,
            DdzRank.Five,
            DdzRank.Six,
            DdzRank.Seven,
            DdzRank.Eight,
            DdzRank.Nine,
            DdzRank.Ten,
            DdzRank.Jack,
            DdzRank.Queen
        )
        val context = aiContext(
            seat = DdzSeat.Robot,
            landlord = DdzSeat.User,
            lastPlaySeat = DdzSeat.User,
            hands = mapOf(
                DdzSeat.User to cards(DdzRank.Two),
                DdzSeat.Character to cards(DdzRank.King, DdzRank.Two),
                DdzSeat.Robot to bombHand
            )
        )

        val play = doudizhuChooseAiPlay(bombHand, active, context)

        assertNotNull(play)
        assertEquals(DdzComboKind.Bomb, play?.combo?.kind)
    }

    @Test
    fun aiPreservesStraightWhenRespondingWithLooseSingle() {
        val active = doudizhuAnalyze(cards(DdzRank.Four))!!
        val hand = cards(
            DdzRank.Five,
            DdzRank.Six,
            DdzRank.Seven,
            DdzRank.Eight,
            DdzRank.Nine,
            DdzRank.Jack
        )
        val context = aiContext(
            seat = DdzSeat.Robot,
            landlord = DdzSeat.User,
            lastPlaySeat = DdzSeat.User,
            hands = mapOf(
                DdzSeat.User to cards(DdzRank.Two),
                DdzSeat.Character to cards(DdzRank.King, DdzRank.Ace),
                DdzSeat.Robot to hand
            )
        )

        val play = doudizhuChooseAiPlay(hand, active, context)

        assertNotNull(play)
        assertEquals(DdzComboKind.Single, play?.combo?.kind)
        assertEquals(DdzRank.Jack, play?.cards?.single()?.rank)
    }

    @Test
    fun aiPassesWhenItHasNoLegalResponse() {
        val active = doudizhuAnalyze(rankCards(DdzRank.Ace, 2))!!
        val hand = cards(DdzRank.Three, DdzRank.Four, DdzRank.Five, DdzRank.Six)
        val context = aiContext(
            seat = DdzSeat.Robot,
            landlord = DdzSeat.User,
            lastPlaySeat = DdzSeat.User,
            hands = mapOf(
                DdzSeat.User to cards(DdzRank.Two),
                DdzSeat.Character to cards(DdzRank.King),
                DdzSeat.Robot to hand
            )
        )

        val play = doudizhuChooseAiPlay(hand, active, context)

        assertEquals(null, play)
    }

    @Test
    fun sfxGroupsFollowMaterialFileNamesByPlayedCardCount() {
        assertEquals(null, doudizhuCardSfxGroupForCount(0))
        assertEquals(DoudizhuSfxGroup.Single, doudizhuCardSfxGroupForCount(1))
        assertEquals(DoudizhuSfxGroup.Pair, doudizhuCardSfxGroupForCount(2))
        assertEquals(DoudizhuSfxGroup.Medium, doudizhuCardSfxGroupForCount(3))
        assertEquals(DoudizhuSfxGroup.Medium, doudizhuCardSfxGroupForCount(5))
        assertEquals(DoudizhuSfxGroup.Many, doudizhuCardSfxGroupForCount(6))
        assertEquals(DoudizhuSfxGroup.Many, doudizhuCardSfxGroupForCount(12))
    }

    @Test
    fun sfxVariantPickerAvoidsImmediateRepeatsWithinEachGroup() {
        val picker = DoudizhuSfxVariantPicker(Random(7))
        DoudizhuSfxGroup.values().forEach { group ->
            val size = if (group == DoudizhuSfxGroup.Deal) 3 else 2
            var previous = picker.nextIndex(group, size)
            assertTrue(previous in 0 until size)
            repeat(20) {
                val next = picker.nextIndex(group, size)
                assertTrue(next in 0 until size)
                assertNotEquals(previous, next)
                previous = next
            }
        }
    }

    private fun cards(vararg ranks: DdzRank): List<DdzCard> {
        val deck = doudizhuDeck()
        val used = mutableMapOf<DdzRank, Int>()
        return ranks.map { rank ->
            val index = used.getOrDefault(rank, 0)
            used[rank] = index + 1
            deck.filter { it.rank == rank }[index]
        }
    }

    private fun rankCards(rank: DdzRank, count: Int): List<DdzCard> =
        doudizhuDeck().filter { it.rank == rank }.take(count)

    private fun aiContext(
        seat: DdzSeat,
        landlord: DdzSeat,
        lastPlaySeat: DdzSeat,
        hands: Map<DdzSeat, List<DdzCard>>,
        passCount: Int = 0
    ): DdzAiContext =
        DdzAiContext(
            seat = seat,
            landlord = landlord,
            lastPlaySeat = lastPlaySeat,
            handSizes = hands.mapValues { it.value.size },
            hands = hands,
            passCount = passCount
        )
}
