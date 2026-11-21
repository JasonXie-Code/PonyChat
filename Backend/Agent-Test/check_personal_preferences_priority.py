"""Synthetic real-Agent probe; never opens user history or changes saved settings."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys
import tempfile

from run_harness_comparison import initialize

PROFILE = "成年角色星铃，陆马，图书管理员。内向害羞、不善主动，总是等朋友发出邀请。"
PREFERENCE = "你要主动邀请我一起做具体的事并率先行动，不要等我推动，不要反复犹豫或询问许可。"
USER = "今天工作结束了，接下来没什么安排。"


async def main():
    output = Path(sys.argv[1] if len(sys.argv) > 1 else '.tmp/preference-priority-probe.json')
    report = {"scope": "合成成年角色；真实 Agent 调用；游戏使用精简台词阶段输入；不修改用户数据。", "cases": []}
    with tempfile.TemporaryDirectory(prefix='ponychat-preference-probe-', ignore_cleanup_errors=True) as folder:
        api = initialize(Path(folder))
        cfg = api[-1]
        from Backend.chat_modules.autonomous_normal import run_autonomous_turn
        from Backend.chat_modules.personal_preferences import personal_preferences_prompt
        from Backend.galgame import harness
        from Backend import config

        async def noop(*args, **kwargs):
            pass

        harness._save_chat_debug_if_requested = noop
        harness._apply_usage_metering = noop
        try:
            for mode in ('normal', 'galgame', 'galgame_lock'):
                for enabled in (False, True):
                    pref = personal_preferences_prompt(
                        {"personal_preferences": {"synthetic": {mode: PREFERENCE}}}, 'synthetic', mode)
                    print('RUN', mode, 'priority' if enabled else 'background', flush=True)
                    if mode == 'normal':
                        result = await run_autonomous_turn(
                            messages=[{"role": "user", "content": USER, "message_id": "synthetic-latest"}],
                            character_profile=PROFILE, environment='图书馆门口，朋友关系。' + ('' if enabled else '\n' + PREFERENCE),
                            personal_preferences=pref if enabled else '', model_config=cfg)
                        reply = result['envelope']
                    else:
                        async def preferences(*args):
                            return pref if enabled else ''
                        harness.load_personal_preferences_prompt = preferences
                        messages = [
                            {"role": "system", "content": "扮演给定角色，保持角色性格，输出本阶段两三句中文台词与动作。禁止替用户行动。角色：" + PROFILE},
                            {"role": "user", "content": USER + ('' if enabled else '\n背景资料中的个人偏好：' + PREFERENCE)}]
                        result = await harness.call_game_harness(
                            {'messages': messages, 'max_tokens': 1200}, cfg, mode=mode, timeout=120,
                            chat_debug_request={'username': 'synthetic', 'character_id': 'synthetic', 'stage': 'PREFERENCE_PROBE'})
                        reply = result.text
                    report['cases'].append({'mode': mode, 'priority_enabled': enabled, 'reply': reply})
                    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
                    print('DONE', mode, enabled, flush=True)
        finally:
            if config.httpx_client is not None:
                await config.httpx_client.aclose()
            config._queue_listener.stop()
            for handler in config._queue_listener.handlers:
                handler.close()


if __name__ == '__main__':
    asyncio.run(main())
