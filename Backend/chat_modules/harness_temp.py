"""Use volatile memory for SDK scratch files on the Linux production host."""
import os
import asyncio
import logging
from pathlib import Path

_pending_closures = set()


def defer_completed_cleanup(harness, workspace):
    """Own both resources until the SDK closes, even if the coroutine is cancelled."""
    def close_and_cleanup():
        try:
            harness.close()
        finally:
            workspace.cleanup()

    task = asyncio.create_task(asyncio.to_thread(close_and_cleanup))
    _pending_closures.add(task)

    def finished(done):
        _pending_closures.discard(done)
        if not done.cancelled():
            error = done.exception()
            if error is not None:
                logging.getLogger(__name__).warning('Completed Harness cleanup failed',
                    exc_info=(type(error), error, error.__traceback__))

    task.add_done_callback(finished)


def scratch_parent():
    # SDK attachment admission needs local files. They are scratch data, not a
    # server media archive; /dev/shm disappears on reboot and homes are removed.
    root = Path('/dev/shm')
    if os.name == 'posix' and root.is_dir() and os.access(root, os.W_OK):
        return str(root)
    return None  # Windows development uses the usual disposable temp directory.
