# 2026-06-17 Change Log

## 聊天路由与关系行为

- 更新普通聊天路由、关系阶段和多角色发言链路，强化 `normal_planner`、`normal_speaker`、`normal_policy`、`normal_postprocess` 与 service 层之间的协作。
- 后端补充会话 DAO、记忆 DAO、角色加载、角色大厅和聊天路由相关逻辑，让角色选择、上下文拼接、关系行为和记忆写入更一致。
- 调整 Galgame director、metadata prompt 与 hints，让剧情模式在角色路由和后续状态生成上更贴合普通模式里的关系判断。
- LLM debug logging、用户事实守门、物种肢体守门和普通回复语言相关测试同步更新，覆盖新的路由与关系行为。

## 剧情推进

- 修复已完成任务后的故事推进问题，避免角色在目标已完成后继续卡在旧任务或重复推进相同节点。
- 普通 planner 与 policy 补充 completed-task 处理规则，让后续回复能承接“任务已经完成”的事实并自然转入下一步。
- 新增 `test_story_progression_completed_task_matrix.py`，并扩充 four-stage pipeline 测试覆盖任务完成后的场景转折。

## MLP 数据库与世界知识

- 新增 `Backend/data/mlp-database` 构建、查询、检查和结构化脚本，加入 episode manifest、manual aliases、Twilight profile 与 `mlp_world.db`。
- 新增后端 `mlp_database` 路由和前端 `DatabaseView` 页面，为 MLP 世界知识查询与调试提供独立入口。
- 新增 `test_normal_setting_memory_recall_matrix.py`，用于验证普通聊天中设定知识、记忆召回和角色回复之间的关系。
- 后续 checkpoint 补充 Pinkie/Twilight profile、query sample、build query result 等数据资产，完善本地知识库调试材料。

## Android 与前端入口

- Android 端调整聊天页、会话历史、角色列表、滚动辅助和通用对话框，配合后端路由与角色大厅能力。
- 新增 `CharacterHallView` 和路由入口，首页与 landing 样式同步补充角色大厅访问路径。
- 管理台会话区继续适配新的聊天/角色信息字段，为后续日志和会话调试打基础。

## 测试与质量

- 更新 normal four-stage pipeline、request context、step architecture、scheduled followup、LLM debug logging、user fact guard 等测试。
- 通过矩阵脚本覆盖关系行为、剧情推进、设定记忆召回和多角色上下文，降低普通聊天链路改动后的回归风险。
