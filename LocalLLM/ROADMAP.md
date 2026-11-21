# ROADMAP

## 目标

在 Windows 本地运行 GGUF 大模型推理服务，对外提供 OpenAI 兼容 API，支持纯文本和多模态（视觉）输入。

## 阶段规划

### Phase 0 - 项目切换（已完成）

- [x] 明确项目主方向为 Windows 服务器
- [x] 新建路线图与项目说明文档
- [x] 移除 Android 工程目录与入口脚本
- [x] 移除安卓遗留工具目录（android-sdk / cmake / gradle-home / jdk / ndk）

### Phase 1 - 服务骨架（已完成）

- [x] 建立 `server/` 目录和 `server/config.json` 配置
- [x] 下载 llama.cpp server b8638（CUDA 12.4）二进制到 `server/bin/`（含 gemma4 等架构支持）
- [x] 下载 CUDA 12.4 运行时 DLL 到 `server/bin/`（项目自包含）
- [x] `scripts/setup.ps1`：自动下载更新二进制
- [x] `scripts/start_server.ps1`：启动服务，支持 mmproj 多模态、CPU 降级
- [x] `scripts/test_api.py`：健康检查 + 多用例文本对话测试
- [x] 首次实际启动成功，服务监听 `http://127.0.0.1:8068`
- [x] 多模态 mmproj 正常加载（Qwen3.5-9B BF16 视觉编码器）
- [x] API 测试通过，RTX 4090 D VRAM 占用约 10 GB，剩余 14 GB

### Phase 1.5 - 启动器改进（已完成）

- [x] 创建 `一键启动.bat`（调用内置 Python，彻底避免编码问题）
- [x] 创建 `scripts/launcher.py`（统一承载部署检查 + 服务启动逻辑）
- [x] 启动时交互选择 `models/` 主模型（`--no-menu` / `--model` 供脚本化调用）
- [x] 每次启动查询 GitHub 最新 llama.cpp release（网络失败则跳过）；端口就绪后可选自动打开浏览器（`open_browser`）
- [x] 启动前自动 kill 旧 llama-server.exe，等待显存释放，防止 VRAM 叠加
- [x] 服务器日志直接输出到启动终端（用户可实时看到所有运行日志）
- [x] 同时保留 `logs/server.log` 文件记录

### Phase 2 - 推理能力（进行中）

- [ ] 流式输出（SSE）调用示例脚本
- [ ] 多模态图像输入端到端测试（上传图片 → 描述）
- [ ] 补充参数调优记录（ctx、batch、思维链 budget_tokens 等）
- [ ] 局域网访问支持（host 改 0.0.0.0，防火墙规则脚本）
- [ ] 并发与超时配置优化

### Phase 3 - 可运维化

- [ ] 日志分类（访问日志、错误日志）
- [ ] CPU/GPU/内存监控脚本
- [ ] 开机自启（Task Scheduler 或 NSSM）
- [ ] 操作手册（启动、停止、换模型、排障）

## 验收标准（MVP）✅ 已达成

- ✅ 一条命令启动服务（`.\scripts\start_server.ps1`）
- ✅ `test_api.py` 通过健康检查并返回正确回复
- ✅ 多模态 mmproj 正常加载，flash attention 已启用
- ✅ 有运行日志（`logs/server.log`）
