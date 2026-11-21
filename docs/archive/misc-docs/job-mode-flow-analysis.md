# Job 模式全流程分析：AI 回复的获取与展示

本文档分析「发消息 → 后端返回 job_id → 前端轮询 → 展示 AI 回复」在三种场景下是否都能正确拿到并展示结果。

---

## 一、统一前提

- 所有模式（对话 / Galgame / 锁分）均使用 `use_job: true`，POST /api/chat 立即返回 `{ job_id, status: "pending" }`。
- 前端收到 `job_id` 后：设 `requestSnapshot._handledByJob = true`，调用 `startJobPolling(jobId, charId, requestSnapshot)` 并 `return`；**finally 块检测到 _handledByJob 则直接 return，不清理打字、不调用 unlock**（避免打字/头像瞬间消失）。
- 轮询：每 450ms 请求 GET /api/chat/job/{job_id}，根据 `status`（pending / streaming / completed / failed）更新 UI 或收尾。

---

## 二、场景 1：在对话页等待完成

### 流程

1. 用户发送消息 → 展示打字动画 → POST /api/chat → 200 + `job_id`。
2. 进入 job 分支 → `startJobPolling`，**finally 因 _handledByJob 跳过**，打字与锁保留。
3. `setInterval(poll, 450)` + 立即执行一次 `poll()`。
4. 轮询中：
   - **Galgame/锁分**：后端一直 `pending`，直到模型返回后写入 `galgame_result` 并设 `status: "completed"`；某次 poll 得到 `completed` + `galgame_result` → 移除打字 → `addGalgameMessage` → `renderChat(..., forceFullRender: true)` → `releaseGenerationLock`。
   - **对话模式**：后端流式写入 `content_so_far` / `full_content`，`status` 变为 `streaming` 再变为 `completed`；poll 得到 `completed` + `full_content` → 移除打字 → `addMessageToConversation` → `renderChat(..., forceFullRender: true)` → `releaseGenerationLock`。
5. 结果：**能正常获取并展示 AI 回复**。

### 结论

✅ **在当前对话页等待**：流程完整，能正常拿到并展示 AI 回复。

---

## 三、场景 2：切到后台再切回前台

### 流程

1. 发消息后进入 job 轮询，用户切到后台（`document.visibilityState === 'hidden'`）。
2. 后台期间：`setInterval` 可能被节流但通常仍会执行，轮询继续；后端任务照常执行，完成后 job 状态为 `completed`。
3. 某次 poll 在后台拿到 `completed`：照常执行 `addGalgameMessage` / `addMessageToConversation`、`saveConversationsToBackend`；`if (window.activeCharId === charId)` 可能为 true（未切角色），则执行 `renderChat`，但此时页面不可见，用户看不到；若为 false 则只写内存不渲染。
4. 用户切回前台（`visibilityState === 'visible'`）→ `handleVisibilityChange`（conversations.js）：
   - 若有 `_currentChatJob` 且 `activeCharId === _currentChatJob.charId`，会再次调用 `startJobPolling(...)`。因 `jobId` 相同，内部直接 `return`，不重复建 interval（若 interval 仍在）；若因休眠被清掉则重新建 interval，继续拉取。
   - 随后 `renderChat(activeCharId, { preserveScrollPosition: true, skipScroll: true })`，**未传 forceFullRender**，若此时 `isGenerating` 仍为 true 会命中「isGenerating && !forceFullRender 则跳过渲染」。但若 job 已在后台完成，poll 里已把 `_currentChatJob` 置空、`isGenerating = false`，则此次 renderChat 会执行，用当前内存数据（已含新消息）重绘，用户能看到新回复。
5. 若切回时 job 仍在进行：`_currentChatJob` 仍在，`startJobPolling` 保证轮询继续；renderChat 时 **message-ui.js 会对该 charId 追加「进行中 job」的打字占位**（对话/Galgame 通用），列表末尾会显示「正在生成」，等 poll 拿到 completed 后再替换为真实消息。

### 结论

✅ **切后台再切回**：能继续轮询或恢复轮询；若已在后台完成则本次 renderChat 展示结果；若未完成则展示打字占位，完成后由 poll 更新并展示。**能正常获取并展示 AI 回复**。

---

## 四、场景 3：切到其他模式/其他角色再切回

### 流程

1. 用户在角色 A（如锁分）发消息，进入 job 轮询，`_currentChatJob = { jobId, charId: A, requestSnapshot }`。
2. 用户切换到角色 B（或同角色切到普通对话等）：`selectCharacter(B)`，`activeCharId = B`，**不停止 A 的 job**（设计上后台继续生成）。
3. 轮询继续在后台执行。某次 poll 得到 A 的 `completed`：`addGalgameMessage(A, ...)` / `addMessageToConversation(A, ...)` 写入 **角色 A 的内存数据**；`if (window.activeCharId === charId)` 此时为 false（当前是 B），故**不执行 renderChat**，仅保存与解锁。
4. 用户再切回角色 A：`selectCharacter(A)` → `loadConversationDetail(A, ...)`（可能拉服务端或直接用内存）→ `renderChat(A, { forceFullRender: true, ... })`。
5. renderChat(A) 时：
   - 若 A 的 job **已完成**：内存里 A 的会话/游戏数据已包含新消息，`visibleItems` 会带上这条；**无** `_currentChatJob.charId === A`，不追加打字占位；渲染出完整对话/游戏内容，**新回复可见**。
   - 若 A 的 job **仍在进行**：`_currentChatJob.charId === A`，**message-ui.js 会为该 charId 追加打字占位**（对话/Galgame 均已支持），列表末尾显示「正在生成」；轮询继续，完成后 poll 里会 `addGalgameMessage(A, ...)` / `addMessageToConversation(A, ...)`，此时若 `activeCharId === A` 会 `renderChat(A, ...)`，用户看到新消息；若当时已是 A，则正常看到更新。

### 结论

✅ **切到其他模式/角色再切回**：  
- 数据始终写在**发消息的角色 A** 上，切换回来用 A 的数据源渲染。  
- 若回来时已完成：内存/服务端已有新消息，直接展示。  
- 若回来时未完成：通过「进行中 job 打字占位」显示正在生成，完成后由轮询更新并展示。  
**能正常获取并展示 AI 回复**。

---

## 五、实现要点汇总

| 要点 | 位置 | 作用 |
|------|------|------|
| 收到 job_id 后不执行 finally 收尾 | chat-api.js：`_handledByJob` + finally 开头判断 | 避免清打字、误调 unlock，解决「打字瞬间消失」 |
| 轮询完成时写内存并视情况 renderChat | chat-api.js：poll 内 status completed 分支 | 保证对话/Galgame 数据有最新回复，当前在看该角色则立即重绘 |
| 切回前台恢复轮询 | conversations.js：visibilitychange → startJobPolling | 切回后继续拉 job 状态，必要时重新建 interval |
| 切回角色时显示「正在生成」 | message-ui.js：visibleItems 追加 isTyping 占位（对话+Galgame） | 切回该角色时若 job 未完成仍能看到打字占位，完成后由 poll 更新 |
| 切换角色不停止 job | char-selection.js：不调 stopJobPolling | 后台继续生成并写入对应角色数据 |

---

## 六、小结

- **当前对话页等待**：轮询到 completed 后写内存 + renderChat，能正常展示。  
- **切后台再切回**：visibility 恢复时恢复/继续轮询，renderChat 用当前内存重绘；未完成则显示打字占位，完成后再更新。  
- **切角色/模式再切回**：数据始终挂在发消息的角色上，切回时用该角色数据 + 可选打字占位渲染；完成后再由 poll 刷新。  

在现有实现下，三种场景下都能正常获取并展示 AI 回复；唯一依赖是轮询不被长期停掉（例如页面被销毁），当前逻辑在「切后台 / 切角色」下都会保持或恢复轮询。
