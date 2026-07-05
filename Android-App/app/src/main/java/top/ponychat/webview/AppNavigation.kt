package top.ponychat.webview

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.os.Build
import androidx.activity.compose.BackHandler
import androidx.compose.animation.EnterTransition
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.core.tween
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.activity.ComponentActivity
import androidx.core.content.FileProvider
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewmodel.compose.viewModel
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
import top.ponychat.webview.ui.chat.ChatScreen
import top.ponychat.webview.ui.chat.ChatViewModel
import top.ponychat.webview.ui.chat.ConversationHistoryScreen
import top.ponychat.webview.ui.chat.MemoryScreen
import top.ponychat.webview.ui.chat.ProactiveTasksScreen
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

}

@Composable
fun AppNavigation(
    prefs: AppPreferences,
    onThemeChanged: (Boolean) -> Unit = {},
    onFontScaleChanged: (Float) -> Unit = {},
    startDestination: String = if (prefs.isLoggedIn()) Routes.CHARACTER_LIST else Routes.LOGIN
) {
    val navController = rememberNavController()
    val context = LocalContext.current
    val backStackEntry by navController.currentBackStackEntryAsState()
    val currentRoute = backStackEntry?.destination?.route
    val authViewModel: AuthViewModel = viewModel()
    val characterViewModel: CharacterViewModel = viewModel()
    // 每个角色拥有独立的 Activity 级 ViewModel，切换角色时各自的生成互不干扰
    fun getChatVm(characterId: String): ChatViewModel {
        val activity = context as ComponentActivity
        return ViewModelProvider(activity, activity.defaultViewModelProviderFactory)
            .get("chat_$characterId", ChatViewModel::class.java)
    }

    var selectedCharacter by remember { mutableStateOf<Character?>(null) }
    var profileCharacter by remember { mutableStateOf<Character?>(null) }
    var editingCharacter by remember { mutableStateOf<Character?>(null) }
    var isCreatingCharacter by remember { mutableStateOf(false) }
    var lastBackPressAt by remember { mutableLongStateOf(0L) }
    val snackbarHostState = CustomToast.current
    val scope = rememberCoroutineScope()

    var showUpgradeDialog by remember { mutableStateOf(false) }
    var forceUpgradeDlState by remember { mutableStateOf<ApkDownloadState>(ApkDownloadState.Idle) }

    fun clearAccountScopedUiState() {
        selectedCharacter = null
        profileCharacter = null
        editingCharacter = null
        isCreatingCharacter = false
        characterViewModel.resetForAccountChange()
    }

    // ==================== 版本更新弹窗 ====================
    var showUpdateDialog by remember { mutableStateOf(false) }
    var updateLatestVersion by remember { mutableStateOf("") }
    var updateDownloadUrl by remember { mutableStateOf("https://ponychat.org/download/apk") }
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
                selectedCharacter = char
                val vm = getChatVm(char.id ?: "default")
                // 使用通知携带的 mode，确保游戏/锁分通知能正确进入对应模式
                vm.initWithCharacter(char, navTarget.mode)
                navController.navigate(Routes.CHAT) {
                    // 若已在某个 CHAT 页则替换，避免叠加多个 CHAT 路由
                    popUpTo(Routes.CHARACTER_LIST) { inclusive = false }
                    launchSingleTop = true
                }
            }
            ProactiveNavTarget.clear()
        }
    }

    BackHandler {
        when (currentRoute) {
            Routes.LOGIN, Routes.CHARACTER_LIST -> {
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
        startDestination = startDestination
    ) {
        composable(Routes.LOGIN) {
            LoginScreen(
                viewModel = authViewModel,
                onLoginSuccess = {
                    clearAccountScopedUiState()
                    characterViewModel.loadMyCharacters()
                    navController.navigate(Routes.CHARACTER_LIST) {
                        popUpTo(Routes.LOGIN) { inclusive = true }
                    }
                },
                onNavigateToRegister = {
                    navController.navigate(Routes.REGISTER)
                },
                onNavigateToNetwork = {
                    navController.navigate(Routes.NETWORK_SETTINGS)
                }
            )
        }

        composable(Routes.REGISTER) {
            RegisterScreen(
                viewModel = authViewModel,
                onRegisterSuccess = {
                    navController.navigate(Routes.LOGIN) {
                        popUpTo(Routes.REGISTER) { inclusive = true }
                    }
                },
                onNavigateBack = { navController.popBackStack() }
            )
        }

        composable(Routes.CHARACTER_LIST) {
            CharacterListScreen(
                viewModel = characterViewModel,
                prefs = prefs,
                onCharacterSelected = { character, mode ->
                    selectedCharacter = character
                    val vm = getChatVm(character.id ?: "default")
                    vm.initWithCharacter(character, mode)
                    navController.navigate(Routes.CHAT)
                },
                onNavigateToSettings = {
                    navController.navigate(Routes.SETTINGS)
                },
                onNavigateToHall = {
                    navController.navigate(Routes.CHARACTER_HALL)
                },
                onNavigateToCreate = {
                    isCreatingCharacter = true
                    editingCharacter = null
                    navController.navigate(Routes.CHARACTER_EDIT)
                },
                onNavigateToEdit = { character ->
                    isCreatingCharacter = false
                    editingCharacter = character
                    navController.navigate(Routes.CHARACTER_EDIT)
                }
            )
        }

        composable(Routes.CHARACTER_HALL) {
            CharacterHallScreen(
                viewModel = characterViewModel,
                prefs = prefs,
                onNavigateBack = { navController.popBackStack() },
                onNavigateToMyPublished = { navController.navigate(Routes.CHARACTER_HALL_MY_PUBLISHED) },
                onCharacterSelected = { character, mode ->
                    profileCharacter = character
                    navController.navigate(Routes.CHARACTER_PROFILE)
                }
            )
        }

        composable(Routes.CHARACTER_HALL_MY_PUBLISHED) {
            MyPublishedHallScreen(
                viewModel = characterViewModel,
                prefs = prefs,
                onNavigateBack = { navController.popBackStack() }
            )
        }

        composable(Routes.CHARACTER_PROFILE) {
            val character = profileCharacter
            if (character == null) {
                LaunchedEffect(Unit) { navController.popBackStack() }
            } else {
                CharacterProfileScreen(
                    character = character,
                    viewModel = characterViewModel,
                    prefs = prefs,
                    onNavigateBack = { navController.popBackStack() },
                    onStartChat = { target, mode ->
                        val localTarget = characterViewModel.state.value.characters.firstOrNull {
                            it.id == target.id ||
                                (target.sourceId?.isNotBlank() == true && it.id == target.sourceId) ||
                                (it.sourceId?.isNotBlank() == true && it.sourceId == target.id) ||
                                (it.contentHash?.isNotBlank() == true && it.contentHash == target.contentHash)
                        } ?: target
                        selectedCharacter = localTarget
                        val vm = getChatVm(localTarget.id ?: "default")
                        vm.initWithCharacter(localTarget, mode)
                        navController.navigate(Routes.CHAT)
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

        composable(Routes.CHARACTER_EDIT) {
            CharacterEditScreen(
                viewModel = characterViewModel,
                prefs = prefs,
                isCreating = isCreatingCharacter,
                character = editingCharacter,
                onNavigateBack = { navController.popBackStack() }
            )
        }

        composable(
            Routes.CHAT,
            enterTransition = { EnterTransition.None },
            exitTransition = { fadeOut(animationSpec = tween(180)) },
            popEnterTransition = { fadeIn(animationSpec = tween(220)) },
            popExitTransition = { fadeOut(animationSpec = tween(180)) }
        ) {
            val character = selectedCharacter
            if (character == null) {
                // 进程被杀后 Nav 恢复 CHAT 但 selectedCharacter 丢失 → 从 prefs 恢复，避免黑屏
                LaunchedEffect(Unit) {
                    val lastId = prefs.lastCharacterId
                    val lastMode = prefs.chatMode
                    if (lastId.isBlank()) {
                        navController.navigate(Routes.CHARACTER_LIST) {
                            popUpTo(0) { inclusive = true }
                        }
                        return@LaunchedEffect
                    }
                    if (characterViewModel.state.value.characters.isEmpty()) {
                        characterViewModel.loadMyCharacters()
                    }
                    var waited = 0
                    while (characterViewModel.state.value.characters.isEmpty() && waited < 30) {
                        kotlinx.coroutines.delay(100)
                        waited++
                    }
                    val char = characterViewModel.state.value.characters.find { it.id == lastId }
                    if (char != null) {
                        selectedCharacter = char
                        getChatVm(char.id ?: "default").initWithCharacter(char, lastMode)
                    } else {
                        navController.navigate(Routes.CHARACTER_LIST) {
                            popUpTo(0) { inclusive = true }
                        }
                    }
                }
            } else {
                val vm = remember(character.id) { getChatVm(character.id ?: "default") }
                ChatScreen(
                    viewModel = vm,
                    character = character,
                    allCharacters = characterViewModel.state.value.characters,
                    prefs = prefs,
                    onNavigateBack = { navController.popBackStack() },
                    onNavigateToEditCharacter = {
                        profileCharacter = character
                        navController.navigate(Routes.CHARACTER_PROFILE)
                    },
                    onNavigateToCharacterProfile = { target ->
                        profileCharacter = target
                        navController.navigate(Routes.CHARACTER_PROFILE)
                    },
                    onNavigateToSettings = { navController.navigate(Routes.SETTINGS) },
                    onNavigateToProactiveTasks = { navController.navigate(Routes.PROACTIVE_TASKS) },
                    onNavigateToHistory = { navController.navigate(Routes.HISTORY) },
                    onThemeChanged = onThemeChanged,
                )
            }
        }

        composable(Routes.HISTORY) {
            val character = selectedCharacter
            if (character != null) {
                val vm = remember(character.id) { getChatVm(character.id ?: "default") }
                ConversationHistoryScreen(
                    viewModel = vm,
                    character = character,
                    prefs = prefs,
                    onNavigateBack = { navController.popBackStack() },
                    onNavigateToMemory = { navController.navigate(Routes.MEMORY) }
                )
            }
        }

        composable(Routes.PROACTIVE_TASKS) {
            val character = selectedCharacter
            if (character != null) {
                ProactiveTasksScreen(
                    character = character,
                    prefs = prefs,
                    onNavigateBack = { navController.popBackStack() }
                )
            }
        }

        composable(Routes.MEMORY) {
            val character = selectedCharacter
            if (character != null) {
                MemoryScreen(
                    character = character,
                    prefs = prefs,
                    onNavigateBack = { navController.popBackStack() }
                )
            }
        }

        composable(Routes.SETTINGS) {
            SettingsScreen(
                prefs = prefs,
                onThemeChanged = onThemeChanged,
                onFontScaleChanged = onFontScaleChanged,
                onNavigateBack = { navController.popBackStack() },
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
                        popUpTo(Routes.CHARACTER_LIST) { inclusive = true }
                        launchSingleTop = true
                    }
                }
            )
        }

        composable(Routes.NETWORK_SETTINGS) {
            NetworkSettingsScreen(
                prefs = prefs,
                onNavigateBack = { navController.popBackStack() }
            )
        }

        composable(Routes.COMPANION_SETTINGS) {
            CompanionSettingsScreen(
                prefs = prefs,
                onNavigateBack = { navController.popBackStack() }
            )
        }

        composable(Routes.PROFILE_EDIT) {
            ProfileEditScreen(
                prefs = prefs,
                onNavigateBack = { navController.popBackStack() }
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
private fun UpdateAvailableDialog(
    currentVersion: String,
    latestVersion: String,
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
