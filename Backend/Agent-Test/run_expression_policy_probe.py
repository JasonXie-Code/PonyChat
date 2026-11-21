"""Real-model expression checks with synthetic chats and a controlled sticker fixture.

Uses cached public character profiles. Does not read/write production chats or
send attachments to a user; the fixture only tests the Agent's modality choice.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time

from run_harness_comparison import initialize, ROOT


SCENARIOS = [
    ('shared_joke', '我刚把一张空白纸也认真归档了，哈哈，又是我们那个一本正经的小糊涂梗！请只回复一段简短的话。'),
    ('celebration', '我准备了好久的第一次舞台演出终于顺利完成啦！现在特别开心，第一时间就想和你分享。请只回复一段简短的话。'),
    ('information', '请只回复一段简短的话，告诉我整理书架时怎样方便找到需要的书。'),
    ('vulnerable', '今天被朋友误会了，很难过，不想听建议，只想你认真陪我一会儿。请只回复一段简短的话。'),
    ('cooldown', '又有一个好消息，我还收到了朋友们的祝福！请只回复一段简短的话。'),
]


async def check_case(character, scenario, user_text, cfg):
    from Backend.chat_modules.autonomous_normal import run_autonomous_turn
    from Backend.chat_modules.autonomous_reply import render_envelope
    from Backend.chat_modules.autonomous_stickers import AgentStickerTools
    from Backend.chat_modules.expression_context import build_expression_context, emoji_symbols
    profile = str(character.get('persona_prompt') or character.get('prompt') or '')
    if not profile:
        raise ValueError('Missing cached public persona')
    cid = character['id']
    history = []
    if scenario == 'shared_joke':
        history = [
            {'role': 'user', 'content': '我喜欢你偶尔用适合的表情接我们的小玩笑，比如咱们刚刚聊的一本正经的小糊涂梗。'},
            {'role': 'assistant', 'content': '一本正经的小糊涂，听起来就是忙着把空白纸也按颜色归档的样子', 'speaker_character_id': cid},
        ]
    if scenario == 'cooldown':
        history = [{'role': 'user', 'content': '我的演出完成了！'},
                   {'role': 'assistant', 'content': '太棒啦，你做到了！🎉', 'speaker_character_id': cid},
                   {'role': 'assistant', 'content': '我也替你开心', 'speaker_character_id': cid}]
    messages = [*history, {'role': 'user', 'content': user_text, 'message_id': f'synthetic-{cid}-{scenario}'}]

    async def candidates(query, tags, selected):
        intro = ('当前角色抱着空白纸假装认真归档，自己忍不住笑起来；温和自嘲，承接一本正经的小糊涂共同玩笑，无贬低含义'
                 if scenario == 'shared_joke' else '当前角色微笑并开心庆祝，适合分享好消息；不含文字或讽刺')
        return [{'ref': 'fixture:happy', 'asset_id': 'fixture-happy',
                 'name': f'受控测试素材：{character["name"]}轻松反应',
                 'intro': intro,
                 'detail': '仅供本地测试选择，无真实交付', 'emotions': ['开心', '庆祝']}]

    def attachment(candidate, request):
        return {'type': 'sticker', 'asset_id': candidate['asset_id'],
                'metadata': {'request_id': request['request_id']}}

    stickers = AgentStickerTools(candidates, attachment)
    started = time.monotonic()
    result = await run_autonomous_turn(
        messages=messages, character_profile=profile,
        environment='合成测试：用户为成年朋友，正常日间聊天，无已知长期表情偏好。',
        model_config=cfg, sticker_tools=stickers, speaker_character_id=cid)
    envelope = json.loads(result['envelope'])
    text = render_envelope(envelope)
    symbols = emoji_symbols(text)
    selected = [event for event in result['tool_trace'] if event['tool'] == 'stage_sticker'
                and event['success'] and event['arguments'].get('asset_ref')]
    mode = 'both' if symbols and selected else 'emoji' if symbols else 'sticker' if selected else 'text'
    passed = len(envelope['bubbles']) == 1
    if scenario in {'information', 'vulnerable', 'cooldown', 'explicit_none'}:
        passed = passed and mode == 'text'
    elif scenario == 'explicit_both':
        passed = passed and mode == 'both'
    elif scenario == 'shared_joke':
        passed = passed and mode in {'emoji', 'sticker'}
    else:
        passed = passed and mode != 'both'  # Eligibility never forces an expression.
    return {'character_id': cid, 'character': character['name'], 'scenario': scenario,
            'input': user_text, 'text': text, 'mode': mode, 'emoji': symbols,
            'passed_hard_expectations': passed, 'seconds': round(time.monotonic()-started, 2),
            'profile_sha256': hashlib.sha256(profile.encode()).hexdigest(),
            'history_context': build_expression_context(history, speaker_character_id=cid),
            'tools': result['tool_trace'], 'llm_api_calls': result['llm_api_calls'],
            'output_format_repairs': result['output_format_repairs'], 'usage': result['usage']}


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default=str(ROOT / 'Backend/Agent-Test/reports/expression-policy-20260906.json'))
    parser.add_argument('--case', choices=[s[0] for s in SCENARIOS])
    args = parser.parse_args()
    profiles = json.loads((ROOT / 'Backend/Agent-Test/cache/system_characters.json').read_text(encoding='utf8'))
    profiles = [next(c for c in profiles if c['id'] == cid) for cid in ('pinkie_pie', 'twilight_sparkle')]
    report = {'model': 'deepseek-flash', 'reasoning_effort': 'low',
              'scope': '真实 Harness/模型，缓存公开角色设定，合成聊天与受控图片候选；不发送用户消息、不写生产聊天或记忆，不作为频率百分比统计。',
              'cases': []}
    output = Path(args.output)
    with tempfile.TemporaryDirectory(prefix='ponychat-expression-probe-') as directory:
        try:
            api = initialize(Path(directory))
            cfg = api[-1]
            for scenario, user_text in SCENARIOS:
                if args.case and scenario != args.case:
                    continue
                for character in profiles:
                    print('Running:', character['id'], scenario, flush=True)
                    result = await check_case(character, scenario, user_text, cfg)
                    report['cases'].append(result)
                    output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf8')
                    print('Completed:', result['character_id'], result['scenario'], result['mode'], result['passed_hard_expectations'], flush=True)
            for scenario, user_text in [
                ('explicit_both', '请用一张开心的表情包和一个合适的emoji向我打招呼，文字只回复一段。'),
                ('explicit_none', '我成功完成了演出，太开心了！这次不要emoji和表情包，只用一段文字和我庆祝。'),
            ]:
                if args.case:
                    continue
                print('Running: twilight_sparkle', scenario, flush=True)
                result = await check_case(profiles[1], scenario, user_text, cfg)
                report['cases'].append(result)
                output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf8')
                print('Completed:', scenario, result['mode'], result['passed_hard_expectations'], flush=True)
        finally:
            config = sys.modules.get('Backend.config')
            if config is not None:
                if config.httpx_client is not None:
                    await config.httpx_client.aclose()
                config._queue_listener.stop()
                for handler in config._queue_listener.handlers:
                    handler.close()
    if not all(case['passed_hard_expectations'] for case in report['cases']):
        raise RuntimeError('Inspect failed expression expectations in the report')


if __name__ == '__main__':
    asyncio.run(main())
