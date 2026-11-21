"""Extreme synthetic history-style A/B through the real normal Agent.

Keep the selected current identity in every arm; seed assistant history with
Twilight-like analytical prose to isolate style from an actual identity change.
No production DB, memory, HTTP account or deployment is used.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib
import json
from pathlib import Path
import subprocess
import time

from replay_expression_focus import ROOT, load_modules


USERS = [
    '下午想和你到公园走走。',
    '我喜欢看树，也想看看池塘里的鸭子。',
    '那就从东门进去吧。',
    '我准备带两个苹果和一个空保温杯。',
    '我有一本蓝色封面的鸟类图鉴，可以带来。',
    '我不想把散步弄得像做作业。',
    '先约下午三点怎么样？',
    '改成下午两点半吧，还是东门。',
    '如果下雨，我们再商量，不预先决定去哪。',
    '那本蓝色鸟类图鉴是我的，只借给你看，散步结束要还给我。',
]
TWILIGHT = [
    '我建议先明确本次活动的目标，再讨论路线。散步可以拆分为三个变量：时间、地点、观察对象。只要把约束条件逐项核实，后续安排就不会出现逻辑上的遗漏。请允许我先建立一份简要记录。',
    '记录完毕：观察对象为树木与鸭子。从分类学角度，两者分别属于植物观察和鸟类行为观察，不能混为同一个研究问题。初步结论是沿林荫区域前往池塘，但路线仍须服从入口条件。',
    '入口变量更新为公园东门。严谨地说，入口已经确定不等于整条路线已经确定；我们目前只有一个起点，尚缺少返回路径。为了避免过早下结论，我将其列为待确认事项。',
    '物资清单记录为两个苹果、一只空保温杯。这里必须区分容器与内容物：空杯不能视为已经装有饮料，因此不能从携带保温杯推导出可以直接饮用热茶。这个细节看似微小，却影响清单的准确性。',
    '补充参考文献：蓝色封面的鸟类图鉴。观察时应先记录可见特征，再与图鉴条目交叉验证，而不是因为某只鸟看起来像鸭子就直接下分类结论。知识判断应当有可复查的依据。',
    '你的要求构成新的活动约束：不把散步变成作业。由此只能推出无需提交观察报告，不能推出不需要任何组织。我会保留必要的事实记录，并把正式的观察表格从执行清单中移除。',
    '暂定时间为十五点。请注意“暂定”与“最终确认”的区别，我会在记录中标注这个状态，避免之后把尚可调整的提议误认为不可更改的约定。现在时间与入口已经能够组成最小安排。',
    '更正已记录：时间由十五点调整为十四点三十分，入口仍为东门。此次修改只影响时间变量，不影响此前确认的观察兴趣和物资清单。旧时间十五点应标记为失效，不能同时保留为第二个有效安排。',
    '天气预案维持未定状态：如果下雨，再共同讨论。逻辑上这是一条条件分支，并不是取消散步的结论，也不意味着已经选定室内地点。当前不能把任何候选方案填写为已确认事实。',
    '所有权与借阅关系已区分：蓝色鸟类图鉴归你所有，我仅在散步期间借阅，结束后归还。归纳目前有效记录：十四点三十分、公园东门、两个苹果、一只空杯，以及临时借阅的图鉴。下面只需按已确认条件继续，不必反复重建整套清单。',
]
NEUTRAL = [
    '下午可以去公园散步。', '记得了，你喜欢看树和池塘里的鸭子。',
    '从公园东门进去。', '你带两个苹果和一个空保温杯。',
    '你可以带那本蓝色封面的鸟类图鉴。', '这次只是散步，不用做作业。',
    '先暂定下午三点。', '改成下午两点半，仍在公园东门。',
    '下雨后再商量，还没定其他地点。',
    '图鉴是你的，我只借来看，散步结束还你；时间是下午两点半，地点是公园东门。',
]
INPUTS = [
    '安排先放一边。你最期待下午哪件小事？',
    '要是我到了以后有点紧张，你会怎么做？',
    '你还记得我们几点、在哪里碰面，还有那本书归谁吗？',
    '我之前关于蓝色鸟类图鉴说的最后一句原话是什么？请逐字复述。',
]
MARKERS = ['变量', '约束条件', '逻辑上', '交叉验证', '分类学', '初步结论', '待确认事项', '归纳', '严谨地说']
TOPICS = ['整理笔记', '不懂的问题', '观察叶片', '给书分类', '安排读书时间',
          '记住新知识', '比较两个观点', '犯了小错误', '别人不同意你', '制定计划',
          '修改计划', '准备活动', '遇到意外', '检查遗漏', '列出问题',
          '寻找依据', '讨论天气', '认识新朋友', '分享发现', '放松一下']


async def run(args):
    from dotenv import dotenv_values
    env = dotenv_values(ROOT / '.env')
    key = env.get('PONYCHAT_DEEPSEEK_API_KEY') or env.get('DEEPSEEK_API_KEY')
    if not key:
        raise RuntimeError('Configured model credential unavailable')
    modules = load_modules()
    prompts = importlib.import_module(modules['autonomous_normal'].__package__ + '.Prompts')
    rule = prompts.HISTORY_CONTEXT_RULE
    profile = next(p for p in json.loads(args.profiles.read_text(encoding='utf-8')) if p['id'] == args.character_id)

    def message(role, content, index):
        return {'role': role, 'content': content, 'message_id': f'synthetic-{index}',
                **({'speaker_character_id': profile['id'], 'speaker_name': profile['name']}
                   if role == 'assistant' else {})}
    fields = [('name', '名称'), ('profileAge', '年龄'), ('profileGender', '性别'),
              ('profileSpecies', '物种'), ('profilePersonality', '性格'),
              ('profileInterests', '兴趣'), ('profileMbti', '16人格'), ('profileIntro', '简介')]
    home = '【角色档案】\n' + '\n'.join(f'{label}：{profile[k]}' for k, label in fields if profile.get(k))
    report = {'synthetic_only': True, 'transport': 'real normal Agent and Harness, no HTTP/DB',
              'production_writes': False, 'memory_enabled': False, 'rule': rule,
              'profile': profile, 'profile_source': str(args.profiles), 'home_profile': home, 'inputs': INPUTS,
              'git_head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True, cwd=ROOT).strip(),
              'source_hashes': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in (ROOT / 'Backend/chat_modules').glob('*.py')},
              'history_identity': f"{profile['id']} throughout; Twilight-like style is deliberately synthetic",
              'seed_users': USERS, 'seed_twilight_style': TWILIGHT, 'seed_neutral': NEUTRAL,
              'history_rounds': args.history_rounds,
              'cases': []}
    args.report.parent.mkdir(parents=True, exist_ok=True)

    def save():
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    plans = [('before-1', TWILIGHT, False), ('after-1', TWILIGHT, True),
             ('before-2', TWILIGHT, False), ('after-2', TWILIGHT, True), ('neutral', NEUTRAL, True)]
    for name, seed, enabled in plans:
        if args.case and args.case != name:
            continue
        history = []
        if args.history_rounds == 30:
            for topic in TOPICS:
                history.append(message('user', f'聊聊{topic}吧，你有什么想法？', len(history)))
                content = (f'讨论{topic}之前，我认为首先需要界定问题的范围。第一，区分已经观察到的事实与尚未验证的假设；第二，列出变量及其相互依赖；第三，根据证据修订结论。严格来说，没有充分依据就不能把可能性写成确定性。我们可以把这一点记入讨论提纲，之后再逐项核对。'
                           if name != 'neutral' else f'{topic}可以慢慢聊，先说说已经知道的事情。')
                history.append(message('assistant', content, len(history)))
        for user, assistant in zip(USERS, seed):
            history.append(message('user', user, len(history)))
            history.append(message('assistant', assistant, len(history)))
        case = {'name': name, 'rule_enabled': enabled, 'history': list(history), 'turns': []}
        report['cases'].append(case)
        for index, text in enumerate(INPUTS, 1):
            history.append(message('user', text, len(history)))
            row = {'turn': index, 'input': text, 'calls': []}
            case['turns'].append(row)
            begin = time.monotonic()

            async def observe(prompt, config, tools, **options):
                assert options['system_prompt'].count(rule) == 1
                if not enabled:
                    options['system_prompt'] = options['system_prompt'].replace('\n' + rule, '', 1)
                assert (rule in options['system_prompt']) == enabled
                call = {'prompt': json.loads(prompt), 'system_prompt': options['system_prompt']}
                row['calls'].append(call)
                result = await modules['harness_runtime'].run_harness_turn(prompt, config, tools, **options)
                call.update({k: result.get(k) for k in ('final_response', 'finish_reason', 'model', 'usage', 'llm_api_calls')})
                return result

            try:
                result = await modules['autonomous_prompt_skills'].run_skill_turn(
                    modules['autonomous_normal'].run_autonomous_turn,
                    messages=history, character_profile=profile['prompt'], home_profile=home,
                    environment=f"当前角色是{profile['name']}，当前用户是成年朋友Jason。正常中文聊天。",
                    model_config={'api_key': key}, speaker_character_id=profile['id'], harness_runner=observe)
                envelope = json.loads(result['envelope'])
                reply = modules['autonomous_reply'].render_envelope(envelope)
                row.update(reply=reply, envelope=envelope, skills=result['prompt_skills'],
                           repairs=result['output_format_repairs'], llm_api_calls=result['llm_api_calls'],
                           lexical_hits=[m for m in MARKERS if m in reply])
                if index == 3:
                    row['fact_checks'] = {'time': any(x in reply for x in ['两点半', '两点三十', '十四点三十', '14:30', '2:30']),
                                          'gate': '东门' in reply, 'ownership': any(x in reply for x in ['你的', '归你', '你那本'])}
                if index == 4:
                    row['verbatim_check'] = USERS[-1] in reply
                for bubble in envelope['bubbles']:
                    history.append(message('assistant', modules['autonomous_reply'].render_envelope({'bubbles': [bubble]}), len(history)))
                print(json.dumps({'case': name, 'turn': index, 'reply': reply}, ensure_ascii=False), flush=True)
            except Exception as exc:
                row['error_type'] = type(exc).__name__
                print(json.dumps({'case': name, 'turn': index, 'error_type': type(exc).__name__}), flush=True)
                break
            finally:
                row['seconds'] = round(time.monotonic() - begin, 2)
                save()
    report['completed'] = all(len(c['turns']) == len(INPUTS) and all('reply' in t for t in c['turns']) for c in report['cases'])
    save()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--character-id', default='pinkie_pie')
    parser.add_argument('--profiles', type=Path, default=ROOT / 'docs/testing/neutral-expression-20260911/neutral1/profiles.json')
    parser.add_argument('--case', choices=['before-1', 'after-1', 'before-2', 'after-2', 'neutral'])
    parser.add_argument('--history-rounds', type=int, choices=[10, 30], default=10)
    asyncio.run(run(parser.parse_args()))
