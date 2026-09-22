# PonyChat 运行与服务器说明

> 本次迁移：2026-09-09。正式切换及清理结果见 `docs/operations/local-backend-migration-20260909.md`。

> 长期运行约定（2026-09-10 用户明确确认）：以后 PonyChat 后端都在本机 `P:\PonyChat` 运行。这是默认生产架构，不是临时开发或测试模式。后续“部署后端”应更新本机服务，不向 Server-USA 恢复后端进程、数据库或知识库；架构迁回远端需要用户另行明确要求。

部署时先核对 `var/local-stack/status.json`、本机 5000 监听进程和 `Backend/.deploy_revision`，再核对 CN IP 与官网 `/api/health` 的 `deploy_token`。公网 URL 所在服务器不是后端进程所在地；即使 Server-USA 回环 5000 能返回健康响应，也可能只是隧道转发。完整步骤见 [本机后端部署](Backend/deploy/README.md)。

## 当前拓扑

聊天、用户数据库、聊天日志、CosyVoice 网关和 SearXNG 在本机 `P:\PonyChat` 运行。Qwen3TTS 沿用本机 `C:\PonyChatVoice\TTS` 的 GPU 服务。

```text
Android 6.0.6+ → https://39.101.74.217（Server-CN）
                 → Nginx → 127.0.0.1:18500（SSH 反向隧道）
                 → 本机 127.0.0.1:5000（FastAPI + SQLite）

PonyChat 官网（Server-USA）→ /download/apk → USA 回环 5000
                           → SSH 反向隧道 → 本机最新签名 APK
官网 /api、/ws 与管理台 → 同一本机后端
voice.ponychat.org/cosyvoice/* API → USA 回环 18010 → 本机 CosyVoice
voice.ponychat.org/qwen3tts/*     → USA 回环 18012 → 本机 Qwen3TTS 8010
```

手机 App 的正式 API 和更新下载使用 IP、443 端口及 HTTPS；旧生产域名偏好在升级后不再作为正式 API 地址。官网域名继续用于官网浏览与下载，旧版 App 的域名入口保留兼容转发。

## 服务与目录

| 服务 | 本机端口 / 目录 | 管理方式 |
| --- | --- | --- |
| 聊天 FastAPI | `5000`；`P:\PonyChat\Backend` | `PonyChat Local Backend Stack` 计划任务 |
| 当前数据库 | `P:\PonyChat\Backend\database\ponychat.db` | SQLite，单进程写入 |
| 日志 | `P:\PonyChat\var\.chatlogs`、`backlogs`、`applogs`、`chatlogs` | 后端运行数据 |
| 附件与知识数据 | `var/drive`、`Backend/data` | 本机持久保存 |
| CosyVoice | `127.0.0.1:18010`；`var/services/cosyvoice` | 同一本地守护任务 |
| SearXNG | `127.0.0.1:18786`；`var/services/searxng` | Waitress + 独立 Python 环境 |
| Qwen3TTS | `127.0.0.1:8010`；`C:\PonyChatVoice\TTS` | 既有 `PonyChat Qwen3TTS Local Stack` 任务 |
| 最新 APK | `P:\PonyChat\var\releases\latest.json` 及同目录版本 APK | 原子发布指针，立即生效 |
| 守护状态 | `P:\PonyChat\var\local-stack` | `status.json` 与各组件日志 |

本机守护程序负责聊天、CosyVoice、搜索、USA/CN 两条隧道；子进程退出后自动重启，服务连续三次健康检查失败后重启。计划任务在当前 Windows 用户登录时启动。电脑必须保持开机、联网并登录该用户；休眠、断网或关机期间，依赖本机的聊天与 APK 下载不可用。

## 启动、停止与检查

双击仓库根 `AAA启动后端.bat` 可在后台启动整套服务；单实例保护避免重复启动。重新登记任务：

```powershell
.\scripts\ops\install_local_stack.ps1 -Start
```

停止本机整套聊天/CosyVoice/搜索及其隧道：

```powershell
.\.venv\Scripts\python.exe scripts/ops/local_stack.py stop
```

Qwen3TTS 由独立任务管理，此命令不停止 GPU 引擎。日志与数据库不会被停止命令删除。

```powershell
Invoke-RestMethod http://127.0.0.1:5000/api/health
Invoke-RestMethod http://127.0.0.1:18010/cosyvoice/health
Invoke-RestMethod http://127.0.0.1:8010/qwen3tts/health
Invoke-WebRequest http://127.0.0.1:18786/healthz
Invoke-RestMethod https://39.101.74.217/api/health
Invoke-RestMethod https://www.ponychat.org/api/health
Get-Content var/local-stack/status.json
```

本机与两个公网入口应返回相同 `deploy_token`。排查时先确认本机健康，再检查隧道和远端 Nginx，不要用静态官网 200 代替后端验收。

## 服务器保留内容

- **Server-USA `154.17.23.237`**：Nginx、TLS、公网入口、PonyChat 网页与语音静态页面、歌曲/乐谱业务、原有历史备份，以及其他业务。
- **Server-CN `39.101.74.217`**：只新增 PonyChat IP 路由与 SSH 回环入口；原有 Scenery、Recorder、五龙源等业务保持原路径。
- USA 上的 `ponychat-backend`、`ponychat-cosyvoice`、`ponychat-searxng` 原计算服务及对应应用数据已清理；历史备份保留，详细校验见迁移记录。不能再向这些旧目录部署生产后端。
- APK 由本机提供；USA 的下载代理关闭缓冲、缓存及临时落盘。历史备份不搬迁、不删除；歌曲、乐谱和网页不搬迁。

## 连接与配置

服务器私钥唯一来源是独立的 `P:\ServerKeys`。USA 使用 `servers.json` 的 `usa`；CN 使用 `yuelimei`，密钥目录是 `Server-CN - 39.101.74.217`。不修改全局 SSH `GatewayPorts`，所有新隧道仅绑定远端回环，由 Nginx 提供公网入口。

本机 `.env` 与 `.env.local-stack` 保存迁移后的配置；CosyVoice 私密配置位于 `var/services/cosyvoice/.env`。这些文件及 `var/` 不提交 Git。Python 3.12 基础运行时位于 `var/runtime/python312`，不依赖 Codex App 的缓存目录。

Clash Verge 的当前本地配置已将 `IP-CIDR,39.101.74.217/32,DIRECT,no-resolve` 放在规则首位，保持 `mode: rule` 和原有 TUN 设置，避免 CN 隧道绕行 USA 代理。独立导入文件为 `C:\Users\Jason Xie\Downloads\VPN-USA Clash_v1.yaml`，原 `VPN-USA Clash.yaml` 保留未改。已让本套服务的 CN SSH 隧道重新连接，实际 22、80 端口连接均命中 `IPCIDR / DIRECT`；CN 完整 APK 下载哈希一致。以后导入配置应使用此版本或保留该优先规则；Global 模式不会按此规则分流。

CN 的增量路由模板是 `Backend/deploy/ponychat-local-cn.nginx.conf`，安装到 `/etc/nginx/snippets/ponychat-local-ip.conf`，由现有 IP 虚拟主机包含。USA 继续使用既有 `ponychat-www`、`voice.ponychat.org` 配置；静态网站部署不应重置本次下载代理与语音静态路由。

Android 构建和本地 APK 发布见 `Android-App/README.md`；后端更新与测试见 `Backend/deploy/README.md`。

当前 Nginx 模板同时保存在 `Backend/deploy/ponychat-local-usa-download.nginx.conf`、`ponychat-local-cn.nginx.conf` 和 `ponychat-local-voice.nginx.conf`，分别对应 USA 下载、CN IP API 和 USA 语音网页/API。
