"""Publish a signed versioned APK without deploying or restarting the backend."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import urllib.request

APP = Path(__file__).resolve().parents[1]
ROOT = APP.parent
TOOLS = ROOT.parent / "Tools"
RELEASE_DIR = "/opt/ponychat/PonyChat-Website/Main/deploy/releases"
PUBLIC_DIR = "/var/www/ponychat-static/releases"
PUBLIC_BASE = "https://www.ponychat.org/releases/"
CERT_SHA256 = "a91fd0637ac948ed0a6ef86e3e5fdb7868bbb9d011498ef7c0145a41c3de4eb1"


def sha256(path: Path) -> str:
    with path.open("rb") as handle:
        digest = hashlib.sha256()
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apk", type=Path, default=APP / "app/build/outputs/apk/release/app-release.apk")
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--activate-download", action="store_true", help="Point nginx /download/apk to this release without starting the backend")
    args = parser.parse_args()
    if args.activate_download and not args.publish:
        parser.error("--activate-download requires --publish")
    apk = args.apk.resolve(strict=True)
    build_tools = sorted((TOOLS / "android-sdk/build-tools").glob("*"), key=lambda path: path.name, reverse=True)
    build_tools = next(path for path in build_tools if (path / "apksigner.bat").is_file())
    env = dict(os.environ, JAVA_HOME=str(TOOLS / "jdk-17"))
    signature = subprocess.check_output([str(build_tools / "apksigner.bat"), "verify", "--print-certs", str(apk)], env=env, text=True, encoding="utf-8")
    certificate = re.search(r"Signer #1 certificate SHA-256 digest: ([0-9a-f]+)", signature)
    if not certificate or certificate.group(1).lower() != CERT_SHA256:
        raise RuntimeError("APK does not match the pinned PonyChat product signing identity")
    badging = subprocess.check_output([str(build_tools / "aapt.exe"), "dump", "badging", str(apk)], env=env, text=True, encoding="utf-8")
    identity = re.search(r"package: name='([^']+)' versionCode='(\d+)' versionName='([0-9.]+)'", badging)
    if not identity or identity.group(1) != "top.ponychat.webview":
        raise RuntimeError("Unexpected APK package or version")
    _, code, version = identity.groups()
    name = f"PonyChat-v{version}-{code}-release.apk"
    digest = sha256(apk)
    archived = APP / "releases" / name
    archived.parent.mkdir(parents=True, exist_ok=True)
    if archived.exists() and sha256(archived) != digest:
        raise RuntimeError("Versioned local APK already exists with different bytes")
    if not archived.exists():
        shutil.copy2(apk, archived)
    report = {"version_name": version, "version_code": int(code), "package": identity.group(1), "sha256": digest,
              "bytes": apk.stat().st_size, "certificate_sha256": CERT_SHA256, "local_apk": str(archived),
              "public_url": PUBLIC_BASE + name, "remote_path": RELEASE_DIR + "/" + name,
              "backend_restart": False, "published": False}
    if args.publish and (ROOT / ".env.local-stack").exists():
        from local_apk_publish import publish_local
        report = publish_local(ROOT, archived, report, sha256)
        archived.with_suffix(".json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return
    if args.publish:
        sys.path.insert(0, str(ROOT.parent / "ServerKeys"))
        from ssh_lib import load_server, scp_to, ssh_bash_s
        server = load_server("usa")
        report["server"] = {"name": server.name, "host": server.host}
        stage = f"{RELEASE_DIR}/.{name}.{digest[:12]}.part"
        # All shell paths derive from fixed roots and verified numeric versions.
        preflight = f'''set -eu
mkdir -p {RELEASE_DIR} {PUBLIC_DIR}
for file in {RELEASE_DIR}/{name} {PUBLIC_DIR}/{name}; do
  if [ -e "$file" ]; then
    test "$(sha256sum "$file" | cut -d ' ' -f1)" = '{digest}'
  fi
done
'''
        if ssh_bash_s(server, preflight) != 0:
            raise RuntimeError("Remote preflight failed or version already has different bytes")
        if scp_to(server, archived, stage) != 0:
            raise RuntimeError("APK upload failed")
        publish = f'''set -eu
test "$(sha256sum '{stage}' | cut -d ' ' -f1)" = '{digest}'
chmod 644 '{stage}'
mv '{stage}' '{RELEASE_DIR}/{name}'
cp '{RELEASE_DIR}/{name}' '{PUBLIC_DIR}/.{name}.part'
chmod 644 '{PUBLIC_DIR}/.{name}.part'
mv '{PUBLIC_DIR}/.{name}.part' '{PUBLIC_DIR}/{name}'
test "$(sha256sum '{PUBLIC_DIR}/{name}' | cut -d ' ' -f1)" = '{digest}'
sha256sum '{RELEASE_DIR}/{name}' '{PUBLIC_DIR}/{name}'
'''
        if ssh_bash_s(server, publish) != 0:
            raise RuntimeError("Remote publish or hash verification failed")
        downloaded = hashlib.sha256()
        size = 0
        with urllib.request.urlopen(report["public_url"], timeout=60) as response:
            report["http_status"] = response.status
            report["content_type"] = response.headers.get("Content-Type")
            for chunk in iter(lambda: response.read(1024 * 1024), b""):
                downloaded.update(chunk)
                size += len(chunk)
        if size != report["bytes"] or downloaded.hexdigest() != digest:
            raise RuntimeError("Public download differs from signed local APK")
        report.update(published=True, public_sha256=downloaded.hexdigest(), public_bytes=size)
        if args.activate_download:
            config_path = "/etc/nginx/sites-enabled/ponychat-www"
            location = ("    # BEGIN PonyChat static APK\n"
                        "    location = /download/apk {\n"
                        f"        alias {RELEASE_DIR}/{name};\n"
                        "        default_type application/vnd.android.package-archive;\n"
                        f"        add_header Content-Disposition 'attachment; filename=\"{name}\"';\n"
                        "        add_header Cache-Control 'no-cache';\n"
                        "    }\n"
                        "    # END PonyChat static APK\n\n")
            activation = f'''set -eu
python3 - <<'PY'
from pathlib import Path
import re, shutil, subprocess, time
path = Path({config_path!r}).resolve(strict=True)
text = path.read_text()
block = {location!r}
marker = "    # BEGIN PonyChat static APK"
if marker in text:
    changed, count = re.subn(r"    # BEGIN PonyChat static APK.*?    # END PonyChat static APK\\n(?:\\n)?", lambda match: block, text, count=1, flags=re.S)
    assert count == 1
else:
    anchor = "    location ^~ /api/drive {{"
    host_start = text.index("server_name www.ponychat.org ponychat.org;")
    anchor_start = text.index(anchor, host_start)
    next_server = text.find("\\nserver {{", host_start)
    assert next_server < 0 or anchor_start < next_server
    changed = text[:anchor_start] + block + text[anchor_start:]
assert "server_name www.ponychat.org ponychat.org;" in changed
backup = path.with_name(path.name + ".before-apk-{version}-{code}-" + str(time.time_ns()))
shutil.copy2(path, backup)
temporary = path.with_name(path.name + ".apk-new")
temporary.write_text(changed)
temporary.chmod(path.stat().st_mode)
temporary.replace(path)
try:
    subprocess.run(["nginx", "-t"], check=True)
    subprocess.run(["systemctl", "reload", "nginx"], check=True)
except BaseException:
    shutil.copy2(backup, path)
    subprocess.run(["nginx", "-t"], check=True)
    subprocess.run(["systemctl", "reload", "nginx"], check=True)
    raise
print("NGINX_BACKUP=" + str(backup))
PY
'''
            if ssh_bash_s(server, activation) != 0:
                raise RuntimeError("Canonical download activation failed; any applied configuration change is rolled back on validation failure")
            canonical = "https://www.ponychat.org/download/apk"
            canonical_hash = hashlib.sha256()
            with urllib.request.urlopen(canonical, timeout=60) as response:
                report["canonical_http_status"] = response.status
                report["canonical_content_disposition"] = response.headers.get("Content-Disposition")
                for chunk in iter(lambda: response.read(1024 * 1024), b""):
                    canonical_hash.update(chunk)
            if canonical_hash.hexdigest() != digest:
                raise RuntimeError("Canonical download differs from signed local APK")
            report.update(canonical_url=canonical, canonical_sha256=canonical_hash.hexdigest(), nginx_reloaded=True)
    report_path = archived.with_suffix(".json")
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
