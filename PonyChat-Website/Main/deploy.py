#!/usr/bin/env python3
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "deploy_lib"))

from incremental import deploy_tree, npm_build  # noqa: E402


def main() -> None:
    frontend = ROOT / "frontend"
    npm_build(frontend)
    deploy_tree(
        local_dir=frontend / "dist",
        target_kind="server",
        target_name="usa",
        remote_dir="/var/www/ponychat-static",
        label="main-site",
    )


if __name__ == "__main__":
    main()
