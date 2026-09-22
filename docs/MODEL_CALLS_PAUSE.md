# 模型调用暂停与恢复

## 当前状态：全部恢复

2026-09-06 按研发测试需要，已恢复生产后端、语音及原有周期性 AI 整理任务。
自动摘要、空闲记忆固化、分层总结和每日关系页面刷新保持原有启用状态。
此前拟增加的周期性整理禁用开关未部署，相关本地改动已撤回。
服务器与本地暂停标记均已解除；启动锁配置保留供以后按需暂停，不影响正常运行。

## 全部模型服务暂停（保留的运维能力）

2026-09-06 曾暂停 Server-USA 的 `ponychat-backend.service` 与
`ponychat-cosyvoice.service`，停止聊天、主动消息、自动摘要、长期记忆、关系页面、
语音等调用。后端 API（包括登录、管理等非模型接口）也会暂时不可用。
静态官网、音乐/乐谱站继续运行。未修改数据库、模型配置、密钥或历史数据。

在 `P:\PonyChat` 下执行：

```powershell
# 查看状态
P:\Tools\python\python.exe scripts/ops/model_calls_pause.py status
# 恢复暂停前处于运行状态的服务，并解除本地 Backend 启动锁
P:\Tools\python\python.exe scripts/ops/model_calls_pause.py resume
# 再次暂停（先停止任何手动启动的本地 Backend 进程）
P:\Tools\python\python.exe scripts/ops/model_calls_pause.py pause
```

服务器启动锁为 `/var/lib/ponychat-model-pause/paused`，对应两个服务各自的
`90-model-pause.conf` systemd drop-in。存在锁时，普通 restart、部署脚本重启、
服务器重启均不会启动这两个服务。恢复脚本只解除本次锁并恢复先前运行状态；
保留 drop-in 供下次暂停使用。不要删除整个 drop-in 目录。

本地锁为仓库根目录 `.ponychat-models-paused`（不提交 Git），在 Backend
导入配置和注册后台任务前拒绝启动。本次检查没有发现本机 PonyChat 运行进程；
旧 `PonyChat Qwen3TTS Local Stack` 计划任务已禁用。暂停脚本不强杀本机进程。
独立模型测试脚本不受 Backend 启动锁约束，暂停期间不要手动运行这些付费测试。

验收不发起任何模型请求，仅检查服务、PID、启动锁和 HTTP 可达状态。
供应商对暂停前请求的费用可能延迟入账，本次未访问供应商账单。
