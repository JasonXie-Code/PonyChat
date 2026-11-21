"""Deployable sealed source-reading contract; no scripts or legacy fallback.

Every dependency is an actual certificate-bound body. An available/accepted
marker cannot opt a payload into this contract or change its musical JSON.
"""
import hashlib
import json
import math
import re
import struct
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from follow_acceptance import binding_path,bindings_match,file_sha256
from source_reading_source_v1 import read_source

_TOKEN=object()
SCHEMA='validated-source-reading-machine/v1'
BOOL=('accepted','machineAccepted','visualAccepted','musicPassed','audioAccepted',
      'sourceCorrectionPending','rootRevisedAudioAndVisualPending')


def require(condition,message):
    if not condition:raise ValueError(message)


def tagged(value):
    if value is None:return ['null']
    if type(value) is bool:return ['boolean',value]
    if isinstance(value,str):return ['string',value]
    if type(value) in (int,float):
        require(math.isfinite(value),'Nonfinite sealed projection')
        return ['number',struct.pack('>d',float(value)).hex()]
    if isinstance(value,list):return ['array',[tagged(v) for v in value]]
    require(isinstance(value,dict) and all(isinstance(k,str) for k in value),'Unsupported sealed projection')
    return ['object',[[k,tagged(value[k])] for k in sorted(value,key=lambda k:k.encode('utf-16-be'))]]


def music_sha(song,sync,notation):
    quality=song['quality'];front=song['frontend'];policy=sync['cursorPolicy']
    projected={k:v for k,v in song.items() if k not in ('quality','frontend','acceptance','generated','attempts')}
    projected['charts']=[p[13:] if p.startswith('/follow-media/') else p for p in song['charts']]
    projected['quality']={k:v for k,v in quality.items() if k not in BOOL+('visualAcceptance',)}
    projected['frontend']={k:v for k,v in front.items() if k!='assets'}
    value=dict(song=projected,sync=dict({k:v for k,v in sync.items() if k not in ('accepted','cursorPolicy')},
        cursorPolicy={k:v for k,v in policy.items() if k not in ('verified','pendingRootReview','evidence','evidenceSha256')}),
        jianpu=notation)
    return hashlib.sha256(json.dumps(tagged(value),ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


@dataclass(frozen=True)
class SealedSourceReading:
    token:object
    followId:str
    canonicalPath:str
    chartPaths:tuple
    automaticEventIndices:tuple
    syncSha256:str
    notationSha256:str


def valid_type(value,fid):
    return isinstance(value,SealedSourceReading) and value.token is _TOKEN and value.followId==fid


def chart_relative(url):
    require(isinstance(url,str) and url.startswith('/source/charts/')
            and '\\' not in url and all(p not in ('','.','..') for p in url.lstrip('/').split('/')),
            'Sealed source chart locator escaped')
    return url.lstrip('/')


def validate(meta,report,notation,sync,follow,media):
    """Fail closed unless the complete normal signed dataset qualifies."""
    from normal_source_public_dispatch_v1 import opted as ensemble_opted,validate as validate_ensemble
    if ensemble_opted(meta,sync):
        return SealedSourceReading(_TOKEN,**validate_ensemble(meta,report,notation,sync,follow,media))
    from sealed_complete_satb_reading_v1 import opted as satb_opted,validate as validate_satb
    if satb_opted(meta,sync):
        return SealedSourceReading(_TOKEN,**validate_satb(meta,report,notation,sync,follow,media))
    from sealed_complete_quarter_reading_v1 import opted,validate as validate_complete
    if opted(meta,sync):
        result=validate_complete(meta,report,notation,sync,follow,media)
        return SealedSourceReading(_TOKEN,**result)
    follow,media=Path(follow),Path(media);fid=meta['id'];pointer=meta.get('acceptance',{})
    require(pointer.get('certificate')=='/generated/'+fid+'/acceptance.json', 'Sealed source certificate missing')
    cert_path=follow/pointer['certificate'].lstrip('/')
    require(file_sha256(cert_path)==pointer.get('sha256'),'Sealed source certificate bytes changed')
    cert=json.loads(cert_path.read_bytes());proof=cert.get('sourceReadingMachineQualification',{})
    require(proof.get('schema')==SCHEMA and cert.get('status')=='approved' and cert.get('reviewedBy')
            and cert.get('signedAt') and cert.get('followId')==fid and cert.get('sourceSongId')==meta['sourceSongId']
            and cert.get('sourceScoreId')==meta['sourceScoreId'] and not cert.get('reasons')
            and set(cert.get('gates',{}))=={'machine','sourceScore','audioIndependent','visual'}
            and all(v is True for v in cert['gates'].values()),'Sealed source normal certificate not approved')
    require(bindings_match(cert['bindings'],follow,media),'Sealed source actual bound file changed/missing')
    bindings={b['sha256']:binding_path(b,follow,media) for b in cert['bindings']}
    def raw(digest):
        require(isinstance(digest,str) and re.fullmatch('[0-9a-f]{64}',digest) and digest in bindings,
                'Sealed source original proof missing from certificate')
        p=bindings[digest];require(file_sha256(p)==digest,'Sealed source original proof changed')
        return p.read_bytes()
    def body(digest):return json.loads(raw(digest))
    inputs=proof['qualifiedContextInputs']
    require(set(inputs)=={'kind','versionAuditSha256','rootV6DecisionSha256','originalProposalSha256',
            'originalIndexSha256','sampleEvidenceSha256','sourceAuditSha256','audioAuditSha256'}
            and inputs['kind']=='actual-source-quarter-Root-V6-context'
            and proof['rootV6DecisionSha256']==inputs['rootV6DecisionSha256'],
            'Unknown sealed qualified context schema or decision')
    version=body(inputs['versionAuditSha256']);decision=body(inputs['rootV6DecisionSha256'])
    proposal=body(inputs['originalProposalSha256']);index=body(inputs['originalIndexSha256'])
    require(decision.get('schema')=='root-qualified-original-score-reference-decision/v6'
            and decision.get('approved') is True and decision.get('reviewedBy')=='/root'
            and decision.get('status')=='root-reviewed-qualified-original-score-reference'
            and version['rootDecisionSha256']==inputs['rootV6DecisionSha256']
            and decision['reviewInputsSha256']==version['reviewInputsSha256']==inputs['originalProposalSha256']
            and decision['evidenceIndexSha256']==version['evidenceIndexSha256']==inputs['originalIndexSha256']
            and proposal.get('schema')=='qualified-original-score-reference-proposal/v6',
            'Sealed source actual Root V6 authority differs/pending')
    require((version.get('schema'),version.get('status')) in (
        ('qualified-original-score-reference-review/v6','root-reviewed-qualified-original-score-reference'),
        ('source-recording-version-adjudication/v6','matched-reviewed-qualified-source-reference')),
        'Unknown sealed V6 version schema')
    for row in index['entries']:raw(row['sha256'])
    for key,value in proposal.items():
        if key in ('schema','status'):continue
        current=version.get(key)
        if key=='overallPrimaryMelodyAndStructureCorrespondence':
            current=dict(current);require(current.pop('rootDecisionSha256',None)==inputs['rootV6DecisionSha256'],
                'Sealed original observation authority changed')
        require(tagged(current)==tagged(value),'Sealed original V6 field changed: '+key)
    require(tagged(sync['sourceAudioClock'])==tagged(version['clockQualification'])
            and decision['qualifiedReferenceScope']==version['qualifiedReferenceScope']
            and all(version[k] is False for k in ('allSourceVoicesLiteralPerformanceConfirmed',
                'allSingerPitchGold','isolatedVoiceAttackGold','allPrintedWordsAcousticallyConfirmed',
                'sourcePitchReplacement','browserPCMOriginMeasured')),
            'Sealed qualified clock/scope became Gold or measured browser origin')
    folder=follow/'generated'/fid
    for name,key in [('sync.json','syncSha256'),('notation.json','notationSha256')]:
        require(file_sha256(folder/name)==version[key]==decision[key]==proposal[key],
                'Sealed source current musical file differs from Root V6 tuple')
    require(json.loads((folder/'sync.json').read_bytes())==sync
            and json.loads((folder/'notation.json').read_bytes())==notation,'Sealed source returned musical JSON changed')
    canonical=cert['canonicalMusicxml'];require(canonical.startswith('generated/'+fid+'/omr/'),
        'Sealed source canonical locator not normal installed XML')
    require(file_sha256(follow/canonical)==version['canonicalSha256']==decision['canonicalSha256']==proposal['canonicalSha256'],
        'Sealed source canonical bytes changed')
    typed=read_source((follow/canonical).read_bytes());rows={r['sourceNoteId']:r for r in typed['rows']}
    pitched={k:r for k,r in rows.items() if r['sourceKind']=='pitch'};events=sync['events'];tokens=notation['tokens']
    require(len(events)==len(pitched)==proof['pitchedHeads'] and len(tokens)==len(rows)==proof['physicalEntities']
            and len(rows)-len(pitched)==proof['readonlyEntities'],'Sealed source complete physical coverage differs')
    by_id={t['originalSourceNoteId']:t for t in tokens}
    require(len(by_id)==len(tokens) and set(by_id)==set(rows),'Sealed source token identities changed')
    clocks={};last={};voice_last={};seen=set()
    for i,e in enumerate(events):
        r=pitched[e['originalSourceNoteId']];t=by_id[e['originalSourceNoteId']]
        require(e['originalSourceNoteId'] not in seen,'Sealed source duplicated a pitched occurrence')
        seen.add(e['originalSourceNoteId'])
        require(type(e['eventIndex']) is int and e['eventIndex']==i==t['eventIndex']
            and e['pitch']==r['pitch']==t['pitch'] and e['partId']==r['sourcePart']
            and e['sourceVoice']==r['voice'] and e['chordTone'] is r['chordTone']
            and e['noteDuration']==r['durationBeats'] and e['beatInMeasure']==r['beatInMeasure']
            and e['tieContinuation'] is any(a['type']=='stop' for a in r['ties'])
            and e['time']==t['time'] and e['endTime']==t['endTime']
            and e['recordingPitchUnconfirmed'] is True and e['recordingLyricUnconfirmed'] is True
            and e['noteAttackGold'] is False and e['physicalGateEndTime'] is None,
            'Sealed source original values or qualified unknown scope changed')
        require(type(e['time']) in (int,float) and type(e['endTime']) in (int,float)
            and math.isfinite(e['time']) and math.isfinite(e['endTime']) and 0<=e['time']<=e['endTime']<=sync['duration']+.5,
            'Sealed source clock invalid')
        p=r['sourcePart'];v=(p,r['voice']);q=Fraction(str(r['sourceQuarter']))
        require(e['time']>=last.get(p,-1) and e['time']>=voice_last.get(v,-1)
                and (q not in clocks or clocks[q]==e['time']),
                'Sealed source part/quarter clock differs')
        last[p]=voice_last[v]=clocks[q]=e['time']
        ink=e['visual']
        require(type(ink['page']) is int and 1<=ink['page']<=len(meta['charts'])
                and ink['noteheadId']==e['originalSourceNoteId']
                and all(type(ink[k]) in (int,float) and math.isfinite(ink[k]) and 0<=ink[k]<=1
                    for k in ('x','y','width','height')) and ink['width']>0 and ink['height']>0,
                'Sealed source actual physical cursor bounds invalid')
    require(seen==set(pitched),'Sealed source lost a pitched occurrence')
    for sid,r in rows.items():
        if r['sourceKind']=='pitch':continue
        t=by_id[sid]
        require(all(t[k] is None for k in ('time','endTime','eventIndex','pitch')) and t['seekAllowed'] is False
            and t['isRest'] is r['isRest'] and t['isUnpitched'] is r['isUnpitched']
            and (r['sourceKind']!='unpitched' or t['token']=='×'), 'Sealed source readonly acquired fake time/pitch')
    cap_spec=proof['sourceReadingCursorCapability'];cap=body(cap_spec['capabilitySha256'])
    descriptor=body(cap_spec['policyDescriptorSha256']);clock=body(cap_spec['rootClockDecisionSha256'])
    require(set(cap_spec)=={'kind','capabilitySha256','policyDescriptorSha256','rootClockDecisionSha256',
                'clockProposalSha256'} and cap_spec['kind']=='root-smile-source-reading-cursor-capability/v1'
            and cap.get('approved') is True and cap.get('reviewedBy')=='/root'
            and cap.get('schema')=='root-smile-source-reading-cursor-capability/v1'
            and cap.get('status')=='root-approved-qualified-source-reading-cursor-capability'
            and cap['policyDescriptorSha256']==cap_spec['policyDescriptorSha256']
            and cap['musicProjectionSha256']==music_sha(meta,sync,notation)
            and cap['rootClockDecisionSha256']==cap_spec['rootClockDecisionSha256']
            and cap['rootClockProposalSha256']==cap_spec['clockProposalSha256']
            and cap['canonicalSha256']==version['canonicalSha256']
            and cap['sourceAudioSha256']==version['sourceAudioSha256']
            and cap['sourcePDFSha256']==version['sourcePDFsha']
            and cap['sourceReadingClockApproved'] is True
            and all(cap[k] is False for k in ('physicalGateGold','pitchGold','singerIdentityGold',
                    'attackGold','wholeAudioGold','formalAdmissionGranted'))
            and clock.get('approved') is True and clock.get('reviewedBy')=='/root'
            and clock.get('schema')=='root-reviewed-source-quarter-shared-music-clock/v1'
            and clock.get('status')=='root-reviewed-qualified-shared-source-music-clock'
            and clock['sourceReadingClockOnly'] is True
            and clock['proposalSha256']==cap_spec['clockProposalSha256'],
            'Sealed source capability/music/current shared clock authority changed')
    source=body(cap['sourceAuditSha256']);source_root=body(cap['fullPhysicalSourceDecisionSha256'])
    require(source.get('sourcePassed') is True and source['canonicalSha256']==version['canonicalSha256']
            and source['sourcePDFsha']==version['sourcePDFsha']
            and source_root.get('schema')=='root-full-physical-source-decision/v1'
            and source_root.get('status')=='root-approved-full-physical-source'
            and source_root.get('approved') is True and source_root.get('sourcePassed') is True
            and source_root.get('reviewedBy')=='/root'
            and source_root['canonicalSha256']==version['canonicalSha256']
            and source_root['sourcePDFsha256']==version['sourcePDFsha']
            and source_root['sourceCounts']=={k:sum(r['sourceKind']==k for r in rows.values())
                for k in ('pitch','rest','unpitched')},'Sealed complete source authority missing/changed')
    clock_proposal=body(cap_spec['clockProposalSha256'])
    require(clock_proposal['syncSha256']==version['syncSha256']
            and clock_proposal['canonicalSha256']==version['canonicalSha256']
            and clock_proposal['sourceAudioSha256']==version['sourceAudioSha256']
            and clock['reviewedReferences']==clock_proposal['references'],
            'Sealed shared clock original references changed')
    fixed='generated/'+fid+'/acceptance-evidence/'
    for name,digest in [('source-reading-cursor-capability.json',cap_spec['capabilitySha256']),
                        ('source-reading-policy-projection.json',cap_spec['policyDescriptorSha256'])]:
        require(file_sha256(follow/fixed/name)==digest and any(b['kind']=='follow' and b['path']==fixed+name
                and b['sha256']==digest for b in cert['bindings']), 'Sealed source public fixed sidecar not installed/bound')
    require(sync['cursorPolicy']['evidenceSha256']==cap_spec['policyDescriptorSha256']
            and sync['cursorPolicy']['evidence']=='acceptance-evidence/source-reading-policy-projection.json'
            and descriptor['schema']=='source-reading-cursor-policy-projection/v1'
            and descriptor['canonicalSha256']==version['canonicalSha256']
            and descriptor['sourceAuditSha256']==cap['sourceAuditSha256']
            and descriptor['terminalDecisionSha256']==cap['terminalDecisionSha256']
            and descriptor['sourceRole']=='source-defined-Lead'
            and descriptor['musicProjectionSha256']==cap['musicProjectionSha256'], 'Sealed source policy changed')
    automatic=tuple(proof['automaticEvents']);require(automatic and len(set(automatic))==len(automatic)
        and all(type(i) is int and 0<=i<len(events) for i in automatic),'Sealed source automatic event policy invalid')
    by_source={e['originalSourceNoteId']:i for i,e in enumerate(events)}
    expected=tuple(descriptor['primaryEventIndices']+[by_source[sid] for sid in descriptor['automaticAdditionalSourceIds']])
    require(automatic==expected and descriptor['primaryEventIndices']==sync['cursorPolicy']['primaryEventIndices']
            and all(events[i]['cursorPrimary'] is True for i in descriptor['primaryEventIndices'])
            and descriptor['actualSingerIdentityConfirmed'] is False and descriptor['physicalGateGold'] is False,
            'Sealed source automatic policy is not the actual bound descriptor')
    chart_paths=tuple(chart_relative(u) for u in meta['charts'])
    require(all(any(b['kind']=='follow' and b['path']==p for b in cert['bindings']) for p in chart_paths),
        'Sealed source actual chart locators are not certificate-bound')
    return SealedSourceReading(_TOKEN,fid,canonical,chart_paths,automatic,version['syncSha256'],version['notationSha256'])


def checked(meta,report,notation,sync,follow,media):
    try:return validate(meta,report,notation,sync,follow,media)
    except (OSError,ValueError,TypeError,KeyError,IndexError):return None
