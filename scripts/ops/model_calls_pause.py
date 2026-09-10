"""Reversible PonyChat model-service pause on Server-USA and local Backend."""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCAL_MARKER = ROOT / ".ponychat-models-paused"

COMMON = """set -eu
state=/var/lib/ponychat-model-pause
units='ponychat-backend.service ponychat-cosyvoice.service'
"""
PAUSE = COMMON + """
install -d "$state"
for unit in $units; do
 if [ ! -e "$state/paused" ]; then
  systemctl is-active "$unit" > "$state/$unit.previous-active" || true
 fi
 install -d "/etc/systemd/system/$unit.d"
 printf '[Unit]\\nConditionPathExists=!/var/lib/ponychat-model-pause/paused\\n' > "/etc/systemd/system/$unit.d/90-model-pause.conf"
done
touch "$state/paused"
systemctl daemon-reload
systemctl stop $units
for unit in $units; do
 test "$(systemctl show "$unit" -p MainPID --value)" = 0
done
echo 'Model services paused; restart and reboot remain blocked.'
"""
RESUME = COMMON + """
if [ -e "$state/paused" ]; then
 for unit in $units; do
  test -f "$state/$unit.previous-active"
 done
 mv "$state/paused" "$state/resuming"
fi
if [ -e "$state/resuming" ]; then
 for unit in $units; do
  if grep -qx active "$state/$unit.previous-active"; then
   systemctl start "$unit"
   systemctl is-active --quiet "$unit"
  fi
 done
 rm "$state/resuming"
fi
echo 'Previous service activity restored.'
"""
STATUS = COMMON + """
if [ -e "$state/paused" ]; then echo 'PAUSED'; else echo 'NOT PAUSED'; fi
systemctl show $units -p Id -p ActiveState -p MainPID
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("pause", "resume", "status"))
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT.parent / "ServerKeys"))
    from ssh_lib import load_server, ssh_bash_s

    if args.action == "pause":
        LOCAL_MARKER.touch()
    result = ssh_bash_s(load_server("usa"), {
        "pause": PAUSE, "resume": RESUME, "status": STATUS,
    }[args.action])
    if result == 0 and args.action == "resume":
        LOCAL_MARKER.unlink(missing_ok=True)
    print(f"Local Backend startup paused: {LOCAL_MARKER.exists()}")
    return result


if __name__ == "__main__":
    sys.exit(main())
