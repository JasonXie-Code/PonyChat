"""Deployable normal ensemble lifecycle rebuilt from the signed full graph."""
import copy
import os
from pathlib import Path

try:
    from . import complete_ensemble_occurrence_normal_v1 as context
    from . import complete_ensemble_occurrence_ui_v1 as ui
    from . import complete_ensemble_normal_v1 as registration
    from .complete_ensemble_occurrence_contract_v1 import certificate_scope,validate_metadata
    from .follow_acceptance import binding_path, bindings_match, file_sha256
    from .follow_frontend import frontend_assets
except ImportError:
    import complete_ensemble_occurrence_normal_v1 as context
    import complete_ensemble_occurrence_ui_v1 as ui
    import complete_ensemble_normal_v1 as registration
    from complete_ensemble_occurrence_contract_v1 import certificate_scope,validate_metadata
    from follow_acceptance import binding_path, bindings_match, file_sha256
    from follow_frontend import frontend_assets

try:
    from .bounded_original_validation_v1 import (initialize_raw_budget,
        budgeted_original_bytes, close_raw_budget, serialized_original_validation, same_original_bytes)
except ImportError:
    from bounded_original_validation_v1 import (initialize_raw_budget,
        budgeted_original_bytes, close_raw_budget, serialized_original_validation, same_original_bytes)

source = context.source
PROFILE = context.PROFILE
require, same = source.require, source.same


def opted(meta, sync):
    declared = meta.get('qualifiedReadingProfile') == PROFILE
    if declared or sync.get('qualifiedReadingProfile')==PROFILE:
        require(declared and sync.get('qualifiedReadingProfile')==PROFILE,'One-sided occurrence lifecycle profile differs')
    return declared


class CertificateResolver:
    closed = False

    def __init__(self, rows, follow, media):
        require(bindings_match(rows, follow, media), 'Actual normal ensemble certificate binding changed')
        self.paths = {}; self.closed = False
        initialize_raw_budget(self)
        for row in rows:
            path = binding_path(row, follow, media); digest = row['sha256']
            if digest in self.paths:
                require(same_original_bytes(self.paths[digest], path), 'Ambiguous original certificate body')
            self.paths[digest] = path

    def resolve(self, digest, raw_bytes=False):
        require(not self.closed, 'Normal ensemble original resolver is closed')
        require(digest in self.paths, 'Normal ensemble original is not certificate-bound')
        raw = budgeted_original_bytes(self, digest, source)
        return raw if raw_bytes else source.strict_json(raw)

    def __enter__(self):
        require(not self.closed, 'Normal ensemble original resolver is closed')
        return self

    def __exit__(self, exc_type, exc, traceback):
        close_raw_budget(self, source)
        return False


def metadata_matches(candidate, meta):
    pointer = meta.get('acceptance')
    require(type(pointer) is dict and set(pointer) == {'certificate', 'sha256'}, 'Exact certificate pointer required')
    expected = {k: v for k, v in candidate.items() if k not in ('attempts', 'acceptance')}
    expected['acceptance'] = pointer
    require(same(expected, meta), 'Normal ensemble catalog projection changed source/musical metadata')


@serialized_original_validation
def validate_graph(meta, report, notation, sync, follow, media):
    require(opted(meta, sync), 'Independent normal ensemble lifecycle required')
    follow, media = Path(follow).resolve(), Path(media).resolve()
    fid = meta['id']; folder = follow / 'generated' / fid
    # Logical EG recording IDs differ from their catalog-registered media paths.
    # Reuse the strict SID/FID/path registration check, never infer an alias.
    registration.registered_audio_path(meta)
    require(meta['scorePdf'] == '/scores/' + meta['sourceScoreId'], 'Normal original score locator differs')
    pointer = meta.get('acceptance', {})
    require(pointer.get('certificate') == '/generated/' + fid + '/acceptance.json', 'Normal certificate locator differs')
    cp = folder / 'acceptance.json'
    require(file_sha256(cp) == pointer.get('sha256'), 'Normal certificate bytes changed or are missing')
    cert = source.strict_json(cp.read_bytes())
    require(cert.get('schemaVersion') == 1 and cert.get('status') == 'approved'
            and cert.get('reviewedBy') == '/root' and cert.get('signedAt')
            and cert.get('followId') == fid and cert.get('sourceSongId') == meta['sourceSongId']
            and cert.get('sourceScoreId') == meta['sourceScoreId'] and cert.get('reasons') == []
            and set(cert.get('gates', {})) == {'machine', 'sourceScore', 'audioIndependent', 'visual'}
            and all(v is True for v in cert['gates'].values()), 'Genuine normal four-gate certificate is pending')
    with CertificateResolver(cert['bindings'], follow, media) as resolver:
        resolver.paths[pointer['sha256']] = cp; hashes = set(resolver.paths)
        required = {('follow', f'generated/{fid}/{name}') for name in (
            'candidate.json', 'sync.json', 'notation.json', 'jianpu.json', 'report.json', 'analysis.json', 'source-provenance.json', 'normal-context.original.json')}
        required |= {('media', meta[k].lstrip('/')) for k in ('audio', 'scorePdf')}
        canonical_path = cert['canonicalMusicxml']
        canonical_target = (follow / canonical_path).resolve()
        require(canonical_path.startswith('generated/' + fid + '/') and canonical_target.is_relative_to(folder),
                'Normal canonical locator escaped the selected recording')
        required.add(('follow', canonical_path))
        charts = []
        for locator in meta['charts']:
            path = locator.removeprefix('/follow-media/').removeprefix('/')
            require(path.startswith('source/charts/') and (follow / path).resolve().is_relative_to(follow / 'source/charts')
                    and (follow / path).is_file(), 'Original source chart locator escaped or is missing')
            charts.append(path); required.add(('follow', path))
        require(charts, 'Actual original-paper chart assets missing')
        web = Path(os.environ.get('MLP_WEB_ROOT', str(Path(__file__).resolve().parents[1] / 'web')))
        required |= {('follow', path) for path, _, _ in frontend_assets(meta, follow, web)}
        require(required <= {(row['kind'], row['path']) for row in cert['bindings']},
                'Normal certificate omitted runtime/original media/renderer resources')
        def raw(name):
            return (folder / name).read_bytes()
        candidate = source.strict_json(raw('candidate.json'))
        sr, nr, canonical = raw('sync.json'), raw('notation.json'), canonical_target.read_bytes()
        metadata_matches(candidate, meta)
        require(same(source.strict_json(raw('report.json')), report)
                and same(source.strict_json(nr), notation) and same(source.strict_json(raw('jianpu.json')), notation),
                'Current normal report or flat/nested jianpu bytes changed')
        original_sync = source.strict_json(sr)
        require(all('accepted' not in b or type(b['accepted']) is bool for b in (original_sync, sync))
                and same({k: v for k, v in original_sync.items() if k != 'accepted'},
                         {k: v for k, v in sync.items() if k != 'accepted'}), 'API lifecycle changed musical sync')
        require(same(report.get('quality'), meta.get('quality'))
                and all(meta['quality'].get(k) is True for k in ('accepted', 'machineAccepted', 'visualAccepted', 'musicPassed', 'audioAccepted')),
                'Normal machine/source/audio/UI lifecycle is pending')
        require(file_sha256(media / meta['audio'].lstrip('/')) == meta['sourceAudioSha256']
                and file_sha256(media / meta['scorePdf'].lstrip('/')) == meta['sourcePDFsha256'], 'Actual original MP3/PDF bytes changed')
        proof = cert.get('sourceReadingMachineQualification', {})
        require(proof.get('schema') == 'validated-source-reading-machine/v1'
                and proof.get('qualifiedReadingProfile') == PROFILE, 'Actual normal ensemble machine proof missing')
        cs, us = proof['qualifiedContextInputs'], proof['sourceReadingCursorCapability']
        require(set(cs)=={'kind',*context.REFS} and set(us)=={'kind','browserAuditSha256','performanceMapSha256','rootNormalUIDecisionSha256'},
            'Exact occurrence context/UI graph required')
        context_raw=raw('normal-context.original.json');context_sha=source.sha(context_raw)
        require(context_sha in hashes and same(source.strict_json(context_raw),cs),'Original occurrence context sidecar differs')
        checked=context.validate_context(cs,candidate,canonical,sr,nr,hashes,resolver.resolve)
        actual_ui=ui.validate_ui(us,cs,candidate,canonical,sr,nr,checked,hashes,resolver.resolve)
        payload=context.checked_payload(checked,cs,candidate,canonical,sr,nr,resolver.resolve)
        visited={e['sourcePhysicalId'] for e in payload['instances'] if e['sourceKind']=='pitch'}
        require(proof.get('rootV6DecisionSha256')==cs['rootV6DecisionSha256']
            and proof.get('physicalEntities')==len(payload['physicalSource'])
            and proof.get('pitchedHeads')==payload['physicalCounts']['pitch']
            and proof.get('readonlyEntities')==sum(p['sourcePhysicalId'] not in visited for p in payload['physicalSource'])
            and same(proof.get('automaticEvents'),list(range(len(original_sync['events'])))),'Occurrence physical/instance machine counts differ')
        version=resolver.resolve(cs['versionAuditSha256'])
        validate_metadata(version,resolver.resolve(cs['rootV6DecisionSha256']),resolver.resolve(cs['originalProposalSha256']))
        signature=cert.get('qualifiedSignatureScope',{})
        require(all(same(signature.get('versionReference',{}).get(k),v) for k,v in certificate_scope(version).items()),
            'Occurrence signed version metadata differs')
        require(same(signature.get('sourceReadingReferenceScope'),ui.performance_map(candidate,canonical,sr,nr,payload)),
            'Occurrence signed complete reference route/map differs')
        result = dict(followId=fid, canonicalPath=canonical_path, chartPaths=tuple(charts),
            automaticEventIndices=tuple(range(len(original_sync['events']))), syncSha256=source.sha(sr), notationSha256=source.sha(nr))
        authority=dict(mode='normal-sealed',profile=PROFILE,context=copy.deepcopy(cs),contextSha256=context_sha,
            normalAdmissionAllowed=True)
        for name,key in [('sourceDecision','sourceDecisionSha256'),('routeDecision','routeDecisionSha256'),('clockDecision','clockDecisionSha256'),('modelDecision','sourceModelDecisionSha256'),('rootV6Decision','rootV6DecisionSha256'),('originalModel','originalModelSha256'),('routeInput','routeInputSha256'),('rawClock','rawClockSha256'),('nativePaperGeometry','nativePaperGeometrySha256'),('originalInkGeometry','originalInkGeometrySha256'),('versionAudit','versionAuditSha256'),('originalProposal','originalProposalSha256'),('originalIndex','originalIndexSha256')]:
            original=resolver.resolve(cs[key],True);authority[name]=dict(sha256=cs[key],rawUtf8=original.decode('utf8'))
        original=resolver.resolve(us['rootNormalUIDecisionSha256'],True)
        authority['normalUIDecision']=dict(sha256=us['rootNormalUIDecisionSha256'],rawUtf8=original.decode('utf8'))
        authority['normalContext']=dict(sha256=context_sha,rawUtf8=context_raw.decode('utf8'))
        authority['certificate']=dict(sha256=pointer['sha256'],rawUtf8=resolver.resolve(pointer['sha256'],True).decode('utf8'))
        return result, authority


def validate(meta, report, notation, sync, follow, media):
    return validate_graph(meta, report, notation, sync, follow, media)[0]


def response(meta, report, notation, sync, follow, media):
    if not (meta.get('qualifiedReadingProfile') == PROFILE or sync.get('qualifiedReadingProfile') == PROFILE):
        return sync, None
    result, authority = validate_graph(meta, report, notation, sync, follow, media)
    require(result['followId'] == meta['id'], 'Normal validated recording identity differs')
    projected = copy.deepcopy(sync); projected['accepted'] = True
    return projected, authority
