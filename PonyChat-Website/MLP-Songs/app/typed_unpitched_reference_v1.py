"""Independent typed-unpitched preparation contract; not a normal-gate bypass.

Pitched sync events and readonly physical unpitched symbols are separate domains.
Only an exact Root source/common-clock review can add sourceReadingTime references.
The existing ensemble validator, four gates and production dispatch stay unchanged.
"""
import copy
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import sys

try:
    from . import typed_unpitched_physical_audit_v1 as physical
    from .typed_unpitched_source_events_v1 import read_source
except ImportError:
    import typed_unpitched_physical_audit_v1 as physical
    from typed_unpitched_source_events_v1 import read_source

PROFILE = 'typed-unpitched-common-source-reading-reference/v1'
DECISION = 'root-typed-unpitched-shared-quarter-decision/v1'
_TOKEN = object()


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def same(left, right):
    return physical.encoded(left) == physical.encoded(right)


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def no_gold(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key.endswith('Gold'):
                require(item is False, 'Source reference cannot claim performance Gold')
            no_gold(item)
    elif isinstance(value, list):
        for item in value:
            no_gold(item)


def inputs(canonical, notation_raw):
    require(type(canonical) is bytes and type(notation_raw) is bytes, 'Original source bytes required')
    projection = physical.projection(canonical)
    notation = json.loads(notation_raw)
    require(notation.get('canonicalSha256') == sha(canonical), 'Notation canonical differs')
    rows = {r['sourceNoteId']: r for r in projection['physicalEvents']}
    tokens = notation.get('tokens', [])
    by_id = {t.get('originalSourceNoteId'): t for t in tokens}
    require(len(tokens) == len(by_id) == len(rows) and set(by_id) == set(rows), 'Complete physical source required')
    nested = [t for m in notation.get('measures', []) for t in m.get('tokens', [])]
    require(len(nested) == len(tokens) and len({t['id'] for t in nested}) == len(tokens)
            and all(same(t, by_id[t['originalSourceNoteId']]) for t in nested), 'Flat/nested source changed')
    unpitched = []
    for sid, row in rows.items():
        token = by_id[sid]
        require(token.get('id') == token.get('sourcePhysicalId') == sid
                and token.get('isRest') is row['isRest'] and token.get('isUnpitched') is row['isUnpitched'],
                'Physical source identity/type changed')
        expected = ('sourcePart', 'sourceQuarter', 'durationBeats', 'pitch', 'voice', 'staff', 'chordTone',
                    'noteType', 'dots', 'syllabic', 'lyricExtend', 'slurs')
        require(same([token.get(k) for k in expected], [row[k] for k in expected])
                and same([token.get('measure'), token.get('beat'), token.get('lyric')],
                         [row['measure'], row['beatInMeasure'], row['sourceLyric']]), 'Source musical/literal payload changed')
        for key, kind in (('tieStart', 'start'), ('tieStop', 'stop')):
            require(token.get(key) is any(t['type'] == kind for t in row['ties']), 'Source tie changed')
        no_gold(token)
        if row['sourceKind'] != 'pitch':
            require(all(token.get(k) is None for k in ('pitch', 'sourcePitch', 'midi', 'time', 'endTime', 'eventIndex'))
                    and token.get('sourceOnlyUntimed') is True and token.get('skipCursorHighlight') is True
                    and token.get('cursorPrimary') is False and token.get('seekAllowed', False) is False,
                    'Readonly physical entity acquired recording time, pitch, MIDI or seek')
        if row['isUnpitched']:
            require(token.get('token') == '×' and len(row['sourceNotehead']) == 1
                    and row['sourceNotehead'][0]['text'] in ('x', 'circle-x')
                    and same(token.get('sourceNotehead'), row['sourceNotehead'])
                    and same(token.get('sourceUnpitchedDisplay'), row['sourceUnpitchedDisplay']),
                    'Literal x/circle-x or display-only position changed')
            unpitched.append(dict(sourceNoteId=sid, sourcePart=row['sourcePart'], measure=row['measure'],
                sourceQuarter=row['sourceQuarter'], sourceQuarterEnd=row['sourceQuarter'] + row['durationBeats'],
                sourceUtteranceLiteral=row['sourceLyric'], sourceKind='unpitched',
                sourceNotehead=copy.deepcopy(row['sourceNotehead']), sourceUnpitchedDisplay=copy.deepcopy(row['sourceUnpitchedDisplay']),
                time=None, endTime=None, eventIndex=None, pitch=None, midi=None, seekAllowed=False,
                sourceReadingTime=None, sourceReadingEndTime=None, recordingSpeechConfirmed=False,
                noteAttackGold=False, recordingPitchGold=False, physicalGateGold=False,
                status='pending-root-source-and-common-quarter-review'))
    require(unpitched, 'Explicit typed-unpitched profile needs physical unpitched heads')
    return dict(profile=PROFILE, canonicalSha256=sha(canonical), notationSha256=sha(notation_raw),
        projection=projection, counts=projection['counts'], unpitchedReferences=unpitched,
        sourceOnlyPrepared=True, normalAdmissionValidated=False, formalAccepted=False)


def bound(digest, resolver):
    require(physical.is_sha(digest), 'Exact bound SHA required')
    raw = resolver(digest)
    require(type(raw) is bytes and sha(raw) == digest, 'Bound original bytes changed')
    return json.loads(raw)


@dataclass(frozen=True)
class ValidatedUnpitchedReference:
    _token: object
    canonicalSha256: str
    notationSha256: str
    rootDecisionSha256: str
    referenceJSON: str
    normalAdmissionValidated: bool = False


def validate_root_references(canonical, notation_raw, root_decision_sha, resolver):
    prepared = inputs(canonical, notation_raw)
    decision = bound(root_decision_sha, resolver)
    require(decision.get('schema') == DECISION and decision.get('status') == 'root-reviewed-qualified-unpitched-source-reading'
            and decision.get('approved') is True and decision.get('reviewedBy') == '/root'
            and decision.get('scope') == 'unpitched-shared-source-quarter-reading-only', 'Root reference approval pending')
    require(decision.get('canonicalSha256') == prepared['canonicalSha256']
            and decision.get('notationSha256') == prepared['notationSha256'], 'Root references another source tuple')
    no_gold(decision)
    require(decision.get('normalAdmissionGranted') is False and decision.get('formalAccepted') is False,
            'Partial source-coordinate authority cannot grant normal admission')
    audit = bound(decision['typedSourceAuditSha256'], resolver)
    physical.validate(audit, canonical, canonical_sha256=sha(canonical),
        source_pdf_sha256=decision['sourcePDFsha256'], pitched_notes=prepared['counts']['pitch'])
    clock = bound(decision['commonClockSha256'], resolver)
    sync = bound(decision['pitchedSyncSha256'], resolver)
    audio = decision.get('sourceAudioSha256')
    require(physical.is_sha(audio) and clock.get('canonicalSha256') == sha(canonical)
            and clock.get('sourceAudioSha256') == sync.get('sourceAudioSha256') == audio
            and clock.get('sourceReadingOnly') is True, 'Common clock/recording identity differs')
    no_gold(clock); no_gold(sync)
    source_rows = read_source(canonical)['rows']
    pitched = {r['sourceNoteId']: r for r in source_rows if r['sourceKind'] == 'pitch'}
    events = sync.get('events', [])
    require(len(events) == len(pitched) and len({e.get('originalSourceNoteId') for e in events}) == len(events)
            and {e.get('originalSourceNoteId') for e in events} == set(pitched), 'Pitched sync must retain its own complete source domain')
    for event in events:
        row = pitched[event['originalSourceNoteId']]
        require(event.get('pitch') == row['pitch'] and event.get('isUnpitched', False) is False
                and finite(event.get('sourceQuarter')) and finite(event.get('noteDuration')) and finite(event.get('time'))
                and event.get('partId') == row['sourcePart'] and event.get('sourceQuarter') == row['sourceQuarter']
                and event.get('noteDuration') == row['durationBeats'] and event.get('recordingPitchUnconfirmed') is True
                and event.get('noteAttackGold') is False,
                'Speech cannot become a pitched sync event')
    nodes = clock.get('clock', [])
    require(type(nodes) is list and nodes and all(finite(n.get('sourceQuarter')) and finite(n.get('time')) for n in nodes)
            and all(b['sourceQuarter'] > a['sourceQuarter'] and b['time'] > a['time'] for a, b in zip(nodes, nodes[1:])),
            'Explicit reviewed common clock is invalid or collapsed')
    by_q = {n['sourceQuarter']: n for n in nodes}
    require(all(e['sourceQuarter'] in by_q and e.get('time') == by_q[e['sourceQuarter']]['time'] for e in events),
            'Pitched and unpitched coordinates must share one reviewed quarter clock')
    refs = decision.get('references', [])
    expected = {r['sourceNoteId']: r for r in prepared['unpitchedReferences']}
    require(len(refs) == len(expected) and len({r['sourceNoteId'] for r in refs}) == len(refs)
            and {r['sourceNoteId'] for r in refs} == set(expected), 'Every unpitched reference needs an exact Root review')
    actual = []
    for reference in refs:
        original = expected[reference['sourceNoteId']]
        allowed = {'sourceNoteId', 'sourcePart', 'measure', 'sourceQuarter', 'sourceQuarterEnd',
            'sourceUtteranceLiteral', 'sourceReadingTime', 'sourceReadingEndTime', 'qualification',
            'recordingSpeechConfirmed', 'individualSingerConfirmed', 'noteAttackGold',
            'recordingPitchGold', 'physicalGateGold', 'actualWindowEvidenceSha256'}
        require(set(reference) == allowed and all(reference[k] is False for k in
            ('noteAttackGold', 'recordingPitchGold', 'physicalGateGold')), 'Unpitched reference acquired undeclared pitch/time or Gold fields')
        require(all(same(reference.get(k), original[k]) for k in ('sourceNoteId', 'sourcePart', 'measure',
                    'sourceQuarter', 'sourceQuarterEnd', 'sourceUtteranceLiteral')), 'Unpitched source reference changed')
        q0, q1 = original['sourceQuarter'], original['sourceQuarterEnd']
        require(q0 in by_q and q1 in by_q and reference.get('sourceReadingTime') == by_q[q0]['time']
                and reference.get('sourceReadingEndTime') == by_q[q1]['time'], 'Reference is not an exact shared clock coordinate')
        require(finite(sync.get('duration')) and finite(reference.get('sourceReadingTime'))
                and finite(reference.get('sourceReadingEndTime'))
                and 0 <= reference['sourceReadingTime'] < reference['sourceReadingEndTime'] <= sync['duration'],
                'Source reading reference interval is invalid')
        require(reference.get('qualification') == 'qualified-common-quarter-source-reference-not-isolated-speech-onset'
                and reference.get('recordingSpeechConfirmed') is False and reference.get('individualSingerConfirmed') is False,
                'Source-coordinate reference became a confirmed spoken performance')
        no_gold(reference)
        measured = bound(reference['actualWindowEvidenceSha256'], resolver)
        window = measured.get('analysisWindow', [])
        rms = measured.get('rmsWindows', [])
        require(measured.get('sourceNoteId') == original['sourceNoteId'] and measured.get('sourceAudioSha256') == audio
                and type(measured.get('sampleCount')) is int and measured['sampleCount'] > 0
                and type(measured.get('sampleRate')) is int and measured['sampleRate'] > 0
                and len(window) == 2 and all(finite(v) for v in window) and window[1] > window[0]
                and abs(measured['sampleCount'] - (window[1]-window[0])*measured['sampleRate']) <= 1.001
                and window[0] <= reference['sourceReadingTime'] < reference['sourceReadingEndTime'] <= window[1],
                'Actual unpitched window sample/identity evidence missing')
        require(type(rms) is list and rms and all(finite(r.get('time')) and finite(r.get('rms')) and r['rms'] >= 0
                and window[0] <= r['time'] <= window[1] for r in rms), 'Actual sample RMS rows required')
        no_gold(measured)
        actual.append({**original, **copy.deepcopy(reference), 'time': None, 'endTime': None, 'eventIndex': None,
                       'pitch': None, 'midi': None, 'seekAllowed': False, 'status': 'reviewed-qualified-source-coordinate'})
    return ValidatedUnpitchedReference(_TOKEN, sha(canonical), sha(notation_raw), root_decision_sha,
                                      physical.encoded(actual).decode())
