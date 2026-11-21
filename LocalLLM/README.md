# LocalLLM - Windows 本地大模型服务

> 2026-09-11：已接入 Qwen3.5-4B 128K 视觉模型。当前启动、切换及验收方式见 [OPERATIONS.md](OPERATIONS.md)。以下为迁入前旧启动器说明，其中旧后端控制台命令已不适用。

基于 **llama.cpp**（b8638，CUDA 12.4）的本地推理服务，通过 OpenAI 兼容 HTTP API 为 PonyChat 后端提供本地大模型能力。

## 目录结构

```
LocalLLM/
├── models/                  # 模型文件（不进 Git）
│   ├── Qwen3.5-4B/          # 4B 轻量版（速度优先）
│   └── Qwen3.5-9B/          # 9B 主力版（当前 config.json 默认）
├── server/
│   ├── config.json          # llama-server 启动参数（端口、模型路径、上下文大小等）
│   └── bin/                 # llama-server.exe + CUDA DLL（完全自包含）
├── scripts/
│   ├── launcher.py          # Python 一键启动脚本（含 GPU 检测、自动下载、健康等待）
│   ├── start_server.ps1     # PowerShell 简易启动脚本
│   ├── setup.ps1            # 下载 llama.cpp 二进制的安装脚本
│   └── test_api.py          # API 连通性测试脚本
├── tools/
│   └── python/              # 便携 Python 3.10 运行时（用于无系统 Python 的环境）
└── logs/
    └── server.log           # llama-server 运行日志
```

## 日常使用

### 通过 PonyChat 后端控制台管理（推荐）

在 `AAA启动后端.py` 控制台中输入：

```
llm             # 开启 / 关闭本地大模型
llm status      # 查看 GPU / 进程 / 当前模型状态
llm list        # 列出 models/ 下所有可用模型目录
llm use <名称>  # 切换模型（更新 config.json 后自动重启）
```

### 手动独立启动（调试用）

```powershell
# PowerShell
.\scripts\start_server.ps1             # 默认：多模态 + GPU
.\scripts\start_server.ps1 -NoMmproj  # 禁用视觉编码器（省 ~1 GB 显存）
.\scripts\start_server.ps1 -CPU       # 强制纯 CPU
```

```bash
# Python（含自动下载和部署检查）
tools\python\python.exe scripts\launcher.py
```

### 验证服务

```bash
tools\python\python.exe scripts\test_api.py
```

## 配置

所有启动参数集中在 `server/config.json`，常用字段：

| 字段 | 说明 |
|------|------|
| `port` | 监听端口（默认 8068） |
| `model` | 主模型路径（相对 LocalLLM/ 的路径） |
| `mmproj` | 多模态投影文件路径（可选） |
| `n_ctx` | 上下文长度（当前 131072） |
| `n_gpu_layers` | GPU offload 层数，99 = 全部 |
| `n_predict` | 单次最大生成 token 数 |
| `reasoning_budget` | 思考 token 预算，0 = 禁用思考链 |

## 前提条件

- NVIDIA GPU（无 GPU 时后端 `llm` 命令直接报错）
- 模型文件放在 `models/<目录名>/`（.gguf 格式）
- `server/config.json` 中 `model` 字段已指向正确路径

## 模型约定

- 模型统一放在 `models/`，不提交到版本库
- 每个模型一个子目录，目录名即为 `llm use <名称>` 参数
- `mmproj-*.gguf` 与主模型放在同一目录，自动识别
