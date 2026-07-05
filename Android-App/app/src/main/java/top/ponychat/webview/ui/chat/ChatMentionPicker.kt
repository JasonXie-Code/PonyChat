package top.ponychat.webview.ui.chat

import android.util.Log
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.graphics.BitmapFactory
import android.net.Uri
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.EnterTransition
import androidx.compose.animation.core.CubicBezierEasing
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeOut
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.scrollBy
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.History
import androidx.compose.material.icons.filled.HourglassEmpty
import androidx.compose.material.icons.filled.Image
import androidx.compose.material.icons.filled.RestartAlt
import androidx.compose.material.icons.filled.SaveAlt
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Share
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.MutableFloatState
import androidx.compose.runtime.MutableIntState
import androidx.compose.runtime.MutableState
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.State
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshots.SnapshotStateList
import androidx.compose.runtime.withFrameNanos
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.PointerEventPass
import androidx.compose.ui.input.pointer.changedToDown
import androidx.compose.ui.input.pointer.changedToDownIgnoreConsumed
import androidx.compose.ui.input.pointer.changedToUpIgnoreConsumed
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.layout
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.positionInWindow
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.platform.LocalViewConfiguration
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.zIndex
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import coil.imageLoader
import coil.request.ImageRequest
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import androidx.activity.compose.BackHandler
import top.ponychat.webview.BackendStreamingVoiceBridge
import top.ponychat.webview.data.model.Character
import top.ponychat.webview.data.model.Message
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.ui.character.CharacterAvatar
import top.ponychat.webview.ui.chinesechess.ChineseChessActivity
import top.ponychat.webview.ui.common.PonyDialogOption
import top.ponychat.webview.ui.common.PonyOptionDialog
import top.ponychat.webview.ui.common.PonyTopBar
import top.ponychat.webview.ui.doudizhu.DoudizhuActivity
import top.ponychat.webview.ui.tictactoe.TicTacToeActivity
import top.ponychat.webview.ui.theme.ErrorColor
import top.ponychat.webview.ui.theme.LocalFontScale
import top.ponychat.webview.ui.theme.Primary
import top.ponychat.webview.util.formatErrorForDisplay
import kotlin.math.max
import kotlin.math.roundToInt
import kotlin.math.abs
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.ui.unit.Density
import java.io.File

internal inline fun List<Message>.noneAfter(messageId: String, predicate: (Message) -> Boolean): Boolean {
    val index = indexOfFirst {
        it.id == messageId || it.messageId == messageId || it.stableChatItemKey() == messageId
    }
    if (index < 0) return true
    return subList(index + 1, size).none(predicate)
}

internal fun recentMentionCandidates(
    mainCharacter: Character,
    allCharacters: List<Character>,
    messages: List<Message>
): List<Character> {
    val mainId = mainCharacter.id.orEmpty()
    val mainCandidate = mainCharacter.takeIf { !it.id.isNullOrBlank() && it.displayName().isNotBlank() }
    val userIndexes = messages.mapIndexedNotNull { index, message ->
        if (message.isUser()) index else null
    }
    val startIndex = userIndexes.takeLast(8).firstOrNull()
        ?: (messages.size - 16).coerceAtLeast(0)
    val recentMessages = messages.drop(startIndex)
    val recentCandidates = if (recentMessages.isEmpty()) {
        emptyList()
    } else {
        allCharacters
            .asSequence()
            .filter { !it.id.isNullOrBlank() && it.id != mainId && !it.name.isNullOrBlank() }
            .mapNotNull { candidate ->
                val candidateId = candidate.id.orEmpty()
                val needle = candidate.displayName().lowercase()
                val lastSeenIndex = recentMessages.indexOfLast { message ->
                    message.speakerCharacterId == candidateId ||
                        buildString {
                            append(message.content)
                            append('\n')
                            append(message.displayContent.orEmpty())
                            append('\n')
                            append(message.speakerName.orEmpty())
                            append('\n')
                            append(message.quotedMessage?.sender.orEmpty())
                        }.lowercase().contains(needle)
                }
                if (lastSeenIndex >= 0) candidate to lastSeenIndex else null
            }
            .sortedByDescending { it.second }
            .map { it.first }
            .distinctBy { it.id }
            .toList()
    }
    return buildList {
        mainCandidate?.let { add(it) }
        recentCandidates.forEach { candidate ->
            if (candidate.id != mainId) add(candidate)
        }
    }
}

internal fun replaceLastMentionTrigger(text: String, characterName: String): String {
    val idx = text.lastIndexOf('@')
    if (idx < 0) {
        return "$text @$characterName "
    }
    val prefix = text.substring(0, idx)
    val suffix = text.substring(idx + 1)
    return buildString {
        append(prefix)
        append('@')
        append(characterName)
        if (suffix.isBlank()) {
            append(' ')
        } else {
            if (!suffix.first().isWhitespace()) append(' ')
            append(suffix)
        }
    }
}

private fun appendMentionToken(text: String, characterName: String): String {
    val name = characterName.trim()
    if (name.isBlank()) return text
    val base = text.trimEnd()
    return buildString {
        append(base)
        if (base.isNotEmpty() && !base.last().isWhitespace()) append(' ')
        append('@')
        append(name)
        append(' ')
    }
}

internal fun appendMentionTokenIfMissing(text: String, character: Character): String {
    return if (findMentionTargetMatches(text, listOf(character)).isNotEmpty()) {
        text
    } else {
        appendMentionToken(text, character.displayName())
    }
}

private fun Char.isMentionTerminator(): Boolean =
    isWhitespace() || this in setOf(
        ',', '.', '?', '!', ';', ':',
        '，', '。', '？', '！', '；', '：', '、',
        ')', ']', '}', '）', '】', '》', '」', '』',
        '"', '\'', '”', '’', '…'
    )

private fun findLastMentionTarget(
    text: String,
    candidates: List<Character>
): Character? {
    return findMentionTargetMatches(text, candidates).lastOrNull()
}

internal fun findMentionTargetMatches(
    text: String,
    candidates: List<Character>
): List<Character> {
    if (text.isBlank() || candidates.isEmpty()) return emptyList()
    val haystack = text.lowercase()
    return candidates
        .asSequence()
        .flatMap { candidate ->
            val name = candidate.displayName().trim()
            if (name.isBlank()) return@flatMap emptySequence()
            val needle = name.lowercase()
            val matches = mutableListOf<MentionMatch>()
            listOf("@", "＠").forEach { marker ->
                val token = marker + needle
                var from = 0
                while (from <= haystack.length) {
                    val index = haystack.indexOf(token, from)
                    if (index < 0) break
                    val end = index + token.length
                    if (end >= haystack.length || haystack[end].isMentionTerminator()) {
                        matches.add(MentionMatch(candidate, index, name.length))
                    }
                    from = index + 1
                }
            }
            matches.asSequence()
        }
        .sortedWith(
            compareBy<MentionMatch> { it.index }
                .thenByDescending { it.nameLength }
        )
        .map { it.character }
        .distinctBy { it.id }
        .toList()
}

private data class MentionMatch(
    val character: Character,
    val index: Int,
    val nameLength: Int
)

@Composable
internal fun MentionCharacterPickerOverlay(
    candidates: List<Character>,
    apiBase: String,
    bottomInset: Dp,
    onDismiss: () -> Unit,
    onSelect: (Character) -> Unit,
) {
    Surface(
        color = MaterialTheme.colorScheme.background.copy(alpha = 0.98f),
        modifier = Modifier.fillMaxSize()
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(start = 18.dp, top = 16.dp, end = 18.dp, bottom = 16.dp + bottomInset)
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = "邀请发言",
                        color = MaterialTheme.colorScheme.onBackground,
                        style = MaterialTheme.typography.titleLarge,
                        fontWeight = FontWeight.Bold
                    )
                    Text(
                        text = "仅可邀请已添加且当前对话已提到的角色",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.bodySmall
                    )
                }
                IconButton(onClick = onDismiss) {
                    Icon(
                        Icons.Filled.Close,
                        contentDescription = "关闭",
                        tint = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }
            Spacer(Modifier.size(12.dp))
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .weight(1f),
                contentAlignment = Alignment.Center
            ) {
                if (candidates.isEmpty()) {
                    Text(
                        text = "没有可邀请的角色",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.bodyMedium
                    )
                } else {
                    LazyColumn(
                        modifier = Modifier.fillMaxSize(),
                        verticalArrangement = Arrangement.spacedBy(10.dp),
                        contentPadding = PaddingValues(vertical = 4.dp)
                    ) {
                        items(candidates, key = { it.stableId() }) { candidate ->
                            Surface(
                                onClick = { onSelect(candidate) },
                                color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.72f),
                                shape = RoundedCornerShape(14.dp),
                                border = androidx.compose.foundation.BorderStroke(
                                    1.dp,
                                    MaterialTheme.colorScheme.outline.copy(alpha = 0.16f)
                                ),
                                modifier = Modifier.fillMaxWidth()
                            ) {
                                Row(
                                    modifier = Modifier.padding(horizontal = 12.dp, vertical = 10.dp),
                                    verticalAlignment = Alignment.CenterVertically
                                ) {
                                    CharacterAvatar(
                                        avatarUrl = candidate.avatarUrl(),
                                        name = candidate.displayName(),
                                        apiBase = apiBase,
                                        size = 42
                                    )
                                    Spacer(Modifier.width(12.dp))
                                    Column(modifier = Modifier.weight(1f)) {
                                        Text(
                                            text = candidate.displayName(),
                                            color = MaterialTheme.colorScheme.onBackground,
                                            style = MaterialTheme.typography.titleSmall,
                                            fontWeight = FontWeight.SemiBold,
                                            maxLines = 1,
                                            overflow = TextOverflow.Ellipsis
                                        )
                                        Text(
                                            text = candidate.displayDescription(),
                                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                                            style = MaterialTheme.typography.bodySmall,
                                            maxLines = 1,
                                            overflow = TextOverflow.Ellipsis
                                        )
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

