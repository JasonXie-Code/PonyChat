package top.ponychat.webview.ui.chat

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.runtime.Composable
import kotlinx.coroutines.FlowPreview
import top.ponychat.webview.data.model.Character
import top.ponychat.webview.data.prefs.AppPreferences

@OptIn(
    ExperimentalMaterial3Api::class,
    ExperimentalFoundationApi::class,
    ExperimentalLayoutApi::class,
    FlowPreview::class
)
@Composable
fun ChatScreen(
    viewModel: ChatViewModel,
    character: Character,
    allCharacters: List<Character> = emptyList(),
    prefs: AppPreferences,
    onNavigateBack: () -> Unit,
    onNavigateToEditCharacter: () -> Unit = {},
    onNavigateToCharacterProfile: (Character) -> Unit = {},
    characterHome: @Composable (() -> Unit) -> Unit,
    onNavigateToSettings: () -> Unit = {},
    onNavigateToProactiveTasks: () -> Unit = {},
    onNavigateToHistory: () -> Unit = {},
    onThemeChanged: (Boolean) -> Unit = {}
) {
    val navigate = rememberChatNavigation()
    ChatScreenContent(
        viewModel = viewModel,
        character = character,
        allCharacters = allCharacters,
        prefs = prefs,
        onNavigateBack = { navigate(onNavigateBack) },
        onNavigateToEditCharacter = { navigate(onNavigateToEditCharacter) },
        onNavigateToCharacterProfile = { target -> navigate { onNavigateToCharacterProfile(target) } },
        characterHome = characterHome,
        onNavigateToSettings = { navigate(onNavigateToSettings) },
        onNavigateToProactiveTasks = { navigate(onNavigateToProactiveTasks) },
        onNavigateToHistory = { navigate(onNavigateToHistory) },
        onThemeChanged = onThemeChanged
    )
}
