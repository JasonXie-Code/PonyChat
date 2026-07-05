"""
数据库访问层核心模块
使用 aiosqlite 实现异步 SQLite 数据库访问
支持连接池、WAL 模式和全局 PRAGMA 优化
"""
import aiosqlite
import asyncio
import json
import os
import sqlite3
import time
from typing import Optional, List, Dict, Any
from datetime import datetime
from ..config import logger
from ..runtime_paths import resolve_database_path

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB_PATH = resolve_database_path(_BACKEND_DIR)

# 数据库 Schema SQL
SCHEMA_SQL = """
-- 用户表（包含认证信息）
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT,  -- 已弃用，保留列以兼容旧数据
    password TEXT NOT NULL,  -- 明文密码
    gender TEXT DEFAULT 'male',  -- 性别
    theme TEXT DEFAULT 'dark',  -- 主题
    role TEXT DEFAULT 'user',  -- 角色：user/admin
    avatar TEXT,  -- 头像路径
    created_at TEXT,  -- 创建时间（ISO格式字符串）
    last_active TEXT,  -- 最后活跃时间（ISO格式字符串）
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 角色表
CREATE TABLE IF NOT EXISTS characters (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    avatar TEXT,
    prompt TEXT,
    bio TEXT,
    data TEXT,  -- JSON 格式的完整角色数据
    memory_identity_profile TEXT,  -- Legacy JSON: 曾用于自动抽取的轻量角色身份档案
    official_source_id TEXT,  -- 官方引用角色指向的唯一 System 源角色 ID
    is_official_reference INTEGER DEFAULT 0,  -- 1=用户侧官方引用入口
    is_official_source INTEGER DEFAULT 0,  -- 1=System 官方唯一源
    official_content_hash_at_link TEXT,  -- 建立引用时的官方内容哈希
    is_hidden INTEGER DEFAULT 0,
    hidden_at TIMESTAMP,
    hidden_reason TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_characters_official_source ON characters(official_source_id);
CREATE INDEX IF NOT EXISTS idx_characters_official_reference ON characters(is_official_reference, official_source_id);

-- 角色 ID 改名别名表：客户端仍持有旧 ID 时，服务端自动解析到新 ID。
CREATE TABLE IF NOT EXISTS character_id_aliases (
    user_id INTEGER NOT NULL,
    old_character_id TEXT NOT NULL,
    new_character_id TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    reason TEXT DEFAULT 'admin_rename',
    PRIMARY KEY (user_id, old_character_id),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_character_id_aliases_new
    ON character_id_aliases(user_id, new_character_id);

-- 对话表
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    character_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    timestamp INTEGER NOT NULL,
    version INTEGER DEFAULT 1,
    summary TEXT,
    context_summary_cutoff_message_id TEXT,
    context_summary_cutoff_timestamp INTEGER,
    context_summary_cutoff_sequence INTEGER,
    is_hidden INTEGER DEFAULT 0,
    hidden_at TIMESTAMP,
    hidden_reason TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- 消息表
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    raw_content TEXT,  -- 包含思考标签的原始内容
    image_url TEXT,
    timestamp INTEGER NOT NULL,
    message_id TEXT UNIQUE,  -- 消息唯一ID
    sequence_number INTEGER,
    previous_message_id TEXT,
    quoted_message_json TEXT,  -- JSON: 被引用的消息快照
    speaker_character_id TEXT,
    speaker_name TEXT,
    speaker_avatar TEXT,
    suggestions TEXT,  -- JSON 数组
    suggestions_status TEXT DEFAULT 'none',  -- none/pending/ready/error
    client_id TEXT,
    generation_duration_ms INTEGER,
    is_hidden INTEGER DEFAULT 0,
    hidden_at TIMESTAMP,
    hidden_reason TEXT,
    deleted_at TIMESTAMP,
    delete_reason TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

-- 聊天消息附件（表情包、贴纸等结构化媒体；普通识图图片仍走 content/image_url）
CREATE TABLE IF NOT EXISTS message_attachments (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'sticker',
    asset_id TEXT,
    user_sticker_id TEXT,
    url TEXT,
    name TEXT DEFAULT '',
    width INTEGER,
    height INTEGER,
    metadata_json TEXT DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_message_attachments_conv_msg ON message_attachments(conversation_id, message_id);
CREATE INDEX IF NOT EXISTS idx_message_attachments_asset ON message_attachments(asset_id);

-- 普通聊天语音消息文本状态。这里只保存可恢复的轻量状态。
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
);
CREATE INDEX IF NOT EXISTS idx_message_voice_states_conv_msg ON message_voice_states(conversation_id, message_id);

-- 普通聊天语音消息服务端待交付音频缓存。
-- 安卓 App 成功写入本地缓存并 ACK 前，服务端保留这份音频，避免错过 WebSocket 推送后只能回退文本。
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
);
CREATE INDEX IF NOT EXISTS idx_message_voice_audio_cache_conv_msg ON message_voice_audio_cache(conversation_id, message_id);
CREATE INDEX IF NOT EXISTS idx_message_voice_audio_cache_expires ON message_voice_audio_cache(expires_at);

-- 角色音色参考音频资产。音色相关资产保存在 PonyChat 后端，不落到外部 TTS 服务。
CREATE TABLE IF NOT EXISTS character_voice_assets (
    filename TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    character_id TEXT,
    voice_profile_id TEXT,
    qwen_voice_id TEXT,
    cosy_voice_id TEXT,
    cosy_voice_model TEXT,
    cosy_registered_at TIMESTAMP,
    cosy_register_error TEXT DEFAULT '',
    cosy_recipe_hash TEXT DEFAULT '',
    qwen_registered_at TIMESTAMP,
    qwen_register_error TEXT DEFAULT '',
    data BLOB NOT NULL,
    mime_type TEXT NOT NULL DEFAULT 'audio/mpeg',
    size_bytes INTEGER DEFAULT 0,
    transcript TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_character_voice_assets_user
    ON character_voice_assets(user_id, created_at DESC);

-- PonyChat 自有角色音色档案。qwen3tts 只作为生成引擎；角色运行时可以用这里
-- 保存的参考音频/文本重新注册 qwen voice，避免语音实验室展示音色的删除/改名影响角色。
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
    cosy_voice_id TEXT DEFAULT '',
    cosy_voice_model TEXT DEFAULT '',
    cosy_registered_at TIMESTAMP,
    cosy_register_error TEXT DEFAULT '',
    cosy_recipe_hash TEXT DEFAULT '',
    clone_status TEXT DEFAULT '',
    clone_error TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_character_voice_profiles_character
    ON character_voice_profiles(character_id, updated_at DESC);

-- 用户全局表情库：source_asset_id 表示收藏平台素材；file_data 表示用户自上传素材。
CREATE TABLE IF NOT EXISTS user_sticker_assets (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    source_asset_id TEXT,
    file_size INTEGER,
    mime_type TEXT,
    is_animated INTEGER DEFAULT 0,
    name TEXT NOT NULL,
    emotions TEXT DEFAULT '[]',
    intensity TEXT DEFAULT 'moderate',
    scenes TEXT DEFAULT '[]',
    age_rating TEXT DEFAULT 'all',
    flirt_level INTEGER DEFAULT 0,
    send_policy TEXT DEFAULT 'response_only',
    min_relationship_stage TEXT DEFAULT 'stranger',
    sender_archetypes TEXT DEFAULT '[]',
    blocked_archetypes TEXT DEFAULT '[]',
    intro TEXT DEFAULT '',                   -- 简介：短句概括，素材列表与模型快速识别用
    detail TEXT DEFAULT '',                  -- 详细描述：画面主体、动作、表情、氛围与适用语境
    image_text TEXT DEFAULT '',              -- 图中文字：OCR 原文，按图中实际文字保存
    custom_tags TEXT DEFAULT '[]',
    sha256 TEXT,
    tagging_json TEXT DEFAULT '{}',
    is_active INTEGER DEFAULT 1,
    review_status TEXT DEFAULT 'ready',
    allow_user_save INTEGER DEFAULT 0,
    file_data BLOB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_user_sticker_assets_user ON user_sticker_assets(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_user_sticker_assets_sha256 ON user_sticker_assets(sha256);
CREATE UNIQUE INDEX IF NOT EXISTS idx_user_sticker_assets_source_unique
    ON user_sticker_assets(user_id, source_asset_id)
    WHERE source_asset_id IS NOT NULL;

-- 用户设置表
CREATE TABLE IF NOT EXISTS user_settings (
    user_id INTEGER PRIMARY KEY,
    settings TEXT NOT NULL,  -- JSON 格式
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Galgame 数据表
CREATE TABLE IF NOT EXISTS galgame_data (
    character_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    score INTEGER DEFAULT 40,
    status TEXT DEFAULT 'playing',
    version INTEGER DEFAULT 1,
    relationship_stage TEXT DEFAULT '',
    mood TEXT DEFAULT '',
    memory_tags TEXT,
    event_flags TEXT,
    score_delta_reason TEXT DEFAULT '',
    context_summary TEXT,
    context_summary_time INTEGER,
    context_summary_cutoff_message_id TEXT,
    context_summary_cutoff_timestamp INTEGER,
    context_summary_cutoff_sequence INTEGER,
    char_memory_json TEXT,
    short_term_memory TEXT,
    short_term_memory_start_turn INTEGER,
    short_term_memory_cutoff_turn INTEGER,
    long_term_memory TEXT,
    long_term_memory_cutoff_turn INTEGER,
    force_clear INTEGER DEFAULT 0,
    active_session_id TEXT,
    last_active_at TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (character_id, user_id),
    FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Galgame 消息表
CREATE TABLE IF NOT EXISTS galgame_messages (
    id TEXT PRIMARY KEY,
    character_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    raw_content TEXT,  -- 包含思考标签的原始内容
    scene_metadata TEXT,  -- JSON: Galgame 场景元数据
    image_url TEXT,
    timestamp INTEGER NOT NULL,
    message_id TEXT UNIQUE,
    sequence_number INTEGER,
    previous_message_id TEXT,
    is_hidden INTEGER DEFAULT 0,
    session_id TEXT,
    deleted_at TIMESTAMP,
    delete_reason TEXT,
    suggestions TEXT,  -- JSON 数组
    suggestions_status TEXT DEFAULT 'none',  -- none/pending/ready/error
    client_id TEXT,
    generation_duration_ms INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- 锁分模式游戏数据表（独立于普通 galgame，分数最低为 1）
CREATE TABLE IF NOT EXISTS galgame_lock_data (
    character_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    score INTEGER DEFAULT 40,
    status TEXT DEFAULT 'playing',
    version INTEGER DEFAULT 1,
    relationship_stage TEXT DEFAULT '',
    mood TEXT DEFAULT '',
    memory_tags TEXT,
    event_flags TEXT,
    score_delta_reason TEXT DEFAULT '',
    context_summary TEXT,
    context_summary_time INTEGER,
    context_summary_cutoff_message_id TEXT,
    context_summary_cutoff_timestamp INTEGER,
    context_summary_cutoff_sequence INTEGER,
    char_memory_json TEXT,
    short_term_memory TEXT,
    short_term_memory_start_turn INTEGER,
    short_term_memory_cutoff_turn INTEGER,
    long_term_memory TEXT,
    long_term_memory_cutoff_turn INTEGER,
    force_clear INTEGER DEFAULT 0,
    active_session_id TEXT,
    char_vitals TEXT,
    char_mood TEXT,
    organ_fill TEXT,
    character_gender TEXT DEFAULT '',
    last_active_at TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (character_id, user_id),
    FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- 锁分模式游戏消息表
CREATE TABLE IF NOT EXISTS galgame_lock_messages (
    id TEXT PRIMARY KEY,
    character_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    raw_content TEXT,
    scene_metadata TEXT,  -- JSON: Galgame 场景元数据
    image_url TEXT,
    timestamp INTEGER NOT NULL,
    message_id TEXT UNIQUE,
    sequence_number INTEGER,
    previous_message_id TEXT,
    is_hidden INTEGER DEFAULT 0,
    session_id TEXT,
    deleted_at TIMESTAMP,
    delete_reason TEXT,
    suggestions TEXT,
    suggestions_status TEXT DEFAULT 'none',
    client_id TEXT,
    generation_duration_ms INTEGER,
    image_thumbnail TEXT,
    galgame_options TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Galgame 归档表（普通模式）
CREATE TABLE IF NOT EXISTS galgame_archives (
    archive_id TEXT PRIMARY KEY,
    character_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    score INTEGER DEFAULT 40,
    status TEXT DEFAULT 'playing',
    version INTEGER DEFAULT 1,
    message_count INTEGER DEFAULT 0,
    snapshot_json TEXT NOT NULL,  -- 完整快照: {score,status,version,messages,updated_at}
    reason TEXT DEFAULT 'reset',
    archived_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    restored_at TIMESTAMP,
    FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Galgame 归档表（锁分模式）
CREATE TABLE IF NOT EXISTS galgame_lock_archives (
    archive_id TEXT PRIMARY KEY,
    character_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    score INTEGER DEFAULT 40,
    status TEXT DEFAULT 'playing',
    version INTEGER DEFAULT 1,
    message_count INTEGER DEFAULT 0,
    snapshot_json TEXT NOT NULL,
    reason TEXT DEFAULT 'reset',
    archived_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    restored_at TIMESTAMP,
    FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- 删除与恢复审计表（软删/恢复/硬删全链路留痕）
CREATE TABLE IF NOT EXISTS deletion_audits (
    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,              -- soft_delete / restore / hard_delete
    object_type TEXT NOT NULL,         -- conversation / message / galgame_message / batch_job
    object_id TEXT NOT NULL,
    user_id INTEGER,
    username TEXT,
    character_id TEXT,
    conversation_id TEXT,
    message_id TEXT,
    operator TEXT DEFAULT 'system',    -- user:<name> / admin:<name> / system
    reason TEXT,
    source TEXT DEFAULT 'api',         -- api / sync / admin_api / migration / retention_job
    details_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 普通对话上下文记忆表（分层摘要，绑定 username+character+conversation）
CREATE TABLE IF NOT EXISTS normal_chat_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    character_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    char_memory_json TEXT DEFAULT '[]',    -- JSON 数组，最近轮次的摘要条目
    short_term_memory TEXT DEFAULT '',
    long_term_memory TEXT DEFAULT '',
    entries_covered_count INTEGER DEFAULT 0,  -- shortTerm 已覆盖的 entries 数
    lt_covered_count INTEGER DEFAULT 0,       -- longTerm 已覆盖的 shortTerm 轮数
    updated_at INTEGER DEFAULT 0,
    UNIQUE(username, character_id, conversation_id)
);
CREATE INDEX IF NOT EXISTS idx_normal_chat_memory_user_char ON normal_chat_memory(username, character_id);

-- 普通对话角色情绪状态：baseline 慢变，reaction 短效。
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
);

-- 普通对话场景锚点：保存每个角色自己的地点层级和 position，供群聊/单聊之间继承
CREATE TABLE IF NOT EXISTS normal_scene_state (
    username TEXT NOT NULL,
    character_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL DEFAULT '',
    scene_json TEXT DEFAULT '{}',
    scene_card TEXT DEFAULT '',
    updated_ms INTEGER DEFAULT 0,
    source TEXT DEFAULT '',
    PRIMARY KEY(username, character_id, conversation_id)
);
CREATE INDEX IF NOT EXISTS idx_normal_scene_state_user_char
    ON normal_scene_state(username, character_id, updated_ms DESC);

-- 普通对话图片追问上下文：保存近期用户发图后的识图摘要，供后续纯文字追问跨重启引用
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
);
CREATE INDEX IF NOT EXISTS idx_normal_image_ctx_lookup
    ON normal_image_contexts(username, character_id, conversation_id, created_ms DESC);

CREATE TABLE IF NOT EXISTS normal_image_context_state (
    username TEXT NOT NULL,
    character_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    last_reply_based_on_image INTEGER DEFAULT 0,
    updated_ms INTEGER DEFAULT 0,
    PRIMARY KEY(username, character_id, conversation_id)
);

-- 角色大厅独立表（每个大厅条目独立存储，与用户角色列表解耦）
CREATE TABLE IF NOT EXISTS hall_characters (
    id TEXT PRIMARY KEY,                  -- 大厅条目 UUID
    source_character_id TEXT,             -- 发布者原始角色 ID（仅用于取消发布时联查）
    publisher_username TEXT NOT NULL,     -- 发布者用户名
    name TEXT NOT NULL,
    avatar TEXT,
    content_hash TEXT NOT NULL UNIQUE,    -- 角色内容哈希（去重 + 已添加判断）
    data TEXT NOT NULL,                   -- 完整角色 JSON（内容字段）
    published_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    times_added INTEGER DEFAULT 0,
    like_count INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_hall_characters_publisher ON hall_characters(publisher_username);
CREATE INDEX IF NOT EXISTS idx_hall_characters_published_at ON hall_characters(published_at DESC);

-- 角色大厅点赞记录：由数据库主键保证同一用户同一天只能给同一角色点一次。
CREATE TABLE IF NOT EXISTS hall_character_likes (
    hall_id TEXT NOT NULL,
    username TEXT NOT NULL,
    like_date TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (hall_id, username, like_date),
    FOREIGN KEY (hall_id) REFERENCES hall_characters(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_hall_character_likes_hall
    ON hall_character_likes(hall_id, like_date DESC);

-- 头像表（存储所有头像二进制数据）
CREATE TABLE IF NOT EXISTS avatars (
    filename TEXT PRIMARY KEY,
    data BLOB NOT NULL,
    mime_type TEXT DEFAULT 'image/jpeg',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 聊天图片表（消息中的 base64 图片转存为二进制，通过 URL 提供）
CREATE TABLE IF NOT EXISTS chat_images (
    filename TEXT PRIMARY KEY,
    data BLOB NOT NULL,
    mime_type TEXT DEFAULT 'image/jpeg',
    size_bytes INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_chat_images_created ON chat_images(created_at DESC);

-- 邀请码表
CREATE TABLE IF NOT EXISTS invite_codes (
    code TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    is_used INTEGER DEFAULT 0,
    used_by TEXT,
    used_at TEXT,
    note TEXT
);

-- 会员表（记录用户会员等级及到期时间）
CREATE TABLE IF NOT EXISTS memberships (
    user_id INTEGER PRIMARY KEY,
    membership_type TEXT NOT NULL DEFAULT 'free',  -- free / pro / pro_plus
    expire_at TEXT,          -- ISO 格式到期时间，NULL = 永久有效（仅对 pro/pro_plus 生效）
    granted_by TEXT,         -- 授权操作人（管理员 username）
    granted_at TEXT,         -- 授权时间
    note TEXT,               -- 备注
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- 角色长期记忆表（跨会话持久，绑定 user+character 关系）
CREATE TABLE IF NOT EXISTS character_memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    character_id TEXT NOT NULL,
    memory_type TEXT NOT NULL DEFAULT 'episode',  -- preference / episode / relationship / activity / summary
    content TEXT NOT NULL,
    source TEXT DEFAULT 'chat',                   -- chat / game / music / video / manual / consolidator
    importance INTEGER DEFAULT 5,                 -- 1~10，越高越优先注入上下文
    is_active INTEGER DEFAULT 1,
    layer INTEGER DEFAULT 0,                      -- 0=C碎片 / 1=D日摘要 / 2=W周摘要 / 3=M月摘要 / 4=A年意识
    period TEXT,                                  -- D: "2026-03-05" / W: "2026-W10" / M: "2026-03" / A: "2026"
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_recalled_at TIMESTAMP,
    recall_count INTEGER DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_memories_user_char_active
    ON character_memories(user_id, character_id, is_active, importance DESC);

-- 长期记忆固化游标：记录每个 user+character 已处理到哪条普通消息，避免重启后重复从头提取
CREATE TABLE IF NOT EXISTS memory_consolidation_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    character_id TEXT NOT NULL,
    last_consolidated_message_ts INTEGER DEFAULT 0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, character_id),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE
);

-- 主动消息表（角色主动发起的消息，由调度引擎写入）
CREATE TABLE IF NOT EXISTS proactive_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    character_id TEXT NOT NULL,
    trigger_type TEXT NOT NULL,   -- inactive_24h / daily_greeting / mood_inquiry / anniversary / activity_followup
    content TEXT NOT NULL,        -- 角色生成的消息文本
    message_id TEXT,               -- 对话 messages 表中的 assistant 消息 id（与 App / outbox payload 对齐）
    is_read INTEGER DEFAULT 0,    -- 0=未读，1=已读
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    read_at TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_proactive_user_char_unread
    ON proactive_messages(user_id, character_id, is_read, created_at DESC);

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
);
CREATE INDEX IF NOT EXISTS idx_scheduled_followups_due
    ON scheduled_followups(status, due_at_ms);
CREATE INDEX IF NOT EXISTS idx_scheduled_followups_conversation
    ON scheduled_followups(username, character_id, conversation_id, status);

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
);
CREATE INDEX IF NOT EXISTS idx_proactive_tasks_due
    ON proactive_tasks(status, due_at_ms);
CREATE INDEX IF NOT EXISTS idx_proactive_tasks_user_char
    ON proactive_tasks(username, character_id, status);

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

CREATE TABLE IF NOT EXISTS quick_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL,
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_quick_messages_user_order
    ON quick_messages(user_id, sort_order, id);

-- 今日积分使用记录（用于限流计数；usage_count 表示当日消耗积分）
CREATE TABLE IF NOT EXISTS daily_chat_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    usage_date TEXT NOT NULL,   -- YYYY-MM-DD
    usage_count INTEGER DEFAULT 0,
    last_used_at TEXT,
    UNIQUE(user_id, usage_date),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- 每日 Token 用量（与 increment_usage / increment_companion_usage 同步累加）
-- llm_calls：当日大模型 HTTP 调用次数（管理后台「调用次数」与分步生成等多调用场景）
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
);
CREATE INDEX IF NOT EXISTS idx_daily_token_date ON daily_token_usage(usage_date);

-- 陪玩会话历史表（每次陪玩结束后写入一条，保存完整对话记录）
CREATE TABLE IF NOT EXISTS companion_sessions (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    character_id TEXT NOT NULL,
    character_name TEXT NOT NULL DEFAULT '',
    started_at TIMESTAMP NOT NULL,
    ended_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    duration_seconds INTEGER DEFAULT 0,
    frame_count INTEGER DEFAULT 0,
    messages TEXT NOT NULL DEFAULT '[]',  -- JSON 数组，每条含 role/content/timestamp_ms
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_companion_sessions_user_char ON companion_sessions(user_id, character_id, ended_at DESC);

-- 中国象棋角色棋力徽章稳定状态：准备步骤可浮动，但同一角色一周内最多移动 1 档。
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
);
CREATE INDEX IF NOT EXISTS idx_xiangqi_power_tier_updated ON xiangqi_power_tier_state(updated_at_ms);

-- 客户端推送送达确认（离线补推 / ACK）
CREATE TABLE IF NOT EXISTS message_outbox (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    msg_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at REAL NOT NULL,
    delivered_at REAL,
    retry_count INTEGER DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_outbox_user_delivered ON message_outbox(user_id, delivered_at);

-- 索引
CREATE INDEX IF NOT EXISTS idx_conversations_character ON conversations(character_id);
CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(user_id);
CREATE INDEX IF NOT EXISTS idx_conversations_timestamp ON conversations(timestamp);
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp);
CREATE INDEX IF NOT EXISTS idx_messages_message_id ON messages(message_id);
CREATE INDEX IF NOT EXISTS idx_galgame_messages_character ON galgame_messages(character_id);
CREATE INDEX IF NOT EXISTS idx_galgame_messages_timestamp ON galgame_messages(timestamp);
CREATE INDEX IF NOT EXISTS idx_galgame_messages_message_id ON galgame_messages(message_id);

-- 🔧 [优化] 新增索引 - 提升常见查询性能（idx_characters_sort 需等迁移添加 sort_order 列后再创建，见 _migrate_columns）
CREATE INDEX IF NOT EXISTS idx_characters_user ON characters(user_id);
CREATE INDEX IF NOT EXISTS idx_invite_codes_used ON invite_codes(is_used);
CREATE INDEX IF NOT EXISTS idx_invite_codes_expires ON invite_codes(expires_at);
CREATE INDEX IF NOT EXISTS idx_galgame_data_user ON galgame_data(user_id);
CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);
CREATE INDEX IF NOT EXISTS idx_conversations_user_char ON conversations(user_id, character_id);
CREATE INDEX IF NOT EXISTS idx_galgame_messages_user ON galgame_messages(user_id);
CREATE INDEX IF NOT EXISTS idx_galgame_archives_user_char_time ON galgame_archives(user_id, character_id, archived_at DESC);
CREATE INDEX IF NOT EXISTS idx_galgame_lock_archives_user_char_time ON galgame_lock_archives(user_id, character_id, archived_at DESC);
CREATE INDEX IF NOT EXISTS idx_deletion_audits_created ON deletion_audits(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_deletion_audits_object ON deletion_audits(object_type, object_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_deletion_audits_user ON deletion_audits(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_character_id_aliases_new
    ON character_id_aliases(user_id, new_character_id);

-- 素材库（表情包、贴纸等多模态基础资源）
CREATE TABLE IF NOT EXISTS media_assets (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'emoji',   -- emoji / sticker / bg / misc
    file_size INTEGER,
    mime_type TEXT,                           -- image/jpeg, image/png, image/gif, image/webp, image/apng
    is_animated INTEGER DEFAULT 0,           -- 1 = 动图（GIF / APNG / animated WebP）
    emotions TEXT DEFAULT '[]',              -- JSON 数组示例：["happy", "excited"]
    intensity TEXT DEFAULT 'moderate',       -- "mild" / "moderate" / "strong"
    scenes TEXT DEFAULT '[]',               -- JSON 数组示例：["greeting", "tease"]
    age_rating TEXT DEFAULT 'all',          -- "all" / "teen" / "adult"
    flirt_level INTEGER DEFAULT 0,          -- 0=日常 / 1=轻微暧昧 / 2=明确调情 / 3=成人亲密
    send_policy TEXT DEFAULT 'always',      -- always / response_only / user_triggered / never_auto
    min_relationship_stage TEXT DEFAULT 'stranger', -- stranger / familiar / close / ambiguous / lover
    sender_archetypes TEXT DEFAULT '[]',    -- 适合发送者人格 JSON 数组
    blocked_archetypes TEXT DEFAULT '[]',   -- 不适合发送者人格 JSON 数组
    custom_tags TEXT DEFAULT '[]',          -- 自定义自由文本标签 JSON 数组
    intro TEXT DEFAULT '',                   -- 简介：短句概括，素材列表与模型快速识别用
    detail TEXT DEFAULT '',                  -- 详细描述：画面主体、动作、表情、氛围与适用语境
    image_text TEXT DEFAULT '',              -- 图中文字：OCR 原文，按图中实际文字保存
    file_data BLOB,                         -- 文件二进制数据（与 avatars 表一致，DB 统一存储）
    uploader_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (uploader_id) REFERENCES users(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_media_assets_category ON media_assets(category);
CREATE INDEX IF NOT EXISTS idx_media_assets_age ON media_assets(age_rating);
CREATE INDEX IF NOT EXISTS idx_media_assets_intensity ON media_assets(intensity);
CREATE INDEX IF NOT EXISTS idx_media_assets_created ON media_assets(created_at DESC);
"""
