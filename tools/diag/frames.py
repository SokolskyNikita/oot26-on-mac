#!/usr/bin/env python3
"""frames.py [VIEW] RUN…: frame times of harness runs from frames.bin (the verify hook's clock: one CLOCK_UPTIME_RAW
timestamp per presented frame) and result.json's marks, plus Lichii's always-on 600-present lines. Standard library
only. RUN is a run folder (runs/ab-…/LABEL) or a batch folder (runs/ab-…).

Views (default: all of them, in this order):
  pct        p50 / p90 / p95 / p99 / max per phase, one line per run and phase
  bands      frames per frame-time band (--bands, default <20, 20-22, 22-26, 26-33, >=33 ms) per phase
  segments   the phase in --segment frames at a time (default 300): p50 / p95 / max and frames per band
  vi2        Lichii's "nx2:vi2 last 600 presents" lines, each with the phase it ended in (log time placed on the
             harness clock as in README.md, "Clocks")

Options: --phase P (segments: walk by default; "all" for every phase), --segment N, --bands, --log-clock,
--with-warmup.
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rundir  # noqa: E402

VIEWS = ("pct", "bands", "segments", "vi2", "all")
VI2 = re.compile(r"\[\s*([\d.]+)\].*nx2:vi2 last 600 presents: frame (\d+) us \(max (\d+), (\d+) over 100 ms\), "
                 r"blocked on the GPU fence (\d+) us \(max (\d+)\), composite (\d+) us, vblank pacing (\d+) us, "
                 r"(\d+) ran a frame ahead, (\d+) vblanks asked \((\d+)% of real time")


def view_pct(runs):
    print(f"{'run':28s} {'phase':7s} {'p50':>6s} {'p90':>6s} {'p95':>6s} {'p99':>6s} {'max':>7s}")
    for r in runs:
        for p in r.phase_names():
            d = r.phase_ms(p)
            if not d:
                continue
            s = sorted(d)
            q = lambda f: rundir.quantile(s, f)
            print(f"{r.label[:28]:28s} {p:7s} {q(.5):6.1f} {q(.9):6.1f} {q(.95):6.1f} {q(.99):6.1f} {s[-1]:7.1f}")


def band_cells(d, edges):
    n = len(d) or 1
    cells = []
    for lo, hi in rundir.band_ranges(edges):
        c = sum(lo <= x < hi for x in d)
        cells.append(f"{rundir.band_name(lo, hi):>6s} {c:5d} ({100 * c / n:4.1f}%)")
    return "  ".join(cells)


def view_bands(runs, edges):
    for r in runs:
        print(rundir.header(r, "  frames per band (ms)"))
        for p in r.phase_names():
            d = r.phase_ms(p)
            if d:
                print(f"  {p:7s} n={len(d):5d}  {band_cells(d, edges)}")


def view_segments(runs, edges, phase, size):
    for r in runs:
        print(rundir.header(r, f"  {size}-frame segments"))
        for p in (r.phase_names() if phase == "all" else [phase]):
            if p not in r.phase_names():
                print(f"  no phase {p}")
                continue
            d = r.phase_ms(p)
            for i in range(0, len(d), size):
                seg = sorted(d[i:i + size])
                over = "  ".join(f">={lo:g}: {sum(x >= lo for x in seg):3d}" for lo, _ in rundir.band_ranges(edges)[1:])
                print(f"  {p:7s} frames {i:5d}-{i + len(seg):5d}: p50 {rundir.quantile(seg, .5):5.1f} "
                      f"p95 {rundir.quantile(seg, .95):5.1f} max {seg[-1]:6.1f}  {over}")


def view_vi2(runs):
    for r in runs:
        print(rundir.header(r, "  nx2:vi2 last 600 presents (Lichii's own counter, always on)"))
        print(f"    {'log s':>8s} {'phase':12s} {'frame ms':>8s} {'max ms':>7s} {'>100ms':>6s} {'fence us':>8s} "
              f"{'ahead':>5s} {'speed%':>6s}")
        rows = 0
        for m in VI2.finditer(r.log_text()):
            t = float(m[1])
            ph = r.phase_of_log_time(t) or _step_before(r, t)
            print(f"    {t:8.1f} {ph:12s} {int(m[2]) / 1000:8.2f} {int(m[3]) / 1000:7.1f} {int(m[4]):6d} "
                  f"{int(m[5]):8d} {int(m[9]):5d} {int(m[11]):6d}")
            rows += 1
        if not rows:
            print("    none in the log")


def _step_before(r, t):
    """The last harness step before a log time, for lines outside the measured phases."""
    best = "before boot"
    for step in ("start", "boot_done", "loading", "in_game", "load_done", "settled", "end"):
        lt = r.step_log_time(step)
        if lt is not None and lt <= t:
            best = "after " + step
    return best


def main():
    view, rest = rundir.view_and_rest(sys.argv[1:], VIEWS, "all")
    ap = rundir.add_common(argparse.ArgumentParser(description=__doc__.split("\n")[0]), phase_default="walk")
    ap.add_argument("--segment", type=int, default=300, help="segment length in frames (default %(default)s)")
    a = ap.parse_args(rest)
    runs = rundir.runs_from(a)
    edges = rundir.parse_bands(a.bands)
    if view in ("pct", "all"):
        view_pct(runs)
    if view in ("bands", "all"):
        view_bands(runs, edges)
    if view in ("segments", "all"):
        view_segments(runs, edges, a.phase, a.segment)
    if view in ("vi2", "all"):
        view_vi2(runs)


if __name__ == "__main__":
    main()
