#!/usr/bin/env python3
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parents[1] / "deploy_lib"))

from incremental import deploy_tree, npm_build  # noqa: E402


def main() -> None:
    web = ROOT / "web"
    npm_build(web)
    deploy_tree(
        local_dir=web / "dist",
        target_kind="server",
        target_name="usa",
        remote_dir="/var/www/standard-mbti-static",
        label="mbti-standard",
    )


if __name__ == "__main__":
    main()
