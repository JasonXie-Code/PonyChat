"""Explicit occurrence normal preparation. Old complete/typed profiles stay separate.

All source/route/clock/model/edition originals must be independently Root bound.
This module issues only a preparation capability, never UI/admission authority.
"""
from dataclasses import dataclass
import copy
import json
import weakref
import xml.etree.ElementTree as ET

try:
    from . import complete_ensemble_reference_v1 as source
    from . import complete_ensemble_occurrence_v1 as mechanics
    from . import complete_ensemble_occurrence_layout_v1 as layout
except ImportError:
    import complete_ensemble_reference_v1 as source
    import complete_ensemble_occurrence_v1 as mechanics
    import complete_ensemble_occurrence_layout_v1 as layout

PROFILE = mechanics.PROFILE
KIND = 'typed-complete-ensemble-occurrence-normal-context/v1'
IDENTITY = ('followId', 'sourceSongId', 'sourceScoreId', 'sourcePDFsha', 'canonicalSha256',
    'sourceAudioSha256', 'syncSha256', 'notationSha256')
SOURCE_REFS = ('sourceAuditSha256', 'sourceDecisionSha256', 'routeInputSha256', 'rawClockSha256',
    'routeDecisionSha256', 'clockDecisionSha256', 'originalModelSha256')
MODEL_REFS = ('nativePaperGeometrySha256', 'originalInkGeometrySha256', 'sourceModelDecisionSha256')
EDITION_REFS = ('versionAuditSha256', 'rootV6DecisionSha256', 'originalProposalSha256', 'originalIndexSha256')
REFS = SOURCE_REFS + MODEL_REFS + EDITION_REFS
require, same, bound = source.require, source.same, source.bound
_TOKEN, _LIVE = object(), {}


def opted(candidate, review=None):
    result = candidate.get('qualifiedReadingProfile') == PROFILE
    if review is not None:
        require(result == (review.get('qualifiedReadingProfile') == PROFILE), 'One-sided occurrence profile')
    return result


def source_connections(rows, exact):
    result = [dict(kind='tie', source=start, target=stop) for start, stop in mechanics._ties(rows, exact)]
    opened = {}
    for row in sorted(rows, key=lambda e: (e['sourcePart'], e['sourceQuarter'], e['sourceNoteIndex'])):
        for mark in row['slurs']:
            key = (row['sourcePart'], row['voice'], row['staff'], mark.get('number', '1'))
            if mark['type'] == 'start':
                require(key not in opened, 'Ambiguous original source slur start')
                opened[key] = (row['sourcePhysicalId'], mark)
            elif mark['type'] == 'stop':
                require(key in opened, 'Original source slur stop lacks start')
                start, original_mark = opened.pop(key)
                result.append(dict(kind='slur', source=start, target=row['sourcePhysicalId'],
                    originalStart=copy.deepcopy(original_mark), originalStop=copy.deepcopy(mark)))
            else:
                require(mark['type'] == 'continue', 'Unknown original slur segment')
    require(not opened, 'Incomplete original source slur')
    return result


def project_runtime(canonical, candidate, route_input, raw_clock, model_raw, route_input_raw=None, raw_clock_raw=None):
    """Unsigned deterministic projection. Supplied times are never fitted/approved."""
    require(opted(candidate), 'Explicit occurrence profile required')
    route_input_raw = source.encoded(route_input) if route_input_raw is None else route_input_raw
    raw_clock_raw = source.encoded(raw_clock) if raw_clock_raw is None else raw_clock_raw
    require(same(source.strict_json(route_input_raw), route_input) and same(source.strict_json(raw_clock_raw), raw_clock),
        'Original route/clock bytes differ from supplied inputs')
    route = mechanics.validate_route(canonical, route_input)
    clock = mechanics.validate_clock(route, raw_clock)
    payload = layout.prepare_reference_payload(canonical, route, clock, model_raw)
    model = source.strict_json(model_raw)
    shift = model.get('commonOctaveShift')
    require(type(shift) is int and model.get('referenceTonicOctave') == 4-shift,
        'One original common octave plan required')
    model_zones = [(mechanics.quarter(z.get('q0', z.get('sourceQuarter'))), z.get('key', z.get('tonic')))
        for z in model.get('keyPlan', [])]
    route_zones = [(mechanics.coordinate(z, 'sourceQuarter'), z['tonic']) for z in route.data()['sourceKeyPlan']]
    require(model_zones == route_zones, 'Original model/route tonic plan differs')
    tokens = []
    for original in payload['physicalSource']:
        token = copy.deepcopy(original)
        tonic = next(z['tonic'] for z in reversed(payload['sourceKeyPlan'])
            if mechanics.coordinate(z, 'sourceQuarter') <= mechanics.coordinate(token, 'sourceQuarter'))
        token.update(id=token['sourcePhysicalId'], localTonic=tonic, readingOnly=True,
            sourceOnlyUntimed=True, lyric=token['sourceLyric'] or ('__' if token['lyricExtend'] else ''),
            beat=token['beatInMeasure'], lane=payload['sourceParts'].index(next(p for p in payload['sourceParts']
                if p['id'] == token['sourcePart'])), skipCursorHighlight=True)
        token.update(tieStart=any(t['type'] == 'start' for t in token['ties']), tieStop=any(t['type'] == 'stop' for t in token['ties']))
        if token['sourceKind'] == 'pitch':
            values = source.number_projection(token['pitch'], tonic, 4-shift)
            token.update(zip(('midi', 'degree', 'octave', 'accidental', 'token'), values))
        else:
            token.update(midi=None, degree=None, octave=None, accidental=None,
                token='0' if token['sourceKind'] == 'rest' else 'X')
        tokens.append(token)
    exact, _ = mechanics._exact_source_rhythm(canonical)
    by_id = {t['id']: t for t in tokens}
    for start, stop in mechanics._ties(payload['physicalSource'], exact):
        by_id[start]['tieTo'] = stop
    common = dict(qualifiedReadingProfile=PROFILE, songId=candidate['id'], sourceSongId=candidate['sourceSongId'],
        sourceScoreId=candidate['sourceScoreId'], sourcePDFsha256=candidate['sourcePDFsha256'],
        canonicalSha256=source.sha(canonical), sourceAudioSha256=candidate['sourceAudioSha256'],
        sourceParts=payload['sourceParts'], primaryPart=None, routeInputSha256=source.sha(route_input_raw),
        rawClockSha256=source.sha(raw_clock_raw), routeProjectionSha256=route.sha256,
        mechanicalClockSha256=clock.sha256, originalModelSha256=source.sha(model_raw),
        mechanicalLayoutSha256=source.sha(source.encoded(payload)))
    sync = dict(schema='complete-ensemble-occurrence-sync/v1', **common, duration=payload['nativeDuration'],
        instances=copy.deepcopy(payload['instances']), events=[copy.deepcopy(e) for e in payload['instances'] if e['sourceKind'] == 'pitch'],
        unpitchedReadingReferences=[copy.deepcopy(e) for e in payload['instances'] if e['sourceKind'] == 'unpitched'],
        visits=payload['visits'], curves=payload['curves'], musicActiveUntilTime=payload['musicActiveUntilTime'],
        clearMusicCursorAtOrAfterTerminal=True, clockApproved=False, normalUIApproved=False, formalAccepted=False)
    spans = layout._measure_spans(canonical)
    meters, meter = {}, None
    for m in ET.fromstring(canonical).findall('part')[0].findall('measure'):
        printed = m.find('attributes/time')
        if printed is not None:
            meter = printed.findtext('beats') + '/' + printed.findtext('beat-type')
        meters[int(m.get('number'))] = meter
    measures = []
    for mn in sorted({t['measure'] for t in tokens}):
        members = [t for t in tokens if t['measure'] == mn]
        a, b = spans[(members[0]['sourcePart'], mn)]
        system = next(s for s in model['originalSystems'] if s['first'] <= mn <= s['last'])
        order = system.get('physicalTopToBottomParts', system['actualSourceParts'])
        for token in members:
            token['lane'] = order.index(token['sourcePart'])
        measures.append(dict(number=mn, measure=mn, tokens=members, lanes=len(order), sourcePartLanes=order,
            beatsPerMeasure=float(b-a), sourceQuarter=float(a), timeSignature=meters[mn], localTonic=members[0]['localTonic']))
    notation = dict(schema='complete-ensemble-occurrence-notation/v1', **common, tokens=tokens, measures=measures,
        notation_octave_shift=shift, commonOctaveShiftAcrossAllParts=True, sourceKeyPlan=payload['sourceKeyPlan'],
        sourceGaps=payload['sourceGaps'], sourceConnections=source_connections(payload['physicalSource'], exact),
        sourceSystemGeometry=dict(originalModelSha256=source.sha(model_raw), systems=payload['sourceSystems']),
        readingOnly=True, normalUIApproved=False, formalAccepted=False)
    return sync, notation, route, clock, payload


def identity(candidate, canonical, sync_raw, notation_raw):
    sync, notation = source.strict_json(sync_raw), source.strict_json(notation_raw)
    require(opted(candidate) and sync.get('qualifiedReadingProfile') == notation.get('qualifiedReadingProfile') == PROFILE,
        'Old/default profile cannot select occurrence semantics')
    for body in (sync, notation):
        require(body.get('songId') == candidate['id'] and body.get('sourceSongId') == candidate['sourceSongId']
            and body.get('sourceScoreId') == candidate['sourceScoreId']
            and body.get('sourceAudioSha256') == candidate['sourceAudioSha256']
            and body.get('sourcePDFsha256') == candidate['sourcePDFsha256']
            and body.get('canonicalSha256') == source.sha(canonical), 'Occurrence musical identity differs')
    return dict(followId=candidate['id'], sourceSongId=candidate['sourceSongId'], sourceScoreId=candidate['sourceScoreId'],
        sourcePDFsha=candidate['sourcePDFsha256'], canonicalSha256=source.sha(canonical),
        sourceAudioSha256=candidate['sourceAudioSha256'], syncSha256=source.sha(sync_raw), notationSha256=source.sha(notation_raw))


def _decision(body, schema, current):
    require(body.get('schema') == schema and body.get('approved') is True and body.get('reviewedBy') == '/root'
        and body.get('qualifiedReadingProfile') == PROFILE and all(body.get(k) == v for k, v in current.items()),
        'Actual Root occurrence decision missing, stale or borrowed: ' + schema)
    source.no_gold(body)
    require(body.get('uiGateApproved') is False and body.get('normalAdmissionGranted') is False
        and body.get('formalAccepted') is False, 'Preparation authority upgraded to UI/admission')


def validate_source_clock(spec, candidate, canonical, sync_raw, notation_raw, hashes, resolve):
    """Stage1 real Source + Route + Clock factories; no model/V6/UI authority."""
    require(all(k in spec for k in SOURCE_REFS), 'Explicit original occurrence source/route/clock refs required')
    current = identity(candidate, canonical, sync_raw, notation_raw)
    audit = bound(spec['sourceAuditSha256'], hashes, resolve)
    source_module = source
    if mechanics.projection(canonical)['counts']['unpitched']:
        try:
            from . import typed_unpitched_source_normal_v1 as source_module
        except ImportError:
            import typed_unpitched_source_normal_v1 as source_module
    st = source_module.validate_source(spec['sourceDecisionSha256'], audit, canonical, hashes, resolve)
    sd = bound(spec['sourceDecisionSha256'], hashes, resolve)
    source_identity = audit if source_module is not source else sd
    require(source_identity.get('followId') == current['followId']
        and source_identity.get('sourcePDFsha256') == current['sourcePDFsha']
        and source_identity.get('sourceSongId') == current['sourceSongId']
        and source_identity.get('sourceScoreId') == current['sourceScoreId'],
        'Original source must bind current registered recording and score')
    route_raw = bound(spec['routeInputSha256'], hashes, resolve, True)
    clock_raw = bound(spec['rawClockSha256'], hashes, resolve, True)
    route_input, raw_clock = source.strict_json(route_raw), source.strict_json(clock_raw)
    model_raw = bound(spec['originalModelSha256'], hashes, resolve, True)
    sr, nr, route, clock, payload = project_runtime(canonical, candidate, route_input, raw_clock, model_raw, route_raw, clock_raw)
    require(same(sr, source.strict_json(sync_raw)) and same(nr, source.strict_json(notation_raw)),
        'Occurrence S/N differs from complete physical and repeated-instance projection')
    rd = bound(spec['routeDecisionSha256'], hashes, resolve)
    cd = bound(spec['clockDecisionSha256'], hashes, resolve)
    _decision(rd, 'root-complete-ensemble-occurrence-route-decision/v1', current)
    _decision(cd, 'root-complete-ensemble-occurrence-reading-clock-decision/v1', current)
    require(rd.get('scope') == 'source-navigation-performance-route-only-not-performance-gold'
        and cd.get('scope') == 'common-occurrence-reading-coordinates-only-not-performance-gold',
        'Occurrence route/clock qualification scope differs')
    for decision in (rd, cd):
        require(all(decision.get(k) == spec[k] for k in ('sourceDecisionSha256', 'routeInputSha256', 'rawClockSha256'))
            and decision.get('routeProjectionSha256') == route.sha256
            and decision.get('mechanicalClockSha256') == clock.sha256,
            'Root route/clock refers to another exact route or clock')
    require(same(rd.get('reviewedVisits'), route.data()['visits'])
        and same(rd.get('sourceOnlyUnvisitedIds'), route.data()['sourceOnlyUnvisitedIds']), 'Whole Root visit inventory differs')
    ro = bound(rd['actualRouteReviewSha256'], hashes, resolve)
    require(ro.get('reviewedBy') == '/root' and ro.get('allVisitsReviewed') is True
        and ro.get('routeInputSha256') == spec['routeInputSha256']
        and same(ro.get('reviewedVisits'), route.data()['visits']), 'Actual Root whole-route observation incomplete')
    navigation = {d for v in route.data()['visits'] for d in v.get('navigationEvidenceSha256s', [])}
    require(set(ro.get('navigationEvidenceSha256s', [])) == navigation, 'Root route navigation original coverage differs')
    for digest in navigation:
        bound(digest, hashes, resolve, True)
    co = bound(cd['actualClockReviewSha256'], hashes, resolve)
    require(co.get('reviewedBy') == '/root' and co.get('allOccurrenceBoundariesReviewed') is True
        and co.get('routeProjectionSha256') == route.sha256
        and same(co.get('reviewedVisitCurves'), clock.data()['curves'])
        and same(cd.get('reviewedVisitCurves'), clock.data()['curves']), 'Actual Root all-visit clock review incomplete')
    for key in ('sampleEvidenceSha256', 'nativeClockEvidenceSha256', 'blindVocalEvidenceSha256'):
        bound(cd[key], hashes, resolve)
    require(cd.get('musicActiveUntilTime') == payload['musicActiveUntilTime']
        and cd.get('nativeDuration') == payload['nativeDuration'], 'Music terminal/native EOF boundary differs')
    source.no_gold(ro); source.no_gold(co)
    return dict(currentIdentity=current, source=st, route=route, clock=clock, payload=payload)


def validate_model(spec, checked, hashes, resolve):
    current, payload = checked['currentIdentity'], checked['payload']
    model = bound(spec['originalModelSha256'], hashes, resolve)
    native = bound(spec['nativePaperGeometrySha256'], hashes, resolve)
    ink = bound(spec['originalInkGeometrySha256'], hashes, resolve)
    md = bound(spec['sourceModelDecisionSha256'], hashes, resolve)
    _decision(md, 'root-complete-ensemble-occurrence-source-model-decision/v1', current)
    require(md.get('scope') == 'original-source-display-systems-only', 'Original model qualification scope differs')
    for key in (*MODEL_REFS[:2], 'originalModelSha256', 'sourceDecisionSha256', 'routeDecisionSha256', 'clockDecisionSha256'):
        require(md.get(key) == spec[key], 'Root occurrence model graph differs')
    require(model['canonicalSha256'] == native['canonicalSha256'] == ink['canonicalSha256'] == current['canonicalSha256']
        and model['sourcePDFsha256'] == native['sourcePDFsha256'] == ink['sourcePDFsha256'] == current['sourcePDFsha']
        and same(model['privateNativeGeometry'], native) and model['sourceGeometrySha256'] == spec['originalInkGeometrySha256']
        and native['sourceGeometrySha256'] == spec['originalInkGeometrySha256'], 'Original occurrence geometry/model binding differs')
    pdf = bound(current['sourcePDFsha'], hashes, resolve, True)
    require(pdf.startswith(b'%PDF-'), 'Original registered PDF bytes required')
    rows = ink['notes'] + ink['readonlyRests'] + ink.get('unpitchedHeads', [])
    by_id = {e['sourceNoteId']: e for e in rows}
    require(len(rows) == len(by_id) == len(payload['physicalSource'])
        and set(by_id) == {p['sourcePhysicalId'] for p in payload['physicalSource']}, 'Complete original ink inventory differs')
    for p in payload['physicalSource']:
        i = by_id[p['sourcePhysicalId']]
        e = next(e for e in model['events'] if e['id'] == p['sourcePhysicalId'])
        require(i['sourcePart'] == p['sourcePart'] and i['measure'] == p['measure']
            and i['page'] == e['nativePage'] and i['staff'] == e['nativeStaff']
            and same(i['headCenter'], p['nativePoint']) and same(i['nativeInkBounds'], p['nativeInkBounds']),
            'Measured original glyph center/bounds differs')
    require(same(model['measureBounds'], native['measureIntervals']), 'Original barline geometry differs')
    require(len(native['systems']) == len(model['originalSystems']), 'Native system inventory differs')
    crops = []
    for s, n, prepared in zip(model['originalSystems'], native['systems'], payload['sourceSystems']):
        require(s['sourceSystemId'] == n['sourceSystemId'] and s['first'] == n['firstMeasure']
            and s['last'] == n['lastMeasure'] and s['page'] == n['page'] and same(s['rect'], n['rect'])
            and same(n.get('actualSourceParts', n.get('actualParts')), prepared['actualSourceParts']), 'Native source systems differ')
        staves = [staff for staff in native['staves'] if staff['sourceSystemId'] == s['sourceSystemId']]
        require({staff['part'] for staff in staves} == set(prepared['actualSourceParts'])
            and all(same(staff['lines'], s['staffLines'][staff['part']]) for staff in staves), 'Actual original staff lanes differ')
        image = bound(s['sha256'], hashes, resolve, True)
        require(image.startswith(b'\x89PNG\r\n\x1a\n'), 'Actual original source crop missing')
        crops.append(dict(sourceSystemId=s['sourceSystemId'], sha256=s['sha256'], sourceRect=s['rect']))
    require(same(md.get('sourceCropReferences'), crops), 'Root original source crop references differ')
    return model


@dataclass(frozen=True)
class ValidatedOccurrencePreparation:
    _token: object
    _owner: object
    specJSON: str
    identityJSON: str
    payloadJSON: str
    normalAdmissionValidated: bool = False
    normalUIApproved: bool = False


def validate_context(spec, candidate, canonical, sync_raw, notation_raw, hashes, resolve):
    require(type(spec) is dict and set(spec) == {'kind', *REFS} and spec.get('kind') == KIND,
        'Explicit occurrence original context required')
    checked = validate_source_clock(spec, candidate, canonical, sync_raw, notation_raw, hashes, resolve)
    validate_model(spec, checked, hashes, resolve)
    current = checked['currentIdentity']
    version, decision, proposal, index = [bound(spec[key], hashes, resolve) for key in EDITION_REFS]
    for body, schema in ((version, 'source-recording-version-adjudication/v6'),
            (decision, 'root-qualified-original-score-reference-decision/v6')):
        _decision(body, schema, current)
    require(proposal.get('schema') == 'qualified-original-score-reference-proposal/v6'
        and proposal.get('qualifiedReadingProfile') == PROFILE and all(proposal.get(k) == v for k, v in current.items()),
        'Original occurrence edition proposal differs')
    require(version.get('relation') == 'qualified-original-score-reference'
        and version.get('status') == 'matched-reviewed-qualified-source-reference'
        and decision.get('status') == 'root-reviewed-qualified-original-score-reference', 'Actual qualified occurrence edition is pending/failed')
    refs = {k: spec[k] for k in SOURCE_REFS + MODEL_REFS}
    pitch_ids = [e['occurrenceId'] for e in checked['payload']['instances'] if e['sourceKind'] == 'pitch']
    for body in (version, decision, proposal):
        require(same(body.get('occurrenceEvidence'), refs) and body.get('referenceContractVersion') == 6
            and same(body.get('pitchUnconfirmedOccurrenceIds'), pitch_ids)
            and same(body.get('recordingLyricUnconfirmedOccurrenceIds'), pitch_ids), 'Occurrence edition coverage or graph differs')
        limits = body.get('qualifiedReferenceScope', {})
        require(all(limits.get(k) is False for k in ('allSourceVoicesLiteralPerformanceConfirmed', 'allSingerPitchGold',
            'isolatedVoiceAttackGold', 'allPrintedWordsAcousticallyConfirmed', 'sourcePitchReplacement', 'browserPCMOriginMeasured')),
            'Occurrence reading qualification was upgraded to physical Gold')
        source.no_gold(body)
    require(version.get('rootDecisionSha256') == spec['rootV6DecisionSha256']
        and version.get('reviewInputsSha256') == decision.get('reviewInputsSha256') == spec['originalProposalSha256']
        and version.get('evidenceIndexSha256') == decision.get('evidenceIndexSha256') == spec['originalIndexSha256'],
        'Exact occurrence edition originals differ')
    indexed = {e['sha256'] for e in index.get('entries', [])}
    require(set(refs.values()) <= indexed <= hashes and all(d in indexed for d in
        (current['canonicalSha256'], current['syncSha256'], current['notationSha256'])), 'Full occurrence original index incomplete')
    for digest in indexed:
        bound(digest, hashes, resolve, True)
    owner = getattr(resolve, '__self__', resolve)
    require(not getattr(owner, 'closed', False), 'Closed original resolver')
    result = ValidatedOccurrencePreparation(_TOKEN, owner, source.encoded(spec).decode(), source.encoded(current).decode(),
        source.encoded(checked['payload']).decode())
    key = id(result)
    _LIVE[key] = (weakref.ref(result, lambda ref: _LIVE.pop(key, None)), source.sha(source.encoded(vars_without_token(result))))
    return result


def vars_without_token(result):
    return {k: v for k, v in vars(result).items() if k not in ('_token', '_owner')}


def checked_payload(result, spec, candidate, canonical, sync_raw, notation_raw, resolve):
    owner = getattr(resolve, '__self__', resolve)
    item = _LIVE.get(id(result))
    require(type(result) is ValidatedOccurrencePreparation and result._token is _TOKEN and item is not None
        and item[0]() is result and result._owner is owner and not getattr(owner, 'closed', False)
        and item[1] == source.sha(source.encoded(vars_without_token(result)))
        and result.specJSON == source.encoded(spec).decode()
        and result.identityJSON == source.encoded(identity(candidate, canonical, sync_raw, notation_raw)).decode()
        and result.normalAdmissionValidated is False and result.normalUIApproved is False,
        'Occurrence preparation is invented, borrowed, closed or stale')
    for digest in spec.values():
        if type(digest) is str and len(digest) == 64:
            source.require(source.sha(resolve(digest, raw_bytes=True)) == digest, 'Original context changed after validation')
    index = source.strict_json(resolve(spec['originalIndexSha256'], raw_bytes=True))
    for row in index['entries']:
        require(source.sha(resolve(row['sha256'], raw_bytes=True)) == row['sha256'], 'Indexed original changed after validation')
    return source.strict_json(result.payloadJSON)
