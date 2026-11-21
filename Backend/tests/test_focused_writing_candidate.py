import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest


directory = Path(__file__).parents[1] / 'Agent-Test'
sys.path.insert(0, str(directory))
spec = importlib.util.spec_from_file_location('tested_focused_writing', directory / 'focused_writing_candidate.py')
candidate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(candidate)


def prepared_snapshot(tmp_path, *, missing_preferences=False):
    source = tmp_path / 'source'
    path = source / 'Backend/chat_modules/Prompts.py'
    path.parent.mkdir(parents=True)
    preferences = '当前用户明确指定：苹果丽丽、醒目露露。\n当前用户的明确身体词偏好：蹄子；名字允许。\n当前用户明确不喜欢相处中的记账。'
    values = {'reply_expression': 'old writing\n' + ('' if missing_preferences else preferences),
              'HISTORY_CONTEXT_RULE': 'old history', 'COGNITION_CORE': 'old duties',
              'CHARACTER_DIRECTION_RULE': 'director material'}
    values.update({key: 'unchanged ' + key for key in ('character_body', 'reply_perspective',
        'delivery', 'reply_language', 'voice_reply', 'evidence', 'continuity', 'followup')})
    path.write_text('\n'.join(name + ' = ' + repr(value) for name, value in values.items()) + '\n', encoding='utf-8')
    adapter = source / 'Backend/chat_modules/autonomous_prompt_skills.py'
    adapter.write_bytes(b'unchanged runtime adapter\n')
    manifest = {str(p.relative_to(source)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in (path, adapter)}
    (tmp_path / 'source-manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    return source, path, preferences, manifest


def test_candidate_preserves_constraints_and_adapter_and_updates_verified_manifest(tmp_path):
    source, path, preferences, before_manifest = prepared_snapshot(tmp_path)
    before = candidate.constants(path)
    candidate.configure(source, tmp_path)
    after = candidate.constants(path)
    for line in preferences.splitlines():
        assert line in after['reply_expression']
    for name in before.keys() - {'reply_expression', 'HISTORY_CONTEXT_RULE', 'COGNITION_CORE'}:
        assert before[name] == after[name]
    assert '双方明确确认' in after['HISTORY_CONTEXT_RULE']
    assert '每个新增气泡' in after['reply_expression']
    manifest = json.loads((tmp_path / 'source-manifest.json').read_text(encoding='utf-8'))
    assert manifest['Backend/chat_modules/Prompts.py'] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert manifest['Backend/chat_modules/autonomous_prompt_skills.py'] == before_manifest['Backend/chat_modules/autonomous_prompt_skills.py']


def test_candidate_rejects_missing_user_constraints_before_mutating_snapshot(tmp_path):
    source, path, _, _ = prepared_snapshot(tmp_path, missing_preferences=True)
    original = path.read_bytes()
    with pytest.raises(ValueError, match='calibrated'):
        candidate.configure(source, tmp_path)
    assert path.read_bytes() == original
