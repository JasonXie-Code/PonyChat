"""Independent occurrence layout preparation, deliberately not normal admission.

Mechanical route/clock wrappers do not authorize audio, Root, UI or publishing.
No existing producer/dispatcher imports this module. A future normal adapter
must independently validate the original authority graph and bind these bytes.
"""
import copy
import json
from fractions import Fraction
import xml.etree.ElementTree as ET

try:
    from . import complete_ensemble_occurrence_v1 as occurrence
except ImportError:
    import complete_ensemble_occurrence_v1 as occurrence

PROFILE = occurrence.PROFILE
SCHEMA = 'mechanical-complete-ensemble-occurrence-layout/v1'
require = occurrence.require


def _measure_spans(canonical):
    spans = {}
    for part in ET.fromstring(canonical).findall('part'):
        q, length = Fraction(0), Fraction(4)
        for measure in part.findall('measure'):
            meter = measure.find('attributes/time')
            if meter is not None:
                length = Fraction(meter.findtext('beats')) * 4 / Fraction(meter.findtext('beat-type'))
            spans[(part.get('id'), int(measure.get('number')))] = q, q+length
            q += length
    return spans


def prepare_reference_payload(canonical, route, clock, original_model_raw):
    """One physical inventory plus many instances; never builds accepted assets."""
    require(type(canonical) is bytes and type(original_model_raw) is bytes,
        'Original canonical and model bytes required')
    require(isinstance(route, occurrence.MechanicalRoute) and isinstance(clock, occurrence.MechanicalClock),
        'Separately mechanically checked occurrence route/clock required')
    r, c = route.data(), clock.data()
    require(c['routeProjectionSha256'] == route.sha256 and c['canonicalSha256'] == r['canonicalSha256']
        == occurrence.sha(canonical), 'Original layout/route/clock canonical differs')
    original = occurrence.projection(canonical)
    require(original == r['sourceProjection'], 'Mechanical route changed actual physical source')
    model = json.loads(original_model_raw)
    require(model.get('schema') == 'prepared-complete-original-ensemble-source-model/v1'
        and model.get('canonicalSha256') == r['canonicalSha256'], 'Actual complete original source model required')
    printed_parts = [dict(id=p.get('id'), name=p.findtext('part-name'))
        for p in ET.fromstring(canonical).findall('part-list/score-part')]
    require(model.get('sourceParts') == printed_parts, 'Original printed part names/order changed')
    rows = original['physicalEvents']; by_id = {e['sourcePhysicalId']: e for e in rows}
    display = model.get('events')
    require(type(display) is list and len(display) == len(rows)
        and {e.get('id') for e in display} == set(by_id), 'Source model dropped/duplicated/invented physical ID')
    exact, _ = occurrence._exact_source_rhythm(canonical)
    spans = _measure_spans(canonical)
    physical = []
    for e in display:
        source = by_id[e['id']]
        require(e.get('part') == source['sourcePart'] and e.get('q') == source['sourceQuarter']
            and e.get('duration') == source['durationBeats'] and e.get('pitch') == source['pitch']
            and e.get('rest') is source['isRest'], 'Original physical source model semantics differ')
        point = e.get('nativePoint'); box = e.get('nativeInkBounds')
        require(type(point) is dict and all(occurrence.finite(point.get(k)) for k in ('x', 'y'))
            and type(box) is dict and all(occurrence.finite(box.get(k)) for k in ('x', 'y', 'width', 'height'))
            and box['width'] > 0 and box['height'] > 0, 'Actual native geometry missing')
        q, length = exact[e['id']]
        physical.append(dict(copy.deepcopy(source),
            **occurrence.coordinate_fields('sourceQuarter', q),
            **occurrence.coordinate_fields('sourceQuarterEnd', q+length),
            nativePoint=copy.deepcopy(point), nativeInkBounds=copy.deepcopy(box),
            time=None, endTime=None, eventIndex=None, seekAllowed=False))
    systems = model.get('originalSystems')
    require(type(systems) is list and systems and len({s.get('sourceSystemId') for s in systems}) == len(systems),
        'Unique actual original systems required')
    prepared_systems, covered, bars = [], set(), set()
    part_order = [p['id'] for p in model['sourceParts']]
    for system in systems:
        members = [e for e in physical if system['first'] <= e['measure'] <= system['last']]
        ids = {e['sourcePhysicalId'] for e in members}
        parts = [p for p in part_order if any(e['sourcePart'] == p for e in members)]
        require(ids == set(system['physicalIds']) and not covered.intersection(ids)
            and system['actualSourceParts'] == parts, 'Original system reused entities or omitted printed parts')
        covered |= ids
        lines = system.get('staffLines')
        require(type(lines) is dict and set(lines) == set(parts) and all(len(lines[p]) == 5
            and all(occurrence.finite(y) for y in lines[p]) for p in parts), 'Actual printed staff lines missing')
        derived = dict(top=min([min(lines[p]) for p in parts]+[e['nativeInkBounds']['y'] for e in members]),
            bottom=max([max(lines[p]) for p in parts]+[e['nativeInkBounds']['y']+e['nativeInkBounds']['height'] for e in members]))
        bounds = system.get('wholeSourcePartsBounds', derived)
        require(type(bounds) is dict and all(occurrence.finite(bounds.get(k)) for k in ('top', 'bottom'))
            and bounds['top'] < bounds['bottom'], 'Whole original part bounds required')
        require(all(bounds['top'] <= min(lines[p]) < max(lines[p]) <= bounds['bottom'] for p in parts),
            'Whole reading line drops an actual original staff')
        require(all(bounds['top'] <= e['nativeInkBounds']['y']
            and e['nativeInkBounds']['y']+e['nativeInkBounds']['height'] <= bounds['bottom'] for e in members),
            'Whole reading line drops actual physical ink')
        q0 = {spans[(p, system['first'])][0] for p in parts}
        q1 = {spans[(p, system['last'])][1] for p in parts}
        require(len(q0) == len(q1) == 1, 'Printed part measure origins disagree')
        a, b = next(iter(q0)), next(iter(q1))
        require(system['q0'] == float(a) and system['q1'] == float(b), 'Model printed system span differs')
        source_bars = set(range(system['first'], system['last']+1))
        require(not bars.intersection(source_bars), 'Original systems overlap printed measures')
        bars |= source_bars
        prepared_systems.append(dict(sourceSystemId=system['sourceSystemId'], firstMeasure=system['first'], lastMeasure=system['last'],
            **occurrence.coordinate_fields('sourceQuarterStart', a), **occurrence.coordinate_fields('sourceQuarterEnd', b),
            actualSourceParts=parts, physicalIds=list(system['physicalIds']), rect=copy.deepcopy(system['rect']),
            wholeSourcePartsBounds=copy.deepcopy(bounds), staffLines=copy.deepcopy(lines)))
    require(covered == set(by_id) and bars == {e['measure'] for e in physical}, 'Complete original source system coverage required')
    intervals = []
    for interval in model.get('measureBounds', []):
        key = interval['part'], interval['measure']
        owner = [s for s in prepared_systems if s['sourceSystemId'] == interval['sourceSystemId']
            and s['firstMeasure'] <= key[1] <= s['lastMeasure'] and key[0] in s['actualSourceParts']]
        require(key in spans and occurrence.finite(interval.get('x0')) and occurrence.finite(interval.get('x1'))
            and interval['x0'] < interval['x1'] and len(owner) == 1, 'Actual original part-measure interval invalid')
        a, b = spans[key]
        intervals.append(dict(part=key[0], measure=key[1], sourceSystemId=interval['sourceSystemId'],
            x0=interval['x0'], x1=interval['x1'], **occurrence.coordinate_fields('sourceQuarterStart', a),
            **occurrence.coordinate_fields('sourceQuarterEnd', b)))
    expected_measures = {(p['sourcePart'], p['measure']) for p in physical}
    require(len(intervals) == len(expected_measures)
        and {(i['part'], i['measure']) for i in intervals} == expected_measures,
        'Every printed part-measure requires its actual interval; unprinted forwards do not')
    return dict(schema=SCHEMA, profile=PROFILE, referenceOnly=True,
        canonicalSha256=r['canonicalSha256'], originalModelSha256=occurrence.sha(original_model_raw),
        routeProjectionSha256=route.sha256, mechanicalClockSha256=clock.sha256,
        physicalSource=physical, physicalCounts=original['counts'], physicalEntityCount=len(physical),
        sourceParts=copy.deepcopy(model['sourceParts']), sourceSystems=prepared_systems, measureBounds=intervals,
        sourceGaps=copy.deepcopy(original['unprintedSourceGaps']), instances=copy.deepcopy(c['instances']),
        visits=copy.deepcopy(c['visits']), curves=copy.deepcopy(c['curves']), sourceKeyPlan=copy.deepcopy(c['sourceKeyPlan']),
        nativeDuration=c['nativeDuration'], musicActiveUntilTime=c['musicActiveUntilTime'],
        requiresIndependentNormalAuthority=True, normalAdmissionValidated=False,
        clockApproved=False, RootModelApproved=False, normalUIApproved=False, formalAccepted=False,
        seekRequestsOnly=True, actualAudioClockAssignedByThisModule=False)
