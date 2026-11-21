"""Bounded, evidence-validated fragments supplied on every normal turn."""
from contextlib import closing
from datetime import datetime, timezone
import json

from . import evidence
from .schema import connect
from .store import FRAGMENT_CATEGORIES


def build_fragment_context(store, *, now=None):
    now = now or datetime.now(timezone.utc)
    result = {
        'as_of': now.isoformat(), 'recent': [], 'important': [],
        'selection': {'recent_limit': 30, 'important_limit': 10,
                      'minimum_importance': 8, 'age_half_weight_days': 90},
        'note': 'recent按保存/更新时间倒序；important与recent去重，按重要性/(1+保存年龄天数/90)排序。'
                'created_at是保存/更新时间，occurred_at才是事件发生时间，null表示未知；旧事实不证明当前状态。',
    }
    with closing(connect(store.path)) as conn:
        conn.execute('BEGIN')
        state = conn.execute('SELECT epoch,enabled FROM agent_memory_state WHERE username=? AND character_id=?',
                             (store.username, store.character_id)).fetchone()
        if not state or state['epoch'] != store.epoch or not state['enabled']:
            return None
        categories = sorted(FRAGMENT_CATEGORIES)
        # No top-500 candidate cap: old high-value fragments remain eligible.
        rows = conn.execute('''SELECT v.*, COALESCE(ir.importance,v.importance) AS effective_importance
            FROM agent_memory_heads h JOIN agent_memory_versions v
              ON h.entry_id=v.entry_id AND h.version=v.version
            LEFT JOIN agent_memory_importance_reviews ir ON ir.entry_id=v.entry_id AND ir.version=v.version
            WHERE h.username=? AND h.character_id=? AND h.epoch=? AND v.kind='fact'
              AND v.status<>'retracted' AND v.scope_conversation_id=''
              AND v.category IN (''' + ','.join('?' for _ in categories) + ') ORDER BY h.id DESC',
            [store.username, store.character_id, store.epoch, *categories])
        candidates = []
        for row in rows:
            if not evidence.valid(conn, store.username, store.character_id, row):
                continue
            try:
                saved = datetime.fromisoformat(row['created_at'].replace('Z', '+00:00'))
                if saved.tzinfo is None:
                    saved = saved.replace(tzinfo=timezone.utc)
                saved_timestamp = saved.timestamp()
            except (ValueError, TypeError, AttributeError):
                saved_timestamp = 0
            age_days = max(0, (now.timestamp() - saved_timestamp) / 86400)
            item = {key: row[key] for key in ('entry_id', 'version', 'category', 'status',
                                             'certainty', 'content', 'created_at')}
            item.update(occurred_at=row['occurred_at'] or None,
                        importance=row['effective_importance'],
                        source_message_ids=json.loads(row['source_message_ids']),
                        source_ref=f"memory:{row['entry_id']}:{row['version']}")
            candidates.append((saved_timestamp, item['importance'] / (1 + age_days / 90), item))
        candidates.sort(key=lambda candidate: candidate[0], reverse=True)
        result['recent'] = [item for _, _, item in candidates[:30]]
        remaining = [candidate for candidate in candidates[30:] if candidate[2]['importance'] >= 8]
        remaining.sort(key=lambda candidate: (candidate[1], candidate[0], candidate[2]['importance']), reverse=True)
        result['important'] = [item for _, _, item in remaining[:10]]
    return result
