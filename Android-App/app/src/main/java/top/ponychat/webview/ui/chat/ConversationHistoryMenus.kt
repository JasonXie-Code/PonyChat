package top.ponychat.webview.ui.chat

import androidx.activity.compose.BackHandler
import coil.compose.AsyncImage
import androidx.compose.animation.*
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.positionInWindow
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.IntRect
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Popup
import androidx.compose.ui.window.PopupPositionProvider
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import top.ponychat.webview.CustomToast
import top.ponychat.webview.data.api.NetworkClient
import top.ponychat.webview.data.model.Character
import top.ponychat.webview.data.model.CompanionMessage
import top.ponychat.webview.data.model.CompanionSessionSummary
import top.ponychat.webview.data.model.MessageAttachment
import top.ponychat.webview.data.model.ResetCharacterChatRequest
import top.ponychat.webview.data.model.SearchMessageResult
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.ui.character.CharacterAvatar
import top.ponychat.webview.ui.common.adaptivePopupMenuAccentColor
import top.ponychat.webview.ui.common.adaptivePopupMenuBorder
import top.ponychat.webview.ui.common.adaptivePopupMenuContainerColor
import top.ponychat.webview.ui.common.adaptivePopupMenuContentColor
import top.ponychat.webview.ui.common.adaptivePopupMenuDangerColor
import top.ponychat.webview.ui.common.PonyDangerCountdownConfirmDialog
import top.ponychat.webview.ui.common.PonyTopBar
import top.ponychat.webview.ui.common.PonyTopSearchBar
import top.ponychat.webview.ui.theme.*
import top.ponychat.webview.util.DebugLog
import java.text.SimpleDateFormat
import java.util.*
import kotlin.math.roundToInt

// ==================== 历史对话菜单/导航组件 ====================

private fun fingerMenuPositionProvider(positionInWindow: IntOffset): PopupPositionProvider =
    object : PopupPositionProvider {
        override fun calculatePosition(
            anchorBounds: IntRect,
            windowSize: IntSize,
            layoutDirection: androidx.compose.ui.unit.LayoutDirection,
            popupContentSize: IntSize
        ): IntOffset {
            val x = positionInWindow.x.coerceIn(0, (windowSize.width - popupContentSize.width).coerceAtLeast(0))
            val y = positionInWindow.y.coerceIn(0, (windowSize.height - popupContentSize.height).coerceAtLeast(0))
            return IntOffset(x, y)
        }
    }

@Composable
internal fun historyActionMenuContainerColor(): Color =
    adaptivePopupMenuContainerColor()

@Composable
internal fun historyActionMenuContentColor(): Color =
    adaptivePopupMenuContentColor()

@Composable
internal fun historyActionMenuDangerColor(): Color =
    adaptivePopupMenuDangerColor()

@Composable
internal fun historyActionMenuBorder(): BorderStroke? =
    adaptivePopupMenuBorder()

@Composable
internal fun HistoryFingerAnchoredDropdownMenu(
    expanded: Boolean,
    positionInWindow: IntOffset,
    onDismissRequest: () -> Unit,
    content: @Composable ColumnScope.() -> Unit
) {
    if (!expanded) return
    Popup(
        popupPositionProvider = remember(positionInWindow) { fingerMenuPositionProvider(positionInWindow) },
        onDismissRequest = onDismissRequest
    ) {
        Surface(
            shape = RoundedCornerShape(12.dp),
            color = historyActionMenuContainerColor(),
            border = historyActionMenuBorder(),
            tonalElevation = 3.dp,
            shadowElevation = 6.dp
        ) {
            Column(
                modifier = Modifier.width(168.dp),
                content = content
            )
        }
    }
}


// ==================== 紧凑底部导航项（与角色列表风格一致） ====================

@OptIn(ExperimentalFoundationApi::class)
@Composable
internal fun RowScope.CompactHistoryNavItem(
    selected: Boolean,
    icon: ImageVector,
    label: String,
    onClick: () -> Unit
) {
    val animatedColor by animateColorAsState(
        targetValue = if (selected) Primary else MaterialTheme.colorScheme.onSurfaceVariant.copy(0.6f),
        animationSpec = tween(200),
        label = "navColor"
    )
    val animatedScale by animateFloatAsState(
        targetValue = if (selected) 1.1f else 1f,
        animationSpec = spring(dampingRatio = 0.6f),
        label = "navScale"
    )
    Box(
        modifier = Modifier
            .weight(1f)
            .fillMaxHeight()
            .combinedClickable(onClick = onClick)
            .padding(vertical = 4.dp),
        contentAlignment = Alignment.Center
    ) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center,
            modifier = Modifier.graphicsLayer {
                scaleX = animatedScale
                scaleY = animatedScale
            }
        ) {
            Box(
                modifier = Modifier
                    .size(28.dp)
                    .clip(RoundedCornerShape(10.dp))
                    .background(
                        if (selected) Primary.copy(alpha = 0.12f) else Color.Transparent
                    ),
                contentAlignment = Alignment.Center
            ) {
                Icon(
                    imageVector = icon,
                    contentDescription = label,
                    tint = animatedColor,
                    modifier = Modifier.size(20.dp)
                )
            }
            Spacer(Modifier.height(2.dp))
            Text(
                text = label,
                style = MaterialTheme.typography.labelSmall.copy(
                    fontSize = AppFontSizes.caption,
                    lineHeight = 12.sp
                ),
                color = animatedColor,
                fontWeight = if (selected) FontWeight.Bold else FontWeight.Medium,
                maxLines = 1,
                textAlign = TextAlign.Center
            )
        }
    }
}
