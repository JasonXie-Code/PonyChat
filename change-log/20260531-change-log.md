# 2026-05-31 变更记录

## Voice Lab 双引擎部署

- `voice.ponychat.org` 已拆成 Qwen3TTS 与 OmniVoice 双引擎工作台。
- Qwen3TTS 继续由 e5 的 `qwen3-tts.service` 提供服务，本地端口 `8010`，经 Server-USA `18010` 暴露；入口为 `/`、`/qwen3tts` 与旧版无前缀 API。
- OmniVoice 由 e5 的 `omnivoice.service` 提供服务，本地端口 `8011`，经 Server-USA `18011` 暴露；入口为 `/omnivoice/` 与 `/omnivoice/*` API。
- Server-USA Nginx 已配置 `/omnivoice/` split route；备份文件移出 `sites-enabled`，避免重复 `server_name voice.ponychat.org` warning。
- 修复旧入口/相对链接继承 `:8443` 后访问超时的问题：公网 `https://voice.ponychat.org:8443/*` 现在 301 跳转到标准 `https://voice.ponychat.org/*`。
- OmniVoice 模型已直接下载到 e5 本地 `/home/e5/qwen3-tts-service/models/OmniVoice`；服务配置改为 `OMNIVOICE_MODEL` 本地路径并启用离线加载，避免生成时临时访问 Hugging Face。
- 修正 OmniVoice 前端示例中的无效 instruct（如 `soft voice`），改用 OmniVoice 支持的固定属性词示例。
- 项目文档已更新：`PROJECT.md`、`SERVER.md`、`PonyChat-Website/TTS/PonyChat-Voice-Lab.md`。
