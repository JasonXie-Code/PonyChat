import json, pathlib, sys
from collections import defaultdict

sys.path.insert(0, 'P:/PonyChat/PonyChat-Website/MLP-Songs-AUTO/scripts')
from build_demo import _score_sort_key

d = json.loads(pathlib.Path('P:/PonyChat/PonyChat-Website/MLP-Songs-AUTO/generated/laughter-song/sync.json').read_text())
evs = d['events']

# 分析3个违反行
rows = defaultdict(list)
for ev in evs:
    vis = ev.get('visual') or {}
    y = vis.get('y')
    page = vis.get('page', ev.get('page', 1))
    if y is not None and not ev.get('skipCursorHighlight'):
        rows[(page, round(y, 3))].append(ev)

keys = sorted(rows.keys())
print("=== 违反行详情 ===")
for i in range(1, len(keys)):
    pk, ck = keys[i-1], keys[i]
    prev_times = [e.get('time',0) for e in rows[pk] if e.get('time') is not None]
    cur_times  = [e.get('time',0) for e in rows[ck] if e.get('time') is not None]
    if not prev_times or not cur_times:
        continue
    pm, cm = max(prev_times), min(cur_times)
    if pm > cm + 0.01:
        gap = pm - cm
        print(f"\nVIOLATION: row{pk} last={pm:.3f} > row{ck} first={cm:.3f}  gap={gap:.3f}s")
        # 查找造成 max 的事件
        worst = max(rows[pk], key=lambda e: e.get('time',0))
        print(f"  prev row max event: m{worst.get('measureNo')} b{worst.get('beatInMeasure')} t={worst.get('time')} ly={worst.get('lyric')!r} page={worst.get('page')}")
        # 查找 min 的事件
        best = min(rows[ck], key=lambda e: e.get('time',0))
        print(f"  cur row min event:  m{best.get('measureNo')} b{best.get('beatInMeasure')} t={best.get('time')} ly={best.get('lyric')!r} page={best.get('page')}")
        src = str(best.get('source',''))
        print(f"  cur row min source: {src[:80]}")
        print(f"  gap={gap:.3f}s  {'(repeat 跳过 ✓)' if gap >= 3.0 else '(需要修复!)'}")

# 最后10个有歌词的事件
print()
print("=== 最后15个事件 ===")
lyric_evs = sorted([e for e in evs if e.get('lyric') or e.get('pdfLyricCue')], key=lambda e: e.get('time',0))
for ev in lyric_evs[-15:]:
    vis = ev.get('visual') or {}
    print(f"  m{ev.get('measureNo'):3d} b{ev.get('beatInMeasure')!s:6} t={ev.get('time'):7.3f}  ly={ev.get('lyric') or ev.get('pdfLyricCue')!r:20}  p={vis.get('page')} y={vis.get('y')}")
