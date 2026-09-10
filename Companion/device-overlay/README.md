# PonyChat device RRO

> 文档状态：2026-08-09 已复核。易变的版本、部署和服务状态在使用前仍需现场验证。

这是自研设备系统镜像使用的 Runtime Resource Overlay 示例，不是第二个 PonyChat App。

量产 BSP 将该 overlay 作为静态系统资源包放入 `/product/overlay`（或对应产品分区），并使用与 PonyChat 兼容的产品签名。它只把同一 PonyChat APK 中的 `device_home_enabled` 从 `false` 覆盖为 `true`，从而启用 `DeviceHomeActivity` 的 HOME 入口。

普通手机没有这个系统 overlay，因此相同 APK 的 HOME Activity 保持禁用，不会参与桌面应用选择。

## 手机版与主机版定义（2026-09-06 确认）

手机版指用户用自己的手机下载 App 的形态；主机版指自研设备搭载 App 的形态。它们是同一个 PonyChat App，由安装环境自动切换，不分别发布两个 APK，也不要求用户手动选择版本。

本 overlay 同时提供自研设备的环境标记。`device_home_enabled=true` 时使用主机首屏；普通手机保持 `false`，打开后进入角色/聊天列表。安装或连接 Companion Runtime 本身不能触发手机变成主机版；Runtime 故障也不应让自研设备退回手机版首屏。

完整产品与界面定义见 [Android App 文档](../../Android-App/README.md)。
