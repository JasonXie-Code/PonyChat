"""Exercise actual project image search/read tools with safe Pinkie Pie images."""
import asyncio
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from Backend.chat_modules.autonomous_web_search import SearxngSearch
from Backend.chat_modules.autonomous_web_images import WebImageTools


async def main():
    output = ROOT / 'var/qa/pinkie-images'
    output.mkdir(parents=True, exist_ok=True)
    tools = WebImageTools(SearxngSearch(), username='image-preview')
    result = await tools.search({'query': '碧琪 单独 可爱',
        'derpibooru_tags': 'pinkie pie, solo', 'rating': 'safe'})
    report = []
    for row in result['results']:
        started = time.monotonic()
        await tools.read({'image_ref': row['image_ref']})
        item = tools.downloaded.get(row['image_ref'])
        if not item:
            continue
        path = output / (row['source_url'].rsplit('/', 1)[-1] + '.jpg')
        path.write_bytes(item['data'])
        report.append({'path': str(path), 'source': row['source_url'],
            'score': row.get('score'), 'rating': row.get('rating'),
            'width': item['width'], 'height': item['height'],
            'seconds': round(time.monotonic() - started, 2)})
        if len(report) == 3:
            break
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if len(report) != 3:
        raise RuntimeError('Fewer than three successful tool downloads')


if __name__ == '__main__':
    asyncio.run(main())
