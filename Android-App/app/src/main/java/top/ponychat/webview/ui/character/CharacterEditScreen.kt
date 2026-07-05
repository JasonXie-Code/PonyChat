package top.ponychat.webview.ui.character

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.media.MediaPlayer
import android.net.Uri
import android.provider.OpenableColumns
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage
import coil.request.ImageRequest
import kotlinx.coroutines.launch
import top.ponychat.webview.CustomToast
import top.ponychat.webview.audio.MobileVoiceEffect
import top.ponychat.webview.data.local.ChatVoiceCache
import top.ponychat.webview.data.model.Character
import top.ponychat.webview.data.model.VoiceAudioTransfer
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.ui.common.AvatarCropDialog
import top.ponychat.webview.ui.common.PonyConfirmDialog
import top.ponychat.webview.ui.common.PonyDialogActionStyle
import top.ponychat.webview.ui.common.PonyAvatar
import top.ponychat.webview.ui.common.PonyTopBar
import top.ponychat.webview.ui.common.adaptivePopupMenuAccentColor
import top.ponychat.webview.ui.common.adaptivePopupMenuBorder
import top.ponychat.webview.ui.common.adaptivePopupMenuContainerColor
import top.ponychat.webview.ui.common.adaptivePopupMenuContentColor
import top.ponychat.webview.ui.common.focusAwareBringIntoView
import top.ponychat.webview.ui.theme.*
import java.util.UUID

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CharacterEditScreen(
    viewModel: CharacterViewModel,
    prefs: AppPreferences,
    isCreating: Boolean,
    character: Character?,
    onNavigateBack: () -> Unit
) {
    val context = LocalContext.current
    val customToast = CustomToast.current
    val scope = rememberCoroutineScope()

    var name by remember { mutableStateOf(character?.name ?: "") }
    var signature by remember {
        mutableStateOf(
            character?.preview?.takeIf { it.isNotBlank() }
                ?: character?.bio?.takeIf { it.isNotBlank() }
                ?: character?.description
                ?: ""
        )
    }
    var prompt by remember { mutableStateOf(character?.effectivePrompt() ?: "") }
    var tags by remember { mutableStateOf(character?.safeTags()?.joinToString(", ") ?: "") }
    var profileCover by remember { mutableStateOf(character?.profileCover ?: "") }
    var profilePhotos by remember { mutableStateOf(character?.safeProfilePhotos() ?: emptyList()) }
    var profileGender by remember { mutableStateOf(character?.profileGender ?: "") }
    var profileSpecies by remember { mutableStateOf(character?.profileSpecies ?: "") }
    var profileAge by remember { mutableStateOf(character?.profileAge ?: "") }
    var profilePersonality by remember { mutableStateOf(character?.profilePersonality ?: "") }
    var profileInterests by remember { mutableStateOf(character?.profileInterests ?: "") }
    var profileIntro by remember {
        mutableStateOf(
            character?.profileIntro?.takeIf { it.isNotBlank() }
                ?: character?.bio?.takeIf { it.isNotBlank() }
                ?: character?.description
                ?: ""
        )
    }
    var profileMbti by remember { mutableStateOf(character?.profileMbti ?: "") }
    val initialVoiceSourceMode = remember(character?.id) { inferVoiceSourceMode(character) }
    val initialVoiceId = character?.voiceId.orEmpty()
    var voiceEnabled by remember { mutableStateOf(character?.voiceEnabled ?: initialVoiceId.isNotBlank()) }
    var voiceSourceMode by remember { mutableStateOf(initialVoiceSourceMode) }
    var voiceId by remember {
        mutableStateOf(
            when {
                initialVoiceSourceMode == VOICE_SOURCE_ID -> initialVoiceId
                initialVoiceSourceMode == VOICE_SOURCE_INSTRUCT -> initialVoiceId
                initialVoiceSourceMode == VOICE_SOURCE_CLONE -> initialVoiceId
                else -> ""
            }
        )
    }
    var voiceInstruct by remember { mutableStateOf(character?.voiceInstruct.orEmpty()) }
    var voiceReferenceAudioUrl by remember { mutableStateOf(character?.voiceReferenceAudioUrl.orEmpty()) }
    var voiceReferenceText by remember { mutableStateOf(character?.voiceReferenceText.orEmpty()) }
    var voiceProfileId by remember {
        mutableStateOf(
            character?.voiceProfileId?.takeIf { it.isNotBlank() }
                ?: initialVoiceId.takeIf { it.startsWith("ponyvoice:", ignoreCase = true) }
                ?: "ponyvoice:${character?.id?.takeIf { it.isNotBlank() } ?: UUID.randomUUID()}"
        )
    }
    var voiceCloneStatus by remember { mutableStateOf(character?.voiceCloneStatus.orEmpty()) }
    var isUploadingProfileImage by remember { mutableStateOf(false) }
    var isUploadingVoiceReference by remember { mutableStateOf(false) }
    var isDesigningVoice by remember { mutableStateOf(false) }
    val voiceDesignPreviewPlayer = remember { mutableStateOf<MediaPlayer?>(null) }
    val voiceDesignPreviewEffects = remember { mutableStateOf<MobileVoiceEffect.PlaybackEffects?>(null) }
    // 保留原有破限值，不在此处展示或修改（破限开关已移至对话设置页）
    val existingJailbreak = character?.jailbreak ?: false
    var avatarDataUrl by remember { mutableStateOf<String?>(null) }
    var showCropDialog by remember { mutableStateOf(false) }
    var rawAvatarBitmap by remember { mutableStateOf<Bitmap?>(null) }
    var nameError by remember { mutableStateOf(false) }
    var showExitConfirmDialog by remember { mutableStateOf(false) }
    val editBlocked = !isCreating && character?.isEditBlockedFor(prefs.username) == true
    fun showEditBlockedToast() {
        scope.launch { customToast.showSnackbar("此角色不可编辑") }
    }

    DisposableEffect(Unit) {
        onDispose {
            voiceDesignPreviewPlayer.value?.let { player ->
                runCatching {
                    if (player.isPlaying) player.stop()
                }
                runCatching { player.release() }
            }
            voiceDesignPreviewEffects.value?.release()
            voiceDesignPreviewEffects.value = null
            voiceDesignPreviewPlayer.value = null
        }
    }

    val avatarPickerLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.GetContent()
    ) { uri ->
        if (uri != null) {
            runCatching {
                context.contentResolver.openInputStream(uri)?.use { stream ->
                    val bytes = stream.readBytes()
                    if (bytes.isNotEmpty()) {
                        rawAvatarBitmap = BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
                        showCropDialog = rawAvatarBitmap != null
                    }
                }
            }
        }
    }

    fun uploadProfileImageBytes(bytes: ByteArray, onUploaded: (String) -> Unit) {
        if (bytes.isEmpty()) return
        isUploadingProfileImage = true
        viewModel.uploadCharacterProfileImage(
            bytes = bytes,
            onResult = { url ->
                isUploadingProfileImage = false
                onUploaded(url)
            },
            onError = { message ->
                isUploadingProfileImage = false
                scope.launch { customToast.showSnackbar(message) }
            }
        )
    }

    val coverPickerLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.GetContent()
    ) { uri ->
        if (uri != null) {
            runCatching {
                context.contentResolver.openInputStream(uri)?.use { stream -> stream.readBytes() }
            }.getOrNull()?.let { bytes ->
                uploadProfileImageBytes(bytes) { profileCover = it }
            }
        }
    }

    val photosPickerLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.GetMultipleContents()
    ) { uris ->
        uris.take(12 - profilePhotos.size).forEach { uri ->
            runCatching {
                context.contentResolver.openInputStream(uri)?.use { stream -> stream.readBytes() }
            }.getOrNull()?.let { bytes ->
                uploadProfileImageBytes(bytes) { url ->
                    profilePhotos = (profilePhotos + url).take(12)
                }
            }
        }
    }

    fun currentVoiceSettings(): VoiceEditSettings {
        val normalizedMode = normalizeVoiceSourceMode(voiceSourceMode)
        val cleanVoiceId = voiceId.trim()
        val cleanProfileId = voiceProfileId.trim().ifBlank {
            "ponyvoice:${character?.id?.takeIf { it.isNotBlank() } ?: UUID.randomUUID()}"
        }
        return when (normalizedMode) {
            VOICE_SOURCE_INSTRUCT -> VoiceEditSettings(
                enabled = voiceEnabled,
                voiceId = cleanProfileId,
                voiceInstruct = voiceInstruct.trim(),
                voiceDecisionPolicy = VOICE_POLICY_BACKEND,
                voiceSourceMode = VOICE_SOURCE_INSTRUCT,
                voiceBaseVoiceId = "",
                voiceReferenceAudioUrl = "",
                voiceReferenceText = "",
                voiceProfileId = cleanProfileId,
                voiceCloneStatus = when {
                    voiceInstruct.isNotBlank() -> "recipe_ready"
                    voiceCloneStatus == "design_failed" -> "design_failed"
                    else -> ""
                }
            )
            VOICE_SOURCE_CLONE -> VoiceEditSettings(
                enabled = voiceEnabled,
                voiceId = cleanProfileId,
                voiceInstruct = voiceInstruct.trim(),
                voiceDecisionPolicy = VOICE_POLICY_BACKEND,
                voiceSourceMode = VOICE_SOURCE_CLONE,
                voiceBaseVoiceId = "",
                voiceReferenceAudioUrl = voiceReferenceAudioUrl.trim(),
                voiceReferenceText = voiceReferenceText.trim(),
                voiceProfileId = cleanProfileId,
                voiceCloneStatus = when {
                    voiceCloneStatus.isNotBlank() -> voiceCloneStatus.trim()
                    voiceReferenceAudioUrl.isNotBlank() -> "recipe_ready"
                    else -> ""
                }
            )
            else -> VoiceEditSettings(
                enabled = voiceEnabled,
                voiceId = cleanVoiceId,
                voiceInstruct = "",
                voiceDecisionPolicy = VOICE_POLICY_BACKEND,
                voiceSourceMode = VOICE_SOURCE_ID,
                voiceBaseVoiceId = "",
                voiceReferenceAudioUrl = "",
                voiceReferenceText = "",
                voiceProfileId = "",
                voiceCloneStatus = ""
            )
        }
    }

    val voiceAudioPickerLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.GetContent()
    ) { uri ->
        if (uri == null) return@rememberLauncherForActivityResult
        if (editBlocked) {
            showEditBlockedToast()
            return@rememberLauncherForActivityResult
        }
        if (voiceReferenceText.isBlank()) {
            scope.launch { customToast.showSnackbar("请先填写音频内文本") }
            return@rememberLauncherForActivityResult
        }
        val bytes = runCatching {
            context.contentResolver.openInputStream(uri)?.use { stream -> stream.readBytes() }
        }.getOrNull()
        if (bytes == null || bytes.isEmpty()) {
            scope.launch { customToast.showSnackbar("无法读取参考音频") }
            return@rememberLauncherForActivityResult
        }
        val mimeType = context.contentResolver.getType(uri) ?: inferAudioMimeType(uri)
        val fileName = displayNameForUri(context.contentResolver, uri)
        isUploadingVoiceReference = true
        viewModel.uploadCharacterVoiceReferenceAudio(
            bytes = bytes,
            fileName = fileName,
            mimeType = mimeType,
            transcript = voiceReferenceText.trim(),
            characterId = character?.id.orEmpty(),
            voiceProfileId = voiceProfileId,
            voiceName = name.trim(),
            onResult = { uploaded ->
                isUploadingVoiceReference = false
                voiceSourceMode = VOICE_SOURCE_CLONE
                voiceEnabled = true
                voiceReferenceAudioUrl = uploaded.url
                voiceReferenceText = uploaded.transcript?.takeIf { it.isNotBlank() } ?: voiceReferenceText
                uploaded.voiceProfileId?.takeIf { it.isNotBlank() }?.let {
                    voiceProfileId = it
                    voiceId = it
                }
                uploaded.voiceId?.takeIf { it.isNotBlank() }?.let { voiceId = it }
                voiceCloneStatus = uploaded.cloneStatus?.takeIf { it.isNotBlank() }
                    ?: "recipe_ready"
                val toastText = when (voiceCloneStatus) {
                    "recipe_ready" -> "参考音频已上传，音色配方已保存"
                    "clone_failed" -> "参考音频已上传，音色配方保存失败"
                    else -> "参考音频已上传"
                }
                scope.launch { customToast.showSnackbar(toastText) }
            },
            onError = { message ->
                isUploadingVoiceReference = false
                scope.launch { customToast.showSnackbar(message) }
            }
        )
    }

    fun playVoiceDesignPreview(transfer: VoiceAudioTransfer?): Boolean {
        val key = "voice_design_preview:${UUID.randomUUID()}"
        val cached = ChatVoiceCache.save(context, key, transfer) ?: return false
        voiceDesignPreviewPlayer.value?.let { old ->
            runCatching {
                if (old.isPlaying) old.stop()
            }
            runCatching { old.release() }
        }
        voiceDesignPreviewEffects.value?.release()
        voiceDesignPreviewEffects.value = null
        return runCatching {
            val player = MediaPlayer().apply {
                setDataSource(cached.localFile)
                setOnCompletionListener { completed ->
                    if (voiceDesignPreviewPlayer.value === completed) {
                        voiceDesignPreviewPlayer.value = null
                        voiceDesignPreviewEffects.value?.release()
                        voiceDesignPreviewEffects.value = null
                    }
                    runCatching { completed.release() }
                }
                prepare()
                voiceDesignPreviewEffects.value = MobileVoiceEffect.attachTo(this)
                start()
            }
            voiceDesignPreviewPlayer.value = player
            true
        }.getOrElse {
            false
        }
    }

    fun requestVoiceDesign(action: String) {
        if (editBlocked) {
            showEditBlockedToast()
            return
        }
        val cleanDescription = voiceInstruct.trim()
        if (cleanDescription.isBlank()) {
            scope.launch { customToast.showSnackbar("请先输入描述") }
            return
        }
        if (isDesigningVoice) return
        isDesigningVoice = true
        viewModel.designCharacterVoice(
            characterId = character?.id.orEmpty(),
            characterName = name.trim(),
            voiceId = voiceId.trim(),
            instruct = cleanDescription,
            action = action,
            onResult = { designed ->
                isDesigningVoice = false
                voiceSourceMode = VOICE_SOURCE_INSTRUCT
                voiceEnabled = true
                designed.voiceProfileId?.takeIf { it.isNotBlank() }?.let {
                    voiceProfileId = it
                    voiceId = it
                }
                designed.voiceId?.takeIf { it.isNotBlank() }?.let { voiceId = it }
                designed.voiceInstruct?.takeIf { it.isNotBlank() }?.let { voiceInstruct = it }
                voiceCloneStatus = designed.designStatus?.takeIf { it.isNotBlank() } ?: "recipe_ready"
                val played = playVoiceDesignPreview(designed.audioTransfer)
                val toastText = when {
                    played -> if (action == "replace") "音色已更换" else "正在试听"
                    designed.previewError?.isNotBlank() == true -> "音色已保存，聊天时会自动生成语音"
                    else -> "音色已保存，暂无试听音频"
                }
                scope.launch { customToast.showSnackbar(toastText) }
            },
            onError = { message ->
                isDesigningVoice = false
                scope.launch { customToast.showSnackbar(message) }
            }
        )
    }

    fun doSave() {
        if (name.isBlank()) return
        if (editBlocked) {
            showEditBlockedToast()
            return
        }
        val tagList = tags.split(",", "，").map { it.trim() }.filter { it.isNotEmpty() }
        val voiceSettings = currentVoiceSettings()
        if (isCreating) {
            viewModel.createCharacterFull(
                name = name.trim(),
                bio = profileIntro.trim(),
                prompt = prompt.trim(),
                preview = signature.trim(),
                avatar = avatarDataUrl ?: "",
                profileCover = profileCover,
                profilePhotos = profilePhotos,
                profileGender = profileGender.trim(),
                profileSpecies = profileSpecies.trim(),
                profileAge = profileAge.trim(),
                profilePersonality = profilePersonality.trim(),
                profileInterests = profileInterests.trim(),
                profileIntro = profileIntro.trim(),
                profileMbti = profileMbti.trim(),
                voiceEnabled = voiceSettings.enabled,
                voiceId = voiceSettings.voiceId,
                voiceInstruct = voiceSettings.voiceInstruct,
                voiceDecisionPolicy = voiceSettings.voiceDecisionPolicy,
                voiceSourceMode = voiceSettings.voiceSourceMode,
                voiceBaseVoiceId = voiceSettings.voiceBaseVoiceId,
                voiceReferenceAudioUrl = voiceSettings.voiceReferenceAudioUrl,
                voiceReferenceText = voiceSettings.voiceReferenceText,
                voiceProfileId = voiceSettings.voiceProfileId,
                voiceCloneStatus = voiceSettings.voiceCloneStatus,
                tags = tagList,
                jailbreak = false
            )
        } else {
            character?.let {
                viewModel.saveEditedCharacterFull(
                    original = it,
                    name = name.trim(),
                    bio = profileIntro.trim(),
                    prompt = prompt.trim(),
                    preview = signature.trim(),
                    avatar = avatarDataUrl ?: it.avatar ?: "",
                    profileCover = profileCover,
                    profilePhotos = profilePhotos,
                    profileGender = profileGender.trim(),
                    profileSpecies = profileSpecies.trim(),
                    profileAge = profileAge.trim(),
                    profilePersonality = profilePersonality.trim(),
                    profileInterests = profileInterests.trim(),
                    profileIntro = profileIntro.trim(),
                    profileMbti = profileMbti.trim(),
                    voiceEnabled = voiceSettings.enabled,
                    voiceId = voiceSettings.voiceId,
                    voiceInstruct = voiceSettings.voiceInstruct,
                    voiceDecisionPolicy = voiceSettings.voiceDecisionPolicy,
                    voiceSourceMode = voiceSettings.voiceSourceMode,
                    voiceBaseVoiceId = voiceSettings.voiceBaseVoiceId,
                    voiceReferenceAudioUrl = voiceSettings.voiceReferenceAudioUrl,
                    voiceReferenceText = voiceSettings.voiceReferenceText,
                    voiceProfileId = voiceSettings.voiceProfileId,
                    voiceCloneStatus = voiceSettings.voiceCloneStatus,
                    tags = tagList,
                    jailbreak = existingJailbreak
                )
            }
        }
    }

    fun normalizeTags(raw: String): String =
        raw.split(",", "，").map { it.trim() }.filter { it.isNotEmpty() }.joinToString(",")

    fun hasCharacterChanges(): Boolean {
        if (isCreating) return true
        val original = character ?: return false
        val initialName = original.name.orEmpty().trim()
        val initialSignature = (original.preview?.takeIf { it.isNotBlank() } ?: original.bio ?: original.description ?: "").trim()
        val initialPrompt = original.effectivePrompt().trim()
        val initialTags = normalizeTags(original.safeTags().joinToString(","))
        val initialAvatar = original.avatar ?: ""
        val initialCover = original.profileCover ?: ""
        val initialPhotos = original.safeProfilePhotos()
        val initialGender = original.profileGender ?: ""
        val initialSpecies = original.profileSpecies ?: ""
        val initialAge = original.profileAge ?: ""
        val initialPersonality = original.profilePersonality ?: ""
        val initialInterests = original.profileInterests ?: ""
        val initialIntro = (original.profileIntro?.takeIf { it.isNotBlank() } ?: original.bio ?: original.description ?: "").trim()
        val initialMbti = original.profileMbti ?: ""
        val initialVoiceSettings = voiceEditSettingsFromCharacter(original)

        return name.trim() != initialName ||
            signature.trim() != initialSignature ||
            prompt.trim() != initialPrompt ||
            profileCover != initialCover ||
            profilePhotos != initialPhotos ||
            profileGender.trim() != initialGender ||
            profileSpecies.trim() != initialSpecies ||
            profileAge.trim() != initialAge ||
            profilePersonality.trim() != initialPersonality ||
            profileInterests.trim() != initialInterests ||
            profileIntro.trim() != initialIntro ||
            profileMbti.trim() != initialMbti ||
            normalizeTags(tags) != initialTags ||
            currentVoiceSettings() != initialVoiceSettings ||
            (avatarDataUrl != null && avatarDataUrl != initialAvatar)
    }

    var hasSavedOnExit by remember { mutableStateOf(false) }
    fun saveOnExit() {
        if (hasSavedOnExit) return
        hasSavedOnExit = true
        if (!hasCharacterChanges()) return
        doSave()
    }

    fun tryNavigateBack() {
        if (isCreating && name.isBlank()) { showExitConfirmDialog = true; return }
        saveOnExit()
        onNavigateBack()
    }

    BackHandler { tryNavigateBack() }

    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        contentWindowInsets = WindowInsets(0, 0, 0, 0),
        topBar = {
            PonyTopBar(
                title = if (isCreating) "创建角色" else "编辑角色",
                onNavigateBack = { tryNavigateBack() }
            )
        }
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .imePadding()
                .verticalScroll(rememberScrollState())
        ) {
            // 头像区域
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(vertical = 24.dp),
                horizontalAlignment = Alignment.CenterHorizontally
            ) {
                val displayAvatar = avatarDataUrl ?: character?.avatarUrl() ?: ""
                val apiBase = prefs.effectiveApiBase()

                Box(
                    modifier = Modifier
                        .size(80.dp)
                        .clickable {
                            if (editBlocked) showEditBlockedToast()
                            else avatarPickerLauncher.launch("image/*")
                        },
                    contentAlignment = Alignment.Center
                ) {
                    PonyAvatar(
                        avatarUrl = displayAvatar,
                        name = name.ifBlank { "?" },
                        apiBase = apiBase,
                        size = 80
                    )
                    Box(
                        modifier = Modifier
                            .align(Alignment.BottomEnd)
                            .size(26.dp)
                            .clip(CircleShape)
                            .background(Primary),
                        contentAlignment = Alignment.Center
                    ) {
                        Icon(
                            Icons.Filled.CameraAlt,
                            contentDescription = null,
                            modifier = Modifier.size(14.dp),
                            tint = Color.White
                        )
                    }
                }
            }

            // 基本信息卡片
            SettingsCard {
                EditItem(
                    label = "名称",
                    value = name,
                    onValueChange = { name = it; nameError = false },
                    placeholder = "角色名称",
                    isError = nameError,
                    enabled = !editBlocked,
                    onDisabledClick = ::showEditBlockedToast
                )
                CardDivider()
                EditItem(
                    label = "个性签名",
                    value = signature,
                    onValueChange = { signature = it },
                    placeholder = "一句话介绍角色",
                    enabled = !editBlocked,
                    onDisabledClick = ::showEditBlockedToast
                )
                CardDivider()
                EditItem(
                    label = "标签",
                    value = tags,
                    onValueChange = { tags = it },
                    placeholder = "用逗号分隔",
                    enabled = !editBlocked,
                    onDisabledClick = ::showEditBlockedToast
                )
            }

            Spacer(Modifier.height(12.dp))

            SettingsCard {
                CardSectionTitle("角色档案")
                EditItem(
                    label = "种族",
                    value = profileSpecies,
                    onValueChange = { profileSpecies = it },
                    placeholder = "例如：飞马 / 人类 / 精灵",
                    enabled = !editBlocked,
                    onDisabledClick = ::showEditBlockedToast
                )
                CardDivider()
                EditItem(
                    label = "性别",
                    value = profileGender,
                    onValueChange = { profileGender = it },
                    placeholder = "例如：女性 / 雌性 / 男性",
                    enabled = !editBlocked,
                    onDisabledClick = ::showEditBlockedToast
                )
                CardDivider()
                EditItem(
                    label = "年龄",
                    value = profileAge,
                    onValueChange = { profileAge = it },
                    placeholder = "例如：22岁 / 成年 / 青少年",
                    enabled = !editBlocked,
                    onDisabledClick = ::showEditBlockedToast
                )
                CardDivider()
                MbtiSelector(
                    value = profileMbti,
                    enabled = !editBlocked,
                    onValueChange = { profileMbti = it },
                    onDisabledClick = ::showEditBlockedToast
                )
                CardDivider()
                EditItem(
                    label = "性格",
                    value = profilePersonality,
                    onValueChange = { profilePersonality = it },
                    placeholder = "例如：温柔内敛",
                    enabled = !editBlocked,
                    onDisabledClick = ::showEditBlockedToast
                )
                CardDivider()
                EditItem(
                    label = "兴趣",
                    value = profileInterests,
                    onValueChange = { profileInterests = it },
                    placeholder = "例如：阅读、整理知识",
                    enabled = !editBlocked,
                    onDisabledClick = ::showEditBlockedToast
                )
                CardDivider()
                Text(
                    text = "简介",
                    style = MaterialTheme.typography.labelLarge,
                    color = MaterialTheme.colorScheme.onSurface,
                    fontWeight = FontWeight.SemiBold,
                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp)
                )
                MultilineEditItem(
                    value = profileIntro,
                    onValueChange = { profileIntro = it },
                    placeholder = "公开角色简介，会作为角色档案的一部分带入设定",
                    minLines = 3,
                    maxLines = 6,
                    enabled = !editBlocked,
                    onDisabledClick = ::showEditBlockedToast
                )
            }

            Spacer(Modifier.height(12.dp))

            SettingsCard {
                CardSectionTitle("主页素材")
                ProfileCoverEditor(
                    coverUrl = profileCover,
                    apiBase = prefs.effectiveApiBase(),
                    isUploading = isUploadingProfileImage,
                    enabled = !editBlocked,
                    onPick = {
                        if (editBlocked) showEditBlockedToast() else coverPickerLauncher.launch("image/*")
                    },
                    onRemove = { profileCover = "" },
                    onDisabledClick = ::showEditBlockedToast
                )
                CardDivider()
                ProfilePhotosEditor(
                    photos = profilePhotos,
                    apiBase = prefs.effectiveApiBase(),
                    isUploading = isUploadingProfileImage,
                    enabled = !editBlocked,
                    onAdd = {
                        if (editBlocked) showEditBlockedToast() else photosPickerLauncher.launch("image/*")
                    },
                    onRemove = { index ->
                        profilePhotos = profilePhotos.filterIndexed { i, _ -> i != index }
                    },
                    onDisabledClick = ::showEditBlockedToast
                )
            }

            Spacer(Modifier.height(12.dp))

            SettingsCard {
                CardSectionTitle("语音音色")
                VoiceToneEditor(
                    voiceEnabled = voiceEnabled,
                    onVoiceEnabledChange = { voiceEnabled = it },
                    sourceMode = voiceSourceMode,
                    onSourceModeChange = { nextMode ->
                        val normalizedNext = normalizeVoiceSourceMode(nextMode)
                        if (normalizedNext == VOICE_SOURCE_CLONE && voiceCloneStatus == "recipe_ready") {
                            voiceId = ""
                            voiceCloneStatus = ""
                        }
                        if (normalizedNext == VOICE_SOURCE_INSTRUCT && voiceCloneStatus != "recipe_ready") {
                            voiceId = ""
                            if (voiceCloneStatus != "design_failed") voiceCloneStatus = ""
                        }
                        if (normalizedNext == VOICE_SOURCE_ID) {
                            voiceCloneStatus = ""
                        }
                        voiceSourceMode = normalizedNext
                    },
                    voiceId = voiceId,
                    onVoiceIdChange = { voiceId = it },
                    instruct = voiceInstruct,
                    onInstructChange = { voiceInstruct = it },
                    referenceAudioUrl = voiceReferenceAudioUrl,
                    referenceText = voiceReferenceText,
                    onReferenceTextChange = { voiceReferenceText = it },
                    isUploadingReference = isUploadingVoiceReference,
                    isDesigningVoice = isDesigningVoice,
                    enabled = !editBlocked,
                    onPreviewDesignVoice = { requestVoiceDesign("preview") },
                    onReplaceDesignVoice = { requestVoiceDesign("replace") },
                    onPickReferenceAudio = {
                        if (editBlocked) showEditBlockedToast() else voiceAudioPickerLauncher.launch("audio/*")
                    },
                    onRemoveReferenceAudio = {
                        voiceReferenceAudioUrl = ""
                        voiceId = ""
                        voiceCloneStatus = ""
                    },
                    onDisabledClick = ::showEditBlockedToast
                )
            }

            Spacer(Modifier.height(12.dp))

            // 角色设定卡片
            SettingsCard {
                CardSectionTitleWithCount("角色详细设定", prompt.length)
                MultilineEditItem(
                    value = prompt,
                    onValueChange = { prompt = it },
                    placeholder = "详细描述角色的性格、背景、说话方式...",
                    minLines = 4,
                    maxLines = 8,
                    enabled = !editBlocked,
                    onDisabledClick = ::showEditBlockedToast
                )
            }

            Spacer(Modifier.height(24.dp))

            if (showCropDialog && rawAvatarBitmap != null) {
                AvatarCropDialog(
                    source = rawAvatarBitmap!!,
                    onDismiss = { showCropDialog = false },
                    onConfirm = { croppedDataUrl ->
                        avatarDataUrl = croppedDataUrl
                        showCropDialog = false
                    }
                )
            }

            if (nameError) {
                Text(
                    "请输入角色名称",
                    color = ErrorColor,
                    style = MaterialTheme.typography.bodySmall,
                    modifier = Modifier.padding(horizontal = 24.dp)
                )
                Spacer(Modifier.height(12.dp))
            }

            if (showExitConfirmDialog) {
                PonyConfirmDialog(
                    title = "确认退出",
                    message = "角色信息不全，退出将不保存，确认退出吗？",
                    confirmText = "退出",
                    actionStyle = PonyDialogActionStyle.Danger,
                    onConfirm = {
                        showExitConfirmDialog = false
                        onNavigateBack()
                    },
                    onDismiss = { showExitConfirmDialog = false }
                )
            }
        }
    }
}

@Composable
private fun Icon(
    imageVector: ImageVector,
    contentDescription: String?,
    modifier: Modifier = Modifier,
    tint: Color = LocalContentColor.current
) {
    ScaledIcon(
        imageVector = imageVector,
        contentDescription = contentDescription,
        modifier = modifier,
        tint = tint
    )
}

