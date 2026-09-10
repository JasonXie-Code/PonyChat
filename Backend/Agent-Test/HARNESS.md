# 普通对话 DeepSeek Harness 版

2026-09-06。使用官方 `deepseek-harness-sdk==0.1.2rc1` 与同版本 runtime。

## 使用

安装 `Backend/conf/requirements.txt` 依赖，在 Android 设置 → AI 功能 → 普通对话引擎选择“DeepSeek Agent（实验）”。默认仍为“现有流程”，下一次发送生效。
HTTP 保留 `mode: "normal"`，`normal_engine: "harness"` 选择 agent，`pipeline` 选择原流程。
两条路径均强制使用 `deepseek-v4-flash-vision-exp`、开启思考、`reasoning_effort: "low"`。凭据只从服务端环境变量解析。

## 自主回复与记忆

每轮输入角色设定、近期原始聊天（最多20条）、单独的最新用户消息、必要时间和环境。
Harness Agent 直接生成自然回复；后端只做协议校验、渲染与交付，不再进行第二次角色正文生成。
简单聊天无需调用工具。旧的 `normal_agent.py` 材料代理保留供历史比较脚本使用。

按需能力包括：

- `read_history`：仅当前账号、角色、会话的更早可见原始消息，支持分页。
- `search_memory`：读取长期偏好、约定或当前会话场景，也可按需读取旧记忆材料。
- `stage_memory`：附来源消息ID、发生时间和版本，暂存记忆草案。
- `inspect_current_images`：仅本轮实际上传的图片。

长期事实按账号及角色隔离，当前场景进一步按会话隔离。数据库使用独立 `agent_memory_entries` 表，保存历史版本及替代关系，不修改原始聊天或旧记忆表。
更新已有记录需要 `entry_id` 和 `expected_version`；并发冲突整批回滚。
只有回复成功持久化且请求仍是当前generation，草案才提交；失败、取消、被新消息取代时丢弃。
后端限制可引用消息与作用域，模型不能通过参数指定其他账号或数据库。

## 能力边界

共用认证、额度、连发取消、回复持久化和SSE/WS/outbox交付。
当前自主路径主要覆盖文字、按需记忆、当前图片；没有注册实时联网、历史图片或资产生成工具，也不使用旧Step 4关系推断和固定主动追问。不能将它描述为所有多媒体能力均已完全对等。
关闭记忆时不注册记忆读写工具。环境中的旧场景不能覆盖用户最新明确动作。

## 运行隔离

每轮独立SDK session/home，禁用shell、文件编辑和本地文件工具。
工具桥接仅监听本机随机端口并用本轮随机Bearer验证，校验JSON参数与长度。
整轮180秒，最多8次工具尝试（含非法参数）。明确要求记住且有合法来源时，只有成功stage才满足完成条件；漏写最多给同一agent一次具体反馈补做，仍失败则报错，不静默改用旧pipeline。两次共用时间/工具预算并合计计费。
时间字段提供由原始时间戳派生的UTC ISO元数据；可控参数错误通过422传回agent用于修正，普通内部异常仍隐藏。
`NORMAL_AGENT_AUTONOMOUS_TRACE` 记录调用次数、token及工具轨迹；不记录凭据。

## 验证

`test_agent_memory_store.py` 测试隔离、来源、版本、并发、取消及原记录不变；`test_autonomous_normal.py` 测试输入窗口、工具及气泡协议；`test_harness_runtime.py` 测试桥接鉴权、参数、预算和生命周期。
`run_autonomous_comparison.py` 在隔离源码及临时SQLite中执行合成多轮真实模型测试。
结果位于 `reports/autonomous-20260906.json`，旧三阶段比较保留在 `harness-comparison-20260906.*`。
小样本只反映这些输入，不证明所有聊天质量更好；真实音频、多设备同步需独立验收。

Android构建使用 `Android-App/tools/build.ps1` 固定JDK与短路径临时目录，避开本机JDK NIO管道错误。
签名APK上传工具为 `Android-App/tools/publish_apk.py`，验签并核对公开下载完整文件哈希。

## 上游

- https://github.com/deepseek-ai/deepseek-harness
- https://github.com/deepseek-ai/deepseek-harness/blob/master/python/sdk/README.md
