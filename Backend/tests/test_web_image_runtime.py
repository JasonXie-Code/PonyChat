"""A web-image turn must destroy pooled SDK scratch before image delivery."""
import asyncio
from pathlib import Path
from types import SimpleNamespace

from test_harness_pool import runtime, pool, FakeHarness, configure


def test_web_image_read_retires_runtime_and_removes_attachment_scratch(monkeypatch):
    class WebHarness(FakeHarness):
        def run(self, prompt, session_id, on_notification=None):
            self.sessions.append(session_id)
            self.request(session_id, name='read_web_image')
            (Path(self.config['dsh_home']) / 'synthetic-image-bytes').write_bytes(b'image')
            return SimpleNamespace(final_response='done', finish_reason='completed', events=[])
    import sys
    monkeypatch.setitem(sys.modules, 'deepseek_harness', SimpleNamespace(DeepSeekHarness=WebHarness))
    async def scenario():
        async def read(): return {'status': 'downloaded'}
        await runtime.run_harness_turn('one', {}, {'read_web_image': read})
        instance = FakeHarness.instances[-1]
        assert instance.closed
        assert not Path(instance.config['dsh_home']).exists()
    asyncio.run(scenario())
