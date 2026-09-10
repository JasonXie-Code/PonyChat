# PonyChat Companion

PonyChat Companion 是预装进自研 Android 设备固件的系统级 Agent Runtime，负责把 PonyChat 的云端理解与决策连接到设备观察、操作、验证和纠错能力。面向用户的聊天、角色和设置仍由 PonyChat App 承载。

当前已在 K2B/H618 Android 12 开发板跑通 64 位双 ABI、系统级 Companion、无障碍与通知监听常驻、原生竖屏和 QQ 私聊板端闭环。签名 OTA、Recovery 维修流程、A/B 可靠性和长期稳定性仍是量产阻塞项。

## 文档导航

| 文档 | 用途 |
| --- | --- |
| [项目介绍](docs/PROJECT_OVERVIEW.md) | 产品定位、目标、已实现能力、项目结构、安全要求和开发路线 |
| [操作手册](docs/OPERATIONS_GUIDE.md) | 开发环境、构建测试、安装运行、QQ、悬浮窗和角色回复操作 |
| [H618 实机排障手册](../../Hardware/H618-K2B/docs/H618_TROUBLESHOOTING.md) | 固件基线、服务常驻、竖屏、scrcpy、QQ UI、ANR、重复回复和故障恢复（共享硬件库） |
| [架构设计](docs/ARCHITECTURE.md) | 分层架构、接口边界和硬件验证基线 |
| [H618 量产安全基线](../../Hardware/H618-K2B/docs/H618_PRODUCTION_SECURITY.md) | 无 Root user 固件、签名、受控诊断、BSP、Recovery 和 OTA（共享硬件库） |
| [2026-08-14 实机闭环经验](../../Hardware/H618-K2B/docs/H618_COMPANION_QQ_LESSONS_2026-08-14.md) | Companion、QQ、角色会话、Recovery 与 scrcpy 的日期化工程决策（共享硬件库） |
| [Controller 手册](controller/README.md) | Windows 工程救援工具与复杂工作流实验 |
| [验收清单](验收清单.md) | Companion 功能、安全和发布门槛 |

## 快速开始

准备 JDK 17、Android SDK 34 和 Android 7.0（API 24）及以上的模拟器或设备，在本目录配置未纳入 Git 的 `local.properties`：

```properties
sdk.dir=P:/Tools/android-sdk
```

运行主要验证：

```powershell
.\gradlew.bat clean testDebugUnitTest lintDebug assembleDebug
```

安装 Debug APK 并显式打开内部诊断页：

```powershell
adb install -r .\app\build\outputs\apk\debug\app-debug.apk
adb shell am start -n top.ponychat.companion/.MainActivity
```

更完整的环境、签名、服务授权和验证步骤见 [操作手册](docs/OPERATIONS_GUIDE.md)。

## 安全提醒

Companion 的无障碍、通知监听和系统控制能力只应在明确授权的测试设备或正式受控产品中启用。接入真实设备前必须落实任务认证、允许列表、敏感操作确认、可见运行状态、急停、审计、超时和失败熔断；量产镜像不得沿用工程 Root、test-keys 或默认开放 ADB 的配置。

## 许可证

本目录遵循 PonyChat 仓库根目录中的 `LICENSE`，引入第三方代码、模型或数据集时必须同时保留并审核其各自许可证。
