# 根目录启动入口

三个 `.bat` 均可从任意工作目录调用，优先使用项目 `.venv`，回退到 `P:\Tools\python`。使用 `--help` 查看参数；`--check` 只检查环境，不启动服务、不安装依赖、不重写项目配置。双击启动失败时会停留显示错误。

| 入口 | 默认行为 | 额外参数 |
| --- | --- | --- |
| `AAA启动后端.bat` | 启动本机聊天、CosyVoice、搜索和按现有配置启用的隧道；已有守护进程时只检查健康状态 | `--status` 查看状态 |
| `AAA安装调试App.bat` | 打开现有 App 安装调试菜单，复用共享 Android SDK、JDK 和 Gradle 缓存 | `--check` 检查环境 |
| `AAA_start_medium_perf_emulator.bat` | 启动 `Medium_Phone_API_36.1`；同名模拟器已启动时直接复用 | `--avd NAME`、`--cores 16`、`--memory 16384` |

后端使用 `scripts/ops/local_stack.py` 和 `.env.local-stack`，启动前要求 `var/local-stack/migration.ready` 存在。缺少环境时返回错误；部署配置见 [本机迁移记录](local-backend-migration-20260909.md)。守护进程日志位于 `var/local-stack`。健康检查成功表示三个本机 HTTP 服务就绪；隧道进程状态不等于公网链路验收。

模拟器优先使用 `P:\Tools\android-sdk`，保留原来的 16 核、16 GB、高优先级及 GPU 加速配置，CPU 数不超过本机逻辑核心数。新进程启动后仍需等待 Android 开机；启动日志保存在 `var/emulator`。不会更改其他模拟器进程的优先级。

共享实现：`scripts/ops/root_launcher.py`。验证命令：

```powershell
.\.venv\Scripts\python.exe -m unittest scripts.ops.test_root_launcher
.\AAA启动后端.bat --check
.\AAA启动后端.bat --status
.\AAA安装调试App.bat --check
.\AAA_start_medium_perf_emulator.bat --check
```
