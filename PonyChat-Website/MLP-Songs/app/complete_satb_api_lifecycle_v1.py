"""Ordinary API lifecycle from the actual registered normal sealed graph only.

The original sync has no accepted field. Its exact musical body remains frozen;
only the API copy adds a boolean accepted lifecycle value after full admission.
"""
import copy
import json
from pathlib import Path

try:
    from . import sealed_source_reading_v1 as sealed
    from . import sealed_complete_satb_reading_v1 as satb
except ImportError:
    import sealed_source_reading_v1 as sealed
    import sealed_complete_satb_reading_v1 as satb

PROFILE = satb.PROFILE


def declared(meta, sync):
    return meta.get('qualifiedReadingProfile') == PROFILE or sync.get('qualifiedReadingProfile') == PROFILE


def response(meta, report, notation, sync, follow, media):
    if not declared(meta, sync): return sync, None
    satb.require(meta.get('qualifiedReadingProfile') == PROFILE and satb.opted(meta, sync),
        'Actual registered complete SATB metadata/profile required')
    result = sealed.checked(meta, report, notation, sync, follow, media)
    satb.require(sealed.valid_type(result, meta['id']), 'Complete normal sealed validation required, never review/accepted markers')
    folder = Path(follow)/'generated'/meta['id']
    raw_sync = (folder/'sync.json').read_bytes(); raw_notation = (folder/'notation.json').read_bytes()
    satb.require(result.syncSha256 == satb.clock.sha(raw_sync) and result.notationSha256 == satb.clock.sha(raw_notation) and
        satb.same(json.loads(raw_sync), sync) and satb.same(json.loads(raw_notation), notation) and
        satb.metadata_lifecycle_matches(json.loads((folder/'candidate.json').read_bytes()), meta) and
        satb.same(json.loads((folder/'report.json').read_bytes()), report),
        'In-memory API bodies must equal the actual current files checked by normal admission')
    satb.require('accepted' not in sync or type(sync['accepted']) is bool, 'Only a boolean API lifecycle is permitted')
    # Rebuild the actual source/clock/normal V6/UI/certificate graph. A copied
    # SealedSourceReading token cannot manufacture this public authority packet.
    authority = satb.public_authority(meta, report, notation, sync, follow, media)
    projected = copy.deepcopy(sync); projected['accepted'] = True
    return projected, authority
