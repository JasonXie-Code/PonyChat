# 数据保存与防丢失全面审查计划

## 一、审查目标

确保**普通对话**与**游戏模式（Galgame）**数据在以下场景下不丢失、不被误覆盖：

- 单设备：正常使用、切后台、杀进程、断网、清理缓存
- 同账号多设备：同时在线、先后上线、删除/编辑同步
- 边缘情况：多标签页、离线删除、保存竞态、角色 id 不一致

---

## 二、数据流总览

### 2.1 写入路径（谁在何时写库）

| 数据类型 | 触发方式 | 接口/路径 | 说明 |
|----------|----------|-----------|------|
| 普通对话 | 前端整包同步 | `POST /api/save_characters`（conversations + galgame_messages） | 防抖 500ms，紧急时 immediate |
| 普通对话 | 用户发消息后 | 同上（reason: user_message，延迟 300ms） | 避免与 /api/chat 竞争 |
| 普通对话 | AI 回复完成后 | 同上（reason: ai_response） | 流式结束后触发 |
| 普通对话 | 删除对话 | `POST /api/conversation/delete` | 原子删除 + 广播 conversation_deleted |
| Galgame | 每条 AI 回复后 | chat 内部 `save_galgame_state_async` → GalgameDAO | 与流式响应同进程，不经过 save_characters |
| Galgame | 前端整包同步 | `POST /api/save_characters`（galgame_messages） | 有内容才进 galgameToSave |

### 2.2 读取路径（谁在何时读库）

| 场景 | 接口/路径 | 说明 |
|------|-----------|------|
| 侧栏对话列表 | `GET /api/load_characters` | 元数据 + 各角色最新一条 |
| 某角色对话详情 | `GET /api/conversation/detail?mode=normal|galgame` | 按 character_id + mode，支持前缀回退 |
| 多设备同步后 | 同上（由 sync 触发 loadConversationDetail） | data_saved / conversation_deleted 后刷新 |

### 2.3 本地/紧急备份

| 存储 | 写入时机 | 读取时机 |
|------|----------|----------|
| localStorage `_emergency_backup` | visibility hidden、pagehide、删除后多源回写 | 启动时 5 分钟内恢复、loadConversationDetail 后端为空时 |
| Android saveToDisk / IndexedDB | 同上（双写/三写） | init 用 loadEmergencyBackupFromAllSources（若存在） |
| 各角色 cache key | 每次 loadConversationDetail 成功后 | 下次同角色同 mode 优先用缓存再 revalidate |

---

## 三、按场景的防护矩阵

### 3.1 单设备

| 场景 | 风险 | 现有防护 | 缺口/建议 |
|------|------|----------|-----------|
| 用户发消息后立刻切后台 | 用户消息未落库 | 发消息后 300ms 触发 save；visibility hidden 时 immediate + emergency 保存 | 已覆盖；可考虑“发完即请求”一次轻量保存（仅当前角色） |
| 用户发消息后立刻杀进程 | 同上 | beforeunload/pagehide + keepalive 保存；emergencySaveWithBeacon 写多源 | keepalive 有 ~64KB 限制，大 payload 可能失败；依赖紧急备份恢复 |
| AI 流式回复中被杀进程 | 本回合 AI 回复未落库 | 每条 Galgame 回复后后端已 save_galgame_state_async；普通模式依赖前端 save_characters | 普通模式若在流式结束前杀进程，本回合可能只存用户消息不存 AI；可接受或后续加“流式块写入” |
| 断网期间对话 | 仅在前端内存 | 恢复在线后 online 事件触发补写；_lastSaveFailed 时 visibility_visible 也补写 | 已覆盖 |
| 清理缓存后重进 | 误以为“全在云端” | 后端为唯一真相源；load_characters + loadConversationDetail 从库拉取 | 若之前从未成功保存则无法恢复；已有多处“空则从备份恢复” |
| 只读模式（无本地内容） | 误发空覆盖 | auto_sync 且无内容时不发保存，改为 loadConversationsFromBackend 拉取 | 已覆盖 |

### 3.2 同账号多设备

| 场景 | 风险 | 现有防护 | 缺口/建议 |
|------|------|----------|-----------|
| A 保存后 B 拉取 | B 显示旧数据 | data_saved 广播 → B 对当前角色 loadConversationDetail | 已覆盖；变更角色仅标记 _needsReload，不刷当前 UI |
| A 删除对话 B 需同步删除 | B 仍显示已删对话 | conversation_deleted 广播 → B markAsDeleted 并移出列表 | 已覆盖 |
| A 正在写、B 也写 | 互相覆盖 | 后端防误删：auto_sync 时拒绝“更少消息覆盖更多”；最后写入胜出 | 可能丢“未保存的那端”的增量；可接受或后续做 OT/合并 |
| B 尚未加载完角色详情就收到 A 的保存 | 后端差量删除误删 B 未传的对话 | partially_synced_characters 名单内角色不执行“后端有而前端未传则删” | 已覆盖 |
| B 正在删除时收到 A 的 data_saved | 删除被 A 的数据“恢复” | _deletionInProgressChars 时忽略涉及该角色的同步事件 | 已覆盖 |
| Galgame 重置 | 多端需一致清空 | 专用 /api/galgame/reset + galgame_reset 广播；前端清空本地并 _needsReload | 已覆盖 |

### 3.3 边缘情况

| 场景 | 风险 | 现有防护 | 缺口/建议 |
|------|------|----------|-----------|
| 多标签页：A 删对话 B 写备份 | B 的备份含已删对话，恢复时又出现 | 删除后多源写回备份（去掉该对话）；init 恢复时 5 分钟内按 _recentlyDeletedConvIds 过滤 | 若 B 在 A 删之前就写了备份且未被覆盖，仍可能恢复已删；建议文档说明或 BroadcastChannel 通知 B 更新备份 |
| 启动时紧急恢复只读一处 | 最新备份在 IndexedDB/Android，init 只读 localStorage | init 已优先 loadEmergencyBackupFromAllSources（若挂到 window） | 需保证 conversations 等先于 init 暴露该函数；已实现则无缺口 |
| 离线删除对话 | 删除请求失败，恢复在线后列表又出现 | 行为等同于“删除未持久化”；可文档说明或做离线待删队列 | 已知限制 |
| 角色 id 不一致（本机 id vs 大厅复合 id） | 同一角色存成两条 key，加载时只看到一条 | 加载端支持 character_id 前缀回退；保存端用当前前端的 id 一致即可 | 建议前端统一：列表、详情、保存始终用同一 id（优先复合 id） |
| 保存中又触发紧急保存 | 第二次被跳过导致未保存 | 紧急保存遇 SaveLock 时设 _pendingEmergencySave，当前保存在 finally 中再执行一次 | 已覆盖 |
| Galgame 本地曾为空不再拉取 | 后端有数据但前端不请求 | 已修复：needsGalgameLoad 在本地 messages.length===0 时也视为需要加载 | 已覆盖 |

---

## 四、后端防护清单（现状）

- **防误删（普通对话）**：save_intent=auto_sync 时，对“前端未传的对话”的删除受 partially_synced_characters 保护；仅 user_edit 可传空列表删全角色对话。
- **防误删（Galgame）**：auto_sync 时拒绝“用更少消息覆盖已有”；重置走 /galgame/reset 清库。
- **删除原子性**：conversation/delete 直接删库并广播，不依赖 save_characters 差量。
- **保存可观测**：已加 Galgame-Save 收到/落库日志，便于排查“是否请求到达、是否写入”。

---

## 五、实施清单（建议优先级）

### P0（必做，防丢/防误覆盖）

- [x] 用户消息发送后延迟保存（已有）
- [x] visibility hidden / pagehide 时 immediate + emergency 保存 + 紧急备份多源写入（已有）
- [x] 紧急保存遇 SaveLock 时 _pendingEmergencySave 在 finally 再执行一次（已有）
- [x] 后端 auto_sync 禁止用空/更少数据覆盖（已有）
- [x] 部分同步角色不参与差量删除（已有）
- [x] 删除进行中忽略涉及该角色的同步事件（已有）
- [x] Galgame 本地为空时仍重新请求后端（已有）
- [x] **保存失败可观测**：前端在保存失败或 partial 时 toaster 提示“对话同步失败，请保持网络/检查网络后重试”（已实现）

### P1（建议，提升可靠性）

- [x] **init 紧急恢复**：init 内备份恢复在应用启动流程中执行（由 app-modular 等触发），此时 conversations.js 已加载，`loadEmergencyBackupFromAllSources` 已挂到 window；init 中已优先调用该多源加载，5 分钟恢复能从多源取最新备份。
- [x] **Galgame 保存后确认**：chat 返回 db_saved: false 时，前端 toaster 提示“游戏进度保存失败，请勿关闭页面，稍后切回将自动重试”（已实现）。
- [ ] **character_id 统一**：前端在列表、详情、保存三处统一使用同一 id（例如优先使用带 _ 后缀的复合 id），减少“同角色两套 key”的概率。

### P2（可选，进一步加固）

- [ ] 多标签：删除后通过 BroadcastChannel 通知其他标签更新内存与紧急备份，减少多标签互相覆盖备份的窗口。
- [ ] 普通模式流式回复：在每 N 个 chunk 或每条完整消息后向后端写入一次（当前为流式结束后前端 save_characters），降低“流式未结束就杀进程”的丢失量。
- [ ] 离线删除：删除 API 失败时标记 pending_delete，恢复在线后重试或提示用户“删除未生效，请重试”。

---

## 六、测试矩阵（建议执行）

| 类型 | 用例 | 预期 |
|------|------|------|
| 单设备 | 发一条消息 → 5 秒内切后台 → 杀进程 → 重进 | 该消息在对话中可见 |
| 单设备 | 游戏模式选一项 → 立刻切后台 → 杀进程 → 重进并切游戏模式 | 该选项与回复可见，分数一致 |
| 单设备 | 断网发消息 → 恢复网络 → 等待补写 → 刷新 | 消息在云端可见 |
| 单设备 | 清空缓存 → 重新登录 | 仅显示云端有的对话/游戏进度 |
| 多设备 | A 发消息并保存 → B 切到同角色 | B 看到新消息 |
| 多设备 | A 删除某对话 → B 同角色 | B 该对话消失 |
| 多设备 | A 保存、B 未加载完该角色详情时 A 再保存 | B 该角色对话不被误删 |
| 边缘 | 标签 A 删除对话 → 标签 B 马上切后台写备份 → 关 A、刷新 B | 理想情况 B 不恢复已删对话（多源+5 分钟过滤）；若 B 备份写得更晚且未含删除结果则可能恢复，属已知限制 |

---

## 七、文档与代码引用

- 既有计划：`docs/audits/plan_prevent_data_loss.md`（用户消息/visibility/紧急保存等）
- 边缘情况：`docs/audits/edge_cases_data_protection.md`（删除竞态、部分同步、多标签等）
- 本审查：`docs/audits/data_integrity_audit_plan.md`（本文档）
- 验证脚本：`misc/archive-scripts/verify_galgame_save.py`（Galgame 落库往返验证）

---

## 八、结论与下一步

- **结论**：单设备、多设备与大部分边缘情况已有明确防护；数据丢失多来自“从未成功写库”或“写库前进程/网络终止”，而非后端误覆盖。
- **下一步**：按 P0 检查是否全部落地 → 做一轮 P1 → 执行第六节测试矩阵并记录结果；若发现新边缘案例，补充到本节并更新本计划。
