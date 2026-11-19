#!/usr/bin/env python3
"""stats.py RUN…: Lichii's periodic statistics lines in harness runs (README.md, level 3a), by harness phase.
Standard library only. RUN is a run folder (runs/ab-…/LABEL) or a batch folder (runs/ab-…).

For each kind of line the run's log holds, one block: a row per figure, a column per phase (walking against
standing). A line counts in the phase its log time falls in, placed on the harness clock as in README.md "Clocks";
a line that sums a window (10 s, 1 s, 600 presents) is placed by the time it was written, at the window's end.
Kinds a log does not hold are left out. Kinds read:

  Back idle in 10 s (EDEN_NX2_BACK_IDLE_TRACE)        Front waits for the back by site, Acquires (EDEN_NX2_ACQUIRE_STATS)
  present fences, last 600 presents (EDEN_NX2_PRESENT_FENCE_TRACE)   Guest threads, Guest core N (GUEST_THREAD_STATS)
  HostTiming wait (EDEN_NX2_HOSTTIMING_STATS)        Guest core N idle (EDEN_NX2_IDLE_STATS)
  DKB frame, gpu_frame, renderer, draws (EDEN_DKB_FRAME_TRACE: once a second, not per frame)
  Draw reuse per frame (EDEN_NX2_DRAW_REUSE_PROBE)   Buffer trace (EDEN_NX2_BUFFER_TRACE)
  Download trace (EDEN_NX2_DOWNLOAD_TRACE: only the first 2,000 guest reads of GPU-written ranges are logged)
  TCTRACE create / delete / upload / stale-skip (EDEN_NX2_TC_TRACE)   Texture cache: device memory (EDEN_NX2_TC_LOG)
  <thread> per second zones (EDEN_NX2_GPU_PROFILE)   Guest storage / file reads (EDEN_NX2_FS_READ_TRACE)

Options: --top N (rows of per-thread kinds, default 8), --log-clock, --with-warmup.
"""
import argparse
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rundir  # noqa: E402

T = r"\[\s*([\d.]+)\].*?"
F = r"([\d.]+)"


def kv_numbers(text, keys):
    out = {}
    for k in keys:
        m = re.search(r"\b" + re.escape(k) + r"=(-?[\d.]+)", text)
        if m:
            out[k] = float(m[1])
    return out


# Each kind: title, switch, line regex, parse(match) -> [(metric, value, agg)], per-entity (rows capped by --top).
# agg: mean / median / max over the phase's lines, sum = total in the phase, rate = total per second of the phase.
def p_back_idle(m):
    out = [("idle ms/frame", float(m[3]), "mean"), ("idle ms/s", float(m[2]), "mean")]
    for name, a, b in re.findall(r"([a-z][a-z ]*?) ([\d.]+) ([\d.]+)(?:,|$)", m[4]):
        out.append((f"  of it, front {name.strip()} ms/frame", float(b), "mean"))
    for n, label in re.findall(r"(\d+) ((?:under |over )?[\d.-]+ ms)", m[5]):
        out.append((f"idle periods {label} per 10 s", float(n), "mean"))
    return out


def p_front_waits(m):
    out = []
    for name, n, ms in re.findall(r"([a-z][a-z ]*?) (\d+) \(([\d.]+) ms", m[2]):
        out.append((f"{name.strip()} ms/s", float(ms) / 10, "mean"))
        out.append((f"{name.strip()} waits/s", float(n) / 10, "mean"))
    return out


def p_acquires(m):
    return [("passed without a drain /s", float(m[2]) / 10, "mean"), ("drained /s", float(m[3]) / 10, "mean")]


def p_fences(m):
    out = []
    for cat, n, susp, gave, mean, mx in re.findall(r"(reached at entry|submitted|beyond submitted|not allocated in "
                                                   r"nvdrv|no fence) (\d+) \((\d+) with a suspended channel, (\d+) auto "
                                                   r"waits gave up, reached in ([\d.]+) ms mean, ([\d.]+) max", m[2]):
        out.append((f"{cat}: presents of 600", float(n), "mean"))
        if int(n):
            out.append((f"{cat}: reached in ms (mean)", float(mean), "mean"))
            out.append((f"{cat}: reached in ms (max)", float(mx), "max"))
    out.append(("reached after the present returned, ms (mean)", float(m[4]), "mean"))
    return out


def p_thread(m):
    name = f"{m[2]} {m[3]}"
    return [(f"{name}: on core ms/frame", float(m[4]), "mean"), (f"{name}: of it JIT", float(m[5]), "mean"),
            (f"{name}: ready without a core", float(m[6]), "mean"), (f"{name}: waiting", float(m[7]), "mean")]


def p_core(m):
    c = f"core {m[2]}"
    return [(f"{c}: JIT ms/frame", float(m[3]), "mean"), (f"{c}: JIT exits/s", float(m[4]), "mean"),
            (f"{c}: block lookups/s", float(m[5]), "mean"), (f"{c}: blocks compiled/s", float(m[6]), "mean"),
            (f"{c}: full code cache clears", float(m[7]), "sum")]


def p_hosttiming(m):
    return [("waits/s", float(m[2]), "mean"), ("OS sleep ms/s", float(m[4]), "mean"),
            ("precise wait ms/s", float(m[5]), "mean"), ("wake late p50 us", float(m[7]), "median"),
            ("wake late p99 us", float(m[8]), "median"), ("wake late max us", float(m[9]), "max"),
            ("events late p50 us", float(m[11]), "median"), ("events late p99 us", float(m[12]), "median")]


def p_idle(m):
    c = f"core {m[2]}"
    return [(f"{c}: idle periods per 10 s", float(m[3]), "mean"),
            (f"{c}: share woken while polling %", 100 * float(m[4]) / max(float(m[3]), 1), "mean"),
            (f"{c}: blocked, woken p50 us", float(m[7]), "median"), (f"{c}: blocked, woken p99 us", float(m[8]), "median")]


def p_kv(keys):
    return lambda m: [(k, v, "median") for k, v in kv_numbers(m[2], keys).items() if v >= 0]


def p_reuse(m):
    t = m[2]
    out = []
    for label, pat in (("hit full", r"hit full ([\d.]+) \(([\d.]+) us\)"), ("miss full", r"miss full ([\d.]+) \(([\d.]+) us\)"),
                       ("miss delta", r"miss full [\d.]+ \([\d.]+ us\) delta ([\d.]+) \(([\d.]+) us\)")):
        x = re.search(pat, t)
        if x:
            out += [(f"{label} draws/frame", float(x[1]), "mean"), (f"{label} us/draw", float(x[2]), "mean")]
    for label, pat in (("gate ms/frame", r"gate ([\d.]+) ms/frame"), ("texture memo hits/frame", r"texture memo ([\d.]+) hits"),
                       ("texture memo misses/frame", r"([\d.]+) misses")):
        x = re.search(pat, t)
        if x:
            out.append((label, float(x[1]), "mean"))
    return out


def p_buffer(m):
    return [("MiB in buffers", float(m[2]), "max"), ("created per 10 s", float(m[3]), "mean"),
            ("MiB created per 10 s", float(m[4]), "mean"), ("joined per 10 s", float(m[5]), "mean"),
            ("MiB copied by joins per 10 s", float(m[6]), "mean"), ("collected per 10 s", float(m[8]), "mean")]


def p_tc(m):
    kind, rest = m[2], m[3]
    out = [(f"{kind} /s", 1.0, "rate")]
    ms = re.search(r"\bms=([\d.]+)", rest)
    if ms and kind in ("create", "upload"):
        out.append((f"{kind} ms/s", float(ms[1]), "rate"))
    if kind == "delete":
        r = re.search(r"reason=(\S+)", rest)
        out.append((f"  delete {r[1] if r else '?'} /s", 1.0, "rate"))
    return out


def p_tclog(m):
    return [("device memory MiB", float(m[2]), "max"), ("images", float(m[5]), "max"), ("images MiB", float(m[6]), "max")]


def p_profile(m):
    out = []
    for zone, ms in re.findall(r"\| ([^|(:]+?) ([\d.]+) ms \(", m[3]):
        out.append((f"{m[2]}: {zone} ms/s", float(ms), "mean"))
    return out


def p_fs(m):
    k = m[2]
    return [(f"{k} reads/s", float(m[3]), "rate"), (f"{k} MiB/s", float(m[5]), "rate"),
            (f"{k} p99 us", float(m[7]), "median"), (f"{k} max us", float(m[8]), "max"),
            (f"{k} reads over 1 ms", float(m[9]), "sum"), (f"{k} reads over 16 ms", float(m[10]), "sum")]


def p_download(m):
    return [("guest reads of GPU-written ranges logged", 1.0, "sum")]


KINDS = [
    ("Back idle in 10 s", "EDEN_NX2_BACK_IDLE_TRACE",
     T + r"Back idle in 10 s: " + F + r" ms/s, " + F + r" ms/frame over \d+ frames; by front state \(ms/s, ms/frame\): "
         r"(.*?); idle periods: (.*)", p_back_idle, False),
    ("Front waits for the back in 10 s by site", "EDEN_NX2_ACQUIRE_STATS",
     T + r"Front waits for the back in 10 s by site: (.*?)(?:; acquire methods|$)", p_front_waits, False),
    ("Acquires in 10 s", "EDEN_NX2_ACQUIRE_STATS", T + r"Acquires: (\d+) passed without a drain .*?, (\d+) drained",
     p_acquires, False),
    ("nx2:vi2 present fences, last 600 presents", "EDEN_NX2_PRESENT_FENCE_TRACE",
     T + r"present fences, last 600 presents: (.*?); reached after the present returned: (\d+) presents, " + F +
     r" ms mean", p_fences, False),
    ("Guest threads over 10 s (ms per frame)", "EDEN_NX2_GUEST_THREAD_STATS",
     T + r"Report:\s+(t\d+) (?:\(presents [\d.]+ a frame\) )?(\S.*?) prio \d+ mask \S+: on core " + F + r" \(JIT " + F +
     r".*?\), ready " + F + r", waiting " + F, p_thread, True),
    ("Guest core N over 10 s", "EDEN_NX2_GUEST_THREAD_STATS",
     T + r"Guest core (\d+) over [\d.]+ s: JIT " + F + r" ms/frame.*?JIT exits/s (\d+).*?(\d+) C\+\+ block lookups/s, "
         r"(\d+) blocks compiled/s, (\d+) full code cache clears", p_core, True),
    ("HostTiming wait (every second)", "EDEN_NX2_HOSTTIMING_STATS",
     T + r"HostTiming wait: (\d+) waits, (\d+) woken by new events, OS sleep " + F + r" ms/s, precise wait " + F +
     r" ms/s, margin (\d+) us; wake late p50/p99/max (\d+)/(\d+)/(\d+) us; (\d+) events late p50/p99/max "
     r"(\d+)/(\d+)/(\d+) us", p_hosttiming, False),
    ("Guest core N idle over 10 s", "EDEN_NX2_IDLE_STATS",
     T + r"Guest core (\d+) idle over [\d.]+ s: (\d+) periods, (\d+) woken while polling, " + F +
     r" us polled on average; (\d+) blocked, woken " + F + r" us \(p50\) " + F + r" us \(p99\)", p_idle, True),
    ("DKB frame (one present a second)", "EDEN_DKB_FRAME_TRACE", T + r"DKB frame (present=.*)",
     p_kv(["cpu_frame_wall_ms", "cpu_present_wall_ms", "fence_wall_ms", "composite_wall_ms", "sleep_actual_wall_ms",
           "pace_wall_ms"]), False),
    ("DKB gpu_frame (one frame timed on the GPU a second)", "EDEN_DKB_FRAME_TRACE", T + r"DKB gpu_frame (.*)",
     p_kv(["gpu_frame_span_ms", "gpu_busy_ms", "measured_submissions", "dropped_submissions"]), False),
    ("DKB renderer (one frame a second)", "EDEN_DKB_FRAME_TRACE", T + r"DKB renderer (.*)",
     p_kv(["cpu_frame_wall_ms", "cpu_composite_wall_ms", "capture_wall_ms", "acquire_frame_wall_ms",
           "record_submit_wall_ms", "frame_end_wall_ms"]), False),
    ("DKB draws (per second)", "EDEN_DKB_FRAME_TRACE", T + r"DKB draws (.*)",
     p_kv(["attempts_per_frame", "zero_direct_per_frame"]), False),
    ("Draw reuse per frame (10 s)", "EDEN_NX2_DRAW_REUSE_PROBE", T + r"Draw reuse per frame over \d+ frames: (.*)",
     p_reuse, False),
    ("Buffer trace (10 s)", "EDEN_NX2_BUFFER_TRACE",
     T + r"Buffer trace: (\d+) MiB in buffers; in 10 s (\d+) created \((\d+) MiB\), (\d+) joined into them \((\d+) MiB "
         r"copied\), (\d+) stream leaps, (\d+) collected", p_buffer, False),
    ("Download trace: guest reads of GPU-written ranges", "EDEN_NX2_DOWNLOAD_TRACE",
     T + r"Download trace: CPU read of GPU-written \[(0x[0-9a-f]+) \+(0x[0-9a-f]+)\) (\S+)", p_download, False),
    ("TCTRACE (per image event)", "EDEN_NX2_TC_TRACE", T + r"TCTRACE (create|delete|upload|stale-skip) (.*)", p_tc, False),
    ("Texture cache: device memory (every 600 frames)", "EDEN_NX2_TC_LOG",
     T + r"Texture cache: device memory (\d+) MiB \(expected (\d+) MiB, critical (\d+) MiB\), (\d+) images (\d+) MiB",
     p_tclog, False),
    ("GPU profile: zones per second (10 s)", "EDEN_NX2_GPU_PROFILE", T + r"Report: (.+?) per second:(\s*\|.*)", p_profile,
     True),
    ("Guest storage and file reads (about once a second)", "EDEN_NX2_FS_READ_TRACE",
     T + r"Guest (storage|file) reads: (\d+) in " + F + r" s, " + F + r" MiB, p50 " + F + r" us, p99 " + F +
     r" us, max " + F + r" us, (\d+) over 1 ms, (\d+) over 16 ms", p_fs, False),
]
COMPILED = [(t, s, re.compile(rx), fn, ent) for t, s, rx, fn, ent in KINDS]


def aggregate(values, agg, seconds):
    if agg == "mean":
        return statistics.fmean(values)
    if agg == "median":
        return statistics.median(values)
    if agg == "max":
        return max(values)
    if agg == "sum":
        return sum(values)
    return sum(values) / seconds if seconds else float("nan")


def fmt(v):
    if v != v:
        return "-"
    return f"{v:,.0f}" if abs(v) >= 1000 else f"{v:.2f}" if abs(v) < 10 else f"{v:.1f}"


def report(run, top):
    print(rundir.header(run))
    phases = run.phase_names()
    secs = {p: (lambda w: w[1] - w[0] if w else 0)(run.phase_log_window(p)) for p in phases}
    lines = run.log_lines()
    found = 0
    for title, switch, rx, fn, per_entity in COMPILED:
        vals = defaultdict(lambda: defaultdict(list))      # metric -> phase -> values
        aggs, order, nlines = {}, [], Counter()
        extra = None
        regions = defaultdict(Counter)
        for line in lines:
            m = rx.search(line)
            if not m:
                continue
            p = run.phase_of_log_time(float(m[1]))
            if not p:
                continue
            nlines[p] += 1
            for metric, v, agg in fn(m):
                if metric not in aggs:
                    aggs[metric] = agg
                    order.append(metric)
                vals[metric][p].append(v)
            if switch == "EDEN_NX2_DOWNLOAD_TRACE":
                regions[p][int(m[2], 16) & ~0xFFFF] += 1
        if not nlines:
            continue
        found += 1
        print(f"  -- {title} [{switch}]; lines " + ", ".join(f"{p} {nlines[p]}" for p in phases))
        rows = order
        if per_entity:
            ent = lambda metric: metric.split(":")[0]
            first = phases[0] if phases else None
            score = defaultdict(float)
            for metric in order:
                if first and vals[metric].get(first) and ent(metric) not in score:     # ranked by its first figure
                    score[ent(metric)] = aggregate(vals[metric][first], aggs[metric], secs[first])
            keep = {e for e, _ in sorted(score.items(), key=lambda kv: -kv[1])[:top]}
            rows = [mt for mt in order if ent(mt) in keep]
            if switch == "EDEN_NX2_GPU_PROFILE":     # each thread's largest zones in the first phase
                val = lambda mt: aggregate(vals[mt][first], aggs[mt], secs[first]) if vals[mt].get(first) else 0
                by_ent = defaultdict(list)
                for mt in rows:
                    by_ent[ent(mt)].append(mt)
                rows = [mt for e in by_ent for mt in sorted(by_ent[e], key=lambda mt: -val(mt))[:12]]
            else:
                rows.sort(key=lambda mt: (-score[ent(mt)], order.index(mt)))
        width = max([len(r) for r in rows] + [20])
        print(f"     {'':{width}s} " + " ".join(f"{p:>10s}" for p in phases))
        for metric in rows:
            cells = []
            for p in phases:
                v = vals[metric].get(p)
                cells.append(f"{fmt(aggregate(v, aggs[metric], secs[p])):>10s}" if v else f"{'-':>10s}")
            print(f"     {metric:{width}s} " + " ".join(cells))
        if regions:
            for p in phases:
                if regions[p]:
                    print(f"     {p}: most read 64 KiB regions: " +
                          ", ".join(f"{r:#x} {n}" for r, n in regions[p].most_common(6)))
    if not found:
        print("  none of the periodic statistics lines this reader knows")


def main():
    ap = rundir.add_common(argparse.ArgumentParser(description=__doc__.split("\n")[0]))
    ap.add_argument("--top", type=int, default=8, help="rows of per-thread and per-core kinds (default %(default)s)")
    a = ap.parse_args()
    for r in rundir.runs_from(a):
        report(r, a.top)


if __name__ == "__main__":
    main()
