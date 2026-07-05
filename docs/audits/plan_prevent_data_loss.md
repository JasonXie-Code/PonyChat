# 防对话数据丢失加固计划

## 一、问题背景

用户反馈 Galgame 模式（柔柔 NSFW）的对话记录在「更新 App + 清理缓存」后丢失。经过分析，发现多种边缘情况可能导致对话数据未能持久化到后端。

## 二、已识别的风险点

### 2.1 前端保存时机缺失

| 场景 | 现状 | 风险 |
|------|------|------|
| 用户发送消息后 | 保存逻辑已注释 | AI 回复前关闭/切走 → 用户消息未落库 |
| 页面切后台/关闭 | 仅 localStorage 备份 | 清理缓存后无法恢复 |
| 保存锁/防抖 | 可能跳过紧急保存 | 关键时刻保存被跳过 |

### 2.2 Galgame 模式特有

| 场景 | 现状 | 风险 |
|------|------|------|
| 用户选择选项 | 无保存 | 同用户消息 |
| galgameToSave 条件 | `messages>0 \|\| score!==40` | 边界情况可能漏报 |

### 2.3 后端相关

| 场景 | 现状 | 风险 |
|------|------|------|
| JSON 解析失败 | 重试后返回 error | 本回合不保存 |
| 重复场景检测 | 触发 retry | 重试耗尽则不保存 |

## 三、加固方案

### 3.1 恢复用户消息保存（chat-api.js）

- **方案**：在用户消息添加后，使用 `setTimeout` 延迟 300ms 触发保存，避免与 `/api/chat` 请求竞争
- **适用**：普通模式 + Galgame 模式
- **实现**：取消注释并改为延迟执行

### 3.2 页面可见性变化时触发网络保存（conversations.js）

- **方案**：`visibilitychange` → hidden 时，立即触发 `saveConversationsToBackend`（immediate + emergency 标记）
- **优化**：取消待执行的防抖，确保立即执行；若正在保存，标记 `_pendingEmergencySave`，当前保存完成后再执行一次

### 3.3 页面卸载时增强保存（conversations.js）

- **方案**：`beforeunload` / `pagehide` 时，先尝试一次同步保存（不依赖防抖）
- **实现**：调用 `saveConversationsToBackend`，并保留现有 localStorage 备份

### 3.4 保存锁与防抖优化（conversations.js）

- **方案**：紧急保存（visibility/pagehide）时，若遇 SaveLock，设置 `_pendingEmergencySave`，在 `finally` 中检查并重试
- **方案**：紧急保存绕过防抖，强制 immediate

### 3.5 Galgame 保存条件放宽（conversations.js）

- **方案**：`galgameToSave` 条件改为 `(galData.messages?.length > 0 || galData.score !== 40 || galData.status !== 'playing')`
- **说明**：确保有「进行中」状态的游戏也能被保存（status 可能是 win/lose 等）

### 3.6 紧急保存时 fetch 使用 keepalive（可选）

- **方案**：当 `options.emergency === true` 时，fetch 添加 `keepalive: true`，允许请求在页面关闭后继续
- **限制**：Chrome 对 keepalive 请求有 ~64KB 限制，大 payload 可能失败，仅作补充手段

### 3.7 紧急备份恢复（conversations.js + auth.js）

- **方案 A**：init.js 已有 < 5 分钟的紧急恢复（启动时）
- **方案 B**：loadConversationDetail 在 Galgame 后端返回空时，从 `_emergency_backup` 尝试恢复（5 min ~ 24h 内）
- **方案 C**：resetAppState 不再移除 `_emergency_backup`，保留给恢复流程使用

## 四、实施清单

- [x] 1. 恢复用户消息发送后的延迟保存（300ms 防竞争）
- [x] 2. visibilitychange 时触发网络保存 + 防抖取消
- [x] 3. pagehide/beforeunload 时同步尝试保存 + keepalive
- [x] 4. 紧急保存时的待重试机制（_pendingEmergencySave）
- [x] 5. Galgame 保存条件优化（hasEndState 等）
- [x] 6. emergency 模式下 fetch keepalive
- [x] 7. 保留 _emergency_backup，增加 tryRecoverGalgameFromBackup

## 五、测试建议

1. **用户消息保存**：发送消息后立即切后台，检查后端是否有记录
2. **Galgame 选项**：选择选项后立即杀进程，重启后检查进度是否保留
3. **清理缓存**：玩几轮后清理缓存，重新登录，确认能从后端恢复
4. **弱网**：模拟慢速网络，发送后迅速关闭，验证延迟保存与紧急保存
