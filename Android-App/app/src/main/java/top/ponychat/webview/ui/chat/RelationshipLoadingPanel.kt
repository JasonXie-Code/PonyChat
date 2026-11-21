package top.ponychat.webview.ui.chat

import androidx.compose.animation.core.*
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import top.ponychat.webview.data.model.Character
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.ui.theme.ponyNeutralContainerColors

@Composable
internal fun RelationshipLoadingPanel(
    character: Character,
    prefs: AppPreferences,
    displayName: String,
    userDisplayName: String,
    stage: RelationshipStageUi,
    loading: Boolean,
    message: String?,
    modifier: Modifier = Modifier,
    scrollState: androidx.compose.foundation.ScrollState = rememberScrollState()
) {
    val statusStage = stage.copy(label = if (loading) "加载中" else "加载失败")
    val statusMessage = if (loading) "" else
        message ?: "聊一聊之后，这里会记录我们的关系"
    Column(
        modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.background)
            .verticalScroll(scrollState)
            .padding(horizontal = 16.dp, vertical = 14.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        RelationshipHero(
            character = character,
            prefs = prefs,
            displayName = displayName,
            userDisplayName = userDisplayName,
            stage = statusStage,
            overview = statusMessage,
            overviewTextAlign = TextAlign.Center
        )
        if (loading) {
            RelationshipLoadingSkeleton()
        }
    }
}

@Composable
private fun RelationshipLoadingSkeleton() {
    val transition = rememberInfiniteTransition(label = "relationshipLoading")
    val opacity by transition.animateFloat(
        initialValue = 0.10f,
        targetValue = 0.24f,
        animationSpec = infiniteRepeatable(tween(1000, easing = FastOutSlowInEasing), RepeatMode.Reverse),
        label = "placeholderOpacity"
    )
    // Match the loaded page: feeling, two portraits, memories, timeline, suggestions.
    SkeletonRelationshipCard({ opacity }, lines = 2, chips = true)
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        SkeletonRelationshipCard({ opacity }, lines = 2, modifier = Modifier.weight(1f))
        SkeletonRelationshipCard({ opacity }, lines = 2, modifier = Modifier.weight(1f))
    }
    repeat(3) { SkeletonRelationshipCard({ opacity }, lines = 3) }
}

@Composable
private fun SkeletonRelationshipCard(
    opacity: () -> Float,
    lines: Int,
    modifier: Modifier = Modifier,
    chips: Boolean = false
) {
    val colors = ponyNeutralContainerColors()
    Surface(
        modifier = modifier.fillMaxWidth(),
        color = colors.container,
        shape = RoundedCornerShape(18.dp),
        border = BorderStroke(1.dp, colors.border)
    ) {
        Column(Modifier.padding(15.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            RelationshipSkeletonBar(opacity, Modifier.fillMaxWidth(0.42f).height(16.dp))
            Spacer(Modifier.height(2.dp))
            repeat(lines) { index ->
                RelationshipSkeletonBar(opacity,
                    Modifier.fillMaxWidth(if (index == lines - 1) 0.68f else 1f).height(12.dp))
            }
            if (chips) {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    repeat(2) { RelationshipSkeletonBar(opacity, Modifier.width(68.dp).height(24.dp)) }
                }
            }
        }
    }
}

@Composable
private fun RelationshipSkeletonBar(opacity: () -> Float, modifier: Modifier) {
    val color = MaterialTheme.colorScheme.onSurface
    Spacer(modifier.drawBehind {
        drawRoundRect(color.copy(alpha = opacity()), cornerRadius = CornerRadius(6.dp.toPx()))
    })
}
