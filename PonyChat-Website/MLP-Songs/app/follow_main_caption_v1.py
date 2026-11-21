"""Expose an unchanged, Root-reviewed main caption body to its sealed score frame."""
import hashlib
import json
from pathlib import Path

DECISION = 'root-exact-main-caption-resegmentation-decision/v1'


def exact_reviewed_main(meta, authority, data, follow):
    """Consume the already verified lifecycle; never approve or rewrite captions."""
    if authority.get('mode') != 'normal-sealed':
        return None
    certificate_ref = authority.get('certificate', {})
    certificate_raw = certificate_ref.get('rawUtf8', '').encode('utf-8')
    if hashlib.sha256(certificate_raw).hexdigest() != certificate_ref.get('sha256'):
        return None
    certificate = json.loads(certificate_raw)
    if (certificate.get('status') != 'approved' or certificate.get('reviewedBy') != '/root'
            or certificate.get('followId') != meta.get('id')
            or certificate.get('sourceSongId') != meta.get('sourceSongId')):
        return None
    sid = meta['sourceSongId']
    key = hashlib.sha256(sid.encode('utf-8')).hexdigest()[:24]
    target = Path(data) / 'lyrics' / (key + '.json')
    if not target.is_file():
        return None
    raw = target.read_bytes()
    # The published main-data mount can use CRLF while the signed original is
    # LF. Permit only that lossless line-ending representation; the resulting
    # entire byte body must still match a genuine signed after-body hash.
    caption_hashes = {hashlib.sha256(raw).hexdigest(),
                      hashlib.sha256(raw.replace(b'\r\n', b'\n')).hexdigest()}
    body = json.loads(raw)
    if (body.get('songId') != sid or body.get('audioSha256') != meta.get('sourceAudioSha256')
            or body.get('reviewed') is not True or body.get('status') != 'available'
            or body.get('timingPolicy') != {'mode': 'strict-explicit-end', 'verified': True}):
        return None
    rows = certificate.get('bindings', [])
    if not any(row.get('kind') == 'follow' and row.get('sha256') in caption_hashes for row in rows):
        return None
    prefix = 'generated/' + meta['id'] + '/acceptance-evidence/'
    approved = set()
    base = Path(follow).resolve()
    for row in rows:
        relative = row.get('path', '')
        if row.get('kind') != 'follow' or not relative.startswith(prefix) or not relative.endswith('.json'):
            continue
        path = (base / relative).resolve()
        if not path.is_relative_to(base) or not path.is_file():
            continue
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != row.get('sha256'):
            continue
        value = json.loads(content)
        if not isinstance(value, dict) or value.get('schema') != DECISION:
            continue
        if (value.get('approved') is True and value.get('reviewedBy') == '/root'
                and value.get('status') == 'root-approved-exact-main-caption-edit'
                and value.get('songId') == sid and value.get('afterSha256') in caption_hashes
                and value.get('sourceAudioSha256') == meta['sourceAudioSha256']
                and value.get('commonClockDecisionSha256') == authority.get('clockDecision', {}).get('sha256')):
            approved.add(row['sha256'])
    return body if len(approved) == 1 else None
