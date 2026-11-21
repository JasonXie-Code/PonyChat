# 2026-06-15 Change Log

## 普通聊天 Handoff

- 新增普通聊天角色 handoff 流程，支持在对话中把回复责任转交给更合适的角色。
- Android 聊天页、角色资料页、消息气泡与 ViewModel 同步接入 handoff / 多角色发言相关字段。
- 后端 request context、speaker router 与 normal speaker 更新，确保 handoff 后的发言角色、上下文和记忆写入保持一致。

## 事实归因与误解处理

- 强化多说话人事实归因守门，减少把第三方指控、玩笑、误会或场景叙述误写成用户事实。
- 用户事实判断移除角色设定干扰，避免把角色档案、世界观或对话中的他人信息归到用户身上。
- 调整误解处理 prompt，让角色在被纠正、被误会或信息不完整时优先澄清当前轮语义，而不是继续放大旧判断。

## 回复节奏与开场白

- 普通回复链路加入显示延迟配置，让 Android 端展示节奏更接近“角色正在组织语言”的体验。
- 修复 opening greeting 兜底生成，避免开场问候在素材不足或生成失败时直接空掉。
- 强化当前动作锚定，让主回复更优先承接用户刚刚说的话和当前场景动作，减少旧上下文抢占当前轮。

## 主动任务与语音

- Scheduled follow-up 与 proactive settings 继续调整，补充被动任务更新、后续追问和后台任务相关测试。
- 普通语音回复、素材选择与 normal voice reply 链路跟随主对话 prompt 更新，保持语音和文本回复使用同一套角色判断。

## 测试与工具

- 更新 normal four-stage pipeline、request context、LLM debug logging、scheduled follow-up prompting、proactive settings 和 user fact guard 测试。
- 增加 speaker router 后端验证脚本，覆盖多说话人路由、归因和 handoff 场景。
