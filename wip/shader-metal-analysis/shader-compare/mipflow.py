from flow import *
latest, _ = lc.load((sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser('~/.cache/lichii/shader/0400486024dec000/lichii-cache.v2.bin')))
tot = collections.Counter(); progs = collections.defaultdict(list); nprog = 0
for (kind, key), p in latest.items():
    if kind != 1: continue
    pr = lc.program(p)
    if not pr['native'] or pr['stage'] != 4: continue
    nprog += 1
    res, N, _ = analyse(pr['native'])
    for i, conds in res:
        tot['implicit-LOD samples'] += 1
        if not conds: tot['unconditional'] += 1; continue
        cls = 'V' if any(c == 'V' for _, c in conds) else '?' if any(c == '?' for _, c in conds) else 'U'
        tot[{'U': 'conditional, condition quad-uniform', 'V': 'conditional, condition per-pixel', '?': 'conditional, condition unknown'}[cls]] += 1
        if cls != 'U': progs[f'{key:016x}'].append((i, cls, conds))
print('fragment programs:', nprog)
for k, v in tot.most_common(): print(f'{v:7}  {k}')
print('programs with a per-pixel or unknown conditional sample:', len(progs))
for k, v in sorted(progs.items(), key=lambda kv: -len(kv[1]))[:40]: print(k, len(v), [(i, c) for i, c, _ in v][:10])
import json; json.dump(progs, open('mipflow.json', 'w'))
