"""Render the selected release replies verbatim, with a short introduction only."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'docs/testing/expression-convergence-20260910'
CHARACTERS = {'pinkie_pie': '碧琪', 'rainbow_dash': '云宝',
              'twilight_sparkle': '紫悦', 'fluttershy': '柔柔'}
SCENARIOS = ('friend_deep_direct', 'flirting_deep_euphemistic', 'flirting_deep_default',
             'flirting_deep_direct', 'partner_deep_euphemistic', 'partner_deep_default')


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def build(final_round):
    directory = (OUT / final_round).resolve()
    assert directory.parent == OUT.resolve()
    trial = read(directory / 'results.json')
    assert trial['transport_passed'] and len(trial['rows']) == 24
    for name, expected in trial['runtime_sha256'].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected, name
    rows = {(r['character_id'], r['scenario']): r for r in trial['rows']}
    assert len(rows) == 24
    lines = ['# 角色表达升级最终报告', '',
        '本次最终采用第八轮的 DeepSeek Flash 版本。生成与两次表达检查均使用 Flash，'
        '重点减少重复挽留、重复表态、解释性尾句和多余的开场，同时保留角色特点、具体动作与有意义的愿望。', '',
        '以下是这版在碧琪、云宝、紫悦、柔柔各 6 种情况中的实际交付回复，共 24 条，'
        '逐字取自同一轮记录，没有人工润色或混用其他轮次。该轮 24 项均完成交付；'
        '这说明流程完成，不代表每句话都已完全达到你的标准，仍能看到少量重复或生硬表达。'
        '原定“伴侣·深入·直白”的 4 项涉及露骨内容，未重新生成，不列入本报告。用户原始提示词保持不变。', '']
    receipt_path = OUT / 'deployment.json'
    if receipt_path.exists():
        receipt = read(receipt_path)
        assert receipt['passed']
        assert all(receipt['hashes'].get(k) == v for k, v in trial['runtime_sha256'].items())
        lines += ['该版本已部署，发布标识：`' + receipt['release'] + '`。', '']
    index = 0
    for character, name in CHARACTERS.items():
        lines += ['## ' + name, '']
        for scenario in SCENARIOS:
            row = rows[(character, scenario)]
            case = row['case']
            assert case['passed'] and case['saved'] and case['http_status'] == 200
            assert case['agent_calls'][-1]['prompt_skills']['expression_review']['status'] == 'reviewed'
            index += 1
            lines += [f'### {index:02d}. {row["label"]}', '']
            for paragraph in case['paragraphs']:
                lines += ['\n'.join('> ' + line for line in paragraph.splitlines()), '']
    target = OUT / 'REPORT.md'
    target.write_text('\n'.join(lines).rstrip() + '\n', encoding='utf-8')
    print(json.dumps({'report': str(target), 'replies': index, 'source_round': final_round}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('round')
    build(parser.parse_args().round)
