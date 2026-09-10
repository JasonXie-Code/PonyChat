"""Preserve raw drafts/edits and aggregate real-model trial measurements."""
import argparse
import json
from pathlib import Path
import statistics

from summarize_expression_latency import summarize


def main(directory):
    summaries = []
    for folder in sorted(directory.iterdir()):
        if not (folder / 'results.json').exists():
            continue
        data = json.loads((folder / 'results.json').read_text(encoding='utf-8'))
        summary = summarize(folder)
        by_key = {row['scenario']: row for row in summary['rows']}
        for entry in data['rows']:
            row = by_key[entry['scenario']]
            agents = entry['case'].get('agent_calls', [])
            row['reviews'] = [a.get('prompt_skills', {}).get('expression_review', {}) for a in agents]
            row['inline_complete'] = bool(row['reviews']) and all(
                r.get('status') == 'reviewed_inline' for r in row['reviews'])
            row['tool_calls'] = sum(a.get('tool_call_count', 0) or 0 for a in agents)
            row['format_repairs'] = sum(a.get('output_format_repairs', 0) or 0 for a in agents)
            row['efforts'] = sorted({a.get('reasoning_effort') or 'unavailable'
                for agent in agents for a in agent.get('harness_attempts', [])})
        (folder / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
        summaries.append(summary)
    comparison = {}
    for prefix in ('baseline', 'candidate'):
        rows = [row for s in summaries if s['round'].startswith(prefix) for row in s['rows']]
        if not rows:
            continue
        times = [r['seconds'] for r in rows if r['seconds'] is not None]
        comparison[prefix] = {
            'cases': len(rows), 'transport_passed': sum(r['passed'] for r in rows),
            'mean_seconds': round(statistics.mean(times), 3),
            'median_seconds': round(statistics.median(times), 3),
            'max_seconds': max(times),
            'llm_api_calls': sum(r['llm_api_calls'] for r in rows),
            'tool_calls': sum(r['tool_calls'] for r in rows),
            'format_repairs': sum(r['format_repairs'] for r in rows),
            'inline_complete': sum(r['inline_complete'] for r in rows),
            'independent_review_attempts': sum(r['review_passes'] for r in rows),
            **{key: sum(r['usage'][key] for r in rows)
               for key in ('prompt_tokens', 'completion_tokens', 'total_tokens')},
        }
    (directory / 'comparison.json').write_text(json.dumps(comparison, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# 单 Agent 表达修订实验原始记录', '',
        '输入逐字沿用碧琪原六场景。基线为两次独立 low 复核；候选为主 Agent 读取 skill，提交草稿与删除清单，程序应用，不调用独立编辑模型。所有测试使用隔离数据库与真实模型。成功标记只代表接口与保存成功，语义质量另评。', '']
    for summary in summaries:
        lines += ['## ' + summary['round'], '']
        for row in summary['rows']:
            lines += ['### ' + row['label'], '', '用户：' + row['input'], '',
                      f"耗时：{row['seconds']} 秒；模型调用：{row['llm_api_calls']}；token：{row['usage']['total_tokens']}。", '', '最终回复：', '']
            lines += row['paragraphs'] or ['（没有成功交付回复）']
            lines += ['']
            if summary['round'].startswith('candidate'):
                for review in row['reviews']:
                    lines += ['草稿与修订清单（原始结构）：', '', '```json',
                              json.dumps(review, ensure_ascii=False, indent=2), '```', '']
    (directory / 'RAW_REPLIES.md').write_text('\n\n'.join(lines), encoding='utf-8')
    print(json.dumps(comparison, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    main(parser.parse_args().directory)
