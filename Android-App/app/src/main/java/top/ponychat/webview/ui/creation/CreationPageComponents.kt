package top.ponychat.webview.ui.creation

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.activity.compose.BackHandler
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import top.ponychat.webview.ui.common.PonyTopBar
import top.ponychat.webview.ui.common.SystemNavigationBarColorEffect
import top.ponychat.webview.ui.theme.Primary

@Composable
internal fun CreationPage(title: String, onBack: () -> Unit, actions: @Composable RowScope.() -> Unit = {}, content: @Composable ColumnScope.() -> Unit) {
    SystemNavigationBarColorEffect(color = MaterialTheme.colorScheme.background)
    Surface(color = MaterialTheme.colorScheme.background, contentColor = MaterialTheme.colorScheme.onBackground,
        modifier = Modifier.fillMaxSize()) {
        Column(Modifier.fillMaxSize()) {
            PonyTopBar(title = title, onNavigateBack = onBack, actions = actions)
            Column(Modifier.weight(1f).fillMaxWidth().navigationBarsPadding().imePadding(), content = content)
        }
    }
}

@Composable
internal fun CreationTextField(value: String, onValueChange: (String) -> Unit, label: String,
    modifier: Modifier = Modifier, minLines: Int = 1, maxLines: Int = 10, hint: String = "") {
    val colors = MaterialTheme.colorScheme
    OutlinedTextField(value, onValueChange, modifier = modifier.fillMaxWidth(), minLines = minLines, maxLines = maxLines,
        label = { Text(label) }, placeholder = { Text(hint) }, shape = RoundedCornerShape(16.dp),
        colors = OutlinedTextFieldDefaults.colors(
            focusedTextColor = colors.onSurface, unfocusedTextColor = colors.onSurface,
            focusedContainerColor = colors.surface, unfocusedContainerColor = colors.surface,
            cursorColor = Primary, focusedBorderColor = Primary, unfocusedBorderColor = colors.outline.copy(alpha = .4f),
            focusedLabelColor = Primary, unfocusedLabelColor = colors.onSurfaceVariant,
            focusedPlaceholderColor = colors.onSurfaceVariant.copy(alpha = .5f),
            unfocusedPlaceholderColor = colors.onSurfaceVariant.copy(alpha = .5f)))
}

@Composable
internal fun CreationCard(modifier: Modifier = Modifier, selected: Boolean = false, content: @Composable ColumnScope.() -> Unit) {
    Surface(modifier = modifier, shape = RoundedCornerShape(16.dp),
        color = if (selected) Primary.copy(alpha = .15f) else MaterialTheme.colorScheme.surface,
        contentColor = MaterialTheme.colorScheme.onSurface,
        border = BorderStroke(1.dp, if (selected) Primary else MaterialTheme.colorScheme.outline.copy(alpha = .18f))) {
        Column(content = content)
    }
}

/** Route toolbar back and Android back through the same save-on-exit action. */
@Composable
internal fun creationExitAction(changed: Boolean, saving: Boolean, onBack: () -> Unit, onSave: () -> Unit): () -> Unit {
    val exit = { if (!saving) { if (changed) onSave() else onBack() } }
    BackHandler { exit() }
    return exit
}
