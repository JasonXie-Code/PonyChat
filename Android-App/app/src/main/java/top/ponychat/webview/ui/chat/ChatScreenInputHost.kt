package top.ponychat.webview.ui.chat

import android.content.Context
import android.content.Intent
import androidx.activity.result.ActivityResultLauncher
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.MutableFloatState
import androidx.compose.runtime.MutableIntState
import androidx.compose.runtime.MutableState
import androidx.compose.runtime.State
import androidx.compose.runtime.remember
import androidx.compose.runtime.snapshots.SnapshotStateList
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.pointer.PointerEventPass
import androidx.compose.ui.input.pointer.changedToDown
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.layout
import androidx.compose.ui.unit.Density
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import top.ponychat.webview.data.model.Character
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.device.LocalCompanionRuntimeReady
import top.ponychat.webview.ui.chinesechess.ChineseChessActivity
import top.ponychat.webview.ui.doudizhu.DoudizhuActivity
import top.ponychat.webview.ui.tictactoe.TicTacToeActivity
import top.ponychat.webview.ui.theme.LocalFontScale

@Composable
internal fun ChatScreenInputHost(
    showInputBar: Boolean,
    density: Density,
    effectiveFontScale: Float,
    state: ChatUiState,
    character: Character,
    prefs: AppPreferences,
    viewModel: ChatViewModel,
    context: Context,
    activeSelectionKey: String?,
    onActiveSelectionKeyChange: (String?) -> Unit,
    panelTargetPx: Int,
    inputBarHeightPx: MutableFloatState,
    restingInputBarHeightPxState: MutableIntState,
    relationshipRestingInputHeightPx: Int,
    relationshipVisibleInputHeightPxForFrame: Int,
    panelLiftPx: Int,
    inputBarLayoutLiftPxForFrame: Int,
    focusInputSignal: Int,
    mentionPickerVisible: Boolean,
    onMentionPickerVisibleChange: (Boolean) -> Unit,
    dismissPanelsSignal: Int,
    panelExtraPxState: MutableIntState,
    inputPanelActiveState: MutableState<Boolean>,
    keyboardHandoffLiftPxState: MutableIntState,
    imeBottomState: State<Int>,
    inputBarLayoutTopPx: MutableFloatState,
    inputFocusedState: MutableState<Boolean>,
    isUploadingChatImages: Boolean,
    onUploadingChatImagesChange: (Boolean) -> Unit,
    activeMentionCharacters: List<Character>,
    onClearSelectedMentionCharacters: () -> Unit,
    pendingImages: SnapshotStateList<String>,
    coroutineScope: CoroutineScope,
    imagePickerLauncher: ActivityResultLauncher<PickVisualMediaRequest>,
    onPickCamera: () -> Unit,
    isCompanionActive: Boolean,
    isAgentCompanionActive: Boolean,
    isAgentAutoLooping: Boolean,
    onNavigateToProactiveTasks: () -> Unit,
    onPersonalPreferencesClick: () -> Unit,
    onOpenImagePreview: (List<String>, Int, String) -> Unit,
    showPrompt: (String) -> Unit,
) {
    if (!showInputBar) return
    CompositionLocalProvider(
        androidx.compose.ui.platform.LocalDensity provides Density(density.density, effectiveFontScale),
        LocalFontScale provides effectiveFontScale
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .background(androidx.compose.material3.MaterialTheme.colorScheme.surfaceVariant)
        ) {
            ChatInputBar(
                onPersonalPreferencesClick = onPersonalPreferencesClick,
                modifier = Modifier
                    .fillMaxWidth()
                    .pointerInput(activeSelectionKey) {
                        awaitPointerEventScope {
                            while (true) {
                                val event = awaitPointerEvent(PointerEventPass.Initial)
                                if (activeSelectionKey != null && event.changes.any { it.changedToDown() }) {
                                    onActiveSelectionKeyChange(null)
                                }
                            }
                        }
                    }
                    .layout { measurable, constraints ->
                        val placeable = measurable.measure(constraints)
                        val visibleInputHeight = (placeable.height - panelTargetPx).coerceAtLeast(0)
                        inputBarHeightPx.floatValue = visibleInputHeight.toFloat()
                        if (visibleInputHeight > 0 && (
                                restingInputBarHeightPxState.intValue == 0 ||
                                    visibleInputHeight < restingInputBarHeightPxState.intValue
                            )
                        ) {
                            restingInputBarHeightPxState.intValue = visibleInputHeight
                        }
                        val restingHeight = restingInputBarHeightPxState.intValue
                            .takeIf { it > 0 }
                            ?: visibleInputHeight
                        val inputExtra = (visibleInputHeight - restingHeight).coerceAtLeast(0)
                        val relationshipCollapsedHeight = if (relationshipRestingInputHeightPx > 0) {
                            relationshipVisibleInputHeightPxForFrame
                        } else {
                            visibleInputHeight
                        }
                        val inputBarLiftPx = panelLiftPx + inputExtra + inputBarLayoutLiftPxForFrame
                        layout(placeable.width, relationshipCollapsedHeight) {
                            placeable.place(0, -inputBarLiftPx)
                        }
                    },
                text = state.inputText,
                focusInputSignal = focusInputSignal,
                onTextChange = { newText ->
                    val oldText = state.inputText
                    val addedMentionTrigger = state.mode == "normal" &&
                        newText.count { it == '@' || it == '＠' } >
                        oldText.count { it == '@' || it == '＠' }
                    viewModel.updateInput(newText)
                    if (state.mode == "normal") {
                        when {
                            addedMentionTrigger -> onMentionPickerVisibleChange(true)
                            mentionPickerVisible && newText != oldText -> onMentionPickerVisibleChange(false)
                        }
                    }
                },
                dismissPanelsSignal = dismissPanelsSignal,
                onPanelHeightChanged = { heightPx ->
                    panelExtraPxState.intValue = heightPx
                    if (heightPx > 0) {
                        keyboardHandoffLiftPxState.intValue = 0
                    }
                },
                onPanelActiveChanged = { active -> inputPanelActiveState.value = active },
                onKeyboardHandoffRequested = { panelHeightPx ->
                    keyboardHandoffLiftPxState.intValue = maxOf(
                        panelHeightPx,
                        imeBottomState.value,
                    )
                },
                onInputBarVisualTopChanged = { topPx ->
                    inputBarLayoutTopPx.floatValue = topPx
                },
                onInputFocusChanged = { focused ->
                    inputFocusedState.value = focused
                },
                onSend = send@{
                    if (isUploadingChatImages && state.mode != "normal") return@send
                    val replyCharacterIds = activeMentionCharacters.mapNotNull { it.id }
                    if (pendingImages.isNotEmpty()) {
                        sendMessageWithImages(
                            state = state,
                            viewModel = viewModel,
                            context = context,
                            pendingImages = pendingImages,
                            replyCharacterIds = replyCharacterIds,
                            coroutineScope = coroutineScope,
                            showPrompt = showPrompt,
                            onUploadingChatImagesChange = onUploadingChatImagesChange,
                            onClearSelectedMentionCharacters = onClearSelectedMentionCharacters,
                        )
                        return@send
                    }
                    viewModel.sendMessageAsGuest(replyCharacterIds)
                    onClearSelectedMentionCharacters()
                },
                isStreaming = state.isStreaming,
                voiceState = state.voiceState,
                imageAttachments = pendingImages,
                onPickImage = {
                    if (pendingImages.size < 4) {
                        imagePickerLauncher.launch(
                            PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)
                        )
                    }
                },
                onPickCamera = onPickCamera,
                onRemoveAttachment = { idx -> if (idx in pendingImages.indices) pendingImages.removeAt(idx) },
                quickMessages = state.quickMessages,
                isLoadingQuickMessages = state.isLoadingQuickMessages,
                stickers = state.stickers,
                isLoadingStickers = state.isLoadingStickers,
                onStickerSend = viewModel::sendSticker,
                onStickerUpload = { uri ->
                    coroutineScope.launch {
                        val ratioError = withContext(Dispatchers.IO) { validateStickerAspectRatio(context, uri) }
                        if (ratioError != null) {
                            showPrompt(ratioError)
                            return@launch
                        }
                        val file = withContext(Dispatchers.IO) { copyPickedStickerToCache(context, uri) }
                        if (file == null) {
                            showPrompt("读取表情图片失败")
                        } else {
                            viewModel.uploadSticker(file, file.nameWithoutExtension)
                        }
                    }
                },
                onStickerDelete = viewModel::deleteSticker,
                onStickerPreview = { imageUrl ->
                    val gallery = state.stickers.mapNotNull { it.fileUrl.takeIf { url -> url.isNotBlank() } }.distinct()
                    onOpenImagePreview(gallery, gallery.indexOf(imageUrl).coerceAtLeast(0), imageUrl)
                },
                onLoadStickers = { viewModel.loadStickers() },
                onQuickMessageSend = viewModel::sendQuickMessage,
                onQuickMessageAdd = viewModel::addQuickMessage,
                onQuickMessageUpdate = viewModel::updateQuickMessage,
                onQuickMessageDelete = viewModel::deleteQuickMessage,
                quotedMessage = state.quotedMessage,
                onClearQuotedMessage = viewModel::clearQuotedMessage,
                selectedMentionNames = activeMentionCharacters
                    .map { it.displayName() }
                    .filter { it.isNotBlank() }
                    .toSet(),
                quotaExceeded = state.quotaExceeded,
                supportsVision = remember(state.character, character) {
                    (state.character ?: character).effectiveSupportsVision()
                },
                isCompanionActive = isCompanionActive,
                isAgentCompanionActive = isAgentCompanionActive,
                isAgentAutoLooping = isAgentAutoLooping,
                showCompanionButton = LocalCompanionRuntimeReady.current && state.mode == "normal",
                onProactiveTasksClick = onNavigateToProactiveTasks,
                onChineseChessClick = {
                    val activeCharacter = state.character ?: character
                    val userName = prefs.nickname.ifBlank { prefs.username }.ifBlank { "我" }
                    context.startActivity(
                        Intent(context, ChineseChessActivity::class.java).apply {
                            putExtra(ChineseChessActivity.EXTRA_CHARACTER_NAME, activeCharacter.displayName())
                            putExtra(ChineseChessActivity.EXTRA_CHARACTER_AVATAR, activeCharacter.avatarUrl())
                            putExtra(ChineseChessActivity.EXTRA_CHARACTER_ID, activeCharacter.id.orEmpty())
                            putExtra(ChineseChessActivity.EXTRA_CONVERSATION_ID, state.conversationId.orEmpty())
                            putExtra(ChineseChessActivity.EXTRA_USERNAME, prefs.username)
                            putExtra(
                                ChineseChessActivity.EXTRA_CHARACTER_SUPPORTS_VOICE,
                                activeCharacter.voiceEnabled == true || !activeCharacter.voiceId.isNullOrBlank()
                            )
                            putExtra(ChineseChessActivity.EXTRA_USER_NAME, userName)
                            putExtra(ChineseChessActivity.EXTRA_USER_AVATAR, prefs.avatar)
                        }
                    )
                },
                onTicTacToeClick = {
                    context.startActivity(Intent(context, TicTacToeActivity::class.java))
                },
                onDoudizhuClick = {
                    val activeCharacter = state.character ?: character
                    val userName = prefs.nickname.ifBlank { prefs.username }.ifBlank { "我" }
                    context.startActivity(
                        Intent(context, DoudizhuActivity::class.java).apply {
                            putExtra(DoudizhuActivity.EXTRA_CHARACTER_NAME, activeCharacter.displayName())
                            putExtra(DoudizhuActivity.EXTRA_CHARACTER_AVATAR, activeCharacter.avatarUrl())
                            putExtra(DoudizhuActivity.EXTRA_CHARACTER_ID, activeCharacter.id.orEmpty())
                            putExtra(DoudizhuActivity.EXTRA_CONVERSATION_ID, state.conversationId.orEmpty())
                            putExtra(DoudizhuActivity.EXTRA_USERNAME, prefs.username)
                            putExtra(DoudizhuActivity.EXTRA_USER_NAME, userName)
                            putExtra(DoudizhuActivity.EXTRA_USER_AVATAR, prefs.avatar)
                        }
                    )
                },
                onShowPrompt = showPrompt,
                mode = state.mode
            )
        }
    }
}

private fun sendMessageWithImages(
    state: ChatUiState,
    viewModel: ChatViewModel,
    context: Context,
    pendingImages: SnapshotStateList<String>,
    replyCharacterIds: List<String>,
    coroutineScope: CoroutineScope,
    showPrompt: (String) -> Unit,
    onUploadingChatImagesChange: (Boolean) -> Unit,
    onClearSelectedMentionCharacters: () -> Unit,
) {
    val imageUrls = pendingImages.toList()
    val textAtSend = state.inputText.trim()
    val localMerged = buildImageMessageContent(textAtSend, imageUrls)
    val useLocalPendingBubble = state.mode == "normal"
    val pendingMessageId = if (useLocalPendingBubble) {
        if (localMerged.isBlank()) {
            showPrompt("没有可发送的内容")
            return
        }
        viewModel.appendUploadingUserMessage(localMerged)
    } else {
        null
    }
    if (useLocalPendingBubble && pendingMessageId == null) {
        showPrompt("没有可发送的内容")
        return
    }
    if (useLocalPendingBubble) {
        pendingImages.removeAll(imageUrls.toSet())
        onClearSelectedMentionCharacters()
    }
    onUploadingChatImagesChange(true)
    coroutineScope.launch {
        try {
            val uploadedImageUrls = uploadPendingChatImages(
                context = context,
                viewModel = viewModel,
                imageUrls = imageUrls,
                showErrors = !useLocalPendingBubble,
                showPrompt = showPrompt,
            )
            if (uploadedImageUrls == null) {
                pendingMessageId?.let {
                    viewModel.failUploadingUserMessage(it, "图片上传失败，未发送")
                }
                return@launch
            }
            val merged = buildImageMessageContent(textAtSend, uploadedImageUrls)
            if (merged.isBlank()) {
                if (!useLocalPendingBubble) showPrompt("没有可发送的内容")
                pendingMessageId?.let {
                    viewModel.failUploadingUserMessage(it, "没有可发送的内容")
                }
                return@launch
            }
            if (pendingMessageId != null) {
                viewModel.completeUploadingUserMessage(
                    messageId = pendingMessageId,
                    content = localMerged,
                    replyCharacterIds = replyCharacterIds
                )
            } else {
                viewModel.updateInput(merged)
                pendingImages.removeAll(imageUrls.toSet())
                viewModel.sendMessageAsGuest(replyCharacterIds)
                onClearSelectedMentionCharacters()
            }
        } finally {
            onUploadingChatImagesChange(false)
        }
    }
}
