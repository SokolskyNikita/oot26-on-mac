#!/usr/bin/env python3
"""cmp.py LABEL...: one row per run from its frame times (sc-update/runs/LABEL) and MoltenVK profile
(path-60/runs/LABEL.prof): standing median and thirds, GPU busy/idle, command buffers, encoders, and the GPU time and
count of the passes this investigation changes."""
import re, struct, subprocess, sys, statistics as S
from pathlib import Path
import os, subprocess
REPO = subprocess.check_output(["git", "rev-parse", "--show-toplevel"],
                               cwd=os.path.dirname(os.path.abspath(__file__)), text=True).strip()
# Folder with the frame-profile runs to read (runs/LABEL.prof and the frame-time runs beside them)
MV = Path(os.environ.get("OOT26_PERF_DIR", REPO + "/build/perf"))
print(f"{'run':14} {'median':>6} {'thirds':>17} {'busy':>5} {'idle':>5} {'CBs':>5} {'enc':>6} | {'net ms':>6} {'copyB n/ms':>11} {'u8 n/ms':>9} {'occl n/ms':>10} {'rpass n/ms':>11} {'gameC n/ms':>11} {'load'}")
for lab in sys.argv[1:]:
    run = MV / "sc-update/runs" / lab
    out = (MV / "sc-update/runs" / (lab + ".out")).read_text()
    mk = {m.group(1): int(m.group(2)) for m in re.finditer(r"mark (\S+) frame (\d+)", out)}
    b = (run / "frames.bin").read_bytes(); t = struct.unpack(f"<{len(b)//8}Q", b)
    if "loaded-standing" not in mk: print(lab, "did not reach standing"); continue
    a, z = mk["loaded-standing"], min(mk.get("walk1", len(t) - 1), len(t) - 1)
    d = [(t[i + 1] - t[i]) / 1e6 for i in range(a, z)]; n = len(d) // 3
    th = "/".join(f"{S.median(d[i*n:(i+1)*n]):.1f}" for i in range(3))
    row = f"{lab:14} {S.median(d):6.1f} {th:>17}"
    prof = MV / "path-60/runs" / (lab + ".prof")
    if prof.exists():
        r = subprocess.run([sys.executable, str(MV / "aio-profile/prof_report.py"), str(prof), str(run), "--top", "500"], capture_output=True, text=True).stdout
        g = lambda p: (re.search(p, r) or [None, "nan"])[1]
        busy = g(r"GPU busy ([\d.]+) ms, GPU idle"); idle = g(r"GPU idle ([\d.]+) ms; frames"); cbs = g(r"\(([\d.]+)/frame\), encoders"); enc = g(r"encoders ([\d.]+)/frame")
        net = cb = u8 = oc = rp = gc = (0.0, 0.0)
        acc = {"net": [0, 0], "cb": [0, 0], "u8": [0, 0], "oc": [0, 0], "rp": [0, 0], "gc": [0, 0]}
        for ln in r.split("\n"):
            f = ln.split()
            if len(f) < 3: continue
            sig = f[0]
            try:
                if sig.startswith("R"):  # "R use9 1440x810 c1 RG11B10F d=D32F load   33.65  4.777 ..."
                    nums = [x for x in f if re.fullmatch(r"[\d.]+", x)]; k = "rp"; nn, sp = float(nums[-5]), float(nums[-4])
                else:
                    nn, sp = float(f[1]), float(f[2])
                    k = "net" if "11e78e3deaec1d65" in sig else "cb" if sig == "B:20" else "u8" if sig.startswith("C:34") else "oc" if sig.startswith("C:33") else "gc" if sig.startswith("C:29") else None
            except (ValueError, IndexError): continue
            if k: acc[k][0] += nn; acc[k][1] += sp

        fm = lambda k: f"{acc[k][0]:.0f}/{acc[k][1]:.2f}"
        row += f" {busy:>5} {idle:>5} {cbs:>5} {enc:>6} | {acc['net'][1]:6.2f} {fm('cb'):>11} {fm('u8'):>9} {fm('oc'):>10} {fm('rp'):>11} {fm('gc'):>11}"
    ld = re.search(lab + r" load: \{ ([\d.]+)", (MV / "path-60/runs").joinpath("all.log").read_text() if (MV / "path-60/runs/all.log").exists() else "")
    print(row + (f" {ld.group(1)}" if ld else ""))
