"""Explicit original-model browser layout graph; grants no musical authority."""
import hashlib
import json

IDENTITY=('followId','sourceSongId','sourceScoreId','sourcePDFsha','canonicalSha256','sourceAudioSha256','syncSha256','notationSha256')

def require(value,message):
    if not value:raise ValueError(message)
def same(a,b):return json.dumps(a,sort_keys=True,separators=(',',':'))==json.dumps(b,sort_keys=True,separators=(',',':'))
def digest(raw):return hashlib.sha256(raw).hexdigest()
def bound(h,hashes,resolve,raw=False):
    require(type(h) is str and h in hashes,'Explicit bound original system body missing')
    value=resolve(h,True);require(digest(value)==h,'Bound original system bytes changed')
    return value if raw else json.loads(value)

def validate_model(evidence,candidate,sync,structural,hashes,resolve,notation):
    require(evidence.get('schema')=='complete-ensemble-original-browser-source-systems/v1','Explicit original browser source-system graph required')
    canonical=bound(evidence['canonicalSha256'],hashes,resolve,True)
    try:
        from . import complete_ensemble_normal_v1 as normal
    except ImportError:
        import complete_ensemble_normal_v1 as normal
    identity=normal.identity(candidate,canonical,bound(evidence['syncSha256'],hashes,resolve,True),bound(evidence['notationSha256'],hashes,resolve,True))
    require(all(evidence.get(k)==identity[k] for k in IDENTITY),'Original layout musical identity differs')
    model=bound(evidence['originalModelSha256'],hashes,resolve)
    native=bound(evidence['nativePaperGeometrySha256'],hashes,resolve)
    ink=bound(evidence['originalInkGeometrySha256'],hashes,resolve)
    source=bound(evidence['sourceDecisionSha256'],hashes,resolve)
    pdf=bound(evidence['sourcePDFsha'],hashes,resolve,True)
    require(pdf.startswith(b'%PDF-'),'Registered original PDF bytes required')
    require(source.get('approved') is True and source.get('sourcePassed') is True and source.get('reviewedBy')=='/root'
        and source.get('followId')==identity['followId'] and source.get('sourceScoreId')==identity['sourceScoreId']
        and source.get('canonicalSha256')==identity['canonicalSha256'] and source.get('sourcePDFsha256')==identity['sourcePDFsha'],
        'Original model/source Root identities differ')
    require(model['canonicalSha256']==native['canonicalSha256']==ink['canonicalSha256']==identity['canonicalSha256']
        and model['sourcePDFsha256']==native['sourcePDFsha256']==ink['sourcePDFsha256']==identity['sourcePDFsha']
        and model['sourceGeometrySha256']==native['sourceGeometrySha256']==evidence['originalInkGeometrySha256']
        and ink['followId']==identity['followId'],'Original model/PDF/native ink identity differs')
    require(same(model['privateNativeGeometry'],native)
        and model['nativePaperGeometryBinding']['sha256']==evidence['nativePaperGeometrySha256']
        and model['nativePaperGeometryBinding']['sourcePDFsha256']==identity['sourcePDFsha'],
        'Renderer original native geometry is a different body')
    require(notation['sourceSystemGeometry']['originalInk']['sha256']==evidence['originalInkGeometrySha256'],
        'Notation original ink locator differs')
    events=structural['projection']['physicalEvents'];by_id={e['sourcePhysicalId']:e for e in events}
    display=model['events'];ids={e['id'] for e in display}
    require(len(ids)==len(display)==len(events) and ids==set(by_id)==set(model['physicalInventory']['ids']),
        'Original model omitted or reused physical source entities')
    for event in display:
        original=by_id[event['id']]
        require(event['part']==original['sourcePart'] and event['measure']==original['measure']
            and event['q']==original['sourceQuarter'] and event['duration']==original['durationBeats']
            and event['rest'] is original['isRest'],'Original physical part/measure/quarter/duration differs')
    ink_rows=ink['notes']+ink['readonlyRests'];ink_by_id={r['sourceNoteId']:r for r in ink_rows}
    require(len(ink_rows)==len(ink_by_id)==len(events) and set(ink_by_id)==ids,'Original ink entity denominator differs')
    for event in display:
        actual=ink_by_id[event['id']]
        require(actual['sourcePart']==event['part'] and actual['measure']==event['measure']
            and actual['page']==event['nativePage'] and actual['staff']==event['nativeStaff'],'Physical source ink belongs to another staff/system')
    systems=model['originalSystems'];native_systems=native['systems']
    require(len(systems)==len(native_systems)>0 and len({s['sourceSystemId'] for s in systems})==len(systems),'Original native system inventory differs')
    covered=set();measures=set();results=[]
    require(len(evidence['sourceCropReferences'])==len(systems),'Every original display crop must be bound')
    part_ids=[p['id'] for p in structural['descriptor']['sourceParts']]
    for i,system in enumerate(systems):
        sid=system['sourceSystemId'];actual=native_systems[i]
        require(actual['sourceSystemId']==sid and actual['page']==system['page'] and actual['firstMeasure']==system['first']
            and actual['lastMeasure']==system['last'],'Registered native/display source system boundaries differ')
        members=[e for e in events if system['first']<=e['measure']<=system['last']]
        expected={e['sourcePhysicalId'] for e in members}
        parts=[p for p in part_ids if any(e['sourcePart']==p for e in members)]
        require(expected==set(system['physicalIds']) and not covered.intersection(expected)
            and parts==system['actualSourceParts']==actual['actualParts'],'Source system omitted/reused physical entities or source voices')
        covered.update(expected)
        bars=set(range(system['first'],system['last']+1));require(not measures.intersection(bars),'Overlapping original measure systems')
        measures.update(bars)
        staves=[s for s in native['staves'] if s['sourceSystemId']==sid]
        require([s['part'] for s in staves]==parts and all(s['page']==system['page'] and len(s['lines'])==5 for s in staves),
            'Registered physical source staff lanes differ')
        crop=evidence['sourceCropReferences'][i]
        require(crop['sourceSystemId']==sid and crop['sha256']==system['sha256'],'Original display crop registration differs')
        image=bound(crop['sha256'],hashes,resolve,True);require(image.startswith(b'\x89PNG\r\n\x1a\n'),'Actual original system PNG required')
        require(len(system['rect'])==4 and system['rect'][0]<system['rect'][2] and system['rect'][1]<system['rect'][3],
            'Original display crop rectangle missing')
        require(all(system['rect'][1]<=y<=system['rect'][3] for s in staves for y in s['lines']),
            'Original display crop cuts an actual source staff')
        results.append(dict(sourceSystemId=sid,firstMeasure=system['first'],lastMeasure=system['last'],actualParts=parts,page=system['page']))
    require(covered==set(by_id) and measures=={e['measure'] for e in events},'Complete original source system coverage missing')
    return results

def resolve_source_systems(browser,candidate,sync,structural,hashes,resolve,notation):
    ref=browser.get('sourceSystemEvidenceSha256')
    if ref is None:
        # Existing callers still take the unchanged notation.systems contract.
        return None
    evidence=bound(ref,hashes,resolve)
    decision=bound(evidence['rootOriginalModelDecisionSha256'],hashes,resolve)
    require(decision.get('schema')=='root-original-browser-source-system-model-decision/v1' and decision.get('approved') is True
        and decision.get('reviewedBy')=='/root' and decision.get('scope')=='original-source-display-systems-only'
        and decision.get('physicalPerformanceGold') is False,'Actual Root original source display-model approval missing')
    keys=(*IDENTITY,'originalModelSha256','nativePaperGeometrySha256','originalInkGeometrySha256','sourceDecisionSha256','sourceCropReferences')
    require(all(same(decision.get(k),evidence.get(k)) for k in keys),'Root original model graph differs')
    return validate_model(evidence,candidate,sync,structural,hashes,resolve,notation)
