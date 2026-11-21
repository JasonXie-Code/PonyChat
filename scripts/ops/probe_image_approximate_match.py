"""Real Agent visual-selection probe with a downloaded safe image; no user writes."""
import asyncio
import importlib
import json
import time
from replay_expression_focus import ROOT, load_modules


async def main():
    from dotenv import dotenv_values
    env = dotenv_values(ROOT / '.env')
    key = env.get('PONYCHAT_DEEPSEEK_API_KEY') or env.get('DEEPSEEK_API_KEY')
    if not key:
        raise RuntimeError('Missing credential')
    modules = load_modules()
    normal, skills = modules['autonomous_normal'], modules['autonomous_prompt_skills']
    web = importlib.import_module(normal.__package__ + '.autonomous_web_images')
    downloads = importlib.import_module(normal.__package__ + '.web_image_download')
    raw = (ROOT / 'var/qa/pinkie-images/1668671.jpg').read_bytes()
    class Search:
        async def search_images(self, args):
            return {'status': 'success', 'results': [{'title': 'Pinkie Pie solo smiling close-up with invitation; not full body',
                'image_url': 'https://derpicdn.net/controlled-fixture.jpg',
                'source_url': 'https://derpibooru.org/images/1668671', 'rating': 'safe', 'score': 2684}],
                'note': 'Controlled fixture; only this close-up candidate is available.'}
    class Downloader:
        def __init__(self, fail): self.fail = fail
        async def download(self, url):
            if self.fail:
                raise downloads.ImageDownloadError('download_unavailable')
            return downloads.normalize_image(raw)
    results = []
    for name, text, fail in [
        ('closest_available', '找一张碧琪全身、单人、微笑的safe图片给我。', False),
        ('required_full_body', '找碧琪safe图片，必须全身，不能是半身或头像；找不到就不要发。', False),
        ('download_failure', '找一张碧琪微笑的safe图片给我，近似的也可以。', True)]:
        staged = []
        def store(data, mime, username):
            staged.append({'bytes': len(data), 'mime': mime})
            return '/chat_images/controlled-test'
        tool = web.WebImageTools(Search(), username='synthetic-image-match',
            downloader=Downloader(fail), transfer_store=store, transfer_discard=lambda key, user: None)
        history = [{'role': 'user', 'content': 'Please speak English using voice.'},
                   {'role': 'assistant', 'content': 'Of course, I will speak English.', 'voice_status': 'ready'},
                   {'role': 'user', 'content': text, 'message_id': name}]
        guidance = '【当前角色回复状态】\n' + json.dumps({'previous_reply_language': 'English',
            'voice_reply': True, 'has_delivery_history': True, 'has_language_history': True})
        started = time.monotonic()
        result = await skills.run_skill_turn(normal.run_autonomous_turn, messages=history,
            character_profile='青竹是一位成年图书管理员，认真友善。',
            home_profile='名称：青竹\n简介：成年图书管理员，认真友善。',
            environment=guidance, delivery_guidance=guidance, model_config={'api_key': key}, web_image_tools=tool)
        row = {'case': name, 'input': text, 'staged': staged, 'tools': result['tool_trace'],
               'envelope': json.loads(result['envelope']), 'seconds': round(time.monotonic()-started, 2)}
        results.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    (ROOT / 'docs/testing/image-approximate-match-v2-20260910.json').write_text(json.dumps({
        'scope': 'Real Agent, controlled search/download, real safe pixels; no production DB, phone delivery or TTS.',
        'results': results}, ensure_ascii=False, indent=2), encoding='utf-8')
    assert 1 <= len(results[0]['staged']) <= 2
    assert not results[1]['staged'] and not results[2]['staged']
    for row in results:
        assert row['envelope']['reply_language']['language'].lower() in {'english', 'en', 'en-us', 'en-gb'}
        assert row['envelope']['voice_reply']['enabled'] is True


if __name__ == '__main__':
    asyncio.run(main())
