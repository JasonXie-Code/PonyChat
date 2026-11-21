"""Single-flight accepted catalog, invalidated by every admission dependency.

Only the original builder may establish acceptance. No raw proof bodies or
typed projections are retained; a cache hit rechecks the entire file/directory
signature vector and returns an independent copy of the accepted metadata.
"""
from __future__ import annotations

import copy
import json
import os
import re
import stat as stat_types
import sys
import threading
from pathlib import Path

from file_signature import signature as current_signature

_LOCK = threading.RLock()
_STATE = None


class DependencyError(ValueError):
    pass


def _require(condition, message):
    if not condition:
        raise DependencyError(message)


def _record(path, resolved=None):
    from normalized_audio import deployed_recording_binding, deployed_source_url
    if deployed_source_url(path) is not None:
        locator = str(Path(path).absolute())
        binding = deployed_recording_binding(locator)
        if binding is None:
            return locator, locator, None
        source_hash, output_hash, clock = binding
        return locator, locator, ('deployed-opus', source_hash, output_hash, *clock[0], *clock[1:])
    # Plans supply absolute native strings and an independently refreshed
    # resolved locator. Avoid rebuilding pathlib objects for every warm stat.
    if isinstance(path, str) and isinstance(resolved, str) and os.path.isabs(path):
        locator = path
        from windows_file_metadata import file_record
        fresh = file_record(locator)
        if fresh is not None:
            return locator, resolved, fresh
    else:
        path = Path(path).absolute()
        resolved = path.resolve() if resolved is None else resolved
        locator = str(path)
    try:
        stat = os.stat(locator)
        if stat_types.S_ISDIR(stat.st_mode):
            # Unrelated journals/temp files change a root directory's clocks.
            # Admission depends on its locator/identity/mode, the actual files,
            # and the separately sampled complete OMR glob member lists.
            signature = ('directory', stat.st_dev, stat.st_ino, stat.st_mode)
        else:
            signature = current_signature(locator, stat) + (stat.st_dev, stat.st_ino, stat.st_mode)
    except FileNotFoundError:
        signature = None
    # Include both the locator and its current resolved target. A redirected
    # symlink is not equivalent merely because it points at equal-size bytes.
    return locator, str(resolved), signature


def _roots(data, follow):
    data, follow = Path(data).absolute(), Path(follow).absolute()
    media = Path(os.environ.get('MLP_MEDIA_ROOT', str(data.parent.parent / 'media-export'))).absolute()
    web = Path(os.environ.get('MLP_WEB_ROOT', str(data.parent.parent / 'web'))).absolute()
    return data, follow, media, web


def dependencies(data, follow, *, registry=None, selected_ids=None):
    """Sample current dependencies; missing files are part of the key too."""
    data, follow, media, web = _roots(data, follow)
    paths = {}
    directories = []
    resolved_roots = {}
    resolved_parents = {}
    cacheable = True

    def add(path, resolved=None):
        key = str(Path(path).absolute())
        if key not in paths:
            paths[key] = _record(path, resolved)
        return Path(path)

    def read(path, default):
        nonlocal cacheable
        before = _record(path); add(path)
        if before[2] is None:
            return default
        try:
            body = json.loads(Path(path).read_bytes())
        except ValueError:
            # The original builder handles invalid JSON per song. Keep the
            # bad body's strong signature, but never cache this generation.
            cacheable = False
            body = default
        _require(_record(path) == before, 'Metadata changed during dependency discovery')
        return body

    def relative(root, locator):
        _require(isinstance(locator, str) and locator and not locator.startswith(('\\', '/')),
                 'Malformed relative dependency')
        relative_path = Path(locator)
        _require(not relative_path.drive and '..' not in relative_path.parts, 'Unsafe dependency traversal')
        # All roots originate in _roots(), including the source subdirectory.
        key = str(root)
        if key not in resolved_roots:
            add(root); resolved_roots[key] = Path(paths[key][1])
        target = root / relative_path
        # Certificates often bind thousands of sibling evidence files. Resolve
        # their shared parent once per scan instead of walking the same long
        # prefix for every file. File symlinks still resolve their full chain;
        # the independent after-scan refreshes every parent before a cache hit.
        parent_key = (key, str(target.parent))
        if parent_key not in resolved_parents:
            parent = target.parent.resolve()
            resolved_parents[parent_key] = (parent, parent.is_relative_to(resolved_roots[key]))
        parent, contained = resolved_parents[parent_key]
        if target.is_symlink():
            resolved = target.resolve()
            contained = resolved.is_relative_to(resolved_roots[key])
        else:
            resolved = parent / target.name
        _require(contained, 'Dependency escaped root')
        return add(target, resolved)

    def url(root, locator):
        _require(isinstance(locator, str) and locator.startswith('/'), 'Malformed asset dependency')
        return relative(root, locator.lstrip('/'))

    for root in (data, follow, media, web): add(root)
    from follow_acceptance import OFFLINE_EVIDENCE_FILENAME, deployed_offline_evidence_pin
    if deployed_offline_evidence_pin():
        add(follow.parent / OFFLINE_EVIDENCE_FILENAME)
    catalog = read(data / 'follow-catalog.json', {}) if registry is None else registry[0]
    _require(isinstance(catalog, dict) and isinstance(catalog.get('songs', []), list), 'Malformed follow registry')
    # The registry itself determines recording/score matching. Track all of its
    # current locators, including absent files which may later be installed.
    for row in catalog.get('songs', []):
        _require(isinstance(row, dict), 'Malformed registry row')
        if selected_ids is not None and row.get('followId') not in selected_ids:
            continue
        if row.get('sourceAudio') is not None: url(media, row['sourceAudio'])
        _require(isinstance(row.get('scoreCandidates', []), list), 'Malformed score candidates')
        for score in row.get('scoreCandidates', []):
            _require(isinstance(score, dict), 'Malformed score candidate')
            if score.get('src') is not None: url(media, score['src'])
    metas = read(follow / 'generated/songs.json', []) if registry is None else registry[1]
    _require(isinstance(metas, list), 'Malformed generated song registry')
    for meta in metas:
        if selected_ids is not None and (not isinstance(meta, dict) or meta.get('id') not in selected_ids):
            continue
        try:
            collect_meta(meta, follow, media, web, add, read, relative, url, directories)
        except DependencyError:
            cacheable = False
    return (tuple(_record(root) for root in (data, follow, media, web)),
            tuple(sorted(paths.values())), tuple(sorted(directories)), cacheable)


def collect_meta(meta, follow, media, web, add, read, relative, url, directories):
    """An invalid individual candidate must not hide healthy validated songs."""
    # The registry signature already covers a malformed row. Capture every
    # safe locator before delegating rejection to the original full builder.
    _require(isinstance(meta, dict) and isinstance(meta.get('id'), str)
             and re.fullmatch('[a-z0-9-]+', meta['id']), 'Malformed generated song ID')
    folder = follow / 'generated' / meta['id']
    for name in ('report.json', 'notation.json', 'jianpu.json', 'sync.json', 'candidate.json',
                 'source-provenance.json', 'analysis.json'):
        add(folder / name)
    omr = folder / 'omr'; add(omr)
    members = []
    if omr.is_dir():
        # Use exactly the builder's two globs, including case sensitivity
        # of the current filesystem. Sorting cannot hide additions/removals.
        for member in sorted({*omr.glob('*.musicxml'), *omr.glob('*.mxl')}, key=str):
            members.append(str(member.absolute())); add(member)
    directories.append((str(omr.absolute()), tuple(members)))
    for key in ('audio', 'scorePdf'):
        if meta.get(key) is not None: url(media, meta[key])
    if meta.get('canonicalMusicxml') is not None: url(follow, meta['canonicalMusicxml'])
    charts = meta.get('charts', [])
    _require(isinstance(charts, list), 'Malformed source charts')
    for chart in charts:
        # Preserve both locator conventions used by the original builder.
        url(follow, chart); url(follow / 'source', chart)
    certificate_paths = {folder / 'acceptance.json'}
    approval = meta.get('acceptance', {})
    _require(isinstance(approval, dict), 'Malformed certificate pointer')
    if approval.get('certificate') is not None:
        certificate_paths.add(url(follow, approval['certificate']))
    for path in sorted(certificate_paths, key=str):
        cert = read(path, {})
        _require(isinstance(cert, dict) and isinstance(cert.get('bindings', []), list), 'Malformed certificate bindings')
        if cert.get('canonicalMusicxml') is not None:
            relative(follow, cert['canonicalMusicxml'])
        for binding in cert.get('bindings', []):
            _require(isinstance(binding, dict), 'Malformed binding row')
            root = follow if binding.get('kind') == 'follow' else media if binding.get('kind') == 'media' else None
            _require(root is not None, 'Malformed certificate dependency kind')
            # Same containment contract as binding_path, with each current
            # root resolved once per sample and each file sampled once.
            relative(root, binding.get('path'))
    frontend = meta.get('frontend')
    if frontend is not None:
        _require(isinstance(frontend, dict) and isinstance(frontend.get('assets'), dict)
                 and isinstance(frontend.get('coreSha256'), dict), 'Malformed frontend manifest')
        prefix = 'generated/' + meta['id'] + '/accepted-frontend/'
        if frontend.get('frame') is not None: relative(follow, frontend['frame'])
        for name in frontend['assets']: relative(follow, prefix + name)
        for name in frontend['coreSha256']: relative(web, name)


def clear_cache():
    """Test/process lifecycle only; callers cannot inject an approved result."""
    global _STATE
    with _LOCK:
        _STATE = None
        scoped = sys.modules.get('follow_catalog_song_cache')
        if scoped is not None:
            scoped.clear_cache()


def accepted_catalog(data, follow, builder):
    global _STATE
    with _LOCK:
        # Discovery and the expensive full builder are in the same lock. All
        # concurrent requests share one validation flight, not one per thread.
        for attempt in range(2):
            try:
                before = dependencies(data, follow)
            except (OSError, DependencyError):
                _STATE = None
                # No coherent complete dependency set exists. Do not return
                # either an old positive or an unverifiable partial snapshot.
                return {}
            if before[-1] and _STATE is not None and _STATE['builder'] is builder and _STATE['key'] == before:
                try:
                    after = dependencies(data, follow)
                except (OSError, DependencyError):
                    after = None
                if after == before:
                    return copy.deepcopy(_STATE['accepted'])
                _STATE = None
                continue
            _STATE = None
            value = builder(data, follow)
            _require(isinstance(value, dict), 'Original catalog builder did not return metadata')
            try:
                after = dependencies(data, follow)
            except (OSError, DependencyError):
                after = None
            if after == before:
                if before[-1]:
                    _STATE = dict(builder=builder, key=after, accepted=copy.deepcopy(value))
                return copy.deepcopy(value)
        # A changing directory/metadata cannot establish a coherent catalog.
        # Never return an old positive or the potentially mixed builder result.
        return {}
