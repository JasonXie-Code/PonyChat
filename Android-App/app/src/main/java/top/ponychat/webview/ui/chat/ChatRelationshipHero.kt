package top.ponychat.webview.ui.chat

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import top.ponychat.webview.data.model.Character
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.ui.character.CharacterAvatar
import top.ponychat.webview.ui.common.PonyAvatar

@Composable
internal fun RelationshipHero(
    character: Character,
    prefs: AppPreferences,
    displayName: String,
    userDisplayName: String,
    stage: RelationshipStageUi,
    overview: String,
    overviewTextAlign: TextAlign = TextAlign.Start
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 2.dp, vertical = 8.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(16.dp)
    ) {
        Box(
            modifier = Modifier.fillMaxWidth(),
            contentAlignment = Alignment.Center
        ) {
            val avatarSize = 76
            val halfDistance = stage.avatarDistance / 2f
            Box(
                modifier = Modifier
                    .height((avatarSize + 20).dp)
                    .fillMaxWidth(),
                contentAlignment = Alignment.Center
            ) {
                RelationshipConnectorLine(
                    stage = stage,
                    modifier = Modifier.width(stage.avatarDistance)
                )
                RelationshipPairAvatar(
                    modifier = Modifier
                        .width(avatarSize.dp)
                        .graphicsLayer { translationX = -halfDistance.toPx() }
                ) {
                    CharacterAvatar(
                        avatarUrl = character.avatarUrl(),
                        name = displayName,
                        apiBase = prefs.effectiveApiBase(),
                        size = avatarSize
                    )
                }
                RelationshipPairAvatar(
                    modifier = Modifier
                        .width(avatarSize.dp)
                        .graphicsLayer { translationX = halfDistance.toPx() }
                ) {
                    PonyAvatar(
                        avatarUrl = prefs.avatar,
                        name = userDisplayName,
                        apiBase = prefs.effectiveApiBase(),
                        size = avatarSize
                    )
                }
            }
        }

        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            Text(
                text = stage.label,
                color = MaterialTheme.colorScheme.onBackground,
                style = MaterialTheme.typography.headlineSmall.copy(
                    fontSize = MaterialTheme.typography.headlineSmall.fontSize * 1.3f
                ),
                fontWeight = FontWeight.Bold,
                textAlign = TextAlign.Center,
                modifier = Modifier.fillMaxWidth()
            )
            Text(
                text = "我们的关系",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.titleMedium,
                textAlign = TextAlign.Center,
                modifier = Modifier.fillMaxWidth()
            )
        }

        if (overview.isNotBlank()) {
            Text(
                text = overview,
                color = MaterialTheme.colorScheme.onSurface,
                style = MaterialTheme.typography.bodyMedium,
                textAlign = overviewTextAlign,
                maxLines = 6,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 10.dp)
            )
        }
    }
}

@Composable
private fun RelationshipConnectorLine(
    stage: RelationshipStageUi,
    modifier: Modifier = Modifier
) {
    val effect = stage.connectorEffect()
    val pulse = if (effect == RelationshipConnectorEffect.Pulse) {
        val transition = rememberInfiniteTransition(label = "relationshipConnectorLine")
        val animatedPulse by transition.animateFloat(
            initialValue = 0.35f,
            targetValue = 1f,
            animationSpec = infiniteRepeatable(
                animation = tween(durationMillis = 1350, easing = LinearEasing),
                repeatMode = RepeatMode.Reverse
            ),
            label = "relationshipConnectorPulse"
        )
        animatedPulse
    } else {
        1f
    }
    val lineHeight = if (effect == RelationshipConnectorEffect.Pulse) 18.dp else 8.dp

    Canvas(modifier = modifier.height(lineHeight)) {
        val centerY = size.height / 2f
        val start = Offset(0f, centerY)
        val end = Offset(size.width, centerY)
        val color = stage.accent
        when (effect) {
            RelationshipConnectorEffect.Pulse -> {
                val glowWidth = (7f + pulse * 7f).dp.toPx()
                drawLine(
                    color = color.copy(alpha = 0.12f + pulse * 0.18f),
                    start = start,
                    end = end,
                    strokeWidth = glowWidth,
                    cap = StrokeCap.Round
                )
                drawLine(
                    color = color.copy(alpha = 0.45f + pulse * 0.35f),
                    start = start,
                    end = end,
                    strokeWidth = 3.dp.toPx(),
                    cap = StrokeCap.Round
                )
            }

            RelationshipConnectorEffect.Dashed -> {
                val dash = 14.dp.toPx()
                val gap = 9.dp.toPx()
                drawLine(
                    color = color.copy(alpha = 0.72f),
                    start = start,
                    end = end,
                    strokeWidth = 2.5.dp.toPx(),
                    cap = StrokeCap.Round,
                    pathEffect = PathEffect.dashPathEffect(floatArrayOf(dash, gap), 0f)
                )
            }

            RelationshipConnectorEffect.Solid -> {
                drawLine(
                    color = color.copy(alpha = 0.38f),
                    start = start,
                    end = end,
                    strokeWidth = 1.5.dp.toPx(),
                    cap = StrokeCap.Round
                )
            }
        }
    }
}

@Composable
private fun RelationshipPairAvatar(
    modifier: Modifier = Modifier,
    avatar: @Composable () -> Unit
) {
    Box(
        modifier = modifier,
        contentAlignment = Alignment.Center
    ) {
        avatar()
    }
}

private enum class RelationshipConnectorEffect {
    Solid,
    Pulse,
    Dashed
}

private fun RelationshipStageUi.connectorEffect(): RelationshipConnectorEffect = when (key) {
    "flirting",
    "committed_partner",
    "intimate_partner" -> RelationshipConnectorEffect.Pulse
    "broken_up",
    "in_conflict",
    "mutual_dislike",
    "hurtful_dynamic" -> RelationshipConnectorEffect.Dashed
    else -> RelationshipConnectorEffect.Solid
}
