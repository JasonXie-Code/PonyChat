import asyncio
import json
from uuid import uuid4

import httpx
from fastapi import FastAPI

from Backend.db import Database, UsersDAO
from Backend.routes import auth, my_music


def test_music_library_uses_authenticated_owner_and_preserves_playlist_order(tmp_path, monkeypatch):
    async def scenario():
        db, client, alice, bob = await open_music_api(tmp_path, monkeypatch)
        try:
            path = "/api/me/music"
            playlist_id = str(uuid4())
            assert (await client.get(path)).status_code == 401
            assert (await client.get(path, headers={"Authorization": "Bearer invalid"})).status_code == 401

            old_library = my_music.empty_library()
            del old_library["favoriteAlbums"]
            old_library["favorites"] = ["first"]
            alice_id = await db.get_user_id("alice")
            conn = await db.acquire()
            try:
                await conn.execute("INSERT INTO user_music(user_id, data) VALUES (?, ?)", (alice_id, json.dumps(old_library)))
                await conn.commit()
            finally:
                await db.release(conn)
            migrated = (await client.get(path, headers=alice)).json()
            assert migrated["favoriteAlbums"] == []
            assert migrated["favorites"] == ["first"]

            create = dict(action="createPlaylist", playlistId=playlist_id, name="  雨天  ", songId="first")
            for _ in range(2):
                result = await client.post(path, headers=alice, json=create)
                assert result.status_code == 200, result.text
                assert result.json()["playlists"] == [{"id": playlist_id, "name": "雨天", "songIds": ["first"]}]

            for action, song, extra in (
                ("addSong", "second", {}),
                ("moveSong", "second", {"direction": -1}),
                ("favorite", "first", {"enabled": True}),
            ):
                result = await client.post(path, headers=alice, json={
                    "action": action, "songId": song, "playlistId": playlist_id, **extra,
                })
                assert result.status_code == 200, result.text

            album = {"action": "favoriteAlbum", "albumId": "first", "enabled": True}
            for _ in range(2):
                result = await client.post(path, headers=alice, json=album)
                assert result.status_code == 200, result.text
                assert result.json()["favoriteAlbums"] == ["first"]

            result = await client.get(path, headers=alice)
            assert result.headers["cache-control"] == "private, no-store"
            assert result.json()["favorites"] == ["first"]
            assert result.json()["playlists"][0]["songIds"] == ["second", "first"]
            result = await client.get(path, headers=bob, params={"username": "alice"})
            assert result.json()["favorites"] == []
            assert result.json()["favoriteAlbums"] == []
            assert result.json()["playlists"] == []
            for _ in range(2):
                result = await client.post(path, headers=alice, json={**album, "enabled": False})
                assert result.status_code == 200, result.text
                assert result.json()["favoriteAlbums"] == []
                assert result.json()["favorites"] == ["first"]
            await client.post(path, headers=bob, json={"action": "deletePlaylist", "playlistId": playlist_id})
            assert len((await client.get(path, headers=alice)).json()["playlists"]) == 1
        finally:
            await client.aclose()
            await db.close()

    asyncio.run(scenario())


def test_history_checkpoints_do_not_double_count_or_restore_deleted_records(tmp_path, monkeypatch):
    async def scenario():
        db, client, alice, bob = await open_music_api(tmp_path, monkeypatch)
        try:
            path = "/api/me/music"

            async def command(**body):
                response = await client.post(path, headers=alice, json=body)
                assert response.status_code == 200, response.text
                return response.json()

            play = dict(action="record", songId="track / 一", playId=str(uuid4()), revision=0, sequence=1, positionMs=5000)
            await command(**play)
            await command(**{**play, "sequence": 2, "positionMs": 12000})
            first = await command(**play)
            assert first["history"][0]["count"] == 1
            assert first["history"][0]["positionMs"] == 12000
            second = await command(**{**play, "playId": str(uuid4())})
            assert second["history"][0]["count"] == 2
            assert len(second["history"]) == 1
            assert (await client.get(path, headers=bob)).json()["history"] == []

            removed = await command(action="removeHistory", songId=play["songId"])
            assert removed["history"] == []
            assert (await command(**{**play, "sequence": 3}))["history"] == []
            disabled = await command(action="historySetting", enabled=False)
            assert (await command(**{**play, "revision": disabled["historyRevision"]}))["history"] == []
            enabled = await command(action="historySetting", enabled=True)
            fresh = await command(**{**play, "playId": str(uuid4()), "revision": enabled["historyRevision"]})
            assert fresh["history"][0]["count"] == 1
            assert (await command(action="clearHistory"))["history"] == []
        finally:
            await client.aclose()
            await db.close()

    asyncio.run(scenario())


async def open_music_api(tmp_path, monkeypatch):
    db = Database(str(tmp_path / "music.db"))
    await db.init()
    dao = UsersDAO(db)
    for username in ("alice", "bob"):
        assert await dao.create_user(username=username, password="test-fixture")

    monkeypatch.setattr(my_music, "get_database", lambda: db)
    monkeypatch.setattr(auth, "get_users_dao", lambda: dao)
    monkeypatch.setattr(auth, "is_app_login_allowed", lambda username: True)
    app = FastAPI()
    app.include_router(my_music.router)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test")
    alice = {"Authorization": f"Bearer {auth._auth_token_create('alice')}"}
    bob = {"Authorization": f"Bearer {auth._auth_token_create('bob')}"}
    return db, client, alice, bob
