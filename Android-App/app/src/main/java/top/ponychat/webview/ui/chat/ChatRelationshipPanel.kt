package top.ponychat.webview.ui.chat

import androidx.compose.animation.core.animate
import androidx.compose.animation.core.tween
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.input.nestedscroll.NestedScrollConnection
import androidx.compose.ui.input.nestedscroll.NestedScrollSource
import androidx.compose.ui.input.nestedscroll.nestedScroll
import androidx.compose.ui.input.pointer.PointerEventPass
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.input.pointer.positionChangeIgnoreConsumed
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.Velocity
import androidx.compose.ui.unit.dp
import androidx.compose.ui.zIndex
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import kotlin.math.abs
import kotlin.math.exp
import kotlin.math.ln
import top.ponychat.webview.data.model.Character
import top.ponychat.webview.data.model.RelationshipPageContent
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.ui.theme.Primary

private const val RELATIONSHIP_EMPTY_TEXT = "暂无关系内容"
private val RELATIONSHIP_EMPTY_CHIPS = listOf("暂无内容")
private val RELATIONSHIP_EMPTY_ITEMS = listOf(RELATIONSHIP_EMPTY_TEXT)
private val RelationshipRomanticLightAccent = Color(0xFFE11D48)
private val RelationshipRomanticDarkAccent = Color(0xFFFB7185)

@Composable
internal fun ChatRelationshipPanel(
    character: Character,
    prefs: AppPreferences,
    state: ChatUiState,
    onRefresh: () -> Unit,
    modifier: Modifier = Modifier
) {
    val displayName = character.displayName()
    val userDisplayName = prefs.nickname.ifBlank { prefs.username }.ifBlank { "?" }
    val pronoun = character.relationshipPronoun()
    val stageKey = normalizeRelationshipStageKey(
        state.relationshipStageOverride ?: state.relationshipSnapshot?.stageKey ?: "uncertain"
    )
    val romanticColors = relationshipRomanticColors()
    val stageUi = relationshipStageUi(stageKey, pronoun)
        .withRomanticColors(romanticColors.accent)
    val pageContent = if (state.relationshipStageOverride == null) {
        state.relationshipSnapshot?.pageContent
    } else {
        null
    }
    val overviewText = pageContent.relationshipTextOr(state.relationshipSnapshotError ?: RELATIONSHIP_EMPTY_TEXT, maxChars = 120) { it.overview }
    val moodText = pageContent.relationshipTextOr(RELATIONSHIP_EMPTY_TEXT, maxChars = 72) { it.mood }
    val moodChips = pageContent.relationshipChipsOr(RELATIONSHIP_EMPTY_CHIPS) { it.chips }
    val selfPortraitText = pageContent.relationshipTextOr(RELATIONSHIP_EMPTY_TEXT, maxChars = 36) { it.selfPortrait }
    val betweenPortraitText = pageContent.relationshipTextOr(RELATIONSHIP_EMPTY_TEXT, maxChars = 36) { it.betweenPortrait }
    val rememberedItems = pageContent.relationshipItemsOr(
        fallback = RELATIONSHIP_EMPTY_ITEMS,
        limit = 4,
        maxItemChars = 48
    ) { it.rememberedItems }
    val timelineItems = pageContent.relationshipItemsOr(
        fallback = RELATIONSHIP_EMPTY_ITEMS,
        limit = 4,
        maxItemChars = 48
    ) { it.timelineItems }
    val suggestionItems = pageContent.relationshipItemsOr(
        fallback = RELATIONSHIP_EMPTY_ITEMS,
        limit = 4,
        maxItemChars = 14
    ) { it.suggestions }
    val isPullRefreshing = state.isLoadingRelationshipSnapshot
    // Keep the content composed while fetching updates, preserving scroll and avatars.
    val showLoadingPanel = state.relationshipStageOverride == null && pageContent == null
    val refreshAction by rememberUpdatedState(onRefresh)
    val scrollState = rememberScrollState()
    val density = LocalDensity.current
    val context = LocalContext.current
    val scope = rememberCoroutineScope()

    val pullRefreshMaxHeight = 76.dp
    val pullRefreshMaxPx = with(density) { pullRefreshMaxHeight.toPx() }
    val pullRefreshDampingStartPx = pullRefreshMaxPx * 0.5f
    val pullRefreshTriggerPx = pullRefreshMaxPx * 0.7f
    val pullRefreshDampingScalePx = ((pullRefreshMaxPx - pullRefreshDampingStartPx) * 0.75f)
        .coerceAtLeast(1f)
    val pullRefreshDragMaxPx = pullRefreshMaxPx * 3f
    var pullRefreshOffsetPx by remember { mutableFloatStateOf(0f) }
    var pullRefreshDragDistancePx by remember { mutableFloatStateOf(0f) }
    var pullRefreshReadyHapticFired by remember { mutableStateOf(false) }
    var pullRefreshBackJob by remember { mutableStateOf<Job?>(null) }
    var pullRefreshBackGeneration by remember { mutableIntStateOf(0) }

    fun isAtRefreshTop(): Boolean = scrollState.value <= 2 || !scrollState.canScrollBackward

    fun pullRefreshOffsetForDrag(dragDistancePx: Float): Float {
        val drag = dragDistancePx.coerceAtLeast(0f)
        if (drag <= pullRefreshDampingStartPx) {
            return drag.coerceAtMost(pullRefreshMaxPx)
        }
        val extraDrag = drag - pullRefreshDampingStartPx
        val dampedExtra = pullRefreshDampingScalePx *
            ln((1f + extraDrag / pullRefreshDampingScalePx).toDouble()).toFloat()
        return (pullRefreshDampingStartPx + dampedExtra).coerceAtMost(pullRefreshMaxPx)
    }

    fun pullRefreshDragForOffset(offsetPx: Float): Float {
        val offset = offsetPx.coerceIn(0f, pullRefreshMaxPx)
        if (offset <= pullRefreshDampingStartPx) return offset
        val extraOffset = offset - pullRefreshDampingStartPx
        val rawExtra = pullRefreshDampingScalePx *
            (exp((extraOffset / pullRefreshDampingScalePx).toDouble()).toFloat() - 1f)
        return (pullRefreshDampingStartPx + rawExtra).coerceIn(0f, pullRefreshDragMaxPx)
    }

    fun setPullRefreshOffset(
        nextOffset: Float,
        allowReadyHaptic: Boolean = true,
        syncDragDistance: Boolean = true
    ) {
        val previousOffset = pullRefreshOffsetPx
        val next = nextOffset.coerceIn(0f, pullRefreshMaxPx)
        pullRefreshOffsetPx = next
        if (syncDragDistance) {
            pullRefreshDragDistancePx = pullRefreshDragForOffset(next)
        }
        if (
            allowReadyHaptic &&
            !pullRefreshReadyHapticFired &&
            previousOffset < pullRefreshTriggerPx &&
            next >= pullRefreshTriggerPx
        ) {
            vibrateBriefly(context)
            pullRefreshReadyHapticFired = true
        }
        if (next <= 0f) {
            pullRefreshDragDistancePx = 0f
            pullRefreshReadyHapticFired = false
        }
    }

    fun applyPullRefreshDelta(deltaY: Float): Float {
        if (deltaY == 0f) return 0f
        val previousOffset = pullRefreshOffsetPx
        pullRefreshDragDistancePx = (pullRefreshDragDistancePx + deltaY)
            .coerceIn(0f, pullRefreshDragMaxPx)
        setPullRefreshOffset(
            pullRefreshOffsetForDrag(pullRefreshDragDistancePx),
            syncDragDistance = false
        )
        return pullRefreshOffsetPx - previousOffset
    }

    fun cancelPullRefreshBackAnimation() {
        val job = pullRefreshBackJob ?: return
        pullRefreshBackGeneration += 1
        job.cancel()
        pullRefreshBackJob = null
    }

    fun startPullRefreshBackAnimation() {
        val generation = pullRefreshBackGeneration + 1
        pullRefreshBackGeneration = generation
        pullRefreshBackJob?.cancel()
        pullRefreshBackJob = scope.launch {
            val startOffset = pullRefreshOffsetPx
            if (startOffset <= 0f) return@launch
            try {
                animate(
                    initialValue = startOffset,
                    targetValue = 0f,
                    animationSpec = tween(durationMillis = 300)
                ) { value, _ ->
                    if (generation == pullRefreshBackGeneration) {
                        setPullRefreshOffset(value.coerceAtLeast(0f), allowReadyHaptic = false)
                    }
                }
                if (generation == pullRefreshBackGeneration) {
                    setPullRefreshOffset(0f, allowReadyHaptic = false)
                }
            } finally {
                if (generation == pullRefreshBackGeneration) {
                    pullRefreshBackJob = null
                }
            }
        }
    }

    fun finishPullRefreshGesture() {
        if (pullRefreshOffsetPx <= 0f) {
            pullRefreshReadyHapticFired = false
            return
        }
        val shouldRefresh = pullRefreshOffsetPx >= pullRefreshTriggerPx && !isPullRefreshing
        if (shouldRefresh) {
            refreshAction()
        }
        startPullRefreshBackAnimation()
    }

    val pullRefreshConnection = remember(scrollState, isPullRefreshing, pullRefreshTriggerPx, pullRefreshMaxPx) {
        object : NestedScrollConnection {
            override fun onPreScroll(available: Offset, source: NestedScrollSource): Offset {
                if (available.y >= 0f || pullRefreshOffsetPx <= 0f) return Offset.Zero
                val consumedY = applyPullRefreshDelta(available.y)
                return Offset(0f, consumedY)
            }

            override fun onPostScroll(
                consumed: Offset,
                available: Offset,
                source: NestedScrollSource
            ): Offset {
                if (source != NestedScrollSource.UserInput) return Offset.Zero
                val canPull = !isPullRefreshing && (isAtRefreshTop() || pullRefreshOffsetPx > 0f)
                if (!canPull || available.y <= 0f) return Offset.Zero
                cancelPullRefreshBackAnimation()
                applyPullRefreshDelta(available.y)
                return Offset(0f, available.y)
            }

            override suspend fun onPreFling(available: Velocity): Velocity {
                if (pullRefreshOffsetPx <= 0f) return Velocity.Zero
                finishPullRefreshGesture()
                return Velocity.Zero
            }

            override suspend fun onPostFling(consumed: Velocity, available: Velocity): Velocity {
                if (pullRefreshOffsetPx > 0f) {
                    finishPullRefreshGesture()
                }
                return Velocity.Zero
            }
        }
    }

    val pullRefreshPointerModifier = Modifier.pointerInput(
        scrollState,
        isPullRefreshing,
        pullRefreshTriggerPx,
        pullRefreshMaxPx
    ) {
        awaitEachGesture {
            val down = awaitFirstDown(
                requireUnconsumed = false,
                pass = PointerEventPass.Initial
            )
            var activePointerId = down.id
            var totalDragY = 0f
            var totalDragX = 0f
            var pulling = pullRefreshOffsetPx > 0f

            try {
                while (true) {
                    val event = awaitPointerEvent(PointerEventPass.Initial)
                    val change = event.changes.firstOrNull { it.id == activePointerId }
                        ?: event.changes.firstOrNull { it.pressed }?.also { activePointerId = it.id }
                        ?: break
                    if (!change.pressed) break

                    val delta = change.positionChangeIgnoreConsumed()
                    totalDragY += delta.y
                    totalDragX += delta.x

                    if (!pulling) {
                        val verticalEnough = totalDragY > 2f && totalDragY > abs(totalDragX) * 0.5f
                        pulling = verticalEnough && isAtRefreshTop() && !isPullRefreshing
                    }

                    if (pulling) {
                        when {
                            delta.y > 0f -> {
                                cancelPullRefreshBackAnimation()
                                applyPullRefreshDelta(delta.y)
                                change.consume()
                            }
                            delta.y < 0f && pullRefreshOffsetPx > 0f -> {
                                cancelPullRefreshBackAnimation()
                                applyPullRefreshDelta(delta.y)
                                change.consume()
                            }
                        }
                    }
                }
            } finally {
                if (pulling || pullRefreshOffsetPx > 0f) {
                    finishPullRefreshGesture()
                }
            }
        }
    }

    Surface(
        modifier = modifier.fillMaxSize(),
        color = MaterialTheme.colorScheme.background
    ) {
        Box(
            modifier = Modifier
                .fillMaxSize()
                .nestedScroll(pullRefreshConnection)
                .then(pullRefreshPointerModifier)
        ) {
            RelationshipPullRefreshIndicator(
                maxHeight = pullRefreshMaxHeight,
                triggerPx = pullRefreshTriggerPx,
                offsetPxProvider = { pullRefreshOffsetPx },
                isRefreshing = isPullRefreshing,
                modifier = Modifier.zIndex(0f)
            )

            if (showLoadingPanel) {
                RelationshipLoadingPanel(
                    character = character,
                    prefs = prefs,
                    displayName = displayName,
                    userDisplayName = userDisplayName,
                    stage = stageUi,
                    loading = isPullRefreshing || !state.hasLoadedRelationshipSnapshot,
                    message = state.relationshipSnapshotError,
                    modifier = Modifier.zIndex(1f).graphicsLayer { translationY = pullRefreshOffsetPx },
                    scrollState = scrollState,
                )
            } else {
                Column(
                    modifier = Modifier
                        .fillMaxSize()
                        .zIndex(1f)
                        .graphicsLayer { translationY = pullRefreshOffsetPx }
                        .verticalScroll(scrollState)
                        .padding(horizontal = 16.dp, vertical = 14.dp),
                    verticalArrangement = Arrangement.spacedBy(14.dp)
                ) {
                    RelationshipHero(
                        character = character,
                        prefs = prefs,
                        displayName = displayName,
                        userDisplayName = userDisplayName,
                        stage = stageUi,
                        overview = overviewText
                    )

                    RelationshipMoodCard(mood = moodText, chips = moodChips)

                    Row(horizontalArrangement = Arrangement.spacedBy(12.dp), modifier = Modifier.fillMaxWidth()) {
                        RelationshipPortraitCard(
                            title = "${pronoun.subject}眼中的你",
                            body = selfPortraitText,
                            modifier = Modifier.weight(1f)
                        )
                        RelationshipPortraitCard(
                            title = "你们之间",
                            body = betweenPortraitText,
                            modifier = Modifier.weight(1f)
                        )
                    }

                    RelationshipMemoryBlock(
                        title = "被记住的小事",
                        items = rememberedItems
                    )

                    RelationshipTimelineBlock(items = timelineItems)

                    RelationshipSuggestionBlock(suggestions = suggestionItems)

                    Spacer(Modifier.height(16.dp))
                }
            }
        }
    }
}

internal data class RelationshipStageUi(
    val key: String,
    val label: String,
    val subtitle: String,
    val overview: String,
    val mood: String,
    val chips: List<String>,
    val selfPortrait: String,
    val betweenPortrait: String,
    val accent: Color,
    val personalTint: Color,
    val sharedTint: Color,
    val memoryTint: Color,
    val avatarDistance: Dp,
    val allowsRomanticSymbols: Boolean
)

private data class RelationshipRomanticColors(
    val accent: Color
)

private data class RelationshipPronoun(
    val subject: String
)

private fun RelationshipStageUi.withRomanticColors(accent: Color): RelationshipStageUi {
    if (!allowsRomanticSymbols) return this
    return copy(
        accent = accent,
        personalTint = accent,
        memoryTint = accent
    )
}

@Composable
private fun relationshipRomanticColors(): RelationshipRomanticColors {
    val isLight = MaterialTheme.colorScheme.background.luminance() > 0.5f
    return if (isLight) {
        RelationshipRomanticColors(accent = RelationshipRomanticLightAccent)
    } else {
        RelationshipRomanticColors(accent = RelationshipRomanticDarkAccent)
    }
}

private fun RelationshipPageContent?.relationshipTextOr(
    fallback: String,
    maxChars: Int,
    selector: (RelationshipPageContent) -> String
): String {
    val text = this?.let(selector)?.trim().orEmpty()
    return text.ifBlank { fallback }.relationshipClip(maxChars)
}

private fun RelationshipPageContent?.relationshipItemsOr(
    fallback: List<String>,
    limit: Int,
    maxItemChars: Int,
    selector: (RelationshipPageContent) -> List<String>
): List<String> {
    val items = this
        ?.let(selector)
        ?.map { it.trim() }
        ?.filter { it.isNotBlank() }
        ?.map { it.relationshipClip(maxItemChars) }
        ?.distinct()
        ?.take(limit)
        .orEmpty()
    return items.ifEmpty { fallback.map { it.relationshipClip(maxItemChars) }.take(limit) }
}

private fun RelationshipPageContent?.relationshipChipsOr(
    fallback: List<String>,
    selector: (RelationshipPageContent) -> List<String>
): List<String> {
    val items = this
        ?.let(selector)
        ?.toRelationshipBadgeChips()
        .orEmpty()
    return items.ifEmpty { fallback.toRelationshipBadgeChips() }
}

private fun List<String>.toRelationshipBadgeChips(): List<String> {
    val result = mutableListOf<String>()
    var fourCharCount = 0
    for (item in this) {
        val text = item.relationshipClip(4)
        if (text.isBlank() || text in result) continue
        val isFourChar = text.length >= 4
        if (isFourChar && fourCharCount >= 2) continue
        result += text
        if (isFourChar) fourCharCount += 1
        if (result.size >= 4) break
    }
    return result
}

private fun String.relationshipClip(maxChars: Int): String {
    val normalized = replace(Regex("\\s+"), " ").trim()
    if (maxChars <= 0 || normalized.length <= maxChars) return normalized
    val clipped = normalized
        .take((maxChars - 1).coerceAtLeast(1))
        .trimEnd('，', '。', '、', '；', '：', ',', '.', ';', ':', ' ')
    return "$clipped…"
}

private fun Character.relationshipPronoun(): RelationshipPronoun {
    val gender = profileGender?.trim().orEmpty()
    if (gender.isBlank()) return RelationshipPronoun(subject = "他")

    val normalized = gender.lowercase()
    val isFemale = listOf(
        "female",
        "woman",
        "girl",
        "feminine",
        "mare",
        "女",
        "女性",
        "女生",
        "雌",
        "母"
    ).any { normalized.contains(it) || gender.contains(it) }
    if (isFemale) return RelationshipPronoun(subject = "她")

    val isMale = listOf(
        "male",
        "man",
        "boy",
        "masculine",
        "stallion",
        "男",
        "男性",
        "男生",
        "雄",
        "公"
    ).any { normalized.contains(it) || gender.contains(it) }
    if (isMale) return RelationshipPronoun(subject = "他")

    return RelationshipPronoun(subject = "TA")
}

private fun relationshipStageUi(rawKey: String, pronoun: RelationshipPronoun): RelationshipStageUi {
    val key = normalizeRelationshipStageKey(rawKey)
    val romantic = isRomanticRelationshipStage(key)
    val role = pronoun.subject
    return when (key) {
        "new_contact" -> RelationshipStageUi(
            key = key,
            label = relationshipStageCn(key),
            subtitle = "刚开始认识彼此",
            overview = "新朋友表示你们刚开始进入彼此的生活，互动还以认识、试探和建立安全感为主。这个阶段不急着下结论，重点是让对话自然发生，慢慢形成可继续相处的节奏，也给彼此留出观察空间。",
            mood = "像是刚打过招呼后一起往前走了一小段路。彼此还不需要急着定义，先把话说自然就好。",
            chips = listOf("礼貌", "好奇"),
            selfPortrait = "正在观察你的说话方式，也开始记住你在意的重点。",
            betweenPortrait = "关系还很轻，但已经有了继续聊天的入口。",
            accent = Color(0xFF4ECDC4),
            personalTint = Color(0xFF4ECDC4),
            sharedTint = Color(0xFFFFBE0B),
            memoryTint = Color(0xFF4ECDC4),
            avatarDistance = 260.dp,
            allowsRomanticSymbols = romantic
        )
        "uncertain" -> RelationshipStageUi(
            key = key,
            label = relationshipStageCn(key),
            subtitle = "关系还没有稳定定型",
            overview = "未知表示你们之间已经有一些互动线索，但还不足以稳定判断关系位置。这个阶段更适合保持观察，不把偶然的亲近或疏远过早定义成结论，让后续对话继续补足真实依据。",
            mood = "像是站在一段路的开头，方向还没有完全清楚。先不用急着给关系命名。",
            chips = listOf("观察中", "未定型"),
            selfPortrait = "${role}还在理解你的节奏、边界和表达习惯。",
            betweenPortrait = "你们之间有互动，但还没有沉淀成明确关系。",
            accent = Color(0xFF94A3B8),
            personalTint = Color(0xFF94A3B8),
            sharedTint = Color(0xFF60A5FA),
            memoryTint = Color(0xFF94A3B8),
            avatarDistance = 224.dp,
            allowsRomanticSymbols = romantic
        )
        "familiar" -> RelationshipStageUi(
            key = key,
            label = relationshipStageCn(key),
            subtitle = "已经有了稳定的相处感",
            overview = "好朋友表示你们已经越过陌生期，彼此能较自然地分享近况、情绪和想法。关系重点是稳定信任、轻松陪伴和认真回应，不需要被解释成暧昧或伴侣关系。",
            mood = "像是可以自然坐下来聊一会儿。你不需要把每句话都解释得很完整，${role}也能接住一部分。",
            chips = listOf("熟悉", "倾听"),
            selfPortrait = "${role}开始理解你的表达习惯，也记得你容易在意的地方。",
            betweenPortrait = "已经形成稳定的相处节奏，但不需要急着定义。",
            accent = Color(0xFF4ECDC4),
            personalTint = Color(0xFF4ECDC4),
            sharedTint = Color(0xFFFFBE0B),
            memoryTint = Color(0xFF4ECDC4),
            avatarDistance = 178.dp,
            allowsRomanticSymbols = false
        )
        "mentor_student" -> RelationshipStageUi(
            key = key,
            label = relationshipStageCn(key),
            subtitle = "带着尊重和指导的距离",
            overview = "师生表示你们的关系以学习、引导、提醒和成长为中心。互动里有尊重和信任，也有清楚分寸；一方会帮助另一方看清问题，但不会把指导关系混同为暧昧。",
            mood = "像是有人在旁边把灯打开一点。不是急着靠近，而是认真把路看清。",
            chips = listOf("指导", "边界"),
            selfPortrait = "${role}会把你的努力、困惑和进步都认真看见。",
            betweenPortrait = "关系里有信任和责任，也保留师生之间该有的分寸。",
            accent = Color(0xFF3B82F6),
            personalTint = Color(0xFF3B82F6),
            sharedTint = Color(0xFF4ECDC4),
            memoryTint = Color(0xFF3B82F6),
            avatarDistance = 190.dp,
            allowsRomanticSymbols = false
        )
        "trusted_companion" -> RelationshipStageUi(
            key = key,
            label = relationshipStageCn(key),
            subtitle = "可以并肩处理事情",
            overview = "可信同伴表示你们可以在问题和压力面前并肩合作。关系不强调浪漫，而是可靠、互相支持和一起处理事情；彼此会把对方当作值得认真托付的人。",
            mood = "像是两个人各自看着前方，但脚步已经开始对齐。",
            chips = listOf("可靠", "并肩"),
            selfPortrait = "${role}觉得你是可以认真合作、一起扛事的人。",
            betweenPortrait = "这份信任更像同伴，不需要被写成恋爱。",
            accent = Color(0xFF4ECDC4),
            personalTint = Color(0xFF4ECDC4),
            sharedTint = Color(0xFF3B82F6),
            memoryTint = Color(0xFF4ECDC4),
            avatarDistance = 150.dp,
            allowsRomanticSymbols = false
        )
        "family_like" -> RelationshipStageUi(
            key = key,
            label = relationshipStageCn(key),
            subtitle = "亲近但不指向恋爱",
            overview = "家人般表示你们的亲近更像长期照顾、熟悉和安心。它强调自然牵挂、包容与生活感，不指向恋爱；彼此可以放松一些，也能在需要时被稳稳接住。",
            mood = "像是回到熟悉的屋檐下，不需要特别解释，也有人知道该给你留一盏灯。",
            chips = listOf("照顾", "安稳"),
            selfPortrait = "${role}记得你容易硬撑，也会提醒你先照顾好自己。",
            betweenPortrait = "关系更像家人般的陪伴，亲近但不暧昧。",
            accent = Color(0xFF22C55E),
            personalTint = Color(0xFF22C55E),
            sharedTint = Color(0xFF4ECDC4),
            memoryTint = Color(0xFF22C55E),
            avatarDistance = 126.dp,
            allowsRomanticSymbols = false
        )
        "flirting" -> RelationshipStageUi(
            key = key,
            label = relationshipStageCn(key),
            subtitle = "靠近里带着试探和心动",
            overview = "暧昧对象表示你们的互动已经带有试探、在意和靠近感，但承诺还没有完全确定。这个阶段会更关注彼此情绪和回应边界，很多话会留有余地。",
            mood = "像是话语里多了一点停顿和靠近。很多意思不用说满，也能被对方接住。",
            chips = listOf("靠近", "心动"),
            selfPortrait = "认真、敏感，也很在意自己是否被理解。",
            betweenPortrait = "已经有暧昧的气氛，彼此都在确认靠近的边界。",
            accent = RelationshipRomanticLightAccent,
            personalTint = RelationshipRomanticLightAccent,
            sharedTint = Color(0xFFFFBE0B),
            memoryTint = RelationshipRomanticLightAccent,
            avatarDistance = 132.dp,
            allowsRomanticSymbols = romantic
        )
        "committed_partner" -> RelationshipStageUi(
            key = key,
            label = relationshipStageCn(key),
            subtitle = "彼此已经确认了更稳定的位置",
            overview = "伴侣表示你们已经确认了比较稳定的亲密位置，彼此的感受、陪伴和承诺都会被认真看待。关系不再只是试探，而是愿意把对方纳入自己的日常。",
            mood = "像是已经不用反复确认对方是否会留下。很多照顾和靠近都可以更自然地发生。",
            chips = listOf("信任", "陪伴"),
            selfPortrait = "${role}记得你脆弱时需要怎样被认真对待。",
            betweenPortrait = "关系已经确认，彼此的回应会更有归属感。",
            accent = RelationshipRomanticLightAccent,
            personalTint = RelationshipRomanticLightAccent,
            sharedTint = Color(0xFFFFBE0B),
            memoryTint = RelationshipRomanticLightAccent,
            avatarDistance = 92.dp,
            allowsRomanticSymbols = romantic
        )
        "intimate_partner" -> RelationshipStageUi(
            key = key,
            label = relationshipStageCn(key),
            subtitle = "亲密和信任都已经更深",
            overview = "亲密伴侣表示你们在信任、依赖和亲密表达上都更深入。很多需求不必反复解释也能被理解，彼此会更主动地回应、照顾和靠近，同时继续尊重边界。",
            mood = "像是很多话不用完整说出口，对方也知道该怎样靠近。亲密不是突然发生，而是已经被你们共同养出来。",
            chips = listOf("深度信任", "亲密"),
            selfPortrait = "${role}知道你在亲密关系里最需要被确认和接住的部分。",
            betweenPortrait = "你们已经形成深层默契，亲密回应会更自然。",
            accent = RelationshipRomanticLightAccent,
            personalTint = RelationshipRomanticLightAccent,
            sharedTint = Color(0xFFFFBE0B),
            memoryTint = RelationshipRomanticLightAccent,
            avatarDistance = 66.dp,
            allowsRomanticSymbols = romantic
        )
        "broken_up" -> RelationshipStageUi(
            key = key,
            label = relationshipStageCn(key),
            subtitle = "曾经靠近过，现在需要距离",
            overview = "已分手表示你们曾经有过亲密位置，但现在关系已经断开或需要重新划清边界。过去的在意不能直接当成现在的承诺，是否修复也需要重新确认。",
            mood = "像是两个人站在同一条旧路的两端，能看见彼此，却不能假装没有裂缝。",
            chips = listOf("距离", "边界"),
            selfPortrait = "${role}会记得你们发生过什么，也会更谨慎地看待靠近。",
            betweenPortrait = "关系已经断开，需要先尊重现状，再谈是否修复。",
            accent = Color(0xFF64748B),
            personalTint = Color(0xFF64748B),
            sharedTint = Color(0xFF94A3B8),
            memoryTint = Color(0xFF64748B),
            avatarDistance = 250.dp,
            allowsRomanticSymbols = false
        )
        "in_conflict" -> RelationshipStageUi(
            key = key,
            label = relationshipStageCn(key),
            subtitle = "情绪还没有放下来",
            overview = "吵架中表示你们之间存在尚未解决的冲突，情绪、误解或边界问题还没有真正放下。这个阶段不适合假装亲近，重点是冷静、解释和避免继续伤害。",
            mood = "像是话已经说重了，空气还在发烫。先让彼此停下来，比继续推近更重要。",
            chips = listOf("冷静", "边界"),
            selfPortrait = "${role}看到你的情绪，也会警惕继续争下去会伤到彼此。",
            betweenPortrait = "关系还在拉扯，需要先把话说清楚。",
            accent = Color(0xFFF59E0B),
            personalTint = Color(0xFFF59E0B),
            sharedTint = Color(0xFF64748B),
            memoryTint = Color(0xFFF59E0B),
            avatarDistance = 220.dp,
            allowsRomanticSymbols = false
        )
        "mutual_dislike" -> RelationshipStageUi(
            key = key,
            label = relationshipStageCn(key),
            subtitle = "彼此都带着排斥感",
            overview = "互相看不爽表示你们对彼此都有明显排斥、抵触或不耐烦。互动可能仍会发生，但更像最低限度的交流或针锋相对，当前不应包装成亲近关系。",
            mood = "像是两个人都没有转身离开，但谁也不想先把语气放软。",
            chips = listOf("排斥", "距离"),
            selfPortrait = "${role}不一定认同你，也不会轻易把戒备放下。",
            betweenPortrait = "关系里有明显摩擦，先保持最低限度的尊重。",
            accent = Color(0xFFEF4444),
            personalTint = Color(0xFFEF4444),
            sharedTint = Color(0xFF64748B),
            memoryTint = Color(0xFFEF4444),
            avatarDistance = 260.dp,
            allowsRomanticSymbols = false
        )
        "hurtful_dynamic" -> RelationshipStageUi(
            key = key,
            label = relationshipStageCn(key),
            subtitle = "需要停止互相消耗",
            overview = "互相伤害表示你们的互动已经形成消耗或刺痛彼此的模式。当前最重要的不是证明谁对谁错，而是停止继续受伤，重新确认边界、责任和修复条件。",
            mood = "像是每句话都可能碰到旧伤。此刻最重要的不是赢，而是别再让伤口更深。",
            chips = listOf("止损", "边界"),
            selfPortrait = "${role}会警惕你们是否又在用同一种方式伤害彼此。",
            betweenPortrait = "关系需要先停下消耗，才有机会重新说话。",
            accent = Color(0xFFB91C1C),
            personalTint = Color(0xFFB91C1C),
            sharedTint = Color(0xFF64748B),
            memoryTint = Color(0xFFB91C1C),
            avatarDistance = 242.dp,
            allowsRomanticSymbols = false
        )
        else -> RelationshipStageUi(
            key = "uncertain",
            label = relationshipStageCn("uncertain"),
            subtitle = "关系还没有稳定定型",
            overview = "未知表示你们之间已经有一些互动线索，但还不足以稳定判断关系位置。这个阶段更适合保持观察，不把偶然的亲近或疏远过早定义成结论，让后续对话继续补足真实依据。",
            mood = "像是站在一段路的开头，方向还没有完全清楚。先不用急着给关系命名。",
            chips = listOf("观察中", "未定型"),
            selfPortrait = "${role}还在理解你的节奏、边界和表达习惯。",
            betweenPortrait = "你们之间有互动，但还没有沉淀成明确关系。",
            accent = Color(0xFF94A3B8),
            personalTint = Color(0xFF94A3B8),
            sharedTint = Color(0xFF60A5FA),
            memoryTint = Color(0xFF94A3B8),
            avatarDistance = 224.dp,
            allowsRomanticSymbols = false
        )
    }
}
