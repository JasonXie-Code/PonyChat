"""Resident participant and event-state rules for the normal-chat Agent."""

from copy import deepcopy




def participant_context(user_background):
    """Copy only the public-to-Agent profile produced by build_user_context.

    Never read raw settings here: share_with_ai was already applied upstream.
    A fresh object per turn prevents guest speakers/users leaking into each other.
    """
    allowed = ('display_name', 'gender', 'species', 'age', 'birthday', 'bio', 'personal_setting')
    background = user_background if isinstance(user_background, dict) else {}
    return {
        'character': {'role': 'assistant', 'profile_ref': 'character_profile', 'reply_pronoun': '我'},
        'user': {'role': 'user', 'reply_pronoun': '你', 'profile_source': 'shared_user_profile',
                 'profile': {key: deepcopy(background[key]) for key in allowed if key in background}},
    }
