"""Verify actual Qwen calls produce the model field consumed by Android."""
import asyncio
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import types

ROOT = Path(__file__).resolve().parents[2]
package = types.ModuleType('status_verification')
package.__path__ = [str(ROOT / 'Backend/chat_modules')]
sys.modules[package.__name__] = package
runtime = importlib.import_module(package.__name__ + '.harness_runtime')
logs = importlib.import_module(package.__name__ + '.agent_logging')
status = importlib.import_module(package.__name__ + '.agent_status')


async def main():
    config = json.loads((ROOT / 'Backend/conf/models/local.json').read_text())['models'][0]
    stages = []
    async def record(stage, data, **kwargs):
        stages.append({'stage': stage, 'model': logs._scope.get()['model']})
    logs.write = record
    with tempfile.TemporaryDirectory() as directory:
        os.environ['PONYCHAT_AGENT_STATUS_DB_PATH'] = str(Path(directory) / 'status.sqlite3')
        async with logs.log_scope('synthetic', 'synthetic', 'normal', model_config=config):
            initial = status.read('synthetic', 'synthetic', 'normal')['model']
            result = await runtime.run_harness_turn('只回答：显示正确', config, {}, max_tokens=64)
        public = status.read('synthetic', 'synthetic', 'normal')
        assert initial == public['model'] == result['model'] == 'qwen3.5-4b-local'
        assert result['finish_reason'] == 'completed'
        assert all(item['model'] == initial for item in stages)
        report = {'scope': 'synthetic input; real local model; isolated status database',
                  'initial_model': initial, 'public_status': public,
                  'response': result['final_response'], 'logged_stages': stages}
        output = ROOT / 'docs/testing/local-qwen35-20260911/status-verification.json'
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'model': public['model'], 'status': public['status'],
                          'response': result['final_response']}, ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(main())
