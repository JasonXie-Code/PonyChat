"""Bounded synthetic Agent load in the live backend cgroup, with an outside watchdog.

Run on Server-USA as root. Does not access user settings, histories or databases.
Only the synthetic worker joins the service cgroup; the watchdog stays outside.
"""
import argparse
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import types
import urllib.request

ROOT = Path('/opt/ponychat')
CODE_ROOT = Path(os.environ.get('PONYCHAT_HARNESS_CODE_ROOT', str(ROOT)))
GROUP = Path('/sys/fs/cgroup/system.slice/ponychat-backend.service')


def read_pairs(path):
    return {key: int(value) for key, value in (line.split() for line in path.read_text().splitlines())}


def health():
    start = time.monotonic()
    try:
        with urllib.request.urlopen('http://127.0.0.1:5000/api/health', timeout=2) as response:
            ok = json.load(response).get('status') == 'running'
        return {'ok': ok, 'seconds': round(time.monotonic()-start, 3)}
    except Exception as exc:
        return {'ok': False, 'seconds': round(time.monotonic()-start, 3), 'error': type(exc).__name__}


async def worker(count, output, rounds=1):
    # All subsequently spawned SDK processes inherit this service memory budget.
    (GROUP/'cgroup.procs').write_text(str(os.getpid()))
    package = types.ModuleType('capacity_runtime')
    package.__path__ = [str(CODE_ROOT/'Backend/chat_modules')]
    sys.modules['capacity_runtime'] = package
    spec = importlib.util.spec_from_file_location('capacity_runtime.harness_runtime', CODE_ROOT/'Backend/chat_modules/harness_runtime.py')
    runtime = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runtime)
    from dotenv import load_dotenv
    load_dotenv(ROOT/'.env')
    config = {'api_key': os.environ.get('PONYCHAT_DEEPSEEK_API_KEY'), 'endpoint': 'https://api.deepseek.com'}
    if not config['api_key']:
        raise RuntimeError('Model credential unavailable')
    os.environ['PONYCHAT_HARNESS_CONCURRENCY'] = str(count)
    results = []

    async def one(index, iteration):
        start = time.monotonic()
        async def read_recent():
            return {'synthetic': True, 'history': [
                {'user': f'读到天文学第{i}章了，我喜欢无糖茶。', 'assistant': '我陪你一起读。'} for i in range(50)]}
        async def remember():
            return {'synthetic': True, 'staged_in_memory_only': True}
        try:
            result = await runtime.run_harness_turn(
                '我有些累。先调用read_recent读取合成历史，再调用remember暂存合成偏好，最后说两句关心的话。',
                config, {'read_recent': read_recent, 'remember': remember},
                system_prompt='合成容量测试，双方为成年人。按顺序使用指定工具，再简短回答。',
                timeout_seconds=75, max_tokens=1024, max_tool_calls=4)
            entry = {'index': index, 'seconds': round(time.monotonic()-start, 2),
                     'finish': result['finish_reason'], 'model_calls': result['llm_api_calls'],
                     'tool_calls': result['tool_call_count'], 'runtime_reused': result.get('runtime_reused', False)}
            entry['passed'] = entry['finish'] == 'completed' and entry['tool_calls'] >= 2
        except Exception as exc:
            entry = {'index': index, 'seconds': round(time.monotonic()-start, 2),
                     'passed': False, 'error': type(exc).__name__}
        results.append(entry)
        entry['round'] = iteration
        output.write_text(json.dumps(results))
    for iteration in range(1, rounds+1):
        await asyncio.gather(*(one(index, iteration) for index in range(count)))


def agents(worker_pid):
    probe = total = 0
    for item in Path('/proc').iterdir():
        if not item.name.isdigit():
            continue
        try:
            if b'deepseek-harness-sdk-runtime' not in (item/'cmdline').read_bytes():
                continue
            parent = next(line.split()[1] for line in (item/'status').read_text().splitlines() if line.startswith('PPid:'))
            total += 1
            probe += parent == str(worker_pid)
        except (OSError, StopIteration):
            continue
    return probe, total


def controller(count, report_path, quiet_start=False, rounds=1):
    if str(GROUP) in str(Path('/sys/fs/cgroup')/Path('/proc/self/cgroup').read_text().split('0::')[-1].strip().lstrip('/')):
        raise RuntimeError('Watchdog must run outside the backend service cgroup')
    results_path = report_path.with_suffix('.results.json')
    if results_path.exists() or report_path.exists():
        raise RuntimeError('Use a fresh report path')
    if quiet_start:
        deadline = time.monotonic()+90
        while agents(-1)[1]:
            if time.monotonic() >= deadline:
                raise RuntimeError('No idle Agent window within 90 seconds; no load launched')
            print('WAITING for existing Agent tasks to finish', flush=True)
            time.sleep(5)
    before = read_pairs(GROUP/'memory.events')
    cpu_before = read_pairs(GROUP/'cpu.stat')['usage_usec']
    start = time.monotonic()
    report = {'concurrency': count, 'rounds': rounds, 'scope': 'synthetic real-model tasks sharing live backend memory limits; extra worker overhead and live traffic are included',
              'started': time.strftime('%Y-%m-%d %H:%M:%S'), 'initial_health': health(),
              'memory_high': int((GROUP/'memory.high').read_text()), 'memory_max': int((GROUP/'memory.max').read_text()),
              'samples': [], 'abort_reason': None}
    if not report['initial_health']['ok']:
        raise RuntimeError('Service unhealthy before probe')
    proc = subprocess.Popen([sys.executable, __file__, '--worker', '--count', str(count), '--rounds', str(rounds), '--report', str(results_path)],
                            start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    report['worker_pid'] = proc.pid
    last_time = start
    last_cpu = list(map(int, Path('/proc/stat').read_text().splitlines()[0].split()[1:9]))
    severe = failed_health = 0
    try:
        while proc.poll() is None:
            time.sleep(2)
            now = time.monotonic()
            cpu = list(map(int, Path('/proc/stat').read_text().splitlines()[0].split()[1:9]))
            delta = [b-a for a, b in zip(last_cpu, cpu)]
            total = max(1, sum(delta))
            events = read_pairs(GROUP/'memory.events')
            pressure = (GROUP/'memory.pressure').read_text().splitlines()[0]
            avg10 = float(pressure.split('avg10=')[1].split()[0])
            probe_count, total_count = agents(proc.pid)
            meminfo = {k: int(v.split()[0]) for k, v in (line.split(':', 1) for line in Path('/proc/meminfo').read_text().splitlines())}
            row = {'seconds': round(now-start, 1), 'cpu_percent': round(100*(sum(delta)-delta[3]-delta[4])/total, 1),
                   'io_wait_percent': round(100*delta[4]/total, 1),
                   'memory_mib': round(int((GROUP/'memory.current').read_text())/1048576, 1),
                   'available_mib': round(meminfo['MemAvailable']/1024, 1),
                   'swap_mib': round(int((GROUP/'memory.swap.current').read_text())/1048576, 1),
                   'memory_high_delta': events['high']-before['high'], 'memory_pressure_avg10': avg10,
                   'probe_agents': probe_count, 'total_agents': total_count}
            if len(report['samples']) % 4 == 0:
                row['health'] = health()
                failed_health = 0 if row['health']['ok'] else failed_health+1
            report['samples'].append(row)
            print(json.dumps(row), flush=True)
            report_path.write_text(json.dumps(report, indent=2))
            severe = severe+1 if avg10 >= 60 else 0
            if events['oom_kill'] > before['oom_kill']:
                report['abort_reason'] = 'cgroup OOM kill'
            elif quiet_start and total_count > probe_count and proc.poll() is None:
                report['abort_reason'] = 'live Agent traffic overlapped; controlled sample invalid'
            elif severe >= 4:
                report['abort_reason'] = 'memory pressure >=60% for four consecutive samples'
            elif failed_health >= 3:
                report['abort_reason'] = 'three failed health checks'
            elif now-start > 100:
                report['abort_reason'] = 'watchdog deadline'
            if report['abort_reason']:
                break
            last_cpu, last_time = cpu, now
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=5)
        # SDK runtimes may survive SIGTERM after their Python parent exits.
        # The dedicated probe group must be reaped independently of that parent.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        report['worker_exit_code'] = proc.returncode
        report['results'] = json.loads(results_path.read_text()) if results_path.exists() else []
        report['elapsed_seconds'] = round(time.monotonic()-start, 2)
        report['backend_cpu_seconds'] = round((read_pairs(GROUP/'cpu.stat')['usage_usec']-cpu_before)/1000000, 2)
        report['final_health'] = health()
        report_path.write_text(json.dumps(report, indent=2))
        print('RESULT', json.dumps({k: v for k, v in report.items() if k != 'samples'}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--count', type=int, choices=range(1, 11), default=8)
    parser.add_argument('--worker', action='store_true')
    parser.add_argument('--quiet-start', action='store_true')
    parser.add_argument('--rounds', type=int, choices=range(1, 4), default=1)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    if args.worker:
        asyncio.run(worker(args.count, args.report, args.rounds))
    else:
        controller(args.count, args.report, args.quiet_start, args.rounds)
