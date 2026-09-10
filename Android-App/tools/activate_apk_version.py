"""Activate a published APK version, preserving deployed backend source and rollback."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
import urllib.request


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipt", type=Path)
    args = parser.parse_args()
    report = json.loads(args.receipt.read_text(encoding="utf-8"))
    version, code, digest = report["version_name"], report["version_code"], report["sha256"]
    assert re.fullmatch(r"\d+\.\d+\.\d+", version)
    assert isinstance(code, int) and code > 0
    assert re.fullmatch(r"[0-9a-f]{64}", digest)
    assert report["published"] and report["public_sha256"] == digest
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "ServerKeys"))
    from ssh_lib import load_server, ssh_bash_s

    script = f'''set -eu
/opt/ponychat/.venv/bin/python - <<'PY'
import hashlib, json, re, shutil, subprocess, time, urllib.request
from pathlib import Path
version, code, digest = {version!r}, {code!r}, {digest!r}
root = Path('/opt/ponychat')
apk = root / f'PonyChat-Website/Main/deploy/releases/PonyChat-v{{version}}-{{code}}-release.apk'
assert hashlib.sha256(apk.read_bytes()).hexdigest() == digest
env = root / '.env'
backup = Path('/var/backups/ponychat-apk-version') / f'{{version}}-{{code}}-{{time.time_ns()}}'
backup.mkdir(parents=True, mode=0o700, exist_ok=False)
shutil.copy2(env, backup / 'environment.before')
service = 'ponychat-backend.service'
subprocess.run(['systemctl', 'is-active', '--quiet', service], check=True)
values = {{'PONYCHAT_APP_VERSION_NAME': version, 'PONYCHAT_APP_VERSION_CODE': str(code),
          'PONYCHAT_APP_APK_PATH': str(apk)}}
lines = env.read_text().splitlines()
for key, value in values.items():
    lines = [line for line in lines if not re.match(r'^\\s*(?:export\\s+)?' + key + r'\\s*=', line)]
    lines.append(key + '=' + value)
try:
    env.write_text('\\n'.join(lines) + '\\n')
    subprocess.run(['systemctl', 'restart', service], check=True)
    for attempt in range(45):
        try:
            with urllib.request.urlopen('http://127.0.0.1:5000/api/app/version', timeout=3) as response:
                current = json.load(response)
            if current['version_name'] == version and current['version_code'] == code:
                break
        except Exception:
            pass
        time.sleep(2)
    else:
        raise RuntimeError('New version was not served')
    subprocess.run(['systemctl', 'is-active', '--quiet', service], check=True)
except BaseException:
    shutil.copy2(backup / 'environment.before', env)
    subprocess.run(['systemctl', 'restart', service], check=True)
    raise
print(json.dumps({{'version': current, 'backup': str(backup), 'backend_source_changed': False}}))
PY
'''
    if ssh_bash_s(load_server("usa"), script) != 0:
        raise RuntimeError("Version activation failed; inspect the rollback result")
    with urllib.request.urlopen("https://www.ponychat.org/api/app/version", timeout=30) as response:
        current = json.load(response)
    assert current["version_name"] == version and current["version_code"] == code
    report.update(version_activated=True, public_version=current, backend_restart=True)
    args.receipt.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"public_version": current, "backend_source_changed": False}))


if __name__ == "__main__":
    main()
