"""Render observed metrics and verbatim replies from isolated initiative runs."""
import argparse
import hashlib
import json
from pathlib import Path


RUNS = (
    ('before', '修复前', 'bounded-before-live-screenshots.json'),
    ('deployed', '修复后（当前已部署最终版）', 'final-12-candidate-live-all.json'),
)
SCREENSHOTS = [f'{kind}_{i}' for kind in ('fixed', 'continuous') for i in range(1, 4)]
STATES = ('relationship_stage', 'character_intimacy_style', 'requested_escalation', 'user_pressure_level')


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def tools(case):
    return [event for call in case.get('calls', []) for event in call.get('tool_calls', [])]


def loaded(case, name):
    return any(t['name'] == 'load_chat_skill' and t.get('arguments', {}).get('name') == name
               and t.get('success') for t in tools(case))


def updated(case):
    return [t for t in tools(case) if t['name'] == 'update_relationship_state' and t.get('success')]


def state(value):
    return ' / '.join(str((value or {}).get(key, '?')) for key in STATES)


def metrics(cases):
    calls = [call for case in cases for call in case.get('calls', [])]
    return {
        'cases': len(cases), 'delivered': sum(bool(c.get('passed')) for c in cases),
        'first_attempt_delivered': sum(bool(c.get('passed')) and len(c.get('calls', [])) == 1 for c in cases),
        'attempts': len(calls),
        'harness_seconds': round(sum(c.get('seconds', 0) for c in calls), 3),
        'budget_exhausted_attempts': sum(c.get('finish_reason') == 'tool_budget_exhausted' for c in calls),
        'relationship_manual_cases': sum(loaded(c, 'relationship') for c in cases),
        'relationship_updated_cases': sum(bool(updated(c)) for c in cases),
        'first_system_characters': calls[0].get('system_characters') if calls else None,
        'recorded_model_api_calls': sum(c.get('llm_api_calls') or 0 for c in calls),
        'recorded_usage': {key: sum((c.get('usage') or {}).get(key, 0) for c in calls)
                           for key in ('prompt_tokens', 'completion_tokens', 'total_tokens')},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reports', type=Path)
    args = parser.parse_args()
    folder = args.reports
    target = folder / 'COMPARISON.md'
    prefix = ('# 修复前与当前最终版：角色回复原文\n\n'
              '只展示修复前与当前已部署最终版的原始角色回复，保留完整措辞、标点、描写和气泡顺序。'
              '使用认证碧琪资料；人类与安静角色另行标注为合成对照。\n\n'
              '截图回放统一假设双方成年、已确认伴侣关系、同坐客厅沙发；生成范围统一为非露骨亲昵互动。'
              '这些是测试前提，并非恢复的生产会话。')
    runs = [(key, title, filename, read(folder / filename)['report'])
            for key, title, filename in RUNS]
    deployment = read(folder / 'deployment.json')
    expected = deployment['hashes']
    assert all(runs[1][3]['source_hashes'].get(n) == digest for n, digest in expected.items())
    assert runs[1][3]['deployment']['deploy_token'] == deployment['release']
    assert len({r['official_character_sha256'] for _, _, _, r in runs}) == 1
    assert len({r['generation_scope'] for _, _, _, r in runs}) == 1
    for label in SCREENSHOTS:
        same_case = [next(c for c in r['cases'] if c['label'] == label) for _, _, _, r in runs]
        assert len({c['input'] for c in same_case}) == 1, label
        if label.startswith('fixed_'):
            assert all(c['fixture_history'] == same_case[0]['fixture_history'] for c in same_case), label
    before_audit = {c['label']: c for c in read(folder / 'before-relationship-audit.json')['cases']}
    for case in runs[0][3]['cases']:
        case['relationship_audit'] = before_audit[case['label']]
    summary = {'deployment': deployment, 'runs': {}}
    for key, _, _, report in runs:
        summary['runs'][key] = {
            'all': metrics(report['cases']),
            'screenshots': metrics([c for c in report['cases'] if c['label'] in SCREENSHOTS]),
            'source_hashes_match_release': all(report['source_hashes'].get(n) == d for n, d in expected.items()),
            'input_contracts_match_code': all(c['relationship_audit']['input_contracts_match_code'] for c in report['cases']),
            'updates_match_code': all(c['relationship_audit'].get('updated_contracts_match_code', True) for c in report['cases']),
            'successful_state_update_calls': sum(len(updated(c)) for c in report['cases']),
        }
    lines = [prefix, '\n## 结果\n', (folder / 'OBSERVATIONS.md').read_text(encoding='utf-8').strip(),
             '\n### 数值记录\n', '| 版本与范围 | 交付成功 | 无外层重试 | Harness 尝试 | 工具耗尽收尾触发 | 读取关系说明的场景 |',
             '|---|---:|---:|---:|---:|---:|']
    for key, title, _, _ in runs:
        for group, suffix in (('screenshots', '截图六轮'), ('all', '全部场景')):
            if key == 'before' and group == 'all':
                continue
            m = summary['runs'][key][group]
            lines.append(f"| {title}·{suffix} | {m['delivered']}/{m['cases']} | {m['first_attempt_delivered']}/{m['cases']} | {m['attempts']} | {m['budget_exhausted_attempts']} | {m['relationship_manual_cases']}/{m['cases']} |")
    lines += ['\n“无外层重试”指一次 Harness 尝试内交付，该尝试仍可能多次调用模型及工具。工具耗尽后的无工具收尾计入尝试，不算首次通过。耗尽前出现的无效工具请求也可能计费，不能把观察到的成功工具回调数当成总额度计数。',
              '\n| 截图六轮 | 首轮 system 字符 | Harness 累计秒数 | 记录的模型 API 调用 | 记录的总 token |',
              '|---|---:|---:|---:|---:|']
    for key, title, _, _ in runs:
        m = summary['runs'][key]['screenshots']
        lines.append(f"| {title} | {m['first_system_characters']} | {m['harness_seconds']} | {m['recorded_model_api_calls']} | {m['recorded_usage']['total_tokens']} |")
    lines += ['\n字符数是进入 Harness 的 system 文本长度，不含任务输入及后续工具返回；提示词变短不能直接推定总 token、耗时或成本下降。单次实测受生成随机性、工具选择和服务负载影响，不是压力测试或统计显著性结论。',
              '\n### 发布核验\n', f"目标：{deployment['target']}。部署源码提交：`{deployment['revision']}`。",
              f"\n发布标识：`{deployment['release']}`。公网 `/api/health` 返回同一标识。",
              f"\n回滚资料：`{deployment['backup']}`，包含原代码与部署前 SQLite 备份。",
              '\n七个发布文件的回执哈希与最终版实测哈希逐项相同。生成验收使用部署源码、真实模型和隔离数据库，并非真实用户会话的线上流量采样。',
              '\n### 关系专项调用证据\n', '字段顺序：阶段 / 风格 / 请求推进 / 压力。表中“匹配”表示每次实际输入和成功更新返回的规则均与代码生成结果一致，不表示可见行为全部通过。',
              '\n| 版本 | 场景 | 首次输入状态 | 关系说明读取 | 成功更新次数 | 保存后状态 | 规则匹配 |',
              '|---|---|---|---|---:|---|---|']
    for key, title, _, report in runs[1:]:
        for case in report['cases']:
            if not case['label'].startswith('relationship_'):
                continue
            audit = case['relationship_audit']
            match = audit['input_contracts_match_code'] and audit['updated_contracts_match_code']
            lines.append(f"| {title} | {case['label']} | {state(audit['input_states'][0])} | {'是' if loaded(case, 'relationship') else '否'} | {len(updated(case))} | {state(audit['saved_state'])} | {'是' if match else '否'} |")

    reply_index = []

    def reply_block(case, key, title, filename):
        result = [f"\n#### {title}\n", f"[原始记录]({filename})；场景 `{case['label']}`。",
                  f"\n交付：{'成功' if case.get('passed') else '失败'}；Harness 尝试：{len(case.get('calls', []))}。"]
        for i, reply in enumerate(case.get('replies', []), 1):
            identifier = f'{key}/{case["label"]}/{i}'
            marker = f'<!-- raw-reply:{identifier} -->'
            result += [f'\n气泡 {i}：\n', marker, '\n'.join('> ' + s for s in reply.split('\n')), '<!-- /raw-reply -->']
            reply_index.append({'id': identifier, 'source': filename,
                                'sha256': hashlib.sha256(reply.encode()).hexdigest(), 'text': reply})
        if not case.get('replies'):
            result.append('\n**没有成功交付的角色回复。** 未交付草稿不作为用户收到的回复。')
        for call_i, call in enumerate(case.get('calls', []), 1):
            if call.get('error_type') or call.get('finish_reason') == 'tool_budget_exhausted':
                result.append(f"\n尝试 {call_i}：`{call.get('error_type') or call.get('finish_reason')}`。")
        if case.get('error_type') or case.get('errors'):
            result.append('\n错误记录：`' + json.dumps({k: case[k] for k in ('error_type', 'errors') if case.get(k)}, ensure_ascii=False) + '`。')
        return result

    audit_lines = lines[1:]
    lines = [prefix, '\n## 原始角色回复：截图对比\n',
              '以下直接从持久化后的 replies 数组提取。括号为实际交付时的呈现。',
              '\nfixed 采用相同的截图文字历史，便于逐轮对照。continuous 将该版本前一轮真实回复送入下一轮，因此第二轮起各版本历史不同；这部分用于观察累积行为，不能视为完全相同输入的独立比较。']
    for label in SCREENSHOTS:
        heading = ('固定历史' if label.startswith('fixed_') else '连续回放') + ' · 第 ' + label.rsplit('_', 1)[1] + ' 轮'
        original = next(c for c in runs[0][3]['cases'] if c['label'] == label)
        lines += [f'\n### {heading}\n', '用户原文：', '\n'.join('> ' + s for s in original['input'].split('\n'))]
        for key, title, filename, report in runs:
            case = next((c for c in report['cases'] if c['label'] == label), None)
            if case is not None:
                lines.extend(reply_block(case, key, title, filename))
    for section, predicate in (
        ('关系六标签', lambda s: s.startswith('relationship_')),
        ('人类与小马四种组合', lambda s: '_with_' in s),
        ('其他边界场景', lambda s: s not in SCREENSHOTS and not s.startswith('relationship_') and '_with_' not in s),
    ):
        lines += [f'\n## 当前最终版原文：{section}\n', '这组专项没有对应的修复前回放记录，以下只展示当前最终版原文。']
        if section == '人类与小马四种组合':
            lines.append('human 开头的角色是合成对照林岚，25 岁成年人类；pony 开头使用认证碧琪。calm_character 为合成安静成年小马，不代表修改认证角色资料。')
        for label in [c['label'] for c in runs[1][3]['cases'] if predicate(c['label'])]:
            original = next(c for c in runs[1][3]['cases'] if c['label'] == label)
            lines += [f'\n### {label}\n', '用户原文：', '\n'.join('> ' + s for s in original['input'].split('\n'))]
            for key, title, filename, report in runs[1:]:
                case = next((c for c in report['cases'] if c['label'] == label), None)
                if case is not None:
                    lines.extend(reply_block(case, key, title, filename))
    lines += audit_lines
    lines += ['\n## 核对记录\n',
              '- [数值汇总](summary.json)、[逐条原文校验索引](verbatim-replies.json)、[发布回执](deployment.json)。',
              '- 两版原始记录的 calls 保留 system、任务输入、工具参数及返回，可核对关系规则的实际注入和重试过程。']
    text = '\n'.join(lines).rstrip() + '\n'
    # Round-trip every presented bubble, including failures with partial delivery.
    for row in reply_index:
        block = text.split(f'<!-- raw-reply:{row["id"]} -->\n', 1)[1].split('\n<!-- /raw-reply -->', 1)[0]
        reconstructed = '\n'.join(line[2:] for line in block.split('\n'))
        assert reconstructed == row['text'], row['id']
    target.write_text(text, encoding='utf-8')
    (folder / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (folder / 'verbatim-replies.json').write_text(json.dumps(reply_index, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'main_reply_bubbles': len(reply_index), 'versions': [key for key, _, _ in RUNS],
                      'verbatim_roundtrip': True, 'release_hashes_match': True}))


if __name__ == '__main__':
    main()
