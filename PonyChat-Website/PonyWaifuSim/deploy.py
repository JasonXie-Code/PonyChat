#!/usr/bin/env python3
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "deploy_lib"))

from incremental import deploy_tree  # noqa: E402


def main() -> None:
    remote_dir = os.environ.get("PONYWAIFUSIM_REMOTE_DIR", "").strip()
    target_kind = os.environ.get("PONYWAIFUSIM_TARGET_KIND", "server").strip()
    target_name = os.environ.get("PONYWAIFUSIM_TARGET_NAME", "usa").strip()
    if not remote_dir:
        raise SystemExit(
            "No production target was found for PonyWaifuSim. "
            "Set PONYWAIFUSIM_REMOTE_DIR, and optionally "
            "PONYWAIFUSIM_TARGET_KIND/PONYWAIFUSIM_TARGET_NAME, before deploying."
        )
    deploy_tree(
        local_dir=ROOT,
        target_kind=target_kind,
        target_name=target_name,
        remote_dir=remote_dir,
        label="pony-waifu-sim",
    )


if __name__ == "__main__":
    main()
