"""Bounded read-only latency and external stack sampling (no frame locals)."""
import argparse
import datetime
import json
import pathlib
import subprocess
import threading
import time
import urllib.request

import psutil


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pid', type=int, required=True)
    parser.add_argument('--py-spy', required=True)
    parser.add_argument('--seconds', type=float, default=120)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 600:
        parser.error('seconds must be between 1 and 600')
    process = psutil.Process(args.pid)
    started = time.monotonic()
    stop = threading.Event()
    rows = []
    lock = threading.Lock()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def add(kind, **data):
        with lock:
            rows.append(dict(kind=kind, at=datetime.datetime.now().isoformat(),
                             elapsed=time.monotonic() - started, **data))

    def probe():
        while not stop.is_set():
            before = time.monotonic()
            try:
                with opener.open('http://127.0.0.1:5000/api/ping', timeout=6) as response:
                    status = response.status
                    response.read()
                add('probe', seconds=time.monotonic() - before, status=status)
            except Exception as exc:
                add('probe', seconds=time.monotonic() - before, error=type(exc).__name__)
            stop.wait(.5)

    worker = threading.Thread(target=probe, daemon=True)
    worker.start()
    process.cpu_percent()
    psutil.cpu_percent()
    try:
        while time.monotonic() - started < args.seconds:
            before = time.monotonic()
            result = subprocess.run([args.py_spy, 'dump', '--pid', str(args.pid),
                                     '--json', '--nonblocking'], capture_output=True,
                                    text=True, timeout=8)
            if result.returncode == 0:
                threads = json.loads(result.stdout)
                selected = []
                for thread in threads:
                    if thread['thread_name'] == 'MainThread' or thread['active'] or thread['owns_gil']:
                        selected.append({key: thread[key] for key in
                                         ('thread_id', 'thread_name', 'active', 'owns_gil')} | {
                            'frames': [{key: frame[key] for key in ('name', 'filename', 'line')}
                                       for frame in thread['frames'][:16]]})
                add('sample', duration=time.monotonic() - before, threads=selected,
                    process_cpu=process.cpu_percent(), host_cpu=psutil.cpu_percent())
            else:
                add('sample_error', returncode=result.returncode)
            stop.wait(.25)
    finally:
        stop.set()
        worker.join(timeout=7)
        pathlib.Path(args.output).write_text(json.dumps(rows, ensure_ascii=False, indent=2),
                                            encoding='utf-8')
    probes = [row for row in rows if row['kind'] == 'probe']
    print(json.dumps({'samples': len(rows) - len(probes), 'probes': len(probes),
                      'max_seconds': max((row['seconds'] for row in probes), default=0),
                      'errors': sum('error' in row for row in probes)}))


if __name__ == '__main__':
    main()
