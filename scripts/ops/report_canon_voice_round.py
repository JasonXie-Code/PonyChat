"""Pair complete route samples without selecting only successful style examples."""
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'docs/testing/canon-voice-round1-20260910'


def stats(cases):
    replies = [p for c in cases for p in c['paragraphs']]
    lengths = [len(re.sub(r'\s', '', p)) for p in replies]
    narrative = sum(n for p, n in zip(replies, lengths) if p.startswith('（') and p.endswith('）'))
    return {'turns': len(cases), 'bubbles': len(replies), 'characters': sum(lengths),
            'mean_characters': round(sum(lengths)/len(cases), 2),
            'narrative_percent': round(narrative/sum(lengths)*100, 2)}


def main():
    data = {n: json.loads((OUT/n/'raw.json').read_text(encoding='utf-8')) for n in ('baseline', 'candidate')}
    reviews = json.loads((OUT/'review.json').read_text(encoding='utf-8'))
    assert all(d['passed'] and len(d['cases']) == 9 for d in data.values())
    metrics = {n: stats(d['cases']) for n,d in data.items()}
    summary = {'metrics': metrics, 'decision': reviews['decision'], 'assessment': 'Codex qualitative review; not blind or statistically calibrated.',
               'prompt_hashes': {n: hashlib.sha256((OUT/n/'autonomous_direct.py').read_bytes()).hexdigest() for n in data}}
    (OUT/'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# 原作对白参考优化：第一轮完整对照', '', reviews['decision'], '',
             '英文短句、中文工作译文与来源说明见 REFERENCES.md。参考为社区转录的动画台词，非官方发布剧本，未逐帧核对。三个片段只能支持局部表达观察。', '',
             '使用三位完整档案角色、三个新聊天场景，在隔离数据库通过真实 /api/chat 路由调用同一模型 deepseek-v4-flash-vision-exp（low）。每版九条，未调用角色原作台词作正确答案。所有 SSE、交付 envelope、工具轨迹见各版 raw.json；不是供应商逐请求网络原文。', '',
             '候选仅重写三条表达规则：让台词完成当下交流目的，动作按实际需要展开，用户纠正后直接落实改法。图片、偏好、第三人称/重复动作例外及传输格式未改。candidate/prompt.diff 保留差异。', '',
             '这是一次提示词候选评估；正式采样前修复过候选快照的字符串闭合错误，该失败发生在导入阶段，没有生成模型回复。', '',
             '## 可复算指标', '', '|版本|回复数|气泡数|平均非空白字符|描写字符占比|', '|---|---:|---:|---:|---:|']
    for name,s in metrics.items():
        lines.append(f"|{name}|{s['turns']}|{s['bubbles']}|{s['mean_characters']}|{s['narrative_percent']}%|")
    lines += ['', '字符统计含标点；描写按整段括号气泡统计。短不必然好，描写占比低也不必然更符合角色；这里只描述变化，不当作自然度总分。', '', '## 逐条结论与全部交付原文']
    assert len(reviews['items']) == 9
    for old,new,review in zip(data['baseline']['cases'],data['candidate']['cases'],reviews['items']):
        assert (old['scenario'],old['character_id']) == (new['scenario'],new['character_id'])
        lines += ['', f"### {old['character_name']} / {old['label']}", '', '用户：'+old['input'], '', review]
        for title,row in [('原版',old),('候选',new)]:
            lines += ['',title,'','```text','\n\n'.join(row['paragraphs']),'```']
    lines += ['', '## 尚未验证', '', '没有对长期多轮、全部六位角色或亲密场景证明提升；原作短句也不能直接代表这些场景。未通过自然度接受判断的候选不部署，不将技术交付成功等同于风格升级。']
    (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False))


if __name__ == '__main__':
    main()
