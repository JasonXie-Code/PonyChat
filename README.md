# PonyChat

PonyChat 是一个以 My Little Pony 角色互动为核心的 AI 伴侣项目。当前完整体验以 Android 客户端为主，Web 端提供官网、轻量聊天、角色大厅、管理后台、PonyDrive 与独立子站；Companion 则承担自研 Android 设备上的受控观察、操作和验证。

Agent 首次接手请先看 [Agent 经验与交接索引](AgentExperience/README.md)。

## 当前状态

- 长期部署约定（2026-09-10 用户确认）：**以后 PonyChat 后端统一在本机 `P:\PonyChat` 运行**。日常“部署后端”指更新并重启本机生产服务；Server-CN / Server-USA 负责公网入口、网站和转发，不再作为后端部署目标。操作前先读 [本机部署流程](Backend/deploy/README.md)。
- 模型服务与周期性 AI 整理已全部恢复，暂停与恢复命令见 [模型调用暂停与恢复](docs/MODEL_CALLS_PAUSE.md)。
- Android 当前版本：`6.0.4` / `versionCode 382`，正式 API 使用 `http://39.101.74.217:80`。
- 运行位置：聊天、语音网关、搜索和日志在本机 `P:\PonyChat`；Server-CN 提供 App 的 IP 入口，Server-USA 保留网页并转发本机最新 APK。详见 [当前运行拓扑](SERVER.md) 与 [迁移验收](docs/operations/local-backend-migration-20260909.md)。
- 后端：FastAPI + SQLite，包含普通聊天、长期记忆、主动消息、角色大厅、素材库、Galgame / 锁分、小游戏、陪玩、语音消息和管理后台 API。
- Android：Jetpack Compose 原生应用，包含普通聊天、语音气泡、图片/多模态、Galgame / 锁分、中国象棋、斗地主、角色大厅、会员/配额、设置和本地缓存。
- Web：`PonyChat-Website/Main/frontend` 是主站与管理后台；`MBTI/`、`LLM/`、`TTS/`、`MLP-Songs/` 是独立子项目。
- Companion：`0.1.0` 开发验证版已在 K2B/H618 Android 12 跑通系统应用、设备控制和 QQ 私聊首轮闭环；量产签名、OTA、设备内 Controller、长期稳定性与完整安全审计尚未完成。
- 语音：聊天默认使用本机 Qwen3TTS（8010）；本机 CosyVoice（18010）保留云端语音能力。Qwen3TTS 的既有登录自启任务继续启用。

## 快速入口

| 路径 | 说明 |
| --- | --- |
| `PROJECT.md` | 产品定位、能力边界、目录说明和长期规划 |
| `SERVER.md` | 本机后端、CN IP 入口、USA 网页及 APK 下载运维 |
| `Android-App/README.md` | Android 构建、版本和模块说明 |
| `Backend/deploy/README.md` | 后端部署与远程测试要求 |
| `docs/README.md` | 项目维护文档索引 |
| `docs/PROJECT_STATUS.md` | 2026-08-09 工程盘点、验证结果、风险与文档维护边界 |
| `Companion/README.md` | Companion 架构、Controller、安全边界和共享 H618 硬件库入口 |
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

主站前端构建：

```powershell
cd PonyChat-Website\Main\frontend
npm run build
```

仓库当前使用集中管理的前端依赖目录；若 Node 的 ESM 解析无法通过 `NODE_PATH` 找到 `vite`，应先让本目录的 `node_modules` 指向已安装依赖，再运行构建，不要把依赖或 `dist/` 提交到 Git。

## 密钥

仓库内模型配置只保留 `${ENV_NAME}` 占位符。真实密钥通过 `.env`、systemd `EnvironmentFile` 或部署环境变量注入，不提交到 Git。

已有密钥如果曾进入本地 Git 历史，上传 GitHub 时应使用干净快照分支或重写历史，避免把旧提交中的密钥带到远程。

