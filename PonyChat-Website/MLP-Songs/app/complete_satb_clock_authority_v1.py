"""Hash-bound common SATB reading clock and loopback authority, never admission.

Recording observations retain their real conditioning. Sparse unforced ASR is
not full phrase coverage; source-frequency queries are not a blind pitch bank.
"""
from dataclasses import dataclass
import copy
import hashlib
import math
import re
import struct
import weakref

try:
    from . import complete_satb_source_authority_v1 as source
except ImportError:
    import complete_satb_source_authority_v1 as source

PROFILE = source.PROFILE
CLOCK_SCHEMA = 'root-complete-satb-source-reading-clock-decision/v1'
CAP_SCHEMA = 'root-complete-satb-loopback-reading-capability/v1'
CLOCK_SCOPE = 'common-source-reading-coordinates-only-not-performance-gold'
CAP_SCOPE = 'loopback-only-normal-assets-review-not-normal-admission'
require, same, bound = source.require, source.same, source.bound
_TOKEN = object()
_LIVE = {}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def midi(pitch):
    match = re.fullmatch(r'([A-G])([#b]*)(-?\d+)', pitch)
    require(match is not None, 'Original spelled pitch required')
    return (int(match[3]) + 1) * 12 + dict(C=0, D=2, E=4, F=5, G=7, A=9, B=11)[match[1]] + match[2].count('#') - match[2].count('b')


def identity(candidate, sync_raw, notation_raw, canonical):
    sync = __import__('json').loads(sync_raw); notation = __import__('json').loads(notation_raw)
    fid = candidate['id']; reg = source.registration(fid)
    require(candidate.get('qualifiedReadingProfile') == PROFILE and
        candidate.get('sourceSongId') == sync.get('sourceSongId') == reg['sourceSongId'] and
        candidate.get('sourceScoreId') == sync.get('sourceScoreId') == reg['sourceScoreId'] and
        candidate.get('sourcePDFsha256') == reg['sourcePDFsha256'] and
        candidate.get('sourceAudioSha256') == sync.get('sourceAudioSha256') == reg['sourceAudioSha256'] and
        candidate.get('canonicalSha256') == sync.get('canonicalSha256') == notation.get('canonicalSha256') == sha(canonical),
        'Actual registered original SATB source/recording identity differs')
    return dict(qualifiedReadingProfile=PROFILE, followId=fid, sourceSongId=reg['sourceSongId'],
        sourceScoreId=reg['sourceScoreId'], sourcePDFsha256=reg['sourcePDFsha256'],
        sourceAudioSha256=reg['sourceAudioSha256'], canonicalSha256=sha(canonical),
        syncSha256=sha(sync_raw), notationSha256=sha(notation_raw)), sync, notation


def reading_projection(candidate, sync_raw, notation_raw, canonical):
    ids, sync, notation = identity(candidate, sync_raw, notation_raw, canonical)
    original = source.complete_projection(canonical, candidate['id'])
    rows = {r['sourcePhysicalId']: r for r in original['physicalEvents']}
    events = sync.get('events'); tokens = notation.get('tokens')
    require(type(events) is list and len(events) == original['physicalCounts']['pitch'] and
        type(tokens) is list and len(tokens) == len(rows) and len({t['id'] for t in tokens}) == len(rows),
        'Every original physical SATB note/rest must remain present')
    token_ids = {t['id']: t for t in tokens}; references = []; groups = {}
    require(set(token_ids) == set(rows), 'Notation dropped or invented physical source IDs')
    nested = [t for m in notation.get('measures', []) for t in m.get('tokens', [])]
    require(len(nested) == len(tokens) and len({t['id'] for t in nested}) == len(tokens) and
        all(same(t, token_ids.get(t['id'])) for t in nested), 'Flat and nested full physical tokens differ')
    for i, e in enumerate(events):
        r = rows.get(e.get('sourcePhysicalId')); t = token_ids.get(e.get('sourcePhysicalId'))
        require(r is not None and r['sourceKind'] == 'pitch' and e.get('eventIndex') == i and
            e.get('isRest') is False and e.get('partId') == r['sourcePart'] and
            e.get('pitch') == r['pitch'] and e.get('sourceQuarter') == r['sourceQuarter'] and
            e.get('sourceQuarterEnd') == r['sourceQuarter'] + r['durationBeats'] and
            e.get('noteDuration') == r['durationBeats'] and e.get('sourceNoteIndex') == r['sourceNoteIndex'] and
            e.get('chordTone') is r['chordTone'] and e.get('sourceVoice') == r['voice'] and
            e.get('tieContinuation') is any(x.get('type') == 'stop' for x in r['ties']) and
            t.get('sourcePart') == r['sourcePart'] and t.get('pitch') == r['pitch'] and t.get('midi') == midi(r['pitch']) and
            t.get('durationBeats') == r['durationBeats'] and t.get('sourceQuarter') == r['sourceQuarter'] and
            t.get('isRest') is False and t.get('isUnpitched') is False,
            'Original source rhythm/pitch/part identity differs from reading event')
        require(finite(e.get('time')) and finite(e.get('endTime')) and 0 <= e['time'] < e['endTime'] and
            same([t.get('time'), t.get('endTime'), t.get('eventIndex')], [e['time'], e['endTime'], i]) and
            e.get('readingOnly') is True and all(e.get(k) is False for k in
            ('performedPitchGold', 'physicalAttackGold', 'singerIdentityGold')),
            'Reading boundary is not physical singer/attack/pitch authority')
        references.append(dict(eventIndex=i, sourcePhysicalId=r['sourcePhysicalId'], sourcePart=r['sourcePart'],
            sourceQuarter=r['sourceQuarter'], sourceQuarterEnd=e['sourceQuarterEnd'], time=e['time'], endTime=e['endTime']))
        groups.setdefault(r['sourceQuarter'], []).append(e)
    require(len({e['sourcePhysicalId'] for e in events}) == len(events), 'Duplicate pitched reference')
    representatives = []
    for quarter, es in sorted(groups.items()):
        primary = [e for e in es if e.get('cursorPrimary') is True]
        require(len(primary) == 1 and all(same(e['time'], es[0]['time']) for e in es),
            'Each real source quarter needs one shared clock, without fake Lead partners')
        e = primary[0]; representatives.append(dict(sourceQuarter=quarter, sourcePhysicalId=e['sourcePhysicalId'],
            sourcePart=e['partId'], eventIndex=e['eventIndex'], time=e['time']))
    require(len(representatives) == original['physicalCounts']['primary'], 'Complete pitched-quarter denominator changed')
    rests = [t['id'] for t in tokens if rows[t['id']]['sourceKind'] == 'rest']
    for sid in rests:
        t = token_ids[sid]
        require(t.get('isRest') is True and t.get('isUnpitched') is False and
            all(t.get(k) is None for k in ('time', 'endTime', 'eventIndex', 'midi')) and
            t.get('sourceOnlyUntimed') is True and t.get('skipCursorHighlight') is True,
            'Printed rest is navigation only, never timed/seekable')
    return ids, original, representatives, references, rests


def nohint_qualification(raw, native, expected):
    require(raw.get('schema') == 'actual-independent-whole-nohint-ASR/v2' and
        raw.get('sourceAudioSha256') == expected['sourceAudioSha256'] and
        raw.get('followId') == expected['followId'] and raw.get('sourceSongId') == expected['sourceSongId'] and
        raw.get('inputKind') == 'original-mix' and
        same(raw.get('configuration'), dict(language='en', beam_size=5, word_timestamps=True,
            vad_filter=False, condition_on_previous_text=False, initial_prompt=None, hotwords=None)) and
        all(raw.get(k) is False for k in ('sourceScoreRead', 'priorLyricsRead', 'sourceForcedText',
            'conditionOnPreviousText', 'singerIsolated', 'wordOrPitchOrAttackGold', 'missingRecognitionProvesAbsence')),
        'Unforced original-mix model provenance is missing; old cache cannot be relabeled')
    require(raw.get('actualNativeRate') == native['nativeSampleRate'] and
        raw.get('actualNativeFrames') == native['nativeDecodedFrames'] and raw.get('actualModelInputRate') == 16000 and
        raw.get('actualModelInputSamples') == native['actualASRMono16000']['samples'] and
        raw.get('actualModelInputPCMFloat32Sha256') == native['actualASRMono16000']['pcmFloat32Sha256'],
        'Actual native clock and resampled model-input clock are distinct')
    segments = raw.get('segments'); require(type(segments) is list and segments, 'Actual raw segments missing')
    windows = [[s['start'], s['end']] for s in segments]
    require(all(finite(a) and finite(b) and 0 <= a < b <= native['nativeDecodedDuration'] + .01 for a, b in windows),
        'Actual raw segment estimates exceed the recording')
    gaps = []; end = 0.0
    for a, b in windows:
        if a > end: gaps.append([end, a])
        end = max(end, b)
    # Trailing accompaniment is not inferred to contain missing text.
    return dict(independentNoHintWholeInput=True, independentNoHintFullPhraseCoverage=False,
        recognizedSegmentWindows=windows, unrecognizedWindowNotAbsence=[g for g in gaps if g[0] != 0],
        historicalASRCacheAudioBindingConfirmed=False, historicalDTWRawPathAvailable=False,
        nativeHarmonicQueriesSourceKnown=True, independentBlindPitchBank=False,
        isolatedSingerIdentityConfirmed=False, wordOrPitchOrAttackOrReleaseGold=False)


@dataclass(frozen=True)
class ValidatedCompleteSATBReadingClock:
    _token: object
    _owner: object
    identity: dict
    clockDecisionSha256: str
    sourceDecisionSha256: str
    automaticEventIndices: tuple
    normalAdmissionValidated: bool = False


def _retain(result):
    ident = id(result)
    fingerprint = source.digest({k: v for k, v in vars(result).items() if k not in ('_token', '_owner')})
    _LIVE[ident] = (weakref.ref(result, lambda r: _LIVE.pop(ident, None)), fingerprint)
    return result


def live(result, expected_type, resolve):
    entry = _LIVE.get(id(result))
    require(type(result) is expected_type and result._token is _TOKEN and entry is not None and
        entry[0]() is result and entry[1] == source.digest({k: v for k, v in vars(result).items()
            if k not in ('_token', '_owner')}) and
        result._owner is getattr(resolve, '__self__', resolve) and getattr(result._owner, 'closed', False) is False,
        'Actual live authority result was invented, mutated or borrowed from another invocation')


def float_wave_data(raw, native):
    require(raw[:4] == b'RIFF' and raw[8:12] == b'WAVE', 'Actual decoded float WAV missing')
    pos = 12; fmt = None; data = None
    while pos + 8 <= len(raw):
        kind, length = raw[pos:pos+4], struct.unpack_from('<I', raw, pos+4)[0]
        chunk = raw[pos+8:pos+8+length]
        require(len(chunk) == length, 'Truncated native WAV chunk')
        if kind == b'fmt ': fmt = chunk
        if kind == b'data': require(data is None, 'Ambiguous native PCM chunk'); data = chunk
        pos += 8 + length + length % 2
    require(fmt is not None and data is not None and len(fmt) >= 16, 'Native PCM format missing')
    encoding, channels, rate, _, block, bits = struct.unpack_from('<HHIIHH', fmt)
    require(encoding in (3, 65534) and channels == native['nativeChannels'] and rate == native['nativeSampleRate']
        and bits == 32 and block == channels * 4 and len(data) == native['nativeDecodedFrames'] * block and
        sha(data) == native['pyavNativePCMFloat32Sha256'], 'Native sample bytes/rate/count differ')
    if encoding == 65534:
        require(len(fmt) >= 40 and fmt[24:40] == bytes.fromhex('0300000000001000800000aa00389b71'), 'Non-float extensible PCM')
    return data, block


def validate_clock(clock_sha, candidate, sync_raw, notation_raw, canonical, source_result, hashes, resolve):
    clock = bound(clock_sha, hashes, resolve)
    ids, original, reps, references, rests = reading_projection(candidate, sync_raw, notation_raw, canonical)
    source.check_source_result(source_result, follow_id=candidate['id'], canonical=canonical,
        audit_sha256=clock.get('sourceAuditSha256'), decision_sha256=clock.get('sourceDecisionSha256'), resolve=resolve)
    require(clock.get('schema') == CLOCK_SCHEMA and clock.get('status') == 'root-approved-qualified-satb-source-reading-clock'
        and clock.get('approved') is True and clock.get('reviewedBy') == '/root' and clock.get('scope') == CLOCK_SCOPE,
        'Actual Root common-reading clock decision is still pending')
    require(all(same(clock.get(k), v) for k, v in ids.items()) and
        same(clock.get('physicalCounts'), original['physicalCounts']) and same(clock.get('quarterRepresentatives'), reps) and
        same(clock.get('pitchedReadingReferences'), references) and same(clock.get('readonlyRestIds'), rests) and
        all(clock.get(k) is False for k in ('physicalPerformanceGold', 'fullAudioApproved', 'editionApproved',
            'normalUIApproved', 'formalAccepted')), 'Root clock scope/current musical tuple changed')
    decision = bound(clock['sourceDecisionSha256'], hashes, resolve)
    require(clock.get('actualGeometryEvidenceSha256') == decision['actualGeometryEvidenceSha256'], 'Different original ink measurement')
    geometry = bound(clock['actualGeometryEvidenceSha256'], hashes, resolve)
    ink = {r['sourcePhysicalId']: r for r in geometry['all222Heads']}
    notation = __import__('json').loads(notation_raw); sync = __import__('json').loads(sync_raw)
    token_ids = {t['id']: t for t in notation['tokens']}
    require(len(ink) == len(references), 'Full actual pitched ink denominator differs')
    for e in sync['events']:
        g = ink.get(e['sourcePhysicalId']); t = token_ids[e['sourcePhysicalId']]; v = e['visual']
        require(g is not None and same(v.get('noteheadCenter'), g['centerNormalized']) and
            same(v.get('bounds'), g['boundsNormalized']) and same(t.get('actualSourceInkCenter'), g['centerNormalized']) and
            same(t.get('sourceHeadBounds'), g['boundsNormalized']) and
            t.get('originalNativeFullHeadSHA256') == v.get('originalNativeFullHeadSHA256') == clock['actualGeometryEvidenceSha256']
            and v.get('bboxCenterUsed') is False, 'Root source ink cannot be replaced by a bbox center or stale nested alias')
    native = bound(clock.get('nativeClockEvidenceSha256'), hashes, resolve)
    require(native.get('schema') == 'actual-native-decoder-clock-review/v1' and native.get('sourceAudioSha256') == ids['sourceAudioSha256']
        and native.get('independentNativeCountEqual') is True and native.get('nativeSamplesBitExactEqual') is True and
        native.get('pyavNativePCMFloat32Sha256') == native.get('ffmpegNativePCMFloat32Sha256'), 'Actual dual native clock missing')
    for row in native['evidence']: bound(row['sha256'], hashes, resolve, binary=True)
    nohint = bound(clock.get('independentNoHintEvidenceSha256'), hashes, resolve)
    qualification = nohint_qualification(nohint, native, ids)
    require(same(clock.get('recordingEvidenceQualification'), qualification), 'Sparse recognition cannot be promoted to complete sung coverage')
    for key in ('resourcePreflight', 'rawSegmentLog'): bound(nohint[key]['sha256'], hashes, resolve, binary=True)
    samples = bound(clock.get('sampleEvidenceSha256'), hashes, resolve)
    require(samples.get('fullNativeFloat32Sha256') == native['pyavNativePCMFloat32Sha256'] and
        samples.get('sampleRate') == native['nativeSampleRate'] and samples.get('frames') == native['nativeDecodedFrames'] and
        samples.get('channels') == native['nativeChannels'], 'Source-known windows do not belong to the native recording')
    windows = {w['sourcePhysicalId']: w for w in samples['samples']}
    require(len(windows) == len(references) and set(windows) == {r['sourcePhysicalId'] for r in references}, 'All actual 222 context windows required')
    pcm, block = float_wave_data(bound(samples['decodedNativePCM']['sha256'], hashes, resolve, binary=True), native)
    for ref in references:
        w = windows[ref['sourcePhysicalId']]
        require(type(w['startFrame']) is int and type(w['endFrameExclusive']) is int and
            0 <= w['startFrame'] < w['endFrameExclusive'] <= native['nativeDecodedFrames'] and
            w.get('sourceKnownQuery') is True and all(w.get(k) is False for k in
            ('independentPitchGold', 'independentVoiceIdentityGold', 'timeGold')),
            'Actual source-known window cannot become independent singer evidence')
        require(sha(pcm[w['startFrame']*block:w['endFrameExclusive']*block]) == w['exactWindowFloat32Sha256'],
            'Actual sample window does not match the native original recording')
        require(w.get('sourceMidi') == token_ids[ref['sourcePhysicalId']]['midi'] and
            w['startFrame'] / native['nativeSampleRate'] <= ref['time'] <= w['endFrameExclusive'] / native['nativeSampleRate'],
            'Source-known window belongs to another written pitch or clock location')
    lineage = bound(clock.get('quarterClockEvidenceSha256'), hashes, resolve)
    require(lineage.get('canonicalSha256') == ids['canonicalSha256'] and lineage.get('rawDTWPathArrayAvailable') is False
        and lineage.get('rawDTWPathArrayNotInvented') is True, 'Historical DTW metadata is not a new raw model path')
    q = clock.get('clockQualification', {})
    require(finite(q.get('nativeToBrowserSeconds')) and q.get('offsetAuthority') == 'Root-reviewed-native-browser-clock-convention'
        and q.get('nativeSampleRate') == native['nativeSampleRate'] and q.get('nativeDecodedFrames') == native['nativeDecodedFrames']
        and same(q.get('nativeDecodedDuration'), native['nativeDecodedDuration']) and
        q.get('browserPCMOriginMeasured') is False and q.get('nativeToBrowserOriginMeasured') is False and
        q.get('mappingAppliedToRawSync') is False, 'Unmeasured PCM origin cannot be labeled physical Gold')
    public = bound(clock.get('actualPublicBrowserClockSha256'), hashes, resolve)
    witness = bound(clock.get('publicAudioByteProofSha256'), hashes, resolve)
    require(public.get('sourceAudioSha256') == witness.get('sourceAudioSha256') == ids['sourceAudioSha256'] and
        finite(public.get('actualBrowserDuration')) and
        abs(public['actualBrowserDuration'] - native['nativeDecodedDuration']) <= .1 and
        public.get('naturalEnded') is True and public.get('browserPCMOriginMeasured') is False and
        witness.get('purpose') == 'exact-original-source-audio-byte-equality-only' and
        type(witness.get('bytes')) is int and witness['bytes'] > 0,
        'Actual same-original public byte/EOF witness required; duration is not a physical PCM origin')
    return _retain(ValidatedCompleteSATBReadingClock(_TOKEN, getattr(resolve, '__self__', resolve), ids,
        clock_sha, clock['sourceDecisionSha256'], tuple(r['eventIndex'] for r in reps)))


def check_clock_result(result, candidate, sync_raw, notation_raw, canonical, resolve):
    ids, _, _, _, _ = reading_projection(candidate, sync_raw, notation_raw, canonical)
    live(result, ValidatedCompleteSATBReadingClock, resolve)
    require(same(result.identity, ids) and result.normalAdmissionValidated is False, 'Live actual clock type/current immutable tuple required')
    return True


@dataclass(frozen=True)
class LoopbackSATBReadingCapability:
    _token: object
    _owner: object
    identity: dict
    capabilitySha256: str
    clockDecisionSha256: str
    normalAdmissionValidated: bool = False


def validate_loopback_capability(cap_sha, candidate, sync_raw, notation_raw, canonical, clock_result, hashes, resolve):
    check_clock_result(clock_result, candidate, sync_raw, notation_raw, canonical, resolve)
    # A caller must not register a constructed dataclass using a borrowed token.
    # Reconstruct the actual authority graph from original bytes at this seam.
    actual_clock = bound(clock_result.clockDecisionSha256, hashes, resolve)
    actual_source = source.validate_source(actual_clock.get('sourceAuditSha256'), actual_clock.get('sourceDecisionSha256'),
        canonical, candidate['id'], hashes, resolve)
    validate_clock(clock_result.clockDecisionSha256, candidate, sync_raw, notation_raw, canonical,
        actual_source, hashes, resolve)
    cap = bound(cap_sha, hashes, resolve)
    _, original, reps, _, rests = reading_projection(candidate, sync_raw, notation_raw, canonical)
    clock = bound(clock_result.clockDecisionSha256, hashes, resolve)
    require(cap.get('schema') == CAP_SCHEMA and cap.get('status') == 'root-approved-loopback-satb-reading-review' and
        cap.get('scope') == CAP_SCOPE and cap.get('reviewedBy') == '/root' and cap.get('approved') is True,
        'Pending/normal capability is not a loopback-only Root review authority')
    require(all(same(cap.get(k), v) for k, v in clock_result.identity.items()) and
        cap.get('sourceDecisionSha256') == clock_result.sourceDecisionSha256 and
        cap.get('sourceAuditSha256') == clock['sourceAuditSha256'] and
        cap.get('clockDecisionSha256') == clock_result.clockDecisionSha256 and
        cap.get('actualGeometryEvidenceSha256') == clock['actualGeometryEvidenceSha256'] and
        same(cap.get('physicalCounts'), original['physicalCounts']) and same(cap.get('readonlyRestIds'), rests) and
        same(cap.get('automaticEventIndices'), [r['eventIndex'] for r in reps]) and
        same(cap.get('frontend'), candidate.get('frontend')) and
        same(cap.get('coreRendererSha256'), candidate['frontend'].get('coreSha256')) and
        all(cap.get(k) is False for k in ('normalV6Approved', 'normalUIApproved', 'publicAdmissionAllowed',
            'formalAccepted', 'physicalPerformanceGold')), 'Loopback authority cannot alter graph or grant admission')
    frontend = candidate['frontend']
    require(frontend.get('version') == 'source-tempo-beats-v1' and
        set(frontend.get('assets', {})) == {'frame.html', 'source-tempo-beats-v1.js', 'source-tempo-beats-v1.css'} and
        set(frontend.get('coreSha256', {})) == {'follow/app.js', 'follow/notation.js', 'follow/policy.js', 'lyrics.js', 'player.js'},
        'Actual normal three assets and five unchanged core resources required')
    for digest in [*frontend['assets'].values(), *frontend['coreSha256'].values()]:
        bound(digest, hashes, resolve, binary=True)
    return _retain(LoopbackSATBReadingCapability(_TOKEN, getattr(resolve, '__self__', resolve), clock_result.identity,
        cap_sha, clock_result.clockDecisionSha256))


def loopback_response(result, candidate, sync_raw, notation_raw, canonical, report, analysis, hashes, resolve,
                      *, hostname, view=None):
    """Ordinary endpoint payload for an explicitly isolated Root review server.

    The production server does not call this function. It never grants accepted
    lifecycle state and never installs a client-side fetch or audio override.
    """
    live(result, LoopbackSATBReadingCapability, resolve)
    ids, _, _, _, _ = reading_projection(candidate, sync_raw, notation_raw, canonical)
    require(same(result.identity, ids) and hostname in ('127.0.0.1', 'localhost', '::1') and
        view in (None, candidate['frontend']['version']), 'Review-only authority cannot serve public or another view')
    cap = bound(result.capabilitySha256, hashes, resolve)
    require(cap.get('clockDecisionSha256') == result.clockDecisionSha256,
        'Response clock locator differs from the actual capability graph')
    actual_clock = bound(cap.get('clockDecisionSha256'), hashes, resolve)
    actual_source = source.validate_source(cap.get('sourceAuditSha256'), cap.get('sourceDecisionSha256'), canonical,
        candidate['id'], hashes, resolve)
    actual_clock_result = validate_clock(cap.get('clockDecisionSha256'), candidate, sync_raw, notation_raw, canonical,
        actual_source, hashes, resolve)
    validate_loopback_capability(result.capabilitySha256, candidate, sync_raw, notation_raw, canonical,
        actual_clock_result, hashes, resolve)
    require(same(cap['frontend'], candidate['frontend']) and candidate.get('quality', {}).get('accepted') is False,
        'Review response cannot borrow a different frontend or claim public admission')
    clock = bound(result.clockDecisionSha256, hashes, resolve)
    def authority(sha256):
        raw = bound(sha256, hashes, resolve, binary=True)
        return dict(sha256=sha256, rawUtf8=raw.decode('utf8'))
    sync = __import__('json').loads(sync_raw); sync['accepted'] = False
    meta = copy.deepcopy(candidate)
    require(meta.get('generated') == '/generated/' + candidate['id'] and
        all(type(p) is str and p.startswith('/source/charts/') for p in meta.get('charts', [])),
        'Actual normal resource aliases required')
    meta['generated'] = '/follow-media' + meta['generated']
    meta['charts'] = ['/follow-media' + p for p in meta.get('charts', [])]
    return dict(song=meta, songs=[], sync=sync, jianpu=__import__('json').loads(notation_raw),
        analysis=copy.deepcopy(analysis), report=dict(counts=report.get('counts'), alignment=report.get('alignment'), musicxml=''),
        sourceReadingAuthority=dict(mode='loopback-review', profile=PROFILE,
            sourceDecision=authority(clock['sourceDecisionSha256']), clockDecision=authority(result.clockDecisionSha256),
            capability=authority(result.capabilitySha256)))
