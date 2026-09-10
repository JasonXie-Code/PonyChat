"""Offline production-log replay. Outputs metrics only; no model requests."""
import ast
import copy
import importlib
import json
from pathlib import Path
import re
import sys
import types
import typing


def main():
    candidate = Path(sys.argv[1])
    ns = dict(vars(typing), json=json, re=re)
    parser = Path('/opt/ponychat/Backend/routes/admin/llm_log_indexer.py')
    for node in ast.parse(parser.read_text()).body:
        if isinstance(node, ast.FunctionDef) and node.name in {
                '_js_template_to_json', '_normalize_debug_log_literal', '_loads_debug_log_literal'}:
            exec(compile(ast.Module(body=[node], type_ignores=[]), 'parser', 'exec'), ns)
    package = types.ModuleType('sample_candidate')
    package.__path__ = [str(candidate / 'Backend/chat_modules')]
    sys.modules[package.__name__] = package
    reply = importlib.import_module('sample_candidate.autonomous_reply')
    wire = importlib.import_module('sample_candidate.autonomous_wire_format')
    rows = []
    repair = []
    for path in sorted(Path('/opt/ponychat/var/.chatlogs/2026-09-07/19').glob('*.js')):
        if not '20260907_192401' <= path.name[:15] <= '20260907_193401':
            continue
        record = ns['_loads_debug_log_literal'](path.read_text().split('=', 1)[1])
        if not record or record.get('stage') != 'AGENT_RUN_RESPONSE' or record.get('mode') != 'normal':
            continue
        data = record['data']
        prompt = data['request']['prompt']
        text = prompt if isinstance(prompt, str) else next(b['text'] for b in prompt if b.get('type') == 'text')
        original = json.loads(text)
        compact = wire.compact_task_data(copy.deepcopy(original))
        # No source-time mappings, source IDs, sequences, content or delivery state lost.
        assert compact['source_message_times'] == original['source_message_times']
        for key in ('recent_raw_messages', 'current_user_batch'):
            assert len(compact[key]) == len(original[key])
            for before, after in zip(original[key], compact[key]):
                assert all(after.get(k) == v for k, v in before.items() if k != 'timestamp')
        assert compact.get('environment') == original.get('environment')
        before_chars = len(json.dumps(original, ensure_ascii=False))
        after_chars = len(json.dumps(compact, ensure_ascii=False, separators=(',', ':')))
        rows.append({'time': record['timestamp'], 'before_characters': before_chars,
                     'after_characters': after_chars, 'saved_characters': before_chars - after_chars})
        if record['timestamp'].startswith('2026-09-07T19:30') and record['params'].get('run_number') in (1, 3):
            raw = data['final_response']
            normalized, _ = reply.reply_envelope(raw)
            assert json.loads(normalized)['bubbles'] == json.loads(raw)['bubbles']
            repair.append(json.loads(normalized))
    assert len(rows) == 9 and len(repair) == 2
    assert repair[0]['bubbles'] == repair[1]['bubbles']
    result = {'offline_only': True, 'model_requests': 0, 'samples': rows,
              'known_failure_accepted': True, 'bubbles_unchanged': True,
              'source_references_and_history_preserved': True,
              'before_characters': sum(r['before_characters'] for r in rows),
              'after_characters': sum(r['after_characters'] for r in rows)}
    print(json.dumps(result))


if __name__ == '__main__':
    main()
