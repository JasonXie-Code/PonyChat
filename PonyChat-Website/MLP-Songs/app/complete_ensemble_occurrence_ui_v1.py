"""Actual native evidence predicates for the explicit occurrence profile only.

No observations or Root decisions are generated here. Physical and performance
denominators stay distinct, and every occurrence requires its explicit action.
"""
import json

try:
    from . import complete_ensemble_occurrence_normal_v1 as context
    from . import complete_ensemble_normal_v1 as geometry
    from . import complete_ensemble_occurrence_frame_preparation_v1 as _frame_preparation
except ImportError:
    import complete_ensemble_occurrence_normal_v1 as context
    import complete_ensemble_normal_v1 as geometry
    import complete_ensemble_occurrence_frame_preparation_v1 as _frame_preparation

source, require, same, bound = context.source, context.require, context.same, context.bound
PROFILE = context.PROFILE
KIND = 'typed-complete-ensemble-occurrence-normal-ui/v1'
SCOPES = {(1280, 'staff'), (1280, 'jianpu'), (375, 'staff'), (375, 'jianpu')}


def frame_at(frame, width, mode, expected, notation, canonical, payload):
    require(frame.get('visitId') == expected['visitId'] and frame.get('localTonic') == expected['localTonic']
        and same(frame.get('activeOccurrenceIds'), expected['activeOccurrenceIds']), 'Actual frame chose another occurrence, visit or tonic')
    structure = _frame_preparation._prepared_structure(canonical)
    geometry.frame_at(frame, width, mode, expected['sourceQuarter'], notation, structure, payload['sourceSystems'])


@_frame_preparation._validation_invocation
def native_scopes(actions, readonly, candidate, notation, canonical, clock, payload, hashes, resolve):
    read = geometry._capture_reader(hashes, resolve)
    pitched = [e for e in payload['instances'] if e['sourceKind'] == 'pitch']
    visited = {e['sourcePhysicalId'] for e in pitched}
    readonly_ids = {p['sourcePhysicalId'] for p in payload['physicalSource'] if p['sourcePhysicalId'] not in visited}
    require(type(actions) is list and len(actions) == len(pitched)*4
        and type(readonly) is list and len(readonly) == len(readonly_ids)*4, 'Four complete occurrence/readonly inventories required')
    for width, mode in SCOPES:
        rows = [r for r in actions if (r['width'], r['view']) == (width, mode)]
        require(len(rows) == len(pitched) and {r['occurrenceId'] for r in rows} == {e['occurrenceId'] for e in pitched},
            'Native scope omitted, duplicated or collapsed a repeated source occurrence')
        for row in rows:
            event = next(e for e in pitched if e['occurrenceId'] == row['occurrenceId'])
            raw = read(row)
            require(raw.get('width') == width and raw.get('mode') == mode and raw.get('action') in ('native-Enter', 'native-double-click')
                and raw.get('sourcePhysicalId') == event['sourcePhysicalId'] and raw.get('occurrenceId') == event['occurrenceId']
                and raw.get('selectedOccurrenceId') == event['occurrenceId'] and raw.get('sourceFragment') == 'start',
                'Actual native action/physical/occurrence identity differs')
            multiple = sum(e['sourcePhysicalId'] == event['sourcePhysicalId'] for e in pitched) > 1
            if multiple:
                require(raw.get('occurrenceChoiceAction') == 'native-explicit-choice'
                    and raw.get('choiceOccurrenceId') == event['occurrenceId']
                    and same(raw.get('beforeMenuAudio'), raw.get('openedMenuAudio')), 'Repeated head was implicitly selected or menu opening sought')
            state = raw['after']
            geometry.audio_at(state['audio'], candidate, event['time'], True)
            expected = context.mechanics.resolve_position(clock, state['frame']['time'])
            require(expected is not None and event['occurrenceId'] in expected['activeOccurrenceIds']
                and abs(state['frame']['time']-state['audio']['time']) <= .003
                and state['frame'].get('selectedSourcePhysicalId') == event['sourcePhysicalId']
                and state['frame'].get('selectedOccurrenceId') == event['occurrenceId'], 'Actual native focused occurrence or frame clock differs')
            frame_at(state['frame'], width, mode, expected, notation, canonical, payload)
        rows = [r for r in readonly if (r['width'], r['view']) == (width, mode)]
        require(len(rows) == len(readonly_ids) and {r['sourcePhysicalId'] for r in rows} == readonly_ids,
            'Every printed rest/X must remain readonly in all scopes')
        for row in rows:
            raw = read(row)
            require(raw.get('action') == 'readonly-DOM-inspection' and raw.get('sourcePhysicalId') == row['sourcePhysicalId']
                and raw.get('width') == width and raw.get('mode') == mode and raw.get('seekEmitted') is False
                and all(raw.get(k) is None for k in ('timeAttribute', 'endTimeAttribute', 'eventIndexAttribute', 'tabindexAttribute'))
                and same(raw['beforeParentAudio'], raw['afterParentAudio']), 'Readonly source acquired ordinary seek/clock attributes')
            geometry.audio_at(raw['afterParentAudio'], candidate)
    return True


def performance_map(candidate, canonical, sync_raw, notation_raw, payload):
    return dict(schema='complete-ensemble-occurrence-source-reading-map/v1', qualifiedReadingProfile=PROFILE,
        **context.identity(candidate, canonical, sync_raw, notation_raw),
        physicalSourceIds=[p['sourcePhysicalId'] for p in payload['physicalSource']],
        physicalCounts=payload['physicalCounts'], sourceGaps=payload['sourceGaps'],
        visits=payload['visits'], curves=payload['curves'], instances=payload['instances'],
        sourceKeyPlan=payload['sourceKeyPlan'], musicActiveUntilTime=payload['musicActiveUntilTime'],
        nativeDuration=payload['nativeDuration'], physicalPerformanceGold=False)


@_frame_preparation._validation_invocation
def validate_browser(browser, candidate, canonical, sync_raw, notation_raw, spec, cap, hashes, resolve):
    payload = context.checked_payload(cap, spec, candidate, canonical, sync_raw, notation_raw, resolve)
    checked = context.validate_source_clock(spec, candidate, canonical, sync_raw, notation_raw, hashes, resolve)
    context.validate_model(spec, checked, hashes, resolve)
    notation = source.strict_json(notation_raw)
    require(browser.get('schema') == 'actual-complete-ensemble-occurrence-native-browser-audit/v1'
        and browser.get('status') == 'passed' and browser.get('qualifiedReadingProfile') == PROFILE
        and all(browser.get(k) == v for k, v in checked['currentIdentity'].items())
        and same(browser.get('frontend'), candidate.get('frontend'))
        and browser.get('sourceModelDecisionSha256') == spec['sourceModelDecisionSha256'], 'Actual occurrence native browser audit pending or stale')
    native_scopes(browser.get('actions'), browser.get('readonlyActions'), candidate, notation,
        canonical, checked['clock'], payload, hashes, resolve)
    inventories = browser.get('sourceInventories', [])
    require(len(inventories) == 4 and {(r['width'], r['view']) for r in inventories} == SCOPES,
        'Four actual physical/fragment inventories required')
    read = geometry._capture_reader(hashes, resolve)
    pitched_ids = {e['sourcePhysicalId'] for e in payload['instances'] if e['sourceKind'] == 'pitch'}
    physical_ids = {p['sourcePhysicalId'] for p in payload['physicalSource']}
    for row in inventories:
        raw = read(row);fragments = raw['fragments']
        require(raw.get('width') == row['width'] and raw.get('mode') == row['view']
            and {f['sourcePhysicalId'] for f in fragments} == physical_ids, 'Actual fragment/source inventory differs')
        targets = [f for f in fragments if f['role'] == 'button']
        require(len(targets) == len(pitched_ids) and {f['sourcePhysicalId'] for f in targets} == pitched_ids,
            'Repeated visual fragment gained a second native target')
        for fragment in fragments:
            require(all(fragment.get(k) is None for k in ('timeAttribute', 'eventIndexAttribute')),
                'A physical fragment acquired an implicit occurrence time')
            if fragment['role'] == 'button':
                require(fragment['sourceFragment'] == 'start' and fragment.get('tabindexAttribute') == '0', 'Continuation became a seek target')
            else:
                require(fragment['role'] == 'img' and fragment.get('tabindexAttribute') is None, 'Readonly fragment became interactive')
    photos = browser.get('screenshots', [])
    require(len(photos) == 4 and {(p['width'], p['view']) for p in photos} == SCOPES
        and len({p['sha256'] for p in photos}) == 4, 'Four actual screenshot scopes required')
    for photo in photos:
        raw = bound(photo['sha256'], hashes, resolve, True)
        require(raw.startswith(b'\x89PNG\r\n\x1a\n') or raw.startswith(b'\xff\xd8\xff'), 'Actual browser image original required')
    read = geometry._capture_reader(hashes, resolve)
    zero, visible, clear, eof = set(), set(), set(), set()
    visited, x_seen = set(), set()
    for row in browser.get('naturalPlayback', []):
        scope = row['width'], row['view'];raw = read(row);audio, frame = raw['audio'], raw['frame']
        require(scope in SCOPES and raw.get('nativeContinuousPlayback') is True and raw.get('seekDuringPlayback') is False,
            'Natural occurrence playback used seeking or another scope')
        geometry.audio_at(audio, candidate)
        require(source.finite(frame['time']) and 0 <= audio['time']-frame['time'] <= .15, 'Actual frame time ahead/stale')
        expected = context.mechanics.resolve_position(checked['clock'], frame['time'])
        if audio['time'] < .003:
            zero.add(scope)
        if expected is not None:
            require(audio['paused'] is False, 'Visible natural occurrence was not playing')
            frame_at(frame, *scope, expected, notation, canonical, payload)
            visible.add(scope);visited.add((*scope, expected['visitId']))
            x_seen.update((*scope, oid) for oid in expected['activeUnpitchedOccurrenceIds'])
        else:
            require(frame['cursorLineCount'] == 0 and frame.get('sourceQuarter') is None,
                'Visit gap/preroll/terminal retained a source line or coordinate')
        if payload['musicActiveUntilTime'] <= frame['time'] < audio['duration'] and not audio['paused'] and not audio['ended']:
            clear.add(scope)
        if audio['ended']:
            require(audio['paused'] is True and abs(audio['time']-audio['duration']) < .003 and frame['cursorLineCount'] == 0,
                'Actual occurrence EOF did not finish with clear cursor')
            eof.add(scope)
    require(zero == visible == clear == eof == SCOPES, 'Four actual zero/playing/playing-terminal-clear/EOF scopes required')
    require(visited == {(*scope, v['visitId']) for scope in SCOPES for v in payload['visits']}, 'Natural playback omitted a source return/visit')
    require(x_seen == {(*scope, e['occurrenceId']) for scope in SCOPES for e in payload['instances'] if e['sourceKind']=='unpitched'},
        'Actual natural source-X occurrence coverage incomplete')
    nav = browser.get('navigation', [])
    require({r['test'] for r in nav} >= {'manual-scroll', 'resume', 'size', 'expanded-exit', 'play-pause'}, 'Actual native navigation incomplete')
    for row in nav:
        require(read(row).get('passed') is True, 'Actual occurrence navigation failed')
    return True


def validate_ui(ui_spec, spec, candidate, canonical, sync_raw, notation_raw, cap, hashes, resolve):
    require(type(ui_spec) is dict and set(ui_spec) == {'kind', 'browserAuditSha256', 'performanceMapSha256', 'rootNormalUIDecisionSha256'}
        and ui_spec['kind'] == KIND, 'Explicit occurrence UI evidence required')
    payload = context.checked_payload(cap, spec, candidate, canonical, sync_raw, notation_raw, resolve)
    browser = bound(ui_spec['browserAuditSha256'], hashes, resolve)
    validate_browser(browser, candidate, canonical, sync_raw, notation_raw, spec, cap, hashes, resolve)
    decision = bound(ui_spec['rootNormalUIDecisionSha256'], hashes, resolve)
    current = context.identity(candidate, canonical, sync_raw, notation_raw)
    require(decision.get('schema') == 'root-complete-ensemble-occurrence-normal-ui-decision/v1'
        and decision.get('reviewedBy') == '/root' and decision.get('approved') is True
        and decision.get('scope') == 'current-normal-native-complete-occurrence-source-reading-only'
        and decision.get('qualifiedReadingProfile') == PROFILE and all(decision.get(k)==v for k,v in current.items())
        and decision.get('browserAuditSha256') == ui_spec['browserAuditSha256']
        and same(decision.get('normalContext'), spec) and same(decision.get('frontend'), candidate.get('frontend')),
        'Actual Root whole-occurrence native UI decision missing/stale')
    source.no_gold(decision)
    mapping = bound(ui_spec['performanceMapSha256'], hashes, resolve)
    require(same(mapping, performance_map(candidate, canonical, sync_raw, notation_raw, payload)), 'Occurrence performance map changed')
    return dict(profile=PROFILE, actualNativeUIValidated=True, formalAccepted=False,
        pitchedOccurrenceIds=[e['occurrenceId'] for e in payload['instances'] if e['sourceKind']=='pitch'])
