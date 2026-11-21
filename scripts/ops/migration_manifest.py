"""Hash, reconcile and verify migrated data and logs without deleting the source."""
from __future__ import annotations

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import gzip
import json
from pathlib import Path
import shutil
import tarfile
import time

from migration_transport import ROOT, STATE, sha256, ssh_run

MAPPINGS = {
    "/opt/ponychat/var/.chatlogs": "var/.chatlogs",
    "/opt/ponychat/var/backlogs": "var/backlogs",
    "/opt/ponychat/var/applogs": "var/applogs",
    "/opt/ponychat/var/chatlogs": "var/chatlogs",
    "/opt/ponychat/var/test_results": "var/test_results",
    "/opt/ponychat/var/agent-status.sqlite3": "var/agent-status.sqlite3",
    "/opt/ponychat/Backend/database/admin_uptime_samples.json": "Backend/database/admin_uptime_samples.json",
    "/opt/ponychat/Backend/database/daily_summary_clean_changes_20260524_094604.jsonl": "Backend/database/daily_summary_clean_changes_20260524_094604.jsonl",
    "/opt/ponychat/Backend/database/daily_summary_clean_pass2_changes_20260524_094733.jsonl": "Backend/database/daily_summary_clean_pass2_changes_20260524_094733.jsonl",
    "/opt/ponychat/Backend/database/.jailbreak_migration_v1.done": "Backend/database/.jailbreak_migration_v1.done",
    "/opt/ponychat/var/drive": "var/drive",
    "/opt/ponychat/var/recovery_snapshots": "var/recovery_snapshots",
    "/opt/ponychat/Backend/data": "Backend/data",
    "/opt/ponychat-cosyvoice/outputs": "var/services/cosyvoice/outputs",
    "/opt/ponychat-cosyvoice/uploads": "var/services/cosyvoice/uploads",
}


def destination(remote: str, *, resolve: bool = True) -> Path:
    for source, local in MAPPINGS.items():
        if remote == source:
            return (ROOT / local).resolve()
        if remote.startswith(source + "/"):
            relative = Path(remote[len(source) + 1:])
            if relative.is_absolute() or relative.drive or ".." in relative.parts:
                raise ValueError("Invalid relative migration path")
            if source.endswith("/Backend/data") and relative.suffix == ".py":
                target = STATE / "server-data-code" / relative
            else:
                target = ROOT / local / relative
            resolved = target.resolve() if resolve else target
            if not resolved.is_relative_to(ROOT):
                raise ValueError("Destination is outside the workspace")
            return resolved
    raise ValueError(f"Unrecognized migration root: {remote}")


def collect(name: str):
    script = "python3 - <<'PY'\n"
    script += "import os,pathlib,hashlib,json,gzip,sys,time,stat\n"
    script += "roots=" + repr(list(MAPPINGS)) + "\n"
    script += "cache={}\n"
    previous = STATE / "initial-data-manifest.jsonl.gz"
    if name != "initial-data-manifest" and previous.exists():
        script += "import base64,io\n"
        script += "previous=base64.b64decode(" + repr(base64.b64encode(previous.read_bytes()).decode()) + ")\n"
        script += "for line in gzip.GzipFile(fileobj=io.BytesIO(previous)):\n"
        script += " row=json.loads(line)\n"
        script += " if row['type']=='file' and row['stable']:cache[row['path']]=(row['mtime_ns'],row['size'],row['sha256'])\n"
        script += "del previous\n"
    script += r'''
with gzip.GzipFile(fileobj=sys.stdout.buffer,mode='wb',compresslevel=1) as out:
 def emit(value):out.write(json.dumps(value,separators=(',',':')).encode()+bytes([10]))
 emit({'type':'header','time':time.time(),'roots':roots})
 for root in roots:
  walk=[(str(pathlib.Path(root).parent),[],[pathlib.Path(root).name])] if os.path.isfile(root) else os.walk(root)
  for directory,dirs,files in walk:
   dirs[:]=[d for d in dirs if d not in {'backups','__pycache__'}]
   for filename in files:
    path=pathlib.Path(directory)/filename
    try:
     before=path.stat()
     if not stat.S_ISREG(before.st_mode):continue
     prior=cache.get(str(path))
     if prior and prior[0]==before.st_mtime_ns and prior[1]==before.st_size:
      digest=prior[2]
     else:
      h=hashlib.sha256()
      with path.open('rb') as f:
       while block:=f.read(1024*1024):h.update(block)
      digest=h.hexdigest()
     after=path.stat()
     emit({'type':'file','path':str(path),'size':after.st_size,'mtime_ns':after.st_mtime_ns,
           'sha256':digest,'stable':before.st_mtime_ns==after.st_mtime_ns and before.st_size==after.st_size})
    except OSError as e:emit({'type':'error','path':str(path),'error':type(e).__name__})
 emit({'type':'end','time':time.time()})
PY
'''
    output = STATE / (name + ".jsonl.gz")
    ssh_run(script, output=output, timeout=3600)
    print(json.dumps({"manifest": str(output), "bytes": output.stat().st_size}), flush=True)


def verify(name: str, *, repair: bool = False):
    source = STATE / (name + ".jsonl.gz")
    cache_path = STATE / "verified-file-cache.json"
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    mismatches, errors = [], []
    files = total = cached = 0
    complete = False
    started = time.monotonic()
    def check(row):
        target = destination(row["path"], resolve=False)
        try:
            info = target.stat()
            identity = [info.st_size, info.st_mtime_ns, info.st_ino]
            prior = cache.get(row["path"])
            reused = bool(prior and prior[:3] == identity)
            digest = prior[3] if reused else sha256(target) if info.st_size == row["size"] else None
            matched = digest == row["sha256"] and info.st_size == row["size"]
            return row, identity + [digest] if matched else None, reused
        except FileNotFoundError:
            return row, None, False

    def consume(batch, pool):
        nonlocal cached
        for row, identity, reused in pool.map(check, batch):
            cached += int(reused)
            if identity is None:
                mismatches.append(row)
            else:
                cache[row["path"]] = identity

    batch = []
    with ThreadPoolExecutor(max_workers=8) as pool, gzip.open(source, "rt", encoding="utf-8") as rows:
        for line in rows:
            row = json.loads(line)
            if row["type"] == "end":
                complete = True
            if row["type"] == "error":
                errors.append(row)
                continue
            if row["type"] != "file":
                continue
            if not row["stable"]:
                errors.append({"path": row["path"], "error": "source_changed_during_hash"})
                continue
            files += 1
            total += row["size"]
            batch.append(row)
            if len(batch) >= 5000:
                consume(batch, pool)
                batch = []
            if files % 50000 == 0:
                print(json.dumps({"checked": files, "mismatches": len(mismatches), "cached": cached}), flush=True)
        consume(batch, pool)
    cache_path.write_text(json.dumps(cache, separators=(",", ":")), encoding="utf-8")
    if not complete:
        errors.append({"error": "manifest_missing_end_marker"})
    receipt = {"manifest": name, "files": files, "bytes": total, "mismatch_count": len(mismatches),
               "errors": errors, "cached": cached, "seconds": round(time.monotonic() - started, 1),
               "passed": not mismatches and not errors}
    (STATE / (name + "-verification.json")).write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    (STATE / (name + "-mismatches.json")).write_text(json.dumps(mismatches), encoding="utf-8")
    print(json.dumps(receipt), flush=True)
    if repair and mismatches:
        fetch_mismatches(name, mismatches)
        receipt = finalize_repairs(name, mismatches)
    return receipt


def fetch_mismatches(name: str, rows: list[dict]):
    paths = [r["path"] for r in rows]
    for path in paths:
        destination(path)  # Scope and traversal validation before remote access.
    script = "python3 - <<'PY'\nimport tarfile,sys,gzip\n"
    script += "with gzip.GzipFile(fileobj=sys.stdout.buffer,mode='wb',compresslevel=1) as gz:\n"
    script += " with tarfile.open(fileobj=gz,mode='w|') as archive:\n"
    script += "  for path in " + repr(paths) + ":archive.add(path,arcname=path.lstrip('/'),recursive=False)\nPY\n"
    archive_path = STATE / (name + "-delta.tar.gz")
    ssh_run(script, output=archive_path, timeout=3600)
    expected = {r["path"]: r for r in rows}
    with tarfile.open(archive_path, "r|gz") as archive:
        for member in archive:
            remote = "/" + member.name
            if remote not in expected or not member.isfile():
                raise ValueError("Unexpected delta archive member")
            target = destination(remote)
            target.parent.mkdir(parents=True, exist_ok=True)
            pending = target.with_name(target.name + ".migration-part")
            with archive.extractfile(member) as source, pending.open("wb") as out:
                shutil.copyfileobj(source, out, 1024 * 1024)
            if sha256(pending) != expected[remote]["sha256"]:
                raise RuntimeError(f"Delta differs from frozen manifest: {remote}")
            pending.replace(target)
    print(json.dumps({"repaired": len(rows), "archive_bytes": archive_path.stat().st_size}), flush=True)


def finalize_repairs(name: str, rows: list[dict]):
    """Verify replaced files, retaining the completed scan of unchanged files."""
    receipt_path = STATE / (name + "-verification.json")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["mismatch_count"] == len(rows)
    cache_path = STATE / "verified-file-cache.json"
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    for row in rows:
        target = destination(row["path"])
        info = target.stat()
        digest = sha256(target)
        assert info.st_size == row["size"] and digest == row["sha256"]
        cache[row["path"]] = [info.st_size, info.st_mtime_ns, info.st_ino, digest]
    cache_path.write_text(json.dumps(cache, separators=(",", ":")), encoding="utf-8")
    receipt.update(mismatch_count=0, repaired=len(rows), passed=not receipt["errors"])
    receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(json.dumps(receipt), flush=True)
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["collect", "verify", "repair"])
    parser.add_argument("name")
    args = parser.parse_args()
    if args.action == "collect":
        collect(args.name)
    else:
        verify(args.name, repair=args.action == "repair")
