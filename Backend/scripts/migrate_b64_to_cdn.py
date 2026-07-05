#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一次性迁移脚本：将 messages / galgame_messages / galgame_lock_messages 表中残留的
base64 data URI 全部转存到 chat_images 表，并替换为 /chat_images/ URL。

用法（在 Backend 目录下）：
    python scripts/migrate_b64_to_cdn.py              # 正式迁移
    python scripts/migrate_b64_to_cdn.py --dry-run    # 仅统计，不写入

幂等安全：重复运行不会产生副作用（SHA-256 去重 + INSERT OR IGNORE）。
"""

import argparse
import base64
import hashlib
import io
import os
import re
import sqlite3
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(_BACKEND_ROOT, "database", "ponychat.db")

TABLES = ["messages", "galgame_messages", "galgame_lock_messages"]

_B64_RE = re.compile(
    r'data:image/(?:jpeg|jpg|png|webp|gif);base64,[A-Za-z0-9+/=\r\n]{100,}'
)


def _store_b64(conn: sqlite3.Connection, data_uri: str) -> str:
    """将单条 base64 data URI 转存到 chat_images 表，返回 /chat_images/{filename}。"""
    stripped = data_uri.strip()
    if not stripped.startswith("data:image"):
        return data_uri
    header, _, b64_part = stripped.partition(",")
    if not b64_part:
        return data_uri
    header_lower = header.lower()
    if "png" in header_lower:
        mime, ext = "image/png", "png"
    elif "webp" in header_lower:
        mime, ext = "image/webp", "webp"
    elif "gif" in header_lower:
        mime, ext = "image/gif", "gif"
    else:
        mime, ext = "image/jpeg", "jpg"
    raw = base64.b64decode(b64_part)
    if len(raw) < 100:
        return data_uri
    h = hashlib.sha256(raw).hexdigest()[:16]
    filename = f"ci_{h}.{ext}"
    conn.execute(
        """INSERT OR IGNORE INTO chat_images (filename, data, mime_type, size_bytes, created_at)
           VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)""",
        (filename, raw, mime, len(raw)),
    )
    return f"/chat_images/{filename}"


def _replace_content_b64(conn: sqlite3.Connection, content: str) -> str:
    """替换 content 字段中所有内联 base64 data URI。"""
    if not content or "data:image" not in content:
        return content
    parts = []
    last_end = 0
    for match in _B64_RE.finditer(content):
        parts.append(content[last_end : match.start()])
        parts.append(_store_b64(conn, match.group(0)))
        last_end = match.end()
    if not parts:
        return content
    parts.append(content[last_end:])
    return "".join(parts)


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    return column in cols


def migrate(dry_run: bool = False):
    if not os.path.exists(DB_PATH):
        print(f"❌ 数据库不存在: {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 10000")
    conn.execute("PRAGMA synchronous = NORMAL")

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS chat_images (
            filename TEXT PRIMARY KEY,
            data BLOB NOT NULL,
            mime_type TEXT DEFAULT 'image/jpeg',
            size_bytes INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_chat_images_created ON chat_images(created_at DESC);
    """)

    total_images_saved = 0
    total_rows_updated = 0
    total_bytes_freed = 0

    for table in TABLES:
        has_thumbnail = _has_column(conn, table, "image_thumbnail")
        print(f"\n{'='*60}")
        print(f"📋 扫描表: {table} (image_thumbnail={'✓' if has_thumbnail else '✗'})")
        print(f"{'='*60}")

        count_row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        total_in_table = count_row[0] if count_row else 0

        b64_condition = (
            "image_url LIKE 'data:image%' "
            "OR content LIKE '%data:image%'"
        )
        if has_thumbnail:
            b64_condition += " OR image_thumbnail LIKE 'data:image%'"

        count_b64 = conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {b64_condition}"
        ).fetchone()[0]

        print(f"   总行数: {total_in_table}，含 base64: {count_b64}")

        if count_b64 == 0:
            print(f"   ✅ 无需迁移")
            continue

        if dry_run:
            size_estimate = 0
            for col in ["image_url", "content"] + (["image_thumbnail"] if has_thumbnail else []):
                row = conn.execute(
                    f"SELECT SUM(LENGTH({col})) FROM {table} WHERE {col} LIKE '%data:image%'"
                ).fetchone()
                if row and row[0]:
                    size_estimate += row[0]
            print(f"   📏 base64 文本总大小约: {size_estimate / 1024 / 1024:.1f} MB")
            print(f"   ⏭️  dry-run 模式，跳过实际写入")
            continue

        select_cols = "id, image_url, content"
        if has_thumbnail:
            select_cols += ", image_thumbnail"

        cursor = conn.execute(
            f"SELECT {select_cols} FROM {table} WHERE {b64_condition}"
        )

        batch_count = 0
        table_updated = 0
        start_time = time.time()

        while True:
            rows = cursor.fetchmany(200)
            if not rows:
                break
            for row in rows:
                row_id = row[0]
                image_url = row[1]
                content = row[2]
                image_thumbnail = row[3] if has_thumbnail else None

                updates = {}
                old_size = 0
                new_size = 0
                imgs_in_row = 0

                if image_url and isinstance(image_url, str) and image_url.startswith("data:image"):
                    old_size += len(image_url)
                    new_url = _store_b64(conn, image_url)
                    if new_url != image_url:
                        updates["image_url"] = new_url
                        new_size += len(new_url)
                        imgs_in_row += 1

                if image_thumbnail and isinstance(image_thumbnail, str) and image_thumbnail.startswith("data:image"):
                    old_size += len(image_thumbnail)
                    new_thumb = _store_b64(conn, image_thumbnail)
                    if new_thumb != image_thumbnail:
                        updates["image_thumbnail"] = new_thumb
                        new_size += len(new_thumb)
                        imgs_in_row += 1

                if content and isinstance(content, str) and "data:image" in content:
                    old_size += len(content)
                    new_content = _replace_content_b64(conn, content)
                    if new_content != content:
                        content_imgs = len(_B64_RE.findall(content))
                        updates["content"] = new_content
                        new_size += len(new_content)
                        imgs_in_row += content_imgs

                if updates:
                    set_clause = ", ".join(f"{k} = ?" for k in updates)
                    values = list(updates.values()) + [row_id]
                    conn.execute(
                        f"UPDATE {table} SET {set_clause} WHERE id = ?", values
                    )
                    table_updated += 1
                    total_images_saved += imgs_in_row
                    total_bytes_freed += (old_size - new_size)

                batch_count += 1
                if batch_count % 200 == 0:
                    conn.commit()
                    elapsed = time.time() - start_time
                    print(f"   ⏳ 已处理 {batch_count}/{count_b64} 行 ({elapsed:.1f}s)")

        conn.commit()
        elapsed = time.time() - start_time
        total_rows_updated += table_updated
        print(f"   ✅ 完成 — 更新 {table_updated} 行 ({elapsed:.1f}s)")

    conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
    conn.close()

    print(f"\n{'='*60}")
    print(f"🎉 迁移完成！")
    print(f"   更新行数: {total_rows_updated}")
    print(f"   转存图片: {total_images_saved}")
    print(f"   释放文本: {total_bytes_freed / 1024 / 1024:.1f} MB (从消息字段移除的 base64 文本)")
    print(f"{'='*60}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="迁移 base64 图片到 chat_images 表")
    parser.add_argument("--dry-run", action="store_true", help="仅统计，不写入")
    args = parser.parse_args()
    migrate(dry_run=args.dry_run)
