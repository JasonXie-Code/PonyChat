"""Production complete-quarter opt-in. No scripts/runtime path dependency.

The Root normal V6/UI decisions and every original certificate binding remain
mandatory. Review-only/private capabilities and accepted markers cannot enter.
"""
import copy
import hashlib
import json
import math
from pathlib import Path
from fractions import Fraction
from urllib.parse import unquote, urlparse
from follow_acceptance import file_sha256, binding_path, bindings_match
from source_reading_source_v1 import read_source

PROFILE='one-more-day-complete-quarter-typed-source-reference/v1'
CONTEXT='actual-complete-source-quarter-Root-V6-context'
CAP='typed-complete-quarter-normal-ui-capability/v1'
CONTEXT_KEYS={'versionAuditSha256','rootV6DecisionSha256','originalProposalSha256','originalIndexSha256',
              'sampleEvidenceSha256','sourceAuditSha256','audioAuditSha256'}
UI_KEYS={'capabilitySha256','normalUIDecisionSha256','rootClockDecisionSha256','clockProposalSha256',
    'policyDescriptorSha256','typedSourceAuditSha256','rootSourceDecisionSha256','canonicalSha256',
    'versionAuditSha256','rootVersionDecisionSha256','originalVersionProposalSha256','originalVersionIndexSha256',
    'browserAuditSha256','currentSyncSha256','currentNotationSha256','performanceMapSha256'}
COUNTS=dict(physical=966,pitch=698,rest=202,unpitched=66,unprintedForwards=299,primary=405)
PARTS=['L','L2','H1','H2','H3']


def require(ok,message):
    if not ok:raise ValueError(message)


def opted(meta,sync):
    declared='qualifiedReadingProfile' in meta or 'qualifiedReadingProfile' in sync
    if declared:
        require(meta.get('qualifiedReadingProfile')==sync.get('qualifiedReadingProfile')==PROFILE
                and meta.get('id')=='one-more-day-59bdb131','Unknown or one-sided sealed complete-quarter profile')
    return declared


def strict_json(content):
    def pairs(items):
        result={}
        for k,v in items:
            require(k not in result,'Duplicate sealed original JSON key');result[k]=v
        return result
    return json.loads(content,object_pairs_hook=pairs,
        parse_constant=lambda value:(_ for _ in ()).throw(ValueError('Nonfinite sealed original JSON')))


def projection(meta,sync,notation):
    song,clock,score=copy.deepcopy((meta,sync,notation));fid=song['id']
    require(song.get('sourceScoreId') and song['scorePdf']=='/scores/'+song['sourceScoreId'],'Normal exact score edition locator missing')
    require(song['generated'] in ('/generated/'+fid,'/follow-media/generated/'+fid),'Normal generated locator changed')
    song['generated']='/follow-media/generated/'+fid
    charts=song['charts'];song['charts']=[p if p.startswith('/follow-media/source/charts/') else '/follow-media'+p for p in charts if p.startswith(('/source/charts/','/follow-media/source/charts/'))]
    require(len(song['charts'])==len(charts)==8,'Complete original eight chart locators required')
    for k in ('accepted','machineAccepted','visualAccepted','audioAccepted','musicPassed','visualAcceptance'):
        if k in song['quality'] and k!='visualAcceptance':require(type(song['quality'][k]) is bool,'Strict sealed acceptance lifecycle')
        song['quality'].pop(k,None)
    song.pop('acceptance',None);song['frontend'].pop('assets',None)
    require(type(clock['accepted']) is bool,'Strict sealed sync lifecycle');clock.pop('accepted')
    for k in ('verified','pendingRootReview','evidence','evidenceSha256'):clock['cursorPolicy'].pop(k,None)
    return dict(song=song,sync=clock,jianpu=score)


def fingerprint(value):
    from sealed_source_reading_v1 import tagged
    return hashlib.sha256(json.dumps(tagged(value),ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def same(a,b):return fingerprint(a)==fingerprint(b)


def inside(box,reader):
    return all(type(x[k]) in (int,float) and math.isfinite(x[k]) for x in (box,reader) for k in ('top','bottom','left','right')) and box['top']>=reader['top']-.5 and box['bottom']<=reader['bottom']+.5 and box['left']>=reader['left']-.5 and box['right']<=reader['right']+.5 and box['bottom']>box['top']


def audio_path(audio,meta):
    require(unquote(urlparse(audio['src']).path)==meta['audio'],'Actual UI uses another original recording')


def natural_ui(browser,events,meta):
    eof,visible,cleared=set(),set(),set()
    primary=sorted((e for e in events if e['cursorPrimary']),key=lambda e:e['time'])
    require(browser.get('rawNaturalPlaybackSamples'),'Actual natural source-reading observations missing')
    for sample in browser['rawNaturalPlaybackSamples']:
        audio,frame=sample['audio'],sample['frame'];audio_path(audio,meta)
        width=sample['viewport']['width'];time=frame['time'];mode=frame['mode']
        require(width in (375,1280) and mode in ('staff','jianpu') and type(time) in (int,float)
            and math.isfinite(time) and time>=0,'Actual natural viewport/mode/clock invalid')
        eligible=[e for e in primary if e['time']<=time+.00001];last=eligible[-1] if eligible else None
        expected=[str(last['eventIndex'])] if last and time<last['endTime'] else []
        require(set(frame.get(mode,[]))==set(expected),'Natural common-quarter cursor differs')
        if not audio['paused']:
            if expected:
                require(frame['cursorLineCount']==1 and frame['cursorSourceStaffIds']==last['visual']['sourceStaffIds']
                    and inside(frame['wholeSystemBounds'],frame['readerBounds']),'Natural whole-part reading clipped')
                visible.add(width)
            else:cleared.add(width)
        if audio['ended']:
            require(audio['paused'] is True and abs(audio['time']-audio['duration'])<.002 and not expected,
                'Actual EOF media/cursor not ended and clear')
            eof.add(width)
    require(eof==visible==cleared=={375,1280},'Both actual widths need visible playing, cleared gap and EOF')


def actual_ui(browser,events,meta,raw):
    scopes={(w,v) for w in ('desktop-1280','mobile-375') for v in ('staff','jianpu')}
    require(browser['status']=='passed' and browser['followId']==meta['id'],'Actual UI reviewed another source or failed')
    require(len(browser['actions'])==698*4,'Four actual full physical UI scopes incomplete')
    for scope,mode in scopes:
        rows=[r for r in browser['actions'] if (r['viewport'],r['view'])==(scope,mode)]
        require(len(rows)==698 and {r['eventIndex'] for r in rows}==set(range(698)),'Actual UI physical head coverage incomplete')
        width=375 if scope=='mobile-375' else 1280
        for row in rows:
            e=events[row['eventIndex']];after=row['after'];frame=after['frame'];audio=after['audio'];action=row['action']
            audio_path(audio,meta)
            require(row['passed'] is True and ('native' in action or 'real' in action)
                and any(k in action for k in ('Enter-','click','pointer','tap')) and row['sourceHeadId']==e['visual']['noteheadId']
                and abs(row['expectedTime']-e['time'])<.001 and abs(audio['time']-e['time'])<.001 and audio['paused'] is True
                and frame['mode']==mode and str(e['eventIndex']) in frame[mode]
                and after['viewport']['width']==after['viewport']['scrollWidth']==width,'Actual native source/time/viewport changed')
            require(frame['cursorLineCount']==1 and frame['cursorSourceStaffIds']==e['visual']['sourceStaffIds']
                and inside(frame['wholeSystemBounds'],frame['readerBounds']),'Actual whole-part row clipped or mismatched')
    require({(p['viewport'],p['view']) for p in browser['screenshots']}==scopes and len({p['sha256'] for p in browser['screenshots']})>=4,'Four actual photo scopes missing')
    for photo in browser['screenshots']:raw(photo['sha256'])
    for digest in browser['rawEvidenceSha256s']:raw(digest)
    require(browser['rawEvidenceSha256s'],'Actual raw UI evidence missing')
    names={r['test'] for r in browser['navigation'] if r['passed'] is True}
    require(all(any(k in name for name in names) for k in ('scroll','resume','size','expanded-exit','play-pause')),'Actual player/navigation checks missing')
    natural_ui(browser,events,meta)


def validate(meta,report,notation,sync,follow,media):
    require(opted(meta,sync),'Explicit complete-quarter production profile required')
    require(meta['sourceSongId']=='best-gift-ever-2018/01 - One More Day.mp3'
        and meta['sourceScoreId']=='Charts, Scores and Lyrics/MLP H1_One More Day CHART R6.pdf'
        and meta['audio']=='/audio/'+meta['sourceSongId'] and meta['scorePdf']=='/scores/'+meta['sourceScoreId'], 'Explicit current recording/edition locators required')
    follow,media=Path(follow),Path(media);fid=meta['id'];pointer=meta.get('acceptance',{})
    require(pointer.get('certificate')=='/generated/'+fid+'/acceptance.json','Normal sealed certificate missing')
    cert_path=follow/pointer['certificate'].lstrip('/')
    require(file_sha256(cert_path)==pointer.get('sha256'),'Normal sealed certificate bytes changed')
    cert=strict_json(cert_path.read_bytes());require(type(cert) is dict,'Normal certificate must be an object')
    proof=cert.get('sourceReadingMachineQualification',{});require(type(proof) is dict,'Normal source-reading proof must be an object')
    require(cert.get('status')=='approved' and cert.get('reviewedBy') and cert.get('signedAt')
        and cert['followId']==fid and cert['sourceSongId']==meta['sourceSongId'] and cert['sourceScoreId']==meta['sourceScoreId']
        and not cert.get('reasons') and set(cert['gates'])=={'machine','sourceScore','audioIndependent','visual'}
        and all(v is True for v in cert['gates'].values()) and proof.get('schema')=='validated-source-reading-machine/v1',
        'Actual complete normal certificate is pending')
    require(bindings_match(cert['bindings'],follow,media),'Original normal certificate binding changed/missing')
    bindings={r['sha256']:binding_path(r,follow,media) for r in cert['bindings']}
    def raw(digest):
        require(digest in bindings and file_sha256(bindings[digest])==digest,'Normal original body unbound or changed')
        return bindings[digest].read_bytes()
    def body(digest):
        value=strict_json(raw(digest));require(type(value) is dict,'Normal original JSON must be an object');return value
    context=proof['qualifiedContextInputs'];ui_spec=proof['sourceReadingCursorCapability']
    require(set(context)=={'kind',*CONTEXT_KEYS} and context['kind']==CONTEXT
        and set(ui_spec)=={'kind',*UI_KEYS} and ui_spec['kind']==CAP,'Unknown normal 7/16-hash opt-in')
    version=body(context['versionAuditSha256']);decision=body(context['rootV6DecisionSha256'])
    original=body(context['originalProposalSha256']);index=body(context['originalIndexSha256'])
    require(decision.get('schema')=='root-qualified-original-score-reference-decision/v6'
        and decision.get('approved') is True and decision.get('reviewedBy')=='/root'
        and decision.get('status')=='root-reviewed-qualified-original-score-reference'
        and original.get('schema')=='qualified-original-score-reference-proposal/v6'
        and version.get('qualifiedReadingProfile')==decision.get('qualifiedReadingProfile')==original.get('qualifiedReadingProfile')==PROFILE,
        'Distinct normal Root V6 required; private or review clock rejects')
    require(version['rootDecisionSha256']==proof['rootV6DecisionSha256']==context['rootV6DecisionSha256']==ui_spec['rootVersionDecisionSha256']
        and version['reviewInputsSha256']==decision['reviewInputsSha256']==context['originalProposalSha256']==ui_spec['originalVersionProposalSha256']
        and version['evidenceIndexSha256']==decision['evidenceIndexSha256']==context['originalIndexSha256']==ui_spec['originalVersionIndexSha256']
        and context['versionAuditSha256']==ui_spec['versionAuditSha256'],'Normal original V6 graph changed')
    require(index['entries'] and {context[k] for k in ('sampleEvidenceSha256','sourceAuditSha256','audioAuditSha256')}<={r['sha256'] for r in index['entries']},'Normal indexed sample/source/audio incomplete')
    for row in index['entries']:raw(row['sha256'])
    for key,value in original.items():
        if key in ('schema','status'):continue
        current=copy.deepcopy(version.get(key))
        if key=='overallPrimaryMelodyAndStructureCorrespondence':require(current.pop('rootDecisionSha256',None)==context['rootV6DecisionSha256'],'Original primary context Root differs')
        require(same(current,value),'Normal V6 original field changed: '+key)
    extension=version['completeQuarterEvidence']
    require(set(extension)=={'modelAdapterSha256','sampleAdapterSha256','contextSpecSha256','nativePublicClockSpecSha256','completeContextItemsSha256'}
        and same(extension,decision['completeQuarterEvidence']) and same(extension,original['completeQuarterEvidence']), 'Root V6 complete original model/sample/context/native graph missing')
    for digest in extension.values():raw(digest)
    require(version['sameVersionMetadataReviewed'] is True and not version['unresolvedVersionContradictions']
        and version['metadataAdjudication']['status']=='root-reviewed-qualified-edition-association'
        and same(version['metadataAdjudication'],decision['metadataAdjudication'])
        and same(version['qualifiedReferenceScope'],decision['qualifiedReferenceScope']), 'Normal whole edition adjudication missing')
    require(all(version[k] is False for k in ('allSourceVoicesLiteralPerformanceConfirmed','allSingerPitchGold','isolatedVoiceAttackGold',
        'allPrintedWordsAcousticallyConfirmed','sourcePitchReplacement','browserPCMOriginMeasured')),'Qualified source reference became Gold')
    require(same(sync['sourceAudioClock'],version['clockQualification']),'Qualified decoder/browser clock changed')
    folder=follow/'generated'/fid
    for name,key in (('sync.json','syncSha256'),('notation.json','notationSha256')):
        require(file_sha256(folder/name)==version[key]==decision[key]==original[key]
            and same(strict_json((folder/name).read_bytes()),sync if name=='sync.json' else notation),'Current normal raw musical file changed')
    canonical=cert['canonicalMusicxml'];require(canonical.startswith('generated/'+fid+'/omr/'),'Normal canonical locator not installed XML')
    require(file_sha256(follow/canonical)==version['canonicalSha256']==decision['canonicalSha256']==ui_spec['canonicalSha256'],'Current normal canonical changed')
    for key,value in dict(followId=fid,sourceSongId=meta['sourceSongId'],sourceScoreId=meta['sourceScoreId'],sourcePDFsha=meta['sourcePDFsha256'],sourceAudioSha256=meta['sourceAudioSha256']).items():
        require(version[key]==decision[key]==original[key]==value,'Current normal source/recording metadata changed: '+key)
    typed=read_source((follow/canonical).read_bytes());rows={r['sourceNoteId']:r for r in typed['rows']}
    pitched={sid:r for sid,r in rows.items() if r['sourceKind']=='pitch'};tokens=notation['tokens'];events=sync['events']
    counts=dict(physical=len(rows),pitch=len(pitched),rest=sum(r['sourceKind']=='rest' for r in rows.values()),
        unpitched=sum(r['sourceKind']=='unpitched' for r in rows.values()),unprintedForwards=len(typed['sourceGaps']),primary=405)
    require(counts==COUNTS and {r['sourcePart'] for r in rows.values()}==set(PARTS)
        and len(events)==698 and len(tokens)==966 and proof['physicalEntities']==966 and proof['pitchedHeads']==698 and proof['readonlyEntities']==268,'Complete physical source partition differs')
    by_id={t['originalSourceNoteId']:t for t in tokens};require(len(by_id)==966 and set(by_id)==set(rows),'Source token inventory lost/duplicated')
    clocks={};last={};groups={};seen=set()
    for i,e in enumerate(events):
        sid=e['originalSourceNoteId'];r=pitched[sid];t=by_id[sid];seen.add(sid)
        require(e['sourcePhysicalId']==sid and e['eventIndex']==t['eventIndex']==i and e['pitch']==t['pitch']==r['pitch']
            and e['partId']==e['sourcePart']==t['sourcePart']==r['sourcePart'] and e['sourceVoice']==r['voice']
            and e['chordTone'] is r['chordTone'] and e['tieContinuation'] is any(a['type']=='stop' for a in r['ties'])
            and e['noteDuration']==r['durationBeats'] and e['beatInMeasure']==r['beatInMeasure'] and e['sourceQuarter']==t['sourceQuarter']==r['sourceQuarter'], 'Source pitch/rhythm/part/chord/tie changed')
        require(all(type(e[k]) in (int,float) and math.isfinite(e[k]) for k in ('time','endTime'))
            and 0<=e['time']<e['endTime']==e['sourceReadingEndTime']<=sync['duration']+.5
            and e['time']==t['time'] and e['endTime']==t['endTime'] and e['physicalGateEndTime'] is None
            and e['physicalGateEndConfirmed'] is False and e['sourceReadingEndIsPhysicalGateEnd'] is False
            and e['noteAttackGold'] is False and e['recordingPitchUnconfirmed'] is True and e['recordingLyricUnconfirmed'] is True,'Source reading clock became physical alignment')
        q=Fraction(str(r['sourceQuarter']));voice=(r['sourcePart'],r['voice']);require(e['time']>=last.get(voice,-1) and(q not in clocks or clocks[q]==e['time']),'Part or shared-quarter clock changed')
        last[voice]=clocks[q]=e['time'];groups.setdefault(q,[]).append(e)
        v=e['visual'];require(v['noteheadId']==sid and v['bboxCenterUsed'] is False and same(v['noteheadCenter'],t['actualSourceInkCenter'])
            and v['staffCount']==len(v['sourceStaffIds'])>0 and all(type(v[k]) in(int,float) and math.isfinite(v[k]) and 0<=v[k]<=1 for k in('x','y','width','height'))
            and v['width']>0 and v['height']>0,'Whole-source ink center/band changed')
    require(len(seen)==698,'Pitched source identity duplicate')
    for sid,r in rows.items():
        if r['sourceKind']=='pitch':continue
        t=by_id[sid];require(all(t[k] is None for k in('time','endTime','eventIndex','pitch','midi')) and t['seekAllowed'] is False and t['skipCursorHighlight'] is True
            and t['isRest'] is r['isRest'] and t['isUnpitched'] is r['isUnpitched'] and(r['sourceKind']!='unpitched' or t['token']=='×'),'Readonly rest/X became a timed pitched event')
    cap=body(ui_spec['capabilitySha256']);ui=body(ui_spec['normalUIDecisionSha256'])
    for item,kind in ((cap,'root-complete-quarter-normal-reading-capability/v1'),(ui,'root-complete-quarter-normal-reading-ui-decision/v1')):
        require(item.get('schema')==kind and item.get('approved') is True and item.get('reviewedBy')=='/root'
            and item.get('scope')=='normal-qualified-common-source-reading-and-actual-ui-only'
            and all(item[k] is False for k in ('performedPitchGold','wordGold','singerIdentityGold','physicalGateGold','formalAccepted')),'Normal actual full UI capability pending/private')
    for key in UI_KEYS-{'capabilitySha256'}:require(cap[key]==ui_spec[key],'Normal16capability original graph changed: '+key)
    music=fingerprint(projection(meta,sync,notation))
    require(cap['musicProjectionSha256']==ui['musicProjectionSha256']==music and same(cap['frontend'],meta['frontend'])
        and same(ui['frontend'],meta['frontend']) and cap['physicalCounts']==ui['physicalCounts']==counts,'Current normal complete metadata/music/assets changed')
    require(ui_spec['currentSyncSha256']==version['syncSha256'] and ui_spec['currentNotationSha256']==version['notationSha256'], 'Normal UI references another raw musical tuple')
    for key in ('followId','sourceSongId','sourceScoreId','canonicalSha256','sourceAudioSha256','sourcePDFsha','syncSha256','notationSha256'):
        require(cap[key]==ui[key]==version[key], 'Normal UI/capability source identity changed: '+key)
    require(raw(cap['implementationSha256']), 'Actual normal UI validator implementation unbound')
    for name,digest in meta['frontend']['assets'].items():require(file_sha256(folder/'accepted-frontend'/name)==digest and digest in bindings,'Current renderer asset unbound/changed')
    for digest in meta['frontend']['coreSha256'].values():raw(digest)
    source=body(context['sourceAuditSha256']);audit=body(ui_spec['typedSourceAuditSha256']);source_root=body(ui_spec['rootSourceDecisionSha256'])
    require(same(audit,source['typedPhysicalSourceAudit']) and same(audit['rootSourceDecision'],source_root)
        and source_root['schema']=='root-full-physical-source-decision/v1' and source_root['approved'] is True and source_root['reviewedBy']=='/root'
        and source_root['canonicalSha256']==version['canonicalSha256'] and source_root['sourcePDFsha256']==version['sourcePDFsha']
        and source_root['sourceCounts']=={k:counts[k] for k in ('pitch','rest','unpitched')} and source_root['unprintedForwardCount']==299,'Original complete typed Root source approval missing')
    descriptor=body(ui_spec['policyDescriptorSha256']);clock=body(ui_spec['rootClockDecisionSha256']);clock_proposal=body(ui_spec['clockProposalSha256'])
    require(clock['schema']=='root-complete-quarter-normal-reading-clock/v1' and clock['approved'] is True and clock['reviewedBy']=='/root'
        and clock['scope']=='qualified-complete-quarter-normal-metadata-reading-clock-only'
        and clock['musicProjectionSha256']==clock_proposal['musicProjectionSha256']==descriptor['musicProjectionSha256']==music
        and all(clock[k] is False for k in('physicalGateGold','performedPitchGold','wordGold','singerIdentityGold','wholeAudioApproved','editionApproved','formalAccepted')),'Normal current complete clock pending or exceeds scope')
    for name,key in (('proposal','clockProposalSha256'),('sync','currentSyncSha256'),('notation','currentNotationSha256'),('policyDescriptor','policyDescriptorSha256')):
        require(clock[name]['sha256']==ui_spec[key] and clock[key]==ui_spec[key],'Normal clock binds another current original body')
    intervals=clock_proposal[cap['clockIntervalField']];require(len(intervals)==698,'Whole698 clock required')
    for r,e in zip(intervals,events):require(r['sourcePhysicalId']==e['sourcePhysicalId'] and r['eventIndex']==e['eventIndex'] and r['sourcePitch']==e['pitch']
        and r['sourcePart']==e['partId'] and r['sourceQuarter']==e['sourceQuarter'] and r['sourceQuarterEnd']==e['sourceQuarter']+e['noteDuration']
        and r['time']==e['time'] and r['sourceReadingEnd']==e['endTime'] and r['physicalGateEnd'] is None,'Normal complete clock interval changed')
    require(len(groups)==405 and sync['cursorPolicy']['representativePreference']==PARTS,'Common405 quarter policy changed')
    primary=[min(es,key=lambda e:(PARTS.index(e['sourcePart']),e['chordTone'],e['sourceNoteIndex']))['eventIndex'] for es in groups.values()]
    primary.sort();extra=[events[i]['sourcePhysicalId'] for i in primary if events[i]['sourcePart']!='L']
    require(len(extra)==13 and descriptor['primaryEventIndices']==sync['cursorPolicy']['primaryEventIndices']==primary
        and descriptor['automaticAdditionalSourceIds']==sync['cursorPolicy']['automaticAdditionalSourceIds']==extra
        and all(e['cursorPrimary']==by_id[e['originalSourceNoteId']]['cursorPrimary']==(e['eventIndex'] in primary) for e in events)
        and tuple(proof['automaticEvents'])==tuple(primary),'Complete preferred source-quarter representatives changed')
    require(ui['rootVersionDecisionSha256']==context['rootV6DecisionSha256'] and ui['browserAuditSha256']==ui_spec['browserAuditSha256'],'Normal UI approved another V6/audit')
    browser=body(ui_spec['browserAuditSha256']);require(browser['schema']=='reviewed-complete-quarter-native-ui/v1' and browser['approved'] is True
        and browser['rootDecision'] is not None and same(browser['frontend'],meta['frontend']),'Current actual whole UI review missing')
    actual_ui(browser,events,meta,raw)
    samples=body(context['sampleEvidenceSha256']);require(len(samples['notes'])==698 and samples['canonicalSha256']==version['canonicalSha256']
        and samples['sourceAudioSha256']==version['sourceAudioSha256'],'Current sample evidence identity/coverage changed')
    for i,(sample,e) in enumerate(zip(samples['notes'],events)):require(sample['sourceNoteId']==e['originalSourceNoteId'] and sample['eventIndex']==i
        and sample['sourcePart']==e['sourcePart'] and sample['sourceQuarter']==e['sourceQuarter'] and sample['physicalGateEndTime'] is None
        and sample['measurementUsesAudioSamples'] is True,'Sample/source identity or actual measurement scope changed')
    mapping=body(ui_spec['performanceMapSha256']);require(len(mapping['performedOccurrences'])==698
        and {r['eventIndex'] for r in mapping['performedOccurrences']}==set(range(698)),'Normal complete occurrence mapping missing/duplicated')
    for r in mapping['performedOccurrences']:
        e=events[r['eventIndex']];require(r['sourceNoteId']==e['originalSourceNoteId'] and r['sourceHeadId']==e['visual']['noteheadId'],'Normal physical occurrence identity changed')
        items=r['timingReview']['evidence'];selected=[t for t in items if t.get('kind')==CONTEXT];require(len(selected)==1,'Normal qualified complete context item required')
        item=selected[0];require(all(item[k]==context[k] for k in ('kind',*CONTEXT_KEYS)) and item['sourceNoteId']==e['originalSourceNoteId']
            and item['sourcePart']==e['partId'] and item['sourceQuarter']==e['sourceQuarter'] and item['eventIndex']==e['eventIndex']
            and item['independent'] is False and item['sourceReadingClockOnly'] is True and item['measurementUsesAudioSamples'] is True
            and item['physicalGateEndTime'] is None and item['isolatedVoiceAttackConfirmed'] is False and item['isolatedVoicePitchConfirmed'] is False,'Normal timing item changed source or pretended isolated performance')
        sample=samples['notes'][e['eventIndex']]
        representative=next(p['eventIndex'] for p in groups[Fraction(str(e['sourceQuarter']))] if p['cursorPrimary'])
        require(item['schema']=='actual-complete-source-quarter-root-v6-context/v1' and item['sha256']==context['sampleEvidenceSha256']
            and item['sourcePhysicalId']==e['sourcePhysicalId'] and item['representativeEventIndex']==representative
            and item['evidenceRowIndex']==e['eventIndex'] and item['window']==sample['window']
            and item['clock']==sample['clock']=='native-decoder' and item['actualDecodedSampleCount']==sample['mixSampleCount']
            and item['sourceTimeUnchanged']==e['time'] and item['sourceReadingEndUnchanged']==e['endTime']
            and all(item[k] is False for k in('performedPitchGold','wordGold','singerIdentityGold','noteAttackGold')),
            'Normal context changed actual sample window, representative or qualified clock')
    paths=tuple(p.lstrip('/') for p in meta['charts']);require(all(any(b['kind']=='follow' and b['path']==p for b in cert['bindings']) for p in paths),'Original chart body not bound')
    return dict(followId=fid,canonicalPath=canonical,chartPaths=paths,automaticEventIndices=tuple(primary),syncSha256=version['syncSha256'],notationSha256=version['notationSha256'])
