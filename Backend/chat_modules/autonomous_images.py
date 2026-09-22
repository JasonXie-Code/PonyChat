"""Resolve current public sticker file routes for the Agent's image tool."""
import base64
from io import BytesIO
import re

import aiosqlite

from .Prompts import AUTONOMOUS_IMAGES_TEXT


CURRENT_IMAGE_GUIDANCE = AUTONOMOUS_IMAGES_TEXT['current_image_guidance']


async def resolve_image_inputs(urls, db_path):
    result = []
    for url in urls[:4]:
        match = re.fullmatch(r"/api/(admin/assets|assets/stickers)/([A-Za-z0-9_-]+)/file", url)
        if not match:
            chat_image = re.fullmatch(r"/chat_images/([A-Za-z0-9_.-]+)", url)
            if chat_image:
                try:
                    from ..chat_image_transfer import load_chat_image_transfer
                    row = load_chat_image_transfer(chat_image.group(1))
                except (ImportError, ValueError):
                    row = None
                if row is None:
                    async with aiosqlite.connect(db_path) as conn:
                        async with conn.execute("SELECT data,mime_type FROM chat_images WHERE filename=?",
                                                (chat_image.group(1),)) as cursor:
                            row = await cursor.fetchone()
                if row and row[0]:
                    mime = row[1] if str(row[1]).startswith('image/') else 'image/jpeg'
                    result.append('data:' + mime + ';base64,' + base64.b64encode(bytes(row[0])).decode('ascii'))
                continue
            result.append(url)
            continue
        route, asset_id = match.groups()
        async with aiosqlite.connect(db_path) as conn:
            if route == "admin/assets":
                async with conn.execute("SELECT file_data,mime_type FROM media_assets WHERE id=?", (asset_id,)) as cursor:
                    row = await cursor.fetchone()
            else:
                async with conn.execute("SELECT file_data,mime_type,source_asset_id FROM user_sticker_assets WHERE id=?", (asset_id,)) as cursor:
                    row = await cursor.fetchone()
                if row and not row[0] and row[2]:
                    async with conn.execute("SELECT file_data,mime_type FROM media_assets WHERE id=?", (row[2],)) as cursor:
                        row = await cursor.fetchone()
        if row and row[0]:
            mime = row[1] if str(row[1]).startswith("image/") else "image/png"
            result.append("data:" + mime + ";base64," + base64.b64encode(bytes(row[0])).decode("ascii"))
    return result


async def resolve_harness_image_blocks(urls, db_path):
    """Materialize images for the one Harness Agent without visual inference."""
    from PIL import Image

    blocks = []
    for index, value in enumerate(await resolve_image_inputs(urls, db_path), 1):
        if not isinstance(value, str) or not value.startswith('data:image/'):
            continue
        try:
            header, encoded = value.split(',', 1)
            raw = base64.b64decode(encoded, validate=True)
            image = Image.open(BytesIO(raw))
            image.load()
            if max(image.size) > 2560:
                image.thumbnail((2560, 2560))
            if image.mode != 'RGB':
                background = Image.new('RGB', image.size, 'white')
                if image.mode in ('RGBA', 'LA') or (image.mode == 'P' and 'transparency' in image.info):
                    alpha = image.convert('RGBA')
                    background.paste(alpha, mask=alpha.getchannel('A'))
                    image = background
                else:
                    image = image.convert('RGB')
            output = BytesIO()
            image.save(output, format='JPEG', quality=75, optimize=True)
            encoded = base64.b64encode(output.getvalue()).decode('ascii')
            media_type = 'image/jpeg'
        except (ValueError, OSError, base64.binascii.Error):
            continue
        blocks.append({'type': 'image', 'mimeType': media_type, 'data': encoded})
    return blocks
