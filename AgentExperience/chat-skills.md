# 普通对话与技能

核对日期：2026-09-13。

## 入口地图

- 主提示词：[Prompts.py](../Backend/chat_modules/Prompts.py)。用户要求聊天提示词集中维护，避免在业务代码另建重复正文。
- 技能目录、按需加载和动态内容：[autonomous_prompt_skills.py](../Backend/chat_modules/autonomous_prompt_skills.py)。只看静态正文不够，schedule、lifecycle、handoff 等还会追加当前能力或状态。
- Agent 回合：[autonomous_normal.py](../Backend/chat_modules/autonomous_normal.py)。
- 入口及死亡状态检查：[chat_request.py](../Backend/chat_modules/service_impl/chat_request.py)。
- 历史及安全元数据：[autonomous_history.py](../Backend/chat_modules/autonomous_history.py)、[reply_language_state.py](../Backend/chat_modules/reply_language_state.py)。不要把 rawContent 整体当作可注入历史；它可能携带内部内容，当前链路只提取认可的元数据。
- 工具动作和原子保存：[autonomous_business.py](../Backend/chat_modules/autonomous_business.py)、[autonomous_transaction.py](../Backend/chat_modules/autonomous_transaction.py)。
- 发声能力、可见文本和语音音频是不同问题：speech / reply_expression / delivery / voice_reply 分别核对。

## 用户已确认的边界

- 本轮技能审查中，“1”是“修复已报告的问题，然后只读检查下一个技能”的快捷指令。此约定源于该审查，不应推广到不相关任务。
- 普通对话的 instant_messaging 与 virtual_roleplay 共享 normal 偏好；不与游戏、锁分偏好混为一谈。
- 嘴部受限不等于每轮必须拟音；声音必须符合能力、实际意图与场景，不能为了变化制造刺激、同意或自动解除限制。
- 动作结构检查留在内部。蹄子和其他种族、部位都一样：直接做能做的动作，用户未问时不刻意解释能力限制。
- 复述是自然聊天能力，不要求考试式逐字一致；仍遵守交付不得在 text 中放换行及括号的规则，描写括号由后端渲染。
- 用户图片和角色图片均可由历史图片重发链路处理，但仍需检查归属与工具条件。
- stage 工具成功只表示暂存；回复、记忆、提醒等业务状态要随成功回复事务落库。失败或被新回合替代时不能宣称完成。
- 死亡后直接聊天不回复。显式 @ 可触发灵魂/残响，后台显式选择发言角色也可作为有效触发；自动转交和主动消息不能绕过，不代表复活。
- image_style 曾有两项建议被用户明确要求不改，不要依据旧检查意见擅自补改。

## 改技能时

先理解调用条件与执行代码，再修改最小范围。规则编号、其他条款引用、能力触发文案、最终片段结构和相关测试一起核对。不要为通过旧文字断言恢复已经被用户批准替换的旧规则，也不要只改断言掩盖行为问题。
