#!/usr/bin/env python3
"""stuttercause.py RUN_DIR...: the stutter trace's slow frames per harness phase, assigned by time (the trace's
"frame=" counts game frames, not the presents result.json's marks count). Needs result.json's t_monotonic (runs from
2026-11-17 evening on): eden_log time is mapped to CLOCK_MONOTONIC_RAW through the Nx2Boot line's mono_s."""
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path


def main():
    for arg in sys.argv[1:]:
        rd = Path(arg)
        res = json.loads((rd / "result.json").read_text())
        tm = res.get("t_monotonic")
        log = (rd / "eden_log.txt").read_text(errors="replace")
        boot = re.search(r"\[\s*([\d.]+)\].*Nx2Boot event=\w+ mono_s=([\d.]+)", log)
        if not tm or not boot:
            print(f"== {rd.name}: no t_monotonic or no Nx2Boot line"); continue
        off = float(boot[2]) - float(boot[1])                     # monotonic s = log s + off
        edges = sorted((v / 1e9, k) for k, v in tm.items() if k in ("stand1", "walk", "stand2", "end"))
        phase = lambda t: next((n for (a, n), (b, _) in zip(edges, edges[1:]) if a <= t < b), None)
        acc = defaultdict(lambda: {"n": 0, "ms": 0.0, "jit": 0.0, "builds": 0, "worst": 0.0, "parts": Counter()})
        for L in re.finditer(r"\[\s*([\d.]+)\].*Nx2Stutter frame=\d+ ms=([\d.]+) cause=(\S+) (.*)", log):
            p = phase(float(L[1]) + off)
            if not p:
                continue
            a = acc[p]; a["n"] += 1; a["ms"] += float(L[2]); a["worst"] = max(a["worst"], float(L[2]))
            for k, v in re.findall(r"(gfx_miss|compute_miss|pipeline_wait|shader_capture|texture|buffer|query_fence|present|other)=([\d.]+)", L[4]):
                a["parts"][k] += float(v)
            j = re.search(r"jit=ms:([\d.]+)", L[4]); a["jit"] += float(j[1]) if j else 0
            b = re.search(r"builds=gfx:(\d+),compute:(\d+)", L[4]); a["builds"] += int(b[1]) + int(b[2]) if b else 0
        print(f"== {rd.name}")
        for p in ("stand1", "walk", "stand2"):
            a = acc[p]
            parts = ", ".join(f"{k} {v:.0f}" for k, v in a["parts"].most_common() if v >= 1)
            print(f"  {p:6s} slow frames {a['n']:3d} (worst {a['worst']:.0f} ms)  JIT {a['jit']:.0f} ms  pipeline builds "
                  f"{a['builds']}  GPU-side ms: {parts or '-'}")


if __name__ == "__main__":
    main()
