# 2026-06-30 Change Log

## 中国象棋棋规与交互

- 中国象棋继续完善将军、被将军、胜负、吃子、候选走法和用户提示相关逻辑。
- 新增被将军音效资源，并替换/调整将军音效，区分角色将军和用户被将军的反馈。
- `ChineseChessPolicyTest` 扩充更多棋规、候选走法和局面判断覆盖。
- 后端 `minigames` 路由和 `test_minigames_metering.py` 继续扩展中国象棋准备、执行、结算和计费相关场景。
- Android 增加 `UserFacingException`，为小游戏或登录等流程提供可直接展示给用户的错误类型。

## 中国象棋模块拆分

- 将大型 `ChineseChessActivity` 拆分出 `ChineseChessAudio`、`ChineseChessDomain`、`ChineseChessEngine`、`ChineseChessGeometry`、`ChineseChessMenuPositionProvider`、`ChineseChessMoveCandidates` 和 `ChineseChessUiComponents`。
- 拆分后棋盘领域模型、引擎逻辑、候选走法、音效播放、几何计算、菜单定位和 Compose UI 组件各自独立，后续继续扩展棋力和界面时更容易维护。
- `EleEyeInstrumentedTest` 跟随拆分后的引擎入口调整，确保 native 引擎仍能在 Android instrumented 环境中加载和调用。

## 大文件拆分

- Android 多个超大 Kotlin 文件迁移到 `split-kotlin` 分片结构，包括 `CompanionService`、聊天气泡、Galgame、输入区、聊天脚手架、ViewModel、角色编辑/列表、历史会话和设置页等。
- 后端多个超大 Python 模块拆为 `*_parts` 结构，包括普通聊天 handoff、planner、speaker、service、数据库、Galgame DAO、角色路由、系统路由、scheduled follow-up、启动脚本和测试文件。
- MLP Songs、主站 landing 样式和 TTS 调试服务也进入分片结构，减少单文件过长带来的编辑、审阅和冲突成本。
- 保留原有入口文件作为兼容层或聚合层，尽量降低外部导入方感知。

## 网站样式与工具

- 主站新增 `landing-mbti.css`，并继续调整 landing 样式。
- Android debug 安装脚本和后端启动脚本同步拆分，保持本地调试入口可维护。

