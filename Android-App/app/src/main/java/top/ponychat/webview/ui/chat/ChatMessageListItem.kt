package top.ponychat.webview.ui.chat

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.util.Log
import androidx.compose.animation.core.CubicBezierEasing
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material3.Icon
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.State
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.positionInWindow
import androidx.compose.ui.unit.dp
import coil.imageLoader
import coil.request.ImageRequest
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import top.ponychat.webview.data.model.Character
import top.ponychat.webview.data.model.Message
import top.ponychat.webview.ui.theme.Primary

@Composable
internal fun ChatMessageListItem(
    msg: Message,
    state: ChatUiState,
    character: Character,
    allCharacters: List<Character>,
    viewModel: ChatViewModel,
    context: Context,
    pendingAnimationIds: MutableSet<String>,
    lastAssistantMessageId: String?,
    lastOverallMessageId: String?,
    msgCharacterName: String,
    msgCharacterAvatarUrl: String?,
    msgUserAvatarUrl: String?,
    msgUserName: String,
    msgApiBase: String,
    currentShowTimestamp: Boolean,
    timestampNow: Long,
    validMentionNames: Set<String>,
    lastAILayoutBottomPx: androidx.compose.runtime.MutableFloatState,
    isGalgameBroken: Boolean,
    latestMessagesState: State<List<Message>>,
    visibleVoiceTranscriptIds: MutableMap<String, Boolean>,
    activeSelectionKey: String?,
    onActiveSelectionKeyChange: (String?) -> Unit,
    onNavigateToCharacterProfile: (Character) -> Unit,
    onNavigateToSettings: () -> Unit,
    onOpenImagePreview: (List<String>, Int, String) -> Unit,
    messagePreviewImages: (List<Message>) -> List<String>,
    plainTextForMessage: (Message) -> String,
    requestVoiceTranscriptSpace: (Float) -> Unit,
    onVoiceTranscriptOpened: () -> Unit,
    onJumpToQuotedMessage: (String) -> Unit,
    onMentionCharacterFromAvatar: (Character) -> Unit,
    onContextActionTriggered: () -> Unit,
    showPrompt: (String) -> Unit,
) {
    val msgKey = msg.stableChatItemKey()
    val isLastAssistant = msgKey == lastAssistantMessageId
    val isLastOverall = msgKey == lastOverallMessageId
    val speakerCharacter = if (msg.isAssistant()) {
        msg.speakerCharacterId
            ?.takeIf { it.isNotBlank() }
            ?.let { speakerId -> allCharacters.firstOrNull { it.id == speakerId } }
    } else {
        null
    }
    val displayMessage = if (msg.isAssistant() && !(speakerCharacter ?: state.character ?: character).supportsCharacterVoice()) {
        msg.copy(voiceState = null)
    } else msg
    val bubbleCharacterName = if (displayMessage.isAssistant()) {
        displayMessage.speakerName?.takeIf { it.isNotBlank() }
            ?: speakerCharacter?.displayName()
            ?: msgCharacterName
    } else {
        msgCharacterName
    }
    val bubbleCharacterAvatarUrl = if (displayMessage.isAssistant()) {
        displayMessage.speakerAvatar?.takeIf { it.isNotBlank() }
            ?: speakerCharacter?.avatarUrl()
            ?: msgCharacterAvatarUrl
    } else {
        msgCharacterAvatarUrl
    }
    val bubbleProfileCharacter = if (displayMessage.isAssistant()) {
        speakerCharacter ?: character
    } else {
        character
    }
    val onMentionBubbleCharacter: (() -> Unit)? =
        if (state.mode == "normal" && displayMessage.isAssistant()) {
            {
                onContextActionTriggered()
                onMentionCharacterFromAvatar(bubbleProfileCharacter)
            }
        } else {
            null
        }
    val isMsgUser = displayMessage.isUser()
    val isGalgameAssistant = state.mode.startsWith("galgame") && !isMsgUser
    val shouldAnimate = pendingAnimationIds.contains(msgKey)
    var msgSettled by remember(msgKey) { mutableStateOf(!shouldAnimate) }
    val msgEasing = CubicBezierEasing(0.25f, 0.1f, 0.25f, 1.0f)
    val slideOffsetX by animateFloatAsState(
        targetValue = if (msgSettled || isGalgameAssistant) 0f else if (isMsgUser) 80f else -60f,
        animationSpec = tween(durationMillis = 200, easing = msgEasing),
        label = "msg_slide_x",
        finishedListener = { if (!isGalgameAssistant) pendingAnimationIds.remove(msgKey) }
    )
    val msgAlpha by animateFloatAsState(
        targetValue = if (isGalgameAssistant && !msgSettled) 0f else 1f,
        animationSpec = tween(durationMillis = 200, easing = msgEasing),
        label = "msg_alpha",
        finishedListener = { if (isGalgameAssistant) pendingAnimationIds.remove(msgKey) }
    )
    LaunchedEffect(msgKey) {
        if (!msgSettled) msgSettled = true
        val hasImages = displayMessage.content.contains("data:image/") ||
            displayMessage.content.contains("![") ||
            displayMessage.content.contains("/chat_images/")
        if (hasImages) {
            val requests = withContext(Dispatchers.IO) {
                val warmT0 = System.nanoTime()
                val media = if (displayMessage.isUser()) splitUserMessageMedia(displayMessage.content, context) else splitMessageMedia(displayMessage.content, context)
                val imgCount = media.imageUrls.size
                val b64Count = media.imageUrls.count { it.startsWith("data:") }
                val localMappedCount = media.imageUrls.count { it.startsWith("/chat_images/") }
                val reqs = mutableListOf<ImageRequest>()
                media.imageUrls.forEach { url ->
                    val model: Any? = when {
                        url.startsWith("data:") -> decodeB64ToFile(url, context)
                        url.startsWith("/chat_images/") -> null
                        url.startsWith("file://") -> android.net.Uri.parse(url)
                        else -> url
                    }
                    if (model != null) {
                        val len = url.length
                        val hash = url.hashCode()
                        val key = if (url.startsWith("data:")) "base64_${len}_${hash}" else url
                        reqs.add(
                            ImageRequest.Builder(context)
                                .data(model)
                                .memoryCacheKey(key)
                                .diskCacheKey(key)
                                .build()
                        )
                    }
                }
                val warmMs = (System.nanoTime() - warmT0) / 1_000_000
                Log.d(IMG_PERF_TAG, "预热 displayMessage=${displayMessage.id.take(8)}: ${imgCount}图(b64=$b64Count localMapped=$localMappedCount), 耗时=${warmMs}ms")
                reqs
            }
            requests.forEach { req -> context.imageLoader.enqueue(req) }
        }
    }
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .graphicsLayer {
                translationX = slideOffsetX
                alpha = msgAlpha
            }
            .then(
                if (isLastAssistant) {
                    Modifier.onGloballyPositioned { coords ->
                        val y = coords.positionInWindow().y
                        val bottom = y + coords.size.height
                        lastAILayoutBottomPx.floatValue = bottom
                    }
                } else {
                    Modifier
                }
            )
    ) {
        if (isLastAssistant) {
            LastAssistantMessageBubble(
                viewModel = viewModel,
                message = displayMessage,
                characterName = bubbleCharacterName,
                characterAvatarUrl = bubbleCharacterAvatarUrl.orEmpty(),
                userAvatarUrl = msgUserAvatarUrl.orEmpty(),
                userName = msgUserName,
                apiBase = msgApiBase,
                mode = state.mode,
                isOverallLast = isLastOverall,
                isStreaming = state.isStreaming,
                showTimestamp = currentShowTimestamp,
                timestampNow = timestampNow,
                validMentionNames = validMentionNames,
                onNavigateToEditCharacter = { onNavigateToCharacterProfile(bubbleProfileCharacter) },
                onMentionCharacter = onMentionBubbleCharacter,
                onNavigateToSettings = onNavigateToSettings,
                onCopy = {
                    val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                    val text = plainTextForMessage(displayMessage)
                    clipboard.setPrimaryClip(ClipData.newPlainText("消息", text))
                    showPrompt("已复制")
                },
                onDelete = { viewModel.deleteMessage(displayMessage.id) },
                onEdit = { updated -> viewModel.editMessage(displayMessage.id, updated) },
                onSelectOption = if (isGalgameBroken) null else { label ->
                    viewModel.updateInput(label)
                    viewModel.sendMessage()
                },
                onFillOption = if (isGalgameBroken) null else { label ->
                    viewModel.updateInput(label)
                },
                onImagePreview = { imageUrl ->
                    val gallery = messagePreviewImages(state.messages)
                    onOpenImagePreview(gallery, gallery.indexOf(imageUrl).coerceAtLeast(0), imageUrl)
                },
                onRegenerate = if (displayMessage.isAssistant()) ({ viewModel.regenerateLastResponse() }) else null,
                onActionBarVisible = null,
                revealGradually = false,
                onParagraphRevealed = null,
                onVoiceTranscriptLayout = requestVoiceTranscriptSpace,
                onVoiceTranscriptOpened = onVoiceTranscriptOpened,
                isVoiceTranscriptVisible = visibleVoiceTranscriptIds[displayMessage.id] == true,
                onVoiceTranscriptVisibilityChange = { visible ->
                    if (visible) {
                        visibleVoiceTranscriptIds[displayMessage.id] = true
                    } else {
                        visibleVoiceTranscriptIds.remove(displayMessage.id)
                    }
                },
                onQuote = if (state.mode == "normal") ({ viewModel.quoteMessage(displayMessage) }) else null,
                onJumpToQuotedMessage = onJumpToQuotedMessage,
                onRetract = if (displayMessage.isUser() && state.messages.noneAfter(displayMessage.id) { it.isAssistant() }) ({ viewModel.retractMessage(displayMessage.id) }) else null,
                onRetractEdit = if (displayMessage.isUser()) ({ viewModel.restoreRetractedMessageInput(displayMessage.id) }) else null,
                activeSelectionKey = activeSelectionKey,
                onActiveSelectionKeyChange = onActiveSelectionKeyChange,
                onContextActionTriggered = onContextActionTriggered
            )
        } else {
            val onCopyMsg = remember(displayMessage.id, displayMessage.content, displayMessage.displayContent, displayMessage.voiceState, state.mode) {
                {
                    val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                    val text = plainTextForMessage(displayMessage)
                    clipboard.setPrimaryClip(ClipData.newPlainText("消息", text))
                    showPrompt("已复制")
                }
            }
            val onDeleteMsg = remember(displayMessage.id) { { viewModel.deleteMessage(displayMessage.id) } }
            val onEditMsg: ((String) -> Unit) = remember(displayMessage.id) { { updated -> viewModel.editMessage(displayMessage.id, updated) } }
            val onImagePreviewMsg: (String) -> Unit = remember(displayMessage.id) {
                { imageUrl ->
                    val gallery = messagePreviewImages(latestMessagesState.value)
                    onOpenImagePreview(gallery, gallery.indexOf(imageUrl).coerceAtLeast(0), imageUrl)
                }
            }
            val onSelectOptionMsg = remember(displayMessage.id, isGalgameBroken) {
                if (isGalgameBroken) null else ({ label: String ->
                    viewModel.updateInput(label)
                    viewModel.sendMessage()
                })
            }
            val onFillOptionMsg = remember(displayMessage.id, isGalgameBroken) {
                if (isGalgameBroken) null else ({ label: String -> viewModel.updateInput(label) })
            }
            val onRegenerateMsg = remember(displayMessage.id) {
                if (displayMessage.isAssistant()) ({ viewModel.regenerateLastResponse() }) else null
            }
            val canRetract = displayMessage.isUser() && state.messages.noneAfter(displayMessage.id) { it.isAssistant() }
            val messageKey = uiMessageKey(displayMessage)
            MessageBubble(
                message = displayMessage,
                characterName = bubbleCharacterName,
                characterAvatarUrl = bubbleCharacterAvatarUrl.orEmpty(),
                userAvatarUrl = msgUserAvatarUrl.orEmpty(),
                userName = msgUserName,
                apiBase = msgApiBase,
                mode = state.mode,
                isLast = isLastOverall,
                isStreaming = false,
                showTimestamp = currentShowTimestamp,
                timestampNow = timestampNow,
                validMentionNames = validMentionNames,
                replyTimer = 0L,
                retryCount = 0,
                isTimerRunning = false,
                onNavigateToEditCharacter = { onNavigateToCharacterProfile(bubbleProfileCharacter) },
                onMentionCharacter = onMentionBubbleCharacter,
                onNavigateToSettings = onNavigateToSettings,
                onCopy = onCopyMsg,
                onDelete = onDeleteMsg,
                onEdit = onEditMsg,
                onSelectOption = onSelectOptionMsg,
                onFillOption = onFillOptionMsg,
                onImagePreview = onImagePreviewMsg,
                onRegenerate = onRegenerateMsg,
                revealGradually = false,
                onVoiceTranscriptLayout = requestVoiceTranscriptSpace,
                onVoiceTranscriptOpened = onVoiceTranscriptOpened,
                isVoiceTranscriptVisible = visibleVoiceTranscriptIds[displayMessage.id] == true,
                onVoiceTranscriptVisibilityChange = { visible ->
                    if (visible) {
                        visibleVoiceTranscriptIds[displayMessage.id] = true
                    } else {
                        visibleVoiceTranscriptIds.remove(displayMessage.id)
                    }
                },
                onQuote = if (state.mode == "normal") remember(displayMessage.id, displayMessage.content, displayMessage.displayContent) { { viewModel.quoteMessage(displayMessage) } } else null,
                onJumpToQuotedMessage = onJumpToQuotedMessage,
                onRetract = if (canRetract) remember(displayMessage.id) { { viewModel.retractMessage(displayMessage.id) } } else null,
                onRetractEdit = if (displayMessage.isUser()) remember(displayMessage.id) { { viewModel.restoreRetractedMessageInput(displayMessage.id) } } else null,
                activeSelectionKey = activeSelectionKey,
                onActiveSelectionKeyChange = onActiveSelectionKeyChange,
                onRetryPendingAccept = if (state.mode == "normal" && displayMessage.isUser()) {
                    remember(messageKey) { { viewModel.retryPendingNormalUserMessage(messageKey) } }
                } else {
                    null
                },
                onContextActionTriggered = onContextActionTriggered
            )
        }
        if (state.isExportMode) {
            val isExportSelected = displayMessage.id in state.exportSelectedIds
            Box(
                modifier = Modifier
                    .matchParentSize()
                    .background(if (isExportSelected) Primary.copy(alpha = 0.16f) else Color.Transparent)
                    .clickable { viewModel.toggleExportSelection(displayMessage.id) }
            ) {
                if (isExportSelected) {
                    Icon(
                        Icons.Filled.CheckCircle,
                        contentDescription = null,
                        tint = Primary,
                        modifier = Modifier
                            .align(Alignment.TopEnd)
                            .padding(end = 12.dp, top = 4.dp)
                            .size(22.dp)
                    )
                }
            }
        }
    }
}
