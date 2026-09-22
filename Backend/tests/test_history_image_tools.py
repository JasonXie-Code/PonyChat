"""History picture ownership, local-phone transfer and native image result regressions."""
import asyncio
import base64
import importlib
from io import BytesIO
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace
import types

import pytest
from PIL import Image

ROOT = Path(__file__).parents[1]
PACKAGE = 'history_image_test_app'
for name, path in [(PACKAGE, ROOT), (PACKAGE + '.chat_modules', ROOT / 'chat_modules')]:
    package = types.ModuleType(name)
    package.__path__ = [str(path)]
    sys.modules[name] = package
module = importlib.import_module(PACKAGE + '.chat_modules.history_image_tools')
transfer = importlib.import_module(PACKAGE + '.chat_modules.history_image_transfer')


def image_data():
    output = BytesIO()
    Image.new('RGB', (64, 48), 'red').save(output, 'PNG')
    return base64.b64encode(output.getvalue()).decode()


@pytest.fixture
def tools(tmp_path):
    db = tmp_path / 'images.db'
    with sqlite3.connect(db) as conn:
        conn.executescript('''
            CREATE TABLE users(id INTEGER,username TEXT);
            CREATE TABLE conversations(id TEXT,user_id INTEGER,character_id TEXT,is_hidden INTEGER DEFAULT 0);
            CREATE TABLE messages(id TEXT,message_id TEXT,conversation_id TEXT,role TEXT,content TEXT,
                timestamp INTEGER,is_hidden INTEGER DEFAULT 0,deleted_at TEXT);
            INSERT INTO users VALUES(1,'alice'),(2,'bob');
            INSERT INTO conversations VALUES('ours',1,'pony',0),('other',2,'pony',0),
                ('other_character',1,'different',0),('hidden_conv',1,'pony',1);
        ''')
        for mid, conv, hidden, deleted in [('old','ours',0,None), ('recent','ours',0,None),
                ('hidden','ours',1,None), ('deleted','ours',0,'today'), ('foreign','other',0,None),
                ('wrong_character','other_character',0,None), ('hidden_conv','hidden_conv',0,None)]:
            # Real legacy user messages have no image URL at all.
            conn.execute('INSERT INTO messages VALUES(?,?,?,?,?,?,?,?)',
                (mid, mid, conv, 'user', 'a previous message', 10, hidden, deleted))
    return module.HistoryImageTools(db, username='alice', character_id='pony', conversation_id='ours')


def test_catalog_reconstructs_legacy_images_and_filters_hidden_and_foreign(tools, monkeypatch):
    calls = []
    async def phone(username, request):
        calls.append((username, request))
        return {'status': 'ok', 'images': [{'message_id': mid, 'image_count': 1}
            for mid in ['old','recent','hidden','deleted','foreign','wrong_character','hidden_conv']], 'has_more': True}
    monkeypatch.setattr(module, 'request_from_phone', phone)
    result = asyncio.run(tools.list_images({'offset': 40, 'limit': 20}))
    assert [r['message_id'] for r in result['images']] == ['old', 'recent']
    assert result['next_offset'] == 60
    assert calls[0][1] == {'action':'list','character_id':'pony','conversation_id':'ours','offset':40,'limit':20}


@pytest.mark.parametrize('mid', ['foreign','hidden','deleted','wrong_character','hidden_conv','absent'])
def test_read_never_requests_unowned_or_deleted_message(tools, monkeypatch, mid):
    async def forbidden(*args, **kwargs):
        raise AssertionError('Must not request this message from phone')
    monkeypatch.setattr(module, 'request_from_phone', forbidden)
    assert asyncio.run(tools.read_image({'message_id':mid}))['status'] == 'not_found'


def test_read_loads_phone_pixels_even_without_server_image_reference(tools, monkeypatch):
    async def phone(username, request):
        if request['action'] == 'list':
            return {'status': 'ok', 'images': [{'message_id': 'old', 'image_count': 2}], 'has_more': False}
        assert request['image_index'] == 2 and request['message_id'] == 'old'
        return {'image':'data:image/png;base64,' + image_data()}
    monkeypatch.setattr(module, 'request_from_phone', phone)
    asyncio.run(tools.list_images({}))
    result = asyncio.run(tools.read_image({'message_id':'old','image_index':2}))
    block = result['content'][1]
    assert block['type'] == 'image' and block['mimeType'] == 'image/jpeg'
    with Image.open(BytesIO(base64.b64decode(block['data']))) as picture:
        assert picture.size == (64,48)
        assert picture.getpixel((20,20))[0] > 240


@pytest.mark.parametrize('operation', ['list', 'read'])
def test_missing_phone_picture_preserves_historical_scope(tools, monkeypatch, operation):
    async def phone(username, request):
        if operation == 'read' and request['action'] == 'list':
            return {'status': 'ok', 'images': [{'message_id': 'old', 'image_count': 1}], 'has_more': False}
        return None
    monkeypatch.setattr(module, 'request_from_phone', phone)
    if operation == 'read':
        asyncio.run(tools.list_images({}))
    result = asyncio.run(tools.list_images({}) if operation == 'list' else tools.read_image({'message_id':'old'}))
    assert result['status'] == 'unavailable' and result['scope'] == 'history'
    assert result['reason'] == ('image_catalog_unavailable' if operation == 'list' else 'original_image_unavailable')
    assert result['message_id'] == (None if operation == 'list' else 'old')
    assert '不代表用户本轮' in result['note'] or '不是用户本轮' in result['note']
    assert '仅当用户本轮明确要求' in result['note']


@pytest.mark.parametrize('message_ids', [[], ['hidden', 'foreign', 'deleted']])
def test_empty_visible_catalog_is_not_a_failed_user_upload(tools, monkeypatch, message_ids):
    async def phone(*args, **kwargs):
        return {'status': 'ok', 'images': [{'message_id': mid, 'image_count': 1} for mid in message_ids],
                'has_more': False}
    monkeypatch.setattr(module, 'request_from_phone', phone)
    result = asyncio.run(tools.list_images({}))
    assert result['status'] == 'ok'
    assert result['images'] == [] and result['next_offset'] is None
    assert 'reason' not in result
    assert '不要求用户重发' in result['note']


@pytest.mark.parametrize('available', [True, False])
def test_read_own_sticker_never_attributes_it_to_user(tools, monkeypatch, available):
    with sqlite3.connect(tools.db_path) as conn:
        conn.execute("UPDATE messages SET role='assistant' WHERE message_id='old'")
    async def phone(username, request):
        if request['action'] == 'list':
            return {'status': 'ok', 'images': [{'message_id': 'old', 'image_count': 1}], 'has_more': False}
        return {'image': 'data:image/png;base64,' + image_data()} if available else None
    monkeypatch.setattr(module, 'request_from_phone', phone)
    asyncio.run(tools.list_images({}))
    result = asyncio.run(tools.read_image({'message_id': 'old'}))
    if available:
        import json
        label = json.loads(result['content'][0]['text'])
        assert label['role'] == 'assistant' and label['message_id'] == 'old'
    else:
        assert result['role'] == 'assistant'
        assert '不要求用户重发角色的图片' in result['note']


def test_plain_text_cannot_be_probed_as_an_image(tools, monkeypatch):
    async def forbidden(*args, **kwargs):
        raise AssertionError('Plain text must not trigger a phone image request')
    monkeypatch.setattr(module, 'request_from_phone', forbidden)
    result = asyncio.run(tools.read_image({'message_id': 'old', 'image_index': 1,
                                          'selection_reason': '核对该条用户消息是否附带图片'}))
    assert result['status'] == 'not_found' and result['reason'] == 'image_not_confirmed'
    assert '不要求用户重发' in result['note']


def test_read_checks_confirmed_image_count_and_current_visibility(tools, monkeypatch):
    async def phone(username, request):
        assert request['action'] == 'list'
        return {'status': 'ok', 'images': [{'message_id': 'old', 'image_count': 1}], 'has_more': False}
    monkeypatch.setattr(module, 'request_from_phone', phone)
    asyncio.run(tools.list_images({}))
    assert asyncio.run(tools.read_image({'message_id': 'old', 'image_index': 2}))['reason'] == 'image_index_out_of_range'
    with sqlite3.connect(tools.db_path) as conn:
        conn.execute("UPDATE messages SET is_hidden=1 WHERE message_id='old'")
    assert asyncio.run(tools.read_image({'message_id': 'old'}))['status'] == 'not_found'


@pytest.mark.parametrize("role", ["user", "assistant"])
def test_explicit_repeat_can_stage_the_same_prior_image(tools, monkeypatch, role):
    with sqlite3.connect(tools.db_path) as conn:
        conn.execute("UPDATE messages SET role=? WHERE message_id='old'", (role,))
    async def phone(username, request):
        if request['action'] == 'list':
            return {'status': 'ok', 'images': [{'message_id': 'old', 'image_count': 1}], 'has_more': False}
        assert request == {'action': 'read', 'character_id': 'pony', 'conversation_id': 'ours',
                           'message_id': 'old', 'image_index': 1}
        return {'image': 'data:image/png;base64,' + image_data()}
    monkeypatch.setattr(module, 'request_from_phone', phone)
    asyncio.run(tools.list_images({}))
    staged = asyncio.run(tools.resend_image({'message_id': 'old', 'after_bubble_index': 0}))
    assert staged['staged'] is True
    request = SimpleNamespace()
    tools.apply_to_request(request, 1)
    attachment = request._assistant_asset_attachments[0]
    assert attachment['metadata']['source'] == 'history_repeat'
    assert attachment['metadata']['source_message_id'] == 'old'

    assert attachment['metadata']['source_role'] == role


def test_repeat_tool_requires_catalog_confirmation(tools):
    registered = {}
    tools.register(lambda name, description, schema, callback: registered.update({name: callback}))
    assert 'resend_history_image' in registered
    with pytest.raises(ValueError, match='目录|定位|图片'):
        asyncio.run(tools.resend_image({'message_id': 'old'}))


@pytest.mark.parametrize('role', ['user', 'assistant'])
@pytest.mark.parametrize('message_id', ['hidden', 'deleted', 'foreign', 'wrong_character', 'hidden_conv'])
def test_repeat_rejects_inaccessible_images(tools, message_id, role):
    with sqlite3.connect(tools.db_path) as conn:
        conn.execute("UPDATE messages SET role=?", (role,))
    with pytest.raises(ValueError, match='只能重发当前账号'):
        asyncio.run(tools.resend_image({'message_id': message_id}))
    assert tools.repeated == []


@pytest.mark.parametrize('original', [None, 'data:image/png;base64,bm90IGFuIGltYWdl'])
def test_repeat_unavailable_or_invalid_original_never_stages(tools, monkeypatch, original):
    with sqlite3.connect(tools.db_path) as conn:
        conn.execute("UPDATE messages SET role='assistant' WHERE message_id='old'")
    async def phone(username, request):
        if request['action'] == 'list':
            return {'status': 'ok', 'images': [{'message_id': 'old', 'image_count': 1}], 'has_more': False}
        return {'image': original}
    monkeypatch.setattr(module, 'request_from_phone', phone)
    asyncio.run(tools.list_images({}))
    result = asyncio.run(tools.resend_image({'message_id': 'old'}))
    assert result['status'] == 'unavailable'
    assert not result.get('staged') and tools.repeated == []


def test_transfer_authenticates_socket_and_account_and_cleans_up(monkeypatch):
    socket, impostor = object(), object()
    async def broadcast(username, request):
        response = {'request_id':request['request_id'], 'status':'ok', 'data':image_data()}
        assert not transfer.receive_original('bob', response, socket)
        assert not transfer.receive_original('alice', response, impostor)
        assert not transfer.receive_original('alice', {**response,'data':'invalid!'}, socket)
        assert transfer.receive_original('alice', response, socket)
    manager = types.SimpleNamespace(active_connections={'alice':{socket}},
        get_connection_count=lambda _: 1, broadcast_to_user=broadcast)
    monkeypatch.setitem(sys.modules, PACKAGE + '.websocket', types.SimpleNamespace(manager=manager))
    result = asyncio.run(transfer.request_from_phone('alice', {'action':'read'}))
    assert result['image'].startswith('data:image/png;base64,')
    assert not transfer._pending


def test_missing_files_finish_promptly_and_timeout_cleans_up(monkeypatch):
    socket = object()
    async def broadcast(username, request):
        transfer.receive_original(username, {'request_id':request['request_id'],'status':'unavailable'}, socket)
    manager = types.SimpleNamespace(active_connections={'alice':{socket}},
        get_connection_count=lambda _: 1, broadcast_to_user=broadcast)
    monkeypatch.setitem(sys.modules, PACKAGE + '.websocket', types.SimpleNamespace(manager=manager))
    assert asyncio.run(transfer.request_from_phone('alice', {'action':'read'})) is None
    async def silent(*args):
        pass
    manager.broadcast_to_user = silent
    assert asyncio.run(transfer.request_from_phone('alice', {'action':'read'}, timeout=.01)) is None
    assert not transfer._pending


def test_catalog_can_move_past_first_page_and_empty_result(tools, monkeypatch):
    async def phone(username, request):
        return {'status':'ok', 'images':[], 'has_more':False}
    monkeypatch.setattr(module, 'request_from_phone', phone)
    assert asyncio.run(tools.list_images({'offset':100}))['next_offset'] is None


def test_surrounding_context_disambiguates_images_without_exposing_other_accounts(tools, monkeypatch):
    with sqlite3.connect(tools.db_path) as conn:
        conn.execute("UPDATE messages SET timestamp=100 WHERE id='old'")
        conn.execute("UPDATE messages SET timestamp=200 WHERE id='recent'")
        for mid, stamp, text, conv in [('menu-before',99,'这是餐厅菜单，稍后问你价格','ours'),
                ('menu-after',101,'菜单里有好多菜','ours'),
                ('cat-before',199,'换个话题，这是猫咪照片','ours'),
                ('foreign-neighbor',100,'不应暴露的另一账号文字','other')]:
            conn.execute('INSERT INTO messages VALUES(?,?,?,?,?,?,?,?)', (mid,mid,conv,'user',text,stamp,0,None))
    async def phone(username, request):
        return {'status':'ok', 'images':[{'message_id':'recent','image_count':1},
            {'message_id':'old','image_count':1}], 'has_more':False}
    monkeypatch.setattr(module, 'request_from_phone', phone)
    result = asyncio.run(tools.list_images({}))
    old = next(r for r in result['images'] if r['message_id']=='old')
    assert old['surrounding_messages']['before'][-1]['text'] == '这是餐厅菜单，稍后问你价格'
    assert old['surrounding_messages']['after'][0]['text'] == '菜单里有好多菜'
    assert '不应暴露' not in str(result)
