# 操作手册

本文面向 Companion 的日常开发、构建、安装和功能验证。H618 固件、显示、服务常驻或 QQ UI 兼容问题请转到共享硬件库的 [H618 实机排障手册](../../../Hardware/H618-K2B/docs/H618_TROUBLESHOOTING.md)。

## 开发环境

- Windows、Linux 或 macOS。
- JDK 17。
- Android SDK 34。
- Android Studio，或直接使用项目自带 Gradle Wrapper。
- Android 7.0（API 24）及以上的模拟器或设备。
- 真机调试时需要启用开发者选项和 USB 调试。

在项目根目录创建不纳入 Git 的 `local.properties`：

```properties
sdk.dir=P:/Tools/android-sdk
```

请根据本机 Android SDK 的实际路径修改。
## 构建与测试

进入项目目录：

```powershell
cd P:\PonyChat\Companion
```

运行单元测试、Android Lint 和 Debug 构建：

```powershell
.\gradlew.bat testDebugUnitTest
.\gradlew.bat lintDebug
.\gradlew.bat assembleDebug
```

也可以一次完成主要验证：

```powershell
.\gradlew.bat clean testDebugUnitTest lintDebug assembleDebug
```

APK 输出位置：

```text
app/build/outputs/apk/debug/app-debug.apk
```

Release 构建会优先读取 `Companion/signing/keystore.properties`，否则自动复用
`Android-App/signing/keystore.properties`，确保 PonyChat App 与 Companion 使用同一产品证书。
也可设置 `PONYCHAT_RELEASE_*` 环境变量。公开 PEM 证书及固定 SHA-256 指纹保存在
`product-signing/`；私钥和密码由 Git 忽略。
## 安装与运行

确认模拟器或设备已经连接：

```powershell
adb devices
```

安装后通过开发命令显式启动内部诊断页：

```powershell
adb install -r .\app\build\outputs\apk\debug\app-debug.apk
adb shell am start -n top.ponychat.companion/.MainActivity
```

开发验证：

1. 点击“打开无障碍服务设置”。
2. 在系统设置中启用 **PonyChat Companion 控制服务**。
3. 返回应用，确认状态显示“控制服务：已连接”。
4. 点击“运行 Agent 闭环演示”验证基础 Runtime。

无障碍服务拥有读取界面和执行操作的能力，只应在开发模拟器或明确授权的测试设备上启用。
## 核心接口示例

```kotlin
val runtime = AgentRuntime(
    brain = brainClient,
    device = AndroidDeviceAdapter(context),
    verifier = resultVerifier,
)

val outcome = runtime.run(
    AgentTask(
        id = "check-messages",
        instruction = "检查是否有新消息",
        maxSteps = 8,
    ),
)
```

`BrainClient` 不应直接调用 Android API；它只根据 `Observation` 返回结构化的 `AgentAction`。Android 细节由 `DeviceAdapter` 负责。
## QQ 消息自动化原型

`controller/` 已接入 Mobile MCP 作为模型无关的设备工具层，复用其 App
发现/启动、UI 树、点击、文本输入、按键和截图能力。QQ 发消息使用确定性状态机：

1. 启动 `com.tencent.mobileqq`，若识别到登录页则返回 `needs_login`。
2. 打开搜索、输入联系人，只接受唯一的精确匹配，防止误发。
3. 进入会话、填入消息、点击发送，再从 UI 树中回读消息验证完成。

运行示例：

```powershell
$env:PYTHONPATH = "P:\PonyChat\Companion\controller"
python -m companion_controller.cli --device emulator-5554 "帮我用QQ给张三发信息：你好"
```

模型路由固定为：普通文本规划和 UI 树决策使用 `deepseek-v4-flash`；只有
截图识别或显式高难度推理使用 `doubao-seed-2-1-pro-260628`。
Mobile MCP 子进程强制关闭匿名遥测，并使用白名单净化的环境变量，不继承 PonyChat 的模型 API 密钥。
## 系统悬浮状态窗

Runtime 提供常驻的 70% 不透明状态窗，展示任务目标、当前阶段、动作和验证结果，不展示模型隐藏思维链。

- 只在 PonyChat 以外的 App 前台时显示；PonyChat 的登录、聊天、设置和设备主页内全部隐藏。
- 标题栏可拖动，位置持久化。Companion 注入点击或滑动时按单个动作申请触摸穿透租约，不会挡住下层 App。
- 检测到用户触摸时立即暂停 Agent，并显示“继续”和“停止”。继续后重新观察界面，停止则结束任务。
- 设备主页固定竖屏并复用 PonyChat Logo。登录页的设备主页图标只在可信、协议兼容且已预装的 Runtime 上显示。
## QQ 角色私聊回复

Runtime 可读取 QQ 通知并把已确认的私聊文本交给 PonyChat 当前角色会话。账号、鉴权和当前
`character_id` 由 PonyChat 通过 signature 权限保护的 AIDL 同步，鉴权只保存在 Runtime 进程内存中。

- 外部聊天文字统一调用 `/api/chat` 的 `mode=normal`，与 PonyChat App 普通对话使用同一套
  上下文、导演、记忆、事实判断、主回复、消息落库和分段显示协议；`/api/companion/frame`
  只用于看屏陪伴，不再用于 QQ 等聊天软件的角色私聊。
- 会话隔离边界固定为 `PonyChat username + character_id`。外部聊天软件的联系人、包名和
  会话标题只用于确认回复目标，不写入模型上下文，也不创建独立角色会话。切换角色后，
  后续外部消息只会续接新角色在 PonyChat 中唯一的普通对话和该角色自己的记忆。
- 外部渠道只上传本轮用户消息。后端先把它追加到当前角色的权威普通对话，再从数据库重建
  完整历史，避免旧客户端消息列表覆盖服务器记录。用户消息和每个角色回复段都会出现在
  PonyChat App 对应角色的聊天记录中；不同角色之间不会串话。
- 普通模式返回的 `assistant_paragraph` 按 `display_delay_ms` 逐条发送到 QQ，回复内容与
  PonyChat 中落库的段落保持一致，不通过额外文本清洗改写。
- 所有回复段发送并回读成功后，Runtime 会点击聊天页语义返回按钮并确认消息输入框已经消失，
  将 QQ 留在会话列表；若软键盘或临时面板拦截返回，最多再执行一次返回，但不会继续退到桌面。
  这样其他联系人的未读条目仍可被前台扫描，后续通知也不会叠加打开成半屏聊天页。
- 返回列表逻辑按聊天软件配置复用：QQ 已接入生产回复链路；微信配置采用“可编辑输入框 +
  语义返回按钮”识别，以便后续微信发送控制器接入时不依赖易变资源 ID。当前版本尚未实现
  微信自动回复本身。
- 只有通知明确标记 `isGroupConversation=false` 且提供安全 `RemoteInput` 回复动作时才发送。
- 群聊、带 conversation title 的通知、无法确认类型的通知和没有安全回复动作的通知全部跳过。
- QQ 事件仍按发送者、正文和通知时间去重以避免重复发送，但发送者身份不参与角色会话和记忆键。

## 实机回归

H618 完整回归项目见共享硬件库的 [H618 实机排障手册：一次完整实机回归的最小清单](../../../Hardware/H618-K2B/docs/H618_TROUBLESHOOTING.md#一次完整实机回归的最小清单)。量产安全、签名与 OTA 验收见 [H618 无 Root 量产安全基线](../../../Hardware/H618-K2B/docs/H618_PRODUCTION_SECURITY.md)。
