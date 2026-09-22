package top.ponychat.webview.ui.settings

import android.util.Base64
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.Logout
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.mutableFloatStateOf
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import kotlin.math.roundToInt
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.luminance
import top.ponychat.webview.util.formatErrorForDisplay
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.viewmodel.compose.viewModel
import top.ponychat.webview.data.model.QuotaInfo
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.ui.character.CharacterAvatar
import top.ponychat.webview.ui.character.pickFallbackApiBase
import top.ponychat.webview.ui.common.PonyConfirmDialog
import top.ponychat.webview.ui.common.PonyDialogActionStyle
import top.ponychat.webview.ui.common.PonyTopBar
import top.ponychat.webview.ui.common.SystemNavigationBarColorEffect
import top.ponychat.webview.ui.common.focusAwareBringIntoView
import top.ponychat.webview.ui.theme.*
import top.ponychat.webview.util.RoleNotificationHelper

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(
    prefs: AppPreferences,
    onThemeChanged: (Boolean) -> Unit = {},
    onFontScaleChanged: (Float) -> Unit = {},
    onNavigateBack: () -> Unit,
    onNavigateToProfileEdit: () -> Unit = {},
    onNavigateToNetwork: () -> Unit = {},
    isCheckingUpdate: Boolean = false,
    onCheckUpdate: () -> Unit = {},
    onLogout: () -> Unit
) {
    val context = LocalContext.current
    val viewModel: SettingsViewModel = viewModel()
    val uiState by viewModel.uiState.collectAsState()
    val appVersionName = remember(context) {
        runCatching {
            val pkg = context.packageName
            val info = context.packageManager.getPackageInfo(pkg, 0)
            info.versionName ?: "未知版本"
        }.getOrDefault("未知版本")
    }

    LaunchedEffect(Unit) {
        viewModel.init(prefs)
        viewModel.loadProfile()
    }

    var showLogoutDialog by remember { mutableStateOf(false) }
    var showResetConfirmDialog by remember { mutableStateOf(false) }
    var showClearCacheConfirmDialog by remember { mutableStateOf(false) }
    var isDarkTheme by remember { mutableStateOf(prefs.isDarkTheme) }
    var fontScale by remember { mutableFloatStateOf(prefs.fontScale) }
    var memoryEnabled by remember { mutableStateOf(prefs.memoryEnabled) }
    var crisisHotlineEnabled by remember { mutableStateOf(prefs.crisisHotlineEnabled) }
    var proactiveMessagesEnabled by remember { mutableStateOf(if (prefs.memoryEnabled) prefs.proactiveMessagesEnabled else false) }
    var proactiveFrequency by remember { mutableStateOf(prefs.proactiveFrequency) }
    var messageVibrationEnabled by remember { mutableStateOf(prefs.messageVibrationEnabled) }
    val iconScale = LocalFontScale.current
    val leadingIconSize = 20.dp * iconScale
    val snackbarHostState = top.ponychat.webview.CustomToast.current
    val scope = rememberCoroutineScope()

    LaunchedEffect(prefs) {
        isDarkTheme = prefs.isDarkTheme
        fontScale = prefs.fontScale
    }

    LaunchedEffect(memoryEnabled) {
        if (!memoryEnabled && proactiveMessagesEnabled) {
            proactiveMessagesEnabled = false
            prefs.proactiveMessagesEnabled = false
        }
    }

    // 退出页面时才将后端调度相关设置同步到服务端，避免每次操作都消耗带宽
    val latestMemoryEnabled = rememberUpdatedState(memoryEnabled)
    val latestProactiveEnabled = rememberUpdatedState(proactiveMessagesEnabled)
    val latestProactiveFrequency = rememberUpdatedState(proactiveFrequency)
    DisposableEffect(Unit) {
        onDispose {
            viewModel.syncAiBackendSettings(
                latestMemoryEnabled.value,
                latestMemoryEnabled.value && latestProactiveEnabled.value,
                latestProactiveFrequency.value
            )
        }
    }

    val settingsNavigationBarColor = MaterialTheme.colorScheme.background
    SystemNavigationBarColorEffect(
        color = settingsNavigationBarColor,
        useDarkIcons = settingsNavigationBarColor.luminance() > 0.5f
    )

    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        topBar = {
            PonyTopBar(
                title = "设置",
                onNavigateBack = onNavigateBack
            ) {
                if (uiState.isSaving) {
                    CircularProgressIndicator(
                        modifier = Modifier.size(20.dp),
                        strokeWidth = 2.dp,
                        color = Primary
                    )
                }
            }
        }
    ) { paddingValues ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(paddingValues)
                .imePadding()
                .verticalScroll(rememberScrollState())
        ) {
            // 用户信息区域
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .clickable { onNavigateToProfileEdit() }
                    .padding(vertical = 20.dp),
                horizontalAlignment = Alignment.CenterHorizontally
            ) {
                CharacterAvatar(
                    avatarUrl = prefs.avatar,
                    name = prefs.nickname.ifBlank { prefs.username },
                    apiBase = prefs.effectiveApiBase(),
                    fallbackApiBase = pickFallbackApiBase(prefs.effectiveApiBase(), prefs.wanUrl, prefs.lanUrl),
                    size = 82
                )
                Spacer(Modifier.height(10.dp))
                Text(
                    prefs.nickname.ifBlank { prefs.username },
                    style = MaterialTheme.typography.headlineSmall,
                    fontWeight = FontWeight.SemiBold,
                    color = MaterialTheme.colorScheme.onBackground
                )
                if (uiState.bio.isNotBlank()) {
                    Spacer(Modifier.height(4.dp))
                    Text(
                        uiState.bio,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.6f),
                        maxLines = 2
                    )
                }
                Spacer(Modifier.height(6.dp))
                Text(
                    "点击编辑资料 >",
                    style = MaterialTheme.typography.bodySmall,
                    color = Primary
                )
            }

            uiState.saveError?.let { err ->
                Text(
                    formatErrorForDisplay(err),
                    color = ErrorColor,
                    style = MaterialTheme.typography.bodySmall,
                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp)
                )
            }
            uiState.saveSuccess?.let { msg ->
                Text(msg, color = Primary, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp))
            }

            Spacer(Modifier.height(8.dp))

            // 订阅等级 & 今日用量
            SettingsScreenSectionTitle("订阅")
            MembershipCard(
                quotaInfo = uiState.quotaInfo,
                isLoading = uiState.isLoadingQuota,
                fallbackMembershipType = prefs.membershipType
            )

            Spacer(Modifier.height(12.dp))

            // 显示设置
            SettingsScreenSectionTitle("显示")
            SettingsScreenCard {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 16.dp, vertical = 12.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Icon(Icons.Filled.DarkMode, contentDescription = null, tint = Primary, modifier = Modifier.size(leadingIconSize))
                    Spacer(Modifier.width(12.dp))
                    Text("深色主题", style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.onBackground, modifier = Modifier.weight(1f))
                    ScaledSwitch(
                        checked = isDarkTheme,
                        onCheckedChange = {
                            isDarkTheme = it
                            prefs.isDarkTheme = it
                            onThemeChanged(it)
                        },
                        colors = SwitchDefaults.colors(
                            checkedThumbColor = androidx.compose.ui.graphics.Color.White,
                            checkedTrackColor = Primary
                        )
                    )
                }
                SettingsScreenCardDivider()
                Column(modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(Icons.Filled.FormatSize, contentDescription = null, tint = Primary, modifier = Modifier.size(leadingIconSize))
                        Spacer(Modifier.width(12.dp))
                        Text("字体大小", style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.onBackground)
                    }
                    Spacer(Modifier.height(8.dp))
                    var sliderValue by remember { mutableFloatStateOf(fontScale) }
                    val haptic = LocalHapticFeedback.current
                    var lastFontStep by remember { mutableIntStateOf(((fontScale - 0.85f) * 20f).roundToInt()) }
                    Slider(
                        value = sliderValue,
                        onValueChange = { v ->
                            sliderValue = v
                            val step = ((v - 0.85f) * 20f).roundToInt()
                            if (step != lastFontStep) {
                                lastFontStep = step
                                haptic.performHapticFeedback(HapticFeedbackType.TextHandleMove)
                            }
                        },
                        onValueChangeFinished = {
                            fontScale = sliderValue
                            prefs.fontScale = sliderValue
                            onFontScaleChanged(sliderValue)
                        },
                        valueRange = 0.85f..1.25f,
                        steps = 7,
                        colors = SliderDefaults.colors(thumbColor = Primary, activeTrackColor = Primary)
                    )
                    Text(
                        text = when {
                            sliderValue < 0.95f -> "小"
                            sliderValue > 1.1f -> "大"
                            else -> "标准"
                        } + " (${(sliderValue * 100).toInt()}%)",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.bodySmall
                    )
                }
            }

            Spacer(Modifier.height(12.dp))

            // 角色列表设置
            SettingsScreenSectionTitle("角色列表")
            SettingsScreenCard {
                var characterSort by remember { mutableStateOf(prefs.characterSort) }
                Column(modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(Icons.Filled.SortByAlpha, contentDescription = null, tint = Primary, modifier = Modifier.size(leadingIconSize))
                        Spacer(Modifier.width(12.dp))
                        Text("角色排序方式", style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.onBackground)
                    }
                    Spacer(Modifier.height(8.dp))
                    SingleChoiceSegmentedButtonRow(modifier = Modifier.fillMaxWidth()) {
                        SegmentedButton(
                            selected = characterSort == "last_chat",
                            onClick = { characterSort = "last_chat"; prefs.characterSort = "last_chat" },
                            shape = SegmentedButtonDefaults.itemShape(0, 3)
                        ) { Text("最近对话", style = MaterialTheme.typography.labelMedium) }
                        SegmentedButton(
                            selected = characterSort == "name",
                            onClick = { characterSort = "name"; prefs.characterSort = "name" },
                            shape = SegmentedButtonDefaults.itemShape(1, 3)
                        ) { Text("名称", style = MaterialTheme.typography.labelMedium) }
                        SegmentedButton(
                            selected = characterSort == "manual",
                            onClick = { characterSort = "manual"; prefs.characterSort = "manual" },
                            shape = SegmentedButtonDefaults.itemShape(2, 3)
                        ) { Text("手动排序", style = MaterialTheme.typography.labelMedium) }
                    }
                    Spacer(Modifier.height(4.dp))
                    Text(
                        text = when (characterSort) {
                            "last_chat" -> "按最近对话时间降序（默认）"
                            "name" -> "按角色名称字母序排列"
                            "manual" -> "长按角色头像拖拽排序"
                            else -> "按最近对话时间降序（默认）"
                        },
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.6f)
                    )
                }
            }

            Spacer(Modifier.height(12.dp))

            // 网络设置摘要（固定公网）
            SettingsScreenSectionTitle("网络")
            SettingsScreenCard {
                SettingsScreenRow(
                    icon = Icons.Filled.Public,
                    title = "服务器",
                    value = AppPreferences.DEFAULT_WAN_URL,
                    maxLines = 2
                )
                SettingsScreenCardDivider()
                SettingsScreenRow(
                    icon = Icons.Filled.Link,
                    title = "连接方式",
                    value = "固定公网"
                )
                SettingsScreenCardDivider()
                SettingsScreenRow(
                    icon = Icons.Filled.Speed,
                    title = "网络状态",
                    value = "${uiState.networkType} / ${uiState.pingMs?.let { "${it}ms" } ?: "--"}"
                )
                SettingsScreenCardDivider()
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 4.dp, vertical = 2.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Spacer(Modifier.weight(1f))
                    TextButton(
                        onClick = { viewModel.refreshLanAndTest() },
                        enabled = !uiState.isTestingNetwork,
                        contentPadding = PaddingValues(horizontal = 12.dp, vertical = 8.dp)
                    ) {
                        if (uiState.isTestingNetwork) {
                            CircularProgressIndicator(modifier = Modifier.size(14.dp), strokeWidth = 2.dp)
                            Spacer(Modifier.width(4.dp))
                        }
                        Text(
                            if (uiState.isTestingNetwork) "测试中" else "测速",
                            style = MaterialTheme.typography.labelMedium
                        )
                    }
                    TextButton(
                        onClick = onNavigateToNetwork,
                        contentPadding = PaddingValues(horizontal = 12.dp, vertical = 8.dp)
                    ) {
                        Text("查看详情", color = Primary, style = MaterialTheme.typography.labelMedium)
                    }
                }
            }

            Spacer(Modifier.height(12.dp))

            // 上下文：累计用量统计（表格形式）+ 说明
            SettingsScreenSectionTitle("上下文")
            SettingsScreenCard {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 16.dp, vertical = 12.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp)
                ) {
                    if (uiState.isLoadingUsage) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            CircularProgressIndicator(modifier = Modifier.size(18.dp), strokeWidth = 2.dp, color = Primary)
                            Spacer(Modifier.width(10.dp))
                            Text("加载用量统计…", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                    } else {
                        uiState.usageStats?.let { u ->
                            ContextUsageTable(
                                inputTokens = u.inputTokens,
                                outputTokens = u.outputTokens
                            )
                        } ?: run {
                            Text(
                                "用量统计加载失败",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.8f)
                            )
                        }
                    }
                }
            }

            Spacer(Modifier.height(12.dp))

            // AI 功能
            SettingsScreenSectionTitle("AI 功能")
            SettingsScreenCard {
                NormalEngineSetting(prefs)
                SettingsScreenCardDivider()
                // 角色长期记忆
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 16.dp, vertical = 14.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Icon(
                        Icons.Filled.Psychology,
                        contentDescription = null,
                        tint = Primary,
                        modifier = Modifier.size(leadingIconSize)
                    )
                    Spacer(Modifier.width(12.dp))
                    Column(modifier = Modifier.weight(1f)) {
                        Text(
                            "角色长期记忆",
                            style = MaterialTheme.typography.titleSmall,
                            color = MaterialTheme.colorScheme.onBackground
                        )
                        Text(
                            if (memoryEnabled) "角色会记住你们的对话内容与偏好"
                            else "已关闭，角色每次对话将不保留记忆",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                    ScaledSwitch(
                        checked = memoryEnabled,
                        onCheckedChange = {
                            memoryEnabled = it
                            prefs.memoryEnabled = it
                        },
                        colors = SwitchDefaults.colors(
                            checkedThumbColor = androidx.compose.ui.graphics.Color.White,
                            checkedTrackColor = Primary
                        )
                    )
                }

                SettingsScreenCardDivider()

                // 角色主动消息
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 16.dp, vertical = 14.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Icon(
                        Icons.Filled.NotificationsActive,
                        contentDescription = null,
                        tint = Primary,
                        modifier = Modifier.size(leadingIconSize)
                    )
                    Spacer(Modifier.width(12.dp))
                    Column(modifier = Modifier.weight(1f)) {
                        Text(
                            "角色主动消息",
                            style = MaterialTheme.typography.titleSmall,
                            color = MaterialTheme.colorScheme.onBackground
                        )
                        Text(
                            if (!memoryEnabled) "长期记忆关闭时不可用"
                            else if (proactiveMessagesEnabled) "角色会在特定时刻主动向你发消息"
                            else "已关闭，角色不会主动发起消息",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                    ScaledSwitch(
                        checked = memoryEnabled && proactiveMessagesEnabled,
                        onCheckedChange = {
                            proactiveMessagesEnabled = it
                            prefs.proactiveMessagesEnabled = it
                        },
                        enabled = memoryEnabled,
                        colors = SwitchDefaults.colors(
                            checkedThumbColor = androidx.compose.ui.graphics.Color.White,
                            checkedTrackColor = Primary
                        )
                    )
                }

                // 消息频率（仅开启时显示）
                if (memoryEnabled && proactiveMessagesEnabled) {
                    SettingsScreenCardDivider()
                    Column(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 16.dp, vertical = 12.dp)
                    ) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Icon(Icons.Filled.Tune, contentDescription = null, tint = Primary, modifier = Modifier.size(leadingIconSize))
                            Spacer(Modifier.width(12.dp))
                            Text("消息频率", style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.onBackground)
                        }
                        Spacer(Modifier.height(8.dp))
                        val freqKeys = listOf("low", "normal", "high")
                        val initFreqFloat = freqKeys.indexOf(proactiveFrequency).takeIf { it >= 0 }?.toFloat() ?: 1f
                        var sliderFreq by remember(proactiveFrequency) { mutableFloatStateOf(initFreqFloat) }
                        val hapticFreq = LocalHapticFeedback.current
                        var lastFreqStep by remember { mutableIntStateOf(initFreqFloat.roundToInt()) }
                        Slider(
                            value = sliderFreq,
                            onValueChange = { v ->
                                sliderFreq = v
                                val step = v.roundToInt()
                                if (step != lastFreqStep) {
                                    lastFreqStep = step
                                    hapticFreq.performHapticFeedback(HapticFeedbackType.TextHandleMove)
                                }
                            },
                            onValueChangeFinished = {
                                val key = freqKeys.getOrElse(sliderFreq.roundToInt()) { "normal" }
                                proactiveFrequency = key
                                prefs.proactiveFrequency = key
                            },
                            valueRange = 0f..2f,
                            steps = 1,
                            colors = SliderDefaults.colors(thumbColor = Primary, activeTrackColor = Primary)
                        )
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween
                        ) {
                            Text("少", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            Text("正常", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            Text("多", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                        Spacer(Modifier.height(4.dp))
                        Text(
                            when (proactiveFrequency) {
                                "low"  -> "冷却时间翻倍，减少打扰"
                                "high" -> "冷却时间减半，更频繁互动"
                                else   -> "默认触发间隔"
                            },
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                }
            }

            Spacer(Modifier.height(12.dp))

            SettingsScreenSectionTitle("消息提醒")
            SettingsScreenCard {
                val lifecycleOwner = LocalLifecycleOwner.current
                var notifBlockHint by remember {
                    mutableStateOf(RoleNotificationHelper.roleNotificationBlockHint(context))
                }
                DisposableEffect(lifecycleOwner) {
                    val obs = LifecycleEventObserver { _, event ->
                        if (event == Lifecycle.Event.ON_RESUME) {
                            notifBlockHint = RoleNotificationHelper.roleNotificationBlockHint(context)
                        }
                    }
                    lifecycleOwner.lifecycle.addObserver(obs)
                    onDispose { lifecycleOwner.lifecycle.removeObserver(obs) }
                }
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 16.dp, vertical = 14.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp)
                ) {
                    val notificationsReady = notifBlockHint == null
                    val statusColor = if (notificationsReady) Color(0xFF22C55E) else Color(0xFFF59E0B)
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Surface(
                            shape = CircleShape,
                            color = statusColor.copy(alpha = 0.14f)
                        ) {
                            Icon(
                                if (notificationsReady) Icons.Filled.NotificationsActive else Icons.Filled.NotificationsOff,
                                contentDescription = null,
                                tint = statusColor,
                                modifier = Modifier
                                    .padding(8.dp)
                                    .size(leadingIconSize)
                            )
                        }
                        Spacer(Modifier.width(12.dp))
                        Column(modifier = Modifier.weight(1f)) {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Text(
                                    "系统通知",
                                    style = MaterialTheme.typography.titleSmall,
                                    color = MaterialTheme.colorScheme.onBackground
                                )
                                Spacer(Modifier.width(8.dp))
                                Surface(
                                    shape = RoundedCornerShape(999.dp),
                                    color = statusColor.copy(alpha = 0.12f)
                                ) {
                                    Text(
                                        if (notificationsReady) "已就绪" else "需设置",
                                        style = MaterialTheme.typography.labelSmall,
                                        color = statusColor,
                                        fontWeight = FontWeight.SemiBold,
                                        modifier = Modifier.padding(horizontal = 8.dp, vertical = 2.dp)
                                    )
                                }
                            }
                            Spacer(Modifier.height(3.dp))
                            Text(
                                if (notificationsReady) "通知栏、锁屏和铃声提醒可正常使用"
                                else "去系统设置开启通知和「角色消息」提醒",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                lineHeight = 18.sp
                            )
                        }
                    }
                    OutlinedButton(
                        onClick = { RoleNotificationHelper.openAppNotificationSettings(context) },
                        modifier = Modifier.fillMaxWidth(),
                        shape = RoundedCornerShape(10.dp),
                        border = BorderStroke(1.dp, Primary.copy(alpha = 0.45f)),
                        contentPadding = PaddingValues(horizontal = 12.dp, vertical = 9.dp)
                    ) {
                        Icon(
                            Icons.Filled.Settings,
                            contentDescription = null,
                            tint = Primary,
                            modifier = Modifier.size(16.dp)
                        )
                        Spacer(Modifier.width(8.dp))
                        Text("打开通知设置", color = Primary, style = MaterialTheme.typography.labelLarge)
                    }
                }
                SettingsScreenCardDivider()
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 16.dp, vertical = 14.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Icon(
                        Icons.Filled.Vibration,
                        contentDescription = null,
                        tint = Primary,
                        modifier = Modifier.size(leadingIconSize)
                    )
                    Spacer(Modifier.width(12.dp))
                    Column(modifier = Modifier.weight(1f)) {
                        Text(
                            "消息震动",
                            style = MaterialTheme.typography.titleSmall,
                            color = MaterialTheme.colorScheme.onBackground
                        )
                        Text(
                            if (messageVibrationEnabled) "收到 AI 消息时短震两下"
                            else "已关闭，收到 AI 消息时不震动",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                    ScaledSwitch(
                        checked = messageVibrationEnabled,
                        onCheckedChange = {
                            messageVibrationEnabled = it
                            prefs.messageVibrationEnabled = it
                        },
                        colors = SwitchDefaults.colors(
                            checkedThumbColor = androidx.compose.ui.graphics.Color.White,
                            checkedTrackColor = Primary
                        )
                    )
                }
            }

            Spacer(Modifier.height(12.dp))

            // 安全
            SettingsScreenSectionTitle("安全")
            SettingsScreenCard {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 16.dp, vertical = 14.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Icon(
                        Icons.Filled.HealthAndSafety,
                        contentDescription = null,
                        tint = Color(0xFF22C55E),
                        modifier = Modifier.size(leadingIconSize)
                    )
                    Spacer(Modifier.width(12.dp))
                    Column(modifier = Modifier.weight(1f)) {
                        Text(
                            "危机援助提示",
                            style = MaterialTheme.typography.titleSmall,
                            color = MaterialTheme.colorScheme.onBackground
                        )
                        Text(
                            if (crisisHotlineEnabled) "检测到极端情绪时显示心理援助热线"
                            else "已关闭，不再显示心理援助信息",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                    ScaledSwitch(
                        checked = crisisHotlineEnabled,
                        onCheckedChange = {
                            crisisHotlineEnabled = it
                            prefs.crisisHotlineEnabled = it
                        },
                        colors = SwitchDefaults.colors(
                            checkedThumbColor = androidx.compose.ui.graphics.Color.White,
                            checkedTrackColor = Color(0xFF22C55E)
                        )
                    )
                }
            }

            Spacer(Modifier.height(12.dp))

            // 调试模式
            var debugMode by remember { mutableStateOf(prefs.debugMode) }
            SettingsScreenSectionTitle("开发者")
            SettingsScreenCard {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 16.dp, vertical = 12.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Icon(
                        Icons.Filled.BugReport,
                        contentDescription = null,
                        tint = Color(0xFFF97316),
                        modifier = Modifier.size(leadingIconSize)
                    )
                    Spacer(Modifier.width(12.dp))
                    Column(modifier = Modifier.weight(1f)) {
                        Text(
                            "调试模式",
                            style = MaterialTheme.typography.titleSmall,
                            color = MaterialTheme.colorScheme.onBackground
                        )
                        if (debugMode) {
                            Text(
                                "对话设置中将显示调试板块",
                                style = MaterialTheme.typography.bodySmall,
                                color = Color(0xFFF97316).copy(alpha = 0.8f)
                            )
                        }
                    }
                    ScaledSwitch(
                        checked = debugMode,
                        onCheckedChange = {
                            debugMode = it
                            prefs.debugMode = it
                        },
                        colors = SwitchDefaults.colors(
                            checkedThumbColor = androidx.compose.ui.graphics.Color.White,
                            checkedTrackColor = Color(0xFFF97316)
                        )
                    )
                }

            }

            Spacer(Modifier.height(12.dp))

            // 关于（排第三）
            SettingsScreenSectionTitle("关于")
            SettingsScreenCard {
                SettingsScreenRow(
                    icon = Icons.Filled.Info,
                    title = "版本",
                    value = "PonyChat $appVersionName"
                )
                SettingsScreenCardDivider()
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 16.dp, vertical = 12.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Icon(Icons.Filled.SystemUpdate, contentDescription = null, tint = Primary, modifier = Modifier.size(leadingIconSize))
                    Spacer(Modifier.width(12.dp))
                    Column(modifier = Modifier.weight(1f)) {
                        Text(
                            "应用更新",
                            style = MaterialTheme.typography.titleSmall,
                            color = MaterialTheme.colorScheme.onBackground
                        )
                        Text(
                            if (isCheckingUpdate) "正在检查新版本…" else "检查是否有新版可用",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                    TextButton(
                        onClick = onCheckUpdate,
                        enabled = !isCheckingUpdate,
                        contentPadding = PaddingValues(horizontal = 8.dp, vertical = 6.dp)
                    ) {
                        if (isCheckingUpdate) {
                            CircularProgressIndicator(
                                modifier = Modifier.size(14.dp),
                                strokeWidth = 2.dp,
                                color = Primary
                            )
                            Spacer(Modifier.width(6.dp))
                        }
                        Text(
                            if (isCheckingUpdate) "检查中" else "检查更新",
                            color = if (isCheckingUpdate) MaterialTheme.colorScheme.onSurfaceVariant else Primary,
                            style = MaterialTheme.typography.labelMedium
                        )
                    }
                }
                SettingsScreenCardDivider()
                SettingsScreenRow(
                    icon = Icons.Filled.Storage,
                    title = "缓存策略",
                    value = "本地缓存 + 自动路由容灾"
                )
            }

            Spacer(Modifier.height(12.dp))

            // 重置与清空缓存
            SettingsScreenSectionTitle("数据")
            SettingsScreenCard {
                // 统计信息展示行
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 16.dp, vertical = 14.dp),
                    horizontalArrangement = Arrangement.SpaceEvenly,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    StorageStatItem(
                        icon = Icons.Filled.Person,
                        label = "角色",
                        value = if (uiState.isLoadingStorage) "…"
                                else uiState.storageStats?.characterCount?.toString() ?: "—"
                    )
                    VerticalDivider(
                        modifier = Modifier.height(36.dp),
                        color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.15f)
                    )
                    StorageStatItem(
                        icon = Icons.Filled.ChatBubbleOutline,
                        label = "消息",
                        value = if (uiState.isLoadingStorage) "…"
                                else uiState.storageStats?.totalMessageCount?.let {
                                    if (it >= 10000) "${it / 1000}k" else it.toString()
                                } ?: "—"
                    )
                    VerticalDivider(
                        modifier = Modifier.height(36.dp),
                        color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.15f)
                    )
                    StorageStatItem(
                        icon = Icons.Filled.Storage,
                        label = "占用",
                        value = if (uiState.isLoadingStorage) "…"
                                else uiState.storageStats?.estimatedSizeBytes?.let { bytes ->
                                    when {
                                        bytes >= 1024 * 1024 -> String.format("%.1f MB", bytes / (1024.0 * 1024.0))
                                        bytes >= 1024 -> String.format("%.1f KB", bytes / 1024.0)
                                        else -> "${bytes} B"
                                    }
                                } ?: "—"
                    )
                }
                SettingsScreenCardDivider()
                Column(
                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp)
                ) {
                    top.ponychat.webview.ui.common.PonyButton(
                        text = "重置所有设置",
                        onClick = { showResetConfirmDialog = true },
                        style = top.ponychat.webview.ui.common.PonyButtonStyle.Warning,
                        icon = { Icon(Icons.Filled.Refresh, contentDescription = null, modifier = Modifier.size(leadingIconSize)) }
                    )
                    top.ponychat.webview.ui.common.PonyButton(
                        text = "清空缓存并刷新",
                        onClick = { showClearCacheConfirmDialog = true },
                        style = top.ponychat.webview.ui.common.PonyButtonStyle.Danger,
                        icon = { Icon(Icons.Filled.Delete, contentDescription = null, modifier = Modifier.size(leadingIconSize)) }
                    )
                }
            }

            Spacer(Modifier.height(20.dp))

            // 退出登录
            Box(modifier = Modifier.padding(horizontal = 12.dp)) {
                top.ponychat.webview.ui.common.PonyButton(
                    text = "退出登录",
                    onClick = { showLogoutDialog = true },
                    style = top.ponychat.webview.ui.common.PonyButtonStyle.Danger,
                    icon = { Icon(Icons.AutoMirrored.Filled.Logout, contentDescription = null, modifier = Modifier.size(leadingIconSize)) }
                )
            }

            Spacer(Modifier.height(32.dp))
        }
    }

    // 退出登录确认
    if (showLogoutDialog) {
        PonyConfirmDialog(
            title = "退出登录",
            message = "确认退出当前账号？",
            confirmText = "退出",
            actionStyle = PonyDialogActionStyle.Danger,
            onDismiss = { showLogoutDialog = false },
            onConfirm = {
                showLogoutDialog = false
                prefs.logout()
                onLogout()
            }
        )
    }

    // 重置所有设置确认
    if (showResetConfirmDialog) {
        PonyConfirmDialog(
            title = "确认重置",
            message = "确定要恢复所有默认设置吗？此操作无法撤销。",
            confirmText = "确认重置",
            actionStyle = PonyDialogActionStyle.Danger,
            onDismiss = { showResetConfirmDialog = false },
            onConfirm = {
                viewModel.resetSettings()
                isDarkTheme = prefs.isDarkTheme
                fontScale = prefs.fontScale
                onThemeChanged(prefs.isDarkTheme)
                onFontScaleChanged(prefs.fontScale)
                showResetConfirmDialog = false
                scope.launch {
                    snackbarHostState.showSnackbar("设置已重置")
                }
            }
        )
    }

    // 清空缓存确认
    if (showClearCacheConfirmDialog) {
        PonyConfirmDialog(
            title = "清空缓存",
            message = "将清除本地对话与角色大厅缓存，登录状态保留。建议完成后重启应用。",
            confirmText = "清空",
            onDismiss = { showClearCacheConfirmDialog = false },
            onConfirm = {
                viewModel.clearCache()
                showClearCacheConfirmDialog = false
                scope.launch {
                    snackbarHostState.showSnackbar("缓存已清空，建议重启应用生效")
                }
            }
        )
    }

}
