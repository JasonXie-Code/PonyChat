"""Real-model finalization after controlled exploration expiry; no user writes."""
import asyncio
import importlib
import json
import time
import os
from replay_expression_focus import ROOT, load_modules


async def main():
    from dotenv import dotenv_values
    env = dotenv_values(ROOT / '.env')
    key = env.get('PONYCHAT_DEEPSEEK_API_KEY') or env.get('DEEPSEEK_API_KEY')
    assert key
    modules = load_modules()
    normal, skills, runtime = (modules[n] for n in ('autonomous_normal', 'autonomous_prompt_skills', 'harness_runtime'))
    web = importlib.import_module(normal.__package__ + '.autonomous_web_images')
    download = importlib.import_module(normal.__package__ + '.web_image_download')
    pixels = download.normalize_image((ROOT / 'var/qa/pinkie-images/1668671.jpg').read_bytes())
    report = {'scope': 'Controlled exploration expiry; real Agent/model selection, real cached safe pixels and staging; synthetic transfer, no production DB or physical phone acceptance.', 'cases': []}
    path = ROOT / os.environ.get('PONYCHAT_IMAGE_PROBE_REPORT', 'docs/testing/image-delivery-budget-20260910/real-model.json')
    style_probe = os.environ.get('PONYCHAT_IMAGE_PROBE_STYLE') == '1'
    profile, home = '青竹是成年图书管理员，认真友善。', '名称：青竹\n简介：成年图书管理员。'
    cases = [('send_cached', '请发一张碧琪微笑的safe图片给我，近似的也可以。'),
             ('respect_exact', '发一张碧琪safe图片，必须完整全身，不能是半身或头像；找不到就不要发。')]
    if style_probe:
        characters = json.loads((ROOT / 'docs/testing/natural-curiosity-20260910/route-profiles.json').read_text(encoding='utf-8'))
        character = next(c for c in characters if c['id'] == 'pinkie_pie')
        profile, home = character['prompt'], character['profileIntro']
        cases = [('style_voice', '碧琪，发一张能表现你开心心情的图片给我，顺便说说是不是你们那里的画风。'),
                 ('explicit_source', '找一张碧琪的图片发给我。从现实绘画角度解释它是不是2D矢量风格，以及能否确认是官方出品。')]
    path.parent.mkdir(parents=True, exist_ok=True)
    for name, request in cases:
        transfers, attempts = [], []
        def store(data, mime, user):
            transfers.append({'bytes': len(data), 'mime': mime})
            return '/chat_images/synthetic-budget-test'
        images = web.WebImageTools(None, username='synthetic', transfer_store=store,
                                   transfer_discard=lambda *args: None)
        images.candidates['web:fixture'] = {'title': 'Pinkie Pie smiling close-up with invitation; not full body',
                                          'source_url': 'https://derpibooru.org/images/1668671'}
        images.downloaded['web:fixture'] = pixels
        async def runner(prompt, config, tools, **options):
            if not attempts:
                # Exercise the real read/observation path with already-downloaded pixels.
                await tools['read_web_image'].callback({'image_ref': 'web:fixture'})
                options['tool_budget_state'].update(calls=12, deadline=time.monotonic()-1)
                attempts.append({'controlled_exploration_expiry': True})
                return {'finish_reason': 'tool_time_budget_exhausted', 'final_response': '', 'llm_api_calls': 0}
            entry = {'tools': list(tools), 'timeout_seconds': options['timeout_seconds']}
            attempts.append(entry)
            result = await runtime.run_harness_turn(prompt, config, tools, **options)
            entry.update({k: result.get(k) for k in ('final_response', 'finish_reason', 'llm_api_calls', 'tool_call_count')})
            return result
        result = await skills.run_skill_turn(normal.run_autonomous_turn,
            messages=[{'role': 'user', 'content': request, 'message_id': name}],
            character_profile=profile, home_profile=home,
            environment='', model_config={'api_key': key}, web_image_tools=images, harness_runner=runner)
        row = {'case': name, 'input': request, 'attempts': attempts, 'transfers': transfers,
               'selected': images.selected, 'envelope': json.loads(result['envelope']), 'trace': result['tool_trace']}
        row['passed'] = not transfers if name == 'respect_exact' else bool(transfers)
        report['cases'].append(row)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'case': name, 'passed': row['passed'], 'transfers': len(transfers)}, ensure_ascii=False), flush=True)
    assert all(c['passed'] for c in report['cases'])


if __name__ == '__main__':
    asyncio.run(main())
