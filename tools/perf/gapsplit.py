#!/usr/bin/env python3
"""gapsplit.py PROF SYNC RUN_DIR: split each "created-after" GPU idle gap (standing phase) into its hops:
  A  GPU idle -> the flush that submits the next command buffer (Lichii's back thread: guest and emulator CPU work)
  B  that flush -> MoltenVK starts encoding it (Vulkan worker picks it up)
  C  encoding (first encoder created -> commit)
  D  commit -> GPU starts
and report how long the GPU worked on the command buffer before the gap and how many draws worth of encoders the
next one holds."""
import re, struct, sys, bisect, statistics as S
from pathlib import Path
prof, trace, run = sys.argv[1], sys.argv[2], Path(sys.argv[3])
out = (run.parent / (run.name + ".out")).read_text()
mk = {m.group(1): int(m.group(2)) for m in re.finditer(r"mark (\S+) frame (\d+)", out)}
raw = (run / "frames.bin").read_bytes(); t = struct.unpack(f"<{len(raw)//8}Q", raw[:len(raw)//8*8])
i0, i1 = mk["loaded-standing"], min(mk.get("walk1", len(t)-1), len(t)-1); w0, w1, nfr = t[i0] / 1e3, t[i1] / 1e3, i1 - i0
cbs = []
for line in open(prof, errors="replace"):
    f = line.split()
    if f and f[0] == "C" and len(f) > 8 and float(f[2]) >= w0 and float(f[3]) <= w1:
        cbs.append((float(f[2]), float(f[3]), float(f[6]), float(f[7]), float(f[8]), int(f[4])))
cbs.sort()
ft = sorted(int(l.split()[0]) / 1e3 for l in open(trace, errors="replace") if " flush " in l or " finish " in l)
A, B, C, D, G, NE = [], [], [], [], [], []; busy_end = None; tot = 0
for gs, ge, ks, ke, cr, n in cbs:
    if busy_end is not None and gs - busy_end >= 100 and cr >= busy_end:
        j = bisect.bisect_right(ft, cr) - 1
        f2 = ft[j] if j >= 0 else cr
        a = max(f2 - busy_end, 0.0); b = cr - max(f2, busy_end)
        A.append(a); B.append(b); C.append(ks - cr); D.append(gs - ks); G.append(gs - busy_end); NE.append(n); tot += gs - busy_end
    if busy_end is None or ge > busy_end: busy_end = ge
m = lambda x: S.median(x); k = len(G)
print(f"{k / nfr:.1f} gaps/frame, {tot / nfr / 1e3:.2f} ms/frame; per gap: median {m(G):.0f} us, mean {sum(G)/k:.0f} us")
for name, x in (("A  GPU idle -> next flush (CPU produces the next commands)", A), ("B  flush -> encoding starts", B), ("C  encoding -> commit", C), ("D  commit -> GPU start", D)):
    print(f"  {name:58} median {m(x):5.0f} us  mean {sum(x)/k:5.0f} us  = {sum(x) / nfr / 1e3:.2f} ms/frame")
print(f"  encoders in the command buffer after a gap: median {m(NE):.0f}; gaps where the next flush came before the GPU went idle: {sum(1 for a in A if a == 0) / k:.0%}")
