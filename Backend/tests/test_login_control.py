import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from Backend import websocket_endpoint, websocket_heartbeat
from Backend.login_control import LOGIN_CONTROL_MESSAGE, is_app_login_allowed
from Backend.routes import auth as auth_route


@pytest.mark.parametrize("username", ["Jason", "System"])
def test_login_allows_whitelisted_users(username):
    assert is_app_login_allowed(username)


@pytest.mark.parametrize("username", ["jason", "system", "ordinary-user", "普通用户", "g_123456", " Jason ", ""])
def test_login_rejects_non_whitelisted_users(username):
    assert not is_app_login_allowed(username)


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


def test_whitelisted_user_can_login_and_verify_token(users):
    result = asyncio.run(auth_route.login_user(
        auth_route.AuthRequest(username="Jason", password="correct-password")
    ))
    assert result["success"]
    assert asyncio.run(auth_route.auth_token_verify(result["auth_token"])) == "Jason"
    users.verify_password.assert_awaited_once_with("Jason", "correct-password")


def test_non_whitelisted_login_is_rejected_before_database_access(monkeypatch):
    get_users_dao = AsyncMock()
    monkeypatch.setattr(auth_route, "get_users_dao", get_users_dao)
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(auth_route.login_user(
            auth_route.AuthRequest(username="ordinary-user", password="correct-password")
        ))
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == LOGIN_CONTROL_MESSAGE
    get_users_dao.assert_not_called()


def test_stale_and_invalid_tokens_still_fail(users):
    stale = auth_route._auth_token_create("Jason", token_version=1)
    assert asyncio.run(auth_route.auth_token_verify(stale)) is None
    valid = auth_route._auth_token_create("Jason", token_version=2)
    assert asyncio.run(auth_route.auth_token_verify(valid + "tampered")) is None


def test_existing_token_for_non_whitelisted_user_is_invalidated(users):
    token = auth_route._auth_token_create("ordinary-user", token_version=2)
    assert asyncio.run(auth_route.auth_token_verify(token)) is None
    users.get_token_version.assert_not_awaited()


def test_guest_login_is_disabled(users):
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(auth_route.guest_login(auth_route.GuestLoginRequest(device_id="device")))
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == LOGIN_CONTROL_MESSAGE


def test_non_whitelisted_websocket_forces_logout(monkeypatch):
    connect = AsyncMock()
    monkeypatch.setattr(auth_route.manager, "connect", connect)
    websocket = AsyncMock()
    websocket.query_params = {}
    asyncio.run(websocket_endpoint(websocket, "ordinary-user"))
    connect.assert_not_awaited()
    websocket.accept.assert_awaited_once()
    websocket.send_json.assert_awaited_once_with({"type": "force_logout", "reason": "login_control"})
    websocket.close.assert_awaited_once_with(code=4003, reason="Login restricted")


def test_non_whitelisted_heartbeat_forces_logout(monkeypatch):
    register = AsyncMock(return_value=False)
    monkeypatch.setattr(auth_route.manager, "register_connection", register)
    websocket = AsyncMock()
    websocket.receive_json.return_value = {"username": "ordinary-user"}
    asyncio.run(websocket_heartbeat(websocket))
    register.assert_not_awaited()
    websocket.send_json.assert_awaited_once_with({"type": "force_logout", "reason": "login_control"})
    websocket.close.assert_awaited_once_with(code=4003, reason="Login restricted")
