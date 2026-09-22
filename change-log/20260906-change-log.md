# 2026-09-06 Change Log

## Harness 普通对话与记忆

- 新增 Harness 普通对话引擎与 Android 设置入口，统一 DeepSeek 视觉 low 配置。
- 升级自主工具调用、记忆整理及回复交付，调整 Harness 回复与手机端体验。
- 完善记忆与小游戏执行链路，恢复关系页面展示；Harness 并发容量调整为 10。
- 根据角色与用户要求处理 emoji 和贴纸，补充表达策略测试记录。

## 发送前证据核验

- 自主回复发送前增加私有证据核验，将事实主张清单与证据验证分开，并增加实测探针和部署脚本。
- 核验保留角色主动性，兼容缺省的可选反馈；即使主张清单为空也检查隐含事实。
- 核验结果绑定服务端维护的主张标识，在回合预算内修复协议错误；事实修正后允许继续恢复输出格式。
- 各轮草稿重试保留已检索证据，避免修订过程中丢失依据。

## Android 与官网

- Git 中记录 Android 5.6.17、5.6.18 至 5.6.20 的版本与发布相关改动，补充构建、APK 发布工具和验收资料。
- 恢复所有用户登录，将 Android 最低登录版本调整为 5.6.19。
- 官网移除停更公告，恢复 Android 下载，支持简体中文、繁体中文、英文和俄文。
- 增加自动语言识别、手动选择持久化和主题语言菜单，同步页面标题与描述，移除多余语言选择标签。

## 服务与稳定性

- 增加模型服务可逆暂停、状态查询和恢复脚本；后续提交记录模型服务与周期性整理任务已全部恢复。
- 后端重新接入本地 Qwen3TTS，补充公网语音健康路由恢复说明。
- 将记忆配置、整理结果及收尾写库移出异步主循环，补充失败处理，修复手机聊天卡住的问题。

## 已提交验证资料

- 补充 Harness 记忆、表达策略、小游戏 Android 实机／模拟器及十路并发相关测试与验收记录。
- 本次补档依据下列提交及其中保存的资料；不包含工作区尚未提交的探针修改和报告，也未重新执行生产部署或设备验收。

## Git 依据

按 Git 作者日期（UTC+08:00）归档，同日连续修复在上文合并说明。

- `1ae493e` 暂停模型服务并提供一键恢复脚本
- `835c52c` Add Harness normal-chat engine and unify DeepSeek vision low
- `5d13b66` 记录模型及周期性整理全部恢复
- `283fb16` Upgrade autonomous Harness memory and publish Android 5.6.17
- `ae8eda2` fix: align Harness replies and mobile experience
- `6b533d8` feat: personalize agent emoji and sticker policy
- `ef0a478` Restore PonyChat login access for all users
- `cccafd3` Align minimum Android login version with 5.6.19
- `b8e0568` Reconnect PonyChat to local Qwen3TTS service
- `e4aeb6e` Document restored public voice health route
- `03e5ffc` Upgrade Harness memory and game execution; restore relationship UI and bound capacity
- `fd824a5` Localize PonyChat website in four languages and restore downloads
- `e2bd4fb` Raise production Harness concurrency to ten
- `932a5a5` Add private evidence review before autonomous reply delivery
- `255f176` Replace language selector with custom themed menu
- `fbda220` Separate claim inventory from evidence verification and add live probes
- `340f9c8` Remove visible language selector label
- `164457f` Preserve character initiative during factual review
- `4b06bf4` Accept evidence verdicts without optional feedback
- `a2d207d` Check implicit claims even when draft inventory is empty
- `b407e69` Bind review results to server-owned claim identities
- `5837148` Repair private review protocol errors within the turn budget
- `e969194` Allow format recovery after factual draft corrections
- `8d97015` Verify game Harness in Android and ten-agent concurrency
- `9c32902` Keep retrieved evidence across all draft retries
- `76191d6` Prevent mobile chat stalls from synchronous memory writes and handle failures
