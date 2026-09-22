import ast
from pathlib import Path


MODULES = {
    'autonomous_behavior_policy.py': {'continuity'},
    'assets.py': {'ASSET_SELECTOR_SYSTEM'},
    'autonomous_delivery.py': set(),
    'autonomous_followup.py': {'followup_contract'},
    'autonomous_normal.py': {'COGNITION_CORE', 'SKILL_CALL_CHECKS', 'WORKFLOW_GENERATION'},
    'autonomous_web_images.py': {'media_handling'},
    'autonomous_preferences.py': {'preferences'},
    'autonomous_prompt_rules.py': {'reply_language', 'character_body', 'speech', 'followup_summary', 'followup'},
    'autonomous_prompt_skills.py': {'COGNITION_CORE', 'evidence', 'narrative'},
    'autonomous_reply.py': {'OUTPUT_CONTRACT'},
    'autonomous_web_search.py': {'mlp_reference'},
    'character.py': {
        'ROLEPLAY_ANCHOR_PROMPT',
    },
    'interaction_modes.py': {'instant_messaging', 'virtual_roleplay'},
    'normal_speaker_impl/speaker_selection.py': {'USER_SPEAKER_INTENT_SYSTEM'},
    'reply_expression_skill.py': {'reply_expression'},
    'smart_router.py': {'SMART_ROUTER_SEARCH_SYSTEM'},
    'web_image_style.py': {'image_style'},
}


def test_static_prompt_texts_have_one_source_file():
    root = Path(__file__).resolve().parents[1] / 'chat_modules'
    source = (root / 'Prompts.py').read_text(encoding='utf-8')
    for names in MODULES.values():
        for name in names:
            assert f'{name} = ' in source

    for filename, names in MODULES.items():
        tree = ast.parse((root / filename).read_text(encoding='utf-8'))
        assigned = {
            target.id
            for node in tree.body if isinstance(node, ast.Assign)
            for target in node.targets if isinstance(target, ast.Name)
        }
        assert not assigned & names
