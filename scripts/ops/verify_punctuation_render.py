"""Replay captured parts against the shared renderer without loading the app/DB."""
import argparse
import hashlib
import json
from pathlib import Path
import runpy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('fixture', help='JSON replay report containing bubble and expected after text')
    parser.add_argument('--source', default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument('--expected-sha256', required=True)
    parser.add_argument('--report', required=True)
    args = parser.parse_args()
    source = Path(args.source).resolve() / 'Backend/chat_modules/normal_parts.py'
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    assert digest == args.expected_sha256, 'Renderer does not match the expected release'
    render = runpy.run_path(str(source))['_normal_stage3_render_parts_bubble']
    fixture = json.loads(Path(args.fixture).read_text(encoding='utf-8-sig'))
    assert fixture['cases'], 'No replay cases supplied'
    cases = []
    for item in fixture['cases']:
        text, _, error = render(item['bubble'], item['bubble']['index'])
        cases.append({'log_id': item['log_id'], 'trace_id': item['trace_id'],
                      'bubble_index': item['bubble']['index'], 'rendered': text,
                      'passed': not error and text == item['after'], 'error': error})
    result = {'passed': all(case['passed'] for case in cases), 'source_sha256': digest,
              'source': str(source), 'production_database_opened': False,
              'model_calls': 0, 'cases': cases}
    Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'passed': result['passed'], 'cases': len(cases), 'source_sha256': digest}))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
