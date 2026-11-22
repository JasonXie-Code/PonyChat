package top.ponychat.webview.ui.common

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.selection.selectableGroup
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ChatBubbleOutline
import androidx.compose.material.icons.filled.MusicNote
import androidx.compose.material.icons.filled.SportsEsports
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.unit.dp
import top.ponychat.webview.ui.character.CompactModeNavItem

@Composable
internal fun PonyHomeBottomBar(
    selectedTab: String,
    openChatList: () -> Unit,
    openGames: () -> Unit,
    openMusic: () -> Unit,
    miniPlayer: @Composable () -> Unit = {},
) {
    val color = MaterialTheme.colorScheme.surface
    SystemNavigationBarColorEffect(color = color, useDarkIcons = color.luminance() > 0.5f)
    Surface(color = color, shadowElevation = 4.dp, modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.navigationBarsPadding()) {
            miniPlayer()
            Row(
                Modifier.fillMaxWidth().height(58.dp).padding(horizontal = 14.dp, vertical = 2.dp).selectableGroup(),
                horizontalArrangement = Arrangement.SpaceEvenly,
            ) {
                CompactModeNavItem(selectedTab == "chat", Icons.Default.ChatBubbleOutline, "聊天", openChatList)
                CompactModeNavItem(selectedTab == "games", Icons.Default.SportsEsports, "游戏", openGames)
                CompactModeNavItem(selectedTab == "music", Icons.Default.MusicNote, "音乐", openMusic)
            }
        }
    }
}
