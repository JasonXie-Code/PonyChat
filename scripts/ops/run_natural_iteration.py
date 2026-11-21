"""Run an immutable prompt snapshot through the isolated real chat route."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tarfile


ROOT = Path(__file__).resolve().parents[2]
round_dir = Path(sys.argv[1]).resolve()
snapshot = round_dir / "autonomous_direct.py"
archive = round_dir / "overlay.tar"
with tarfile.open(archive, "w") as tar:
    tar.add(snapshot, arcname="Backend/chat_modules/autonomous_direct.py")
os.environ.update({
    "PONYCHAT_COVERAGE_OVERLAY": str(archive),
    "PONYCHAT_STYLE_PROFILES": str(ROOT / "docs/testing/natural-curiosity-20260910/route-profiles.json"),
    "PONYCHAT_STYLE_CASES": str(ROOT / "docs/testing/natural-curiosity-20260910/route-acceptance-cases.json"),
    "PONYCHAT_STYLE_CHARACTERS": "twilight_sparkle,pinkie_pie,fluttershy",
    "PONYCHAT_STYLE_PROGRESS": str(round_dir / "progress.json"),
    "PONYCHAT_SMOKE_TIMEOUT_SECONDS": "5400",
})
spec = importlib.util.spec_from_file_location("matrix", ROOT / "Backend/Agent-Test/run_style_matrix_probe.py")
matrix = importlib.util.module_from_spec(spec)
spec.loader.exec_module(matrix)


async def exercise(workspace):
    sys.path.insert(0, str(workspace))
    from Backend.chat_modules import harness_runtime
    actual = harness_runtime.run_harness_turn
    attempts = []

    async def observed(prompt, config, tools, **options):
        entry = {"index": len(attempts) + 1, "input": prompt,
                 "system_prompt": options.get("system_prompt"),
                 "model": config.get("model")}
        attempts.append(entry)
        try:
            result = await actual(prompt, config, tools, **options)
            entry.update({k: result.get(k) for k in (
                "final_response", "finish_reason", "llm_api_calls", "tool_call_count")})
            return result
        except Exception as exc:
            entry["error_type"] = type(exc).__name__
            raise
        finally:
            (round_dir / "model-raw.json").write_text(
                json.dumps(attempts, ensure_ascii=False, indent=2), encoding="utf-8")

    harness_runtime.run_harness_turn = observed
    try:
        result = await matrix.exercise(workspace)
        result["prompt_snapshot_sha256"] = hashlib.sha256(snapshot.read_bytes()).hexdigest()
        result["variant"] = "isolated prompt snapshot; deployment field is source marker only"
        return result
    finally:
        harness_runtime.run_harness_turn = actual


matrix.smoke.exercise = exercise
sys.argv = [sys.argv[0], str(round_dir / "raw.json"), "--source", str(ROOT)]
raise SystemExit(matrix.smoke.main())
