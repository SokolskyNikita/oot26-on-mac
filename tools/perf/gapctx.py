#!/usr/bin/env python3
"""gapctx.py PROF RUN_DIR: for the frames the profiler dumped encoder by encoder (every 150th), print the GPU idle gaps
of 100 us or more with the last encoders of the command buffer before each gap and the first of the one after it.
Then a tally over all sampled frames of (last encoder before, first encoder after)."""
import re, struct, sys
from collections import Counter
from pathlib import Path
prof, run = sys.argv[1], Path(sys.argv[2])
out = (run.parent / (run.name + ".out")).read_text()
mk = {m.group(1): int(m.group(2)) for m in re.finditer(r"mark (\S+) frame (\d+)", out)}
raw = (run / "frames.bin").read_bytes(); t = struct.unpack(f"<{len(raw)//8}Q", raw[:len(raw)//8*8])
w0, w1 = t[mk["loaded-standing"]] / 1e3, t[min(mk.get("walk1", len(t)-1), len(t)-1)] / 1e3
cbs = []; cur = None
for line in open(prof, errors="replace"):
    f = line.split()
    if not f: continue
    if f[0] == "C" and len(f) > 8:
        cur = dict(gs=float(f[2]), ge=float(f[3]), ks=float(f[6]), ke=float(f[7]), cr=float(f[8]), n=int(f[4]), enc=[], sig=[])
        cbs.append(cur)
    elif f[0] == "E" and cur is not None: cur["enc"].append(f[2])
    elif f[0] == "S" and cur is not None: cur["sig"].append((f[1], int(f[2])))
cbs = [c for c in cbs if c["gs"] >= w0 and c["ge"] <= w1]; cbs.sort(key=lambda c: c["gs"])
def short(s): return re.sub(r"0000000000000000:0", "mvk", s)
tally = Counter(); shown = 0; busy_end = None; prev = None; ngap = 0; tot = 0.0
for c in cbs:
    if busy_end is not None and c["gs"] > busy_end and c["gs"] - busy_end >= 100:
        gap = c["gs"] - busy_end
        kind = "created-after" if c["cr"] >= busy_end else "committed-late" if c["ks"] >= busy_end else "scheduled-late"
        if prev["enc"] and c["enc"]:
            ngap += 1; tot += gap
            key = (kind, short(prev["enc"][-1]), short(c["enc"][0]))
            tally[key] += gap
            if shown < 14:
                shown += 1
                print(f"gap {gap:6.0f} us {kind:14} prev CB {prev['n']:3} enc, GPU {prev['ge']-prev['gs']:6.0f} us, ends: {' | '.join(short(e) for e in prev['enc'][-3:])}")
                print(f"{'':28} next CB {c['n']:3} enc, created {c['cr']-busy_end:+6.0f} us after idle, commit {c['ks']-busy_end:+6.0f}; starts: {' | '.join(short(e) for e in c['enc'][:3])}")
    if busy_end is None or c["ge"] > busy_end: busy_end, prev = c["ge"], c
print(f"\nsampled gaps: {ngap}, {tot/1e3:.1f} ms total. By (kind, last encoder before, first encoder after), share of sampled gap time:")
for (k, a, b), v in tally.most_common(25):
    print(f"  {100*v/tot:5.1f}%  {k:14} {a:44} -> {b}")
