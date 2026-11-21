"""Summarize immutable real-route samples without rewriting their messages."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics


def summarize(directory):
    data = json.loads((directory / 'results.json').read_text(encoding='utf-8'))
    rows = []
    for entry in data['rows']:
        case = entry['case']
        agents = case.get('agent_calls', [])
        attempts = [a for agent in agents for a in agent.get('harness_attempts', [])]
        reviews = [agent.get('prompt_skills', {}).get('expression_review', {}) for agent in agents]
        usage = {key: sum(a.get('usage', {}).get(key, 0) for a in attempts)
                 for key in ('prompt_tokens', 'completion_tokens', 'total_tokens')}
        rows.append({
            'scenario': entry['scenario'], 'label': entry['label'],
            'input': entry['input'], 'paragraphs': case.get('paragraphs', []),
            'passed': case.get('passed', False), 'seconds': case.get('seconds'),
            'usage': usage, 'llm_api_calls': sum(a.get('llm_api_calls', 0) or 0 for a in attempts),
            'review_seconds': round(sum(r.get('seconds', 0) for r in reviews), 3),
            'review_passes': sum(len(r.get('passes', [])) for r in reviews),
            'review_complete': bool(reviews) and all(r.get('status') == 'reviewed' for r in reviews),
            'models': sorted({a.get('model') or 'unavailable' for a in attempts}),
        })
    times = [row['seconds'] for row in rows if row['seconds'] is not None]
    return {
        'round': directory.name, 'inputs_sha256': data['inputs_sha256'],
        'runtime_sha256': data['runtime_sha256'], 'rows': sorted(rows, key=lambda r: r['scenario']),
        'aggregate': {
            'cases': len(rows), 'transport_passed': sum(row['passed'] for row in rows),
            'reviews_complete': sum(row['review_complete'] for row in rows),
            'mean_seconds': round(statistics.mean(times), 3),
            'median_seconds': round(statistics.median(times), 3), 'max_seconds': max(times),
            'mean_review_seconds': round(statistics.mean(row['review_seconds'] for row in rows), 3),
            'llm_api_calls': sum(row['llm_api_calls'] for row in rows),
            **{key: sum(row['usage'][key] for row in rows)
               for key in ('prompt_tokens', 'completion_tokens', 'total_tokens')},
        },
        'limitations': 'Isolated DB, real /api/chat and Flash, six simultaneous first turns. '
                        'Token totals are SDK observations, not a monetary bill or production latency SLA. '
                        'Semantic quality requires a separate review; transport pass is not quality pass.',
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    result = summarize(args.directory)
    (args.directory / 'summary.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result['aggregate'], ensure_ascii=False))


if __name__ == '__main__':
    main()
