# PonyChat 本地后端部署

> 2026-09-09 起，生产聊天、CosyVoice、搜索和日志迁至 `P:\PonyChat`。入口与服务器分工见 [SERVER.md](../../SERVER.md)，迁移校验见 [迁移记录](../../docs/operations/local-backend-migration-20260909.md)。

**2026-09-10 用户确认：以后 PonyChat 后端统一在本机运行。** 日常部署目标固定为本机 `P:\PonyChat` 的生产进程。Server-CN / Server-USA 保留公网入口和转发职责；不能因为官网域名指向美国服务器就对其执行后端发布。

部署前核对本机运行进程、部署标记和工作区改动。当前生产与研发共用目录，重启会加载目录中的其他后端改动；发现并行任务的未提交运行代码时，先协调并核验版本，不把它作为已验证版本一并上线。保存上一版代码及部署标记并备份数据库；部署后核对本机、CN IP、官网的健康标记，再执行对应真实功能验收。版本记录应列出实际生效文件及哈希。

小马中文维基的原始文字存档位于本机 `Backend/data/mlp/pages`。在线正文失败时的存档恢复依赖此目录；这些是旧抓取资料，不是实时网页。后端部署无需将此知识库或用户数据库上传远端。

## 启动与更新

双击仓库根 `AAA启动后端.bat`；安装或恢复登录自启任务：

```powershell
.\scripts\ops\install_local_stack.ps1 -Start
```

任务名是 `PonyChat Local Backend Stack`，后台运行 `scripts/ops/local_stack.py supervise`。它使用本机 `.venv` 和独立 Python 3.12，启动聊天、CosyVoice、SearXNG，以及到 USA/CN 的 SSH 隧道。`var/local-stack/migration.ready` 表示数据库和文件迁移已核验；`production.enabled` 控制公网隧道。不要在数据尚未准备好时手工创建这两个标志。

正常更新代码后，在仓库根运行相关测试，再停止旧进程并重新启动：

```powershell
.\.venv\Scripts\python.exe scripts/ops/local_stack.py stop
# 确认 var/local-stack/supervisor.log 已记录停止，相关端口已释放。
Start-ScheduledTask -TaskName 'PonyChat Local Backend Stack'
```

不要同时运行另一份生产 `python -m Backend`。开发和测试必须设置独立 `PONYCHAT_DB_PATH`、日志目录及端口，不能对生产用户做重复登录或压力测试。

`deploy_backend_server_usa.py` 在检测到 `.env.local-stack` 时会拒绝旧服务器部署。旧 systemd 文件和其他远程发布工具只作历史参考；不得用它们恢复 USA 后端或把本机数据库上传服务器。

## 配置与路径

- `.env`、`.env.local-stack`：迁移的模型/API 配置与本机路径，禁止提交 Git。
- `Backend/database/ponychat.db`：本机生产 SQLite；WAL/SHM 与主库一起由 SQLite 管理。
- `var/.chatlogs`、`var/backlogs`、`var/applogs`：生产日志；历史日志索引中的 Linux 路径已转换为 Windows 路径。
- `var/drive`、`Backend/data`、`var/recovery_snapshots`：附件、知识数据和恢复状态。
- `var/services/cosyvoice`：CosyVoice 配置、上传和生成音频；服务代码沿用 `PonyChat-Website/TTS/app_cosyvoice.py`，通过 `COSYVOICE_DATA_ROOT` 分离数据位置。
- `var/services/searxng`：原版本源码、配置、独立 Windows 环境。`local_search.py` 只适配 Unix 账号日志查询，并使用 Waitress；不改变搜索引擎规则。
- `var/runtime/python312`：本项目持有的 Python 基础运行时。
- `var/releases/latest.json`：最新 APK 发布指针，后端每次请求重新读取，更新 APK 不要求重启聊天。
- `var/backups`：本机以后按原策略新建的正常备份。服务器历史备份未迁入。

Windows 使用 `asyncio` 事件循环并安装 `tzdata`；Linux 的 `.venv` 不直接复制使用。主环境包含聊天与 CosyVoice 依赖，SearXNG 使用独立环境。原服务版本清单和私密迁移证据保存在忽略的 `var/migration-20260909`。

Qwen3TTS 继续由 `C:\PonyChatVoice\TTS` 和 `PonyChat Qwen3TTS Local Stack` 管理。聊天直接请求本机 8010，CosyVoice 请求本机 18010，搜索请求本机 18786。

## 网络与验收

- App：`http://39.101.74.217:80` → CN Nginx → CN 回环 18500 → 本机 5000。
- 官网、管理台与旧版兼容 API：USA Nginx → USA 回环 5000 → 本机 5000。
- 官网 `/download/apk` 和 `/releases/`：USA 只作无缓存转发，APK 文件在本机。
- CosyVoice：USA 回环 18010 → 本机 18010；语音静态网页保留在 USA。
- 既有 Qwen 公网语音路由继续用 USA 回环 18012，不与本次新隧道争用。

健康检查必须分别覆盖本机、CN IP 和 USA 公网；比较三者 `deploy_token`。同时验证真实聊天、搜索工具调用、语音生成及音频解码、数据库与管理台历史日志读取、完整 APK 下载 SHA-256。

```powershell
Invoke-RestMethod http://127.0.0.1:5000/api/health
Invoke-RestMethod http://39.101.74.217:80/api/health
Invoke-RestMethod https://www.ponychat.org/api/health
Get-Content var/local-stack/status.json
```

## 本地验证命令

```powershell
$env:PONYCHAT_HARNESS_POOL='0'
.\.venv\Scripts\python.exe -m pytest Backend/tests/test_local_apk.py Backend/tests/test_harness_runtime.py Backend/tests/test_web_image_runtime.py -q
```

上述独立单元测试的 SDK stub 不启动进程池；真实 Agent 验收仍使用生产的池配置。真实模型测试应使用 `scripts/ops/smoke_deployed_harness.py` 的隔离数据库，语音场景由 `Backend/Agent-Test/run_agent_voice_probe.py` 验证。

当前实际安装版本已固化在 `Backend/conf/requirements-local-windows.lock.txt` 和 `requirements-searxng-windows.lock.txt`。`scripts/ops/migration_*.py`、`retire_server_backend.py` 为本次迁移留存的审计工具，正常更新不再执行。复查公网、历史日志与完整 APK 可运行 `scripts/ops/verify_local_stack.py`。
