#!/usr/bin/env python3
"""modecmp.py LABEL A0 A1 B0 B1: compare two frame ranges of the standing phase (frame offsets) of a run that has a
MoltenVK profile and a P60_SYNC_TRACE: frame time, GPU busy, and per frame the traced waits, flushes and buffer copies."""
import re, struct, sys, bisect, statistics as S
from collections import Counter
from pathlib import Path
import os, subprocess
REPO = subprocess.check_output(["git", "rev-parse", "--show-toplevel"],
                               cwd=os.path.dirname(os.path.abspath(__file__)), text=True).strip()
MV = Path(REPO + "/build/old-trees")
lab = sys.argv[1]; ranges = [(int(sys.argv[2]), int(sys.argv[3])), (int(sys.argv[4]), int(sys.argv[5]))]
SITES = ["Other", "FetchDrain", "Acquire", "SemaphoreFlush", "FenceRelease", "ListWriters", "ListCopies", "ListSync", "ListFlush",
         "MacroDmaRead", "MacroDmaWrites", "MacroDmaFlush", "GpSyncFence", "Map"]
run = MV / "sc-update/runs" / lab
mk = {m.group(1): int(m.group(2)) for m in re.finditer(r"mark (\S+) frame (\d+)", (MV / "sc-update/runs" / (lab + ".out")).read_text())}
b = (run / "frames.bin").read_bytes(); t = [x / 1e3 for x in struct.unpack(f"<{len(b)//8}Q", b)]
a = mk["loaded-standing"]
ev = []
for line in open(MV / "path-60/runs" / (lab + ".sync"), errors="replace"):
    f = line.split()
    if len(f) < 5: continue
    ts = int(f[0]) / 1e3
    if f[1] in ("flush", "finish"): ev.append((ts, "n " + f[1] + " " + Path(f[2]).name + ":" + f[3], 1))
    elif f[1] == "gpuwait": ev.append((ts, "ms Scheduler::Wait for host GPU", int(f[4]) / 1e6))
    elif f[1] == "frontwait": ev.append((ts, "ms front waits for back: " + SITES[min(int(f[3]), 13)], int(f[4]) / 1e6)); ev.append((ts, "n front waits for back: " + SITES[min(int(f[3]), 13)], 1))
    elif f[1] == "hostwait": ev.append((ts, "ms read download waits for host GPU (" + f[2] + ")", int(f[3]) / 1e6)); ev.append((ts, "n read download waits (" + f[2] + ")", 1))
    elif f[1].startswith("copy"): ev.append((ts, f"KiB {f[1]} {f[2]}:{f[3]}", int(f[4]) / 1024)); ev.append((ts, f"n {f[1]} {f[2]}:{f[3]}", 1))
cbs = []
for line in open(MV / "path-60/runs" / (lab + ".prof"), errors="replace"):
    f = line.split()
    if f and f[0] == "C" and len(f) > 8: cbs.append((float(f[2]), float(f[3])))
res = []
for (r0, r1) in ranges:
    w0, w1, n = t[a + r0], t[a + r1], r1 - r0
    d = [(t[a + i + 1] - t[a + i]) / 1e3 for i in range(r0, r1)]
    c = Counter()
    for ts, k, v in ev:
        if w0 <= ts < w1: c[k] += v
    busy = sum(ge - gs for gs, ge in cbs if gs >= w0 and ge <= w1) / n / 1e3
    res.append((S.median(d), sum(d) / n, busy, {k: v / n for k, v in c.items()}))
print(f"{lab}: frames {ranges[0]} vs {ranges[1]}: median {res[0][0]:.1f} vs {res[1][0]:.1f} ms, mean {res[0][1]:.1f} vs {res[1][1]:.1f}, GPU work/frame {res[0][2]:.1f} vs {res[1][2]:.1f} ms")
keys = sorted(set(res[0][3]) | set(res[1][3]), key=lambda k: -max(res[0][3].get(k, 0), res[1][3].get(k, 0)) if k.startswith("ms") else 0)
for pref in ("ms", "n", "KiB"):
    rows = [(k, res[0][3].get(k, 0), res[1][3].get(k, 0)) for k in keys if k.startswith(pref + " ")]
    rows.sort(key=lambda r: -max(r[1], r[2]))
    for k, x, y in rows[:14]:
        if max(x, y) >= 0.05: print(f"  {x:9.2f} {y:9.2f}  {k} per frame")
