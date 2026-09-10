import ast
from pathlib import Path


MODULES = {
    'autonomous_behavior_policy.py': {'CONTINUITY_REVIEW'},
    'assets.py': {'ASSET_SELECTOR_SYSTEM'},
    'autonomous_delivery.py': {'LANGUAGE_CONTINUITY_RULE'},
    'autonomous_followup.py': {'FOLLOWUP_CONTRACT'},
    'autonomous_normal.py': {'RELATIONSHIP_INTERACTION_POLICY', 'LEGACY_NORMAL_SYSTEM'},
    'autonomous_scene_state.py': {'SCENE_STATE_CONTRACT'},
    'autonomous_web_images.py': {'IMAGE_MATCH_POLICY'},
    'autonomous_preferences.py': {'PREFERENCE_POLICY'},
    'autonomous_prompt_rules.py': {
        'CORE_EXPRESSION', 'CORE_DELIVERY', 'BUBBLE_COMPOSITION', 'CORE_LANGUAGE',
        'INTIMACY_MOTIVATION', 'BODY_EXPRESSION', 'SPEECH_GUIDANCE',
        'FOLLOWUP_SUMMARY', 'FOLLOWUP_GUIDANCE',
    },
    'autonomous_prompt_skills.py': {'COGNITION_REFERENCE', 'COGNITION_CORE'},
    'autonomous_reply.py': {'OUTPUT_CONTRACT'},
    'autonomous_scene_facts.py': {'PARTICIPANT_AND_SCENE_RULES'},
    'autonomous_web_search.py': {'MLP_CANON_SCOPE', 'MLP_WIKI_POLICY'},
    'character.py': {
        'ROLEPLAY_ANCHOR_PROMPT', 'NORMAL_MODE_WRITER_ANCHOR_PROMPT',
        'NORMAL_MODE_REASONING_PERSPECTIVE_GUARD_PROMPT', 'NORMAL_MODE_OUTPUT_STYLE_PROMPT',
    },
    'interaction_modes.py': {'ROUTING', 'INSTANT_MESSAGING', 'VIRTUAL_ROLEPLAY'},
    'normal_plain_text.py': {'NORMAL_CHAT_EXPRESSION_PROMPT'},
    'normal_policy.py': {'NORMAL_POLICY_DEFAULT', 'PLANNER_POLICY_RUNTIME_APPEND'},
    'normal_speaker_impl/speaker_selection.py': {'USER_SPEAKER_INTENT_SYSTEM'},
    'reply_expression_skill.py': {
        'DIRECT_CHARACTER_RULES', 'NATURAL_CHARACTER_STYLE', 'IMAGE_RESPONSE_STYLE',
        'TURN_EXPRESSION_REVIEW',
    },
    'smart_router.py': {'SMART_ROUTER_CLASSIFIER_SYSTEM', 'SMART_ROUTER_SEARCH_SYSTEM'},
    'web_image_style.py': {'PONY_IMAGE_POLICY'},
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
