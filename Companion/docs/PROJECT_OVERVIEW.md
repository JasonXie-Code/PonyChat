# 项目介绍

PonyChat Companion 是 PonyChat 的 Android 实体执行终端项目，目标是把云端 AI 的理解、规划和决策能力，与 Android 设备的界面观察、触控执行和硬件能力连接起来。

它与 **PonyChat App** 分工明确，但不是第二个面向用户的软件：

- **PonyChat App**：设备上唯一面向用户的交互产品，承载聊天、角色切换、个性设置和状态反馈。
- **PonyChat Companion**：预装进自研设备固件的系统级 Agent Runtime，负责观察、规划、执行和验证；默认没有桌面图标，也不向用户展示诊断页。

量产设备不会展示原生 Android 桌面，而由固件中的自定义 Launcher / Kiosk 界面承载 PonyChat 的展示内容。当前 `MainActivity` 仅为工程诊断入口，不声明 `MAIN/LAUNCHER`，需要通过开发工具显式启动。

Companion 通过受 `signature` 权限保护的 AIDL 服务向 PonyChat 提供版本化能力握手。设备操作能力要求包签名一致、AIDL 协议兼容，并且 Companion 是物理设备上的系统预装应用（或该系统应用的更新）；Debug 安装不豁免预装检查，模拟器不具备主机资格，也不启动 Companion 状态悬浮窗。手机版与主机版入口由系统镜像的 `device_home_enabled` 资源配置决定，普通模拟器使用手机版。量产时 PonyChat 与 Companion 必须使用同一产品证书签名。

> 当前状态：已在 K2B/H618（4 GB + 32 GB）Android 12 开发板跑通 64 位双 ABI、
> 系统级 Companion、无障碍与通知监听常驻、原生竖屏和 QQ 私聊板端闭环。2026-08-14
> 已开始实施无 Root `user` 量产基线、协议 4 受控诊断和正式 BSP 集成；签名 OTA、
> Recovery 维修流程、A/B 可靠性和长期稳定性仍是量产阻塞项。

## 项目目标

PonyChat Companion 希望建立一个与具体硬件无关的手机 Agent 闭环：

```text
用户任务
   ↓
PonyChat Cloud Brain
   ↓
观察 → 理解 → 决策 → 操作 → 验证 → 纠错
   ↓
Android DeviceAdapter
   ├── Accessibility / UI Tree
   ├── 坐标点击、滑动和输入
   ├── 截图与视觉定位
   └── Emulator / Android / H618
```

设计原则：

1. Agent 大脑和设备执行层分离。
2. 优先使用可靠的系统/UI API，坐标操作作为兼容层，视觉操作作为通用回退。
3. 每次动作后重新观察并验证结果，不把“动作已调用”视为“任务已完成”。
4. Runtime 必须具备最大步骤数、异常收敛和纠错反馈，避免无限操作。
5. 敏感动作在产品化前必须加入用户确认、允许列表、审计和急停机制。

## 已实现能力

### Agent Runtime

- `AgentTask`：任务描述与最大步骤数。
- `BrainClient`：云端或本地模型的决策接口。
- `DeviceAdapter`：模拟器、Android 和 H618 的统一设备接口。
- `ResultVerifier`：动作后的任务结果验证接口。
- `AgentRuntime`：观察、决策、执行、验证和纠错循环。
- `AgentOutcome`：完成、达到步骤上限和异常失败三种结果。
- 结构化步骤历史和运行事件日志。

### Android 执行层

- 读取当前窗口的 Accessibility UI Tree。
- 按 View ID、文字或无障碍描述查找并点击控件。
- 坐标点击与滑动。
- 输入文字。
- 返回和 Home 系统动作。
- 按包名启动已安装 App。
- `VisionLocator` 视觉定位扩展接口。

### 内部诊断与测试

- 内部诊断页显示控制服务连接状态和当前基础能力，不进入用户桌面或产品导航。
- 可跳转到系统无障碍设置。
- 内置无副作用的 Agent 闭环演示，不会操作其他 App。
- Runtime 单元测试覆盖正常完成、纠错、最大步骤数和设备异常。

## 尚需产品化

- PonyChat Cloud Brain 网络协议与认证。
- MediaProjection 或系统级截图。
- 云端/本地视觉模型和真实 `VisionLocator`。
- Windows Controller 只保留为工程救援工具；生产操作链路必须在设备内完成。
- 完整的敏感动作确认、App/动作允许列表和可导出的审计日志。
- 摄像头人脸识别、目光检测、麦克风与音频输出。
- 微信、游戏等更多第三方 App 的专项兼容；QQ 已完成首轮实机适配。
- K2B/H618 BSP 的量产签名、OTA、GPU、USB/HDMI、功耗和温控适配。

H618 无 Root 量产、受控诊断、BSP 集成和维修 Recovery 的实施基线见共享硬件库的
[H618_PRODUCTION_SECURITY.md](../../../Hardware/H618-K2B/docs/H618_PRODUCTION_SECURITY.md)。
2026-08-14 的 Companion/QQ 普通对话、角色隔离、无障碍、返回列表、Recovery 与 scrcpy
实机经验汇总见
[H618_COMPANION_QQ_LESSONS_2026-08-14.md](../../../Hardware/H618-K2B/docs/H618_COMPANION_QQ_LESSONS_2026-08-14.md)。

这些能力不能仅凭模拟器结果判断可用，必须在普通 Android 真机和 K2B/H618 上分别验证。

## 项目结构

```text
Companion/
├── app/
│   ├── src/main/java/top/ponychat/companion/
│   │   ├── agent/                 # 硬件无关 Agent Runtime
│   │   ├── android/               # Android DeviceAdapter 与无障碍服务
│   │   └── MainActivity.kt        # 基础控制和演示界面
│   ├── src/main/res/              # Manifest 配置、文字、主题和图标
│   └── src/test/                   # Runtime JVM 单元测试
├── docs/ARCHITECTURE.md            # 架构、开发阶段和硬件验证基线
├── build.gradle.kts
├── settings.gradle.kts
└── gradlew.bat
```

## 安全要求

接入真实云端模型或控制用户设备前，至少需要完成：

- 任务来源认证、请求签名和防重放。
- App、联系人、动作和数据范围允许列表。
- 发送消息、付款、删除、授权等敏感操作的用户确认。
- 屏幕上的明显运行状态和随时可用的紧急停止入口。
- 完整的任务、模型决策、动作和验证审计日志。
- 超时、最大步骤数、速率限制、失败熔断和网络断开保护。
- Token、密钥和用户数据的安全存储及最小化上传。

## 开发路线

### 阶段 1：模拟器

1. 定义 Cloud Brain API。
2. 接入截图与视觉定位器。
3. 完成 UI Tree、坐标和视觉回退的端到端任务。
4. 接入 AndroidWorld 或自建任务集进行自动回归。

### 阶段 2：普通 Android 真机

1. 验证 ARM 环境、真实触控、摄像头和麦克风。
2. 验证后台保活、息屏、系统杀进程与温度变化。
3. 验证常用第三方 App 的兼容性和安全确认流程。

### 阶段 3：K2B/H618

1. 实现 H618 `DeviceAdapter`。
2. 接入系统级 Input、Window、Audio 和 Camera 能力。
3. 验证 BSP/HAL、Mali GPU、USB/HDMI、内存、功耗和温控。
4. 执行长期运行和故障恢复测试。

完整设计与摄像头选型基线参见 [docs/ARCHITECTURE.md](ARCHITECTURE.md)。
