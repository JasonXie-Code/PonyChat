"""Offline checks for the isolated experiment, not a production feature flag."""
import asyncio
import importlib.util
import json
from pathlib import Path

import pytest


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


@pytest.fixture(scope='module')
def trial(tmp_path_factory):
    import sys
    root = Path(__file__).resolve().parents[2]
    scripts = str(root / 'Backend/Agent-Test')
    sys.path.insert(0, scripts)
    try:
        from build_single_agent_expression_trial import build
        destination = tmp_path_factory.mktemp('single-agent') / 'runtime'
        build(destination)
    finally:
        sys.path.remove(scripts)
    return destination / 'Backend/chat_modules'


def source(edits):
    return json.dumps({'bubble_count': 1, 'bubbles': [{'index': 1, 'parts': [
        {'kind': 'speech', 'text': '好，你靠着就好。安静也很好。'}]}],
        'scene_patch': {'reset': False}, 'expression_edits': edits}, ensure_ascii=False)


def test_inline_deletion_preserves_metadata_and_draft(trial):
    editor = module(trial / 'agent_expression_review.py', 'Backend.chat_modules.trial_editor')
    edits = [{'bubble': 1, 'part': 1, 'original': '好，你靠着就好。安静也很好。',
              'replacement': '好，你靠着就好。', 'reason': '末句重复安静陪伴'}]
    final, record = editor.apply_inline_revision(source(edits), {})
    result = json.loads(final)
    assert result['bubbles'][0]['parts'][0]['text'] == '好，你靠着就好。'
    assert result['scene_patch'] == {'reset': False}
    assert record['draft']['bubbles'][0]['parts'][0]['text'].endswith('安静也很好。')
    assert record['independent_review_calls'] == 0


@pytest.mark.parametrize('replacement', ['好，我陪你去散步。', '安静也很好。好，你靠着就好。', ''])
def test_invalid_authorship_or_empty_reply_rejected(trial, replacement):
    editor = module(trial / 'agent_expression_review.py', 'Backend.chat_modules.trial_editor')
    with pytest.raises(ValueError):
        editor.apply_inline_revision(source([{'bubble': 1, 'part': 1,
            'original': '好，你靠着就好。安静也很好。', 'replacement': replacement, 'reason': 'test'}]), {})


def test_skill_gate_and_no_extra_review_runner(trial):
    editor = module(trial / 'agent_expression_review.py', 'Backend.chat_modules.trial_editor')
    with pytest.raises(ValueError, match='expression_revision'):
        editor.apply_inline_revision(source([]), {'expression_revision_required': True})
    skills = module(trial / 'autonomous_prompt_skills.py', 'Backend.chat_modules.trial_skills')

    async def actual_turn(**kwargs):
        return {'inline_expression_review': {'status': 'reviewed_inline'}}

    async def forbidden_runner(*args, **kwargs):
        raise AssertionError('Independent model review must not be called')

    result = asyncio.run(skills.run_skill_turn(actual_turn, character_profile='',
        model_config={}, harness_runner=forbidden_runner))
    assert result['prompt_skills']['expression_review']['status'] == 'reviewed_inline'
