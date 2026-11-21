"""Verify local production, both public routes, historical logs and full APK bytes."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import sqlite3
import time

import httpx

ROOT = Path(__file__).resolve().parents[2]


def verify():
    expected = json.loads((ROOT / "var/releases/latest.json").read_text())
    token = json.loads((ROOT / "Backend/.deploy_revision").read_text())["deploy_token"]
    headers = {"X-PonyChat-Client": "android", "X-App-Version": str(expected["version_code"]),
               "X-App-Version-Name": expected["version_name"]}
    report = {"passed": False, "health": {}, "versions": {}, "downloads": {}, "log_details": []}
    with httpx.Client(trust_env=False, timeout=30) as client:
        for label, base in [("local", "http://127.0.0.1:5000"),
                            ("cn", "https://39.101.74.217"), ("usa", "https://www.ponychat.org")]:
            response = client.get(base + "/api/health")
            response.raise_for_status()
            report["health"][label] = response.json()
            assert response.json()["deploy_token"] == token
            response = client.get(base + "/api/app/version", headers=headers)
            response.raise_for_status()
            report["versions"][label] = response.json()
            assert response.json()["version_code"] == expected["version_code"]
            assert response.json()["download_url"] == expected["download_url"]
        with sqlite3.connect((ROOT / "Backend/database/ponychat.db").as_uri() + "?mode=ro", uri=True) as db:
            samples = db.execute("SELECT id,log_file_path FROM llm_log_index ORDER BY id DESC LIMIT 3").fetchall()
            for ident, path in samples:
                assert Path(path).is_file()
                response = client.get("http://127.0.0.1:5000/api/admin/llm-logs/" + str(ident))
                response.raise_for_status()
                report["log_details"].append({"id": ident, "http_status": response.status_code,
                                               "body_present": bool(response.json())})
            count = db.execute("SELECT COUNT(*) FROM llm_log_index WHERE log_file_path LIKE '/opt/ponychat/%'").fetchone()[0]
            report["remaining_linux_log_paths"] = count
            assert count == 0
        for label, url in [("search", "http://127.0.0.1:18786/healthz"),
                           ("cosyvoice", "http://127.0.0.1:18010/cosyvoice/health"),
                           ("qwen", "http://127.0.0.1:8010/qwen3tts/health")]:
            response = client.get(url)
            response.raise_for_status()
            report[label + "_health"] = response.status_code

    def download(item):
        label, url = item
        digest, size, started = hashlib.sha256(), 0, time.monotonic()
        with httpx.Client(trust_env=False, timeout=180) as client, client.stream("GET", url) as response:
            response.raise_for_status()
            for block in response.iter_bytes():
                digest.update(block)
                size += len(block)
            result = {"http_status": response.status_code, "bytes": size, "sha256": digest.hexdigest(),
                      "seconds": round(time.monotonic() - started, 2),
                      "content_type": response.headers.get("content-type")}
        assert size == expected["bytes"] and digest.hexdigest() == expected["sha256"], label
        return label, result

    with ThreadPoolExecutor(2) as pool:
        report["downloads"] = dict(pool.map(download, [
            ("cn", expected["download_url"]), ("official_site", "https://www.ponychat.org/download/apk")]))
    report["passed"] = True
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=ROOT / "var/local-stack/acceptance.json")
    args = parser.parse_args()
    result = verify()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result), flush=True)
