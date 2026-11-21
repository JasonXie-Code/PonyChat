# PonyChat 本地 Qwen3.5-4B

Qwen3.5-4B Q4_K_M 主模型及同目录 BF16 视觉投影，通过 llama.cpp 接入 PonyChat。

- API：`http://127.0.0.1:8068/v1`
- 模型 ID：`qwen3.5-4b-local`
- 上下文：131072 tokens，单槽；输入与输出共同占用 128K
- GPU 全层加载；Q8_0 KV cache；输出上限 8192；默认关闭思考
- 当前已有权重是 HauhauCS 派生量化版本，并非官方原始权重

## 启动与切换

双击 `一键启动.bat` 启动主模型及视觉投影。项目根目录 `AAA启动后端.bat` 仅在后端选中 Qwen 时检查并启动本地模型，复用已启动的实例；选中 DeepSeek 时不会自动加载 Qwen。

双击 `切换到Qwen.bat` 将全局默认设为本地 Qwen；双击 `切换到DeepSeek.bat` 切回 DeepSeek。配置热加载，下一次请求生效，无须重启后端。切换不会停止本地服务。

后端模型选项：**Qwen3.5-4B 本地 · 128K · 视觉**。用户端不提供模型切换；普通聊天及游戏统一使用后端全局选项，忽略遗留用户偏好和客户端 `model_id`。后台记忆任务及陪玩专用推理仍使用原专用模型。

从项目根目录运行：

```powershell
.venv/Scripts/python.exe LocalLLM/scripts/manage.py start
.venv/Scripts/python.exe LocalLLM/scripts/manage.py status
.venv/Scripts/python.exe LocalLLM/scripts/manage.py qwen
.venv/Scripts/python.exe LocalLLM/scripts/manage.py deepseek
.venv/Scripts/python.exe LocalLLM/scripts/manage.py stop
.venv/Scripts/python.exe -X utf8 LocalLLM/scripts/verify_ponychat.py
```

## 配置与验收

启动参数在 `server/config.json`，模型清单在 `Backend/conf/models/local.json`。本地模型使用 SDK 的 pi-ai OpenAI 兼容适配器，显式声明图片输入和 131072 上下文。进程池按模型、服务地址、适配器及配置隔离。

验收脚本用合成输入经过实际 Agent 适配器测试文字、图片及工具往返，结果保存到 `docs/testing/local-qwen35-20260911/`。图片测试须正确识别左右颜色和形状。128K 由服务器槽位和 SDK 配置验证；未进行填满 128K 的长文质量或并发压力测试。

权重、CUDA 二进制、第三方源码及日志不纳入 Git。服务仅监听本机。失败查看 `logs/qwen.stderr.log`。独立本地模型暂无崩溃自动重启，再次运行启动入口可恢复。

参考：[Qwen 模型说明](https://huggingface.co/Qwen/Qwen3.5-4B)、[Harness 自托管模型配置](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/llm/llm-pi-ai/README.md)。
