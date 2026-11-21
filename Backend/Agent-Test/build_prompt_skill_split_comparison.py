"""Render exact delivered bubbles and explicit editorial assessment for the A/B sample."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
BEFORE = ROOT / 'docs/testing/prompt-skill-split-20260911-before-v2'
AFTER = ROOT / 'docs/testing/prompt-skill-split-20260911-r3'
REV = '384cf8724a3085308e4bd717c5005562151ceb0b'
REV_AFTER = subprocess.check_output(['git', 'rev-parse', '1355955'], cwd=ROOT).decode().strip()
NOTES = {
    ('happy', 'twilight_sparkle'): '角色味小幅增强：修改前是通用的“石头落地”，修改后用“清单划掉”表达成就感，更贴合紫悦的计划习惯。两版都只追加一次好奇提问，没有明显重复补句。修改前的“愿意的话”消失，表达更直接；这一例支持小幅改善，不足以证明稳定提升。',
    ('happy', 'pinkie_pie'): '两版本来就有碧琪的热情。修改后拉长感叹、强调“绝对”并联想到撒彩纸，兴奋和联想更鲜明，但也更依赖庆祝标签；修改前“越啰嗦越好”反而有独特的好奇心。“绝对、绝对”是语气强调，不应机械判为废话。修改后仍围绕同一件开心事扩写，算角色味更显眼、信息增量有限，不能判为全面优于修改前。',
    ('tired', 'twilight_sparkle'): '建议和追问明显减少，但合理性未达标。修改后“有好几次看资料……穗龙把吃的端到我面前”是一段具体既往经历；本次提供的角色档案只支持爱研究、穗龙是助手，不包含该事件及频次，工具轨迹也没有补充事实来源。角色味增加不能抵消无依据自述。开头仍主要复述用户并认可感受。这一例是去建议改善、事实可靠性变差。',
    ('tired', 'pinkie_pie'): '从泛泛夸奖、许可休息和食物建议，变成较活泼的隔空陪聊口吻，但第二泡仍提供“想听／不想听”的选项，并补“我明天照样给你发新笑话”。该格业务工具轨迹为空，没有调度凭据，不能认为明天发消息已经落实；这也是用户未要求的额外承诺。没有完全解决服务式陪伴和多余收尾。',
    ('friction', 'twilight_sparkle'): '三泡减为两泡，删掉了“想说／不想说”的陪伴菜单。急于理清事情的动机符合紫悦，但“道理你比我清楚”没有依据，显得过度退让；“不用我再念一遍”又重申了停止说教。有所收束，仍有解释动机和重复收尾，不能判为无废话。输入是独立首轮抱怨，没有真实的此前说教记录，不能把她承认的具体行为当作已核实历史。',
    ('friction', 'pinkie_pie'): '修改后删掉纸条意象和陪伴菜单，三泡变两泡，更直接。但“我就停”“我不讲了”“我闭嘴”在同一回复里重复表达停止，“你说了算”又补一次让步；中间还解释自己着急的动机。这个样本的重复补句依然明显，目标未达成。修改前也重复，但不能用篇幅变短代替语义去重验收。',
}


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    before, after = read(BEFORE / 'results.json'), read(AFTER / 'results.json')
    assert read(BEFORE / 'cases.json') == read(AFTER / 'cases.json')
    assert read(BEFORE / 'profiles.json') == read(AFTER / 'profiles.json')
    lookup = {(r['scenario'], r['character_id']): r for r in before['rows']}
    lines = ['# 普通对话提示词第一轮：修改前后原文对照', '',
             '结论：按需加载已生效，但表达质量有改善也有退步，尚未达到“角色鲜明、合理、没有重复补句”的完整目标。开心场景差异更清楚；疲惫场景少了饮食建议，却出现无依据经历和额外承诺；冲突场景缩短后仍反复说停止。以下评价由本次审阅给出，不是模型评分。', '',
             '## 样本与版本', '',
             f'- 修改前：补跑基线，提示词文件来自 `{REV}`，即 `1355955` 的父提交。原有前三批都是修改后的候选，不能当作修改前。',
             f'- 修改后：沿用已保存的 r3 最终样本，对应提交 `{REV_AFTER}`；没有重新生成或挑选更好回复。',
             '- 基线仅将 `Prompts.py` 和 `autonomous_prompt_skills.py` 恢复到父版本，通过只含这两个文件的 overlay 加载到临时后端；当前工作区业务代码没有被回退。其他运行代码来自补跑时本地工作区，且两批采样时间不同，因此不是完整运行环境冻结的严格因果实验。',
             '- 两批角色档案与三条用户输入经逐字段一致性校验。紫悦、碧琪各三个独立首轮场景，没有此前对话或额外风格指令；角色档案自身已有语言习惯要求。',
             f'- 两批各 6 格均完成真实 Agent `/api/chat` ASGI 交付和隔离数据库保存。修改前全并发 {before["wall_seconds"]} 秒，修改后全并发 {after["wall_seconds"]} 秒；这是整批耗时，不是稳定单轮延迟或性能提升结论。',
             '- 以下逐字取自 `case.paragraphs`，即实际交付文字；每个引用块是一条气泡。没有润色、补标点、删句或把两泡合并。传输前模型 JSON 原文另见各格 raw.json。',
             '- 原报告误将 r2 的“塞进气球里放走”当成 r3 最终回复，现已纠正。此前 12,850 字符是组合器接收的旧底层系统提示词，不能作为修改前实际发给模型的系统提示词长度来宣称此次降幅。',
             '- 基线第一次启动因归档包含目录条目，被隔离脚本校验拒绝，未进入模型调用；修正归档后才产生这里的六条基线。', '',
             '## 六组完整原文与评价', '']
    for row in after['rows']:
        key = (row['scenario'], row['character_id'])
        original = lookup[key]
        assert original['case']['input'] == row['case']['input']
        lines += [f'### {row["case"]["label"]} · {row["case"]["character_name"]}', '',
                  '用户：' + row['case']['input'], '', '**修改前**', '']
        for p in original['case']['paragraphs']:
            lines += ['> ' + p.replace('\n', '\n> '), '']
        lines += ['**修改后（r3）**', '']
        for p in row['case']['paragraphs']:
            lines += ['> ' + p.replace('\n', '\n> '), '']
        lines += ['**评价：** ' + NOTES[key], '']
    lines += ['## 验收结论与证据', '',
              '- 已验证：普通表达/语言整包不再每轮强制读取；最终样本只有紫悦开心场景读取 reply_expression，六格均未读取 reply_language；六格交付成功。',
              '- 部分改善：角色节奏、注意点和比喻有所区分，疲惫场景的通用饮食建议减少，冲突场景更短。',
              '- 未达标：碧琪冲突场景的重复停止、疲惫场景的额外承诺，以及紫悦无直接资料支持的具体自述。不能概括为“没有废话和重复”。',
              '- 每格每版只有一次采样，模型存在随机性；不提供伪精确分数或整体提升百分比。报告不改变提示词、不部署服务。', '',
              '[修改前完整结果](../prompt-skill-split-20260911-before-v2/results.json) · [修改后完整结果](results.json)', '']
    destination = AFTER / 'README.md'
    destination.write_text('\n'.join(lines), encoding='utf-8')
    rendered = destination.read_text(encoding='utf-8')
    for data in (before, after):
        for row in data['rows']:
            for p in row['case']['paragraphs']:
                assert '> ' + p.replace('\n', '\n> ') in rendered
    hashes = {}
    for rev in (REV, REV_AFTER):
        hashes[rev] = {name: hashlib.sha256(subprocess.check_output(
            ['git', 'show', rev + ':Backend/chat_modules/' + name], cwd=ROOT)).hexdigest()
            for name in ('Prompts.py', 'autonomous_prompt_skills.py')}
    (AFTER / 'comparison-provenance.json').write_text(json.dumps({
        'prompt_git_blob_sha256': hashes, 'before_results_sha256': hashlib.sha256((BEFORE / 'results.json').read_bytes()).hexdigest(),
        'after_results_sha256': hashlib.sha256((AFTER / 'results.json').read_bytes()).hexdigest(),
        'fixtures_equal': True, 'all_delivered_bubbles_in_report': True}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('Verified: 6 paired cases; every delivered bubble preserved verbatim.')


if __name__ == '__main__':
    main()
