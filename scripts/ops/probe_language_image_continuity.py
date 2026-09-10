"""Real normal Agent with synthetic history and a controlled Chinese search result."""
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
    delivery = importlib.import_module(normal.__package__ + '.autonomous_delivery')
    web = importlib.import_module(normal.__package__ + '.autonomous_web_images')
    class Search:
        async def search_images(self, args):
            return {'status': 'no_results', 'results': [], 'note': '本次受控搜索没有合适图片，请如实告知。'}
    results = []
    for name, text in [
        ('continue_english_voice', '帮我搜一张图书馆的图片发给我。简短回复一句。'),
        ('explicit_chinese', '改用中文语音，帮我搜一张图书馆图片。简短回复一句。'),
        ('text_only_preserves_language', '帮我搜一张图书馆图片，不用语音，文字回复一句就好。')]:
        history = [{'role': 'user', 'content': 'Please speak English using voice.'},
                   {'role': 'assistant', 'content': 'Of course. I will speak English.', 'voice_status': 'ready'}]
        guidance = delivery.agent_delivery_guidance(history, speaker='test', main='test')
        started = time.monotonic()
        result = await skills.run_skill_turn(normal.run_autonomous_turn,
            messages=history + [{'role': 'user', 'content': text, 'message_id': name}],
            character_profile='青竹是一位成年图书管理员，认真友善。',
            home_profile='名称：青竹\n简介：成年图书管理员，认真友善。',
            environment=guidance, delivery_guidance=guidance, model_config={'api_key': key},
            web_image_tools=web.WebImageTools(Search(), username='synthetic-language-test'))
        row = {'case': name, 'input': text, 'envelope': json.loads(result['envelope']),
               'repairs': result['output_format_repairs'], 'tools': result['tool_trace'],
               'seconds': round(time.monotonic()-started, 2)}
        results.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    (ROOT / 'docs/testing/language-image-continuity-20260910.json').write_text(
        json.dumps({'scope': 'Real normal Agent, synthetic history, controlled search; no production DB or TTS.',
                    'results': results}, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    asyncio.run(main())
