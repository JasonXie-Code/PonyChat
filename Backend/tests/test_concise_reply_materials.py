import importlib.util
import json
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location('tested_concise_materials',
    Path(__file__).parents[1] / 'Agent-Test' / 'concise_reply_materials.py')
materials = importlib.util.module_from_spec(spec)
spec.loader.exec_module(materials)


def text_task():
    return {'interaction_context': {'selected_this_turn': 'instant_messaging'},
            'latest_user_message': {'content': '会紧张吗？'}, 'current_scene': {'fields': {}},
            'recent_raw_messages': [{'role': 'assistant', 'content': '完整原文保留'}],
            'character_profile': '完整角色资料',
            'server_loaded_core_manuals': [{'skill': name, 'instructions': 'full ' + name} for name in (
                'delivery', 'continuity', 'followup', 'character_body', 'reply_expression', 'evidence', 'reply_language', 'voice_reply')]}


def result(patch=None):
    value = {'bubbles': [{'parts': [{'kind': 'speech', 'text': '原句保留'}]}],
             'used_facts': ['原始事实'], 'followup_decision': {'enabled': False}}
    if patch is not None:
        value['scene_patch'] = patch
    return {'finish_reason': 'completed', 'final_response': json.dumps(value, ensure_ascii=False)}


def test_material_view_preserves_profile_history_and_protected_instructions():
    task = text_task()
    before = json.loads(json.dumps(task))
    materials.apply_material_view(task)
    assert task['character_profile'] == before['character_profile']
    assert task['recent_raw_messages'] == before['recent_raw_messages']
    assert task['latest_user_message'] == before['latest_user_message']
    for old, new in zip(before['server_loaded_core_manuals'], task['server_loaded_core_manuals']):
        if old['skill'] not in materials.SUMMARIES:
            assert new == old


@pytest.mark.parametrize('change', ['virtual_roleplay', 'image', 'known_state', 'media_request'])
def test_out_of_scope_requests_keep_full_materials(change):
    task = text_task()
    if change == 'virtual_roleplay': task['interaction_context']['selected_this_turn'] = change
    if change == 'image': task['current_images_available'] = True
    if change == 'known_state': task['current_scene']['fields'] = {'location': {'value': '已知位置'}}
    if change == 'media_request': task['latest_user_message']['content'] = '发送语音'
    before = json.loads(json.dumps(task))
    materials.apply_material_view(task)
    assert task == before


def test_initialization_fills_only_unknowns_and_preserves_parts_and_business_decisions():
    original = result({'reset': False, 'changes': {'location': {'value': '角色实际明确的位置', 'source_message_ids': ['$reply']}}})
    normalized = materials.initialize_unknown_text_scene(original, text_task(), 'instant_messaging')
    before, after = json.loads(original['final_response']), json.loads(normalized['final_response'])
    assert before['bubbles'] == after['bubbles'] and before['used_facts'] == after['used_facts']
    assert before['followup_decision'] == after['followup_decision']
    assert after['scene_patch']['changes']['location']['value'] == '角色实际明确的位置'
    for name in materials.FIELDS:
        if name != 'location': assert after['scene_patch']['changes'][name] == {'value': None, 'source_message_ids': ['$reply']}
    assert normalized['server_scene_initialization']['model_calls'] == 0


def test_existing_scene_invalid_patch_virtual_and_silence_remain_unchanged():
    task = text_task(); task['current_scene']['fields'] = {'location': {'value': '已有'}}
    original = result()
    assert materials.initialize_unknown_text_scene(original, task, 'instant_messaging') is original
    for patch in ({'reset': True, 'changes': {}}, {'reset': False, 'changes': 'wrong'}):
        original = result(patch)
        assert materials.initialize_unknown_text_scene(original, text_task(), 'instant_messaging') is original
    original = result()
    assert materials.initialize_unknown_text_scene(original, text_task(), 'virtual_roleplay') is original
    for alteration in ({'current_images_available': True},
                       {'latest_user_message': {'content': '这是共同场景'}},
                       {'latest_user_message': {'content': '发送语音'}}):
        assert materials.initialize_unknown_text_scene(original, {**text_task(), **alteration}, 'instant_messaging') is original
    original = {'finish_reason': 'completed', 'final_response': '{"bubbles":[]}'}
    assert materials.initialize_unknown_text_scene(original, text_task(), 'instant_messaging') is original
