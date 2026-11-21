"""Project the admitted API lifecycle after real sealed-body validation only.

The immutable musical sync stays untouched. Ordinary and Smile payloads use
their original response; no accepted JSON marker can enter this projection.
"""
import copy
from pathlib import Path

import sealed_source_reading_v1 as sealed
from follow_acceptance import file_sha256

PROFILE = 'one-more-day-complete-quarter-typed-source-reference/v1'
FOLLOW_ID = 'one-more-day-59bdb131'
SYNC_SHA = '9ea0606509ac544780c810c0738b2cb93887e4f1d7780892d5af6eedd216793f'
NOTATION_SHA = '456770d1819318e21ffc4118e51eab25fcecd0026ddd85013110264e3d7ab82a'


def response_sync(meta, report, notation, sync, follow, media):
    if meta.get('id') != FOLLOW_ID and meta.get('qualifiedReadingProfile') != PROFILE \
            and sync.get('qualifiedReadingProfile') != PROFILE:
        return sync
    sealed.require(meta.get('id') == FOLLOW_ID and
        meta.get('qualifiedReadingProfile') == sync.get('qualifiedReadingProfile') == PROFILE,
        'Complete API lifecycle requires the exact current recording and profile')
    result = sealed.checked(meta, report, notation, sync, follow, media)
    sealed.require(sealed.valid_type(result, FOLLOW_ID),
        'Complete API lifecycle requires actual sealed validation, not an accepted marker')
    folder = Path(follow) / 'generated' / FOLLOW_ID
    sealed.require(result.syncSha256 == SYNC_SHA == file_sha256(folder / 'sync.json') and
        result.notationSha256 == NOTATION_SHA == file_sha256(folder / 'notation.json') and
        type(sync.get('accepted')) is bool and sync['accepted'] is False,
        'Complete API lifecycle cannot relabel different or projected original musical bytes')
    projected = copy.deepcopy(sync)
    projected['accepted'] = True
    return projected
