package top.ponychat.webview.ui.chat

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.tween
import androidx.compose.animation.expandVertically
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.shrinkVertically
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.NotificationsActive
import androidx.compose.material.icons.filled.PauseCircle
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import top.ponychat.webview.data.api.NetworkClient
import top.ponychat.webview.data.model.Character
import top.ponychat.webview.data.model.ProactiveTask
import top.ponychat.webview.data.model.ProactiveTaskRequest
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.ui.character.CharacterAvatar
import top.ponychat.webview.ui.common.PonyTopBar
import top.ponychat.webview.ui.common.PonyTopBarBackButton
import top.ponychat.webview.ui.common.focusAwareBringIntoView
import top.ponychat.webview.ui.theme.Primary
import top.ponychat.webview.ui.theme.PrimaryLight
import top.ponychat.webview.ui.theme.ponyNeutralContainerColors
import top.ponychat.webview.ui.theme.ponyTintContainerColors
import top.ponychat.webview.util.formatErrorForDisplay
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Date
import java.util.Locale

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ProactiveTasksScreen(
    character: Character,
    prefs: AppPreferences,
    onNavigateBack: () -> Unit
) {
    val scope = rememberCoroutineScope()
    val focusManager = LocalFocusManager.current
    val keyboardController = LocalSoftwareKeyboardController.current
    var tasks by remember(character.id) { mutableStateOf<List<ProactiveTask>>(emptyList()) }
    var loading by remember(character.id) { mutableStateOf(false) }
    var hasLoadedTasks by remember(character.id) { mutableStateOf(false) }
    var message by remember(character.id) { mutableStateOf("") }
    var deletingTaskIds by remember(character.id) { mutableStateOf<Set<String>>(emptySet()) }
    var updatingTaskIds by remember(character.id) { mutableStateOf<Set<String>>(emptySet()) }
    var title by remember { mutableStateOf("早安叫醒") }
    var prompt by remember { mutableStateOf("每天早上温柔叫我起床") }
    var scheduleType by remember { mutableStateOf("daily") }
    var dateText by remember { mutableStateOf(todayDateText()) }
    var timeOfDay by remember { mutableStateOf("07:30") }
    var intervalMinutes by remember { mutableStateOf("120") }
    var selectedWeekDay by remember { mutableIntStateOf(Calendar.getInstance().get(Calendar.DAY_OF_WEEK).toPonyWeekday()) }
    var monthDay by remember { mutableStateOf(Calendar.getInstance().get(Calendar.DAY_OF_MONTH).toString()) }

    fun refresh() {
        scope.launch {
            loading = true
            message = ""
            try {
                val api = NetworkClient.createApiService(prefs)
                val resp = api.listProactiveTasks(character.id ?: "")
                tasks = if (resp.isSuccessful) resp.body()?.tasks.orEmpty() else emptyList()
                if (!resp.isSuccessful) message = "加载失败：${resp.code()}"
            } catch (e: Exception) {
                message = "网络不可用，稍后再试"
            } finally {
                hasLoadedTasks = true
                loading = false
            }
        }
    }

    fun createTask(request: ProactiveTaskRequest, okText: String) {
        focusManager.clearFocus(force = true)
        keyboardController?.hide()
        scope.launch {
            message = ""
            try {
                val api = NetworkClient.createApiService(prefs)
                val resp = api.createProactiveTask(request)
                if (resp.isSuccessful) {
                    message = okText
                    refresh()
                } else {
                    message = "创建失败：${resp.code()}"
                }
            } catch (e: Exception) {
                message = "创建失败，请检查网络"
            }
        }
    }

    fun submitTask() {
        val normalizedTime = normalizeTimeOfDay(timeOfDay)
        if (normalizedTime.isBlank() && scheduleType != "interval") {
            message = "请输入正确时间，例如 07:30"
            return
        }
        val interval = intervalMinutes.toIntOrNull()?.coerceAtLeast(1) ?: 0
        if (scheduleType == "interval" && interval <= 0) {
            message = "请输入正确间隔分钟数"
            return
        }
        val monthlyDay = monthDay.toIntOrNull()?.coerceIn(1, 31)
        if (scheduleType == "monthly" && monthlyDay == null) {
            message = "请输入 1-31 之间的每月日期"
            return
        }
        val onceDueAt = if (scheduleType == "once") parseDateTimeMs(dateText, normalizedTime) else null
        if (scheduleType == "once" && onceDueAt == null) {
            message = "请输入正确日期和时间"
            return
        }
        val effectiveTitle = title.ifBlank { scheduleType.defaultTaskTitle() }
        val effectivePrompt = prompt.ifBlank { "到时间后用角色的语气提醒我：$effectiveTitle" }
        createTask(
            ProactiveTaskRequest(
                characterId = character.id ?: "",
                title = effectiveTitle,
                taskType = if (scheduleType == "daily" && normalizedTime < "12:00") "morning_wakeup" else "reminder",
                scheduleType = scheduleType,
                dueAtMs = onceDueAt,
                intervalSeconds = if (scheduleType == "interval") interval * 60 else 0,
                timeOfDay = if (scheduleType == "interval") "" else normalizedTime,
                days = when (scheduleType) {
                    "weekly" -> listOf(selectedWeekDay)
                    "monthly" -> listOf(monthlyDay ?: 1)
                    else -> emptyList()
                },
                prompt = effectivePrompt,
                style = "gentle",
                jitterMinutes = if (scheduleType in setOf("daily", "weekly", "monthly")) 5 else 0
            ),
            "已创建${scheduleType.shortLabel()}任务"
        )
    }

    LaunchedEffect(character.id) { refresh() }
    val isInitialTasksLoading = !hasLoadedTasks && tasks.isEmpty()

    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        topBar = {
            PonyTopBar {
                PonyTopBarBackButton(onClick = onNavigateBack)
                Spacer(Modifier.width(4.dp))
                Row(
                    modifier = Modifier.weight(1f),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    CharacterAvatar(
                        avatarUrl = character.avatarUrl(),
                        name = character.displayName(),
                        apiBase = prefs.effectiveApiBase(),
                        size = 32
                    )
                    Spacer(Modifier.width(10.dp))
                    Column(
                        verticalArrangement = Arrangement.Center
                    ) {
                        Text(
                            "定时任务",
                            style = MaterialTheme.typography.titleMedium.copy(lineHeight = 20.sp),
                            fontWeight = FontWeight.SemiBold,
                            color = MaterialTheme.colorScheme.onBackground,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis
                        )
                        Text(
                            character.displayName(),
                            style = MaterialTheme.typography.labelSmall.copy(lineHeight = 16.sp),
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis
                        )
                    }
                }
                IconButton(onClick = { refresh() }) {
                    Icon(Icons.Filled.Refresh, contentDescription = "刷新")
                }
            }
        }
    ) { innerPadding ->
        LazyColumn(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
                .imePadding(),
            contentPadding = PaddingValues(start = 16.dp, top = 16.dp, end = 16.dp, bottom = 24.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp)
        ) {
            item {
                TaskSummaryCard(tasks = tasks, loading = loading || isInitialTasksLoading)
            }

            item {
                val taskEditorColors = ponyNeutralContainerColors()
                val taskIconColors = ponyTintContainerColors(Primary)
                Surface(
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(12.dp),
                    color = taskEditorColors.container,
                    border = BorderStroke(1.dp, taskEditorColors.border)
                ) {
                    Column(
                        verticalArrangement = Arrangement.spacedBy(0.dp)
                    ) {
                        Row(
                            modifier = Modifier.padding(start = 16.dp, end = 16.dp, top = 14.dp, bottom = 8.dp),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Icon(
                                Icons.Filled.Add,
                                contentDescription = null,
                                tint = taskIconColors.content,
                                modifier = Modifier
                                    .size(28.dp)
                                    .background(taskIconColors.container, CircleShape)
                                    .padding(5.dp)
                            )
                            Spacer(Modifier.width(10.dp))
                            Column {
                                Text("新建任务", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
                                Text("也会显示从普通对话里识别出的提醒", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            }
                        }
                        TaskCardDivider()
                        TaskEditItem(
                            label = "标题",
                            value = title,
                            onValueChange = { title = it },
                            placeholder = "早安叫醒"
                        )
                        TaskCardDivider()
                        TaskEditBlock(
                            label = "任务内容",
                            value = prompt,
                            onValueChange = { prompt = it },
                            placeholder = "每天早上温柔叫我起床"
                        )
                        TaskCardDivider()
                        ScheduleTypeSelector(
                            selected = scheduleType,
                            onSelected = { scheduleType = it }
                        )
                        TaskCardDivider()
                        when (scheduleType) {
                            "once" -> {
                                TaskEditItem(
                                    label = "日期",
                                    value = dateText,
                                    onValueChange = { dateText = it.take(10) },
                                    placeholder = "2026-06-13",
                                    keyboardType = KeyboardType.Number
                                )
                                TaskCardDivider()
                                TaskEditItem(
                                    label = "时间",
                                    value = timeOfDay,
                                    onValueChange = { timeOfDay = it.take(5) },
                                    placeholder = "07:30",
                                    keyboardType = KeyboardType.Number
                                )
                            }
                            "daily" -> TaskEditItem(
                                label = "时间",
                                value = timeOfDay,
                                onValueChange = { timeOfDay = it.take(5) },
                                placeholder = "07:30",
                                keyboardType = KeyboardType.Number
                            )
                            "weekly" -> {
                                WeekdaySelector(
                                    selected = selectedWeekDay,
                                    onSelected = { selectedWeekDay = it }
                                )
                                TaskCardDivider()
                                TaskEditItem(
                                    label = "时间",
                                    value = timeOfDay,
                                    onValueChange = { timeOfDay = it.take(5) },
                                    placeholder = "07:30",
                                    keyboardType = KeyboardType.Number
                                )
                            }
                            "monthly" -> {
                                TaskEditItem(
                                    label = "每月日期",
                                    value = monthDay,
                                    onValueChange = { monthDay = it.filter(Char::isDigit).take(2) },
                                    placeholder = "13",
                                    keyboardType = KeyboardType.Number
                                )
                                TaskCardDivider()
                                TaskEditItem(
                                    label = "时间",
                                    value = timeOfDay,
                                    onValueChange = { timeOfDay = it.take(5) },
                                    placeholder = "07:30",
                                    keyboardType = KeyboardType.Number
                                )
                            }
                            "interval" -> TaskEditItem(
                                label = "间隔分钟",
                                value = intervalMinutes,
                                onValueChange = { intervalMinutes = it.filter(Char::isDigit).take(5) },
                                placeholder = "120",
                                keyboardType = KeyboardType.Number
                            )
                        }
                        TaskCardDivider()
                        Column(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(horizontal = 16.dp, vertical = 12.dp)
                        ) {
                            Button(
                                onClick = { submitTask() },
                                modifier = Modifier.fillMaxWidth(),
                                shape = RoundedCornerShape(999.dp),
                                contentPadding = PaddingValues(horizontal = 12.dp, vertical = 12.dp)
                            ) {
                                Text("创建")
                            }
                        }
                        if (message.isNotBlank()) {
                            Text(
                                formatErrorForDisplay(message),
                                style = MaterialTheme.typography.bodySmall,
                                color = PrimaryLight
                            )
                        }
                    }
                }
            }

            if (loading || isInitialTasksLoading) {
                item {
                    Box(Modifier.fillMaxWidth().padding(28.dp), contentAlignment = Alignment.Center) {
                        CircularProgressIndicator()
                    }
                }
            } else if (tasks.isEmpty()) {
                item {
                    EmptyTasksState()
                }
            } else {
                items(tasks, key = { it.id }) { task ->
                    AnimatedVisibility(
                        visible = task.id !in deletingTaskIds,
                        enter = fadeIn(animationSpec = tween(140)) + expandVertically(animationSpec = tween(180)),
                        exit = fadeOut(animationSpec = tween(140)) + shrinkVertically(animationSpec = tween(220)),
                        modifier = Modifier.animateItem()
                    ) {
                        ProactiveTaskItem(
                            task = task,
                            busy = task.id in updatingTaskIds || task.id in deletingTaskIds,
                            onToggle = {
                                if (task.id in updatingTaskIds || task.id in deletingTaskIds) return@ProactiveTaskItem
                                val before = task
                                val nextEnabled = !task.enabled
                                tasks = tasks.map {
                                    if (it.id == task.id) {
                                        it.copy(
                                            enabled = nextEnabled,
                                            status = if (nextEnabled) "active" else "paused"
                                        )
                                    } else {
                                        it
                                    }
                                }
                                updatingTaskIds = updatingTaskIds + task.id
                                scope.launch {
                                    try {
                                        val api = NetworkClient.createApiService(prefs)
                                        val resp = api.updateProactiveTask(task.id, before.toRequest(enabled = nextEnabled))
                                        if (!resp.isSuccessful) {
                                            tasks = tasks.map { if (it.id == before.id) before else it }
                                            message = "更新失败：${resp.code()}"
                                        }
                                    } catch (e: Exception) {
                                        tasks = tasks.map { if (it.id == before.id) before else it }
                                        message = "更新失败，请检查网络"
                                    } finally {
                                        updatingTaskIds = updatingTaskIds - task.id
                                    }
                                }
                            },
                            onDelete = {
                                if (task.id in deletingTaskIds) return@ProactiveTaskItem
                                val beforeIndex = tasks.indexOfFirst { it.id == task.id }.coerceAtLeast(0)
                                deletingTaskIds = deletingTaskIds + task.id
                                scope.launch {
                                    delay(240)
                                    tasks = tasks.filterNot { it.id == task.id }
                                    try {
                                        val api = NetworkClient.createApiService(prefs)
                                        val resp = api.deleteProactiveTask(task.id)
                                        if (!resp.isSuccessful) {
                                            val insertIndex = beforeIndex.coerceIn(0, tasks.size)
                                            tasks = tasks.toMutableList().apply { add(insertIndex, task) }
                                            message = "删除失败：${resp.code()}"
                                        }
                                    } catch (e: Exception) {
                                        val insertIndex = beforeIndex.coerceIn(0, tasks.size)
                                        tasks = tasks.toMutableList().apply { add(insertIndex, task) }
                                        message = "删除失败，请检查网络"
                                    } finally {
                                        deletingTaskIds = deletingTaskIds - task.id
                                    }
                                }
                            }
                        )
                    }
                }
            }
        }
    }
}
