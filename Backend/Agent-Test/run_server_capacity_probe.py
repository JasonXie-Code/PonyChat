"""Run on Server-USA in a bounded transient systemd unit; synthetic prompts only."""
import asyncio
import argparse
import importlib.util
import json
import os
import sys
import time
import types
from pathlib import Path

ROOT=Path('/opt/ponychat')
package=types.ModuleType('capacity_runtime')
package.__path__=[str(ROOT/'Backend/chat_modules')]
sys.modules['capacity_runtime']=package
spec=importlib.util.spec_from_file_location('capacity_runtime.harness_runtime',ROOT/'Backend/chat_modules/harness_runtime.py')
runtime=importlib.util.module_from_spec(spec);spec.loader.exec_module(runtime)
from dotenv import load_dotenv
load_dotenv(ROOT/'.env')
config={'api_key':os.environ.get('PONYCHAT_DEEPSEEK_API_KEY'),'endpoint':'https://api.deepseek.com'}
if not config['api_key']:raise RuntimeError('Model credential unavailable')
cgroup=Path('/sys/fs/cgroup')/Path('/proc/self/cgroup').read_text().split('0::',1)[1].strip().lstrip('/')


async def run(count):
    os.environ['PONYCHAT_HARNESS_CONCURRENCY']=str(count)
    samples=[];done=False
    async def sample():
        while not done:
            mem={k:int(v.split()[0]) for k,v in (line.split(':',1) for line in Path('/proc/meminfo').read_text().splitlines())}
            samples.append({'memory':int((cgroup/'memory.current').read_text()),
                            'swap':int((cgroup/'memory.swap.current').read_text()),
                            'available':mem['MemAvailable']*1024})
            await asyncio.sleep(.15)
    watcher=asyncio.create_task(sample())
    async def one(index):
        started=time.monotonic()
        realistic='--context' in sys.argv
        async def read_recent():
            return {'history':[{'user':f'第{i}次一起读书，我读了天文学入门的第{i}章，喜欢无糖茶。',
                                'assistant':'我会和你一起慢慢梳理书中的知识，也记得你希望饮料不要加糖。'} for i in range(50)]}
        async def remember():return {'staged':True,'synthetic':True}
        tools={'read_recent':read_recent,'remember':remember} if realistic else {}
        prompt='我有些累，请作为图书管理员朋友，简短说两句温和的话。'
        if realistic:prompt+='先调用read_recent读取历史，再调用remember暂存偏好，最后回复。'
        result=await runtime.run_harness_turn(prompt,config,tools,
            system_prompt='合成容量测试。用户与角色都是成年人。按要求使用工具，最后只输出两句日常关心。',
            timeout_seconds=55,max_tokens=1024 if realistic else 512,max_tool_calls=4 if realistic else 0)
        return {'seconds':round(time.monotonic()-started,2),'finish':result['finish_reason'],
                'calls':result['llm_api_calls'],'tools':result['tool_call_count']}
    try:
        results=await asyncio.gather(*(one(i) for i in range(count)),return_exceptions=True)
    finally:
        done=True;await watcher
    return {'concurrency':count,'context_tools':'--context' in sys.argv,'results':[str(type(r).__name__) if isinstance(r,Exception) else r for r in results],
        'passed':all(isinstance(r,dict) and r['finish']=='completed' and
                     (r['tools']>=2 if '--context' in sys.argv else True) for r in results),
        'peak_group_mib':round(max(s['memory'] for s in samples)/1048576,1),
        'peak_swap_mib':round(max(s['swap'] for s in samples)/1048576,1),
        'min_host_available_mib':round(min(s['available'] for s in samples)/1048576,1)}


parser=argparse.ArgumentParser()
parser.add_argument('--context',action='store_true')
parser.add_argument('--counts',type=int,nargs='+',choices=range(1,11))
parser.add_argument('--rounds',type=int,choices=range(1,4),default=1)
args=parser.parse_args()
for iteration in range(args.rounds):
    for count in (args.counts or ([2,3] if args.context else [1,2,3])):
        print(json.dumps(dict(asyncio.run(run(count)),round=iteration+1)),flush=True)
