"""Synthetic, non-persistent ownership checks through the real Agent and Harness."""
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

CASES = [
    ('character', 'assistant', '我拿出自己的相册给你看，里面都是旅行照片。相册还是我的相册。',
     '找找有没有你和朋友一起的照片，先聊聊，不用发图。', '相册归角色所有，放在桌上给用户看'),
    ('user', 'user', '我拿出自己的相册给你看，里面都是旅行照片。',
     '看看有没有我们一起的照片，先聊聊，不用发图。', '相册归用户所有，放在桌上给角色看'),
    ('borrow', 'user', '这本相册是你的，我只是借来翻看。',
     '我拿着相册走到窗边了。相册是谁的？', '相册归角色所有，用户正在借阅'),
    ('gift', 'assistant', '这是我的相册，我现在把它送给你了，以后它就是你的了。',
     '谢谢！现在相册是谁的？', '相册原归角色所有，角色已赠送给用户，现归用户所有'),
    ('third_party', 'assistant', '这是青禾借给我的相册，你可以拿着看。',
     '我看完了，这本相册该还给谁？', '相册归青禾所有，角色借来后给用户看'),
    ('correction', 'assistant', '你把你的相册放好了。',
     '刚才说错了，那是你的相册，我只是帮你放回桌上。现在是谁的？', '相册归用户所有，放在桌上'),
    ('container', 'assistant', '我从自己的相册里取出一张旅行照片送给你，其他照片还留在里面。',
     '现在照片是我的了，那相册也是我的吗？', '相册归角色所有，其中一张照片已赠送给用户'),
    ('sender', 'user', '我把你刚才从自己相册里拿出的照片扫描发给你了。',
     '我发的这个扫描件，原照片和相册是谁的？', '原照片及相册归角色所有，用户只扫描发送了副本'),
]


async def main(target, selected=()):
    from Backend.chat_modules.autonomous_normal import run_autonomous_turn
    from Backend.chat_modules.autonomous_prompt_skills import run_skill_turn
    from Backend.chat_modules.harness_runtime import run_harness_turn
    async def observe(*args, **kwargs):
        result = await run_harness_turn(*args, **kwargs)
        if result.get('finish_reason') != 'completed':
            print(json.dumps({'finish_reason': result.get('finish_reason'),
                              'events': [e for e in result.get('events', []) if e.get('type') == 'turn/end']}, ensure_ascii=False), flush=True)
        return result
    from Backend.config import model_manager
    model = model_manager.get_active_model()
    rows = []
    for name, role, history, latest, state in CASES:
        if selected and name not in selected:
            continue
        result = await run_skill_turn(run_autonomous_turn,
            messages=[{'role': role, 'content': history, 'message_id': 'source'},
                      {'role': 'user', 'content': latest, 'message_id': 'latest'}],
            character_profile='名称：青竹。人类成年人，直率、爱旅行和拍照，与青禾是朋友。',
            home_profile='名称：青竹\n简介：直率、爱旅行和拍照的成年人。',
            environment='双方正在共同想象的旅行书房里，讨论普通旅行相册。',
            scene_state={'revision': 1, 'fields': {'item:相册':
                         {'value': state, 'source_message_ids': ['source']}}},
            model_config=model, harness_runner=observe)
        rows.append({'case': name, 'history': history, 'latest': latest, 'state': state,
                     'raw_response': result['final_response'], 'skills': result.get('prompt_skills'),
                     'usage': result.get('usage')})
        target.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
        print(name, result['final_response'], flush=True)


if __name__ == '__main__':
    asyncio.run(main(Path(sys.argv[1]), sys.argv[2:]))
