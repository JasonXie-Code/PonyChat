"""Actual Root V6 edition context for a complete pitched/rest SATB reference.

Source/clock approvals remain separate live types. This context is not a UI
approval, public capability or admission, and never confirms performer Gold.
"""
from dataclasses import dataclass
import copy
import hashlib
import json
import weakref

try:
    from . import complete_satb_source_authority_v1 as source
    from . import complete_satb_clock_authority_v1 as clock
except ImportError:
    import complete_satb_source_authority_v1 as source
    import complete_satb_clock_authority_v1 as clock

PROFILE=source.PROFILE
KIND='typed-complete-satb-normal-reference-context/v1'
REFS=('versionAuditSha256','rootV6DecisionSha256','originalProposalSha256','originalIndexSha256',
      'sourceAuditSha256','sourceDecisionSha256','clockDecisionSha256','actualGeometryEvidenceSha256')
EVIDENCE=('sourceAuditSha256','sourceDecisionSha256','clockDecisionSha256','actualGeometryEvidenceSha256',
          'quarterClockEvidenceSha256','sampleEvidenceSha256','nativeClockEvidenceSha256',
          'independentNoHintEvidenceSha256','actualPublicBrowserClockSha256','publicAudioByteProofSha256')
IDENTITY=('followId','sourceSongId','sourceScoreId','sourcePDFsha','canonicalSha256','sourceAudioSha256','syncSha256','notationSha256')
LIMITS=('allSourceVoicesLiteralPerformanceConfirmed','allSingerPitchGold','isolatedVoiceAttackGold',
        'allPrintedWordsAcousticallyConfirmed','sourcePitchReplacement','browserPCMOriginMeasured','isolatedVoiceReleaseGold','physicalPerformanceGold')
require,same=source.require,source.same
_TOKEN=object();_LIVE={}


def strict_json(raw):
    def pairs(items):
        out={}
        for k,v in items:require(k not in out,'Duplicate normal evidence JSON key');out[k]=v
        return out
    def invalid(value):raise ValueError('Nonfinite normal evidence: '+value)
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=invalid)


def body(digest,hashes,resolve):
    value=strict_json(source.bound(digest,hashes,resolve,binary=True))
    require(type(value) is dict,'Actual normal original JSON object required');return value


def identity(candidate,sync_raw,notation_raw,canonical):
    value,_,_=clock.identity(candidate,sync_raw,notation_raw,canonical)
    value['sourcePDFsha']=value.pop('sourcePDFsha256')
    return {k:value[k] for k in IDENTITY}


def evidence_refs(clock_sha,decision):
    return {k:clock_sha if k=='clockDecisionSha256' else decision[k] for k in EVIDENCE}


def complete_original_bindings(decision,candidate,hashes,resolve):
    """Original bodies actually consumed by source/native/nohint validators."""
    required=set(evidence_refs('0'*64,decision).values())-{'0'*64}
    required.update((candidate['sourcePDFsha256'],candidate['sourceAudioSha256']))
    root=body(decision['sourceDecisionSha256'],hashes,resolve)
    required.update(root['actualSourceReviewEvidenceSha256s'])
    native=body(decision['nativeClockEvidenceSha256'],hashes,resolve)
    required.update(row['sha256'] for row in native['evidence'])
    nohint=body(decision['independentNoHintEvidenceSha256'],hashes,resolve)
    required.update(nohint[k]['sha256'] for k in ('resourcePreflight','rawSegmentLog'))
    samples=body(decision['sampleEvidenceSha256'],hashes,resolve)
    required.add(samples['decodedNativePCM']['sha256'])
    return required


def scope(candidate,canonical):
    original=source.complete_projection(canonical,candidate['id'])
    return dict(kind='complete-original-SATB-source-quarter-reference-only',
        physicalCounts=original['physicalCounts'],sourceParts=original['sourceParts'],
        allPhysicalSourceEntriesIncluded=True,allPitchedQuarterCoordinatesIncluded=True,
        readonlyRestTimingOrSeek=False,unpitchedOrForwardEntriesInvented=False,
        sourcePitchReplacement=False,isolatedSingerPitchAttackReleaseOrWordGold=False,
        publicPCMOriginMeasured=False)


def music_projection(candidate,sync_raw,notation_raw):
    """Complete current musical/metadata body; lifecycle is checked separately."""
    song=copy.deepcopy(candidate)
    for key in ('quality','acceptance','generated','attempts'):song.pop(key,None)
    song['charts']=[p.removeprefix('/follow-media') if p.startswith('/follow-media/') else p for p in song['charts']]
    sync=strict_json(sync_raw);sync.pop('accepted',None)
    return source.digest(dict(song=song,sync=sync,jianpu=strict_json(notation_raw)))


def compatibility_aliases(candidate,sync_raw,notation_raw,canonical,clock_sha,decision):
    """Old certificate field names retain qualified source-only semantics.

    Uncertainty masks come from the actual complete source denominator. Sparse
    mix recognition does not confirm each printed word or any isolated voice.
    Printed rests are distinct from unresolved/X source-head options.
    """
    _,original,reps,heads,rests=clock.reading_projection(candidate,sync_raw,notation_raw,canonical)
    sync=strict_json(sync_raw);unknown=[r['eventIndex'] for r in heads]
    secondary=[e['eventIndex'] for e in sync['events'] if e['cursorPrimary'] is False]
    parts=[p['id'] for p in original['sourceParts']]
    qualification='Complete original SATB source-quarter reading reference; isolated performed voices, words and attacks/releases remain unconfirmed.'
    limitations=[f'All {len(heads)} written pitch and word references remain recording-unconfirmed.',
        f'Only {len(reps)} shared source-quarter coordinates are automatic; {len(secondary)} other heads remain manually addressable.',
        f'All {len(rests)} printed rests are untimed, readonly source navigation with no seek or full-glyph ink claim.',
        'Sparse unforced mix recognition is partial; missing recognition does not prove absence.',
        'Source-known frequency windows are not independent singer pitch evidence.',
        'Historical DTW raw path and independent CTC raw body are unavailable; neither is fabricated.',
        'Native-to-browser offset is a reviewed reading convention, not a measured PCM origin.']
    correspondence=dict(status='pending-Root-qualified-correspondence-review',sourceReferenceOnly=True,
        completeSourceQuarterReference=True,literalAllVoicesPerformanceConfirmed=False,
        evidence=[dict(kind=kind,sha256=digest) for kind,digest in (
            ('source-structure',decision['sourceAuditSha256']),
            ('qualified-common-source-reading-clock',clock_sha),
            ('source-known-native-context-windows',decision['sampleEvidenceSha256']),
            ('sparse-independent-unforced-mix-recognition',decision['independentNoHintEvidenceSha256']))])
    return dict(readonlySourceOptions=[],readonlyRestIds=rests,displayLimitations=limitations,
        qualification=qualification,primaryContextTimingOnly=True,
        pitchUnconfirmedEventIndices=unknown,manualSecondaryEventIndices=secondary,
        recordingLyricUnconfirmedEventIndices=unknown.copy(),unknownSourceVoicesUnisolated=parts,
        overallPrimaryMelodyAndStructureCorrespondence=correspondence)


def validate_compatibility_aliases(value,aliases,stage,root_decision_sha=None):
    for k,v in aliases.items():
        if k!='overallPrimaryMelodyAndStructureCorrespondence':
            require(same(value.get(k),v),'Normal V6 source-derived certificate alias differs: '+k)
    actual=copy.deepcopy(value.get('overallPrimaryMelodyAndStructureCorrespondence'))
    require(type(actual) is dict,'Qualified source correspondence alias is missing')
    expected=copy.deepcopy(aliases['overallPrimaryMelodyAndStructureCorrespondence'])
    if stage=='review':
        require(actual.pop('rootDecisionSha256',None)==root_decision_sha,'Root-reviewed correspondence alias refers to another genuine V6 decision')
    if stage in ('review','decision'):expected['status']='reviewed-qualified'
    require(same(actual,expected),'Qualified source correspondence alias invented literal performance or changed original facts')
    return True


def pending_proposal(candidate,sync_raw,notation_raw,canonical,clock_sha,decision):
    """Truthful unsigned facts. The caller supplies actual original Root clock."""
    expected=identity(candidate,sync_raw,notation_raw,canonical)
    require(all(decision.get('sourcePDFsha256' if k=='sourcePDFsha' else k)==v for k,v in expected.items()),
        'Pending context facts must refer to the actual current Root clock')
    return dict(schema='qualified-original-score-reference-proposal/v6',status='pending-root-qualified-source-reference-review',
        referenceContractVersion=6,qualifiedReadingProfile=PROFILE,relation='qualified-original-score-reference',
        **expected,completeSATBEvidence=evidence_refs(clock_sha,decision),
        qualifiedReferenceScope=scope(candidate,canonical),clockQualification=copy.deepcopy(decision['clockQualification']),
        recordingEvidenceQualification=copy.deepcopy(decision['recordingEvidenceQualification']),
        reviewedRuntimeFrontend=copy.deepcopy(candidate['frontend']),
        musicProjectionSha256=music_projection(candidate,sync_raw,notation_raw),
        metadataAssociationFacts=dict(sourceSongId=candidate['sourceSongId'],sourceScoreId=candidate['sourceScoreId'],
            sourceAudioSha256=candidate['sourceAudioSha256'],sourcePDFsha=candidate['sourcePDFsha256'],
            relationProposed='qualified-original-score-reference',literalPerformanceIdentityClaimed=False),
        independentCTCRawBodyAvailable=False,historicalDTWRawPathAvailable=False,
        sameVersionMetadataReviewed=False,**{k:False for k in LIMITS},
        **compatibility_aliases(candidate,sync_raw,notation_raw,canonical,clock_sha,decision))


def pending_review_inputs(proposal,proposal_sha,index_sha):
    """Root supplies decisions after actual original edition adjudication."""
    require(source.is_sha(proposal_sha) and source.is_sha(index_sha),'Actual unsigned proposal/index bindings required')
    review=copy.deepcopy(proposal);decision=copy.deepcopy(proposal)
    for value in (review,decision):
        value.update(status='pending-root-qualified-source-reference-review',reviewedBy=None,
            reviewInputsSha256=proposal_sha,evidenceIndexSha256=index_sha,
            metadataAdjudication=None,unresolvedVersionContradictions=None)
    review.update(schema='source-recording-version-adjudication/v6',rootDecisionSha256=None)
    decision.update(schema='root-qualified-original-score-reference-decision/v6',approved=False)
    return review,decision


@dataclass(frozen=True)
class ValidatedCompleteSATBNormalContext:
    _token:object
    _owner:object
    followId:str
    identity:dict
    references:dict
    sourceScope:dict
    normalAdmissionValidated:bool=False
    physicalPerformanceGold:bool=False


def check_context_result(result,spec,candidate,sync_raw,notation_raw,canonical,resolve):
    entry=_LIVE.get(id(result));owner=getattr(resolve,'__self__',resolve)
    require(type(result) is ValidatedCompleteSATBNormalContext and result._token is _TOKEN and entry is not None
        and entry[0]() is result and entry[1]==source.digest({k:v for k,v in vars(result).items() if k not in ('_token','_owner')})
        and result._owner is owner and getattr(owner,'closed',False) is False and result.followId==candidate['id']
        and same(result.identity,identity(candidate,sync_raw,notation_raw,canonical))
        and same(result.references,{k:spec[k] for k in REFS}) and result.normalAdmissionValidated is False
        and result.physicalPerformanceGold is False,'Actual live normal V6 context was invented, mutated or borrowed')
    for h in result.references.values():source.bound(h,{h},resolve,binary=True)
    proposal=body(result.references['originalProposalSha256'],set(result.references.values()),resolve)
    require(proposal.get('musicProjectionSha256')==music_projection(candidate,sync_raw,notation_raw),
        'Live normal V6 context cannot authorize changed song/source music')
    index=body(result.references['originalIndexSha256'],set(result.references.values()),resolve)
    for row in index['entries']:source.bound(row['sha256'],{row['sha256']},resolve,binary=True)
    return True


def validate_context(spec,candidate,sync_raw,notation_raw,canonical,hashes,resolve,*,source_result,clock_result):
    require(type(spec) is dict and set(spec)=={'kind',*REFS} and spec['kind']==KIND,'Explicit complete normal SATB context spec required')
    require(all(source.is_sha(spec[k]) for k in REFS),'Complete normal original context references required')
    source.check_source_result(source_result,follow_id=candidate['id'],canonical=canonical,
        audit_sha256=spec['sourceAuditSha256'],decision_sha256=spec['sourceDecisionSha256'],resolve=resolve)
    clock.check_clock_result(clock_result,candidate,sync_raw,notation_raw,canonical,resolve)
    require(clock_result.clockDecisionSha256==spec['clockDecisionSha256'],'Actual normal context refers to another common clock')
    # Reconstruct original approved source and native/sample clock bodies at this
    # boundary. A registered data token alone cannot bypass current raw files.
    actual_source=source.validate_source(spec['sourceAuditSha256'],spec['sourceDecisionSha256'],canonical,candidate['id'],hashes,resolve)
    clock.validate_clock(spec['clockDecisionSha256'],candidate,sync_raw,notation_raw,canonical,actual_source,hashes,resolve)
    actual_clock=body(spec['clockDecisionSha256'],hashes,resolve)
    require(spec['actualGeometryEvidenceSha256']==actual_clock['actualGeometryEvidenceSha256'],'Actual full-original geometry differs')
    expected=identity(candidate,sync_raw,notation_raw,canonical)
    proposal=body(spec['originalProposalSha256'],hashes,resolve);review=body(spec['versionAuditSha256'],hashes,resolve)
    decision=body(spec['rootV6DecisionSha256'],hashes,resolve);index=body(spec['originalIndexSha256'],hashes,resolve)
    require(proposal.get('schema')=='qualified-original-score-reference-proposal/v6' and
        review.get('schema') in ('qualified-original-score-reference-review/v6','source-recording-version-adjudication/v6')
        and review.get('status') in ('root-reviewed-qualified-original-score-reference','matched-reviewed-qualified-source-reference')
        and review.get('reviewedBy')=='/root' and review.get('sameVersionMetadataReviewed') is True
        and decision.get('schema')=='root-qualified-original-score-reference-decision/v6'
        and decision.get('status')=='root-reviewed-qualified-original-score-reference'
        and decision.get('approved') is True and decision.get('reviewedBy')=='/root','Genuine normal Root V6 edition/reference approval is pending')
    for v in (proposal,review,decision):
        require(v.get('qualifiedReadingProfile')==PROFILE and v.get('referenceContractVersion')==6
            and v.get('relation')=='qualified-original-score-reference'
            and all(v.get(k)==value for k,value in expected.items()),'Normal V6 original source/recording identity differs')
        require(same(v.get('qualifiedReferenceScope'),scope(candidate,canonical))
            and all(v.get(k) is False for k in LIMITS),'Qualified source reference cannot grant performer/word/attack/release/PCM Gold')
    require(review.get('rootDecisionSha256')==spec['rootV6DecisionSha256']
        and decision.get('reviewInputsSha256')==review.get('reviewInputsSha256')==spec['originalProposalSha256']
        and decision.get('evidenceIndexSha256')==review.get('evidenceIndexSha256')==spec['originalIndexSha256'],'Normal Root V6 original proposal/index graph differs')
    facts=pending_proposal(candidate,sync_raw,notation_raw,canonical,spec['clockDecisionSha256'],actual_clock)
    for name in ('completeSATBEvidence','clockQualification','recordingEvidenceQualification','reviewedRuntimeFrontend','metadataAssociationFacts','musicProjectionSha256'):
        require(all(same(v.get(name),facts[name]) for v in (proposal,review,decision)),'Normal V6 original scope/facts changed: '+name)
    aliases=compatibility_aliases(candidate,sync_raw,notation_raw,canonical,spec['clockDecisionSha256'],actual_clock)
    for stage,value in (('proposal',proposal),('review',review),('decision',decision)):
        validate_compatibility_aliases(value,aliases,stage,spec['rootV6DecisionSha256'])
    require(proposal.get('sameVersionMetadataReviewed') is False and proposal.get('independentCTCRawBodyAvailable') is False
        and proposal.get('historicalDTWRawPathAvailable') is False,'Unsigned original cannot invent an edition decision or missing raw model path')
    for v in (review,decision):
        require(v.get('independentCTCRawBodyAvailable') is False and v.get('historicalDTWRawPathAvailable') is False
            and v.get('sameVersionMetadataReviewed') is True and v.get('unresolvedVersionContradictions')==[],
            'Normal qualified edition unresolved or invented raw-model proof')
    adjudication=review.get('metadataAdjudication')
    require(type(adjudication) is dict and adjudication.get('status')=='root-reviewed-qualified-edition-association'
        and adjudication.get('reviewedBy')=='/root' and adjudication.get('relation')=='qualified-original-score-reference'
        and adjudication.get('sourceDecisionSha256')==spec['sourceDecisionSha256']
        and adjudication.get('clockDecisionSha256')==spec['clockDecisionSha256']
        and adjudication.get('literalPerformanceIdentityClaimed') is False and same(adjudication,decision.get('metadataAdjudication')),
        'Actual Root metadata association is missing; source-only/private tickets are not edition approval')
    entries=index.get('entries');require(type(entries) is list and entries and all(type(r) is dict and source.is_sha(r.get('sha256')) for r in entries),'Actual original evidence index entries missing')
    indexed={r['sha256'] for r in entries}
    needed=complete_original_bindings(actual_clock,candidate,hashes,resolve)|{spec['clockDecisionSha256']}
    require(needed.issubset(indexed),'Complete actual SATB source/clock/native/model original-byte context missing from index')
    for h in indexed:source.bound(h,hashes,resolve,binary=True)
    for h in facts['completeSATBEvidence'].values():source.bound(h,hashes,resolve,binary=True)
    # Issuance is deliberately local to this completed original-graph check;
    # no registration API can bless a reconstructed dataclass/private token.
    result=ValidatedCompleteSATBNormalContext(_TOKEN,getattr(resolve,'__self__',resolve),candidate['id'],expected,
        {k:spec[k] for k in REFS},scope(candidate,canonical))
    identifier=id(result);fingerprint=source.digest({k:v for k,v in vars(result).items() if k not in ('_token','_owner')})
    _LIVE[identifier]=(weakref.ref(result,lambda r:_LIVE.pop(identifier,None)),fingerprint)
    return result
