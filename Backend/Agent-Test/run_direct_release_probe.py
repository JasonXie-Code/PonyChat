"""Exercise the production default route; no test-only reply composer override."""
import hashlib
import os
from pathlib import Path

import run_node_timing_probe as timing
import smoke_deployed_harness as smoke


async def exercise(workspace):
    result = await timing.exercise(workspace)
    calls = [call for row in result["cases"] for call in row["agent_calls"]]
    direct = bool(calls) and all((call.get("prompt_skills") or {}).get("reply_composer") == "agent" for call in calls)
    result["direct_acceptance"] = {"default_composer_is_agent": direct}
    result["observed_source_hashes"]["Backend/chat_modules/autonomous_direct.py"] = hashlib.sha256(
        (workspace / "Backend/chat_modules/autonomous_direct.py").read_bytes()).hexdigest()
    result["passed"] = result["passed"] and direct
    return result


if __name__ == "__main__":
    os.environ.setdefault("PONYCHAT_SMOKE_TIMEOUT_SECONDS", "1200")
    smoke.exercise = exercise
    raise SystemExit(smoke.main())
