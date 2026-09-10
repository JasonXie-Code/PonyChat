"""Show unchanged user inputs and raw replies beside the two-review baseline."""
import argparse
import json
from pathlib import Path

from summarize_expression_latency import summarize


def main(directory):
    reports = {name: summarize(directory / name) for name in ('baseline1', 'noreview1')}
    for name, report in reports.items():
        (directory / name / 'summary.json').write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    baseline, current = reports['baseline1'], reports['noreview1']
    assert baseline['inputs_sha256'] == current['inputs_sha256']
    assert [k for k, v in baseline['runtime_sha256'].items()
            if current['runtime_sha256'][k] != v] == ['Backend/chat_modules/autonomous_prompt_skills.py']
    raw = json.loads((directory / 'noreview1/results.json').read_text(encoding='utf-8'))
    for row in raw['rows']:
        for agent in row['case'].get('agent_calls', []):
            skills = agent.get('prompt_skills', {})
            assert skills.get('expression_review', {}).get('status') == 'disabled_for_comparison'
            assert not any(read.get('name') == 'expression_revision' for read in skills.get('reads', []))
            for attempt in agent.get('harness_attempts', []):
                assert attempt.get('model') == 'deepseek-flash'
                assert attempt.get('reasoning_effort') == 'low'
    lines = ['# 碧琪：不加新 skill、不做表达复核的对比实验', '',
        '实验版直接交付主 Agent 生成并通过格式与业务校验的回复，不加入 expression_revision skill，不调用两次表达复核。既有角色、语言、偏好和表达提示词均保留，用户原文不变。六场景并发，模型全部为 DeepSeek Flash low，隔离数据库，未部署。', '',
        '对照使用本轮先前完成的 baseline1：相同输入与运行代码，仅表达复核入口不同。每个版本各六条，非同时运行；时间和 token 是小样本观测，不是生产保证。接口成功不代表表达质量全部达标。', '',
        '| 指标 | 两次表达复核 | 无表达复核 |', '|---|---:|---:|']
    for key, label in [('transport_passed', '成功回复数 / 6'), ('mean_seconds', '平均耗时（秒）'),
                       ('llm_api_calls', '模型调用总数'), ('total_tokens', '总 token')]:
        lines.append(f"| {label} | {baseline['aggregate'][key]} | {current['aggregate'][key]} |")
    old = {row['scenario']: row for row in baseline['rows']}
    for row in current['rows']:
        lines += ['', '## ' + row['label'], '', '**原始用户发言**', '', row['input'], '',
                  '**本次：无新 skill、无表达复核**', '']
        lines += [paragraph + '\n' for paragraph in row['paragraphs']] or ['（未成功交付）']
        lines += ['', '**对照：两次表达复核**', '']
        lines += [paragraph + '\n' for paragraph in old[row['scenario']]['paragraphs']]
    lines += ['', '原始 JSON、调用记录和运行源码快照分别位于 noreview1 与 baseline1 目录。本文逐字提取可见回复，没有人工润色。']
    (directory / '碧琪无表达复核对比_20260911.md').write_text('\n'.join(lines), encoding='utf-8')
    print(json.dumps({k: v['aggregate'] for k, v in reports.items()}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    main(parser.parse_args().directory)
