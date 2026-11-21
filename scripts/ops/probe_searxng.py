"""Record actual deployed Agent-tool results, without opening the chat database."""
import argparse
import asyncio
import importlib
import json
from pathlib import Path
import sys
import time
import types


async def probe(source):
    package = types.ModuleType('searxng_probe_modules')
    package.__path__ = [str(source/'Backend/chat_modules')]
    sys.modules[package.__name__] = package
    module = importlib.import_module(package.__name__+'.autonomous_web_search')
    rows = []
    tool = module.SearxngSearch()
    for query in ('紫悦', 'Twilight Sparkle'):
        started = time.monotonic()
        result = await tool.search({'query': query})
        rows.append({'elapsed_seconds': round(time.monotonic()-started, 3), 'tool_result': result})
    return {'target': 'Server-USA', 'production_database_opened': False,
            'passed': all(row['tool_result']['results'] and row['tool_result']['status'] in ('success', 'partial') for row in rows),
            'queries': rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', default='/opt/ponychat')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    result = asyncio.run(probe(Path(args.source)))
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf8')
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
