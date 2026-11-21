# 2026-06-29 Change Log

## 小游戏基础设施

- 新增后端 `/api/minigames` 路由，开始承载小游戏准备、执行、计费、结算和中国象棋相关接口。
- Android 新增 `MinigameRepository` 与小游戏数据模型，聊天输入区接入小游戏入口。
- 新增井字棋 `TicTacToeActivity`，作为轻量小游戏界面与仓库/API 调用的第一批移动端落点。
- 数据库初始化和计费测试补充小游戏相关表结构与扣费规则，`test_minigames_metering.py` 覆盖准备、执行和计量边界。

## 中国象棋体验

- 新增 `docs/design/小游戏 - 中国象棋设计.md`，定义中国象棋作为普通对话关系延伸的目标、入口流程、摆棋动画、准备步骤、角色语音、棋风配置、消息输入和后续 JSON 协议。
- Android 中国象棋界面继续完善棋盘、底部栏、消息输入、角色区域、执棋方、翻转方向和准备步骤等待体验。
- 中国象棋接入对局音效资源，包括拿起棋子、落子、吃子、将军、胜利和失败。
- 角色对局回复提示继续调整，让角色在下棋时保留原本称呼、关系、语气、记忆和互动习惯。
- 棋局移动展示时机优化，减少用户走棋、AI 思考、角色回复和音效之间的错位。

## EleEye 引擎

- Android 引入 EleEye 中国象棋引擎、开局库和多 ABI native 库，新增 `third_party/eleeye/NOTICE.md` 与 Android 构建脚本。
- 新增 `EleEyeInstrumentedTest` 和 `ChineseChessPolicyTest`，覆盖本地引擎加载、棋规策略和候选走法。
- 后端小游戏接口同步扩展引擎与角色棋风相关字段，为服务端准备步骤和移动端走法展示提供更多上下文。

## 普通聊天验证

- 新增普通对话模式角色测试达标卷，覆盖上下文一致性、场景位置状态锚定、短中长期记忆召回和解剖学正确性。
- 新增对应矩阵脚本 `test_normal_context_consistency_doc_matrix.py`、`test_normal_scene_position_state_anchor_matrix.py` 和 `test_normal_anatomy_correctness_doc_matrix.py`。
- 普通聊天物种解剖、事实判断、场景保存、检索关键词和回复防抖继续调整，配合新一批文档化角色测试。
- 聊天导出 instrumented test 补充，覆盖消息导出内容在新聊天 UI 和小游戏入口加入后的稳定性。

