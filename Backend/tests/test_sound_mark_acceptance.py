"""Acceptance must not count failed delivery or exceed the per-turn budget."""
from Backend.scripts.test_normal_sound_mark_acceptance import classify, group_violations, parse_response


def result(reply, *, persisted=True):
    return dict(ok=True, reply=reply, bubbles=reply.splitlines(), persisted=persisted)


def test_per_turn_limit_applies_across_bubbles():
    verdict = classify({'expect': 'present'}, result('好～\n来～\n嗯～'))
    assert not verdict['compliant'] and not verdict['invalid']


def test_two_marks_and_unmarked_daily_reply_are_valid():
    assert classify({'expect': 'present'}, result('好～\n来～'))['compliant']
    assert classify({'expect': 'none'}, result('今天晴天'))['compliant']


def test_daily_marks_are_optional_and_still_bounded():
    assert classify({'expect': 'optional'}, result('好～'))['compliant']
    assert classify({'expect': 'optional'}, result('好'))['compliant']
    assert not classify({'expect': 'optional'}, result('好～\n来～\n嗯～'))['compliant']
    assert not classify({'expect': 'none'}, result('好～'))['compliant']


def test_unsaved_reply_is_invalid_even_with_expected_marks():
    assert classify({'expect': 'present'}, result('好～', persisted=False))['invalid']


def test_paragraphs_take_precedence_over_duplicate_deltas():
    reply, bubbles, no_reply, saved = parse_response({
        'protocol': 'ponychat_chat_v1', 'events': [
            {'choices': [{'delta': {'content': '好～'}}]},
            {'type': 'assistant_paragraph', 'content': '好～'},
            {'type': 'save_status', 'success': True},
        ]})
    assert (reply, bubbles, no_reply, saved) == ('好～', ['好～'], False, True)


def test_empty_success_envelope_is_not_a_valid_reply():
    reply, bubbles, no_reply, saved = parse_response({
        'protocol': 'ponychat_chat_v1', 'events': [{'type': 'done'}]})
    assert classify({'expect': 'none'}, dict(ok=True, reply=reply, bubbles=bubbles,
                                           no_reply=no_reply, persisted=saved))['invalid']


def intimate_cases(counts):
    return [dict(character=name, scene='B_intimate',
                 verdict=dict(tilde_count=count, invalid=False))
            for name in ('碧琪', '紫悦') for count in counts]


def test_intimacy_group_allows_unmarked_turns_but_requires_an_occurrence():
    assert not group_violations(intimate_cases([1, 0, 1]))
    assert len(group_violations(intimate_cases([0, 0, 0]))) == 1


def test_reserved_character_can_omit_marks():
    cases = intimate_cases([1, 0, 1])
    for case in cases:
        if case['character'] == '紫悦':
            case['verdict']['tilde_count'] = 0
    assert not group_violations(cases)


def test_intimacy_group_rejects_marks_in_consecutive_turns():
    assert len(group_violations(intimate_cases([1, 1, 0]))) == 2
