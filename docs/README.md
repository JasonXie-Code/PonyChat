# PonyChat 文档索引

> 最后更新：2026-07-05

本目录只维护项目设计、测试、审计和计划文档。角色资料、RAG 数据集、第三方源码文档和历史归档不在日常文档更新范围内。

## 入口文档

| 文档 | 用途 |
| --- | --- |
| `../README.md` | GitHub 入口和本地验证命令 |
| `../PROJECT.md` | 产品状态、模式边界、目录约定 |
| `../SERVER.md` | 生产服务器、域名和部署说明 |
| `../Android-App/README.md` | Android 客户端构建与版本 |
| `../Backend/deploy/README.md` | 后端部署与远程测试要求 |
| `../PonyChat-Website/TTS/PonyChat-Voice-Lab.md` | 语音站与 TTS 网关说明 |

## 子目录

| 路径 | 内容 |
| --- | --- |
| `design/` | 产品模式、聊天、Galgame、小游戏和滚动行为设计 |
| `test/` | 人工/矩阵测试流程与达标卷 |
| `plans/` | 管理后台、语音消息等实施计划 |
| `audits/` | 数据完整性、键盘、模块化等审计记录 |
| `archive/` | 历史整理和旧报告，通常不再更新 |

## 维护规则

- 当前事实写在入口文档；历史流水写入 `change-log/YYYYMMDD-change-log.md`。
- 测试流程变更优先同步 `docs/test/测试流程.md` 和 `Backend/deploy/README.md`。
- 不把密钥、数据库、运行日志、APK 构建产物、TTS 输出和本机自动保存文件写入文档或 Git。

