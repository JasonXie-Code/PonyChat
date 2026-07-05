# PonyChat

PonyChat 是一个以 My Little Pony 角色互动为核心的 AI 伴侣项目。当前完整体验以 Android 客户端为主，Web 端提供官网、轻量聊天、角色大厅、管理后台、MBTI 子站、LLM 静态站和语音实验室。

## 当前状态

- Android 当前版本：`5.6.13` / `versionCode 353`。
- 后端：FastAPI + SQLite，包含普通聊天、长期记忆、主动消息、角色大厅、素材库、Galgame / 锁分、小游戏、陪玩、语音消息和管理后台 API。
- Android：Jetpack Compose 原生应用，包含普通聊天、语音气泡、图片/多模态、Galgame / 锁分、中国象棋、斗地主、角色大厅、会员/配额、设置和本地缓存。
- Web：`PonyChat-Website/Main/frontend` 是主站与管理后台；`MBTI/`、`LLM/`、`TTS/`、`MLP-Songs/` 是独立子项目。
- 语音：生产部署默认走 `voice.ponychat.org/cosyvoice` 的 DashScope / 百炼 CosyVoice 网关；旧 Qwen3TTS / OmniVoice 代码保留为兼容或历史参考，本机 Qwen3TTS 自启任务默认不应依赖。

## 快速入口

| 路径 | 说明 |
| --- | --- |
| `PROJECT.md` | 产品定位、能力边界、目录说明和长期规划 |
| `SERVER.md` | Server-USA、域名、部署和运维说明 |
| `Android-App/README.md` | Android 构建、版本和模块说明 |
| `Backend/deploy/README.md` | 后端部署与远程测试要求 |
| `docs/README.md` | 项目维护文档索引 |
| `.env.example` | 本地/生产环境变量模板，不包含真实密钥 |

## 本地验证

后端静态检查：

```powershell
python -m py_compile Backend\__init__.py Backend\__main__.py Backend\model_manager.py
```

Android 单元测试：

```powershell
cd Android-App
.\gradlew.bat testDebugUnitTest
```

Android 构建：

```powershell
cd Android-App
.\gradlew.bat :app:compileDebugKotlin
.\gradlew.bat :app:assembleDebug
```

## 密钥

仓库内模型配置只保留 `${ENV_NAME}` 占位符。真实密钥通过 `.env`、systemd `EnvironmentFile` 或部署环境变量注入，不提交到 Git。

已有密钥如果曾进入本地 Git 历史，上传 GitHub 时应使用干净快照分支或重写历史，避免把旧提交中的密钥带到远程。

