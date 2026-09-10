"""Copy the stopped Server-USA SQLite database using verified changed blocks."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import struct

from migration_transport import ROOT, STATE, sha256, ssh_run

BLOCK = 1024 * 1024


def sync_stopped_database():
    if (ROOT / "var/local-stack/migration.ready").exists():
        raise RuntimeError("Local production is already migrated; refusing to overwrite its database")
    remote = r'''python3 - <<'PY'
import subprocess,sqlite3,pathlib,hashlib,json
assert subprocess.run(['systemctl','is-active','--quiet','ponychat-backend']).returncode != 0, 'Production writer must be stopped'
path=pathlib.Path('/opt/ponychat/Backend/database/ponychat.db')
assert path.is_file() and path.stat().st_size>0, 'Source database is missing; never create a replacement'
with sqlite3.connect(path,timeout=30) as c:
 result=c.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()
 assert result[0]==0, result
h=hashlib.sha256(); blocks=[]
with path.open('rb') as f:
 while data:=f.read(1024*1024):
  h.update(data);blocks.append(hashlib.sha256(data).hexdigest())
print(json.dumps({'size':path.stat().st_size,'sha256':h.hexdigest(),'blocks':blocks,'checkpoint':result}))
PY
'''
    manifest = json.loads(ssh_run(remote, timeout=1800))
    (STATE / "final-database-source.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    target = ROOT / "Backend" / "database" / "ponychat.db"
    previous = STATE / "preexisting-local" / "database"
    previous.mkdir(parents=True, exist_ok=True)
    initialized = STATE / "database-initialized.json"
    if not initialized.exists():
        for suffix in ("", "-wal", "-shm"):
            file = Path(str(target) + suffix)
            preserved = previous / file.name
            if file.exists():
                if preserved.exists():
                    raise FileExistsError(f"Local database already preserved: {preserved}")
                shutil.move(str(file), str(preserved))
        shutil.copy2(STATE / "preflight-production.db", target)
        initialized.write_text(json.dumps({"path": str(target)}), encoding="utf-8")
    changed = []
    with target.open("rb") as local:
        for index, expected in enumerate(manifest["blocks"]):
            if hashlib.sha256(local.read(BLOCK)).hexdigest() != expected:
                changed.append(index)
    delta = STATE / "database-delta.bin"
    script = "python3 - <<'PY'\nimport sys,struct\n"
    script += "with open('/opt/ponychat/Backend/database/ponychat.db','rb') as f:\n"
    script += " for i in " + repr(changed) + ":\n"
    script += "  f.seek(i*1048576); data=f.read(1048576); sys.stdout.buffer.write(struct.pack('>QI',i*1048576,len(data)));sys.stdout.buffer.write(data)\nPY\n"
    ssh_run(script, output=delta, timeout=1800)
    with target.open("r+b") as local, delta.open("rb") as source:
        while header := source.read(12):
            if len(header) != 12:
                raise ValueError("Incomplete database block header")
            offset, size = struct.unpack(">QI", header)
            data = source.read(size)
            if len(data) != size or offset + size > manifest["size"]:
                raise ValueError("Incomplete or out-of-range database block")
            local.seek(offset)
            local.write(data)
        local.truncate(manifest["size"])
    actual_hash = sha256(target)
    if actual_hash != manifest["sha256"]:
        raise RuntimeError("Final migrated database SHA-256 differs from stopped source")
    with sqlite3.connect(target.as_uri() + "?mode=ro", uri=True) as database:
        integrity = database.execute("PRAGMA integrity_check").fetchone()[0]
        tables = [r[0] for r in database.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        counts = {t: database.execute('SELECT COUNT(*) FROM "' + t.replace('"', '""') + '"').fetchone()[0]
                  for t in tables}
    assert integrity == "ok"
    receipt = {"sha256": actual_hash, "size": target.stat().st_size,
               "changed_blocks": len(changed), "transferred_bytes": delta.stat().st_size,
               "integrity": integrity, "all_table_counts_match": True,
               "table_count_proof": "All database bytes match the stopped source SHA-256; table counts and integrity checked locally",
               "counts": counts,
               "tables": len(counts), "path": str(target)}
    (STATE / "final-database-receipt.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(json.dumps(receipt), flush=True)


if __name__ == "__main__":
    sync_stopped_database()
