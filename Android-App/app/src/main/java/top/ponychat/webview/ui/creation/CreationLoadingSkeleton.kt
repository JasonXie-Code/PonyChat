package top.ponychat.webview.ui.creation

import androidx.compose.foundation.layout.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import top.ponychat.webview.ui.common.SkeletonBlock
import top.ponychat.webview.ui.common.loadingSemantics

@Composable
internal fun CreationReplySkeleton() {
    Column(Modifier.fillMaxWidth().loadingSemantics().padding(vertical = 8.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            SkeletonBlock(Modifier.size(40.dp), radius = 20.dp)
            SkeletonBlock(Modifier.width(108.dp).height(14.dp))
        }
        Spacer(Modifier.height(18.dp))
        Column(verticalArrangement = Arrangement.spacedBy(14.dp)) {
            SkeletonBlock(Modifier.fillMaxWidth(.92f).height(16.dp))
            SkeletonBlock(Modifier.fillMaxWidth().height(16.dp))
            SkeletonBlock(Modifier.fillMaxWidth(.68f).height(16.dp))
        }
    }
}

@Composable
internal fun CreationLoadingSkeleton() {
    Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(28.dp)) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
            SkeletonBlock(Modifier.width(144.dp).height(44.dp), radius = 16.dp)
            Spacer(Modifier.width(10.dp))
            SkeletonBlock(Modifier.size(40.dp), radius = 20.dp)
        }
        CreationReplySkeleton()
        CreationReplySkeleton()
    }
}

@Composable
internal fun CreationPendingReplyBody() {
    Column(Modifier.fillMaxWidth().padding(vertical = 8.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
        SkeletonBlock(Modifier.fillMaxWidth(.92f).height(16.dp))
        SkeletonBlock(Modifier.fillMaxWidth().height(16.dp))
        SkeletonBlock(Modifier.fillMaxWidth(.68f).height(16.dp))
    }
}
