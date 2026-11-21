# PROJECT

## 项目名称

LocalLLM

## 项目定位

在 Windows 环境运行的本地大模型服务器项目。使用 `llama.cpp server` 作为推理引擎，提供 OpenAI 兼容 API，支持多模态（文字 + 图像）输入，供本地应用或内网系统调用。

## 当前状态 ✅ MVP 已完成

| 项目 | 状态 |
|------|------|
| 推理引擎 | llama.cpp server b8638（已就绪；含 gemma4 等新架构）|
| CUDA | 12.4，运行时 DLL 已打包到 `server/bin/` |
| 模型 | Qwen3.5-9B Q4_K_M（5.6 GB）|
| 视觉编码器 | mmproj BF16（922 MB），已加载 |
| Flash Attention | 已启用（auto）|
| VRAM 占用 | ~10 GB / 24 GB（RTX 4090 D）|
| API | `/v1/chat/completions`，OpenAI 兼容 ✅ |
| 服务地址 | `http://127.0.0.1:8068` |
| Android 方向 | 已移除 |

## 目录结构

```text
P:\Utility\LocalLLM\
├── models\
│   ├── README.md                   # 模型注册表
│   └── Qwen3.5-9B\
│       ├── *.Q4_K_M.gguf          # 主模型（5.6 GB）
│       └── mmproj-*.BF16.gguf     # 视觉编码器（922 MB）
├── server\
│   ├── config.json                 # 服务参数配置
│   └── bin\                        # llama-server.exe + CUDA DLL（自包含）
├── scripts\
│   ├── setup.ps1                   # 下载/更新 llama.cpp 二进制
│   ├── start_server.ps1            # 启动服务
│   └── test_api.py                 # API 测试
├── logs\                           # 运行日志
├── tools\
│   └── python\                     # 内置 Python 3.10（用于测试脚本）
├── ROADMAP.md
├── PROJECT.md
└── README.md
```

## 快速启动

```
双击  一键启动.bat
```

启动器会在终端列出 **0 = 沿用 `server/config.json`**，以及本机 `models/` 下扫描到的其他主模型（`.gguf` 且文件名不含 `mmproj`）；选择序号后回车即可。同目录若存在视觉编码器（文件名含 `mmproj`），会自动一并匹配。

非交互或脚本调用：`.\一键启动.bat --no-menu`（仅用配置文件），或 `.\一键启动.bat --model models\子目录\主模型.gguf`。

每次启动时，启动器会尝试访问 GitHub 查询 **llama.cpp 当前最新 release** 并与本地 `llama-server` 比对（`--version` 合并输出中取 **最后一条** `version:`/`build:`，避免被 CUDA 等前置日志干扰）。对齐后会写入 `server/bin/llama_installed.json`；**仅当无法从 exe 解析版本时**才采信该文件，以免记录与磁盘旧文件不一致时误判。**不在下载前删除** `llama-server.exe`，解压直接覆盖，避免中断下载后丢失可执行文件。网络不可用时跳过在线检查，仅保证不低于项目 `launcher.py` 中的保底版本。端口就绪后默认 **自动打开浏览器** 访问服务根地址；可在 `server/config.json` 中设置 `"open_browser": false` 关闭。

或命令行：

```powershell
# 推荐（自动处理编码、自动清旧进程）
.\一键启动.bat

# 高级用法（PowerShell 直接调用）
.\scripts\start_server.ps1            # 多模态 + GPU
.\scripts\start_server.ps1 -NoMmproj  # 禁用视觉编码器（省 ~1.5 GB 显存）
.\scripts\start_server.ps1 -CPU       # 强制纯 CPU

# 测试 API
.\tools\python\python.exe scripts\test_api.py
```

## 技术选型

| 组件 | 选型 |
|------|------|
| 推理引擎 | llama.cpp server b8638 |
| CUDA 运行时 | 12.4（项目自包含 DLL）|
| 模型格式 | GGUF（Q4_K_M）|
| 视觉编码器 | GGUF mmproj（BF16）|
| API 协议 | OpenAI Chat Completions |
| 配置 | JSON |
| 启动入口 | `一键启动.bat` → `scripts/launcher.py` |
| 高级启动 | PowerShell `scripts/start_server.ps1` |
| 测试脚本 | Python 3.10（仅标准库）|

## 注意事项

- Qwen3.5 是思维链（CoT）模型，内部生成 `<think>` 推理，客户端 `max_tokens` 建议 ≥ 2048
- `server/bin/` 包含所有运行时 DLL，可在无独立 CUDA 安装的机器上运行（但需要 NVIDIA 驱动）
- 模型文件不提交 Git，迁移时需重新放置到 `models/` 对应目录
- 若日志出现 `unknown model architecture`（例如 `gemma4`），表示 **llama-server 构建过旧**；请使用 **b8638 或更新** 的二进制（一键启动器会在构建号低于项目要求时自动下载替换，亦可手动运行 `scripts\setup.ps1`）
- **启动方式与参数差异**：通过 `一键启动.bat` / `launcher.py` 启动时，`server/config.json` 中的 `n_predict`、`reasoning_budget`、`cache-type-k`、`cache-type-v` 等扩展参数会由 `launcher.py` 解析后逐一传入 `llama-server.exe`；若直接使用 `scripts/start_server.ps1` 手动启动，这些字段**不会**被自动读取，需在 ps1 脚本中手动补充对应的命令行参数，否则将以 llama-server 默认值运行。
