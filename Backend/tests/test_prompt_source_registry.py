"""The normal Agent's skill names and static text have one source of truth."""
import ast
import importlib
import re
from pathlib import Path

from test_autonomous_normal import PACKAGE

prompts = importlib.import_module(PACKAGE + '.Prompts')
shortcuts = importlib.import_module(PACKAGE + '.autonomous_shortcuts')
ROOT = Path(__file__).resolve().parents[1]
TEXT_COMPONENTS = (
    'harness_live_input.py', 'harness_runtime.py', 'memory_importance.py',
    'personal_preferences.py', 'character.py', 'species_anatomy.py',
    'history_image_tools.py', 'interaction_modes.py',
    'normal_speaker_impl/speaker_selection.py',
)


def test_every_skill_uses_its_exact_registered_name_as_the_source_variable():
    assert set(prompts.CHAT_SKILL_TEXTS) == set(prompts.SKILL_TITLES)
    tree = ast.parse((ROOT / 'chat_modules/Prompts.py').read_text(encoding='utf-8'))
    definitions = {target.id: node.value for node in tree.body if isinstance(node, ast.Assign)
                   for target in node.targets if isinstance(target, ast.Name)}
    for name, text in prompts.CHAT_SKILL_TEXTS.items():
        assert isinstance(text, str) and text.strip()
        assert getattr(prompts, name) == text
        assert isinstance(definitions[name], ast.Constant), name
        assert definitions[name].value == text
    assert not hasattr(prompts, 'SPEECH_GUIDANCE')
    assert not hasattr(prompts, 'LEGACY_NORMAL_SYSTEM')


def test_skill_rule_numbers_are_continuous_and_examples_are_not_embedded():
    for name, text in prompts.CHAT_SKILL_TEXTS.items():
        numbers = [int(match.group(1)) for line in text.splitlines()
                   if (match := re.match(r'^(\d+)\.\s', line))]
        assert numbers == list(range(1, len(numbers) + 1)), (name, numbers)
        assert not re.search(r'例如|比如|譬如|示例', text), name


def test_skill_search_markers_are_adjacent_to_their_definitions():
    source = (ROOT / 'chat_modules/Prompts.py').read_text(encoding='utf-8')
    for name in prompts.CHAT_SKILL_TEXTS:
        assert source.count(f'# 【{name}】') == 1, name
        marker = rf'# skill: {re.escape(name)}[^\n]*\n# 【{re.escape(name)}】\n{name} = '
        assert re.search(marker, source), name


def test_removed_prompt_fragments_do_not_return():
    obsolete = {
        'LEGACY_NORMAL_SYSTEM', 'NEUTRAL_EXAMPLES', 'SPEECH_GUIDANCE', 'ROUTING',
        'PARTICIPANT_AND_SCENE_RULES', 'COGNITION_REFERENCE', 'SCENE_STATE_CONTRACT',
        'IMAGE_MATCH_POLICY', 'media_auxiliary_rules', 'web_search_mlp_scope',
        'memory_importance_rules',
    }
    assert not obsolete & set(vars(prompts))


def test_runtime_components_do_not_own_static_rule_prose():
    files = set((ROOT / 'chat_modules').glob('autonomous_*.py'))
    files.update(ROOT / 'chat_modules' / filename for filename in TEXT_COMPONENTS)
    files.add(ROOT / 'agent_memory/relationship_control.py')
    violations = []
    for path in sorted(files):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            if len(node.value) < 12 or not re.search('[\u4e00-\u9fff]', node.value):
                continue
            if isinstance(parents.get(node), ast.Expr):
                continue  # Python documentation is not sent to the Agent.
            chain, current = [], node
            while current in parents:
                current = parents[current]
                chain.append(current)
            if any(isinstance(parent, ast.Call) and isinstance(parent.func, ast.Attribute)
                   and isinstance(parent.func.value, ast.Name) and parent.func.value.id == 're'
                   for parent in chain):
                continue  # Matching syntax stays beside the matching logic.
            violations.append(f'{path.relative_to(ROOT)}:{node.lineno}')
    assert not violations, violations


def test_speech_requirement_is_scoped_to_virtual_roleplay():
    assert 'name为speech' in prompts.virtual_roleplay
    assert 'name为speech' not in prompts.SKILL_CALL_CHECKS
    assert 'name为speech' not in prompts.instant_messaging


def test_shortcut_profile_parsing_does_not_invent_a_pony():
    for profile in ('{"profileSpecies": "人类"}', "{'profileSpecies': '人类'}", '【角色档案】\n种族：人类'):
        species = shortcuts._character_species(profile)
        assert species == '人类'
        assert shortcuts._description_error('我的手指轻轻弯曲', species) == ''
    assert shortcuts._character_species('没有种族字段') == ''


def test_prompt_module_has_no_duplicate_variable_definitions_or_business_imports():
    tree = ast.parse((ROOT / 'chat_modules/Prompts.py').read_text(encoding='utf-8'))
    names = [target.id for node in tree.body if isinstance(node, ast.Assign)
             for target in node.targets if isinstance(target, ast.Name)]
    assert len(names) == len(set(names))
    assert not any(isinstance(node, (ast.Import, ast.ImportFrom)) for node in tree.body)
