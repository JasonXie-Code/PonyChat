"""Exact native rectangle/union coverage for the explicitly typed source model.

No source, clock, model or UI approval is created. The existing unmeasured-rest
path is unchanged; explicit measured readonly rests require original-ink proof.
Pitched/X and opted-in measured rest visible ink must not be clipped.
"""
import json
import math


def require(value,message):
    if not value: raise ValueError(message)


def same(a,b):
    return json.dumps(a,sort_keys=True,separators=(',',':'),allow_nan=False)==json.dumps(b,sort_keys=True,separators=(',',':'),allow_nan=False)


def finite(value): return type(value) in (int,float) and math.isfinite(value)


def rectangle(row):
    require(type(row) is list and len(row)==4 and all(finite(v) for v in row)
        and row[0]<row[2] and row[1]<row[3],'Finite nonempty native clip rectangle required')
    return row


def covers(regions,box):
    """Full rectangle union coverage; four corners alone can hide a middle gap."""
    rectangle(box)
    xs=sorted({box[0],box[2],*[v for r in regions for v in (r[0],r[2]) if box[0]<v<box[2]]})
    ys=sorted({box[1],box[3],*[v for r in regions for v in (r[1],r[3]) if box[1]<v<box[3]]})
    return all(any(r[0]<=x<=r[2] and r[1]<=y<=r[3] for r in regions)
        for x in [(a+b)/2 for a,b in zip(xs,xs[1:])]
        for y in [(a+b)/2 for a,b in zip(ys,ys[1:])])


def validate(system,native,page,events):
    primary=rectangle(system['rect'])
    if 'displayClipRegions' in system or 'displayClipRegions' in native:
        regions=system.get('displayClipRegions')
        require(type(regions) is list and regions and same(regions,native.get('displayClipRegions'))
            and type(system.get('displayClipQualification')) is str and system['displayClipQualification'].strip()
            and ('displayClipQualification' not in native or system['displayClipQualification']==native['displayClipQualification']),
            'Actual model/native union clip or qualification differs')
        for region in regions: rectangle(region)
        envelope=[min(r[0] for r in regions),min(r[1] for r in regions),max(r[2] for r in regions),max(r[3] for r in regions)]
        require(same(primary,envelope) and same(native.get('rect'),primary),
            'Native viewbox is not the exact union envelope')
    else:
        regions=[primary]
    require(type(page.get('widthPdfPoints')) in (int,float) and finite(page['widthPdfPoints'])
        and type(page.get('heightPdfPoints')) in (int,float) and finite(page['heightPdfPoints']), 'Actual native page dimensions required')
    for region in regions:
        rectangle(region)
        require(0<=region[0]<region[2]<=page['widthPdfPoints']
            and 0<=region[1]<region[3]<=page['heightPdfPoints'],'Union clip escapes actual page')
    require(events and all(e.get('nativeSystemId')==system['sourceSystemId'] for e in events),
        'Clip events belong to another actual system')
    measured=0;midpoint_only=0;measured_rests=0
    for event in events:
        bounds=event.get('nativeInkBounds')
        if event.get('isRest') is True and event.get('readonlyRestGeometry')=='measured-original-readonly-rest-ink/v1':
            require(event.get('sourceKind')=='rest' and event.get('isUnpitched') is False
                and event.get('seekAllowed') is False and event.get('cursorPrimary') is False
                and all(event.get(k) is None for k in ('pitch','sourcePitch','soundingPitch','midi',
                    'time','endTime','eventIndex','sourceReadingTime','sourceReadingEndTime')),
                'Measured readonly rest acquired pitch, time or seek')
            require(type(bounds) is dict and all(finite(bounds.get(k)) for k in ('x','y','width','height'))
                and bounds['width']>0 and bounds['height']>0
                and event.get('centerBasis')=='actual-original-PDF-rendered-visible-rest-ink',
                'Explicit measured readonly-rest ink required')
            actual=event.get('originalGlyph',{})
            registration=actual.get('registration',{});selected=registration.get('selected',{})
            require(actual.get('sourcePhysicalId')==event.get('id')==event.get('sourcePhysicalId')
                and actual.get('sourceKind')=='rest' and actual.get('usesFontBBoxCenter') is False
                and actual.get('usesCanonicalPitchForMeasurement') is False
                and same(actual.get('actualInkBoundsPdfPoints'),bounds)
                and same(actual.get('actualInkCenterPdfPoints'),event.get('nativePoint'))
                and registration.get('mechanicalIsolationSupported') is True
                and finite(selected.get('directMatch')) and selected['directMatch']>.97
                and finite(selected.get('supportWithinOnePixel')) and selected['supportWithinOnePixel']>.995,
                'Measured readonly-rest provenance differs from actual source ink')
            box=[bounds['x'],bounds['y'],bounds['x']+bounds['width'],bounds['y']+bounds['height']]
            require(covers(regions,box),'Native crop clips actual measured readonly rest')
            measured_rests+=1
        elif event.get('isRest') is True:
            require(bounds is None and event.get('centerBasis')=='actual-original-font-glyph-bounds-midpoint-not-measured-visible-rest-ink',
                'Rest glyph midpoint became a measured visible-ink claim')
            point=event['nativePoint'];require(finite(point['x']) and finite(point['y'])
                and any(r[0]<=point['x']<=r[2] and r[1]<=point['y']<=r[3] for r in regions),
                'Readonly rest midpoint is outside native display')
            midpoint_only+=1
        else:
            require(type(bounds) is dict and all(finite(bounds.get(k)) for k in ('x','y','width','height'))
                and bounds['width']>0 and bounds['height']>0
                and event.get('centerBasis')=='actual-original-PDF-rendered-visible-head-ink',
                'Actual measured pitched/X ink required')
            box=[bounds['x'],bounds['y'],bounds['x']+bounds['width'],bounds['y']+bounds['height']]
            require(covers(regions,box),'Native crop clips actual measured pitched/X head')
            measured+=1
    result=dict(measuredHeadInkCovered=measured,unmeasuredRestMidpointsCovered=midpoint_only,
        recordingTimeApproved=False,sourceModelApproved=False,normalUIApproved=False)
    if measured_rests:result['measuredReadonlyRestInkCovered']=measured_rests
    return result
