#!/usr/bin/env python3
"""stutterjit.py RUN_DIR...: where the JIT's code cache was fully flushed and what the slow frames cost, per harness
phase, from a run's stutter trace (EDEN_NX2_STUTTER_TRACE=1) and result.json's marks (frame numbers)."""
import json
import re
import sys
from pathlib import Path

LINE = re.compile(r"\[\s*([\d.]+)\].*Nx2Stutter frame=(\d+) ms=([\d.]+).*?jit=ms:([\d.]+),blocks:(\d+),clears:(\d+),full:(\d+)")
FLUSH = re.compile(r"\[\s*([\d.]+)\].*RequestJitFlush: .*\((.*)\)")


def main():
    for arg in sys.argv[1:]:
        rd = Path(arg)
        res = json.loads((rd / "result.json").read_text())
        marks = res.get("marks", {})
        phase_of = lambda f: next((n for n, start in sorted(marks.items(), key=lambda kv: -kv[1]) if f >= start),
                                  "before stand1")
        log = (rd / "eden_log.txt").read_text(errors="replace")
        rows = [(float(m[1]), int(m[2]), float(m[3]), float(m[4]), int(m[5]), int(m[6]), int(m[7]))
                for m in LINE.finditer(log)]
        print(f"== {rd.name}  marks {marks}")
        for m in FLUSH.finditer(log):
            print(f"  requested flush at {float(m[1]):.1f} s ({m[2]})")
        for t, f, ms, jms, blocks, clears, full in rows:
            if full:
                print(f"  FULL FLUSH at {t:.1f} s, frame {f} ({phase_of(f)}): frame {ms:.0f} ms, JIT {jms:.0f} ms, "
                      f"{blocks:,} blocks")
        by = {}
        for t, f, ms, jms, blocks, clears, full in rows:
            p = phase_of(f)
            n, worst, jit = by.get(p, (0, 0.0, 0.0))
            by[p] = (n + 1, max(worst, ms), jit + jms)
        for p in ("stand1", "walk", "stand2", "end"):
            if p in by:
                n, worst, jit = by[p]
                print(f"  {p:7s} traced slow frames {n:3d}, worst {worst:6.1f} ms, JIT in them {jit:7.1f} ms")


if __name__ == "__main__":
    main()
