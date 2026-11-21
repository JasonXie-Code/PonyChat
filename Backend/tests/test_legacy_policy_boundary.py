"""Removed legacy policy must not return as a runtime dependency or prompt source."""
import ast
from pathlib import Path

from test_prompt_mechanical_audit import PROMPTS


ROOT = Path(__file__).resolve().parents[1]
GETTERS = {'get_reply_policy_text', 'get_planner_policy_text', 'get_voice_policy_text'}


def references(source, forbidden):
    for node in ast.walk(ast.parse(source)):
        value = (node.id if isinstance(node, ast.Name) else
                 node.attr if isinstance(node, ast.Attribute) else
                 node.name if isinstance(node, ast.alias) else
                 node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None)
        if value in forbidden:
            yield value


def test_runtime_cannot_read_legacy_defaults_or_inject_getters():
    forbidden = GETTERS | {
        'NORMAL_POLICY_DEFAULT', 'PLANNER_POLICY_REQUIRED_RULES', 'normal_policy',
        'get_normal_mode_policy', 'get_policy_version', 'write_normal_mode_policy',
        'normal_mode_policy.json', '/normal-policy',
    }
    for path in ROOT.rglob('*.py'):
        relative = path.relative_to(ROOT)
        if relative.parts[0] in {'tests', 'scripts', 'Agent-Test', '__pycache__', 'data'}:
            continue
        assert not list(references(path.read_text(encoding='utf-8-sig'), forbidden)), str(relative)


def test_legacy_policy_modules_and_defaults_are_removed():
    assert not (ROOT / 'chat_modules/normal_policy.py').exists()
    assert not (ROOT / 'routes/admin/normal_policy.py').exists()
    assert 'NORMAL_POLICY_DEFAULT' not in PROMPTS
    assert 'PLANNER_POLICY_REQUIRED_RULES' not in PROMPTS


def test_boundary_detects_alias_attribute_and_dynamic_name_access():
    for source in ('from x import get_reply_policy_text as alias',
                   'x.get_reply_policy_text()', 'getattr(x, "get_reply_policy_text")()'):
        assert list(references(source, GETTERS))


def test_creation_authority_is_defined_once_and_pointed_to_by_dependent_skills():
    marker = '【创作授权边界】'
    clause = '单纯要求详细、继续或多写一点不构成授权'
    assert [name for name, text in PROMPTS['CHAT_SKILL_TEXTS'].items() if clause in text] == ['narrative']
    for name in ('continuity', 'speech', 'interaction_reply'):
        assert 'narrative' + marker in PROMPTS[name]
        assert '明确授权的创作任务按narrative限定范围处理' not in PROMPTS[name]
