from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent.parent
WEB_ROOT = ROOT / "web"
DATA_ROOT = Path(os.environ.get("MLP_AUTO_DATA_ROOT", str(ROOT))).resolve()
SOURCE_ROOT = DATA_ROOT / "source"
GENERATED_ROOT = DATA_ROOT / "generated"

app = FastAPI(title="MLP Songs AUTO", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def read_json(path: Path, fallback: Any) -> Any:
    if not path.is_file():
        return fallback
    return json.loads(path.read_text(encoding="utf-8"))


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/demo")
def demo(song: str = "catchy-song") -> dict[str, Any]:
    songs = read_json(GENERATED_ROOT / "songs.json", [])
    song_meta = next((s for s in songs if s.get("id") == song), None)
    if not song_meta and songs:
        song_meta = songs[0]
    if not song_meta:
        song_meta = {
            "id": "catchy-song",
            "title": "You're In My Head Like a Catchy Song",
            "subtitle": "My Little Pony S07E13",
            "audio": "/source/audio/catchy-song.mp3",
            "scorePdf": "/source/scores/catchy-song.pdf",
            "charts": [
                "/source/charts/MLP713 In My Head Like a Catchy song CHART R4 EDIT_00.png",
                "/source/charts/MLP713 In My Head Like a Catchy song CHART R4 EDIT_01.png",
            ],
        }
    generated = GENERATED_ROOT / song_meta["id"]
    report = read_json(generated / "report.json", {})
    analysis = read_json(generated / "analysis.json", {})
    sync = read_json(generated / "sync.json", {})
    jianpu = read_json(generated / "jianpu.json", {})
    return {
        "song": song_meta,
        "songs": songs,
        "report": report,
        "analysis": analysis,
        "sync": sync,
        "jianpu": jianpu,
    }


@app.get("/api/songs")
def songs() -> list[dict[str, Any]]:
    return read_json(GENERATED_ROOT / "songs.json", [])


@app.get("/api/sync")
def sync(song: str = "catchy-song") -> dict[str, Any]:
    return read_json(GENERATED_ROOT / song / "sync.json", {"events": []})


@app.get("/api/analysis")
def analysis(song: str = "catchy-song") -> dict[str, Any]:
    return read_json(GENERATED_ROOT / song / "analysis.json", {})


@app.get("/api/report")
def report(song: str = "catchy-song") -> dict[str, Any]:
    return read_json(GENERATED_ROOT / song / "report.json", {})


@app.get("/api/jianpu")
def jianpu(song: str = "catchy-song") -> dict[str, Any]:
    return read_json(GENERATED_ROOT / song / "jianpu.json", {})


def mount_if_dir(route: str, path: Path, name: str) -> None:
    if path.is_dir():
        app.mount(route, StaticFiles(directory=str(path)), name=name)


mount_if_dir("/audio", SOURCE_ROOT / "audio", "audio")
mount_if_dir("/scores", SOURCE_ROOT / "scores", "scores")
mount_if_dir("/charts", SOURCE_ROOT / "charts", "charts")
mount_if_dir("/generated", GENERATED_ROOT, "generated")

if WEB_ROOT.is_dir():
    app.mount("/", StaticFiles(directory=str(WEB_ROOT), html=True), name="web")
