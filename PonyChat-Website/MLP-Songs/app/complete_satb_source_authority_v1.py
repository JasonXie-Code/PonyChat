"""Complete pitched/rest source authority, separate from spoken-X contracts.

Mechanical XML conservation is not paper approval. Only an actual bound Root
whole-source decision can construct the source type. It does not grant clock,
recording edition, native UI, normal admission or performance Gold authority.
"""
from dataclasses import dataclass
import hashlib
import json
import re
import weakref
import xml.etree.ElementTree as ET

try:
    from .source_reading_source_v1 import read_source
except ImportError:
    from source_reading_source_v1 import read_source

PROFILE = 'complete-original-satb-source-quarter-reference/v1'
AUDIT_SCHEMA = 'complete-pitched-rest-printed-source-audit/v1'
DECISION_SCHEMA = 'root-complete-pitched-rest-printed-source-decision/v1'
SCOPE = 'all-original-physical-pitched-rest-notes-parts-and-printed-xml-markup'
REGISTRATIONS = {
    'behold-princess-twilight-sparkle-4dac5968': dict(
        sourceSongId='season-03-2012/11 - Behold, Princess Twilight Sparkle.mp3',
        sourceScoreId='Charts, Scores and Lyrics/MLP313-6_Behold Princess Twilight Sparkle_CHART.pdf',
        sourcePDFsha256='03033a0d7f82b3aa92e49a613179db0c1e806e6357fa3e03871e528fcf258893',
        sourceAudioSha256='116d0da2034e1ae6f0ab67e9c7e3eea8fb0a7dc1ba1f986190799c6af50013e1',
        physicalCounts=dict(physical=257, pitch=222, rest=35, unpitched=0, unprintedForwards=0, primary=62),
        sourceParts=[dict(id='P1', name='SOPRANO'), dict(id='P2', name='ALTO'),
                     dict(id='P3', name='TENOR'), dict(id='P4', name='BASS')], partMeasures=92),
}
AUDIT_FIELDS = {'schema', 'status', 'qualifiedReadingProfile', 'followId', 'canonicalSha256',
                'sourcePDFsha256', 'completeSourceProjection', 'completeSourceProjectionSha256', 'rootSourceDecision'}
DECISION_FIELDS = {'schema', 'status', 'reviewedBy', 'approved', 'sourcePassed', 'sourceReviewScope',
    'qualifiedReadingProfile', 'followId', 'sourceSongId', 'sourceScoreId', 'sourcePDFsha256',
    'canonicalSha256', 'physicalCounts', 'sourceParts', 'completeSourceProjectionSha256',
    'actualSourceReviewEvidenceSha256s', 'actualGeometryEvidenceSha256', 'geometryScope', 'physicalPerformanceGold'}
_TOKEN = object()
_RESULTS = {}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf8')


def same(a, b):
    return encoded(a) == encoded(b)


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def is_sha(value):
    return type(value) is str and re.fullmatch('[a-f0-9]{64}', value) is not None


def registration(follow_id):
    require(follow_id in REGISTRATIONS, 'An explicit complete SATB source registration is required')
    return json.loads(encoded(REGISTRATIONS[follow_id]))


def xml_payload(node):
    return dict(tag=node.tag, attributes=dict(node.attrib), text=node.text, tail=node.tail,
                children=[xml_payload(child) for child in node])


def complete_projection(content, follow_id):
    """Full XML payload includes all marks, harmonies, clefs, key and lyrics."""
    reg = registration(follow_id); source = read_source(content); root = ET.fromstring(content)
    rows = source['rows']; counts = reg['physicalCounts']
    require(len(rows) == len({r['sourcePhysicalId'] for r in rows}) == counts['physical'] and
        same(source['counts'], {k: counts[k] for k in ('pitch', 'rest', 'unpitched')}) and
        not source['sourceGaps'], 'Complete pitched/rest SATB source partition changed')
    require(same([dict(id=p.get('id'), name=p.findtext('part-name')) for p in root.findall('part-list/score-part')],
        reg['sourceParts']) and len(root.findall('part/measure')) == reg['partMeasures'],
        'Complete original SATB names and all part-bars required')
    require(len({r['sourceQuarter'] for r in rows if r['sourceKind'] == 'pitch'}) == counts['primary'],
        'Full original pitched-quarter denominator changed')
    return dict(schema='complete-pitched-rest-printed-source-projection/v1', followId=follow_id,
        physicalCounts=counts, sourceParts=reg['sourceParts'], physicalEvents=rows,
        wholePrintedMusicXML=xml_payload(root), sourceApproved=False, recordingSchedule=False)


def pending_source_audit(content, follow_id):
    reg = registration(follow_id); projection = complete_projection(content, follow_id)
    return dict(schema=AUDIT_SCHEMA, status='pending-root-complete-pitched-rest-source-review',
        qualifiedReadingProfile=PROFILE, followId=follow_id, canonicalSha256=hashlib.sha256(content).hexdigest(),
        sourcePDFsha256=reg['sourcePDFsha256'], completeSourceProjection=projection,
        completeSourceProjectionSha256=digest(projection), rootSourceDecision=None)


def pending_source_decision(content, follow_id):
    reg = registration(follow_id); projection = complete_projection(content, follow_id)
    return dict(schema=DECISION_SCHEMA, status='pending-root-complete-pitched-rest-source-review',
        reviewedBy=None, approved=False, sourcePassed=False, sourceReviewScope=SCOPE,
        qualifiedReadingProfile=PROFILE, followId=follow_id, sourceSongId=reg['sourceSongId'],
        sourceScoreId=reg['sourceScoreId'], sourcePDFsha256=reg['sourcePDFsha256'],
        canonicalSha256=hashlib.sha256(content).hexdigest(), physicalCounts=reg['physicalCounts'],
        sourceParts=reg['sourceParts'], completeSourceProjectionSha256=digest(projection),
        actualSourceReviewEvidenceSha256s=[], actualGeometryEvidenceSha256=None,
        geometryScope=geometry_scope(follow_id), physicalPerformanceGold=False)


def geometry_scope(follow_id):
    counts = registration(follow_id)['physicalCounts']
    return dict(pitchedHeads=counts['pitch'], pitchedHeadInkMeasured=True,
        readonlyRests=counts['rest'], restPlacementRole='original-PDF-glyph-navigation-only',
        restFullInkMeasured=False, readonlyRestSeekAllowed=False, physicalPerformanceGold=False)


def bound(digest_value, hashes, resolve, *, binary=False):
    require(is_sha(digest_value) and digest_value in hashes, 'Actual complete-source original evidence is unbound')
    raw = resolve(digest_value, raw_bytes=True)
    require(type(raw) is bytes and hashlib.sha256(raw).hexdigest() == digest_value,
            'Actual complete-source original bytes changed')
    return raw if binary else json.loads(raw)


@dataclass(frozen=True)
class ValidatedCompleteSATBSource:
    _token: object
    _owner: object
    followId: str
    canonicalSha256: str
    sourceAuditSha256: str
    sourceDecisionSha256: str
    projectionSha256: str
    normalAdmissionValidated: bool = False
    recordingOrPerformanceApproved: bool = False


def validate_source(audit_sha256, decision_sha256, canonical, follow_id, hashes, resolve):
    """Validate genuine source-only authority; no zero-X workaround or markers."""
    reg = registration(follow_id); expected = complete_projection(canonical, follow_id)
    audit = bound(audit_sha256, hashes, resolve); decision = bound(decision_sha256, hashes, resolve)
    require(type(audit) is dict and set(audit) == AUDIT_FIELDS and audit['schema'] == AUDIT_SCHEMA and
        audit['status'] == 'root-approved-complete-pitched-rest-source', 'Actual complete Root source audit is pending')
    require(type(decision) is dict and set(decision) == DECISION_FIELDS and decision['schema'] == DECISION_SCHEMA and
        decision['status'] == 'root-approved-complete-pitched-rest-printed-source' and
        decision['approved'] is True and decision['sourcePassed'] is True and decision['reviewedBy'] == '/root' and
        decision['sourceReviewScope'] == SCOPE, 'Genuine whole-source Root decision required; narrow geometry alone is insufficient')
    require(audit['qualifiedReadingProfile'] == decision['qualifiedReadingProfile'] == PROFILE and
        audit['followId'] == decision['followId'] == follow_id and same(audit['rootSourceDecision'], decision),
        'Complete source audit or Root decision belongs to another explicit profile')
    require(audit['canonicalSha256'] == decision['canonicalSha256'] == hashlib.sha256(canonical).hexdigest() and
        audit['sourcePDFsha256'] == decision['sourcePDFsha256'] == reg['sourcePDFsha256'] and
        decision['sourceSongId'] == reg['sourceSongId'] and decision['sourceScoreId'] == reg['sourceScoreId'],
        'Source identity differs from the actual whole-source Root decision')
    require(same(audit['completeSourceProjection'], expected) and
        audit['completeSourceProjectionSha256'] == decision['completeSourceProjectionSha256'] == digest(expected) and
        same(decision['physicalCounts'], reg['physicalCounts']) and same(decision['sourceParts'], reg['sourceParts']) and
        same(decision['geometryScope'], geometry_scope(follow_id)) and
        decision['physicalPerformanceGold'] is False, 'Complete notes/printed marks/parts cannot be replaced by a count or Gold marker')
    evidence = decision['actualSourceReviewEvidenceSha256s']
    require(type(evidence) is list and evidence and len(evidence) == len(set(evidence)) and
        decision['actualGeometryEvidenceSha256'] in evidence, 'Actual full-source ink/geometry review bodies missing')
    for sha in evidence:
        bound(sha, hashes, resolve, binary=True)
    paper = []
    for sha in evidence:
        raw = bound(sha, hashes, resolve, binary=True)
        try:
            item = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            continue
        if type(item) is dict and item.get('schema') == 'root-complete-original-paper-and-native-head-review/v1':
            paper.append(item)
    require(len(paper) == 1, 'One genuine complete original-paper Root observation is required')
    observation = paper[0]
    require(observation.get('reviewedBy') == '/root' and observation.get('sourceOnlyApproved') is True and
        observation.get('all92PartBarsActuallyComparedToFourOriginalSystems') is True and
        observation.get('canonical', {}).get('sha256') == decision['canonicalSha256'] and
        observation.get('originalPDF', {}).get('sha256') == reg['sourcePDFsha256'] and
        observation.get('actualGeometry', {}).get('sha256') == decision['actualGeometryEvidenceSha256'] and
        same(observation.get('allPhysicalSourceRows'), expected['physicalEvents']) and
        all(observation.get(k) is False for k in ('audioApproved', 'nativeUIApproved', 'formalAccepted',
            'performedPitchGold', 'wordGold', 'singerIdentityGold', 'physicalAttackGold', 'physicalReleaseGold')),
        'Actual original paper review does not approve this canonical/full semantic source')
    images = observation.get('actualViewedImages')
    require(type(images) is list and len(images) == 5 and len({i['sha256'] for i in images}) == 5 and
        all(i['sha256'] in evidence for i in images), 'Four actual original systems and actual wholehead contact evidence missing')
    owner = getattr(resolve, '__self__', resolve)
    require(getattr(owner, 'closed', False) is False, 'Closed complete-source evidence invocation')
    result = ValidatedCompleteSATBSource(_TOKEN, owner, follow_id, hashlib.sha256(canonical).hexdigest(),
        audit_sha256, decision_sha256, digest(expected))
    identity = id(result); _RESULTS[identity] = weakref.ref(result, lambda ref: _RESULTS.pop(identity, None))
    return result


def check_source_result(result, *, follow_id, canonical, audit_sha256, decision_sha256, resolve):
    require(type(result) is ValidatedCompleteSATBSource and result._token is _TOKEN and
        id(result) in _RESULTS and _RESULTS[id(result)]() is result and
        result._owner is getattr(resolve, '__self__', resolve) and getattr(result._owner, 'closed', False) is False and
        result.followId == follow_id and result.canonicalSha256 == hashlib.sha256(canonical).hexdigest() and
        result.sourceAuditSha256 == audit_sha256 and result.sourceDecisionSha256 == decision_sha256 and
        result.projectionSha256 == digest(complete_projection(canonical, follow_id)) and
        result.normalAdmissionValidated is False and result.recordingOrPerformanceApproved is False,
        'Source-only authority must be the live actual validated source invocation; not normal permission')
    for expected_sha in (audit_sha256, decision_sha256):
        raw = resolve(expected_sha, raw_bytes=True)
        require(type(raw) is bytes and hashlib.sha256(raw).hexdigest() == expected_sha,
            'Source authority original bytes changed after typed validation')
    return True
