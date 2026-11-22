"""Account-owned library for the native player. Song and album IDs come from the public catalog."""
import json
import time
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, StringConstraints, Field

from .auth import auth_token_verify
from ..db import get_database

router = APIRouter(prefix="/api/me/music", tags=["My Music"])
SongId = Annotated[str, StringConstraints(min_length=1, max_length=1024)]
AlbumId = Annotated[str, StringConstraints(min_length=1, max_length=256)]
PlaylistName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


class RecordPlay(BaseModel):
    action: Literal["record"]
    songId: SongId
    playId: UUID
    revision: int = Field(ge=0)
    sequence: int = Field(ge=0)
    positionMs: int = Field(ge=0, le=86_400_000)


class HistorySetting(BaseModel):
    action: Literal["historySetting"]
    enabled: bool


class HistoryRemoval(BaseModel):
    action: Literal["removeHistory", "clearHistory"]
    songId: SongId | None = None


class Favorite(BaseModel):
    action: Literal["favorite"]
    songId: SongId
    enabled: bool


class FavoriteAlbum(BaseModel):
    action: Literal["favoriteAlbum"]
    albumId: AlbumId
    enabled: bool


class PlaylistNameChange(BaseModel):
    action: Literal["createPlaylist", "renamePlaylist"]
    playlistId: UUID
    name: PlaylistName
    songId: SongId | None = None


class PlaylistRemoval(BaseModel):
    action: Literal["deletePlaylist"]
    playlistId: UUID


class PlaylistSong(BaseModel):
    action: Literal["addSong", "removeSong", "moveSong"]
    playlistId: UUID
    songId: SongId
    direction: Literal[-1, 1] = 1


MusicCommand = Annotated[
    RecordPlay | HistorySetting | HistoryRemoval | Favorite | FavoriteAlbum | PlaylistNameChange | PlaylistRemoval | PlaylistSong,
    Field(discriminator="action"),
]


async def require_user(authorization: Annotated[str | None, Header()] = None) -> int:
    scheme, _, token = (authorization or "").partition(" ")
    username = await auth_token_verify(token.strip()) if scheme.lower() == "bearer" else None
    user_id = await get_database().get_user_id(username) if username else None
    if user_id is None:
        raise HTTPException(401, "请登录 PonyChat 后重试")
    return user_id


def empty_library():
    return {
        "favorites": [],
        "favoriteAlbums": [],
        "playlists": [],
        "history": [],
        "historyEnabled": True,
        "historyRevision": 0,
        "plays": {},
    }


async def read_library(conn, user_id):
    async with conn.execute("SELECT data FROM user_music WHERE user_id = ?", (user_id,)) as cursor:
        row = await cursor.fetchone()
    if row is None:
        return empty_library()
    library = json.loads(row[0])
    library.setdefault("favoriteAlbums", [])
    return library


def public_library(state):
    result = {key: value for key, value in state.items() if key != "plays"}
    result["history"] = [{key: value for key, value in entry.items() if key != "playId"} for entry in state["history"]]
    return result


def record_play(state, cmd: RecordPlay):
    if not state["historyEnabled"] or cmd.revision != state["historyRevision"]:
        return
    plays = state["plays"]
    play_id = str(cmd.playId)
    play = plays.get(play_id)
    if play and (cmd.songId != play["songId"] or cmd.sequence <= play["sequence"]):
        return

    history = state["history"]
    entry = next((item for item in history if item["songId"] == cmd.songId), None)
    if play is None:
        if entry is None:
            entry = {"songId": cmd.songId, "count": 0}
        else:
            history.remove(entry)
        entry.update(count=entry["count"] + 1, playId=play_id, playedAtMs=time.time_ns() // 1_000_000)
        history.insert(0, entry)
        del history[200:]
    if entry and entry["playId"] == play_id:
        entry["positionMs"] = cmd.positionMs
    plays.pop(play_id, None)
    plays[play_id] = {"songId": cmd.songId, "sequence": cmd.sequence}
    if len(plays) > 1000:
        del plays[next(iter(plays))]


def apply_command(state, cmd: MusicCommand):
    if isinstance(cmd, RecordPlay):
        record_play(state, cmd)
    elif isinstance(cmd, HistorySetting):
        if state["historyEnabled"] != cmd.enabled:
            state["historyEnabled"] = cmd.enabled
            state["historyRevision"] += 1
            state["plays"].clear()
    elif isinstance(cmd, HistoryRemoval):
        if cmd.action == "clearHistory":
            state["history"].clear()
        elif cmd.songId is not None:
            state["history"] = [item for item in state["history"] if item["songId"] != cmd.songId]
        else:
            raise HTTPException(422, "请选择要删除的歌曲")
        state["historyRevision"] += 1
        state["plays"].clear()
    elif isinstance(cmd, Favorite):
        change_favorite(state["favorites"], cmd.songId, cmd.enabled)
    elif isinstance(cmd, FavoriteAlbum):
        change_favorite(state["favoriteAlbums"], cmd.albumId, cmd.enabled)
    else:
        change_playlist(state["playlists"], cmd)


def change_favorite(favorites: list[str], item_id: str, enabled: bool):
    if enabled and item_id not in favorites:
        if len(favorites) >= 2000:
            raise HTTPException(409, "收藏已满")
        favorites.insert(0, item_id)
    elif not enabled and item_id in favorites:
        favorites.remove(item_id)


def change_playlist(playlists, cmd):
    playlist_id = str(cmd.playlistId)
    playlist = next((item for item in playlists if item["id"] == playlist_id), None)
    if cmd.action == "createPlaylist":
        if playlist is None:
            if len(playlists) >= 100:
                raise HTTPException(409, "歌单已满")
            playlists.append({"id": playlist_id, "name": cmd.name, "songIds": [cmd.songId] if cmd.songId else []})
        return
    if playlist is None:
        if cmd.action == "deletePlaylist":
            return
        raise HTTPException(404, "歌单已删除")
    if cmd.action == "renamePlaylist":
        playlist["name"] = cmd.name
    elif cmd.action == "deletePlaylist":
        playlists.remove(playlist)
    else:
        songs = playlist["songIds"]
        if cmd.action == "addSong" and cmd.songId not in songs:
            if len(songs) >= 500:
                raise HTTPException(409, "歌单曲目已满")
            songs.append(cmd.songId)
        elif cmd.action == "removeSong" and cmd.songId in songs:
            songs.remove(cmd.songId)
        elif cmd.action == "moveSong" and cmd.songId in songs:
            index = songs.index(cmd.songId)
            target = index + cmd.direction
            if 0 <= target < len(songs):
                songs[index], songs[target] = songs[target], songs[index]


@router.get("")
async def get_music(response: Response, user_id: Annotated[int, Depends(require_user)]):
    response.headers["Cache-Control"] = "private, no-store"
    db = get_database()
    conn = await db.acquire()
    try:
        return public_library(await read_library(conn, user_id))
    finally:
        await db.release(conn)


@router.post("")
async def update_music(cmd: MusicCommand, response: Response, user_id: Annotated[int, Depends(require_user)]):
    response.headers["Cache-Control"] = "private, no-store"
    db = get_database()
    conn = await db.acquire()
    try:
        await conn.execute("BEGIN IMMEDIATE")
        state = await read_library(conn, user_id)
        apply_command(state, cmd)
        data = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
        if len(data.encode("utf-8")) > 2_000_000:
            raise HTTPException(409, "个人曲库已满")
        await conn.execute(
            """INSERT INTO user_music(user_id, data) VALUES (?, ?)
               ON CONFLICT(user_id) DO UPDATE SET data = excluded.data""",
            (user_id, data),
        )
        await conn.commit()
        return public_library(state)
    finally:
        if conn.in_transaction:
            await conn.rollback()
        await db.release(conn)
