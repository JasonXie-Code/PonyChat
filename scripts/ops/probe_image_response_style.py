"""Compare contextual image reactions with explicitly requested visual description."""
import asyncio
import base64
import json
import sys
from replay_expression_focus import ROOT, load_modules


async def main():
    from dotenv import dotenv_values
    env = dotenv_values(ROOT / '.env')
    key = env.get('PONYCHAT_DEEPSEEK_API_KEY') or env.get('DEEPSEEK_API_KEY')
    assert key
    modules = load_modules()
    profiles = json.loads((ROOT / 'docs/testing/natural-curiosity-20260910/route-profiles.json').read_text(encoding='utf-8'))
    character = next(c for c in profiles if c['id'] == 'twilight_sparkle')
    pixels = (ROOT / 'var/qa/pinkie-images/1668671.jpg').read_bytes()
    blocks = [{'type': 'image', 'mimeType': 'image/jpeg', 'data': base64.b64encode(pixels).decode('ascii')}]
    cases = [('reaction', '[发送表情包]'),
             ('describe_conflicting_label', '请描述这张表情包里实际画了什么。附件标签写着：蓝色小马在哭。标签不一定准确。')]
    report = {'scope': 'Real Agent and actual sticker pixels; synthetic conversation, no production DB. Same image for both tasks.', 'cases': []}
    path = ROOT / sys.argv[1]
    path.parent.mkdir(parents=True, exist_ok=True)
    for name, text in cases:
        attempts = []
        async def observed(prompt, config, tools, **options):
            result = await modules['harness_runtime'].run_harness_turn(prompt, config, tools, **options)
            attempts.append({'native_images': sum(b.get('type') == 'image' for b in prompt) if isinstance(prompt, list) else 0,
                             **{k: result.get(k) for k in ('final_response', 'finish_reason', 'tool_call_count')}})
            return result
        result = await modules['autonomous_prompt_skills'].run_skill_turn(modules['autonomous_normal'].run_autonomous_turn,
            messages=[{'role': 'user', 'content': '我今天终于把拖了很久的事情做完了，开心！', 'message_id': 'before'},
                      {'role': 'assistant', 'content': '终于完成了！我也替你高兴。'},
                      {'role': 'user', 'content': text, 'message_id': name}],
            character_profile=character['prompt'], home_profile=character['profileIntro'],
            environment='', model_config={'api_key': key}, current_image_blocks=blocks, harness_runner=observed)
        report['cases'].append({'case': name, 'input': text, 'attempts': attempts, 'envelope': json.loads(result['envelope'])})
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(name+' complete', flush=True)


if __name__ == '__main__':
    asyncio.run(main())
