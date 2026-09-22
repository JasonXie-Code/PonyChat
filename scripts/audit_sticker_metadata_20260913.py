"""Export a read-only sticker snapshot and per-asset animation contact sheets."""
import hashlib
import io
import json
import sqlite3
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'var/sticker-audit-20260913'


def export():
    OUT.mkdir(exist_ok=True)
    if (OUT / 'before.json').exists():
        raise RuntimeError('Snapshot already exists; never overwrite the audit baseline.')
    (OUT / 'images').mkdir(exist_ok=True)
    conn = sqlite3.connect(f'file:{ROOT.as_posix()}/Backend/database/ponychat.db?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute('BEGIN')
    records = []
    for index, row in enumerate(conn.execute("SELECT * FROM media_assets WHERE category IN ('emoji','sticker') ORDER BY name,id"), 1):
        item = dict(row)
        raw = item.pop('file_data')
        item['sha256'] = hashlib.sha256(raw).hexdigest()
        item['index'] = index
        im = Image.open(io.BytesIO(raw))
        frames = getattr(im, 'n_frames', 1)
        chosen = sorted(set(round(i * (frames - 1) / 7) for i in range(8)))
        sheet = Image.new('RGB', (640 if frames > 1 else 480, 380 * ((len(chosen)+1)//2) if frames > 1 else 500), '#dedede')
        draw = ImageDraw.Draw(sheet)
        for n, frame in enumerate(chosen):
            im.seek(frame)
            tile = im.convert('RGBA')
            tile.thumbnail((310, 345) if frames > 1 else (470, 470))
            x, y = ((n % 2)*320, (n//2)*380) if frames > 1 else (0, 0)
            sheet.paste(tile, (x, y+25), tile)
            draw.text((x+5,y+5), f'{index:03d} frame {frame}/{frames}', fill='black')
        path = OUT / 'images' / f'{index:03d}.jpg'
        sheet.save(path, quality=90)
        item['preview'] = str(path)
        item['frames'] = frames
        records.append(item)
    conn.close()
    (OUT / 'before.json').write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
    for group in range(4):
        subset = [r for i,r in enumerate(records) if i % 4 == group]
        (OUT / f'batch-{group}.json').write_text(json.dumps(subset, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'count':len(records), 'out':str(OUT)}))


if __name__ == '__main__':
    export()
