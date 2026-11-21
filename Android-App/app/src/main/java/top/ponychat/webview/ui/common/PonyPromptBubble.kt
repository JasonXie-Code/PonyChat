package top.ponychat.webview.ui.common

import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.unit.dp
import top.ponychat.webview.util.formatErrorForDisplay

@Composable
fun PonyPromptBubble(
    message: String,
    modifier: Modifier = Modifier
) {
    val displayMessage = formatErrorForDisplay(message, compact = true)
    val isDark = MaterialTheme.colorScheme.background.luminance() < 0.5f
    Surface(
        modifier = modifier,
        shape = RoundedCornerShape(24.dp),
        color = if (isDark) Color(0xE6323232) else Color(0xF0FFFFFF),
        shadowElevation = 0.dp
    ) {
        Text(
            text = displayMessage,
            style = MaterialTheme.typography.bodyMedium,
            color = if (isDark) Color.White else Color(0xFF333333),
            modifier = Modifier.padding(horizontal = 24.dp, vertical = 12.dp)
        )
    }
}
