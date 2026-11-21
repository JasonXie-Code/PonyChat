package top.ponychat.webview.ui.settings

import androidx.compose.foundation.layout.Column
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.ui.theme.Primary

@Composable
@Suppress("UNUSED_PARAMETER")
fun EditNetworkDialog(
    currentWanUrls: String,
    currentLanUrl: String,
    currentRouteMode: String = "wan",
    fullNetworkSettings: Boolean = false,
    effectiveApiBase: String = AppPreferences.DEFAULT_WAN_URL,
    activeApiBaseDisplay: String = AppPreferences.DEFAULT_WAN_URL,
    networkTypeLabel: String = "未知",
    pingMs: Long? = null,
    recommendation: String? = null,
    isTestingNetwork: Boolean = false,
    onDismiss: () -> Unit,
    onSave: (wan: String, lan: String, routeMode: String) -> Unit,
    onClearLan: (() -> Unit)? = null,
    onRunSpeedTest: (() -> Unit)? = null
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = MaterialTheme.colorScheme.surface,
        title = {
            Text(
                if (fullNetworkSettings) "网络连接设置" else "服务器地址",
                color = MaterialTheme.colorScheme.onBackground
            )
        },
        text = {
            Column {
                Text(
                    "当前服务器",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                Text(
                    AppPreferences.DEFAULT_WAN_URL,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onBackground
                )
            }
        },
        confirmButton = {
            TextButton(
                onClick = {
                    onSave(AppPreferences.DEFAULT_WAN_URL, "", "wan")
                    onDismiss()
                }
            ) {
                Text("关闭", color = Primary, fontWeight = FontWeight.Bold)
            }
        },
        dismissButton = null
    )
}
