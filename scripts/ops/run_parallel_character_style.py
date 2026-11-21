"""Run isolated real-route cells with up to twelve workers, retaining every result."""
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'docs/testing/character-led-parallel-20260910'


def main():
    global OUT
    if len(sys.argv) > 1:
        OUT = Path(sys.argv[1]).resolve()
    cases = json.loads((OUT / 'cases.json').read_text(encoding='utf-8'))
    profiles = json.loads((OUT / 'profiles.json').read_text(encoding='utf-8'))
    cells = [(s[0], c['id']) for s in cases for c in profiles]
    assert cells and len(set(cells)) == len(cells)
    prompt = ROOT / 'Backend/chat_modules/autonomous_direct.py'
    digest = hashlib.sha256(prompt.read_bytes()).hexdigest()
    (OUT / 'candidate.py').write_bytes(prompt.read_bytes())
    started = time.time()

    def run(cell):
        scenario, character = cell
        directory = OUT / 'cells' / (scenario + '_' + character)
        directory.mkdir(parents=True, exist_ok=False)
        env = {k: v for k, v in os.environ.items()
               if not k.startswith('PONYCHAT_STYLE_') and k != 'PONYCHAT_COVERAGE_OVERLAY'}
        env.update(PYTHONPATH=str(ROOT / 'scripts/ops'),
                   PONYCHAT_STYLE_PROFILES=str(OUT / 'profiles.json'),
                   PONYCHAT_STYLE_CASES=str(OUT / 'cases.json'),
                   PONYCHAT_STYLE_CHARACTERS=character,
                   PONYCHAT_STYLE_SCENARIO=scenario,
                   PONYCHAT_STYLE_PROGRESS=str(directory / 'progress.json'))
        begin = time.time()
        with (directory / 'stdout.log').open('wb') as stdout, (directory / 'stderr.log').open('wb') as stderr:
            process = subprocess.Popen([sys.executable, str(ROOT / 'Backend/Agent-Test/run_style_matrix_probe.py'),
                                        str(directory / 'raw.json'), '--source', str(ROOT)],
                                       cwd=ROOT, env=env, stdout=stdout, stderr=stderr,
                                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            try:
                code = process.wait(timeout=600)
            except subprocess.TimeoutExpired:
                import psutil
                parent = psutil.Process(process.pid)
                for child in reversed(parent.children(recursive=True)):
                    try:
                        child.terminate()
                    except psutil.NoSuchProcess:
                        pass
                process.kill()
                code = process.wait()
        row = {'scenario': scenario, 'character_id': character, 'exit_code': code,
               'started_at': begin, 'ended_at': time.time(), 'pid': process.pid}
        if (directory / 'raw.json').exists():
            result = json.loads((directory / 'raw.json').read_text(encoding='utf-8'))
            row['result'] = result
        print(json.dumps({'cell': directory.name, 'exit_code': code,
                          'seconds': round(row['ended_at'] - begin, 2)}, ensure_ascii=False), flush=True)
        return row

    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        rows = list(pool.map(run, cells))
    assert hashlib.sha256(prompt.read_bytes()).hexdigest() == digest, 'Prompt changed during sampling'
    events = sorted([(r['started_at'], 1) for r in rows] + [(r['ended_at'], -1) for r in rows])
    active = peak = 0
    for _, delta in events:
        active += delta
        peak = max(peak, active)
    result = {'passed': all(r['exit_code'] == 0 and r.get('result', {}).get('passed') for r in rows),
              'wall_seconds': round(time.time() - started, 2), 'max_overlapping_workers': peak,
              'candidate_sha256': digest, 'rows': rows,
              'note': 'Up to twelve concurrent isolated processes; provider scheduling is outside this measurement.'}
    (OUT / 'parallel.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k != 'rows'}), flush=True)
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
