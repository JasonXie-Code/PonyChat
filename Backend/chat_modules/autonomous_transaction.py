"""Commit reply, staged memory and requested reviews before any delivery event."""
import asyncio
import json
import sqlite3
import time
import uuid


def install_memory_transaction(request, store, business=None):

    async def before_commit(conn):
        task = asyncio.current_task()
        internal_followup = getattr(request, '_normal_internal_followup_task_id', '')
        internal_task = getattr(request, '_normal_internal_proactive_task_id', '')
        if internal_followup:
            from ..proactive_settings import load_proactive_settings
            from ..scheduled_followup import _source_has_user_reply_after_message, proactive_reply_limit_reached
            if not (await load_proactive_settings(request.username)).enabled:
                raise RuntimeError('Proactive messages disabled before follow-up commit')
            row = await (await conn.execute(
                "SELECT status,expires_at_ms FROM scheduled_followups WHERE id=? AND username=? AND character_id=? AND conversation_id=?",
                (internal_followup, request.username, request.character_id, request.conversation_id))).fetchone()
            if not row or row[0] != 'processing':
                raise RuntimeError('Follow-up cancelled before reply commit')
            if row[1] and row[1] < int(time.time() * 1000):
                raise RuntimeError('Follow-up expired before reply commit')
            if await _source_has_user_reply_after_message(conn, request.conversation_id,
                    getattr(request, '_normal_internal_proactive_source_message_id', '')):
                raise RuntimeError('User replied before follow-up commit')
            if (await proactive_reply_limit_reached(conn, request.conversation_id)).get('reached'):
                raise RuntimeError('Consecutive proactive reply limit reached')
        if business and business.schedules:
            from ..proactive_settings import load_proactive_settings
            settings = await load_proactive_settings(request.username)
            if not settings.enabled:
                raise RuntimeError('Scheduling was disabled before reply commit')
            from ..scheduled_followup import proactive_reply_limit_reached
            if any(p['kind']=='followup' for p in business.schedules):
                if (await proactive_reply_limit_reached(conn, request.conversation_id)).get('reached'):
                    raise RuntimeError('Consecutive proactive reply limit reached')

        def current():
            guard = getattr(request, '_autonomous_generation_is_current', lambda: True)
            cancelling = getattr(task, 'cancelling', lambda: task.cancelled() or getattr(task, '_must_cancel', False))
            return not cancelling() and guard()

        def write():
            raw = conn._conn
            factory = raw.row_factory
            raw.row_factory = sqlite3.Row
            try:
                if not current():
                    raise RuntimeError('Generation was superseded before reply commit')
                from .normal_lifecycle import assert_normal_reply_allowed_on_connection
                assert_normal_reply_allowed_on_connection(raw, request)
                if internal_task:
                    from ..proactive_task_commit import assert_task_processing_on_connection
                    assert_task_processing_on_connection(raw, request)
                preferences = getattr(request, '_autonomous_preference_edits', None)
                if preferences:
                    preferences.commit_on_connection(raw)
                # Settings can be changed without a new chat request/configure.
                if store or internal_followup or internal_task or (business and business.schedules):
                    settings_row = raw.execute('SELECT s.settings FROM user_settings s JOIN users u ON u.id=s.user_id WHERE u.username=?',
                                               (request.username,)).fetchone()
                    persisted_settings = json.loads(settings_row[0]) if settings_row else {}
                    if store and persisted_settings.get('memory_enabled') is False:
                        raise RuntimeError('Memory was disabled before reply commit')
                    if (internal_followup or internal_task or business and business.schedules) and (persisted_settings.get('memory_enabled') is False or
                                                           persisted_settings.get('proactive_messages_enabled') is False):
                        raise RuntimeError('Scheduling was disabled before reply commit')
                saved = store.commit_on_connection(raw, generation_is_current=current) if store else []
                target = getattr(store, 'review_target', None) if store else None
                if target:
                    from ..agent_memory.schema import bump
                    bump(raw, store.username, store.character_id, delay=0)
                    raw.execute('UPDATE agent_memory_state SET target_period=? WHERE username=? AND character_id=?',
                                (json.dumps(target), store.username, store.character_id))
                request._autonomous_committed_memories = saved
                from ..agent_memory.participants import share_reply_experience_on_connection
                share_reply_experience_on_connection(raw, request)
                scene_patch = getattr(request, '_autonomous_scene_patch', None)
                if store is not None and scene_patch is not None:
                    from .autonomous_scene_state import commit_scene
                    commit_scene(raw, store, request._autonomous_scene_snapshot, scene_patch,
                                 list(getattr(request, '_autonomous_pending_reply_message_ids', ()) or ()))
                if business:
                    from .autonomous_schedule import persist_schedules
                    persist_schedules(raw, business)
                    if business.lifecycle:
                        now = int(time.time()*1000)
                        from .normal_speaker import effective_speaker_character_id
                        raw.execute('''INSERT INTO normal_character_lifecycle(username,character_id,conversation_id,state,
                            death_message_id,death_reason,created_at_ms,updated_at_ms) VALUES(?,?,?,'dead',?,?,?,?)
                            ON CONFLICT(username,character_id,conversation_id) DO UPDATE SET state='dead',
                            death_message_id=excluded.death_message_id,death_reason=excluded.death_reason,updated_at_ms=excluded.updated_at_ms''',
                            (request.username,effective_speaker_character_id(request) or request.character_id,request.conversation_id,
                             business.lifecycle['source_message_id'],business.lifecycle['reason'],now,now))
                fields = getattr(request, '_autonomous_image_fields', None)
                if fields:
                    raw.execute('''INSERT INTO normal_image_contexts(entry_id,username,character_id,conversation_id,created_ms,
                        user_text,image_count,should_refuse,image_summary,visible_text,identified_entities_json,uncertainty,error)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                        (uuid.uuid4().hex,request.username,request.character_id,request.conversation_id,int(time.time()*1000),
                         fields['user_text'],fields['image_count'],int(fields.get('should_refuse',False)),fields.get('image_summary',''),
                         fields.get('visible_text',''),json.dumps(fields.get('identified_entities',[]),ensure_ascii=False),
                         fields.get('uncertainty',''),fields.get('error','')))
                    raw.execute('DELETE FROM normal_image_contexts WHERE username=? AND character_id=? AND conversation_id=? '
                        'AND entry_id NOT IN (SELECT entry_id FROM normal_image_contexts WHERE username=? AND character_id=? '
                        'AND conversation_id=? ORDER BY created_ms DESC,rowid DESC LIMIT 10)',
                        (request.username,request.character_id,request.conversation_id)*2)
                raw.execute('''INSERT INTO normal_image_context_state(username,character_id,conversation_id,last_reply_based_on_image,updated_ms)
                    VALUES(?,?,?,?,?) ON CONFLICT(username,character_id,conversation_id) DO UPDATE SET
                    last_reply_based_on_image=excluded.last_reply_based_on_image,updated_ms=excluded.updated_ms''',
                    (request.username,request.character_id,request.conversation_id,
                     int(bool(fields or getattr(request,'_autonomous_prior_image_used',False))),int(time.time()*1000)))
                if internal_followup:
                    from ..proactive_task_commit import current_reply_message_id
                    delivered = current_reply_message_id(raw, request)
                    # A restart between reply commit and scheduler audit must
                    # never requeue an already delivered follow-up.
                    if delivered is not None:
                        raw.execute("UPDATE scheduled_followups SET status='sent',sent_message_id=?,updated_at_ms=? "
                                    "WHERE id=? AND status='processing'",
                                    (delivered, int(time.time()*1000), internal_followup))
                if internal_task:
                    from ..proactive_task_commit import finish_task_on_connection
                    finish_task_on_connection(raw, request)
                if not current():
                    raise RuntimeError('Generation was superseded before reply commit')
                if business and business.lifecycle:
                    request._normal_committed_death_message_id = business.lifecycle['source_message_id']
            finally:
                raw.row_factory = factory

        # aiosqlite executes on its own worker; never pass its connection to
        # asyncio.to_thread or create a second writer while this transaction holds.
        await conn._execute(write)

    request._autonomous_before_reply_commit = before_commit
