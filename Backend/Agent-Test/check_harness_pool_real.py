"""Real SDK reuse/isolation probe using synthetic tool values and no user data."""
import asyncio
import base64
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import struct
import zlib

from run_harness_comparison import initialize


async def main():
    output = Path(sys.argv[1] if len(sys.argv) > 1 else '.tmp/harness-pool-real.json')
    with tempfile.TemporaryDirectory(prefix='ponychat-pool-real-', ignore_cleanup_errors=True) as folder:
        api = initialize(Path(folder))
        config = api[-1]
        os.environ['PONYCHAT_HARNESS_POOL'] = '1'
        from Backend.chat_modules.harness_runtime import run_harness_turn
        from Backend import config as backend_config
        results = []
        try:
            for label in ['ACCOUNT_A_CANARY_7492', 'ACCOUNT_B_CANARY_2861']:
                async def current():
                    return {'current_value': label}
                start = time.monotonic()
                result = await run_harness_turn(
                    'Call read_current once. Reply with only its current_value. Do not use other sessions.',
                    config, {'read_current': current},
                    system_prompt='Synthetic SDK test. Follow the current tool result exactly.',
                    max_tokens=300, max_tool_calls=2, timeout_seconds=60)
                assert label in result['final_response'], result['final_response']
                if len(results):
                    assert 'ACCOUNT_A_CANARY_7492' not in result['final_response']
                    assert result['runtime_reused']
                results.append({'case': label, 'seconds': round(time.monotonic()-start, 2),
                                'runtime_reused': result['runtime_reused'], 'reply': result['final_response'],
                                'tool_calls': result['tool_call_count']})
                output.write_text(json.dumps(results, indent=2), encoding='utf-8')
                print('PASS', label, results[-1]['seconds'], result['runtime_reused'], flush=True)
            def png(rgb):
                def chunk(kind, data):
                    return struct.pack('!I', len(data))+kind+data+struct.pack('!I', zlib.crc32(kind+data))
                raw = (b'\x00'+bytes(rgb)*16)*16
                data = b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR', struct.pack('!2I5B',16,16,8,2,0,0,0))
                return base64.b64encode(data+chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b'')).decode()
            for color, rgb in [('red', (255,0,0)), ('blue', (0,0,255))]:
                blocks = [{'type':'text','text':'Name only the dominant color of this image in English.'},
                          {'type':'image','mimeType':'image/png','data':png(rgb)}]
                start = time.monotonic()
                result = await run_harness_turn(blocks, config, {},
                    system_prompt='Describe the supplied image accurately. Reply with one English color word.',
                    max_tokens=300, max_tool_calls=0, timeout_seconds=60)
                assert color in result['final_response'].lower(), result['final_response']
                if color == 'blue':
                    assert result['runtime_reused']
                results.append({'case':color+'_image','seconds':round(time.monotonic()-start,2),
                                'runtime_reused':result['runtime_reused'],'reply':result['final_response']})
                output.write_text(json.dumps(results, indent=2), encoding='utf-8')
                print('PASS', color+'_image', result['runtime_reused'], flush=True)
        finally:
            if backend_config.httpx_client is not None:
                await backend_config.httpx_client.aclose()
            backend_config._queue_listener.stop()
            for handler in backend_config._queue_listener.handlers:
                handler.close()


if __name__ == '__main__':
    asyncio.run(main())
