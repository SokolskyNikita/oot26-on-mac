#!/usr/bin/env python3
"""gaptrace.py PROF SYNC_TRACE RUN_DIR: match the GPU idle gaps of the standing phase (MoltenVK profile) with Lichii's
sync events (P60_SYNC_TRACE). For every "created-after" gap of 100 us or more it takes the last flush before the next
command buffer's first encoder and the waits that overlap the gap, and tallies gap time by them."""
import re, struct, sys, bisect
from collections import Counter, defaultdict
from pathlib import Path
prof, trace, run = sys.argv[1], sys.argv[2], Path(sys.argv[3])
SITES = ["Other", "FetchDrain", "Acquire", "SemaphoreFlush", "FenceRelease", "ListWriters", "ListCopies", "ListSync", "ListFlush",
         "MacroDmaRead", "MacroDmaWrites", "MacroDmaFlush", "GpSyncFence", "Map"]
out = (run.parent / (run.name + ".out")).read_text()
mk = {m.group(1): int(m.group(2)) for m in re.finditer(r"mark (\S+) frame (\d+)", out)}
raw = (run / "frames.bin").read_bytes(); t = struct.unpack(f"<{len(raw)//8}Q", raw[:len(raw)//8*8])
i0, i1 = mk["loaded-standing"], min(mk.get("walk1", len(t)-1), len(t)-1)
w0, w1, nfr = t[i0] / 1e3, t[i1] / 1e3, i1 - i0
cbs = []
for line in open(prof, errors="replace"):
    f = line.split()
    if f and f[0] == "C" and len(f) > 8 and float(f[2]) >= w0 and float(f[3]) <= w1:
        cbs.append((float(f[2]), float(f[3]), float(f[6]), float(f[7]), float(f[8])))
cbs.sort()
flushes, waits = [], []   # (time_us, where) ; (start_us, end_us, kind)
for line in open(trace, errors="replace"):
    f = line.split()
    if len(f) < 5: continue
    ts = int(f[0]) / 1e3
    if ts < w0 - 1e5 or ts > w1 + 1e5: continue
    if f[1] in ("flush", "finish"): flushes.append((ts, f"{f[1]} {Path(f[2]).name}:{f[3]}"))
    elif f[1] == "gpuwait": waits.append((ts - int(f[4]) / 1e3, ts, "wait for host GPU tick (Scheduler::Wait)"))
    elif f[1] == "frontwait":
        s = int(f[3]); waits.append((ts - int(f[4]) / 1e3, ts, "front waits for back: " + (SITES[s] if s < len(SITES) else str(s))))
    elif f[1] == "hostwait": waits.append((ts - int(f[3]) / 1e3, ts, f"read download waits for host GPU ({f[2]})"))
flushes.sort(); ft = [x[0] for x in flushes]
waits_by_end = sorted(waits, key=lambda w: w[1]); wends = [w[1] for w in waits_by_end]
by_flush, by_wait = Counter(), Counter(); cnt_flush = Counter(); total = 0.0; n = 0; busy_end = None
allwait = Counter()
for s, e, k in waits: allwait[k] += e - s
for gs, ge, ks, ke, cr in cbs:
    if busy_end is not None and gs - busy_end >= 100 and cr >= busy_end:
        gap = gs - busy_end; total += gap; n += 1
        j = bisect.bisect_right(ft, cr) - 1
        key = flushes[j][1] if j >= 0 and cr - flushes[j][0] < 5000 else "no flush within 5 ms"
        # the flush that submitted the command buffer the GPU ran last before going idle
        j2 = bisect.bisect_right(ft, busy_end) - 1
        prev = flushes[j2][1] if j2 >= 0 else "?"
        by_flush[prev] += gap; cnt_flush[prev] += 1
        ov = Counter()
        j0 = bisect.bisect_left(wends, busy_end)
        for ws, we, k in waits_by_end[j0:j0 + 4000]:
            if ws >= gs and we - ws < 1e5 and we > gs + 2e5: break
            o = min(we, gs) - max(ws, busy_end)
            if o > 0: ov[k] += o
        if ov:
            k, o = ov.most_common(1)[0]; by_wait[k] += gap
        else: by_wait["no traced wait overlaps the gap"] += gap
    if busy_end is None or ge > busy_end: busy_end = ge
print(f"standing: {nfr} frames; created-after gaps of 100 us or more: {n / nfr:.1f} per frame, {total / nfr / 1e3:.2f} ms per frame")
print("\ngap time by the last flush before the GPU went idle (ms/frame, gaps/frame):")
for k, v in by_flush.most_common(12): print(f"  {v / nfr / 1e3:5.2f}  {cnt_flush[k] / nfr:5.2f}  {k}")
print("\ngap time by the traced wait that overlaps the gap most (ms/frame):")
for k, v in by_wait.most_common(12): print(f"  {v / nfr / 1e3:5.2f}  {k}")
print("\nall traced waits in the phase, whether or not the GPU was idle (ms/frame):")
for k, v in allwait.most_common(12): print(f"  {v / nfr / 1e3:5.2f}  {k}")
print("\nflushes per frame by site:")
fc = Counter(w for ts, w in flushes if w0 <= ts <= w1)
for k, v in fc.most_common(14): print(f"  {v / nfr:6.1f}  {k}")
