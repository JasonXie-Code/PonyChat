"""Build a reproducible review of both real-model mode-skill batches."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'docs/testing/interaction-mode-skills-20260910'
EXPECTED = {
    'instant': ('instant_messaging', 'instant_messaging'),
    'virtual': ('virtual_roleplay', 'virtual_roleplay'),
    'to_real': ('virtual_roleplay', 'instant_messaging'),
    'to_virtual': ('instant_messaging', 'virtual_roleplay'),
}


def build(directory):
    batch = json.loads((directory / 'parallel.json').read_text(encoding='utf-8'))
    rows, details = [], []
    correct = searched = saved = 0
    for row in batch['rows']:
        case = row['result']['cases'][0]
        for index, turn in enumerate((case, case['recovery'])):
            skill = turn['agent_calls'][-1]['prompt_skills']
            expected = EXPECTED[row['scenario']][index]
            actual = skill.get('interaction_mode')
            ok = actual == expected
            correct += ok
            searched += bool(skill['searched_this_turn'])
            saved += bool(turn['saved'])
            label = f"{row['scenario']} / {case['character_name']} / 第{index + 1}轮"
            rows.append(f'| {label} | {expected} | {actual} | {"通过" if ok else "失败"} |')
            details.extend([f'## {label}', '', '**用户原文**', '', turn['input'], '',
                            f'预期 `{expected}`；实际 `{actual}`。', '', '**客户端收到的全部段落**', '',
                            '```text', '\n\n'.join(turn['paragraphs']), '```', ''])
    total = len(rows)
    metrics = {'turns': total, 'mode_correct': correct, 'reference_searched': searched,
               'saved': saved, 'transport_passed': batch['passed'],
               'wall_seconds': batch['wall_seconds'], 'max_overlapping_workers': batch['max_overlapping_workers']}
    (directory / 'metrics.json').write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    report = ['# 对话模式实测原始回复', '',
              f'模式正确 {correct}/{total}；角色设定检索 {searched}/{total}；消息保存 {saved}/{total}。', '',
              '模型配置 ID：deepseek-flash。使用实际普通对话路由与模型 API，每个场景/角色使用隔离数据库，两个消息在同一会话内连续发送。',
              '这里的通过仅指边界与执行检查，不代表自然度通过。原始 JSON 和 SSE 保存在 cells/*/raw.json；其中 deployment 是取样时旧服务的部署标记，不表示候选代码已部署。', '',
              '| 场景 / 角色 / 轮次 | 预期模式 | 实际模式 | 判定 |', '|---|---|---|---|', *rows, '', *details]
    (directory / 'RAW-REVIEW.md').write_text('\n'.join(report), encoding='utf-8')
    return metrics


if __name__ == '__main__':
    folders = [Path(arg).resolve() for arg in sys.argv[1:]] or [OUT, OUT / 'round2']
    for folder in folders:
        print(folder.name, build(folder))
