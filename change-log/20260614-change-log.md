# 2026-06-13 ~ 2026-06-14 Change Log

## 普通聊天链路

- 强化 normal chat 四阶段 pipeline，补充 stage-aware supersede gates，避免过期阶段结果覆盖当前请求。
- 优先使用当前场景输入参与回复规划，减少旧上下文对当前对话的干扰。
- 修复普通回复去重与 Stage 3 JSON prompt，提升输出格式稳定性。
- 增加 species-aware prompt 与回复清洗逻辑，让角色回复更符合物种、身份与当前场景设定。
- 增加多组 normal pipeline、request context、single conversation 与 user fact guard 测试。

## Guest Speaker 多说话人

- 新增 guest speaker chat 后端支持，补齐 speaker 选择、历史记录、消息路由与上下文拼接。
- 修复 guest speaker 历史与聊天路由问题，确保多说话人消息能正确进入会话与展示。
- Android 聊天气泡、消息内容与角色资料页同步适配 guest speaker 展示。

## 主动任务与 Follow-up

- 新增 proactive task 入口，更新主动任务列表、状态同步与本地缓存逻辑。
- 优化 scheduled followup prompt，增强被动任务更新与后续追问行为。
- 为 planner 与 followup 增加 partner private party guard，避免私密场景被不合时宜地打断。
- 补充 long proactive、scheduled followup 与 normal planner 相关测试。

## 语音与 CosyVoice

- 继续推进 CosyVoice 语音栈迁移，完善角色音色注册、语音消息缓存与语音回复链路。
- 优化 voice handling、voice message 生成与 normal voice reply 的上下文处理。
- 增加 CosyVoice client、voice audio cache、aux language voice reply 等测试覆盖。

## Android 体验

- 新增消息震动开关，设置页可控制新消息到达时是否震动。
- 优化聊天媒体网格、消息气泡、输入区、展示设置与会话相关 UI。
- 更新主动任务页与聊天页交互，改善任务入口、消息展示和运行时状态同步。
- 调整部分角色编辑、角色资料、日期选择器与个人资料编辑体验。

## 后端与运维

- 优化部署脚本：移除每次部署时的远端 `ffmpeg` 检查/安装步骤，部署后直接检测并重启 systemd 服务。
- 保留 deploy token 探活机制，继续通过 `/api/health` 确认新进程已加载本次部署。
- 更新 systemd / service / runtime 相关逻辑，配合聊天 pipeline 与语音能力调整。

## 测试与质量

- 增加 normal four-stage pipeline、request context、planner policy、planner architecture 等测试。
- 增加 system role quality、LLM debug logging、scheduled followup prompting、voice cache 等测试。
- 持续整理后端角色回复测试流程文档，覆盖普通聊天、主动任务与多说话人相关场景。
