# Companion Mobile Controller

> 文档状态：2026-08-09 已复核。易变的版本、部署和服务状态在使用前仍需现场验证。

This host-side prototype uses [Mobile MCP](https://github.com/mobile-next/mobile-mcp)
as the device tool layer. Companion owns task parsing, safety rules, the QQ state
machine, model routing, and completion checks; it does not duplicate ADB/UI-dump
implementations already supplied by Mobile MCP.

## Run

```powershell
python -m companion_controller.cli --device emulator-5554 "帮我用QQ给张三发信息：你好"

# 从系统桌面使用默认浏览器搜索图片，经系统分享面板发送给唯一 QQ 联系人

python -m companion_controller.cli --device emulator-5554 `
  "Companion在浏览器里面搜索小马宝莉的小马“紫悦”的图片，并发给QQ的谢永鹏"

# 从系统桌面启动 Chrome、打开网站并保存验收截图

python -m companion_controller.cli --open-url https://yuelimei.cn --screenshot result.png

# 调试/旧版本救援：监听旧 Companion 私聊事件并通过 Mobile MCP 执行回复

python -m companion_controller.cli --device emulator-5554 --watch-qq-replies
```

当前 H618 Companion 的普通 QQ 私聊已经在设备内完成输入、发送和回读，不应在生产环境
启动 `--watch-qq-replies`。本 Controller 只作为显式启动的开发、诊断和恢复工具。

Chrome 工作流把设备操作和云端视觉验收分开报告。页面已打开而视觉模型暂时
不可用时返回 `completed_unverified`，不会把成功的手机操作误报为失败；截图仍会保留供人工核验。

Mobile MCP is launched as a child process with anonymous telemetry disabled and
with a sanitized environment that excludes PonyChat model API keys. Install or
allow `@mobilenext/mobile-mcp` before running the real-device command.
Android currently uses Mobile MCP's official legacy robot so UIAutomator exposes
the complete accessibility tree on Android 16 instead of a single root node.
Unicode input uses Mobile Next DeviceKit 1.2.4. Push the official release asset
to the emulator before running tasks that contain Chinese text:

QQ 自动回复同样复用 Mobile MCP。Android Companion 只负责新消息事件、角色与记忆、
私聊确认和用户打断；Controller 负责 UI Tree、语义定位、输入、发送、结果验证及恢复。
事件 ID 在设备端和 Controller 日志中双重去重，避免界面刷新导致重复发送。

QQ 私聊中的联网请求支持天气、普通网页、文章/资料、图片和视频。Controller 会让设备
浏览器真实打开 Google/Bing 搜索页，同时复用 PonyChat 后端的豆包联网搜索生成摘要；
天气额外使用 Open-Meteo 的结构化当前天气和三日预报。浏览器 UI 可读取的标题、云端
摘要、数据来源及完整搜索链接会合并后返回。图片请求继续走系统分享面板发送图片。
所有结果只允许发回原私聊发送者，不采用指令文字中提供的其他收件人。

```powershell
adb -s emulator-5554 push devicekit.dex /data/local/tmp/devicekit.dex
```

Pinned release asset SHA-256:
`e3f51fc1b5ef0f2adedda8dfe7f3a9eef7cfb9eda1d4e7eeb9504990a5d1990f`.

## 可迁移流程记忆

控制器把成功流程保存为语义步骤和环境变体，而不是保存绝对点击坐标。图片分享技能
通过系统默认浏览器打开图片搜索，按“图片结果 / 分享图片 / QQ / 精确联系人 /
图片预览 / 发送”等语义重新定位。成功后会在
`%LOCALAPPDATA%\PonyChat\Companion\procedure_memory.json` 中累计对应浏览器环境的
策略成功次数；换浏览器或系统界面时先走通用语义流程，成功后再形成独立环境变体。

联系人只命中一个精确结果或唯一的 `姓名@别名` 时会自动继续。多个候选时返回
`needs_contact_selection` 和 `contact_candidates`，并停留在 QQ 联系人列表，供
PonyChat 前台弹出选择框。用户选择后续办并记住小名：

```powershell
python -m companion_controller.cli --device emulator-5554 `
  --select-contact "王晓明@销售部" --remember-as "王总"
```

确认过的映射保存在
`%LOCALAPPDATA%\PonyChat\Companion\contact_aliases.json`。以后任务中的“王总”
会直接解析为该精确 QQ 联系人；如果联系人不再出现在当前列表，仍会停止而不会盲发。

## Test

```powershell
python -m unittest discover -s controller/tests -v
```
