"""Archive the scoped description prompt check and every delivered reply."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'docs/testing/context-description-20260910'


def main():
    previous = ROOT / 'docs/testing/canon-voice-round1-20260910/baseline/raw.json'
    baseline = json.loads(previous.read_text(encoding='utf-8'))
    candidate = json.loads((OUT / 'raw.json').read_text(encoding='utf-8'))
    assert candidate['passed'] and len(candidate['cases']) == 6
    old = [r for r in baseline['cases'] if r['scenario'] == 'achievement']
    new = [r for r in candidate['cases'] if r['scenario'] == 'achievement']
    assert len(old) == len(new) == 3
    lines = ['# 按当前语境限制描写', '',
             '只修改当前运行版本的一条普通 Agent 提示词，没有采用上一轮未通过的候选。默认只发台词；当前语境已涉及具体物品或身体部位时，才按需要简短描写与其直接相关的变化。用户明确要求描写或动作时正常执行。', '',
             '使用隔离数据库、完整角色档案和真实 /api/chat 路由调用模型。三个普通聊天样本复用上一轮同模型、同档案、同输入的原版作对照；不是同一时刻采样，未固定随机种子，也不是盲评。另测物品、身体和明确描写要求三个边界。', '',
             '## 结论', '',
             '本轮六个样本符合描写范围要求：三条普通聊天全部为台词；物品及身体互动各保留相关动作；明确要求描写的样本正常展开。接受这一项定向修改。', '',
             '仍有独立问题：紫悦说出按下复盘清单的规则复述；碧琪索要全部细节的追问偏强；物品样本在没有书页证据时擅自认定第一页为空白。后者是事实依据问题，不能把它算作全面通过，只能说明物品相关动作没有被误删。本轮未修复这些问题。', '',
             '## 普通聊天：原版与本次全部原文']
    for a, b in zip(old, new):
        assert a['character_id'] == b['character_id']
        lines += ['', '### ' + a['character_name'], '', '用户：' + a['input']]
        for label, row in [('原版', a), ('本次', b)]:
            lines += ['', label, '', '```text', '\n\n'.join(row['paragraphs']), '```']
    lines += ['', '## 边界样本全部原文']
    for row in candidate['cases']:
        if row['scenario'] == 'achievement':
            continue
        lines += ['', '### ' + row['label'] + ' / ' + row['character_name'], '',
                  '用户：' + row['input'], '', '```text', '\n\n'.join(row['paragraphs']), '```']
    lines += ['', '## 验证范围', '',
              '已有相关测试 38 项通过。raw.json 保留原始 SSE、交付内容及记录到的工具轨迹，不含供应商完整网络请求。代码和提示词快照保留，部署结果单独见 deployment.json。', '',
              '这是限制描写的定向验证，不代表整体 AI 味道已消除；少量单轮样本不能证明长期对话百分之百遵守。']
    (OUT / 'REPORT.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    provenance = {'baseline_source': str(previous.relative_to(ROOT)),
                  'baseline_sha256': hashlib.sha256(previous.read_bytes()).hexdigest(),
                  'baseline_profile_sha256': baseline['profiles_sha256'],
                  'candidate_profile_sha256': candidate['profiles_sha256'],
                  'candidate_prompt_sha256': hashlib.sha256((OUT / 'candidate.py').read_bytes()).hexdigest(),
                  'route_cases_passed': len(candidate['cases']), 'existing_tests_passed': 38}
    (OUT / 'checks.json').write_text(json.dumps(provenance, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(provenance, ensure_ascii=False))


if __name__ == '__main__':
    main()
