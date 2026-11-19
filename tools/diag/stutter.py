#!/usr/bin/env python3
"""stutter.py [VIEW] RUN…: Lichii's stutter trace (EDEN_NX2_STUTTER_TRACE=1) in harness runs, by harness phase.
Standard library only. RUN is a run folder (runs/ab-…/LABEL) or a batch folder (runs/ab-…).

The trace writes an Nx2Stutter line for every frame presented more than 33 ms after the one before (constexpr
StutterMs in video_core/nx2_stutter_trace.cpp), or for every frame with EDEN_NX2_STUTTER_ALL_FRAMES=1; an
Nx2StutterDetail line for frames over EDEN_NX2_STUTTER_DETAIL_MS; an Nx2StutterSummary every 10 s; Nx2Boot at boot
steps; and, with the trace or EDEN_NX2_GUEST_THREAD_STATS, each core's running "JIT totals" at most every 2 s. Its
frame= counts the trace's own presents, not the harness's, so lines are placed in phases by time (README.md,
"Clocks"). The summary's jit_cache_mib counts the shared code cache once per core, 6x too high (KNOWN-ISSUES KI-6).

Views:
  slow (default)  per phase: slow frames, their worst, JIT ms in them, pipeline builds, the GPU-side categories;
                  requested and full JIT code cache flushes; each slow frame (>= --slow-ms, default 33) classified:
                  "JIT compile" when its jit ms >= 5, else "pipeline build" when it built one, else what is most
                  above the phase's ordinary frame by 2 ms or more: a category (texture, buffer, query_fence, …), a
                  GPU thread's busy time or the trace's "other" (with ALL_FRAMES, against the phase's median frame;
                  without it only the categories, against the 10 s summaries' per-frame cost), else "unattributed"
  segments        a phase (--phase, default walk) in --segment frames at a time (default 300): frame times from
                  frames.bin with the trace lines that fall in each segment, then the 10 s summaries over the run
  split           where an ordinary frame's time goes (needs ALL_FRAMES): repeats pooled by label without -rN, the
                  phase's frames sorted by length and averaged over the median (45-55th percentile), p90 (87.5-92.5th)
                  and p99 (top 2 %) bands: CPU core time inside the JIT's Run summed over the six cores (so it can
                  exceed the frame) with its JIT work (compile, code cache lock wait, fastmem fault handling) and the
                  rest (guest code and callbacks), blocks and faults, GPU thread busy, the trace's categories
  totals          the last "JIT totals" line of each core summed, at the end of the load and at the end of the run:
                  blocks, compile ms, lookups, lock waits by kind, discarded translations, faults, clears, veneers
  flushes         requested JIT flushes (RequestJitFlush) and full code cache flushes, with the phase they fell in
  all             slow, flushes, segments and totals

Options: --phase, --segment, --slow-ms, --bands, --log-clock, --with-warmup (keep warm-up runs of a batch folder).
"""
import argparse
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rundir  # noqa: E402

VIEWS = ("slow", "segments", "split", "totals", "flushes", "all")
LINE = re.compile(r"\[\s*([\d.]+)\].*Nx2Stutter frame=(\d+) ms=([\d.]+) cause=(\S+) (.*)")
SUMMARY = re.compile(r"\[\s*([\d.]+)\].*Nx2StutterSummary window_s=([\d.]+) frames=(\d+) over33=(\d+).*?"
                     r"cat_ms=(\S+).*?jit=ms:([\d.]+),blocks:(\d+),.*?fastmem:(\d+),run:([\d.]+),lock:([\d.]+),"
                     r"fault:([\d.]+)")
FLUSH = re.compile(r"\[\s*([\d.]+)\].*JIT code cache flush requested \((.*?)\)")
TOTALS = re.compile(r"\[\s*([\d.]+)\].*JIT totals core=(\d+) (.*)")
CATS = ("gfx_miss", "compute_miss", "pipeline_wait", "shader_capture", "texture", "buffer", "query_fence", "present")
GPU_PARTS = CATS + ("other",)
TOTAL_KEYS = ["blocks", "compile_ms", "lookups", "lookup_hits", "lookup_wait_ms", "emit_wait_ms", "emit_hold_ms",
              "discarded", "discarded_ms", "with_company", "inval_requests", "inval_blocks", "fastmem_recompiles",
              "fastmem_stale", "fastmem_faults", "fault_handler_ms", "fault_wait_ms", "clears", "veneers"]
JIT_COMPILE_MS = 5.0
ELEVATED_MS = 2.0


def stutter_lines(run):
    """Every Nx2Stutter line: dict(t, frame, ms, cause, cats{}, other, busy{}, builds, jit{})."""
    out = []
    for m in LINE.finditer(run.log_text()):
        f = {"t": float(m[1]), "frame": int(m[2]), "ms": float(m[3]), "cause": m[4], "cats": {}, "busy": {},
             "builds": 0, "jit": {}, "other": 0.0, "raw": m[5]}
        for tok in m[5].split():
            k, _, v = tok.partition("=")
            if k in CATS:
                f["cats"][k] = float(v)
            elif k == "other":
                f["other"] = float(v)
            elif k == "busy" and v != "none":
                f["busy"] = {a: float(b) for a, b in (p.split(":") for p in v.split(",") if ":" in p)}
            elif k == "builds":
                f["builds"] = sum(int(b) for _, b in (p.split(":") for p in v.split(",") if ":" in p))
            elif k == "jit":
                f["jit"] = {a: float(b) for a, b in (p.split(":") for p in v.split(",") if ":" in p)}
        out.append(f)
    return out


def all_frames(run):
    return "EDEN_NX2_STUTTER_ALL_FRAMES" in run.env


def full_flushes(run, lines):
    return [f for f in lines if f["jit"].get("full", 0)]


def classify(f, base):
    """The kind of a slow frame (see the module docstring). base holds the phase's ordinary frame: medians of every
    category, thread and "other" with ALL_FRAMES, else the 10 s summaries' per-frame categories only (thread busy
    and "other" are then not judged: they are large in every frame)."""
    if f["jit"].get("ms", 0) >= JIT_COMPILE_MS:
        return "JIT compile"
    if f["builds"]:
        return "pipeline build"
    excess = {k: f["cats"].get(k, 0) - base.get(k, 0) for k in CATS}
    if "other" in base:
        excess.update({"GPU " + k + " thread busy": v - base.get("busy:" + k, 0) for k, v in f["busy"].items()})
        excess["other GPU-thread time"] = f["other"] - base["other"]
    k, v = max(excess.items(), key=lambda kv: kv[1])
    return k if v >= ELEVATED_MS else "unattributed"


def baseline(frames):
    """Median of each category, thread and "other" over the phase's lines (with ALL_FRAMES: every frame)."""
    keys = set(CATS) | {"other"} | {"busy:" + k for f in frames for k in f["busy"]}
    val = lambda f, k: f["busy"].get(k[5:], 0) if k.startswith("busy:") else (f["other"] if k == "other" else
                                                                               f["cats"].get(k, 0))
    return {k: statistics.median(val(f, k) for f in frames) for k in keys} if frames else {}


def summary_baseline(run, phase):
    """Per-frame category ms of the 10 s summaries that end inside the phase (their cat_ms is every frame's cost)."""
    w = run.phase_log_window(phase)
    tot, n = Counter(), 0
    for m in SUMMARY.finditer(run.log_text()):
        if w and w[0] < float(m[1]) <= w[1] + 10:
            for kv in m[5].split(","):
                k, v = kv.split(":")
                tot[k] += float(v)
            n += int(m[3])
    return {k: v / n for k, v in tot.items()} if n else {}


def by_phase(run, lines):
    out = defaultdict(list)
    for f in lines:
        p = run.phase_of_log_time(f["t"])
        if p:
            out[p].append(f)
    return out


def view_slow(runs, slow_ms):
    for r in runs:
        print(rundir.header(r))
        lines = stutter_lines(r)
        if not lines:
            print("  no Nx2Stutter lines: the stutter trace was off (EDEN_NX2_STUTTER_TRACE=1)")
            continue
        if not r.t_monotonic:
            print("  no t_monotonic in result.json: lines cannot be placed in phases")
            continue
        ph = by_phase(r, lines)
        for p in r.phase_names():
            fs = ph.get(p, [])
            parts = Counter()
            for f in fs:
                for k in GPU_PARTS:
                    parts[k] += f["cats"].get(k, 0) if k != "other" else f["other"]
            parts_s = ", ".join(f"{k} {v:.0f}" for k, v in parts.most_common() if v >= 1)
            worst = max((f["ms"] for f in fs), default=0.0)
            jit = sum(f["jit"].get("ms", 0) for f in fs)
            builds = sum(f["builds"] for f in fs)
            full = sum(1 for f in fs if f["jit"].get("full", 0))
            print(f"  {p:6s} slow frames {len(fs):3d} (worst {worst:.0f} ms)  JIT {jit:.0f} ms  pipeline builds "
                  f"{builds}  GPU-side ms: {parts_s or '-'}" + (f"  JIT FULL FLUSHES {full}" if full else ""))
        if all_frames(r):
            print(f"  (EDEN_NX2_STUTTER_ALL_FRAMES: every frame has a line, so 'slow frames' counts every frame)")
        for p in r.phase_names():
            fs = ph.get(p, [])
            base = baseline(fs) if all_frames(r) else summary_baseline(r, p)
            slow = [f for f in fs if f["ms"] >= slow_ms]
            if not slow:
                continue
            kinds = defaultdict(list)
            for f in slow:
                kinds[classify(f, base)].append(f["ms"])
            cells = ", ".join(f"{k} {len(v)} ({sum(v):.0f} ms)" for k, v in
                              sorted(kinds.items(), key=lambda kv: -len(kv[1])))
            how = "against the phase's median frame" if all_frames(r) else "against the 10 s summaries' categories"
            print(f"  {p:6s} frames >= {slow_ms:g} ms by kind ({how}): {cells}")


def view_flushes(runs):
    for r in runs:
        print(rundir.header(r, "  JIT code cache flushes"))
        log = r.log_text()
        n = 0
        for m in FLUSH.finditer(log):
            t = float(m[1])
            print(f"  requested flush at {t:.1f} s ({m[2]}), {r.phase_of_log_time(t) or 'outside the phases'}")
            n += 1
        for f in full_flushes(r, stutter_lines(r)):
            print(f"  FULL FLUSH at {f['t']:.1f} s ({r.phase_of_log_time(f['t']) or 'outside the phases'}): frame "
                  f"{f['ms']:.0f} ms, JIT {f['jit'].get('ms', 0):.0f} ms, {int(f['jit'].get('blocks', 0)):,} blocks")
            n += 1
        if not n:
            print("  none")


def view_segments(runs, phase, size):
    for r in runs:
        res = r.res
        wc = r.walk_call
        print(rundir.header(r, f"  loadavg {[round(x, 1) for x in res.get('loadavg_before', [])]}  moved "
                               f"{res.get(r.prefix + 'walk_moved_m')} m  turns at {wc.get('turns_at_frame')}  "
                               f"picture {res.get('picture')}"))
        if phase not in r.phase_names():
            print(f"  no phase {phase}")
            continue
        d = r.phase_ms(phase)
        ts = [t / 1e9 for t in r.phase_present_ns(phase)[1:]]          # each frame's present, uptime s
        s = sorted(d)
        q = lambda x, f: rundir.quantile(x, f)
        print(f"  {phase} all: n={len(d)} p50 {q(s, .5):.1f} p90 {q(s, .9):.1f} p95 {q(s, .95):.1f} "
              f"p99 {q(s, .99):.1f} max {s[-1]:.1f}")
        st = [(r.log_to_uptime(f["t"]), f["ms"], f["jit"].get("ms", 0)) for f in stutter_lines(r)]
        st = [x for x in st if x[0] is not None]
        for i in range(0, len(d), size):
            seg, tt = d[i:i + size], ts[i:i + size]
            if len(seg) < size // 3:
                continue
            ss = [(ms, j) for (x, ms, j) in st if tt[0] - seg[0] / 1e3 <= x <= tt[-1]]
            sseg = sorted(seg)
            print(f"  frames {i:4d}-{i + len(seg):4d}: p50 {q(sseg, .5):5.1f} p95 {q(sseg, .95):5.1f} "
                  f"max {sseg[-1]:5.1f}  >=22: {sum(x >= 22 for x in seg):3d}  >=26: {sum(x >= 26 for x in seg):3d}  "
                  f">=33: {sum(x >= 33 for x in seg):2d}  traced {len(ss)} (JIT in them {sum(j for _, j in ss):.0f} "
                  f"of {sum(ms for ms, _ in ss):.0f} ms)")
        for p in r.phase_names():
            if p != phase:
                x = sorted(r.phase_ms(p))
                print(f"  {p:8s}: n={len(x)} p50 {q(x, .5):.1f} p95 {q(x, .95):.1f} max {x[-1]:.1f}")
        steps = [(r.step_log_time(k), k) for k in ("settled", "walk", "stand2", "end") if r.step_log_time(k) is not None]
        steps.sort()
        t_ph = r.step_log_time(phase) or 0.0
        for m in SUMMARY.finditer(r.log_text()):
            end = float(m[1])
            start = end - float(m[2])
            if not steps or end < steps[0][0] or start > steps[-1][0]:
                continue
            where = "/".join(n for (x, n), (y, _) in zip(steps, steps[1:]) if x < end and y > start)
            cat = dict(kv.split(":") for kv in m[5].split(","))
            n = int(m[3])
            print(f"  10s window ending {phase}{end - t_ph:+7.1f}s [{where:14s}] frames {n:4d} over33 {m[4]:>3s}  "
                  f"per frame: JIT {float(m[6]) / n:5.2f} ms (blocks {int(m[7]) / n:6.1f}, fastmem {int(m[8]) / n:5.1f}, "
                  f"lock {float(m[10]) / n:4.2f}, fault {float(m[11]) / n:4.2f})  buffer {float(cat['buffer']) / n:4.2f}"
                  f"  texture {float(cat['texture']) / n:4.2f}  query_fence {float(cat['query_fence']) / n:4.2f}")


SPLIT = re.compile(r"\[\s*([\d.]+)\].*Nx2Stutter frame=\d+ ms=([\d.]+) cause=(\S+)(.*) other=([\d.]+) busy=(\S+) "
                   r"builds=\S+ jit=(\S+)")


def view_split(runs, phase):
    pooled = {}
    for r in runs:
        w = r.phase_log_window(phase)
        if not w:
            continue
        if not all_frames(r):
            print(f"({r.label}: left out, no EDEN_NX2_STUTTER_ALL_FRAMES: only slow frames have lines)")
            continue
        lo, hi = w
        frames = []
        for m in SPLIT.finditer(r.log_text()):
            if not (lo <= float(m[1]) <= hi):
                continue
            f = {"ms": float(m[2])}
            for k, v in re.findall(r" (\w+)=([\d.]+)", m[4]):
                f["gpu:" + k] = float(v)
            f["gpu:other"] = float(m[5])
            for part in m[6].split(","):
                if ":" in part:
                    k, v = part.split(":")
                    f["busy:" + k] = float(v)
            j = dict(kv.split(":") for kv in m[7].split(","))
            f["jit:compile"] = float(j.get("ms", 0)); f["jit:lock"] = float(j.get("lock", 0))
            f["jit:fault"] = float(j.get("fault", 0)); f["cpu:run"] = float(j.get("run", 0))
            f["n:blocks"] = float(j.get("blocks", 0)); f["n:faults"] = float(j.get("faults", 0))
            frames.append(f)
        pooled.setdefault(r.base, []).extend(frames)
    bands = (("median", 0.45, 0.55), ("p90", 0.875, 0.925), ("p99", 0.98, 1.0))
    for label, frames in pooled.items():
        frames.sort(key=lambda f: f["ms"])
        n = len(frames)
        if not n:
            continue
        print(f"\n== {label}: {n} {phase} frames")
        keys = sorted({k for f in frames for k in f} - {"ms"})
        rows = []
        for name, a, b in bands:
            band = frames[int(a * n):max(int(a * n) + 1, int(b * n))]
            avg = lambda k: sum(f.get(k, 0) for f in band) / len(band)
            rows.append((name, len(band), avg("ms"), {k: avg(k) for k in keys}))
        print("%-34s" % "frame band" + "".join("%12s" % f"{name} ({cnt})" for name, cnt, _, _ in rows))
        print("%-34s" % "frame length, ms" + "".join("%12.2f" % ms for _, _, ms, _ in rows))

        def line(title, fn, fmt="%12.2f"):
            print("%-34s" % title + "".join(fmt % fn(v) for _, _, _, v in rows))
        jit = lambda v: v["jit:compile"] + v["jit:lock"] + v["jit:fault"]
        line("CPU cores inside the JIT run, ms", lambda v: v["cpu:run"])
        line("  JIT work: compile", lambda v: v["jit:compile"])
        line("  JIT work: waiting for cache lock", lambda v: v["jit:lock"])
        line("  JIT work: fastmem fault handling", lambda v: v["jit:fault"])
        line("  guest code and callbacks", lambda v: v["cpu:run"] - jit(v))
        line("  JIT work as % of core time", lambda v: 100 * jit(v) / v["cpu:run"] if v["cpu:run"] else 0, "%11.1f%%")
        line("blocks compiled per frame", lambda v: v["n:blocks"], "%12.1f")
        line("fastmem faults per frame", lambda v: v["n:faults"], "%12.1f")
        for k in keys:
            if k.startswith("busy:"):
                line("GPU thread busy: " + k[5:] + ", ms", lambda v, k=k: v[k])
        for k in keys:
            if k.startswith("gpu:") and any(v[k] >= 0.05 for _, _, _, v in rows):
                line("trace category: " + k[4:] + ", ms", lambda v, k=k: v[k])


def totals_until(run, until):
    last = {}
    for m in TOTALS.finditer(run.log_text()):
        if float(m[1]) > until:
            continue
        last[int(m[2])] = dict((k, float(v)) for k, v in (kv.split("=") for kv in m[3].split()))
    return {k: sum(c.get(k, 0) for c in last.values()) for k in TOTAL_KEYS}, len(last)


def view_totals(runs):
    for r in runs:
        end_load = r.step_log_time("load_done")
        if end_load is None:
            end_load = (r.res.get("load_s") or 0)
        for name, until in (("end of load", end_load + 1), ("end of run", 1e9)):
            t, cores = totals_until(r, until)
            if not cores:
                continue
            print(f"{r.label:18s} {name:11s} load {r.res.get('load_s')} s, {cores} cores: " +
                  " ".join(f"{k}={t[k]:.0f}" for k in TOTAL_KEYS))


def main():
    view, rest = rundir.view_and_rest(sys.argv[1:], VIEWS, "slow")
    ap = rundir.add_common(argparse.ArgumentParser(description=__doc__.split("\n")[0]), phase_default="walk")
    ap.add_argument("--segment", type=int, default=300, help="segment length in frames (default %(default)s)")
    ap.add_argument("--slow-ms", type=float, default=33.0, help="slow frame threshold for the classification")
    a = ap.parse_args(rest)
    runs = rundir.runs_from(a)
    if view in ("slow", "all"):
        view_slow(runs, a.slow_ms)
    if view in ("flushes", "all"):
        view_flushes(runs)
    if view in ("segments", "all"):
        view_segments(runs, a.phase, a.segment)
    if view == "split":
        view_split(runs, a.phase)
    if view in ("totals", "all"):
        view_totals(runs)


if __name__ == "__main__":
    main()
