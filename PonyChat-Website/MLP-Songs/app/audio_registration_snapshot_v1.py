"""Invocation-local original registration bytes; never caches gate results.

Unchanged registries are parsed once per parser within a validation invocation.
Every registration predicate still runs for every observation. Fresh streamed
SHA and file identity checks run at exit, including failure exits. No state is
retained across invocations; direct calls keep their existing fresh-read path.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import hashlib
from pathlib import Path
from validation_heap import trim_validation_heap

_CURRENT = ContextVar('actual_audio_registration_validation_scope', default=None)


def _dependency(path):
    resolved = path.resolve(strict=True)
    link, target = path.lstat(), path.stat()
    return (str(resolved), link.st_dev, link.st_ino, link.st_mtime_ns,
            link.st_size, target.st_dev, target.st_ino, target.st_mtime_ns,
            target.st_size)


def _fresh_sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


class _Snapshot:
    def __init__(self):
        self.rows = {}
        self.closed = False

    def catalog(self, path, strict_json):
        if self.closed:
            raise ValueError('Audio registration validation scope is closed')
        path = Path(path).absolute()
        key = (path, strict_json)
        if key not in self.rows:
            before = _dependency(path)
            raw = path.read_bytes()
            if _dependency(path) != before:
                raise ValueError('Audio registration dependency changed during snapshot read')
            row = self.rows[key] = [before, hashlib.sha256(raw).hexdigest(), None, None]
            try:
                row[2] = strict_json(raw)
            except Exception as error:
                row[3] = error
                raise
        row = self.rows[key]
        if row[3] is not None:
            raise row[3]
        return row[2]

    def close(self):
        try:
            for (path, _), (dependency, digest, _, _) in self.rows.items():
                if (_dependency(path) != dependency or _fresh_sha(path) != digest
                        or _dependency(path) != dependency):
                    raise ValueError('Audio registration original changed during validation')
        finally:
            self.closed = True
            self.rows.clear()


@contextmanager
def registration_scope():
    existing = _CURRENT.get()
    if existing is not None:
        if existing.closed:
            raise ValueError('Audio registration validation scope is closed')
        yield existing
        return
    snapshot = _Snapshot()
    token = _CURRENT.set(snapshot)
    try:
        yield snapshot
    finally:
        try:
            snapshot.close()
        finally:
            _CURRENT.reset(token)
            # This outermost scope exits after the original graph returns and
            # closes, while its existing serialization lock is still held.
            trim_validation_heap()


def snapshot_validation(function):
    @wraps(function)
    def checked(*args, **kwargs):
        with registration_scope():
            return function(*args, **kwargs)
    return checked


def registration_catalog(path, strict_json):
    from runtime_paths import registration_path
    path = registration_path(path)
    snapshot = _CURRENT.get()
    if snapshot is None:
        return strict_json(Path(path).read_bytes())
    return snapshot.catalog(path, strict_json)
