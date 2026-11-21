package top.ponychat.webview.ui.doudizhu

import androidx.compose.ui.unit.Dp
import kotlin.math.roundToInt

internal const val DDZ_OPENING_ANIMATION_MS = 6_000L
internal const val DDZ_INITIAL_DEAL_DURATION_MS = 5_500L
internal const val DDZ_INITIAL_SORT_DURATION_MS = DDZ_OPENING_ANIMATION_MS - DDZ_INITIAL_DEAL_DURATION_MS
internal const val DDZ_LANDLORD_INSERT_DURATION_MS = 2_000L
internal const val DDZ_LANDLORD_SORT_DURATION_MS = 500L
internal const val DDZ_LANDLORD_FADE_PROGRESS_FRACTION = 0.25f
internal const val DDZ_LANDLORD_DROP_PROGRESS_FRACTION = 0.40f
internal const val DDZ_DEAL_CARD_TOTAL = 51
internal const val DDZ_ANIMATION_FRAME_COUNT = 30
internal const val DDZ_DEAL_FLY_FRAME_COUNT = 3

internal enum class DdzLandlordIntroStage {
    Insert,
    Sort
}

internal data class DdzLandlordIntroState(
    val seat: DdzSeat,
    val stage: DdzLandlordIntroStage
)

internal fun doudizhuDealVisibleCount(seat: DdzSeat, dealtCards: Int): Int {
    val seatIndex = when (seat) {
        DdzSeat.User -> 0
        DdzSeat.Robot -> 1
        DdzSeat.Character -> 2
    }
    val safeCount = dealtCards.coerceIn(0, DDZ_DEAL_CARD_TOTAL)
    return (safeCount / 3 + if (safeCount % 3 > seatIndex) 1 else 0).coerceAtMost(17)
}

internal fun doudizhuLandlordBaseHand(finalHand: List<DdzCard>, bottomCards: List<DdzCard>): List<DdzCard> {
    val bottomIds = bottomCards.map { it.id }.toSet()
    return finalHand.filterNot { it.id in bottomIds }
}

internal fun doudizhuLandlordIntroHand(
    finalHand: List<DdzCard>,
    bottomCards: List<DdzCard>,
    stage: DdzLandlordIntroStage?
): List<DdzCard> {
    val baseHand = doudizhuLandlordBaseHand(finalHand, bottomCards)
    return when (stage) {
        DdzLandlordIntroStage.Insert -> baseHand + bottomCards
        DdzLandlordIntroStage.Sort -> finalHand
        null -> finalHand
    }
}

internal fun doudizhuLandlordIntroCount(
    finalHand: List<DdzCard>,
    bottomCards: List<DdzCard>,
    stage: DdzLandlordIntroStage?,
    insertProgress: Float
): Int {
    if (stage != DdzLandlordIntroStage.Insert) return finalHand.size
    val baseCount = doudizhuLandlordBaseHand(finalHand, bottomCards).size
    val insertedCount = (bottomCards.size * insertProgress.coerceIn(0f, 1f)).roundToInt()
    return baseCount + insertedCount
}

internal fun doudizhuHintCycleSignature(hand: List<DdzCard>, activeCombo: DdzCombo?): String {
    val handPart = hand.joinToString(separator = ",") { it.id.toString() }
    val activePart = activeCombo?.let {
        "${it.kind}:${it.major}:${it.cardCount}:${it.sequenceLength}"
    }.orEmpty()
    return "$handPart|$activePart"
}

internal fun clampDp(value: Dp, min: Dp, max: Dp): Dp = when {
    value < min -> min
    value > max -> max
    else -> value
}
