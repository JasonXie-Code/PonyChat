import json
import pytest
from Backend.chat_modules.local_state_contract import add_local_state_contract
from Backend.chat_modules.autonomous_scene_state import FIELDS, validate_patch


def test_local_contract_preserves_scene_validation_and_evidence():
    prompt = {'allowed_source_ids': ['user-1', 'reply-1']}
    messages = [{'message_id': 'user-1', 'timestamp': 1791019917933}]
    add_local_state_contract(prompt, messages, [], {'fields': {}})
    schema = prompt['output_json_schema']['properties']
    changes = schema['scene_patch']['properties']['changes']
    assert changes['type'] == 'object'
    assert set(changes['required']) == FIELDS
    assert changes['additionalProperties']['properties']['source_message_ids']['items']['enum'] == ['user-1', 'reply-1']
    assert 'user-1' in prompt['source_message_times']
    assert schema['memories']['items']['properties']['occurred_at']['type'] == ['string', 'null']
    json.dumps(prompt)
    with pytest.raises(ValueError):
        validate_patch({'reset': False, 'changes': []}, {'user-1'}, initial=True)
    patch = {'reset': False, 'changes': {field: {'value': None, 'source_message_ids': ['user-1']} for field in FIELDS}}
    assert validate_patch(patch, {'user-1'}, initial=True) == patch


def test_existing_scene_does_not_require_reinitialization():
    prompt = {'allowed_source_ids': ['user-1']}
    add_local_state_contract(prompt, [], [], {'fields': {'location': {'value': '书店'}}})
    assert 'required' not in prompt['output_json_schema']['properties']['scene_patch']['properties']['changes']
