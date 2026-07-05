package top.ponychat.webview.ui.doudizhu

import kotlin.math.max
import kotlin.random.Random

internal enum class DdzSeat(val fallbackLabel: String, val isAi: Boolean) {
    User("你", false),
    Character("角色", true),
    Robot("机器人", true);

    fun next(): DdzSeat = when (this) {
        User -> Robot
        Robot -> Character
        Character -> User
    }
}

internal enum class DdzPhase {
    Bidding,
    Playing,
    RoundOver
}

internal enum class DdzShuffleMode {
    Regular,
    Firepower
}

internal enum class DdzSuit(val label: String, val tintKey: String) {
    Spade("黑桃", "black"),
    Heart("红桃", "red"),
    Club("梅花", "black"),
    Diamond("方片", "red"),
    Joker("", "joker")
}

internal enum class DdzRank(val weight: Int, val label: String) {
    Three(3, "3"),
    Four(4, "4"),
    Five(5, "5"),
    Six(6, "6"),
    Seven(7, "7"),
    Eight(8, "8"),
    Nine(9, "9"),
    Ten(10, "10"),
    Jack(11, "J"),
    Queen(12, "Q"),
    King(13, "K"),
    Ace(14, "A"),
    Two(15, "2"),
    SmallJoker(16, "小王"),
    BigJoker(17, "大王");

    val canChain: Boolean
        get() = weight in Three.weight..Ace.weight
}

internal data class DdzCard(
    val id: Int,
    val rank: DdzRank,
    val suit: DdzSuit
) {
    val isRed: Boolean
        get() = suit == DdzSuit.Heart || suit == DdzSuit.Diamond || rank == DdzRank.BigJoker

    val shortSuit: String
        get() = when (suit) {
            DdzSuit.Spade -> "S"
            DdzSuit.Heart -> "H"
            DdzSuit.Club -> "C"
            DdzSuit.Diamond -> "D"
            DdzSuit.Joker -> ""
        }
}

internal enum class DdzComboKind(val label: String) {
    Single("单张"),
    Pair("对子"),
    Triple("三张"),
    TripleSingle("三带一"),
    TriplePair("三带二"),
    Straight("顺子"),
    PairSequence("连对"),
    TripleSequence("飞机"),
    PlaneSingle("飞机带单"),
    PlanePair("飞机带对"),
    FourTwoSingles("四带二"),
    FourTwoPairs("四带两对"),
    Bomb("炸弹"),
    Rocket("王炸")
}

internal data class DdzCombo(
    val kind: DdzComboKind,
    val major: Int,
    val cardCount: Int,
    val sequenceLength: Int = 1
) {
    val label: String
        get() = when (kind) {
            DdzComboKind.Straight -> "${cardCount}张顺子"
            DdzComboKind.PairSequence -> "${sequenceLength}连对"
            DdzComboKind.TripleSequence -> "${sequenceLength}连飞机"
            DdzComboKind.PlaneSingle -> "${sequenceLength}飞机带单"
            DdzComboKind.PlanePair -> "${sequenceLength}飞机带对"
            else -> kind.label
        }
}

internal data class DdzCandidate(
    val cards: List<DdzCard>,
    val combo: DdzCombo
)

internal data class DdzAiContext(
    val seat: DdzSeat? = null,
    val landlord: DdzSeat? = null,
    val lastPlaySeat: DdzSeat? = null,
    val handSizes: Map<DdzSeat, Int> = emptyMap(),
    val hands: Map<DdzSeat, List<DdzCard>> = emptyMap(),
    val passCount: Int = 0
) {
    fun sameSide(first: DdzSeat?, second: DdzSeat?): Boolean {
        if (first == null || second == null) return false
        if (first == second) return true
        val knownLandlord = landlord ?: return false
        return first != knownLandlord && second != knownLandlord
    }

    fun partnerOf(currentSeat: DdzSeat): DdzSeat? {
        val knownLandlord = landlord ?: return null
        if (currentSeat == knownLandlord) return null
        return DdzSeat.values().firstOrNull { it != currentSeat && it != knownLandlord }
    }

    fun handSize(seat: DdzSeat): Int =
        handSizes[seat] ?: hands[seat]?.size ?: Int.MAX_VALUE
}

internal data class DdzPlay(
    val seat: DdzSeat,
    val cards: List<DdzCard> = emptyList(),
    val combo: DdzCombo? = null,
    val pass: Boolean = false
) {
    val summary: String
        get() = if (pass) "不出" else combo?.label.orEmpty()

    companion object {
        fun pass(seat: DdzSeat): DdzPlay = DdzPlay(seat = seat, pass = true)
    }
}

internal data class DdzScore(
    val userWins: Int = 0,
    val characterWins: Int = 0,
    val robotWins: Int = 0
) {
    fun addWinners(winners: Set<DdzSeat>, landlord: DdzSeat? = null): DdzScore {
        fun pointsFor(seat: DdzSeat): Int {
            if (seat !in winners) return 0
            return if (seat == landlord) 2 else 1
        }

        return copy(
            userWins = userWins + pointsFor(DdzSeat.User),
            characterWins = characterWins + pointsFor(DdzSeat.Character),
            robotWins = robotWins + pointsFor(DdzSeat.Robot)
        )
    }
}

internal data class DdzGameState(
    val phase: DdzPhase = DdzPhase.Bidding,
    val hands: Map<DdzSeat, List<DdzCard>> = emptyMap(),
    val dealtHands: Map<DdzSeat, List<DdzCard>> = emptyMap(),
    val bottomCards: List<DdzCard> = emptyList(),
    val landlord: DdzSeat? = null,
    val turn: DdzSeat = DdzSeat.User,
    val lastPlay: DdzPlay? = null,
    val tablePlays: Map<DdzSeat, DdzPlay> = emptyMap(),
    val passCount: Int = 0,
    val winner: DdzSeat? = null,
    val winners: Set<DdzSeat> = emptySet(),
    val message: String = "叫地主",
    val score: DdzScore = DdzScore(),
    val round: Int = 1
) {
    val activeCombo: DdzCombo?
        get() = lastPlay?.combo

    fun hand(seat: DdzSeat): List<DdzCard> = hands[seat].orEmpty()

    fun dealtHand(seat: DdzSeat): List<DdzCard> = dealtHands[seat].orEmpty().ifEmpty { hand(seat) }

    fun callLandlord(call: Boolean, random: Random = Random.Default): DdzGameState {
        if (phase != DdzPhase.Bidding) return this
        if (call) {
            return startPlaying(DdzSeat.User, "你叫地主，拿到底牌")
        }
        val robotStrength = doudizhuBidStrength(hand(DdzSeat.Robot))
        val characterStrength = doudizhuBidStrength(hand(DdzSeat.Character))
        val robotCalls = robotStrength >= 29 || (robotStrength >= 24 && random.nextInt(100) < 42)
        val characterCalls = characterStrength >= 30 || (characterStrength >= 24 && random.nextInt(100) < 38)
        val landlordSeat = when {
            robotCalls && characterCalls -> if (robotStrength >= characterStrength) DdzSeat.Robot else DdzSeat.Character
            robotCalls -> DdzSeat.Robot
            characterCalls -> DdzSeat.Character
            else -> listOf(DdzSeat.User, DdzSeat.Robot, DdzSeat.Character).maxBy { doudizhuBidStrength(hand(it)) }
        }
        val line = when (landlordSeat) {
            DdzSeat.User -> "大家都不叫，你的牌力最高，默认成为地主"
            DdzSeat.Character -> "你不叫，角色叫地主"
            DdzSeat.Robot -> "你不叫，机器人叫地主"
        }
        return startPlaying(landlordSeat, line)
    }

    fun playUserCards(cardIds: Set<Int>): DdzGameState {
        if (phase != DdzPhase.Playing) return this
        if (turn != DdzSeat.User) return copy(message = "还没轮到你")
        val cards = hand(DdzSeat.User).filter { it.id in cardIds }
        if (cards.isEmpty()) return copy(message = "先选牌")
        val combo = doudizhuAnalyze(cards) ?: return copy(message = "这个牌型不能出")
        if (!doudizhuCanBeat(combo, activeCombo)) {
            return copy(message = doudizhuBlockedPlayMessage(combo, activeCombo))
        }
        return applyPlay(DdzSeat.User, cards, combo)
    }

    fun passUser(): DdzGameState {
        if (phase != DdzPhase.Playing) return this
        if (turn != DdzSeat.User) return copy(message = "还没轮到你")
        if (activeCombo == null) return copy(message = "你先出牌，不能过")
        return applyPass(DdzSeat.User)
    }

    fun playAiTurn(random: Random = Random.Default): DdzGameState {
        if (phase != DdzPhase.Playing || turn == DdzSeat.User) return this
        val seat = turn
        val candidate = doudizhuChooseAiPlay(
            hand = hand(seat),
            active = activeCombo,
            context = DdzAiContext(
                seat = seat,
                landlord = landlord,
                lastPlaySeat = lastPlay?.seat,
                handSizes = hands.mapValues { it.value.size },
                hands = hands,
                passCount = passCount
            ),
            random = random
        )
        return if (candidate == null) {
            applyPass(seat)
        } else {
            applyPlay(seat, candidate.cards, candidate.combo)
        }
    }

    fun newRound(random: Random = Random.Default, shuffleMode: DdzShuffleMode = DdzShuffleMode.Regular): DdzGameState =
        doudizhuNewGame(score = score, round = round + 1, random = random, shuffleMode = shuffleMode)

    fun resetMatch(random: Random = Random.Default, shuffleMode: DdzShuffleMode = DdzShuffleMode.Regular): DdzGameState =
        doudizhuNewGame(random = random, shuffleMode = shuffleMode)

    fun restartRound(random: Random = Random.Default, shuffleMode: DdzShuffleMode = DdzShuffleMode.Regular): DdzGameState =
        doudizhuNewGame(score = score, round = round, random = random, shuffleMode = shuffleMode)

    private fun startPlaying(seat: DdzSeat, line: String): DdzGameState {
        val nextHands = hands.toMutableMap()
        nextHands[seat] = doudizhuSortCards(nextHands[seat].orEmpty() + bottomCards)
        return copy(
            phase = DdzPhase.Playing,
            hands = nextHands,
            landlord = seat,
            turn = seat,
            lastPlay = null,
            tablePlays = emptyMap(),
            passCount = 0,
            winner = null,
            winners = emptySet(),
            message = "$line，${seat.fallbackLabel}先出"
        )
    }

    private fun applyPlay(seat: DdzSeat, cards: List<DdzCard>, combo: DdzCombo): DdzGameState {
        val remaining = hand(seat).filterNot { card -> cards.any { it.id == card.id } }
        val nextHands = hands.toMutableMap().also { it[seat] = remaining }
        val play = DdzPlay(seat = seat, cards = doudizhuSortCards(cards), combo = combo)
        if (remaining.isEmpty()) {
            val currentLandlord = landlord ?: seat
            val sideWinners = if (seat == currentLandlord) {
                setOf(currentLandlord)
            } else {
                DdzSeat.values().toSet() - currentLandlord
            }
            val resultText = if (seat == currentLandlord) "地主赢了" else "农民赢了"
            return copy(
                phase = DdzPhase.RoundOver,
                hands = nextHands,
                turn = seat,
                lastPlay = play,
                tablePlays = tablePlays + (seat to play),
                passCount = 0,
                winner = seat,
                winners = sideWinners,
                score = score.addWinners(sideWinners, currentLandlord),
                message = resultText
            )
        }
        return copy(
            hands = nextHands,
            turn = seat.next(),
            lastPlay = play,
            tablePlays = tablePlays + (seat to play),
            passCount = 0,
            message = "${seat.fallbackLabel}出了${combo.label}"
        )
    }

    private fun applyPass(seat: DdzSeat): DdzGameState {
        val passPlay = DdzPlay.pass(seat)
        val nextPassCount = passCount + 1
        val leader = lastPlay?.seat
        if (leader != null && nextPassCount >= 2) {
            return copy(
                turn = leader,
                lastPlay = null,
                tablePlays = tablePlays + (seat to passPlay),
                passCount = 0,
                message = "${seat.fallbackLabel}不出，继续出牌"
            )
        }
        return copy(
            turn = seat.next(),
            tablePlays = tablePlays + (seat to passPlay),
            passCount = nextPassCount,
            message = "${seat.fallbackLabel}不出"
        )
    }
}

internal fun doudizhuNewGame(
    score: DdzScore = DdzScore(),
    round: Int = 1,
    random: Random = Random.Default,
    shuffleMode: DdzShuffleMode = DdzShuffleMode.Regular
): DdzGameState {
    val deal = doudizhuDeal(shuffleMode = shuffleMode, random = random)
    val dealtHands = deal.hands
    val hands = mapOf(
        DdzSeat.User to doudizhuSortCards(dealtHands.getValue(DdzSeat.User)),
        DdzSeat.Robot to doudizhuSortCards(dealtHands.getValue(DdzSeat.Robot)),
        DdzSeat.Character to doudizhuSortCards(dealtHands.getValue(DdzSeat.Character))
    )
    return DdzGameState(
        phase = DdzPhase.Bidding,
        hands = hands,
        dealtHands = dealtHands,
        bottomCards = doudizhuSortCards(deal.bottomCards),
        score = score,
        round = round,
        message = "第${round}局，是否叫地主？"
    )
}

internal fun doudizhuDeck(): List<DdzCard> {
    val normalRanks = DdzRank.values().filter { it.weight in DdzRank.Three.weight..DdzRank.Two.weight }
    var id = 0
    val cards = mutableListOf<DdzCard>()
    for (rank in normalRanks) {
        for (suit in listOf(DdzSuit.Spade, DdzSuit.Heart, DdzSuit.Club, DdzSuit.Diamond)) {
            cards += DdzCard(id++, rank, suit)
        }
    }
    cards += DdzCard(id++, DdzRank.SmallJoker, DdzSuit.Joker)
    cards += DdzCard(id, DdzRank.BigJoker, DdzSuit.Joker)
    return cards
}

private data class DdzDeal(
    val hands: Map<DdzSeat, List<DdzCard>>,
    val bottomCards: List<DdzCard>
)

private fun doudizhuDeal(shuffleMode: DdzShuffleMode, random: Random): DdzDeal {
    if (shuffleMode == DdzShuffleMode.Regular) {
        val deck = doudizhuDeck().shuffled(random)
        return DdzDeal(
            hands = mapOf(
                DdzSeat.User to deck.subList(0, 17),
                DdzSeat.Robot to deck.subList(17, 34),
                DdzSeat.Character to deck.subList(34, 51)
            ),
            bottomCards = deck.subList(51, 54)
        )
    }
    val deck = doudizhuDeck()
    val byRank = deck.groupBy { it.rank }
    val seats = DdzSeat.values().toList()
    val hands = seats.associateWith { mutableListOf<DdzCard>() }
    val bombRanks = DdzRank.values()
        .filter { it.weight in DdzRank.Three.weight..DdzRank.Two.weight }
        .shuffled(random)
        .take(random.nextInt(1, 4))
    val usedIds = mutableSetOf<Int>()
    bombRanks.forEach { rank ->
        val seat = seats.filter { hands.getValue(it).size <= 13 }.random(random)
        val bombCards = byRank.getValue(rank)
        hands.getValue(seat).addAll(bombCards.shuffled(random))
        usedIds.addAll(bombCards.map { it.id })
    }
    val remaining = deck.filterNot { it.id in usedIds }.shuffled(random).toMutableList()
    seats.shuffled(random).forEach { seat ->
        while (hands.getValue(seat).size < 17) {
            hands.getValue(seat).add(remaining.removeAt(0))
        }
        hands.getValue(seat).shuffle(random)
    }
    return DdzDeal(
        hands = hands.mapValues { it.value.toList() },
        bottomCards = remaining.take(3)
    )
}

internal fun doudizhuSortCards(cards: List<DdzCard>): List<DdzCard> =
    cards.sortedWith(compareByDescending<DdzCard> { it.rank.weight }.thenBy { it.suit.ordinal }.thenBy { it.id })

internal fun doudizhuDisplayCards(cards: List<DdzCard>): List<DdzCard> =
    doudizhuSortCards(cards)

internal fun doudizhuAnalyze(cards: List<DdzCard>): DdzCombo? {
    if (cards.isEmpty()) return null
    val sorted = cards.sortedBy { it.rank.weight }
    val n = sorted.size
    val counts = sorted.groupingBy { it.rank.weight }.eachCount().toSortedMap()
    val countValues = counts.values.sortedDescending()
    val weights = counts.keys.toList()

    fun combo(kind: DdzComboKind, major: Int, sequenceLength: Int = 1): DdzCombo =
        DdzCombo(kind = kind, major = major, cardCount = n, sequenceLength = sequenceLength)

    if (n == 2 && weights == listOf(DdzRank.SmallJoker.weight, DdzRank.BigJoker.weight)) {
        return combo(DdzComboKind.Rocket, DdzRank.BigJoker.weight)
    }
    if (n == 4 && countValues == listOf(4)) return combo(DdzComboKind.Bomb, weights.first())
    if (n == 1) return combo(DdzComboKind.Single, weights.first())
    if (n == 2 && countValues == listOf(2)) return combo(DdzComboKind.Pair, weights.first())
    if (n == 3 && countValues == listOf(3)) return combo(DdzComboKind.Triple, weights.first())
    if (n == 4 && countValues == listOf(3, 1)) {
        return combo(DdzComboKind.TripleSingle, counts.firstNotNullOf { if (it.value == 3) it.key else null })
    }
    if (n == 5 && countValues == listOf(3, 2)) {
        return combo(DdzComboKind.TriplePair, counts.firstNotNullOf { if (it.value == 3) it.key else null })
    }
    if (n >= 5 && counts.values.all { it == 1 } && doudizhuIsChain(weights)) {
        return combo(DdzComboKind.Straight, weights.last(), sequenceLength = n)
    }
    if (n >= 6 && n % 2 == 0 && counts.values.all { it == 2 } && doudizhuIsChain(weights)) {
        return combo(DdzComboKind.PairSequence, weights.last(), sequenceLength = n / 2)
    }
    if (n >= 6 && n % 3 == 0 && counts.values.all { it == 3 } && doudizhuIsChain(weights)) {
        return combo(DdzComboKind.TripleSequence, weights.last(), sequenceLength = n / 3)
    }
    doudizhuAnalyzePlane(counts, n)?.let { return it }
    val fourWeight = counts.firstNotNullOfOrNull { if (it.value == 4) it.key else null }
    if (n == 6 && fourWeight != null && counts.filterKeys { it != fourWeight }.values.sum() == 2) {
        return combo(DdzComboKind.FourTwoSingles, fourWeight)
    }
    if (n == 8 && countValues == listOf(4, 2, 2)) {
        return combo(DdzComboKind.FourTwoPairs, fourWeight ?: counts.firstNotNullOf { if (it.value == 4) it.key else null })
    }
    return null
}

private fun doudizhuAnalyzePlane(counts: Map<Int, Int>, cardCount: Int): DdzCombo? {
    val exactTriples = counts.filterValues { it == 3 }.keys.sorted()
    for (length in exactTriples.size downTo 2) {
        exactTriples.windowed(length).forEach { chain ->
            if (!doudizhuIsChain(chain)) return@forEach
            val remaining = counts.filterKeys { it !in chain }
            val major = chain.last()
            if (cardCount == length * 4 && remaining.values.sum() == length) {
                return DdzCombo(DdzComboKind.PlaneSingle, major, cardCount, length)
            }
            if (cardCount == length * 5 && remaining.values.all { it == 2 } && remaining.values.sum() == length * 2) {
                return DdzCombo(DdzComboKind.PlanePair, major, cardCount, length)
            }
        }
    }
    return null
}

private fun doudizhuIsChain(weights: List<Int>): Boolean {
    if (weights.any { it > DdzRank.Ace.weight }) return false
    if (weights.distinct().size != weights.size) return false
    return weights.zipWithNext().all { (a, b) -> b == a + 1 }
}

internal fun doudizhuCanBeat(candidate: DdzCombo, active: DdzCombo?): Boolean {
    active ?: return true
    if (candidate.kind == DdzComboKind.Rocket) return active.kind != DdzComboKind.Rocket
    if (active.kind == DdzComboKind.Rocket) return false
    if (candidate.kind == DdzComboKind.Bomb && active.kind != DdzComboKind.Bomb) return true
    if (candidate.kind != active.kind) return false
    if (candidate.cardCount != active.cardCount) return false
    if (candidate.sequenceLength != active.sequenceLength) return false
    return candidate.major > active.major
}

internal fun doudizhuBlockedPlayMessage(candidate: DdzCombo, active: DdzCombo?): String {
    active ?: return "当前可以直接出牌"
    if (active.kind == DdzComboKind.Rocket) return "王炸最大，只能不出"
    if (active.kind == DdzComboKind.Bomb && candidate.kind != DdzComboKind.Bomb) {
        return "当前要出炸弹或王炸"
    }
    val samePattern = candidate.kind == active.kind &&
        candidate.cardCount == active.cardCount &&
        candidate.sequenceLength == active.sequenceLength
    return if (samePattern) {
        "牌不够大，需要更大的${active.label}"
    } else {
        "当前要出${active.label}，不能出${candidate.label}"
    }
}

internal fun doudizhuGenerateCandidates(hand: List<DdzCard>): List<DdzCandidate> {
    val byWeight = hand.groupBy { it.rank.weight }.toSortedMap()
    val candidates = mutableListOf<DdzCandidate>()

    fun take(weight: Int, count: Int): List<DdzCard> = byWeight.getValue(weight).take(count)
    fun add(cards: List<DdzCard>) {
        doudizhuAnalyze(cards)?.let { candidates += DdzCandidate(doudizhuSortCards(cards), it) }
    }

    byWeight.forEach { (_, cards) ->
        add(cards.take(1))
        if (cards.size >= 2) add(cards.take(2))
        if (cards.size >= 3) add(cards.take(3))
        if (cards.size == 4) add(cards.take(4))
    }

    val singleWeights = byWeight.keys.toList()
    byWeight.filterValues { it.size >= 3 }.keys.forEach { triple ->
        singleWeights.filter { it != triple }.forEach { wing ->
            add(take(triple, 3) + take(wing, 1))
        }
        byWeight.filterValues { it.size >= 2 }.keys.filter { it != triple }.forEach { wing ->
            add(take(triple, 3) + take(wing, 2))
        }
    }
    byWeight.filterValues { it.size == 4 }.keys.forEach { four ->
        doudizhuCombinations(singleWeights.filter { it != four }, 2).forEach { singles ->
            add(take(four, 4) + singles.flatMap { take(it, 1) })
        }
        byWeight.filterValues { it.size >= 2 }.keys.filter { it != four }.forEach { pair ->
            add(take(four, 4) + take(pair, 2))
        }
        doudizhuCombinations(byWeight.filterValues { it.size >= 2 }.keys.filter { it != four }, 2).forEach { pairs ->
            add(take(four, 4) + pairs.flatMap { take(it, 2) })
        }
    }

    val chainWeights = byWeight.keys.filter { it <= DdzRank.Ace.weight }
    doudizhuConsecutiveWindows(chainWeights, 5).forEach { seq ->
        add(seq.flatMap { take(it, 1) })
    }
    val pairWeights = byWeight.filterValues { it.size >= 2 }.keys.filter { it <= DdzRank.Ace.weight }
    doudizhuConsecutiveWindows(pairWeights, 3).forEach { seq ->
        add(seq.flatMap { take(it, 2) })
    }
    val tripleWeights = byWeight.filterValues { it.size >= 3 }.keys.filter { it <= DdzRank.Ace.weight }
    doudizhuConsecutiveWindows(tripleWeights, 2).forEach { seq ->
        add(seq.flatMap { take(it, 3) })
        doudizhuCombinations(singleWeights.filter { it !in seq }, seq.size).forEach { wings ->
            add(seq.flatMap { take(it, 3) } + wings.flatMap { take(it, 1) })
        }
        val pairWings = byWeight.filterValues { it.size >= 2 }.keys.filter { it !in seq }
        doudizhuCombinations(pairWings, seq.size).forEach { wings ->
            add(seq.flatMap { take(it, 3) } + wings.flatMap { take(it, 2) })
        }
    }

    if (byWeight.containsKey(DdzRank.SmallJoker.weight) && byWeight.containsKey(DdzRank.BigJoker.weight)) {
        add(take(DdzRank.SmallJoker.weight, 1) + take(DdzRank.BigJoker.weight, 1))
    }
    return candidates.distinctBy { it.cards.map { card -> card.id }.sorted() }
}

private fun <T> doudizhuCombinations(items: List<T>, pick: Int): List<List<T>> {
    if (pick == 0) return listOf(emptyList())
    if (pick < 0 || items.size < pick) return emptyList()
    val result = mutableListOf<List<T>>()
    fun visit(start: Int, chosen: MutableList<T>) {
        if (chosen.size == pick) {
            result += chosen.toList()
            return
        }
        val remainingNeeded = pick - chosen.size
        val lastStart = items.size - remainingNeeded
        for (index in start..lastStart) {
            chosen += items[index]
            visit(index + 1, chosen)
            chosen.removeAt(chosen.lastIndex)
        }
    }
    visit(0, mutableListOf())
    return result
}

private fun doudizhuConsecutiveWindows(weights: List<Int>, minLength: Int): List<List<Int>> {
    val sorted = weights.distinct().sorted()
    val result = mutableListOf<List<Int>>()
    var start = 0
    while (start < sorted.size) {
        var end = start + 1
        while (end < sorted.size && sorted[end] == sorted[end - 1] + 1) end++
        val run = sorted.subList(start, end)
        for (length in minLength..run.size) {
            for (offset in 0..(run.size - length)) {
                result += run.subList(offset, offset + length)
            }
        }
        start = end
    }
    return result
}

internal fun doudizhuChooseAiPlay(
    hand: List<DdzCard>,
    active: DdzCombo?,
    random: Random = Random.Default
): DdzCandidate? = doudizhuChooseAiPlay(
    hand = hand,
    active = active,
    context = DdzAiContext(),
    random = random
)

internal fun doudizhuChooseAiPlay(
    hand: List<DdzCard>,
    active: DdzCombo?,
    context: DdzAiContext,
    random: Random = Random.Default
): DdzCandidate? {
    val legal = doudizhuGenerateCandidates(hand)
        .filter { doudizhuCanBeat(it.combo, active) }
    if (legal.isEmpty()) return null

    legal.firstOrNull { it.cards.size == hand.size }?.let { return it }

    if (active != null) {
        return doudizhuChooseAiResponse(hand, legal, active, context)
    }

    return doudizhuChooseAiLead(hand, legal, context, random)
}

private fun doudizhuChooseAiResponse(
    hand: List<DdzCard>,
    legal: List<DdzCandidate>,
    active: DdzCombo,
    context: DdzAiContext
): DdzCandidate? {
    val seat = context.seat
    val activeSeat = context.lastPlaySeat
    if (seat != null && activeSeat != null && context.sameSide(seat, activeSeat)) {
        return null
    }

    if (doudizhuShouldLeaveResponseToPartner(active, context)) {
        return null
    }

    val urgent = doudizhuIsUrgentOpponentThreat(context)
    val normal = legal.filterNot { it.combo.kind == DdzComboKind.Bomb || it.combo.kind == DdzComboKind.Rocket }
    val pool = when {
        urgent -> legal
        normal.isNotEmpty() -> normal
        hand.size <= 8 -> legal
        legal.any { doudizhuEstimatedTurnCount(doudizhuCardsAfterPlay(hand, it.cards)) <= 1 } -> legal
        else -> emptyList()
    }
    if (pool.isEmpty()) return null
    return pool.minWithOrNull(
        compareBy<DdzCandidate> { doudizhuResponseScore(hand, it, context, urgent) }
            .thenBy { it.combo.major }
            .thenBy { it.cards.size }
    )
}

private fun doudizhuChooseAiLead(
    hand: List<DdzCard>,
    legal: List<DdzCandidate>,
    context: DdzAiContext,
    random: Random
): DdzCandidate? {
    val seat = context.seat
    val partner = seat?.let { context.partnerOf(it) }
    if (seat != null && partner != null && partner == seat.next() && context.handSize(partner) == 1) {
        val single = legal
            .filter { it.combo.kind == DdzComboKind.Single }
            .minWithOrNull(compareBy<DdzCandidate> { it.combo.major }.thenBy { it.cards.firstOrNull()?.id ?: Int.MAX_VALUE })
        if (single != null) return single
    }

    val nonBomb = legal.filterNot { it.combo.kind == DdzComboKind.Bomb || it.combo.kind == DdzComboKind.Rocket }
    val pool = if (nonBomb.isNotEmpty() && hand.size > 4) nonBomb else legal
    val tieBreakers = pool.associateWith { random.nextInt(16) }
    return pool.minWithOrNull(
        compareBy<DdzCandidate> { doudizhuLeadScore(hand, it, context) }
            .thenBy { tieBreakers[it] ?: 0 }
            .thenByDescending { it.cards.size }
            .thenBy { it.combo.major }
    )
}

private fun doudizhuShouldLeaveResponseToPartner(active: DdzCombo, context: DdzAiContext): Boolean {
    val seat = context.seat ?: return false
    val activeSeat = context.lastPlaySeat ?: return false
    val landlord = context.landlord ?: return false
    if (activeSeat != landlord || seat == landlord || context.passCount != 0) return false
    val partner = context.partnerOf(seat) ?: return false
    val partnerHand = context.hands[partner].orEmpty()
    if (partnerHand.isEmpty()) return false
    return doudizhuGenerateCandidates(partnerHand).any {
        it.cards.size == partnerHand.size && doudizhuCanBeat(it.combo, active)
    }
}

private fun doudizhuIsUrgentOpponentThreat(context: DdzAiContext): Boolean {
    val seat = context.seat ?: return false
    val activeSeat = context.lastPlaySeat ?: return false
    if (context.sameSide(seat, activeSeat)) return false
    val activeSize = context.handSize(activeSeat)
    if (activeSize <= 2) return true
    return activeSeat == context.landlord && activeSize <= 4
}

private fun doudizhuLeadScore(hand: List<DdzCard>, candidate: DdzCandidate, context: DdzAiContext): Int {
    val remaining = doudizhuCardsAfterPlay(hand, candidate.cards)
    if (remaining.isEmpty()) return Int.MIN_VALUE
    var score = doudizhuHandShapeScore(remaining)
    score -= candidate.cards.size * 14
    score += candidate.combo.major
    score += when (candidate.combo.kind) {
        DdzComboKind.PlanePair -> -70
        DdzComboKind.PlaneSingle -> -64
        DdzComboKind.TripleSequence -> -58
        DdzComboKind.PairSequence -> -46
        DdzComboKind.Straight -> -40
        DdzComboKind.TriplePair -> -24
        DdzComboKind.TripleSingle -> -18
        DdzComboKind.Triple -> -10
        DdzComboKind.Pair -> 6
        DdzComboKind.Single -> 16
        DdzComboKind.Bomb -> 130
        DdzComboKind.Rocket -> 170
        DdzComboKind.FourTwoSingles,
        DdzComboKind.FourTwoPairs -> 12
    }
    val seat = context.seat
    val partner = seat?.let { context.partnerOf(it) }
    if (partner != null && context.handSize(partner) <= 2 && candidate.combo.kind in setOf(DdzComboKind.Single, DdzComboKind.Pair)) {
        score -= 22
    }
    return score + doudizhuComboBreakPenalty(hand, candidate.cards)
}

private fun doudizhuResponseScore(
    hand: List<DdzCard>,
    candidate: DdzCandidate,
    context: DdzAiContext,
    urgent: Boolean
): Int {
    val remaining = doudizhuCardsAfterPlay(hand, candidate.cards)
    if (remaining.isEmpty()) return Int.MIN_VALUE
    val remainingTurns = doudizhuEstimatedTurnCount(remaining)
    var score = doudizhuHandShapeScore(remaining) + remainingTurns * 18
    score += candidate.combo.major * when (candidate.combo.kind) {
        DdzComboKind.Single,
        DdzComboKind.Pair -> 3
        else -> 1
    }
    score += candidate.cards.size
    score += when (candidate.combo.kind) {
        DdzComboKind.Bomb -> if (urgent) 12 else 150
        DdzComboKind.Rocket -> if (urgent) 18 else 190
        else -> 0
    }
    if (!urgent && candidate.combo.major >= DdzRank.Two.weight) score += 18
    if (urgent) score -= 38
    score += doudizhuComboBreakPenalty(hand, candidate.cards)

    val seat = context.seat
    val activeSeat = context.lastPlaySeat
    if (seat != null && activeSeat == context.landlord && seat != context.landlord) {
        score -= 12
    }
    return score
}

private fun doudizhuCardsAfterPlay(hand: List<DdzCard>, playedCards: List<DdzCard>): List<DdzCard> {
    val playedIds = playedCards.mapTo(mutableSetOf()) { it.id }
    return hand.filterNot { it.id in playedIds }
}

private fun doudizhuComboBreakPenalty(hand: List<DdzCard>, playedCards: List<DdzCard>): Int {
    val handCounts = hand.groupingBy { it.rank.weight }.eachCount()
    val playedCounts = playedCards.groupingBy { it.rank.weight }.eachCount()
    var penalty = 0
    playedCounts.forEach { (weight, playedCount) ->
        val originalCount = handCounts[weight] ?: return@forEach
        penalty += when {
            originalCount == 4 && playedCount in 1..3 -> 80
            originalCount == 3 && playedCount in 1..2 -> 26
            originalCount == 2 && playedCount == 1 -> 12
            else -> 0
        }
    }
    return penalty
}

private fun doudizhuHandShapeScore(hand: List<DdzCard>): Int {
    if (hand.isEmpty()) return Int.MIN_VALUE / 2
    val counts = hand.groupingBy { it.rank.weight }.eachCount()
    val candidates = doudizhuGenerateCandidates(hand)
    val estimatedTurns = doudizhuEstimatedTurnCount(hand)
    val singles = counts.filterValues { it == 1 }.keys
    val pairs = counts.filterValues { it == 2 }.keys
    val triples = counts.filterValues { it == 3 }.keys
    val bombs = counts.values.count { it == 4 }
    val hasRocket = counts.containsKey(DdzRank.SmallJoker.weight) && counts.containsKey(DdzRank.BigJoker.weight)
    val bestSequenceCards = candidates
        .filter {
            it.combo.kind in setOf(
                DdzComboKind.Straight,
                DdzComboKind.PairSequence,
                DdzComboKind.TripleSequence,
                DdzComboKind.PlaneSingle,
                DdzComboKind.PlanePair
            )
        }
        .maxOfOrNull { it.cards.size } ?: 0
    val bestPlayCards = candidates.maxOfOrNull { it.cards.size } ?: 0

    var score = hand.size * 6 + estimatedTurns * 45
    score += singles.fold(0) { total, weight ->
        total + if (weight <= DdzRank.Ten.weight) 18 else if (weight <= DdzRank.Ace.weight) 10 else 4
    }
    score += pairs.fold(0) { total, weight ->
        total + if (weight <= DdzRank.Ten.weight) 8 else 3
    }
    score -= triples.size * 8
    score -= bombs * 28
    if (hasRocket) score -= 32
    score -= bestSequenceCards * 6
    score -= max(0, bestPlayCards - 4) * 3
    score -= doudizhuControlScore(hand)
    return score
}

private fun doudizhuControlScore(hand: List<DdzCard>): Int =
    hand.fold(0) { total, card ->
        total + when (card.rank) {
            DdzRank.BigJoker -> 18
            DdzRank.SmallJoker -> 16
            DdzRank.Two -> 10
            DdzRank.Ace -> 6
            DdzRank.King -> 3
            else -> 0
        }
    }

private fun doudizhuEstimatedTurnCount(hand: List<DdzCard>): Int {
    if (hand.isEmpty()) return 0
    if (hand.size <= 12) return doudizhuExactTurnCount(hand, mutableMapOf())
    var remaining = hand
    var turns = 0
    while (remaining.isNotEmpty() && turns < 20) {
        val best = doudizhuGenerateCandidates(remaining)
            .maxWithOrNull(compareBy<DdzCandidate> { doudizhuTurnRemovalValue(it) }.thenBy { -it.combo.major })
            ?: return turns + remaining.size
        remaining = doudizhuCardsAfterPlay(remaining, best.cards)
        turns += 1
    }
    return turns + remaining.size
}

private fun doudizhuExactTurnCount(hand: List<DdzCard>, memo: MutableMap<Long, Int>): Int {
    if (hand.isEmpty()) return 0
    val key = doudizhuHandKey(hand)
    memo[key]?.let { return it }
    val candidates = doudizhuGenerateCandidates(hand)
        .sortedWith(compareByDescending<DdzCandidate> { doudizhuTurnRemovalValue(it) }.thenBy { it.combo.major })
        .take(56)
    var best = hand.size
    candidates.forEach { candidate ->
        val next = doudizhuCardsAfterPlay(hand, candidate.cards)
        val turns = 1 + doudizhuExactTurnCount(next, memo)
        if (turns < best) best = turns
    }
    memo[key] = best
    return best
}

private fun doudizhuHandKey(hand: List<DdzCard>): Long =
    hand.fold(0L) { acc, card -> acc or (1L shl card.id) }

private fun doudizhuTurnRemovalValue(candidate: DdzCandidate): Int {
    val kindBonus = when (candidate.combo.kind) {
        DdzComboKind.PlanePair -> 90
        DdzComboKind.PlaneSingle -> 82
        DdzComboKind.TripleSequence -> 76
        DdzComboKind.PairSequence -> 64
        DdzComboKind.Straight -> 58
        DdzComboKind.TriplePair -> 42
        DdzComboKind.TripleSingle -> 36
        DdzComboKind.FourTwoPairs -> 30
        DdzComboKind.FourTwoSingles -> 26
        DdzComboKind.Triple -> 22
        DdzComboKind.Pair -> 8
        DdzComboKind.Single -> 0
        DdzComboKind.Bomb -> -18
        DdzComboKind.Rocket -> -24
    }
    return candidate.cards.size * 100 + kindBonus - candidate.combo.major
}

internal fun doudizhuHintCandidates(hand: List<DdzCard>, active: DdzCombo?): List<DdzCandidate> =
    doudizhuGenerateCandidates(hand)
        .filter { doudizhuCanBeat(it.combo, active) }
        .sortedWith(
            compareBy<DdzCandidate> { doudizhuHintTier(it.combo, active) }
                .thenBy { it.combo.major }
                .thenBy { it.cards.size }
                .thenBy { it.cards.sumOf { card -> card.rank.weight } }
        )

internal fun doudizhuHint(hand: List<DdzCard>, active: DdzCombo?): DdzCandidate? =
    doudizhuHintCandidates(hand, active).firstOrNull()

private fun doudizhuHintTier(candidate: DdzCombo, active: DdzCombo?): Int {
    if (active == null) return candidate.kind.ordinal
    val matchesActive = candidate.kind == active.kind &&
        candidate.cardCount == active.cardCount &&
        candidate.sequenceLength == active.sequenceLength
    return when {
        matchesActive -> 0
        candidate.kind == DdzComboKind.Bomb -> 1
        candidate.kind == DdzComboKind.Rocket -> 2
        else -> 3
    }
}

internal fun doudizhuBidStrength(hand: List<DdzCard>): Int {
    val counts = hand.groupingBy { it.rank.weight }.eachCount()
    var high = 0
    hand.forEach { card ->
        high += when (card.rank) {
            DdzRank.BigJoker -> 9
            DdzRank.SmallJoker -> 8
            DdzRank.Two -> 5
            DdzRank.Ace -> 3
            DdzRank.King -> 2
            else -> 0
        }
    }
    val bombs = counts.values.count { it == 4 } * 8
    val triples = counts.values.count { it == 3 } * 3
    val pairs = counts.values.count { it == 2 }
    val chains = doudizhuGenerateCandidates(hand).filter {
        it.combo.kind in setOf(DdzComboKind.Straight, DdzComboKind.PairSequence, DdzComboKind.TripleSequence)
    }.maxOfOrNull { it.cards.size } ?: 0
    return high + bombs + triples + pairs + max(0, chains - 4)
}

internal fun doudizhuSeatTitle(
    seat: DdzSeat,
    characterName: String,
    userName: String
): String = when (seat) {
    DdzSeat.User -> userName.ifBlank { seat.fallbackLabel }
    DdzSeat.Character -> characterName.ifBlank { seat.fallbackLabel }
    DdzSeat.Robot -> seat.fallbackLabel
}
