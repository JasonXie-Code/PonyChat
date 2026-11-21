package top.ponychat.webview.ui.common

import androidx.compose.foundation.BorderStroke
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.unit.dp
import top.ponychat.webview.ui.theme.ErrorColor
import top.ponychat.webview.ui.theme.PopupMenuBackground
import top.ponychat.webview.ui.theme.PopupMenuDanger
import top.ponychat.webview.ui.theme.PopupMenuOnBackground
import top.ponychat.webview.ui.theme.PrimaryLight

@Composable
fun adaptivePopupMenuIsDarkTheme(): Boolean =
    MaterialTheme.colorScheme.background.luminance() < 0.5f

@Composable
fun adaptivePopupMenuContainerColor(): Color =
    if (adaptivePopupMenuIsDarkTheme()) PopupMenuBackground else MaterialTheme.colorScheme.surface

@Composable
fun adaptivePopupMenuContentColor(): Color =
    if (adaptivePopupMenuIsDarkTheme()) PopupMenuOnBackground else MaterialTheme.colorScheme.onSurface

@Composable
fun adaptivePopupMenuAccentColor(): Color =
    if (adaptivePopupMenuIsDarkTheme()) PrimaryLight else MaterialTheme.colorScheme.primary

@Composable
fun adaptivePopupMenuDangerColor(): Color =
    if (adaptivePopupMenuIsDarkTheme()) PopupMenuDanger else ErrorColor

@Composable
fun adaptivePopupMenuBorder(): BorderStroke? =
    if (adaptivePopupMenuIsDarkTheme()) {
        null
    } else {
        BorderStroke(1.dp, MaterialTheme.colorScheme.outline.copy(alpha = 0.22f))
    }
