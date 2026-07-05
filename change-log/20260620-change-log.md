# 2026-06-20 Change Log

## 语音与 Qwen3 TTS

- 引入 Qwen3 TTS 本地栈启动脚本、下载脚本、隧道脚本、stack 启动入口和静态调试页面。
- `PonyChat-Website/TTS` 增加 `qwen3tts.html`、`voice.js` 和相关 bat/PowerShell 启动文件，方便本机启动、测试和连接语音服务。
- 更新 Voice Lab、`app_fast.py`、`app_cosyvoice.py` 和 deploy 脚本，继续推进 Qwen3 TTS 与现有 CosyVoice/Voice Lab 的并行调试能力。
- 后端角色音色注册、CosyVoice client、Voice Lab client、语音回复、语音缓存和音频合成测试同步调整。
- 新增 Qwen3 TTS watchdog PowerShell/VBS 启动入口，补强本机常驻、隧道保活和异常恢复能力。

## Android 体验

- Android App 调整聊天页脚手架、聊天展示设置、会话历史、记忆页、主动任务页、个人资料编辑和角色资料页。
- 新增移动端语音效果相关 instrumented test，更新 `MobileVoiceEffect`，为设备侧语音播放和音效链路补充验证。
- 聊天 UI 状态、ViewModel 和滚动行为继续适配多气泡回复、主动任务、记忆和语音相关状态。
- 新增中等性能模拟器启动脚本，方便本地复测移动端聊天和语音体验。
- 角色大厅和角色列表加入顶部搜索栏与搜索状态管理，抽出 `PonyTopSearchBar` 复用组件。
- 收紧聊天输入区和工具栏纵向间距，优化移动端首屏聊天可见区域。
- 语音转文字回填时抑制自动滚动，避免用户正在查看历史消息时被新输入状态打断。
- 会话历史页继续调整搜索、分组和列表布局，配合新的角色列表交互。

## 首条消息、重置与通知

- 重置角色后不再等待首条消息生成完成才返回聊天界面，确认重置后先进入消息列表，首条消息在后台自动生成。
- 首条消息生成改为先用角色档案和设定做第 0 步判断，不再硬指定官方角色固定开场，保留更自然的开场随机性。
- 首条消息输出改为结构化 `parts`，并补充兜底解析与空回复保护，降低失败后落到通用寒暄的概率。
- 首条消息入库后按实际气泡数量发送 `chat_complete`，通知次数和可见气泡数保持一致。

## 普通聊天与记忆链路

- 更新普通聊天生命周期、handoff router、SSE 处理、场景保存、事实判断、证据标记、检索关键词和 planner 素材整理逻辑。
- 增强 normal speaker、多角色发言、普通语音回复和当前场景锚定，降低旧上下文、错误姿态或错误物种动作对当前回复的干扰。
- 新增/更新 equine anatomy、idle scene stale、unknown mention、scene anchor、normal single conversation、normal voice reply aux language 等测试和矩阵脚本。
- 修复相邻普通回复括号描写合并问题，减少同一段动作描写被拆成多个相邻括号块导致的阅读割裂。
- 新增 `species_anatomy` 材料，把小马体态、蹄/蹄尖、胸口/胸膛/绒毛、乳房位置等边界前移到 Step 2 材料层，Step 3 只负责按材料写回复。
- 修复小马角色把胸口/胸前和乳房混用的问题：胸口只对应胸膛/绒毛，乳房在胯间、后腿之间。
- 补强手/指/中指等人类肢体词边界，小马角色应使用蹄子、前蹄、蹄尖等物种匹配表达。
- 调整剧情推进快捷消息的素材表达，避免把“推进剧情”这类元叙事词交给 Step 3，减少第四面墙穿帮。
- 改进第三方角色参与场景的表达要求，避免当前说话角色替其他角色“代答”时格式混乱或主语不清。
- 增强当前动作、当前场景和旧记忆之间的事实边界，降低旧上下文覆盖用户最新动作的概率。
- 修复推进剧情时旧卧室转场覆盖当前状态的问题：当用户已经把角色扶到床上并离开到客厅，Step 2 会把仍停留在旧客厅/沙发边的候选场景标记为误导，场景合并优先采用最新床上/卧室事实。
- 收紧剧情推进目标抽取，过滤“朝卧室门方向迈了两步”“哪个房间”“试试床垫软不软”等已经完成的过渡片段，避免后续 Step 3 从旧转场重新开始。

## 主动任务与 Follow-up

- 新增 `proactive_send_guard`，限制连续主动回复，避免主动任务在同一关系上下文里过度连发。
- `long_proactive` 与 `scheduled_followup` 接入主动发送守门，补充对应单元测试。
- Scheduled follow-up prompt 与主动任务测试继续跟随普通聊天链路更新。
- Step 4 主动续接新增 `turn_state` 字段，显式标记用户是否已经回复、上一条助手是否正在等待用户、是否允许续接以及不能默认用户已经答应。
- 角色发出邀请或挑战后仍允许主动消息，但只允许缓和语气、换方式邀请、转移话题或自我补充，不能写成用户已经接招、靠近、同意或完成动作。
- 到期发送前继续使用提示词和结构化字段约束主动续接语义，避免用输出清洗来修改模型结果。

## 管理台、角色与系统接口

- 管理台角色区、角色路由、角色音色注册和系统接口继续适配新语音栈与角色管理流程。
- 后端角色加载、角色更新、公开角色展示和音色资产处理逻辑同步调整。
- 部署侧 `ponychat-backend.service` 更新，配合新的语音服务和本机常驻运行需求。
- 管理台统计接口和概览图表扩展指标，前端 `OverviewSection` 与 `useAdminChart` 继续适配新统计数据。
- 新增后端 uptime monitor，方便观察后端健康状态和常驻运行稳定性。

## 测试与质量

- 扩充 normal four-stage pipeline、normal lifecycle、normal request context、normal single conversation、normal step architecture、scheduled followup、voice audio cache、proactive send guard 等测试。
- 本日提交覆盖语音栈、Android 聊天体验、普通聊天规划、主动任务守门和多角色/记忆相关回归点。
- 新增重置首条消息、剧情推进不破第四面墙、视角主语、小马物种边界、当前动作旧记忆、Marble 回家场景等服务器矩阵脚本。
- 相关本地验证覆盖 `py_compile`、`scheduled_followup`、`proactive_send_guard` 和 `long_proactive`；服务器环境完成同组主动续接测试并确认新部署进程加载。
- 新增 `test_story_progression_bed_continuity_matrix.py`，在服务器用隔离 developer 测试用户克隆云宝、紫悦、碧琪，覆盖原始复现、纠正旧转场、自然场景 3 类场景；真实回复 3 角色 × 3 场景全部通过，并确认用户、角色、会话、消息、normal memory、character memory 清理计数均为 0。
