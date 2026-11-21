"""Serve exact current signed frontend bytes under their certificate cache key."""
from __future__ import annotations

from pathlib import Path
import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from follow_frontend import accepted_frontend_path, frontend_assets


def versioned_frontend_response(version, relative, follow, web, entries):
    """An alias is allowed only for the current admitted exact asset manifest."""
    from follow_clock_system_route import RELATIVE, response_path
    if relative == RELATIVE:
        try:
            path,digest=response_path(version,relative,follow,web,entries)
        except (OSError,ValueError,KeyError,TypeError,AttributeError):
            raise HTTPException(404, 'Signed frontend asset not found') from None
        return FileResponse(path,headers={'Cache-Control':'no-cache','ETag':'"'+digest+'"'})
    match = re.fullmatch(r'generated/([a-z0-9-]+)/accepted-frontend/([a-z0-9.-]+)', relative)
    if not re.fullmatch(r'[a-f0-9]{64}', version) or match is None:
        raise HTTPException(404, 'Signed frontend asset not found')
    fid, name = match.groups()
    meta = next((m for m in entries.values() if m.get('id') == fid), None)
    try:
        if meta is None or meta.get('acceptance', {}).get('sha256') != version:
            raise ValueError('Not current certificate')
        expected = '/follow-media/v/' + version + '/' + meta['frontend']['frame']
        validated = getattr(entries, 'frontend_paths', None) or {}
        frame = validated.get(meta.get('sourceSongId'))
        if (frame if frame is not None else accepted_frontend_path(meta, follow, web)) != expected:
            raise ValueError('Not signed current frontend')
        # The admission cache already checked the entire signed asset set and
        # freshly rechecked every dependency before returning this sidecar.
        assets = ([(f"generated/{fid}/accepted-frontend/{asset}",
                    Path(follow) / f"generated/{fid}/accepted-frontend/{asset}", digest)
                   for asset, digest in meta['frontend']['assets'].items()]
                  if frame is not None else frontend_assets(meta, follow, web))
        row = next((r for r in assets if r[0] == relative), None)
        if name not in meta['frontend']['assets'] or row is None:
            raise ValueError('Undeclared frontend asset')
        path = Path(row[1]).resolve()
        if not path.is_relative_to(Path(follow).resolve()):
            raise ValueError('Asset escaped follow root')
    except (OSError, ValueError, KeyError, TypeError):
        raise HTTPException(404, 'Signed frontend asset not found') from None
    return FileResponse(path, headers={'Cache-Control': 'no-cache', 'ETag': '"' + row[2] + '"'})


router = APIRouter()


@router.get('/follow-media/v/{version}/{relative:path}')
def versioned_frontend(version: str, relative: str):
    # Resolve the active process configuration, including isolated previews.
    import os
    import music_data
    from follow_clock_system_route import FID, RELATIVE
    web = Path(os.environ.get('MLP_WEB_ROOT', str(music_data.DATA.parent.parent / 'web')))
    match = re.fullmatch(r'generated/([a-z0-9-]+)/accepted-frontend/([a-z0-9.-]+)', relative)
    if match is not None or relative == RELATIVE:
        from follow_catalog import accepted_follow_entry
        # The one signed clock sidecar belongs to this same recording. Keep its
        # complete response_path proof checks without scanning unrelated songs.
        follow_id = match[1] if match is not None else FID
        entries = accepted_follow_entry(music_data.DATA, music_data.FOLLOW, follow_id)
    else:
        entries = music_data.accepted_follow_entries(music_data.DATA, music_data.FOLLOW)
    return versioned_frontend_response(version, relative, music_data.FOLLOW, web, entries)
