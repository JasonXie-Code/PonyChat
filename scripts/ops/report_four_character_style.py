"""Build a complete, reviewable four-character style sample report."""
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'docs/testing/four-character-three-scene-20260910'


def main():
    data = json.loads((OUT / 'raw.json').read_text(encoding='utf-8'))
    review = json.loads((OUT / 'review.json').read_text(encoding='utf-8'))
    assert data['passed'] and len(data['cases']) == 12
    lines = ['# 四角色 × 三场景：AI 味道共同审阅', '',
             '使用当前已部署的 DeepSeek V4.1 Flash（deepseek-flash）、既有 low 推理和高优先级角色设定检索。未调整提示词。', '',
             '四位角色依次为紫悦、碧琪、云宝、柔柔。使用完整档案来源，实际进入上下文的检索由 Agent 决定。每格为隔离数据库的一次独立首轮，真实 /api/chat 路由与真实模型；没有读取用户生产聊天。', '',
             '三个场景中的“对说教不满”输入是测试用户的投诉陈述，没有预置助手说教原文，因此只评承接投诉的表达，不评多轮事实连续性。原始记录中的 profile_source 是测试工具的固定来源标签，本次实际读取冻结 profiles.json，非本轮重新拉取线上档案。', '',
             '## 评价方法', '',
             '观察重复用户原话、无依据评价或猜测、固定安慰/建议流程、规则执行宣言、角色关注点及接话空间。性格活泼不等于必须夸张，害羞不等于必须结巴；台词里的身体比喻按用户确认视为可接受，不按部位关键词扣分。', '',
             '以下是 Codex 的主观结构审阅，不是 AI 文本检测概率、独立盲评或校准分数。每格一次生成，不能据此给角色稳定排名。用户意见留空，不代替用户判断。', '',
             '## 我的整体观察', '', review['summary'], '',
             '## 逐条概览', '', '|编号|场景 / 角色|非空白字符|气泡|设定检索次数|我的观察|', '|---|---|---:|---:|---:|---|']
    for index, row in enumerate(data['cases'], 1):
        key = row['scenario'] + '_' + row['character_id'].removeprefix('style-' + row['scenario'] + '-')
        reads = [r for a in row['agent_calls'] for r in a['prompt_skills']['reads'] if r['type'] == 'character_reference']
        n = sum(len(re.sub(r'\s', '', p)) for p in row['paragraphs'])
        lines.append(f"|{index:02}|{row['label']} / {row['character_name']}|{n}|{len(row['paragraphs'])}|{len(reads)}|{review['items'][key]}|")
    lines += ['', '字符包含标点，只是客观长度，不当作好坏分数。', '', '## 全部原始回复与用户审阅栏']
    for index, row in enumerate(data['cases'], 1):
        key = row['scenario'] + '_' + row['character_id'].removeprefix('style-' + row['scenario'] + '-')
        reads = [r for a in row['agent_calls'] for r in a['prompt_skills']['reads'] if r['type'] == 'character_reference']
        lines += ['', f"### {index:02} · {row['label']} / {row['character_name']}", '', '用户：' + row['input'], '',
                  '```text', '\n\n'.join(row['paragraphs']), '```', '', '我的观察：' + review['items'][key], '',
                  '你的意见：待填写。', '', '设定检索词：' + '；'.join(r['query'] for r in reads)]
    lines += ['', '## 资料', '',
              'raw.json 保留全部 SSE、交付 envelope 与工具轨迹；cases.json 和 profiles.json 是冻结输入，verification.json 是运行版本证据。没有只挑好例子，也未改写模型交付文本。']
    (OUT / 'REPORT.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('Saved all 12 replies and paired review fields.')


if __name__ == '__main__':
    main()
