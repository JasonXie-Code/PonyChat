"""Pure occurrence-route/clock mechanics for an explicit, separate profile.

This module grants no source, recording, Root, UI, certificate or admission
authority. Factories/dispatchers deliberately do not call it yet. Canonical
physical rows are unique; repeated visits live in a separate performance
coordinate. Position resolution never interpolates across a navigation edge.
"""
from bisect import bisect_right
from dataclasses import dataclass
from fractions import Fraction
import hashlib
import json
import math
import re
import xml.etree.ElementTree as ET

try:
    from .complete_ensemble_reference_v1 import projection
except ImportError:
    from complete_ensemble_reference_v1 import projection

PROFILE = 'complete-original-ensemble-occurrence-reading-reference/v1'
ROUTE = 'complete-ensemble-occurrence-route/v1'
CLOCK = 'complete-ensemble-occurrence-reading-clock/v1'
NEAR_NODE_SECONDS = 3e-6
_ENTRY_POLICY = 'source-continuation-without-recording-attack-claim'
_EXIT_POLICY = 'source-tie-cut-by-navigation-without-release-claim'


def require(value, message):
    if not value:
        raise ValueError(message)


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), allow_nan=False).encode('utf8')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def quarter(value):
    require(type(value) in (int, float, str), 'Explicit finite quarter required')
    if type(value) is float:
        require(math.isfinite(value), 'Nonfinite quarter')
    try:
        return Fraction(str(value))
    except (ValueError, ZeroDivisionError) as error:
        raise ValueError('Invalid quarter') from error


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def coordinate(body, name):
    """Fractions are authoritative; optional numeric fields are display only.

    A decimal float alone remains its exact stated decimal, never guessed to
    mean a nearby musical fraction. A paired float must equal float(fraction)
    exactly. Neither timing nor rational identity is widened with an epsilon.
    """
    fraction_name = name + 'Fraction'
    if fraction_name not in body:
        return quarter(body.get(name))
    value = quarter(body[fraction_name])
    shown = body.get(name)
    require((finite(shown) and shown == float(value))
        or (type(shown) is str and quarter(shown) == value), 'Fraction/display coordinate mismatch')
    return value


def coordinate_fields(name, value):
    return {name: float(value), name + 'Fraction': str(value)}


def no_authority(body):
    require(body.get('profile') == PROFILE and body.get('referenceOnly') is True,
        'Explicit occurrence reference profile required')
    require(all(body.get(k, False) is False for k in ('approved', 'sourceApproved',
        'clockApproved', 'normalUIApproved', 'formalAccepted', 'physicalPerformanceGold')),
        'Pure mechanics cannot grant approval or performance Gold')


@dataclass(frozen=True)
class MechanicalRoute:
    """Immutable mechanically checked bytes, not a normal authority capability."""
    body: bytes
    sha256: str

    def data(self):
        require(type(self.body) is bytes and sha(self.body) == self.sha256,
            'Occurrence route bytes changed')
        return json.loads(self.body)


@dataclass(frozen=True)
class MechanicalClock:
    body: bytes
    sha256: str

    def data(self):
        require(type(self.body) is bytes and sha(self.body) == self.sha256,
            'Occurrence clock bytes changed')
        return json.loads(self.body)


def _exact_source_rhythm(canonical):
    """Retain XML rational subdivisions across ties; do not guess from floats.

    The full projection/parser above already validates physical semantics and
    closure. This small parallel pass keeps exact arithmetic for route edges.
    """
    rhythm, length = {}, Fraction(0)
    for part in ET.fromstring(canonical).findall('part'):
        origin, divisions, meter = Fraction(0), Fraction(1), Fraction(4)
        for measure in part.findall('measure'):
            beat, prior = Fraction(0), None
            for element in measure:
                if element.tag == 'attributes':
                    if element.find('divisions') is not None:
                        divisions = Fraction(element.findtext('divisions'))
                    if element.find('time') is not None:
                        meter = Fraction(element.findtext('time/beats')) * 4 / Fraction(element.findtext('time/beat-type'))
                elif element.tag in ('backup', 'forward'):
                    delta = Fraction(element.findtext('duration')) / divisions
                    beat += delta if element.tag == 'forward' else -delta
                    prior = None
                elif element.tag == 'note':
                    duration = Fraction(element.findtext('duration')) / divisions
                    chord = element.find('chord') is not None
                    onset = prior if chord else beat
                    rhythm[element.get('id')] = (origin + onset, duration)
                    if not chord:
                        prior = onset
                        beat += duration
            origin += meter
        length = max(length, origin)
    return rhythm, length


def _ties(rows, rhythm):
    """Keep source ties separate from attacks; reject ambiguous source pairing."""
    opened, result = {}, []
    ordered = sorted(rows, key=lambda r: (r['sourcePart'], r['sourceQuarter'], r['sourceNoteIndex']))
    for row in ordered:
        if row['sourceKind'] != 'pitch':
            continue
        key = tuple(row[k] for k in ('sourcePart', 'voice', 'staff', 'pitch'))
        types = [t.get('type') for t in row['ties']]
        require(len(types) == len(set(types)) and set(types) <= {'start', 'stop'}, 'Ambiguous source tie type')
        if 'stop' in types:
            require(key in opened, 'Source tie stop has no matching printed start')
            start = opened.pop(key)
            start_q, duration = rhythm[start['sourcePhysicalId']]
            require(start_q + duration == rhythm[row['sourcePhysicalId']][0],
                'Source tie pair is not rhythmically adjacent')
            result.append((start['sourcePhysicalId'], row['sourcePhysicalId']))
        if 'start' in types:
            require(key not in opened, 'Overlapping source tie starts are ambiguous')
            opened[key] = row
    require(not opened, 'Source tie start has no printed stop')
    return result


def _policies(visit, name, allowed):
    values = visit.get(name, [])
    require(type(values) is list and all(type(v) is dict and set(v) == {'sourcePhysicalId', 'policy'}
        and v['policy'] == allowed for v in values), 'Explicit source tie boundary policy required')
    result = {v['sourcePhysicalId']: v['policy'] for v in values}
    require(len(result) == len(values), 'Duplicate tie boundary policy')
    return result


def validate_route(canonical, route):
    """Derive every visit instance from actual source; never assign audio times.

Navigation evidence hashes are locators only. An eventual authority consumer
must validate their original bytes and actual Root route/edition decision.
"""
    require(type(canonical) is bytes and type(route) is dict, 'Original source and route required')
    no_authority(route)
    require(route.get('schema') == ROUTE and route.get('canonicalSha256') == sha(canonical),
        'Occurrence route source binding differs')
    source = projection(canonical)
    rows = source['physicalEvents']
    by_id = {r['sourcePhysicalId']: r for r in rows}
    require(len(by_id) == len(rows), 'Duplicate physical source identity')
    rhythm, length = _exact_source_rhythm(canonical)
    require(set(rhythm) == set(by_id) and all(float(rhythm[r['sourcePhysicalId']][0]) == r['sourceQuarter']
        and float(rhythm[r['sourcePhysicalId']][1]) == r['durationBeats'] for r in rows),
        'Exact source rhythm differs from full physical projection')
    visits = route.get('visits')
    require(type(visits) is list and visits and all(type(v) is dict for v in visits), 'Explicit visits required')
    ids = [v.get('visitId') for v in visits]
    require(all(type(i) is str and re.fullmatch('[A-Za-z0-9_.-]+', i) for i in ids)
        and len(set(ids)) == len(ids), 'Unique visit identity required')
    zones = route.get('sourceKeyPlan')
    require(type(zones) is list and zones and all(type(z) is dict and {'sourceQuarter', 'tonic'} <= set(z)
        <= {'sourceQuarter', 'sourceQuarterFraction', 'tonic'}
        and type(z['tonic']) is str and re.fullmatch('[A-G](?:#{1,2}|b{1,2})?', z['tonic']) for z in zones),
        'Explicit printed-position tonic plan required')
    require(coordinate(zones[0], 'sourceQuarter') == 0 and all(0 <= coordinate(z, 'sourceQuarter') < length for z in zones)
        and all(coordinate(b, 'sourceQuarter') > coordinate(a, 'sourceQuarter') for a, b in zip(zones, zones[1:])),
        'Source tonic zones must start at zero and increase')
    source_pairs = _ties(rows, rhythm)
    zones = [dict(z, **coordinate_fields('sourceQuarter', coordinate(z, 'sourceQuarter'))) for z in zones]
    visits = [dict(v) for v in visits]
    instances, visit_members = [], {}
    previous = None
    for visit in visits:
        a, b, p, end = (coordinate(visit, k) for k in ('sourceStart', 'sourceEnd', 'performanceStart', 'performanceEnd'))
        for name, value in zip(('sourceStart', 'sourceEnd', 'performanceStart', 'performanceEnd'), (a, b, p, end)):
            visit.update(coordinate_fields(name, value))
        require(0 <= a < b <= length and 0 <= p < end and end-p == b-a, 'Visit changes source span or rhythmic length')
        if previous is None:
            require(p == 0 and visit.get('incomingEdge') == 'start', 'Explicit performance origin required')
        else:
            require(p == coordinate(previous, 'performanceEnd'), 'Performance visit gap/overlap')
            jumping = a != coordinate(previous, 'sourceEnd')
            require((jumping and visit.get('incomingEdge') in ('DS', 'DC', 'ToCoda', 'repeat', 'reviewed-jump'))
                or (not jumping and visit.get('incomingEdge') == 'continue'), 'Missing or false navigation edge')
            if jumping:
                evidence = visit.get('navigationEvidenceSha256s')
                require(type(evidence) is list and evidence and len(set(evidence)) == len(evidence)
                    and all(type(d) is str and re.fullmatch('[0-9a-f]{64}', d) for d in evidence),
                    'Navigation needs explicit original evidence locators, not automatic repeat inference')
        members = [r for r in rows if a <= rhythm[r['sourcePhysicalId']][0] < b]
        require(members, 'Visit has no physical source')
        require(not any(start < a < start+duration for start, duration in rhythm.values()),
            'Visit starts inside a source entity')
        require(all(sum(rhythm[r['sourcePhysicalId']]) <= b for r in members),
            'Source entity straddles navigation boundary')
        visit_members[visit['visitId']] = {r['sourcePhysicalId'] for r in members}
        for row in members:
            if row['sourceKind'] == 'rest':
                continue
            sq, duration = rhythm[row['sourcePhysicalId']]
            pq = p + sq-a
            tonic = next(z['tonic'] for z in reversed(zones) if coordinate(z, 'sourceQuarter') <= sq)
            instance = dict(occurrenceId=visit['visitId'] + ':' + row['sourcePhysicalId'],
                visitId=visit['visitId'], sourcePhysicalId=row['sourcePhysicalId'], sourcePart=row['sourcePart'],
                sourceKind=row['sourceKind'],
                pitch=row['pitch'], sourceLyric=row['sourceLyric'], localTonic=tonic,
                tieContinuation=any(t['type'] == 'stop' for t in row['ties']),
                time=None, endTime=None, eventIndex=None, physicalPerformanceGold=False,
                noteAttackGold=False, physicalGateEndTime=None,
                recordingPitchUnconfirmed=True, recordingLyricUnconfirmed=True)
            for name, value in (('sourceQuarter', sq), ('sourceQuarterEnd', sq+duration),
                    ('performanceQuarter', pq), ('performanceQuarterEnd', pq+duration)):
                instance.update(coordinate_fields(name, value))
            instances.append(instance)
        previous = visit
    require(instances, 'Route has no nonrest source references')
    covered = set().union(*visit_members.values())
    unvisited = route.get('sourceOnlyUnvisitedIds')
    require(type(unvisited) is list and all(type(sid) is str for sid in unvisited) and len(set(unvisited)) == len(unvisited)
        and set(unvisited) == set(by_id)-covered, 'Explicit unvisited source inventory differs')
    by_occ = {e['occurrenceId']: e for e in instances}
    for index, visit in enumerate(visits):
        vid = visit['visitId']; members = visit_members[vid]
        entries = _policies(visit, 'entryTiePolicies', _ENTRY_POLICY)
        exits = _policies(visit, 'exitTiePolicies', _EXIT_POLICY)
        used_entry, used_exit = set(), set()
        for start, stop in source_pairs:
            dest = by_occ.get(vid + ':' + stop)
            origin = by_occ.get(vid + ':' + start)
            if dest:
                if origin is None and index and visit['incomingEdge'] == 'continue':
                    origin = by_occ.get(visits[index-1]['visitId'] + ':' + start)
                if origin:
                    dest['continuationOfOccurrenceId'] = origin['occurrenceId']
                else:
                    require(stop in entries, 'Tie continuation entered without explicit boundary policy')
                    dest['entryTiePolicy'] = entries[stop]; used_entry.add(stop)
            if origin and start in members and stop not in members:
                next_visit = visits[index+1] if index+1 < len(visits) else None
                carries = next_visit and next_visit['incomingEdge'] == 'continue' and stop in visit_members[next_visit['visitId']]
                if not carries:
                    require(start in exits, 'Tie leaves route without explicit boundary policy')
                    origin['exitTiePolicy'] = exits[start]; used_exit.add(start)
        require(set(entries) == used_entry and set(exits) == used_exit, 'Unused/invented tie policy')
    body = dict(schema='mechanically-checked-occurrence-route/v1', profile=PROFILE,
        canonicalSha256=sha(canonical), routeSha256=sha(encoded(route)), sourceProjection=source,
        visits=visits, sourceKeyPlan=zones, instances=instances, sourceOnlyUnvisitedIds=unvisited,
        physicalEntityCount=len(rows), physicalCounts=source['counts'],
        readonlyRestIds=[r['sourcePhysicalId'] for r in rows if r['isRest']],
        occurrenceCount=len(instances), rationalCoordinateContract='explicit-fraction-with-exact-display-projection/v1',
        mechanicalOnly=True, normalAdmissionValidated=False,
        physicalPerformanceGold=False)
    raw = encoded(body)
    return MechanicalRoute(raw, sha(raw))


def validate_clock(route, clock):
    """Check supplied complete coordinates, without inferring/fitting any time."""
    require(isinstance(route, MechanicalRoute) and type(clock) is dict, 'Checked route and explicit clock required')
    data = route.data(); no_authority(clock)
    require(clock.get('schema') == CLOCK and clock.get('routeProjectionSha256') == route.sha256,
        'Occurrence clock has another route projection')
    require(finite(clock.get('nativeDuration')) and clock['nativeDuration'] > 0, 'Actual duration required')
    curves = clock.get('visits')
    require(type(curves) is list and all(type(c) is dict for c in curves)
        and [c.get('visitId') for c in curves] == [v['visitId'] for v in data['visits']],
        'Clock omitted/reordered/duplicated a visit')
    prepared, instances, previous_end, pitched_index = [], [], None, 0
    for visit, curve in zip(data['visits'], curves):
        events = [e for e in data['instances'] if e['visitId'] == visit['visitId']]
        expected = {coordinate(visit, 'performanceStart'), coordinate(visit, 'performanceEnd')}
        expected |= {coordinate(e, k) for e in events for k in ('performanceQuarter', 'performanceQuarterEnd')}
        nodes = curve.get('nodes')
        require(type(nodes) is list and all(type(n) is dict for n in nodes) and len(nodes) == len(expected)
            and [coordinate(n, 'performanceQuarter') for n in nodes] == sorted(expected),
            'Every occurrence start/end and visit boundary required exactly once')
        require(all(finite(n.get('time')) and 0 <= n['time'] <= clock['nativeDuration']
            and finite(n.get('uncertaintySeconds')) and n['uncertaintySeconds'] >= 0 for n in nodes),
            'Unbounded occurrence reading time/uncertainty')
        require(all(b['time'] > a['time'] for a, b in zip(nodes, nodes[1:])), 'Collapsed/backward occurrence clock')
        require(previous_end is None or nodes[0]['time'] >= previous_end, 'Overlapping visit clocks are ambiguous')
        previous_end = nodes[-1]['time']
        times = {coordinate(n, 'performanceQuarter'): n['time'] for n in nodes}
        for event in events:
            e = dict(event)
            start, end = (times[coordinate(e, k)] for k in ('performanceQuarter', 'performanceQuarterEnd'))
            e.update(sourceReadingTime=start, sourceReadingEndTime=end)
            if e['sourceKind'] == 'pitch':
                e.update(time=start, endTime=end, eventIndex=pitched_index)
                pitched_index += 1
            else:
                e.update(pitch=None, midi=None, seekAllowed=False)
            instances.append(e)
        prepared.append(dict(visitId=visit['visitId'], nodes=[dict(n,
            **coordinate_fields('performanceQuarter', coordinate(n, 'performanceQuarter'))) for n in nodes]))
    require(clock.get('musicActiveUntilTime') == previous_end and clock.get('clearMusicCursorAtOrAfterTerminal') is True,
        'Explicit music terminal differs from final visit; never stretch to EOF')
    body = dict(schema='mechanically-checked-occurrence-clock/v1', profile=PROFILE,
        routeProjectionSha256=route.sha256, inputClockSha256=sha(encoded(clock)),
        canonicalSha256=data['canonicalSha256'], nativeDuration=clock['nativeDuration'],
        musicActiveUntilTime=previous_end, visits=data['visits'], sourceKeyPlan=data['sourceKeyPlan'],
        curves=prepared, instances=instances,
        readonlyRestIds=data['readonlyRestIds'], mechanicalOnly=True, normalAdmissionValidated=False,
        physicalPerformanceGold=False, rationalCoordinateContract=data['rationalCoordinateContract'])
    raw = encoded(body)
    return MechanicalClock(raw, sha(raw))


def resolve_position(clock, native_time):
    """One common position across parts. Raw native time is returned unchanged."""
    require(isinstance(clock, MechanicalClock), 'Mechanically checked occurrence clock required')
    data = clock.data()
    require(finite(native_time) and native_time >= 0, 'Invalid native time')
    if native_time >= data['nativeDuration']:
        return None
    near = {n['time'] for c in data['curves'] for n in c['nodes'] if abs(n['time']-native_time) <= NEAR_NODE_SECONDS}
    require(len(near) <= 1, 'Ambiguous numerical reading-node equivalence')
    reading_time = next(iter(near)) if near else native_time
    if reading_time >= data['musicActiveUntilTime']:
        return None
    candidates = [(v, c) for v, c in zip(data['visits'], data['curves'])
        if c['nodes'][0]['time'] <= reading_time < c['nodes'][-1]['time']]
    require(len(candidates) <= 1, 'Ambiguous current visit')
    if not candidates:
        return None
    visit, curve = candidates[0]
    nodes = curve['nodes']; i = bisect_right([n['time'] for n in nodes], reading_time)
    a, b = nodes[i-1], nodes[i]
    ratio = (quarter(reading_time)-quarter(a['time'])) / (quarter(b['time'])-quarter(a['time']))
    pq = coordinate(a, 'performanceQuarter') + ratio * (coordinate(b, 'performanceQuarter')-coordinate(a, 'performanceQuarter'))
    active = [e for e in data['instances'] if e['visitId'] == visit['visitId']
        and e['sourceReadingTime'] <= reading_time < e['sourceReadingEndTime']]
    if not active:
        return None
    sq = coordinate(visit, 'sourceStart') + pq-coordinate(visit, 'performanceStart')
    tonic = next(z['tonic'] for z in reversed(data['sourceKeyPlan']) if coordinate(z, 'sourceQuarter') <= sq)
    return dict(visitId=visit['visitId'], **coordinate_fields('performanceQuarter', pq),
        **coordinate_fields('sourceQuarter', sq), localTonic=tonic,
        actualNativeTime=native_time, readingCoordinateTime=reading_time,
        activeOccurrenceIds=[e['occurrenceId'] for e in active],
        activePhysicalIds=[e['sourcePhysicalId'] for e in active],
        activeSourceParts=sorted({e['sourcePart'] for e in active}),
        activeUnpitchedOccurrenceIds=[e['occurrenceId'] for e in active if e['sourceKind'] == 'unpitched'],
        commonReadingLineCount=1, mechanicalOnly=True, normalAdmissionValidated=False)
