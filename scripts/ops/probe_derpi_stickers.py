"""Real normal Agent, live Derpibooru search and downloads; no production chat writes."""
import argparse
import asyncio
import hashlib
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

from dotenv import dotenv_values
from replay_expression_focus import ROOT, load_modules


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--case', choices=['direct', 'empty_catalog', 'spontaneous'], default='direct')
    args = parser.parse_args()
    folder = args.output
    folder.mkdir(parents=True, exist_ok=True)
    env = dotenv_values(ROOT / '.env')
    key = env.get('PONYCHAT_DEEPSEEK_API_KEY') or env.get('DEEPSEEK_API_KEY')
    assert key
    modules = load_modules()
    package = modules['autonomous_normal'].__package__
    search = importlib.import_module(package + '.autonomous_web_search')
    web = importlib.import_module(package + '.autonomous_web_images')
    stickers = importlib.import_module(package + '.autonomous_stickers')
    report = {'case': args.case, 'searches': [], 'downloads': [], 'staged': [],
              'catalog_queries': [], 'scope': 'Real Agent and live network; synthetic conversation and local file receipt.'}

    class Search(search.SearxngSearch):
        async def search_images(self, arguments):
            result = await super().search_images(arguments)
            report['searches'].append({'arguments': arguments, 'status': result.get('status'),
                                      'results': result.get('results', [])})
            return result

    class Downloader(web.PublicImageDownloader):
        async def download(self, url):
            item = await super().download(url)
            report['downloads'].append({'url': url, 'width': item['width'], 'height': item['height'],
                                        'mime': item['mime_type'], 'sha256': hashlib.sha256(item['data']).hexdigest()})
            return item

    def store(data, mime, username):
        digest = hashlib.sha256(data).hexdigest()
        path = folder / (digest + ('.gif' if mime == 'image/gif' else '.jpg'))
        path.write_bytes(data)
        report['staged'].append({'sha256': digest, 'mime': mime, 'bytes': len(data)})
        return '/synthetic/' + path.name

    async def empty(query, tags, selected):
        report['catalog_queries'].append({'query': query, 'tags': tags})
        return []

    tool = web.WebImageTools(Search(), username='synthetic-derpi-sticker', downloader=Downloader(),
                            transfer_store=store, transfer_discard=lambda *_: None)
    catalog = stickers.AgentStickerTools(empty, lambda *_: None)
    cases = {
        'direct': '发一张紫悦开心的表情包吧，直接按呆站标签找，普通安全评级就好。',
        'empty_catalog': '发一张紫悦开心的表情包庆祝一下吧！库里没有合适的也没关系，找张贴合的。',
        'spontaneous': '哈哈哈哈，真的一次过了！终于把那个卡了我们一周的超级难题搞定啦！这次必须庆祝！',
    }
    profile = '你是紫悦，成年天角兽，热爱学习和魔法。现在刚和朋友解决困扰已久的难题，非常兴奋，愿意分享喜悦。'
    messages = [{'role': 'user', 'content': '那个难题总让我想起小马捧脸星星眼的庆祝反应图，太逗了。我喜欢这种图梗。'},
                {'role': 'assistant', 'content': '等我们成功解出来，这个梗就应景了。'},
                {'role': 'user', 'content': cases[args.case], 'message_id': 'synthetic-sticker-request'}]
    try:
        result = await modules['autonomous_prompt_skills'].run_skill_turn(
            modules['autonomous_normal'].run_autonomous_turn,
            messages=messages, character_profile=profile,
            home_profile='名称：紫悦；物种：天角兽；成年。',
            environment='用户是成年朋友。当前是普通对话，最近没有发送emoji或表情包。',
            model_config={'api_key': key}, sticker_tools=catalog, web_image_tools=tool,
            speaker_character_id='twilight_sparkle')
        report['envelope'] = json.loads(result['envelope'])
        report['tool_trace'] = result['tool_trace']
        request = SimpleNamespace()
        catalog.apply_to_request(request, result['bubble_count'])
        tool.apply_to_request(request, result['bubble_count'])
        report['attachments'] = request._assistant_asset_attachments
        report['passed'] = bool(report['attachments']) and all(
            item['metadata'].get('purpose') == 'sticker' and 'derpibooru.org/' in item['metadata']['source_url']
            for item in report['attachments'])
    except Exception as exc:
        report.update(passed=False, error=type(exc).__name__ + ': ' + str(exc))
    finally:
        tool.discard()
        (folder / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: report.get(k) for k in ['case', 'passed', 'error', 'staged', 'attachments', 'envelope']}, ensure_ascii=False), flush=True)
    assert report['passed'], 'Real Agent did not deliver a Derpibooru sticker; inspect result.json'


if __name__ == '__main__':
    asyncio.run(main())
