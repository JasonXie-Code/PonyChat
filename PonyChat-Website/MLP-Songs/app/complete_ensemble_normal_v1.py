"""Typed normal ensemble reference authority over original evidence bodies.

Source, common clock, recording edition and actual native UI have separate
Root decisions. Private/source-only tickets never authorize normal admission.
The complete original source denominator is derived, never a SATB alias.
"""
from dataclasses import dataclass
import copy
import json
from pathlib import Path
import weakref
from urllib.parse import unquote, urlparse

try:
    from .audio_registration_snapshot_v1 import registration_catalog, snapshot_validation
except ImportError:
    from audio_registration_snapshot_v1 import registration_catalog, snapshot_validation

try:
    from . import complete_ensemble_reference_v1 as source
except ImportError:
    import complete_ensemble_reference_v1 as source

PROFILE = source.PROFILE
KIND = 'typed-complete-ensemble-normal-reference-context/v1'
UI_KIND = 'typed-complete-ensemble-normal-ui-capability/v1'
REFS = ('versionAuditSha256', 'rootV6DecisionSha256', 'originalProposalSha256', 'originalIndexSha256',
        'sourceAuditSha256', 'sourceDecisionSha256', 'clockDecisionSha256', 'actualGeometryEvidenceSha256')
UI_REFS = (*REFS, 'rootNormalUIDecisionSha256', 'browserAuditSha256', 'performanceMapSha256')
IDENTITY = ('followId', 'sourceSongId', 'sourceScoreId', 'sourcePDFsha', 'canonicalSha256',
            'sourceAudioSha256', 'syncSha256', 'notationSha256')
SCOPES = {(1280, 'staff'), (1280, 'jianpu'), (375, 'staff'), (375, 'jianpu')}
require, same, bound = source.require, source.same, source.bound
_TOKEN = object()
_LIVE = {}


def opted(candidate, review=None):
    result = candidate.get('qualifiedReadingProfile') == PROFILE
    if review is not None and review.get('qualifiedReadingProfile') == PROFILE:
        require(result, 'Version/candidate explicit ensemble profile differs')
    if result and review is not None:
        require(review.get('qualifiedReadingProfile') == PROFILE, 'Candidate/version explicit ensemble profile differs')
    return result


def identity(candidate, canonical, sync_raw, notation_raw):
    sync = source.strict_json(sync_raw); notation = source.strict_json(notation_raw)
    require(candidate.get('id') == sync.get('songId') == notation.get('songId')
            and candidate.get('sourceSongId') == sync.get('sourceSongId') == notation.get('sourceSongId')
            and candidate.get('sourceScoreId') == sync.get('sourceScoreId')
            and candidate.get('canonicalSha256') == sync.get('canonicalSha256') == notation.get('canonicalSha256') == source.sha(canonical)
            and candidate.get('sourceAudioSha256') == sync.get('sourceAudioSha256'), 'Current original ensemble identities differ')
    return dict(followId=candidate['id'], sourceSongId=candidate['sourceSongId'],
        sourceScoreId=candidate['sourceScoreId'], sourcePDFsha=candidate['sourcePDFsha256'],
        canonicalSha256=source.sha(canonical), sourceAudioSha256=candidate['sourceAudioSha256'],
        syncSha256=source.sha(sync_raw), notationSha256=source.sha(notation_raw))


def whole_clock(sync, structural):
    clock = sync['qualifiedCommonSourceReadingClock']
    nodes = clock.get('clock')
    reps = structural['representatives']
    require(type(nodes) is list and len(nodes) == len(reps) + 1,
            'Every shared pitched source quarter plus actual music terminal required')
    for row, representative in zip(nodes[:-1], reps):
        expected_ids = [e['sourcePhysicalId'] for e in sync['events']
                        if e['sourceQuarter'] == representative['sourceQuarter']]
        require(source.finite(row.get('sourceQuarter')) and source.finite(row.get('time'))
                and row['sourceQuarter'] == representative['sourceQuarter'] and row['time'] == representative['time']
                and same(row.get('sourcePhysicalIds'), expected_ids)
                and row.get('readingEstimateOnly') is True
                and source.finite(row.get('uncertaintySeconds')) and row['uncertaintySeconds'] >= 0,
                'Common coordinate lost an actual same-quarter voice or changed its estimate')
    terminal = nodes[-1]
    require(terminal.get('readingTerminalOnly') is True and terminal.get('sourcePhysicalIds') == []
            and source.finite(terminal.get('sourceQuarter')) and source.finite(terminal.get('time'))
            and terminal['sourceQuarter'] == max(e['sourceQuarterEnd'] for e in sync['events'])
            and 0 < terminal['time'] <= sync['duration']
            and clock.get('musicActiveUntilTime') == terminal['time']
            and clock.get('clearMusicCursorAtOrAfterTerminal') is True
            and clock.get('nativeMP3ContinuesTo') == sync['duration'],
            'Music terminal was inferred from native EOF or retained a cursor into dialogue')
    require(all(source.finite(row.get('time')) and source.finite(row.get('sourceQuarter'))
                and b['time'] > row['time'] and b['sourceQuarter'] > row['sourceQuarter']
                for row, b in zip(nodes, nodes[1:])), 'Common reading clock moved backwards or collapsed')
    return nodes


def validate_context(spec, candidate, sync_raw, notation_raw, canonical, hashes, resolve):
    require(type(spec) is dict and set(spec) == {'kind', *REFS} and spec.get('kind') == KIND,
            'Explicit normal ensemble original-evidence context required')
    require(opted(candidate), 'Independent ensemble profile required, never an existing song/profile alias')
    version = bound(spec['versionAuditSha256'], hashes, resolve)
    decision = bound(spec['rootV6DecisionSha256'], hashes, resolve)
    proposal = bound(spec['originalProposalSha256'], hashes, resolve)
    index = bound(spec['originalIndexSha256'], hashes, resolve)
    current = identity(candidate, canonical, sync_raw, notation_raw)
    require(version.get('schema') == 'source-recording-version-adjudication/v6'
            and version.get('referenceContractVersion') == 6 and version.get('reviewedBy') == '/root'
            and version.get('relation') == 'qualified-original-score-reference'
            and version.get('status') == 'matched-reviewed-qualified-source-reference'
            and version.get('qualifiedReadingProfile') == PROFILE,
            'Actual ensemble recording edition is pending or borrowed')
    require(decision.get('schema') == 'root-qualified-original-score-reference-decision/v6'
            and decision.get('approved') is True and decision.get('reviewedBy') == '/root'
            and decision.get('status') == 'root-reviewed-qualified-original-score-reference'
            and proposal.get('schema') == 'qualified-original-score-reference-proposal/v6',
            'Actual Root qualified edition decision is pending')
    for body in (version, decision, proposal):
        require(all(body.get(k) == v for k, v in current.items())
                and body.get('qualifiedReadingProfile') == PROFILE, 'Root edition refers to another exact musical tuple')
        source.no_gold(body)
    require(version.get('rootDecisionSha256') == spec['rootV6DecisionSha256']
            and version.get('reviewInputsSha256') == decision.get('reviewInputsSha256') == spec['originalProposalSha256']
            and version.get('evidenceIndexSha256') == decision.get('evidenceIndexSha256') == spec['originalIndexSha256'],
            'Actual Root edition does not bind the exact original proposal/index')
    refs = {k: spec[k] for k in REFS[4:]}
    for body in (version, decision, proposal):
        require(same(body.get('completeEnsembleEvidence'), refs), 'Root edition source/clock/geometry graph differs')
    indexed = {row['sha256'] for row in index.get('entries', [])}
    require(indexed and indexed <= hashes and set(refs.values()) <= indexed,
            'Actual full original ensemble evidence index is incomplete')
    # Touch each indexed original; a hash named in a JSON file is insufficient.
    for digest in indexed:
        bound(digest, hashes, resolve, True)
    audit = bound(spec['sourceAuditSha256'], hashes, resolve)
    st = source.validate_source(spec['sourceDecisionSha256'], audit, canonical, hashes, resolve)
    descriptor = json.loads(st.descriptorJSON)
    structural = source.validate_structure(canonical, sync_raw, notation_raw, descriptor)
    sync = source.strict_json(sync_raw)
    expected_unknown = list(range(descriptor['physicalCounts']['pitch']))
    expected_secondary = [e['eventIndex'] for e in sync['events'] if not e['cursorPrimary']]
    for body in (version, decision, proposal):
        require(same(body.get('completeEnsembleSourceDescriptor'), descriptor)
                and same(body.get('pitchUnconfirmedEventIndices'), expected_unknown)
                and same(body.get('recordingLyricUnconfirmedEventIndices'), expected_unknown)
                and same(body.get('manualSecondaryEventIndices'), expected_secondary)
                and body.get('readonlySourceOptions') == []
                and same(body.get('readonlyRestIds'), structural['readonlyRestIds']),
                'Root complete source denominator or performance-unknown masks changed')
        scope = body.get('qualifiedReferenceScope', {})
        limits = ('allSourceVoicesLiteralPerformanceConfirmed', 'allSingerPitchGold',
                  'isolatedVoiceAttackGold', 'allPrintedWordsAcousticallyConfirmed',
                  'sourcePitchReplacement', 'browserPCMOriginMeasured')
        require(type(scope) is dict and all(scope.get(k) is False for k in limits),
                'Qualified source reference was upgraded to literal performed voice/word/attack Gold')
    validate_clock(spec['clockDecisionSha256'], candidate, sync_raw, notation_raw, canonical, st, hashes, resolve)
    geometry = bound(spec['actualGeometryEvidenceSha256'], hashes, resolve)
    require(type(geometry) is dict, 'Actual independent source geometry original required')
    owner = getattr(resolve, '__self__', resolve)
    require(not getattr(owner, 'closed', False), 'Closed normal ensemble evidence invocation')
    result = ValidatedEnsembleContext(_TOKEN, owner, source.encoded(spec).decode(),
        source.sha(source.encoded(current)), source.encoded(structural).decode(), spec['rootV6DecisionSha256'])
    key = id(result)
    fingerprint = source.sha(source.encoded({k: v for k, v in vars(result).items() if k not in ('_token', '_owner')}))
    _LIVE[key] = (weakref.ref(result, lambda ref: _LIVE.pop(key, None)), fingerprint)
    return result


def validate_clock(decision_sha, candidate, sync_raw, notation_raw, canonical, source_result, hashes, resolve):
    """Actual source plus Root common-clock authority; no version/UI admission."""
    source.check_source(source_result, canonical, resolve)
    current = identity(candidate, canonical, sync_raw, notation_raw)
    structural = source.validate_structure(canonical, sync_raw, notation_raw, json.loads(source_result.descriptorJSON))
    sync = source.strict_json(sync_raw)
    nodes = whole_clock(sync, structural)
    clock = bound(decision_sha, hashes, resolve)
    require(clock.get('schema') == 'root-complete-ensemble-source-reading-clock-decision/v1'
            and clock.get('reviewedBy') == '/root' and clock.get('approved') is True
            and clock.get('scope') == 'common-source-reading-coordinates-only-not-performance-gold'
            and all(clock.get(k) == v for k, v in current.items())
            and clock.get('sourceDecisionSha256') == source_result.decisionSha256
            and same(clock.get('commonClock'), nodes), 'Actual Root common reading-clock approval is pending or stale')
    source.no_gold(clock)
    evidence_keys = ('actualClockReviewSha256', 'sampleEvidenceSha256', 'nativeClockEvidenceSha256',
                     'blindVocalEvidenceSha256')
    bodies = {k: bound(clock[k], hashes, resolve) for k in evidence_keys}
    observations = bodies['actualClockReviewSha256']
    require(observations.get('reviewedBy') == '/root' and observations.get('commonClockOnly') is True
            and observations.get('syncSha256') == current['syncSha256']
            and observations.get('notationSha256') == current['notationSha256']
            and same(observations.get('reviewedCoordinates'), nodes)
            and observations.get('allSourceQuarterReferencesReviewed') is True,
            'Actual Root all-coordinate audio review original is incomplete')
    source.no_gold(observations)
    try:
        from .complete_ensemble_boundary_clock_v1 import validate as validate_boundaries
    except ImportError:
        from complete_ensemble_boundary_clock_v1 import validate as validate_boundaries
    validate_boundaries(sync, observations, source, nodes)
    require(clock.get('musicClockApproved') is True and clock.get('uiGateApproved') is False and clock.get('normalAdmissionGranted') is False
            and clock.get('formalAccepted') is False, 'Reading clock authority was upgraded to UI/admission')
    return dict(schema='validated-ensemble-common-reading-clock/v1', clockDecisionSha256=decision_sha,
        sourceDecisionSha256=source_result.decisionSha256, currentIdentity=current,
        commonClock=copy.deepcopy(nodes), clockApproved=True, normalUIApproved=False,
        normalAdmissionValidated=False, physicalPerformanceGold=False)


@dataclass(frozen=True)
class ValidatedEnsembleContext:
    _token: object
    _owner: object
    specJSON: str
    identityFingerprint: str
    structureJSON: str
    rootV6DecisionSha256: str
    normalAdmissionValidated: bool = False
    physicalPerformanceGold: bool = False


def check_context(result, spec, candidate, canonical, sync_raw, notation_raw, resolve):
    owner = getattr(resolve, '__self__', resolve); entry = _LIVE.get(id(result))
    require(type(result) is ValidatedEnsembleContext and result._token is _TOKEN
            and entry is not None and entry[0]() is result and result._owner is owner
            and entry[1] == source.sha(source.encoded({k: v for k, v in vars(result).items() if k not in ('_token', '_owner')}))
            and not getattr(owner, 'closed', False) and result.specJSON == source.encoded(spec).decode()
            and result.identityFingerprint == source.sha(source.encoded(identity(candidate, canonical, sync_raw, notation_raw)))
            and result.normalAdmissionValidated is False and result.physicalPerformanceGold is False,
            'Normal context is invented, borrowed, closed, or stale')
    return json.loads(result.structureJSON)


def _capture_reader(hashes, resolve):
    # One decoded original, preserving every byte/hash/pointer/semantic check.
    try:
        from .bounded_original_validation_v1 import bounded_capture_reader
    except ImportError:
        from bounded_original_validation_v1 import bounded_capture_reader
    return bounded_capture_reader(hashes, resolve, source)


def captured(row, hashes, resolve):
    return _capture_reader(hashes, resolve)(row)


def registered_audio_path(candidate):
    # EG catalog IDs deliberately differ from their actual media URL paths.
    # Read the current registration; never infer or accept a caller-supplied alias.
    catalog = registration_catalog(Path(__file__).resolve().parent / 'data/follow-catalog.json', source.strict_json)
    require(type(catalog) is dict and type(catalog.get('songs')) is list
            and all(type(row) is dict for row in catalog['songs']), 'Current audio catalog is malformed')
    rows = [row for row in catalog.get('songs', []) if row.get('songId') == candidate.get('sourceSongId')]
    require(len(rows) == 1 and (candidate.get('id') is None or rows[0].get('followId') == candidate['id']),
            'Current recording registration is missing, duplicated or belongs to another follow ID')
    value = rows[0].get('sourceAudio')
    require(type(value) is str and value.startswith('/audio/'), 'Current registered audio URL is missing')
    parsed = urlparse(value)
    require(not parsed.scheme and not parsed.netloc and not parsed.query and not parsed.fragment,
            'Current audio registration is not an exact local media URL')
    path = unquote(parsed.path)
    require('..' not in path.split('/') and '\\' not in path
            and candidate.get('audio') == value,
            'Candidate audio URL differs from its current exact recording registration')
    return path


def audio_at(audio, candidate, time=None, paused=None):
    require(unquote(urlparse(audio['src']).path) == registered_audio_path(candidate),
            'Actual normal parent audio is a different recording')
    require(source.finite(audio['time']) and source.finite(audio['duration']) and audio['duration'] > 0,
            'Actual native parent audio clock is missing')
    if time is not None:
        require(abs(audio['time'] - time) < .003, 'Native action did not reach the exact requested reading coordinate')
    if paused is not None:
        require(audio['paused'] is paused, 'Actual native pause state differs')


def reading_coordinate_time(actual_time, nodes):
    # Native MP3 times can differ from a requested double by microseconds.
    # This is the frontend's sub-sample numerical node equivalence, not an
    # audio timing correction. Captured parent/frame times remain unchanged.
    require(source.finite(actual_time), 'Actual reading coordinate time is missing')
    near = [point['time'] for point in nodes if abs(actual_time - point['time']) <= 3e-6]
    require(len(near) <= 1, 'Approved reading-node numerical equivalence is ambiguous')
    return near[0] if near else actual_time


def visible_reading_line(frame):
    line, area, viewport = frame['cursorLineBounds'], frame['readingViewportBounds'], frame['viewport']
    keys = ('left', 'right', 'top', 'bottom')
    require(all(source.finite(rect[k]) for rect in (line, area) for k in keys)
            and source.finite(viewport['height']) and viewport['height'] > 0
            and 0 <= area['left'] < area['right'] <= viewport['width'] + .5
            and 0 <= area['top'] < area['bottom'] <= viewport['height'] + .5,
            'Actual safe reading viewport is empty, missing, or outside the frame')
    stroke = frame['cursorStrokeWidthPx']
    require(source.finite(line['width']) and line['width'] >= 0 and line['left'] <= line['right']
            and line['top'] < line['bottom'] and source.finite(stroke) and stroke >= 0
            and (line['width'] > 0 or stroke > 0), 'Actual reading line has no visible extent')
    # SVG vertical lines have a zero-width DOM box. Their actual painted stroke
    # still intersects the clipped reading pane; tall voice groups may pan.
    padding = stroke / 2 if line['width'] == 0 else 0
    require(line['right'] + padding > area['left'] and line['left'] - padding < area['right']
            and line['bottom'] > area['top'] and line['top'] < area['bottom'],
            'Actual reading line is offscreen or hidden behind the reading controls')
    return True


def frame_at(frame, width, mode, q, notation=None, structural=None, source_systems=None):
    viewport = frame['viewport']
    outer = frame.get('outerViewport', viewport)
    require(frame['mode'] == mode and outer['width'] == width
            and source.finite(outer['scrollWidth']) and 0 < outer['scrollWidth'] <= width
            and source.finite(viewport['width']) and 0 < viewport['width'] <= width
            and source.finite(viewport['scrollWidth']) and 0 < viewport['scrollWidth'] <= viewport['width'],
            'Actual viewport/mode has page overflow or another scope')
    require(frame['cursorLineCount'] == 1 and abs(frame['sourceQuarter'] - q) < .00001
            and frame.get('cursorSpansWholeSourceSystem') is True
            and frame.get('cursorSourceParts') == frame.get('systemSourceParts')
            and frame.get('systemSourceParts'), 'One complete source-system reading line required, including all printed voices')
    if notation is not None and structural is not None:
        systems = source_systems if source_systems is not None else notation['sourceSystemGeometry']['systems']
        rows = structural['projection']['physicalEvents']
        origins = {(r['measure'], r['sourceQuarter'] - r['beatInMeasure']) for r in rows}
        measure = max((mn for mn, start in origins if start <= q), default=0)
        matching = [s for s in systems if s['firstMeasure'] <= measure <= s['lastMeasure']]
        require(len(matching) == 1, 'Actual source system coordinate is ambiguous')
        system = matching[0]
        parts = [p['id'] for p in structural['descriptor']['sourceParts'] if any(
            r['sourcePart'] == p['id'] and system['firstMeasure'] <= r['measure'] <= system['lastMeasure'] for r in rows)]
        require(frame.get('sourceSystemId') == system['sourceSystemId']
                and same(frame.get('systemSourceParts'), parts), 'Actual line omitted an original printed source part')
    # A large five-part score may be panned. The line must span its real source
    # system, not just the clipped visible slice, and all source lanes survive.
    line = frame['cursorLineBounds']
    system = frame.get('wholeSourcePartsBounds', frame['wholeSystemBounds'])
    require(all(source.finite(v[k]) for v in (line, system) for k in ('top', 'bottom'))
            and line['top'] <= system['top'] + .5 and line['bottom'] >= system['bottom'] - .5,
            'Actual line ends before one or more source lanes')
    visible_reading_line(frame)


@snapshot_validation
def validate_native_scopes(actions, readonly, candidate, sync, structural, hashes, resolve, notation=None, read_capture=None, source_systems=None):
    """Check actual native inventories; this grants no overall UI authority."""
    read_capture = read_capture or _capture_reader(hashes, resolve)
    events = sync['events']; rests = structural['readonlyRestIds']
    require(type(actions) is list and len(actions) == len(events) * len(SCOPES)
            and type(readonly) is list and len(readonly) == len(rests) * len(SCOPES),
            'All native physical-head/readonly-rest scopes are required')
    for width, mode in SCOPES:
        rows = [r for r in actions if (r['width'], r['view']) == (width, mode)]
        require(len(rows) == len(events) and {r['eventIndex'] for r in rows} == set(range(len(events))),
                'Native head scope omitted or duplicated an original source head')
        for row in rows:
            require(type(row['eventIndex']) is int, 'Native event index must be an integer')
            e = events[row['eventIndex']]; raw = read_capture(row)
            require(raw['action'] in ('native-Enter', 'native-double-click')
                    and raw['sourcePhysicalId'] == e['sourcePhysicalId'] and raw['eventIndex'] == e['eventIndex'],
                    'Actual native source head/action identity differs')
            if 'width' in raw or 'mode' in raw:
                require(raw.get('width') == width and raw.get('mode') == mode, 'Actual native source scope differs')
            state = raw['after'] if 'after' in raw else raw
            audio_at(state['audio'], candidate, e['time'], True)
            frame_at(state['frame'], width, mode, e['sourceQuarter'], notation, structural, source_systems)
            if 'selectedSourcePhysicalId' in state['frame']:
                require(state['frame']['selectedSourcePhysicalId'] == e['sourcePhysicalId'],
                        'Actual native focus selected another source head')
        rows = [r for r in readonly if (r['width'], r['view']) == (width, mode)]
        require(len(rows) == len(rests) and {r['sourcePhysicalId'] for r in rows} == set(rests),
                'Native readonly rest scope omitted original entities')
        for row in rows:
            raw = read_capture(row)
            require(raw['sourcePhysicalId'] == row['sourcePhysicalId']
                    and all(raw.get(k) is None for k in ('timeAttribute', 'eventIndexAttribute', 'tabindexAttribute')),
                    'Actual printed rest became timed or seekable')
            if raw['action'] == 'native-readonly-inspection':
                require(raw['seekEmitted'] is False and same(raw['beforeAudio'], raw['afterAudio']),
                        'Actual printed rest emitted a seek')
                audio_at(raw['afterAudio'], candidate)
            else:
                require(raw['action'] == 'readonly-DOM-inspection' and raw.get('width') == width
                        and raw.get('mode') == mode and same(raw['beforeParentAudio'], raw['afterParentAudio'])
                        and source.finite(raw['afterParentAudio']['time'])
                        and 0 <= raw['afterParentAudio']['time'] <= candidate['duration'] + .01
                        and raw['afterParentAudio']['paused'] is True
                        and ('seekEmitted' not in raw or raw['seekEmitted'] is False),
                        'Actual readonly DOM inspection changed its native parent clock or scope')
    return True


@snapshot_validation
def validate_browser(browser, candidate, sync, structural, hashes, resolve, notation=None):
    require(browser.get('schema') == 'actual-complete-ensemble-native-browser-audit/v1'
            and browser.get('status') == 'passed' and browser.get('qualifiedReadingProfile') == PROFILE,
            'Actual normal native ensemble browser audit is pending')
    try:
        from .complete_ensemble_source_systems_v1 import resolve_source_systems
    except ImportError:
        from complete_ensemble_source_systems_v1 import resolve_source_systems
    source_systems = resolve_source_systems(browser, candidate, sync, structural, hashes, resolve, notation)
    read_capture = _capture_reader(hashes, resolve)
    validate_native_scopes(browser.get('actions'), browser.get('readonlyActions'), candidate, sync,
                           structural, hashes, resolve, notation, read_capture, source_systems)
    photos = browser.get('screenshots', [])
    require({(r['width'], r['view']) for r in photos} == SCOPES
            and len({r['sha256'] for r in photos}) >= len(SCOPES), 'Four actual screenshot scopes required')
    for row in photos:
        raw = bound(row['sha256'], hashes, resolve, True)
        require(raw.startswith(b'\x89PNG\r\n\x1a\n') or raw.startswith(b'\xff\xd8\xff'), 'Actual browser photograph bytes required')
    natural = browser.get('naturalPlayback', []); start, visible, clear, ended = set(), set(), set(), set()
    nodes = whole_clock(sync, structural)
    try:
        from .complete_ensemble_boundary_clock_v1 import display_nodes, pitched_active
    except ImportError:
        from complete_ensemble_boundary_clock_v1 import display_nodes, pitched_active
    nodes = display_nodes(sync, nodes)
    for row in natural:
        raw = read_capture(row); audio, frame = raw['audio'], raw['frame']
        scope = row['width'], row['view']
        require(scope in SCOPES and raw['nativeContinuousPlayback'] is True and raw['seekDuringPlayback'] is False,
                'Natural playback was simulated or used seeking')
        audio_at(audio, candidate)
        require(source.finite(frame['time']) and 0 <= audio['time'] - frame['time'] <= .15,
                'Actual frame clock is ahead or stale relative to the parent audio')
        time = reading_coordinate_time(frame['time'], nodes)
        if audio['time'] < .003:
            start.add(scope)
        active = nodes[0]['time'] <= time < nodes[-1]['time']
        if sync.get('sourceReadingBoundaryClock') is not None:
            active = active and pitched_active(sync, time)
        if active:
            require(audio['paused'] is False, 'Natural visible cue was not observed while playing')
            i = next(i for i, point in enumerate(nodes) if point['time'] > time)
            a, b = nodes[i - 1], nodes[i]
            q = a['sourceQuarter'] + (time - a['time']) / (b['time'] - a['time']) * (b['sourceQuarter'] - a['sourceQuarter'])
            frame_at(frame, row['width'], row['view'], q, notation, structural, source_systems); visible.add(scope)
        else:
            require(frame['cursorLineCount'] == 0, 'Music preroll/terminal/EOF retained a reading cursor')
            if time >= nodes[-1]['time']:
                clear.add(scope)
        if audio['ended']:
            require(audio['paused'] is True and abs(audio['time'] - audio['duration']) < .003
                    and frame['cursorLineCount'] == 0, 'Actual native EOF did not end with a clear cursor')
            ended.add(scope)
    require(start == visible == clear == ended == SCOPES, 'Four actual natural zero/visible/terminal-clear/EOF scopes incomplete')
    navigation = browser.get('navigation', [])
    require({r['test'] for r in navigation} >= {'manual-scroll', 'resume', 'size', 'expanded-exit', 'play-pause'},
            'Actual normal reading navigation evidence missing')
    for row in navigation:
        require(read_capture(row).get('passed') is True, 'An actual normal navigation check failed')
    return True


def validate_ui(spec, candidate, sync_raw, notation_raw, canonical, hashes, resolve, context_result):
    require(type(spec) is dict and set(spec) == {'kind', *UI_REFS} and spec.get('kind') == UI_KIND,
            'Explicit normal ensemble native UI graph required')
    cs = dict(kind=KIND, **{k: spec[k] for k in REFS})
    structural = check_context(context_result, cs, candidate, canonical, sync_raw, notation_raw, resolve)
    current = identity(candidate, canonical, sync_raw, notation_raw)
    browser = bound(spec['browserAuditSha256'], hashes, resolve)
    require(all(browser.get(k) == v for k, v in current.items())
            and same(browser.get('frontend'), candidate.get('frontend')), 'Actual native UI musical/assets identities differ')
    validate_browser(browser, candidate, source.strict_json(sync_raw), structural, hashes, resolve,
                     source.strict_json(notation_raw))
    decision = bound(spec['rootNormalUIDecisionSha256'], hashes, resolve)
    require(decision.get('schema') == 'root-complete-ensemble-normal-ui-decision/v1'
            and decision.get('approved') is True and decision.get('reviewedBy') == '/root'
            and decision.get('scope') == 'current-normal-native-complete-source-reading-only'
            and all(decision.get(k) == v for k, v in current.items())
            and decision.get('browserAuditSha256') == spec['browserAuditSha256']
            and decision.get('rootV6DecisionSha256') == spec['rootV6DecisionSha256']
            and same(decision.get('frontend'), candidate.get('frontend')),
            'Actual Root normal native UI decision is pending or stale')
    source.no_gold(decision)
    mapping = bound(spec['performanceMapSha256'], hashes, resolve)
    require(same(mapping, performance_map(candidate, sync_raw, notation_raw, canonical, structural)),
            'Complete source-reading map differs from fresh canonical/runtime projection')
    return dict(automaticEventIndices=tuple(r['eventIndex'] for r in structural['representatives']),
                rootV6DecisionSha256=spec['rootV6DecisionSha256'])


def performance_map(candidate, sync_raw, notation_raw, canonical, structural=None):
    structural = structural or source.validate_structure(canonical, sync_raw, notation_raw)
    sync = source.strict_json(sync_raw)
    return dict(schema='complete-ensemble-source-reading-performance-map/v1', qualifiedReadingProfile=PROFILE,
        **identity(candidate, canonical, sync_raw, notation_raw),
        descriptor=copy.deepcopy(structural['descriptor']),
        pitchedReadingReferences=[{k: e[k] for k in ('eventIndex', 'sourcePhysicalId', 'partId',
            'sourceQuarter', 'sourceQuarterEnd', 'time', 'endTime')} for e in sync['events']],
        quarterRepresentatives=copy.deepcopy(structural['representatives']),
        readonlyRestIds=copy.deepcopy(structural['readonlyRestIds']),
        technicalForwards=copy.deepcopy(structural['projection']['unprintedSourceGaps']),
        readonlyRestSeekAllowed=False, physicalPerformanceGold=False,
        isolatedSingerPitchAttackReleaseGold=False, allPrintedWordsAcousticallyConfirmed=False)
