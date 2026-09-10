# 架构与验证基线

> 文档状态：2026-08-13 已复核。K2B/H618 已完成 Android 12、系统应用常驻、原生竖屏和 QQ 私聊板端闭环，并开始实施无 Root `user` 量产、协议 4 受控诊断与独立维修环境；本文的“后续工作”仍表示量产缺口。

## 分层

```text
Cloud PonyChat Brain
        │ 任务 / 决策 / 验证反馈
        ▼
Hardware-independent Agent Runtime
        │ observe / execute
        ▼
DeviceAdapter
   ┌────┴──────────┐
Emulator/Android   H618/K2B
Adapter            Adapter
```

Runtime 不引用 Android API；同一个 Brain 和任务循环可用于 JVM 单元测试、Android 模拟器、普通手机和未来的 H618/K2B。`DeviceAdapter` 负责抹平设备差异。

## 量产设备应用边界

```text
用户
  │
  ▼
PonyChat App / 自定义设备界面（唯一可见入口）
  │ 当前 character_id、任务、确认结果
  ▼
Companion Runtime（系统镜像内置，无桌面入口）
  │ 统一工具协议
  ▼
Android Framework / Accessibility / Input / Window / Audio / Camera
```

- PonyChat App 管理角色、个性、聊天历史、用户确认和可见状态。
- Companion Runtime 管理设备观察、操作、验证、审计和失败恢复，不提供独立用户产品界面。
- 不同角色用 `username + character_id` 隔离会话和长期记忆；设备工具、权限和安全策略由所有角色共享。
- 切换角色前必须同步结束旧角色会话并确认记忆落库，随后才能清空当前显示上下文并启用新角色。
- 量产镜像由自定义 Launcher / Kiosk 界面替代原生桌面；平台签名、`/system` 或 `/product` 预装、开机拉起与系统权限授予属于 BSP/固件集成，不在普通 Debug APK 中伪装实现。

PonyChat 本身保持单 APK。普通手机和自研设备的区别由运行时能力握手决定，而不是两个 Gradle 产品变体：

1. PonyChat 显式绑定 `top.ponychat.companion` 的 AIDL 能力服务。
2. Android `signature` 权限与客户端二次签名比对共同阻止伪造 Runtime。
3. Runtime 返回协议版本、运行版本和系统预装状态。
4. 只有可信且协议兼容的 Runtime 才开放设备操作；异常时保留大屏和聊天，但关闭执行入口。
5. 同一 APK 内的 `DeviceHomeActivity` 默认禁用，由量产系统 RRO 启用并设置为 HOME。
6. PonyChat 前台时通过可信 AIDL 隐藏 Runtime 状态悬浮窗；离开 PonyChat 后恢复。设备主页固定竖屏。

量产运行与维修严格分离：正常系统使用 `user`、`ro.debuggable=0`、无 `su`，Companion
通过 privileged 权限白名单获得最小系统能力；只读诊断和服务授权修复由签名保护的协议 4
AIDL 提供。分区修复和 root ADB 只允许在独立 OEM 签名 Recovery 中使用。完整实施和验收
基线见共享硬件库的 [H618_PRODUCTION_SECURITY.md](../../../Hardware/H618-K2B/docs/H618_PRODUCTION_SECURITY.md)。

## Agent 闭环

每一步固定执行：

1. 观察前台 App、Accessibility UI Tree 和可用截图。
2. Brain 根据任务、观察、历史步骤和上一次验证反馈作出决策。
3. DeviceAdapter 执行动作。
4. 再次观察，不以“动作调用成功”代替“任务成功”。
5. Verifier 判断是否完成，并把失败原因交回下一轮纠错。
6. 达到 `maxSteps` 后安全停止，避免无限操作。

## 三层操作能力

| 层 | 当前基础 | 后续工作 |
|---|---|---|
| 系统/UI API | Accessibility UI Tree、语义点击、输入、返回、Home、App 启动 | UiAutomator、系统级 Input/Window API |
| 坐标操作 | 点击和滑动 | 长按、多点手势、分辨率/旋转坐标映射 |
| 视觉操作 | `VisionLocator` 接口与视觉目标回退路径 | MediaProjection/系统截图、云端或本地视觉模型 |

## 开发与验证阶段

### 阶段 1：Android 模拟器

优先完成 Brain → Screenshot/UI Tree → Understand → Action → Verify 闭环。任务规划、App 启动/切换、UI Tree、点击/滑动/输入和大部分视觉逻辑都应在此阶段开发和自动测试。

### 阶段 2：普通 Android 手机（最好具备开发权限）

验证真实 ARM 环境、触控、摄像头、麦克风、微信/QQ/游戏兼容、后台保活、系统杀进程和息屏行为。模拟器通过不代表真机通过。

### 阶段 3：K2B / H618（首轮实机闭环已完成）

当前已验证 64 位双 ABI Android 12、系统应用预装与常驻、Accessibility/通知监听、原生竖屏、QQ 私聊、主机侧工程 Controller、四路 sysfs 温度和 Mali busy/idle 占用率。当前测试板仍依赖 `su 0` 读取受保护指标，只能作为 userdebug 工程板；Thermal HAL 注册和 B 槽启动尚未解决。量产固件改为无 Root `user`，监看和诊断必须迁移到正式 HAL、受控 Binder 诊断及 Recovery 维修流程。Android Framework、正式 HAL/VTS、USB/HDMI、功耗、量产 OTA 与长期稳定性仍需按签名量产镜像继续验证。详细实机命令和故障记录见共享硬件库的 [H618 实机排障手册](../../../Hardware/H618-K2B/docs/H618_TROUBLESHOOTING.md)。

## 摄像头基线

桌面 Companion 的常见人机距离约为 40–100 cm，第一版优先采用稳定定焦方案：

- 1080p / 2–5 MP；
- 70–90° FOV；
- 最佳对焦针对约 50–100 cm；
- 目标景深约 40 cm–1.5 m；
- 供应商样品需在 40 cm、60 cm、80 cm 和 1 m 验证人脸关键点与目光检测稳定性。

只有设备需要覆盖约 20 cm–2/3 m 的大距离变化，或要近拍物品、二维码和文字时，才优先考虑自动对焦。最终清晰度、USB 摄像头兼容和 ISP/性能必须在 K2B 真机验证。

## 上线前安全门槛

当前项目只适合测试设备。连接真实云端 Brain 前至少需要：

- App/动作允许列表和任务权限范围；
- 发消息、付款、删除、授权等敏感动作的用户确认；
- 可见的运行状态、完整审计日志和一键急停；
- 云端认证、请求签名、防重放和密钥安全存储；
- 任务超时、最大步骤数、失败熔断与速率限制。
