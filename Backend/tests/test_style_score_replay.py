import importlib.util
import json
from pathlib import Path


spec = importlib.util.spec_from_file_location('tested_style_score_replay',
    Path(__file__).parents[1] / 'Agent-Test' / 'write_style_scores.py')
scores = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scores)


def test_replayed_prefix_never_enters_generated_score_or_latency(tmp_path):
    source = {'turns': [{'turn': 1, 'replayed': True, 'seconds': 9999},
                       {'turn': 5, 'seconds': 2, 'phase': '简单提问', 'user_message': '现在呢？',
                        'delivered_messages': ['现在很好'], 'passed': True, 'model_attempts': [{'llm_api_calls': 1}]}],
              'bootstrap': {'source': 'prior-run.json'}}
    grades = {'characters': {'lotus_blossom': [{'turn': 5, 'scores': [4, 4, 4, 4, 4], 'note': '本轮评价'}]},
              'conclusion': '一个新样本', 'next_step': '继续调查'}
    (tmp_path / 'lotus_blossom.json').write_text(json.dumps(source), encoding='utf-8')
    (tmp_path / 'scores.json').write_text(json.dumps(grades), encoding='utf-8')
    scores.write(tmp_path)
    text = (tmp_path / '打分表.md').read_text(encoding='utf-8')
    assert '| 整体 | 1 | 4.000 |' in text
    assert '中位数：2.00 秒' in text and '| 芙蓉 | 5-5 |' in text
    assert '不计新生成评分' in (tmp_path / '原始对话.md').read_text(encoding='utf-8')
