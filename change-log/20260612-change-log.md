# 2026-06-12 Change Log

## CosyVoiceTTS 迁移

- e5 GPU 节点确认退役，删除旧 e5 连接密钥与旧部署入口依赖。
- `voice.ponychat.org` 迁移到 Server-USA 的 `CosyVoiceTTS`：
  - 当前入口为 `https://voice.ponychat.org/cosyvoice`
  - `/qwen3tts` 301 跳转到 `/cosyvoice`
  - `/omnivoice` 返回 410
- CosyVoiceTTS 后端接入 DashScope / 百炼 CosyVoice HTTP API，支持合成、克隆、设计与管理界面。

## PonyChat 后端语音

- 后端聊天语音开关已打开：
  - `PONYCHAT_VOICE_ENABLED=1`
  - `PONYCHAT_VOICE_LAB_ENABLED=1`
  - `PONYCHAT_TTS_PROVIDER=cosyvoice`
- 角色音色改为懒注册模式：
  - PonyChat 继续保存用户上传的参考音频作为兜底源。
  - 首次语音生成时把参考音频注册到阿里 CosyVoice。
  - 后续同一 voice recipe 直接复用 `cosy_voice_id`，不再重复上传音频。
  - 阿里侧音色失效、合成失败或 recipe hash 变化时才重新注册。
- 兼容旧官方音色 ID：CosyVoice provider 下的 `qwen3tts:<官方角色>` 会映射到 `ponyvoice:<官方角色>`。

## 手机拾音与计费

- 网页端试听保留“手机拾音模拟”开关，服务端用于网页预览后处理。
- Android 端收到官方 API 原音后，在 App 本地执行同款手机拾音处理。
- 每条成功生成的语音消息扣 `10` 今日积分；同一回复多条语音按条累计。失败、超时与缓存重发不扣分。

## 验证

- Server-USA 后端与 CosyVoiceTTS health 检查通过。
- 模拟器中小呆角色成功生成并播放语音气泡。
- 线上 smoke 验证真实生成一条语音后，今日积分增量为 `10`。
- 本地语音测试通过：`Backend/tests/test_voice_audio_cache.py` 共 `21 passed`。
