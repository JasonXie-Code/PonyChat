package top.ponychat.webview.ui.chat

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AutoAwesome
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import top.ponychat.webview.ui.theme.PonyContrastColors
import top.ponychat.webview.ui.theme.ponyNeutralContainerColors

private val RelationshipMoodLightAccent = Color(0xFF0EA5E9)
private val RelationshipMoodLightContainer = Color(0xFFE0F2FE)
private val RelationshipMoodLightContent = Color(0xFF075985)
private val RelationshipMoodLightBorder = Color(0xFF7DD3FC)
private val RelationshipMoodDarkAccent = Color(0xFF38BDF8)
private val RelationshipMoodDarkContainer = Color(0xFF0B2A3D)
private val RelationshipMoodDarkContent = Color(0xFFBAE6FD)
private val RelationshipMoodDarkBorder = Color(0xFF0284C7)

private data class RelationshipMoodColors(
    val accent: Color,
    val container: PonyContrastColors
)

@Composable
internal fun RelationshipMoodCard(mood: String, chips: List<String>) {
    val moodColors = relationshipMoodColors()
    RelationshipBlock(title = "此刻的感觉", icon = Icons.Filled.AutoAwesome, iconTint = moodColors.accent) {
        Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text(
                text = mood,
                color = MaterialTheme.colorScheme.onSurface,
                style = MaterialTheme.typography.bodyMedium
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                chips.forEach { chip ->
                    RelationshipChip(chip, colors = moodColors.container)
                }
            }
        }
    }
}

@Composable
internal fun RelationshipPortraitCard(
    title: String,
    body: String,
    modifier: Modifier = Modifier
) {
    val cardColors = ponyNeutralContainerColors()
    Surface(
        modifier = modifier,
        color = cardColors.container,
        shape = RoundedCornerShape(18.dp),
        border = BorderStroke(1.dp, cardColors.border)
    ) {
        Column(
            modifier = Modifier.padding(horizontal = 13.dp, vertical = 14.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            Text(
                text = title,
                color = MaterialTheme.colorScheme.onBackground,
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.SemiBold
            )
            Text(
                text = body,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
                maxLines = 4,
                overflow = TextOverflow.Ellipsis
            )
        }
    }
}

@Composable
internal fun RelationshipMemoryBlock(
    title: String,
    items: List<String>
) {
    RelationshipBlock(title = title) {
        Column(verticalArrangement = Arrangement.spacedBy(9.dp)) {
            items.forEach { item ->
                RelationshipNote(item)
            }
        }
    }
}

@Composable
internal fun RelationshipTimelineBlock(items: List<String>) {
    RelationshipBlock(title = "最近共同经历") {
        Column(verticalArrangement = Arrangement.spacedBy(9.dp)) {
            items.forEach { item ->
                RelationshipNote(item)
            }
        }
    }
}

@Composable
internal fun RelationshipSuggestionBlock(suggestions: List<String>) {
    RelationshipBlock(title = "下一次可以聊") {
        Column(verticalArrangement = Arrangement.spacedBy(9.dp)) {
            suggestions.forEach { suggestion ->
                RelationshipSuggestionRow(suggestion)
            }
        }
    }
}

@Composable
private fun relationshipMoodColors(): RelationshipMoodColors {
    val isLight = MaterialTheme.colorScheme.background.luminance() > 0.5f
    return if (isLight) {
        RelationshipMoodColors(
            accent = RelationshipMoodLightAccent,
            container = PonyContrastColors(
                container = RelationshipMoodLightContainer,
                content = RelationshipMoodLightContent,
                border = RelationshipMoodLightBorder
            )
        )
    } else {
        RelationshipMoodColors(
            accent = RelationshipMoodDarkAccent,
            container = PonyContrastColors(
                container = RelationshipMoodDarkContainer,
                content = RelationshipMoodDarkContent,
                border = RelationshipMoodDarkBorder
            )
        )
    }
}

@Composable
private fun RelationshipSuggestionRow(text: String) {
    Row(verticalAlignment = Alignment.Top, modifier = Modifier.fillMaxWidth()) {
        Box(
            modifier = Modifier
                .padding(top = 7.dp)
                .size(8.dp)
                .background(MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.42f), CircleShape)
        )
        Spacer(Modifier.width(10.dp))
        Text(
            text = text,
            color = MaterialTheme.colorScheme.onSurface,
            style = MaterialTheme.typography.bodySmall,
            modifier = Modifier.weight(1f)
        )
    }
}

@Composable
private fun RelationshipNote(text: String) {
    val noteColors = ponyNeutralContainerColors(strong = true)
    Surface(
        color = noteColors.container,
        shape = RoundedCornerShape(12.dp),
        border = BorderStroke(1.dp, noteColors.border),
        modifier = Modifier.fillMaxWidth()
    ) {
        Text(
            text = text,
            color = noteColors.content,
            style = MaterialTheme.typography.bodySmall,
            modifier = Modifier.padding(horizontal = 12.dp, vertical = 10.dp)
        )
    }
}

@Composable
private fun RelationshipChip(text: String, colors: PonyContrastColors) {
    Surface(
        shape = RoundedCornerShape(999.dp),
        color = colors.container,
        border = BorderStroke(1.dp, colors.border)
    ) {
        Text(
            text = text,
            color = colors.content,
            style = MaterialTheme.typography.labelSmall,
            fontWeight = FontWeight.SemiBold,
            modifier = Modifier.padding(horizontal = 10.dp, vertical = 6.dp)
        )
    }
}

@Composable
private fun RelationshipBlock(
    title: String,
    icon: ImageVector? = null,
    iconTint: Color = MaterialTheme.colorScheme.onSurfaceVariant,
    content: @Composable () -> Unit
) {
    val blockColors = ponyNeutralContainerColors()
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = blockColors.container,
        shape = RoundedCornerShape(18.dp),
        border = BorderStroke(1.dp, blockColors.border)
    ) {
        Column(
            modifier = Modifier.padding(horizontal = 15.dp, vertical = 14.dp),
            verticalArrangement = Arrangement.spacedBy(11.dp)
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                if (icon != null) {
                    Icon(
                        icon,
                        contentDescription = null,
                        tint = iconTint,
                        modifier = Modifier.size(18.dp)
                    )
                    Spacer(Modifier.width(8.dp))
                }
                Text(
                    text = title,
                    color = MaterialTheme.colorScheme.onBackground,
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.SemiBold
                )
            }
            content()
        }
    }
}
