import asyncio
import importlib.util
from pathlib import Path
import tempfile
import threading


spec = importlib.util.spec_from_file_location('harness_temp_test', Path(__file__).parents[1] / 'chat_modules/harness_temp.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_completed_cleanup_retains_workspace_until_close_finishes():
    started, release = threading.Event(), threading.Event()
    workspace = tempfile.TemporaryDirectory()
    path = Path(workspace.name)

    class Harness:
        def close(self):
            started.set()
            assert release.wait(3)
            assert path.exists()

    async def exercise():
        module.defer_completed_cleanup(Harness(), workspace)
        assert await asyncio.to_thread(started.wait, 2)
        assert path.exists()
        tasks = tuple(module._pending_closures)
        release.set()
        await asyncio.gather(*tasks)
        assert not path.exists()

    asyncio.run(exercise())


def test_cancelled_cleanup_task_still_closes_before_removing_workspace():
    started, release, cleaned = threading.Event(), threading.Event(), threading.Event()
    temporary = tempfile.TemporaryDirectory()
    path = Path(temporary.name)

    class Workspace:
        def cleanup(self):
            temporary.cleanup()
            cleaned.set()

    class Harness:
        def close(self):
            started.set()
            assert release.wait(3)
            assert path.exists()

    async def exercise():
        module.defer_completed_cleanup(Harness(), Workspace())
        assert await asyncio.to_thread(started.wait, 2)
        tasks = tuple(module._pending_closures)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        assert path.exists()
        release.set()
        assert await asyncio.to_thread(cleaned.wait, 2)
        assert not path.exists()

    asyncio.run(exercise())
