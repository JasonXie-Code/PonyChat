package top.ponychat.webview.ui.doudizhu

import android.media.AudioManager
import android.os.Build
import android.os.Bundle
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.zIndex
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlin.random.Random
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.ui.common.PonyAvatar
import top.ponychat.webview.ui.common.SystemNavigationBarColorEffect
import top.ponychat.webview.ui.theme.PonyChatTheme

class DoudizhuActivity : ComponentActivity() {
    private lateinit var sfxPlayer: DoudizhuSfxPlayer

    companion object {
        const val EXTRA_CHARACTER_NAME = "character_name"
        const val EXTRA_CHARACTER_AVATAR = "character_avatar"
        const val EXTRA_CHARACTER_ID = "character_id"
        const val EXTRA_CONVERSATION_ID = "conversation_id"
        const val EXTRA_USERNAME = "username"
        const val EXTRA_USER_NAME = "user_name"
        const val EXTRA_USER_AVATAR = "user_avatar"
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        volumeControlStream = AudioManager.STREAM_MUSIC
        sfxPlayer = DoudizhuSfxPlayer(this)
        val prefs = AppPreferences(this)
        val characterName = intent.getStringExtra(EXTRA_CHARACTER_NAME)
            ?.takeIf { it.isNotBlank() }
            ?: "角色"
        val characterAvatar = intent.getStringExtra(EXTRA_CHARACTER_AVATAR).orEmpty()
        val userName = intent.getStringExtra(EXTRA_USER_NAME)
            ?.takeIf { it.isNotBlank() }
            ?: prefs.nickname.ifBlank { prefs.username }.ifBlank { "我" }
        val userAvatar = intent.getStringExtra(EXTRA_USER_AVATAR)
            ?.takeIf { it.isNotBlank() }
            ?: prefs.avatar
        val apiBase = prefs.effectiveApiBase()
        WindowCompat.setDecorFitsSystemWindows(window, false)
        window.statusBarColor = android.graphics.Color.TRANSPARENT
        window.setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_NOTHING)
        enableEdgeToEdge()
        setContent {
            PonyChatTheme(darkTheme = prefs.isDarkTheme, fontScale = prefs.fontScale) {
                val systemBarColor = doudizhuWoodDark()
                val useDarkSystemIcons = systemBarColor.luminance() > 0.5f
                SideEffect {
                    val w = this@DoudizhuActivity.window
                    val controller = WindowCompat.getInsetsController(w, w.decorView)
                    controller.isAppearanceLightStatusBars = useDarkSystemIcons
                    enterImmersiveMode()
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                        w.isStatusBarContrastEnforced = false
                    }
                }
                SystemNavigationBarColorEffect(
                    color = systemBarColor,
                    useDarkIcons = useDarkSystemIcons,
                    restoreOnDispose = true
                )
                DoudizhuScreen(
                    characterName = characterName,
                    characterAvatar = characterAvatar,
                    userName = userName,
                    userAvatar = userAvatar,
                    apiBase = apiBase,
                    sfxPlayer = sfxPlayer,
                    onBack = { finish() }
                )
            }
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        if (::sfxPlayer.isInitialized) {
            sfxPlayer.release()
        }
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus) enterImmersiveMode()
    }

    private fun enterImmersiveMode() {
        WindowCompat.getInsetsController(window, window.decorView).apply {
            hide(WindowInsetsCompat.Type.systemBars())
            systemBarsBehavior = WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
        }
    }
}

@Composable
private fun DoudizhuScreen(
    characterName: String,
    characterAvatar: String,
    userName: String,
    userAvatar: String,
    apiBase: String,
    sfxPlayer: DoudizhuSfxPlayer,
    onBack: () -> Unit
) {
    val random = remember { Random(System.nanoTime()) }
    var shuffleMode by remember { mutableStateOf(DdzShuffleMode.Regular) }
    var game by remember { mutableStateOf(doudizhuNewGame(random = random, shuffleMode = shuffleMode)) }
    var selectedIds by remember { mutableStateOf<Set<Int>>(emptySet()) }
    var aiThinkingSeat by remember { mutableStateOf<DdzSeat?>(null) }
    var actionSecondsLeft by remember { mutableStateOf(DDZ_BIDDING_SECONDS) }
    var hintCycleSignature by remember { mutableStateOf("") }
    var hintCycleIndex by remember { mutableStateOf(0) }
    var dealtCardCount by remember { mutableStateOf(0) }
    var dealFlyingCardId by remember { mutableStateOf<Int?>(null) }
    var dealFlyingProgress by remember { mutableStateOf(1f) }
    var dealSortProgress by remember { mutableStateOf(1f) }
    var landlordIntro by remember { mutableStateOf<DdzLandlordIntroState?>(null) }
    var landlordInsertProgress by remember { mutableStateOf(1f) }
    var landlordSortProgress by remember { mutableStateOf(1f) }
    var landlordIntroCompletedRound by remember { mutableStateOf(-1) }

    val dealFinished = game.phase != DdzPhase.Bidding ||
        (dealtCardCount >= DDZ_DEAL_CARD_TOTAL && dealSortProgress >= 1f)
    val landlordIntroPending = game.phase == DdzPhase.Playing &&
        game.landlord != null &&
        game.lastPlay == null &&
        game.tablePlays.isEmpty() &&
        landlordIntroCompletedRound != game.round
    val actionsEnabled = dealFinished && !landlordIntroPending

    fun resetHintCycle() {
        hintCycleSignature = ""
        hintCycleIndex = 0
    }

    fun toggleShuffleModeAndRestart() {
        val nextMode = if (shuffleMode == DdzShuffleMode.Regular) {
            DdzShuffleMode.Firepower
        } else {
            DdzShuffleMode.Regular
        }
        shuffleMode = nextMode
        aiThinkingSeat = null
        landlordIntro = null
        selectedIds = emptySet()
        resetHintCycle()
        game = game.restartRound(random = random, shuffleMode = nextMode)
    }

    LaunchedEffect(game.phase, game.turn, game.hands, game.activeCombo, actionsEnabled) {
        if (!actionsEnabled || game.phase != DdzPhase.Playing || game.turn == DdzSeat.User || game.winner != null) {
            aiThinkingSeat = null
            return@LaunchedEffect
        }
        aiThinkingSeat = game.turn
        delay(620L)
        val current = game
        val seat = current.turn
        val next = current.playAiTurn(random)
        sfxPlayer.playCardsIfHandShrank(current, next, seat)
        game = next
        aiThinkingSeat = null
    }

    LaunchedEffect(game.phase, game.round, game.hands, game.bottomCards) {
        if (game.phase != DdzPhase.Bidding) {
            dealtCardCount = DDZ_DEAL_CARD_TOTAL
            dealFlyingCardId = null
            dealFlyingProgress = 1f
            dealSortProgress = 1f
            return@LaunchedEffect
        }
        landlordIntroCompletedRound = -1
        dealtCardCount = 0
        dealFlyingCardId = null
        dealFlyingProgress = 1f
        dealSortProgress = 0f
        sfxPlayer.awaitReady()
        val cardDelay = DDZ_INITIAL_DEAL_DURATION_MS / DDZ_DEAL_CARD_TOTAL / DDZ_DEAL_FLY_FRAME_COUNT
        repeat(DDZ_DEAL_CARD_TOTAL) { index ->
            val nextDealtCount = index + 1
            val seat = when (index % 3) {
                0 -> DdzSeat.User
                1 -> DdzSeat.Robot
                else -> DdzSeat.Character
            }
            val visibleCount = doudizhuDealVisibleCount(seat, nextDealtCount)
            dealFlyingCardId = game.dealtHand(seat).getOrNull(visibleCount - 1)?.id
            dealtCardCount = nextDealtCount
            dealFlyingProgress = 0f
            if (seat == DdzSeat.User) {
                sfxPlayer.playDeal()
            }
            repeat(DDZ_DEAL_FLY_FRAME_COUNT) { frame ->
                delay(cardDelay)
                dealFlyingProgress = (frame + 1).toFloat() / DDZ_DEAL_FLY_FRAME_COUNT
            }
        }
        dealFlyingCardId = null
        val sortDelay = DDZ_INITIAL_SORT_DURATION_MS / DDZ_ANIMATION_FRAME_COUNT
        repeat(DDZ_ANIMATION_FRAME_COUNT) { frame ->
            delay(sortDelay)
            dealSortProgress = (frame + 1).toFloat() / DDZ_ANIMATION_FRAME_COUNT
        }
    }

    LaunchedEffect(game.phase, game.landlord, game.round) {
        val landlord = game.landlord
        val shouldRunIntro = game.phase == DdzPhase.Playing &&
            landlord != null &&
            game.lastPlay == null &&
            game.tablePlays.isEmpty() &&
            landlordIntroCompletedRound != game.round
        if (!shouldRunIntro || landlord == null) {
            if (game.phase != DdzPhase.Playing) landlordIntro = null
            return@LaunchedEffect
        }
        landlordIntro = DdzLandlordIntroState(landlord, DdzLandlordIntroStage.Insert)
        landlordInsertProgress = 0f
        landlordSortProgress = 0f
        launch {
            sfxPlayer.awaitReady()
            repeat(game.bottomCards.size) { index ->
                if (index > 0) delay(DDZ_LANDLORD_DEAL_SOUND_INTERVAL_MS)
                sfxPlayer.playDeal()
            }
        }
        val insertDelay = DDZ_LANDLORD_INSERT_DURATION_MS / DDZ_ANIMATION_FRAME_COUNT
        repeat(DDZ_ANIMATION_FRAME_COUNT) { frame ->
            delay(insertDelay)
            landlordInsertProgress = (frame + 1).toFloat() / DDZ_ANIMATION_FRAME_COUNT
        }
        landlordIntro = DdzLandlordIntroState(landlord, DdzLandlordIntroStage.Sort)
        val sortDelay = DDZ_LANDLORD_SORT_DURATION_MS / DDZ_ANIMATION_FRAME_COUNT
        repeat(DDZ_ANIMATION_FRAME_COUNT) { frame ->
            delay(sortDelay)
            landlordSortProgress = (frame + 1).toFloat() / DDZ_ANIMATION_FRAME_COUNT
        }
        landlordIntro = null
        landlordIntroCompletedRound = game.round
    }

    LaunchedEffect(game.phase, game.turn, game.lastPlay, game.hand(DdzSeat.User), game.round, actionsEnabled) {
        if (!actionsEnabled) {
            actionSecondsLeft = 0
            return@LaunchedEffect
        }
        val seconds = when {
            game.phase == DdzPhase.Bidding -> DDZ_BIDDING_SECONDS
            game.phase == DdzPhase.Playing && game.turn == DdzSeat.User && game.winner == null -> DDZ_PLAY_SECONDS
            else -> 0
        }
        actionSecondsLeft = seconds
        if (seconds <= 0) return@LaunchedEffect
        repeat(seconds) { tick ->
            delay(1_000L)
            actionSecondsLeft = seconds - tick - 1
        }
        when {
            game.phase == DdzPhase.Bidding -> {
                selectedIds = emptySet()
                resetHintCycle()
                game = game.callLandlord(call = false, random = random)
            }
            game.phase == DdzPhase.Playing && game.turn == DdzSeat.User && game.winner == null -> {
                val hint = doudizhuHint(game.hand(DdzSeat.User), game.activeCombo)
                if (hint != null) {
                    val hintIds = hint.cards.map { it.id }.toSet()
                    selectedIds = emptySet()
                    resetHintCycle()
                    val current = game
                    val next = current.playUserCards(hintIds)
                    sfxPlayer.playCardsIfHandShrank(current, next, DdzSeat.User)
                    game = next
                } else {
                    selectedIds = emptySet()
                    resetHintCycle()
                    game = if (game.activeCombo != null) {
                        game.passUser()
                    } else {
                        game.copy(message = "没有可出的牌")
                    }
                }
            }
        }
    }

    val selectedCards = game.hand(DdzSeat.User).filter { it.id in selectedIds }
    val selectedCombo = doudizhuAnalyze(selectedCards)
    val canPlaySelection = selectedCombo != null && doudizhuCanBeat(selectedCombo, game.activeCombo)
    val displayMessage = when {
        game.phase == DdzPhase.Bidding && dealtCardCount < DDZ_DEAL_CARD_TOTAL -> "发牌中"
        game.phase == DdzPhase.Bidding && !dealFinished -> "整理手牌"
        else -> doudizhuPromptMessage(
            game = game,
            selectedCombo = selectedCombo,
            selectedCount = selectedIds.size,
            canPlaySelection = canPlaySelection,
            aiThinkingSeat = aiThinkingSeat,
            characterName = characterName,
            userName = userName
        )
    }

    BoxWithConstraints(
        modifier = Modifier
            .fillMaxSize()
            .background(doudizhuWoodDark())
    ) {
        val compact = maxHeight < 420.dp
        val handHeight = if (compact) 92.dp else 112.dp
        val handCardWidth = if (compact) 48.dp else 58.dp
        val handCardHeight = if (compact) 76.dp else 92.dp
        val actionBottom = handHeight + if (compact) 14.dp else 20.dp
        val roundOver = game.phase == DdzPhase.RoundOver
        val userPlayBottom = actionBottom
        val roundOverActionButtonHeight = if (compact) 42.dp else 48.dp
        val actionDockBottom = if (roundOver) {
            (userPlayBottom - roundOverActionButtonHeight) / 2f
        } else {
            actionBottom
        }
        val handSideReserve = if (compact) 110.dp else 132.dp
        val handMaxWidth = clampDp(
            value = maxWidth - (handSideReserve * 2),
            min = if (compact) 430.dp else 520.dp,
            max = maxWidth
        )
        val opponentSeatSide = if (compact) 64.dp else 76.dp
        val opponentSeatWidth = if (compact) 226.dp else 272.dp
        val opponentSeatHorizontalPadding = if (compact) 8.dp else 10.dp
        val opponentCountWidth = if (compact) 48.dp else 58.dp
        val opponentPlayWidth = if (compact) 312.dp else 408.dp
        val opponentCountCenterFromEdge = opponentSeatSide + opponentSeatWidth -
            opponentSeatHorizontalPadding - opponentCountWidth / 2f
        val opponentPlayOffsetFromEdge = opponentCountCenterFromEdge - opponentPlayWidth / 2f
        val userActionsVisible = game.phase == DdzPhase.Playing &&
            actionsEnabled &&
            game.turn == DdzSeat.User &&
            game.winner == null &&
            aiThinkingSeat == null
        val userPlayWidth = if (compact) 312.dp else 408.dp
        val activeLandlordIntro = landlordIntro ?: game.landlord
            ?.takeIf { landlordIntroPending }
            ?.let { DdzLandlordIntroState(it, DdzLandlordIntroStage.Insert) }
        val userLandlordIntroStage = activeLandlordIntro
            ?.takeIf { it.seat == DdzSeat.User }
            ?.stage
        val userOpeningSortActive = game.phase == DdzPhase.Bidding &&
            dealtCardCount >= DDZ_DEAL_CARD_TOTAL &&
            dealSortProgress < 1f
        val userCards = when {
            game.phase == DdzPhase.Bidding && dealtCardCount < DDZ_DEAL_CARD_TOTAL -> {
                game.dealtHand(DdzSeat.User).take(doudizhuDealVisibleCount(DdzSeat.User, dealtCardCount))
            }
            userOpeningSortActive -> game.hand(DdzSeat.User)
            userLandlordIntroStage != null -> {
                doudizhuLandlordIntroHand(game.hand(DdzSeat.User), game.bottomCards, userLandlordIntroStage)
            }
            else -> game.hand(DdzSeat.User)
        }
        val userHandCards = if (roundOver) emptyList() else userCards
        val userOpeningInsertedCardIds = if (game.phase == DdzPhase.Bidding && dealFlyingProgress < 1f) {
            setOfNotNull(dealFlyingCardId)
        } else {
            emptySet()
        }
        val userLandlordInsertedCardIds = if (userLandlordIntroStage == DdzLandlordIntroStage.Insert) {
            game.bottomCards.map { it.id }.toSet()
        } else {
            emptySet()
        }
        val userSortFromCards = when {
            userOpeningSortActive -> game.dealtHand(DdzSeat.User)
            userLandlordIntroStage == DdzLandlordIntroStage.Sort -> {
                doudizhuLandlordBaseHand(game.hand(DdzSeat.User), game.bottomCards) + game.bottomCards
            }
            else -> emptyList()
        }
        val userSortProgress = when {
            userOpeningSortActive -> dealSortProgress
            userLandlordIntroStage == DdzLandlordIntroStage.Sort -> landlordSortProgress
            else -> 1f
        }
        val userInsertProgress = when {
            userLandlordIntroStage == DdzLandlordIntroStage.Insert -> landlordInsertProgress
            userOpeningInsertedCardIds.isNotEmpty() -> dealFlyingProgress
            else -> 1f
        }

        fun displayedCardCount(seat: DdzSeat): Int {
            if (game.phase == DdzPhase.Bidding) {
                return doudizhuDealVisibleCount(seat, dealtCardCount)
            }
            val intro = activeLandlordIntro
            if (intro?.seat == seat) {
                return doudizhuLandlordIntroCount(
                    finalHand = game.hand(seat),
                    bottomCards = game.bottomCards,
                    stage = intro.stage,
                    insertProgress = landlordInsertProgress
                )
            }
            return game.hand(seat).size
        }

        DoudizhuWoodBackdrop()
        DoudizhuTopHud(
            game = game,
            userName = userName,
            characterName = characterName,
            shuffleMode = shuffleMode,
            onBack = onBack,
            onToggleShuffleMode = { toggleShuffleModeAndRestart() },
            onReset = {
                selectedIds = emptySet()
                resetHintCycle()
                game = game.resetMatch(random, shuffleMode)
            },
            modifier = Modifier
                .align(Alignment.TopStart)
                .fillMaxWidth()
                .padding(start = 14.dp, end = 14.dp, top = 6.dp)
        )
        DoudizhuBottomCards(
            game = game,
            compact = compact,
            modifier = Modifier
                .align(Alignment.TopCenter)
                .padding(top = if (compact) 8.dp else 12.dp)
        )
        DoudizhuOpponentSeat(
            seat = DdzSeat.Character,
            name = characterName,
            avatar = {
                PonyAvatar(
                    avatarUrl = characterAvatar,
                    name = characterName,
                    apiBase = apiBase,
                    size = if (compact) 46 else 54
                )
            },
            cardCount = displayedCardCount(DdzSeat.Character),
            score = game.score.characterWins,
            isLandlord = game.landlord == DdzSeat.Character,
            isTurn = game.turn == DdzSeat.Character && game.phase == DdzPhase.Playing,
            isThinking = aiThinkingSeat == DdzSeat.Character,
            isWinner = DdzSeat.Character in game.winners,
            reverse = false,
            compact = compact,
            modifier = Modifier
                .align(Alignment.TopStart)
                .padding(start = opponentSeatSide, top = if (compact) 54.dp else 62.dp)
                .width(opponentSeatWidth)
                .height(if (compact) 72.dp else 84.dp)
        )
        DoudizhuOpponentSeat(
            seat = DdzSeat.Robot,
            name = "机器人",
            avatar = { RobotAvatar(size = if (compact) 46.dp else 54.dp) },
            cardCount = displayedCardCount(DdzSeat.Robot),
            score = game.score.robotWins,
            isLandlord = game.landlord == DdzSeat.Robot,
            isTurn = game.turn == DdzSeat.Robot && game.phase == DdzPhase.Playing,
            isThinking = aiThinkingSeat == DdzSeat.Robot,
            isWinner = DdzSeat.Robot in game.winners,
            reverse = true,
            compact = compact,
            modifier = Modifier
                .align(Alignment.TopEnd)
                .padding(end = opponentSeatSide, top = if (compact) 54.dp else 62.dp)
                .width(opponentSeatWidth)
                .height(if (compact) 72.dp else 84.dp)
        )
        DoudizhuTableMessage(
            text = displayMessage,
            modifier = Modifier
                .align(Alignment.Center)
                .zIndex(30f)
                .offset(y = if (compact) (-64).dp else (-72).dp)
        )
        DoudizhuFloatingPlaySpot(
            play = when {
                roundOver && game.winner == DdzSeat.Character -> game.tablePlays[DdzSeat.Character]
                roundOver -> null
                else -> game.tablePlays[DdzSeat.Character]
            },
            revealedCards = if (roundOver && game.winner != DdzSeat.Character) game.hand(DdzSeat.Character) else emptyList(),
            compact = compact,
            centerContent = true,
            modifier = Modifier
                .align(Alignment.TopStart)
                .padding(start = opponentPlayOffsetFromEdge, top = if (compact) 150.dp else 180.dp)
                .width(opponentPlayWidth)
        )
        DoudizhuFloatingPlaySpot(
            play = when {
                roundOver && game.winner == DdzSeat.Robot -> game.tablePlays[DdzSeat.Robot]
                roundOver -> null
                else -> game.tablePlays[DdzSeat.Robot]
            },
            revealedCards = if (roundOver && game.winner != DdzSeat.Robot) game.hand(DdzSeat.Robot) else emptyList(),
            compact = compact,
            alignEnd = true,
            centerContent = true,
            modifier = Modifier
                .align(Alignment.TopEnd)
                .padding(end = opponentPlayOffsetFromEdge, top = if (compact) 150.dp else 180.dp)
                .width(opponentPlayWidth)
        )
        DoudizhuFloatingPlaySpot(
            play = when {
                userActionsVisible -> null
                roundOver && game.winner != DdzSeat.User -> null
                else -> game.tablePlays[DdzSeat.User]
            },
            revealedCards = if (roundOver && game.winner != DdzSeat.User) game.hand(DdzSeat.User) else emptyList(),
            compact = compact,
            centerContent = true,
            modifier = Modifier
                .align(Alignment.BottomCenter)
                .width(userPlayWidth)
                .padding(bottom = userPlayBottom)
        )
        DoudizhuActionDock(
            game = game,
            canPlaySelection = canPlaySelection,
            actionSecondsLeft = actionSecondsLeft,
            actionsEnabled = actionsEnabled,
            aiThinkingSeat = aiThinkingSeat,
            compact = compact,
            onCallLandlord = {
                if (actionsEnabled) {
                    selectedIds = emptySet()
                    resetHintCycle()
                    game = game.callLandlord(call = true, random = random)
                }
            },
            onPassLandlord = {
                if (actionsEnabled) {
                    selectedIds = emptySet()
                    resetHintCycle()
                    game = game.callLandlord(call = false, random = random)
                }
            },
            onHint = {
                if (actionsEnabled) {
                    val candidates = doudizhuHintCandidates(game.hand(DdzSeat.User), game.activeCombo)
                    if (candidates.isEmpty()) {
                        selectedIds = emptySet()
                        resetHintCycle()
                        game = game.copy(message = "没有更大的牌")
                    } else {
                        val signature = doudizhuHintCycleSignature(game.hand(DdzSeat.User), game.activeCombo)
                        val index = if (signature == hintCycleSignature) {
                            hintCycleIndex % candidates.size
                        } else {
                            0
                        }
                        selectedIds = candidates[index].cards.map { it.id }.toSet()
                        hintCycleSignature = signature
                        hintCycleIndex = (index + 1) % candidates.size
                    }
                }
            },
            onPlay = {
                if (actionsEnabled) {
                    val current = game
                    val next = current.playUserCards(selectedIds)
                    val played = next.lastPlay
                    if (played?.seat == DdzSeat.User && !played.pass) {
                        selectedIds = emptySet()
                        resetHintCycle()
                    }
                    sfxPlayer.playCardsIfHandShrank(current, next, DdzSeat.User)
                    game = next
                }
            },
            onPass = {
                if (actionsEnabled) {
                    selectedIds = emptySet()
                    resetHintCycle()
                    game = game.passUser()
                }
            },
            onNewRound = {
                selectedIds = emptySet()
                resetHintCycle()
                game = game.newRound(random, shuffleMode)
            },
            modifier = Modifier
                .align(Alignment.BottomCenter)
                .padding(bottom = actionDockBottom)
        )
        DoudizhuHumanBadge(
            userName = userName,
            userAvatar = userAvatar,
            apiBase = apiBase,
            cardCount = displayedCardCount(DdzSeat.User),
            score = game.score.userWins,
            isLandlord = game.landlord == DdzSeat.User,
            isTurn = game.turn == DdzSeat.User && game.phase == DdzPhase.Playing,
            isWinner = DdzSeat.User in game.winners,
            compact = compact,
            modifier = Modifier
                .align(Alignment.BottomStart)
                .padding(start = if (compact) 18.dp else 24.dp, bottom = if (compact) 10.dp else 14.dp)
        )
        DoudizhuHumanHand(
            cards = userHandCards,
            selectedIds = selectedIds,
            enabled = actionsEnabled && game.phase == DdzPhase.Playing && game.turn == DdzSeat.User && userHandCards.isNotEmpty(),
            cardWidth = handCardWidth,
            cardHeight = handCardHeight,
            maxExpandedWidth = handMaxWidth,
            insertedCardIds = userOpeningInsertedCardIds + userLandlordInsertedCardIds,
            insertProgress = userInsertProgress,
            insertFromTop = userLandlordIntroStage == DdzLandlordIntroStage.Insert,
            sortFromCards = userSortFromCards,
            sortProgress = userSortProgress,
            onToggleCard = { card ->
                resetHintCycle()
                selectedIds = if (card.id in selectedIds) {
                    selectedIds - card.id
                } else {
                    selectedIds + card.id
                }
            },
            onSetCardSelected = { card, selected ->
                resetHintCycle()
                selectedIds = if (selected) selectedIds + card.id else selectedIds - card.id
            },
            modifier = Modifier
                .align(Alignment.BottomCenter)
                .padding(
                    start = if (compact) 14.dp else 18.dp,
                    end = if (compact) 14.dp else 18.dp,
                    bottom = 6.dp
                )
                .height(handHeight)
                .fillMaxWidth()
        )
    }
}

private fun doudizhuPromptMessage(
    game: DdzGameState,
    selectedCombo: DdzCombo?,
    selectedCount: Int,
    canPlaySelection: Boolean,
    aiThinkingSeat: DdzSeat?,
    characterName: String,
    userName: String
): String {
    val selectedPrompt = when {
        selectedCount <= 0 -> null
        selectedCombo == null -> "未成牌型"
        game.phase == DdzPhase.Playing && !canPlaySelection -> {
            doudizhuBlockedPlayMessage(selectedCombo, game.activeCombo)
        }
        else -> selectedCombo.label
    }
    val thinkingPrompt = aiThinkingSeat?.let {
        "${doudizhuSeatTitle(it, characterName = characterName, userName = userName)}思考中"
    }
    val fallback = game.message
        .replace("角色", characterName.ifBlank { DdzSeat.Character.fallbackLabel })
        .replace("你", userName.ifBlank { DdzSeat.User.fallbackLabel })
    return selectedPrompt ?: thinkingPrompt ?: fallback
}

private const val DDZ_BIDDING_SECONDS = 10
private const val DDZ_PLAY_SECONDS = 15
private const val DDZ_LANDLORD_DEAL_SOUND_INTERVAL_MS = 200L

@Composable
private fun DoudizhuWoodBackdrop() {
    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(
                Brush.verticalGradient(
                    colors = listOf(
                        Color(0xFF6A2A16),
                        Color(0xFFA65D2A),
                        Color(0xFF8D421E),
                        Color(0xFF491A12)
                    )
                )
            )
    ) {
        Canvas(modifier = Modifier.fillMaxSize()) {
            val plankHeight = size.height / 7f
            for (i in 0..7) {
                val y = i * plankHeight
                drawLine(
                    color = Color(0xFF321008).copy(alpha = 0.32f),
                    start = Offset(0f, y),
                    end = Offset(size.width, y + 14f),
                    strokeWidth = 4f
                )
                drawLine(
                    color = Color(0xFFFFE6B2).copy(alpha = 0.10f),
                    start = Offset(0f, y + 4f),
                    end = Offset(size.width, y + 18f),
                    strokeWidth = 2f
                )
            }
            for (i in 0..16) {
                val y = (i + 1) * size.height / 18f
                val phase = if (i % 2 == 0) 28f else -34f
                drawLine(
                    color = Color(0xFF2B0F08).copy(alpha = 0.16f),
                    start = Offset(-80f, y),
                    end = Offset(size.width + 80f, y + phase),
                    strokeWidth = 2f
                )
            }
            drawRect(
                brush = Brush.radialGradient(
                    colors = listOf(
                        Color(0xFFFFD173).copy(alpha = 0.22f),
                        Color.Transparent
                    ),
                    center = Offset(size.width * 0.50f, size.height * 0.46f),
                    radius = size.width * 0.45f
                )
            )
            drawRect(color = Color.Black.copy(alpha = 0.18f))
        }
    }
}

@Composable
private fun DoudizhuTopHud(
    game: DdzGameState,
    userName: String,
    characterName: String,
    shuffleMode: DdzShuffleMode,
    onBack: () -> Unit,
    onToggleShuffleMode: () -> Unit,
    onReset: () -> Unit,
    modifier: Modifier = Modifier
) {
    Row(
        modifier = modifier.height(42.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        CircleIconButton(onClick = onBack) {
            Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回", tint = Color.White)
        }
        Spacer(modifier = Modifier.width(10.dp))
        Text(
            text = "斗地主",
            color = Color(0xFFFFE34E),
            fontWeight = FontWeight.Black,
            fontSize = 18.sp
        )
        Spacer(modifier = Modifier.width(10.dp))
        StatusChip(text = "第${game.round}局")
        Spacer(modifier = Modifier.width(8.dp))
        StatusChip(
            text = if (shuffleMode == DdzShuffleMode.Firepower) "火力" else "常规",
            onClick = onToggleShuffleMode
        )
        Spacer(modifier = Modifier.width(8.dp))
        StatusChip(
            text = when (game.phase) {
                DdzPhase.Bidding -> "叫地主"
                DdzPhase.Playing -> "出牌中"
                DdzPhase.RoundOver -> "结算"
            }
        )
        Spacer(modifier = Modifier.weight(1f))
        StatusChip(
            text = "${userName.ifBlank { "你" }} ${game.score.userWins}  ·  " +
                "${characterName.ifBlank { "角色" }} ${game.score.characterWins}  ·  " +
                "机器人 ${game.score.robotWins}"
        )
        Spacer(modifier = Modifier.width(10.dp))
        CircleIconButton(onClick = onReset) {
            Icon(Icons.Filled.Refresh, contentDescription = "重开", tint = Color.White)
        }
    }
}

@Composable
private fun CircleIconButton(
    onClick: () -> Unit,
    content: @Composable () -> Unit
) {
    Surface(
        color = Color.Black.copy(alpha = 0.42f),
        shape = CircleShape,
        border = BorderStroke(1.dp, Color(0xFFFFE6B2).copy(alpha = 0.34f)),
        modifier = Modifier.size(38.dp)
    ) {
        IconButton(onClick = onClick, modifier = Modifier.fillMaxSize()) {
            content()
        }
    }
}

@Composable
private fun StatusChip(text: String, onClick: (() -> Unit)? = null) {
    Surface(
        color = Color.Black.copy(alpha = 0.42f),
        shape = RoundedCornerShape(999.dp),
        border = BorderStroke(1.dp, Color(0xFFFFE6B2).copy(alpha = 0.26f)),
        modifier = if (onClick == null) Modifier else Modifier.clickable(onClick = onClick)
    ) {
        Text(
            text = text,
            color = Color(0xFFFFF7E0),
            fontSize = 12.sp,
            fontWeight = FontWeight.SemiBold,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.padding(horizontal = 10.dp, vertical = 6.dp)
        )
    }
}

@Composable
private fun DoudizhuBottomCards(
    game: DdzGameState,
    compact: Boolean,
    modifier: Modifier = Modifier
) {
    Column(
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(5.dp),
        modifier = modifier
    ) {
        Text(
            text = "底牌",
            color = Color(0xFFFFE34E),
            fontSize = 13.sp,
            fontWeight = FontWeight.Black
        )
        Row(horizontalArrangement = Arrangement.spacedBy(if (compact) 6.dp else 8.dp)) {
            doudizhuDisplayCards(game.bottomCards).forEach { card ->
                if (game.phase == DdzPhase.Bidding) {
                    DdzCardBack(
                        modifier = Modifier.size(
                            width = if (compact) 34.dp else 42.dp,
                            height = if (compact) 48.dp else 60.dp
                        )
                    )
                } else {
                    DdzCardFace(
                        card = card,
                        compact = true,
                        modifier = Modifier.size(
                            width = if (compact) 34.dp else 42.dp,
                            height = if (compact) 48.dp else 60.dp
                        )
                    )
                }
            }
        }
    }
}

@Composable
private fun DoudizhuTableMessage(text: String, modifier: Modifier = Modifier) {
    Surface(
        color = Color.Black.copy(alpha = 0.52f),
        shape = RoundedCornerShape(999.dp),
        border = BorderStroke(1.dp, Color(0xFFFFE6B2).copy(alpha = 0.28f)),
        modifier = modifier
    ) {
        Text(
            text = text,
            color = Color(0xFFFFF7E0),
            fontWeight = FontWeight.Black,
            fontSize = 16.sp,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.padding(horizontal = 22.dp, vertical = 8.dp)
        )
    }
}

@Composable
private fun DoudizhuFloatingPlaySpot(
    play: DdzPlay?,
    revealedCards: List<DdzCard> = emptyList(),
    compact: Boolean,
    alignEnd: Boolean = false,
    centerContent: Boolean = false,
    modifier: Modifier = Modifier
) {
    if (play == null && revealedCards.isEmpty()) return
    val cardWidth = if (compact) 48.dp else 58.dp
    val cardHeight = if (compact) 76.dp else 92.dp
    val maxWidth = if (compact) 312.dp else 408.dp
    Box(
        modifier = modifier.widthIn(min = 92.dp, max = maxWidth),
        contentAlignment = when {
            centerContent -> Alignment.Center
            alignEnd -> Alignment.CenterEnd
            else -> Alignment.CenterStart
        }
    ) {
        if (revealedCards.isNotEmpty()) {
            DoudizhuStackedTableCards(
                cards = revealedCards,
                compact = compact,
                cardWidth = cardWidth,
                cardHeight = cardHeight,
                maxWidth = maxWidth
            )
        } else if (play?.pass == true) {
            ActionWord(
                text = "不出",
                color = Color(0xFFB8FF7A),
                compact = compact
            )
        } else {
            DoudizhuStackedTableCards(
                cards = play?.cards.orEmpty(),
                compact = compact,
                cardWidth = cardWidth,
                cardHeight = cardHeight,
                maxWidth = maxWidth
            )
        }
    }
}

@Composable
private fun DoudizhuStackedTableCards(
    cards: List<DdzCard>,
    compact: Boolean,
    cardWidth: Dp,
    cardHeight: Dp,
    maxWidth: Dp
) {
    val minStep = if (compact) 8.dp else 10.dp
    val naturalStep = cardWidth - if (compact) 10.dp else 12.dp
    val step = if (cards.size <= 1) {
        naturalStep
    } else {
        val naturalWidth = cardWidth + naturalStep * (cards.size - 1)
        if (naturalWidth <= maxWidth) {
            naturalStep
        } else {
            clampDp((maxWidth - cardWidth) / (cards.size - 1).toFloat(), minStep, naturalStep)
        }
    }
    val gap = step - cardWidth
    Row(
        horizontalArrangement = Arrangement.spacedBy(gap),
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier.widthIn(max = maxWidth)
    ) {
        val orderedCards = doudizhuDisplayCards(cards)
        orderedCards.forEach { card ->
            DdzCardFace(
                card = card,
                modifier = Modifier.size(width = cardWidth, height = cardHeight)
            )
        }
    }
}

@Composable
private fun DoudizhuHumanBadge(
    userName: String,
    userAvatar: String,
    apiBase: String,
    cardCount: Int,
    score: Int,
    isLandlord: Boolean,
    isTurn: Boolean,
    isWinner: Boolean,
    compact: Boolean,
    modifier: Modifier = Modifier
) {
    val avatarFrameSize = if (compact) 44.dp else 52.dp
    val avatarSize = if (compact) 34 else 42
    Column(
        modifier = modifier,
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(2.dp)
    ) {
        Text(
            text = userName.ifBlank { "我" },
            color = Color(0xFFFFEA70),
            fontSize = if (compact) 10.sp else 12.sp,
            fontWeight = FontWeight.Black,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.widthIn(max = if (compact) 72.dp else 88.dp)
        )
        Surface(
            shape = RoundedCornerShape(7.dp),
            color = Color.Black.copy(alpha = 0.42f),
            border = BorderStroke(if (isTurn) 2.dp else 1.dp, if (isTurn) Color(0xFFFFD45A) else Color(0xFFFFE6B2).copy(alpha = 0.28f)),
            shadowElevation = if (isTurn) 8.dp else 2.dp
        ) {
            Box(
                modifier = Modifier
                    .size(avatarFrameSize)
                    .padding(3.dp),
                contentAlignment = Alignment.Center
            ) {
                PonyAvatar(
                    avatarUrl = userAvatar,
                    name = userName.ifBlank { "我" },
                    apiBase = apiBase,
                    size = avatarSize
                )
            }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(4.dp), verticalAlignment = Alignment.CenterVertically) {
            if (isLandlord) LandlordBadge()
            if (isWinner) WinnerBadge()
        }
        Text(
            text = "$cardCount 张 · 胜 $score",
            color = Color(0xFFFFF1D6).copy(alpha = 0.90f),
            fontSize = if (compact) 9.sp else 10.sp,
            fontWeight = FontWeight.SemiBold
        )
    }
}

@Composable
private fun DoudizhuHumanHand(
    cards: List<DdzCard>,
    selectedIds: Set<Int>,
    enabled: Boolean,
    cardWidth: Dp,
    cardHeight: Dp,
    maxExpandedWidth: Dp,
    insertedCardIds: Set<Int> = emptySet(),
    insertProgress: Float = 1f,
    insertFromTop: Boolean = false,
    sortFromCards: List<DdzCard> = emptyList(),
    sortProgress: Float = 1f,
    onToggleCard: (DdzCard) -> Unit,
    onSetCardSelected: (DdzCard, Boolean) -> Unit,
    modifier: Modifier = Modifier
) {
    BoxWithConstraints(modifier = modifier) {
        val density = LocalDensity.current
        val latestSelectedIds = rememberUpdatedState(selectedIds)
        val latestOnSetCardSelected = rememberUpdatedState(onSetCardSelected)
        val startPadding = 8.dp
        val endPadding = 14.dp
        val rowHorizontalPadding = 22.dp
        val baseStep = cardWidth - 8.dp
        val minStep = cardWidth * 0.36f
        val targetWidth = clampDp(maxExpandedWidth, cardWidth + rowHorizontalPadding, maxWidth)
        val naturalWidth = if (cards.isEmpty()) {
            0.dp
        } else {
            cardWidth + (baseStep * (cards.size - 1)) + rowHorizontalPadding
        }
        val minimumWidth = if (cards.isEmpty()) {
            0.dp
        } else {
            cardWidth + (minStep * (cards.size - 1)) + rowHorizontalPadding
        }
        val boundedWidth = when {
            cards.isEmpty() -> 0.dp
            naturalWidth <= targetWidth -> naturalWidth
            minimumWidth <= targetWidth -> targetWidth
            else -> clampDp(minimumWidth, cardWidth + rowHorizontalPadding, maxWidth)
        }
        val cardStep = if (cards.size <= 1) {
            baseStep
        } else {
            val rawStep = (boundedWidth - rowHorizontalPadding - cardWidth) / (cards.size - 1).toFloat()
            clampDp(rawStep, minStep, baseStep)
        }
        val horizontalGap = cardStep - cardWidth
        val rowWidth = if (cards.isEmpty()) {
            0.dp
        } else {
            cardWidth + (cardStep * (cards.size - 1)) + rowHorizontalPadding
        }
        val rowModifier = Modifier
            .align(Alignment.BottomCenter)
            .width(rowWidth)
        val sortFromIndexById = sortFromCards.mapIndexed { index, card -> card.id to index }.toMap()
        val startPaddingPx = with(density) { startPadding.toPx() }
        val cardWidthPx = with(density) { cardWidth.toPx() }
        val stepPx = with(density) { cardStep.toPx() }.coerceAtLeast(1f)
        val dragSelectModifier = if (enabled) {
            Modifier.pointerInput(cards, cardWidth, cardStep) {
                var targetSelected: Boolean? = null
                val touchedIds = mutableSetOf<Int>()

                fun cardAt(position: Offset): DdzCard? {
                    if (cards.isEmpty()) return null
                    val contentX = position.x - startPaddingPx
                    val lastCardEnd = (cards.lastIndex * stepPx) + cardWidthPx
                    if (contentX < 0f || contentX > lastCardEnd) return null
                    val index = (contentX / stepPx).toInt().coerceIn(0, cards.lastIndex)
                    return cards.getOrNull(index)
                }

                fun applySelectionAt(position: Offset) {
                    val card = cardAt(position) ?: return
                    if (!touchedIds.add(card.id)) return
                    val target = targetSelected ?: (card.id !in latestSelectedIds.value).also {
                        targetSelected = it
                    }
                    latestOnSetCardSelected.value(card, target)
                }

                detectDragGestures(
                    onDragStart = { position ->
                        targetSelected = null
                        touchedIds.clear()
                        applySelectionAt(position)
                    },
                    onDragCancel = {
                        targetSelected = null
                        touchedIds.clear()
                    },
                    onDragEnd = {
                        targetSelected = null
                        touchedIds.clear()
                    },
                    onDrag = { change, _ ->
                        change.consume()
                        applySelectionAt(change.position)
                    }
                )
            }
        } else {
            Modifier
        }

        Row(
            modifier = rowModifier
                .then(dragSelectModifier)
                .padding(start = startPadding, end = endPadding, top = 6.dp, bottom = 6.dp),
            horizontalArrangement = Arrangement.spacedBy(horizontalGap),
            verticalAlignment = Alignment.Bottom
        ) {
            cards.forEachIndexed { index, card ->
                val selected = card.id in selectedIds
                val insertRawProgress = insertProgress.coerceIn(0f, 1f)
                val insertMoveProgress = if (insertFromTop) (insertRawProgress / DDZ_LANDLORD_DROP_PROGRESS_FRACTION).coerceIn(0f, 1f) else insertRawProgress
                val insertRemaining = 1f - insertMoveProgress
                val insertAlpha = if (card.id in insertedCardIds && insertFromTop) (insertRawProgress / DDZ_LANDLORD_FADE_PROGRESS_FRACTION).coerceIn(0f, 1f) else 1f
                val insertOffsetX = if (card.id in insertedCardIds && insertRemaining > 0f && !insertFromTop) {
                    cardWidth * 2.4f * insertRemaining
                } else 0.dp
                val insertOffsetY = if (card.id in insertedCardIds && insertRemaining > 0f && insertFromTop) {
                    -cardHeight * 1.25f * insertRemaining
                } else 0.dp
                val sortOffset = sortFromIndexById[card.id]?.takeIf { sortProgress < 1f }?.let { oldIndex ->
                    cardStep * (oldIndex - index).toFloat() * (1f - sortProgress.coerceIn(0f, 1f))
                } ?: 0.dp
                DdzCardFace(
                    card = card,
                    selected = selected,
                    modifier = Modifier
                        .size(width = cardWidth, height = cardHeight)
                        .offset(
                            x = insertOffsetX + sortOffset,
                            y = insertOffsetY + if (selected) (-8).dp else 0.dp
                        )
                        .graphicsLayer(alpha = insertAlpha)
                        .clickable(enabled = enabled) { onToggleCard(card) }
                )
            }
        }
    }
}

@Composable
private fun DdzCardFace(
    card: DdzCard,
    modifier: Modifier = Modifier,
    selected: Boolean = false,
    compact: Boolean = false
) {
    val red = card.isRed
    val textColor = when {
        card.rank == DdzRank.BigJoker -> Color(0xFFE23E35)
        card.rank == DdzRank.SmallJoker -> Color(0xFF222222)
        red -> Color(0xFFD62E28)
        else -> Color(0xFF111111)
    }
    val isJoker = card.suit == DdzSuit.Joker
    val centerMarkSize = when {
        compact -> 8.dp
        else -> 16.dp
    }
    Surface(
        color = if (selected) Color(0xFFFFF4C7) else Color(0xFFFFFCF5),
        shape = RoundedCornerShape(if (compact) 5.dp else 7.dp),
        border = BorderStroke(1.dp, if (selected) Color(0xFFFFD13F) else Color(0xFF3A2A1F).copy(alpha = 0.35f)),
        shadowElevation = if (selected) 6.dp else 2.dp,
        modifier = modifier.shadow(if (selected) 6.dp else 2.dp, RoundedCornerShape(if (compact) 5.dp else 7.dp))
    ) {
        Box(modifier = Modifier.fillMaxSize()) {
            if (isJoker) {
                DdzJokerMark(
                    compact = compact,
                    color = textColor,
                    modifier = Modifier
                        .align(Alignment.CenterStart)
                        .padding(start = if (compact) 3.dp else 5.dp, top = if (compact) 2.dp else 4.dp, bottom = if (compact) 2.dp else 4.dp)
                )
            } else {
                Column(
                    modifier = Modifier
                        .align(Alignment.TopStart)
                        .padding(start = if (compact) 3.dp else 5.dp, top = if (compact) 2.dp else 4.dp),
                    horizontalAlignment = Alignment.CenterHorizontally
                ) {
                    Text(
                        text = card.rank.label,
                        color = textColor,
                        fontSize = when {
                            compact -> 12.sp
                            card.rank == DdzRank.Ten -> 18.sp
                            else -> 22.sp
                        },
                        fontWeight = FontWeight.Black,
                        lineHeight = if (compact) 12.sp else 20.sp,
                        maxLines = 1
                    )
                }
                DdzSuitMark(
                    suit = card.suit,
                    color = textColor.copy(alpha = 0.95f),
                    modifier = Modifier
                        .align(Alignment.Center)
                        .size(centerMarkSize)
                )
            }
        }
    }
}

@Composable
private fun DdzSuitMark(
    suit: DdzSuit,
    color: Color,
    modifier: Modifier = Modifier
) {
    Canvas(modifier = modifier) {
        drawSuitGlyph(suit, color)
    }
}

@Composable
private fun DdzJokerMark(
    compact: Boolean,
    color: Color,
    modifier: Modifier = Modifier
) {
    Column(
        modifier = modifier,
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        "JOKER".forEach { letter ->
            Text(
                text = letter.toString(),
                color = color,
                fontSize = if (compact) 6.sp else 9.sp,
                fontWeight = FontWeight.Black,
                lineHeight = if (compact) 6.sp else 9.sp,
                maxLines = 1
            )
        }
    }
}

private fun DrawScope.drawSuitGlyph(suit: DdzSuit, color: Color) {
    val w = size.width
    val h = size.height
    when (suit) {
        DdzSuit.Heart -> {
            drawCircle(color, radius = w * 0.23f, center = Offset(w * 0.32f, h * 0.32f))
            drawCircle(color, radius = w * 0.23f, center = Offset(w * 0.68f, h * 0.32f))
            val path = Path().apply {
                moveTo(w * 0.08f, h * 0.38f)
                lineTo(w * 0.50f, h * 0.94f)
                lineTo(w * 0.92f, h * 0.38f)
                close()
            }
            drawPath(path, color)
        }
        DdzSuit.Diamond -> {
            val path = Path().apply {
                moveTo(w * 0.50f, 0f)
                lineTo(w, h * 0.50f)
                lineTo(w * 0.50f, h)
                lineTo(0f, h * 0.50f)
                close()
            }
            drawPath(path, color)
        }
        DdzSuit.Club -> {
            drawCircle(color, radius = w * 0.22f, center = Offset(w * 0.50f, h * 0.28f))
            drawCircle(color, radius = w * 0.22f, center = Offset(w * 0.30f, h * 0.52f))
            drawCircle(color, radius = w * 0.22f, center = Offset(w * 0.70f, h * 0.52f))
            drawRect(
                color = color,
                topLeft = Offset(w * 0.44f, h * 0.56f),
                size = Size(w * 0.12f, h * 0.32f)
            )
            val base = Path().apply {
                moveTo(w * 0.32f, h)
                lineTo(w * 0.68f, h)
                lineTo(w * 0.56f, h * 0.82f)
                lineTo(w * 0.44f, h * 0.82f)
                close()
            }
            drawPath(base, color)
        }
        DdzSuit.Spade -> {
            val path = Path().apply {
                moveTo(w * 0.50f, h * 0.03f)
                cubicTo(w * 0.30f, h * 0.22f, w * 0.13f, h * 0.39f, w * 0.13f, h * 0.55f)
                cubicTo(w * 0.13f, h * 0.70f, w * 0.30f, h * 0.77f, w * 0.43f, h * 0.66f)
                cubicTo(w * 0.46f, h * 0.74f, w * 0.43f, h * 0.86f, w * 0.30f, h * 0.98f)
                lineTo(w * 0.70f, h * 0.98f)
                cubicTo(w * 0.57f, h * 0.86f, w * 0.54f, h * 0.74f, w * 0.57f, h * 0.66f)
                cubicTo(w * 0.70f, h * 0.77f, w * 0.87f, h * 0.70f, w * 0.87f, h * 0.55f)
                cubicTo(w * 0.87f, h * 0.39f, w * 0.70f, h * 0.22f, w * 0.50f, h * 0.03f)
                close()
            }
            drawPath(path, color)
        }
        DdzSuit.Joker -> Unit
    }
}

@Composable
internal fun DdzCardBack(modifier: Modifier = Modifier) {
    Surface(
        color = Color(0xFFD39A52),
        shape = RoundedCornerShape(7.dp),
        border = BorderStroke(1.dp, Color(0xFFFFE4A8).copy(alpha = 0.85f)),
        shadowElevation = 3.dp,
        modifier = modifier
    ) {
        Canvas(
            modifier = Modifier
                .fillMaxSize()
                .padding(5.dp)
        ) {
            val w = size.width
            val h = size.height
            drawRoundRect(
                color = Color(0xFFFFD88A).copy(alpha = 0.70f),
                size = Size(w, h),
                cornerRadius = CornerRadius(8f, 8f),
                style = Stroke(width = 2.2f)
            )
            drawCircle(
                color = Color(0xFF9E5F2A).copy(alpha = 0.28f),
                radius = minOf(w, h) * 0.33f,
                center = Offset(w / 2f, h / 2f),
                style = Stroke(width = 2.2f)
            )
            drawCircle(
                color = Color(0xFFFFE1A0).copy(alpha = 0.42f),
                radius = minOf(w, h) * 0.22f,
                center = Offset(w / 2f, h / 2f),
                style = Stroke(width = 1.6f)
            )
        }
    }
}

private fun doudizhuWoodDark(): Color = Color(0xFF6B281C)
