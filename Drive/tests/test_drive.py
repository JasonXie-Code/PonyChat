import base64
import hashlib
import hmac
import importlib
import json
import time

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setenv('PONYCHAT_DRIVE_AUTH_SECRET', 'test-drive-secret')
    monkeypatch.setenv('PONYCHAT_DRIVE_PASSWORD', 'test-password')
    app = importlib.import_module('Drive.app')
    routes = importlib.import_module('Drive.routes')
    monkeypatch.setattr(routes, 'DRIVE_ROOT', tmp_path)
    monkeypatch.setattr(routes, 'FILES_ROOT', tmp_path / 'files')
    monkeypatch.setattr(routes, 'TRASH_ROOT', tmp_path / '.trash')
    monkeypatch.setattr(routes, 'TRASH_META', tmp_path / '.trash/metadata.json')
    with TestClient(app.app) as client:
        token = client.post('/api/drive/login', json={'password': 'test-password'}).json()['token']
        client.headers['Authorization'] = f'Bearer {token}'
        yield client, routes


def test_health_and_auth_are_independent_of_chat_backend(service):
    client, _ = service
    assert client.get('/api/drive/health').json()['service'] == 'ponychat-drive'
    assert client.post('/api/drive/login', json={'password': 'wrong'}).status_code == 401
    assert client.get('/api/drive/list', headers={'Authorization': 'Bearer wrong'}).status_code == 401
    assert client.get('/api/chat').status_code == 404


def test_upload_download_and_same_size_txt_save(service):
    client, _ = service
    result = client.post('/api/drive/upload', data={'path': '/'},
                         files=[('files', ('同步.txt', '中文 A', 'text/plain'))])
    assert result.status_code == 200
    assert client.get('/api/drive/list').json()['items'][0]['name'] == '同步.txt'
    assert client.get('/api/drive/download', params={'path': '/同步.txt'}).text == '中文 A'
    assert client.post('/api/drive/text', json={'path': '/同步.txt', 'content': '中文 B'}).status_code == 200
    assert client.get('/api/drive/download', params={'path': '/同步.txt'}).text == '中文 B'


def test_new_empty_txt_and_duplicate_name_preserve_existing_file(service):
    client, _ = service
    for content in (b'original', b''):
        assert client.post('/api/drive/upload', data={'path': '/'},
                           files=[('files', ('new.txt', content, 'text/plain'))]).status_code == 200
    items = client.get('/api/drive/list').json()['items']
    assert {item['name'] for item in items} == {'new.txt', 'new (2).txt'}
    assert client.get('/api/drive/download', params={'path': '/new.txt'}).content == b'original'


def test_folders_copy_rename_trash_restore_and_purge(service):
    client, _ = service
    assert client.post('/api/drive/folder', json={'name': 'folder'}).status_code == 200
    client.post('/api/drive/upload', data={'path': '/folder'}, files=[('files', ('x.txt', b'x', 'text/plain'))])
    assert client.get('/api/drive/tree').json()['folders'][0]['path'] == '/folder'
    copied = client.post('/api/drive/copy', json={'paths': ['/folder/x.txt'], 'target_path': '/'}).json()
    assert copied['items'][0]['path'] == '/x.txt'
    assert client.post('/api/drive/rename', json={'path': '/x.txt', 'name': 'y.txt'}).status_code == 200
    removed = client.post('/api/drive/delete', json={'paths': ['/y.txt']}).json()['items'][0]
    assert client.get('/api/drive/trash').json()['trashCount'] == 1
    assert client.post('/api/drive/restore', json={'ids': [removed['id']]}).status_code == 200
    assert client.get('/api/drive/download', params={'path': '/y.txt'}).content == b'x'
    removed = client.post('/api/drive/delete', json={'paths': ['/y.txt']}).json()['items'][0]
    assert client.post('/api/drive/permanent-delete', json={'ids': [removed['id']]}).status_code == 200
    assert client.get('/api/drive/trash').json()['trashCount'] == 0


def test_path_boundary_and_binary_download(service):
    client, _ = service
    assert client.get('/api/drive/list', params={'path': '/../outside'}).status_code == 400
    raw = bytes(range(256)) * 32
    client.post('/api/drive/upload', data={'path': '/'}, files=[('files', ('binary.bin', raw, 'application/octet-stream'))])
    result = client.get('/api/drive/download', params={'path': '/binary.bin'})
    assert hashlib.sha256(result.content).digest() == hashlib.sha256(raw).digest()


def test_old_login_tokens_are_accepted_only_during_migration_window(service, monkeypatch):
    client, routes = service
    payload = base64.urlsafe_b64encode(json.dumps({'scope': 'ponychat_drive', 'exp': int(time.time()) + 3600}).encode()).decode().rstrip('=')
    signature = base64.urlsafe_b64encode(hmac.new(b'legacy-secret', payload.encode(), 'sha256').digest()).decode().rstrip('=')
    token = f'{payload}.{signature}'
    monkeypatch.setenv('PONYCHAT_DRIVE_LEGACY_AUTH_SECRET', 'legacy-secret')
    monkeypatch.setenv('PONYCHAT_DRIVE_LEGACY_UNTIL', str(int(time.time()) + 600))
    assert routes._drive_token_verify(token)
    assert client.get('/api/drive/list', headers={'Authorization': f'Bearer {token}'}).status_code == 200
    monkeypatch.setenv('PONYCHAT_DRIVE_LEGACY_UNTIL', '1')
    assert not routes._drive_token_verify(token)


def test_cached_cn_clients_get_cors_headers_for_usa_service(service):
    client, _ = service
    response = client.options('/api/drive/login', headers={'Origin': 'https://drive.ponychat.org',
        'Access-Control-Request-Method': 'POST', 'Access-Control-Request-Headers': 'content-type,authorization'})
    assert response.status_code == 200
    assert response.headers['access-control-allow-origin'] == 'https://drive.ponychat.org'
