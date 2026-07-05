# 键盘适配流程分析 (v2.1)

## 📊 数据流向图

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                            用户点击输入框                                        │
└─────────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                     Android 系统弹出虚拟键盘                                      │
│                                                                                 │
│   系统触发 WindowInsetsAnimation（键盘动画）                                      │
└─────────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│               MainActivity.kt: setupKeyboardAnimationSync()                     │
│  ┌────────────────────────────────────────────────────────────────────────────┐ │
│  │  WindowInsetsAnimationCompat.Callback                                      │ │
│  │                                                                            │ │
│  │  onProgress() - 每帧回调:                                                  │ │
│  │    1. 获取 imeInsets.bottom (物理像素)                                     │ │
│  │    2. cssKeyboardHeight = imeHeight / density                              │ │
│  │    3. 调用 injectKeyboardHeightRealtime(cssKeyboardHeight)                 │ │
│  │                                                                            │ │
│  │  ❌ [v2.1 已移除] webView.setPadding(0, 0, 0, imeHeight)                   │ │
│  │                                                                            │ │
│  │  onEnd() - 动画结束回调:                                                   │ │
│  │    1. 获取最终 imeHeight                                                   │ │
│  │    2. 调用 injectKeyboardStateToWebView(cssKeyboardHeight, isVisible)      │ │
│  │                                                                            │ │
│  │  ❌ [v2.1 已移除] webView.setPadding(0, 0, 0, imeHeight)                   │ │
│  └────────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────────┘
                                      │
            ┌─────────────────────────┴─────────────────────────┐
            │                                                   │
            ▼                                                   ▼
┌──────────────────────────────────┐       ┌──────────────────────────────────────┐
│  injectKeyboardHeightRealtime()  │       │    injectKeyboardStateToWebView()    │
│                                  │       │                                      │
│  实时注入 CSS 变量:               │       │  完整注入:                           │
│  --keyboard-height: ${xxx}px     │       │  1. window._keyboardHeight = xxx     │
│                                  │       │  2. window._keyboardVisible = bool   │
│  ⚡ 每帧调用，无状态变化           │       │  3. --keyboard-height: ${xxx}px      │
│                                  │       │  4. 触发 'android-keyboard-change'   │
└──────────────────────────────────┘       │     自定义事件                       │
            │                              └──────────────────────────────────────┘
            │                                                   │
            └─────────────────────────┬─────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           CSS 层响应 (chat.css)                                  │
│                                                                                 │
│   .chat-input-area {                                                            │
│       position: absolute;                                                       │
│       bottom: max(0px, var(--keyboard-height, 0px));  ← 🔑 核心定位              │
│   }                                                                             │
│                                                                                 │
│   .chat-messages {                                                              │
│       padding-bottom: calc(180px + var(--keyboard-height, 0px));  ← 消息区适配  │
│   }                                                                             │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                    JS 层响应 (mobile-keyboard.js)                                │
│                                                                                 │
│   监听 'android-keyboard-change' 事件:                                          │
│     1. 更新 androidKeyboardHeight 变量                                          │
│     2. 如果在模态框/面板内的输入框，调用 handleModalInput/handlePanelInput       │
│     3. 主聊天输入框：滚动 chat-container 到底部                                  │
│     4. 键盘收起时：主动 blur 输入框，恢复容器位置                                 │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 🔴 修复前：双重偏移问题

```
键盘弹出时的偏移计算（修复前）:

 Android 原生层                     CSS 层
      │                               │
      ▼                               ▼
webView.setPadding(bottom=imeHeight)  +  .chat-input-area { bottom: var(--keyboard-height) }
      │                               │
      └───────────┬───────────────────┘
                  │
                  ▼
           输入框总偏移 = imeHeight + cssKeyboardHeight
                     ≈ 2 × 键盘高度  ❌ 过度上浮！
```

**问题原因**:
- `webView.setPadding(0, 0, 0, imeHeight)` 会把**整个 WebView 内容区域**往上推
- 同时 CSS `bottom: var(--keyboard-height)` 又把 `.chat-input-area` **再次上移**
- 两者叠加导致输入框上移了约 2 倍键盘高度

**为什么小米13正常但小米15异常？**
- 不同设备的 Android 版本、MIUI 版本对 `WindowInsetsAnimation` 的处理可能存在差异
- 某些设备可能已经在系统层面做了部分适配，导致 padding 效果不明显
- 小米15 可能使用了更新的 Insets 处理方式，使得双重偏移更明显

---

## 🟢 修复后：单一偏移机制

```
键盘弹出时的偏移计算（修复后）:

 Android 原生层                     CSS 层
      │                               │
      ▼                               ▼
   [不再设置 padding]              .chat-input-area { bottom: var(--keyboard-height) }
                                      │
                                      ▼
                           输入框总偏移 = cssKeyboardHeight
                                  = 正确的键盘高度 ✅
```

**修复策略**:
1. **移除所有 `webView.setPadding()` 调用**
2. **只依赖 CSS 变量 `--keyboard-height`** 统一控制布局
3. 增加设备信息日志便于后续调试

---

## 📋 修改文件清单

| 文件 | 行号 | 修改内容 |
|------|------|----------|
| `MainActivity.kt` | 160-161 | 注释掉 `onProgress()` 中的 `webView.setPadding()` |
| `MainActivity.kt` | 180-181 | 注释掉 `onEnd()` 中的 `webView.setPadding()` |
| `MainActivity.kt` | 246-248 | 注释掉 `setupKeyboardWorkaround()` 中的 `webView.setPadding()` |
| `MainActivity.kt` | 143-146 | 新增设备信息日志 |
| `mobile-keyboard.js` | 180-187 | 增强键盘状态日志 |
| `index.html` | 1232 | 更新版本号 `PATCH35` → `PATCH36` |

---

## ⚠️ 潜在风险点检查

### 1. ✅ `.chat-messages` padding-bottom
```css
padding-bottom: calc(180px + var(--keyboard-height, 0px));
```
- **结论**: 正确，使用 CSS 变量，不依赖 WebView padding

### 2. ✅ `.chat-input-area` bottom
```css
bottom: max(0px, var(--keyboard-height, 0px));
```
- **结论**: 正确，使用 `max()` 确保不会有负值

### 3. ✅ 其他 CSS 使用 `--keyboard-height` 的地方
检查了 `settings.css`, `modal.css`, `auth.css`，都只使用 CSS 变量，与 WebView padding 无关

### 4. ⚠️ 键盘收起时 `--keyboard-height` 会被设为 0
```kotlin
// onEnd() 中:
injectKeyboardStateToWebView(cssKeyboardHeight, isImeVisible)  // cssKeyboardHeight = 0 when hidden
```
- **结论**: 正确，键盘隐藏时 CSS 变量会被设为 0px，输入框回归原位

### 5. ⚠️ setupKeyboardWorkaround() 是否还在使用？
```kotlin
// onCreate() 中只调用了:
setupKeyboardAnimationSync()  // ← 主要方法

// setupKeyboardWorkaround() 未被调用，仅作为备用
```
- **结论**: 安全，该方法未被主动调用，已修改其中的 padding 代码以防万一

---

## 🧪 测试验证步骤

1. **重新编译 APK**:
   ```powershell
   cd e:\2026.1.18_RolePlay\App
   .\gradlew.bat assembleDebug
   ```

2. **安装到小米15并测试**:
   - 打开聊天界面
   - 点击输入框，观察输入框是否正确定位在键盘上方
   - 检查消息列表是否可以正常滚动
   - 打开设置/模态框，测试其中的输入框

3. **查看 Logcat 日志**:
   ```
   adb logcat -s Keyboard
   ```
   预期看到:
   ```
   I/Keyboard: Device: Xiaomi 2503ALN69C, Android 15.0 (API 35), density=3.0
   D/Keyboard: Animation ended: visible=true, imeHeight=1008px (physical), cssHeight=336px (css)
   ```

4. **查看浏览器控制台**:
   预期看到:
   ```
   📱 [键盘适配] Android 键盘状态: { visible: true, height: "336px", viewportHeight: "800px", ... }
   ```
