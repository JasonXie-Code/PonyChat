"""Compare live-only reads and same-source archive recovery, with no app DB."""
import asyncio
import importlib
import json
import time

from replay_expression_focus import ROOT, load_modules


async def main():
    load_modules()
    web = importlib.import_module('expression_focus_replay.autonomous_web_search')
    rows = []
    for title in ('辉麦与金梨果酱', '并蒂连枝', '暮光闪闪'):
        url = 'https://mlp.huijiwiki.com/wiki/' + title
        for mode in ('live_only', 'with_recovery'):
            tool = web.SearxngSearch(**({'snapshot_dir': None} if mode == 'live_only' else {}))
            start = time.monotonic()
            result = await tool.search({'url': url, 'source': 'mlp_wiki'})
            rows.append({'title': title, 'mode': mode, 'seconds': round(time.monotonic() - start, 3),
                'status': result['status'], 'provider': result['provider'],
                'online_status': result.get('online_status'), 'http_status': result.get('http_status'),
                'freshness': result.get('freshness'), 'content_chars': len(result.get('content', '')),
                'content_truncated': result.get('content_truncated'),
                'snapshot_sha256': result.get('snapshot_sha256'), 'url': url})
            print(json.dumps(rows[-1], ensure_ascii=False), flush=True)
    report = {'scope': 'Local real network observations, 3 articles per mode, not a general production success-rate estimate.',
              'cases': rows}
    (ROOT / 'docs/testing/wiki-recovery-network-20260910.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    asyncio.run(main())
