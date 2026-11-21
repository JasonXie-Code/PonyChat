package top.ponychat.webview.ui.auth

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.Add
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.FocusDirection
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import top.ponychat.webview.ui.common.LoadingOverlay
import top.ponychat.webview.ui.common.focusAwareBringIntoView
import top.ponychat.webview.ui.common.WheelDatePickerDialog
import top.ponychat.webview.ui.common.SwipeToVerify
import top.ponychat.webview.ui.theme.*
import java.util.Calendar
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import top.ponychat.webview.ui.common.AvatarCropDialog
import top.ponychat.webview.ui.common.PonyAvatar
import top.ponychat.webview.util.formatErrorForDisplay

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun RegisterScreen(
    viewModel: AuthViewModel,
    onRegisterSuccess: () -> Unit,
    onNavigateBack: () -> Unit
) {
    val registerState by viewModel.registerState.collectAsState()
    val focusManager = LocalFocusManager.current

    var username by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var confirmPassword by remember { mutableStateOf("") }
    var gender by remember { mutableStateOf("male") }
    var birthYear by remember { mutableStateOf(2000) }
    var birthMonth by remember { mutableStateOf(1) }
    var birthDay by remember { mutableStateOf(1) }
    var inviteCode by remember { mutableStateOf("") }
    var passwordVisible by remember { mutableStateOf(false) }
    var showDatePicker by remember { mutableStateOf(false) }
    var isVerified by remember { mutableStateOf(false) }
    var localError by remember { mutableStateOf<String?>(null) }
    
    var avatarDataUrl by remember { mutableStateOf<String?>(null) }
    var showCropDialog by remember { mutableStateOf(false) }
    var rawAvatarBitmap by remember { mutableStateOf<Bitmap?>(null) }

    val context = androidx.compose.ui.platform.LocalContext.current
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

    val currentYear = Calendar.getInstance().get(Calendar.YEAR)
    val maxYear = currentYear - 18

    val birthDateString = "%04d-%02d-%02d".format(birthYear, birthMonth, birthDay)

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(
                Brush.verticalGradient(
                    colors = listOf(
                        MaterialTheme.colorScheme.background.copy(alpha = 0.85f),
                        MaterialTheme.colorScheme.surface.copy(alpha = 0.95f)
                    )
                )
            )
            .windowInsetsPadding(WindowInsets.systemBars)
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                // imePadding 必须在 verticalScroll 外层：先缩短可见视口再滚动，
                // 键盘才能"缩短"列表高度让邀请码滚入可见区域。
                // 若顺序倒置（在 scroll 内部），imePadding 只在内容底部追加空白，
                // 视口不变，键盘仍会遮挡输入框且无法靠滑动解决。
                .imePadding()
                .verticalScroll(rememberScrollState())
        ) {
            // 顶栏
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 8.dp, vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                top.ponychat.webview.ui.common.PonyIconButton(
                    onClick = onNavigateBack,
                    icon = Icons.AutoMirrored.Filled.ArrowBack,
                    contentDescription = "返回",
                    tint = MaterialTheme.colorScheme.onSurface
                )
                Text(
                    "创建账号",
                    style = MaterialTheme.typography.titleLarge,
                    fontWeight = FontWeight.ExtraBold,
                    color = MaterialTheme.colorScheme.onBackground,
                    modifier = Modifier.padding(start = 4.dp)
                )
            }

            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 32.dp),
                horizontalAlignment = Alignment.CenterHorizontally
            ) {
                Spacer(Modifier.height(16.dp))

                // 用户头像上传占位符（无头像时显示默认图标，支持裁剪）
                Box(
                    modifier = Modifier
                        .size(100.dp)
                        .clickable {
                            avatarPickerLauncher.launch("image/*")
                        }
                ) {
                    // 底层：被裁切的正圆形底座
                    Box(
                        modifier = Modifier
                            .fillMaxSize()
                            .clip(CircleShape)
                            .background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.8f))
                            .border(2.dp, Primary.copy(alpha = 0.5f), CircleShape),
                        contentAlignment = Alignment.Center
                    ) {
                        val selectedAvatar = avatarDataUrl?.takeIf { it.isNotBlank() }
                        if (selectedAvatar != null) {
                            PonyAvatar(
                                avatarUrl = selectedAvatar,
                                name = username.ifBlank { "用户" },
                                size = 100
                            )
                        } else {
                            Icon(
                                imageVector = Icons.Filled.Person,
                                contentDescription = "默认头像",
                                modifier = Modifier.size(56.dp),
                                tint = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.5f)
                            )
                        }
                    }
                    
                    // 顶层：独立悬浮悬挂于右下角的加号标识，不受 CircleShape 裁切影响
                    Box(
                        modifier = Modifier
                            .align(Alignment.BottomEnd)
                            .offset(x = (-2).dp, y = (-2).dp)
                            .size(28.dp)
                            .clip(CircleShape)
                            .background(Primary),
                        contentAlignment = Alignment.Center
                    ) {
                        Icon(
                            imageVector = Icons.Filled.Add,
                            contentDescription = "上传头像",
                            modifier = Modifier.size(16.dp),
                            tint = MaterialTheme.colorScheme.onPrimary
                        )
                    }
                }
                
                Spacer(Modifier.height(12.dp))
                
                Text(
                    text = "上传包含你风格的头像",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.8f)
                )

                Spacer(Modifier.height(32.dp))

                // 用户名
                PonyTextField(
                    value = username,
                    onValueChange = { username = it; localError = null; viewModel.clearRegisterError() },
                    label = "用户名",
                    hint = "2-20位，支持字母/数字/中文/下划线",
                    imeAction = ImeAction.Next,
                    onImeAction = { focusManager.moveFocus(FocusDirection.Down) }
                )
                Spacer(Modifier.height(16.dp))

                // 密码
                PonyTextField(
                    value = password,
                    onValueChange = { password = it; localError = null; viewModel.clearRegisterError() },
                    label = "密码",
                    hint = "不少于4位",
                    isPassword = true,
                    passwordVisible = passwordVisible,
                    onPasswordVisibilityToggle = { passwordVisible = !passwordVisible },
                    imeAction = ImeAction.Next,
                    onImeAction = { focusManager.moveFocus(FocusDirection.Down) }
                )
                Spacer(Modifier.height(16.dp))

                // 确认密码
                PonyTextField(
                    value = confirmPassword,
                    onValueChange = { confirmPassword = it; localError = null; viewModel.clearRegisterError() },
                    label = "确认密码",
                    isPassword = true,
                    passwordVisible = passwordVisible,
                    onPasswordVisibilityToggle = { passwordVisible = !passwordVisible },
                    imeAction = ImeAction.Next,
                    onImeAction = { focusManager.moveFocus(FocusDirection.Down) }
                )
                Spacer(Modifier.height(20.dp))

                // 性别选择
                Text(
                    "性别",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(bottom = 8.dp)
                )
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(12.dp)
                ) {
                    listOf("male" to "男", "female" to "女").forEach { (value, label) ->
                        val selected = gender == value
                        Box(
                            modifier = Modifier
                                .weight(1f)
                                .height(48.dp)
                                .clip(RoundedCornerShape(16.dp))
                                .background(
                                    if (selected) Primary.copy(alpha = 0.15f)
                                    else MaterialTheme.colorScheme.surface.copy(alpha = 0.6f)
                                )
                                .border(
                                    width = if (selected) 2.dp else 1.dp,
                                    color = if (selected) Primary else MaterialTheme.colorScheme.outline.copy(alpha = 0.3f),
                                    shape = RoundedCornerShape(16.dp)
                                )
                                .clickable { gender = value },
                            contentAlignment = Alignment.Center
                        ) {
                            Text(
                                label,
                                color = if (selected) Primary else MaterialTheme.colorScheme.onSurfaceVariant,
                                fontWeight = if (selected) FontWeight.Bold else FontWeight.Medium
                            )
                        }
                    }
                }
                Spacer(Modifier.height(20.dp))

                // 出生日期
                Text(
                    "出生日期 (＞18岁)",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(bottom = 8.dp)
                )
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(56.dp)
                        .clip(RoundedCornerShape(16.dp))
                        .background(MaterialTheme.colorScheme.surface.copy(alpha = 0.6f))
                        .border(1.dp, MaterialTheme.colorScheme.outline.copy(alpha = 0.3f), RoundedCornerShape(16.dp))
                        .clickable { showDatePicker = true },
                    contentAlignment = Alignment.CenterStart
                ) {
                    Text(
                        text = birthDateString,
                        modifier = Modifier.padding(horizontal = 16.dp),
                        color = MaterialTheme.colorScheme.onSurface,
                        style = MaterialTheme.typography.bodyLarge
                    )
                }

                Spacer(Modifier.height(16.dp))

                // 邀请码
                PonyTextField(
                    value = inviteCode,
                    onValueChange = { inviteCode = it; localError = null; viewModel.clearRegisterError() },
                    label = "邀请码",
                    hint = "请输入邀请码",
                    imeAction = ImeAction.Done,
                    onImeAction = { focusManager.clearFocus() },
                    // 页面底部字段：键盘动画约需 250-300ms，需等动画完成再请求滚入视野，
                    // 否则 bringIntoView 在键盘未出现时即返回"已可见"，不触发滚动。
                    bringIntoViewDelay = 300L
                )
                Spacer(Modifier.height(24.dp))

                // 滑动验证
                SwipeToVerify(
                    isVerified = isVerified,
                    onVerifySuccess = {
                        isVerified = true
                        localError = null
                        viewModel.clearRegisterError()
                    },
                    modifier = Modifier.fillMaxWidth()
                )
                Spacer(Modifier.height(16.dp))

                // 错误提示
                AnimatedVisibility(visible = registerState.error != null || localError != null) {
                    (localError ?: registerState.error)?.let { err ->
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

                Spacer(Modifier.height(32.dp))

                // 注册按钮
                top.ponychat.webview.ui.common.PonyButton(
                    text = "同意协议并注​​册",
                    onClick = {
                        focusManager.clearFocus()
                        if (!isVerified) {
                            localError = "请先完成向右滑动验证"
                            return@PonyButton
                        }
                        localError = null
                        viewModel.register(
                            username, password, confirmPassword,
                            gender, birthDateString, inviteCode,
                            avatar = avatarDataUrl,
                            onSuccess = { onRegisterSuccess() }
                        )
                    },
                    enabled = username.isNotBlank() && password.isNotBlank() && confirmPassword.isNotBlank(),
                    isLoading = registerState.isLoading
                )

                Spacer(Modifier.height(48.dp))
            }
        }
        LoadingOverlay(visible = registerState.isLoading, message = "注册中…")
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

    // 滚轮日期选择器（与 Web wheel-date-picker 一致）
    if (showDatePicker) {
        WheelDatePickerDialog(
            title = "选择出生日期",
            minYear = (maxYear - 100).coerceAtLeast(1900),
            maxYear = maxYear,
            selectedYear = birthYear,
            selectedMonth = birthMonth,
            selectedDay = birthDay,
            onDateSelected = { y, m, d ->
                birthYear = y
                birthMonth = m
                birthDay = d
                showDatePicker = false
            },
            onDismiss = { showDatePicker = false }
        )
    }
}

@Composable
private fun PonyTextField(
    value: String,
    onValueChange: (String) -> Unit,
    label: String,
    hint: String = "",
    isPassword: Boolean = false,
    passwordVisible: Boolean = false,
    onPasswordVisibilityToggle: (() -> Unit)? = null,
    imeAction: ImeAction = ImeAction.Next,
    onImeAction: (() -> Unit)? = null,
    bringIntoViewDelay: Long = 0L
) {
    OutlinedTextField(
        value = value,
        onValueChange = onValueChange,
        label = { Text(label) },
        placeholder = if (hint.isNotEmpty()) ({ Text(hint, color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.5f)) }) else null,
        singleLine = true,
        modifier = Modifier
            .fillMaxWidth()
            .focusAwareBringIntoView(delayMillis = bringIntoViewDelay),
        shape = RoundedCornerShape(16.dp),
        visualTransformation = if (isPassword && !passwordVisible)
            PasswordVisualTransformation() else VisualTransformation.None,
        keyboardOptions = KeyboardOptions(
            keyboardType = if (isPassword) KeyboardType.Password else KeyboardType.Text,
            imeAction = imeAction
        ),
        keyboardActions = KeyboardActions(
            onNext = { onImeAction?.invoke() },
            onDone = { onImeAction?.invoke() }
        ),
        trailingIcon = if (isPassword && onPasswordVisibilityToggle != null) ({
            top.ponychat.webview.ui.common.PonyIconButton(
                onClick = onPasswordVisibilityToggle,
                icon = if (passwordVisible) Icons.Filled.Visibility else Icons.Filled.VisibilityOff,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }) else null,
        colors = OutlinedTextFieldDefaults.colors(
            focusedBorderColor = Primary,
            unfocusedBorderColor = MaterialTheme.colorScheme.outline.copy(alpha = 0.3f),
            focusedLabelColor = Primary,
            unfocusedContainerColor = MaterialTheme.colorScheme.surface.copy(alpha = 0.6f),
            focusedContainerColor = MaterialTheme.colorScheme.surface.copy(alpha = 0.9f)
        )
    )
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
