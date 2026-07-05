#!/usr/bin/env python3
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "deploy_lib"))

from incremental import deploy_tree  # noqa: E402


def main() -> None:
    deploy_tree(
        local_dir=ROOT / "app",
        target_kind="server",
        target_name="usa",
        remote_dir="/opt/mlp-music-auto/app",
        label="mlp-music-auto-app",
        post_commands=[
            "/opt/mlp-music-auto/venv/bin/pip install -q -r /opt/mlp-music-auto/app/requirements.txt",
            "systemctl restart mlp-music-auto.service",
        ],
    )
    deploy_tree(
        local_dir=ROOT / "web",
        target_kind="server",
        target_name="usa",
        remote_dir="/var/www/mlp-music-auto",
        label="mlp-music-auto-web",
    )
    for name in ("source", "generated"):
        path = ROOT / name
        if path.is_dir():
            deploy_tree(
                local_dir=path,
                target_kind="server",
                target_name="usa",
                remote_dir=f"/data/mlp-music-auto/{name}",
                label=f"mlp-music-auto-{name}",
            )


if __name__ == "__main__":
    main()
