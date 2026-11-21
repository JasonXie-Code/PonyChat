

class Database:
    """数据库访问类 - 支持连接池和 WAL 模式"""
    
    # 连接池大小。normal 聊天已拆成多阶段并会并发执行工具，默认池太小会频繁创建临时连接。
    POOL_SIZE = max(5, int(os.getenv("PONYCHAT_DB_POOL_SIZE") or "16"))
    
    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        """
        初始化数据库连接
        
        参数：
            db_path: 数据库文件路径
        """
        self.db_path = os.path.abspath(db_path)
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._initialized = False
        self._migrations_done = False
        # 连接池
        self._pool: asyncio.Queue = asyncio.Queue(maxsize=self.POOL_SIZE)
        self._pool_initialized = False
        self._pool_lock = asyncio.Lock()
    
    async def _configure_connection(self, db: aiosqlite.Connection):
        """为连接设置全局 PRAGMA 优化"""
        await db.execute("PRAGMA journal_mode = WAL")        # WAL 模式提升并发读写
        busy_timeout_ms = int(os.getenv("PONYCHAT_SQLITE_BUSY_TIMEOUT_MS") or "30000")
        await db.execute(f"PRAGMA busy_timeout = {max(5000, busy_timeout_ms)}")
        await db.execute("PRAGMA synchronous = NORMAL")       # 平衡性能与安全
        await db.execute("PRAGMA foreign_keys = ON")          # 启用外键约束
        await db.execute("PRAGMA cache_size = -8000")         # 8MB 缓存
        await db.execute("PRAGMA temp_store = MEMORY")        # 临时表存内存
    
    async def _init_pool(self):
        """初始化连接池"""
        if self._pool_initialized:
            return
        async with self._pool_lock:
            if self._pool_initialized:
                return
            for _ in range(self.POOL_SIZE):
                conn = await aiosqlite.connect(self.db_path)
                await self._configure_connection(conn)
                await self._pool.put(conn)
            self._pool_initialized = True
            logger.info(f"🔗 [Database] 连接池已初始化 (大小: {self.POOL_SIZE})")
    
    async def acquire(self) -> aiosqlite.Connection:
        """从池中获取连接"""
        if not self._pool_initialized:
            await self._init_pool()
        try:
            conn = self._pool.get_nowait()
        except asyncio.QueueEmpty:
            # 池耗尽时创建临时连接
            logger.warning("⚠️ [Database] 连接池耗尽，创建临时连接")
            conn = await aiosqlite.connect(self.db_path)
            await self._configure_connection(conn)
        return conn
    
    async def release(self, conn: aiosqlite.Connection):
        """归还连接到池"""
        try:
            if getattr(conn, "in_transaction", False):
                await conn.rollback()
                logger.warning("⚠️ [Database] 归还连接时发现未结束事务，已自动 rollback")
        except Exception as e:
            logger.warning(f"⚠️ [Database] 归还连接前 rollback 失败，将关闭连接: {e}")
            try:
                await conn.close()
            except Exception:
                pass
            return
        try:
            self._pool.put_nowait(conn)
        except asyncio.QueueFull:
            # 池已满（临时连接），直接关闭
            await conn.close()
    
    async def init(self):
        """初始化数据库，创建表结构"""
        if not self._initialized:
            try:
                async with aiosqlite.connect(self.db_path) as db:
                    await db.execute("PRAGMA auto_vacuum = FULL")
                    await self._configure_connection(db)
                    await self._migrate_pre_schema_columns(db)
                    await db.executescript(SCHEMA_SQL)
                    await db.commit()
                self._initialized = True
                logger.info(f"✅ [Database] 数据库初始化成功: {self.db_path}")
            except Exception as e:
                logger.error(f"❌ [Database] 数据库初始化失败: {e}")
                raise
        
        # 🔧 [向后兼容] 迁移始终运行（幂等），确保缺失列被补全
        if not self._migrations_done:
            try:
                async with aiosqlite.connect(self.db_path) as db:
                    await self._configure_connection(db)
                    await self._migrate_columns(db)
                self._migrations_done = True
            except Exception as e:
                logger.warning(f"⚠️ [DB迁移] 迁移过程异常: {e}")
        
        # 初始化连接池
        await self._init_pool()
    
    async def _migrate_pre_schema_columns(self, db: aiosqlite.Connection):
        """为旧库补充 SCHEMA_SQL 索引可能引用的列。"""
        await self._migrate_asset_text_columns(db)
        pre_schema_migrations = [
            ("media_assets", "flirt_level", "INTEGER DEFAULT 0"),
            ("media_assets", "send_policy", "TEXT DEFAULT 'always'"),
            ("media_assets", "min_relationship_stage", "TEXT DEFAULT 'stranger'"),
            ("media_assets", "sender_archetypes", "TEXT DEFAULT '[]'"),
            ("media_assets", "blocked_archetypes", "TEXT DEFAULT '[]'"),
            ("media_assets", "custom_tags", "TEXT DEFAULT '[]'"),
            ("media_assets", "intro", "TEXT DEFAULT ''"),
            ("media_assets", "detail", "TEXT DEFAULT ''"),
            ("media_assets", "image_text", "TEXT DEFAULT ''"),
            ("media_assets", "file_data", "BLOB"),
            ("media_assets", "uploader_id", "INTEGER"),
            ("media_assets", "is_active", "INTEGER DEFAULT 1"),
            ("media_assets", "review_status", "TEXT DEFAULT 'ready'"),
            ("media_assets", "allow_user_save", "INTEGER DEFAULT 1"),
            ("characters", "official_source_id", "TEXT"),
            ("characters", "is_official_reference", "INTEGER DEFAULT 0"),
            ("characters", "is_official_source", "INTEGER DEFAULT 0"),
            ("characters", "official_content_hash_at_link", "TEXT"),
            ("messages", "speaker_character_id", "TEXT"),
            ("messages", "speaker_name", "TEXT"),
            ("messages", "speaker_avatar", "TEXT"),
        ]
        changed = False
        for table, column, col_type in pre_schema_migrations:
            try:
                async with db.execute(f"PRAGMA table_info({table})") as cursor:
                    columns = {row[1] for row in await cursor.fetchall()}
                if columns and column not in columns:
                    await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
                    changed = True
                    logger.info(f"[DB pre-migration] Added {table}.{column}")
            except Exception as e:
                logger.warning(f"[DB pre-migration] Failed to add {table}.{column}: {e}")
        if changed:
            await db.commit()

    async def _migrate_asset_text_columns(self, db: aiosqlite.Connection):
        """将素材文本元数据迁移到当前的 intro/detail/image_text 字段结构。"""
        mappings = {
            "description": "intro",
            "usage_hint": "detail",
            "visible_text": "image_text",
        }
        for table in ("media_assets", "user_sticker_assets"):
            try:
                async with db.execute(f"PRAGMA table_info({table})") as cursor:
                    columns = {row[1] for row in await cursor.fetchall()}
                if not columns:
                    continue
                changed = False
                for old_col, new_col in mappings.items():
                    if old_col in columns and new_col not in columns:
                        await db.execute(f"ALTER TABLE {table} RENAME COLUMN {old_col} TO {new_col}")
                        columns.remove(old_col)
                        columns.add(new_col)
                        changed = True
                        logger.info(f"[DB migration] Renamed {table}.{old_col} -> {new_col}")
                    elif old_col in columns and new_col in columns:
                        await db.execute(
                            f"""UPDATE {table}
                                SET {new_col} = {old_col}
                                WHERE COALESCE({new_col}, '') = ''
                                  AND COALESCE({old_col}, '') != ''"""
                        )
                        try:
                            await db.execute(f"ALTER TABLE {table} DROP COLUMN {old_col}")
                            columns.remove(old_col)
                            logger.info(f"[DB migration] Dropped legacy {table}.{old_col}")
                        except Exception as drop_error:
                            logger.warning(f"[DB migration] Failed to drop {table}.{old_col}: {drop_error}")
                        changed = True
                if "ocr_summary" in columns:
                    try:
                        await db.execute(f"ALTER TABLE {table} DROP COLUMN ocr_summary")
                        logger.info(f"[DB migration] Dropped legacy {table}.ocr_summary")
                        changed = True
                    except Exception as drop_error:
                        logger.warning(f"[DB migration] Failed to drop {table}.ocr_summary: {drop_error}")
                if changed:
                    await db.commit()
            except Exception as e:
                logger.warning(f"[DB migration] Failed asset text schema migration for {table}: {e}")
    
    async def _drop_legacy_conversation_archives(self, db: aiosqlite.Connection):
        """移除历史遗留的普通对话恢复快照表，普通聊天以 messages 主表为唯一数据源。"""
        try:
            await db.execute("DROP TABLE IF EXISTS conversation_archives")
            await db.commit()
            logger.info("[DB migration] Dropped legacy conversation_archives")
        except Exception as e:
            logger.warning(f"[DB migration] Failed to drop legacy conversation_archives: {e}")

    async def _migrate_columns(self, db: aiosqlite.Connection):
        """检查并添加缺失的列（向后兼容迁移，幂等且每步独立）"""
        await self._drop_legacy_conversation_archives(db)
        # 允许的表名白名单（防止 SQL 注入）
        allowed_tables = {"conversations", "messages", "galgame_messages", "galgame_lock_messages", "galgame_data", "galgame_lock_data", "characters", "users", "memberships", "daily_chat_usage", "daily_token_usage", "character_memories", "proactive_messages", "proactive_tasks", "relationship_presence_states", "proactive_campaigns", "proactive_touch_attempts", "normal_character_lifecycle", "quick_messages", "companion_sessions", "hall_characters", "message_outbox", "normal_chat_memory", "normal_emotion_state", "normal_scene_state", "normal_image_contexts", "normal_image_context_state", "media_assets", "message_attachments", "message_voice_states", "message_voice_audio_cache", "character_voice_assets", "character_voice_profiles", "user_sticker_assets"}
        migrations = [
            ("messages", "raw_content", "TEXT"),
            ("galgame_messages", "raw_content", "TEXT"),
            ("galgame_messages", "scene_metadata", "TEXT"),  # JSON: Galgame 场景元数据
            ("relationship_presence_states", "relationship_stage", "TEXT NOT NULL DEFAULT 'uncertain'"),
            ("relationship_presence_states", "relationship_page_json", "TEXT NOT NULL DEFAULT '{}'"),
            ("relationship_presence_states", "relationship_page_updated_at_ms", "INTEGER NOT NULL DEFAULT 0"),
            ("relationship_presence_states", "relationship_page_source_json", "TEXT NOT NULL DEFAULT '{}'"),
            ("characters", "sort_order", "INTEGER"),
            ("characters", "is_hidden", "INTEGER DEFAULT 0"),
            ("characters", "hidden_at", "TIMESTAMP"),
            ("characters", "hidden_reason", "TEXT"),
            ("characters", "official_source_id", "TEXT"),
            ("characters", "is_official_reference", "INTEGER DEFAULT 0"),
            ("characters", "is_official_source", "INTEGER DEFAULT 0"),
            ("characters", "official_content_hash_at_link", "TEXT"),
            ("messages", "image_thumbnail", "TEXT"),
            ("galgame_messages", "image_thumbnail", "TEXT"),
            ("galgame_messages", "galgame_options", "TEXT"),  # JSON: 存储游戏选项
            ("messages", "think_translations", "TEXT"),  # JSON: 思考卡片译文 { "think-msgId-0": "中文", ... }
            ("messages", "generation_duration_ms", "INTEGER"),  # AI 生成耗时（毫秒）
            ("galgame_messages", "generation_duration_ms", "INTEGER"),
            ("galgame_lock_messages", "generation_duration_ms", "INTEGER"),
            ("galgame_data", "force_clear", "INTEGER DEFAULT 0"),  # 1=用户主动重置，加载时信任空状态
            ("conversations", "is_hidden", "INTEGER DEFAULT 0"),
            ("conversations", "hidden_at", "TIMESTAMP"),
            ("conversations", "hidden_reason", "TEXT"),
            ("conversations", "context_summary_cutoff_message_id", "TEXT"),
            ("conversations", "context_summary_cutoff_timestamp", "INTEGER"),
            ("conversations", "context_summary_cutoff_sequence", "INTEGER"),
            ("messages", "deleted_at", "TIMESTAMP"),
            ("messages", "delete_reason", "TEXT"),
            ("messages", "is_hidden", "INTEGER DEFAULT 0"),
            ("messages", "hidden_at", "TIMESTAMP"),
            ("messages", "hidden_reason", "TEXT"),
            ("galgame_data", "active_session_id", "TEXT"),
            ("galgame_lock_data", "active_session_id", "TEXT"),
            ("galgame_data", "relationship_stage", "TEXT DEFAULT ''"),
            ("galgame_data", "mood", "TEXT DEFAULT ''"),
            ("galgame_data", "memory_tags", "TEXT"),
            ("galgame_data", "event_flags", "TEXT"),
            ("galgame_data", "score_delta_reason", "TEXT DEFAULT ''"),
            ("galgame_data", "context_summary", "TEXT"),
            ("galgame_data", "context_summary_time", "INTEGER"),
            ("galgame_data", "context_summary_cutoff_message_id", "TEXT"),
            ("galgame_data", "context_summary_cutoff_timestamp", "INTEGER"),
            ("galgame_data", "context_summary_cutoff_sequence", "INTEGER"),
            ("galgame_lock_data", "relationship_stage", "TEXT DEFAULT ''"),
            ("galgame_lock_data", "mood", "TEXT DEFAULT ''"),
            ("galgame_lock_data", "memory_tags", "TEXT"),
            ("galgame_lock_data", "event_flags", "TEXT"),
            ("galgame_lock_data", "score_delta_reason", "TEXT DEFAULT ''"),
            ("galgame_lock_data", "context_summary", "TEXT"),
            ("galgame_lock_data", "context_summary_time", "INTEGER"),
            ("galgame_lock_data", "context_summary_cutoff_message_id", "TEXT"),
            ("galgame_lock_data", "context_summary_cutoff_timestamp", "INTEGER"),
            ("galgame_lock_data", "context_summary_cutoff_sequence", "INTEGER"),
            ("galgame_messages", "session_id", "TEXT"),
            ("galgame_messages", "deleted_at", "TIMESTAMP"),
            ("galgame_messages", "delete_reason", "TEXT"),
            ("galgame_lock_messages", "session_id", "TEXT"),
            ("galgame_lock_messages", "deleted_at", "TIMESTAMP"),
            ("galgame_lock_messages", "delete_reason", "TEXT"),
            ("galgame_lock_messages", "scene_metadata", "TEXT"),  # JSON: Galgame 场景元数据
            ("messages", "suggestions_status", "TEXT DEFAULT 'none'"),
            ("messages", "quoted_message_json", "TEXT"),
            ("galgame_messages", "suggestions_status", "TEXT DEFAULT 'none'"),
            ("galgame_lock_messages", "suggestions_status", "TEXT DEFAULT 'none'"),
            ("users", "token_version", "INTEGER DEFAULT 0"),  # 单设备：登录时递增，使旧 token 失效
            ("users", "total_input_tokens", "INTEGER DEFAULT 0"),   # 累计：大模型读取（输入）
            ("users", "total_output_tokens", "INTEGER DEFAULT 0"),  # 累计：大模型输出
            ("users", "total_cache_read_tokens", "INTEGER DEFAULT 0"),  # 累计：缓存命中
            ("users", "companion_input_tokens", "INTEGER DEFAULT 0"),   # 陪玩模式：输入
            ("users", "companion_output_tokens", "INTEGER DEFAULT 0"),  # 陪玩模式：输出
            ("users", "companion_cache_read_tokens", "INTEGER DEFAULT 0"),  # 陪玩模式：缓存命中
            ("galgame_data", "last_active_at", "TIMESTAMP"),             # 情感状态持久化：上次活跃时间
            ("galgame_lock_data", "last_active_at", "TIMESTAMP"),
            ("galgame_lock_data", "char_vitals", "TEXT"),
            ("galgame_lock_data", "char_mood", "TEXT"),
            ("galgame_lock_data", "organ_fill", "TEXT"),
            ("galgame_lock_data", "character_gender", "TEXT DEFAULT ''"),
            ("galgame_data", "char_memory_json", "TEXT"),
            ("galgame_lock_data", "char_memory_json", "TEXT"),
            # Galgame 分层记忆（长期/短期摘要，与 context_summary 独立）
            ("galgame_data", "short_term_memory", "TEXT"),
            ("galgame_data", "short_term_memory_start_turn", "INTEGER"),
            ("galgame_data", "short_term_memory_cutoff_turn", "INTEGER"),
            ("galgame_data", "long_term_memory", "TEXT"),
            ("galgame_data", "long_term_memory_cutoff_turn", "INTEGER"),
            ("daily_token_usage", "llm_calls", "INTEGER DEFAULT 0"),
            ("galgame_lock_data", "short_term_memory", "TEXT"),
            ("galgame_lock_data", "short_term_memory_start_turn", "INTEGER"),
            ("galgame_lock_data", "short_term_memory_cutoff_turn", "INTEGER"),
            ("galgame_lock_data", "long_term_memory", "TEXT"),
            ("galgame_lock_data", "long_term_memory_cutoff_turn", "INTEGER"),
            # 满分庆祝弹窗已展示（跨设备/重装后同一账号不重复弹）
            ("galgame_data", "victory_celebration_ack", "INTEGER DEFAULT 0"),
            ("galgame_lock_data", "victory_celebration_ack", "INTEGER DEFAULT 0"),
            # 陪玩专用精简版角色提示词（服务端缓存，用户不可见）
            ("characters", "companion_prompt", "TEXT"),
            ("characters", "companion_prompt_updated_at", "TIMESTAMP"),
            # 记忆提取专用轻量角色身份档案（也同步写入 characters.data，列用于后续快速查询/排查）
            ("characters", "memory_identity_profile", "TEXT"),
            # 分层记忆：layer=0(C碎片)/1(D日)/2(W周)/3(M月)/4(A年意识)，period 为对应时间标识
            ("character_memories", "layer", "INTEGER DEFAULT 0"),
            ("character_memories", "period", "TEXT"),
            # 网页端可见标记（替代 web_chars.json）
            ("characters", "is_web_visible", "INTEGER DEFAULT 0"),
            ("media_assets", "flirt_level", "INTEGER DEFAULT 0"),
            ("media_assets", "send_policy", "TEXT DEFAULT 'always'"),
            ("media_assets", "min_relationship_stage", "TEXT DEFAULT 'stranger'"),
            ("media_assets", "sender_archetypes", "TEXT DEFAULT '[]'"),
            ("media_assets", "blocked_archetypes", "TEXT DEFAULT '[]'"),
            ("media_assets", "custom_tags", "TEXT DEFAULT '[]'"),
            ("media_assets", "intro", "TEXT DEFAULT ''"),
            ("media_assets", "detail", "TEXT DEFAULT ''"),
            ("media_assets", "image_text", "TEXT DEFAULT ''"),
            ("media_assets", "file_data", "BLOB"),
            ("media_assets", "uploader_id", "INTEGER"),
            ("media_assets", "is_active", "INTEGER DEFAULT 1"),
            ("media_assets", "review_status", "TEXT DEFAULT 'ready'"),
            ("media_assets", "allow_user_save", "INTEGER DEFAULT 1"),
            ("message_attachments", "user_sticker_id", "TEXT"),
            ("message_voice_states", "voice_sentences_json", "TEXT NOT NULL DEFAULT '[]'"),
            ("user_sticker_assets", "file_size", "INTEGER"),
            ("user_sticker_assets", "is_animated", "INTEGER DEFAULT 0"),
            ("user_sticker_assets", "sha256", "TEXT"),
            ("user_sticker_assets", "emotions", "TEXT DEFAULT '[]'"),
            ("user_sticker_assets", "intensity", "TEXT DEFAULT 'moderate'"),
            ("user_sticker_assets", "scenes", "TEXT DEFAULT '[]'"),
            ("user_sticker_assets", "age_rating", "TEXT DEFAULT 'all'"),
            ("user_sticker_assets", "flirt_level", "INTEGER DEFAULT 0"),
            ("user_sticker_assets", "send_policy", "TEXT DEFAULT 'response_only'"),
            ("user_sticker_assets", "min_relationship_stage", "TEXT DEFAULT 'stranger'"),
            ("user_sticker_assets", "sender_archetypes", "TEXT DEFAULT '[]'"),
            ("user_sticker_assets", "blocked_archetypes", "TEXT DEFAULT '[]'"),
            ("user_sticker_assets", "intro", "TEXT DEFAULT ''"),
            ("user_sticker_assets", "detail", "TEXT DEFAULT ''"),
            ("user_sticker_assets", "image_text", "TEXT DEFAULT ''"),
            ("user_sticker_assets", "tagging_json", "TEXT DEFAULT '{}'"),
            ("user_sticker_assets", "is_active", "INTEGER DEFAULT 1"),
            ("user_sticker_assets", "review_status", "TEXT DEFAULT 'ready'"),
            ("user_sticker_assets", "allow_user_save", "INTEGER DEFAULT 0"),
        ]
        all_ok = True
        for table, column, col_type in migrations:
            if table not in allowed_tables:
                logger.warning(f"⚠️ [DB迁移] 跳过不在白名单中的表: {table}")
                continue
            try:
                async with db.execute(f"PRAGMA table_info({table})") as cursor:
                    columns = {row[1] for row in await cursor.fetchall()}
                if column not in columns:
                    await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
                    await db.commit()
                    logger.info(f"🔧 [DB迁移] 已添加 {table}.{column} 列")
            except Exception as e:
                all_ok = False
                logger.warning(f"⚠️ [DB迁移] 添加 {table}.{column} 失败: {e}")
        try:
            await db.execute("CREATE INDEX IF NOT EXISTS idx_media_assets_flirt ON media_assets(flirt_level)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_media_assets_send_policy ON media_assets(send_policy)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_media_assets_active ON media_assets(is_active)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_media_assets_review ON media_assets(review_status)")
            await db.execute(
                """CREATE INDEX IF NOT EXISTS idx_message_attachments_conv_msg
                   ON message_attachments(conversation_id, message_id)"""
            )
            await db.execute("CREATE INDEX IF NOT EXISTS idx_message_attachments_asset ON message_attachments(asset_id)")
            await db.execute(
                """CREATE INDEX IF NOT EXISTS idx_user_sticker_assets_user
                   ON user_sticker_assets(user_id, created_at DESC)"""
            )
            await db.execute("CREATE INDEX IF NOT EXISTS idx_user_sticker_assets_sha256 ON user_sticker_assets(sha256)")
            await db.execute(
                """CREATE UNIQUE INDEX IF NOT EXISTS idx_user_sticker_assets_source_unique
                   ON user_sticker_assets(user_id, source_asset_id)
                   WHERE source_asset_id IS NOT NULL"""
            )
            await db.commit()
        except Exception as e:
            all_ok = False
            logger.warning(f"⚠️ [DB迁移] 创建素材发送约束索引失败: {e}")

        try:
            await db.execute(
                """CREATE TABLE IF NOT EXISTS character_id_aliases (
                    user_id INTEGER NOT NULL,
                    old_character_id TEXT NOT NULL,
                    new_character_id TEXT NOT NULL,
                    created_at_ms INTEGER NOT NULL,
                    updated_at_ms INTEGER NOT NULL,
                    reason TEXT DEFAULT 'admin_rename',
                    PRIMARY KEY (user_id, old_character_id),
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )"""
            )
            await db.execute(
                """CREATE INDEX IF NOT EXISTS idx_character_id_aliases_new
                   ON character_id_aliases(user_id, new_character_id)"""
            )
            await db.commit()
        except Exception as e:
            all_ok = False
            logger.warning(f"⚠️ [DB迁移] 确保 character_id_aliases 表存在失败: {e}")

        # 兼容历史数据：老版本仅写 deleted_*，补齐 hidden_* 便于定位「为什么消息不显示」并支持恢复。
        try:
            await db.execute(
                """UPDATE messages
                   SET is_hidden = 1
                   WHERE deleted_at IS NOT NULL AND COALESCE(is_hidden, 0) = 0"""
            )
            await db.execute(
                """UPDATE messages
                   SET hidden_at = COALESCE(hidden_at, deleted_at, CURRENT_TIMESTAMP)
                   WHERE deleted_at IS NOT NULL"""
            )
            await db.execute(
                """UPDATE messages
                   SET hidden_reason = COALESCE(hidden_reason, delete_reason, 'legacy_deleted_message')
                   WHERE deleted_at IS NOT NULL"""
            )
            await db.commit()
        except Exception as e:
            all_ok = False
            logger.warning(f"⚠️ [DB迁移] 回填 messages.hidden_* 失败: {e}")
        # 修复历史数据：游戏/锁分模式的开场指令消息未被正确标记为隐藏，导致在 UI 中显示（幂等；无变更时不打日志）
        try:
            _before = db.total_changes
            for tbl in ("galgame_messages", "galgame_lock_messages"):
                await db.execute(
                    f"""UPDATE {tbl}
                       SET is_hidden = 1
                       WHERE role = 'user'
                         AND COALESCE(is_hidden, 0) = 0
                         AND content LIKE '【核心指令】游戏开始%'"""
                )
            await db.commit()
            if db.total_changes > _before:
                logger.info("🔧 [DB迁移] 已修复 galgame 开场指令消息的 is_hidden 标记")
        except Exception as e:
            logger.warning(f"⚠️ [DB迁移] 修复 galgame 开场指令 is_hidden 失败: {e}")

        # idx_characters_sort 依赖 sort_order 列，需在列迁移后创建
        try:
            await db.execute("CREATE INDEX IF NOT EXISTS idx_characters_sort ON characters(user_id, sort_order)")
            await db.commit()
        except Exception as e:
            logger.warning(f"⚠️ [DB迁移] 创建 idx_characters_sort 失败（可能已存在）: {e}")

        # 一次性迁移：将 web_chars.json 中的 ID 写入 characters.is_web_visible
        await self._migrate_web_chars_json(db)

        # 确保会员相关表存在（部分旧数据库可能在 SCHEMA_SQL 执行前已建库）
        try:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS memberships (
                    user_id INTEGER PRIMARY KEY,
                    membership_type TEXT NOT NULL DEFAULT 'free',
                    expire_at TEXT,
                    granted_by TEXT,
                    granted_at TEXT,
                    note TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS daily_chat_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    usage_date TEXT NOT NULL,
                    usage_count INTEGER DEFAULT 0,
                    last_used_at TEXT,
                    UNIQUE(user_id, usage_date),
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
            """)
            await db.execute("CREATE INDEX IF NOT EXISTS idx_daily_usage_user_date ON daily_chat_usage(user_id, usage_date)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_memberships_type ON memberships(membership_type)")
            await db.execute("""
                CREATE TABLE IF NOT EXISTS daily_token_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    usage_date TEXT NOT NULL,
                    input_tokens INTEGER DEFAULT 0,
                    output_tokens INTEGER DEFAULT 0,
                    companion_in INTEGER DEFAULT 0,
                    companion_out INTEGER DEFAULT 0,
                    llm_calls INTEGER DEFAULT 0,
                    UNIQUE(user_id, usage_date),
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
            """)
            await db.execute("CREATE INDEX IF NOT EXISTS idx_daily_token_date ON daily_token_usage(usage_date)")
            await db.commit()
        except Exception as e:
            logger.warning(f"⚠️ [DB迁移] 确保会员表存在失败: {e}")

        # 确保长期主动关系表存在（旧数据库兼容）
        try:
            await db.executescript("""
                CREATE TABLE IF NOT EXISTS relationship_presence_states (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    character_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL DEFAULT '',
                    state TEXT NOT NULL DEFAULT 'active_chatting',
                    relationship_stage TEXT NOT NULL DEFAULT 'uncertain',
                    relationship_page_json TEXT NOT NULL DEFAULT '{}',
                    relationship_page_updated_at_ms INTEGER NOT NULL DEFAULT 0,
                    relationship_page_source_json TEXT NOT NULL DEFAULT '{}',
                    character_initiative INTEGER NOT NULL DEFAULT 45,
                    user_proactive_frequency TEXT NOT NULL DEFAULT 'normal',
                    last_user_message_id TEXT DEFAULT '',
                    last_user_at_ms INTEGER DEFAULT 0,
                    last_assistant_message_id TEXT DEFAULT '',
                    last_assistant_at_ms INTEGER DEFAULT 0,
                    last_proactive_message_id TEXT DEFAULT '',
                    last_proactive_at_ms INTEGER DEFAULT 0,
                    absence_started_at_ms INTEGER DEFAULT 0,
                    silence_hours REAL DEFAULT 0,
                    consecutive_proactive_days INTEGER NOT NULL DEFAULT 0,
                    total_proactive_in_absence INTEGER NOT NULL DEFAULT 0,
                    last_motivation TEXT DEFAULT '',
                    motivation_history_json TEXT NOT NULL DEFAULT '[]',
                    content_signature_history_json TEXT NOT NULL DEFAULT '[]',
                    cooldown_until_ms INTEGER DEFAULT 0,
                    next_evaluation_at_ms INTEGER DEFAULT 0,
                    user_ended_conversation INTEGER NOT NULL DEFAULT 0,
                    user_do_not_disturb_until_ms INTEGER DEFAULT 0,
                    disabled_reason TEXT DEFAULT '',
                    created_at_ms INTEGER NOT NULL,
                    updated_at_ms INTEGER NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_relationship_presence_pair
                    ON relationship_presence_states(username, character_id);
                CREATE INDEX IF NOT EXISTS idx_relationship_presence_eval
                    ON relationship_presence_states(next_evaluation_at_ms);
                CREATE TABLE IF NOT EXISTS proactive_campaigns (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    character_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL DEFAULT '',
                    campaign_type TEXT NOT NULL DEFAULT 'absence_reconnect',
                    status TEXT NOT NULL DEFAULT 'active',
                    started_at_ms INTEGER NOT NULL,
                    ended_at_ms INTEGER DEFAULT 0,
                    current_day_index INTEGER NOT NULL DEFAULT 0,
                    max_day_index INTEGER NOT NULL DEFAULT 7,
                    cadence_policy TEXT NOT NULL DEFAULT 'adaptive',
                    pressure_ceiling TEXT NOT NULL DEFAULT 'low',
                    relationship_stage_at_start TEXT DEFAULT 'uncertain',
                    seed_context_json TEXT NOT NULL DEFAULT '{}',
                    last_touch_at_ms INTEGER DEFAULT 0,
                    next_touch_due_at_ms INTEGER DEFAULT 0,
                    next_touch_window_start_ms INTEGER DEFAULT 0,
                    next_touch_window_end_ms INTEGER DEFAULT 0,
                    stop_if_user_replies INTEGER NOT NULL DEFAULT 1,
                    stop_reason TEXT DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at_ms INTEGER NOT NULL,
                    updated_at_ms INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_proactive_campaigns_active
                    ON proactive_campaigns(status, next_touch_due_at_ms);
                CREATE INDEX IF NOT EXISTS idx_proactive_campaigns_pair
                    ON proactive_campaigns(username, character_id, status);
                CREATE TABLE IF NOT EXISTS proactive_touch_attempts (
                    id TEXT PRIMARY KEY,
                    campaign_id TEXT NOT NULL,
                    username TEXT NOT NULL,
                    character_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL DEFAULT '',
                    due_at_ms INTEGER NOT NULL,
                    window_start_ms INTEGER NOT NULL,
                    window_end_ms INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    motivation TEXT NOT NULL DEFAULT '',
                    pressure_level TEXT NOT NULL DEFAULT 'low',
                    topic_source TEXT NOT NULL DEFAULT '',
                    prompt_seed TEXT NOT NULL DEFAULT '',
                    generated_message_id TEXT DEFAULT '',
                    generated_content TEXT DEFAULT '',
                    content_signature TEXT DEFAULT '',
                    skip_reason TEXT DEFAULT '',
                    failure_reason TEXT DEFAULT '',
                    created_at_ms INTEGER NOT NULL,
                    updated_at_ms INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_proactive_touch_attempts_due
                    ON proactive_touch_attempts(status, due_at_ms);
                CREATE INDEX IF NOT EXISTS idx_proactive_touch_attempts_campaign
                    ON proactive_touch_attempts(campaign_id, status);
                CREATE TABLE IF NOT EXISTS normal_character_lifecycle (
                    username TEXT NOT NULL,
                    character_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL DEFAULT '',
                    state TEXT NOT NULL DEFAULT 'alive',
                    death_message_id TEXT DEFAULT '',
                    death_reason TEXT DEFAULT '',
                    created_at_ms INTEGER NOT NULL,
                    updated_at_ms INTEGER NOT NULL,
                    PRIMARY KEY (username, character_id, conversation_id)
                );
                CREATE INDEX IF NOT EXISTS idx_normal_character_lifecycle_state
                    ON normal_character_lifecycle(username, character_id, state);
            """)
            await db.commit()
        except Exception as e:
            logger.warning(f"⚠️ [DB迁移] 确保长期主动关系表存在失败: {e}")

        # 确保 character_memories 表存在（旧数据库兼容）
        try:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS character_memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    character_id TEXT NOT NULL,
                    memory_type TEXT NOT NULL DEFAULT 'episode',
                    content TEXT NOT NULL,
                    source TEXT DEFAULT 'chat',
                    importance INTEGER DEFAULT 5,
                    is_active INTEGER DEFAULT 1,
                    layer INTEGER DEFAULT 0,
                    period TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_recalled_at TIMESTAMP,
                    recall_count INTEGER DEFAULT 0,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                    FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_memories_user_char_active "
                "ON character_memories(user_id, character_id, is_active, importance DESC)"
            )
            await db.execute("""
                CREATE TABLE IF NOT EXISTS memory_consolidation_state (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    character_id TEXT NOT NULL,
                    last_consolidated_message_ts INTEGER DEFAULT 0,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, character_id),
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                    FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE
                )
            """)
            await db.commit()
        except Exception as e:
            logger.warning(f"⚠️ [DB迁移] 确保 character_memories 表存在失败: {e}")

        # 确保 proactive_messages 表存在（旧数据库兼容）
        try:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS proactive_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    character_id TEXT NOT NULL,
                    trigger_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    message_id TEXT,
                    is_read INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    read_at TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                    FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_proactive_user_char_unread "
                "ON proactive_messages(user_id, character_id, is_read, created_at DESC)"
            )
            await db.commit()
        except Exception as e:
            logger.warning(f"⚠️ [DB迁移] 确保 proactive_messages 表存在失败: {e}")

        try:
            await db.execute("ALTER TABLE proactive_messages ADD COLUMN message_id TEXT")
            await db.commit()
        except Exception:
            pass  # 列已存在

        # 确保 hall_characters 表存在（旧数据库兼容）
        try:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS scheduled_followups (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    character_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    source_message_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    due_at_ms INTEGER NOT NULL,
                    expires_at_ms INTEGER NOT NULL DEFAULT 0,
                    cancel_if_user_replies INTEGER NOT NULL DEFAULT 1,
                    allow_reschedule_after_send INTEGER NOT NULL DEFAULT 0,
                    seed TEXT NOT NULL DEFAULT '',
                    reason TEXT NOT NULL DEFAULT '',
                    pressure_level TEXT NOT NULL DEFAULT 'low',
                    chain_id TEXT,
                    chain_count INTEGER NOT NULL DEFAULT 0,
                    planner_json TEXT NOT NULL DEFAULT '{}',
                    sent_message_id TEXT,
                    cancel_reason TEXT,
                    created_at_ms INTEGER NOT NULL,
                    updated_at_ms INTEGER NOT NULL
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_scheduled_followups_due "
                "ON scheduled_followups(status, due_at_ms)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_scheduled_followups_conversation "
                "ON scheduled_followups(username, character_id, conversation_id, status)"
            )
            await db.commit()
        except Exception as e:
            logger.warning(f"⚠️ [DB迁移] 确保 scheduled_followups 表存在失败: {e}")

        # 纭繚 hall_characters 琛ㄥ瓨鍦紙鏃ф暟鎹簱鍏煎锛?        try:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS proactive_tasks (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    character_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL DEFAULT '',
                    source_message_id TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL DEFAULT '',
                    task_type TEXT NOT NULL DEFAULT 'life_share',
                    schedule_type TEXT NOT NULL DEFAULT 'once',
                    source TEXT NOT NULL DEFAULT 'user',
                    status TEXT NOT NULL DEFAULT 'active',
                    due_at_ms INTEGER NOT NULL,
                    interval_seconds INTEGER NOT NULL DEFAULT 0,
                    time_of_day TEXT NOT NULL DEFAULT '',
                    timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai',
                    days_json TEXT NOT NULL DEFAULT '[]',
                    jitter_minutes INTEGER NOT NULL DEFAULT 0,
                    prompt TEXT NOT NULL DEFAULT '',
                    style TEXT NOT NULL DEFAULT 'gentle',
                    cancel_if_user_replies INTEGER NOT NULL DEFAULT 0,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    last_run_at_ms INTEGER,
                    run_count INTEGER NOT NULL DEFAULT 0,
                    created_at_ms INTEGER NOT NULL,
                    updated_at_ms INTEGER NOT NULL
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_proactive_tasks_due "
                "ON proactive_tasks(status, due_at_ms)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_proactive_tasks_user_char "
                "ON proactive_tasks(username, character_id, status)"
            )
            await db.commit()
        except Exception as e:
            logger.warning(f"⚠️ [DB迁移] 确保 proactive_tasks 表存在失败: {e}")

        try:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS hall_characters (
                    id TEXT PRIMARY KEY,
                    source_character_id TEXT,
                    publisher_username TEXT NOT NULL,
                    name TEXT NOT NULL,
                    avatar TEXT,
                    content_hash TEXT NOT NULL UNIQUE,
                    data TEXT NOT NULL,
                    published_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    times_added INTEGER DEFAULT 0,
                    like_count INTEGER DEFAULT 0
                )
            """)
            try:
                await db.execute("ALTER TABLE hall_characters ADD COLUMN like_count INTEGER DEFAULT 0")
            except Exception:
                pass
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_hall_characters_publisher "
                "ON hall_characters(publisher_username)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_hall_characters_published_at "
                "ON hall_characters(published_at DESC)"
            )
            await db.execute("""
                CREATE TABLE IF NOT EXISTS hall_character_likes (
                    hall_id TEXT NOT NULL,
                    username TEXT NOT NULL,
                    like_date TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (hall_id, username, like_date),
                    FOREIGN KEY (hall_id) REFERENCES hall_characters(id) ON DELETE CASCADE
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_hall_character_likes_hall "
                "ON hall_character_likes(hall_id, like_date DESC)"
            )
            await db.commit()
        except Exception as e:
            logger.warning(f"⚠️ [DB迁移] 确保 hall_characters 表存在失败: {e}")

        # 确保 message_outbox 表存在（客户端推送 ACK / 离线补推）
        try:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS message_outbox (
                    id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    msg_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    delivered_at REAL,
                    retry_count INTEGER DEFAULT 0,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_outbox_user_delivered "
                "ON message_outbox(user_id, delivered_at)"
            )
            await db.commit()
        except Exception as e:
            logger.warning(f"⚠️ [DB迁移] 确保 message_outbox 表存在失败: {e}")

        # 确保中国象棋角色棋力徽章稳定状态表存在
        try:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS xiangqi_power_tier_state (
                    username TEXT NOT NULL,
                    character_key TEXT NOT NULL,
                    power_tier TEXT NOT NULL,
                    model_power_tier TEXT NOT NULL DEFAULT '',
                    window_start_tier TEXT NOT NULL,
                    window_start_ms INTEGER NOT NULL,
                    updated_at_ms INTEGER NOT NULL,
                    evidence_json TEXT NOT NULL DEFAULT '{}',
                    PRIMARY KEY (username, character_key)
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_xiangqi_power_tier_updated "
                "ON xiangqi_power_tier_state(updated_at_ms)"
            )
            await db.commit()
        except Exception as e:
            logger.warning(f"⚠️ [DB迁移] 确保 xiangqi_power_tier_state 表存在失败: {e}")

        # 确保 message_voice_states 表存在（聊天语音消息轻量文本状态）
        try:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS message_voice_states (
                    conversation_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    voice_status TEXT NOT NULL DEFAULT 'disabled',
                    voice_id TEXT,
                    voice_job_id TEXT,
                    voice_cache_key TEXT,
                    tts_text TEXT,
                    transcript TEXT,
                    text_fragments_json TEXT NOT NULL DEFAULT '[]',
                    voice_sentences_json TEXT NOT NULL DEFAULT '[]',
                    voice_error TEXT,
                    updated_at INTEGER NOT NULL,
                    PRIMARY KEY (conversation_id, message_id),
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_message_voice_states_conv_msg "
                "ON message_voice_states(conversation_id, message_id)"
            )
            await db.commit()
        except Exception as e:
            logger.warning(f"⚠️ [DB迁移] 确保 message_voice_states 表存在失败: {e}")

        # 确保 message_voice_audio_cache 表存在（安卓 ACK 前保留待交付音频）
        try:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS message_voice_audio_cache (
                    voice_cache_key TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    character_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    mime_type TEXT NOT NULL DEFAULT 'audio/mpeg',
                    variant TEXT,
                    audio_data BLOB NOT NULL,
                    byte_size INTEGER NOT NULL,
                    created_at INTEGER NOT NULL,
                    last_delivered_at INTEGER,
                    delivered_count INTEGER NOT NULL DEFAULT 0,
                    expires_at INTEGER,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_message_voice_audio_cache_conv_msg "
                "ON message_voice_audio_cache(conversation_id, message_id)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_message_voice_audio_cache_expires "
                "ON message_voice_audio_cache(expires_at)"
            )
            await db.commit()
        except Exception as e:
            logger.warning(f"⚠️ [DB迁移] 确保 message_voice_audio_cache 表存在失败: {e}")

        # 确保 character_voice_assets 表存在（角色音色参考音频保存在 PonyChat 后端）
        try:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS character_voice_assets (
                    filename TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    character_id TEXT,
                    voice_profile_id TEXT,
                    qwen_voice_id TEXT,
                    qwen_registered_at TIMESTAMP,
                    qwen_register_error TEXT DEFAULT '',
                    data BLOB NOT NULL,
                    mime_type TEXT NOT NULL DEFAULT 'audio/mpeg',
                    size_bytes INTEGER DEFAULT 0,
                    transcript TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_character_voice_assets_user "
                "ON character_voice_assets(user_id, created_at DESC)"
            )
            for col_name, col_type in (
                ("voice_profile_id", "TEXT"),
                ("qwen_voice_id", "TEXT"),
                ("cosy_voice_id", "TEXT"),
                ("cosy_voice_model", "TEXT"),
                ("cosy_registered_at", "TIMESTAMP"),
                ("cosy_register_error", "TEXT DEFAULT ''"),
                ("cosy_recipe_hash", "TEXT DEFAULT ''"),
                ("qwen_registered_at", "TIMESTAMP"),
                ("qwen_register_error", "TEXT DEFAULT ''"),
            ):
                try:
                    await db.execute(f"ALTER TABLE character_voice_assets ADD COLUMN {col_name} {col_type}")
                except Exception:
                    pass
            await db.commit()
        except Exception as e:
            logger.warning(f"⚠️ [DB迁移] 确保 character_voice_assets 表存在失败: {e}")

        # 确保 PonyChat 自有角色音色档案表存在
        try:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS character_voice_profiles (
                    voice_profile_id TEXT PRIMARY KEY,
                    user_id INTEGER,
                    character_id TEXT,
                    source_mode TEXT NOT NULL DEFAULT 'voice_id',
                    display_name TEXT DEFAULT '',
                    description TEXT DEFAULT '',
                    transcript TEXT DEFAULT '',
                    extra_instruct TEXT DEFAULT '',
                    audio_data BLOB,
                    mime_type TEXT NOT NULL DEFAULT 'audio/mpeg',
                    recipe_hash TEXT DEFAULT '',
                    qwen_voice_id TEXT DEFAULT '',
                    qwen_cached_voice_id TEXT DEFAULT '',
                    clone_status TEXT DEFAULT '',
                    clone_error TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_character_voice_profiles_character "
                "ON character_voice_profiles(character_id, updated_at DESC)"
            )
            for col_name, col_type in (
                ("user_id", "INTEGER"),
                ("character_id", "TEXT"),
                ("source_mode", "TEXT NOT NULL DEFAULT 'voice_id'"),
                ("display_name", "TEXT DEFAULT ''"),
                ("description", "TEXT DEFAULT ''"),
                ("transcript", "TEXT DEFAULT ''"),
                ("extra_instruct", "TEXT DEFAULT ''"),
                ("audio_data", "BLOB"),
                ("mime_type", "TEXT NOT NULL DEFAULT 'audio/mpeg'"),
                ("recipe_hash", "TEXT DEFAULT ''"),
                ("qwen_voice_id", "TEXT DEFAULT ''"),
                ("qwen_cached_voice_id", "TEXT DEFAULT ''"),
                ("cosy_voice_id", "TEXT DEFAULT ''"),
                ("cosy_voice_model", "TEXT DEFAULT ''"),
                ("cosy_registered_at", "TIMESTAMP"),
                ("cosy_register_error", "TEXT DEFAULT ''"),
                ("cosy_recipe_hash", "TEXT DEFAULT ''"),
                ("clone_status", "TEXT DEFAULT ''"),
                ("clone_error", "TEXT DEFAULT ''"),
                ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
                ("updated_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
            ):
                try:
                    await db.execute(f"ALTER TABLE character_voice_profiles ADD COLUMN {col_name} {col_type}")
                except Exception:
                    pass
            await db.commit()
        except Exception as e:
            logger.warning(f"⚠️ [DB迁移] 确保 character_voice_profiles 表存在失败: {e}")

        # 一次性：从 characters / hall_characters 的 data JSON 中移除已废弃的 firstMessage 键
        try:
            await db.execute(
                """CREATE TABLE IF NOT EXISTS _schema_patches (
                    name TEXT PRIMARY KEY,
                    applied_at TEXT DEFAULT CURRENT_TIMESTAMP
                )"""
            )
            await db.commit()
            async with db.execute(
                "SELECT 1 FROM _schema_patches WHERE name = ?",
                ("strip_character_first_message_v1",),
            ) as cur:
                _already_strip_fm = await cur.fetchone() is not None
            if not _already_strip_fm:
                n_char = 0
                async with db.execute(
                    "SELECT id, data FROM characters WHERE data LIKE ?",
                    ("%firstMessage%",),
                ) as cur:
                    _fm_rows = await cur.fetchall()
                for _cid, _dj in _fm_rows:
                    if not _dj:
                        continue
                    try:
                        _d = json.loads(_dj)
                    except (json.JSONDecodeError, TypeError):
                        continue
                    if not isinstance(_d, dict) or "firstMessage" not in _d:
                        continue
                    del _d["firstMessage"]
                    n_char += 1
                    await db.execute(
                        "UPDATE characters SET data = ? WHERE id = ?",
                        (json.dumps(_d, ensure_ascii=False), _cid),
                    )
                n_hall = 0
                try:
                    async with db.execute(
                        "SELECT id, data FROM hall_characters WHERE data LIKE ?",
                        ("%firstMessage%",),
                    ) as cur:
                        _fm_hall = await cur.fetchall()
                except Exception:
                    _fm_hall = []
                for _hid, _dj in _fm_hall:
                    if not _dj:
                        continue
                    try:
                        _d = json.loads(_dj)
                    except (json.JSONDecodeError, TypeError):
                        continue
                    if not isinstance(_d, dict) or "firstMessage" not in _d:
                        continue
                    del _d["firstMessage"]
                    n_hall += 1
                    await db.execute(
                        "UPDATE hall_characters SET data = ? WHERE id = ?",
                        (json.dumps(_d, ensure_ascii=False), _hid),
                    )
                await db.execute(
                    "INSERT INTO _schema_patches (name) VALUES (?)",
                    ("strip_character_first_message_v1",),
                )
                await db.commit()
                if n_char or n_hall:
                    logger.info(
                        "🔧 [DB迁移] 已从角色 JSON 移除废弃键 firstMessage："
                        f"characters={n_char} 条，hall_characters={n_hall} 条"
                    )
        except Exception as e:
            logger.warning(f"⚠️ [DB迁移] 清理角色 JSON 中的 firstMessage 失败: {e}")

        # 确保 normal_chat_memory 表存在（旧数据库兼容）
        try:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS normal_chat_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    character_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    char_memory_json TEXT DEFAULT '[]',
                    short_term_memory TEXT DEFAULT '',
                    long_term_memory TEXT DEFAULT '',
                    entries_covered_count INTEGER DEFAULT 0,
                    lt_covered_count INTEGER DEFAULT 0,
                    updated_at INTEGER DEFAULT 0,
                    UNIQUE(username, character_id, conversation_id)
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_normal_chat_memory_user_char "
                "ON normal_chat_memory(username, character_id)"
            )
            await db.commit()
        except Exception as e:
            logger.warning(f"⚠️ [DB迁移] 确保 normal_chat_memory 表存在失败: {e}")

        # 确保普通对话图片追问上下文表存在（旧数据库兼容）
        try:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS normal_emotion_state (
                    username TEXT NOT NULL,
                    character_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    period_key TEXT NOT NULL,
                    baseline_json TEXT DEFAULT '{}',
                    reactive_json TEXT DEFAULT '{}',
                    emotion_blend TEXT DEFAULT '',
                    updated_ms INTEGER DEFAULT 0,
                    PRIMARY KEY(username, character_id, conversation_id)
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS normal_scene_state (
                    username TEXT NOT NULL,
                    character_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL DEFAULT '',
                    scene_json TEXT DEFAULT '{}',
                    scene_card TEXT DEFAULT '',
                    updated_ms INTEGER DEFAULT 0,
                    source TEXT DEFAULT '',
                    PRIMARY KEY(username, character_id, conversation_id)
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_normal_scene_state_user_char "
                "ON normal_scene_state(username, character_id, updated_ms DESC)"
            )
            await db.execute("""
                CREATE TABLE IF NOT EXISTS normal_image_contexts (
                    entry_id TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    character_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    created_ms INTEGER NOT NULL,
                    user_text TEXT DEFAULT '',
                    image_count INTEGER DEFAULT 0,
                    should_refuse INTEGER DEFAULT 0,
                    image_summary TEXT DEFAULT '',
                    visible_text TEXT DEFAULT '',
                    identified_entities_json TEXT DEFAULT '[]',
                    uncertainty TEXT DEFAULT '',
                    error TEXT DEFAULT ''
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_normal_image_ctx_lookup "
                "ON normal_image_contexts(username, character_id, conversation_id, created_ms DESC)"
            )
            await db.execute("""
                CREATE TABLE IF NOT EXISTS normal_image_context_state (
                    username TEXT NOT NULL,
                    character_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    last_reply_based_on_image INTEGER DEFAULT 0,
                    updated_ms INTEGER DEFAULT 0,
                    PRIMARY KEY(username, character_id, conversation_id)
                )
            """)
            await db.commit()
        except Exception as e:
            logger.warning(f"⚠️ [DB迁移] 确保 normal_image_context* 表存在失败: {e}")

        if not all_ok:
            raise RuntimeError("部分迁移失败，下次启动将重试")

    async def _migrate_web_chars_json(self, db: aiosqlite.Connection):
        """一次性将 web_chars.json 中的角色 ID 写入 characters.is_web_visible（幂等）。"""
        import json as _json
        from pathlib import Path as _Path
        _data_dir = _Path(__file__).resolve().parent.parent / "data"
        _src = _data_dir / "web_chars.json"
        _done = _data_dir / "web_chars.json.migrated"
        if _done.exists() or not _src.exists():
            return
        try:
            raw = _src.read_text(encoding="utf-8")
            ids = _json.loads(raw)
            if not isinstance(ids, list) or not ids:
                _src.rename(_done)
                return
            placeholders = ",".join("?" * len(ids))
            await db.execute(
                f"UPDATE characters SET is_web_visible=1 WHERE id IN ({placeholders})",
                tuple(ids),
            )
            await db.commit()
            _src.rename(_done)
            logger.info(f"🔧 [DB迁移] web_chars.json → is_web_visible 完成，共迁移 {len(ids)} 个角色")
        except Exception as e:
            logger.warning(f"⚠️ [DB迁移] web_chars.json 迁移失败: {e}")

    async def _get_user_id(self, db: aiosqlite.Connection, username: str) -> Optional[int]:
        """
        获取用户ID，如果不存在则创建
        
        参数：
            db: 数据库连接
            username: 用户名
            
        返回：
            用户ID
        """
        async with db.execute(
            "SELECT id FROM users WHERE username = ?",
            (username,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return row[0]
        
        # 用户不存在，创建新用户
        await db.execute(
            "INSERT INTO users (username, password) VALUES (?, ?)",
            (username, "")
        )
        await db.commit()
        
        async with db.execute(
            "SELECT id FROM users WHERE username = ?",
            (username,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0]

    async def resolve_character_id_alias(
        self,
        db: aiosqlite.Connection,
        user_id: int,
        character_id: str,
    ) -> str:
        """Resolve an old character id to the latest id for this user."""
        current = str(character_id or "").strip()
        if not current or not user_id:
            return current

        seen: set[str] = set()
        for _ in range(8):
            if current in seen:
                logger.warning("⚠️ [DB] 角色 ID alias 出现循环: user=%s char=%s", user_id, current)
                return str(character_id or "").strip()
            seen.add(current)
            try:
                async with db.execute(
                    """SELECT new_character_id
                       FROM character_id_aliases
                       WHERE user_id = ? AND old_character_id = ?""",
                    (user_id, current),
                ) as cursor:
                    row = await cursor.fetchone()
            except sqlite3.OperationalError as e:
                if "no such table" in str(e).lower():
                    return current
                raise
            if not row or not row[0]:
                return current
            current = str(row[0]).strip()

        logger.warning("⚠️ [DB] 角色 ID alias 链过长: user=%s char=%s", user_id, character_id)
        return current

    async def record_character_id_alias(
        self,
        db: aiosqlite.Connection,
        user_id: int,
        old_character_id: str,
        new_character_id: str,
        *,
        reason: str = "admin_rename",
    ) -> None:
        """Remember a character id rename so active clients using old ids keep working."""
        old_id = str(old_character_id or "").strip()
        new_id = str(new_character_id or "").strip()
        if not old_id or not new_id or old_id == new_id or not user_id:
            return
        now_ms = int(time.time() * 1000)
        await db.execute(
            """INSERT INTO character_id_aliases
                   (user_id, old_character_id, new_character_id, created_at_ms, updated_at_ms, reason)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(user_id, old_character_id) DO UPDATE SET
                   new_character_id = excluded.new_character_id,
                   updated_at_ms = excluded.updated_at_ms,
                   reason = excluded.reason""",
            (user_id, old_id, new_id, now_ms, now_ms, reason),
        )
        await db.execute(
            """UPDATE character_id_aliases
               SET new_character_id = ?, updated_at_ms = ?
               WHERE user_id = ? AND new_character_id = ?""",
            (new_id, now_ms, user_id, old_id),
        )
    
    async def get_user_id(self, username: str) -> Optional[int]:
        """获取用户ID（公共方法）- 使用连接池"""
        conn = await self.acquire()
        try:
            return await self._get_user_id(conn, username)
        finally:
            await self.release(conn)
    
    async def close(self):
        """关闭连接池：先执行 WAL checkpoint 确保数据落盘，再关闭所有连接（防止 reload 后新进程读不到未刷盘的 Galgame 等数据）"""
        conn_for_checkpoint = None
        try:
            conn_for_checkpoint = self._pool.get_nowait()
        except asyncio.QueueEmpty:
            pass
        if conn_for_checkpoint is None and self._pool_initialized:
            try:
                conn_for_checkpoint = await aiosqlite.connect(self.db_path)
                await self._configure_connection(conn_for_checkpoint)
            except Exception as e:
                logger.warning(f"⚠️ [Database] 关闭前创建临时连接失败，跳过 checkpoint: {e}")
        if conn_for_checkpoint is not None:
            try:
                # PASSIVE：不等其他连接，快速写回已提交页，多 worker 并发关闭时不互相阻塞。
                # SQLite WAL 有崩溃恢复，即使此时被 SIGKILL，下次启动会自动 replay WAL，数据安全。
                await conn_for_checkpoint.execute("PRAGMA wal_checkpoint(PASSIVE)")
                await conn_for_checkpoint.close()
                logger.info("🛑 [Database] WAL PASSIVE checkpoint 完成，连接已关闭")
            except Exception as e:
                logger.warning(f"⚠️ [Database] WAL checkpoint 失败: {e}")
                try:
                    await conn_for_checkpoint.close()
                except Exception:
                    pass
        while not self._pool.empty():
            try:
                conn = self._pool.get_nowait()
                await conn.close()
            except asyncio.QueueEmpty:
                break
        self._pool_initialized = False
        logger.info("🛑 [Database] 连接池已关闭")
