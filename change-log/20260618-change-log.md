# 2026-06-18 Change Log

## 模块拆分

- 将大型普通聊天模块拆分为兼容 wrapper + `*_parts` 结构：`normal_nonstream`、`normal_planner`、`service` 和 `voice_messages` 都拆出按职责命名的 part 文件。
- 保留原模块导入入口，降低外部调用方迁移成本，同时让 handoff router、用户事实提取、SSE 处理、场景判断、事实判断、主规划和语音合成等逻辑更容易单独维护。
- 新增/调整 request context 与相关测试，确保拆分后上下文对象、阶段编号和调试日志仍保持兼容。

## 普通聊天场景与记忆

- 修复 normal planner 场景落地与当前轮锚定问题，减少旧场景、旧群聊和历史记忆覆盖当前消息的情况。
- 调整场景亲密度、事实判断、场景保存、证据标记和检索关键词生成，让普通回复更稳定地围绕当前地点、角色姿态、用户当前动作和可验证事实。
- 修复 Stage 3 气泡数量与回复等级不一致的问题，避免规划层与实际输出层在多气泡回复上脱节。
- 增加 equine anatomy、idle scene stale、unknown mention、scene anchor、story progression intimacy/transition 等矩阵脚本和测试覆盖。

## 管理台与会话日志

- 新增 LLM 调试日志索引器与管理台日志页面，支持扫描 `.chatlogs`、提取模型/用户/阶段/token/状态等字段，并在前端进行检索和查看。
- 管理台会话区新增剧情/普通模式识别、游戏模式展示和按模式清空会话能力。
- 修复公开角色名在管理台会话中的解析，避免只显示 id 或来源不清。
- 修复管理台游戏预览 Markdown 渲染，让剧情内容、选项和格式化文本在后台预览中更接近真实展示。

## 语音、Android 与运行体验

- Android 聊天、导出、历史、记忆、顶部栏、Markdown、Galgame 和输入区继续跟随普通聊天链路调整。
- 后端 voice message、normal voice reply、voice audio cache、web visibility 和 runtime 相关逻辑同步适配新的模块结构。
- 继续推进故事推进与亲密度测试脚本，补充 `run_story_progression_intimacy*` 部署侧入口。

## 文档与工程整理

- 大规模整理历史文档、审计文档、设计文档、计划文档和临时脚本，将旧的 `.docs`、`misc/docs`、`.agent`、`misc/tmp-scripts` 等内容归档到 `docs/archive`、`docs/design`、`docs/audits`、`misc/archive-scripts` 等目录。
- 删除旧的临时模型与远端附件缓存，更新 `.gitignore` 和项目说明，减少仓库根目录噪音。
- 维护部署、诊断、清理测试用户和支持性回复测试脚本，配合新的管理台日志与普通聊天调试流程。

## 测试与质量

- 扩充 normal four-stage pipeline、normal request context、normal step architecture、scheduled followup、voice cache 和 supportive matrix 测试。
- 拆分模块后继续覆盖场景锚点、事实守门、回复气泡数量、故事推进、支持性回复和管理台日志检索等关键路径。
