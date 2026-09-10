"""Lossless transport compaction; never change source state or reply prose."""
from __future__ import annotations

from datetime import datetime, timezone


def normalize_used_facts(facts):
    """Accept only the known legacy type/content record, retaining its text exactly.

    AGENT_RUN_RESPONSE retains the original model response for auditing; this
    conversion affects only the validated delivery envelope, not that raw log.
    """
    if not isinstance(facts, list):
        raise ValueError("used_facts必须是字符串数组，可以为空")
    result = []
    for fact in facts:
        if isinstance(fact, str):
            result.append(fact)
        elif (isinstance(fact, dict) and set(fact) == {"type", "content"}
              and isinstance(fact["type"], str) and fact["type"].strip()
              and isinstance(fact["content"], str) and fact["content"].strip()):
            result.append(fact["content"])
        else:
            raise ValueError("used_facts必须是字符串数组，可以为空")
    return result


def compact_task_data(data):
    """Compact an already isolated prompt object; retain ambiguous duplicates.

    Source times remain the canonical mapping used by memory tools. Only remove
    a message's millisecond timestamp when that mapping proves the same instant.
    Original history in the backend and tool responses is never changed.
    """
    times = data.get("source_message_times")
    removed_time = False
    if isinstance(times, dict):
        messages = []
        for key in ("recent_raw_messages", "current_user_batch"):
            if isinstance(data.get(key), list):
                messages.extend(data[key])
        if isinstance(data.get("latest_user_message"), dict):
            messages.append(data["latest_user_message"])
        for message in messages:
            if not isinstance(message, dict):
                continue
            stamp = message.get("timestamp")
            meta = times.get(message.get("message_id"))
            if type(stamp) is not int or not isinstance(meta, dict):
                continue
            try:
                instant = datetime.fromisoformat(meta.get("occurred_at", "").replace("Z", "+00:00"))
                if instant.tzinfo is None:
                    continue
                # Integer arithmetic preserves millisecond precision and avoids
                # treating rounded sub-millisecond values as identical.
                delta = instant.astimezone(timezone.utc) - datetime(1970, 1, 1, tzinfo=timezone.utc)
                micros = (delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds
                if micros != stamp * 1000:
                    continue
            except (TypeError, ValueError, AttributeError, OverflowError):
                continue
            del message["timestamp"]
            removed_time = True
    if removed_time:
        data["message_time_reference"] = "消息未列timestamp时，以message_id查source_message_times的occurred_at；它与原始毫秒时间戳是同一时刻。"

    state = data.get("relationship_state")
    if isinstance(state, dict) and state:
        keys = ("relationship_stage", "character_intimacy_style", "requested_escalation", "user_pressure_level")
        for name in ("relationship_context", "relationship_execution_contract"):
            obj = data.get(name)
            if not isinstance(obj, dict) or "relationship_state_ref" in obj:
                continue
            # All four must agree. Partial or contradictory evidence stays intact.
            if all(k in state and k in obj and type(obj[k]) is type(state[k]) and obj[k] == state[k] for k in keys):
                for key in keys:
                    del obj[key]
                obj["relationship_state_ref"] = "relationship_state"
    return data
