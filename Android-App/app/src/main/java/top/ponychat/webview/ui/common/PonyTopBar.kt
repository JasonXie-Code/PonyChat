package top.ponychat.webview.ui.common

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LocalContentColor
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.contentColorFor
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.RectangleShape
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

@Composable
fun PonyTopBar(
    modifier: Modifier = Modifier,
    contentHeight: Dp = 48.dp,
    containerColor: Color = MaterialTheme.colorScheme.surface,
    shadowElevation: Dp = 1.dp,
    horizontalPadding: Dp = 4.dp,
    content: @Composable RowScope.() -> Unit
) {
    CompositionLocalProvider(LocalContentColor provides contentColorFor(containerColor)) {
        Row(
            modifier = modifier
                .shadow(shadowElevation, RectangleShape, clip = false)
                .background(containerColor)
                .fillMaxWidth()
                .statusBarsPadding()
                .height(contentHeight)
                .padding(horizontal = horizontalPadding),
            verticalAlignment = Alignment.CenterVertically,
            content = content
        )
    }
}

/**
 * 各页面左上角统一的返回按钮。
 *
 * 渲染规格与对话界面顶栏完全一致（Material3 IconButton + 默认 24dp 的 ArrowBack、
 * onSurface 默认配色），且不随字体缩放变化；特殊背景可覆盖颜色，
 * 普通页面直接复用默认规格，保持与对话界面一致。
 */
@Composable
fun PonyTopBarBackButton(
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    icon: ImageVector = Icons.AutoMirrored.Filled.ArrowBack,
    contentDescription: String = "返回",
    tint: Color = MaterialTheme.colorScheme.onSurface
) {
    IconButton(onClick = onClick, modifier = modifier) {
        Icon(
            imageVector = icon,
            contentDescription = contentDescription,
            tint = tint
        )
    }
}

@Composable
fun PonyTopBar(
    title: String,
    onNavigateBack: () -> Unit,
    modifier: Modifier = Modifier,
    navigationIcon: ImageVector = Icons.AutoMirrored.Filled.ArrowBack,
    navigationContentDescription: String = "返回",
    contentHeight: Dp = 48.dp,
    actions: @Composable RowScope.() -> Unit = {}
) {
    PonyTopBar(
        modifier = modifier,
        contentHeight = contentHeight
    ) {
        PonyTopBarBackButton(
            onClick = onNavigateBack,
            icon = navigationIcon,
            contentDescription = navigationContentDescription
        )
        Spacer(Modifier.width(4.dp))
        Text(
            text = title,
            style = MaterialTheme.typography.headlineSmall,
            fontWeight = FontWeight.SemiBold,
            color = MaterialTheme.colorScheme.onBackground
        )
        Spacer(Modifier.weight(1f))
        actions()
    }
}
