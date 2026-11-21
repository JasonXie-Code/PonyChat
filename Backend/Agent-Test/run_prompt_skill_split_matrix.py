"""Run the six first-round prompt-skill split samples in parallel isolation."""
from __future__ import annotations

import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "docs/testing/four-character-three-scene-20260910"
CHARACTERS = ("twilight_sparkle", "pinkie_pie")


def write(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(output: Path) -> int:
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    cases = json.loads((SOURCE / "cases.json").read_text(encoding="utf-8"))
    profiles = [profile for profile in json.loads((SOURCE / "profiles.json").read_text(encoding="utf-8"))
                if profile["id"] in CHARACTERS]
    assert len(profiles) == len(CHARACTERS)
    write(output / "cases.json", cases)
    write(output / "profiles.json", profiles)
    cells = [(scenario[0], character) for scenario in cases for character in CHARACTERS]

    def run(cell):
        scenario, character = cell
        directory = output / "cells" / f"{scenario}_{character}"
        directory.mkdir(parents=True)
        env = {key: value for key, value in os.environ.items() if not key.startswith("PONYCHAT_STYLE_")}
        env.update(PYTHONPATH=str(ROOT / "scripts/ops"), PYTHONUTF8="1",
                   PONYCHAT_STYLE_PROFILES=str(output / "profiles.json"),
                   PONYCHAT_STYLE_CASES=str(output / "cases.json"),
                   PONYCHAT_STYLE_CHARACTERS=character, PONYCHAT_STYLE_SCENARIO=scenario,
                   PONYCHAT_STYLE_PROGRESS=str(directory / "progress.json"),
                   PONYCHAT_SMOKE_TIMEOUT_SECONDS="300")
        started = time.time()
        with (directory / "stdout.log").open("wb") as stdout, (directory / "stderr.log").open("wb") as stderr:
            process = subprocess.Popen([sys.executable, str(ROOT / "Backend/Agent-Test/run_style_matrix_probe.py"),
                                        str(directory / "raw.json"), "--source", str(ROOT)], cwd=ROOT, env=env,
                                       stdout=stdout, stderr=stderr,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            code = process.wait(timeout=360)
        raw = json.loads((directory / "raw.json").read_text(encoding="utf-8")) if (directory / "raw.json").exists() else {}
        case = (raw.get("cases") or [{}])[0]
        return {"scenario": scenario, "character_id": character, "exit_code": code,
                "seconds": round(time.time() - started, 2), "case": case}

    started = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(cells)) as pool:
        rows = list(pool.map(run, cells))
    result = {"passed": all(row["exit_code"] == 0 and row["case"].get("passed") for row in rows),
              "parallel_workers": len(cells), "wall_seconds": round(time.time() - started, 2), "rows": rows}
    write(output / "results.json", result)
    print(json.dumps({key: value for key, value in result.items() if key != "rows"}, ensure_ascii=False))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1])))
