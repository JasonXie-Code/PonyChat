"""Bounded public JSON copies after the original lifecycle has succeeded.

Only serialized responses survive. Every hit rechecks the full recording
dependency graph before and after decoding; no sealed tokens or parsed proof
graphs are retained. Misses still execute every original public lifecycle gate.
"""
from collections import OrderedDict
import json
import logging
import os
import threading
import zlib

from fastapi import HTTPException
import follow_catalog_cache as dependencies
from follow_catalog_song_cache import response_snapshot
from validation_heap import trim_validation_heap

MAX_BYTES = min(256 * 1024 * 1024, max(1024 * 1024,
    int(os.environ.get('MLP_FOLLOW_RESPONSE_CACHE_BYTES', str(16 * 1024 * 1024)))))
MAX_ENTRIES = 128
_LOCK = threading.RLock()
_CACHE = OrderedDict()
_BYTES = 0
_REFERENCES = {}


def clear_cache():
    global _BYTES
    with _LOCK:
        _CACHE.clear()
        _REFERENCES.clear()
        _BYTES = 0


def _snapshot(data, follow, follow_id):
    try:
        return response_snapshot(data, follow, follow_id)
    except (OSError, ValueError, TypeError, KeyError):
        return None


def _discard(key):
    global _BYTES
    encoded = _CACHE.pop(key, None)
    if encoded is not None:
        identity = id(encoded)
        _REFERENCES[identity] -= 1
        if not _REFERENCES[identity]:
            del _REFERENCES[identity]
            _BYTES -= len(encoded)


def _retain(key, encoded):
    global _BYTES
    identity = id(encoded)
    if identity not in _REFERENCES:
        _REFERENCES[identity] = 0
        _BYTES += len(encoded)
    _REFERENCES[identity] += 1
    _CACHE[key] = encoded


def follow_response(data, follow, follow_id, view, builder, response_views=None, context=()):
    """Single-flight expensive proofs and return an independent public copy."""
    global _BYTES
    owner = (tuple(map(str, dependencies._roots(data, follow))), builder,
             response_views, context, follow_id, view)
    with _LOCK:
        try:
            for _ in range(2):
                before = _snapshot(data, follow, follow_id)
                cached = _CACHE.get(owner)
                if before is not None and cached is not None:
                    # The dependency key travels inside the compressed envelope.
                    saved = json.loads(zlib.decompress(cached))
                    if saved['key'] == json.loads(json.dumps(before)):
                        after = _snapshot(data, follow, follow_id)
                        if before == after:
                            _CACHE.move_to_end(owner)
                            return saved['payload']
                        continue
                _discard(owner)
                # Prior proof/JSON allocations must not force the next graph
                # into cgroup memory.high reclamation while still executing.
                trim_validation_heap()
                result = builder(follow_id, view=view)
                after = _snapshot(data, follow, follow_id)
                if before is None:
                    return result  # No trustworthy dependency clock: never cache.
                if before != after:
                    continue
                encoded = zlib.compress(json.dumps(dict(key=before, payload=result),
                    ensure_ascii=False, separators=(',', ':')).encode('utf-8'), 1)
                if len(encoded) <= MAX_BYTES:
                    views = response_views(result, view) if response_views else (view,)
                    for allowed_view in views:
                        alias = owner[:-1] + (allowed_view,)
                        _discard(alias)
                        while _CACHE and (_BYTES + (0 if id(encoded) in _REFERENCES else len(encoded)) > MAX_BYTES or len(_CACHE) >= MAX_ENTRIES):
                            _discard(next(iter(_CACHE)))
                        _retain(alias, encoded)
                return result
            raise HTTPException(409, 'Score changed while loading; reopen the score')
        finally:
            trim_validation_heap()


def warm_follow_responses(catalog, data, follow):
    """Pay cold validation once before the first visitor requests a score."""
    from music_data import follow_for
    logger = logging.getLogger('uvicorn.error')
    metas = json.loads((follow / 'generated/songs.json').read_bytes())
    by_id = {meta['id']: meta for meta in metas if isinstance(meta, dict) and 'id' in meta}
    total = 0
    logger.info('Warming validated score responses: %s recordings', sum(bool(song.get('followId')) for song in catalog.get('songs', [])))
    for song in catalog.get('songs', []):
        fid = song.get('followId')
        if not fid:
            continue
        view = by_id.get(fid, {}).get('frontend', {}).get('version')
        try:
            follow_for(fid, view=view)
            total += 1
            if total % 10 == 0:
                logger.info('Validated score response warmup progress: %s recordings', total)
        except HTTPException:
            logger.exception('Score response warmup rejected: %s', fid)
    retained = {key[-2] for key in _CACHE}
    logger.info('Validated score responses warmed: %s; retained=%s; entries=%s; compressed_bytes=%s; byte_limit=%s',
                                    total, len(retained), len(_CACHE), _BYTES, MAX_BYTES)
    if len(retained) < total:
        logger.warning('Score response byte budget retained only %s/%s warmed recordings', len(retained), total)
