import json, pathlib
from collections import defaultdict

def check_song(song_id):
    path = pathlib.Path(f'P:/PonyChat/PonyChat-Website/MLP-Songs-AUTO/generated/{song_id}/sync.json')
    d = json.loads(path.read_text())
    evs = d['events']
    rows = defaultdict(list)
    for ev in evs:
        vis = ev.get('visual') or {}
        y = vis.get('y')
        page = vis.get('page', ev.get('page', 1))
        if y is not None and not ev.get('skipCursorHighlight'):
            rows[(page, round(y, 3))].append(ev)
    keys = sorted(rows.keys())
    violations = []
    for i in range(1, len(keys)):
        pk, ck = keys[i-1], keys[i]
        prev_times = [e.get('time',0) for e in rows[pk] if e.get('time') is not None]
        cur_times  = [e.get('time',0) for e in rows[ck] if e.get('time') is not None]
        if not prev_times or not cur_times: continue
        pm, cm = max(prev_times), min(cur_times)
        if pm > cm + 0.01:
            violations.append((pk, ck, pm, cm))
    return violations

for song in ['catchy-song', 'love-in-bloom', 'smile-song', 'laughter-song']:
    v = check_song(song)
    small = [(pk,ck,pm,cm) for pk,ck,pm,cm in v if pm-cm < 3.0]
    large = [(pk,ck,pm,cm) for pk,ck,pm,cm in v if pm-cm >= 3.0]
    if not v:
        print(f'{song}: 全部正常 ✓')
    elif not small:
        print(f'{song}: {len(large)} 个重复段大间距（均 >=3s，正常跳过） ✓')
    else:
        for pk,ck,pm,cm in small:
            print(f'{song}: VIOLATION row{pk} last={pm:.3f} > row{ck} first={cm:.3f} gap={pm-cm:.3f}')
        if large:
            print(f'  另有 {len(large)} 个重复段大间距（正常跳过）')
