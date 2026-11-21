"""Exercise deployed fixes with synthetic data in the existing isolated smoke harness."""
import asyncio
import json
import os
from pathlib import Path
import sqlite3
import sys
import time

import smoke_deployed_harness as smoke


async def exercise(workspace):
    try:
        result = await smoke._exercise(workspace)
        assert result['passed'], 'Foreground chat smoke failed'
        from Backend import config, utils, character_voice_registration as voice
        from Backend.db import CharactersDAO, get_database
        from Backend.routes.admin.characters import edit_character
        from Backend.routes.admin.llm_log_indexer import LLMLogIndexer
        from Backend.chat_modules.harness_runtime import HarnessTool, run_harness_turn
        from Backend.agent_memory import jobs, evidence
        from datetime import datetime

        db = get_database()
        assert Path(db.db_path).resolve().is_relative_to(workspace.resolve())
        username = result['request']['username']
        assert username == 'System'
        uid = await db.get_user_id(username)
        os.environ['PONYCHAT_VOICE_ENABLED'] = '1'
        admin_results = []
        for mode in ('instruct', 'clone'):
            char_id = 'synthetic_logfix_'+mode
            profile_id = 'ponyvoice:'+char_id
            assert await CharactersDAO(db).save_characters(username,[{'id':char_id,'name':'测试角色','prompt':'合成测试'}])
            if mode == 'instruct':
                # A cached design recipe exercises real DB writes without creating
                # an external voice or sending any reference audio.
                await voice.upsert_character_voice_profile(db,username=username,character_id=char_id,
                    voice_profile_id=profile_id,source_mode=mode,description='calm test voice',
                    qwen_cached_voice_id='synthetic-cache',clone_status='design_registered')
            else:
                with sqlite3.connect(db.db_path) as conn:
                    conn.execute('INSERT INTO character_voice_assets(filename,user_id,data,transcript) VALUES(?,?,?,?)',
                                 ('synthetic.mp3',uid,b'synthetic-audio','synthetic reference'))
            began = time.monotonic()
            edited = await asyncio.wait_for(edit_character({'character_id':char_id,'voiceSourceMode':mode,
                'voiceProfileId':profile_id,'voiceInstruct':'calm test voice','voiceEnabled':True,
                'voiceReferenceAudioUrl':'/synthetic.mp3','voiceReferenceText':'synthetic reference'}),10)
            assert edited['success']
            with sqlite3.connect(db.db_path) as conn:
                char = json.loads(conn.execute('SELECT data FROM characters WHERE id=?',(char_id,)).fetchone()[0])
                assert char['voiceCloneStatus'] in ('design_registered','recipe_ready')
                assert conn.execute('SELECT 1 FROM character_voice_profiles WHERE voice_profile_id=?',(profile_id,)).fetchone()
            admin_results.append({'mode':mode,'passed':True,'seconds':round(time.monotonic()-began,3)})
        os.environ['PONYCHAT_VOICE_ENABLED'] = '0'

        model = config.model_manager.get_model_for_task('normal')
        calls = []
        async def probe(args):
            calls.append(args)
            return {'probe':len(calls), 'instruction':'Continue with the next numbered probe only if budget remains.'}
        probe_result = await run_harness_turn('依次调用probe检查步骤1、2、3，遵守工具预算；不能执行的步骤留给下一轮。最后只输出JSON说明完成情况。',
            model, {'probe':HarnessTool(probe,'Execute a synthetic numbered probe.',{
                'type':'object','properties':{'step':{'type':'integer','minimum':1,'maximum':3}},'required':['step']})},
            max_tool_calls=1,stop_on_tool_budget=True,timeout_seconds=90)
        assert len(calls) == 1 and probe_result['tool_call_count'] == 1
        assert probe_result['finish_reason'] in ('completed','tool_budget_exhausted')
        assert probe_result['llm_api_calls'] > 0

        jobs.initialize(db.db_path)
        jobs.enqueue(db.db_path,username,result['request']['character_id'],immediate=True,
            target_period={'category':'daily','period':datetime.now(evidence.LOCAL).date().isoformat()})
        async def profile(*_):
            return '你叫云杉，是成年独角兽小马。温和、简洁地陪用户聊天。'
        review = await jobs.run_one(db.db_path,model,profile,username=username,
                                   character_id=result['request']['character_id'])
        assert review is not None and review['saved']
        assert any(item['category']=='daily' for item in review['saved'])
        assert not any(not item['success'] for item in review['tools'])
        indexer = LLMLogIndexer(db.db_path)
        indexer.logs_root = str(utils._CHAT_LOGS_DIR)
        assert Path(indexer.logs_root).resolve().is_relative_to(workspace.resolve())
        await indexer.init_schema()
        first, second = await indexer.scan_all(), await indexer.scan_all()
        assert first['success'] and second['success'] and second['entries_inserted'] == 0
        result['log_fixes'] = {'passed':True,'admin_edits':admin_results,
            'budget_probe':{'finish_reason':probe_result['finish_reason'],'tool_call_count':probe_result['tool_call_count'],
                            'llm_api_calls':probe_result['llm_api_calls'],'usage':probe_result['usage']},
            'memory_review':{'status':review['status'],'needs_more':review['needs_more'],
                             'saved_categories':[item['category'] for item in review['saved']],
                             'llm_api_calls':review['llm_api_calls'],'tool_trace':review['tools']},
            'index_first':first,'index_second':second,'production_database_opened':False}
        return result
    finally:
        db_module = sys.modules.get('Backend.db')
        if db_module:
            await db_module.get_database().close()
        config = sys.modules.get('Backend.config')
        if config:
            if config.httpx_client:
                await config.httpx_client.aclose()
            config._queue_listener.stop()
            config._file_handler.close()


if __name__ == '__main__':
    os.environ.setdefault('PONYCHAT_SMOKE_USERNAME','System')
    os.environ.setdefault('PONYCHAT_SMOKE_CLIENT_ID','android')
    os.environ.setdefault('PONYCHAT_SMOKE_TIMEOUT_SECONDS','480')
    smoke.exercise = exercise
    raise SystemExit(smoke.main())
