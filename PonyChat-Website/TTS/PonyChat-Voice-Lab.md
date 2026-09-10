# PonyChat Voice Lab 说明

> 文档状态：2026-09-09 更新本机后端与服务器静态网页分工。易变的版本、部署和服务状态在使用前仍需现场验证。

> 最后更新日期：2026-09-09

聊天当前默认使用本机 `C:\PonyChatVoice\TTS` 的 Qwen3TTS（8010）。CosyVoice 网关也已迁到本机，由 `P:\PonyChat\scripts\ops\local_stack.py` 在 18010 启动；数据在 `var/services/cosyvoice`，调用官方 DashScope / 百炼 API。

语音静态网页保留在 Server-USA `/opt/ponychat-cosyvoice/static`，由 Nginx 直接提供；API 经反向隧道连接本机。`PonyChat Qwen3TTS Local Stack` 登录自启任务继续启用。不要运行旧 `deploy.py` 重建 USA 的 CosyVoice 服务。完整运行说明见 [SERVER.md](../../SERVER.md)。

## 当前生产入口

| 路径 | 状态 | 说明 |
| --- | --- | --- |
| `https://voice.ponychat.org/` | 跳转 | 跳转到 `/cosyvoice/` |
| `https://voice.ponychat.org/cosyvoice/` | 当前入口 | CosyVoiceTTS 网页与 API |
| `https://voice.ponychat.org/cosyvoice/health` | 当前入口 | 健康检查，返回 `backend=dashscope-cosyvoice-http` |
| `/qwen3tts`、`/qwen3tts/` | 当前 Qwen 入口 | USA 回环 18012 转发本机 8010，不能重定向至 CosyVoice |
| `/omnivoice`、`/omnivoice/*` | 已移除 | 返回 410 |

## 代码边界

| 文件 / 目录 | 用途 |
| --- | --- |
| `app_cosyvoice.py` | 本机 FastAPI 网关，提供 CosyVoice 页面、任务队列、音色注册、合成和声音库接口 |
| `deploy.py` | 历史部署工具；本次迁移后停用，原流程部署 `app_cosyvoice.py`、静态资源、systemd 和 `voice.ponychat.org` Nginx 路由 |
| `static/cosyvoice.html`、`static/assets/cosyvoice.js` | 当前语音实验室页面 |
| `app_fast.py`、`app_fast_impl/` | 旧本机 Qwen3TTS 兼容后端 |
| `app_omni.py` | 旧 OmniVoice 后端，生产入口已移除 |
| `start_qwen3tts_*.ps1`、`install_qwen3tts_startup_task.ps1` | 本机 Qwen3TTS 启动/隧道/自启脚本，既有本机任务继续启用 |

运行数据、模型、声音库、输出音频和上传缓存均被 `.gitignore` 排除：`models/`、`voices/`、`outputs/`、`uploads/`、`generation_logs/` 等不应提交。

## 历史 systemd 模板（不再用于生产部署）

生产后端 systemd 模板默认：

```ini
Environment=PONYCHAT_VOICE_ENABLED=1
Environment=PONYCHAT_VOICE_LAB_ENABLED=1
Environment=PONYCHAT_TTS_PROVIDER=cosyvoice
Environment=PONYCHAT_COSYVOICE_BASE_URL=https://voice.ponychat.org/cosyvoice
Environment=COSYVOICE_MODEL=cosyvoice-v3.5-plus
Environment=PONYCHAT_VOICE_LAB_DEFAULT_VARIANT=original
```

后端 `Backend/cosyvoice_client.py` 会调用 `/cosyvoice/jobs/*` 接口。角色参考音频先注册为可复用的 `cosy_voice_id`，后续合成优先复用该 ID；注册失败或音色失效时再使用 PonyChat 保存的参考音频重新注册。

旧 `qwen3tts:<角色>` voice id 会在 CosyVoice provider 下做兼容映射，不要求本机 Qwen3TTS 服务在线。

## CosyVoice API

基础地址：`https://voice.ponychat.org/cosyvoice`

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/health` | 健康检查 |
| `GET` | `/voices` | 系统音色与远端自定义音色 ID 列表 |
| `GET` | `/voices/meta` | 声音库详情 |
| `POST` | `/jobs/tts` | 文本合成入队 |
| `POST` | `/jobs/tts/segmented` | 分段文本合成入队 |
| `POST` | `/jobs/voices/clone` | 上传参考音频并注册克隆音色 |
| `POST` | `/jobs/voices/design` | 用文本描述生成/注册音色 |
| `GET` | `/jobs/{job_id}` | 查询任务状态 |
| `GET` | `/jobs/{job_id}/audio` | 下载任务音频 |
| `DELETE` | `/voices/{voice_id}` | 删除远端自定义音色 |

合成示例：

```bash
curl -X POST https://voice.ponychat.org/cosyvoice/jobs/tts \
  -H "Content-Type: application/json" \
  -d '{
    "voice_id": "longanyang",
    "text": "你好，这里是 PonyChat 语音测试。",
    "format": "wav",
    "sample_rate": 24000,
    "mobile_microphone": false
  }'
```

## 部署

从仓库根目录运行：

```powershell
$env:DASHSCOPE_API_KEY="<从密钥库注入>"
python PonyChat-Website\TTS\deploy.py
```

部署脚本会：

1. 同步 `app_cosyvoice.py` 和精简静态资源到 Server-USA `/opt/ponychat-cosyvoice`。
2. 创建或更新 `/etc/ponychat/cosyvoice.env`。
3. 写入 `ponychat-cosyvoice.service`，监听 `127.0.0.1:18010`。
4. 写入 `voice.ponychat.org` Nginx 路由，`/qwen3tts` 跳转到 `/cosyvoice/`，`/omnivoice` 返回 410。
5. 重启服务并 reload Nginx。

验收：

```bash
curl https://voice.ponychat.org/cosyvoice/health
curl -I https://voice.ponychat.org/qwen3tts
curl -I https://voice.ponychat.org/omnivoice
```

## 本机 Qwen3TTS 回退

仓库仍保留本机 Qwen3TTS 栈：

- `AAA_start_qwen3tts_local.bat`
- `start_qwen3tts_local.ps1`
- `start_qwen3tts_tunnel.ps1`
- `start_qwen3tts_watchdog.ps1`
- `install_qwen3tts_startup_task.ps1`

当前本机自启任务应保持禁用；如需临时测试，先确认模型、虚拟环境、Redis、`127.0.0.1:8010`、Server-USA `18012` 隧道和后端 provider 全部一致。测试结束后再停止进程并禁用计划任务。
