# Job 模式全面优化计划（前后端一致性 + 可观测性）

## 目标

- 消除“后端已 completed，前端仍持续 typing”的卡住问题。
- 保持并强化“AI typing 无缝替换 AI 正式回复”的交互体验。
- 提升 Job 轮询链路可观测性，出现异常时可快速定位根因。

## 一、状态机与收敛策略

- 统一前端 Job 生命周期：`pending -> streaming -> completed/failed/cancelled/timeout`。
- 任何终态都必须可追踪地进入收尾流程（清理轮询、更新生成态、释放锁、必要时兜底补拉）。
- 保留并优先使用“typing DOM 原位升级为正式消息 DOM”的无缝替换路径，避免闪烁与空窗。

## 二、缓存与一致性策略

- 前端轮询请求显式 `cache: no-store`，并附带时间戳参数防止中间层缓存命中旧状态。
- 后端 `/chat/job/{job_id}` 返回 `Cache-Control: no-store/no-cache` 等响应头，形成双保险。
- 前后端均记录和透传关键缓存头，用于快速判定是否出现缓存污染。

## 三、关键日志与诊断策略

- 增加统一 `JobTrace` 日志事件：
  - `polling_start`
  - `status_changed`
  - `status_stalled`
  - `terminal_completed`
  - `terminal_failed`
  - `terminal_cancelled`
  - `polling_timeout`
  - `poll_http_not_ok`
  - `poll_request_error`
- `status_stalled` 触发条件：`pending/streaming` 状态持续超过阈值并重复出现。
- 日志字段最小集合：`jobId/charId/mode/pollCount/elapsedMs/statusStableMs/headers`。

## 四、角色 ID 一致性策略

- 统一使用字符串化比较字符 ID，避免 `number` 与 `string` 混用导致分支漏触发。
- Job 轮询、渲染判定、同步兜底三个链路保持一致比较规则。

## 五、分阶段执行

- Phase A（已执行）：
  - 前端轮询 no-store + 时间戳。
  - 后端 Job 接口 no-cache 响应头。
  - JobTrace 与停滞日志。
  - 关键路径 charId 归一化比较。
- Phase B（建议下轮）：
  - 将 Job 收尾逻辑抽象为单一收敛函数，减少多分支重复收尾。（已执行：`settleJobTerminal`）
  - 增加“状态迁移计数指标”，支持按角色聚合排查。
- Phase C（建议下轮）：
  - 增加管理端诊断面板（最近 N 条 JobTrace + 快速过滤）。
  - 引入轻量告警（例如 `status_stalled` 连续触发超过阈值）。

## 六、验收标准

- 在游戏模式与锁分模式下，连续 50 次请求中无“completed 后 typing 持续 > 5s”案例。
- 日志可完整还原每个 Job 的状态迁移与终态收敛路径。
- 切后台、切角色、切回前台三种场景下，均可稳定收敛并显示正式回复。
