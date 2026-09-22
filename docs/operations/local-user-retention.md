# 本机用户清理与数据存档

## 2026-09-09 重启后验收

- **数据操作已全部完成**。完整存档：`P:\PonyChat\Backend\数据存档\20260909-210152`，1,224,349 个文件、28,893,319,976 字节。独立完整数据库为 `ponychat.full-backup.db`；恢复说明为存档内 `备份及清理结果.md`。
- 实际运行库仅剩 Jason（1）、System（73）；68 个角色、325 段普通对话、29,302 条普通消息。已按用户明确选择删除“柯林”及其 8 段关联对话和记忆。运行库完整性、外键、保留资料指纹和旧日志清空均已验证，见存档内 `LIVE-VERIFIED-BEFORE-START.json`。
- 最后验收：本机、CN IP 和 USA 官网 `/api/health` 全部 HTTP 200，部署标识均为 `local-20260909-cn-ip-5.6.36`；搜索、CosyVoice 也健康。详细结果为存档内 `SERVICE-HEALTH.json`。
- **重启自动启动已验证成功**：`PonyChat Local Backend Stack` 已启用且运行，日志显示 22:00:05 自动启动；守护进程 PID 6396，三个本机服务和两条隧道正常。CN、USA 入口均 HTTP 200。独立 Qwen 任务配置未改变。不要再次执行数据清理。
- **日志误判已纠正**：复查旧清单发现 `tags.jsonl`、`tags_test.jsonl`、`pages/Dishwater Slog.txt`、`pages/Fictional chronology.txt` 被旧规则误认为日志。四个知识库文件已从已验证备份原样恢复，大小和 SHA-256 均匹配。规则改为识别日志目录、明确日志扩展名和独立日志词，保护知识库正文及 JSONL 数据；使用旧清单清理时也重新判定。原始存档和清理凭据保持不变，纠正结果见 `POST-REBOOT-RESTORED.json`。
- 根目录三个启动入口此前已更新并提交 `dffd63f`，8 项启动测试通过。数据保留和日志分类测试共 12 项；重启后的复核记录见存档内 `POST-REBOOT-VERIFIED.json`。

用户重启完成后已继续验收，未再次执行数据库清理。

本次范围是本机正式数据库：保留 `Jason`（ID 1）、`System`（ID 73）及其角色、对话、记忆和引用的图片；清除其他用户及孤立资料、全部模型调用日志和运行日志、数据库日志索引与 Agent 进度。用户另外明确选择删除其他用户的“柯林”角色及 Jason 引用它的 8 段对话和关联记忆。全局素材和知识库保留。历史备份与迁移存档不作为运行数据清理。

私密存档位于 `Backend/数据存档/<时间>/`，该目录只跟踪 `.gitignore`。操作前禁用并停止 `PonyChat Local Backend Stack`，确认聊天、搜索、CosyVoice 和隧道子进程停止；完成后恢复该任务。独立 Qwen 任务配置不变。

## 备份与清理顺序

1. 停止服务，执行 SQLite WAL checkpoint；记录保留账号身份。
2. `archive_runtime_directories.py <存档目录>` 保存独立完整数据库并验证 SHA-256、完整性及全部表行数。日志目录在同盘内原样移动到存档的 `files/`，验证 NTFS 目录身份及全部相对路径、大小、修改时间。其他运行资料和零散日志逐文件复制并核对 SHA-256。
3. `retain_local_users.py prepare <存档目录>` 只修改生成的数据库副本。逐表保存保留资料的内容指纹；对无外键的用户名资料、记忆版本、头像与聊天图片做显式归属处理。遇到未知表、保留资料变化或外键错误会停止。旧日志全文索引清空重建，原表结构及触发器恢复不变。
4. `retain_local_users.py apply <存档目录>` 要求 `VERIFIED.json`、`CLEANUP-PREPARED.json` 有效且原数据库仍匹配备份。先复制并校验候选文件，再关闭原数据库 WAL，在停机状态下原子替换数据库；清空辅助进度库，并删除已经核对备份的零散运行日志和应删除的用户/角色恢复快照。
5. 恢复服务前再次验证保留数据、账号数量、外键与日志清空状态；恢复后检查本机及公开入口健康。服务恢复后正常产生的新日志不属于清理前的历史日志。

运行示例（使用项目根目录的 `.venv\Scripts\python.exe`）：

```text
Backend/maintenance/archive_runtime_directories.py <存档目录>
Backend/maintenance/retain_local_users.py prepare <存档目录> --remove-referenced-character 9d66f982-c09c-43be-baa3-433058d425b8
Backend/maintenance/retain_local_users.py apply <存档目录>
Backend/maintenance/test_retain_local_users.py
Backend/maintenance/test_archive_local_runtime.py
```

## 恢复

恢复前同样暂停服务并另存当前数据库。使用 SQLite backup API 将存档中的 `ponychat.full-backup.db` 恢复到 `Backend/database/ponychat.db`；将存档 `files/` 内所需内容按项目相对路径复制回项目。先检查数据库完整性，再恢复服务。原日志文件保持原样，无需解压。

`database-before.json`、`manifest.jsonl.gz`、`VERIFIED.json`、`CLEANUP-PREPARED.json`、`CLEANUP-COMPLETED.json` 保存完整性和变更记录。未完成 ZIP 封装的临时产物不用于恢复。
