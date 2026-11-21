package top.ponychat.webview.ui.settings

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardOptions
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
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import top.ponychat.webview.ui.theme.ScaledSwitch
import androidx.compose.ui.unit.sp
import androidx.lifecycle.viewmodel.compose.viewModel
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.ui.common.adaptivePopupMenuBorder
import top.ponychat.webview.ui.common.adaptivePopupMenuContainerColor
import top.ponychat.webview.ui.common.adaptivePopupMenuContentColor
import top.ponychat.webview.ui.common.AvatarCropDialog
import top.ponychat.webview.ui.common.PonyAvatar
import top.ponychat.webview.ui.common.PonyTopBar
import top.ponychat.webview.ui.common.WheelDatePickerDialog
import top.ponychat.webview.ui.common.focusAwareBringIntoView
import top.ponychat.webview.ui.theme.*
import top.ponychat.webview.util.formatErrorForDisplay
import java.util.Calendar

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ProfileEditScreen(
    prefs: AppPreferences,
    onNavigateBack: () -> Unit
) {
    val viewModel: SettingsViewModel = viewModel()
    val uiState by viewModel.uiState.collectAsState()
    val context = LocalContext.current

    LaunchedEffect(prefs) {
        viewModel.init(prefs)
        viewModel.loadProfile()
    }

    var nickname by remember { mutableStateOf(uiState.nickname.ifBlank { prefs.nickname }) }
    var bio by remember { mutableStateOf(uiState.bio.ifBlank { prefs.userBio }) }
    var personalSetting by remember { mutableStateOf(uiState.personalSetting) }
    val defaultSpeciesOption = "人类"
    val customSpeciesOption = "自定义"
    val speciesPresetOptions = listOf("人类", "陆马", "飞马", "独角兽", "天角兽", customSpeciesOption)

    fun normalizeSpeciesPreset(raw: String): String =
        raw.ifBlank { defaultSpeciesOption }.takeIf { it in speciesPresetOptions } ?: defaultSpeciesOption

    fun resolveSpeciesSelection(preset: String, custom: String): String =
        if (custom.trim().isNotEmpty()) customSpeciesOption else normalizeSpeciesPreset(preset)

    var speciesPreset by remember {
        mutableStateOf(
            resolveSpeciesSelection(uiState.speciesPreset, uiState.speciesCustom)
        )
    }
    var speciesCustom by remember { mutableStateOf(uiState.speciesCustom) }
    var shareWithAi by remember { mutableStateOf(uiState.shareWithAi) }
    var showSpeciesPresetDropdown by remember { mutableStateOf(false) }
    val currentYear = Calendar.getInstance().get(Calendar.YEAR)
    val maxBirthYear = currentYear - 18
    val defaultBirthParts = remember(maxBirthYear) { DateParts(maxBirthYear, 1, 1) }
    val initialBirthParts = remember(uiState.birthDate, maxBirthYear) {
        parseBirthDateParts(uiState.birthDate) ?: defaultBirthParts
    }
    var birthDate by remember { mutableStateOf(uiState.birthDate) }
    var birthYear by remember { mutableStateOf(initialBirthParts.year) }
    var birthMonth by remember { mutableStateOf(initialBirthParts.month) }
    var birthDay by remember { mutableStateOf(initialBirthParts.day) }
    var showDatePicker by remember { mutableStateOf(false) }
    var avatarDataUrl by remember { mutableStateOf<String?>(null) }
    var showCropDialog by remember { mutableStateOf(false) }
    var rawAvatarBitmap by remember { mutableStateOf<Bitmap?>(null) }

    // 账号安全
    var currentPassword by remember { mutableStateOf("") }
    var newUsername by remember { mutableStateOf(prefs.username) }
    var newPassword by remember { mutableStateOf("") }
    var showSecuritySection by remember { mutableStateOf(false) }
    val iconScale = LocalFontScale.current
    val leadingIconSize = 20.dp * iconScale
    val smallIconSize = 14.dp * iconScale

    // 仅监听资料相关字段，避免网络测速/用量统计等无关字段变化时覆盖用户正在输入的内容
    LaunchedEffect(
        uiState.nickname, uiState.bio, uiState.personalSetting,
        uiState.speciesPreset, uiState.speciesCustom, uiState.birthDate, uiState.shareWithAi, uiState.avatar
    ) {
        nickname = uiState.nickname.ifBlank { prefs.nickname }
        bio = uiState.bio
        personalSetting = uiState.personalSetting
        speciesPreset = resolveSpeciesSelection(uiState.speciesPreset, uiState.speciesCustom)
        speciesCustom = uiState.speciesCustom
        birthDate = uiState.birthDate
        val parts = parseBirthDateParts(uiState.birthDate) ?: defaultBirthParts
        birthYear = parts.year
        birthMonth = parts.month
        birthDay = parts.day
        shareWithAi = uiState.shareWithAi
    }

    fun selectedSpeciesOption(): String =
        normalizeSpeciesPreset(speciesPreset.trim())

    fun isCustomSpeciesSelected(): Boolean =
        selectedSpeciesOption() == customSpeciesOption

    fun savedSpeciesPreset(): String =
        if (isCustomSpeciesSelected()) defaultSpeciesOption else selectedSpeciesOption()

    fun savedSpeciesCustom(): String =
        if (isCustomSpeciesSelected()) speciesCustom.trim() else ""

    fun hasProfileChanges(): Boolean {
        val initialNickname = uiState.nickname.ifBlank { prefs.nickname }.trim()
        val initialBio = uiState.bio.trim()
        val initialPersonalSetting = uiState.personalSetting.trim()
        val initialSpeciesPreset = resolveSpeciesSelection(uiState.speciesPreset, uiState.speciesCustom)
        val initialSpeciesCustom = if (initialSpeciesPreset == customSpeciesOption) uiState.speciesCustom.trim() else ""
        val initialBirthDate = uiState.birthDate.trim()
        val initialShareWithAi = uiState.shareWithAi
        val initialAvatar = uiState.avatar.ifBlank { prefs.avatar }

        return nickname.trim() != initialNickname ||
            bio.trim() != initialBio ||
            personalSetting.trim() != initialPersonalSetting ||
            selectedSpeciesOption() != initialSpeciesPreset ||
            savedSpeciesCustom() != initialSpeciesCustom ||
            birthDate.trim() != initialBirthDate ||
            shareWithAi != initialShareWithAi ||
            (avatarDataUrl != null && avatarDataUrl != initialAvatar)
    }

    var hasSavedOnExit by remember { mutableStateOf(false) }
    fun saveProfileOnExit() {
        if (hasSavedOnExit) return
        hasSavedOnExit = true
        if (!hasProfileChanges()) return
        viewModel.saveProfile(
            currentPassword = "",
            nickname = nickname.trim(),
            bio = bio.trim(),
            personalSetting = personalSetting.trim(),
            speciesPreset = savedSpeciesPreset(),
            speciesCustom = savedSpeciesCustom(),
            birthDate = birthDate.trim(),
            shareWithAi = shareWithAi,
            avatarDataUrl = avatarDataUrl
        )
    }

    fun navigateBackWithSave() {
        saveProfileOnExit()
        onNavigateBack()
    }

    BackHandler { navigateBackWithSave() }
    DisposableEffect(Unit) {
        onDispose {
            saveProfileOnExit()
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

    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        contentWindowInsets = WindowInsets(0, 0, 0, 0),
        topBar = {
            PonyTopBar(
                title = "编辑资料",
                onNavigateBack = { navigateBackWithSave() }
            )
        }
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .imePadding()
                .navigationBarsPadding()
                .verticalScroll(rememberScrollState())
        ) {
            if (uiState.saveError != null) {
                Text(
                    text = formatErrorForDisplay(uiState.saveError),
                    color = MaterialTheme.colorScheme.error,
                    style = MaterialTheme.typography.bodySmall,
                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp)
                )
            }
            // 头像区域
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(vertical = 24.dp),
                horizontalAlignment = Alignment.CenterHorizontally
            ) {
                val currentAvatar = uiState.avatar.ifBlank { prefs.avatar }
                val displayAvatar = avatarDataUrl ?: currentAvatar
                val apiBase = prefs.effectiveApiBase()

                Box(
                    modifier = Modifier
                        .size(80.dp)
                        .clickable { avatarPickerLauncher.launch("image/*") },
                    contentAlignment = Alignment.Center
                ) {
                    PonyAvatar(
                        avatarUrl = displayAvatar,
                        name = nickname.ifBlank { "?" },
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
                            modifier = Modifier.size(smallIconSize),
                            tint = Color.White
                        )
                    }
                }
            }

            // 基本信息卡片
            SettingsCard {
                EditItem(
                    label = "昵称",
                    value = nickname,
                    onValueChange = { nickname = it },
                    placeholder = "请输入昵称"
                )
                CardDivider()
                Column(modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp)) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Text("个人简介", color = MaterialTheme.colorScheme.onBackground, style = MaterialTheme.typography.titleSmall)
                        Text("${bio.length}/200", color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.7f), style = MaterialTheme.typography.bodySmall)
                    }
                    Spacer(Modifier.height(6.dp))
                    OutlinedTextField(
                        value = bio,
                        onValueChange = { if (it.length <= 200) bio = it },
                        modifier = Modifier.fillMaxWidth().focusAwareBringIntoView(),
                        minLines = 1,
                        maxLines = 2,
                        textStyle = MaterialTheme.typography.bodyMedium.copy(color = MaterialTheme.colorScheme.onBackground),
                        shape = RoundedCornerShape(10.dp),
                        colors = OutlinedTextFieldDefaults.colors(
                            focusedBorderColor = Primary,
                            unfocusedBorderColor = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.3f),
                            cursorColor = Primary,
                            focusedContainerColor = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.3f),
                            unfocusedContainerColor = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.2f)
                        )
                    )
                }
            }

            Spacer(Modifier.height(12.dp))

            // 个人设定卡片（开启「允许 AI 读取资料」时作为用户信息供模型参考）
            SettingsCard {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 16.dp, vertical = 12.dp)
                ) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Text(
                            text = "个人设定",
                            color = MaterialTheme.colorScheme.onBackground,
                            style = MaterialTheme.typography.titleSmall
                        )
                        Text(
                            text = "${personalSetting.length}/2000",
                            color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.7f),
                            style = MaterialTheme.typography.bodySmall
                        )
                    }
                    Text(
                        text = "填写个人的详细设定，开启「允许 AI 读取资料」时会作为用户信息供 AI 参考",
                        color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.7f),
                        style = MaterialTheme.typography.bodySmall,
                        modifier = Modifier.padding(top = 4.dp, bottom = 8.dp)
                    )
                    OutlinedTextField(
                        value = personalSetting,
                        onValueChange = { if (it.length <= 2000) personalSetting = it },
                        modifier = Modifier
                            .fillMaxWidth()
                            .focusAwareBringIntoView(),
                        placeholder = {
                            Text(
                                "如：性格、喜好、背景等详细设定…",
                                color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.4f),
                                style = MaterialTheme.typography.bodyMedium
                            )
                        },
                        minLines = 3,
                        maxLines = 5,
                        textStyle = MaterialTheme.typography.bodyMedium.copy(color = MaterialTheme.colorScheme.onBackground),
                        shape = RoundedCornerShape(10.dp),
                        colors = OutlinedTextFieldDefaults.colors(
                            focusedBorderColor = Primary,
                            unfocusedBorderColor = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.3f),
                            cursorColor = Primary,
                            focusedContainerColor = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.3f),
                            unfocusedContainerColor = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.2f)
                        )
                    )
                }
            }

            Spacer(Modifier.height(12.dp))

            // 种族设定卡片
            SettingsCard {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 16.dp, vertical = 14.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text(
                        text = "种族",
                        color = MaterialTheme.colorScheme.onBackground,
                        style = MaterialTheme.typography.titleSmall,
                        modifier = Modifier.width(80.dp)
                    )
                    Spacer(Modifier.weight(1f))
                    Box {
                        Row(
                            modifier = Modifier.clickable { showSpeciesPresetDropdown = true },
                            horizontalArrangement = Arrangement.End,
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Text(
                                text = speciesPreset,
                                color = MaterialTheme.colorScheme.onBackground,
                                style = MaterialTheme.typography.titleSmall
                            )
                            Spacer(Modifier.width(4.dp))
                            Icon(
                                Icons.Filled.ArrowDropDown,
                                contentDescription = "展开选项",
                                tint = MaterialTheme.colorScheme.onSurfaceVariant,
                                modifier = Modifier.size(leadingIconSize)
                            )
                        }
                        DropdownMenu(
                            expanded = showSpeciesPresetDropdown,
                            onDismissRequest = { showSpeciesPresetDropdown = false },
                            shape = RoundedCornerShape(12.dp),
                            containerColor = adaptivePopupMenuContainerColor(),
                            border = adaptivePopupMenuBorder(),
                            tonalElevation = 2.dp
                        ) {
                            speciesPresetOptions.forEach { option ->
                                DropdownMenuItem(
                                    text = {
                                        Text(
                                            option,
                                            color = adaptivePopupMenuContentColor()
                                        )
                                    },
                                    onClick = {
                                        speciesPreset = option
                                        if (option != customSpeciesOption) {
                                            speciesCustom = ""
                                        }
                                        showSpeciesPresetDropdown = false
                                    }
                                )
                            }
                        }
                    }
                }
                if (speciesPreset == customSpeciesOption) {
                    CardDivider()
                    EditItem(
                        label = "自定义",
                        value = speciesCustom,
                        onValueChange = { speciesCustom = it },
                        placeholder = "更详细的描述"
                    )
                }
                CardDivider()
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clickable { showDatePicker = true }
                        .padding(horizontal = 16.dp, vertical = 14.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text(
                        text = "生日",
                        color = MaterialTheme.colorScheme.onBackground,
                        style = MaterialTheme.typography.titleSmall,
                        modifier = Modifier.width(80.dp)
                    )
                    Spacer(Modifier.weight(1f))
                    Text(
                        text = birthDate.ifBlank { formatBirthDate(birthYear, birthMonth, birthDay) },
                        color = MaterialTheme.colorScheme.onBackground,
                        style = MaterialTheme.typography.titleSmall
                    )
                    Spacer(Modifier.width(4.dp))
                    Icon(
                        Icons.Filled.ArrowDropDown,
                        contentDescription = "选择生日",
                        tint = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.size(leadingIconSize)
                    )
                }
            }

            Spacer(Modifier.height(12.dp))

            // 隐私设置卡片
            SettingsCard {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 16.dp, vertical = 14.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Column(modifier = Modifier.weight(1f)) {
                        Text(
                            "允许 AI 读取资料",
                            color = MaterialTheme.colorScheme.onBackground,
                            style = MaterialTheme.typography.titleSmall
                        )
                        Text(
                            "AI 将根据你的资料提供个性化回复。开启后，昵称、年龄、性别、种族、个人简介、个人设定等会发送给模型供参考。",
                            color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.6f),
                            style = MaterialTheme.typography.bodySmall
                        )
                    }
                    ScaledSwitch(
                        checked = shareWithAi,
                        onCheckedChange = { shareWithAi = it },
                        colors = SwitchDefaults.colors(
                            checkedThumbColor = Color.White,
                            checkedTrackColor = Primary
                        )
                    )
                }
            }

            Spacer(Modifier.height(12.dp))

            // 账号安全卡片
            SettingsCard {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clickable { showSecuritySection = !showSecuritySection }
                        .padding(horizontal = 16.dp, vertical = 14.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text(
                        "账号安全",
                        color = MaterialTheme.colorScheme.onBackground,
                        style = MaterialTheme.typography.titleSmall,
                        modifier = Modifier.weight(1f)
                    )
                    Icon(
                        if (showSecuritySection) Icons.Filled.ExpandLess else Icons.Filled.ExpandMore,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.size(leadingIconSize)
                    )
                }

                if (showSecuritySection) {
                    CardDivider()
                    Column(
                        modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
                        verticalArrangement = Arrangement.spacedBy(8.dp)
                    ) {
                        Text(
                            "修改账号信息需要验证当前密码",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.6f)
                        )
                        SecurityInput(
                            label = "当前密码",
                            value = currentPassword,
                            onValueChange = { currentPassword = it },
                            isPassword = true
                        )
                        SecurityInput(
                            label = "新用户名",
                            value = newUsername,
                            onValueChange = { newUsername = it }
                        )
                        SecurityInput(
                            label = "新密码",
                            value = newPassword,
                            onValueChange = { newPassword = it },
                            isPassword = true
                        )
                        Spacer(Modifier.height(4.dp))
                        top.ponychat.webview.ui.common.PonyButton(
                            text = "更新账号信息",
                            onClick = {
                                if (currentPassword.isNotBlank()) {
                                    viewModel.updateSecurity(currentPassword, newUsername, newPassword)
                                    currentPassword = ""
                                    newPassword = ""
                                }
                            },
                            enabled = currentPassword.isNotBlank(),
                            style = top.ponychat.webview.ui.common.PonyButtonStyle.Secondary,
                            height = 48.dp
                        )
                        Spacer(Modifier.height(4.dp))
                    }
                }
            }

            Spacer(Modifier.height(24.dp))
        }

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

    if (showDatePicker) {
        WheelDatePickerDialog(
            title = "选择出生日期",
            minYear = (maxBirthYear - 100).coerceAtLeast(1900),
            maxYear = maxBirthYear,
            selectedYear = birthYear,
            selectedMonth = birthMonth,
            selectedDay = birthDay,
            onDateSelected = { y, m, d ->
                birthYear = y
                birthMonth = m
                birthDay = d
                birthDate = formatBirthDate(y, m, d)
                showDatePicker = false
            },
            onDismiss = { showDatePicker = false }
        )
    }
    }
}

@Composable
private fun SettingsCard(content: @Composable ColumnScope.() -> Unit) {
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 12.dp),
        shape = RoundedCornerShape(12.dp),
        color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f),
        border = androidx.compose.foundation.BorderStroke(
            1.dp,
            MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.12f)
        )
    ) {
        Column(content = content)
    }
}

@Composable
private fun CardDivider() {
    HorizontalDivider(
        modifier = Modifier.padding(start = 16.dp),
        color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.08f)
    )
}

@Composable
private fun EditItem(
    label: String,
    value: String,
    onValueChange: (String) -> Unit,
    placeholder: String = "",
    singleLine: Boolean = true,
    keyboardType: KeyboardType = KeyboardType.Text
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = if (singleLine) 14.dp else 12.dp),
        verticalAlignment = if (singleLine) Alignment.CenterVertically else Alignment.Top
    ) {
        Text(
            text = label,
            color = MaterialTheme.colorScheme.onBackground,
            style = MaterialTheme.typography.titleSmall,
            modifier = Modifier.width(80.dp)
        )
        BasicTextField(
            value = value,
            onValueChange = onValueChange,
            modifier = Modifier
                .weight(1f)
                .focusAwareBringIntoView(),
            textStyle = MaterialTheme.typography.titleSmall.copy(
                color = MaterialTheme.colorScheme.onBackground,
                textAlign = TextAlign.End
            ),
            singleLine = singleLine,
            keyboardOptions = KeyboardOptions(keyboardType = keyboardType),
            cursorBrush = SolidColor(Primary),
            decorationBox = { innerTextField ->
                Box(contentAlignment = if (singleLine) Alignment.CenterEnd else Alignment.TopEnd) {
                    if (value.isEmpty()) {
                        Text(
                            placeholder,
                            color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.4f),
                            style = MaterialTheme.typography.titleSmall,
                            textAlign = TextAlign.End
                        )
                    }
                    innerTextField()
                }
            }
        )
    }

}

private data class DateParts(val year: Int, val month: Int, val day: Int)

private fun parseBirthDateParts(value: String?): DateParts? {
    val parts = value.orEmpty().split("-")
    if (parts.size != 3) return null
    val year = parts[0].toIntOrNull() ?: return null
    val month = parts[1].toIntOrNull()?.coerceIn(1, 12) ?: return null
    val maxDay = maxDayOfMonth(year, month)
    val day = parts[2].toIntOrNull()?.coerceIn(1, maxDay) ?: return null
    return DateParts(year, month, day)
}

private fun formatBirthDate(year: Int, month: Int, day: Int): String =
    "%04d-%02d-%02d".format(year, month, day.coerceIn(1, maxDayOfMonth(year, month)))

private fun maxDayOfMonth(year: Int, month: Int): Int =
    when (month) {
        2 -> if (year % 4 == 0 && (year % 100 != 0 || year % 400 == 0)) 29 else 28
        4, 6, 9, 11 -> 30
        else -> 31
    }

@Composable
private fun SecurityInput(
    label: String,
    value: String,
    onValueChange: (String) -> Unit,
    isPassword: Boolean = false
) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(8.dp),
        color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f)
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 12.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(
                text = label,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.labelMedium,
                modifier = Modifier.width(64.dp)
            )
            BasicTextField(
                value = value,
                onValueChange = onValueChange,
                modifier = Modifier
                    .weight(1f)
                    .focusAwareBringIntoView(),
                textStyle = MaterialTheme.typography.bodyMedium.copy(
                    color = MaterialTheme.colorScheme.onBackground
                ),
                singleLine = true,
                cursorBrush = SolidColor(Primary),
                keyboardOptions = KeyboardOptions(
                    keyboardType = if (isPassword) KeyboardType.Password else KeyboardType.Text
                )
            )
        }
    }
}
