"""Invalidate recording admission per song, while retaining every original gate.

Registry contents select a song's dependencies; unrelated registry rows and
recordings cannot invalidate its result. Only the original builder can admit
an entry. No raw evidence or decoded proof graph survives a builder call.
"""
from contextvars import ContextVar
import copy
import hashlib
import json
from pathlib import Path
import re

import follow_catalog_cache as dependencies
from follow_dependency_plan import DependencyPlan, DependencyScan

_SELECTED = ContextVar('follow_catalog_selected_ids', default=None)
_FRAMES = ContextVar('follow_catalog_validated_frames', default=None)
_STATE = None


class AcceptedEntries(dict):
    """Metadata and frame URLs established by the original admission builder."""
    frontend_paths = None


def record_frontend(follow_id, path):
    frames = _FRAMES.get()
    if frames is not None:
        frames[follow_id] = path


def _result(value, frames):
    result = AcceptedEntries(copy.deepcopy(value))
    result.frontend_paths = {sid: frames[meta['id']] for sid, meta in value.items()
                             if meta.get('id') in frames}
    return result


def selected_follow_ids():
    return _SELECTED.get()


def clear_cache():
    global _STATE
    with dependencies._LOCK:
        _STATE = None


def _registry(data, follow):
    paths = (Path(data) / 'follow-catalog.json', Path(follow) / 'generated/songs.json',
             Path(data) / 'index.json')
    before = tuple(dependencies._record(path) for path in paths)
    bodies = [json.loads(path.read_bytes()) if path.is_file() else default
              for path, default in zip(paths, ({}, [], {}))]
    dependencies._require(before == tuple(dependencies._record(path) for path in paths),
                          'Registry changed during read')
    catalog, metas, index = bodies
    dependencies._require(isinstance(catalog, dict) and isinstance(catalog.get('songs', []), list)
                          and isinstance(metas, list), 'Malformed follow registries')
    dependencies._require(all(isinstance(row, dict) for row in catalog.get('songs', [])),
                          'Malformed recording registration')
    dependencies._require(isinstance(index, dict) and isinstance(index.get('songs', []), list)
                          and all(isinstance(row, dict) for row in index.get('songs', [])),
                          'Malformed recording index')
    return catalog, metas, index


def _snapshots(data, follow, plans=None, selected_ids=None):
    registry = _registry(data, follow)
    context = tuple(map(str, dependencies._roots(data, follow)))
    rows, metas = registry[0].get('songs', []), registry[1]
    ids = dict.fromkeys(meta['id'] for meta in metas if isinstance(meta, dict)
                        and isinstance(meta.get('id'), str) and re.fullmatch('[a-z0-9-]+', meta['id']))
    snapshots = {}
    # Request-local only. The caller's before/after invocations each create an
    # independent sweep; a shared file changed between them cannot stay warm.
    scan = DependencyScan(dependencies._record)
    for fid in ids:
        if selected_ids is not None and fid not in selected_ids:
            continue
        selected_rows = [row for row in rows if row.get('followId') == fid]
        selected_metas = [meta for meta in metas if isinstance(meta, dict) and meta.get('id') == fid]
        song_ids = {row.get('songId') for row in selected_rows}
        song_ids.update(meta.get('sourceSongId') for meta in selected_metas)
        content = json.dumps([selected_rows, selected_metas,
                              [row for row in registry[2].get('songs', []) if row.get('id') in song_ids]],
                             sort_keys=True, ensure_ascii=False, separators=(',', ':'))
        content = hashlib.sha256(content.encode('utf-8')).hexdigest()
        try:
            previous = plans.get(fid) if plans is not None else None
            if previous is not None and previous[0] == content and previous[1].matches(context, dependencies._record, scan):
                key = previous[1].fingerprint
            else:
                snapshot = dependencies.dependencies(data, follow, registry=registry, selected_ids={fid})
                key = _fingerprint(snapshot)
                if plans is not None:
                    plans[fid] = (content, DependencyPlan(context, snapshot, key))
        except (OSError, dependencies.DependencyError):
            key = None
        snapshots[fid] = (content, key)
    # Do not combine keys discovered across two registry generations.
    dependencies._require(registry == _registry(data, follow), 'Registry changed during discovery')
    return snapshots


def _fingerprint(snapshot):
    """Retain every dependency clock without keeping three full path vectors.

    Discovery still reads/stat-checks every original dependency on each scan.
    Only its comparison key is compressed; this never establishes admission.
    Per-record encoding keeps temporary allocations bounded by one record.
    """
    digest = hashlib.sha256()
    for section in snapshot[:-1]:
        digest.update(b'section\0')
        for record in section:
            digest.update(json.dumps(record, ensure_ascii=True,
                                     separators=(',', ':')).encode('ascii'))
            digest.update(b'\0')
    return digest.hexdigest(), snapshot[-1]


def _cacheable(snapshot):
    return snapshot is not None and snapshot[1] is not None and snapshot[1][-1]


def response_snapshot(data, follow, follow_id):
    """Fresh complete per-recording dependency key, never an admission token."""
    with dependencies._LOCK:
        owner = (str(Path(data).absolute()), str(Path(follow).absolute()))
        plans = (_STATE['plans'] if _STATE is not None and _STATE['owner'][:2] == owner else {})
        value = _snapshots(data, follow, plans, {follow_id}).get(follow_id)
        if not _cacheable(value):
            return None
        # Ensemble responses may also expose the separately mounted reviewed
        # main caption body. It must revoke a response independently of its
        # certificate-bound original copy.
        metas = _registry(data, follow)[1]
        captions = tuple(dependencies._record(Path(data) / 'lyrics' /
            (hashlib.sha256(meta['sourceSongId'].encode()).hexdigest()[:24] + '.json'))
            for meta in metas if isinstance(meta, dict) and meta.get('id') == follow_id
            and isinstance(meta.get('sourceSongId'), str))
        return value, captions


def accepted_song(data, follow, builder, follow_id):
    """Use the same admission generation while checking only the requested song."""
    global _STATE
    with dependencies._LOCK:
        owner = (str(Path(data).absolute()), str(Path(follow).absolute()), builder)
        if _STATE is not None and _STATE['owner'] == owner:
            try:
                before = _snapshots(data, follow, _STATE['plans'], {follow_id})
                key = before.get(follow_id)
                if _cacheable(key) and _STATE['keys'].get(follow_id) == key:
                    after = _snapshots(data, follow, _STATE['plans'], {follow_id})
                    if before == after:
                        return _result(_STATE['values'].get(follow_id, {}),
                            {follow_id: _STATE['frames'][follow_id]} if follow_id in _STATE['frames'] else {})
            except (OSError, ValueError):
                pass
        all_entries = accepted_songs(data, follow, builder)
        selected = AcceptedEntries({sid: meta for sid, meta in all_entries.items() if meta.get('id') == follow_id})
        selected.frontend_paths = {sid: path for sid, path in all_entries.frontend_paths.items() if sid in selected}
        return selected


def accepted_songs(data, follow, builder):
    global _STATE
    with dependencies._LOCK:
        owner = (str(Path(data).absolute()), str(Path(follow).absolute()), builder)
        if _STATE is None or _STATE['owner'] != owner:
            _STATE = dict(owner=owner, keys={}, values={}, plans={}, frames={})
        plans = _STATE['plans']
        result = {}
        result_frames = {}
        for _ in range(2):
            result = {}
            try:
                before = _snapshots(data, follow, plans)
            except (OSError, ValueError):
                # A transient write to one registry must not discard every
                # unrelated song. Retained keys are always freshly checked
                # before any later result can be returned.
                continue
            changed = {fid for fid, key in before.items()
                       if not _cacheable(key) or _STATE['keys'].get(fid) != key}
            value = {}
            validated_frames = {}
            if changed:
                token = _SELECTED.set(frozenset(changed))
                frame_token = _FRAMES.set(validated_frames)
                try:
                    value = builder(data, follow)
                    dependencies._require(isinstance(value, dict), 'Original builder must return metadata')
                finally:
                    _FRAMES.reset(frame_token)
                    _SELECTED.reset(token)
            try:
                after = _snapshots(data, follow, plans)
            except (OSError, ValueError):
                continue
            stable = [fid for fid in before if before[fid] == after.get(fid)]
            keys, values, frames = {}, {}, {}
            result = {}
            result_frames = {}
            for fid in stable:
                accepted = ({sid: meta for sid, meta in value.items() if meta.get('id') == fid}
                            if fid in changed else _STATE['values'].get(fid, {}))
                if before[fid][1] is None:
                    accepted = {}  # An unavailable dependency clock cannot establish a positive.
                result.update(accepted)
                path = (validated_frames.get(fid) if fid in changed else _STATE['frames'].get(fid))
                if accepted and path is not None:
                    result_frames[fid] = path
                if _cacheable(before[fid]):
                    keys[fid], values[fid] = before[fid], copy.deepcopy(accepted)
                    if accepted and path is not None:
                        frames[fid] = path
            plans = {fid: plans[fid] for fid in after if fid in plans}
            _STATE = dict(owner=owner, keys=keys, values=values, plans=plans, frames=frames)
            if before == after:
                return _result(result, result_frames)
        # Stable unrelated songs remain usable; a changing song never gets an
        # old positive result. Every retained entry passed both current scans.
        return _result(result, result_frames)
