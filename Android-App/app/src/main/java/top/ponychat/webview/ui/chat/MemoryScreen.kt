package top.ponychat.webview.ui.chat

import androidx.compose.animation.*
import androidx.compose.animation.core.*
import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.DirectionsRun
import androidx.compose.material.icons.automirrored.filled.EventNote
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import kotlinx.coroutines.launch
import top.ponychat.webview.CustomToast
import top.ponychat.webview.data.api.NetworkClient
import top.ponychat.webview.data.model.*
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.ui.character.CharacterAvatar
import top.ponychat.webview.ui.common.PonyConfirmDialog
import top.ponychat.webview.ui.common.PonyDialogActionStyle
import top.ponychat.webview.ui.common.PonyTopBar
import top.ponychat.webview.ui.common.adaptivePopupMenuAccentColor
import top.ponychat.webview.ui.common.adaptivePopupMenuBorder
import top.ponychat.webview.ui.common.adaptivePopupMenuContainerColor
import top.ponychat.webview.ui.common.adaptivePopupMenuContentColor
import top.ponychat.webview.ui.theme.*
import top.ponychat.webview.util.formatErrorForDisplay
import java.text.SimpleDateFormat
import java.util.*

// ==================== UI 状态 ====================

private data class MemoryUiState(
    val memories: List<MemoryItem> = emptyList(),
    val isLoading: Boolean = false,
    val error: String? = null,
    val selectedLayer: Int = 0,
    val fragmentTypeFilter: String? = null
)

// ==================== 主页面 ====================

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MemoryScreen(
    character: Character,
    prefs: AppPreferences,
    onNavigateBack: () -> Unit
) {
    val scope = rememberCoroutineScope()
    var uiState by remember { mutableStateOf(MemoryUiState(isLoading = true)) }
    var showAddDialog by remember { mutableStateOf(false) }
    var editingMemory by remember { mutableStateOf<MemoryItem?>(null) }
    var pendingDeleteId by remember { mutableStateOf<Int?>(null) }
    val snackbarHostState = CustomToast.current

    val username = prefs.username
    val displayName = prefs.nickname.ifBlank { prefs.username }
    val charId = character.id ?: ""

    fun loadMemories() {
        scope.launch {
            uiState = uiState.copy(isLoading = true, error = null)
            try {
                val api = NetworkClient.createApiService(prefs)
                val types = if (uiState.selectedLayer == 0)
                    uiState.fragmentTypeFilter
                else null
                val resp = api.getMemories(
                    username = username,
                    characterId = charId,
                    memoryType = types,
                    layer = uiState.selectedLayer
                )
                if (resp.isSuccessful) {
                    uiState = uiState.copy(
                        memories = resp.body()?.memories ?: emptyList(),
                        isLoading = false
                    )
                } else {
                    uiState = uiState.copy(isLoading = false, error = "加载失败 (${resp.code()})")
                }
            } catch (e: Exception) {
                uiState = uiState.copy(isLoading = false, error = "网络错误：${e.message}")
            }
        }
    }

    LaunchedEffect(uiState.selectedLayer, uiState.fragmentTypeFilter) { loadMemories() }

    // 删除确认弹窗
    if (pendingDeleteId != null) {
        val id = pendingDeleteId!!
        val layer = uiState.memories.find { it.id == id }?.layer ?: 0
        val message = if (layer == 0)
            "确认删除这条记忆碎片？AI 将不再记得这件事。"
        else
            "确认删除这条 AI 生成的摘要？此操作无法撤销。"
        PonyConfirmDialog(
            title = "删除记忆",
            message = message,
            confirmText = "删除",
            actionStyle = PonyDialogActionStyle.Danger,
            onDismiss = { pendingDeleteId = null },
            onConfirm = {
                pendingDeleteId = null
                scope.launch {
                    try {
                        val api = NetworkClient.createApiService(prefs)
                        api.deleteMemory(id, DeleteMemoryRequest(username, charId))
                        uiState = uiState.copy(
                            memories = uiState.memories.filter { it.id != id }
                        )
                        snackbarHostState.showSnackbar("记忆已删除")
                    } catch (e: Exception) {
                        snackbarHostState.showSnackbar("删除失败，请重试")
                    }
                }
            }
        )
    }

    // 添加弹窗（仅碎片层可操作）
    if (showAddDialog) {
        MemoryEditDialog(
            title = "新增记忆碎片",
            initial = null,
            onDismiss = { showAddDialog = false },
            onConfirm = { type, content, importance ->
                showAddDialog = false
                scope.launch {
                    try {
                        val api = NetworkClient.createApiService(prefs)
                        val resp = api.addMemory(
                            AddMemoryRequest(
                                username = username,
                                characterId = charId,
                                memoryType = type,
                                content = content,
                                importance = importance,
                                source = "manual"
                            )
                        )
                        if (resp.isSuccessful) {
                            resp.body()?.let { newItem ->
                                uiState = uiState.copy(
                                    memories = listOf(newItem) + uiState.memories
                                )
                            }
                            snackbarHostState.showSnackbar("记忆碎片已添加")
                        } else {
                            snackbarHostState.showSnackbar("添加失败 (${resp.code()})")
                        }
                    } catch (e: Exception) {
                        snackbarHostState.showSnackbar("网络错误，请重试")
                    }
                }
            }
        )
    }

    editingMemory?.takeIf { it.layer == 0 }?.let { item ->
        MemoryEditDialog(
            title = "编辑记忆碎片",
            initial = item,
            onDismiss = { editingMemory = null },
            onConfirm = { type, content, importance ->
                editingMemory = null
                scope.launch {
                    try {
                        val api = NetworkClient.createApiService(prefs)
                        val resp = api.updateMemory(
                            item.id,
                            UpdateMemoryRequest(
                                username = username,
                                characterId = charId,
                                content = content,
                                importance = importance,
                                memoryType = type
                            )
                        )
                        if (resp.isSuccessful) {
                            uiState = uiState.copy(
                                memories = uiState.memories.map {
                                    if (it.id == item.id) it.copy(
                                        content = content,
                                        importance = importance,
                                        memoryType = type
                                    ) else it
                                }
                            )
                            snackbarHostState.showSnackbar("记忆已更新")
                        } else {
                            snackbarHostState.showSnackbar("更新失败 (${resp.code()})")
                        }
                    } catch (e: Exception) {
                        snackbarHostState.showSnackbar("网络错误，请重试")
                    }
                }
            }
        )
    }

    editingMemory?.takeIf { it.layer != 0 }?.let { item ->
        SummaryEditDialog(
            item = item,
            onDismiss = { editingMemory = null },
            onConfirm = { content ->
                editingMemory = null
                scope.launch {
                    try {
                        val api = NetworkClient.createApiService(prefs)
                        val resp = api.updateMemory(
                            item.id,
                            UpdateMemoryRequest(
                                username = username,
                                characterId = charId,
                                content = content
                            )
                        )
                        if (resp.isSuccessful) {
                            uiState = uiState.copy(
                                memories = uiState.memories.map {
                                    if (it.id == item.id) it.copy(content = content) else it
                                }
                            )
                            snackbarHostState.showSnackbar("${item.layerLabel()}已更新")
                        } else {
                            snackbarHostState.showSnackbar("更新失败 (${resp.code()})")
                        }
                    } catch (e: Exception) {
                        snackbarHostState.showSnackbar("网络错误，请重试")
                    }
                }
            }
        )
    }

    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        topBar = {
            MemoryTopBar(
                character = character,
                prefs = prefs,
                memoryCount = uiState.memories.size,
                selectedLayer = uiState.selectedLayer,
                onNavigateBack = onNavigateBack
            )
        },
        floatingActionButton = {
            AnimatedVisibility(
                visible = uiState.selectedLayer == 0,
                enter = scaleIn(),
                exit = scaleOut()
            ) {
                FloatingActionButton(
                    onClick = { showAddDialog = true },
                    containerColor = Primary,
                    contentColor = Color.White,
                    shape = CircleShape,
                    elevation = FloatingActionButtonDefaults.elevation(4.dp)
                ) {
                    Icon(Icons.Filled.Add, contentDescription = "添加记忆碎片")
                }
            }
        }
    ) { innerPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
        ) {
            // 层级 Tab 栏
            LayerTabBar(
                selected = uiState.selectedLayer,
                onSelect = { layer ->
                    uiState = uiState.copy(
                        selectedLayer = layer,
                        fragmentTypeFilter = null,
                        memories = emptyList()
                    )
                },
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 10.dp)
            )

            // Fragment 层的类型筛选条（仅在碎片层显示）
            AnimatedVisibility(
                visible = uiState.selectedLayer == 0,
                enter = expandVertically() + fadeIn(),
                exit = shrinkVertically() + fadeOut()
            ) {
                Column {
                    FragmentTypeFilterBar(
                        selected = uiState.fragmentTypeFilter,
                        onSelect = { uiState = uiState.copy(fragmentTypeFilter = it) },
                        modifier = Modifier.padding(start = 16.dp, end = 16.dp, bottom = 10.dp)
                    )
                }
            }

            HorizontalDivider(
                color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.1f)
            )

            // 内容区域
            Box(modifier = Modifier.fillMaxSize()) {
                when {
                    uiState.isLoading -> MemoryLoadingState(Modifier.align(Alignment.Center))
                    uiState.error != null -> MemoryErrorState(
                        message = uiState.error!!,
                        onRetry = { loadMemories() },
                        modifier = Modifier.align(Alignment.Center)
                    )
                    uiState.memories.isEmpty() -> MemoryEmptyState(
                        selectedLayer = uiState.selectedLayer,
                        fragmentTypeFilter = uiState.fragmentTypeFilter,
                        modifier = Modifier.align(Alignment.Center)
                    )
                    uiState.selectedLayer == 0 -> FragmentMemoryList(
                        memories = uiState.memories,
                        displayName = displayName,
                        onEdit = { editingMemory = it },
                        onDelete = { pendingDeleteId = it.id }
                    )
                    else -> SummaryMemoryList(
                        memories = uiState.memories,
                        layer = uiState.selectedLayer,
                        displayName = displayName,
                        onEdit = { editingMemory = it },
                        onDelete = { pendingDeleteId = it.id }
                    )
                }
            }
        }
    }
}
