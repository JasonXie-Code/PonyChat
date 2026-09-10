import asyncio
import base64
import importlib
from io import BytesIO
import sqlite3

from PIL import Image

from test_autonomous_normal import normal

images = importlib.import_module(normal.__package__ + ".autonomous_images")


def test_resolve_public_sticker_routes_and_keep_direct_images(tmp_path):
    path = tmp_path / "images.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE media_assets(id TEXT,file_data BLOB,mime_type TEXT)")
        conn.execute("CREATE TABLE user_sticker_assets(id TEXT,file_data BLOB,mime_type TEXT,source_asset_id TEXT)")
        conn.execute("INSERT INTO media_assets VALUES('p',?, 'image/png')", (b'png-test',))
        conn.execute("INSERT INTO user_sticker_assets VALUES('u',NULL,NULL,'p')")
    resolved = asyncio.run(images.resolve_image_inputs([
        '/api/admin/assets/p/file', '/api/assets/stickers/u/file',
        'data:image/png;base64,direct', '/api/admin/assets/missing/file'], str(path)))
    assert resolved == ['data:image/png;base64,cG5nLXRlc3Q=', 'data:image/png;base64,cG5nLXRlc3Q=',
                        'data:image/png;base64,direct']


def test_user_sticker_source_asset_becomes_native_pixels_not_labels(tmp_path):
    output = BytesIO()
    Image.new('RGB', (8, 6), (255, 0, 0)).save(output, format='PNG')
    path = tmp_path / 'sticker.db'
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE media_assets(id TEXT,file_data BLOB,mime_type TEXT)')
        conn.execute('CREATE TABLE user_sticker_assets(id TEXT,file_data BLOB,mime_type TEXT,source_asset_id TEXT)')
        conn.execute("INSERT INTO media_assets VALUES('source',?, 'image/png')", (output.getvalue(),))
        conn.execute("INSERT INTO user_sticker_assets VALUES('blue-crying-label',NULL,NULL,'source')")
    blocks = asyncio.run(images.resolve_harness_image_blocks(
        ['/api/assets/stickers/blue-crying-label/file'], str(path)))
    assert len(blocks) == 1 and blocks[0]['type'] == 'image'
    actual = Image.open(BytesIO(base64.b64decode(blocks[0]['data'])))
    red, green, blue = actual.getpixel((0, 0))
    assert actual.size == (8, 6) and red > 240 and green < 10 and blue < 10


def test_resolve_native_harness_image_blocks_without_visual_model(tmp_path):
    output = BytesIO()
    Image.new('RGB', (4, 3), 'blue').save(output, format='PNG')
    data_url = 'data:image/png;base64,' + base64.b64encode(output.getvalue()).decode()
    path = tmp_path / 'images.db'
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE media_assets(id TEXT,file_data BLOB,mime_type TEXT)")
        conn.execute("CREATE TABLE user_sticker_assets(id TEXT,file_data BLOB,mime_type TEXT,source_asset_id TEXT)")

    blocks = asyncio.run(images.resolve_harness_image_blocks([data_url], str(path)))
    assert len(blocks) == 1
    assert blocks[0]['type'] == 'image'
    assert blocks[0]['mimeType'] == 'image/jpeg'
    assert base64.b64decode(blocks[0]['data']).startswith(b'\xff\xd8\xff')
