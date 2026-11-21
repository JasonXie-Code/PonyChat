"""Actual complete SATB browser proof plus separate genuine normal Root UI.

Every note/rest scope and natural observation refers to original captured bytes.
This data checker does not sign those originals or infer UI from a private cap.
"""
from dataclasses import dataclass
import copy
import math
import weakref
from urllib.parse import unquote,urlparse
try:
    from . import complete_satb_normal_context_v1 as context
except ImportError:
    import complete_satb_normal_context_v1 as context

source,clock=context.source,context.clock
require,same=source.require,source.same
PROFILE=context.PROFILE
KIND='typed-complete-satb-normal-ui-capability/v1'
UI_SCHEMA='root-complete-satb-normal-ui-decision/v1'
BROWSER_SCHEMA='actual-complete-satb-native-browser-audit/v1'
CAP_SCHEMA='root-complete-satb-normal-reading-capability/v1'
CAP_SCOPE='normal-complete-satb-source-reading-only'
REFS=(*context.REFS,'capabilitySha256','rootNormalUIDecisionSha256','browserAuditSha256','performanceMapSha256')
SCOPES={(1280,'staff'),(1280,'jianpu'),(375,'staff'),(375,'jianpu')}
_TOKEN=object();_LIVE={}


def inside(box,reader):
    keys=('top','bottom','left','right')
    return all(type(v[k]) in (int,float) and math.isfinite(v[k]) for v in (box,reader) for k in keys) and \
        box['top']>=reader['top']-.5 and box['bottom']<=reader['bottom']+.5 and \
        box['left']>=reader['left']-.5 and box['right']<=reader['right']+.5 and box['bottom']>box['top']


def captured(row,hashes,resolve):
    raw=context.body(row['rawEvidenceSha256'],hashes,resolve)
    for key in row.get('capturePath',[]):
        require(type(key) in (str,int) and type(key) is not bool,'Invalid original capture pointer')
        raw=raw[key]
    require(type(raw) is dict and same(raw,row['captured']),'Browser wrapper changed original captured body')
    return raw


def audio_at(audio,candidate,time=None,paused=None):
    require(unquote(urlparse(audio['src']).path)=='/audio/'+candidate['sourceSongId'],'Native UI played a different recording')
    require(clock.finite(audio['time']) and clock.finite(audio['duration']) and audio['duration']>0,'Actual parent audio clock missing')
    if time is not None:require(abs(audio['time']-time)<.003,'Native UI seek did not reach exact source time')
    if paused is not None:require(audio['paused'] is paused,'Actual parent pause state changed')


def frame_at(frame,width,mode,parts,q):
    require(frame['mode']==mode and frame['viewport']['width']==frame['viewport']['scrollWidth']==width,
        'Actual native viewport/mode or horizontal overflow differs')
    require(frame['cursorLineCount']==1 and frame['cursorSourceParts']==parts and
        abs(frame['sourceQuarter']-q)<.00001 and inside(frame['wholeSystemBounds'],frame['readerBounds']),
        'Native whole four-part cue is clipped or not the complete source quarter')


def performance_map(candidate,sync_raw,notation_raw,canonical):
    _,sync,notation=clock.identity(candidate,sync_raw,notation_raw,canonical)
    _,_,representatives,rows,rests=clock.reading_projection(candidate,sync_raw,notation_raw,canonical)
    return dict(schema='complete-satb-source-reading-performance-map/v1',qualifiedReadingProfile=PROFILE,
        **context.identity(candidate,sync_raw,notation_raw,canonical),
        qualification='qualified-source-reading-coordinate-not-isolated-performance',
        pitchedReadingReferences=rows,quarterRepresentatives=representatives,readonlyRestIds=rests,
        readonlyRestSeekAllowed=False,physicalPerformanceGold=False,isolatedSingerPitchAttackReleaseGold=False,
        allPrintedWordsAcousticallyConfirmed=False)


def pending_ui_inputs(spec,candidate,sync_raw,notation_raw,canonical):
    """Unsigned genuine graph template, not the normal Root decision factory."""
    expected=context.identity(candidate,sync_raw,notation_raw,canonical)
    _,original,reps,_,rests=clock.reading_projection(candidate,sync_raw,notation_raw,canonical)
    base=dict(qualifiedReadingProfile=PROFILE,**expected,sourcePDFsha256=candidate['sourcePDFsha256'],
        frontend=copy.deepcopy(candidate['frontend']),physicalPerformanceGold=False)
    decision=dict(base,schema=UI_SCHEMA,status='pending-root-normal-native-ui-review',approved=False,reviewedBy=None,
        scope='current-normal-native-complete-source-reading-only',rootV6DecisionSha256=spec.get('rootV6DecisionSha256'),
        browserAuditSha256=spec.get('browserAuditSha256'))
    cap=dict(base,schema=CAP_SCHEMA,status='pending-root-normal-source-reading-capability',scope=CAP_SCOPE,
        approved=False,reviewedBy=None,**{k:spec.get(k) for k in REFS if k!='capabilitySha256'},
        coreRendererSha256=copy.deepcopy(candidate['frontend']['coreSha256']),physicalCounts=original['physicalCounts'],
        automaticEventIndices=[r['eventIndex'] for r in reps],readonlyRestIds=rests,
        normalV6Approved=False,normalUIApproved=False,publicAdmissionAllowed=False,formalAccepted=False)
    return decision,cap


def validate_browser(browser,candidate,sync_raw,notation_raw,canonical,hashes,resolve):
    expected=context.identity(candidate,sync_raw,notation_raw,canonical)
    require(browser.get('schema')==BROWSER_SCHEMA and browser.get('status')=='passed' and
        browser.get('qualifiedReadingProfile')==PROFILE and all(browser.get(k)==v for k,v in expected.items()) and
        same(browser.get('frontend'),candidate['frontend']),'Actual current complete SATB browser originals missing')
    _,sync,notation=clock.identity(candidate,sync_raw,notation_raw,canonical)
    _,_,reps,_,rests=clock.reading_projection(candidate,sync_raw,notation_raw,canonical)
    events=sync['events'];parts=[p['id'] for p in notation['sourceParts']]
    actions=browser.get('actions');readonly=browser.get('readonlyActions')
    require(type(actions) is list and len(actions)==len(events)*4 and type(readonly) is list and len(readonly)==len(rests)*4,
        'Complete native 222x4 note and35x4 readonly scopes are mandatory')
    for width,mode in SCOPES:
        rows=[r for r in actions if (r['width'],r['view'])==(width,mode)]
        require(len(rows)==len(events) and {r['eventIndex'] for r in rows}==set(range(len(events))),
            'Native note scope duplicates or excludes original heads')
        for row in rows:
            require(type(row['eventIndex']) is int,'Actual native physical index must be an integer')
            e=events[row['eventIndex']];raw=captured(row,hashes,resolve)
            require(raw['action']=='native-Enter' and raw['sourcePhysicalId']==e['sourcePhysicalId'] and
                raw['eventIndex']==e['eventIndex'] and raw['expectedTime']==e['time'],'Original native action/source identity differs')
            audio_at(raw['after']['audio'],candidate,e['time'],True)
            frame_at(raw['after']['frame'],width,mode,parts,e['sourceQuarter'])
            require(raw['after']['frame']['selectedSourcePhysicalId']==e['sourcePhysicalId'],'Selected original head differs')
        rrows=[r for r in readonly if (r['width'],r['view'])==(width,mode)]
        require(len(rrows)==len(rests) and {r['sourcePhysicalId'] for r in rrows}==set(rests),'Readonly rest scope incomplete')
        for row in rrows:
            raw=captured(row,hashes,resolve)
            require(raw['sourcePhysicalId']==row['sourcePhysicalId'] and raw['action']=='native-readonly-inspection' and
                raw['role']=='img' and raw['timeAttribute'] is None and raw['eventIndexAttribute'] is None and
                raw['tabindexAttribute'] is None and raw['seekEmitted'] is False and same(raw['beforeAudio'],raw['afterAudio']),
                'An untimed source rest received navigation or audio timing')
            audio_at(raw['afterAudio'],candidate)
    photos=browser.get('screenshots',[])
    require({(r['width'],r['view']) for r in photos}==SCOPES and len({r['sha256'] for r in photos})>=4,'Four actual normal screenshot scopes required')
    for row in photos:
        original=source.bound(row['sha256'],hashes,resolve,binary=True)
        require(original.startswith(b'\x89PNG\r\n\x1a\n') or original.startswith(b'\xff\xd8\xff'),'Actual original PNG/JPEG browser photograph bytes required')
    natural=browser.get('naturalPlayback',[]);covered=set();gaps=set();ended=set();starts=set()
    for row in natural:
        raw=captured(row,hashes,resolve);audio=raw['audio'];frame=raw['frame'];key=(row['width'],row['view'])
        require(key in SCOPES and raw['nativeContinuousPlayback'] is True and raw['seekDuringPlayback'] is False,
            'Natural UI evidence used seeking or wrong original scope')
        audio_at(audio,candidate);time=frame['time']
        # Natural playback is sampled between parent message deliveries. This
        # bounded UI transport age is not a measured decoder/PCM origin.
        require(clock.finite(time) and 0<=audio['time']-time<=.15,'Actual frame clock is ahead or stale relative to parent audio')
        if audio['time']<.003:starts.add(key)
        eligible=[r for r in reps if r['time']<=time];last=eligible[-1] if eligible else None
        final=max(e['endTime'] for e in events)
        if last and time<final:
            require(audio['paused'] is False,'Natural visible cue was not observed during actual playback')
            frame_at(frame,row['width'],row['view'],parts,frame['sourceQuarter']);covered.add(key)
            points=[{'time':r['time'],'q':r['sourceQuarter']} for r in reps]
            points.append({'time':final,'q':max(e['sourceQuarterEnd'] for e in events)})
            idx=next(i for i,p in enumerate(points) if p['time']>time)
            a,b=points[idx-1],points[idx];q=a['q']+(time-a['time'])/(b['time']-a['time'])*(b['q']-a['q'])
            require(abs(frame['sourceQuarter']-q)<.00001,'Natural whole-source reading coordinate differs')
        else:
            require(frame['cursorLineCount']==0,'Source gap or EOF retained a cue');gaps.add(key)
        if audio['ended']:
            require(audio['paused'] is True and abs(audio['time']-audio['duration'])<.003 and frame['cursorLineCount']==0,'Natural EOF not ended and clear')
            ended.add(key)
    require(covered==gaps==ended==starts==SCOPES,'Four natural zero/visible/gap/EOF scopes incomplete')
    navigation=browser.get('navigation',[])
    require({r['test'] for r in navigation}>= {'manual-scroll','resume','size','expanded-exit','play-pause'},'Actual stock navigation evidence missing')
    for row in navigation:
        require(captured(row,hashes,resolve).get('passed') is True,'Original stock navigation failed')
    return True


@dataclass(frozen=True)
class ValidatedCompleteSATBNormalUI:
    _token:object
    _owner:object
    followId:str
    references:dict
    identity:dict
    automaticEventIndices:tuple
    normalAdmissionValidated:bool=False
    physicalPerformanceGold:bool=False


def check_ui_result(result,spec,candidate,sync_raw,notation_raw,canonical,resolve):
    entry=_LIVE.get(id(result));owner=getattr(resolve,'__self__',resolve)
    require(type(result) is ValidatedCompleteSATBNormalUI and result._token is _TOKEN and entry is not None and entry[0]() is result and
        entry[1]==source.digest({k:v for k,v in vars(result).items() if k not in ('_token','_owner')}) and result._owner is owner and
        not getattr(owner,'closed',False) and same(result.references,{k:spec[k] for k in REFS}) and
        same(result.identity,context.identity(candidate,sync_raw,notation_raw,canonical)) and
        result.normalAdmissionValidated is False and result.physicalPerformanceGold is False,'Actual live normal UI type invented or borrowed')
    return True


def validate_ui(spec,candidate,sync_raw,notation_raw,canonical,hashes,resolve,*,context_result):
    require(type(spec) is dict and set(spec)=={'kind',*REFS} and spec['kind']==KIND,'Explicit complete normal SATB UI spec required')
    cs={k:spec[k] for k in context.REFS};cs['kind']=context.KIND
    context.check_context_result(context_result,cs,candidate,sync_raw,notation_raw,canonical,resolve)
    for k in REFS:require(source.is_sha(spec[k]),'Normal UI original reference missing')
    browser=context.body(spec['browserAuditSha256'],hashes,resolve);validate_browser(browser,candidate,sync_raw,notation_raw,canonical,hashes,resolve)
    expected=context.identity(candidate,sync_raw,notation_raw,canonical)
    decision=context.body(spec['rootNormalUIDecisionSha256'],hashes,resolve);cap=context.body(spec['capabilitySha256'],hashes,resolve)
    require(decision.get('schema')==UI_SCHEMA and decision.get('approved') is True and decision.get('reviewedBy')=='/root' and
        decision.get('scope')=='current-normal-native-complete-source-reading-only','Actual normal Root UI approval is pending')
    for value in (decision,cap):
        require(value.get('qualifiedReadingProfile')==PROFILE and all(value.get(k)==v for k,v in expected.items()) and
            value.get('sourcePDFsha256')==candidate['sourcePDFsha256'] and same(value.get('frontend'),candidate['frontend']) and
            value.get('physicalPerformanceGold') is False,'Normal UI identity/assets/qualification differs')
    require(decision.get('rootV6DecisionSha256')==spec['rootV6DecisionSha256'] and decision.get('browserAuditSha256')==spec['browserAuditSha256'],
        'Root normal UI does not bind actual version/browser')
    require(cap.get('schema')==CAP_SCHEMA and cap.get('scope')==CAP_SCOPE and cap.get('approved') is True and cap.get('reviewedBy')=='/root' and
        cap.get('publicAdmissionAllowed') is True and cap.get('normalV6Approved') is True and cap.get('normalUIApproved') is True,
        'Private/review capability cannot enable public admission')
    for k in REFS:
        if k!='capabilitySha256':require(cap.get(k)==spec[k],'Normal capability original graph differs: '+k)
    require(same(cap.get('coreRendererSha256'),candidate['frontend']['coreSha256']) and
        same(context.body(spec['performanceMapSha256'],hashes,resolve),performance_map(candidate,sync_raw,notation_raw,canonical)),
        'Actual whole-source qualified map/core changed')
    _,sync,notation=clock.identity(candidate,sync_raw,notation_raw,canonical)
    _,_,reps,_,rests=clock.reading_projection(candidate,sync_raw,notation_raw,canonical);indices=tuple(r['eventIndex'] for r in reps)
    require(cap.get('automaticEventIndices')==list(indices) and cap.get('readonlyRestIds')==rests and
        same(cap.get('physicalCounts'),context.scope(candidate,canonical)['physicalCounts']), 'Normal capability excluded physical source entries')
    result=ValidatedCompleteSATBNormalUI(_TOKEN,getattr(resolve,'__self__',resolve),candidate['id'],{k:spec[k] for k in REFS},expected,indices)
    identifier=id(result);_LIVE[identifier]=(weakref.ref(result,lambda r:_LIVE.pop(identifier,None)),source.digest({k:v for k,v in vars(result).items() if k not in ('_token','_owner')}))
    return result
