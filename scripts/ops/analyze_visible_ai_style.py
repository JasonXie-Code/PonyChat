"""Reproducible descriptive metrics, not an AI-authorship probability detector."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'docs/testing/visible-ai-style-20260910'
SOURCES = {
    'fluttershy': '20260910_152238_930-e8d8e3461e51_normal_AGENT_PERSIST_RESULT_fluttershy__u_1.js',
    'twilight': '20260910_151711_565-a71294456d6e_normal_AGENT_PERSIST_RESULT_twilight_sparkle__u_1.js',
}
SOFT = r'轻轻|慢慢|缓缓|一下|一点|一会儿|一动不动'
MOTIFS = {'呼吸': r'呼吸|屏住', '眼睫': r'睫毛|眼睛', '发热': r'烫|热|红',
          '心跳': r'心跳', '耳朵': r'耳朵|耳根', '翅膀': r'翅膀', '蹄子': r'前蹄|蹄尖',
          '靠近接触': r'挪|搭在|抵在|贴在|滑了', '被子': r'被子'}
META = [r'好，重新说，这次我慢慢说。', r'这一次我不排步骤[^。\n]*', r'这次我不抢着[^。\n]*']


def length(text):
    return len(re.sub(r'\s', '', text))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    detector = ROOT / 'docs/research/ai-style-libraries-20260910/zh-ai-flavor-rules/src/detect.ts'
    rules = detector.parent.parent / 'rules/rules.json'
    report = {'method': 'Upstream v10.7 plus transparent descriptive counts; no calibrated aggregate score or authorship probability.',
              'length_definition': 'All non-whitespace characters, including punctuation; narrative classified by whole parenthesized bubble.',
              'detector_sha256': hashlib.sha256(detector.read_bytes()).hexdigest(),
              'rules_sha256': hashlib.sha256(rules.read_bytes()).hexdigest(),
              'soft_regex': SOFT, 'motif_regex': MOTIFS, 'meta_regex': META, 'samples': {}}
    for name, filename in SOURCES.items():
        path = ROOT / 'var/.chatlogs/2026-09-10/15' / filename
        source = path.read_text(encoding='utf-8')
        match = re.search(r'"submitted_reply": `([^`]+)`', source)
        assert match, filename
        text = match.group(1)
        raw_path = OUT / (name+'.txt')
        raw_path.write_text(text, encoding='utf-8')
        upstream = subprocess.run(['node', '--experimental-strip-types', str(detector), '--file', str(raw_path)],
                                  capture_output=True, text=True, encoding='utf-8', check=True)
        bubbles = text.split('\n\n')
        narrative = [b for b in bubbles if b.startswith('（') and b.endswith('）')]
        meta = [m.group() for pattern in META for m in re.finditer(pattern, text)]
        clauses = [s for s in re.split('[，。；！？\n]+', text) if s.strip()]
        report['samples'][name] = {
            'source': str(path.relative_to(ROOT)), 'source_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'text': text, 'upstream': json.loads(upstream.stdout), 'characters': length(text),
            'bubbles': len(bubbles), 'shape': ['描写' if b in narrative else '台词' for b in bubbles],
            'narrative_characters': sum(length(b) for b in narrative),
            'narrative_percent': round(100*sum(length(b) for b in narrative)/length(text), 2),
            'softeners': dict(Counter(re.findall(SOFT, text))),
            'motifs': {k: re.findall(pattern, text) for k, pattern in MOTIFS.items() if re.search(pattern, text)},
            'meta_spans': meta, 'meta_characters': sum(length(s) for s in meta),
            'meta_percent': round(100*sum(length(s) for s in meta)/length(text), 2),
            'clause_count': len(clauses),
            'mean_clause_characters': round(sum(length(c) for c in clauses)/len(clauses), 2),
        }
    report['shared_motifs'] = sorted(set.intersection(*(set(s['motifs']) for s in report['samples'].values())))
    (OUT/'analysis.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: {x: v[x] for x in ('upstream','characters','shape','narrative_percent','softeners','meta_percent','meta_spans')}
                      for k,v in report['samples'].items()}, ensure_ascii=False, indent=2))
    print('shared motifs:', report['shared_motifs'])


if __name__ == '__main__':
    main()
