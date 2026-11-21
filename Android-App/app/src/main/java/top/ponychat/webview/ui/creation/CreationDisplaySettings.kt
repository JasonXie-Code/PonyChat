package top.ponychat.webview.ui.creation

import androidx.compose.foundation.layout.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.ui.theme.ScaledSwitch

@Composable
internal fun CreationDisplaySettings(prefs: AppPreferences, onBack: () -> Unit, onChanged: () -> Unit) {
    val feedback = creationHapticAction()
    var dark by remember { mutableStateOf(prefs.isDarkTheme) }
    var scale by remember { mutableFloatStateOf(prefs.fontScale) }
    var timestamp by remember { mutableStateOf(prefs.showTimestamp) }
    CreationPage("对话设置", onBack) {
        Column(Modifier.padding(16.dp)) {
            Text("显示", color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(bottom = 12.dp))
            CreationCard {
                Row(Modifier.fillMaxWidth().padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
                    Icon(Icons.Default.DarkMode, null, tint = MaterialTheme.colorScheme.primary)
                    Text("深色主题", Modifier.weight(1f).padding(start = 12.dp))
                    ScaledSwitch(dark, { feedback { dark = it; prefs.isDarkTheme = it; onChanged() } })
                }
                HorizontalDivider(color = MaterialTheme.colorScheme.outline.copy(alpha = .15f))
                Column(Modifier.padding(16.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(Icons.Default.TextFields, null, tint = MaterialTheme.colorScheme.primary)
                        Text("字体大小", Modifier.padding(start = 12.dp))
                    }
                    Slider(scale, { value ->
                        if (((value - .85f) * 20).toInt() != ((scale - .85f) * 20).toInt()) feedback {}
                        scale = value; prefs.fontScale = value; onChanged() }, valueRange = .85f..1.25f, steps = 7,
                        onValueChangeFinished = { onChanged() })
                    Text("${if (scale < .95f) "小" else if (scale > 1.1f) "大" else "标准"} (${(scale * 100).toInt()}%)",
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                HorizontalDivider(color = MaterialTheme.colorScheme.outline.copy(alpha = .15f))
                Row(Modifier.fillMaxWidth().padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
                    Icon(Icons.Default.Schedule, null, tint = MaterialTheme.colorScheme.primary)
                    Text("显示时间戳", Modifier.weight(1f).padding(start = 12.dp))
                    ScaledSwitch(timestamp, { feedback { timestamp = it; prefs.showTimestamp = it; onChanged() } })
                }
            }
        }
    }
}
