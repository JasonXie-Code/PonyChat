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
internal fun ChatScreenContent(
    viewModel: ChatViewModel,
    character: Character,
    allCharacters: List<Character> = emptyList(),
    prefs: AppPreferences,
    onNavigateBack: () -> Unit,
    onNavigateToEditCharacter: () -> Unit = {},
    onNavigateToCharacterProfile: (Character) -> Unit = {},
    onNavigateToSettings: () -> Unit = {},
    onNavigateToProactiveTasks: () -> Unit = {},
    onNavigateToHistory: () -> Unit = {},
    onThemeChanged: (Boolean) -> Unit = {}
) {
    ChatScreenContentBody(
        viewModel = viewModel,
        character = character,
        allCharacters = allCharacters,
        prefs = prefs,
        onNavigateBack = onNavigateBack,
        onNavigateToEditCharacter = onNavigateToEditCharacter,
        onNavigateToCharacterProfile = onNavigateToCharacterProfile,
        onNavigateToSettings = onNavigateToSettings,
        onNavigateToProactiveTasks = onNavigateToProactiveTasks,
        onNavigateToHistory = onNavigateToHistory,
        onThemeChanged = onThemeChanged
    )
}
