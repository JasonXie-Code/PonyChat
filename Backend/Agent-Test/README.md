# PonyChat Agent Test

真实 DeepSeek Harness 并行实验版见 [HARNESS.md](HARNESS.md)。下述 Goose 原型仍是历史 mock，不代表 Harness 的真实模型测试结果。

> 文档状态：2026-08-09 已复核。易变的版本、部署和服务状态在使用前仍需现场验证。

这个目录是普通对话 agent 化的本地测试版。目标不是替换线上 `/api/chat`，而是验证“把角色设定、对话上下文、最新用户输入、记忆碎片和摘要交给一个 agent，由 agent 自己安排流程”的形态。

当前机器没有检测到 `goose` 命令，所以这里先提供两层：

- `run_normal_chat_sim.py`：不依赖 goose 的本地模拟器，可直接跑通普通对话场景。
- `mcp_server.py` + `goose.recipe.yaml`：给 goose 使用的 stdio MCP 工具服务和 recipe 草案。安装 goose 后，可以把这个目录作为测试 extension 接入。

## 快速测试

从仓库根目录运行：

```powershell
python Backend\Agent-Test\export_system_characters.py --limit 3
python Backend\Agent-Test\run_normal_chat_sim.py --message "今天有点累，陪我聊会儿" --character-index 0
python Backend\Agent-Test\mcp_server.py --self-test
```

默认会从 `Backend/database/ponychat.db` 导出 `System` 用户下可见角色，缓存到 `Backend/Agent-Test/cache/system_characters.json`。缓存文件被 `.gitignore` 忽略，避免把服务器/本地角色资料提交进仓库。

从线上生产站下载 System 角色设定作为备用：

```powershell
python Backend\Agent-Test\download_online_system_characters.py
```

这个命令默认读取 `https://www.ponychat.org/api/load_characters?username=System&lazy=true`，写入：

- `Backend/Agent-Test/cache/system_characters.online.json`：线上备份。
- `Backend/Agent-Test/cache/system_characters.json`：当前本地测试默认缓存。

如果以后有服务器端导出的 JSON 地址，可以这样下载：

```powershell
$env:PONYCHAT_AGENT_TEST_SYSTEM_CHARACTERS_URL="https://example.com/system-characters.json"
python Backend\Agent-Test\export_system_characters.py --remote-url $env:PONYCHAT_AGENT_TEST_SYSTEM_CHARACTERS_URL --refresh
```

远端 JSON 可以是角色数组，也可以是 `{"characters": [...]}`。字段至少需要 `id`、`name`，推荐包含 `data`、`prompt` 或 `persona_prompt`。

## Goose 接入

安装 goose 后，在本目录启动 recipe：

```powershell
cd Backend\Agent-Test
goose run --recipe goose.recipe.yaml
```

如果要让 goose 使用项目里的 DeepSeek V4 Flash 配置，使用：

```powershell
Backend\Agent-Test\run_goose_deepseek.ps1
```

这个脚本会读取 `Backend/conf/models/deepseek.json` 中的 `deepseek-v4-flash`，临时设置 goose 所需的 `GOOSE_PROVIDER`、`GOOSE_MODEL`、`GOOSE_PROVIDER__HOST`、`GOOSE_PROVIDER__API_KEY`，并兼容 goose OpenAI provider 当前实际读取的 `OPENAI_API_KEY`、`OPENAI_HOST`、`OPENAI_BASE_PATH`。密钥不会写入 goose recipe，也不会写入 Git。

recipe 会让 goose 通过 `mcp_server.py` 调用这些工具：

- `load_system_characters`：加载/刷新 System 角色。
- `get_character_profile`：读取一个角色的公开档案和 persona，用于让 goose 自己生成角色回复。
- `search_character_setting`：按 query 检索角色设定片段，避免整段 persona 每轮塞进上下文。
- `read_dialogue_context`：按 `context_id` 读取本轮原始对话上下文的最近消息或相关消息。
- `normal_chat_turn`：模拟普通聊天 agent 回合。
- `search_memory_fragments`：在传入的记忆碎片中做轻量检索。
- `read_summaries`：读取日/周/月/年摘要。
- `update_working_state`：根据最新输入维护临时工作状态。
- `export_conversation_document`：把对话转成 Markdown 文档。
- `describe_pose_image_prompt`：根据角色设定和当前请求生成图片提示词。

## 设计边界

这个测试版刻意不实现短期/中期记忆，只接受：

- 最近对话 `messages`
- 记忆碎片 `memory_fragments`
- 日/周/月/年摘要 `summaries`
- 当前回合工作状态 `working_state`

`agent.py` 里的回复生成是 deterministic mock，不调用线上模型。它用于验证 agent 编排形态、工具输入输出和鹅式多步调用，不代表最终角色回复质量。

## Stateless Turn Test

更接近目标架构的测试是每轮不使用 goose session：

```powershell
python Backend\Agent-Test\run_stateless_pinkie_context_test.py
```

每一轮只把 `character_id`、`context_id`、`latest_user_input` 和本轮目的发给 goose；原始对话上下文写入 `Backend/Agent-Test/runs/*.json`，goose 只能通过 `read_dialogue_context` 按需读取，角色设定只能通过 `search_character_setting` 按需读取。最终输出只应是本轮回复正文。
