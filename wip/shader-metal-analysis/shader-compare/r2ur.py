"""Uniform-register copies (R2UR): is the copied value provably the same for every pixel of the draw?"""
from flow import *
latest, _ = lc.load((sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser('~/.cache/lichii/shader/0400486024dec000/lichii-cache.v2.bin')))
tot = collections.defaultdict(collections.Counter); per = collections.defaultdict(list)
for (kind, key), p in latest.items():
    if kind != 1: continue
    pr = lc.program(p)
    if not pr['native']: continue
    st = str(lc.STAGES.get(pr['stage'], pr['stage']))
    _, N, r2 = analyse(pr['native'], ipa_const_uniform=False)
    c = tot[st]; c['programs'] += 1
    if not r2: continue
    c['programs with R2UR'] += 1; skip = 0
    for i, src, pc in r2:
        c['R2UR'] += 1
        ok = src == 'U' and pc in (None, 'U')
        c['  source draw-uniform, safe to skip'] += ok; skip += ok
        c['  source per-pixel'] += src == 'V'; c['  source unknown'] += src == '?'
        c['  source uniform but predicate per-pixel/unknown'] += src == 'U' and not ok
    c['programs where every R2UR is skippable'] += skip == len(r2)
    per[st].append((len(r2), skip))
for st, c in tot.items():
    print('==', st); [print(f'   {v:6}  {k}') for k, v in c.items()]
