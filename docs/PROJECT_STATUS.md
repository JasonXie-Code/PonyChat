> 2026-09-09 运行位置更新：聊天、语音网关、搜索和日志迁至 `P:\PonyChat`；App 5.6.36/376 通过 `39.101.74.217:80` 连接本机，官网转发本机最新 APK。当前部署以 [SERVER.md](../SERVER.md) 和迁移验收记录为准，下文旧日期盘点保留历史语境。

> 2026-09-06 更新：普通对话升级为统一 Agent 对话与记忆架构，游戏及锁分分步调用接入 Harness，APK 5.6.20/360。详见 [设计](design/普通对话Agent记忆架构.md) 与 [本次验收](../Backend/Agent-Test/reports/unified-agent-upgrade-20260906.md)。

# PonyChat 项目状态盘点

> 盘点日期：2026-08-09
> 事实来源：当前 Git 工作树、构建配置、后端路由、模块入口与最近提交。生产环境状态仍以实际部署和健康检查为准。

## 总体结论

PonyChat 已形成 Android 主客户端、FastAPI 后端、Vue 主站/管理后台和 Companion 设备执行端四条主线。Android 对话、长期记忆、主动消息、语音、Galgame/锁分、小游戏和角色大厅已具备完整代码链路；Companion 已从模拟器原型推进到 K2B/H618 Android 12 实机验证，但仍是开发验证版本，不应表述为量产完成。

| 模块 | 技术基线 | 当前状态 | 主要入口 |
| --- | --- | --- | --- |
| Android App | Kotlin、Jetpack Compose，SDK 34，minSdk 24 | `5.6.16` / `356`；主要产品体验端 | `Android-App/README.md` |
| Backend | Python、FastAPI、SQLite WAL | 对话、记忆、主动消息、角色/素材、语音、陪玩、小游戏、管理 API 可用 | `Backend/__main__.py`、`Backend/routes/` |
| Main Web | Vue 3、Vite 6、Pinia、Vue Router | 官网、轻量聊天、管理后台、PonyDrive | `PonyChat-Website/Main/PROJECT.md` |
| Companion | Kotlin Android + Python Controller + Mobile MCP | `0.1.0`；K2B/H618、QQ 私聊和设备控制已完成首轮实机闭环 | `Companion/README.md` |
| 独立子站 | Vue/静态站/FastAPI | MBTI、LLM、TTS、MLP Songs 独立维护 | `PonyChat-Website/` 各子目录文档 |

## 当前产品边界

- Android 是完整体验端；Web 聊天不承诺与 Android 的长期关系、语音、Galgame/锁分和陪玩能力完全同构。
- 普通聊天、Galgame/锁分、剧情规划是不同数据边界；游戏事件不应混入普通聊天长期记忆。
- Companion 是受签名和系统能力约束的设备执行端。当前完成的是开发板验证，不等于量产签名、OTA、长期稳定性、完整审计和自主恢复全部完成。
- 后端默认面向公网模型服务；模型、TTS 和部署事实可能随环境配置变化，代码默认值与生产值需要分别核对。
- 真实密钥仅通过 `.env`、systemd `EnvironmentFile` 或部署环境注入，不进入项目文档和 Git。

## 工程盘点

### 已验证的基线

- 4 个超过 1500 行的 Vue 文件已拆分，模板、逻辑和 scoped 样式保持原接口：
  - `CharactersSection.vue`：1397 行；角色纯逻辑在 `charactersSectionModel.js`，样式在 `styles/CharactersSection.css`。
  - `ConversationsSection.vue`：1320 行；样式在 `styles/ConversationsSection.css`。
  - `ConversationLogsSection.vue`：1083 行；样式在 `styles/ConversationLogsSection.css`。
  - `DriveView.vue`：1439 行；文件类型与格式化逻辑在 `driveViewModel.js`。
- 主站生产构建通过：Vite 转换 116 个模块并生成 `dist/`。
- 主站页面和管理后台子页已改为 Vue Router 路由级动态导入。生产入口 JS 从 803.13 kB 降至 120.09 kB（gzip 46.83 kB），最大延迟加载 JS 为终端页 295.59 kB；所有 chunk 均低于 Vite 500 kB 提示阈值。

### 当前重点风险与后续工作

1. Companion 量产化：产品签名、BSP 固化、OTA、设备内 Controller、长期保活、敏感动作确认、完整审计和稳定性压力测试。
2. 前端体积：源文件与路由 chunk 拆分已经完成；后续新增页面必须继续使用动态导入，并在生产构建中关注入口和单路由 chunk 是否重新超过 500 kB。
3. 陪玩实时链路：Android 存在 `/ws/companion/realtime` 使用方，后端当前未挂载同名路由；不要把它描述为已上线。
4. 文档漂移：`PROJECT.md` 是产品与能力总览，本文是日期化工程快照；专题文档必须通过 `docs/README.md` 标注的状态判断用途。
5. 生产验证：数据库、模型、TTS、域名和服务状态属于易变信息，部署前必须按 `SERVER.md` 和部署 README 现场核验。

## 文档维护范围

本轮维护覆盖 PonyChat 自有的项目说明、模块 README/PROJECT/ROADMAP、部署/API 文档、设计、审计和测试规范。

以下内容不作为项目文档改写：

- `Backend/data/` 下的角色设定、知识库和测试语料；
- `PonyChat-Website/MLP-Songs-AUTO/alphaTab-src/` 等第三方源码及其许可证/README；
- `docs/archive/`、`change-log/` 等历史记录；
- `artifacts/`、`tmp/`、`temp/`、构建日志和生成产物。

完整索引与状态定义见 `docs/README.md`。
