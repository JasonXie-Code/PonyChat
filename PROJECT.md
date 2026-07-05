# PonyChat 项目介绍

> **最后更新日期**：2026-07-05（同步 GitHub 上传前的代码现状：Android 5.6.13、斗地主/象棋小游戏、CosyVoice 语音部署、密钥环境变量化）

> **产品标语**：接入最先进的智能网络，开启你的故事
>
> **产品简介**：她记得你说过的话，记得你输掉的那局，记得你不开心的那天。她不等你开口，她先找来。陪你打牌，陪你上战场；你倒下，她第一个跑来。角色虚拟，体验存心。
>
> **产品目标**：从 AI 聊天平台演进为「追平网恋体验」的 AI 伴侣产品
>
> **关系优先级**：核心价值在 **人与角色** 的互动与长期关系，**不是**人与人的泛社交；大厅、关注、二创、角色主页等能力仅服务于发现角色与供给。

**IP 定位**：长期聚焦 **My Little Pony** 世界观与角色；不做泛二次元扩圈。

---

## 阶段总览

| 阶段 | 名称 | 状态 | 说明 |
| --- | --- | --- | --- |
| — | 基础能力 | 已完成 | 后端、Android、主站、管理后台与核心聊天链路已打通 |
| 一 | 长期记忆系统 + 合规基础 | 已完成 | 记忆提取/注入、上下文摘要、设置开关与合规提示 |
| 二 | 主动消息推送 | 已完成 | 角色可主动找用户；定时 follow-up、多段推送和通知顺序持续优化 |
| 三 | 聊天陪玩 + 语音 | 进行中 | 普通聊天语音回复已接入 CosyVoice；经典陪玩、ASR/TTS 可用；Android 侧 Omni 实时桥接代码存在，但后端 `/ws/companion/realtime` 尚未挂载；旧 Qwen3TTS / OmniVoice 代码保留为兼容或历史参考，本机 Qwen3TTS 自启已停用，不再作为默认部署依赖 |
| 四 | 音乐共同欣赏 | 待开始 | MediaSession 监听 + 记忆联动 + 主动消息 |
| 五 | 视频共同讨论 | 待开始 | 链接解析 + 截图/画面讨论 |
| 六 | 游戏 AI 真实参与 | 规划中 | 已有 Android 中国象棋与斗地主小游戏雏形；远期再推进真实游戏画面识别、AccessibilityService 操作和第二台设备控制 |

---

## 产品模式（三大板块）

| 模式 | 说明 | 客户端 | 备注 |
| --- | --- | --- | --- |
| **对话模式 + 陪玩** | 与小马角色自然对话；包含长期记忆、主动消息、语音回复与轻量陪玩 | 主要 **Android**；Web 仅提供轻量普通聊天 | 主对话统一使用 **DeepSeek V4 Flash**（`model_config.json` 中 `active_model`，所有 `for_chat`/`for_memory`/`for_summarize` 任务均指向该模型）；识图走 **豆包 2.0 Mini**；陪玩固定 **豆包 2.0 Mini**。模型大厅保留多供应商配置，但当前生产实际只走上述两条主线。普通聊天以服务端数据库消息表为权威，Android 只上传最新用户批次，历史按服务端分页加载。 |
| **游戏 / 锁分（Galgame）** | 好感度导向的 Galgame；锁分含体征与死亡条件等 | **Android** | **游戏模式**全体用户可用；**锁分模式**仅 **developer / admin**（客户端长按进入 + 服务端校验）。分步提示词位于 `Backend/galgame/seq_prompts/`：`step_00` 共用，第 1～9 步为导演至选项，第 10 步为角色短期记忆改写。游戏/锁分会话与普通长期记忆隔离。 |
| **剧情模式** | 与角色进入独立剧本，探索结局 | 规划 **Android** 优先 | 先选角色再选剧本；剧本定关键节点，AI 填细节；结局重玩重置，**不回写**长期记忆。 |

**Web 端**：主站负责落地页、下载、轻量网页聊天、MBTI 入口、项目近况与管理后台；不提供与 Android 完全同构的角色长期关系、语音消息、Galgame/锁分和陪玩体验。完整产品形态以 **Android** 为准。

---

## 平台与权限摘要

- **客户端策略**：**仅 Android** 作为主要体验端；当前不考虑 iOS。
- **Android 版本线索**：仓库当前 `Android-App/app/build.gradle.kts` 为 `versionName = "5.6.13"`、`versionCode = 353`（以发布包与服务端 `/api/app-version` 为准）。
- **角色创建**：用户均可创建角色，默认 **私有**；公开角色走角色大厅与审核/运营流程。
- **官方角色源**：`System` 账号创建或保存的角色会标记为官方源。用户添加官方角色时走引用机制；官方源 ID 迁移会同步更新用户引用 ID 与相关对话、记忆、Galgame、主动消息、图片上下文等引用表。
- **游戏与长期记忆**：游戏/锁分会话与普通对话 **隔离**，游戏事件 **不** 混入普通聊天长期记忆。

## 模式边界

| 模式 | 长期记忆 | 主动消息 | 陪玩 | 主要入口 |
| --- | --- | --- | --- | --- |
| 聊天模式 | 是 | 是 | 是 | Android；Web 轻量普通聊天 |
| 游戏模式（Galgame） | 否 | 否 | 否 | Android |
| 锁分模式 | 否 | 否 | 否 | Android，developer / admin |
| 剧情模式 | 独立虚拟线 | 否 | 否 | 规划中 |

---

## 当前核心能力

- **后端**：FastAPI、SQLite WAL、邀请码 + HMAC Token、WebSocket 多端同步、Job 后台任务、定时备份、记忆提取与注入、主动消息调度、模型大厅、Galgame / 锁分分步、小游戏象棋 API、`memory/mlp_rag`、管理后台 API、素材 BLOB 存储、语音消息状态与短期音频缓存。
- **Android（Compose）**：角色列表与角色大厅、角色主页、角色编辑、SSE / Job、普通聊天历史分页、语音气泡、上下文摘要、Galgame / 锁分 UI、中国象棋、斗地主、语音输入输出、图片与多模态、会员与配额、智能路由与网络检测、本地缓存、设置与合规弹窗。
- **普通聊天历史**：服务端消息表为权威；Android 请求只带最新用户消息批次。`POST /api/messages/hide` 支持按用户、角色、会话与消息 ID 软隐藏单条普通聊天消息并写入删除审计。
- **语音回复链路**：普通对话导演决定文本/语音；语音进入 `normal_voice_reply` 生成口语化脚本，按句携带 `emotion_prompt`。默认后端部署通过 Server-USA 的 CosyVoiceTTS 网关调用官方 DashScope / 百炼 CosyVoice API；角色参考音频先注册成可复用的 `cosy_voice_id`，后续合成直接复用，故障或配方变化时才用 PonyChat 保存的参考音频重新注册。旧 Qwen3TTS recipe 路径仍在代码中作为兼容层，但不再是默认 systemd 部署。网页端试听可开关手机拾音模拟；Android 收到官方原音后在本地做手机拾音处理。括号旁白可作为文本段展示，emoji 与不适合朗读内容会从 TTS 文本中清理。服务端保存 `voice_status`、`voice_id`、`voice_job_id`、`voice_cache_key`、`tts_text`、`transcript`、`text_fragments`、`voice_sentences` 等状态，并支持缓存取回与 ACK 清理。每条成功生成的语音消息计入今日积分，默认扣 `10` 分；同一回复多条语音按条累计。
- **角色主页与大厅**：公开档案页展示封面、头像、作者、个性签名、人气数据、相册、16 人格、性格、兴趣和角色档案；封面/相册支持全屏预览与下载。角色主页素材由角色编辑页维护；喜欢数据由后端表真实计数并限制同日重复点赞。
- **官方角色与迁移**：官方源动态识别，不再只依赖固定 ID 列表；管理后台创建/编辑角色可维护角色 ID。修改已有角色 ID 时执行安全迁移而非硬改主键。Jason 名下旧版同名“紫悦”“碧琪”已在生产环境融合到官方引用 ID，旧角色隐藏并保留 `mergedInto`。
- **陪玩**：经典路径使用 `/api/companion/frame`、`/api/companion/stream`、`/api/companion/end`；ASR / TTS 使用 `/ws/speech/*`、`/ws/tts/*`。Android 的 `OmniRealtimeBridge` 默认路径为 `/ws/companion/realtime`，当前后端未挂载该路由。
- **检索与对话**：普通聊天可注入 MLP RAG（`Backend/data/mlp/`，`PONYCHAT_MLP_RAG=0` 关闭）；游戏 / 锁分不注入 RAG。纯文字追问可经 `image_context_store` 注入近期识图摘要。普通模式可选 IM 式回复延迟（`Backend/chat_modules/im_reply_delay.py`）。
- **推理后端**：`Backend` 仅对接云端 / 公网 Chat Completions 类 API。**当前生产模型**：主回答与所有核心任务（对话、路由、导演、记忆、摘要）统一使用 **DeepSeek V4 Flash**（`deepseek-v4-flash`，`model_config.json` 中 `active_model`）；识图使用 **豆包 2.0 Mini**（`doubao-2-0-mini`，`for_web_search`）；陪玩固定 **豆包 2.0 Mini**；AI 绘画使用 Banana Pro（代理 Gemini 3 Pro Image）。模型大厅保留 Qwen、OpenRouter、xAI Grok 等多供应商配置可回退，但当前生产事实只走 DeepSeek + 豆包 Mini 两条主线。已移除内置 LocalLLM、Ollama / llama-server 回环 Provider 与相关分步特例。
- **Web 语音实验室**：`voice.ponychat.org/cosyvoice` 为 Server-USA 上的 CosyVoiceTTS 在线站，调用官方 DashScope / 百炼 CosyVoice HTTP API；旧 `/qwen3tts` 跳转到 `/cosyvoice/`，旧 `/omnivoice` 返回 410。仓库仍保留本机 Qwen3TTS 脚本供历史回溯或本地实验，默认不上传其运行数据和自动保存文件。
- **LLM 静态站**：`PonyChat-Website/LLM/` 面向 OpenAI-compatible `/v1/chat/completions` 与 `/v1/models`，支持流式输出、思维链折叠、Markdown/KaTeX、代码高亮与图片输入；公网链路见 `SERVER.md` 与 `PonyChat-Website/LLM/README.md`。
- **运维要点**：生产服务器与大桥信息见 `SERVER.md`；各网站根目录的 `deploy.py` 负责只部署对应网站到对应远端目录，并使用远端 manifest 做增量同步。后端部署脚本写入 `.deploy_revision`，启动时读取 deploy token，避免旧进程误报新版本。

## 模型策略

- **生产主回答模型**：**DeepSeek V4 Flash**（`deepseek-v4-flash`），`model_config.json` 中 `active_model`。所有核心任务（聊天 `for_chat`、路由 `for_chat_router`、导演 `for_chat_director`、记忆 `for_memory`、摘要 `for_summarize`）统一指向该模型。主对话/游戏通过 `resolve_auth_and_quota` 中 `model_manager.get_model_for_task("chat")` 智能路由固定使用该模型，与模型大厅用户所选模型无关。
- **识图模型**：**豆包 2.0 Mini**（`doubao-2-0-mini`），标记 `for_web_search`，支持视觉多模态。普通对话中图片由该模型预处理为文本描述后注入主回答上下文（主回答模型 DeepSeek V4 Flash 本身无视觉能力）。
- **陪玩模型**：固定 **豆包 2.0 Mini**（`COMPANION_LLM_MODEL_ID = "doubao-2-0-mini"`），不随聊天模型大厅变化。
- **AI 绘画**：Banana Pro（`banana-pro`，代理 Gemini 3 Pro Image Preview），标记 `is_draw`。
- **代码/开发用**：DeepSeek V4 Flash Code（`deepseek-v4-flash-code`），隐藏模型，使用独立 API Key。
- **代码回退默认**：`DEFAULT_FALLBACK_MODEL_ID = "doubao-2-0-lite"`，仅在 `model_config.json` 不存在或清单为空时作为冷启动占位，不代表生产实际使用。
- **语音链路**：语音回复由导演决定是否生成，TTS 语言读取导演 `reply_language`；当前生产 TTS provider 为 `cosyvoice`，旧 `qwen3tts:<官方角色>` 会兼容映射到对应 `ponyvoice:<角色>` 配方。
- **供应商清单**：`Backend/conf/models/` 下保留 Doubao、DeepSeek、Qwen DashScope、xAI、OpenRouter、apiyi、poloai 等多供应商配置片段，热加载与路由由 `model_manager.py` 统一处理。当前 xAI Grok 系列已禁用 (`enabled: false`)，Qwen/OpenRouter 等可用但非核心链路。

---

## 角色大厅与社区延伸

**核心**：人与 **角色（AI）** 的互动与长期关系优先，**不是**泛社交网络。大厅、关注、二创、角色主页和素材展示都服务于发现角色与供给。

- **已落地/进行中**：公开角色、官方角色源、角色主页、封面/头像/相册、16 人格、角色档案、喜欢计数、素材上传、管理后台角色 ID 迁移。
- **可做优先**：关注创作者、收藏夹 / 清单、标签搜索、匿名热度、版本与更新日志、Fork 带署名、运营位。
- **后置**：评论、协作、活动运营；这些能力需要审核、治理与滥用处理配套。
- **暂不建议**：全站时间线、泛 @、站内私信，除非同步建设完整社区治理。

---

## 未来规划（摘录）

- **角色状态**：按角色设定生成作息/状态；用户深夜发消息可「吵醒」角色，影响回复语气与 IM 拟人延迟（与 `im_reply_delay` 联动）。
- **剧情模式**：见 `docs/design/剧情模式设计.md`；与普通聊天独立，不回写长期记忆。
- **音乐共同欣赏**：`MusicWatcher` + `POST /api/activity/music`，与记忆、主动消息联动。
- **视频共同讨论**：轻量版链接解析 + `POST /api/activity/video`；完整版可复用陪玩截图与弹幕 UI。
- **真机游戏 AI**：棋牌方向以 VLM 读牌、JSON 决策、AccessibilityService 为第一步；动作游戏方向采用慢层策略 + 快层检测的分层架构；第二台设备控制端为远期产品叙事，成本与合规需单独立项。
- **多平台**：当前不做 iOS；桌面端仅作为远期可能性。

---

## 持续优化项

- **语音**：角色音色配置、CosyVoice 注册缓存、TTS 稳定性、语音/文本选择策略、多段语音计费与时序、历史消息回退展示。
- **记忆**：分层与衰减、用户侧查看 / 删除、图像上下文与普通聊天的更稳注入。
- **陪玩**：更多场景、切应用后麦克风策略、实时路由挂载、断线重连、操作类陪玩。
- **角色大厅**：官方源治理、角色 ID 迁移审计、公开档案展示、素材审核与热度体系。
- **工程**：`ChatScreen.kt`、部分 Web/admin 组件和后端路由仍有体量较大的文件，后续宜继续拆分子模块。

---

## 仓库目录结构（约定）

| 路径 | 说明 |
| --- | --- |
| `Backend/`、`Android-App/` | 后端（FastAPI）与 Android 客户端；普通聊天历史由服务端权威重建，Android 只发最新用户增量，并通过 `/api/messages/hide` 做单条消息软隐藏 |
| `Backend/chat_modules/` | 普通聊天调度、规划、非流式回复、语音回复、语音消息状态、图片上下文等 |
| `Backend/galgame/` | Galgame/锁分：响应解析、体征级联、重试、历史归一化；`galgame/seq_prompts/` 为分步提示词；`step_10_char_memory_update.py` + `galgame/memory.py` 负责角色短期记忆 |
| `Backend/memory/` | 上下文摘要、记忆固化/提取、分层调度、MLP RAG（实现于 `memory/mlp_rag.py` 等） |
| `Backend/routes/` | API 路由，包括聊天、角色、角色大厅、素材、模型、主动消息、管理后台等 |
| `Backend/scripts/` | 一次性维护脚本；锁分体征情绪链轻量校验见 `verify_vitals_emotion_chain.py` |
| `Backend/docs/` | 后端专题说明（如 `galgame_tiered_memory_api.md`、已移除 API 记录等） |
| `docs/plans/admin-refactor-plan.md` | 管理后台角色合并与素材管理记录；当前素材以 `media_assets.file_data` BLOB 存储，经 `/api/admin/assets/{id}/file` 返回 |
| `Backend/deploy/` | 生产部署：`deploy_backend_server_usa.py` 增量同步 Backend 至 Server-USA 并重启服务 |
| `Backend/scripts/launch/` | 本地启动与便携部署：`AAA_launch_backend.py`、`AAA_install_debug_app.py`、`AAA_deploy_portable.bat` |
| `AAA启动后端.bat`、`AAA安装调试App.bat` | 根目录快捷入口：调用便携 Python 与 `Backend/scripts/launch/` 中脚本 |
| `PonyChat-Website/Main/frontend/` | 主站、轻量网页聊天、管理后台等 Web 前端（Vite + Vue）；构建产物由静态站部署 |
| `PonyChat-Website/Main/deploy/server-usa/` | 主站生产部署脚本与 Nginx 配置（Server-USA `154.17.23.237`；详见 `SERVER.md`） |
| `PonyChat-Website/Main/deploy/releases/` | 发布用 APK（`PonyChat.apk`），供 `GET /download/apk` |
| `PonyChat-Website/MBTI/` | MBTI 子站集合：`MLP/`（小马 MBTI）、`Standard/`（标准 MBTI）、`Common/`（共享组件） |
| `PonyChat-Website/MLP-Songs/` | MLP 歌曲相关小项目 |
| `PonyChat-Website/TTS/` | PonyChat CosyVoiceTTS：Server-USA 在线站点，调用官方 DashScope / 百炼 CosyVoice HTTP API；旧 Qwen3TTS / OmniVoice 入口仅保留兼容或历史说明，生产默认不依赖本机 GPU 隧道 |
| `PonyChat-Website/LLM/` | 本地 LLM 静态聊天站：OpenAI-compatible API、流式输出、思维链折叠、Markdown/KaTeX 与图片输入 |
| `Backend/data/mlp/` | 小马知识库数据与脚本（RAG；`misc/project_paths.mlp_data_dir` 会解析到此） |
| `docs/design/` | 产品设计类 Markdown |
| `change-log/` | 每日增量和流水账，文件名格式 `YYYYMMDD-change-log.md` |
| `scripts/ops/` | 常用本地运维脚本，如便携部署、备份恢复和服务器 Backend 对比 |
| `misc/` | 路径兼容层与归档杂项；`project_paths.py` 和便携工具链 `misc/tools/` 保留在此，历史脚本/素材在 `misc/archive*` |
| `var/` | 运行时日志、证书等（**不入库**，见根 `.gitignore`）；`var/ChatMonitor/` 为 ChatMonitor 同步服务器 `.chatlogs` 的本地落盘 |

**运维 / 密钥**：私钥与 `servers.json` 等仍以工作区 **`ServerKeys/`** 为唯一来源；全文说明见本项目根目录 [`ServerKeys.md`](ServerKeys.md)。

---

## 商业化里程碑

| 节点 | 对应阶段 | 行动 |
| --- | --- | --- |
| 阶段一完成 | 长期记忆 | 上线「她真的记得你」宣传，测试 Pro 付费转化率 |
| 阶段二完成 | 主动消息 | 推广「会主动找你的 AI 伴侣」 |
| 阶段三完成 | 聊天陪玩 + 语音 | 语音陪伴、陪玩短视频传播；陪玩可作为高阶功能 |
| 角色主页成熟 | 角色大厅 | 推动官方角色、用户角色与素材供给 |
| 阶段六·第一步 | 棋牌陪玩 | 验证「她真的在玩」 |
| 阶段六·第二步 | 动作游戏 | 核心传播素材 |
| 硬件捆绑上市 | — | 定制设备 + 订阅双轨（远期） |
| 全部完成 | — | 订阅制 + 虚拟礼物 + 硬件 |

---

## 变更记录规则

根目录旧规划流水账文件已退役。本文只保存稳定产品定位、长期规划、模式边界与目录索引；日常流水账按天写入 `change-log/YYYYMMDD-change-log.md`。主站「项目近况」页面根据 `change-log/` 做面向用户的摘要，不替代每日日志。
