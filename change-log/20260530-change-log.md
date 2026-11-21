# 2026-05-30 Change Log

## 普通聊天历史权威化

- Android 普通聊天改为只向服务端发送最新用户消息批次，避免全量会话反复回写造成历史覆盖或竞态。
- 后端 `chat_modules/service.py` 会在普通模式下按服务端数据库历史重建请求上下文，并合并最新用户增量。
- Android 历史页改为分页读取服务端消息，新增 `isLoadingMoreHistory` 区分首次加载与向前翻页。
- `CharacterRepository.saveConversation()` 已保留兼容入口但跳过旧式整段回写，服务端消息表成为普通聊天权威来源。

## 删除与通知同步

- 新增 `POST /api/messages/hide`，按用户、角色、会话和消息 ID 软隐藏单条普通聊天消息，并写入删除审计。
- Android 删除消息时携带会话 ID，先本地隐藏，失败时回滚。
- WebSocket / Job 轮询完成通知改为按消息 ID 或 outbox ID 生成通知 key，同一角色的多段回复不再被压成一条。
- `JobPollWorker` 不再按角色去重 proactive 批次，保证多条主动消息都能展示。

## 主动与定时消息

- 定时 follow-up 和 proactive task 的助手回复会按空行拆成多个消息段写入数据库。
- 每个段落独立入 outbox / proactive 推送，并保持连续 `sequence_number` 与 `previous_message_id` 链。
- 后端持久化完成后按每段 enqueue `chat_complete`，客户端可以逐条收到完成事件。

## 普通模式表达策略

- `normal_mode_policy` 升级到 `2026-05-29-normal-agency-v6`。
- 对“描写心理活动 / 环境 / 看到的内容 / 动作表情 / 只描写感受”等非侵入式写法请求，规划器会按表达调度处理，不再误判为越界指令。

## Voice Lab

- `PonyChat-Website/TTS/` 升级到 FastAPI `0.4.0`，引入 Redis 任务队列、后台 worker、任务轮询与 `/jobs/*` 下载接口。
- 克隆、设计、合成统一使用 Qwen3-TTS 1.7B 系列模型，默认 bfloat16 + TF32 + SDPA。
- 新增 CustomVoice 预置说话人、`speaker:<name>` 音色、情绪/风格 `instruct`、分段情绪合成和动态 token 上限。
- 前端重做声音列表、参数档位、任务状态和播放器体验；说明见 `PonyChat-Website/TTS/PonyChat-Voice-Lab.md`。

## LLM 静态站

- 新增 `PonyChat-Website/LLM/`，提供本地 OpenAI-compatible LLM 聊天页面。
- 支持 `/v1/models`、`/v1/chat/completions` 流式调用、图片输入、Markdown、KaTeX、代码高亮与思维链折叠。

## 文档

- 更新 `PROJECT.md`、`Android-App/README.md`、`SERVER.md`。
- 新增 `PonyChat-Website/TTS/PonyChat-Voice-Lab.md` 与 `PonyChat-Website/LLM/README.md`。

## 文档归档规则

- 根目录 `ROADMAP.md` 退役并删除。
- 长期产品定位、阶段规划、模式边界、社区策略、远期功能规划统一沉淀到 `PROJECT.md`。
- 每日增量和流水账统一按日期写入 `change-log/YYYYMMDD-change-log.md`。
- 2026-04-11、2026-04-20、2026-04-21、2026-04-26、2026-04-27、2026-05-18 的旧 ROADMAP 顶部流水账已拆成独立 change-log 文件。

## 验证

- 待提交前运行后端 pytest、Android Kotlin 编译和前端静态语法检查。
