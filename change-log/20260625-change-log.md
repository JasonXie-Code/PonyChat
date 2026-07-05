# 2026-06-25 Change Log

## 自动滚动与状态同步

- 普通对话自动滚动设计文档大幅补充，明确初始展示、用户发送、助手多气泡到达、后台刷新、键盘/面板遮挡、语音转写展开、历史加载和引用跳转的触发边界。
- 新增 `docs/design/游戏、锁分模式的自动滚动设计.md`，把剧情/锁分模式从普通滚动策略中拆出来单独定义。
- 游戏和锁分模式新增“顶部阅读锚点”与“底部打字锚点”概念：进入页面和角色长回复到达时优先展示最后一条角色消息开头，用户发送后则定位到打字动画底部。
- 游戏和锁分模式避免把角色长回复直接滚到底部，并要求初始加载遮罩不因 `conversationId` 落定而重建。
- Android 聊天页主体、输入区、脚手架、滚动 helper、滚动副作用和 WebSocket 同步逻辑跟随上述设计调整。
- 消息列表刷新时进一步区分真实新增消息、同长度替换、元数据变化和用户手势，减少进入页面、回前台或服务端补拉时的视角抢夺。

## 普通回复与事实边界

- 普通聊天 `normal_planner`、`normal_speaker`、nonstream SSE 和 service 层继续强化当前场景、当前动作、图片内容和回复契约之间的传递。
- 场景保存和检索关键词整理补充更多当前事实锚点，降低旧动作、旧道具或旧场景覆盖用户最新输入的概率。
- 针对图片附件回复补充真实图片语义验证，避免角色只按旧上下文或泛化物品进行回应。
- 增加回复契约惯性验证，覆盖角色刚承诺的称呼、语气、语言和互动方式在后续回复里被冲掉的问题。
- 增加 `@` 提及场景的回复契约验证，确保被点名角色、说话人和多角色上下文不会被后续普通回复误归属。
- 主动消息推进验证补充到矩阵脚本，减少主动续接只复述开场、不推进当前互动的情况。

## 管理台、语音与测试

- 管理台用户统计接口和对应单元测试更新，继续补强后台用户数据展示。
- TTS 调试服务、语音消息合成和语音音频缓存测试跟随当前语音链路调整。
- 新增 `test_proactive_progression_case.py`、`test_rainbow_dash_image_attachment_reply.py`、`test_reply_contract_inertia_matrix.py` 和 `test_reply_contract_at_inertia_matrix.py` 等矩阵脚本。
- 扩充 `test_normal_reply_language.py`、`test_normal_four_stage_pipeline.py`、`test_normal_request_context.py`、`test_scheduled_followup_prompting.py` 和 `test_voice_audio_cache.py`，覆盖滚动、回复语言、图片、主动任务和语音缓存相关回归点。

