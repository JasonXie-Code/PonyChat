# PonyChat Drive

用户于 2026-10-15 明确指定：**网盘服务和网盘文件放在 Server-USA，本机继续承载对话后端。** 此约定优先于旧文档中“全部后端在本机”的泛化表述；不要重新把网盘部署为本机聊天服务的存储模块。

## 运行拓扑

```text
浏览器 → https://drive.ponychat.org
       → USA Nginx → 127.0.0.1:18050
       → ponychat-drive.service → /var/lib/ponychat-drive

对话 App / 管理台 → 既有 USA/CN 对话入口 → 本机 127.0.0.1:5000
```

网盘网页、API、正常文件及回收站都在 USA。网盘容量取决于 USA 数据目录所在磁盘，不依赖本机 P 盘容量、聊天进程或聊天反向 SSH 隧道。生产网盘仅监听 USA 回环地址，不新增公网应用端口。

| 项目 | Server-USA 路径 / 名称 |
| --- | --- |
| 应用 | `/opt/ponychat-drive/Drive` |
| 独立 Python 环境 | `/opt/ponychat-drive/.venv` |
| 正常文件 | `/var/lib/ponychat-drive/files` |
| 回收站和元数据 | `/var/lib/ponychat-drive/.trash` |
| 私密配置 | `/etc/ponychat-drive/service.env`，root 所有、权限 0600 |
| 服务 | `ponychat-drive.service`，专用用户 `ponychat-drive`，开机自启 |
| 健康检查 | `http://127.0.0.1:18050/healthz` 或公网 `/api/drive/health` |

服务只依赖 FastAPI、Uvicorn 和 multipart 处理，不导入聊天配置、模型、数据库或 Agent。`Backend/routes/drive.py` 是兼容转发器，不再实现本机网盘读写；已运行的聊天进程无需为迁移重启，后续正常重启会加载该兼容器。

## 配置与升级

必须设置 `PONYCHAT_DRIVE_PASSWORD` 和独立的 `PONYCHAT_DRIVE_AUTH_SECRET`。生产另设 `PONYCHAT_DRIVE_ROOT=/var/lib/ponychat-drive`。不要提交私密配置或将其写入日志。

本次迁移保持访问密码，签发新 token 使用独立网盘密钥。`PONYCHAT_DRIVE_LEGACY_AUTH_SECRET` 与 `PONYCHAT_DRIVE_LEGACY_UNTIL` 仅用于在迁移后的七天内接受原有登录 token；到期后旧密钥即使仍配置也不再参与验证。

部署使用 `requirements.lock.txt` 固定完整依赖。应用代码及虚拟环境必须允许专用服务用户读取/执行；数据目录归该用户所有，服务的 `ProtectSystem=strict` 仅放行网盘数据目录写入。更新后只重启 `ponychat-drive.service`，不要重启本机对话后端。

Nginx 配置见 `deploy/nginx-usa.conf`，在现有 Drive 虚拟主机内包含。`deploy/nginx-cn-compat.conf` 用于兼容已缓存旧页面、仍请求国内 IP 的浏览器：该入口通过验证证书的 HTTPS 转发至 USA，所有文件操作最终仍发生在 USA。新版网页只请求 Drive 域名下的同源 API。

## 验证与数据保护

```powershell
.\.venv\Scripts\python.exe -m pytest Drive/tests -q
```

端到端浏览器检查使用 `PonyChat-Website/Main/frontend/tests/drive-browser-sync.mjs`。设置 `DRIVE_TEST_BLOCK_CN_API=1` 可验证新版网页不依赖国内网盘接口；`DRIVE_TEST_LOGIN_UI=1` 检查真实登录表单；`DRIVE_TEST_LIST_RECOVERY=1` 检查列表接口失败后恢复。

迁移记录见 `../docs/operations/drive-server-usa-20261015.md`。完整搬迁包括 `files`、`.trash` 及 `metadata.json`，先复制、再暂停写入补齐差异、校验所有文件 SHA-256、最后切换入口。本机旧 `var/drive` 保留为迁移前快照，不是活动网盘，也不会自动同步后续 USA 改动。不要用该旧快照覆盖新服务数据。
