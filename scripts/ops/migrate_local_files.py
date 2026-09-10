"""Merge explicit migrated data into the workspace, preserving local conflicts."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import time

from migration_transport import ROOT, STATE, sha256


def merge(source: Path, target: Path, label: str) -> dict:
    source, target = source.resolve(), target.resolve()
    if not source.is_relative_to(STATE.resolve()) or not target.is_relative_to(ROOT):
        raise ValueError("Migration source or destination is outside its allowed root")
    preserved = STATE / "preexisting-local" / label
    moved = identical = conflicts = 0
    total_bytes = 0
    started = time.monotonic()
    for path in source.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(source)
        dest = target / relative
        if (not path.resolve().is_relative_to(STATE.resolve())
                or not dest.resolve().is_relative_to(ROOT)):
            raise ValueError("Refusing a migration path through an external link")
        digest = sha256(path)
        total_bytes += path.stat().st_size
        if dest.exists():
            if dest.stat().st_size == path.stat().st_size and sha256(dest) == digest:
                identical += 1
                path.unlink()
                continue
            previous = preserved / relative
            if previous.exists():
                raise FileExistsError(f"Refusing to overwrite preserved file: {previous}")
            previous.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(dest), str(previous))
            conflicts += 1
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(dest))
        if sha256(dest) != digest:
            raise RuntimeError(f"Migration hash mismatch: {relative}")
        moved += 1
        if moved % 25000 == 0:
            print(json.dumps({"label": label, "moved": moved, "same": identical}), flush=True)
    report = {"label": label, "source": str(source), "target": str(target),
              "moved": moved, "same": identical, "preserved_conflicts": conflicts,
              "bytes": total_bytes, "seconds": round(time.monotonic() - started, 1)}
    (STATE / ("merge-" + label + ".json")).write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    parser.add_argument("label")
    args = parser.parse_args()
    merge(args.source, args.target, args.label)
