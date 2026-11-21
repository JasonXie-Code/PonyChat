"""Shortcut target validation must not confuse human-user anatomy with the pony."""
from copy import deepcopy
import pytest
from Backend.chat_modules.autonomous_shortcuts import ShortcutContract


@pytest.mark.parametrize('target,kind', [('心理活动','thought'),('身体状态','body_state'),('看到的画面','visual')])
def test_target_kind_and_user_body_are_independent(target, kind):
    contract = ShortcutContract([{'role':'user','content':('（请详细写出当前你看到的画面）' if kind == 'visual' else f'（请详细写出当前你的{target}）')}],
        '种族：独角兽', speaker='pony', main='pony')
    envelope = {'bubble_count':3, 'bubbles':[{'parts':[{'kind':kind,'text':'我注意到你的手指翻过书页'}]} for _ in range(3)],
                'voice_reply':{'enabled':False}, 'reply_language':{'language':'Chinese'}}
    assert contract.error(envelope) == ''
    wrong = deepcopy(envelope)
    wrong['bubbles'][0]['parts'][0]['kind'] = 'action'
    assert kind in contract.error(wrong)
