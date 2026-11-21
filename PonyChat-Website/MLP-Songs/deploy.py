#!/usr/bin/env python3
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "deploy_lib"))

from incremental import deploy_tree, run  # noqa: E402


def main() -> None:
    marker = ROOT.parent.parent / "var" / "music-site" / "local-origin.enabled"
    if marker.exists():
        print("[ERROR] 已启用本机音乐源站，禁止使用旧版 Server-USA 全量部署。"
              "请更新本机后端和数据，仅将网页发布到 Server-USA。", file=sys.stderr)
        raise SystemExit(2)
    run([sys.executable, "scripts/generate_index.py"], cwd=ROOT, timeout=None)
    deploy_tree(
        local_dir=ROOT / "app",
        target_kind="server",
        target_name="usa",
        remote_dir="/opt/mlp-music/app",
        label="mlp-music-app",
        post_commands=[
            "/opt/mlp-music/venv/bin/pip install -q -r /opt/mlp-music/app/requirements.txt",
            "/opt/mlp-music/venv/bin/python /opt/mlp-music/app/analytics_setup.py",
            "systemctl restart mlp-music.service",
        ],
    )
    deploy_tree(
        local_dir=ROOT / "web",
        target_kind="server",
        target_name="usa",
        remote_dir="/var/www/mlp-music",
        label="mlp-music-web",
    )
    media = ROOT / "media-export"
    if media.is_dir():
        deploy_tree(
            local_dir=media,
            target_kind="server",
            target_name="usa",
            remote_dir="/data/mlp-music",
            label="mlp-music-media",
            excludes={"dist"},
        )
    else:
        print(f"Skip media: missing {media}")


if __name__ == "__main__":
    main()
