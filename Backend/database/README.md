# PonyChat 后端数据库

当前后端使用 SQLite。生产数据库只应存在于服务器运行目录，例如：

```text
/opt/ponychat/Backend/database/ponychat.db
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

生产数据以 Server-USA 上运行中的数据库为准；不要把 `.db`、`.db-wal`、`.db-shm` 或备份数据提交到代码仓库。MLP RAG 的 `mlp_vectors.db` 也是运行时索引，本地默认放在 `%LOCALAPPDATA%/PonyChat/mlp_vectors.db`，生产可继续使用服务器上的既有路径或通过环境变量显式指定。

当前主要表包括用户、角色、普通对话、Galgame / 锁分数据、长期记忆、主动消息 outbox、陪玩历史、网页可见角色标记，以及素材库 `media_assets`。素材图片二进制存储在 `media_assets.file_data`，由 `/api/admin/assets/{id}/file` 按需返回。
