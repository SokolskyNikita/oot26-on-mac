#!/usr/bin/env python3
"""perframe.py LABEL [N]: per presented frame in the standing phase: frame time, GPU busy, command buffers, encoders
(from the MoltenVK profile). Prints N consecutive frames and the correlation summary by frame-time bucket."""
import re, struct, sys, bisect, statistics as S
from pathlib import Path
import os, subprocess
REPO = subprocess.check_output(["git", "rev-parse", "--show-toplevel"],
                               cwd=os.path.dirname(os.path.abspath(__file__)), text=True).strip()
# Folder with the frame-profile runs to read (runs/LABEL.prof and the frame-time runs beside them)
MV = Path(os.environ.get("OOT26_PERF_DIR", REPO + "/build/perf"))
lab = sys.argv[1]; N = int(sys.argv[2]) if len(sys.argv) > 2 else 24
run = MV / "sc-update/runs" / lab
mk = {m.group(1): int(m.group(2)) for m in re.finditer(r"mark (\S+) frame (\d+)", (MV / "sc-update/runs" / (lab + ".out")).read_text())}
b = (run / "frames.bin").read_bytes(); t = [x / 1e3 for x in struct.unpack(f"<{len(b)//8}Q", b)]
a, z = mk["loaded-standing"], min(mk.get("walk1", len(t) - 1), len(t) - 1)
fr = t[a:z + 1]; rows = [[fr[i + 1] - fr[i], 0.0, 0, 0] for i in range(len(fr) - 1)]
for line in open(MV / "path-60/runs" / (lab + ".prof"), errors="replace"):
    f = line.split()
    if f and f[0] == "C" and len(f) > 8:
        gs, ge = float(f[2]), float(f[3]); i = bisect.bisect_right(fr, ge) - 1
        if 0 <= i < len(rows): rows[i][1] += ge - gs; rows[i][2] += 1; rows[i][3] += int(f[4])
print(" ".join(f"{r[0]/1e3:.0f}ms/{r[1]/1e3:.0f}busy/{r[2]}cb/{r[3]}enc" for r in rows[400:400 + N]))
for lo, hi in ((0, 24), (24, 34), (34, 50), (50, 70), (70, 1e9)):
    w = [r for r in rows if lo <= r[0] / 1e3 < hi]
    if w: print(f"frames {lo}-{hi if hi < 1e8 else 'inf'} ms: {len(w):4}  GPU work in them: median {S.median(r[1] for r in w)/1e3:5.1f} ms, CBs {S.median(r[2] for r in w):.0f}, encoders {S.median(r[3] for r in w):.0f}")
