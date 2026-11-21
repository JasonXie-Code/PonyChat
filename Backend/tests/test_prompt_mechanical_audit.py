"""Active prompt contracts remain single-sourced."""
import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'chat_modules/Prompts.py').read_text(encoding='utf-8')
PROMPTS = {}
exec(compile(SOURCE, 'Prompts.py', 'exec'), PROMPTS)


def test_fixed_prompt_templates_have_consumers():
    # Only these dictionaries have a literal-access contract. Skill registries
    # are consumed dynamically and do not belong here.
    names = {'AUTONOMOUS_BUSINESS_TEXT', 'AUTONOMOUS_PROMPT_SKILLS_TEXT',
             'AUTONOMOUS_SHORTCUTS_TEXT', 'AUTONOMOUS_WEB_SEARCH_TEXT'}
    used = {name: set() for name in names}
    for path in ROOT.rglob('*.py'):
        if path == ROOT / 'chat_modules/Prompts.py' or 'tests' in path.relative_to(ROOT).parts:
            continue
        source = path.read_text(encoding='utf-8-sig')
        if not any(name in source for name in names):
            continue
        tree = ast.parse(source)
        aliases = {name: name for name in names}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                aliases.update({a.asname or a.name: a.name for a in node.names if a.name in names})
        for node in ast.walk(tree):
            if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
                name = aliases.get(node.value.id)
                if name:
                    assert isinstance(node.slice, ast.Constant), (path, node.lineno)
                    used[name].add(node.slice.value)
    for name in names:
        assert set(PROMPTS[name]) == used[name], (name, set(PROMPTS[name]) ^ used[name])


def test_nonhuman_limb_feedback_uses_shared_prompt():
    path = ROOT / 'chat_modules/normal_nonstream_impl/handoff_router_recent_assistant_turns_impl/handoff_router.py'
    source = path.read_text(encoding='utf-8')
    function = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)
                    and n.name == '_description_reply_violation_reason')
    scope = {'re': re, 'AUTONOMOUS_SHORTCUTS_TEXT': PROMPTS['AUTONOMOUS_SHORTCUTS_TEXT'],
             '_DESCRIPTION_NONHUMAN_LIMB_RE': re.compile('手掌'),
             '_description_is_human_species': lambda species: species == 'human'}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), 'exec'), scope)
    check = scope['_description_reply_violation_reason']
    assert check('摊开手掌', character_species='pony') == PROMPTS['AUTONOMOUS_SHORTCUTS_TEXT']['description_error_2']
    assert check('摊开手掌', character_species='human') == ''
    assert check('', character_species='pony') == ''
    assert PROMPTS['AUTONOMOUS_SHORTCUTS_TEXT']['description_error_2'] not in source


def test_prompt_dictionaries_have_no_duplicate_literal_keys():
    for node in ast.walk(ast.parse(SOURCE)):
        if isinstance(node, ast.Dict):
            keys = [key.value for key in node.keys if isinstance(key, ast.Constant)]
            assert len(keys) == len(set(keys)), node.lineno


def test_followup_contract_and_errors_derive_limits_from_one_definition():
    tree = ast.parse(SOURCE)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'FOLLOWUP_LIMITS'
                                                for t in node.targets):
            node.value = ast.parse("{'text_min': 2, 'text_max': 7, 'delay_min': 13, 'delay_max': 19}", mode='eval').body
    ast.fix_missing_locations(tree)
    changed = {}
    exec(compile(tree, 'changed_limits.py', 'exec'), changed)
    assert changed['followup_summary'] is changed['followup_contract']
    assert '2到7' in changed['followup_contract'] and '13到19' in changed['followup_contract']
    errors = changed['AUTONOMOUS_FOLLOWUP_TEXT']
    assert '2到7' in errors['finalize_followup_2'] and '2到7' in errors['finalize_followup_3']
    assert '13到19' in errors['finalize_followup_4']


def test_numeric_rule_references_are_replaced_by_stable_topics():
    for name in ('speech', 'delivery'):
        assert not re.search(r'第\d+条', PROMPTS[name])
    assert '【声音延长条件】' in PROMPTS['speech']
    assert '【声音与纯描写】' in PROMPTS['speech']
    assert '【混合片段与顺序保留】' in PROMPTS['delivery']
    assert '分别为6分、7分、8分、10分' in PROMPTS['memory']


def test_router_has_one_policy_owner_and_wire_errors_share_one_key():
    assert not {f'payload_{i}' for i in range(1, 6)} & PROMPTS['SPEAKER_SELECTION_TEXT'].keys()
    source = (ROOT / 'chat_modules/normal_speaker_impl/speaker_selection.py').read_text(encoding='utf-8')
    assert '输出前自检' not in source
    assert 'used_facts_type' in PROMPTS['AUTONOMOUS_WIRE_FORMAT_TEXT']
    assert 'normalize_used_facts_1' not in PROMPTS['AUTONOMOUS_WIRE_FORMAT_TEXT']
    assert 'normalize_used_facts_2' not in PROMPTS['AUTONOMOUS_WIRE_FORMAT_TEXT']
