import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from Backend import websocket_endpoint, websocket_heartbeat
from Backend.login_control import is_app_login_allowed
from Backend.routes import auth as auth_route


@pytest.mark.parametrize("username", ["Jason", "System", "LaoWuPony"])
def test_existing_users_remain_allowed(username):
    assert is_app_login_allowed(username)


@pytest.mark.parametrize("username", ["jason", "system", "ordinary-user", "普通用户", "g_123456", " Jason ", ""])
def test_login_has_no_username_allowlist(username):
    assert is_app_login_allowed(username)


@pytest.fixture
def users(monkeypatch):
    dao = AsyncMock()
    dao.get_user.return_value = {"role": "user", "gender": "male"}
    dao.verify_password.return_value = True
    dao.get_token_version.return_value = 2
    dao.increment_token_version.return_value = 2
    dao.user_exists.return_value = True
    monkeypatch.setattr(auth_route, "get_users_dao", lambda: dao)
    monkeypatch.setattr(auth_route.manager, "force_logout_user", AsyncMock())
    return dao


@pytest.mark.parametrize("username", ["Jason", "LaoWuPony", "ordinary-user", "普通用户"])
def test_any_valid_account_can_login_and_verify_token(users, username):
    result = asyncio.run(auth_route.login_user(
        auth_route.AuthRequest(username=username, password="correct-password")
    ))
    assert result["success"]
    assert asyncio.run(auth_route.auth_token_verify(result["auth_token"])) == username
    users.verify_password.assert_awaited_once_with(username, "correct-password")


def test_wrong_password_is_still_rejected(users):
    users.verify_password.return_value = False
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(auth_route.login_user(
            auth_route.AuthRequest(username="ordinary-user", password="wrong-password")))
    assert exc_info.value.status_code == 401


def test_unknown_account_is_still_rejected(users):
    users.get_user.return_value = None
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(auth_route.login_user(
            auth_route.AuthRequest(username="missing-user", password="wrong-password")))
    assert exc_info.value.status_code == 401


def test_stale_and_invalid_tokens_still_fail(users):
    stale = auth_route._auth_token_create("Jason", token_version=1)
    assert asyncio.run(auth_route.auth_token_verify(stale)) is None
    valid = auth_route._auth_token_create("Jason", token_version=2)
    assert asyncio.run(auth_route.auth_token_verify(valid + "tampered")) is None


def test_existing_valid_token_for_ordinary_user_remains_valid(users):
    token = auth_route._auth_token_create("ordinary-user", token_version=2)
    assert asyncio.run(auth_route.auth_token_verify(token)) == "ordinary-user"
    users.get_token_version.assert_awaited_once_with("ordinary-user")


def test_existing_guest_can_login(users):
    result = asyncio.run(auth_route.guest_login(auth_route.GuestLoginRequest(device_id="device")))
    assert result['username'].startswith('g_')
    assert asyncio.run(auth_route.auth_token_verify(result['token'])) == result['username']


def test_ordinary_websocket_reaches_connection_manager(monkeypatch):
    from fastapi import WebSocketDisconnect
    import Backend.delivery_outbox as outbox
    connect = AsyncMock()
    monkeypatch.setattr(auth_route.manager, 'connect', connect)
    monkeypatch.setattr(auth_route.manager, 'disconnect', AsyncMock())
    monkeypatch.setattr(outbox, 'flush_outbox_to_websocket', AsyncMock())
    websocket = AsyncMock()
    websocket.query_params = {}
    websocket.receive_text.side_effect = WebSocketDisconnect()
    asyncio.run(websocket_endpoint(websocket, 'ordinary-user'))
    connect.assert_awaited_once_with(websocket, 'ordinary-user')
    websocket.send_json.assert_not_awaited()


def test_ordinary_heartbeat_reaches_connection_manager(monkeypatch):
    register = AsyncMock(return_value=False)
    monkeypatch.setattr(auth_route.manager, 'register_connection', register)
    websocket = AsyncMock()
    websocket.receive_json.return_value = {'username': 'ordinary-user'}
    asyncio.run(websocket_heartbeat(websocket))
    register.assert_awaited_once_with(websocket, 'ordinary-user')
    websocket.send_json.assert_not_awaited()
