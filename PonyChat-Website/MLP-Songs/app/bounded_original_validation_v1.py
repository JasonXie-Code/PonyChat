"""Memory budgets only: never caches a validation result or weakens authority."""
from collections import OrderedDict
from functools import wraps
import hashlib
import threading

RAW_CACHE_LIMIT = 32 * 1024 * 1024
_GRAPH_LOCK = threading.RLock()


def serialized_original_validation(function):
    """One original graph at a time across both deployed source profiles."""
    @wraps(function)
    def checked(*args, **kwargs):
        try:
            from .audio_registration_snapshot_v1 import registration_scope
        except ImportError:
            from audio_registration_snapshot_v1 import registration_scope
        with _GRAPH_LOCK, registration_scope():
            return function(*args, **kwargs)
    return checked


def initialize_raw_budget(owner):
    owner.cache = OrderedDict()
    owner.cache_bytes = 0
    owner.accessed_digests = set()


def budgeted_original_bytes(owner, digest, source):
    """Retain bounded immutable bytes; misses always read and strongly hash."""
    if digest in owner.cache:
        raw = owner.cache.pop(digest)
        owner.cache[digest] = raw
    else:
        raw = owner.paths[digest].read_bytes()
        source.require(source.sha(raw) == digest,
                       'Normal ensemble original bytes changed after validation')
        if len(raw) <= RAW_CACHE_LIMIT:
            while owner.cache and owner.cache_bytes + len(raw) > RAW_CACHE_LIMIT:
                _, evicted = owner.cache.popitem(last=False)
                owner.cache_bytes -= len(evicted)
            owner.cache[digest] = raw
            owner.cache_bytes += len(raw)
    owner.accessed_digests.add(digest)
    return raw


def same_original_bytes(first, second):
    """Preserve exact duplicate-body comparison without two whole-file copies."""
    with first.open('rb') as a, second.open('rb') as b:
        while True:
            left, right = a.read(1024 * 1024), b.read(1024 * 1024)
            if left != right:
                return False
            if not left:
                return True


def streamed_original_sha(path):
    """Uncached post-validation hash without a second whole-file allocation."""
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def close_raw_budget(owner, source):
    try:
        for digest, raw in owner.cache.items():
            source.require(source.sha(raw) == digest,
                           'Normal ensemble cached original changed during validation')
        # Eviction must not remove an original from the final TOCTOU audit.
        for digest in owner.accessed_digests:
            source.require(streamed_original_sha(owner.paths[digest]) == digest,
                           'Normal ensemble original changed during validation')
    finally:
        owner.closed = True
        owner.cache.clear()
        owner.cache_bytes = 0


def bounded_capture_reader(hashes, resolve, source):
    """One decoded original at a time; actual rows still resolve/hash each time."""
    cached_digest = None
    cached_raw = None
    cached_body = None

    def read(row):
        nonlocal cached_digest, cached_raw, cached_body
        digest = row['rawEvidenceSha256']
        source.require(type(digest) is str and digest in hashes,
                       'Original ensemble evidence is not bound')
        if digest != cached_digest:
            raw = source.bound(digest, hashes, resolve, True)
            # Drop the previous potentially large graph BEFORE the next decode.
            cached_digest = cached_raw = cached_body = None
            body = source.strict_json(raw)
            cached_digest, cached_raw, cached_body = digest, raw, body
        else:
            # Exact prior behavior: still resolve and compare immutable raw bytes;
            # a resolver miss rehashes, and exit rehashes every touched file.
            raw = resolve(digest, raw_bytes=True)
            source.require(type(raw) is bytes and raw == cached_raw, 'Original ensemble evidence bytes changed')
        body = cached_body
        for key in row.get('capturePath', []):
            source.require(type(key) in (str, int) and type(key) is not bool,
                           'Invalid actual original capture pointer')
            body = body[key]
        source.require(type(body) is dict and
                       ('captured' not in row or source.same(body, row['captured'])),
                       'Browser wrapper changed the actual original capture')
        return body
    return read
