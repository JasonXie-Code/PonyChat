import json, pathlib
from collections import defaultdict

d = json.loads(pathlib.Path('P:/PonyChat/PonyChat-Website/MLP-Songs-AUTO/generated/love-in-bloom/sync.json').read_text())
evs = d['events']

print("=" * 60)
print("修复一：行边界 'here' 跳跃问题 (m38 -> m39)")
print("=" * 60)
for ev in evs:
    m = int(ev.get('measureNo', 0) or 0)
    b = ev.get('beatInMeasure', 0)
    t = ev.get('time', 0)
    ly = ev.get('lyric', '')
    vis = ev.get('visual') or {}
    y = vis.get('y', '?')
    if m == 38 and b >= 3.0:
        print(f"  m38 b{b} t={t}  ly={ly!r}  y={y}")
    if m == 39 and b == 0.0:
        print(f"  m39 b{b} t={t}  ly={ly!r}  y={y}")
        print()
        prev_t = 67.920
        gap = round(float(t) - prev_t, 3)
        print(f"  gap = {t} - 67.920 = {gap}s  =>  " + ("✓ 正常（>0）" if gap > 0 else "✗ 仍有反转！"))

print()
print("=" * 60)
print("修复二：'cause' -> 'love' 最小间距 100ms")
print("=" * 60)
for ev in evs:
    m = int(ev.get('measureNo', 0) or 0)
    b = ev.get('beatInMeasure', 0)
    t = ev.get('time', 0)
    ly = ev.get('lyric', '')
    if m == 41 and b >= 1.5:
        print(f"  m41 b{b} t={t}  ly={ly!r}")
    if m == 42 and b == 0.0:
        print(f"  m42 b{b} t={t}  ly={ly!r}")
        prev_t = 71.5983
        gap = round(float(t) - prev_t, 3)
        print(f"  cause->love gap = {t} - 71.598 = {gap}s  =>  " + ("✓ ≥ 100ms" if gap >= 0.099 else "✗ 间距太短！"))

print()
print("=" * 60)
print("行边界全检")
print("=" * 60)
rows = defaultdict(list)
for ev in evs:
    vis = ev.get('visual') or {}
    y = vis.get('y')
    page = vis.get('page', ev.get('page', 1))
    if y is not None and ev.get('skipCursorHighlight') is not True:
        rows[(page, round(y, 3))].append(ev)

keys = sorted(rows.keys())
all_ok = True
for i in range(1, len(keys)):
    pk, ck = keys[i-1], keys[i]
    prev_times = [ev.get('time', 0) for ev in rows[pk] if ev.get('time') is not None]
    cur_times  = [ev.get('time', 0) for ev in rows[ck] if ev.get('time') is not None]
    if not prev_times or not cur_times:
        continue
    pm = max(prev_times)
    cm = min(cur_times)
    if pm > cm + 0.01:
        gap = round(pm - cm, 3)
        print(f"  VIOLATION row{pk} last={pm:.3f}  > row{ck} first={cm:.3f}  (gap={gap})")
        all_ok = False
if all_ok:
    print("  全部行边界 ✓ 正常")
