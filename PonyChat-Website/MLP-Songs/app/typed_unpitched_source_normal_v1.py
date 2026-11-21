"""Complete ensemble source conservation and independent, hash-bound authority.

The contract is not tied to a song, number of parts, or voice arrangement.
Printed rests and technical forwards remain different. Its source-only result
cannot authorize a recording clock, normal UI, public admission, or Gold.
"""
from dataclasses import dataclass
from fractions import Fraction
import hashlib
import json
import math
import re
import weakref
import xml.etree.ElementTree as ET

try:
    from .source_reading_source_v1 import read_source
except ImportError:
    from source_reading_source_v1 import read_source

PROFILE = 'typed-unpitched-common-source-reading-reference/v1'
KIND = 'typed-unpitched-source-runtime-conservation/v1'
_TOKEN = object()
_LIVE = {}


def require(value, message):
    if not value:
        raise ValueError(message)


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(',', ':'), allow_nan=False).encode('utf8')


def same(a, b):
    return encoded(a) == encoded(b)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def strict_json(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            require(key not in value, 'Duplicate evidence JSON key')
            value[key] = item
        return value
    def invalid(value):
        raise ValueError('Nonfinite evidence JSON: ' + value)
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


def bound(digest, hashes, resolve, binary=False):
    require(type(digest) is str and re.fullmatch('[0-9a-f]{64}', digest)
            and digest in hashes, 'Original ensemble evidence is not bound')
    raw = resolve(digest, raw_bytes=True)
    require(type(raw) is bytes and sha(raw) == digest, 'Original ensemble evidence bytes changed')
    return raw if binary else strict_json(raw)


def projection(canonical):
    source = read_source(canonical)
    root = ET.fromstring(canonical)
    nodes = {node.get('id'): node for node in root.findall('part/measure/note')}
    def payload(node):
        return None if node is None else dict(tag=node.tag, attributes=dict(node.attrib),
            text=node.text, tail=node.tail, children=[payload(child) for child in node])
    for row in source['rows']:
        node = nodes[row['sourcePhysicalId']]
        row.update(sourceNoteAttributes=dict(node.attrib), sourceLyrics=[payload(n) for n in node.findall('lyric')],
            sourceNotehead=[payload(n) for n in node.findall('notehead')],
            sourceUnpitchedDisplay=payload(node.find('unpitched')), sourceRestPayload=payload(node.find('rest')),
            sourceTimeModification=payload(node.find('time-modification')),
            sourceBeams=[payload(n) for n in node.findall('beam')],
            sourceNotations=[payload(n) for n in node.findall('notations')])
    measures = {(part.get('id'), int(measure.get('number'))): measure
                for part in root.findall('part') for measure in part.findall('measure')}
    for gap in source['sourceGaps']:
        node = list(measures[(gap['sourcePart'], gap['measure'])])[gap['sourceNoteIndex']]
        gap.update(sourceNodeKind='forward', sourceForwardPayload=payload(node))
    return dict(schema='typed-physical-source-projection/v1', sourceParserSchema=source['schema'],
        physicalEvents=source['rows'], unprintedSourceGaps=source['sourceGaps'],
        counts=source['counts'], physicalEventCount=len(source['rows']),
        unprintedForwardCount=len(source['sourceGaps']), sourceApproved=False, recordingSchedule=False)


def source_descriptor(canonical):
    root = ET.fromstring(canonical)
    p = projection(canonical)
    return dict(physicalCounts=dict(physical=p['physicalEventCount'], **p['counts'],
        unprintedForwards=p['unprintedForwardCount'],
        primary=len({r['sourceQuarter'] for r in p['physicalEvents'] if r['sourceKind'] == 'pitch'})),
        sourceParts=[dict(id=e.get('id'), name=e.findtext('part-name'))
                     for e in root.findall('part-list/score-part')],
        partMeasures=len(root.findall('part/measure')))


def pitch_midi(label):
    match = re.fullmatch(r'([A-G])([#b]*)(-?\d+)', label)
    require(match is not None, 'Original spelled pitch required')
    return ((int(match[3]) + 1) * 12 + dict(C=0, D=2, E=4, F=5, G=7, A=9, B=11)[match[1]]
            + match[2].count('#') - match[2].count('b'))


def number_projection(pitch, tonic, reference_octave):
    p = re.fullmatch(r'([A-G])([#b]*)(-?\d+)', pitch)
    t = re.fullmatch(r'([A-G])([#b]*)', tonic)
    require(p is not None and t is not None and type(reference_octave) is int,
            'Explicit local tonic and common reference octave required')
    letters = 'CDEFGAB'
    degree = (letters.index(p[1]) - letters.index(t[1])) % 7
    tonic_midi = pitch_midi(tonic + str(reference_octave))
    base_octave = int(p[3]) - reference_octave - (letters.index(p[1]) < letters.index(t[1]))
    expected_midi = tonic_midi + base_octave * 12 + (0, 2, 4, 5, 7, 9, 11)[degree]
    alter = pitch_midi(pitch) - expected_midi
    require(-2 <= alter <= 2, 'Explicit tonic interpretation required for unusual alteration')
    accidental = '♯' * max(alter, 0) + '♭' * max(-alter, 0)
    return [pitch_midi(pitch), degree + 1, base_octave, accidental, accidental + str(degree + 1)]


def no_gold(value):
    if type(value) is dict:
        require(all(v is False for k,v in value.items() if k.endswith('Gold'))
            and value.get('physicalGateEndTime') is None and value.get('physicalGateEndConfirmed',False) is False
            and all(value.get(k,False) is False for k in ('fixture','synthetic','mock','harnessGenerated')),
            'Source-reading evidence cannot claim Gold or invented fixture observations')
        for child in value.values(): no_gold(child)
    elif type(value) is list:
        for child in value: no_gold(child)


def validate_structure(canonical, sync_raw, notation_raw, expected=None):
    """Fresh full XML projection, including lower voices, marks and forwards."""
    require(all(type(v) is bytes for v in (canonical, sync_raw, notation_raw)), 'Actual original bytes required')
    sync, notation = strict_json(sync_raw), strict_json(notation_raw)
    root = ET.fromstring(canonical)
    original = projection(canonical)
    descriptor = source_descriptor(canonical)
    if expected is not None:
        require(same(descriptor, expected), 'Actual complete ensemble denominator or original part names changed')
    rows = {r['sourcePhysicalId']: r for r in original['physicalEvents']}
    require(len(rows) == len(original['physicalEvents']) and original['counts']['unpitched'] > 0,
            'Explicit positive typed-unpitched physical source domain required')
    for body in (sync, notation):
        require(body.get('canonicalSha256') == sha(canonical)
                and same(body.get('sourceParts'), descriptor['sourceParts']), 'Source/runtime canonical or parts differ')
        require(body.get('primaryPart') is None, 'A shared ensemble cue cannot select one melody part')
    require(sync.get('songId') == notation.get('songId')
            and sync.get('sourceSongId') == notation.get('sourceSongId'), 'Recording identities differ')
    gap_keys = ('sourcePart', 'measure', 'beatInMeasure', 'sourceQuarter', 'durationBeats', 'sourceNoteIndex', 'isSyntheticGap')
    require(same([{k: r[k] for k in gap_keys} for r in notation.get('sourceGaps', [])],
                 [{k: r[k] for k in gap_keys} for r in original['unprintedSourceGaps']]),
            'Technical forwards were dropped, moved, or turned into physical rests')
    tokens = notation.get('tokens')
    require(type(tokens) is list and len(tokens) == len(rows), 'Complete physical notation required')
    token_by = {t.get('id'): t for t in tokens}
    require(len(token_by) == len(rows) and set(token_by) == set(rows), 'Missing, duplicate, or invented notation entity')
    nested = [t for m in notation.get('measures', []) for t in m.get('tokens', [])]
    require(len(nested) == len(tokens) and len({t['id'] for t in nested}) == len(tokens)
            and all(same(t, token_by[t['id']]) for t in nested), 'Flat and nested full notation differ')
    nodes = {n.get('id'): n for n in root.findall('part/measure/note')}
    reference_octave = 4 - notation.get('notation_octave_shift', 0)
    require(type(notation.get('notation_octave_shift')) is int
            and notation.get('commonOctaveShiftAcrossAllParts') is True, 'One real common octave plan required')
    for sid, row in rows.items():
        token = token_by[sid]
        keys = ('sourcePart', 'sourceQuarter', 'durationBeats', 'pitch', 'voice', 'staff',
                'chordTone', 'noteType', 'dots', 'syllabic', 'lyricExtend', 'slurs')
        require(token.get('sourcePhysicalId') == token.get('originalSourceNoteId') == sid
                and same([token.get(k) for k in keys], [row[k] for k in keys])
                and token.get('lyric') == (row['sourceLyric'])
                and same([token.get('measure'), token.get('beat')], [row['measure'], row['beatInMeasure']]),
                'Physical source voice/pitch/rhythm/lyric/connection tuple changed')
        require(token.get('isRest') is row['isRest'] and token.get('isUnpitched') is row['isUnpitched']
                and token.get('readingOnly') is True, 'Physical source kind or reading scope changed')
        for flag, tie_type in (('tieStart', 'start'), ('tieStop', 'stop')):
            require(token.get(flag) is any(t['type'] == tie_type for t in row['ties']), 'Printed tie changed')
        no_gold(token)
        if row['isRest']:
            require(all(token.get(k) is None for k in ('time', 'endTime', 'eventIndex', 'midi', 'pitch'))
                    and token.get('sourceOnlyUntimed') is True and token.get('skipCursorHighlight') is True
                    and token.get('seekAllowed', False) is False and token.get('cursorPrimary') is False,
                    'Printed rest became timed, seekable, or an automatic cursor')
        elif row['isUnpitched']:
            require(all(token.get(k) is None for k in ('pitch','sourcePitch','soundingPitch','midi','time','endTime','eventIndex'))
                and token.get('isRest') is False and token.get('isUnpitched') is True
                and token.get('seekAllowed') is False and token.get('cursorPrimary') is False
                and token.get('sourceOnlyUntimed') is True and token.get('skipCursorHighlight') is True,
                'Typed X acquired pitch/MIDI/recording time/seek or became a rest')
            require(same(token.get('sourceNotehead'), row['sourceNotehead'])
                and same(token.get('sourceUnpitchedDisplay'), row['sourceUnpitchedDisplay'])
                and len(row['sourceNotehead']) == 1 and row['sourceNotehead'][0]['text'] in ('x','circle-x')
                and token.get('noteheadShape') == row['sourceNotehead'][0]['text'] and token.get('token') == '×',
                'Literal X/circle-X or display-only position changed')
        else:
            # Degree and octave are relative to the declared local tonic. A key
            # change must redeclare it rather than accumulating accidentals.
            tonic = token.get('localTonic', notation.get('tonic'))
            expected_number = number_projection(row['pitch'], tonic, reference_octave)
            require(same([token.get(k) for k in ('midi', 'degree', 'octave', 'accidental', 'token')], expected_number),
                    'Jianpu pitch/local tonic/common octave differs from canonical source')
            notehead = nodes[sid].find('notehead')
            require(token.get('parentheses', False) is (notehead is not None and notehead.get('parentheses') == 'yes'),
                    'Physical notehead parentheses changed')
    pitched = {sid: r for sid, r in rows.items() if r['sourceKind'] == 'pitch'}
    events = sync.get('events')
    require(type(events) is list and len(events) == len(pitched)
            and len({e['sourcePhysicalId'] for e in events}) == len(pitched)
            and {e['sourcePhysicalId'] for e in events} == set(pitched), 'Every original pitched head required')
    groups = {}
    require(finite(sync.get('duration')) and sync['duration'] > 0, 'Actual recording duration required')
    for index, event in enumerate(events):
        sid = event['sourcePhysicalId']; row = pitched[sid]; token = token_by[sid]
        require(type(event.get('eventIndex')) is int and event['eventIndex'] == index
                and event.get('originalSourceNoteId') == sid and event.get('isRest') is False,
                'Actual physical event/index identity differs')
        ek = ('partId', 'sourceQuarter', 'beatInMeasure', 'noteDuration', 'pitch', 'sourceVoice', 'chordTone', 'sourceLyric')
        rk = ('sourcePart', 'sourceQuarter', 'beatInMeasure', 'durationBeats', 'pitch', 'voice', 'chordTone', 'sourceLyric')
        expected_event = [row[k] for k in rk]
        expected_event[-1] = row['sourceLyric']
        require(same([event.get(k) for k in ek], expected_event)
                and Fraction(str(event['sourceQuarterEnd'])) == Fraction(str(row['sourceQuarter'])) + Fraction(str(row['durationBeats']))
                and event.get('tieContinuation') is any(t['type'] == 'stop' for t in row['ties']),
                'Actual pitched reference source semantics changed')
        no_gold(event)
        require(event.get('readingOnly') is True and event.get('recordingPitchUnconfirmed') is True
                and event.get('recordingLyricUnconfirmed',True) is True and type(event.get('cursorPrimary')) is bool
                and finite(event.get('time')) and finite(event.get('endTime'))
                and 0 <= event['time'] < event['endTime'] <= sync['duration'], 'Invalid reading clock or reading scope')
        require(same([token.get(k) for k in ('time', 'endTime', 'eventIndex', 'cursorPrimary')],
                     [event[k] for k in ('time', 'endTime', 'eventIndex', 'cursorPrimary')]), 'Notation/event clock differs')
        groups.setdefault(row['sourceQuarter'], []).append(event)
    representatives = []
    for quarter, group in sorted(groups.items()):
        require(len({e['time'] for e in group}) == 1, 'Same source quarter has disagreeing voice clocks')
        primary = [e for e in group if e['cursorPrimary']]
        require(len(primary) == 1, 'One actual representative per shared pitched quarter required')
        e = primary[0]
        representatives.append(dict(sourceQuarter=quarter, time=e['time'], eventIndex=e['eventIndex'],
                                    sourcePhysicalId=e['sourcePhysicalId'], sourcePart=e['partId']))
    require(all(b['time'] > a['time'] for a, b in zip(representatives, representatives[1:])),
            'Distinct shared source quarters collapsed or moved backwards')
    return dict(schema=KIND, canonicalSha256=sha(canonical), syncSha256=sha(sync_raw),
        notationSha256=sha(notation_raw), descriptor=descriptor, projection=original,
        representatives=representatives, readonlyRestIds=[sid for sid, row in rows.items() if row['isRest']],
        readonlyUnpitchedIds=[sid for sid,row in rows.items() if row['isUnpitched']],
        sourceOnlyDataValidated=True, sourceApproved=False, clockApproved=False,
        normalUIApproved=False, formalAccepted=False, physicalPerformanceGold=False)


@dataclass(frozen=True)
class ValidatedEnsembleSource:
    _token: object
    _owner: object
    canonicalSha256: str
    decisionSha256: str
    projectionSha256: str
    descriptorJSON: str
    normalAdmissionValidated: bool = False
    recordingOrPerformanceApproved: bool = False


def validate_source(decision_sha, source_audit, canonical, hashes, resolve):
    """Actual complete typed Source authority; never derives approval from XML."""
    try:
        from . import typed_unpitched_physical_audit_v1 as physical
    except ImportError:
        import typed_unpitched_physical_audit_v1 as physical
    audit = bound(decision_sha, hashes, resolve)
    pdf_sha = audit['sourcePDFsha256']
    physical.validate(audit, canonical, canonical_sha256=sha(canonical),
        source_pdf_sha256=pdf_sha, pitched_notes=projection(canonical)['counts']['pitch'])
    expected_audit = source_audit.get('typedPhysicalSourceAudit', source_audit)
    require(same(expected_audit,audit),'Current typed Source wrapper changed actual Root authority')
    pdf = bound(pdf_sha, hashes, resolve, True)
    require(pdf.startswith(b'%PDF-'),'Actual registered original paper bytes required')
    for digest in audit['rootSourceDecision']['actualSourceReviewEvidenceSha256s']:
        bound(digest,hashes,resolve,True)
    owner = getattr(resolve, '__self__', resolve)
    require(not getattr(owner,'closed',False),'Closed typed Source invocation')
    expected=projection(canonical)
    result=ValidatedEnsembleSource(_TOKEN,owner,sha(canonical),decision_sha,
        sha(encoded(expected)),encoded(source_descriptor(canonical)).decode())
    fingerprint=sha(encoded({k:v for k,v in vars(result).items() if k not in ('_token','_owner')}))
    key=id(result);_LIVE[key]=(weakref.ref(result,lambda ref:_LIVE.pop(key,None)),fingerprint)
    return result


def check_source(result, canonical, resolve):
    owner = getattr(resolve, '__self__', resolve)
    entry = _LIVE.get(id(result))
    require(type(result) is ValidatedEnsembleSource and result._token is _TOKEN
            and entry is not None and entry[0]() is result and result._owner is owner
            and entry[1] == sha(encoded({k: v for k, v in vars(result).items() if k not in ('_token', '_owner')}))
            and not getattr(owner, 'closed', False) and result.canonicalSha256 == sha(canonical)
            and result.projectionSha256 == sha(encoded(projection(canonical)))
            and result.normalAdmissionValidated is False and result.recordingOrPerformanceApproved is False,
            'Ensemble source type is invented, borrowed, closed, or stale')
    return True
