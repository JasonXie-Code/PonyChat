# 2026-06-27 Change Log

## Android 普通聊天恢复

- Android 继续收紧普通对话刷新合并逻辑，确保本地 pending 用户消息在服务端快照暂时缺失时仍保留在 UI 与运行态消息列表中。
- `NormalPendingUserMergeInstrumentedTest` 补充覆盖服务端后续返回权威用户消息后的去重与序号回填，避免同一条用户消息重复出现。
- ChatViewModel 和 runtime ops 跟随普通聊天恢复路径调整，减少刷新、同步和本地临时消息之间的状态漂移。

## 普通聊天生命周期

- 后端 `normal_lifecycle`、事实证据标记和检索关键词整理继续更新，让普通回复在处理当前动作、场景位置和角色状态时更稳。
- 角色路由接口继续调整，配合普通聊天里的角色资料、公开角色和当前用户角色关系。
- `test_normal_four_stage_pipeline.py` 和 `test_normal_single_conversation.py` 扩充当前轮事实、单会话普通回复和场景锚定相关断言。

## 文档整理

- 将 `Backend/tests/测试流程.md` 移动到 `docs/test/测试流程.md`，把测试流程文档从测试代码目录中抽出，减少后端测试目录噪音。
- Android 构建配置继续跟随 instrumented test 与拆分后的聊天测试结构调整。

