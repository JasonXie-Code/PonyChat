"""Collect the six real replies and verify the existing-skill-only trial."""
import argparse
import json
from pathlib import Path
import re

from summarize_expression_latency import summarize


def main(directory):
    folder = directory / 'neutral1'
    summary = summarize(folder)
    raw = json.loads((folder / 'results.json').read_text(encoding='utf-8'))
    checks = []
    for row in raw['rows']:
        agents = row['case'].get('agent_calls', [])
        assert agents
        for agent in agents:
            skills = agent.get('prompt_skills', {})
            assert skills['expression_review']['status'] == 'disabled_for_comparison'
            assert not any('expression_revision' in a.get('loaded_skills', [])
                           for a in skills.get('attempts', []))
            assert all(a.get('model') == 'deepseek-flash' and a.get('reasoning_effort') == 'low'
                       for a in agent.get('harness_attempts', []))
        text = '\n'.join(row['case'].get('paragraphs', []))
        checks.append({'scenario': row['scenario'], 'independent_reviews': 0,
                       'example_object_matches': re.findall('盒子|架子|收纳|便签|笔杆|折法|这张纸', text)})
    summary['checks'] = checks
    (folder / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# 碧琪六场景：现有表达 skill 加入八个中性例子', '',
        '本次将用户确认的八个结构化中性例子加入既有 reply_expression，并用“表达内容与交流主动性”替换旧的表达完成点段落。允许有效反问、好奇、话题延伸和自然转题，保留具体内容；其余角色、偏好、用户输入不变。', '',
        '测试条件：六场景并发，真实 /api/chat 与隔离数据库，全部 DeepSeek Flash low；关闭两次独立表达复核，未新增 skill、未启用删除清单。线上服务未重启、未部署本实验。', '',
        f"成功交付 {summary['aggregate']['transport_passed']}/6；平均 {summary['aggregate']['mean_seconds']} 秒；模型调用合计 {summary['aggregate']['llm_api_calls']} 次；总 token {summary['aggregate']['total_tokens']}。", '',
        '相关提示词与共享表达回归 41 项通过。原始输入哈希、代码快照、工具记录与模型调用保存在 neutral1。成功交付仅表示接口与保存成功，不等于语义质量达标。例子物品词检查仅作泄漏线索，不能证明完全不存在提示词污染。', '',
        '观察：本轮保留了较充分的动作、愿望和角色口吻，但安静陪伴及部分亲近场景仍存在重复保证、宣布回答和追加挽留，不能认定冗余问题已解决。六场景本身没有专门覆盖收纳、反问、转题请求，因此不宣称八类能力全部验收。', '']
    for row in summary['rows']:
        lines += ['## ' + row['label'], '', '**原始用户发言**', '', row['input'], '', '**原始角色回复**', '']
        for paragraph in row['paragraphs']:
            lines += [paragraph, '']
        lines += [f"耗时：{row['seconds']} 秒；模型调用：{row['llm_api_calls']} 次。", '']
    (directory / '碧琪六场景原始回复_中性例子版.md').write_text('\n'.join(lines), encoding='utf-8')
    print(json.dumps(summary['aggregate'], ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    main(parser.parse_args().directory)
