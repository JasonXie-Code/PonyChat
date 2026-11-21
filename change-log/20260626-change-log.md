# 2026-06-26 Change Log

## 语音上传与管理台

- 管理台角色接口支持上传和处理 voice reference 相关文件，前端 `CharactersSection`、`UsersSection` 和 admin API 同步适配。
- Server-USA Nginx 配置补充管理台语音参考文件上传所需限制与转发规则。
- Android 聊天输入区和 Manifest 跟随语音/文件选择场景调整，为移动端语音素材与聊天输入体验继续铺路。
- 网站增量部署脚本继续适配新增的管理台资源上传路径。

## 中国象棋雏形

- Android 新增 `ChineseChessActivity`，开始搭建中国象棋小游戏界面、棋盘交互和聊天入口衔接。
- 新增 `docs/design/chinese-chess-icon-candidates.html`，用于比较中国象棋入口图标候选方案。
- 普通对话自动滚动设计继续补充小游戏入口与底部输入区相关细节。

## Server-USA 部署前稳定性

- 新增 `Backend/shutdown_state.py`，为后端进程停机、部署切换和后台任务收尾提供统一的 shutdown 标记。
- Long proactive、scheduled follow-up、后台任务和记忆调度在 shutdown 请求期间避免继续启动新生成，未完成的主动触达会保留或重新排队，降低部署时丢任务的风险。
- 后端配置和 `ponychat-backend.service` 继续整理，配合 Server-USA 部署前的运行方式。
- 普通聊天场景保存、事实证据标记和检索关键词继续补充，确保部署前的普通回复链路保持稳定。

## Android 消息可靠性

- Android 本地缓存、连接服务、聊天 ViewModel 和消息操作继续修复普通对话刷新时的消息合并问题。
- 新增 `NormalPendingUserMergeInstrumentedTest`，覆盖服务端快照只返回助手消息时，本地刚发送的用户消息不能被刷新吞掉。
- 新增 `RetractedMessageEditInstrumentedTest`，覆盖撤回消息经过服务端占位刷新后，编辑输入仍能恢复原始文本。
- 聊天显示设置和 vital overlay 跟随新的消息恢复、撤回和刷新状态调整。

## 测试与提示词

- `test_normal_four_stage_pipeline.py`、`test_normal_step_architecture.py` 和 `test_scheduled_followup_prompting.py` 补充 shutdown、主动任务和普通场景锚定相关覆盖。
- 普通聊天事实证据规则继续强化，减少关键信息在场景保存、检索和后续回复之间丢失。

