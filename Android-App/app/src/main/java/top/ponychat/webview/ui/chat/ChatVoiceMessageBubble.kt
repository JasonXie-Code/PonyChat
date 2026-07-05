package top.ponychat.webview.ui.chat

import android.util.Log
import android.Manifest
import android.app.Activity
import android.content.ClipData
import android.content.ClipboardManager
import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.media.MediaPlayer
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.Settings as AndroidSettings
import android.provider.MediaStore
import android.view.View
import android.view.ViewTreeObserver
import android.view.WindowManager
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.ImageDecoder
import android.util.Base64
import android.text.method.LinkMovementMethod
import android.util.TypedValue
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.*
import androidx.compose.animation.core.*
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.Image
import androidx.compose.foundation.gestures.animateScrollBy
import androidx.compose.foundation.gestures.scrollBy
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.gestures.draggable
import androidx.compose.foundation.gestures.rememberDraggableState
import androidx.compose.foundation.gestures.Orientation
import androidx.compose.foundation.gestures.rememberTransformableState
import androidx.compose.foundation.gestures.transformable
import androidx.compose.ui.input.nestedscroll.NestedScrollConnection
import androidx.compose.ui.input.nestedscroll.NestedScrollSource
import androidx.compose.ui.input.nestedscroll.nestedScroll
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.Velocity
import kotlinx.coroutines.withTimeoutOrNull
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.Chat
import androidx.compose.material.icons.automirrored.filled.Subject
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.material3.AssistChipDefaults
import androidx.compose.material3.TextFieldDefaults
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.pointer.PointerEventPass
import androidx.compose.ui.input.pointer.changedToDown
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.Density
import androidx.compose.ui.draw.BlurredEdgeTreatment
import androidx.compose.ui.draw.blur
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.layout.positionInWindow
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogWindowProvider
import androidx.compose.ui.window.DialogProperties
import androidx.compose.ui.window.Popup
import androidx.compose.ui.window.PopupPositionProvider
import androidx.compose.ui.unit.IntRect
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.zIndex
import androidx.core.content.ContextCompat
import androidx.core.graphics.drawable.toBitmap
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsAnimationCompat
import androidx.core.view.WindowInsetsCompat as ViewWindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import coil.compose.AsyncImagePainter
import coil.compose.rememberAsyncImagePainter
import coil.imageLoader
import coil.request.ImageRequest
import io.noties.markwon.Markwon
import io.noties.markwon.ext.strikethrough.StrikethroughPlugin
import io.noties.markwon.ext.tables.TablePlugin
import io.noties.markwon.linkify.LinkifyPlugin
import kotlin.math.max
import kotlin.math.min
import kotlin.math.pow
import kotlin.math.roundToInt
import kotlinx.coroutines.delay
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.FlowPreview
import kotlinx.coroutines.flow.debounce
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import top.ponychat.webview.BackendStreamingVoiceBridge
import top.ponychat.webview.CompanionService
import top.ponychat.webview.CustomToast
import top.ponychat.webview.audio.MobileVoiceEffect
import top.ponychat.webview.data.model.Character
import top.ponychat.webview.data.model.GalgameOptionItem
import top.ponychat.webview.data.model.ModelInfo
import top.ponychat.webview.data.model.Message
import top.ponychat.webview.data.model.MessageVoiceState
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.ui.character.CharacterAvatar
import top.ponychat.webview.ui.common.PonyAvatar
import top.ponychat.webview.ui.common.PonyPromptBubble
import top.ponychat.webview.ui.common.WheelStringColumn
import top.ponychat.webview.ui.common.adaptivePopupMenuBorder
import top.ponychat.webview.ui.common.adaptivePopupMenuContainerColor
import top.ponychat.webview.ui.common.adaptivePopupMenuContentColor
import top.ponychat.webview.ui.common.adaptivePopupMenuDangerColor
import top.ponychat.webview.ui.common.resolveAvatarUrlForApi
import top.ponychat.webview.ui.settings.CrisisHotlineDialog
import top.ponychat.webview.ui.theme.*
import top.ponychat.webview.util.ChatEventBus
import androidx.compose.ui.text.TextLayoutResult
import java.io.ByteArrayOutputStream
import java.io.File
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Date
import java.util.Locale


private fun estimatedVoiceDurationMs(text: String, explicitDurationMs: Long?): Long {
    explicitDurationMs?.takeIf { it > 0L }?.let { return it.coerceIn(VOICE_DURATION_MIN_MS, VOICE_DURATION_MAX_MS) }
    val nonBlankChars = text.count { !it.isWhitespace() }.coerceAtLeast(8)
    return (nonBlankChars * 210L).coerceIn(1_800L, VOICE_DURATION_MAX_MS)
}

private const val VOICE_DURATION_MIN_MS = 1_000L
private const val VOICE_DURATION_MAX_SECONDS = 60
private const val VOICE_DURATION_MAX_MS = VOICE_DURATION_MAX_SECONDS * 1_000L

private fun voiceDurationSeconds(durationMs: Long): Int {
    val safeDuration = durationMs.coerceIn(VOICE_DURATION_MIN_MS, VOICE_DURATION_MAX_MS)
    return ((safeDuration + 999L) / 1_000L).toInt().coerceIn(1, VOICE_DURATION_MAX_SECONDS)
}

private object ChatVoicePlaybackCoordinator {
    var currentOwner by mutableStateOf<String?>(null)
        private set
    var currentIsPlaying by mutableStateOf(false)
        private set
    var currentPositionMs by mutableLongStateOf(0L)
        private set

    private var currentDurationMs: Long = 0L
    private var currentFilePath: String? = null
    private var player: MediaPlayer? = null
    private var playbackEffects: MobileVoiceEffect.PlaybackEffects? = null
    private var simulatedStartedAtMs: Long = 0L
    private var simulatedStartPositionMs: Long = 0L

    fun start(owner: String, filePath: String?, durationMs: Long, startPositionMs: Long): Boolean {
        val safeDuration = durationMs.coerceIn(VOICE_DURATION_MIN_MS, VOICE_DURATION_MAX_MS)
        if (currentOwner != owner || currentFilePath != filePath) {
            releasePlayer()
        }
        currentOwner = owner
        currentFilePath = filePath
        currentDurationMs = safeDuration
        currentPositionMs = startPositionMs.coerceIn(0L, safeDuration).let { if (it >= safeDuration) 0L else it }
        if (filePath == null) {
            simulatedStartPositionMs = currentPositionMs
            simulatedStartedAtMs = System.currentTimeMillis()
            currentIsPlaying = true
            return true
        }
        val active = ensurePlayer(filePath, owner) ?: run {
            currentIsPlaying = false
            return false
        }
        return runCatching {
            active.seekTo(currentPositionMs.toInt().coerceIn(0, safeDuration.toInt()))
            active.start()
            currentIsPlaying = true
            true
        }.getOrElse {
            currentIsPlaying = false
            false
        }
    }

    fun pause(owner: String) {
        if (currentOwner != owner) return
        refreshPosition(owner)
        player?.let { active ->
            runCatching {
                if (active.isPlaying) active.pause()
            }
        }
        currentIsPlaying = false
    }

    fun seek(owner: String, positionMs: Long) {
        if (currentOwner != owner) return
        val duration = currentDurationMs.coerceAtLeast(VOICE_DURATION_MIN_MS)
        val next = positionMs.coerceIn(0L, duration)
        currentPositionMs = next
        if (currentFilePath == null) {
            simulatedStartPositionMs = next
            simulatedStartedAtMs = System.currentTimeMillis()
        } else {
            player?.let { active ->
                runCatching { active.seekTo(next.toInt().coerceIn(0, duration.toInt())) }
            }
        }
    }

    fun refreshPosition(owner: String): Long {
        if (currentOwner != owner) return 0L
        val duration = currentDurationMs.coerceAtLeast(VOICE_DURATION_MIN_MS)
        val next = currentFilePath?.let {
            player?.currentPosition?.toLong()
        } ?: if (currentIsPlaying) {
            simulatedStartPositionMs + (System.currentTimeMillis() - simulatedStartedAtMs)
        } else {
            currentPositionMs
        }
        currentPositionMs = (next ?: currentPositionMs).coerceIn(0L, duration)
        if (currentIsPlaying && currentPositionMs >= duration) {
            currentPositionMs = 0L
            currentIsPlaying = false
        }
        return currentPositionMs
    }

    fun isCurrent(owner: String): Boolean = currentOwner == owner

    fun stopAll() {
        releasePlayer()
        currentOwner = null
        currentFilePath = null
        currentDurationMs = 0L
        currentPositionMs = 0L
        currentIsPlaying = false
        simulatedStartedAtMs = 0L
        simulatedStartPositionMs = 0L
    }

    private fun ensurePlayer(filePath: String, owner: String): MediaPlayer? {
        player?.let { return it }
        return runCatching {
            MediaPlayer().apply {
                setDataSource(filePath)
                setOnCompletionListener {
                    if (currentOwner == owner) {
                        currentPositionMs = 0L
                        currentIsPlaying = false
                    }
                }
                prepare()
                playbackEffects = MobileVoiceEffect.attachTo(this)
            }
        }.getOrNull()?.also { player = it }
    }

    private fun releasePlayer() {
        playbackEffects?.release()
        playbackEffects = null
        player?.let { active ->
            runCatching {
                if (active.isPlaying) active.stop()
            }
            runCatching { active.release() }
        }
        player = null
    }
}

internal fun stopActiveChatVoicePlayback() {
    ChatVoicePlaybackCoordinator.stopAll()
}

private data class VoicePlaybackHandle(
    val isPlaying: Boolean,
    val isSeeking: Boolean,
    val playbackPositionMs: Long,
    val togglePlayback: () -> Unit,
    val seekToProgress: (Float) -> Unit,
    val beginSeek: () -> Unit,
    val endSeek: () -> Unit,
)

@Composable
private fun rememberVoicePlaybackHandle(
    messageId: String,
    voiceState: MessageVoiceState,
    durationMs: Long,
): VoicePlaybackHandle {
    val ownerKey = remember(messageId) { "chat_voice:$messageId" }
    val playableFile = remember(voiceState.localFile, voiceState.debugPlayable) {
        voiceState.localFile
            ?.takeIf { it.isNotBlank() && !voiceState.debugPlayable }
            ?.takeIf { File(it).exists() }
    }
    val safeDuration = durationMs.coerceIn(VOICE_DURATION_MIN_MS, VOICE_DURATION_MAX_MS)
    var isSeeking by remember(messageId) { mutableStateOf(false) }
    var seekPositionMs by remember(messageId) { mutableLongStateOf(0L) }
    var resumeAfterSeek by remember(messageId) { mutableStateOf(false) }

    val isCurrent = ChatVoicePlaybackCoordinator.currentOwner == ownerKey
    val isPlaying = isCurrent && ChatVoicePlaybackCoordinator.currentIsPlaying
    val playbackPositionMs = if (isSeeking) {
        seekPositionMs
    } else if (isCurrent) {
        ChatVoicePlaybackCoordinator.currentPositionMs
    } else {
        0L
    }

    fun seekTo(progress: Float) {
        val next = (safeDuration * progress.coerceIn(0f, 1f)).toLong().coerceIn(0L, safeDuration)
        seekPositionMs = next
        if (ChatVoicePlaybackCoordinator.isCurrent(ownerKey)) {
            ChatVoicePlaybackCoordinator.seek(ownerKey, next)
        }
    }

    fun startPlayback(startAtMs: Long = playbackPositionMs) {
        val startPosition = startAtMs.let { if (it >= safeDuration) 0L else it.coerceAtLeast(0L) }
        if (ChatVoicePlaybackCoordinator.start(ownerKey, playableFile, safeDuration, startPosition)) {
            seekPositionMs = 0L
        }
    }

    fun togglePlayback() {
        if (ChatVoicePlaybackCoordinator.isCurrent(ownerKey) && ChatVoicePlaybackCoordinator.currentIsPlaying) {
            ChatVoicePlaybackCoordinator.pause(ownerKey)
        } else {
            startPlayback(
                if (seekPositionMs > 0L) seekPositionMs
                else if (ChatVoicePlaybackCoordinator.isCurrent(ownerKey)) ChatVoicePlaybackCoordinator.currentPositionMs
                else 0L
            )
        }
    }

    LaunchedEffect(ownerKey, isCurrent, isPlaying, isSeeking, safeDuration) {
        while (
            ChatVoicePlaybackCoordinator.currentOwner == ownerKey &&
            ChatVoicePlaybackCoordinator.currentIsPlaying
        ) {
            if (!isSeeking) {
                ChatVoicePlaybackCoordinator.refreshPosition(ownerKey)
            }
            delay(40L)
        }
    }

    LaunchedEffect(ownerKey, ChatVoicePlaybackCoordinator.currentOwner) {
        if (ChatVoicePlaybackCoordinator.currentOwner != ownerKey && !isSeeking) {
            seekPositionMs = 0L
        }
    }

    return VoicePlaybackHandle(
        isPlaying = isPlaying,
        isSeeking = isSeeking,
        playbackPositionMs = playbackPositionMs,
        togglePlayback = { togglePlayback() },
        seekToProgress = { seekTo(it) },
        beginSeek = {
            resumeAfterSeek = ChatVoicePlaybackCoordinator.isCurrent(ownerKey) &&
                ChatVoicePlaybackCoordinator.currentIsPlaying
            seekPositionMs = if (ChatVoicePlaybackCoordinator.isCurrent(ownerKey)) {
                ChatVoicePlaybackCoordinator.refreshPosition(ownerKey)
            } else {
                0L
            }
            isSeeking = true
        },
        endSeek = {
            val next = seekPositionMs
            isSeeking = false
            if (ChatVoicePlaybackCoordinator.isCurrent(ownerKey)) {
                ChatVoicePlaybackCoordinator.seek(ownerKey, next)
            }
            if (resumeAfterSeek) {
                startPlayback(next)
            }
            resumeAfterSeek = false
        },
    )
}
@Composable
private fun VoiceDurationLabel(
    durationMs: Long,
    modifier: Modifier = Modifier,
    color: Color = MaterialTheme.colorScheme.onSurfaceVariant,
) {
    val totalSeconds = voiceDurationSeconds(durationMs)
    Row(
        modifier = modifier,
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(1.dp)
    ) {
        Text(
            text = totalSeconds.toString(),
            style = MaterialTheme.typography.labelMedium,
            fontWeight = FontWeight.SemiBold,
            color = color,
            maxLines = 1,
            softWrap = false
        )
        Text(
            text = "\"",
            style = MaterialTheme.typography.labelSmall,
            fontWeight = FontWeight.SemiBold,
            color = color,
            maxLines = 1,
            softWrap = false,
            modifier = Modifier.offset(y = (-5).dp)
        )
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
internal fun AssistantVoiceMessageBlock(
    message: Message,
    voiceState: MessageVoiceState,
    characterName: String,
    characterAvatarUrl: String,
    apiBase: String,
    showTimestamp: Boolean,
    timestampNow: Long,
    actionMenuTextColor: Color,
    actionMenuDeleteColor: Color,
    onNavigateToEditCharacter: () -> Unit,
    onMentionCharacter: (() -> Unit)?,
    onDelete: () -> Unit,
    onQuote: (() -> Unit)?,
    mode: String,
    onVoiceTranscriptLayout: ((Float) -> Unit)?,
    onVoiceTranscriptOpened: (() -> Unit)?,
    showTranscript: Boolean,
    onVoiceTranscriptVisibilityChange: (Boolean) -> Unit,
    onContextActionTriggered: () -> Unit,
) {
    val haptic = LocalHapticFeedback.current
    val clipboardManager = LocalClipboardManager.current
    val transcriptText = voiceState.readableText(message.content)
    val durationMs = remember(message.id, transcriptText, voiceState.durationMs) {
        estimatedVoiceDurationMs(transcriptText, voiceState.durationMs)
    }
    val playback = rememberVoicePlaybackHandle(
        messageId = message.messageId?.takeIf { it.isNotBlank() } ?: message.id,
        voiceState = voiceState,
        durationMs = durationMs
    )
    var showMenu by remember(message.id) { mutableStateOf(false) }
    var menuPosition by remember(message.id) { mutableStateOf(IntOffset.Zero) }
    var bubbleTopLeft by remember(message.id) { mutableStateOf(Offset.Zero) }
    var bubbleSize by remember(message.id) { mutableStateOf(IntSize.Zero) }
    var transcriptChars by remember(message.id, transcriptText) { mutableIntStateOf(if (showTranscript) transcriptText.length else 0) }
    var transcriptWasVisible by remember(message.id) { mutableStateOf(showTranscript) }

    LaunchedEffect(showTranscript, transcriptText, message.id) {
        if (!showTranscript) {
            transcriptChars = 0
            transcriptWasVisible = false
            return@LaunchedEffect
        }
        if (transcriptWasVisible) {
            transcriptChars = transcriptText.length
            return@LaunchedEffect
        }
        transcriptWasVisible = true
        transcriptChars = 0
        transcriptText.forEachIndexed { index, _ ->
            transcriptChars = index + 1
            delay(24L)
        }
    }

    Column {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier.padding(bottom = 4.dp, start = 48.dp),
        ) {
            Text(
                text = characterName,
                style = MaterialTheme.typography.labelSmall.copy(fontWeight = FontWeight.Medium),
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            if (showTimestamp) {
                Spacer(Modifier.width(8.dp))
                Text(
                    text = formatMessageTime(message.timestamp, timestampNow),
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.7f)
                )
            }
        }
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(end = 48.dp),
            verticalAlignment = Alignment.Top
        ) {
            val avatarModifier = if (mode == "normal" && onMentionCharacter != null) {
                Modifier.combinedClickable(
                    onClick = onNavigateToEditCharacter,
                    onLongClick = onMentionCharacter
                )
            } else {
                Modifier.clickable { onNavigateToEditCharacter() }
            }
            Box(modifier = avatarModifier) {
                PonyStyleAvatar(
                    avatarUrl = characterAvatarUrl,
                    name = characterName,
                    apiBase = apiBase,
                    size = 40
                )
            }
            Spacer(Modifier.width(8.dp))
            val durationSeconds = voiceDurationSeconds(durationMs)
            val minBubbleWidth = 112.dp
            val maxBubbleWidth = 260.dp
            Column(
                modifier = Modifier
                    .width(maxBubbleWidth)
                    .weight(1f, fill = false),
                verticalArrangement = Arrangement.spacedBy(6.dp)
            ) {
                val durationProgress = (durationSeconds - 1) / (VOICE_DURATION_MAX_SECONDS - 1).toFloat()
                val bubbleWidth = minBubbleWidth + (maxBubbleWidth - minBubbleWidth) * durationProgress
                val voiceAccent = Color(0xFF14B8A6)
                val bubbleColor = MaterialTheme.colorScheme.surfaceVariant
                val playbackProgress = (playback.playbackPositionMs.toFloat() / durationMs.toFloat()).coerceIn(0f, 1f)
                Surface(
                    modifier = Modifier
                        .width(bubbleWidth)
                        .height(44.dp)
                        .onGloballyPositioned { coords ->
                            bubbleTopLeft = coords.positionInWindow()
                            bubbleSize = coords.size
                        }
                        .combinedClickable(
                            onClick = playback.togglePlayback,
                            onLongClick = {
                                onContextActionTriggered()
                                haptic.performHapticFeedback(HapticFeedbackType.LongPress)
                                menuPosition = IntOffset(
                                    (bubbleTopLeft.x + bubbleSize.width / 2f).roundToInt(),
                                    (bubbleTopLeft.y + bubbleSize.height / 2f).roundToInt()
                                )
                                showMenu = true
                            }
                    ),
                    shape = RoundedCornerShape(topStart = 4.dp, topEnd = 18.dp, bottomStart = 18.dp, bottomEnd = 18.dp),
                    color = bubbleColor,
                    border = BorderStroke(1.dp, voiceAccent.copy(alpha = if (playback.isPlaying) 0.48f else 0.22f)),
                    shadowElevation = 1.dp,
                    tonalElevation = 0.dp
                ) {
                    Box(modifier = Modifier.fillMaxSize()) {
                        Row(
                            modifier = Modifier
                                .align(Alignment.CenterStart)
                                .fillMaxWidth()
                                .padding(start = 12.dp, end = 10.dp),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Icon(
                                imageVector = if (playback.isPlaying) Icons.Filled.PauseCircle else Icons.Filled.PlayCircle,
                                contentDescription = if (playback.isPlaying) "暂停语音" else "播放语音",
                                tint = voiceAccent,
                                modifier = Modifier.size(22.dp)
                            )
                            Spacer(Modifier.width(8.dp))
                            VoiceWaveBars(
                                progress = playbackProgress,
                                color = voiceAccent,
                                waveform = voiceState.waveform,
                                modifier = Modifier
                                    .weight(1f)
                                    .height(22.dp),
                                onTogglePlayback = playback.togglePlayback,
                                onLongPress = {
                                    onContextActionTriggered()
                                    haptic.performHapticFeedback(HapticFeedbackType.LongPress)
                                    menuPosition = IntOffset(
                                        (bubbleTopLeft.x + bubbleSize.width / 2f).roundToInt(),
                                        (bubbleTopLeft.y + bubbleSize.height / 2f).roundToInt()
                                    )
                                    showMenu = true
                                },
                                onSeek = playback.seekToProgress,
                                onSeekStart = playback.beginSeek,
                                onSeekEnd = playback.endSeek
                            )
                            Spacer(Modifier.width(10.dp))
                            VoiceDurationLabel(durationMs = durationMs)
                        }
                    }
                }
                FingerAnchoredDropdownMenu(
                    expanded = showMenu,
                    onDismissRequest = { showMenu = false },
                    positionInWindow = menuPosition
                ) {
                    DropdownMenuItem(
                        text = { Text(if (showTranscript) "隐藏文字" else "转文字", color = actionMenuTextColor) },
                        leadingIcon = { Icon(Icons.Filled.Subtitles, contentDescription = null, tint = actionMenuTextColor) },
                        onClick = {
                            showMenu = false
                            val nextShow = !showTranscript
                            onVoiceTranscriptVisibilityChange(nextShow)
                            if (nextShow) onVoiceTranscriptOpened?.invoke()
                        }
                    )
                    if (showTranscript && transcriptText.isNotBlank()) {
                        DropdownMenuItem(
                            text = { Text("复制", color = actionMenuTextColor) },
                            leadingIcon = { Icon(Icons.Filled.ContentCopy, contentDescription = null, tint = actionMenuTextColor) },
                            onClick = {
                                showMenu = false
                                clipboardManager.setText(AnnotatedString(transcriptText))
                            }
                        )
                    }
                    if (onQuote != null && mode == "normal") {
                        DropdownMenuItem(
                            text = { Text("引用", color = actionMenuTextColor) },
                            leadingIcon = { Icon(Icons.Filled.FormatQuote, contentDescription = null, tint = actionMenuTextColor) },
                            onClick = { showMenu = false; onQuote() }
                        )
                    }
                    DropdownMenuItem(
                        text = { Text("删除", color = actionMenuDeleteColor) },
                        leadingIcon = { Icon(Icons.Filled.Delete, contentDescription = null, tint = actionMenuDeleteColor) },
                        onClick = { showMenu = false; onDelete() }
                    )
                }
                AnimatedVisibility(
                    visible = showTranscript && transcriptText.isNotBlank(),
                    enter = expandVertically(tween(180)) + fadeIn(tween(180)),
                    exit = shrinkVertically(tween(140)) + fadeOut(tween(120))
                ) {
                    VoiceTextCard(
                        text = transcriptText.take(transcriptChars.coerceIn(0, transcriptText.length)),
                        accent = voiceAccent,
                        label = "识别结果",
                        modifier = Modifier
                            .fillMaxWidth()
                            .onGloballyPositioned { coords ->
                                onVoiceTranscriptLayout?.invoke(
                                    coords.positionInWindow().y + coords.size.height
                                )
                            }
                    )
                }
                voiceState.textFragments.filter { it.isNotBlank() }.forEach { fragment ->
                    VoiceTextCard(
                        text = fragment,
                        accent = MaterialTheme.colorScheme.primary.copy(alpha = 0.72f),
                        label = null,
                        modifier = Modifier.fillMaxWidth()
                    )
                }
                val error = voiceState.voiceError?.takeIf { it.isNotBlank() }
                if (error != null) {
                    Text(
                        text = error,
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.error.copy(alpha = 0.75f)
                    )
                }
            }
        }
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
internal fun UserVoiceMessageBubble(
    message: Message,
    voiceState: MessageVoiceState,
    actionMenuTextColor: Color,
    actionMenuDeleteColor: Color,
    isRetractable: Boolean,
    onRetract: (() -> Unit)?,
    onDelete: () -> Unit,
    onQuote: (() -> Unit)?,
    mode: String,
    onVoiceTranscriptLayout: ((Float) -> Unit)?,
    onVoiceTranscriptOpened: (() -> Unit)?,
    showTranscript: Boolean,
    onVoiceTranscriptVisibilityChange: (Boolean) -> Unit,
    onContextActionTriggered: () -> Unit,
) {
    val haptic = LocalHapticFeedback.current
    val clipboardManager = LocalClipboardManager.current
    val transcriptText = voiceState.readableText(message.content)
    val durationMs = remember(message.id, transcriptText, voiceState.durationMs) {
        estimatedVoiceDurationMs(transcriptText, voiceState.durationMs)
    }
    val playback = rememberVoicePlaybackHandle(
        messageId = message.messageId?.takeIf { it.isNotBlank() } ?: message.id,
        voiceState = voiceState,
        durationMs = durationMs
    )
    var showMenu by remember(message.id) { mutableStateOf(false) }
    var menuPosition by remember(message.id) { mutableStateOf(IntOffset.Zero) }
    var bubbleTopLeft by remember(message.id) { mutableStateOf(Offset.Zero) }
    var bubbleSize by remember(message.id) { mutableStateOf(IntSize.Zero) }
    var transcriptChars by remember(message.id, transcriptText) { mutableIntStateOf(if (showTranscript) transcriptText.length else 0) }
    var transcriptWasVisible by remember(message.id) { mutableStateOf(showTranscript) }

    LaunchedEffect(showTranscript, transcriptText, message.id) {
        if (!showTranscript) {
            transcriptChars = 0
            transcriptWasVisible = false
            return@LaunchedEffect
        }
        if (transcriptWasVisible) {
            transcriptChars = transcriptText.length
            return@LaunchedEffect
        }
        transcriptWasVisible = true
        transcriptChars = 0
        transcriptText.forEachIndexed { index, _ ->
            transcriptChars = index + 1
            delay(24L)
        }
    }

    val durationSeconds = voiceDurationSeconds(durationMs)
    val minBubbleWidth = 112.dp
    val maxBubbleWidth = 260.dp
    val durationProgress = (durationSeconds - 1) / (VOICE_DURATION_MAX_SECONDS - 1).toFloat()
    val bubbleWidth = minBubbleWidth + (maxBubbleWidth - minBubbleWidth) * durationProgress
    val userVoiceShape = RoundedCornerShape(topStart = 18.dp, topEnd = 4.dp, bottomStart = 18.dp, bottomEnd = 18.dp)
    val playbackProgress = (playback.playbackPositionMs.toFloat() / durationMs.toFloat()).coerceIn(0f, 1f)

    Column(
        modifier = Modifier.width(maxBubbleWidth),
        horizontalAlignment = Alignment.End,
        verticalArrangement = Arrangement.spacedBy(6.dp)
    ) {
        Box(
            modifier = Modifier
                .width(bubbleWidth)
                .height(44.dp)
                .shadow(4.dp, userVoiceShape, spotColor = Color(0xFF6366F1).copy(alpha = if (playback.isPlaying) 0.28f else 0.18f))
                .clip(userVoiceShape)
                .background(
                    Brush.linearGradient(
                        colors = if (playback.isPlaying) {
                            listOf(Color(0xFF4F46E5), Color(0xFF0F766E))
                        } else {
                            listOf(Color(0xFF6366F1), Color(0xFF4F46E5))
                        }
                    )
                )
                .border(1.dp, Color.White.copy(alpha = if (playback.isPlaying) 0.22f else 0.14f), userVoiceShape)
                .onGloballyPositioned { coords ->
                    bubbleTopLeft = coords.positionInWindow()
                    bubbleSize = coords.size
                }
                .combinedClickable(
                    onClick = playback.togglePlayback,
                    onLongClick = {
                        onContextActionTriggered()
                        haptic.performHapticFeedback(HapticFeedbackType.LongPress)
                        menuPosition = IntOffset(
                            (bubbleTopLeft.x + bubbleSize.width / 2f).roundToInt(),
                            (bubbleTopLeft.y + bubbleSize.height / 2f).roundToInt()
                        )
                        showMenu = true
                    }
                )
        ) {
            Row(
                modifier = Modifier
                    .align(Alignment.CenterStart)
                    .fillMaxWidth()
                    .padding(start = 12.dp, end = 10.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Icon(
                    imageVector = if (playback.isPlaying) Icons.Filled.PauseCircle else Icons.Filled.PlayCircle,
                    contentDescription = if (playback.isPlaying) "暂停语音" else "播放语音",
                    tint = Color.White,
                    modifier = Modifier.size(22.dp)
                )
                Spacer(Modifier.width(8.dp))
                VoiceWaveBars(
                    progress = playbackProgress,
                    color = Color.White,
                    waveform = voiceState.waveform,
                    modifier = Modifier
                        .weight(1f)
                    .height(22.dp),
                    onLongPress = {
                        onContextActionTriggered()
                        haptic.performHapticFeedback(HapticFeedbackType.LongPress)
                        menuPosition = IntOffset(
                            (bubbleTopLeft.x + bubbleSize.width / 2f).roundToInt(),
                            (bubbleTopLeft.y + bubbleSize.height / 2f).roundToInt()
                        )
                        showMenu = true
                    },
                    onTogglePlayback = playback.togglePlayback,
                    onSeek = playback.seekToProgress,
                    onSeekStart = playback.beginSeek,
                    onSeekEnd = playback.endSeek
                )
                Spacer(Modifier.width(10.dp))
                VoiceDurationLabel(
                    durationMs = durationMs,
                    color = Color.White.copy(alpha = 0.92f)
                )
            }
        }
        FingerAnchoredDropdownMenu(
            expanded = showMenu,
            onDismissRequest = { showMenu = false },
            positionInWindow = menuPosition
        ) {
            if (isRetractable && onRetract != null) {
                DropdownMenuItem(
                    text = { Text("撤回", color = actionMenuTextColor) },
                    leadingIcon = {
                        @Suppress("DEPRECATION")
                        Icon(Icons.Filled.Undo, contentDescription = null, tint = actionMenuTextColor)
                    },
                    onClick = { showMenu = false; onRetract() }
                )
            }
            DropdownMenuItem(
                text = { Text(if (showTranscript) "隐藏文字" else "转文字", color = actionMenuTextColor) },
                leadingIcon = { Icon(Icons.Filled.Subtitles, contentDescription = null, tint = actionMenuTextColor) },
                onClick = {
                    showMenu = false
                    val nextShow = !showTranscript
                    onVoiceTranscriptVisibilityChange(nextShow)
                    if (nextShow) onVoiceTranscriptOpened?.invoke()
                }
            )
            if (showTranscript && transcriptText.isNotBlank()) {
                DropdownMenuItem(
                    text = { Text("复制", color = actionMenuTextColor) },
                    leadingIcon = { Icon(Icons.Filled.ContentCopy, contentDescription = null, tint = actionMenuTextColor) },
                    onClick = {
                        showMenu = false
                        clipboardManager.setText(AnnotatedString(transcriptText))
                    }
                )
            }
            if (onQuote != null && mode == "normal") {
                DropdownMenuItem(
                    text = { Text("引用", color = actionMenuTextColor) },
                    leadingIcon = { Icon(Icons.Filled.FormatQuote, contentDescription = null, tint = actionMenuTextColor) },
                    onClick = { showMenu = false; onQuote() }
                )
            }
            DropdownMenuItem(
                text = { Text("删除", color = actionMenuDeleteColor) },
                leadingIcon = { Icon(Icons.Filled.Delete, contentDescription = null, tint = actionMenuDeleteColor) },
                onClick = { showMenu = false; onDelete() }
            )
        }
        AnimatedVisibility(
            visible = showTranscript && transcriptText.isNotBlank(),
            enter = expandVertically(tween(180)) + fadeIn(tween(180)),
            exit = shrinkVertically(tween(140)) + fadeOut(tween(120))
        ) {
            VoiceTextCard(
                text = transcriptText.take(transcriptChars.coerceIn(0, transcriptText.length)),
                accent = Color(0xFF6366F1),
                label = "识别结果",
                modifier = Modifier
                    .fillMaxWidth()
                    .onGloballyPositioned { coords ->
                        onVoiceTranscriptLayout?.invoke(
                            coords.positionInWindow().y + coords.size.height
                        )
                    }
            )
        }
    }
}

