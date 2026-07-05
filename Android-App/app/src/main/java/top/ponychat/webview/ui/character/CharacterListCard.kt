package top.ponychat.webview.ui.character

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowUpward
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.PersonAdd
import androidx.compose.material.icons.filled.PushPin
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import top.ponychat.webview.data.model.Character
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.ui.common.adaptivePopupMenuAccentColor
import top.ponychat.webview.ui.common.adaptivePopupMenuBorder
import top.ponychat.webview.ui.common.adaptivePopupMenuContainerColor
import top.ponychat.webview.ui.common.adaptivePopupMenuContentColor
import top.ponychat.webview.ui.common.adaptivePopupMenuDangerColor
import top.ponychat.webview.ui.common.adaptivePopupMenuIsDarkTheme
import top.ponychat.webview.ui.theme.AppFontSizes
import top.ponychat.webview.ui.theme.ErrorColor
import top.ponychat.webview.ui.theme.Primary
import top.ponychat.webview.ui.theme.ScaledIcon as Icon
import top.ponychat.webview.ui.theme.Secondary
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Locale

@Composable
private fun characterCardActionMenuIsDarkTheme(): Boolean =
    adaptivePopupMenuIsDarkTheme()

@Composable
private fun characterCardActionMenuContainerColor(): Color =
    adaptivePopupMenuContainerColor()

@Composable
private fun characterCardActionMenuContentColor(): Color =
    adaptivePopupMenuContentColor()

@Composable
private fun characterCardActionMenuMutedColor(): Color =
    characterCardActionMenuContentColor().copy(alpha = 0.62f)

@Composable
private fun characterCardActionMenuAccentColor(): Color =
    adaptivePopupMenuAccentColor()

@Composable
private fun characterCardActionMenuDangerColor(): Color =
    adaptivePopupMenuDangerColor()

@Composable
private fun characterCardActionMenuDividerColor(): Color =
    characterCardActionMenuContentColor().copy(alpha = if (characterCardActionMenuIsDarkTheme()) 0.18f else 0.10f)

@Composable
private fun characterCardActionMenuBorder() =
    adaptivePopupMenuBorder()

// ==================== 角色列表项（Pony风格，支持长按菜单） ====================

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun CharacterCard(
    character: Character,
    apiBase: String,
    fallbackApiBase: String = "",
    isOwned: Boolean,
    isPinned: Boolean = false,
    @Suppress("UNUSED_PARAMETER")
    showDragHandle: Boolean = false,
    dragHandleModifier: Modifier = Modifier,
    isDragging: Boolean = false,
    /** 当前模式下未读 AI 完成条数（头像角标） */
    unreadCount: Int = 0,
    /** 模式专属最后对话时间（毫秒），>0 时优先于 character.lastChatTime 展示 */
    modeLastChatMs: Long = 0L,
    /** 当前模式下最近一条助手消息摘要；空则回退 [Character.displayDescription] */
    listSubtitleLine: String = "",
    currentUsername: String = "",
    onClick: () -> Unit,
    onEdit: () -> Unit,
    onDelete: () -> Unit,
    onDuplicate: () -> Unit,
    onAddFromHall: (() -> Unit)? = null,
    onTogglePublish: (() -> Unit)? = null,
    onTogglePin: (() -> Unit)? = null
) {
    var showMenu by remember { mutableStateOf(false) }
    val cardElevation by animateFloatAsState(
        targetValue = if (isDragging) 8f else 0f,
        animationSpec = tween(150),
        label = "cardElevation"
    )
    val actionMenuTextColor = characterCardActionMenuContentColor()
    val actionMenuMutedTextColor = characterCardActionMenuMutedColor()
    val actionMenuPrimaryColor = characterCardActionMenuAccentColor()
    val actionMenuDeleteColor = characterCardActionMenuDangerColor()
    val actionMenuDivider = characterCardActionMenuDividerColor()
    val canManagePublish = character.canManagePublishing(currentUsername)

    Box(
        modifier = Modifier
            .shadow(cardElevation.dp)
            .background(MaterialTheme.colorScheme.background)
    ) {
        Column {
            // 尾栏：时间悬浮在 48dp 可点区上方，布局高度只计 48dp；end padding 与 48 内 20dp 图标的右缘对齐；主行纵向居中以缩小「时间-三点」间视觉空隙
            val menuSlotWidth = 64.dp
            val menuIconVisualEndPadding = 14.dp // (48-20)/2，与 IconButton 内 20dp 图标的右缘同竖线
            val trailingGap = 4.dp
            val timeFloatOffsetY = 4.dp
            /** 尾栏（时间+格）整体下移 */
            val trailingVerticalNudgeY = 4.dp
            /** 在整体下移基础上，三点多下移 */
            val menuIconNudgeY = 6.dp
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .clickable(onClick = onClick)
                    .padding(
                        start = 16.dp,
                        end = 2.dp,
                        top = 12.dp,
                        bottom = 12.dp
                    )
            ) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Box(modifier = dragHandleModifier) {
                        CharacterAvatar(
                            avatarUrl = character.avatarUrl(),
                            name = character.displayName(),
                            apiBase = apiBase,
                            fallbackApiBase = fallbackApiBase,
                            size = 50,
                            modifier = Modifier
                        )
                        if (isPinned) {
                            Box(
                                modifier = Modifier
                                    .align(Alignment.TopStart)
                                    .offset(x = (-2).dp, y = (-2).dp)
                                    .size(9.dp)
                                    .clip(CircleShape)
                                    .background(Primary)
                                    .semantics { contentDescription = "已置顶" }
                            )
                        }
                        if (unreadCount > 0) {
                            val label = when {
                                unreadCount <= 1 -> ""
                                unreadCount > 99 -> "99+"
                                else -> unreadCount.toString()
                            }
                            if (label.isEmpty()) {
                                Box(
                                    modifier = Modifier
                                        .align(Alignment.TopEnd)
                                        .offset(x = 4.dp, y = (-3).dp)
                                        .size(9.dp)
                                        .clip(CircleShape)
                                        .background(ErrorColor)
                                )
                            } else {
                                Surface(
                                    modifier = Modifier
                                        .align(Alignment.TopEnd)
                                        .offset(x = 6.dp, y = (-4).dp),
                                    shape = RoundedCornerShape(10.dp),
                                    color = ErrorColor,
                                    shadowElevation = 0.dp
                                ) {
                                    Text(
                                        text = label,
                                        modifier = Modifier.padding(horizontal = 5.dp, vertical = 1.dp),
                                        style = MaterialTheme.typography.labelSmall.copy(
                                            fontSize = 10.sp,
                                            lineHeight = 12.sp,
                                            fontWeight = FontWeight.Bold
                                        ),
                                        color = Color.White,
                                        maxLines = 1
                                    )
                                }
                            }
                        }
                    }
                    Spacer(Modifier.width(12.dp))
                    Column(
                        modifier = Modifier.weight(1f)
                    ) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text(
                                text = character.displayName(),
                                style = MaterialTheme.typography.titleMedium,
                                fontWeight = FontWeight.Medium,
                                color = MaterialTheme.colorScheme.onBackground,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                                modifier = Modifier.weight(1f, fill = false)
                            )
                            if (character.isDefault) {
                                Spacer(Modifier.width(6.dp))
                                Surface(
                                    shape = RoundedCornerShape(3.dp),
                                    color = Secondary.copy(alpha = 0.15f)
                                ) {
                                    Text(
                                        "官方",
                                        modifier = Modifier.padding(horizontal = 4.dp, vertical = 1.dp),
                                        style = MaterialTheme.typography.labelSmall.copy(fontSize = AppFontSizes.captionSmall),
                                        color = Secondary
                                    )
                                }
                            }
                            val ownerLabel = character.listOwnerLabel()
                            if (!isOwned && ownerLabel.isNotBlank()) {
                                Spacer(Modifier.width(6.dp))
                                Text(
                                    text = ownerLabel,
                                    style = MaterialTheme.typography.labelSmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.5f),
                                    maxLines = 1
                                )
                            }
                        }
                        Spacer(Modifier.height(4.dp))
                        val secondLine = listSubtitleLine.trim().ifBlank { character.displayDescription() }
                        Text(
                            text = secondLine,
                            style = MaterialTheme.typography.labelMedium.copy(lineHeight = 18.sp),
                            color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.7f),
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                            softWrap = false,
                        )
                    }
                    if (isOwned) {
                        Spacer(Modifier.width(trailingGap))
                        val moreForA11y = "${character.displayName()} 的更多操作"
                        val timeLabel = if (modeLastChatMs > 0L) formatLastChatTimeMs(modeLastChatMs) else null
                        Box(
                            Modifier
                                .width(menuSlotWidth)
                                .offset(y = trailingVerticalNudgeY)
                        ) {
                            Box(
                                modifier = Modifier
                                    .align(Alignment.TopEnd)
                                    .size(menuSlotWidth, 48.dp)
                                    .graphicsLayer { clip = false }
                            ) {
                                IconButton(
                                    onClick = { showMenu = true },
                                    modifier = Modifier
                                        .align(Alignment.CenterEnd)
                                        .offset(y = menuIconNudgeY)
                                        .size(48.dp)
                                        .semantics { contentDescription = moreForA11y }
                                ) {
                                    Icon(
                                        Icons.Filled.MoreVert,
                                        contentDescription = null,
                                        tint = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.4f),
                                        modifier = Modifier.size(20.dp)
                                    )
                                }
                                if (timeLabel != null) {
                                    Text(
                                        text = timeLabel,
                                        style = MaterialTheme.typography.labelSmall.copy(
                                            fontSize = 10.sp,
                                            lineHeight = 12.sp
                                        ),
                                        color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.5f),
                                        maxLines = 1,
                                        overflow = TextOverflow.Ellipsis,
                                        textAlign = TextAlign.End,
                                        modifier = Modifier
                                            .align(Alignment.TopEnd)
                                            .offset(y = -timeFloatOffsetY)
                                            .fillMaxWidth()
                                            .padding(end = menuIconVisualEndPadding)
                                    )
                                }
                                DropdownMenu(
                                    expanded = showMenu,
                                    onDismissRequest = { showMenu = false },
                                    modifier = Modifier.widthIn(min = 200.dp),
                                    shape = RoundedCornerShape(12.dp),
                                    containerColor = characterCardActionMenuContainerColor(),
                                    border = characterCardActionMenuBorder(),
                                    tonalElevation = 3.dp,
                                    shadowElevation = 6.dp
                                ) {
                                    if (onTogglePin != null) {
                                        DropdownMenuItem(
                                            text = { Text(if (isPinned) "取消置顶" else "置顶", color = actionMenuTextColor) },
                                            leadingIcon = {
                                                PinToggleMenuIcon(
                                                    showStrikethrough = isPinned,
                                                    tint = if (isPinned) actionMenuMutedTextColor else actionMenuPrimaryColor
                                                )
                                            },
                                            onClick = { showMenu = false; onTogglePin() }
                                        )
                                        HorizontalDivider(color = actionMenuDivider)
                                    }
                                    if (!character.isEditBlockedFor(AppPreferences(LocalContext.current).username)) {
                                        DropdownMenuItem(
                                            text = { Text("编辑", color = actionMenuTextColor) },
                                            leadingIcon = { Icon(Icons.Filled.Edit, contentDescription = null, tint = actionMenuPrimaryColor) },
                                            onClick = { showMenu = false; onEdit() }
                                        )
                                    }
                                    DropdownMenuItem(
                                        text = { Text("复制角色", color = actionMenuTextColor) },
                                        leadingIcon = { Icon(Icons.Filled.ContentCopy, contentDescription = null, tint = actionMenuPrimaryColor) },
                                        onClick = { showMenu = false; onDuplicate() }
                                    )
                                    if (onTogglePublish != null && canManagePublish) {
                                        if (character.isPublic) {
                                            val t = actionMenuMutedTextColor
                                            DropdownMenuItem(
                                                text = { Text("取消发布", color = t) },
                                                leadingIcon = {
                                                    PublishToggleMenuIcon(
                                                        showStrikethrough = true,
                                                        tint = t
                                                    )
                                                },
                                                onClick = { showMenu = false; onTogglePublish() }
                                            )
                                        } else {
                                            DropdownMenuItem(
                                                text = { Text("发布到大厅", color = actionMenuTextColor) },
                                                leadingIcon = {
                                                    PublishToggleMenuIcon(
                                                        showStrikethrough = false,
                                                        tint = actionMenuPrimaryColor
                                                    )
                                                },
                                                onClick = { showMenu = false; onTogglePublish() }
                                            )
                                        }
                                    }
                                    Spacer(Modifier.height(4.dp))
                                    Text(
                                        "危险操作",
                                        style = MaterialTheme.typography.labelSmall,
                                        color = actionMenuTextColor.copy(0.45f),
                                        modifier = Modifier.padding(horizontal = 12.dp, vertical = 2.dp)
                                    )
                                    Spacer(Modifier.height(2.dp))
                                    HorizontalDivider(color = actionMenuDivider)
                                    DropdownMenuItem(
                                        text = { Text("删除", color = actionMenuDeleteColor) },
                                        leadingIcon = { Icon(Icons.Filled.Delete, contentDescription = null, tint = actionMenuDeleteColor) },
                                        onClick = { showMenu = false; onDelete() }
                                    )
                                }
                            }
                        }
                    } else {
                        if (onAddFromHall != null) {
                            Spacer(Modifier.width(4.dp))
                            Icon(
                                Icons.Filled.PersonAdd,
                                contentDescription = "添加到我的角色",
                                tint = Primary,
                                modifier = Modifier
                                    .size(20.dp)
                                    .clickable { onAddFromHall() }
                            )
                        }
                    }
                }
            }
        }
    }
}

/** 置顶/取消置顶：图钉；取消置顶时在图钉上叠对角划线。 */
@Composable
private fun PinToggleMenuIcon(
    showStrikethrough: Boolean,
    tint: Color
) {
    if (!showStrikethrough) {
        Icon(
            imageVector = Icons.Filled.PushPin,
            contentDescription = null,
            tint = tint
        )
    } else {
        Box(
            modifier = Modifier.size(24.dp),
            contentAlignment = Alignment.Center
        ) {
            Icon(
                imageVector = Icons.Filled.PushPin,
                contentDescription = null,
                modifier = Modifier.size(20.dp),
                tint = tint
            )
            Canvas(Modifier.matchParentSize()) {
                val pad = 2.5.dp.toPx()
                drawLine(
                    color = tint,
                    start = Offset(pad, size.height - pad),
                    end = Offset(size.width - pad, pad),
                    strokeWidth = 1.5.dp.toPx()
                )
            }
        }
    }
}

/** 发布/取消发布：向上箭头；取消发布时在箭头上加对角划线（示意撤回发布）。 */
@Composable
private fun PublishToggleMenuIcon(
    showStrikethrough: Boolean,
    tint: Color
) {
    if (!showStrikethrough) {
        Icon(
            imageVector = Icons.Filled.ArrowUpward,
            contentDescription = null,
            tint = tint
        )
    } else {
        Box(
            modifier = Modifier.size(24.dp),
            contentAlignment = Alignment.Center
        ) {
            Icon(
                imageVector = Icons.Filled.ArrowUpward,
                contentDescription = null,
                modifier = Modifier.size(20.dp),
                tint = tint
            )
            Canvas(Modifier.matchParentSize()) {
                val pad = 2.5.dp.toPx()
                drawLine(
                    color = tint,
                    start = Offset(pad, size.height - pad),
                    end = Offset(size.width - pad, pad),
                    strokeWidth = 1.5.dp.toPx()
                )
            }
        }
    }
}

private fun Character.canManagePublishing(username: String): Boolean {
    val current = username.trim()
    if (current.isBlank()) return false
    if (isLockedOfficialReference()) return false
    if (sourceId?.isNotBlank() == true || originalId?.isNotBlank() == true) return false
    return ownerRaw?.trim()?.equals(current, ignoreCase = true) == true ||
        owner?.trim()?.equals(current, ignoreCase = true) == true
}

private fun Character.listOwnerLabel(): String {
    if (isSystemPublished()) return "认证角色"
    val ownerName = owner?.trim().orEmpty()
    return ownerName.takeIf { it.isNotBlank() }?.let { "by $it" }.orEmpty()
}

/** 将毫秒时间戳格式化为易读的相对时间字符串 */
private fun formatLastChatTimeMs(ms: Long): String? {
    if (ms <= 0L) return null
    return try {
        val date = java.util.Date(ms)
        val cal = Calendar.getInstance().apply { time = date }
        val now = Calendar.getInstance()
        val isSameDay = cal.get(Calendar.YEAR) == now.get(Calendar.YEAR) &&
                cal.get(Calendar.DAY_OF_YEAR) == now.get(Calendar.DAY_OF_YEAR)
        val isYesterday = run {
            val yesterday = Calendar.getInstance().apply { add(Calendar.DAY_OF_YEAR, -1) }
            cal.get(Calendar.YEAR) == yesterday.get(Calendar.YEAR) &&
                    cal.get(Calendar.DAY_OF_YEAR) == yesterday.get(Calendar.DAY_OF_YEAR)
        }
        val isSameYear = cal.get(Calendar.YEAR) == now.get(Calendar.YEAR)
        when {
            isSameDay -> SimpleDateFormat("HH:mm", Locale.getDefault()).format(date)
            isYesterday -> "昨天"
            isSameYear -> SimpleDateFormat("M月d日", Locale.getDefault()).format(date)
            else -> SimpleDateFormat("yy/M/d", Locale.getDefault()).format(date)
        }
    } catch (_: Exception) { null }
}

