#!/usr/bin/env python3
"""sigdiff.py LABEL A0 A1 B0 B1 [LABEL2]: encoder signatures (MoltenVK profile S records) per frame in two standing
frame ranges (of one run, or range A of LABEL and range B of LABEL2): count and GPU ms per frame, largest changes first."""
import re, struct, sys, bisect
from collections import defaultdict
from pathlib import Path
import os, subprocess
REPO = subprocess.check_output(["git", "rev-parse", "--show-toplevel"],
                               cwd=os.path.dirname(os.path.abspath(__file__)), text=True).strip()
MV = Path(REPO + "/build/old-trees")
def load(lab, r0, r1):
    run = MV / "sc-update/runs" / lab
    mk = {m.group(1): int(m.group(2)) for m in re.finditer(r"mark (\S+) frame (\d+)", (MV / "sc-update/runs" / (lab + ".out")).read_text())}
    b = (run / "frames.bin").read_bytes(); t = [x / 1e3 for x in struct.unpack(f"<{len(b)//8}Q", b)]
    a = mk["loaded-standing"]; w0, w1 = t[a + r0], t[a + r1]
    acc = defaultdict(lambda: [0, 0.0]); inside = False; ncb = 0
    for line in open(MV / "path-60/runs" / (lab + ".prof"), errors="replace"):
        f = line.split()
        if not f: continue
        if f[0] == "C" and len(f) > 8:
            inside = w0 <= float(f[3]) < w1; ncb += inside
        elif f[0] == "S" and inside:
            acc[f[1]][0] += int(f[2]); acc[f[1]][1] += int(f[3]) / 1e6
    n = r1 - r0
    return {k: (v[0] / n, v[1] / n) for k, v in acc.items()}, ncb / n
lab = sys.argv[1]; A = load(lab, int(sys.argv[2]), int(sys.argv[3])); B = load(sys.argv[6] if len(sys.argv) > 6 else lab, int(sys.argv[4]), int(sys.argv[5]))
print(f"command buffers/frame {A[1]:.1f} vs {B[1]:.1f}; encoders/frame {sum(v[0] for v in A[0].values()):.0f} vs {sum(v[0] for v in B[0].values()):.0f}; encoder GPU ms/frame {sum(v[1] for v in A[0].values()):.2f} vs {sum(v[1] for v in B[0].values()):.2f}")
keys = sorted(set(A[0]) | set(B[0]), key=lambda k: -abs(B[0].get(k, (0, 0))[1] - A[0].get(k, (0, 0))[1]))
for k in keys[:int(sys.argv[7]) if len(sys.argv) > 7 else 16]:
    x, y = A[0].get(k, (0, 0)), B[0].get(k, (0, 0))
    print(f"  {x[0]:7.2f} {x[1]:7.3f} ms -> {y[0]:7.2f} {y[1]:7.3f} ms  ({y[1]-x[1]:+.3f})  {k}")
