# PonyChat 后端数据库

> 文档状态：2026-09-09 已迁移运行目录。易变的版本、部署和服务状态在使用前仍需现场验证。

当前后端使用 SQLite。本次迁移后的生产数据库位于本机：

```text
P:\PonyChat\Backend\database\ponychat.db
```

本地开发默认使用系统用户数据目录，不再写入代码仓库：

```text
%LOCALAPPDATA%/PonyChat/ponychat.db
```

也可以用环境变量显式指定：

```text
PONYCHAT_DB_PATH
PONYCHAT_BACKUP_DIR
PONYCHAT_MLP_VECTOR_DB_PATH
MLP_VECTOR_DB_PATH
```

数据库初始化、表结构和迁移逻辑位于 `Backend/db/database.py`，后端启动时由 `Backend/config.py` 调用 `init_database(DB_PATH)`。

生产数据以本机 `.env.local-stack` 指定的数据库为准；不要把 `.db`、`.db-wal`、`.db-shm` 或备份数据提交到代码仓库。MLP RAG 的 `mlp_vectors.db` 也是运行时索引，本地默认放在 `%LOCALAPPDATA%/PonyChat/mlp_vectors.db`，本次迁移保留 `Backend/data` 中的既有索引，通过环境变量显式指定时以实际配置为准。

当前主要表包括用户、角色、普通对话、Galgame / 锁分数据、长期记忆、主动消息 outbox、陪玩历史、网页可见角色标记，以及素材库 `media_assets`。素材图片二进制存储在 `media_assets.file_data`，由 `/api/admin/assets/{id}/file` 按需返回。

迁移先验证停机源库的 SHA-256、65 张表行数和 SQLite 完整性，再仅转换三个日志索引路径列；聊天内容、账号、记忆及登录 token 版本保持原数据。服务器历史备份保留原处，不作为当前生产库。验收细节见 [迁移记录](../../docs/operations/local-backend-migration-20260909.md)。
