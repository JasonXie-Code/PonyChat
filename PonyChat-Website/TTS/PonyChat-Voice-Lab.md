# PonyChat Voice Lab 说明

> 最后更新日期：2026-07-05

`PonyChat-Website/TTS/` 是 PonyChat 语音实验室和生产 TTS 网关目录。当前生产默认只依赖 Server-USA 上的 CosyVoiceTTS 网关，调用官方 DashScope / 百炼 CosyVoice HTTP API。

旧 Qwen3TTS / OmniVoice 代码仍保留在仓库中，主要用于历史回溯、本地实验或兼容旧 voice id。它们不再是默认生产路径。本机 Qwen3TTS 计划任务和 `127.0.0.1:8010` 服务已停用；需要临时回退时必须手动重新启用本机栈、反向隧道和后端 systemd 环境变量。

## 当前生产入口

| 路径 | 状态 | 说明 |
| --- | --- | --- |
| `https://voice.ponychat.org/` | 跳转 | 跳转到 `/cosyvoice/` |
| `https://voice.ponychat.org/cosyvoice/` | 当前入口 | CosyVoiceTTS 网页与 API |
| `https://voice.ponychat.org/cosyvoice/health` | 当前入口 | 健康检查，返回 `backend=dashscope-cosyvoice-http` |
| `/qwen3tts`、`/qwen3tts/` | 兼容跳转 | 跳转到 `/cosyvoice/` |
| `/omnivoice`、`/omnivoice/*` | 已移除 | 返回 410 |

## 代码边界

| 文件 / 目录 | 用途 |
| --- | --- |
| `app_cosyvoice.py` | Server-USA FastAPI 网关，提供 CosyVoice 页面、任务队列、音色注册、合成和声音库接口 |
| `deploy.py` | 部署 `app_cosyvoice.py`、静态资源、systemd 和 `voice.ponychat.org` Nginx 路由 |
| `static/cosyvoice.html`、`static/assets/cosyvoice.js` | 当前语音实验室页面 |
| `app_fast.py`、`app_fast_impl/` | 旧本机 Qwen3TTS 兼容后端 |
| `app_omni.py` | 旧 OmniVoice 后端，生产入口已移除 |
| `start_qwen3tts_*.ps1`、`install_qwen3tts_startup_task.ps1` | 本机 Qwen3TTS 启动/隧道/自启脚本，默认不启用 |

运行数据、模型、声音库、输出音频和上传缓存均被 `.gitignore` 排除：`models/`、`voices/`、`outputs/`、`uploads/`、`generation_logs/` 等不应提交。

## 后端接入

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
