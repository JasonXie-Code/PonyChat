"""Normal complete SATB admission rebuilds original typed source/V6/UI graph.

No review-only cap, JSON accepted marker, fabricated no-X partner or models are
substitutes. Ordinary public authority is derived from the same checked graph.
"""
from dataclasses import dataclass
import copy
import hashlib
import os
from pathlib import Path
import weakref
try:
    from . import complete_satb_normal_context_v1 as context
    from . import complete_satb_normal_ui_v1 as ui
    from .follow_acceptance import binding_path,bindings_match,file_sha256
    from .follow_frontend_tempo import frontend_assets
except ImportError:
    import complete_satb_normal_context_v1 as context
    import complete_satb_normal_ui_v1 as ui
    from follow_acceptance import binding_path,bindings_match,file_sha256
    from follow_frontend_tempo import frontend_assets

source,clock=context.source,context.clock
require,same=source.require,source.same
PROFILE=context.PROFILE
_TOKEN=object();_LIVE={}


def configured_web_root():
    """Use the same deployed web root as the ordinary music catalog."""
    return Path(os.environ.get('MLP_WEB_ROOT',str(Path(__file__).resolve().parents[1]/'web')))


def opted(meta,sync):
    declared=meta.get('qualifiedReadingProfile')==PROFILE
    if declared:
        require(sync.get('qualifiedReadingProfile',PROFILE)==PROFILE,'One-sided normal SATB profile differs')
        source.registration(meta['id'])
    return declared


def sync_lifecycle_matches(original,current):
    """Original may omit accepted; only a strict bool lifecycle overlay exists.

    Source validation also consumes the unchanged raw dict before the public
    API overlay. Neither a missing marker nor a true marker grants admission.
    """
    require(type(original) is dict and type(current) is dict and
        all('accepted' not in row or type(row['accepted']) is bool for row in (original,current)),
        'Invalid raw/API acceptance lifecycle type')
    require(same({k:v for k,v in original.items() if k!='accepted'},
                 {k:v for k,v in current.items() if k!='accepted'}),'API lifecycle overlay changed musical sync')
    return True


def metadata_lifecycle_matches(candidate,current):
    """Match the exact catalog projection used by normal certificate promotion.

    The catalog drops diagnostic attempts and adds the verified certificate
    pointer; those two publication fields are not musical metadata changes.
    Certificate bytes and authority are checked separately by validate_sealed.
    """
    require(type(candidate) is dict and type(current) is dict,'Invalid normal catalog metadata')
    pointer=current.get('acceptance')
    require(type(pointer) is dict and set(pointer)=={'certificate','sha256'} and
        source.is_sha(pointer.get('sha256')),'Exact normal certificate pointer required')
    if 'acceptance' in candidate:
        require(same(candidate['acceptance'],pointer),'Candidate certificate pointer changed')
    projected={k:v for k,v in candidate.items() if k not in ('attempts','acceptance')}
    projected['acceptance']=pointer
    require(same(projected,current),'Normal catalog projection changed source or musical metadata')
    return True


class CertificateResolver:
    closed=False
    def __init__(self,rows,follow,media):
        require(bindings_match(rows,follow,media),'Actual normal original certificate binding changed')
        self.paths={}
        for row in rows:
            path=binding_path(row,follow,media);h=row['sha256']
            if h in self.paths:require(self.paths[h].read_bytes()==path.read_bytes(),'Ambiguous original normal body')
            self.paths[h]=path
    def resolve(self,digest,raw_bytes=False):
        require(digest in self.paths,'Normal original SHA is not certificate-bound')
        raw=self.paths[digest].read_bytes()
        require(hashlib.sha256(raw).hexdigest()==digest,'Actual normal body changed after certificate validation')
        return raw if raw_bytes else context.strict_json(raw)


@dataclass(frozen=True)
class SealedCompleteSATBReading:
    _token:object
    resolver:object
    identity:dict
    result:dict
    authority:dict
    contextResult:object
    uiResult:object
    certificateSha256:str


def checked_result(value):
    entry=_LIVE.get(id(value))
    require(type(value) is SealedCompleteSATBReading and value._token is _TOKEN and entry is not None and entry[0]() is value and
        not value.resolver.closed and entry[1]==source.digest(dict(identity=value.identity,result=value.result,authority=value.authority,certificateSha256=value.certificateSha256)),
        'Actual typed normal sealed graph was invented or mutated')
    for h in value.resolver.paths:value.resolver.resolve(h,raw_bytes=True)
    return copy.deepcopy(value.result)


def validate_sealed(meta,report,notation,sync,follow,media):
    require(opted(meta,sync),'Explicit normal complete SATB source-reference opt-in required')
    follow,media=Path(follow).resolve(),Path(media).resolve();fid=meta['id'];folder=follow/'generated'/fid
    require(meta['audio']=='/audio/'+meta['sourceSongId'] and meta['scorePdf']=='/scores/'+meta['sourceScoreId'] and
        meta['generated'] in ('/generated/'+fid,'/follow-media/generated/'+fid),'Current normal original locators required')
    pointer=meta.get('acceptance',{})
    require(pointer.get('certificate')=='/generated/'+fid+'/acceptance.json' and source.is_sha(pointer.get('sha256')),
        'Normal acceptance certificate is pending')
    cp=folder/'acceptance.json';require(file_sha256(cp)==pointer['sha256'],'Normal acceptance certificate changed')
    cert=context.strict_json(cp.read_bytes())
    require(cert.get('schemaVersion')==1 and cert.get('status')=='approved' and cert.get('reviewedBy')=='/root' and cert.get('signedAt') and
        cert.get('followId')==fid and cert.get('sourceSongId')==meta['sourceSongId'] and cert.get('sourceScoreId')==meta['sourceScoreId'] and
        cert.get('reasons')==[] and set(cert.get('gates',{}))=={'machine','sourceScore','audioIndependent','visual'} and
        all(v is True for v in cert['gates'].values()),'Genuine full normal certificate is pending')
    resolver=CertificateResolver(cert['bindings'],follow,media)
    resolver.paths[pointer['sha256']]=cp;hashes=set(resolver.paths)
    required={('follow',f'generated/{fid}/{n}') for n in ('candidate.json','sync.json','notation.json','jianpu.json','report.json','analysis.json','source-provenance.json')}
    required|={('media',meta[k].lstrip('/')) for k in ('audio','scorePdf')}
    canonical_path=cert['canonicalMusicxml']
    require(canonical_path.startswith('generated/'+fid+'/omr/') and (follow/canonical_path).resolve().is_relative_to(folder/'omr'),
        'Exact installed original canonical locator required')
    required.add(('follow',canonical_path))
    charts=[]
    for locator in meta['charts']:
        path=locator.removeprefix('/follow-media/').removeprefix('/')
        require(path.startswith('source/charts/') and (follow/path).is_file(),'Original four-system chart resources required')
        charts.append(path);required.add(('follow',path))
    require(len(charts)==len(notation['sourceSystemGeometry']['pages']),'Complete original paper pages missing')
    required|={('follow',path) for path,_,_ in frontend_assets(meta,follow,configured_web_root())}
    require(required<={(r['kind'],r['path']) for r in cert['bindings']},'Normal certificate excludes required original runtime resources')
    def file(name):return (folder/name).read_bytes()
    candidate=context.strict_json(file('candidate.json'));sync_raw=file('sync.json');notation_raw=file('notation.json');canonical=(follow/canonical_path).read_bytes()
    require(metadata_lifecycle_matches(candidate,meta) and same(context.strict_json(file('report.json')),report) and
        same(context.strict_json(notation_raw),notation) and same(context.strict_json(file('jianpu.json')),notation),
        'Current normal metadata/report/flat+measure source body changed')
    disk_sync=context.strict_json(sync_raw)
    sync_lifecycle_matches(disk_sync,sync)
    require(same(report.get('quality'),meta.get('quality')) and all(meta['quality'].get(k) is True for k in
        ('accepted','machineAccepted','visualAccepted','musicPassed','audioAccepted')),'Normal lifecycle is pending')
    require(file_sha256(media/meta['audio'].lstrip('/'))==meta['sourceAudioSha256'] and
        file_sha256(media/meta['scorePdf'].lstrip('/'))==meta['sourcePDFsha256'],'Actual original recording/PDF bytes differ')
    proof=cert.get('sourceReadingMachineQualification',{})
    require(proof.get('schema')=='validated-source-reading-machine/v1' and proof.get('qualifiedReadingProfile')==PROFILE,
        'Actual normal complete SATB machine proof missing')
    cs=proof['qualifiedContextInputs'];us=proof['sourceReadingCursorCapability']
    require(set(cs)=={'kind',*context.REFS} and set(us)=={'kind',*ui.REFS} and all(us[k]==cs[k] for k in context.REFS),
        'Normal context/UI original typed graph differs')
    st=source.validate_source(cs['sourceAuditSha256'],cs['sourceDecisionSha256'],canonical,fid,hashes,resolver.resolve)
    ct=clock.validate_clock(cs['clockDecisionSha256'],candidate,sync_raw,notation_raw,canonical,st,hashes,resolver.resolve)
    vc=context.validate_context(cs,candidate,sync_raw,notation_raw,canonical,hashes,resolver.resolve,source_result=st,clock_result=ct)
    vu=ui.validate_ui(us,candidate,sync_raw,notation_raw,canonical,hashes,resolver.resolve,context_result=vc)
    authority=dict(mode='normal-sealed',profile=PROFILE)
    for name,key in [('sourceDecision','sourceDecisionSha256'),('clockDecision','clockDecisionSha256'),('capability','capabilitySha256')]:
        raw=resolver.resolve(us[key],raw_bytes=True);authority[name]=dict(sha256=us[key],rawUtf8=raw.decode('utf8'))
    authority['certificate']=dict(sha256=pointer['sha256'],rawUtf8=cp.read_bytes().decode('utf8'))
    result=dict(followId=fid,canonicalPath=canonical_path,chartPaths=tuple(charts),automaticEventIndices=vu.automaticEventIndices,
        syncSha256=clock.sha(sync_raw),notationSha256=clock.sha(notation_raw))
    sealed=SealedCompleteSATBReading(_TOKEN,resolver,context.identity(candidate,sync_raw,notation_raw,canonical),result,authority,vc,vu,pointer['sha256'])
    k=id(sealed);fingerprint=source.digest(dict(identity=sealed.identity,result=sealed.result,authority=sealed.authority,certificateSha256=sealed.certificateSha256))
    _LIVE[k]=(weakref.ref(sealed,lambda r:_LIVE.pop(k,None)),fingerprint)
    return sealed


def validate(meta,report,notation,sync,follow,media):
    """Shared existing SealedSourceReading factory consumes this exact result."""
    return checked_result(validate_sealed(meta,report,notation,sync,follow,media))


def public_authority(meta,report,notation,sync,follow,media):
    """Fresh graph at each ordinary public API response; no metadata flags."""
    result=validate_sealed(meta,report,notation,sync,follow,media);checked_result(result)
    return copy.deepcopy(result.authority)
