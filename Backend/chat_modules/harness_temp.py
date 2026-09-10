"""Use volatile memory for SDK scratch files on the Linux production host."""
import os
from pathlib import Path


def scratch_parent():
    # SDK attachment admission needs local files. They are scratch data, not a
    # server media archive; /dev/shm disappears on reboot and homes are removed.
    root = Path('/dev/shm')
    if os.name == 'posix' and root.is_dir() and os.access(root, os.W_OK):
        return str(root)
    return None  # Windows development uses the usual disposable temp directory.
