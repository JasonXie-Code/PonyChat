package top.ponychat.webview

import android.app.Activity
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.pm.ServiceInfo
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.BitmapShader
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Outline
import android.graphics.Paint
import android.graphics.PixelFormat
import android.graphics.RectF
import android.graphics.Shader
import android.graphics.drawable.GradientDrawable
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.Image
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.VibrationEffect
import android.os.Vibrator
import android.content.pm.PackageManager
import android.provider.Settings
import android.text.InputType
import android.util.Base64
import android.util.DisplayMetrics
import android.util.Log
import android.animation.Animator
import android.animation.AnimatorListenerAdapter
import android.animation.ValueAnimator
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import android.view.ViewOutlineProvider
import android.view.WindowManager
import android.view.animation.AccelerateInterpolator
import android.view.animation.DecelerateInterpolator
import android.view.animation.LinearInterpolator
import android.view.inputmethod.InputMethodManager
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.util.ClientContextHelper
import androidx.core.app.NotificationCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import kotlin.math.abs

internal fun CompanionService.executeAgentAction(action: org.json.JSONObject) {
    if (!CompanionService._isRunning.value) {
        Log.w(CompanionService.TAG, "executeAgentAction: service already stopped, discarding action")
        return
    }
    val type = action.optString("type", "none")
    Log.i(CompanionService.TAG, "executeAgentAction: $action")
    if (android.os.Build.VERSION.SDK_INT < android.os.Build.VERSION_CODES.N) {
        Log.w(CompanionService.TAG, "gesture dispatch requires API 24+, skipping")
        return
    }
    lastAgentActionType = type  // 供自动循环判断是否继续
    when (type) {
        "tap" -> {
            val nx = action.optDouble("x", -1.0).toFloat()
            val ny = action.optDouble("y", -1.0).toFloat()
            if (nx < 0 || ny < 0) { lastAgentActionType = "none"; return }
            // 兼容 AI 有时返回像素值（>1）而非归一化值（0~1）：
            // 若坐标 >1 则视为绝对像素直接使用，否则乘以屏幕尺寸
            val px = if (nx > 1f) nx else nx * screenWidth
            val py = if (ny > 1f) ny else ny * screenHeight
            Log.i(CompanionService.TAG, "Agent tap: raw=($nx,$ny) → pixel=($px,$py) screen=${screenWidth}x${screenHeight}")
            lastTapNx = if (nx > 1f) nx / screenWidth else nx
            lastTapNy = if (ny > 1f) ny / screenHeight else ny
            val rescueTarget = launchRescueTarget()
            if (rescueTarget != null && shouldRescueSuspiciousSearchTap(lastTapNy)) {
                Log.w(
                    CompanionService.TAG,
                    "Agent tap looks suspicious after repeated input failures, fallback launch target=$rescueTarget raw=($nx,$ny)"
                )
                lastLaunchApp = launchAppByName(rescueTarget)
                return
            }
            AgentAccessibilityService.performTap(px, py)
        }
        "swipe" -> {
            val fx = action.optDouble("from_x", -1.0).toFloat()
            val fy = action.optDouble("from_y", -1.0).toFloat()
            val tx = action.optDouble("to_x", -1.0).toFloat()
            val ty = action.optDouble("to_y", -1.0).toFloat()
            val dur = action.optLong("duration_ms", 400L)
            if (fx < 0 || fy < 0 || tx < 0 || ty < 0) { lastAgentActionType = "none"; return }
            val fpx = if (fx > 1f) fx else fx * screenWidth
            val fpy = if (fy > 1f) fy else fy * screenHeight
            val tpx = if (tx > 1f) tx else tx * screenWidth
            val tpy = if (ty > 1f) ty else ty * screenHeight
            Log.i(CompanionService.TAG, "Agent swipe: ($fpx,$fpy)→($tpx,$tpy)")
            lastSwipeFx = if (fx > 1f) fx / screenWidth else fx
            lastSwipeFy = if (fy > 1f) fy / screenHeight else fy
            lastSwipeTx = if (tx > 1f) tx / screenWidth else tx
            lastSwipeTy = if (ty > 1f) ty / screenHeight else ty
            AgentAccessibilityService.performSwipe(fpx, fpy, tpx, tpy, dur)
        }
        "system" -> {
            val sysAction = action.optString("action", "")
            lastSystemAction = sysAction
            val ok = AgentAccessibilityService.performSystemAction(sysAction)
            if (!ok) {
                // performGlobalAction 返回 false：可能是 ROM 兼容性问题（已知 Xiaomi/Poco 等）
                Log.w(CompanionService.TAG, "system action failed, downgrading to none: $sysAction")
                lastAgentActionType = "none"
            }
        }
        "long_press" -> {
            val nx = action.optDouble("x", -1.0).toFloat()
            val ny = action.optDouble("y", -1.0).toFloat()
            if (nx < 0 || ny < 0) { lastAgentActionType = "none"; return }
            val px = if (nx > 1f) nx else nx * screenWidth
            val py = if (ny > 1f) ny else ny * screenHeight
            lastLongPressNx = if (nx > 1f) nx / screenWidth else nx
            lastLongPressNy = if (ny > 1f) ny / screenHeight else ny
            Log.i(CompanionService.TAG, "Agent long_press: raw=($nx,$ny) → pixel=($px,$py)")
            AgentAccessibilityService.performLongPress(px, py)
        }
        "input_text" -> {
            val text = action.optString("text", "")
            if (text.isBlank()) { lastAgentActionType = "none"; return }
            lastInputText = text.take(20)
            Log.i(CompanionService.TAG, "Agent input_text: ${text.take(30)}")
            val ok = AgentAccessibilityService.performInputText(text)
            if (!ok) {
                lastInputText = "${text.take(16)}-FAIL"
                Log.w(CompanionService.TAG, "Agent input_text failed: ${text.take(30)}")
                val rescueTarget = launchRescueTarget(text)
                if (rescueTarget != null && shouldRescueInputFailure(text)) {
                    Log.w(CompanionService.TAG, "Agent input_text fallback to launch: $rescueTarget")
                    lastLaunchApp = launchAppByName(rescueTarget)
                }
            }
        }
        "launch" -> {
            val appName = action.optString("app", "").trim()
            if (appName.isBlank()) {
                Log.w(CompanionService.TAG, "launch action missing 'app' field")
                lastLaunchApp = "?-FAIL"
                lastAgentActionType = "none"
            } else {
                lastLaunchApp = launchAppByName(appName)
            }
        }
        "none" -> {
            // 仅聊天，无需操作；lastAgentActionType 已设为 "none"，循环将在本步后结束
            val reason = action.optString("reason")
            if (reason.isNotBlank()) Log.i(CompanionService.TAG, "AgentAction none reason: $reason")
        }
        "failed" -> {
            // 当前步骤无法完成；记录原因，循环将在本步后停止
            lastFailedReason = action.optString("reason", "无法完成当前步骤")
            Log.w(CompanionService.TAG, "AgentAction failed reason: $lastFailedReason")
        }
        "wait" -> {
            // 等待界面加载；不执行任何手势，由 agentLoopStep 在延迟分支中消费 lastWaitMs
            val ms = action.optLong("ms", 1500L).coerceIn(500L, 5000L)
            lastWaitMs = ms
            Log.i(CompanionService.TAG, "Agent wait: ${ms}ms")
        }
        else -> {
            Log.w(CompanionService.TAG, "unknown agent action type: $type")
            lastAgentActionType = "none"
        }
    }
}

/**
 * 用 PackageManager 模糊匹配 App 名称并直接启动，返回实际记录用的描述字符串。
 * 成功返回 "AppLabel"，失败返回 "AppLabel-FAIL"；同时更新 lastAgentActionType。
 */
internal fun CompanionService.launchAppByName(appName: String): String {
    val pm = packageManager
    val apps = pm.getInstalledApplications(PackageManager.GET_META_DATA)
    // 先精确匹配 label，再 contains 匹配，最后尝试匹配 package name
    val match = apps.firstOrNull { app ->
        val label = pm.getApplicationLabel(app).toString()
        label.equals(appName, ignoreCase = true)
    } ?: apps.firstOrNull { app ->
        val label = pm.getApplicationLabel(app).toString()
        label.contains(appName, ignoreCase = true) || appName.contains(label, ignoreCase = true)
    } ?: apps.firstOrNull { app ->
        app.packageName.contains(appName, ignoreCase = true)
    }

    if (match == null) {
        Log.w(CompanionService.TAG, "launchApp: 找不到 App「$appName」")
        lastAgentActionType = "launch"   // 保持 launch 让 AI 看到 FAIL 后降级
        return "$appName-FAIL"
    }

    val launchIntent = pm.getLaunchIntentForPackage(match.packageName)
    if (launchIntent == null) {
        Log.w(CompanionService.TAG, "launchApp: 「$appName」无启动 Intent (pkg=${match.packageName})")
        lastAgentActionType = "launch"
        return "$appName-FAIL"
    }

    launchIntent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
    startActivity(launchIntent)
    val label = pm.getApplicationLabel(match).toString()
    Log.i(CompanionService.TAG, "launchApp: 已启动「$label」(${match.packageName})")
    lastAgentActionType = "launch"
    return label
}

internal fun CompanionService.recentInputFailCount(window: Int = 4): Int {
    return agentStepHistory.takeLast(window).count { it.contains("INPUT(") && it.contains("-FAIL") }
}

internal fun CompanionService.recentInputTarget(): String? {
    val regex = Regex("""INPUT\(「(.+?)」\)""")
    return agentStepHistory.asReversed().firstNotNullOfOrNull { step ->
        regex.find(step)?.groupValues?.getOrNull(1)
            ?.removeSuffix("-FAIL")
            ?.trim()
            ?.takeIf { it.isNotBlank() }
    }
}

internal fun CompanionService.launchRescueTarget(preferred: String? = null): String? {
    val target = preferred?.trim().orEmpty().ifBlank { recentInputTarget().orEmpty() }
    if (target.isBlank()) return null
    if (target.length > 16) return null
    if (target.any { it.isWhitespace() }) return null
    return target
}

internal fun CompanionService.shouldRescueInputFailure(text: String): Boolean {
    if (!isAgentMode) return false
    if (recentInputFailCount() < 2) return false
    if (text.length > 16) return false
    return taskLooksLikeOpenApp()
}

internal fun CompanionService.shouldRescueSuspiciousSearchTap(normalizedY: Float): Boolean {
    if (!isAgentMode) return false
    if (recentInputFailCount() < 2) return false
    if (!taskLooksLikeOpenApp()) return false
    return normalizedY >= 0.42f
}

internal fun CompanionService.taskLooksLikeOpenApp(): Boolean {
    if (agentLoopTask.isBlank()) return false
    val keywords = listOf("打开", "点开", "进入", "启动", "搜索")
    return keywords.any { agentLoopTask.contains(it) }
}


// ── 操作陪玩自动循环 ──────────────────────────────────────────────────────

/**
 * Plan-and-Execute 第一阶段：调用后端规划端点，获取任务的分步执行计划。
 * 返回 Pair(步骤列表, 角色反应文字)；失败时降级为单步（以 task 本身作为唯一步骤）。
 */
/**
 * fetchAgentPlan 的返回值：
 * - stopRequested=true：后端判断用户意图是"停止/取消"，直接终止循环。
 * - chatOnly=true：后端判断用户只是聊天，不需要操作手机，跳过任务执行。
 */
data class AgentPlanResult(
    val plan: List<String>,
    val reaction: String,
    val stopRequested: Boolean = false,
    val chatOnly: Boolean = false,
)

internal suspend fun CompanionService.fetchAgentPlan(task: String, bitmap: Bitmap?): AgentPlanResult =
    withContext(Dispatchers.IO) {
        try {
            val b64 = bitmap?.let { bmp ->
                val baos = ByteArrayOutputStream()
                bmp.compress(Bitmap.CompressFormat.JPEG, 72, baos)
                // 这里不 recycle，bitmap 将由调用方继续使用（agentLoopStep 第一步需要它）
                Base64.encodeToString(baos.toByteArray(), Base64.NO_WRAP)
            } ?: ""
            val ctx = ClientContextHelper.buildContext(applicationContext)
            val bodyJson = JSONObject().apply {
                put("image_base64", b64)
                put("character_id", characterId)
                put("username", username)
                put("user_text", task)
                put("max_chars", 30)
                put("client_context", JSONObject().apply {
                    ctx.timeIso?.let { put("time_iso", it) }
                    ctx.deviceModel?.let { put("device_model", it) }
                    ctx.osVersion?.let { put("os_version", it) }
                    ctx.osFlavor?.let { put("os_flavor", it) }
                    ctx.navMode?.let { put("nav_mode", it) }
                })
            }.toString()
            val request = Request.Builder()
                .url("${apiBase.trimEnd('/')}/api/companion/agent_plan")
                .addHeader("X-Chat-Auth", authToken)
                .post(bodyJson.toRequestBody("application/json".toMediaTypeOrNull()))
                .build()
            val response = httpClient.newCall(request).execute()
            if (!response.isSuccessful) {
                Log.w(CompanionService.TAG, "fetchAgentPlan: HTTP ${response.code}")
                return@withContext AgentPlanResult(listOf(task), "好，我来帮你！")
            }
            val body = response.body?.string() ?: return@withContext AgentPlanResult(listOf(task), "好，我来帮你！")
            val json = JSONObject(body)
            val reaction = json.optString("reaction", "好，我来帮你！")
            // 后端规划模型判断任务为"停止/取消"语义时返回 stop: true
            if (json.optBoolean("stop", false)) {
                Log.i(CompanionService.TAG, "fetchAgentPlan: 停止指令，不启动循环")
                return@withContext AgentPlanResult(emptyList(), reaction, stopRequested = true)
            }
            // 后端判断用户只是聊天（不需要操作手机）时返回 chat: true
            if (json.optBoolean("chat", false)) {
                Log.i(CompanionService.TAG, "fetchAgentPlan: 纯对话，跳过任务执行")
                return@withContext AgentPlanResult(emptyList(), reaction, chatOnly = true)
            }
            val planArray = json.optJSONArray("plan")
            if (planArray == null || planArray.length() == 0) {
                return@withContext AgentPlanResult(listOf(task), reaction)
            }
            val plan = (0 until planArray.length())
                .map { planArray.getString(it).trim() }
                .filter { it.isNotEmpty() }
            Log.i(CompanionService.TAG, "fetchAgentPlan: ${plan.size} 步 → $plan")
            AgentPlanResult(plan.ifEmpty { listOf(task) }, reaction)
        } catch (e: Exception) {
            Log.w(CompanionService.TAG, "fetchAgentPlan failed: ${e.message}")
            AgentPlanResult(listOf(task), "好，我来帮你！")
        }
    }

/**
 * 启动自动循环：AI 持续截图 → 分析 → 执行操作，直到认为任务完成（返回 none）或达到步数上限。
 * [task] 为用户本次输入的任务描述，会随每步一起传给后端，保持目标连贯。
 * 若已在循环中，先停止旧循环再以新任务重新开始。
 */
internal fun CompanionService.startAgentLoop(task: String = "") {
    stopAgentLoop(reason = null)  // 停止旧循环（不展示停止消息）
    // 若新任务是"重新/再试/没点到"类反馈，自动带上上一轮有效任务作为上下文
    val retryKeywords = listOf("重新", "再试", "再点", "没点到", "没捡到", "点错了", "试一次", "还没")
    val isRetryIntent = task.isNotBlank() && retryKeywords.any { task.contains(it) }
    agentLoopTask = if (isRetryIntent && lastMeaningfulTask.isNotBlank()) {
        "$lastMeaningfulTask（用户补充：$task）"
    } else {
        task
    }
    if (!isRetryIntent && task.isNotBlank()) lastMeaningfulTask = task
    // 重置所有循环状态（含 Plan-and-Execute 状态）
    autoLoopStepCount = 0
    lastAgentActionType = "none"
    lastFailedReason = ""
    lastWaitMs = 0L
    agentStepHistory.clear()
    agentPlan = emptyList()
    agentPlanStepIndex = 0
    agentCurrentStepHistory.clear()
    recentStepDescs.clear()
    prevStepThumbnail?.recycle()
    prevStepThumbnail = null
    CompanionService._isAutoLooping.value = true
    mainHandler.post { showAgentLoopStatusCard(0) }  // 悬浮窗操作必须在主线程

    autoLoopJob = serviceScope.launch {
        // ── 规划阶段：截图 + 调用规划端点 ────────────────────────────────────
        val planBitmap = captureScreen()
        val planResult = fetchAgentPlan(agentLoopTask, planBitmap)
        planBitmap?.recycle()

        // 守卫：规划期间若循环被取消则退出
        if (!CompanionService._isRunning.value || !CompanionService._isAutoLooping.value) return@launch

        // 规划模型判断任务是"停止/取消"语义 → 直接停止，不启动执行循环
        if (planResult.stopRequested) {
            Log.i(CompanionService.TAG, "startAgentLoop: 规划返回停止信号，终止循环")
            CompanionService._isAutoLooping.value = false
            withContext(kotlinx.coroutines.Dispatchers.Main) {
                val msg = planResult.reaction
                if (chatDialogView != null) appendMessageToDialog(isUser = false, text = msg)
                else showOrUpdateCompanionCardOnMain(msg)
                speakIfNotRecording(msg)
                scheduleAutoHide()
            }
            return@launch
        }

        // 规划模型判断用户只是聊天（不需要操作手机） → 直接播报 plan reaction，不再调 agent_action
        if (planResult.chatOnly) {
            Log.i(CompanionService.TAG, "startAgentLoop: 纯对话回应，跳过任务执行")
            CompanionService._isAutoLooping.value = false
            withContext(kotlinx.coroutines.Dispatchers.Main) {
                val msg = planResult.reaction
                if (chatDialogView != null) appendMessageToDialog(isUser = false, text = msg)
                else showOrUpdateCompanionCardOnMain(msg)
                speakIfNotRecording(msg)
                scheduleAutoHide()
            }
            return@launch
        }

        val plan = planResult.plan
        val planReaction = planResult.reaction
        agentPlan = plan

        // 向用户展示计划（多步时显示列表）
        withContext(kotlinx.coroutines.Dispatchers.Main) {
            if (agentPlan.size > 1) {
                val planText = buildString {
                    append("执行计划（${agentPlan.size} 步）：\n")
                    agentPlan.forEachIndexed { i, step -> append("${i + 1}. $step\n") }
                }.trimEnd()
                if (chatDialogView != null) {
                    appendMessageToDialog(isUser = false, text = planText)
                } else {
                    showOrUpdateCompanionCardOnMain(planText)
                }
                if (planReaction.isNotEmpty()) speakIfNotRecording(planReaction)
            } else {
                // 单步或兼容模式：保持原来的简短提示
                if (agentLoopTask.isNotBlank() && chatDialogView != null) {
                    appendMessageToDialog(isUser = false, text = "好的，我来帮你：$agentLoopTask")
                }
            }
        }

        if (agentPlan.size > 1) kotlinx.coroutines.delay(600L) // 给用户时间看计划
        if (!CompanionService._isRunning.value || !CompanionService._isAutoLooping.value) return@launch

        mainHandler.post { showAgentLoopStatusCard(autoLoopStepCount + 1) }
        agentLoopStep()
    }
}

/**
 * 停止自动循环。[reason] 非 null 时在对话卡 / 弹幕展示停止原因。
 */
internal fun CompanionService.stopAgentLoop(reason: String? = "已停止") {
    autoLoopJob?.cancel()
    autoLoopJob = null
    CompanionService._isAutoLooping.value = false
    prevStepThumbnail?.recycle()
    prevStepThumbnail = null
    if (reason != null) {
        mainHandler.post {
            val msg = "$reason（共执行 $autoLoopStepCount 步）"
            if (chatDialogView != null) appendMessageToDialog(isUser = false, text = msg)
            else showOrUpdateCompanionCardOnMain(msg)
        }
    }
}

/**
 * 循环的单步逻辑（在 IO 协程中运行）：
 * 截图 → 发送给后端 agent_action 端点 → 执行操作 → 判断是否继续。
 * Plan-and-Execute 模式下：以当前计划步骤为焦点，步骤完成（none）后推进到下一步。
 */
internal suspend fun CompanionService.agentLoopStep() {
    // 守卫1：步骤开头检查服务和循环状态，以及协程是否已被取消
    if (!CompanionService._isRunning.value || !CompanionService._isAutoLooping.value) return

    autoLoopStepCount++
    mainHandler.post { showAgentLoopStatusCard(autoLoopStepCount) }

    // ── 截图 + 前后界面变化对比（回写上一步 -OK/-NOCHANGE）──────────────────
    val bitmap = captureScreen()
    val currentThumb = if (bitmap != null) createStepThumbnail(bitmap) else null
    if (prevStepThumbnail != null && currentThumb != null && agentStepHistory.isNotEmpty()) {
        val changed = !thumbnailsSimilar(prevStepThumbnail!!, currentThumb)
        val suffix = if (changed) "-OK" else "-NOCHANGE"
        val li = agentStepHistory.size - 1
        if (!agentStepHistory[li].contains("-OK") && !agentStepHistory[li].contains("-NOCHANGE")) {
            agentStepHistory[li] += suffix
        }
        if (agentPlan.isNotEmpty() && agentCurrentStepHistory.isNotEmpty()) {
            val ci = agentCurrentStepHistory.size - 1
            if (!agentCurrentStepHistory[ci].contains("-OK") && !agentCurrentStepHistory[ci].contains("-NOCHANGE")) {
                agentCurrentStepHistory[ci] += suffix
            }
        }
        prevStepThumbnail?.recycle()
    }
    prevStepThumbnail = currentThumb

    // ── 收集无障碍树可交互元素（辅助模型坐标定位）────────────────────────
    val uiElements = AgentAccessibilityService.getInteractiveElements(screenWidth.toInt(), screenHeight.toInt())

    // 选择本步的操作历史：计划模式用步骤内历史（更聚焦），兼容模式用全局历史
    val historyToUse = if (agentPlan.isNotEmpty()) agentCurrentStepHistory.toList()
                       else agentStepHistory.toList()

    // sendTextToBackendStreaming 在内部会调用 executeAgentAction，回写 lastAgentActionType
    sendTextToBackendStreaming(
        agentLoopTask, bitmap,
        stepHistory = historyToUse,
        suppressReaction = true,
        uiElements = uiElements,
    )

    // 守卫2：网络调用（OkHttp）不受协程取消打断，返回后立即再次检查
    if (!CompanionService._isRunning.value || !CompanionService._isAutoLooping.value) return

    withContext(kotlinx.coroutines.Dispatchers.Main) {
        streamingBubbleTv = null
        streamingBubbleRow = null
    }

    // 守卫3
    if (!CompanionService._isRunning.value || !CompanionService._isAutoLooping.value) return

    // 记录本步操作到历史（含坐标），供下步决策参考
    val stepDesc = when (lastAgentActionType) {
        "tap"        -> "第${autoLoopStepCount}步: TAP(%.3f,%.3f)".format(lastTapNx, lastTapNy)
        "long_press" -> "第${autoLoopStepCount}步: LONG_PRESS(%.3f,%.3f)".format(lastLongPressNx, lastLongPressNy)
        "swipe"      -> "第${autoLoopStepCount}步: SWIPE(%.3f,%.3f→%.3f,%.3f)".format(lastSwipeFx, lastSwipeFy, lastSwipeTx, lastSwipeTy)
        "system"     -> "第${autoLoopStepCount}步: SYSTEM($lastSystemAction)"
        "launch"     -> "第${autoLoopStepCount}步: LAUNCH($lastLaunchApp)"
        "input_text" -> "第${autoLoopStepCount}步: INPUT($lastInputText)"
        "wait"       -> "第${autoLoopStepCount}步: WAIT(${lastWaitMs}ms)"
        "failed"     -> "第${autoLoopStepCount}步: FAILED"
        else         -> "第${autoLoopStepCount}步: NONE"
    }
    agentStepHistory.add(stepDesc)
    if (agentPlan.isNotEmpty()) agentCurrentStepHistory.add(stepDesc)

    // ── 卡住检测：AAA（3步相同）或 ABAB（4步交替）─────────────────────────
    val actionKey = when (lastAgentActionType) {
        "tap"        -> "TAP(%.2f,%.2f)".format(lastTapNx, lastTapNy)
        "swipe"      -> "SWIPE(%.2f→%.2f)".format(lastSwipeFy, lastSwipeTy)
        "system"     -> "SYSTEM($lastSystemAction)"
        "launch"     -> "LAUNCH($lastLaunchApp)"
        else         -> lastAgentActionType
    }
    recentStepDescs.addLast(actionKey)
    if (recentStepDescs.size > 4) recentStepDescs.removeFirst()
    val isStuck = when {
        lastAgentActionType in listOf("none", "failed", "input_text", "wait") -> false
        recentStepDescs.size >= 3 && recentStepDescs.takeLast(3).all { it == actionKey } -> true
        recentStepDescs.size >= 4 -> {
            val d = recentStepDescs.toList()
            d[0] == d[2] && d[1] == d[3] && d[0] != d[1]
        }
        else -> false
    }

    // 判断是否继续循环
    when {
        !CompanionService._isRunning.value || !CompanionService._isAutoLooping.value -> return  // 守卫4
        autoLoopStepCount >= CompanionService.MAX_AGENT_LOOP_STEPS ->
            stopAgentLoop("已达最大步数上限 $CompanionService.MAX_AGENT_LOOP_STEPS 步")
        lastAgentActionType == "failed" -> {
            if (agentPlan.isEmpty() || agentPlanStepIndex >= agentPlan.size - 1) {
                // 兼容模式或最后一步：直接停止
                val label = if (agentPlan.isNotEmpty()) "步骤 ${agentPlanStepIndex + 1}" else "任务"
                stopAgentLoop("$label 失败：$lastFailedReason")
            } else {
                // Plan 模式且还有后续步骤：跳过失败步骤，继续执行
                Log.w(CompanionService.TAG, "plan step ${agentPlanStepIndex + 1} failed, skipping: $lastFailedReason")
                agentPlanStepIndex++
                agentCurrentStepHistory.clear()
                recentStepDescs.clear()
                mainHandler.post {
                    val skipMsg = "步骤 ${agentPlanStepIndex} 未能完成，继续下一步…"
                    if (chatDialogView != null) appendMessageToDialog(isUser = false, text = skipMsg)
                    else showOrUpdateCompanionCardOnMain(skipMsg)
                    showAgentLoopStatusCard(autoLoopStepCount)
                }
                kotlinx.coroutines.delay(CompanionService.AGENT_LOOP_STEP_DELAY_MS)
                if (CompanionService._isRunning.value && CompanionService._isAutoLooping.value) agentLoopStep()
            }
        }
        isStuck -> stopAgentLoop("操作似乎卡住了，请检查界面后重试")
        lastAgentActionType == "none" -> {
            if (agentPlan.isEmpty()) {
                // 兼容模式（无计划）：直接结束
                CompanionService._isAutoLooping.value = false
                autoLoopJob = null
                if (autoLoopStepCount > 0) {
                    mainHandler.post {
                        val doneMsg = "✓ 操作完成（共 $autoLoopStepCount 步）"
                        if (chatDialogView != null) appendMessageToDialog(isUser = false, text = doneMsg)
                        else showOrUpdateCompanionCardOnMain(doneMsg)
                        mainHandler.postDelayed({ sendProactiveAiMessage("followup") }, 300L)
                    }
                }
            } else {
                // Plan-and-Execute：当前步骤完成，推进到下一步
                agentPlanStepIndex++
                agentCurrentStepHistory.clear()
                recentStepDescs.clear()
                if (agentPlanStepIndex >= agentPlan.size) {
                    // 所有步骤全部完成
                    CompanionService._isAutoLooping.value = false
                    autoLoopJob = null
                    mainHandler.post {
                        val doneMsg = "✓ 任务完成（共 ${agentPlan.size} 步，$autoLoopStepCount 次操作）"
                        if (chatDialogView != null) appendMessageToDialog(isUser = false, text = doneMsg)
                        else showOrUpdateCompanionCardOnMain(doneMsg)
                        mainHandler.postDelayed({ sendProactiveAiMessage("followup") }, 300L)
                    }
                } else {
                    // 继续执行下一个计划步骤
                    val nextStep = agentPlan[agentPlanStepIndex]
                    Log.i(CompanionService.TAG, "agentLoopStep: 步骤 ${agentPlanStepIndex}/${agentPlan.size} → $nextStep")
                    mainHandler.post { showAgentLoopStatusCard(autoLoopStepCount) }
                    kotlinx.coroutines.delay(CompanionService.AGENT_LOOP_STEP_DELAY_MS)
                    if (CompanionService._isRunning.value && CompanionService._isAutoLooping.value) agentLoopStep()
                }
            }
        }
        else -> {
            // wait 动作：等待 lastWaitMs；其他动作：等待正常延迟后继续
            val delayMs = if (lastAgentActionType == "wait") {
                lastWaitMs.also { lastWaitMs = 0L }
            } else {
                CompanionService.AGENT_LOOP_STEP_DELAY_MS
            }
            kotlinx.coroutines.delay(delayMs)
            if (CompanionService._isRunning.value && CompanionService._isAutoLooping.value) agentLoopStep()
        }
    }
}

/** 在弹幕卡片顶部状态行显示当前循环步骤（不影响下方的角色发言行）。 */
internal fun CompanionService.showAgentLoopStatusCard(step: Int) {
    if (!CompanionService._isRunning.value) return
    val text = when {
        step == 0 -> "正在规划任务…"
        agentPlan.size > 1 -> {
            val planStep = agentPlan.getOrNull(agentPlanStepIndex)?.take(14)
            "步骤 ${agentPlanStepIndex + 1}/${agentPlan.size}：$planStep"
        }
        else -> "执行中… 第 $step 步"
    }
    updateAgentStatusLineOnMain(text)
}

/**
 * 更新弹幕卡片顶部的任务状态行（agent 模式专用）。
 * 若卡片尚未创建，则先创建空内容卡片再显示状态；
 * 若卡片已存在，仅更新状态行，不触碰下方的角色发言行。
 */
internal fun CompanionService.updateAgentStatusLineOnMain(statusText: String) {
    if (!CompanionService._isRunning.value) return
    if (currentCardView != null) {
        currentCardStatusTv?.text = statusText
        currentCardStatusTv?.visibility = View.VISIBLE
        currentCardContentTv?.text = ""
        autoHideRunnable?.let { mainHandler.removeCallbacks(it) }
        scheduleAutoHide()
    } else {
        // 卡片尚未创建：先用空内容占位创建卡片，再显示状态行
        showOrUpdateCompanionCardOnMain("")
        currentCardStatusTv?.text = statusText
        currentCardStatusTv?.visibility = View.VISIBLE
    }
}

// ── 截图变化检测（操作有效性判断）────────────────────────────────────────

/**
 * 将 Bitmap 缩放为 40×70 的微缩图（保持近似比例），用于低开销的前后界面对比。
 * 返回的是新 Bitmap，不影响原图，不 recycle 原图。
 */
internal fun CompanionService.createStepThumbnail(bmp: Bitmap): Bitmap =
    Bitmap.createScaledBitmap(bmp, 40, 70, false)

/**
 * 逐像素比较两张缩略图的 RGB 均值差。
 * 差值 < 12/255（均值）视为"界面基本未变化"，返回 true；否则返回 false。
 */
internal fun CompanionService.thumbnailsSimilar(a: Bitmap, b: Bitmap): Boolean {
    if (a.width != b.width || a.height != b.height) return false
    var totalDiff = 0L
    val total = a.width * a.height
    for (y in 0 until a.height) {
        for (x in 0 until a.width) {
            val ca = a.getPixel(x, y)
            val cb = b.getPixel(x, y)
            totalDiff += kotlin.math.abs(android.graphics.Color.red(ca)   - android.graphics.Color.red(cb))
            totalDiff += kotlin.math.abs(android.graphics.Color.green(ca) - android.graphics.Color.green(cb))
            totalDiff += kotlin.math.abs(android.graphics.Color.blue(ca)  - android.graphics.Color.blue(cb))
        }
    }
    return (totalDiff / (total * 3)) < 12L
}

/**
 * 触发 TTS 朗读。
 * 录音时也直接播放——硬件 AEC（VOICE_COMMUNICATION + AcousticEchoCanceler）负责消除回声，
 * 用户说新话时 sendUserText() 会先调 ttsBridge?.stop() 打断当前语音。
 * companionVoiceEnabled 为 false 时跳过 TTS，仅保留字幕。
 */
