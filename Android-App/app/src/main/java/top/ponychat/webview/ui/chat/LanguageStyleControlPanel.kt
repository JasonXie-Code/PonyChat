package top.ponychat.webview.ui.chat

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import top.ponychat.webview.ui.theme.Primary

internal val sexualLanguageStyleKeys = listOf("euphemistic", "default", "direct")
internal fun sexualLanguageStyleCn(style: String) = when (style) { "euphemistic" -> "委婉"; "default" -> "默认"; else -> "直白" }

@Composable
internal fun LanguageStyleControlPanel(style: String, enabled: Boolean, onSelect: (String) -> Unit) {
    val selected = sexualLanguageStyleKeys.indexOf(style).coerceAtLeast(0)
    Surface(color = MaterialTheme.colorScheme.surfaceVariant, shape = RoundedCornerShape(18.dp)) {
        Column(Modifier.fillMaxWidth().padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("语言风格", style = MaterialTheme.typography.labelLarge)
            Text(sexualLanguageStyleCn(style), style = MaterialTheme.typography.bodyLarge, fontWeight = FontWeight.SemiBold, color = Primary)
            Slider(value = selected.toFloat(), onValueChange = { onSelect(sexualLanguageStyleKeys[it.toInt().coerceIn(0, 2)]) }, valueRange = 0f..2f, steps = 1, enabled = enabled, modifier = Modifier.fillMaxWidth().semantics { contentDescription = "性相关语言风格：${sexualLanguageStyleCn(style)}" }, colors = SliderDefaults.colors(thumbColor = Primary, activeTrackColor = Primary))
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) { sexualLanguageStyleKeys.forEach { Text(sexualLanguageStyleCn(it), style = MaterialTheme.typography.labelSmall, color = if (it == style) Primary else MaterialTheme.colorScheme.onSurfaceVariant) } }
        }
    }
}
