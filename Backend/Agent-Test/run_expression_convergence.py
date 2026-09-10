"""Versioned real-route reruns with immutable user inputs and transparent omissions."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import time

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / 'docs/testing/character-preference-intimacy-20260910'
OUT = ROOT / 'docs/testing/expression-convergence-20260910'
RUNTIME = ['Backend/chat_modules/' + name for name in
           ('Prompts.py', 'reply_expression_skill.py', 'autonomous_prompt_skills.py', 'agent_expression_review.py',
            'autonomous_behavior_policy.py', 'autonomous_normal.py', 'harness_runtime.py', 'harness_pool.py')]
CHARACTERS = ('pinkie_pie', 'rainbow_dash', 'twilight_sparkle', 'fluttershy')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('round')
    parser.add_argument('--characters', nargs='+', choices=CHARACTERS, default=CHARACTERS)
    parser.add_argument('--output-root', type=Path, default=OUT)
    parser.add_argument('--runtime-root', type=Path, default=ROOT)
    args = parser.parse_args()
    if not args.round.replace('-', '').isalnum():
        raise ValueError('Round name must be alphanumeric')
    directory = args.output_root.resolve() / args.round
    directory.mkdir(parents=True, exist_ok=False)
    for name in ('cases.json', 'profiles.json'):
        shutil.copyfile(BASELINE / name, directory / name)
    inputs = {name: sha(directory / name) for name in ('cases.json', 'profiles.json')}
    snapshot_hashes = {name: sha(args.runtime_root / name) for name in RUNTIME}
    overlay = directory / 'runtime.tar'
    with tarfile.open(overlay, 'w') as archive:
        for name in RUNTIME:
            archive.add(args.runtime_root / name, arcname=name)
    cases = json.loads((directory / 'cases.json').read_text(encoding='utf-8'))
    cells, omitted = [], []
    for character in args.characters:
        for scenario, label, text in cases:
            cell = {'character_id': character, 'scenario': scenario, 'label': label, 'input': text}
            if scenario == 'partner_deep_direct':
                omitted.append({**cell, 'status': 'not_generated_explicit_content_boundary',
                                'reason': '用户允许涉及露骨内容时停在该项；原始输入及语言档位保留，不改写后冒充同项测试。'})
            else:
                cells.append(cell)
    stages = {row[0]: ('familiar' if row[0].startswith('friend_') else
                      'flirting' if row[0].startswith('flirting_') else 'intimate_partner') for row in cases}
    write(directory / 'manifest.json', {'source_revision': subprocess.check_output(
        ['git', 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip(), 'inputs_sha256': inputs,
        'runtime_sha256': snapshot_hashes, 'requested_cells': len(args.characters)*len(cases),
        'run_cells': len(cells), 'omitted': omitted})
    started = time.time()

    def run(cell):
        cell_dir = directory / 'cells' / (cell['character_id']+'_'+cell['scenario'])
        cell_dir.mkdir(parents=True)
        style = cell['scenario'].split('_')[-1]
        env = {k: v for k, v in os.environ.items() if not k.startswith('PONYCHAT_STYLE_')}
        env.update(PYTHONPATH=str(ROOT / 'scripts/ops'), PYTHONUTF8='1',
            PONYCHAT_COVERAGE_OVERLAY=str(overlay), PONYCHAT_STYLE_PROFILES=str(directory / 'profiles.json'),
            PONYCHAT_STYLE_CASES=str(directory / 'cases.json'), PONYCHAT_STYLE_CHARACTERS=cell['character_id'],
            PONYCHAT_STYLE_SCENARIO=cell['scenario'], PONYCHAT_STYLE_PROGRESS=str(cell_dir / 'progress.json'),
            PONYCHAT_STYLE_LANGUAGE_BY_CHARACTER=json.dumps({cell['character_id']: style}),
            PONYCHAT_STYLE_RELATIONSHIP_STAGES=json.dumps(stages), PONYCHAT_SMOKE_TIMEOUT_SECONDS='300')
        with (cell_dir / 'stdout.log').open('wb') as stdout, (cell_dir / 'stderr.log').open('wb') as stderr:
            process = subprocess.Popen([sys.executable, str(ROOT / 'Backend/Agent-Test/run_style_matrix_probe.py'),
                str(cell_dir / 'raw.json'), '--source', str(ROOT)], cwd=ROOT, env=env,
                stdout=stdout, stderr=stderr, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            began = time.time()
            try:
                code = process.wait(timeout=360)
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
        raw_path = cell_dir / 'raw.json'
        raw = json.loads(raw_path.read_text(encoding='utf-8')) if raw_path.exists() else {}
        result = (raw.get('cases') or [{}])[0]
        row = {**cell, 'style': style, 'exit_code': code, 'pid': process.pid,
               'started_at': began, 'ended_at': time.time(), 'case': result}
        if result and result['input'] != cell['input']:
            raise AssertionError('User input changed')
        print(json.dumps({'cell': cell_dir.name, 'passed': result.get('passed', False)}, ensure_ascii=False), flush=True)
        return row

    rows = []
    with ThreadPoolExecutor(max_workers=len(cells)) as pool:
        for future in as_completed([pool.submit(run, cell) for cell in cells]):
            rows.append(future.result())
            write(directory / 'progress.json', rows)
    events = sorted([(r['started_at'], 1) for r in rows] + [(r['ended_at'], -1) for r in rows])
    active = peak = 0
    for _, delta in events:
        active += delta
        peak = max(peak, active)
    assert all(sha(BASELINE / name) == value == sha(directory / name) for name, value in inputs.items())
    result = {'transport_passed': all(r['exit_code'] == 0 and r['case'].get('passed') for r in rows),
              'semantic_passed': None, 'elapsed_seconds': round(time.time()-started, 2),
              'peak_processes': peak, 'rows': rows, 'omitted': omitted,
              'inputs_sha256': inputs, 'runtime_sha256': snapshot_hashes}
    write(directory / 'results.json', result)
    print(json.dumps({k: v for k, v in result.items() if k not in ('rows', 'omitted')}, ensure_ascii=False), flush=True)
    return 0 if result['transport_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
