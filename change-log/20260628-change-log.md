# 2026-06-28 Change Log

## 角色资料与注册体验

- Android 角色资料页、角色列表、角色 ViewModel、头像组件和注册页继续调整，改善角色展示与账号入口体验。
- 后端角色对象和管理台角色接口同步适配，保持 App、后台和公开角色数据字段一致。
- 角色头像显示逻辑继续增强，对不同来源的头像和资料字段做更稳的兜底。

## 普通聊天与主动任务

- 普通 planner 的视觉上下文、事实判断、场景保存、证据标记、规划和检索关键词继续强化。
- `normal_voice_reply` 和 runtime 逻辑继续跟随普通对话上下文结构调整。
- 主动任务与 scheduled follow-up 补充分层 follow-up 行为，让主动触达更能承接当前关系、近期对话和长期记忆。
- 新增 `test_proactive_layered_followup.py`，覆盖主动消息分层上下文和 follow-up prompt 的关键规则。
- `test_normal_four_stage_pipeline.py`、`test_normal_request_context.py` 和 `test_scheduled_followup_prompting.py` 跟随普通聊天上下文字段更新。

## 图片与资料数据

- 聊天图片 DAO 继续调整，提升图片路径、缩略图或附件记录在普通聊天链路中的稳定性。
- MLP 数据库临时 `shm/wal` 文件进入当前 checkpoint，后续又在小游戏提交中清理，反映本地知识库调试过程中的数据库状态变化。

## 滚动设计补充

- 普通对话自动滚动设计继续补充进入页面、刷新和底部栏变化时的边界说明。
- Android 聊天输入区和脚手架同步调整，继续减少普通聊天页面在键盘、底部栏和消息刷新时的跳动。

