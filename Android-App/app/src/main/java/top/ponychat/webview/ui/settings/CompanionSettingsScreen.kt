package top.ponychat.webview.ui.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Subject
import androidx.compose.material.icons.filled.AspectRatio
import androidx.compose.material.icons.filled.DisplaySettings
import androidx.compose.material.icons.filled.FormatSize
import androidx.compose.material.icons.filled.Palette
import androidx.compose.material.icons.filled.RecordVoiceOver
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.Surface
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.ui.common.PonyTopBar
import top.ponychat.webview.ui.theme.LocalFontScale
import top.ponychat.webview.ui.theme.Primary
import top.ponychat.webview.ui.theme.ScaledSwitch

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CompanionSettingsScreen(
    prefs: AppPreferences,
    onNavigateBack: () -> Unit
) {
    var companionCardAlpha by remember { mutableIntStateOf(prefs.companionCardAlpha) }
    var companionCardWidth by remember { mutableStateOf(prefs.companionCardWidth) }
    var companionCardFontSize by remember { mutableStateOf(prefs.companionCardFontSize) }
    var companionCardTextColor by remember { mutableStateOf(prefs.companionCardTextColor) }
    var companionCardMaxChars by remember { mutableIntStateOf(prefs.companionCardMaxChars) }
    var companionVoiceEnabled by remember { mutableStateOf(prefs.companionVoiceEnabled) }
    val leadingIconSize = 20.dp * LocalFontScale.current

    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        topBar = {
            PonyTopBar(
                title = "陪玩设置",
                onNavigateBack = onNavigateBack
            )
        }
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .verticalScroll(rememberScrollState())
        ) {
            SectionTitle("卡片显示")
            SettingsCard {
                Column(modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(Icons.Filled.DisplaySettings, contentDescription = null, tint = Primary, modifier = Modifier.size(leadingIconSize))
                        Spacer(Modifier.size(12.dp))
                        Text("弹幕卡片透明度", style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.onBackground, modifier = Modifier.weight(1f))
                        Text("${companionCardAlpha}%", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    Spacer(Modifier.height(8.dp))
                    Slider(
                        value = companionCardAlpha.toFloat(),
                        onValueChange = {
                            companionCardAlpha = it.toInt()
                            prefs.companionCardAlpha = companionCardAlpha
                        },
                        valueRange = 10f..100f,
                        steps = 17,
                        colors = SliderDefaults.colors(thumbColor = Primary, activeTrackColor = Primary)
                    )
                    Text("调低透明度可减少画面遮挡", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                CardDivider()
                Column(modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(Icons.Filled.AspectRatio, contentDescription = null, tint = Primary, modifier = Modifier.size(leadingIconSize))
                        Spacer(Modifier.size(12.dp))
                        Text("卡片宽度", style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.onBackground)
                    }
                    Spacer(Modifier.height(8.dp))
                    SingleChoiceSegmentedButtonRow(modifier = Modifier.fillMaxWidth()) {
                        SegmentedButton(selected = companionCardWidth == "small", onClick = { companionCardWidth = "small"; prefs.companionCardWidth = "small" }, shape = SegmentedButtonDefaults.itemShape(0, 3)) { Text("窄") }
                        SegmentedButton(selected = companionCardWidth == "medium", onClick = { companionCardWidth = "medium"; prefs.companionCardWidth = "medium" }, shape = SegmentedButtonDefaults.itemShape(1, 3)) { Text("标准") }
                        SegmentedButton(selected = companionCardWidth == "large", onClick = { companionCardWidth = "large"; prefs.companionCardWidth = "large" }, shape = SegmentedButtonDefaults.itemShape(2, 3)) { Text("宽") }
                    }
                }
                CardDivider()
                Column(modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(Icons.Filled.FormatSize, contentDescription = null, tint = Primary, modifier = Modifier.size(leadingIconSize))
                        Spacer(Modifier.size(12.dp))
                        Text("卡片字号", style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.onBackground)
                    }
                    Spacer(Modifier.height(8.dp))
                    SingleChoiceSegmentedButtonRow(modifier = Modifier.fillMaxWidth()) {
                        SegmentedButton(selected = companionCardFontSize == "small", onClick = { companionCardFontSize = "small"; prefs.companionCardFontSize = "small" }, shape = SegmentedButtonDefaults.itemShape(0, 4)) { Text("小") }
                        SegmentedButton(selected = companionCardFontSize == "medium", onClick = { companionCardFontSize = "medium"; prefs.companionCardFontSize = "medium" }, shape = SegmentedButtonDefaults.itemShape(1, 4)) { Text("中") }
                        SegmentedButton(selected = companionCardFontSize == "large", onClick = { companionCardFontSize = "large"; prefs.companionCardFontSize = "large" }, shape = SegmentedButtonDefaults.itemShape(2, 4)) { Text("大") }
                        SegmentedButton(selected = companionCardFontSize == "xlarge", onClick = { companionCardFontSize = "xlarge"; prefs.companionCardFontSize = "xlarge" }, shape = SegmentedButtonDefaults.itemShape(3, 4)) { Text("特大") }
                    }
                }
                CardDivider()
                Column(modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(Icons.Filled.Palette, contentDescription = null, tint = Primary, modifier = Modifier.size(leadingIconSize))
                        Spacer(Modifier.size(12.dp))
                        Text("文字颜色", style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.onBackground)
                    }
                    Spacer(Modifier.height(8.dp))
                    SingleChoiceSegmentedButtonRow(modifier = Modifier.fillMaxWidth()) {
                        SegmentedButton(selected = companionCardTextColor == "white", onClick = { companionCardTextColor = "white"; prefs.companionCardTextColor = "white" }, shape = SegmentedButtonDefaults.itemShape(0, 3)) { Text("白") }
                        SegmentedButton(selected = companionCardTextColor == "yellow", onClick = { companionCardTextColor = "yellow"; prefs.companionCardTextColor = "yellow" }, shape = SegmentedButtonDefaults.itemShape(1, 3)) { Text("黄", color = if (companionCardTextColor == "yellow") Color(0xFFFFE57F) else MaterialTheme.colorScheme.onSurface) }
                        SegmentedButton(selected = companionCardTextColor == "cyan", onClick = { companionCardTextColor = "cyan"; prefs.companionCardTextColor = "cyan" }, shape = SegmentedButtonDefaults.itemShape(2, 3)) { Text("青", color = if (companionCardTextColor == "cyan") Color(0xFF80DEEA) else MaterialTheme.colorScheme.onSurface) }
                    }
                }
            }

            Spacer(Modifier.height(12.dp))

            SectionTitle("交互偏好")
            SettingsCard {
                Column(modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(Icons.AutoMirrored.Filled.Subject, contentDescription = null, tint = Primary, modifier = Modifier.size(leadingIconSize))
                        Spacer(Modifier.size(12.dp))
                        Text("回复字数", style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.onBackground, modifier = Modifier.weight(1f))
                        Text("$companionCardMaxChars 字", style = MaterialTheme.typography.bodySmall, color = Primary)
                    }
                    Spacer(Modifier.height(8.dp))
                    var charsSlider by remember { mutableFloatStateOf((companionCardMaxChars / 10f) - 1f) }
                    Slider(
                        value = charsSlider,
                        onValueChange = { charsSlider = it },
                        onValueChangeFinished = {
                            companionCardMaxChars = (charsSlider.toInt() + 1) * 10
                            prefs.companionCardMaxChars = companionCardMaxChars
                        },
                        valueRange = 0f..4f,
                        steps = 3,
                        colors = SliderDefaults.colors(thumbColor = Primary, activeTrackColor = Primary)
                    )
                    Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                        listOf("10", "20", "30", "40", "50").forEach {
                            Text(it, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                    }
                }
                CardDivider()
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 16.dp, vertical = 14.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Icon(Icons.Filled.RecordVoiceOver, contentDescription = null, tint = Primary, modifier = Modifier.size(leadingIconSize))
                    Spacer(Modifier.size(12.dp))
                    Column(modifier = Modifier.weight(1f)) {
                        Text("AI 语音", style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.onBackground)
                        Text(
                            if (companionVoiceEnabled) "AI 回复时同步播放语音" else "已关闭，仅显示文字字幕",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                    ScaledSwitch(
                        checked = companionVoiceEnabled,
                        onCheckedChange = {
                            companionVoiceEnabled = it
                            prefs.companionVoiceEnabled = it
                        },
                        colors = SwitchDefaults.colors(
                            checkedThumbColor = Color.White,
                            checkedTrackColor = Primary
                        )
                    )
                }
            }

            Spacer(Modifier.height(20.dp))
        }
    }
}

@Composable
private fun SectionTitle(text: String) {
    Text(
        text = text,
        style = MaterialTheme.typography.labelMedium,
        fontWeight = FontWeight.Medium,
        color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.6f),
        modifier = Modifier.padding(start = 24.dp, top = 8.dp, bottom = 8.dp)
    )
}

@Composable
private fun SettingsCard(content: @Composable () -> Unit) {
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 12.dp),
        shape = RoundedCornerShape(12.dp),
        color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f),
        border = CardDefaults.outlinedCardBorder()
    ) {
        Column { content() }
    }
}

@Composable
private fun CardDivider() {
    HorizontalDivider(
        modifier = Modifier.padding(start = 48.dp),
        color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.1f)
    )
}
