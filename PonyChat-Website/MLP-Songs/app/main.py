# -*- coding: utf-8 -*-
"""
MLP Music — FastAPI 元数据 API。

生产后端与数据位于本机；Server-CN 中转，Server-USA 提供静态网页及域名。
媒体目录由环境变量指定，本地开发默认挂载项目下 media-export/。

项目根目录：PonyChat/MLP-Songs/
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from music_data import DATA, FOLLOW, follow_for, load_index, lyrics_for, search_songs
from analytics_routes import router as analytics_router
from follow_frontend_routes import router as follow_frontend_router
from analytics_lifespan import lifespan
from api_compression import ApiCompression
from normalized_audio import CatalogPlaybackOnly, audio_response
from source_asset_compression import SourceAssetCompression

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent
INDEX_PATH = DATA / "index.json"

MEDIA_ROOT = Path(
    os.environ.get("MLP_MEDIA_ROOT", str(ROOT_DIR / "media-export"))
).resolve()

WEB_ROOT = Path(os.environ.get("MLP_WEB_ROOT", str(ROOT_DIR / "web"))).resolve()
OPUS_ONLY = bool(os.environ.get("MLP_NORMALIZED_ROOT"))

app = FastAPI(title="MLP Music API", version="2.0.7", lifespan=lifespan)
app.include_router(analytics_router)
app.include_router(follow_frontend_router)
app.add_middleware(ApiCompression)
app.add_middleware(SourceAssetCompression)
if OPUS_ONLY:
    app.add_middleware(CatalogPlaybackOnly)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _load_index() -> dict[str, Any]:
    return load_index()


@app.get("/api/lyrics")
def api_lyrics(song: str = Query(...)):
    return lyrics_for(song)


@app.get("/api/follow/demo")
def api_follow(song: str = "catchy-song", view: str | None = None):
    payload = follow_for(song, view=view) if view is not None else follow_for(song)
    return JSONResponse(payload)


@app.get("/api/search")
def api_search(q: str = Query(..., min_length=1, max_length=160), versions: bool = False):
    return {"songs": search_songs(q, versions)}


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": "2.0.7"}


@app.get("/api/ready")
def readiness():
    """Exercise real directory loading; /api/health remains a liveness probe."""
    if getattr(app.state, 'follow_warming', False):
        raise HTTPException(503, 'Recording directory available; score readers warming')
    if getattr(app.state, 'follow_warm_error', False):
        raise HTTPException(503, 'Score reader warmup unavailable')
    try:
        data = load_index()
        if not data.get("songs"):
            raise ValueError("Empty recording catalog")
    except Exception as error:
        raise HTTPException(503, "Music catalog unavailable") from error
    return {"status": "ok", "songs": len(data["songs"]),
            "albums": len(data.get("albums", [])), "scores": len(data.get("scores", [])),
            "follows": sum(bool(song.get("followId")) for song in data["songs"])}


@app.get("/api/albums")
def api_albums() -> dict[str, Any]:
    data = load_index(include_follows=False)
    return {"generated": data.get("generated"), "albums": data.get("albums", [])}


@app.get('/api/library')
def api_library():
    """Browsable recordings need no follow admission; never imply an approved reader.

    Clients obtain follow badges separately from the original strict /api/songs.
    Follow API responses and signed assets retain their live admission checks.
    """
    data = load_index(include_follows=False)
    songs = [{key: value for key, value in song.items()
              if key not in ('followId', 'followViewPath')} for song in data['songs']]
    return JSONResponse(dict(generated=data.get('generated'), albums=data.get('albums', []),
                             songs=songs, scores=data.get('scores', [])),
                        headers={'Cache-Control': 'no-cache'})


@app.get("/api/songs")
def api_songs(
    album: str | None = Query(None, description="专辑 slug，如 season-01-2010"),
    q: str | None = Query(None, description="标题模糊搜索"),
) -> dict[str, Any]:
    if getattr(app.state, 'follow_warming', False):
        raise HTTPException(503, 'Score readers warming',
                            headers={'X-Music-Warming': 'readers', 'Retry-After': '3'})
    if getattr(app.state, 'follow_warm_error', False):
        raise HTTPException(503, 'Score reader warmup unavailable')
    data = _load_index()
    songs: list[dict] = list(data.get("songs", []))
    if album:
        songs = [s for s in songs if s.get("albumId") == album]
    if q and q.strip():
        pat = re.compile(re.escape(q.strip()), re.IGNORECASE)
        songs = [s for s in songs if pat.search(s.get("title") or "")]
    return {
        "generated": data.get("generated"),
        "count": len(songs),
        "songs": songs,
    }


@app.get("/api/scores")
def api_scores(
    q: str | None = Query(None, description="乐谱文件名/标题模糊搜索"),
) -> dict[str, Any]:
    data = load_index(include_follows=False)
    scores: list[dict] = list(data.get("scores", []))
    if q and q.strip():
        pat = re.compile(re.escape(q.strip()), re.IGNORECASE)
        scores = [x for x in scores if pat.search(x.get("title") or x.get("id") or "")]
    return {
        "generated": data.get("generated"),
        "count": len(scores),
        "scores": scores,
    }


def _mount_if_dir(mount_path: str, sub: str) -> None:
    full = MEDIA_ROOT / sub
    if full.is_dir():
        app.mount(mount_path, StaticFiles(directory=str(full)), name=sub.replace("/", "_"))


@app.api_route('/audio/{audio_path:path}', methods=['GET', 'HEAD'])
def audio_file(audio_path: str):
    return audio_response(audio_path, MEDIA_ROOT, opus_only=OPUS_ONLY)


_mount_if_dir("/scores", "scores")
_mount_if_dir("/covers", "covers")
_mount_if_dir("/charts", "charts")

for section in ("audio", "scores", "charts"):
    path = FOLLOW / "source" / section
    if path.is_dir():
        app.mount("/follow-media/" + section, StaticFiles(directory=str(path)), name="follow-" + section)
source_charts = FOLLOW / "source" / "charts"
if source_charts.is_dir():
    app.mount("/follow-media/source/charts", StaticFiles(directory=str(source_charts)), name="follow-source-charts")
if (FOLLOW / "generated").is_dir():
    app.mount("/follow-media/generated", StaticFiles(directory=str(FOLLOW / "generated")), name="follow-generated")

if WEB_ROOT.is_dir() and (WEB_ROOT / "index.html").is_file():
    app.mount("/", StaticFiles(directory=str(WEB_ROOT), html=True), name="web")
