package top.ponychat.webview.ui.character

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.derivedStateOf
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import top.ponychat.webview.data.model.Character
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.ui.common.LoadingOverlay
import top.ponychat.webview.ui.common.PonyConfirmDialog
import top.ponychat.webview.ui.common.PonyDialogActionStyle
import top.ponychat.webview.ui.common.PonyTopBar
import top.ponychat.webview.ui.common.SystemNavigationBarColorEffect
import top.ponychat.webview.ui.theme.*
import top.ponychat.webview.util.formatErrorForDisplay

@Composable
fun MyPublishedHallScreen(
    viewModel: CharacterViewModel,
    prefs: AppPreferences,
    onNavigateBack: () -> Unit
) {
    val state by viewModel.state.collectAsState()
    val activeApiBase = prefs.effectiveApiBase()
    val fallbackApiBase = pickFallbackApiBase(activeApiBase, prefs.wanUrl, prefs.lanUrl)
    val currentUsername = prefs.username.trim()
    var detailCharacter by remember { mutableStateOf<Character?>(null) }
    var hallCharacterToUnpublish by remember { mutableStateOf<Character?>(null) }
    var showNotice by remember { mutableStateOf(!prefs.myPublishedHallNoticeDismissed) }

    val listBackgroundColor = MaterialTheme.colorScheme.background
    SystemNavigationBarColorEffect(
        color = listBackgroundColor,
        useDarkIcons = listBackgroundColor.luminance() > 0.5f
    )

    LaunchedEffect(Unit) {
        viewModel.loadMyCharacters(silent = true)
        viewModel.loadCharacterHall()
    }

    val hallIdToLocal by remember(state.characters) {
        derivedStateOf {
            state.characters
                .filter { it.hallId?.isNotBlank() == true }
                .associateBy { it.hallId!! }
        }
    }

    val myPublishedChars by remember(state.hallCharacters, currentUsername) {
        derivedStateOf {
            if (currentUsername.isBlank()) {
                emptyList()
            } else {
                state.hallCharacters
                    .filter { it.ownerRaw?.equals(currentUsername, ignoreCase = true) == true }
                    .sortedByDescending { it.publishedAt ?: "" }
            }
        }
    }
    val isInitialPublishedLoading = !state.hasLoadedHallCharacters && state.hallCharacters.isEmpty()

    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        topBar = {
            PonyTopBar(
                title = "我发布的",
                onNavigateBack = onNavigateBack
            ) {
                top.ponychat.webview.ui.common.PonyIconButton(
                    onClick = { viewModel.loadCharacterHall() },
                    icon = Icons.Filled.Refresh,
                    contentDescription = "刷新",
                    tint = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.7f),
                    size = 32.dp,
                    iconSize = 18.dp
                )
            }
        }
    ) { paddingValues ->
        Box(modifier = Modifier.fillMaxSize().padding(paddingValues)) {
            LazyColumn(modifier = Modifier.fillMaxSize()) {
                if (showNotice) {
                    item {
                        Surface(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(horizontal = 16.dp, vertical = 12.dp),
                            shape = RoundedCornerShape(12.dp),
                            color = Primary.copy(alpha = 0.10f)
                        ) {
                            Row(
                                modifier = Modifier.padding(start = 12.dp, top = 10.dp, end = 8.dp, bottom = 10.dp),
                                verticalAlignment = Alignment.Top
                            ) {
                                Icon(
                                    Icons.Filled.Info,
                                    contentDescription = null,
                                    tint = Primary.copy(alpha = 0.85f),
                                    modifier = Modifier.size(18.dp)
                                )
                                Spacer(Modifier.width(8.dp))
                                Text(
                                    text = "这里管理你发布到角色大厅的副本：可同步本地最新版本，或从大厅下架。",
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.78f),
                                    modifier = Modifier.weight(1f)
                                )
                                Spacer(Modifier.width(4.dp))
                                IconButton(
                                    onClick = {
                                        prefs.myPublishedHallNoticeDismissed = true
                                        showNotice = false
                                    },
                                    modifier = Modifier.size(24.dp)
                                ) {
                                    Icon(
                                        Icons.Filled.Close,
                                        contentDescription = "关闭通知",
                                        tint = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.65f),
                                        modifier = Modifier.size(16.dp)
                                    )
                                }
                            }
                        }
                    }
                }

                state.error?.let { err ->
                    item {
                        Card(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(horizontal = 16.dp, vertical = 8.dp),
                            colors = CardDefaults.cardColors(containerColor = ErrorColor.copy(0.12f)),
                            shape = RoundedCornerShape(8.dp)
                        ) {
                            Row(
                                modifier = Modifier.padding(12.dp),
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                Icon(Icons.Filled.Warning, contentDescription = null, tint = ErrorColor)
                                Spacer(Modifier.width(8.dp))
                                Text(
                                    formatErrorForDisplay(err),
                                    color = ErrorColor,
                                    style = MaterialTheme.typography.bodySmall,
                                    modifier = Modifier.weight(1f)
                                )
                                TextButton(onClick = { viewModel.clearError() }) {
                                    Text("关闭", color = ErrorColor)
                                }
                            }
                        }
                    }
                }

                state.actionMessage?.let { msg ->
                    item {
                        Surface(
                            color = Primary.copy(0.12f),
                            modifier = Modifier.fillMaxWidth()
                        ) {
                            Text(
                                msg,
                                color = Primary,
                                style = MaterialTheme.typography.bodySmall,
                                modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp)
                            )
                        }
                    }
                }

                item {
                    Text(
                        text = "共 ${myPublishedChars.size} 个角色",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.6f),
                        modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp)
                    )
                }

                if (myPublishedChars.isEmpty() && state.hasLoadedHallCharacters && !state.isLoading) {
                    item {
                        Box(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(top = 60.dp),
                            contentAlignment = Alignment.Center
                        ) {
                            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                                Icon(
                                    Icons.Filled.CloudOff,
                                    contentDescription = null,
                                    modifier = Modifier.size(64.dp),
                                    tint = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.4f)
                                )
                                Spacer(Modifier.height(12.dp))
                                Text(
                                    "你还没有发布任何角色到大厅",
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    style = MaterialTheme.typography.bodyMedium
                                )
                            }
                        }
                    }
                }

                items(items = myPublishedChars, key = { it.stableId() }) { character ->
                    val localSource = character.id?.let { hallIdToLocal[it] }
                    val needsHallSync = localSource != null &&
                        character.contentHash?.isNotBlank() == true &&
                        localSource.contentHash?.isNotBlank() == true &&
                        localSource.contentHash != character.contentHash
                    MyPublishedHallCard(
                        character = character,
                        apiBase = activeApiBase,
                        fallbackApiBase = fallbackApiBase,
                        needsHallSync = needsHallSync,
                        onClick = { detailCharacter = character },
                        onSyncToHall = { viewModel.syncHallFromLocal(character) },
                        onUnpublish = { hallCharacterToUnpublish = character }
                    )
                }

                item { Spacer(Modifier.height(16.dp)) }
            }

            LoadingOverlay(visible = state.isLoading || isInitialPublishedLoading, message = "加载中…")
        }

        detailCharacter?.let { selected ->
            val localSourceD = selected.id?.let { hallIdToLocal[it] }
            val needsHallSyncD = localSourceD != null &&
                selected.contentHash?.isNotBlank() == true &&
                localSourceD.contentHash?.isNotBlank() == true &&
                localSourceD.contentHash != selected.contentHash
            AlertDialog(
                onDismissRequest = { detailCharacter = null },
                title = {
                    Text(
                        text = selected.displayName(),
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.SemiBold
                    )
                },
                text = {
                    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            Surface(
                                modifier = Modifier.weight(1f),
                                shape = RoundedCornerShape(8.dp),
                                color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.45f)
                            ) {
                                Row(
                                    modifier = Modifier.padding(horizontal = 8.dp, vertical = 6.dp),
                                    verticalAlignment = Alignment.CenterVertically
                                ) {
                                    Icon(Icons.Filled.Download, contentDescription = null, tint = Primary, modifier = Modifier.size(14.dp))
                                    Spacer(Modifier.width(6.dp))
                                    Text(
                                        text = "已添加 ${selected.timesAdded ?: 0} 次",
                                        style = MaterialTheme.typography.labelSmall,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant
                                    )
                                }
                            }
                            Surface(
                                modifier = Modifier.weight(1f),
                                shape = RoundedCornerShape(8.dp),
                                color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.45f)
                            ) {
                                Row(
                                    modifier = Modifier.padding(horizontal = 8.dp, vertical = 6.dp),
                                    verticalAlignment = Alignment.CenterVertically
                                ) {
                                    Icon(Icons.Filled.Schedule, contentDescription = null, tint = Primary, modifier = Modifier.size(14.dp))
                                    Spacer(Modifier.width(6.dp))
                                    Text(
                                        text = "发布于 ${formatPublishTime(selected.publishedAt)}",
                                        style = MaterialTheme.typography.labelSmall,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant
                                    )
                                }
                            }
                        }
                        Surface(
                            shape = RoundedCornerShape(8.dp),
                            color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f)
                        ) {
                            Column(modifier = Modifier.padding(8.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                                Text("角色简介", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                Text(
                                    text = selected.displayDescription(),
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurface
                                )
                            }
                        }
                    }
                },
                confirmButton = {
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        if (needsHallSyncD) {
                            FilledTonalButton(
                                onClick = {
                                    viewModel.syncHallFromLocal(selected)
                                    detailCharacter = null
                                },
                                colors = ButtonDefaults.filledTonalButtonColors(
                                    containerColor = Color(0xFFFF9800).copy(alpha = 0.15f),
                                    contentColor = Color(0xFFFF9800)
                                )
                            ) {
                                Text("同步到大厅")
                            }
                        }
                        OutlinedButton(
                            onClick = {
                                detailCharacter = null
                                hallCharacterToUnpublish = selected
                            }
                        ) {
                            Text("下架", color = ErrorColor)
                        }
                    }
                },
                dismissButton = {
                    TextButton(onClick = { detailCharacter = null }) {
                        Text("关闭")
                    }
                }
            )
        }

        hallCharacterToUnpublish?.let { target ->
            PonyConfirmDialog(
                title = "从大厅下架",
                message = "下架后其他用户将无法在角色大厅找到「${target.displayName()}」。你的本地角色不会被删除。",
                confirmText = "确认下架",
                actionStyle = PonyDialogActionStyle.Danger,
                onDismiss = { hallCharacterToUnpublish = null },
                onConfirm = {
                    viewModel.unpublishFromHall(target)
                    hallCharacterToUnpublish = null
                    if (detailCharacter?.id == target.id) {
                        detailCharacter = null
                    }
                }
            )
        }
    }
}

@Composable
private fun MyPublishedHallCard(
    character: Character,
    apiBase: String,
    fallbackApiBase: String,
    needsHallSync: Boolean,
    onClick: () -> Unit,
    onSyncToHall: () -> Unit,
    onUnpublish: () -> Unit
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.22f))
            .clickable(onClick = onClick)
            .padding(horizontal = 12.dp, vertical = 12.dp),
        verticalAlignment = Alignment.Top
    ) {
        CharacterAvatar(
            avatarUrl = character.avatarUrl(),
            name = character.displayName(),
            apiBase = apiBase,
            fallbackApiBase = fallbackApiBase,
            size = 50
        )
        Spacer(Modifier.width(12.dp))
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = character.displayName(),
                fontWeight = FontWeight.Medium,
                style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.onBackground,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis
            )
            Spacer(Modifier.height(4.dp))
            Text(
                text = character.displayDescription(),
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.7f),
                maxLines = 2,
                overflow = TextOverflow.Ellipsis
            )
            Spacer(Modifier.height(6.dp))
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                Icon(Icons.Filled.Download, contentDescription = null, tint = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.6f), modifier = Modifier.size(13.dp))
                Text("${character.timesAdded ?: 0}", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.65f))
                Icon(Icons.Filled.Schedule, contentDescription = null, tint = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.6f), modifier = Modifier.size(13.dp))
                Text(formatPublishTime(character.publishedAt), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.65f))
            }
        }
        Spacer(Modifier.width(8.dp))
        Column(
            horizontalAlignment = Alignment.End,
            verticalArrangement = Arrangement.spacedBy(6.dp)
        ) {
            if (needsHallSync) {
                FilledTonalButton(
                    onClick = onSyncToHall,
                    modifier = Modifier.height(32.dp),
                    contentPadding = PaddingValues(horizontal = 10.dp),
                    colors = ButtonDefaults.filledTonalButtonColors(
                        containerColor = Color(0xFFFF9800).copy(alpha = 0.15f),
                        contentColor = Color(0xFFFF9800)
                    )
                ) {
                    Icon(Icons.Filled.Upload, contentDescription = null, modifier = Modifier.size(14.dp))
                    Spacer(Modifier.width(4.dp))
                    Text("同步", style = MaterialTheme.typography.bodySmall)
                }
            } else {
                Surface(
                    modifier = Modifier.height(32.dp),
                    shape = RoundedCornerShape(50),
                    color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.6f)
                ) {
                    Row(
                        modifier = Modifier.padding(horizontal = 10.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Icon(Icons.Filled.Check, contentDescription = null, tint = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.6f), modifier = Modifier.size(14.dp))
                        Spacer(Modifier.width(4.dp))
                        Text("已同步", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.6f))
                    }
                }
            }
            OutlinedButton(
                onClick = onUnpublish,
                modifier = Modifier.height(30.dp),
                contentPadding = PaddingValues(horizontal = 10.dp),
                border = androidx.compose.foundation.BorderStroke(1.dp, ErrorColor.copy(alpha = 0.35f))
            ) {
                Text("下架", style = MaterialTheme.typography.bodySmall, color = ErrorColor)
            }
        }
    }
}
