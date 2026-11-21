"""Real Derpibooru bytes and real Agent choices, isolated from production chats."""
import asyncio
import importlib
import json
from pathlib import Path
from io import BytesIO
from PIL import Image
from dotenv import dotenv_values
from replay_expression_focus import ROOT, load_modules


async def main():
    modules = load_modules()
    package = modules['autonomous_normal'].__package__
    search = importlib.import_module(package + '.autonomous_web_search')
    web = importlib.import_module(package + '.autonomous_web_images')
    download = importlib.import_module(package + '.web_image_download')
    provider, downloader = search.SearxngSearch(), download.PublicImageDownloader()
    folder = ROOT / 'docs/testing/animated-images-20260912'
    folder.mkdir(exist_ok=True)
    profile = next(p for p in json.loads((ROOT / 'docs/testing/natural-curiosity-20260910/route-profiles.json').read_text(encoding='utf-8')) if p['id'] == 'fluttershy')
    env = dotenv_values(ROOT / '.env')
    key = env.get('PONYCHAT_DEEPSEEK_API_KEY') or env.get('DEEPSEEK_API_KEY')
    report_path = folder / 'real-agent.json'
    rows = json.loads(report_path.read_text(encoding='utf-8')) if report_path.exists() else []
    for animated in (True, False):
        scenario = 'animated_available' if animated else 'controlled_static_fallback'
        if any(row['scenario'] == scenario for row in rows):
            continue
        result = await provider.search_images({'query': 'fluttershy', 'derpibooru_tags': 'fluttershy', 'rating': 'safe', 'animated': animated})
        candidate, item = None, None
        for c in result['results']:
            try:
                downloaded = await downloader.download(c['image_url'])
                if downloaded.get('animated', False) == animated:
                    candidate, item = c, downloaded
                    break
            except download.ImageDownloadError:
                continue
        assert item is not None, 'No usable live candidate'
        record = {'scenario': 'animated_available' if animated else 'controlled_static_fallback',
                  'source': candidate, 'downloaded_mime': item['mime_type'],
                  'downloaded_frames': getattr(Image.open(BytesIO(item['data'])), 'n_frames', 1),
                  'search_calls': [], 'staged': [], 'calls': []}
        rows.append(record)
        class AvailableSearch:
            async def search_images(self, args):
                record['search_calls'].append(args)
                return {'status': 'success', 'results': [candidate], 'animation_fallback': not animated}
        class CachedDownload:
            async def download(self, url):
                return item
        def store(data, mime, username):
            assert data == item['data']
            record['staged'].append({'mime': mime, 'frames': getattr(Image.open(BytesIO(data)), 'n_frames', 1)})
            return '/synthetic/animation.' + ('gif' if animated else 'jpg')
        tool = web.WebImageTools(AvailableSearch(), username='synthetic-animation',
            downloader=CachedDownload(), transfer_store=store, transfer_discard=lambda *_: None)
        async def observe(prompt, config, tools, **options):
            call = {'prompt': json.loads(prompt), 'system': options['system_prompt']}
            record['calls'].append(call)
            result = await modules['harness_runtime'].run_harness_turn(prompt, config, tools, **options)
            call['final_response'] = result.get('final_response')
            return result
        result = await modules['autonomous_prompt_skills'].run_skill_turn(
            modules['autonomous_normal'].run_autonomous_turn,
            messages=[{'role': 'user', 'message_id': 'request', 'content': '找一张柔柔的安全评级动图发给我吧。'}],
            character_profile=profile['prompt'], home_profile='名称：柔柔\n物种：飞马',
            environment='当前角色是柔柔，用户是成年朋友Jason。', model_config={'api_key': key},
            speaker_character_id='fluttershy', web_image_tools=tool, harness_runner=observe)
        record['reply'] = modules['autonomous_reply'].render_envelope(json.loads(result['envelope']))
        record['repairs'] = result['output_format_repairs']
        record['tools'] = result['tool_trace']
        record['requested_animation'] = any(c.get('animated') is True for c in record['search_calls'])
        (folder/'real-agent.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:record[k] for k in ('scenario','downloaded_frames','staged','requested_animation','reply','repairs')},ensure_ascii=False),flush=True)
        tool.discard()


if __name__ == '__main__':
    asyncio.run(main())
