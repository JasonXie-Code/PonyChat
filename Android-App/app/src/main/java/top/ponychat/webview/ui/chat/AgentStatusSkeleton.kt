package top.ponychat.webview.ui.chat

import androidx.compose.foundation.layout.*
import androidx.compose.material3.HorizontalDivider
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import top.ponychat.webview.ui.common.SkeletonBlock
import top.ponychat.webview.ui.common.loadingSemantics

@Composable
internal fun AgentStatusSkeleton() {
    Column(Modifier.fillMaxWidth().loadingSemantics(), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        SkeletonBlock(Modifier.fillMaxWidth(0.65f).height(22.dp))
        repeat(6) { StatusSkeletonRow(labelWidth = 64) }
        SkeletonBlock(Modifier.fillMaxWidth(0.8f).height(18.dp))
    }
}

@Composable
internal fun ConversationActivitySkeleton(mode: String) {
    Column(Modifier.fillMaxWidth().loadingSemantics(), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        SkeletonBlock(Modifier.fillMaxWidth(0.6f).height(22.dp))
        SkeletonBlock(Modifier.fillMaxWidth().height(36.dp))
        HorizontalDivider()
        repeat(if (mode == "normal") 3 else 1) { StatusSkeletonRow(labelWidth = 72) }
    }
}

@Composable
private fun StatusSkeletonRow(labelWidth: Int) {
    Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        SkeletonBlock(Modifier.width(labelWidth.dp).height(18.dp))
        SkeletonBlock(Modifier.weight(1f).height(18.dp))
    }
}
