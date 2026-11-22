package top.ponychat.webview

import androidx.lifecycle.compose.collectAsStateWithLifecycle

import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.layout.heightIn

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.os.Build
import androidx.activity.compose.BackHandler
import androidx.compose.animation.AnimatedContentScope
import androidx.compose.animation.EnterTransition
import androidx.compose.animation.ExitTransition
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.tween
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.activity.ComponentActivity
import androidx.core.content.FileProvider
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavBackStackEntry
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import android.net.Uri
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.ui.graphics.Color
import androidx.compose.foundation.shape.RoundedCornerShape
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Protocol
import okhttp3.Request
import top.ponychat.webview.BuildConfig
import top.ponychat.webview.data.api.NetworkClient
import top.ponychat.webview.data.model.Character
import top.ponychat.webview.data.api.AuthEventBus
import top.ponychat.webview.data.api.ProactiveNavTarget
import top.ponychat.webview.ConnectionService
import top.ponychat.webview.data.api.SyncWebSocketManager
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.ui.auth.AuthViewModel
import top.ponychat.webview.ui.auth.LoginScreen
import top.ponychat.webview.ui.auth.RegisterScreen
import top.ponychat.webview.ui.character.CharacterEditScreen
import top.ponychat.webview.ui.character.CharacterHallScreen
import top.ponychat.webview.ui.character.MyPublishedHallScreen
import top.ponychat.webview.ui.character.CharacterProfileScreen
import top.ponychat.webview.ui.character.CharacterListScreen
import top.ponychat.webview.ui.character.CharacterViewModel
import top.ponychat.webview.ui.common.PonyHomeBottomBar
import top.ponychat.webview.ui.music.MusicPlayerScreen
import top.ponychat.webview.ui.music.MusicSearchScreen
import top.ponychat.webview.ui.music.MusicPlayerViewModel
import top.ponychat.webview.ui.music.MusicScreen
import top.ponychat.webview.ui.chat.ChatScreen
import top.ponychat.webview.ui.creation.CreationChatScreen
import top.ponychat.webview.ui.chat.ChatViewModel
import top.ponychat.webview.ui.chat.clearFailedChatRoundIfNeeded
import top.ponychat.webview.ui.chat.ConversationHistoryScreen
import top.ponychat.webview.ui.chat.MemoryScreen
import top.ponychat.webview.ui.chat.ProactiveTasksScreen
import top.ponychat.webview.ui.device.DeviceHomeScreen
import top.ponychat.webview.ui.device.DeviceCharacterPickerScreen
import top.ponychat.webview.ui.images.BooruSearchScreen
import top.ponychat.webview.ui.settings.ProfileEditScreen
import top.ponychat.webview.ui.settings.CompanionSettingsScreen
import top.ponychat.webview.ui.settings.NetworkSettingsScreen
import top.ponychat.webview.ui.settings.SettingsScreen
import top.ponychat.webview.util.formatErrorForDisplay
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.TimeUnit

object Routes {
    const val LOGIN = "login"
    const val REGISTER = "register"
    const val CHARACTER_LIST = "character_list"
    const val GAMES = "games"
    const val MUSIC = "music"
    const val MUSIC_PLAYER = "music_player"
    const val MUSIC_SEARCH = "music_search"
    const val CHARACTER_HALL = "character_hall"
    const val CHARACTER_HALL_MY_PUBLISHED = "character_hall_my_published"
    const val CHARACTER_PROFILE = "character_profile"
    const val CHARACTER_EDIT = "character_edit"
    const val CHAT = "chat"
    const val HISTORY = "history"
    const val MEMORY = "memory"
    const val PROACTIVE_TASKS = "proactive_tasks"
    const val SETTINGS = "settings"
    const val COMPANION_SETTINGS = "companion_settings"
    const val PROFILE_EDIT = "profile_edit"
    const val NETWORK_SETTINGS = "network_settings"
    const val DEVICE_HOME = "device_home"
    const val DEVICE_CHARACTER_PICKER = "device_character_picker"
    const val BOORU_SEARCH = "booru_search"

}

private const val CHAT_CHARACTER_ID = "chatCharacterId"
private const val CHAT_MODE = "chatMode"
private const val LEGACY_CREATION_ROUTE = "creation"

@Composable
fun AppNavigation(
    prefs: AppPreferences,
    isDeviceExperience: Boolean = false,
    isCompanionRuntimeReady: Boolean = false,
    companionRuntimeStatus: String = "",
    onThemeChanged: (Boolean) -> Unit = {},
    onFontScaleChanged: (Float) -> Unit = {},
    startDestination: String = if (isDeviceExperience) {
        Routes.DEVICE_HOME
    } else if (!prefs.isLoggedIn()) {
        Routes.LOGIN
    } else {
        Routes.CHARACTER_LIST
    },
    openMusicPlayer: Boolean = false,
    onMusicPlayerOpened: () -> Unit = {},
) {
    val navController = rememberNavController()
    val context = LocalContext.current
    val backStackEntry by navController.currentBackStackEntryAsState()
    val currentRoute = backStackEntry?.destination?.route
    val authViewModel: AuthViewModel = viewModel()
    val characterViewModel: CharacterViewModel = viewModel()
    val musicModel: MusicPlayerViewModel = viewModel()
    val scope = rememberCoroutineScope()
    var openPlayerJob by remember { mutableStateOf<Job?>(null) }
    fun openMusic() {
        val fromGames = navController.currentDestination?.route == Routes.GAMES
        navController.navigate(Routes.MUSIC) {
            if (fromGames) popUpTo(Routes.GAMES) { inclusive = true }
            launchSingleTop = true
            restoreState = true
        }
    }
    fun openGames() {
        val fromMusic = navController.currentDestination?.route == Routes.MUSIC
        navController.navigate(Routes.GAMES) {
            if (fromMusic) {
                popUpTo(Routes.MUSIC) {
                    inclusive = true
                    saveState = true
                }
            }
            launchSingleTop = true
        }
    }
    fun openChatList() {
        val fromMusic = navController.currentDestination?.route == Routes.MUSIC
        if (!navController.popBackStack(Routes.CHARACTER_LIST, inclusive = false, saveState = fromMusic)) {
            navController.navigate(Routes.CHARACTER_LIST) { launchSingleTop = true }
        }
    }
    fun openPlayer() {
        val source = navController.currentBackStackEntry ?: return
        openPlayerJob?.cancel()
        openPlayerJob = scope.launch {
            musicModel.awaitCurrentLyrics()
            if (navController.currentBackStackEntry === source) {
                navController.navigate(Routes.MUSIC_PLAYER) { launchSingleTop = true }
            }
        }
    }
    LaunchedEffect(currentRoute) {
        if (currentRoute in listOf(Routes.CHARACTER_LIST, Routes.MUSIC, Routes.MUSIC_PLAYER)) musicModel.connect()
    }
    LaunchedEffect(openMusicPlayer, currentRoute) {
        if (!openMusicPlayer || currentRoute == null) return@LaunchedEffect
        onMusicPlayerOpened()
        if (!prefs.isLoggedIn() || currentRoute == Routes.MUSIC_PLAYER) return@LaunchedEffect
        if (currentRoute == Routes.MUSIC_SEARCH && navController.popBackStack(Routes.MUSIC_PLAYER, inclusive = false)) {
            return@LaunchedEffect
        }
        if (currentRoute != Routes.MUSIC) openMusic()
        openPlayer()
    }
    // 各账号、角色和模式独立保存输入、消息与生成状态。
    fun getChatVm(characterId: String, mode: String): ChatViewModel {
        val activity = context as ComponentActivity
        return ViewModelProvider(activity, activity.defaultViewModelProviderFactory)
            .get("chat:${prefs.username}:$characterId:$mode", ChatViewModel::class.java)
    }

    val openedCharacters = remember { mutableStateMapOf<String, Character>() }
    val characterState by characterViewModel.state.collectAsStateWithLifecycle()
    fun chatCharacter(characterId: String): Character? =
        openedCharacters[characterId] ?: characterState.characters.firstOrNull { it.id == characterId }

    fun openChat(character: Character, mode: String = "normal", fromNotification: Boolean = false) {
        val characterId = character.id?.takeIf(String::isNotBlank) ?: return
        val initialMode = when (mode) {
            "creation", "galgame", "galgame_lock" -> mode
            else -> "normal"
        }
        openedCharacters[characterId] = character
        prefs.lastCharacterId = characterId
        prefs.chatMode = initialMode
        navController.navigate(Routes.CHAT) {
            if (fromNotification) {
                popUpTo(Routes.CHARACTER_LIST) { inclusive = false }
                launchSingleTop = true
            }
        }
        navController.currentBackStackEntry?.savedStateHandle?.apply {
            set(CHAT_CHARACTER_ID, characterId)
            set(CHAT_MODE, initialMode)
        }
    }
    fun openChatDetail(route: String, chatEntry: NavBackStackEntry) {
        navController.navigate(route)
        navController.currentBackStackEntry?.savedStateHandle?.apply {
            set(CHAT_CHARACTER_ID, chatEntry.savedStateHandle.get<String>(CHAT_CHARACTER_ID) ?: prefs.lastCharacterId)
            set(CHAT_MODE, chatEntry.savedStateHandle.get<String>(CHAT_MODE) ?: prefs.chatMode)
        }
    }
    var profileCharacter by remember { mutableStateOf<Character?>(null) }
    var editingCharacter by remember { mutableStateOf<Character?>(null) }
    var isCreatingCharacter by remember { mutableStateOf(false) }
    var lastBackPressAt by remember { mutableLongStateOf(0L) }
    val snackbarHostState = CustomToast.current

    var showUpgradeDialog by remember { mutableStateOf(false) }
    var forceUpgradeDlState by remember { mutableStateOf<ApkDownloadState>(ApkDownloadState.Idle) }

    fun clearAccountScopedUiState() {
        openedCharacters.clear()
        profileCharacter = null
        editingCharacter = null
        isCreatingCharacter = false
        navController.clearBackStack(Routes.MUSIC)
        characterViewModel.resetForAccountChange()
    }

    // ==================== 版本更新弹窗 ====================
    var showUpdateDialog by remember { mutableStateOf(false) }
    var updateLatestVersion by remember { mutableStateOf("") }
    var updateReleaseNotes by remember { mutableStateOf("") }
    var updateDownloadUrl by remember { mutableStateOf(AppPreferences.DEFAULT_WAN_URL + "/download/apk") }
    var isCheckingUpdate by remember { mutableStateOf(false) }

    suspend fun checkForAppUpdate(manual: Boolean) {
        if (isCheckingUpdate) return
        isCheckingUpdate = true
        val today = SimpleDateFormat("yyyy-MM-dd", Locale.getDefault()).format(Date())
        try {
            val resp = withContext(Dispatchers.IO) {
                NetworkClient.createApiService(prefs).getAppVersion()
            }
            if (resp.isSuccessful) {
                val body = resp.body() ?: return
                if (body.versionCode > BuildConfig.VERSION_CODE) {
                    updateLatestVersion = body.versionName
                    updateReleaseNotes = body.releaseNotes.orEmpty().trim()
                    updateDownloadUrl = body.downloadUrl
                    if (!manual) prefs.updateDialogLastDate = today
                    showUpdateDialog = true
                } else if (manual) {
                    snackbarHostState.showSnackbar("当前已是最新版本")
                }
            } else if (manual) {
                snackbarHostState.showSnackbar("检查更新失败：HTTP ${resp.code()}")
            }
        } catch (e: Exception) {
            // 网络不可用或服务端无此接口时静默忽略，不影响正常使用
            if (manual) snackbarHostState.showSnackbar("检查更新失败：${e.message?.take(40) ?: "网络异常"}")
        } finally {
            isCheckingUpdate = false
        }
    }

    LaunchedEffect(Unit) {
        val today = SimpleDateFormat("yyyy-MM-dd", Locale.getDefault()).format(Date())
        if (prefs.updateDialogLastDate == today) return@LaunchedEffect
        checkForAppUpdate(manual = false)
    }

    fun requestManualUpdateCheck() {
        scope.launch {
            checkForAppUpdate(manual = true)
        }
    }

    if (showUpdateDialog) {
        UpdateAvailableDialog(
            currentVersion = BuildConfig.VERSION_NAME,
            latestVersion = updateLatestVersion,
            releaseNotes = updateReleaseNotes,
            downloadUrl = updateDownloadUrl,
            onDismiss = { showUpdateDialog = false }
        )
    }

    if (showUpgradeDialog) {
        AlertDialog(
            onDismissRequest = {},
            title = { Text("版本已停止支持") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    when (val s = forceUpgradeDlState) {
                        is ApkDownloadState.Idle -> Text(
                            "当前版本过旧，已无法继续使用。请立即更新至最新版 PonyChat。",
                            style = MaterialTheme.typography.bodyMedium
                        )
                        is ApkDownloadState.Downloading -> Column(
                            verticalArrangement = Arrangement.spacedBy(4.dp)
                        ) {
                            Text(
                                "正在下载… ${(s.progress * 100).toInt()}%",
                                style = MaterialTheme.typography.bodyMedium
                            )
                            LinearProgressIndicator(
                                progress = { s.progress },
                                modifier = Modifier.fillMaxWidth(),
                            )
                        }
                        is ApkDownloadState.Installing -> Text(
                            "下载完成，正在启动安装…",
                            style = MaterialTheme.typography.bodyMedium
                        )
                        is ApkDownloadState.Failed -> Text(
                            "${formatErrorForDisplay("下载失败：${s.message}")}\n请重试或退出后手动前往官网更新。",
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.error
                        )
                    }
                }
            },
            confirmButton = {
                when (forceUpgradeDlState) {
                    is ApkDownloadState.Idle, is ApkDownloadState.Failed -> {
                        TextButton(onClick = {
                            forceUpgradeDlState = ApkDownloadState.Downloading(0f)
                            scope.launch {
                                try {
                                    val apkFile = downloadApkToCache(
                                        context = context,
                                        url = updateDownloadUrl,
                                        onProgress = { p ->
                                            forceUpgradeDlState = ApkDownloadState.Downloading(p)
                                        }
                                    )
                                    forceUpgradeDlState = ApkDownloadState.Installing
                                    installApk(context, apkFile)
                                } catch (e: Exception) {
                                    forceUpgradeDlState = ApkDownloadState.Failed(
                                        e.message?.take(60) ?: "未知错误"
                                    )
                                }
                            }
                        }) { Text("立即更新") }
                    }
                    is ApkDownloadState.Downloading, is ApkDownloadState.Installing -> {
                        TextButton(onClick = {}, enabled = false) { Text("下载中…") }
                    }
                }
            },
            dismissButton = {
                if (forceUpgradeDlState !is ApkDownloadState.Downloading) {
                    TextButton(onClick = { (context as? Activity)?.finish() }) { Text("退出") }
                }
            }
        )
    }

    // 监听版本升级要求事件（HTTP 426）
    LaunchedEffect(Unit) {
        AuthEventBus.upgradeRequired.collect {
            showUpgradeDialog = true
        }
    }

    // 监听异地登录强制登出事件
    LaunchedEffect(Unit) {
        AuthEventBus.forceLogout.collect { reason ->
            if (prefs.isLoggedIn() || navController.currentDestination?.route == Routes.LOGIN) return@collect
            ConnectionService.stop(context.applicationContext)
            SyncWebSocketManager.stop()
            // 账号被新登录顶下线时同步停止陪玩服务，避免陪玩悬浮窗残留
            context.stopService(Intent(context, CompanionService::class.java))
            clearAccountScopedUiState()
            authViewModel.clearLoginState()
            navController.navigate(Routes.LOGIN) {
                popUpTo(0) { inclusive = true }
                launchSingleTop = true
            }
            snackbarHostState.showSnackbar(
                if (reason == "logged_in_elsewhere") "账号已在其他地方登录，您已被登出"
                else "登录已过期，请重新登录"
            )
        }
    }

    // 监听通知点击导航：收到目标角色 ID 后，在角色列表加载完成时跳转到对应聊天页
    LaunchedEffect(Unit) {
        ProactiveNavTarget.target.collect { navTarget ->
            if (navTarget == null) return@collect
            // 等待角色列表加载完毕（最多等 3 秒）
            var waited = 0
            while (characterViewModel.state.value.characters.isEmpty() && waited < 30) {
                kotlinx.coroutines.delay(100)
                waited++
            }
            val char = characterViewModel.state.value.characters.find { it.id == navTarget.characterId }
            if (char != null) {
                openChat(char, navTarget.mode, fromNotification = true)
            }
            ProactiveNavTarget.clear()
        }
    }

    BackHandler {
        when (navController.currentDestination?.route) {
            Routes.DEVICE_HOME -> Unit
            Routes.CHARACTER_LIST -> {
                if (isDeviceExperience && navController.popBackStack()) return@BackHandler
                val now = System.currentTimeMillis()
                if (now - lastBackPressAt < 2000) {
                    (context as? Activity)?.finish()
                } else {
                    lastBackPressAt = now
                    scope.launch { snackbarHostState.showSnackbar("再按一次退出") }
                }
            }
            Routes.LOGIN -> {
                if (isDeviceExperience && navController.popBackStack()) return@BackHandler
                val now = System.currentTimeMillis()
                if (now - lastBackPressAt < 2000) {
                    (context as? Activity)?.finish()
                } else {
                    lastBackPressAt = now
                    scope.launch { snackbarHostState.showSnackbar("再按一次退出") }
                }
            }
            else -> {
                if (!navController.popBackStack()) {
                    (context as? Activity)?.finish()
                }
            }
        }
    }

    NavHost(
        navController = navController,
        startDestination = startDestination,
        exitTransition = {
            if (targetState.destination.route == Routes.MUSIC_PLAYER) ExitTransition.KeepUntilTransitionsFinished
            else fadeOut(tween(700))
        },
        popEnterTransition = {
            if (initialState.destination.route == Routes.MUSIC_PLAYER) EnterTransition.None else fadeIn(tween(700))
        },
        popExitTransition = { fadeOut(tween(700)) },
    ) {
        composable(Routes.LOGIN) {
            LoginScreen(
                viewModel = authViewModel,
                onLoginSuccess = {
                    clearAccountScopedUiState()
                    characterViewModel.loadMyCharacters()
                    val destination = if (isDeviceExperience) Routes.DEVICE_HOME else Routes.CHARACTER_LIST
                    navController.navigate(destination) {
                        if (isDeviceExperience) {
                            popUpTo(Routes.DEVICE_HOME) { inclusive = false }
                        } else {
                            popUpTo(Routes.LOGIN) { inclusive = true }
                        }
                        launchSingleTop = true
                    }
                },
                onNavigateToRegister = {
                    navController.navigate(Routes.REGISTER)
                },
                onNavigateToNetwork = {
                    navController.navigate(Routes.NETWORK_SETTINGS)
                },
                showDeviceHomeButton = isCompanionRuntimeReady,
                onNavigateToDeviceHome = {
                    navController.navigate(Routes.DEVICE_HOME) {
                        launchSingleTop = true
                    }
                },
            )
        }

        composable(Routes.REGISTER) { entry ->
            RegisterScreen(
                viewModel = authViewModel,
                onRegisterSuccess = {
                    navController.navigate(Routes.LOGIN) {
                        popUpTo(Routes.REGISTER) { inclusive = true }
                    }
                },
                onNavigateBack = { navController.popPage(entry) }
            )
        }

        composable(Routes.DEVICE_HOME) {
            val activeCharacter = characterState.characters.firstOrNull {
                it.id == prefs.lastCharacterId
            }
            DeviceHomeScreen(
                runtimeStatus = companionRuntimeStatus,
                runtimeReady = isCompanionRuntimeReady,
                activeCharacter = activeCharacter,
                avatarApiBase = prefs.activeApiBase,
                onOpenConversations = {
                    if (prefs.isLoggedIn()) {
                        characterViewModel.loadMyCharacters()
                        if (activeCharacter == null) {
                            navController.navigate(Routes.DEVICE_CHARACTER_PICKER)
                        } else {
                            openChat(activeCharacter)
                        }
                    } else {
                        navController.navigate(Routes.LOGIN)
                    }
                },
                onSwitchCharacter = {
                    if (prefs.isLoggedIn()) {
                        characterViewModel.loadMyCharacters()
                        navController.navigate(Routes.DEVICE_CHARACTER_PICKER)
                    } else {
                        navController.navigate(Routes.LOGIN)
                    }
                },
                onOpenSettings = {
                    navController.navigate(if (prefs.isLoggedIn()) Routes.SETTINGS else Routes.LOGIN)
                },
            )
        }

        composable(Routes.DEVICE_CHARACTER_PICKER) { entry ->
            DeviceCharacterPickerScreen(
                characters = characterState.characters,
                activeCharacterId = prefs.lastCharacterId,
                avatarApiBase = prefs.activeApiBase,
                isLoading = characterState.isLoading,
                onBack = { navController.popPage(entry) },
                onCharacterSelected = { character ->
                    val characterId = character.id?.takeIf(String::isNotBlank)
                        ?: return@DeviceCharacterPickerScreen
                    prefs.lastCharacterId = characterId
                    if (!navController.popBackStack(Routes.DEVICE_HOME, inclusive = false)) {
                        navController.navigate(Routes.DEVICE_HOME) { launchSingleTop = true }
                    }
                },
            )
        }

        composable(Routes.CHARACTER_LIST) {
            CharacterListScreen(
                viewModel = characterViewModel,
                prefs = prefs,
                onNavigateToGames = ::openGames,
                onNavigateToMusic = ::openMusic,
                onCharacterSelected = { character, _ -> openChat(character) },
                onNavigateToSettings = {
                    navController.navigate(Routes.SETTINGS)
                },
                onNavigateToHall = {
                    navController.navigate(Routes.CHARACTER_HALL)
                },
                onNavigateToBooruSearch = {
                    navController.navigate(Routes.BOORU_SEARCH)
                },
                onNavigateToCreate = {
                    isCreatingCharacter = true
                    editingCharacter = null
                    navController.navigate(Routes.CHARACTER_EDIT)
                },
                showDeviceHomeAction = isCompanionRuntimeReady,
                onNavigateToDeviceHome = {
                    if (!navController.popBackStack(Routes.DEVICE_HOME, inclusive = false)) {
                        navController.navigate(Routes.DEVICE_HOME) {
                            launchSingleTop = true
                        }
                    }
                },
                onNavigateToEdit = { character ->
                    isCreatingCharacter = false
                    editingCharacter = character
                    navController.navigate(Routes.CHARACTER_EDIT)
                }
            )
        }

        composable(Routes.GAMES) {
            Scaffold(
                modifier = Modifier.fillMaxSize(),
                containerColor = MaterialTheme.colorScheme.background,
                bottomBar = {
                    PonyHomeBottomBar(
                        selectedTab = "games",
                        openChatList = ::openChatList,
                        openGames = {},
                        openMusic = ::openMusic,
                    )
                },
            ) { padding ->
                Box(Modifier.fillMaxSize().padding(padding), contentAlignment = Alignment.Center) {
                    Text("游戏内容开发中", color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        }

        composable(Routes.MUSIC) {
            val albumRequests = remember(it) { it.savedStateHandle.getStateFlow<String?>("musicAlbum", null) }
            val requestedAlbum by albumRequests.collectAsStateWithLifecycle()
            MusicScreen(
                musicModel, ::openPlayer, prefs, requestedAlbum,
                onAlbumRequestHandled = { it.savedStateHandle["musicAlbum"] = null },
            ) {
                PonyHomeBottomBar(
                    selectedTab = "music",
                    openChatList = ::openChatList,
                    openGames = ::openGames,
                    openMusic = {},
                )
            }
        }

        composable(
            Routes.MUSIC_PLAYER,
            enterTransition = {
                slideInVertically(animationSpec = tween(300, easing = FastOutSlowInEasing)) { fullHeight -> fullHeight }
            },
            popEnterTransition = { fadeIn(tween(700)) },
            popExitTransition = {
                slideOutVertically(animationSpec = tween(280, easing = FastOutSlowInEasing)) { fullHeight -> fullHeight }
            },
        ) { entry ->
            MusicPlayerScreen(
                musicModel,
                close = { navController.popPage(entry) },
                openSearch = { navController.navigate(Routes.MUSIC_SEARCH) { launchSingleTop = true } },
                openAlbum = { id ->
                    navController.popPage(entry)
                    if (navController.currentBackStackEntry?.destination?.route != Routes.MUSIC) openMusic()
                    navController.currentBackStackEntry?.savedStateHandle?.set("musicAlbum", id)
                },
            )
        }

        composable(Routes.MUSIC_SEARCH) { entry ->
            MusicSearchScreen(musicModel) { navController.popPage(entry) }
        }

        composable(Routes.CHARACTER_HALL) { entry ->
            CharacterHallScreen(
                viewModel = characterViewModel,
                prefs = prefs,
                onNavigateBack = { navController.popPage(entry) },
                onNavigateToMyPublished = { navController.navigate(Routes.CHARACTER_HALL_MY_PUBLISHED) },
                onCharacterSelected = { character, _ ->
                    profileCharacter = character
                    navController.navigate(Routes.CHARACTER_PROFILE)
                }
            )
        }

        composable(Routes.BOORU_SEARCH) { entry ->
            BooruSearchScreen(
                prefs = prefs,
                onNavigateBack = { navController.popPage(entry) },
            )
        }

        composable(Routes.CHARACTER_HALL_MY_PUBLISHED) { entry ->
            MyPublishedHallScreen(
                viewModel = characterViewModel,
                prefs = prefs,
                onNavigateBack = { navController.popPage(entry) }
            )
        }

        composable(Routes.CHARACTER_PROFILE) { entry ->
            val character = profileCharacter
            if (character == null) {
                LaunchedEffect(Unit) { navController.popPage(entry) }
            } else {
                CharacterProfileScreen(
                    character = character,
                    viewModel = characterViewModel,
                    prefs = prefs,
                    onNavigateBack = { navController.popPage(entry) },
                    onStartChat = { target, _ ->
                        val localTarget = characterViewModel.state.value.characters.firstOrNull {
                            it.id == target.id ||
                                (target.sourceId?.isNotBlank() == true && it.id == target.sourceId) ||
                                (it.sourceId?.isNotBlank() == true && it.sourceId == target.id) ||
                                (it.contentHash?.isNotBlank() == true && it.contentHash == target.contentHash)
                        } ?: target
                        openChat(localTarget)
                    },
                    onEditSettings = { target ->
                        isCreatingCharacter = false
                        editingCharacter = target
                        navController.navigate(Routes.CHARACTER_EDIT)
                    },
                    onAddFromHall = { target -> characterViewModel.addCharacterFromHall(target) }
                )
            }
        }

        composable(Routes.CHARACTER_EDIT) { entry ->
            CharacterEditScreen(
                viewModel = characterViewModel,
                prefs = prefs,
                isCreating = isCreatingCharacter,
                character = editingCharacter,
                onNavigateBack = { navController.popPage(entry) }
            )
        }

        val renderChat: @Composable AnimatedContentScope.(NavBackStackEntry) -> Unit = { entry ->
            val characterId by entry.savedStateHandle
                .getStateFlow(CHAT_CHARACTER_ID, prefs.lastCharacterId).collectAsStateWithLifecycle()
            val initialMode = if (entry.destination.route == LEGACY_CREATION_ROUTE) "creation" else prefs.chatMode
            val mode by entry.savedStateHandle
                .getStateFlow(CHAT_MODE, initialMode).collectAsStateWithLifecycle()
            val character = chatCharacter(characterId)
            if (character == null) {
                LaunchedEffect(entry, characterId) {
                    if (characterId.isNotBlank()) kotlinx.coroutines.delay(3000)
                    if (chatCharacter(characterId) == null && navController.currentBackStackEntry === entry) {
                        navController.popPage(entry)
                    }
                }
            } else {
                val vm = if (mode == "creation") null else remember(characterId, mode) {
                    getChatVm(characterId, mode)
                }
                val activeVm by rememberUpdatedState(vm)
                // 切换模式时仍在同一个聊天页，离页清理只在聊天页退出时执行。
                DisposableEffect(entry) {
                    onDispose { activeVm?.clearFailedChatRoundIfNeeded() }
                }
                val onModeSelected: (String) -> Unit = { nextMode ->
                    if (navController.currentBackStackEntry === entry && nextMode != mode) {
                        prefs.chatMode = nextMode
                        entry.savedStateHandle[CHAT_MODE] = nextMode
                    }
                }
                val showDisplaySettingsState = rememberSaveable(characterId) { mutableStateOf(false) }
                key(characterId, mode) {
                    if (vm == null) {
                        CreationChatScreen(
                            character = character,
                            prefs = prefs,
                            onBack = { navController.popPage(entry) },
                            onCharacterProfile = {
                                profileCharacter = character
                                navController.navigate(Routes.CHARACTER_PROFILE)
                            },
                            onUserProfile = { navController.navigate(Routes.SETTINGS) },
                            onThemeChanged = onThemeChanged,
                            onFontScaleChanged = onFontScaleChanged,
                            onModeSelected = onModeSelected,
                            showDisplaySettingsState = showDisplaySettingsState,
                        )
                    } else {
                        var initialized by remember { mutableStateOf(false) }
                        LaunchedEffect(character) {
                            vm.initWithCharacter(character, mode)
                            initialized = true
                        }
                        if (initialized) ChatScreen(
                            viewModel = vm,
                            character = character,
                            allCharacters = characterState.characters,
                            prefs = prefs,
                            onNavigateBack = { navController.popPage(entry) },
                            onNavigateToEditCharacter = {
                                profileCharacter = character
                                navController.navigate(Routes.CHARACTER_PROFILE)
                            },
                            onNavigateToCharacterProfile = { target ->
                                profileCharacter = target
                                navController.navigate(Routes.CHARACTER_PROFILE)
                            },
                            characterHome = { returnToChat ->
                                CharacterProfileScreen(
                                    character = character,
                                    viewModel = characterViewModel,
                                    prefs = prefs,
                                    embedded = true,
                                    onNavigateBack = returnToChat,
                                    onStartChat = { _, _ -> returnToChat() },
                                    onEditSettings = { target ->
                                        isCreatingCharacter = false
                                        editingCharacter = target
                                        navController.navigate(Routes.CHARACTER_EDIT)
                                    },
                                    onAddFromHall = { characterViewModel.addCharacterFromHall(it) },
                                )
                            },
                            onNavigateToSettings = { navController.navigate(Routes.SETTINGS) },
                            onNavigateToProactiveTasks = { openChatDetail(Routes.PROACTIVE_TASKS, entry) },
                            onNavigateToHistory = { openChatDetail(Routes.HISTORY, entry) },
                            onThemeChanged = onThemeChanged,
                            onModeSelected = onModeSelected,
                            showDisplaySettingsState = showDisplaySettingsState,
                        )
                    }
                }
            }
        }
        composable(
            Routes.CHAT,
            enterTransition = { EnterTransition.None },
            exitTransition = { fadeOut(animationSpec = tween(180)) },
            popEnterTransition = { fadeIn(animationSpec = tween(220)) },
            popExitTransition = { fadeOut(animationSpec = tween(180)) },
            content = renderChat,
        )
        // 从旧版本恢复导航栈时，原创造页面也使用同一个聊天界面。
        composable(LEGACY_CREATION_ROUTE, content = renderChat)

        composable(Routes.HISTORY) { entry ->
            val characterId = entry.savedStateHandle.get<String>(CHAT_CHARACTER_ID) ?: prefs.lastCharacterId
            val mode = entry.savedStateHandle.get<String>(CHAT_MODE) ?: prefs.chatMode
            val character = chatCharacter(characterId)
            if (character != null) {
                val vm = remember(characterId, mode) { getChatVm(characterId, mode) }
                LaunchedEffect(vm, character) {
                    if (vm.state.value.character == null) vm.initWithCharacter(character, mode)
                }
                ConversationHistoryScreen(
                    viewModel = vm,
                    character = character,
                    prefs = prefs,
                    onNavigateBack = { navController.popPage(entry) },
                    onNavigateToMemory = { openChatDetail(Routes.MEMORY, entry) }
                )
            }
        }

        composable(Routes.PROACTIVE_TASKS) { entry ->
            val character = chatCharacter(entry.savedStateHandle.get<String>(CHAT_CHARACTER_ID) ?: prefs.lastCharacterId)
            if (character != null) {
                ProactiveTasksScreen(
                    character = character,
                    prefs = prefs,
                    onNavigateBack = { navController.popPage(entry) }
                )
            }
        }

        composable(Routes.MEMORY) { entry ->
            val character = chatCharacter(entry.savedStateHandle.get<String>(CHAT_CHARACTER_ID) ?: prefs.lastCharacterId)
            if (character != null) {
                MemoryScreen(
                    character = character,
                    prefs = prefs,
                    onNavigateBack = { navController.popPage(entry) }
                )
            }
        }

        composable(Routes.SETTINGS) { entry ->
            SettingsScreen(
                prefs = prefs,
                onThemeChanged = onThemeChanged,
                onFontScaleChanged = onFontScaleChanged,
                onNavigateBack = { navController.popPage(entry) },
                onNavigateToProfileEdit = {
                    navController.navigate(Routes.PROFILE_EDIT)
                },
                onNavigateToNetwork = {
                    navController.navigate(Routes.NETWORK_SETTINGS)
                },
                isCheckingUpdate = isCheckingUpdate,
                onCheckUpdate = ::requestManualUpdateCheck,
                onLogout = {
                    ConnectionService.stop(context.applicationContext)
                    SyncWebSocketManager.stop()
                    clearAccountScopedUiState()
                    authViewModel.clearLoginState()
                    navController.navigate(Routes.LOGIN) {
                        popUpTo(0) { inclusive = true }
                        launchSingleTop = true
                    }
                }
            )
        }

        composable(Routes.NETWORK_SETTINGS) { entry ->
            NetworkSettingsScreen(
                prefs = prefs,
                onNavigateBack = { navController.popPage(entry) }
            )
        }

        composable(Routes.COMPANION_SETTINGS) { entry ->
            CompanionSettingsScreen(
                prefs = prefs,
                onNavigateBack = { navController.popPage(entry) }
            )
        }

        composable(Routes.PROFILE_EDIT) { entry ->
            ProfileEditScreen(
                prefs = prefs,
                onNavigateBack = { navController.popPage(entry) }
            )
        }
    }
}

private sealed class ApkDownloadState {
    object Idle : ApkDownloadState()
    data class Downloading(val progress: Float) : ApkDownloadState()
    object Installing : ApkDownloadState()
    data class Failed(val message: String) : ApkDownloadState()
}

/** 下载 APK 到私有缓存目录，通过 [onProgress] 回报 0f-1f 进度。 */
private suspend fun downloadApkToCache(
    context: Context,
    url: String,
    onProgress: (Float) -> Unit,
): File = withContext(Dispatchers.IO) {
    val client = OkHttpClient.Builder()
        .followSslRedirects(false)
        // APK self-update should prefer a plain HTTP/1.1 transfer. Some mobile
        // networks/proxies reset long HTTP/2 streams with INTERNAL_ERROR.
        .protocols(listOf(Protocol.HTTP_1_1))
        .connectTimeout(30, TimeUnit.SECONDS)
        .readTimeout(300, TimeUnit.SECONDS)
        .build()
    val apkFile = File(context.cacheDir, "ponychat_update.apk")
    var lastError: Throwable? = null
    repeat(2) { attempt ->
        try {
            if (apkFile.exists()) apkFile.delete()
            val request = Request.Builder()
                .url(url)
                .header("Accept", "application/vnd.android.package-archive,*/*")
                .header("Cache-Control", "no-cache")
                .build()
            client.newCall(request).execute().use { response ->
                if (!response.isSuccessful) error("下载失败，HTTP ${response.code}")
                val body = response.body ?: error("服务器返回空内容")
                val contentLength = body.contentLength()
                body.byteStream().use { input ->
                    apkFile.outputStream().use { output ->
                        val buf = ByteArray(64 * 1024)
                        var totalRead = 0L
                        var n: Int
                        while (input.read(buf).also { n = it } != -1) {
                            output.write(buf, 0, n)
                            totalRead += n
                            if (contentLength > 0) {
                                onProgress((totalRead.toFloat() / contentLength).coerceIn(0f, 1f))
                            }
                        }
                    }
                }
                if (contentLength > 0 && apkFile.length() != contentLength) {
                    error("下载不完整：${apkFile.length()}/$contentLength")
                }
            }
            onProgress(1f)
            return@withContext apkFile
        } catch (e: Throwable) {
            lastError = e
            if (attempt == 0) onProgress(0f)
        }
    }
    error(lastError?.message ?: "下载失败，请稍后重试")
}

/** 触发系统安装器安装指定 APK 文件（Android 7+ 用 FileProvider 共享 URI）。 */
private fun installApk(context: Context, apkFile: File) {
    val uri = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
        FileProvider.getUriForFile(context, "${context.packageName}.fileprovider", apkFile)
    } else {
        @Suppress("DEPRECATION")
        Uri.fromFile(apkFile)
    }
    val intent = Intent(Intent.ACTION_VIEW).apply {
        setDataAndType(uri, "application/vnd.android.package-archive")
        addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
    }
    context.startActivity(intent)
}

@Composable
internal fun UpdateAvailableDialog(
    currentVersion: String,
    latestVersion: String,
    releaseNotes: String = "",
    downloadUrl: String,
    onDismiss: () -> Unit,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val accentColor = Color(0xFF6366F1)
    var dlState by remember { mutableStateOf<ApkDownloadState>(ApkDownloadState.Idle) }

    AlertDialog(
        onDismissRequest = {
            if (dlState !is ApkDownloadState.Downloading) onDismiss()
        },
        containerColor = MaterialTheme.colorScheme.surface,
        shape = RoundedCornerShape(20.dp),
        title = {
            Text(
                "发现新版本",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
                color = MaterialTheme.colorScheme.onBackground
            )
        },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                // 版本信息卡片
                Surface(
                    shape = RoundedCornerShape(12.dp),
                    color = MaterialTheme.colorScheme.surfaceVariant,
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Column(
                        modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp),
                        verticalArrangement = Arrangement.spacedBy(8.dp)
                    ) {
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween
                        ) {
                            Text(
                                "当前版本",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                            Text(
                                "v$currentVersion",
                                style = MaterialTheme.typography.bodySmall,
                                fontWeight = FontWeight.Medium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween
                        ) {
                            Text(
                                "最新版本",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                            Text(
                                "v$latestVersion",
                                style = MaterialTheme.typography.bodySmall,
                                fontWeight = FontWeight.Bold,
                                color = accentColor
                            )
                        }
                    }
                }
                if (releaseNotes.isNotBlank()) {
                    Column(
                        modifier = Modifier.fillMaxWidth().heightIn(max = 220.dp)
                            .verticalScroll(rememberScrollState()),
                        verticalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        Text("更新内容", style = MaterialTheme.typography.titleSmall,
                            fontWeight = FontWeight.SemiBold)
                        Text(releaseNotes, style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
                // 状态区域
                when (val s = dlState) {
                    is ApkDownloadState.Idle -> Text(
                        "PonyChat 有新版本可用，建议立即更新以获得更好的体验。",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                    is ApkDownloadState.Downloading -> Column(
                        verticalArrangement = Arrangement.spacedBy(4.dp)
                    ) {
                        Text(
                            "正在下载… ${(s.progress * 100).toInt()}%",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                        LinearProgressIndicator(
                            progress = { s.progress },
                            modifier = Modifier.fillMaxWidth(),
                            color = accentColor,
                        )
                    }
                    is ApkDownloadState.Installing -> Text(
                        "下载完成，正在启动安装…",
                        style = MaterialTheme.typography.bodySmall,
                        color = accentColor
                    )
                    is ApkDownloadState.Failed -> Text(
                        formatErrorForDisplay("下载失败：${s.message}"),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.error
                    )
                }
            }
        },
        confirmButton = {
            when (dlState) {
                is ApkDownloadState.Idle, is ApkDownloadState.Failed -> {
                    TextButton(onClick = {
                        // 无论是首次还是失败后重试，都在 App 内下载
                        dlState = ApkDownloadState.Downloading(0f)
                        scope.launch {
                            try {
                                val apkFile = downloadApkToCache(
                                    context = context,
                                    url = downloadUrl,
                                    onProgress = { p ->
                                        dlState = ApkDownloadState.Downloading(p)
                                    }
                                )
                                dlState = ApkDownloadState.Installing
                                installApk(context, apkFile)
                                onDismiss()
                            } catch (e: Exception) {
                                dlState = ApkDownloadState.Failed(
                                    e.message?.take(60) ?: "未知错误"
                                )
                            }
                        }
                    }) {
                        Text(
                            "立即更新",
                            color = accentColor,
                            fontWeight = FontWeight.SemiBold
                        )
                    }
                }
                is ApkDownloadState.Downloading, is ApkDownloadState.Installing -> {
                    // 下载中禁用按钮
                    TextButton(onClick = {}, enabled = false) {
                        Text("下载中…", color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.38f))
                    }
                }
            }
        },
        dismissButton = {
            if (dlState !is ApkDownloadState.Downloading) {
                TextButton(onClick = onDismiss) {
                    Text("稍后再说", color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        }
    )
}
