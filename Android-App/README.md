# PonyChat Android App

原生 Android 应用（Jetpack Compose），用于 PonyChat 的登录、角色、聊天、Galgame / 锁分、陪玩、绘图、记忆与设置等核心功能。

> **最后更新日期**：2026-07-05
> 当前版本：`5.6.13` / `versionCode 353`

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
│       │   ├── AppNavigation.kt
│       │   ├── JobPollWorker.kt
│       │   ├── CompanionService.kt
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

Debug APK 输出路径：
`app\build\outputs\apk\debug\app-debug.apk`

Release 构建需要签名配置：`Android-App/signing/keystore.properties`，或设置 `PONYCHAT_RELEASE_STORE_FILE`、`PONYCHAT_RELEASE_STORE_PASSWORD`、`PONYCHAT_RELEASE_KEY_ALIAS`、`PONYCHAT_RELEASE_KEY_PASSWORD` 环境变量。

## 配置

- 应用名：`app/src/main/res/values/strings.xml`
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
