"""Publish reviewed Chinese daily summaries backed by a complete Git snapshot."""
from collections import defaultdict
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
OUTPUT = Path(__file__).resolve().parents[1] / 'public/changelog/history.json'
SUMMARIES = Path(__file__).resolve().parents[1] / 'src/content/changelog-daily.json'


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT).decode('utf-8')


def main():
    revision = git('rev-parse', 'HEAD').strip()
    lines = git('log', revision, '--format=%H%x09%cs').splitlines()
    sources = defaultdict(list)
    for line in lines:
        sha, date = line.split('\t')
        sources[date].append(sha)
    first_commit = min(sources)
    early = []
    paths = git('ls-tree', '-r', '--name-only', revision, 'change-log').splitlines()
    for path in paths:
        match = re.search(r'/(2026\d{4})-change-log.md$', path)
        if not match or match[1] >= first_commit.replace('-', ''):
            continue
        content = git('show', f'{revision}:{path}')
        topics = [line[3:].strip() for line in content.splitlines() if line.startswith('## ')]
        topics = [topic for topic in topics if topic != '涉及文件']
        date = f'{match[1][:4]}-{match[1][4:6]}-{match[1][6:]}'
        source_revision = git('log', revision, '-1', '--format=%H', '--', path).strip()
        early.append(dict(date=date, source=path, topics=topics, hash=source_revision))
    summaries = json.loads(SUMMARIES.read_text(encoding='utf-8'))
    early_by_date = {entry['date']: entry for entry in early}
    dates = set(sources) | set(early_by_date)
    missing = dates - summaries.keys()
    if missing:
        raise SystemExit(f'Write reviewed Chinese daily summaries for: {sorted(missing)}')
    days = []
    for date in sorted(dates, reverse=True):
        items = summaries[date]
        if not items or not all(re.search(r'[\u4e00-\u9fff]', item) for item in items):
            raise SystemExit(f'Empty or untranslated summary: {date}')
        days.append(dict(date=date, items=items, sources=sources.get(date, []),
                         earlySource=early_by_date.get(date)))
    payload = dict(revision=revision, firstCommit=first_commit, through=max(sources),
                   count=len(lines), days=days)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'{len(lines)} commits, {len(days)} update days, {len(early)} early logs -> {OUTPUT}')


if __name__ == '__main__':
    main()
