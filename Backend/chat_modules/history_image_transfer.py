"""One-shot retrieval of a conversation image from the owner's online phone."""
import asyncio
import base64
import secrets
from io import BytesIO

_pending = {}


async def request_from_phone(username, request, *, timeout=20):
    from ..websocket import manager
    if not manager.get_connection_count(username):
        return None
    token = secrets.token_urlsafe(24)
    future = asyncio.get_running_loop().create_future()
    targets = set(manager.active_connections.get(username, ()))
    _pending[token] = (username, future, targets, request['action'])
    try:
        await manager.broadcast_to_user(username, {
            **request, 'type': 'history_image_request', 'request_id': token,
        })
        return await asyncio.wait_for(future, timeout)
    except asyncio.TimeoutError:
        return None
    finally:
        _pending.pop(token, None)


def receive_original(username, payload, socket):
    token = payload.get('request_id')
    if not isinstance(token, str) or len(token) > 128:
        return False
    pending = _pending.get(token)
    if not pending or pending[0] != username or pending[1].done() or socket not in pending[2]:
        return False
    if payload.get('status') != 'ok':
        pending[2].discard(socket)
        if not pending[2]:
            pending[1].set_result(None)
        return True
    if pending[3] == 'list':
        pending[1].set_result({'status': 'ok', 'images': payload.get('images'),
                               'has_more': payload.get('has_more') is True})
        return True
    encoded = payload.get('data')
    if not isinstance(encoded, str) or not 0 < len(encoded) <= 12 * 1024 * 1024:
        return False
    try:
        raw = base64.b64decode(encoded, validate=True)
    except ValueError:
        return False
    from PIL import Image
    try:
        with Image.open(BytesIO(raw)) as picture:
            mime = Image.MIME.get(picture.format)
            picture.verify()
    except (ValueError, OSError):
        return False
    if not mime or len(raw) > 8 * 1024 * 1024:
        return False
    pending[1].set_result({'image': 'data:' + mime + ';base64,' + encoded})
    return True
