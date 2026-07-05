# -*- coding: utf-8 -*-
"""
MLP Music — FastAPI 元数据 API。

生产环境由 Nginx 将 /audio、/scores、/covers 指向 /data/mlp-music/；
本地开发可设置环境变量或默认挂载项目下 media-export/ 以便联调。

项目根目录：PonyChat/MLP-Songs/
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent
INDEX_PATH = BASE_DIR / "data" / "index.json"

MEDIA_ROOT = Path(
    os.environ.get("MLP_MEDIA_ROOT", str(ROOT_DIR / "media-export"))
).resolve()

WEB_ROOT = Path(os.environ.get("MLP_WEB_ROOT", str(ROOT_DIR / "web"))).resolve()

app = FastAPI(title="MLP Music API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _load_index() -> dict[str, Any]:
    if not INDEX_PATH.is_file():
        return {
            "generated": None,
            "albums": [],
            "songs": [],
            "scores": [],
        }
    return json.loads(INDEX_PATH.read_text(encoding="utf-8"))


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/albums")
def api_albums() -> dict[str, Any]:
    data = _load_index()
    return {"generated": data.get("generated"), "albums": data.get("albums", [])}


@app.get("/api/songs")
def api_songs(
    album: str | None = Query(None, description="专辑 slug，如 season-01-2010"),
    q: str | None = Query(None, description="标题模糊搜索"),
) -> dict[str, Any]:
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
    data = _load_index()
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


_mount_if_dir("/audio", "audio")
_mount_if_dir("/scores", "scores")
_mount_if_dir("/covers", "covers")
_mount_if_dir("/charts", "charts")

if WEB_ROOT.is_dir() and (WEB_ROOT / "index.html").is_file():
    app.mount("/", StaticFiles(directory=str(WEB_ROOT), html=True), name="web")
