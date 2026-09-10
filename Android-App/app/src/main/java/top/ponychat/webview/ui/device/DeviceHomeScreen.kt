package top.ponychat.webview.ui.device

import androidx.compose.foundation.background
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.ChatBubbleOutline
import androidx.compose.material.icons.rounded.Settings
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.delay
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import top.ponychat.webview.R
import top.ponychat.webview.data.model.Character
import top.ponychat.webview.ui.common.PonyAvatar

internal val DeviceBackground = Brush.linearGradient(
    colors = listOf(
        Color(0xFF090A18),
        Color(0xFF191733),
        Color(0xFF28204A),
    ),
)

@Composable
fun DeviceHomeScreen(
    runtimeStatus: String,
    runtimeReady: Boolean,
    activeCharacter: Character?,
    avatarApiBase: String,
    onOpenConversations: () -> Unit,
    onSwitchCharacter: () -> Unit,
    onOpenSettings: () -> Unit,
) {
    var now by remember { mutableStateOf(Date()) }
    LaunchedEffect(Unit) {
        while (true) {
            now = Date()
            delay(30_000L)
        }
    }

    BoxWithConstraints(
        modifier = Modifier
            .fillMaxSize()
            .background(DeviceBackground)
            .statusBarsPadding()
            .navigationBarsPadding()
            .padding(horizontal = 42.dp, vertical = 28.dp),
    ) {
        val compact = maxWidth < 760.dp || maxHeight < 520.dp
        Column(modifier = Modifier.fillMaxSize()) {
            DeviceTopBar(
                now = now,
                runtimeStatus = runtimeStatus,
                runtimeReady = runtimeReady,
                onOpenSettings = onOpenSettings,
            )
            Spacer(Modifier.height(if (compact) 20.dp else 34.dp))
            Column(
                modifier = Modifier
                    .weight(1f)
                    .fillMaxWidth(),
                verticalArrangement = Arrangement.spacedBy(if (compact) 18.dp else 28.dp),
            ) {
                DeviceHero(
                    modifier = Modifier
                        .weight(1f)
                        .fillMaxWidth(),
                    compact = compact,
                    activeCharacter = activeCharacter,
                    avatarApiBase = avatarApiBase,
                    onOpenConversations = onOpenConversations,
                    onSwitchCharacter = onSwitchCharacter,
                )
                DeviceQuickPanel(
                    modifier = Modifier.fillMaxWidth(),
                    compact = compact,
                    onOpenConversations = onOpenConversations,
                    onOpenSettings = onOpenSettings,
                )
            }
        }
    }
}

@Composable
private fun DeviceTopBar(
    now: Date,
    runtimeStatus: String,
    runtimeReady: Boolean,
    onOpenSettings: () -> Unit,
) {
    val time = remember(now) { SimpleDateFormat("HH:mm", Locale.getDefault()).format(now) }
    val date = remember(now) { SimpleDateFormat("M月d日 EEEE", Locale.getDefault()).format(now) }
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(
                modifier = Modifier
                    .size(10.dp)
                    .clip(CircleShape)
                    .background(if (runtimeReady) Color(0xFF8CE7C4) else Color(0xFFFFBF69)),
            )
            Spacer(Modifier.width(10.dp))
            Column {
                Text(
                    text = "PonyChat Device",
                    color = Color.White.copy(alpha = 0.82f),
                    style = MaterialTheme.typography.titleMedium,
                )
                Text(
                    text = runtimeStatus,
                    color = Color.White.copy(alpha = 0.46f),
                    fontSize = 10.sp,
                )
            }
        }
        Spacer(Modifier.weight(1f))
        Column(horizontalAlignment = Alignment.End) {
            Text(time, color = Color.White, fontSize = 24.sp, fontWeight = FontWeight.SemiBold)
            Text(date, color = Color.White.copy(alpha = 0.58f), fontSize = 12.sp)
        }
        Spacer(Modifier.width(18.dp))
        Surface(
            onClick = onOpenSettings,
            shape = CircleShape,
            color = Color.White.copy(alpha = 0.10f),
        ) {
            Icon(
                imageVector = Icons.Rounded.Settings,
                contentDescription = "设置",
                tint = Color.White.copy(alpha = 0.86f),
                modifier = Modifier.padding(12.dp).size(22.dp),
            )
        }
    }
}

@Composable
private fun DeviceHero(
    modifier: Modifier,
    compact: Boolean,
    activeCharacter: Character?,
    avatarApiBase: String,
    onOpenConversations: () -> Unit,
    onSwitchCharacter: () -> Unit,
) {
    Column(modifier = modifier, verticalArrangement = Arrangement.Center) {
        if (activeCharacter == null) {
            Image(
                painter = painterResource(R.mipmap.ic_launcher_round),
                contentDescription = "PonyChat",
                modifier = Modifier
                    .size(if (compact) 66.dp else 82.dp)
                    .clip(CircleShape),
            )
        } else {
            PonyAvatar(
                avatarUrl = activeCharacter.avatarUrl(),
                name = activeCharacter.displayName(),
                apiBase = avatarApiBase,
                size = if (compact) 66 else 82,
            )
        }
        Spacer(Modifier.height(22.dp))
        Text(
            text = activeCharacter?.displayName() ?: "欢迎回来",
            color = Color.White,
            fontSize = if (compact) 36.sp else 48.sp,
            lineHeight = if (compact) 42.sp else 54.sp,
            fontWeight = FontWeight.Bold,
        )
        Text(
            text = activeCharacter?.displayDescription()
                ?: "你的角色就在这里，陪你聊天，也陪你一起使用这台设备。",
            color = Color.White.copy(alpha = 0.66f),
            fontSize = if (compact) 15.sp else 18.sp,
            lineHeight = if (compact) 22.sp else 27.sp,
            modifier = Modifier.padding(top = 12.dp, bottom = 28.dp).fillMaxWidth(0.86f),
        )
        Row(horizontalArrangement = Arrangement.spacedBy(14.dp)) {
            Button(
                onClick = onOpenConversations,
                colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF8878EF)),
                shape = RoundedCornerShape(16.dp),
                modifier = Modifier.height(56.dp),
            ) {
                Icon(Icons.Rounded.ChatBubbleOutline, contentDescription = null)
                Spacer(Modifier.width(10.dp))
                Text("打开对话", fontSize = 17.sp, fontWeight = FontWeight.SemiBold)
            }
            Button(
                onClick = onSwitchCharacter,
                colors = ButtonDefaults.buttonColors(containerColor = Color.White.copy(alpha = 0.12f)),
                shape = RoundedCornerShape(16.dp),
                modifier = Modifier.height(56.dp),
            ) {
                Text("切换角色", fontSize = 17.sp, fontWeight = FontWeight.SemiBold)
            }
        }
    }
}

@Composable
private fun DeviceQuickPanel(
    modifier: Modifier,
    compact: Boolean,
    onOpenConversations: () -> Unit,
    onOpenSettings: () -> Unit,
) {
    Surface(
        modifier = modifier,
        shape = RoundedCornerShape(28.dp),
        color = Color.White.copy(alpha = 0.08f),
        border = androidx.compose.foundation.BorderStroke(1.dp, Color.White.copy(alpha = 0.10f)),
    ) {
        Column(
            modifier = Modifier.padding(if (compact) 16.dp else 24.dp),
            verticalArrangement = Arrangement.spacedBy(if (compact) 8.dp else 14.dp),
        ) {
            Text(
                text = "快捷入口",
                color = Color.White,
                fontSize = 18.sp,
                fontWeight = FontWeight.SemiBold,
            )
            Text(
                text = "进入角色列表继续对话，或管理设备中的 PonyChat 设置。",
                color = Color.White.copy(alpha = 0.58f),
                fontSize = 13.sp,
                lineHeight = 19.sp,
            )
            Spacer(Modifier.height(if (compact) 2.dp else 8.dp))
            DeviceAction("对话列表", "选择角色并继续之前的故事", compact, onOpenConversations)
            DeviceAction("PonyChat 设置", "账号、显示、网络与设备选项", compact, onOpenSettings)
        }
    }
}

@Composable
private fun DeviceAction(title: String, subtitle: String, compact: Boolean, onClick: () -> Unit) {
    Surface(
        onClick = onClick,
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(16.dp),
        color = Color.White.copy(alpha = 0.08f),
    ) {
        Column(
            modifier = Modifier.padding(
                horizontal = if (compact) 12.dp else 16.dp,
                vertical = if (compact) 6.dp else 13.dp,
            ),
        ) {
            Text(
                title,
                color = Color.White,
                fontSize = if (compact) 14.sp else 16.sp,
                fontWeight = FontWeight.Medium,
            )
            Text(
                subtitle,
                color = Color.White.copy(alpha = 0.48f),
                fontSize = if (compact) 10.sp else 11.sp,
                maxLines = 1,
                textAlign = TextAlign.Start,
            )
        }
    }
}
