"""Remove non-certified voice data, retaining text and a recoverable DB snapshot."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3

from Backend.certified_voice_policy import row_is_certified, strip_voice_settings


def clean_database(db_path: str, backup_path: str | None = None) -> dict:
    with sqlite3.connect(db_path, timeout=30) as conn:
        if backup_path:
            target = Path(backup_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                raise RuntimeError("Refusing to overwrite the pre-cleanup snapshot")
            with sqlite3.connect(target) as backup:
                conn.backup(backup)
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute("SELECT c.id,u.username,c.data,c.official_source_id FROM characters c "
                            "JOIN users u ON u.id=c.user_id").fetchall()
        certified = {r[0] for r in rows if row_is_certified(conn, r)}
        denied = {r[0] for r in rows if r[0] not in certified}
        protected_profiles = set()
        protected_renderers = set()
        removed_renderers = set()
        for cid, _, raw, _ in rows:
            data = json.loads(raw or "{}")
            if cid in certified:
                for key in ('voiceId', 'voice_id', 'voiceProfileId', 'voice_profile_id'):
                    value = str(data.get(key) or '')
                    if value:
                        protected_profiles.add(value)
                        if value.startswith('qwen3tts:'):
                            protected_renderers.add(value.split(':', 1)[1])
            else:
                for key in ('voiceId', 'voice_id', 'voiceBaseVoiceId', 'voice_base_voice_id'):
                    value = str(data.get(key) or '')
                    if value.startswith('qwen3tts:'):
                        removed_renderers.add(value.split(':', 1)[1])
                conn.execute("UPDATE characters SET data=? WHERE id=?",
                             (json.dumps(strip_voice_settings(data), ensure_ascii=False), cid))
        counts = {'noncertified_characters': len(denied), 'certified_characters_preserved': len(certified)}
        for hid, publisher, raw in conn.execute("SELECT id,publisher_username,data FROM hall_characters").fetchall():
            if str(publisher).lower() != 'system':
                conn.execute("UPDATE hall_characters SET data=? WHERE id=?",
                             (json.dumps(strip_voice_settings(json.loads(raw or '{}')), ensure_ascii=False), hid))
        profiles = conn.execute("SELECT voice_profile_id,character_id,qwen_voice_id,qwen_cached_voice_id "
                                "FROM character_voice_profiles").fetchall()
        counts['voice_profiles_deleted'] = 0
        for pid, cid, qid, cached_id in profiles:
            renderers = {str(v).removeprefix('qwen3tts:') for v in (qid, cached_id) if v}
            if cid in certified or pid in protected_profiles:
                protected_renderers.update(renderers)
                protected_profiles.add(pid)
            else:
                removed_renderers.update(renderers)
                conn.execute("DELETE FROM character_voice_profiles WHERE voice_profile_id=?", (pid,))
                counts['voice_profiles_deleted'] += 1
        counts['voice_assets_deleted'] = 0
        for filename, cid, pid in conn.execute(
            "SELECT filename,character_id,voice_profile_id FROM character_voice_assets"
        ).fetchall():
            if cid not in certified and pid not in protected_profiles:
                conn.execute("DELETE FROM character_voice_assets WHERE filename=?", (filename,))
                counts['voice_assets_deleted'] += 1
        states = conn.execute(
            "SELECT s.conversation_id,s.message_id,COALESCE(NULLIF(m.speaker_character_id,''),v.character_id) "
            "FROM message_voice_states s JOIN conversations v ON v.id=s.conversation_id "
            "LEFT JOIN messages m ON m.conversation_id=s.conversation_id AND m.message_id=s.message_id"
        ).fetchall()
        counts['voice_states_deleted'] = 0
        for conv, mid, speaker in states:
            if speaker not in certified:
                conn.execute("DELETE FROM message_voice_states WHERE conversation_id=? AND message_id=?", (conv, mid))
                counts['voice_states_deleted'] += 1
        counts['audio_cache_deleted'] = 0
        for key, cid in conn.execute("SELECT voice_cache_key,character_id FROM message_voice_audio_cache").fetchall():
            if cid not in certified:
                conn.execute("DELETE FROM message_voice_audio_cache WHERE voice_cache_key=?", (key,))
                counts['audio_cache_deleted'] += 1
        conn.commit()
        counts['quick_check'] = conn.execute('PRAGMA quick_check').fetchone()[0]
        counts['removed_renderer_ids'] = sorted(removed_renderers - protected_renderers)
        counts['protected_renderer_ids'] = sorted(protected_renderers)
        return counts


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', required=True)
    parser.add_argument('--backup', required=True)
    parser.add_argument('--report', required=True)
    args = parser.parse_args()
    result = clean_database(args.db, args.backup)
    Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))
