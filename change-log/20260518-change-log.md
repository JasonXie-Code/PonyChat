# 2026-05-18 Change Log

## 文档与代码对齐

- 管理后台「网页角色」已并入「角色管理」。
- `/admin/web-chars` 前端重定向到 `/admin/characters`，兼容 API 仍保留。
- 素材管理已落地，素材图片以 SQLite BLOB 存在 `media_assets.file_data`，经 `/api/admin/assets/{id}/file` 返回。

## Android 与 Galgame 状态说明

- Android 设计文档已更正：Galgame / 锁分并未下线，当前仍由 `Backend/galgame/` 与 Android 原生 UI 承载。
- 陪玩文档更正：当前后端可用的是经典 `/api/companion/frame|stream|end` 与 ASR/TTS WebSocket。
- Android `OmniRealtimeBridge` 默认指向的 `/ws/companion/realtime` 在后端尚未挂载。
