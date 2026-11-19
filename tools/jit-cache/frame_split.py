#!/usr/bin/env python3
"""frame_split.py RUNS_DIR [PHASE]: where the time of an ordinary frame goes, in the JIT and outside it.

Needs runs made with EDEN_NX2_STUTTER_TRACE=1 and EDEN_NX2_STUTTER_ALL_FRAMES=1 (one Nx2Stutter line per frame).
Takes the frames of PHASE (walk, the default, or stand2) of every run, pools the runs of one configuration (label
without its -rN), sorts the frames by length and averages each figure over three bands: the median frames (45th to
55th percentile), the 90th percentile frames (87.5th to 92.5th) and the 99th percentile frames (the top 2 %).

CPU side, summed over the six cores (so it can exceed the frame's length): `run` is the time inside the JIT's Run;
of it, `compile` (translate, emit, link), `lock` (waiting for the code cache's lock) and `fault` (fastmem fault
handling) are the JIT's own work, and the rest is guest code with its callbacks. GPU side: how long the emulator's
GPU threads were busy, and the trace's own per-frame categories."""
import glob, json, os, re, sys
runs_dir = sys.argv[1]; phase = sys.argv[2] if len(sys.argv) > 2 else 'walk'
nxt = {'walk': 'stand2', 'stand2': 'end'}[phase]
pooled = {}
for p in sorted(glob.glob(runs_dir + '/*/result.json')):
    r = json.load(open(p)); t = r.get('t_monotonic') or {}
    if phase not in t or nxt not in t or 'warmup' in r['label'] or 'trace' in r['label']: continue
    lo, hi = (t[phase] - t['start']) / 1e9, (t[nxt] - t['start']) / 1e9
    frames = []
    for l in open(os.path.dirname(p) + '/eden_log.txt', errors='replace'):
        m = re.match(r'\[\s*([\d.]+)\].*Nx2Stutter frame=\d+ ms=([\d.]+) cause=(\S+)(.*) other=([\d.]+) busy=(\S+) builds=\S+ jit=(\S+)', l)
        if not m or not (lo <= float(m[1]) <= hi): continue
        f = {'ms': float(m[2])}
        for k, v in re.findall(r' (\w+)=([\d.]+)', m[4]): f['gpu:' + k] = float(v)
        f['gpu:other'] = float(m[5])
        for part in m[6].split(','):
            if ':' in part: k, v = part.split(':'); f['busy:' + k] = float(v)
        j = dict(kv.split(':') for kv in m[7].split(','))
        f['jit:compile'] = float(j.get('ms', 0)); f['jit:lock'] = float(j.get('lock', 0)); f['jit:fault'] = float(j.get('fault', 0))
        f['cpu:run'] = float(j.get('run', 0)); f['n:blocks'] = float(j.get('blocks', 0)); f['n:faults'] = float(j.get('faults', 0))
        frames.append(f)
    pooled.setdefault(re.sub(r'-r\d+$', '', r['label']), []).extend(frames)
bands = (('median', 0.45, 0.55), ('p90', 0.875, 0.925), ('p99', 0.98, 1.0))
for label, frames in pooled.items():
    frames.sort(key=lambda f: f['ms']); n = len(frames)
    if not n: continue
    print(f'\n== {label}: {n} {phase} frames')
    keys = sorted({k for f in frames for k in f} - {'ms'})
    rows = []
    for name, a, b in bands:
        band = frames[int(a * n):max(int(a * n) + 1, int(b * n))]
        avg = lambda k: sum(f.get(k, 0) for f in band) / len(band)
        rows.append((name, len(band), avg('ms'), {k: avg(k) for k in keys}))
    print('%-34s' % 'frame band' + ''.join('%12s' % f'{name} ({cnt})' for name, cnt, _, _ in rows))
    print('%-34s' % 'frame length, ms' + ''.join('%12.2f' % ms for _, _, ms, _ in rows))
    def line(title, fn, fmt='%12.2f'): print('%-34s' % title + ''.join(fmt % fn(v) for _, _, _, v in rows))
    jit = lambda v: v['jit:compile'] + v['jit:lock'] + v['jit:fault']
    line('CPU cores inside the JIT run, ms', lambda v: v['cpu:run'])
    line('  JIT work: compile', lambda v: v['jit:compile'])
    line('  JIT work: waiting for cache lock', lambda v: v['jit:lock'])
    line('  JIT work: fastmem fault handling', lambda v: v['jit:fault'])
    line('  guest code and callbacks', lambda v: v['cpu:run'] - jit(v))
    line('  JIT work as % of core time', lambda v: 100 * jit(v) / v['cpu:run'] if v['cpu:run'] else 0, '%11.1f%%')
    line('blocks compiled per frame', lambda v: v['n:blocks'], '%12.1f')
    line('fastmem faults per frame', lambda v: v['n:faults'], '%12.1f')
    for k in keys:
        if k.startswith('busy:'): line('GPU thread busy: ' + k[5:] + ', ms', lambda v, k=k: v[k])
    for k in keys:
        if k.startswith('gpu:') and any(v[k] >= 0.05 for _, _, _, v in rows): line('trace category: ' + k[4:] + ', ms', lambda v, k=k: v[k])
