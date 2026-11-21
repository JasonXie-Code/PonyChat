"""One certificate-bound source-system sidecar; no general evidence-file route."""
import json
from pathlib import Path
import re

from follow_acceptance import file_sha256
from follow_frontend import accepted_frontend_path

FID='laughter-song'
RELATIVE='generated/laughter-song/acceptance-evidence/reading-clock-source-systems.json'
SCHEMA='reviewed-signed-reading-clock-correction/v1'


def require(value):
    if not value:raise ValueError('Not a current signed clock-system sidecar')


def local(follow,relative):
    require(isinstance(relative,str) and not relative.startswith(('/','\\'))
        and '\\' not in relative and ':' not in relative
        and all(p not in ('','.','..') for p in relative.split('/')))
    root=Path(follow).resolve();path=(root/relative).resolve()
    require(path.is_relative_to(root) and path.is_file())
    return path


def response_path(version,relative,follow,web,entries):
    require(relative==RELATIVE and re.fullmatch(r'[a-f0-9]{64}',version))
    matches=[m for m in entries.values() if m.get('id')==FID];require(len(matches)==1)
    meta=matches[0];approval=meta.get('acceptance',{})
    require(approval.get('sha256')==version and accepted_frontend_path(meta,follow,web)==
        '/follow-media/v/'+version+'/'+meta['frontend']['frame'])
    cert_path=local(follow,'generated/'+FID+'/acceptance.json')
    require(file_sha256(cert_path)==version);cert=json.loads(cert_path.read_text('utf8'))
    require(cert.get('schemaVersion')==1 and cert.get('status')=='approved' and cert.get('followId')==FID
        and cert.get('sourceSongId')==meta['sourceSongId'] and cert.get('qualifiedSignatureScope')
        and all(cert.get('gates',{}).get(k) is True for k in ('machine','sourceScore','audioIndependent','visual')))
    scope=cert.get('signedCorrection',{})
    require(isinstance(scope,dict) and set(scope)=={'schema','followId','songId','beforeStateSha256',
        'oldCertificateSha256','canonicalSha256','changes','evidence'}
        and all(isinstance(scope[k],str) and re.fullmatch(r'[a-f0-9]{64}',scope[k])
            for k in ('beforeStateSha256','oldCertificateSha256','canonicalSha256'))
        and scope.get('schema')==SCHEMA and scope.get('followId')==FID
        and scope.get('songId')==meta['sourceSongId'] and isinstance(scope.get('changes'),list) and scope['changes'])
    changes=scope['changes'];prefix='generated/'+FID+'/'
    require(len({r['path'] for r in changes})==len(changes))
    for change in changes:
        path=change['path']
        allowed=path in {prefix+n for n in ('sync.json','notation.json','jianpu.json','candidate.json','report.json')}
        allowed=allowed or (path.startswith(prefix+'acceptance-evidence/') and Path(path).suffix=='.json')
        allowed=allowed or (path.startswith(prefix+'accepted-frontend/') and Path(path).suffix in {'.js','.css','.html'})
        require(set(change)=={'path','oldSha256','newSha256'} and allowed and change['path'].startswith(prefix)
            and '\\' not in change['path'] and all(p not in ('','.','..') for p in change['path'].split('/'))
            and all(re.fullmatch(r'[a-f0-9]{64}',change[k]) for k in ('oldSha256','newSha256'))
            and change['oldSha256']!=change['newSha256'])
    declared={r['path']:r for r in changes}
    require({prefix+n for n in ('sync.json','notation.json','jianpu.json')}<=set(declared))
    rows=cert['bindings'];require(isinstance(rows,list))
    def bound(path):
        matching=[r for r in rows if r.get('kind')=='follow' and r.get('path')==path]
        require(len(matching)==1 and re.fullmatch(r'[a-f0-9]{64}',matching[0].get('sha256','')))
        target=local(follow,path);require(file_sha256(target)==matching[0]['sha256'])
        return target,matching[0]['sha256']
    def document(digest):
        require(isinstance(digest,str) and re.fullmatch(r'[a-f0-9]{64}',digest))
        matching=[r for r in rows if r.get('kind')=='follow' and r.get('sha256')==digest];require(matching)
        target=local(follow,matching[0]['path']);require(file_sha256(target)==digest)
        return json.loads(target.read_text('utf8'))
    evidence=scope.get('evidence',{})
    require(set(evidence)=={'rootDecision','conservation','sourceAudit','audioAudit','actualUiAudit'})
    decision=document(evidence['rootDecision']);proof=document(evidence['conservation'])
    require(decision.get('schema')=='root-signed-reading-clock-correction-decision/v1'
        and decision.get('status')=='root-approved-qualified-reading-clock-correction' and decision.get('reviewedBy')=='/root'
        and all(decision.get(k) is True for k in ('approved','sourceApproved','audioApproved','visualApproved'))
        and decision.get('followId')==FID and decision.get('sourceSongId')==meta['sourceSongId']
        and decision.get('oldCertificateSha256')==scope.get('oldCertificateSha256')
        and decision.get('beforeStateSha256')==scope.get('beforeStateSha256')
        and decision.get('canonicalSha256')==scope.get('canonicalSha256')
        and decision.get('changes')==scope['changes']
        and decision.get('evidenceSha256')=={k:v for k,v in evidence.items() if k!='rootDecision'}
        and decision.get('performedAttackGoldAdded') is False and decision.get('acousticReleaseGoldAdded') is False)
    require(proof.get('schema')=='same-canonical-reading-clock-conservation/v1'
        and proof.get('canonicalSha256')==scope['canonicalSha256'] and proof.get('followId')==FID
        and proof.get('sourceSongId')==meta['sourceSongId'])
    sync_path,sync_sha=bound(prefix+'sync.json');_,notation_sha=bound(prefix+'notation.json')
    _,jianpu_sha=bound(prefix+'jianpu.json')
    require(declared[prefix+'sync.json']['newSha256']==sync_sha
        and declared[prefix+'notation.json']['newSha256']==declared[prefix+'jianpu.json']['newSha256']==notation_sha==jianpu_sha)
    require(proof['music']['newSync']['sha256']==sync_sha and proof['music']['newNotation']['sha256']==notation_sha)
    for key in ('sourceAudit','audioAudit','actualUiAudit'):
        audit=document(evidence[key]);require(audit.get('followId')==FID and audit.get('status')=='passed')
        if key=='sourceAudit':require(audit.get('canonicalSha256')==scope['canonicalSha256'])
        else:require(audit.get('syncSha256')==sync_sha and audit.get('notationSha256')==notation_sha)
    canonical_path,canonical_sha=bound(cert['canonicalMusicxml']);require(canonical_sha==scope['canonicalSha256'])
    path,digest=bound(RELATIVE);side=json.loads(path.read_text('utf8'));sync=json.loads(sync_path.read_text('utf8'))
    require(side.get('schema')=='original-score-systems/v1' and side['song']['followId']==FID
        and side['song']['syncSha256']==sync_sha and side['song']['notationSha256']==notation_sha)
    systems=side['song']['events'];events=sync['events']
    require(len(systems)==len(events) and all(type(r.get('eventIndex')) is int for r in systems)
        and sorted(r['eventIndex'] for r in systems)==list(range(len(events))))
    for row in systems:
        event=events[row['eventIndex']]
        require(row['time']==event['time'] and row['measure']==str(event['measure'])
            and row['visual']=={k:event['visual'][k] for k in row['visual']})
    return path,digest
