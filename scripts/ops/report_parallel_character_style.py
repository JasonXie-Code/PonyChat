"""Pair every concurrent candidate output with its frozen baseline."""
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'docs/testing/character-led-parallel-20260910'


def main():
    data = json.loads((OUT / 'parallel.json').read_text(encoding='utf-8'))
    baseline_path = ROOT / 'docs/testing/four-character-three-scene-20260910/raw.json'
    baseline = json.loads(baseline_path.read_text(encoding='utf-8'))
    reviews = json.loads((OUT / 'review.json').read_text(encoding='utf-8'))
    assert len(data['rows']) == 12
    old = {(r['scenario'], r['character_id'].removeprefix('style-' + r['scenario'] + '-')): r
           for r in baseline['cases']}
    lines = ['# 角色自主表达：并发十二格对照', '', reviews['summary'], '',
             '## 方法与限制', '',
             '同一组四角色、三场景、冻结完整角色档案，当前 deepseek-flash（V4.1 Flash）和 low 推理。保留设定检索、图片回应、动作范围、传输和明确用户要求；本轮只改共享表达规则。', '',
             f"候选使用十二个独立数据库和测试进程并发运行，最大重叠进程数 {data['max_overlapping_workers']}，总耗时 {data['wall_seconds']} 秒。该指标不是供应商 GPU 并发度。基线为之前顺序执行的十二条，没有同步重采样或固定随机种子；负载和采样随机性均可能影响结果。", '',
             '这是同一优化者的定性审阅，不是盲评或校准分数。每格仅一条，不能证明稳定风格提升。台词比喻允许，不按身体部位关键词扣分。冲突场景无前置说教原文，只检查如何承接用户投诉。', '',
             '## 全部原始回复与逐条判断']
    counts = {'baseline': [], 'candidate': []}
    for i, cell in enumerate(data['rows'], 1):
        key = (cell['scenario'], cell['character_id'])
        before = old[key]
        candidates = cell.get('result', {}).get('cases', [])
        after = candidates[0] if candidates else None
        label = key[0] + '_' + key[1]
        lines += ['', f"### {i:02} · {before['label']} / {before['character_name']}", '',
                  '用户：' + before['input'], '', '我的观察：' + reviews['items'][label], '',
                  '你的意见：' + reviews.get('user_reviews', {}).get(label, '待填写。')]
        for title, row in [('baseline', before), ('candidate', after)]:
            lines += ['', '原版' if title == 'baseline' else '本轮候选', '']
            if row:
                assert row['input'] == before['input']
                counts[title].append(sum(len(re.sub(r'\s', '', p)) for p in row['paragraphs']))
                lines += ['```text', '\n\n'.join(row['paragraphs']), '```']
            else:
                lines += ['本格未成功交付，见该格日志。没有删去或用补跑覆盖。']
    metrics = {k: {'samples': len(v), 'mean_characters': round(sum(v) / len(v), 2) if v else None}
               for k, v in counts.items()}
    lines += ['', '## 可复算长度指标', '', json.dumps(metrics, ensure_ascii=False), '',
              '字符含标点，短不等于好。parallel.json 和 cells 下 raw.json 保存所有原始 SSE、交付对象、检索记录、执行时间；没有挑选回复。回滚快照与 candidate.py 保留前后提示词。部署状态另见 deployment.json（如存在）。']
    (OUT / 'REPORT.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    (OUT / 'metrics.json').write_text(json.dumps(metrics, indent=2), encoding='utf-8')
    print(json.dumps(metrics))


if __name__ == '__main__':
    main()
