"""Comparable real-Agent speech/description fixtures; no production database."""
import argparse
import asyncio
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import verify_normal_bubble_style as probe

CASES = {
    'spoken_action': '把书合上，同时轻声对我说“等我一下”。然后告诉我你猜小猫这会儿在干什么。',
    'spoken_sound': '你伸个懒腰，打个哈欠，把实际发出的“哈……”写出来，再跟我说你想休息一下。',
    'quiet_thought': '只描述你读完书后没有说出口的心理活动，不要任何台词，也不要真的发出声音。',
    'remembered_quote': '回想我以前对你说过的“早点休息”，只写你没有说出口的心理活动，不要说话。',
    'one_bubble': '只回一个气泡：先点头，再对我说“好”。',
}


def validate(case):
    envelope = case.get('reply_envelope') or {}
    parts = [part for bubble in envelope.get('bubbles', []) for part in bubble['parts']]
    spoken = ''.join(part['text'] for part in parts if part['kind'] == 'speech')
    described = ''.join(part['text'] for part in parts if part['kind'] != 'speech')
    label = case['label']
    if not case.get('delivered'):
        return False
    if label == 'spoken_action':
        return '等我一下' in spoken and '等我一下' not in described and any(word in spoken for word in ('我猜', '我想它', '八成'))
    if label == 'spoken_sound':
        return '哈' in spoken and any(word in spoken for word in ('休息', '歇', '眯一会')) and '哈……' not in described
    if label in ('quiet_thought', 'remembered_quote'):
        return not spoken and bool(described)
    return envelope.get('bubble_count') == 1 and '好' in spoken


async def main(args):
    probe.PROFILE = '名称：林夏。28岁成年女性人类，喜欢读书，说话自然，养了一只小猫。'
    probe.CASES.update({key: {'text': text, 'stage': 'familiar'} for key, text in CASES.items()})
    await probe.run(argparse.Namespace(report=args.report, variant=args.variant, wire_audit=False, cases=list(CASES)))
    report = json.loads(args.report.read_text(encoding='utf-8'))
    report['classification_checks'] = {case['label']: validate(case) for case in report['cases']}
    report['classification_passed'] = all(report['classification_checks'].values())
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report['classification_checks'], ensure_ascii=False))
    return 0 if report['classification_passed'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', required=True, type=Path)
    parser.add_argument('--variant', required=True)
    raise SystemExit(asyncio.run(main(parser.parse_args())))
