# PonyChat Android App

> 文档状态：2026-09-09 更新运行入口与发布流程。易变的版本、部署和服务状态在使用前仍需现场验证。

原生 Android 应用（Jetpack Compose），用于 PonyChat 的登录、角色、聊天、Galgame / 锁分、陪玩、绘图、记忆与设置等核心功能。

普通对话现已统一使用聊天 Agent 和后台记忆整理 Agent，采用同一个版本化记忆库；设计与验收见 [Agent 记忆架构](../docs/design/普通对话Agent记忆架构.md)。

## 手机版与主机版：同一 App 按安装环境自动切换

本节定义由产品方于 2026-09-06 确认，后续开发、文档与测试统一使用以下名称：

- **手机版**：用户用自己的手机下载并安装 PonyChat App 时的形态。打开后进入普通角色/聊天列表，不显示 `PonyChat Device` 主机首屏。
- **主机版**：自研设备搭载 PonyChat App 时的形态。打开后显示主机大屏首屏，包含当前角色、时间、打开对话、切换角色和设备入口。
- **两者是同一个 App、同一个 APK**，不是两个产品或两个独立安装包，也不依赖用户手动选择手机版/主机版。App 根据安装环境自动切换。

自研设备系统镜像通过 Runtime Resource Overlay 将 `device_home_enabled` 覆盖为 `true`，启用 `DeviceHomeActivity` 的 HOME 入口，并标明主机安装环境。普通手机上该资源保持默认 `false`，使用手机版入口。只有连接到 Companion Runtime，不能据此把普通手机切成主机版；模拟器中安装 Companion 调试包也不改变这条规则。

Companion Runtime 的同签名、系统预装和协议检查决定设备操作能力是否可用，与手机版/主机版的环境判断分开。Runtime 维护、离线或协议不兼容时，自研设备仍保持主机首屏和聊天能力，相关设备操作入口按实际能力关闭。

验收时，普通手机或普通模拟器必须显示手机版首屏；自研设备镜像必须显示主机首屏。安装环境与首屏形态的验证，不能只用 Companion 是否在线代替。

> **最后更新日期**：2026-09-09
> 当前版本：`6.0.11` / `versionCode 389`

## 技术栈

- UI: Jetpack Compose + Material3
- 架构: ViewModel + Repository
- 网络: Retrofit + OkHttp（含 SSE 流式读取）
- 后台任务: WorkManager
- 图片: Coil
- 扫码: CameraX + ML Kit

## 近期实现要点

- 普通聊天历史以服务端消息表为权威，Android 发送请求时只带最新用户消息批次，后端会自动合并服务端历史。
- 普通聊天历史页使用服务端分页加载，首次加载和向前翻页分别由 `isLoadingHistory` / `isLoadingMoreHistory` 管理。
- 单条消息删除改为调用 `/api/messages/hide` 软隐藏，客户端会先本地移除，失败后恢复。
- 完成通知按 `message_id` 或 `outbox_id` 生成通知 ID，避免多段回复互相覆盖。
- 系统导航栏颜色由统一 effect 同步到聊天页、设置页等 Compose 页面。
- 中国象棋小游戏接入后端 `api/minigames/xiangqi/*`，支持角色化准备卡、执行回复、悔棋/投降、跨局记忆写回和本地 EleEye 走法候选。
- 斗地主小游戏为 Android 本地规则/AI 实现，支持叫地主、出牌、提示、得分、音效分组、手牌排序、四带二和队友协作策略；核心规则由 `DoudizhuPolicyTest` 覆盖。

## 主要目录

```
Android-App/
├── app/
│   ├── build.gradle.kts
│   ├── proguard-rules.pro
│   └── src/main/
│       ├── AndroidManifest.xml
│       ├── java/top/ponychat/webview/
│       │   ├── MainActivity.kt
│       │   ├── DeviceHomeActivity.kt
│       │   ├── AppNavigation.kt
│       │   ├── JobPollWorker.kt
│       │   ├── CompanionService.kt
│       │   ├── device/            # Companion Runtime 探测、签名校验和设备形态判断
│       │   ├── ui/device/         # 自研设备大屏首页
│       │   ├── ui/
│       │   │   ├── chinesechess/
│       │   │   ├── doudizhu/
│       │   ├── data/
│       │   └── ...
│       └── res/
├── signing/
└── icon-packs/
```

## 构建

### Android Studio

1. 打开 Android Studio
2. `File` -> `Open` 选择仓库中的 **`Android-App`** 目录
3. 等待 Gradle 同步
4. 运行 `app` 模块

### 命令行

在 **PonyChat 仓库** 下（`Android-App` 为工程根目录）：

```powershell
cd PonyChat\Android-App
.\gradlew.bat assembleDebug
```

本机可使用固定便携工具链构建，避免默认 Windows 临时目录下 Gradle daemon 的
`Unable to establish loopback connection` 启动错误：

```powershell
.\tools\build.ps1                             # 正式签名 Release
.\tools\build.ps1 -Tasks ':app:compileDebugKotlin'
.\tools\build.ps1 -Offline                    # 仅在依赖缓存齐全时使用
```

脚本为当前进程设置 `P:\Tools\jdk-17`、`P:\Tools\gradle-home` 与独立的
`P:\Tools\gradle-tmp`，退出后恢复原环境变量；不会修改系统环境或启动后端。

仅发布 APK 到本机（验证固定产品签名和版本，再原子更新最新指针）：

```powershell
..\.venv\Scripts\python.exe .\tools\publish_apk.py --publish
```

归档文件在 `Android-App/releases`，实际分发文件在 `P:\PonyChat\var\releases`。
发布回执写入版本 JSON；APK 不入 Git。`latest.json` 在完整文件 SHA-256 验证通过后才切换，
拒绝同版本不同内容或意外降级。后端无需重启，USA/CN 不上传或保存 APK。

官网 `/download/apk` 通过 USA 转发本机最新文件；App 更新下载地址为
`https://39.101.74.217/download/apk`。`--activate-download` 在本地模式兼容旧命令，
不再写服务器静态 APK alias。不要使用旧服务器发布/部署流程恢复 USA APK 文件。

Debug APK 输出路径：
`app\build\outputs\apk\debug\app-debug.apk`

Release 构建需要签名配置：`Android-App/signing/keystore.properties`，或设置 `PONYCHAT_RELEASE_STORE_FILE`、`PONYCHAT_RELEASE_STORE_PASSWORD`、`PONYCHAT_RELEASE_KEY_ALIAS`、`PONYCHAT_RELEASE_KEY_PASSWORD` 环境变量。公开证书及固定 SHA-256 指纹保存在 `product-signing/`；私钥和密码不得提交到 Git。Companion 默认复用同一份本地签名配置。

## 配置

- 应用名：`app/src/main/res/values/strings.xml`
- 正式连接：`https://39.101.74.217`（HTTPS，Server-CN 回环隧道到本机 5000）；升级时忽略旧生产域名偏好，显式调试地址仍可使用。
- 默认公网地址：`app/src/main/java/top/ponychat/webview/data/prefs/AppPreferences.kt` 中 `DEFAULT_WAN_URL`
- 当前版本号：`app/build.gradle.kts` 中 `versionName` / `versionCode`
- 服务端最低版本门槛：后端 `Backend/config.py` 中 `PONYCHAT_MIN_APP_VERSION_NAME`，当前默认 `5.3.0`

## 测试

```powershell
cd PonyChat\Android-App
.\gradlew.bat testDebugUnitTest
.\gradlew.bat :app:compileDebugKotlin
.\gradlew.bat :app:assembleDebug
```

小游戏规则改动至少运行相关单元测试：

```powershell
.\gradlew.bat testDebugUnitTest --tests "*DoudizhuPolicyTest" --tests "*ChineseChessPolicyTest"
```

## 许可证

MIT License
