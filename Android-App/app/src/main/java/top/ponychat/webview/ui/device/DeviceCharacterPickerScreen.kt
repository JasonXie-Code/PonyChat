package top.ponychat.webview.ui.device

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.ArrowBack
import androidx.compose.material.icons.rounded.Check
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import top.ponychat.webview.data.model.Character
import top.ponychat.webview.ui.common.PonyAvatar

@Composable
fun DeviceCharacterPickerScreen(
    characters: List<Character>,
    activeCharacterId: String,
    avatarApiBase: String,
    isLoading: Boolean,
    onBack: () -> Unit,
    onCharacterSelected: (Character) -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(DeviceBackground)
            .statusBarsPadding()
            .navigationBarsPadding()
            .padding(horizontal = 28.dp, vertical = 20.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = onBack) {
                Icon(
                    Icons.AutoMirrored.Rounded.ArrowBack,
                    contentDescription = "返回大屏",
                    tint = Color.White,
                )
            }
            Spacer(Modifier.width(8.dp))
            Column {
                Text("切换角色", color = Color.White, fontSize = 26.sp, fontWeight = FontWeight.Bold)
                Text("选择后，角色的个性与记忆会一起切换", color = Color.White.copy(alpha = 0.58f), fontSize = 12.sp)
            }
        }

        if (isLoading && characters.isEmpty()) {
            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                CircularProgressIndicator(color = Color(0xFF8878EF))
            }
        } else {
            LazyColumn(
                modifier = Modifier.padding(top = 22.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                items(characters, key = { it.stableId() }) { character ->
                    val selected = character.id == activeCharacterId
                    Surface(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clickable { onCharacterSelected(character) },
                        shape = RoundedCornerShape(20.dp),
                        color = if (selected) Color(0xFF8878EF).copy(alpha = 0.22f)
                            else Color.White.copy(alpha = 0.08f),
                        border = BorderStroke(
                            1.dp,
                            if (selected) Color(0xFF9D91FF) else Color.White.copy(alpha = 0.10f),
                        ),
                    ) {
                        Row(
                            modifier = Modifier.padding(horizontal = 16.dp, vertical = 14.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            PonyAvatar(
                                avatarUrl = character.avatarUrl(),
                                name = character.displayName(),
                                apiBase = avatarApiBase,
                                size = 58,
                            )
                            Spacer(Modifier.width(14.dp))
                            Column(modifier = Modifier.weight(1f)) {
                                Text(
                                    character.displayName(),
                                    color = Color.White,
                                    fontSize = 18.sp,
                                    fontWeight = FontWeight.SemiBold,
                                    maxLines = 1,
                                    overflow = TextOverflow.Ellipsis,
                                )
                                Text(
                                    character.displayDescription(),
                                    color = Color.White.copy(alpha = 0.58f),
                                    fontSize = 13.sp,
                                    maxLines = 2,
                                    overflow = TextOverflow.Ellipsis,
                                    modifier = Modifier.padding(top = 4.dp),
                                )
                            }
                            if (selected) {
                                Box(
                                    modifier = Modifier
                                        .size(30.dp)
                                        .clip(CircleShape)
                                        .background(Color(0xFF8878EF)),
                                    contentAlignment = Alignment.Center,
                                ) {
                                    Icon(Icons.Rounded.Check, contentDescription = "当前角色", tint = Color.White)
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
