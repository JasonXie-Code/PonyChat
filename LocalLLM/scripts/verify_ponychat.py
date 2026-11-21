"""Synthetic text, vision and tool roundtrip through PonyChat's actual Agent adapter."""
import asyncio
import base64
import importlib
from io import BytesIO
import json
import os
from pathlib import Path
import sys
import time
import types

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
package = types.ModuleType('local_llm_verification')
package.__path__ = [str(ROOT / 'Backend/chat_modules')]
sys.modules[package.__name__] = package
runtime = importlib.import_module(package.__name__ + '.harness_runtime')
cfg = json.loads((ROOT / 'Backend/conf/models/local.json').read_text(encoding='utf-8'))['models'][0]


async def main():
    os.environ['PONYCHAT_HARNESS_POOL'] = '1'
    report = {'scope': 'synthetic inputs only; real local model and production Agent adapter', 'cases': []}
    image = Image.new('RGB', (480, 300), 'white')
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 70, 170, 210), fill='red')
    draw.ellipse((290, 70, 430, 210), fill='blue')
    data = BytesIO()
    image.save(data, format='PNG')
    calls = []

    async def read_code(args):
        calls.append(args)
        return {'code': 'LOCAL-7429'}

    tool = runtime.HarnessTool(read_code, 'Read the verification code.', {'type': 'object'})
    cases = [
        ('text', '只回答：本地连接成功', {}),
        ('vision', [{'type': 'text', 'text': '描述图片左边和右边各是什么颜色和形状。'},
                    {'type': 'image', 'mimeType': 'image/png', 'data': base64.b64encode(data.getvalue()).decode()}], {}),
        ('tool', '调用 read_code 工具取得验证码，然后原样回复验证码。', {'read_code': tool}),
    ]
    for name, prompt, tools in cases:
        began = time.monotonic()
        result = await runtime.run_harness_turn(prompt, cfg, tools, max_tokens=512, timeout_seconds=120)
        item = {key: result.get(key) for key in ('model', 'final_response', 'finish_reason', 'tool_call_count', 'usage')}
        item.update(case=name, seconds=round(time.monotonic()-began, 3))
        contexts = [event['data'].get('contextWindow') for event in result['events']
                    if event.get('type') == 'request/context']
        assert contexts and all(value == 131072 for value in contexts), contexts
        item['context_window'] = contexts[0]
        assert item['finish_reason'] == 'completed', item
        if name == 'vision':
            reply = item['final_response']
            assert all(word in reply for word in ('左', '右', '红', '蓝', '圆')), item
            assert '矩形' in reply or '方形' in reply, item
            assert not any(word in reply for word in ('无法', '看不到', '不能')), item
        if name == 'tool':
            assert calls and 'LOCAL-7429' in item['final_response'], item
        report['cases'].append(item)
        print(json.dumps(item, ensure_ascii=False), flush=True)
    output = ROOT / 'docs/testing/local-qwen35-20260911'
    output.mkdir(parents=True, exist_ok=True)
    image.save(output / 'vision-input.png')
    (output / 'agent-verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    asyncio.run(main())
