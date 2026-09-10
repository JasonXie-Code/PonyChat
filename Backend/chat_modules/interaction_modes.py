"""Mutually exclusive, Agent-selected conversation-world skills."""

from .Prompts import (ROUTING, INSTANT_MESSAGING, VIRTUAL_ROLEPLAY)
from copy import deepcopy

MODES = ('instant_messaging', 'virtual_roleplay')
FIELD = 'interaction_mode'



CATALOG = {
    'instant_messaging': ('即时通讯软件式聊天，用户谈现实生活；不自动代表恋爱关系。', INSTANT_MESSAGING),
    'virtual_roleplay': ('双方参与共同想象场景，场景内可行动、递物和使用角色能力。', VIRTUAL_ROLEPLAY),
}


def previous_mode(data):
    value = ((data.get('current_scene') or {}).get('fields') or {}).get(FIELD, {}).get('value')
    return value if value in MODES else 'instant_messaging'


def attach_mode(result, mode):
    """Persist selection through the existing successful-reply transaction."""
    result['interaction_mode'] = mode
    if mode in MODES and result.get('scene_patch') is not None:
        result['scene_patch']['changes'][FIELD] = {'value': mode, 'source_message_ids': ['$reply']}


def scope_memory(arguments, mode):
    scoped = deepcopy(arguments)
    if mode == 'virtual_roleplay':
        scoped['kind'] = 'current_scene'
        scoped['category'] = 'current_scene'
        text = str(scoped.get('content') or '')
        if not text.startswith('【虚拟扮演】'):
            scoped['content'] = '【虚拟扮演】' + text
    return scoped
