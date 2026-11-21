"""Exact Root-reviewed pitched start/end curve, with no timed rest events."""


def validate(sync, observation, source, standard_nodes):
    boundary = sync.get('sourceReadingBoundaryClock')
    if boundary is None:
        return standard_nodes
    source.require(type(boundary) is dict and
        boundary.get('schema') == 'complete-source-reading-pitched-start-and-end-boundary-clock/v1' and
        boundary.get('canonicalSha256') == sync['canonicalSha256'] and
        boundary.get('sourceAudioSha256') == sync['sourceAudioSha256'] and
        boundary.get('sourceDerivedOnly') is True and boundary.get('noRestRecordingEventCreated') is True,
        'Explicit original pitched boundary identity differs')
    source.no_gold(boundary)
    source.require(source.same(observation.get('reviewedBoundaryCoordinates'), boundary),
        'Root original start/end curve review is missing or differs')
    heads = [{k: event[k] for k in ('sourcePart', 'sourcePhysicalId', 'sourceQuarter',
        'sourceQuarterEnd', 'time', 'endTime')} for event in sync['events']]
    source.require(source.same(observation.get('all347ReviewedStartEndReferences'), heads),
        'Root original complete pitched start/end review differs')
    times = {}
    starts, ends = {}, {}
    for event in sync['events']:
        source.require(not event.get('isRest') and event['endTime'] > event['time'],
            'Pitched end curve contains a rest or inverted event')
        for q, time, groups in ((event['sourceQuarter'], event['time'], starts),
                                (event['sourceQuarterEnd'], event['endTime'], ends)):
            source.require(source.finite(q) and source.finite(time) and
                (q not in times or times[q] == time), 'Conflicting original same-quarter start/end')
            times[q] = time
            groups.setdefault(q, []).append(event['sourcePhysicalId'])
    terminal = standard_nodes[-1]
    source.require(terminal['sourceQuarter'] in times and
        times[terminal['sourceQuarter']] == terminal['time'], 'Original pitched terminal differs from approved music terminal')
    nodes = boundary.get('clock')
    expected = sorted(times)
    source.require(type(nodes) is list and len(nodes) == len(expected), 'Original complete pitched boundary inventory differs')
    for row, q in zip(nodes, expected):
        source.require(row.get('sourceQuarter') == q and row.get('time') == times[q] and
            row.get('readingEstimateOnly') is True and row.get('restEvent') is False and
            row.get('seekableRestEvent') is False and
            source.same(row.get('sourcePhysicalIds'), starts.get(q, [])) and
            source.same(row.get('sourceEndPhysicalIds'), ends.get(q, [])),
            'A source pitched boundary was omitted, moved or turned into a rest event')
    source.require(all(b['sourceQuarter'] > a['sourceQuarter'] and b['time'] > a['time']
        for a, b in zip(nodes, nodes[1:])), 'Original pitched end curve is not increasing')
    return nodes


def display_nodes(sync, standard_nodes):
    """Called only after genuine context/clock validation, never grants authority."""
    boundary = sync.get('sourceReadingBoundaryClock')
    return standard_nodes if boundary is None else boundary['clock']


def pitched_active(sync, time):
    # Match the renderer's sub-sample exact-node convention; rests stay untimed.
    return any(event['time'] <= time + 3e-6 and time < event['endTime']
        for event in sync['events'])
