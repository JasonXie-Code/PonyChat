> 2026-09-09 运行位置更新：聊天、语音网关、搜索和日志迁至 `P:\PonyChat`；App 5.6.36/376 通过 `39.101.74.217:80` 连接本机，官网转发本机最新 APK。当前部署以 [SERVER.md](../SERVER.md) 和迁移验收记录为准，下文旧日期盘点保留历史语境。

# PonyChat 文档索引

> 最后复核：2026-08-14

本索引只覆盖 PonyChat 自有项目文档。文档分为“当前事实”“规范/测试基线”“计划/审计记录”和“历史归档”，阅读时不要把规划或旧审计结论当成当前实现。

## 状态定义

| 状态 | 含义 |
| --- | --- |
| 当前 | 随代码持续维护，可用于构建、部署、接口或现状判断 |
| 规范 | 产品/交互/测试基线；实现变化时必须同步，但不代表所有条目已上线 |
| 计划 | 实施方案或阶段记录；完成情况以 `PROJECT_STATUS.md` 和代码为准 |
| 历史 | 仅供追溯，原则上不再改写 |

## 当前事实与操作入口

| 文档 | 状态 | 用途 |
| --- | --- | --- |
| `../README.md` | 当前 | 仓库入口、本地验证和密钥规则 |
| `../PROJECT.md` | 当前 | 产品定位、能力边界、目录和长期方向 |
| `PROJECT_STATUS.md` | 当前 | 2026-08-09 工程盘点、验证结果和风险 |
| `operations/local-backend-migration-20260909.md` | 当前 | 本机迁移、CN IP、APK 下载、完整性与清理验收 |
| `../SERVER.md` | 当前 | 生产域名、服务器与运维说明；使用前现场核验 |
| `../Android-App/README.md` | 当前 | 手机版/主机版环境定义、Android 构建、模块与测试 |
| `../Backend/database/README.md` | 当前 | SQLite 路径、初始化和数据边界 |
| `../Backend/deploy/README.md` | 当前 | 后端部署与健康检查 |
| `../Backend/deploy/REMOTE_TESTING.md` | 当前 | 远程测试隔离要求 |
| `../Companion/README.md` | 当前 | Companion 文档入口与快速开始 |
| `../Companion/docs/PROJECT_OVERVIEW.md` | 当前 | Companion 项目定位、能力、结构、安全要求和路线 |
| `../Companion/docs/OPERATIONS_GUIDE.md` | 当前 | Companion 构建、安装、QQ、悬浮窗和角色回复操作 |
| `../../Hardware/H618-K2B/docs/H618_TROUBLESHOOTING.md` | 当前 | 共享硬件库中的 H618 固件、显示、scrcpy、QQ 和 Controller 排障 |
| `../Companion/docs/ARCHITECTURE.md` | 当前 | Companion 分层、安全与验证阶段 |
| `../../Hardware/H618-K2B/docs/H618_COMPANION_QQ_LESSONS_2026-08-14.md` | 当前 | 共享硬件库中的 H618、Companion、QQ、角色会话、Recovery 与 scrcpy 实机经验 |
| `../Companion/controller/README.md` | 当前 | Mobile MCP Controller 运行与测试 |
| `../Companion/device-overlay/README.md` | 当前 | 自研设备 RRO 边界 |
| `../Companion/验收清单.md` | 规范 | Companion 数字伴侣、手机操作、安全与发布门槛 |
| `../PonyChat-Website/Main/PROJECT.md` | 当前 | 主站、管理后台、PonyDrive 与构建结构 |
| `../PonyChat-Website/Main/deploy/server-usa/DEPLOY-STATIC-WEB.md` | 当前 | 主站静态部署 |
| `../PonyChat-Website/LLM/README.md` | 当前 | OpenAI-compatible 静态聊天站 |
| `../PonyChat-Website/TTS/PonyChat-Voice-Lab.md` | 当前 | CosyVoice 语音站与兼容边界 |

## 后端专题与测试工具

| 文档 | 状态 | 用途 |
| --- | --- | --- |
| `../Backend/docs/galgame_tiered_memory_api.md` | 当前 | Galgame 分层记忆 API |
| `../Backend/docs/suggest_questions_api_removed.md` | 历史 | 已移除建议问题 API 的兼容记录 |
| `../Backend/Agent-Test/README.md` | 当前 | Agent 回复测试工具 |
| `../Backend/Agent-Test/goose_reply_test_prompt.md` | 规范 | 测试提示词；修改会影响测试语义 |
| `../Backend/tests/test-copy.md` | 规范 | 后端测试复制/执行参考，不是产品说明 |

## 产品设计与测试基线

- [普通对话辅助表达规则](design/普通对话辅助表达规则.md)：emoji/图片表情包的场景评分、角色节奏、用户偏好、去重与 Agent 执行标准。
- `design/`：普通聊天、剧情、Galgame/锁分、Android 模式、中国象棋与滚动行为规范。
- `test/测试流程.md`：统一测试入口。
- `test/普通对话模式角色测试达标卷 - *.md`：上下文、场景位置、记忆召回和解剖学正确性达标卷。
- `test/象棋测试达标卷 - 对局记忆.md`：中国象棋对局与跨局记忆基线。

这些文档属于“规范”：保留详细验收项，不以最近修改日期推断功能是否已完成。

## 计划与审计

- `plans/admin-refactor-plan.md`、`plans/voice-message-implementation-plan.md`：实施计划与设计决策；当前实现以代码和工程盘点为准。
- `audits/`：数据完整性、边界保护、键盘、模块化与防数据丢失审计。
- `audits/workflows/verify_galgame_persistence.md`：Galgame 持久化验证流程。

## 独立子项目文档

- `../PonyChat-Website/MBTI/`：MLP/Standard 的 README、PROJECT、ROADMAP、评分与权利说明。
- `../PonyChat-Website/MLP-Songs/`：歌曲站 PROJECT/ROADMAP。
- `../PonyChat-Website/MLP-Songs-AUTO/README.md`：自动化歌曲实验入口；其 `alphaTab-src/` 属第三方源码，不纳入 PonyChat 文档维护。
- `../Android-App/icon-packs/README.md`、`../Android-App/signing/README.md`：图标包和签名配置专题。

## 非维护范围

- `Backend/data/` 内角色设定、RAG 知识库和测试语料；
- 第三方源码、README、许可证和字体说明，尤其是 `MLP-Songs-AUTO/alphaTab-src/`；
- `archive/`、`../change-log/` 和网页历史快照；
- `artifacts/`、`tmp/`、`temp/`、构建日志、生成的 `dist/` 和 APK；
- `.env`、数据库、备份、运行日志和任何真实密钥。

## 维护规则

1. 先更新代码旁的模块 README，再同步根 `README.md`、`PROJECT.md` 和 `PROJECT_STATUS.md`。
2. API、路径或部署方式变化时同步专题文档，并运行链接/命令核查。
3. 设计或测试基线仍有效但没有功能变化时，只更新复核日期和状态说明，不改写历史结论。
4. 易变的生产信息必须在执行前现场验证；文档中的日期化快照不能替代健康检查。
5. 不把密钥、数据库、运行日志或生成产物写入文档和 Git。
6. 后端聊天链路的提示词必须集中维护在 `P:\PonyChat\Backend\chat_modules\Prompts.py`；不得在其他业务代码中新增或散落重复的提示词正文。需要复用时应从该模块导入或调用既有构建函数，变更时同步更新相关测试与说明。
