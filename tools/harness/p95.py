#!/usr/bin/env python3
"""p95.py RUN_DIR...: per phase median / p90 / p95 / p99 / max frame time (ms) from frames.bin and result.json's marks,
for runs made before the harness recorded p95."""
import json
import sys
from pathlib import Path

import numpy as np


def main():
    print(f"{'run':28s} {'phase':7s} {'p50':>6s} {'p90':>6s} {'p95':>6s} {'p99':>6s} {'max':>7s}")
    for arg in sys.argv[1:]:
        rd = Path(arg)
        if not (rd / "result.json").exists():
            continue
        res = json.loads((rd / "result.json").read_text())
        fr = np.fromfile(rd / "frames.bin", dtype="<u8")
        m = res.get("marks", {})
        names = [n for n in ("stand1", "walk", "stand2", "end") if n in m]
        for a, b in zip(names, names[1:]):
            d = np.diff(fr[m[a]:m[b] + 1]) / 1e6
            if len(d) == 0:
                continue
            s = np.sort(d)
            q = lambda f: s[min(len(s) - 1, int(f * len(s)))]
            print(f"{rd.name[:28]:28s} {a:7s} {q(.5):6.1f} {q(.9):6.1f} {q(.95):6.1f} {q(.99):6.1f} {s[-1]:7.1f}")


if __name__ == "__main__":
    main()
