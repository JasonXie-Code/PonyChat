# Job 轮询与 WebSocket 兜底 - 整体审查报告

## 一、修改与数据流总览

### 1.1 核心问题（已解决）

- **现象**：锁分模式下发消息后，后端已返回并落库，前端长时间只显示打字动画，最后打字与 AI 消息一起消失。
- **根因**：① 前端 job 轮询只发起一次即停止（Android/后台对 setInterval 节流）；② 本机收到的 `SYNC_DATA (galgame_update/generation_complete)` 被 `source === clientId` 直接忽略，导致从未刷新。

### 1.2 已实施的修改

| 位置 | 修改内容 |
|------|----------|
| **chat-api.js** | 轮询改为 setTimeout 链；抽 `clearJobGenerationState(charId)` 统一清理；轮询失败/超时/404/完成/失败均走该清理；404/5xx 时仅当前角色拉取+渲染，非当前角色仅后台拉取；`clearJobGenerationState` 内增加对 `generationStates` 的清理。 |
| **chat-api.js** | `stopAIGeneration` 的 job 分支：按 `job.charId` 清理打字 DOM 与 `generationStates`，避免切走后该角色仍残留打字。 |
| **sync.js** | 本机 `galgame_update` / `generation_complete` 兜底：清状态 → 仅当 `activeCharId === charId` 时 `loadConversationDetail` + `renderChat`；更新 `_syncTimestamps.galgame` 与 localStorage。 |

---

## 二、数据流与竞态检查

### 2.1 正常完成路径（轮询拿到 completed）

1. `startJobPolling(jobId, charId, requestSnapshot)` → 设置 `_currentChatJob`，`poll().then(scheduleNext, scheduleNext)` 启动链。
2. 某次 `poll()` 返回 `status === 'completed'` 且 `galgame_result` / `full_content` 存在 → `clearJobGenerationState(charId)` → 写消息 / 更新分数 → `releaseGenerationLock` → `renderChat`（仅当 `activeCharId === charId` 时对 Galgame 分支渲染）。
3. `scheduleNext` 依赖 `_currentChatJob && jobId 一致 && _jobPollTimeoutId != null`；`clearJobGenerationState` 已清空 `_currentChatJob` 和 `_jobPollTimeoutId`，故不再调度下一轮，无竞态。

### 2.2 推送兜底路径（本机 SYNC_DATA）

1. WebSocket 收到 `SYNC_DATA`，`reason` 为 `galgame_update` 或 `generation_complete`，`source === this.clientId`。
2. 若 `charId` 匹配且（`activeCharId === charId` 或 `_currentChatJob?.charId === charId`）→ `clearJobGenerationState(cid)` → 仅当 `isCurrent` 时 `loadConversationDetail` + `renderChat` → 更新 `_syncTimestamps.galgame`。
3. 与轮询的竞态：若轮询先拿到 completed，已执行 `clearJobGenerationState` 并清空 `_currentChatJob`，随后推送到达时 `isWaitingJob` 为 false，但 `isCurrent` 仍可能为 true，会再执行一次 load + render，属幂等，可接受。若推送先到，先清状态并可能 load+render，轮询后续再返回 completed 时仍会走 `clearJobGenerationState` 和业务逻辑，不会重复写消息（由 `addGalgameMessage` / 服务端数据决定），逻辑一致。

### 2.3 404/5xx 路径

1. `poll()` 得到 404 或 5xx → `clearJobGenerationState(charId)` + `releaseGenerationLock`。
2. **仅当 `activeCharId === charId`** 时：`loadConversationDetail` → `renderChat`，避免把非当前角色画到主区域。
3. **当 `activeCharId !== charId`** 时：仅 `loadConversationDetail(charId, ...)` 后台拉取，不调用 `renderChat`，保证切回该角色时数据已就绪且不覆盖当前视图。

### 2.4 超时路径（JOB_POLL_MAX_MS）

- `clearJobGenerationState(charId)` + `releaseGenerationLock`，无 load/render，避免长时间卡在“生成中”。

### 2.5 用户点击「停止生成」

- Job 分支：`stopJobPolling`，`_currentChatJob = null`，按 **job.charId** 移除打字 DOM 并清除该角色的 `generationStates`，再 `releaseGenerationLock`，最后对 **activeCharId** 做一次 `renderChat`（刷新当前视图）。即使用户已切到别的角色，也能清掉原角色打字占位。

---

## 三、与最佳实践的对齐

- **推送优先、轮询兜底**：完成态主要依赖后端 SYNC_DATA；轮询用于断线/未推送时的补救，符合常见做法。
- **本机事件**：对“数据已落库”的 `galgame_update` / `generation_complete` 做白名单兜底，其余 self 事件仍忽略，兼顾防抖与数据可见性。
- **单 job 设计**：全局仅一个 `_currentChatJob`，多角色并发时其它角色依赖推送 + 切角色时的 `loadConversationDetail`，与单视图 UI 匹配。

---

## 四、本次审查中顺带修复的问题

1. **404/5xx 且非当前角色**：原先会执行 `renderChat(charId, ...)`，可能把非当前角色对话画到主区域；已改为仅后台 `loadConversationDetail`，不渲染。
2. **clearJobGenerationState**：未清理 `generationStates`，可能导致同步/UI 仍认为该角色在生成；已为该角色清理 `generationStates[charId_gal/chat]` 与 `generationStates[charId]`。
3. **stopAIGeneration（job）**：原先按 `activeCharId` 清打字 DOM，若用户已切走则 job 所属角色的打字不会清除；已改为按 `job.charId` 清打字与 `generationStates`，并保留对当前视图的 `renderChat(activeCharId)`。

---

## 五、仍可选的后续优化

- **单次 poll 请求超时**：对 `fetch(/api/chat/job/...)` 加请求级 timeout（如 10s），超时 reject 后由 `scheduleNext` 继续下一轮，避免单次请求挂死导致整条链停掉。
- **多角色并行 job**：若产品需要“同一屏多角色同时显示打字/进度”，再考虑将 `_currentChatJob` 扩展为按角色/会话的 map 及多路轮询；当前单 job + 推送兜底已满足“多角色发消息、切回后都能看到完整记录”的需求。

---

*审查日期：基于当前代码库与对话中的修改整理。*
