"""Atomic delivery receipts for user-created and Agent-created timed tasks."""
import json
import time


def current_reply_message_id(conn, request):
    message_ids = tuple(getattr(request, '_autonomous_pending_reply_message_ids', ()) or ())
    if not message_ids:
        return None  # Agent silence is valid and does not count as task delivery.
    rows = conn.execute(
        "SELECT message_id FROM messages WHERE conversation_id=? AND role='assistant' "
        "AND deleted_at IS NULL AND COALESCE(is_hidden,0)=0 AND message_id IN ("
        + ','.join('?' for _ in message_ids) + ") ORDER BY timestamp DESC,rowid DESC",
        (request.conversation_id, *message_ids),
    ).fetchall()
    if len(rows) != len(set(message_ids)):
        raise RuntimeError('Task delivery receipt requires every reply message to be saved')
    if any(row[0] == request._normal_internal_proactive_source_message_id for row in rows):
        raise RuntimeError('Task delivery receipt cannot reuse its source reply')
    return rows[0][0]


def assert_task_processing_on_connection(conn, request):
    task_id = request._normal_internal_proactive_task_id
    row = conn.execute(
        "SELECT * FROM proactive_tasks WHERE id=? AND username=? AND character_id=? "
        "AND (conversation_id=? OR conversation_id='')",
        (task_id, request.username, request.character_id, request.conversation_id),
    ).fetchone()
    if not row or row['status'] != 'processing':
        raise RuntimeError('Timed task cancelled or changed before reply commit')
    if row['cancel_if_user_replies']:
        source = conn.execute(
            "SELECT sequence_number,timestamp FROM messages WHERE conversation_id=? AND message_id=?",
            (request.conversation_id, request._normal_internal_proactive_source_message_id),
        ).fetchone()
        if not source and request._normal_internal_proactive_source_message_id:
            raise RuntimeError('Timed task source no longer exists')
        source_seq = (source[0] or 0) if source else 0
        source_ts = (source[1] or 0) if source else row['created_at_ms']
        later = conn.execute(
            "SELECT 1 FROM messages WHERE conversation_id=? AND role='user' AND deleted_at IS NULL "
            "AND COALESCE(is_hidden,0)=0 AND ((?=1 AND COALESCE(sequence_number,0)>?) OR "
            "(COALESCE(sequence_number,0)=? AND COALESCE(timestamp,0)>?) OR "
            "(?=0 AND COALESCE(timestamp,0)>?)) LIMIT 1",
            (request.conversation_id, int(bool(source)), source_seq, source_seq, source_ts,
             int(bool(source)), source_ts),
        ).fetchone()
        if later:
            raise RuntimeError('User replied before timed task commit')
    return dict(row)


def finish_task_on_connection(conn, request):
    from .proactive_tasks import _next_due_ms, normalize_schedule_type

    row = assert_task_processing_on_connection(conn, request)
    delivered = current_reply_message_id(conn, request)
    if delivered is None:
        return
    metadata = json.loads(row['metadata_json'] or '{}')
    metadata.update(last_result='sent', last_message_id=delivered)
    metadata.pop('last_reason', None)
    recurring = normalize_schedule_type(row['schedule_type']) != 'once'
    now = int(time.time() * 1000)
    conn.execute(
        "UPDATE proactive_tasks SET status=?,due_at_ms=?,last_run_at_ms=?,run_count=run_count+1,"
        "metadata_json=?,updated_at_ms=? WHERE id=? AND status='processing'",
        ('active' if recurring else 'completed', _next_due_ms(row) if recurring else row['due_at_ms'],
         now, json.dumps(metadata, ensure_ascii=False), now, row['id']),
    )
