"""Real SDK/chat acceptance with synthetic data, checking persisted Agent logs."""
import asyncio
from collections import Counter
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys

import smoke_deployed_harness as smoke


async def exercise(workspace):
    overlay = os.environ.get('PONYCHAT_AGENT_LOG_OVERLAY')
    if overlay:
        for source in (Path(overlay)/'Backend').rglob('*.py'):
            target = workspace/source.relative_to(overlay)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    try:
        result = await smoke._exercise(workspace)
        from Backend import utils, config
        from Backend.routes.admin import llm_logs
        from Backend.routes.admin.llm_log_indexer import LLMLogIndexer, _parse_log_file
        root = Path(utils._CHAT_LOGS_DIR).resolve()
        assert root.is_relative_to(workspace.resolve())
        records = [(p, llm_logs._read_log_detail(str(p))) for p in root.rglob('*.js')]
        records = [(p,r) for p,r in records if r and 'AGENT' in r.get('stage','')]
        stages = Counter(r['stage'] for _,r in records)
        required = {'AGENT_RUN_REQUEST','AGENT_RUN_RESPONSE','AGENT_STEP_RESPONSE',
                    'AGENT_TOOL_REQUEST','AGENT_TOOL_RESULT','AGENT_EXECUTION_END','AGENT_PERSIST_RESULT'}
        assert required <= stages.keys(), 'Missing Agent stages: '+str(required-stages.keys())
        runs = [(p,r) for p,r in records if r['stage']=='AGENT_RUN_RESPONSE']
        trace_ids = {r['params']['trace_id'] for _,r in runs}
        assert len(trace_ids)==1, 'Foreground repairs lost trace association'
        trace = next(iter(trace_ids))
        assert all(r.get('params',{}).get('trace_id')==trace for _,r in records)
        assert all(r['data']['request'].get('system_prompt') and r['data']['request'].get('prompt') for _,r in runs)
        assert any(r['data']['sdk_events'] for _,r in runs)
        assert all(r['data']['llm_api_calls']>=1 for _,r in runs)
        tools = [r['data']['events'][0]['data'] for _,r in records if r['stage']=='AGENT_TOOL_RESULT']
        assert any(t['status']=='success' and t.get('result') is not None for t in tools)
        assert all(t.get('tool_call_id') and 'arguments' in t and t['latency_ms']>=0 for t in tools)
        persistence = [r['data'] for _,r in records if r['stage']=='AGENT_PERSIST_RESULT']
        assert any(p.get('save_ok') and p.get('message_ids') for p in persistence)
        indexer = LLMLogIndexer(config.DB_PATH)
        indexer.logs_root = str(root)
        await indexer.init_schema()
        await indexer.scan_all()
        with sqlite3.connect(config.DB_PATH) as conn:
            row = conn.execute("SELECT id FROM llm_log_index WHERE trace_id=? AND stage='AGENT_RUN_RESPONSE' LIMIT 1",(trace,)).fetchone()
            indexed_tokens = conn.execute('SELECT SUM(total_tokens) FROM llm_log_index WHERE trace_id=?',(trace,)).fetchone()[0]
        detail = await llm_logs.get_log_detail(row[0])
        assert detail['traceId']==trace and detail['request'].get('prompt')
        expected_tokens = sum(r['data']['usage'].get('total_tokens',0) for _,r in runs)
        assert indexed_tokens == expected_tokens, 'Agent usage double counted'
        for path,raw in records:
            assert _parse_log_file(str(path))[0]['status']==llm_logs._infer_status_from_log(raw)
        result['agent_logging'] = {'passed':True,'stages':dict(stages),'trace_id':trace,
            'tool_count':len(tools),'sdk_event_types':dict(Counter(e.get('type','') for _,r in runs for e in r['data']['sdk_events'])),
            'indexed_tokens':indexed_tokens,'run_count':len(runs),'persistence_records':len(persistence),
            'production_database_opened':False,'overlay':bool(overlay)}
        return result
    finally:
        database_module=sys.modules.get('Backend.db')
        if database_module:
            await database_module.get_database().close()
        config=sys.modules.get('Backend.config')
        if config:
            if config.httpx_client:
                await config.httpx_client.aclose()
            config._queue_listener.stop()
            config._file_handler.close()


if __name__=='__main__':
    os.environ.setdefault('PONYCHAT_SMOKE_TIMEOUT_SECONDS','300')
    os.environ.setdefault('PONYCHAT_SMOKE_CLIENT_ID','android')
    os.environ.setdefault('PONYCHAT_SMOKE_USERNAME','System')
    smoke.exercise=exercise
    raise SystemExit(smoke.main())
