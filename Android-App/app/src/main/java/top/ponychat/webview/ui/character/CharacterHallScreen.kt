package top.ponychat.webview.ui.character

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.derivedStateOf
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import top.ponychat.webview.data.model.Character
import top.ponychat.webview.data.prefs.AppPreferences
import androidx.compose.ui.graphics.luminance
import top.ponychat.webview.ui.common.adaptivePopupMenuAccentColor
import top.ponychat.webview.ui.common.adaptivePopupMenuBorder
import top.ponychat.webview.ui.common.adaptivePopupMenuContainerColor
import top.ponychat.webview.ui.common.adaptivePopupMenuContentColor
import top.ponychat.webview.ui.common.LoadingOverlay
import top.ponychat.webview.ui.common.PonyTopBar
import top.ponychat.webview.ui.common.PonyTopSearchBar
import top.ponychat.webview.ui.common.SystemNavigationBarColorEffect
import top.ponychat.webview.ui.theme.*
import top.ponychat.webview.util.formatErrorForDisplay

enum class SortOption(val label: String) {
    NEWEST("最新"),
    POPULAR("热门"),
    NAME("名称")
}

@Composable
private fun hallMenuContainerColor(): Color =
    adaptivePopupMenuContainerColor()

@Composable
private fun hallMenuContentColor(): Color =
    adaptivePopupMenuContentColor()

@Composable
private fun hallMenuAccentColor(): Color =
    adaptivePopupMenuAccentColor()

@Composable
private fun hallMenuBorder(): BorderStroke? =
    adaptivePopupMenuBorder()

@OptIn(ExperimentalMaterial3Api::class, ExperimentalFoundationApi::class)
@Composable
fun CharacterHallScreen(
    viewModel: CharacterViewModel,
    prefs: AppPreferences,
    onNavigateBack: () -> Unit,
    onNavigateToMyPublished: () -> Unit,
    onCharacterSelected: (Character, String) -> Unit
) {
    val state by viewModel.state.collectAsState()
    val activeApiBase = prefs.effectiveApiBase()
    val fallbackApiBase = pickFallbackApiBase(activeApiBase, prefs.wanUrl, prefs.lanUrl)
    var searchQuery by remember { mutableStateOf("") }
    var selectedSort by remember { mutableStateOf(SortOption.NEWEST) }
    var showSortMenu by remember { mutableStateOf(false) }
    var selectedIds by remember { mutableStateOf(setOf<String>()) }
    var isBatchMode by remember { mutableStateOf(false) }
    var detailCharacter by remember { mutableStateOf<Character?>(null) }
    val maxSelection = 10

    val bottomBarColor = MaterialTheme.colorScheme.surface
    val navigationBarColor = if (isBatchMode) bottomBarColor else MaterialTheme.colorScheme.background
    SystemNavigationBarColorEffect(
        color = navigationBarColor,
        useDarkIcons = navigationBarColor.luminance() > 0.5f
    )

    LaunchedEffect(Unit) {
        viewModel.loadMyCharacters(silent = true)
        viewModel.loadCharacterHall()
    }

    val selectedCharacters by remember(selectedIds, state.hallCharacters) {
        derivedStateOf {
            state.hallCharacters.filter { selectedIds.contains(it.id) }
        }
    }

    // 用本地角色的 contentHash 集合做「已添加」判断：
    // 只要用户拥有与大厅角色内容哈希完全一致的副本，就视为已添加（与是否编辑过直接挂钩）
    val ownedContentHashes by remember(state.characters) {
        derivedStateOf {
            val contentHashes = state.characters
                .mapNotNull { it.contentHash?.takeIf { h -> h.isNotBlank() } }
                .toSet()
            val sourceHashes = state.characters
                .mapNotNull { it.sourceContentHash?.takeIf { h -> h.isNotBlank() } }
                .toSet()
            contentHashes + sourceHashes
        }
    }
    // 通过 sourceId（添加时服务端注入的大厅 id）做精确匹配——兜底方案
    val ownedSourceIds by remember(state.characters) {
        derivedStateOf {
            state.characters.mapNotNull { it.sourceId?.takeIf { id -> id.isNotBlank() } }.toSet()
        }
    }
    val filteredAndSortedChars by remember(
        state.hallCharacters,
        searchQuery,
        selectedSort
    ) {
        derivedStateOf {
            var list = state.hallCharacters

            if (searchQuery.isNotBlank()) {
                list = list.filter {
                    it.displayName().contains(searchQuery, ignoreCase = true) ||
                        it.displayDescription().contains(searchQuery, ignoreCase = true) ||
                        it.hallOwnerName().contains(searchQuery, ignoreCase = true)
                }
            }

            when (selectedSort) {
                SortOption.NEWEST -> list.sortedByDescending { it.publishedAt ?: "" }
                SortOption.POPULAR -> list.sortedByDescending { it.timesAdded ?: 0 }
                SortOption.NAME -> list.sortedBy { it.displayName() }
            }
        }
    }
    val isInitialHallLoading = !state.hasLoadedHallCharacters && state.hallCharacters.isEmpty()

    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        bottomBar = {
            AnimatedVisibility(
                visible = isBatchMode,
                enter = slideInVertically(initialOffsetY = { it }) + fadeIn(),
                exit = slideOutVertically(targetOffsetY = { it }) + fadeOut()
            ) {
                Surface(
                    modifier = Modifier.fillMaxWidth(),
                    color = bottomBarColor,
                    tonalElevation = 2.dp,
                    shadowElevation = 4.dp
                ) {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .navigationBarsPadding()
                            .padding(horizontal = 10.dp, vertical = 3.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Text(
                            text = "取消",
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            style = MaterialTheme.typography.labelMedium,
                            modifier = Modifier
                                .clip(RoundedCornerShape(4.dp))
                                .clickable {
                                    isBatchMode = false
                                    selectedIds = emptySet()
                                }
                                .padding(horizontal = 8.dp, vertical = 6.dp)
                        )
                        Spacer(Modifier.weight(1f))
                        Text(
                            text = "已选 ${selectedIds.size}/$maxSelection",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                        Spacer(Modifier.width(10.dp))
                        FilledTonalButton(
                            onClick = {
                                viewModel.addCharactersFromHall(selectedCharacters)
                                isBatchMode = false
                                selectedIds = emptySet()
                            },
                            enabled = selectedIds.isNotEmpty() && !state.isLoading,
                            modifier = Modifier.height(32.dp),
                            contentPadding = PaddingValues(horizontal = 12.dp),
                            colors = ButtonDefaults.filledTonalButtonColors(
                                containerColor = Primary.copy(alpha = 0.12f),
                                contentColor = Primary
                            )
                        ) {
                            Icon(
                                Icons.Filled.Add,
                                contentDescription = null,
                                modifier = Modifier.size(16.dp)
                            )
                            Spacer(Modifier.width(4.dp))
                            Text("添加", style = MaterialTheme.typography.bodySmall)
                        }
                    }
                }
            }
        },
        topBar = {
            PonyTopBar(
                title = "角色大厅",
                onNavigateBack = onNavigateBack
            ) {
                top.ponychat.webview.ui.common.PonyIconButton(
                    onClick = onNavigateToMyPublished,
                    icon = Icons.Filled.ManageAccounts,
                    contentDescription = "我发布的",
                    tint = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.85f),
                    size = 36.dp,
                    iconSize = 20.dp
                )
            }
        }
    ) { paddingValues ->
        Box(modifier = Modifier.fillMaxSize().padding(paddingValues)) {
        LazyColumn(modifier = Modifier.fillMaxSize()) {
            // 搜索栏
            item {
                PonyTopSearchBar(
                    value = searchQuery,
                    onValueChange = { searchQuery = it },
                    placeholder = "搜索角色名称、描述或作者...",
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 12.dp, vertical = 8.dp)
                )
            }

            state.error?.let { err ->
                item {
                    Card(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(16.dp),
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
                                style = MaterialTheme.typography.bodySmall
                            )
                            Spacer(Modifier.weight(1f))
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
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(start = 16.dp, end = 8.dp, top = 4.dp, bottom = 4.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text(
                        text = "共 ${filteredAndSortedChars.size} 个角色",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.6f)
                    )
                    Spacer(Modifier.weight(1f))
                    Box {
                        Row(
                            modifier = Modifier
                                .clip(RoundedCornerShape(6.dp))
                                .clickable { showSortMenu = true }
                                .padding(horizontal = 8.dp, vertical = 4.dp),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Text(
                                text = "按${selectedSort.label}排序",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.7f)
                            )
                            Spacer(Modifier.width(2.dp))
                            Icon(
                                Icons.Filled.ArrowDropDown,
                                contentDescription = null,
                                tint = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.7f),
                                modifier = Modifier.size(16.dp)
                            )
                        }
                        DropdownMenu(
                            expanded = showSortMenu,
                            onDismissRequest = { showSortMenu = false },
                            shape = RoundedCornerShape(12.dp),
                            containerColor = hallMenuContainerColor(),
                            border = hallMenuBorder(),
                            tonalElevation = 2.dp
                        ) {
                            SortOption.entries.forEach { option ->
                                DropdownMenuItem(
                                    text = {
                                        Row(verticalAlignment = Alignment.CenterVertically) {
                                            Text(
                                                option.label,
                                                color = if (selectedSort == option) hallMenuAccentColor() else hallMenuContentColor()
                                            )
                                            if (selectedSort == option) {
                                                Spacer(Modifier.width(8.dp))
                                                Icon(
                                                    Icons.Filled.Check,
                                                    contentDescription = null,
                                                    tint = hallMenuAccentColor(),
                                                    modifier = Modifier.size(16.dp)
                                                )
                                            }
                                        }
                                    },
                                    onClick = {
                                        selectedSort = option
                                        showSortMenu = false
                                    }
                                )
                            }
                        }
                    }
                    top.ponychat.webview.ui.common.PonyIconButton(
                        onClick = { viewModel.loadCharacterHall(searchQuery.ifBlank { null }) },
                        icon = Icons.Filled.Refresh,
                        contentDescription = "刷新",
                        tint = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.7f),
                        size = 32.dp,
                        iconSize = 18.dp
                    )
                    if (!isBatchMode) {
                        top.ponychat.webview.ui.common.PonyIconButton(
                            onClick = { isBatchMode = true },
                            icon = Icons.Filled.Checklist,
                            contentDescription = "批量添加",
                            tint = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.7f),
                            size = 32.dp,
                            iconSize = 18.dp
                        )
                    }
                }
            }

            if (filteredAndSortedChars.isEmpty() && state.hasLoadedHallCharacters && !state.isLoading) {
                item {
                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(top = 60.dp),
                        contentAlignment = Alignment.Center
                    ) {
                        Column(horizontalAlignment = Alignment.CenterHorizontally) {
                            Icon(
                                Icons.Filled.SearchOff,
                                contentDescription = null,
                                modifier = Modifier.size(64.dp),
                                tint = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.4f)
                            )
                            Spacer(Modifier.height(12.dp))
                            Text(
                                if (searchQuery.isNotBlank())
                                    "没有找到匹配的角色"
                                else
                                    "大厅暂无角色",
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                style = MaterialTheme.typography.bodyMedium
                            )
                            if (searchQuery.isNotBlank()) {
                                Spacer(Modifier.height(8.dp))
                                TextButton(onClick = {
                                    searchQuery = ""
                                }) {
                                    Text("清除筛选", color = Primary)
                                }
                            }
                        }
                    }
                }
            }

            items(
                items = filteredAndSortedChars,
                key = { it.stableId() }
            ) { character ->
                val charId = character.id ?: ""
                val isSelected = selectedIds.contains(charId)
                val isOwnedByHash = character.contentHash?.takeIf { it.isNotBlank() }
                    ?.let { ownedContentHashes.contains(it) } == true
                val isOwnedBySource = character.id?.let { ownedSourceIds.contains(it) } == true
                val isOwned = isOwnedByHash || isOwnedBySource
                HallCharacterCard(
                    character = character,
                    apiBase = activeApiBase,
                    fallbackApiBase = fallbackApiBase,
                    isBatchMode = isBatchMode,
                    isSelected = isSelected,
                    isOwned = isOwned,
                    onToggleSelect = {
                        if (!isOwned) {
                            if (isSelected) {
                                selectedIds = selectedIds - charId
                            } else if (selectedIds.size < maxSelection) {
                                selectedIds = selectedIds + charId
                            }
                        }
                    },
                    onClick = {
                        if (isBatchMode) {
                            if (!isOwned) {
                                if (isSelected) {
                                    selectedIds = selectedIds - charId
                                } else if (selectedIds.size < maxSelection) {
                                    selectedIds = selectedIds + charId
                                }
                            }
                        } else {
                            onCharacterSelected(character, prefs.chatMode.ifBlank { "normal" })
                        }
                    },
                    onAdd = { viewModel.addCharacterFromHall(character) }
                )
            }

            item {
                Spacer(Modifier.height(16.dp))
            }
        }
        LoadingOverlay(visible = state.isLoading || isInitialHallLoading, message = "加载中…")
        }

        detailCharacter?.let { selected ->
            val isOwnedByHashD = selected.contentHash?.takeIf { it.isNotBlank() }
                ?.let { ownedContentHashes.contains(it) } == true
            val isOwnedBySourceD = selected.id?.let { ownedSourceIds.contains(it) } == true
            val isOwned = isOwnedByHashD || isOwnedBySourceD
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
                        val ownerLabel = selected.hallOwnerDetailLabel()
                        if (ownerLabel.isNotBlank()) {
                            Text(
                                text = ownerLabel,
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                        Row(
                            horizontalArrangement = Arrangement.spacedBy(8.dp)
                        ) {
                            Surface(
                                modifier = Modifier.weight(1f),
                                shape = RoundedCornerShape(8.dp),
                                color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.45f)
                            ) {
                                Row(
                                    modifier = Modifier.padding(horizontal = 8.dp, vertical = 6.dp),
                                    verticalAlignment = Alignment.CenterVertically
                                ) {
                                    Icon(
                                        Icons.Filled.Download,
                                        contentDescription = null,
                                        tint = Primary,
                                        modifier = Modifier.size(14.dp)
                                    )
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
                                    Icon(
                                        Icons.Filled.Schedule,
                                        contentDescription = null,
                                        tint = Primary,
                                        modifier = Modifier.size(14.dp)
                                    )
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
                                Text(
                                    text = "角色简介",
                                    style = MaterialTheme.typography.labelSmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant
                                )
                                Text(
                                    text = selected.displayDescription(),
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurface
                                )
                            }
                        }
                        if (selected.effectivePrompt().isNotBlank()) {
                            Surface(
                                shape = RoundedCornerShape(8.dp),
                                color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f)
                            ) {
                                Column(modifier = Modifier.padding(8.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                                    Text(
                                        text = "核心设定预览",
                                        style = MaterialTheme.typography.labelSmall,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant
                                    )
                                    Text(
                                        text = selected.effectivePrompt(),
                                        style = MaterialTheme.typography.bodySmall,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                        maxLines = 6,
                                        overflow = TextOverflow.Ellipsis
                                    )
                                }
                            }
                        }
                    }
                },
                confirmButton = {
                    FilledTonalButton(
                        onClick = {
                            if (isOwned) {
                                val localCopy = state.characters.firstOrNull { it.sourceId == selected.id }
                                    ?: state.characters.firstOrNull {
                                        it.contentHash?.isNotBlank() == true &&
                                            it.contentHash == selected.contentHash
                                    } ?: selected
                                detailCharacter = null
                                onCharacterSelected(localCopy, prefs.chatMode.ifBlank { "normal" })
                            } else {
                                viewModel.addCharacterFromHall(selected)
                                detailCharacter = null
                            }
                        },
                        colors = ButtonDefaults.filledTonalButtonColors(
                            containerColor = Primary.copy(alpha = 0.15f),
                            contentColor = Primary
                        )
                    ) {
                        Text(if (isOwned) "开始聊天" else "添加到我的角色")
                    }
                },
                dismissButton = null
            )
        }
    }
}

@Composable
private fun HallCharacterCard(
    character: Character,
    apiBase: String,
    fallbackApiBase: String,
    isBatchMode: Boolean,
    isSelected: Boolean,
    isOwned: Boolean,
    onToggleSelect: () -> Unit,
    onClick: () -> Unit,
    onAdd: () -> Unit,
) {
    val contentAlpha = if (isOwned) 0.5f else 1f
    Column {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .background(
                    when {
                        isOwned -> MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.3f)
                        isSelected && isBatchMode -> Primary.copy(alpha = 0.08f)
                        else -> MaterialTheme.colorScheme.background
                    }
                )
                .clickable(onClick = onClick)
                .padding(horizontal = 12.dp, vertical = 12.dp),
            verticalAlignment = Alignment.Top
        ) {
            if (isBatchMode && !isOwned) {
                Box(
                    modifier = Modifier
                        .size(22.dp)
                        .clip(CircleShape)
                        .background(
                            if (isSelected) Primary
                            else MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.25f)
                        )
                        .clickable { onToggleSelect() },
                    contentAlignment = Alignment.Center
                ) {
                    if (isSelected) {
                        Icon(
                            Icons.Filled.Check,
                            contentDescription = null,
                            tint = MaterialTheme.colorScheme.onPrimary,
                            modifier = Modifier.size(14.dp)
                        )
                    }
                }
                Spacer(Modifier.width(10.dp))
            }
            CharacterAvatar(
                avatarUrl = character.avatarUrl(),
                name = character.displayName(),
                apiBase = apiBase,
                fallbackApiBase = fallbackApiBase,
                size = 50
            )
            Spacer(Modifier.width(12.dp))
            Column(modifier = Modifier.weight(1f)) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Text(
                        text = character.displayName(),
                        fontWeight = FontWeight.Medium,
                        style = MaterialTheme.typography.titleMedium,
                        color = MaterialTheme.colorScheme.onBackground.copy(alpha = contentAlpha),
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                        modifier = Modifier.weight(1f)
                    )
                }
                Spacer(Modifier.height(4.dp))
                Text(
                    text = character.displayDescription(),
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.7f * contentAlpha),
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis
                )
                val ownerLabel = character.hallOwnerInlineLabel()
                Spacer(Modifier.height(6.dp))
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    Icon(
                        Icons.Filled.Download,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.6f * contentAlpha),
                        modifier = Modifier.size(13.dp)
                    )
                    Text(
                        text = "${character.timesAdded ?: 0}",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.65f * contentAlpha)
                    )
                    Icon(
                        Icons.Filled.Schedule,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.6f * contentAlpha),
                        modifier = Modifier.size(13.dp)
                    )
                    Text(
                        text = formatPublishTime(character.publishedAt),
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.65f * contentAlpha)
                    )
                    if (ownerLabel.isNotBlank()) {
                        Text(
                            text = ownerLabel,
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.55f * contentAlpha),
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                            modifier = Modifier.weight(1f)
                        )
                    }
                }
                if (!character.tags.isNullOrEmpty()) {
                    Spacer(Modifier.height(6.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                        character.tags.take(3).forEach { tag ->
                            Surface(
                                shape = RoundedCornerShape(4.dp),
                                color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = contentAlpha)
                            ) {
                                Text(
                                    text = tag,
                                    style = MaterialTheme.typography.labelSmall.copy(fontSize = AppFontSizes.caption),
                                    color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.7f * contentAlpha),
                                    modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp)
                                )
                            }
                        }
                        if (character.tags.size > 3) {
                            Text(
                                text = "+${character.tags.size - 3}",
                                style = MaterialTheme.typography.labelSmall.copy(fontSize = AppFontSizes.caption),
                                color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.5f * contentAlpha),
                                modifier = Modifier.align(Alignment.CenterVertically)
                            )
                        }
                    }
                }
            }
            if (!isBatchMode) {
                Spacer(Modifier.width(8.dp))
                Column(
                    horizontalAlignment = Alignment.End,
                    verticalArrangement = Arrangement.spacedBy(4.dp)
                ) {
                    if (isOwned) {
                        Surface(
                            modifier = Modifier.height(32.dp),
                            shape = RoundedCornerShape(50),
                            color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.6f)
                        ) {
                            Row(
                                modifier = Modifier.padding(horizontal = 12.dp),
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                Icon(
                                    Icons.Filled.Check,
                                    contentDescription = null,
                                    tint = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.5f),
                                    modifier = Modifier.size(14.dp)
                                )
                                Spacer(Modifier.width(4.dp))
                                Text(
                                    "已添加",
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.5f)
                                )
                            }
                        }
                    } else {
                        FilledTonalButton(
                            onClick = onAdd,
                            modifier = Modifier.height(32.dp),
                            contentPadding = PaddingValues(horizontal = 12.dp),
                            colors = ButtonDefaults.filledTonalButtonColors(
                                containerColor = Primary.copy(alpha = 0.12f),
                                contentColor = Primary
                            )
                        ) {
                            Icon(
                                Icons.Filled.Add,
                                contentDescription = null,
                                modifier = Modifier.size(16.dp)
                            )
                            Spacer(Modifier.width(4.dp))
                            Text("添加", style = MaterialTheme.typography.bodySmall)
                        }
                    }
                }
            }
        }
    }
}

private fun Character.hallOwnerName(): String {
    return ownerRaw?.trim()?.takeIf { it.isNotBlank() }
        ?: owner?.replace(Regex("\\s*\\([^)]*\\)\\s*$"), "")?.trim().orEmpty()
}

private const val CertifiedCharacterLabel = "认证角色"

private fun Character.hallOwnerInlineLabel(): String {
    if (isSystemPublished()) return CertifiedCharacterLabel
    val ownerName = hallOwnerName()
    return ownerName.takeIf { it.isNotBlank() }?.let { "by $it" }.orEmpty()
}

private fun Character.hallOwnerDetailLabel(): String {
    if (isSystemPublished()) return "身份：$CertifiedCharacterLabel"
    val ownerName = hallOwnerName()
    return ownerName.takeIf { it.isNotBlank() }?.let { "作者：$it" }.orEmpty()
}

@Composable
private fun Icon(
    imageVector: ImageVector,
    contentDescription: String?,
    modifier: Modifier = Modifier,
    tint: Color = LocalContentColor.current
) {
    ScaledIcon(
        imageVector = imageVector,
        contentDescription = contentDescription,
        modifier = modifier,
        tint = tint
    )
}
