"""Mutually exclusive, Agent-selected conversation-world skills."""
from .Prompts import INTERACTION_MODES_TEXT

from .Prompts import (instant_messaging, virtual_roleplay)
from copy import deepcopy

MODES = ('instant_messaging', 'virtual_roleplay')
FIELD = 'interaction_mode'



CATALOG = {
    'instant_messaging': (INTERACTION_MODES_TEXT['CATALOG_1'], instant_messaging),
    'virtual_roleplay': (INTERACTION_MODES_TEXT['CATALOG_2'], virtual_roleplay),
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
    return scoped
