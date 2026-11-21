"""Opt-in full-physical source-reading projection/layout seam, never admission.

Uses the existing typed-unpitched reference contract and ordinary Root clock
decision schema. No dispatch, legacy guard, version/UI gate or MIDI path changes.
Only validated original Root source+clock+typed references acquire X reading times.
"""
import copy
from dataclasses import dataclass
import json
import weakref
import xml.etree.ElementTree as ET
try:
    from . import typed_unpitched_reference_v1 as typed
    from .complete_ensemble_reference_v1 import pitch_midi
except ImportError:
    import typed_unpitched_reference_v1 as typed
    from complete_ensemble_reference_v1 import pitch_midi

PROFILE=typed.PROFILE
require=typed.require
same=typed.same
finite=typed.finite
encoded=typed.physical.encoded
_TOKEN=object()
_LIVE={}

def _bytes(digest,resolver):
    require(typed.physical.is_sha(digest),'Exact original evidence SHA required')
    try:raw=resolver(digest)
    except (KeyError,FileNotFoundError) as error:raise ValueError('Original evidence body missing') from error
    require(type(raw) is bytes and typed.sha(raw)==digest,'Original evidence bytes changed')
    return raw

def _body(digest,resolver):
    return json.loads(_bytes(digest,resolver))

def _opted(profile):
    require(profile==PROFILE,'Explicit typed-unpitched profile required; legacy route unchanged')

def prepare_projection(profile,canonical,notation_raw):
    """Mechanical full inventory, unscheduled unless validated separately."""
    _opted(profile)
    original=typed.inputs(canonical,notation_raw)
    notation=json.loads(notation_raw)
    tokenby={t['originalSourceNoteId']:t for t in notation['tokens']}
    entities=[]
    literal=('sourceNoteAttributes','sourceLyrics','sourceNotehead','sourceUnpitchedDisplay',
        'sourceRestPayload','sourceTimeModification','sourceBeams','sourceNotations')
    for row in original['projection']['physicalEvents']:
        token=tokenby[row['sourceNoteId']]
        for field in literal:
            require(field not in token or same(token[field],row[field]),'Literal original payload changed: '+field)
        entity=copy.deepcopy(token)
        entity.update(sourceKind=row['sourceKind'],sourcePhysicalId=row['sourceNoteId'],
            sourceQuarterEnd=row['sourceQuarter']+row['durationBeats'],
            sourceReadingTime=None,sourceReadingEndTime=None,sourceReadingOnly=True)
        for field in literal:entity[field]=copy.deepcopy(row[field])
        if row['isUnpitched']:
            entity.update(token='×',noteheadShape=row['sourceNotehead'][0]['text'],
                pitch=None,sourcePitch=None,midi=None,time=None,endTime=None,eventIndex=None,
                seekAllowed=False,cursorPrimary=False,sourceOnlyUntimed=True,skipCursorHighlight=True)
        elif row['isRest']:
            entity.update(pitch=None,sourcePitch=None,midi=None,time=None,endTime=None,eventIndex=None,
                seekAllowed=False,cursorPrimary=False,sourceOnlyUntimed=True,skipCursorHighlight=True)
        else:
            require(type(entity.get('midi')) is int and entity['midi']==pitch_midi(row['pitch']),
                'Pitched MIDI differs from original spelled source pitch')
            entity.update(time=None,endTime=None,eventIndex=None,seekAllowed=False,cursorPrimary=False,
                sourceOnlyUntimed=True,skipCursorHighlight=True)
        entities.append(entity)
    measures=[]
    for measure in notation['measures']:
        item=copy.deepcopy(measure);ids=[t['sourcePhysicalId'] for t in measure['tokens']]
        by={e['sourcePhysicalId']:e for e in entities};item['tokens']=[copy.deepcopy(by[sid]) for sid in ids]
        measures.append(item)
    parts=[dict(id=p.get('id'),name=p.findtext('part-name')) for p in ET.fromstring(canonical).findall('part-list/score-part')]
    metadata={k:copy.deepcopy(notation[k]) for k in ('title','tonic','tempo','keyRoot','referenceOctave','sourceKeyMap','printedTempoMap','sourceTempoMap','physicalStaffRows') if k in notation}
    return dict(**metadata,profile=PROFILE,canonicalSha256=typed.sha(canonical),notationSha256=typed.sha(notation_raw),
        sourceParts=parts or [dict(id=p,name=p) for p in dict.fromkeys(e['sourcePart'] for e in entities)],primaryPart=None,
        physicalCounts=original['counts'],physicalEntityCount=len(entities),entities=entities,measures=measures,
        sourceGaps=original['projection']['unprintedSourceGaps'],sourceReadingOnly=True,
        pitchedSyncEvents=[],unpitchedReferences=copy.deepcopy(original['unpitchedReferences']),
        commonClock=None,readingCoordinatesValidated=False,normalAdmissionValidated=False,formalAccepted=False)

def _source_and_clock(canonical,nr,sr,reference_decision_sha,clock_decision_sha,resolver):
    """Existing typed contract plus independent exact ordinary clock approval."""
    reference=typed.validate_root_references(canonical,nr,reference_decision_sha,resolver)
    decision=_body(reference_decision_sha,resolver)
    require(decision['pitchedSyncSha256']==typed.sha(sr),'Root typed reference binds another pitched runtime')
    sync=json.loads(sr);typed.no_gold(sync)
    audit=_body(decision['typedSourceAuditSha256'],resolver)
    # Existing typed source validator checks semantic content; additionally
    # resolve the actual original Root paper evidence it names in this seam.
    for digest in audit['rootSourceDecision']['actualSourceReviewEvidenceSha256s']:_bytes(digest,resolver)
    pdf=_bytes(decision['sourcePDFsha256'],resolver)
    require(pdf.startswith(b'%PDF-'),'Actual original PDF bytes required')
    rawclock=_body(decision['commonClockSha256'],resolver);clock=_body(clock_decision_sha,resolver)
    require(clock.get('schema')=='root-complete-ensemble-source-reading-clock-decision/v1'
        and clock.get('reviewedBy')=='/root' and clock.get('approved') is True
        and clock.get('scope')=='common-source-reading-coordinates-only-not-performance-gold',
        'Independent Root common clock approval pending')
    require(clock.get('normalAdmissionGranted') is False and clock.get('formalAccepted') is False,
        'Partial clock authority cannot grant normal admission')
    require(clock.get('canonicalSha256')==typed.sha(canonical)
        and clock.get('notationSha256')==typed.sha(nr) and clock.get('syncSha256')==typed.sha(sr)
        and clock.get('sourceAudioSha256')==decision['sourceAudioSha256']
        and same(clock.get('commonClock'),rawclock['clock']), 'Root common clock binds another exact typed tuple')
    source_decision_sha=clock.get('sourceDecisionSha256')
    require(same(_body(source_decision_sha,resolver),audit['rootSourceDecision']),
        'Root clock does not bind the complete typed physical source decision')
    typed.no_gold(clock)
    observation=_body(clock['actualClockReviewSha256'],resolver)
    require(observation.get('reviewedBy')=='/root' and observation.get('commonClockOnly') is True
        and observation.get('syncSha256')==typed.sha(sr) and observation.get('notationSha256')==typed.sha(nr)
        and observation.get('allSourceQuarterReferencesReviewed') is True
        and same(observation.get('reviewedCoordinates'),rawclock['clock']),
        'Actual Root all-coordinate clock observation missing')
    typed.no_gold(observation)
    rows=typed.physical.projection(canonical)['physicalEvents']
    pitched={r['sourceNoteId']:r for r in rows if r['sourceKind']=='pitch'}
    nodes={n['sourceQuarter']:n for n in rawclock['clock']}
    require(finite(sync.get('duration')) and sync['duration']>0,'Native original duration required')
    require(all(0<=n['time']<=sync['duration'] for n in nodes.values()),'Shared clock exceeds native original')
    events=sync['events'];eventby={e['originalSourceNoteId']:e for e in events}
    require(len(events)==len(pitched) and len(eventby)==len(events),'Only complete pitched sync domain required')
    groups={}
    for index,e in enumerate(events):
        sid=e['originalSourceNoteId'];row=pitched[sid];q=row['sourceQuarter'];end=q+row['durationBeats']
        require(e.get('eventIndex')==index and type(e.get('eventIndex')) is int
            and e.get('sourcePhysicalId')==sid and e.get('isRest') is False
            and e.get('isUnpitched',False) is False,'Pitched event identity/index differs or contains X/rest')
        require(q in nodes and end in nodes and finite(e.get('endTime'))
            and e['time']==nodes[q]['time'] and e['endTime']==nodes[end]['time']
            and 0<=e['time']<e['endTime']<=sync['duration'],'Pitched start/end not on the same reviewed quarter clock')
        require(e.get('sourceQuarterEnd')==end and e.get('sourceVoice')==row['voice']
            and e.get('chordTone') is row['chordTone'] and e.get('sourceLyric')==row['sourceLyric']
            and e.get('tieContinuation') is any(t['type']=='stop' for t in row['ties']),
            'Pitched source voice/connection/literal payload changed')
        require(type(e.get('cursorPrimary')) is bool,'Explicit pitched shared-quarter representative required')
        require('midi' not in e or type(e['midi']) is int and e['midi']==pitch_midi(row['pitch']),
            'Pitched sync MIDI differs from original pitch')
        groups.setdefault(q,[]).append(e)
    require(all(sum(e['cursorPrimary'] for e in group)==1 for group in groups.values()),
        'Pitched shared coordinate lost or gained representatives')
    return reference,rawclock,sync

@dataclass(frozen=True)
class ValidatedTypedSourceReading:
    _token:object
    _owner:object
    canonicalSha256:str
    notationSha256:str
    syncSha256:str
    typedDecisionSha256:str
    clockDecisionSha256:str
    payloadJSON:str
    normalAdmissionValidated:bool=False

def validate_source_reading(profile,canonical,nr,sr,typed_decision_sha,clock_decision_sha,resolver):
    _opted(profile)
    require(all(type(b) is bytes for b in (canonical,nr,sr)),'Actual original source/notation/runtime bytes required')
    payload=prepare_projection(profile,canonical,nr)
    reference,clock,sync=_source_and_clock(canonical,nr,sr,typed_decision_sha,clock_decision_sha,resolver)
    refs=json.loads(reference.referenceJSON);refby={r['sourceNoteId']:r for r in refs}
    eventby={e['sourcePhysicalId']:e for e in sync['events']}
    for entity in payload['entities']:
        sid=entity['sourcePhysicalId']
        if entity['isUnpitched']:
            r=refby[sid];entity.update(sourceReadingTime=r['sourceReadingTime'],sourceReadingEndTime=r['sourceReadingEndTime'])
            # Normal pitched fields stay null even after genuine coordinate review.
            require(all(entity[k] is None for k in ('pitch','sourcePitch','midi','time','endTime','eventIndex'))
                and entity['seekAllowed'] is entity['cursorPrimary'] is False,'X reference escaped readonly domain')
        elif not entity['isRest']:
            e=eventby[sid];entity.update(time=e['time'],endTime=e['endTime'],eventIndex=e['eventIndex'],
                sourceReadingTime=e['time'],sourceReadingEndTime=e['endTime'],cursorPrimary=e['cursorPrimary'],
                sourceOnlyUntimed=False,skipCursorHighlight=False,seekAllowed=True)
    by={e['sourcePhysicalId']:e for e in payload['entities']}
    for measure in payload['measures']:measure['tokens']=[copy.deepcopy(by[t['sourcePhysicalId']]) for t in measure['tokens']]
    payload.update(pitchedSyncEvents=copy.deepcopy(sync['events']),unpitchedReferences=refs,
        commonClock=copy.deepcopy(clock['clock']),readingCoordinatesValidated=True,
        sourceAudioSha256=sync['sourceAudioSha256'],duration=sync['duration'],
        typedDecisionSha256=typed_decision_sha,clockDecisionSha256=clock_decision_sha)
    owner=getattr(resolver,'__self__',resolver)
    require(not getattr(owner,'closed',False),'Closed original evidence invocation')
    result=ValidatedTypedSourceReading(_TOKEN,owner,typed.sha(canonical),typed.sha(nr),typed.sha(sr),
        typed_decision_sha,clock_decision_sha,encoded(payload).decode())
    fingerprint=typed.sha(encoded({k:v for k,v in vars(result).items() if k not in ('_token','_owner')}))
    key=id(result);_LIVE[key]=(weakref.ref(result,lambda ref:_LIVE.pop(key,None)),fingerprint)
    return result

def checked_payload(result,profile,canonical,nr,sr,resolver):
    _opted(profile);owner=getattr(resolver,'__self__',resolver);entry=_LIVE.get(id(result))
    require(type(result) is ValidatedTypedSourceReading and result._token is _TOKEN
        and entry is not None and entry[0]() is result and result._owner is owner
        and entry[1]==typed.sha(encoded({k:v for k,v in vars(result).items() if k not in ('_token','_owner')}))
        and not getattr(owner,'closed',False) and result.canonicalSha256==typed.sha(canonical)
        and result.notationSha256==typed.sha(nr) and result.syncSha256==typed.sha(sr)
        and result.normalAdmissionValidated is False,'Typed reading capability invented, borrowed, changed, closed or stale')
    # Touch the current originals again. A sealed object is not permission to
    # keep rendering after its evidence was modified or resolver replaced.
    _source_and_clock(canonical,nr,sr,result.typedDecisionSha256,result.clockDecisionSha256,resolver)
    return json.loads(result.payloadJSON)

def active_physical_entities(result,profile,canonical,nr,sr,resolver,native_time):
    require(finite(native_time),'Finite native playback time required')
    payload=checked_payload(result,profile,canonical,nr,sr,resolver)
    return [e['sourcePhysicalId'] for e in payload['entities'] if not e['isRest']
        and finite(e['sourceReadingTime']) and e['sourceReadingTime']<=native_time<e['sourceReadingEndTime']]
