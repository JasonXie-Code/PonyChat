"""Four real Agent searches, downloads, visual selections and staged image artifacts."""
import asyncio
import importlib
import json
import os
import time

from replay_expression_focus import ROOT, load_modules


async def main():
    from dotenv import dotenv_values
    env = dotenv_values(ROOT / '.env')
    key = env.get('PONYCHAT_DEEPSEEK_API_KEY') or env.get('DEEPSEEK_API_KEY')
    assert key
    modules = load_modules()
    normal, skills = modules['autonomous_normal'], modules['autonomous_prompt_skills']
    web = importlib.import_module(normal.__package__ + '.autonomous_web_images')
    search = importlib.import_module(normal.__package__ + '.autonomous_web_search')
    output = ROOT / 'docs/testing/g4-image-defaults-20260910'
    (output / 'images').mkdir(parents=True, exist_ok=True)
    only = os.environ.get('G4_IMAGE_CASE')
    reports = json.loads((output / 'four-images.json').read_text(encoding='utf8'))['cases'] if only else []
    for name, tags, bio in [
        ('pinkie', 'pinkie pie', '碧琪，粉色陆马，卷曲的深粉色鬃毛，外向开朗。'),
        ('twilight', 'twilight sparkle', '暮光闪闪，紫色独角兽小马，深蓝色鬃毛有紫粉色条纹，认真友善。'),
        ('rainbow', 'rainbow dash', '云宝，蓝色飞马，彩虹色鬃毛，大胆直率。'),
        ('fluttershy', 'fluttershy', '柔柔，黄色飞马，粉色长鬃毛，温柔害羞。'),
    ]:
        if only and name != only:
            continue
        reports = [r for r in reports if r['case'] != name]
        staged = []
        def store(data, mime, username):
            suffix = '.png' if mime == 'image/png' else '.jpg'
            path = output / 'images' / (name + '-' + str(len(staged)+1) + suffix)
            path.write_bytes(data)
            staged.append(str(path))
            return '/chat_images/synthetic-' + name + '-' + str(len(staged))
        tool = web.WebImageTools(search.SearxngSearch(), username='g4-style-test',
                                transfer_store=store, transfer_discard=lambda *_: None)
        started = time.monotonic()
        result = await skills.run_skill_turn(normal.run_autonomous_turn,
            messages=[{'role': 'user', 'content': '去网上找一张你自己的图片发给我，选你觉得合适的一张。',
                       'message_id': name}],
            character_profile='你是' + bio, home_profile='名称：' + bio.split('，')[0] + '\n简介：' + bio,
            environment='', model_config={'api_key': key}, web_image_tools=tool)
        selected = [tool.candidates[ref] for ref in tool.selected]
        trace = result['tool_trace']
        calls = [t['arguments'] for t in trace if t.get('tool') == 'search_images']
        passed = len(staged) == 1 and bool(selected) and all(
            c.get('style', 'g4_pony') == 'g4_pony' and tags in c.get('derpibooru_tags', '') for c in calls)
        row = {'case': name, 'passed': passed, 'images': staged, 'selected': selected,
               'tool_trace': trace, 'envelope': json.loads(result['envelope']),
               'seconds': round(time.monotonic()-started, 2)}
        reports.append(row)
        (output / 'four-images.json').write_text(json.dumps({'passed': all(r['passed'] for r in reports),
            'scope': 'Real Agent and live online image search/download; synthetic staging; no production account writes.',
            'cases': reports}, ensure_ascii=False, indent=2), encoding='utf8')
        print(json.dumps({'case': name, 'passed': passed, 'images': staged,
                          'sources': [s['source_url'] for s in selected]}, ensure_ascii=False), flush=True)
    assert len(reports) == 4 and all(r['passed'] for r in reports)


if __name__ == '__main__':
    asyncio.run(main())
