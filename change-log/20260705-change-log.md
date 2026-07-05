# 2026-07-05 change log

- 更新 GitHub 入口文档、项目总览、Android、后端部署、网站与语音站说明。
- 将模型供应商配置中的真实 API Key 改为环境变量占位符，并补充 `.env.example`。
- 后端 systemd 模板切换到 CosyVoice provider，避免默认依赖本机 Qwen3TTS 隧道。
- TTS 部署模板将 `/qwen3tts` 重定向到 `/cosyvoice/`，`/omnivoice` 保持 410。
- 补充忽略规则，避免本机 `.song.autosave`、History 自动保存和 Android 构建日志进入 GitHub。
- 保留既有主站停更公告改动；未回退用户已有工作区修改。

