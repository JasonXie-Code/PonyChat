# PonyChat 生产服务器说明

> **唯一生产服务器**：**Server-USA**（DMIT 洛杉矶，`154.17.23.237`）  
> 密钥与连接配置的唯一来源：**`P:\ServerKeys\`**（与本仓库分离）
> **e5 GPU 节点已退役**：`P:\ServerKeys` 中的 e5 大桥条目与私钥已删除；`voice.ponychat.org` 的默认 TTS 能力为 Server-USA 上的 CosyVoiceTTS 网关，调用官方 DashScope / 百炼在线 API。本机 Qwen3TTS 自启任务已停用，不再作为默认生产依赖。

---

## 架构概览

```
公网入口 / DNS
  www.ponychat.org           → A → 154.17.23.237
  ponychat.org               → A → 154.17.23.237
  admin.ponychat.org         → Server-USA 主站 SPA 管理入口
  mbti.ponychat.org          → A → 154.17.23.237
  standard-mbti.ponychat.org → A → 154.17.23.237
  voice.ponychat.org         → Server-USA CosyVoiceTTS（/cosyvoice）
  llm.ponychat.org           → 历史 e5 GPU LLM 入口（已退役）
  great-bridge*.ponychat.org → SSH 大桥入口
  server.ponychat.org        → Server-USA 管理入口

Server-USA（154.17.23.237）
  Nginx stream :443 SNI
    www/ponychat.org / admin / mbti / standard-mbti → 127.0.0.1:8443
                                └─ Nginx TLS（Let's Encrypt）
                                    ├─ /var/www/ponychat-static           ← 主站 + admin 路由
                                    ├─ /var/www/mbti-ponychat-static      ← PonyChat-Website/MBTI/MLP/ dist
                                    └─ /var/www/standard-mbti-static      ← PonyChat-Website/MBTI/Standard/ dist

  SSH 大桥（sshd GatewayPorts yes）
    :2222  jx@...    ← GreatBridgeHome
    :2223  aiopc@... ← GreatBridgeAIOPC
    :2224  dckj@...  ← GreatBridgeCQ
    :2225  e5@...    ← 已退役，连接条目与私钥已删除

  TTS 服务域名
    voice.ponychat.org → Server-USA 本地 CosyVoiceTTS 网关（/cosyvoice，旧 /qwen3tts 跳转）
    llm.ponychat.org   → 已退役
```

---

## Server-USA 基本信息

| 项目 | 内容 |
|------|------|
| 服务商 | DMIT, Inc. |
| 套餐 | LAX.AN4.Pro.STARTER |
| IP（IPv4） | `154.17.23.237` |
| SSH | 端口 `22`，用户 `root` |
| 操作系统 | Ubuntu 24.04 LTS x64 |
| 规格 | 2 vCPU / 2 GB RAM / 80 GB SSD / 3 TB 流量 |

---

## 静态站部署

### 一键部署

```bash
cd PonyChat-Website/Main/frontend
npm run build
cd ../../..
python PonyChat-Website/Main/deploy/server-usa/deploy_static_web_now.py
```

默认连接参数从 `P:\ServerKeys\servers.json`（`servers.usa` 条目）读取；可通过 `PONYCHAT_USA_HOST`、`PONYCHAT_USA_KEY` 环境变量覆盖。

### Nginx 配置

生产配置：`PonyChat-Website/Main/deploy/server-usa/nginx-ponychat-www.conf`

- `:80`：ACME 验证 + 301 重定向（覆盖 `www`、根域、`admin`、`mbti`、`standard-mbti` 等域名）
- `127.0.0.1:8443`：Let's Encrypt TLS 终止
  - `www.ponychat.org` / `ponychat.org` → `/var/www/ponychat-static`
  - `admin.ponychat.org` → `/var/www/ponychat-static`，根路径 302 到 `/admin`
  - `mbti.ponychat.org` → `/var/www/mbti-ponychat-static`
  - `standard-mbti.ponychat.org` → `/var/www/standard-mbti-static`
- `voice.ponychat.org/cosyvoice` 运行在 Server-USA 的 `/opt/ponychat-cosyvoice`，由 `ponychat-cosyvoice.service` 监听 `127.0.0.1:18010`，调用官方 DashScope / 百炼 CosyVoice HTTP API。
- `voice.ponychat.org` 原双引擎 Voice Lab（Qwen3TTS / OmniVoice）已退役；`/qwen3tts` 跳转到 `/cosyvoice/`，`/omnivoice` 返回 410。
- `voice.ponychat.org:8443` 不是正式用户入口；为兼容旧链接，公网 `8443` 只返回 301 到标准 `https://voice.ponychat.org/...`。

### 后端语音与计费

`ponychat-backend.service` 已在 Server-USA 显式打开聊天语音：

- `PONYCHAT_VOICE_ENABLED=1`
- `PONYCHAT_VOICE_LAB_ENABLED=1`
- `PONYCHAT_TTS_PROVIDER=cosyvoice`
- `PONYCHAT_COSYVOICE_BASE_URL=https://voice.ponychat.org/cosyvoice`

角色音色迁移策略：PonyChat 后端保存用户上传的参考音频作为兜底源；正常情况下首次语音生成时注册到 CosyVoice 并缓存 `cosy_voice_id`，后续直接使用阿里音色 ID 合成。仅当阿里侧音色失效、合成失败或本地 voice recipe 变化时，才用后端保存的参考音频重新注册。

计费规则：每条成功生成的语音消息扣 `10` 今日积分；同一回复拆成多条语音时按条累计。成本可通过 `PONYCHAT_VOICE_MESSAGE_CREDIT_COST` 调整。缓存重发、失败或超时不会再次扣分。

详细流程见 `PonyChat-Website/Main/deploy/server-usa/DEPLOY-STATIC-WEB.md`。

### Let's Encrypt 证书

- 路径：`/etc/letsencrypt/live/www.ponychat.org/`
- SAN：以 `certbot certificates` 为准；主证书 `www.ponychat.org` 至少包含 `www.ponychat.org`、`ponychat.org`、`admin.ponychat.org`、`mbti.ponychat.org`、`standard-mbti.ponychat.org`，并含 `great-bridge*.ponychat.org`、`server.ponychat.org` 等（扩展示例见下）。
- `voice.ponychat.org` / `llm.ponychat.org` 为 GPU 服务域名，证书位置跟随实际反向代理入口；如合并进主证书，扩展 SAN 时必须一并加入。
- 如需新增子域 SAN：`certbot certonly --webroot --expand -d ... -d 新子域`
- 扩展示例（主站、管理入口、MBTI 与大桥域名）：
  ```bash
  sudo certbot certonly --webroot --expand --cert-name www.ponychat.org \
    -w /var/www/html \
    -d www.ponychat.org -d ponychat.org -d admin.ponychat.org \
    -d mbti.ponychat.org -d standard-mbti.ponychat.org \
    -w /var/www/certbot \
    -d great-bridge.ponychat.org -d great-bridge-aiopc.ponychat.org \
    -d great-bridge-cq.ponychat.org -d server.ponychat.org
  ```

---

## 大桥 SSH（GreatBridge）

所有大桥经 Server-USA 转发；密钥均在 `P:\ServerKeys\`：

| 大桥 | 连接方式 | 密钥 |
|------|---------|------|
| GreatBridgeHome | `jx@154.17.23.237:2222` | `P:\ServerKeys\GreatBridgeHome\id_ed25519` |
| GreatBridgeAIOPC | `aiopc@154.17.23.237:2223` | `P:\ServerKeys\GreatBridgeAIOPC\id_ed25519_aiopc` |
| GreatBridgeCQ | `dckj@154.17.23.237:2224` | `P:\ServerKeys\GreatBridgeCQ\id_ed25519` |
| e5 GPU 节点 | 已退役 | `P:\ServerKeys\servers.json` / `ssh_lib.py` 中的 e5 条目与私钥已删除 |

推荐用 `P:\ServerKeys\ssh_lib.py` 统一管理（自动处理密钥 ACL、临时目录复制、执行后清理）：

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path("P:/ServerKeys")))
from ssh_lib import load_server, load_bridge, ssh_exec

ssh_exec(load_server("usa"), "nginx -t && systemctl reload nginx")
ssh_exec(load_bridge("home"), "systemctl status ponychat")
```

命令行快速连通测试：

```powershell
python P:\ServerKeys\ssh_lib.py usa
python P:\ServerKeys\ssh_lib.py home
```

---

## 机内核对（登录 Server-USA 后）

```bash
# Nginx 状态与监听
systemctl is-active nginx
ss -tlnp | grep -E ':80|:443|:8443'

# 配置语法与已启用站点
nginx -t && ls /etc/nginx/sites-enabled/

# 证书
certbot certificates 2>/dev/null | grep -A3 "www.ponychat.org"

# 活跃大桥端口（e5 的 2225 已退役）
ss -tlnp | grep -E ':2222|:2223|:2224|:55222|:55322'

# CosyVoiceTTS
ss -tlnp | grep ':18010'
curl https://voice.ponychat.org/cosyvoice/health
curl -I https://voice.ponychat.org/qwen3tts
curl -I https://voice.ponychat.org/omnivoice
```

---

## 域名一览

| 域名 | 服务 | 备注 |
|------|------|------|
| `www.ponychat.org` / `ponychat.org` | 静态展示站（`PonyChat-Website/Main/frontend` 构建产物） | |
| `admin.ponychat.org` | 主站管理控制台 | 与主站共用 `/var/www/ponychat-static`，根路径跳转到 `/admin` |
| `mbti.ponychat.org` | MLP MBTI 静态站（PonyChat-Website/MBTI/MLP/） | |
| `standard-mbti.ponychat.org` | 标准 MBTI 人格测试（`PonyChat-Website/MBTI/Standard` 构建产物） | |
| `great-bridge.ponychat.org` | GreatBridgeHome SSH 中继 | DNS A → 154.17.23.237，端口 2222 |
| `great-bridge-aiopc.ponychat.org` | GreatBridgeAIOPC SSH 中继 | DNS A → 154.17.23.237，端口 2223 |
| `great-bridge-cq.ponychat.org` | GreatBridgeCQ SSH 中继 | DNS A → 154.17.23.237，端口 2224 |
| `server.ponychat.org` | Server-USA 管理/证书域名 | 随主证书维护，实际管理入口以 `P:\ServerKeys\servers.json` 为准 |
| `voice.ponychat.org/cosyvoice` | PonyChat CosyVoiceTTS | Server-USA 本地 FastAPI 网关调用官方 DashScope / 百炼 CosyVoice HTTP API；`/qwen3tts` 跳转到 `/cosyvoice`，`/omnivoice` 已移除 |
| `llm.ponychat.org` | 历史 PonyChat LLM 静态站与聊天 API | e5 已退役，不再作为生产入口维护 |

---

## 关键文件

| 路径 | 用途 |
|------|------|
| `Backend/deploy/deploy_backend_server_usa.py` | 增量同步后端到 Server-USA 并重启 `ponychat-backend` |
| `PonyChat-Website/Main/deploy/server-usa/deploy_static_web_now.py` | 一键同步静态站到 Server-USA |
| `PonyChat-Website/**/deploy.py` | 各网站根目录部署入口；只部署对应站点内容，远端 manifest 增量同步 |
| `PonyChat-Website/deploy_lib/incremental.py` | 网站部署脚本共用的 SSH、manifest 与增量同步工具 |
| `PonyChat-Website/Main/deploy/server-usa/nginx-ponychat-www.conf` | 当前生产 Nginx 配置（含 `admin`、`mbti`、`standard-mbti` 子域） |
| `PonyChat-Website/MBTI/MLP/misc/deploy_mbti_server_usa.py` | 同步 MLP MBTI 静态站到 Server-USA |
| `PonyChat-Website/MBTI/Standard/misc/deploy_standard_mbti_server_usa.py` | 同步 Standard MBTI 静态站到 Server-USA |
| `PonyChat-Website/TTS/deploy.py` | 部署 CosyVoiceTTS 到 Server-USA `/opt/ponychat-cosyvoice`，写入 systemd 与 `voice.ponychat.org` Nginx 路由 |
| `PonyChat-Website/TTS/deploy_omni_runtime.py` | e5 退役后已禁用；不再安装 OmniVoice 运行环境 |
| `PonyChat-Website/TTS/deploy_voice_nginx_split.py` | e5 退役后已禁用；不再配置旧 Voice Lab 分流 |
| `PonyChat-Website/TTS/PonyChat-Voice-Lab.md` | Voice Lab 架构、API、队列与 GPU 节点说明 |
| `PonyChat-Website/LLM/README.md` | 本地 LLM 静态站接口与部署说明 |
| `PonyChat-Website/LLM/index.html` | `llm.ponychat.org` 静态站入口 |
| `PonyChat-Website/Main/deploy/server-usa/DEPLOY-STATIC-WEB.md` | 完整部署流程文档 |
| `PonyChat-Website/Main/deploy/server-usa/fix-ssh-key-acl.ps1` | Windows SSH 密钥 ACL 修复 |
| `P:\ServerKeys\servers.json` | 各服务器/大桥连接参数 |
| `P:\ServerKeys\ssh_lib.py` | 统一 SSH 工具库 |

> `PonyChat-Website/Main/deploy/server-usa/` 目录内其余脚本（`deploy-hk-cn2-cf-ws.sh`、`fix-cn2-nginx-443-stream-merge.sh`、`nginx-panel-www-ponychat-le.conf` 等）均为 2026-04-04 迁移前 HK-CN2 时代的历史存档，不再使用。

---

## 注意事项

- SSH 私钥**不提交**至本仓库；密钥实体在 `P:\ServerKeys\DMIT - 154.17.23.237\`，仓库内 `TheServerUSA-id_rsa/` 为空占位目录。
- Windows OpenSSH 报 `bad permissions`：优先用 `ssh_lib.py` 自动处理，或在 `PonyChat-Website/Main/deploy/server-usa/` 目录执行 `fix-ssh-key-acl.ps1`。
