"""Ensure the experiment changes loading, not the source rule text or production class."""
from pathlib import Path
import asyncio
import re

from replay_expression_focus import load_modules
from expression_path_experiment import CORE, PATHS, partition, split_session_class


def test_every_original_rule_is_preserved_verbatim_in_at_least_one_manual():
    modules = load_modules()
    skills = modules['autonomous_prompt_skills']
    original = Path(__file__).with_name('expression_original.txt').read_text(encoding='utf-8')
    cls = split_session_class(skills.PromptSkills, original)
    session = cls(profile='名称：柔柔', preferences='', business=None, normal_module=modules['autonomous_normal'])
    delivered = '\n'.join(session.skill_instructions(n) for n in ('reply_expression', *PATHS))
    for number, rule in partition(original).items():
        assert rule in delivered, number
    assert set(CORE).union(*map(set, PATHS.values())) == set(range(1, 19))


def test_split_is_local_and_loading_a_path_does_not_load_other_paths():
    modules = load_modules()
    skills = modules['autonomous_prompt_skills']
    args = dict(profile='名称：柔柔', preferences='', business=None, normal_module=modules['autonomous_normal'])
    baseline = skills.PromptSkills(**args)
    original = baseline.skill_instructions('reply_expression')
    cls = split_session_class(skills.PromptSkills, Path(__file__).with_name('expression_original.txt').read_text(encoding='utf-8'))
    session = cls(**args)
    result = asyncio.run(session.load({'name': 'description_reply'}))
    assert result['skill'] == 'description_reply'
    assert session.loaded == {'description_reply'}
    assert baseline.skill_instructions('reply_expression') == original
    assert not (set(baseline.catalog) & set(PATHS))
    assert '3. ' in result['instructions'] and '7. ' in result['instructions']


def test_each_selected_path_retains_original_description_gate_and_body_requirements():
    rules = partition(Path(__file__).with_name('expression_original.txt').read_text(encoding='utf-8'))
    for name, indices in PATHS.items():
        assert 7 in indices, name
    assert 'character_body' in rules[7]
    assert 'relationship' in rules[7]
    assert '没有需要承接的已确认持续动作' in rules[7]
    assert 14 in CORE and 18 in CORE
