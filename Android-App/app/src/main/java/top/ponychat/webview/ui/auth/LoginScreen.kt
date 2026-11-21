package top.ponychat.webview.ui.auth

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material.icons.rounded.Monitor
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.collectAsState
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.focus.FocusDirection
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.launch
import android.app.Activity
import android.view.WindowManager
import kotlin.math.PI
import kotlin.math.sin
import top.ponychat.webview.ui.common.LoadingOverlay
import top.ponychat.webview.ui.common.PonyAlertDialog
import top.ponychat.webview.ui.theme.*
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.util.formatErrorForDisplay

@Composable
fun LoginScreen(
    viewModel: AuthViewModel,
    onLoginSuccess: () -> Unit,
    onNavigateToRegister: () -> Unit,
    onNavigateToNetwork: () -> Unit = {},
    showDeviceHomeButton: Boolean = false,
    onNavigateToDeviceHome: () -> Unit = {},
) {
    val loginState by viewModel.loginState.collectAsState()
    val focusManager = LocalFocusManager.current
    val context = androidx.compose.ui.platform.LocalContext.current

    var username by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var passwordVisible by remember { mutableStateOf(false) }
    var showAiDisclaimer by remember { mutableStateOf(false) }

    // 登录成功后检查是否需要显示 AI 声明弹窗
    LaunchedEffect(loginState.success) {
        if (loginState.success) {
            val prefs = AppPreferences(context)
            if (!prefs.aiDisclaimerShown) {
                showAiDisclaimer = true
            } else {
                onLoginSuccess()
            }
        }
    }

    if (showAiDisclaimer) {
        PonyAlertDialog(
            title = "关于 PonyChat 角色",
            onDismiss = {},
            content = {
                Text(
                    "PonyChat 中所有角色均由人工智能驱动。\n\n" +
                    "角色的全部回复均为 AI 生成内容，不代表真实的感情承诺或真人关系。\n\n" +
                    "请理性使用，保持健康的现实生活。",
                    style = MaterialTheme.typography.bodyMedium,
                    lineHeight = androidx.compose.ui.unit.TextUnit(22f, androidx.compose.ui.unit.TextUnitType.Sp)
                )
            },
            confirmButton = {
                top.ponychat.webview.ui.common.PonyButton(
                    text = "我已了解，进入应用",
                    onClick = {
                        AppPreferences(context).aiDisclaimerShown = true
                        showAiDisclaimer = false
                        onLoginSuccess()
                    }
                )
            }
        )
    }

    val view = LocalView.current
    DisposableEffect(Unit) {
        val activity = view.context as? Activity
        val window = activity?.window
        val originalMode = window?.attributes?.softInputMode
        window?.setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_NOTHING)
        onDispose {
            window?.setSoftInputMode(
                originalMode ?: run {
                    @Suppress("DEPRECATION")
                    WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE or WindowManager.LayoutParams.SOFT_INPUT_STATE_HIDDEN
                }
            )
        }
    }

    LaunchedEffect(loginState.error) {
        if (loginState.error != null) {
            // error shown in UI
        }
    }

    val infiniteTransition = rememberInfiniteTransition(label = "glow")
    val t1 by infiniteTransition.animateFloat(
        initialValue = 0f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(
            animation = tween(8000, easing = LinearEasing),
            repeatMode = RepeatMode.Reverse
        ),
        label = "glow1"
    )
    val t2 by infiniteTransition.animateFloat(
        initialValue = 0f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(
            animation = tween(12000, easing = LinearEasing),
            repeatMode = RepeatMode.Reverse
        ),
        label = "glow2"
    )
    val t3 by infiniteTransition.animateFloat(
        initialValue = 0f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(
            animation = tween(10000, easing = LinearEasing),
            repeatMode = RepeatMode.Reverse
        ),
        label = "glow3"
    )

    Box(modifier = Modifier.fillMaxSize()) {
        // 底部运动光晕（紫/红，平滑往返）
        Canvas(
            modifier = Modifier
                .fillMaxSize()
                .align(Alignment.BottomCenter)
        ) {
            val w = size.width
            val h = size.height
            val radius = w.coerceAtLeast(h) * 0.55f
            // 紫色光晕 1
            val cx1 = w * (0.15f + 0.35f * sin(2 * PI * t1).toFloat())
            val cy1 = h * (0.55f + 0.35f * sin(2 * PI * t2 * 1.3f).toFloat())
            drawCircle(
                brush = Brush.radialGradient(
                    colors = listOf(
                        Primary.copy(alpha = 0.35f),
                        Primary.copy(alpha = 0.12f),
                        Color.Transparent
                    ),
                    center = Offset(cx1, cy1),
                    radius = radius
                ),
                center = Offset(cx1, cy1),
                radius = radius
            )
            // 红色光晕
            val cx2 = w * (0.5f + 0.4f * sin(2 * PI * t2 * 0.9f).toFloat())
            val cy2 = h * (0.6f + 0.35f * sin(2 * PI * t3 * 1.1f).toFloat())
            drawCircle(
                brush = Brush.radialGradient(
                    colors = listOf(
                        AccentRose.copy(alpha = 0.32f),
                        AccentRose.copy(alpha = 0.1f),
                        Color.Transparent
                    ),
                    center = Offset(cx2, cy2),
                    radius = radius
                ),
                center = Offset(cx2, cy2),
                radius = radius
            )
            // 紫色光晕 2（另一相位）
            val cx3 = w * (0.75f + 0.2f * sin(2 * PI * t3 * 0.7f).toFloat())
            val cy3 = h * (0.5f + 0.4f * sin(2 * PI * t1 * 1.2f).toFloat())
            drawCircle(
                brush = Brush.radialGradient(
                    colors = listOf(
                        Primary.copy(alpha = 0.25f),
                        Primary.copy(alpha = 0.08f),
                        Color.Transparent
                    ),
                    center = Offset(cx3, cy3),
                    radius = radius * 0.85f
                ),
                center = Offset(cx3, cy3),
                radius = radius * 0.85f
            )
        }

        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(
                    Brush.verticalGradient(
                        colors = listOf(
                            MaterialTheme.colorScheme.background.copy(alpha = 0.75f),
                            MaterialTheme.colorScheme.surface.copy(alpha = 0.6f)
                        )
                    )
                )
        )

        val config = LocalConfiguration.current
        val isWide = config.screenWidthDp.dp >= 600.dp

        Row(
            modifier = Modifier
                .fillMaxSize()
                .windowInsetsPadding(WindowInsets.systemBars)
        ) {
            if (isWide) {
                Surface(
                    modifier = Modifier
                        .weight(1.2f)
                        .fillMaxHeight(),
                    color = Primary.copy(alpha = 0.15f)
                ) {
                    Column(
                        modifier = Modifier
                            .fillMaxSize()
                            .padding(48.dp),
                        verticalArrangement = Arrangement.Center
                    ) {
                        Text(
                            "连接全球顶尖 AI，\n体验前所未有的\n跨次元深度交互。",
                            style = MaterialTheme.typography.displaySmall,
                            fontWeight = FontWeight.Bold,
                            color = MaterialTheme.colorScheme.onSurface
                        )
                        Spacer(Modifier.height(24.dp))
                        Text(
                            "次世代联网大模型矩阵\n多模态视觉理解\n极致情感智能",
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                }
            }
            Column(
                modifier = Modifier
                    .weight(1f)
                    .fillMaxHeight(),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.Center
            ) {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .verticalScroll(rememberScrollState())
                        .padding(horizontal = 32.dp, vertical = 24.dp),
                    horizontalAlignment = Alignment.CenterHorizontally
                ) {
                    Text(
                        text = "PonyChat",
                        style = MaterialTheme.typography.displayLarge.copy(fontSize = AppFontSizes.displayLogo),
                        fontWeight = FontWeight.ExtraBold,
                        color = Primary
                    )
                    Spacer(Modifier.height(16.dp))
                    Text(
                        text = "接入最先进的智能网络，开启你的故事",
                        style = MaterialTheme.typography.bodyLarge,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )

                    Spacer(Modifier.height(48.dp))

                    OutlinedTextField(
                        value = username,
                        onValueChange = {
                            username = it
                            viewModel.clearLoginError()
                        },
                        label = { Text("用户名") },
                        singleLine = true,
                        modifier = Modifier
                            .fillMaxWidth(),
                        shape = RoundedCornerShape(16.dp),
                        keyboardOptions = KeyboardOptions(
                            keyboardType = KeyboardType.Text,
                            imeAction = ImeAction.Next
                        ),
                        keyboardActions = KeyboardActions(
                            onNext = { focusManager.moveFocus(FocusDirection.Down) }
                        ),
                        colors = OutlinedTextFieldDefaults.colors(
                            focusedBorderColor = Primary,
                            unfocusedBorderColor = MaterialTheme.colorScheme.outline.copy(alpha = 0.3f),
                            focusedLabelColor = Primary,
                            unfocusedContainerColor = MaterialTheme.colorScheme.surface.copy(alpha = 0.6f),
                            focusedContainerColor = MaterialTheme.colorScheme.surface.copy(alpha = 0.9f)
                        )
                    )

                    Spacer(Modifier.height(20.dp))

                    OutlinedTextField(
                        value = password,
                        onValueChange = {
                            password = it
                            viewModel.clearLoginError()
                        },
                        label = { Text("密码") },
                        singleLine = true,
                        modifier = Modifier
                            .fillMaxWidth(),
                        shape = RoundedCornerShape(16.dp),
                        visualTransformation = if (passwordVisible)
                            VisualTransformation.None else PasswordVisualTransformation(),
                        keyboardOptions = KeyboardOptions(
                            keyboardType = KeyboardType.Password,
                            imeAction = ImeAction.Done
                        ),
                        keyboardActions = KeyboardActions(
                            onDone = {
                                focusManager.clearFocus()
                                viewModel.login(username, password, onSuccess = { onLoginSuccess() })
                            }
                        ),
                        trailingIcon = {
                            top.ponychat.webview.ui.common.PonyIconButton(
                                onClick = { passwordVisible = !passwordVisible },
                                icon = if (passwordVisible) Icons.Filled.Visibility else Icons.Filled.VisibilityOff,
                                contentDescription = if (passwordVisible) "隐藏密码" else "显示密码",
                                tint = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        },
                        colors = OutlinedTextFieldDefaults.colors(
                            focusedBorderColor = Primary,
                            unfocusedBorderColor = MaterialTheme.colorScheme.outline.copy(alpha = 0.3f),
                            focusedLabelColor = Primary,
                            unfocusedContainerColor = MaterialTheme.colorScheme.surface.copy(alpha = 0.6f),
                            focusedContainerColor = MaterialTheme.colorScheme.surface.copy(alpha = 0.9f)
                        )
                    )

                    Spacer(Modifier.height(16.dp))

                    AnimatedVisibility(visible = loginState.error != null) {
                        loginState.error?.let { err ->
                            Card(
                                modifier = Modifier.fillMaxWidth(),
                                colors = CardDefaults.cardColors(
                                    containerColor = ErrorColor.copy(alpha = 0.12f)
                                ),
                                shape = RoundedCornerShape(12.dp)
                            ) {
                                Text(
                                    text = formatErrorForDisplay(err),
                                    color = ErrorColor,
                                    style = MaterialTheme.typography.bodyMedium,
                                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp)
                                )
                            }
                        }
                    }

                    Spacer(Modifier.height(48.dp))

                    top.ponychat.webview.ui.common.PonyButton(
                        text = "登录",
                        onClick = {
                            focusManager.clearFocus()
                            viewModel.login(username, password, onSuccess = { onLoginSuccess() })
                        },
                        enabled = username.isNotBlank() && password.isNotBlank(),
                        isLoading = loginState.isLoading
                    )

                    Spacer(Modifier.height(24.dp))

                    TextButton(
                        onClick = onNavigateToRegister,
                        modifier = Modifier.padding(vertical = 8.dp)
                    ) {
                        Text(
                            "还没有账号？立即注册",
                            color = Primary,
                            style = MaterialTheme.typography.bodyLarge,
                            fontWeight = FontWeight.Medium
                        )
                    }
                }
            }
            // success=true 时保持遮罩可见直到导航完成；显示声明弹窗时撤遮罩（弹窗浮在最上层）。
            // 退出登录时 AppNavigation 会调用 authViewModel.clearLoginState() 清除残留 success，
            // 确保返回登录页时 success=false，不会误遮登录表单。
            LoadingOverlay(visible = loginState.isLoading || (loginState.success && !showAiDisclaimer), message = "登录中…")
        }

        Box(
            modifier = Modifier
                .align(Alignment.TopEnd)
                .windowInsetsPadding(WindowInsets.systemBars)
                .padding(4.dp)
        ) {
            IconButton(onClick = onNavigateToNetwork) {
                Icon(
                    imageVector = Icons.Filled.Settings,
                    contentDescription = "网络连接设置",
                    tint = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }
        if (showDeviceHomeButton) {
            Box(
                modifier = Modifier
                    .align(Alignment.TopStart)
                    .windowInsetsPadding(WindowInsets.systemBars)
                    .padding(4.dp),
            ) {
                IconButton(onClick = onNavigateToDeviceHome) {
                    Icon(
                        imageVector = Icons.Rounded.Monitor,
                        contentDescription = "进入设备主页",
                        tint = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
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
