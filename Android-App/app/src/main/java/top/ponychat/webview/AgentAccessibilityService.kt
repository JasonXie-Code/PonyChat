package top.ponychat.webview

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.graphics.Path
import android.os.Build
import android.os.Bundle
import android.os.SystemClock
import android.util.Log
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import androidx.annotation.RequiresApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * 操作陪玩无障碍服务。
 * 允许 AI 通过 [performTap] / [performSwipe] 向当前前台 App 注入手势，
 * 实现截图 → AI 决策 → 自动执行操作 的闭环代理流程。
 *
 * 使用前提：用户在「设置 → 无障碍」中手动开启 PonyChat 的操作陪玩服务。
 * 服务开启后 [isEnabled] 返回 true；停止后自动置 false。
 */
class AgentAccessibilityService : AccessibilityService() {

    companion object {
        private const val TAG = "AgentA11yService"

        @Volatile private var instance: AgentAccessibilityService? = null

        private val _isEnabled = MutableStateFlow(false)
        val isEnabled: StateFlow<Boolean> = _isEnabled.asStateFlow()

        /**
         * 在当前屏幕坐标 (x, y) 执行单次点击。
         * 坐标为真实像素值（相对屏幕左上角）。
         * 若服务未开启，静默忽略。
         */
        fun performTap(x: Float, y: Float) {
            if (Build.VERSION.SDK_INT < Build.VERSION_CODES.N) return
            instance?.doTap(x, y) ?: Log.w(TAG, "performTap skipped: service not running")
        }

        /**
         * 执行系统全局操作（返回桌面、返回上一级、查看多任务）。
         * [action] 取值："home" | "back" | "recents"
         */
        /**
         * 返回 true 表示系统接受了操作，false 表示失败（部分厂商 ROM 有兼容性问题）。
         */
        fun performSystemAction(action: String): Boolean {
            val svc = instance ?: run {
                Log.w(TAG, "performSystemAction skipped: service not running")
                return false
            }
            val code = when (action) {
                "home"    -> GLOBAL_ACTION_HOME
                "back"    -> GLOBAL_ACTION_BACK
                "recents" -> GLOBAL_ACTION_RECENTS
                else      -> { Log.w(TAG, "performSystemAction unknown action: $action"); return false }
            }
            val ok = svc.performGlobalAction(code)
            if (ok) Log.i(TAG, "system action ok: $action (code=$code)")
            else    Log.w(TAG, "system action FAILED (returned false): $action (code=$code) — may be a ROM compatibility issue")
            return ok
        }

        /**
         * 在当前屏幕坐标 (x, y) 执行长按（500ms）。
         * 用于触发右键菜单、选择文本、App 图标操作菜单等。
         */
        fun performLongPress(x: Float, y: Float) {
            if (Build.VERSION.SDK_INT < Build.VERSION_CODES.N) return
            instance?.doLongPress(x, y) ?: Log.w(TAG, "performLongPress skipped: service not running")
        }

        /**
         * 向当前获得输入焦点的文本框注入文本。
         * 会先尝试查找当前输入框/搜索框并自动聚焦，再执行 ACTION_SET_TEXT / PASTE。
         */
        fun performInputText(text: String): Boolean {
            return instance?.doInputText(text) ?: run {
                Log.w(TAG, "performInputText skipped: service not running")
                false
            }
        }

        /**
         * 执行滑动手势：从 (fromX, fromY) 滑到 (toX, toY)。
         * duration 单位毫秒，默认 400ms。
         */
        fun performSwipe(
            fromX: Float, fromY: Float,
            toX: Float, toY: Float,
            durationMs: Long = 400L
        ) {
            if (Build.VERSION.SDK_INT < Build.VERSION_CODES.N) return
            instance?.doSwipe(fromX, fromY, toX, toY, durationMs)
                ?: Log.w(TAG, "performSwipe skipped: service not running")
        }

        /**
         * 从无障碍树提取当前界面的可交互元素列表，格式 "[标签](归一化x,归一化y)"。
         * 供操作陪玩决策时辅助定位，提升坐标精度。
         * 若服务未开启或采集失败，返回空列表。
         */
        fun getInteractiveElements(screenW: Int, screenH: Int): List<String> {
            val svc = instance ?: return emptyList()
            return try {
                svc.buildElementsHint(screenW, screenH)
            } catch (e: Exception) {
                Log.w(TAG, "getInteractiveElements failed: ${e.message}")
                emptyList()
            }
        }
    }

    // ── 生命周期 ──────────────────────────────────────────────────────────────

    override fun onServiceConnected() {
        super.onServiceConnected()
        instance = this
        _isEnabled.value = true
        Log.i(TAG, "AgentAccessibilityService connected")
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        // 操作陪玩只需执行手势，不需要监听事件
    }

    override fun onInterrupt() {
        Log.w(TAG, "AgentAccessibilityService interrupted")
    }

    override fun onDestroy() {
        super.onDestroy()
        instance = null
        _isEnabled.value = false
        Log.i(TAG, "AgentAccessibilityService destroyed")
    }

    // ── 手势执行 ──────────────────────────────────────────────────────────────

    @RequiresApi(Build.VERSION_CODES.N)
    private fun doTap(x: Float, y: Float) {
        // lineTo(x+1, y) 让路径有非零长度，在部分设备上更可靠；120ms 满足图片相册等需稳定点击的场景
        val path = Path().apply {
            moveTo(x, y)
            lineTo(x + 1f, y)
        }
        val gesture = GestureDescription.Builder()
            .addStroke(GestureDescription.StrokeDescription(path, 0L, 120L))
            .build()
        dispatchGesture(gesture, object : GestureResultCallback() {
            override fun onCompleted(gestureDescription: GestureDescription?) {
                Log.d(TAG, "tap completed at ($x, $y)")
            }
            override fun onCancelled(gestureDescription: GestureDescription?) {
                Log.w(TAG, "tap cancelled at ($x, $y)")
            }
        }, null)
    }

    @RequiresApi(Build.VERSION_CODES.N)
    private fun doSwipe(
        fromX: Float, fromY: Float,
        toX: Float, toY: Float,
        durationMs: Long
    ) {
        val path = Path().apply {
            moveTo(fromX, fromY)
            lineTo(toX, toY)
        }
        val gesture = GestureDescription.Builder()
            .addStroke(GestureDescription.StrokeDescription(path, 0L, durationMs))
            .build()
        dispatchGesture(gesture, object : GestureResultCallback() {
            override fun onCompleted(gestureDescription: GestureDescription?) {
                Log.d(TAG, "swipe completed ($fromX,$fromY)→($toX,$toY)")
            }
            override fun onCancelled(gestureDescription: GestureDescription?) {
                Log.w(TAG, "swipe cancelled")
            }
        }, null)
    }

    @RequiresApi(Build.VERSION_CODES.N)
    private fun doLongPress(x: Float, y: Float) {
        // 标准长按阈值为 500ms；路径加 lineTo 保证非零长度
        val path = Path().apply {
            moveTo(x, y)
            lineTo(x + 1f, y)
        }
        val gesture = GestureDescription.Builder()
            .addStroke(GestureDescription.StrokeDescription(path, 0L, 600L))
            .build()
        dispatchGesture(gesture, object : GestureResultCallback() {
            override fun onCompleted(gestureDescription: GestureDescription?) {
                Log.d(TAG, "long_press completed at ($x, $y)")
            }
            override fun onCancelled(gestureDescription: GestureDescription?) {
                Log.w(TAG, "long_press cancelled at ($x, $y)")
            }
        }, null)
    }

    private fun doInputText(text: String): Boolean {
        // 优先向当前焦点输入框注入；若没有焦点，则遍历界面寻找搜索框/输入框后再重试。
        // rootInActiveWindow 只返回有"输入焦点"的窗口，有时目标 App 未抢到焦点会返回 null。
        // 此时降级为遍历 windows 列表（需要 flagRetrieveInteractiveWindows 权限），从所有可见窗口里找输入框。
        var root = rootInActiveWindow
        if (root == null) {
            Log.w(TAG, "doInputText: rootInActiveWindow == null, trying windows list")
            if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.LOLLIPOP) {
                val ownPkg = packageName?.toString() ?: "top.ponychat.webview"
                // 过滤：排除输入法窗口 + 排除 PonyChat 自身窗口（避免误写入自身对话框/搜索框）
                root = windows
                    ?.filter { w ->
                        w.type != android.view.accessibility.AccessibilityWindowInfo.TYPE_INPUT_METHOD
                    }
                    ?.mapNotNull { w -> w.root }
                    ?.filter { r -> r.packageName?.toString() != ownPkg }
                    ?.firstOrNull { r ->
                        val candidate = findInputCandidate(r)
                        if (candidate != null) { releaseAccessibilityNode(candidate); true } else false
                    }
                if (root != null) {
                    Log.i(TAG, "doInputText: found root via windows list, pkg=${root.packageName}")
                } else {
                    Log.w(TAG, "doInputText: no usable window found in windows list")
                    return false
                }
            } else {
                return false
            }
        }
        val rootPkg = root.packageName?.toString().orEmpty()
        val launcherSearchContext = isLikelyLauncherSearchContext(root)
        Log.i(TAG, "doInputText: pkg=$rootPkg launcherSearch=$launcherSearchContext")

        var focused = root.findFocus(AccessibilityNodeInfo.FOCUS_INPUT)
        if (focused == null || !isLikelyInputNode(focused)) {
            releaseAccessibilityNode(focused)
            focused = findInputCandidate(root)
            if (focused != null) {
                Log.i(TAG, "doInputText: found candidate input node, trying to focus/click first")
                focused.performAction(AccessibilityNodeInfo.ACTION_FOCUS)
                focused.performAction(AccessibilityNodeInfo.ACTION_CLICK)
                SystemClock.sleep(180L)
            } else if (launcherSearchContext && tapLauncherSearchFieldFallback()) {
                Log.i(TAG, "doInputText: no input node found, tapped top search field fallback")
                SystemClock.sleep(220L)
            } else {
                Log.w(TAG, "doInputText: no focused input node and no candidate found in tree")
            }
        }
        releaseAccessibilityNode(root)

        // 第一轮：重新取最新焦点节点，尝试 ACTION_SET_TEXT
        val root2 = rootInActiveWindow
        if (root2 != null) {
            var layoutRoot: AccessibilityNodeInfo? = root2
            var target = root2.findFocus(AccessibilityNodeInfo.FOCUS_INPUT)
            if (target == null || !isLikelyInputNode(target)) {
                releaseAccessibilityNode(target)
                target = findInputCandidate(root2)
                if (target == null && launcherSearchContext && tapLauncherSearchFieldFallback()) {
                    SystemClock.sleep(220L)
                    releaseAccessibilityNode(root2)
                    layoutRoot = rootInActiveWindow
                    val lr = layoutRoot
                    if (lr != null) {
                        target = lr.findFocus(AccessibilityNodeInfo.FOCUS_INPUT)
                        if (target == null || !isLikelyInputNode(target)) {
                            releaseAccessibilityNode(target)
                            target = findInputCandidate(lr)
                        }
                    }
                }
            }
            if (target != null) {
                val ok = trySetText(target, text)
                releaseAccessibilityNode(target)
                releaseAccessibilityNode(layoutRoot)
                if (ok) {
                    Log.i(TAG, "doInputText ok via ACTION_SET_TEXT: ${text.take(20)}")
                    return true
                }
                Log.w(TAG, "doInputText ACTION_SET_TEXT failed, trying clipboard paste fallback")
            } else {
                releaseAccessibilityNode(layoutRoot)
            }
        }

        // 第二轮：通过剪贴板粘贴（需要焦点在输入框上，若无焦点则继续尝试候选节点）
        try {
            val cm = getSystemService(CLIPBOARD_SERVICE) as android.content.ClipboardManager
            cm.setPrimaryClip(android.content.ClipData.newPlainText("agent_input", text))
            val root3 = rootInActiveWindow ?: return false
            var layoutRoot: AccessibilityNodeInfo = root3
            var target = layoutRoot.findFocus(AccessibilityNodeInfo.FOCUS_INPUT)
            if (target == null || !isLikelyInputNode(target)) {
                releaseAccessibilityNode(target)
                target = findInputCandidate(layoutRoot)
                if (target == null && launcherSearchContext && tapLauncherSearchFieldFallback()) {
                    SystemClock.sleep(220L)
                    releaseAccessibilityNode(layoutRoot)
                    layoutRoot = rootInActiveWindow ?: return false
                    target = layoutRoot.findFocus(AccessibilityNodeInfo.FOCUS_INPUT)
                        ?: findInputCandidate(layoutRoot)
                }
            }
            if (target != null) {
                // 优先直接 PASTE（保留当前焦点，避免 ACTION_CLICK 触发弹窗或重置）
                var ok = target.performAction(AccessibilityNodeInfo.ACTION_PASTE)
                if (!ok) {
                    // 若直接 PASTE 失败，再走 FOCUS + CLICK 重新获焦后重试
                    target.performAction(AccessibilityNodeInfo.ACTION_FOCUS)
                    target.performAction(AccessibilityNodeInfo.ACTION_CLICK)
                    SystemClock.sleep(180L)
                    ok = target.performAction(AccessibilityNodeInfo.ACTION_PASTE)
                }
                releaseAccessibilityNode(target)
                releaseAccessibilityNode(layoutRoot)
                if (ok) {
                    Log.i(TAG, "doInputText ok via clipboard paste: ${text.take(20)}")
                    return true
                }
            } else {
                releaseAccessibilityNode(layoutRoot)
            }
            Log.w(TAG, "doInputText clipboard paste failed: no usable input node accepted paste")
        } catch (e: Exception) {
            Log.e(TAG, "doInputText fallback failed: $e")
        }
        return false
    }

    private fun trySetText(node: AccessibilityNodeInfo, text: String): Boolean {
        node.performAction(AccessibilityNodeInfo.ACTION_FOCUS)
        node.performAction(AccessibilityNodeInfo.ACTION_CLICK)
        SystemClock.sleep(80L)
        val args = Bundle().apply {
            putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text)
        }
        val apiOk = node.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args)
        if (!apiOk) return false
        // 部分自定义 View（如 Pony 输入框）ACTION_SET_TEXT 返回 true 但文字实际未写入，需要验证
        SystemClock.sleep(100L)
        node.refresh()
        val actual = node.text?.toString() ?: ""
        if (actual.isBlank() && text.isNotBlank()) {
            Log.w(TAG, "trySetText: ACTION_SET_TEXT returned true but node.text is blank, treating as failure")
            return false
        }
        return true
    }

    private fun isLikelyInputNode(node: AccessibilityNodeInfo?): Boolean {
        if (node == null) return false
        val className = node.className?.toString()?.lowercase() ?: ""
        val viewId = node.viewIdResourceName?.lowercase() ?: ""
        val hint = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            node.hintText?.toString()?.lowercase() ?: ""
        } else ""
        val text = node.text?.toString()?.lowercase() ?: ""
        val desc = node.contentDescription?.toString()?.lowercase() ?: ""
        return node.isEditable ||
            "edittext" in className ||
            "searchview" in className ||
            "autocomplete" in className ||
            "input" in viewId ||
            "edit" in viewId ||
            "search" in viewId ||
            "搜索" in text ||
            "search" in text ||
            "搜索" in desc ||
            "search" in desc ||
            "搜索" in hint ||
            "search" in hint
    }

    /**
     * API 33（Tiramisu）起无障碍节点不再使用对象池，[AccessibilityNodeInfo.recycle] 在新系统上无效果；
     * 在更低版本上仍须 recycle 以归还池中实例（见官方文档）。
     */
    @Suppress("DEPRECATION")
    private fun releaseAccessibilityNode(node: AccessibilityNodeInfo?) {
        if (node == null) return
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) {
            node.recycle()
        }
    }

    /** API 33 起官方建议用拷贝构造替代已废弃的 [AccessibilityNodeInfo.obtain]。 */
    private fun copyAccessibilityNode(node: AccessibilityNodeInfo): AccessibilityNodeInfo =
        AccessibilityNodeInfo(node)

    private fun findInputCandidate(node: AccessibilityNodeInfo?): AccessibilityNodeInfo? {
        if (node == null) return null
        if (isLikelyInputNode(node)) return copyAccessibilityNode(node)
        for (i in 0 until node.childCount) {
            val child = node.getChild(i)
            val result = findInputCandidate(child)
            releaseAccessibilityNode(child)
            if (result != null) return result
        }
        return null
    }

    private fun isLikelyLauncherSearchContext(root: AccessibilityNodeInfo): Boolean {
        val pkg = root.packageName?.toString()?.lowercase().orEmpty()
        if ("miui.home" in pkg || "launcher" in pkg || "quicksearchbox" in pkg) return true
        return hasSearchLikeNode(root)
    }

    private fun hasSearchLikeNode(node: AccessibilityNodeInfo?): Boolean {
        if (node == null) return false
        val hint = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            node.hintText?.toString()?.lowercase() ?: ""
        } else ""
        val text = node.text?.toString()?.lowercase() ?: ""
        val desc = node.contentDescription?.toString()?.lowercase() ?: ""
        val looksLikeSearch = "搜索" in hint || "search" in hint ||
            "搜索" in text || "search" in text ||
            "搜索" in desc || "search" in desc
        if (looksLikeSearch) return true
        for (i in 0 until node.childCount) {
            val child = node.getChild(i)
            val found = hasSearchLikeNode(child)
            releaseAccessibilityNode(child)
            if (found) return true
        }
        return false
    }

    private fun tapLauncherSearchFieldFallback(): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.N) return false
        val metrics = resources.displayMetrics
        val tapX = metrics.widthPixels * 0.5f
        val tapY = metrics.heightPixels * 0.09f
        Log.i(TAG, "tapLauncherSearchFieldFallback: tap=($tapX,$tapY)")
        doTap(tapX, tapY)
        return true
    }

    // ── 无障碍树元素提取 ──────────────────────────────────────────────────────

    /**
     * 遍历当前界面的无障碍树，返回可交互元素列表，格式 "[标签](x,y)"（归一化坐标）。
     * 最多返回 20 个，仅采集有文字/描述且可点击/可聚焦的节点，剔除 PonyChat 自身窗口。
     */
    private fun buildElementsHint(screenW: Int, screenH: Int): List<String> {
        if (screenW <= 0 || screenH <= 0) return emptyList()
        val root = rootInActiveWindow ?: return emptyList()
        val result = mutableListOf<String>()
        try {
            collectClickableNodes(root, screenW, screenH, result)
        } finally {
            releaseAccessibilityNode(root)
        }
        return result
    }

    private fun collectClickableNodes(
        node: AccessibilityNodeInfo,
        screenW: Int,
        screenH: Int,
        result: MutableList<String>,
        depth: Int = 0
    ) {
        if (!node.isVisibleToUser || result.size >= 20 || depth > 14) return
        val ownPkg = packageName?.toString() ?: "top.ponychat.webview"
        if (node.packageName?.toString() == ownPkg) return  // 跳过 PonyChat 自身控件

        val text = node.text?.toString()?.trim().orEmpty()
        val desc = node.contentDescription?.toString()?.trim().orEmpty()
        val label = (if (text.isNotEmpty()) text else desc).take(18)
        if (label.isNotEmpty() && (node.isClickable || node.isCheckable || node.isFocusable)) {
            val bounds = android.graphics.Rect()
            node.getBoundsInScreen(bounds)
            if (bounds.width() > 8 && bounds.height() > 8) {
                val cx = "%.2f".format(bounds.centerX().toFloat() / screenW)
                val cy = "%.2f".format(bounds.centerY().toFloat() / screenH)
                result.add("[$label]($cx,$cy)")
            }
        }
        for (i in 0 until node.childCount) {
            val child = node.getChild(i) ?: continue
            collectClickableNodes(child, screenW, screenH, result, depth + 1)
            releaseAccessibilityNode(child)
        }
    }
}
