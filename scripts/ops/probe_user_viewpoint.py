"""Synthetic before/after real-Harness pronoun checks; no production database."""
import asyncio
import argparse
import json
from pathlib import Path
import time

from replay_expression_focus import ROOT, load_modules, constant_at

CASES = [
    ('thought', '你是成年图书管理员青竹，我是来访的成年朋友小林。刚才我帮你整理完书架。请只写两段你此刻的心理描写，不要台词，每段不超过50字。'),
    ('action', '你是青竹，我是小林。我们在图书馆，你找到我想看的书了。写一段动作和一段心理，每段不超过50字。'),
    ('third_party', '你是青竹，我是小林。我的朋友阿明刚离开图书馆，他把伞忘在这里；我帮你整理好了书架。请分别对我表达感谢，并说说阿明忘带伞这件事。两段，每段不超过50字。'),
    ('history_bias', '你是青竹，我是小林。上一条你写了：（我想到他刚才帮忙整理书架，心里很感激。）现在我把分类标签递给你。请继续只写两段心理描写，每段不超过50字。'),
]

EXTRA_CASES = [
    ('parenthesized_thought', '你是成年图书管理员青竹，我是成年朋友小林。今天你工作很累，我默默替你收好散落的书。只用括号写两段此刻的心理独白，每段不超过50字。'),
    ('memory', '你是青竹，我是小林。昨天我在雨里给你送了一把蓝伞，今天我来还书。请用角色视角回忆昨天这件事，写一段心理与一段动作，每段不超过50字。'),
    ('imagination', '你是青竹，我是小林。我刚邀请你明天一起去植物园，你还没答应。请写你想象明天同行时的心理活动，明确只是想象，最多两段。'),
    ('two_third_parties', '你是青竹，我是小林。阿明刚把红伞交给小夏，她拿着红伞去门口了；我把蓝书递给你。请分别描述你接过我的书和看到他们交接红伞的情形，两段简短描写，不要改变物品归属。'),
    ('direct_quote', '你是青竹，我是小林。阿明评价我时原话是“小林很细心，他总能发现错字”。请先原样引用这句话，再写一句你对我帮忙校对的心理感受。'),
    ('female_user', '你是青竹，我叫小雨，是一位成年女性朋友。我刚为你修好了书架。请写两段关于这件事的内心独白，只写心理，不要台词，每段不超过50字。'),
    ('three_bubbles', '你是青竹，我是小林。我帮你把展览办完了，你很开心。请分成三个气泡：一句对我说的话、一段你的动作、一段你的心理，每段不超过40字。'),
    ('misleading_history', '你是青竹，我是小林。之前你的两条心理描写写成了“他又来陪我整理书架了”“对方总记得我的习惯”。现在我给你递来温水，接着之前情境写两段心理描写，不要复述之前的句子，每段不超过50字。'),
]


async def main(extra=False):
    from dotenv import dotenv_values
    env = dotenv_values(ROOT / '.env')
    key = env.get('PONYCHAT_DEEPSEEK_API_KEY') or env.get('DEEPSEEK_API_KEY')
    if not key:
        raise RuntimeError('Missing model credential')
    modules = load_modules()
    direct, skills = modules['autonomous_direct'], modules['autonomous_prompt_skills']
    candidate = direct.CORE_EXPRESSION
    baseline = constant_at('baeae8b', 'CORE_EXPRESSION')
    systems = {}
    for variant, rule in [('before', baseline), ('after', candidate)]:
        if extra and variant == 'before':
            continue
        direct.CORE_EXPRESSION = rule
        systems[variant] = direct.direct_system(skills.COGNITION_CORE)
    direct.CORE_EXPRESSION = candidate
    results = []
    slots = asyncio.Semaphore(2)
    async def check(variant, name, text):
        async with slots:
            started = time.monotonic()
            result = await modules['harness_runtime'].run_harness_turn(
                text, {'api_key': key}, {}, system_prompt=systems[variant],
                timeout_seconds=100, max_tokens=4096, force_no_tools=True)
            row = {'variant': variant, 'case': name, 'input': text,
                   'finish_reason': result.get('finish_reason'),
                   'output': result.get('final_response'),
                   'seconds': round(time.monotonic()-started, 2)}
            results.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
    cases = EXTRA_CASES if extra else CASES
    await asyncio.gather(*(check(v, name, text) for v in systems for name, text in cases))
    report = ROOT / ('docs/testing/user-viewpoint-extra8-20260910.json' if extra
                     else 'docs/testing/user-viewpoint-20260910.json')
    report.write_text(json.dumps({'model': modules['harness_runtime'].MODEL,
        'baseline_revision': 'baeae8b',
        'scope': 'Synthetic real Harness, resident normal prompt; no production DB or delivery.',
        'cases': results}, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--extra', action='store_true', help='Eight new candidate-only cases')
    asyncio.run(main(parser.parse_args().extra))
