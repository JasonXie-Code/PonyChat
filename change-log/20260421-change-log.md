# 2026-04-21 Change Log

## 文档与仓库对齐

- Galgame 分步提示词位于 `Backend/galgame/seq_prompts/`。
- 本地快捷入口为仓库根目录 `AAA启动后端.bat`、`AAA安装调试App.bat`。
- 快捷入口会先经 `Backend/scripts/launch/AAA_deploy_portable.bat` 绿色部署，再调用 `AAA_launch_backend.py` / `AAA_install_debug_app.py` 与便携 Python。
- `var/ChatMonitor/` 为 ChatMonitor 同步服务器聊天调试日志的本地落盘，包含 `.chatlogs/` 等运行时内容，不入库。
- 项目结构中的 `var/` 路径已校正。
- 代码路径统一为 `Backend/` 前缀，例如 `Backend/chat_modules/`。
