"""Regenerate one explicitly named user's existing memory prose, preserving provenance."""
import argparse
import asyncio
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


async def rewrite_batch(character, username, rows, config):
    from Backend.chat_modules.Prompts import MEMORY_REWRITE_SYSTEM
    from Backend.chat_modules.harness_runtime import run_harness_turn
    from Backend.agent_memory.prose import validate_rewritten_prose
    payload = dict(character_name=character, user_name=username,
                   memories=[{k: row[k] for k in ('entry_id', 'content', 'category', 'occurred_at', 'period')} for row in rows])
    expected = {row['entry_id'] for row in rows}
    errors = []
    for attempt in range(3):
        response = await run_harness_turn(json.dumps(payload, ensure_ascii=False), config, {},
            system_prompt=MEMORY_REWRITE_SYSTEM, max_tokens=12000, max_tool_calls=0,
            force_no_tools=True, timeout_seconds=180)
        try:
            raw = response.get('final_response', '')
            if raw.startswith('```'):
                raw = raw.split('\n', 1)[1].rsplit('```', 1)[0]
            answer = json.loads(raw)['rewrites']
            result = {row['entry_id']: validate_rewritten_prose(row['content']) for row in answer}
            if len(answer) != len(expected) or set(result) != expected:
                raise ValueError('Output IDs must cover each input exactly once')
            return result
        except (ValueError, KeyError, TypeError) as exc:
            errors.append(type(exc).__name__ + ': ' + str(exc))
            payload['validation_feedback'] = errors[-1]
    raise RuntimeError('Rewrite validation failed: ' + errors[-1])


async def run(args):
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
    load_dotenv(ROOT / '.env.local-stack', override=True)
    from Backend.runtime_paths import resolve_database_path
    from Backend.model_manager import model_manager
    from Backend.agent_memory.rewrite import snapshot, apply, STRUCTURED
    from Backend.agent_memory.store import MemoryConflictError
    path = Path(resolve_database_path(str(ROOT / 'Backend')))
    config = model_manager.get_active_model()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        user = conn.execute('SELECT id,username FROM users WHERE username=?', (args.username,)).fetchone()
        if not user:
            raise ValueError('Exact username not found')
        characters = dict(conn.execute('SELECT id,name FROM characters WHERE user_id=?', (user[0],)))
        for (cid,) in conn.execute('SELECT character_id FROM agent_memory_state WHERE username=?', (args.username,)):
            if cid not in characters:
                row = conn.execute('SELECT name FROM characters WHERE id=?', (cid,)).fetchone()
                characters[cid] = row[0] if row else cid
    semaphore = asyncio.Semaphore(args.concurrency)
    results = []

    async def character(cid, name):
        async with semaphore:
            for attempt in range(3):
                plan = await asyncio.to_thread(snapshot, path, args.username, cid)
                rows = [row for row in plan['rows'] if row['category'] not in STRUCTURED]
                backup = output / f'{cid}-attempt{attempt}.json'
                backup.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8')
                rewritten = {}
                for start in range(0, len(rows), 4):
                    rewritten.update(await rewrite_batch(name, args.username, rows[start:start+4], config))
                (output / f'{cid}-rewrites{attempt}.json').write_text(
                    json.dumps(rewritten, ensure_ascii=False, indent=2), encoding='utf-8')
                if not args.apply:
                    result = dict(processed=len(rows), applied=False)
                else:
                    try:
                        result = await asyncio.to_thread(apply, path, plan, rewritten)
                    except MemoryConflictError:
                        if attempt == 2:
                            raise
                        continue
                report = dict(character_id=cid, character_name=name, **result)
                results.append(report)
                (output / 'report.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
                print(json.dumps(report, ensure_ascii=False), flush=True)
                return

    outcomes = await asyncio.gather(*(character(cid, name) for cid, name in characters.items()), return_exceptions=True)
    errors = [str(outcome) for outcome in outcomes if isinstance(outcome, BaseException)]
    if errors:
        raise RuntimeError(f'{len(errors)} character tasks failed: {errors}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--username', required=True)
    parser.add_argument('--output', required=True, type=Path, help='Private backup and model output directory')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--concurrency', type=int, choices=range(1, 5), default=3)
    asyncio.run(run(parser.parse_args()))
