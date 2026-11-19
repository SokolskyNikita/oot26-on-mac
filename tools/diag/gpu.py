#!/usr/bin/env python3
"""gpu.py [VIEW] RUN…: the GPU side of a harness run: MoltenVK's frame profiler (MVK_FRAMEPROF={rd}/frameprof.txt)
and Lichii's sync trace (P60_SYNC_TRACE={rd}/sync.txt), frame by frame against frames.bin. Standard library only.

All three are on CLOCK_UPTIME_RAW: frames.bin and the sync trace in ns, the profiler in host microseconds from
mach_absolute_time. Stutter-trace lines are placed on that clock through result.json (README.md, "Clocks").

Profiler records (MoltenVK/MoltenVK/Utility/MVKFrameProf.mm): C per command buffer (frame, GPU start and end us,
encoders, unsampled, kernel start and end us, host time its first encoder was made), S per encoder signature in it
(count, span, vertex, fragment in GPU ticks = ns), E per encoder only for every 150th frame, P per present, T clock
pairs. Sync trace lines: "<ns> <tag> <where> <a> <b>": frontwait (a = site, b = ns the GPU front waited for its back),
gpuwait (a = tick, b = ns Scheduler::Wait waited for the host GPU), hostwait (where = reader or gpu-side, a = ns a
read download waited), flush and finish (where:a = the call site), copy / copy-batched / copy-reordered (where:a =
the site, b = bytes).

Views (phase with --phase; the default is in brackets):
  frames [walk]    per frame: GPU busy (the union of command buffers' GPU intervals clipped to the frame's
                   present-to-present interval) and idle, command buffers, encoders, sync events and wait ms by tag,
                   JIT ms from matching stutter lines; by frame-time band for the whole phase, its first 300 frames
                   and the rest; where the slow bands' excess over the fast band goes; runs of slow frames
  sync [all]       needs only sync.txt: frames >= --slow-ms (default 30) classed as JIT (stutter line >= 5 ms JIT),
                   read wait (guest readers waited >= 5 ms for the host GPU), late start (no flush or finish for
                   >= 8 ms from the frame's start), mid gap (such a gap later in the frame) or other; GPU waits >= 8 ms;
                   -v lists every frame
  slow [walk]      each frame >= --slow-ms: the longest stretch with no flush or finish and where it starts, the
                   longest GPU idle gap (with the profiler), the largest frontwait and gpuwait, reader hostwaits, JIT
  stalls [walk]    command buffers whose GPU interval is >= --stall-ms (default 6): GPU ms, sampled pass time (sum of
                   S spans), encoders, top signatures, and whether a frame >= --slow-ms ends within two presents
  gaps [stand2]    GPU idle gaps of >= 100 us where the next command buffer was created after the GPU went idle,
                   split into hops: GPU idle -> the flush that submits it (CPU), flush -> encoding starts, encoding
                   -> commit, commit -> GPU start
  gapwaits [stand2] the same gaps by the last flush site before the GPU went idle and by the traced wait that
                   overlaps each most; all waits of the phase; flushes per frame by site
  gapctx [stand2]  for the frames the profiler dumped encoder by encoder, the gaps with the encoders around them,
                   and a tally of (kind, last encoder before, first encoder after)
  perframe [stand2] --count frames from --start (default 24 from 400): frame ms / GPU busy / CBs / encoders, and
                   medians by frame-time bucket
  sigdiff [stand2] A0 A1 B0 B1: encoder signatures per frame in two frame ranges of the phase (of RUN, or range B
                   of --run2), count and GPU ms, largest changes first (--top, default 16)
"""
import argparse
import bisect
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rundir  # noqa: E402

VIEWS = ("frames", "sync", "slow", "stalls", "gaps", "gapwaits", "gapctx", "perframe", "sigdiff")
PHASE_DEFAULT = {"frames": "walk", "sync": "all", "slow": "walk", "stalls": "walk", "gaps": "stand2",
                 "gapwaits": "stand2", "gapctx": "stand2", "perframe": "stand2", "sigdiff": "stand2"}
# video_core/gpu_split.h, enum class DrainSite
SITES = ["Other", "FetchDrain", "Acquire", "SemaphoreFlush", "FenceRelease", "ListWriters", "ListCopies", "ListSync",
         "ListFlush", "MacroDmaRead", "MacroDmaWrites", "MacroDmaFlush", "GpSyncFence", "Map", "FrontStart",
         "FrontVerify", "RingFull", "BackRegister", "BackCode", "SafeRead"]
STUTTER = re.compile(r"\[\s*([\d.]+)\].*Nx2Stutter frame=\d+ ms=([\d.]+) .*?jit=ms:([\d.]+),blocks:(\d+)")


def site_name(s):
    return SITES[s] if 0 <= s < len(SITES) else str(s)


# ---- loading ---------------------------------------------------------------------------------------------------
def load_profile(run):
    """Command buffers of frameprof.txt: dicts frame, gs, ge, n, ks, ke, cr (us), sigs [(sig, count, span ns)],
    enc [encoder signatures], in file order."""
    f = run.file("frameprof.txt")
    if not f.exists():
        return None
    cbs, cur = [], None
    with open(f, errors="replace") as fh:
        for line in fh:
            p = line.split()
            if not p:
                continue
            if p[0] == "C" and len(p) > 8:
                cur = {"frame": int(p[1]), "gs": float(p[2]), "ge": float(p[3]), "n": int(p[4]), "ks": float(p[6]),
                       "ke": float(p[7]), "cr": float(p[8]), "sigs": [], "enc": []}
                cbs.append(cur)
            elif p[0] == "S" and cur is not None and len(p) > 3:
                cur["sigs"].append((p[1], int(p[2]), int(p[3])))
            elif p[0] == "E" and cur is not None and len(p) > 2:
                cur["enc"].append(p[2])
    return cbs


def load_sync(run, t0_us=None, t1_us=None, margin_us=1e5):
    """Sync-trace events (ts us, tag, where, a, b), in file order, within [t0 - margin, t1 + margin] when given."""
    f = run.file("sync.txt")
    if not f.exists():
        return None
    lo = -1e300 if t0_us is None else t0_us - margin_us
    hi = 1e300 if t1_us is None else t1_us + margin_us
    out = []
    with open(f, errors="replace") as fh:
        for line in fh:
            p = line.split()
            if len(p) < 5:
                continue
            ts = int(p[0]) / 1e3
            if lo <= ts <= hi:
                out.append((ts, p[1], p[2], int(p[3]), int(p[4])))
    return out


def window(run, phase):
    """(edges in us, frame ms) of the phase: its presents on the uptime clock and the intervals between them."""
    run.require_phase(phase)
    edges = [t / 1e3 for t in run.phase_present_ns(phase)]
    return edges, [(b - a) / 1e3 for a, b in zip(edges, edges[1:])]


def stutter_on_uptime(run):
    """(uptime us, ms, jit ms, blocks) of every Nx2Stutter line."""
    out = []
    for m in STUTTER.finditer(run.log_text()):
        t = run.log_to_uptime(float(m[1]))
        if t is not None:
            out.append((t * 1e6, float(m[2]), float(m[3]), int(m[4])))
    return out


def need(run, what, name):
    if what is None:
        print(f"  no {name} in {run.path} ({'MVK_FRAMEPROF' if 'prof' in name else 'P60_SYNC_TRACE'}={{rd}}/{name})")
        return False
    return True


def q(sorted_values, f):
    return rundir.quantile(sorted_values, f)


def median(xs):
    xs = list(xs)
    return statistics.median(xs) if xs else float("nan")


def merged(intervals):
    out = []
    for s, e in sorted(intervals):
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out


def busy_per_frame(edges, cbs):
    """GPU busy ms per frame: the union of command buffer GPU intervals clipped to each frame."""
    n = len(edges) - 1
    busy = [0.0] * n
    for gs, ge in merged((c["gs"], c["ge"]) for c in cbs if c["ge"] > edges[0] and c["gs"] < edges[-1] and c["ge"] > c["gs"]):
        i = max(0, bisect.bisect_right(edges, gs) - 1)
        while i < n and edges[i] < ge:
            lo, hi = max(gs, edges[i]), min(ge, edges[i + 1])
            if hi > lo:
                busy[i] += (hi - lo) / 1e3
            i += 1
    return busy


# ---- frames (per-frame GPU busy by band) -------------------------------------------------------------------------
def view_frames(run, a):
    edges, d = window(run, a.phase)
    if a.frames:
        edges, d = edges[:a.frames + 1], d[:a.frames]
    n = len(d)
    cbs = load_profile(run)
    ev_all = load_sync(run, edges[0], edges[-1], 0)
    if not need(run, cbs, "frameprof.txt") or not need(run, ev_all, "sync.txt"):
        return
    inwin = [c for c in cbs if c["ge"] > edges[0] and c["gs"] < edges[-1] and c["ge"] > c["gs"]]
    busy = busy_per_frame(edges, inwin)
    ncb, enc = [0] * n, [0] * n
    for c in inwin:
        i = bisect.bisect_right(edges, c["gs"]) - 1
        if 0 <= i < n:
            ncb[i] += 1
            enc[i] += c["n"]
    idle = [x - y for x, y in zip(d, busy)]
    ev = defaultdict(lambda: [0] * n)
    wait = defaultdict(lambda: [0.0] * n)
    for ts, tag, where, x, y in ev_all:
        i = bisect.bisect_right(edges, ts) - 1
        if not 0 <= i < n:
            continue
        ev[tag][i] += 1
        if tag in ("gpuwait", "frontwait"):
            wait[tag][i] += y / 1e6
        elif tag == "hostwait":
            wait["hostwait:" + where][i] += x / 1e6
    jit = [None] * n
    for t, ms, j, _ in stutter_on_uptime(run):
        i = bisect.bisect_left(edges, t - 2000) - 1            # the line is written at the present that ends it
        cand = [k for k in (i - 1, i, i + 1) if 0 <= k < n]
        if not cand:
            continue
        k = min(cand, key=lambda k: abs(d[k] - ms))
        if abs(d[k] - ms) <= 3:
            jit[k] = j
    res = run.res
    s = sorted(d)
    print(rundir.header(run, f"  loadavg {[round(x, 1) for x in res.get('loadavg_before', [])]}  {a.phase} n={n} "
                             f"p50 {q(s, .5):.1f} p95 {q(s, .95):.1f} p99 {q(s, .99):.1f} max {s[-1]:.1f}  "
                             f"turns {run.walk_call.get('turns_at_frame')}"))
    bands = rundir.band_ranges(rundir.parse_bands(a.bands))
    tags, wtags = sorted(ev), sorted(wait)
    for scope, sel in (("whole " + a.phase, lambda i: True), ("frames 0-300", lambda i: i < 300),
                       ("frames 300+", lambda i: i >= 300)):
        print(f"  -- {scope}")
        for lo, hi in bands:
            w = [i for i in range(n) if sel(i) and lo <= d[i] < hi]
            if not w:
                continue
            evs = " ".join(f"{t} {sum(ev[t][i] for i in w) / len(w):.1f}" for t in tags)
            ws = " ".join(f"{t} {sum(wait[t][i] for i in w) / len(w):.2f}" for t in wtags)
            jj = [jit[i] for i in w if jit[i] is not None]
            hs = f"{hi:g}" if hi < 1e8 else ""
            print(f"  {lo:>2g}-{hs:<3} n={len(w):4d}  frame {median(d[i] for i in w):5.1f}  "
                  f"GPU busy {median(busy[i] for i in w):5.1f}  idle {median(idle[i] for i in w):5.1f}  "
                  f"cbs {median(ncb[i] for i in w):4.0f}  encoders {median(enc[i] for i in w):5.0f} | events/frame: "
                  f"{evs} | wait ms/frame: {ws}" + (f" | JIT ms (traced {len(jj)}): median {median(jj):.1f}" if jj else ""))
    base = [i for i in range(n) if bands[0][0] <= d[i] < bands[0][1]]
    if base:
        b_busy, b_idle, b_d = median(busy[i] for i in base), median(idle[i] for i in base), median(d[i] for i in base)
        for lo, hi in bands[2:]:
            w = [i for i in range(n) if lo <= d[i] < hi]
            if not w:
                continue
            ex = sum(d[i] - b_d for i in w)
            share = sum(busy[i] - b_busy for i in w) / ex * 100 if ex else 0
            more = sum((busy[i] - b_busy) > (idle[i] - b_idle) for i in w)
            hs = f"{hi:g}" if hi < 1e8 else ""
            print(f"  excess of {lo:g}-{hs} ms frames over the {rundir.band_name(*bands[0])} ms "
                  f"median: {share:.0f}% is extra GPU busy time, {100 - share:.0f}% extra idle; frames where busy "
                  f"grew more than idle: {more} of {len(w)}")
    slow_at = bands[2][0] if len(bands) > 2 else 22
    runs_ = Counter()
    k = 0
    for x in d + [0.0]:
        if x >= slow_at:
            k += 1
        elif k:
            runs_[min(k, 5)] += 1
            k = 0
    print(f"  runs of consecutive >={slow_at:g} ms frames (length: count, 5 = 5 or more):", dict(sorted(runs_.items())))
    nxt = [d[i + 1] for i in range(n - 1) if d[i] >= slow_at]
    if nxt:
        print(f"  frame after a >={slow_at:g} ms frame: median {median(nxt):.1f} ms; share under 17 ms "
              f"{100 * sum(x < 17 for x in nxt) / len(nxt):.0f}%")


# ---- sync (classification with the sync trace only) ---------------------------------------------------------
def frame_flush_view(ev, ts, s0, s1):
    """Events of [s0, s1): flush/finish times with the frame edges, the gaps between them (ms) and the longest."""
    w = ev[bisect.bisect_left(ts, s0):bisect.bisect_left(ts, s1)]
    fl = [s0] + [t for t, tag, *_ in w if tag in ("flush", "finish")] + [s1]
    g = [(b - a) / 1e3 for a, b in zip(fl, fl[1:])]
    gi = g.index(max(g))
    return w, fl, g, gi


def view_sync(run, a):
    ev = load_sync(run)
    res = run.res
    wc = run.walk_call
    p = wc.get("path") or []
    stalls = [i for i in range(1, len(p)) if sum((x - y) ** 2 for x, y in zip(p[i], p[i - 1])) ** 0.5 < 0.3]
    print(rundir.header(run, f"  loadavg {[round(x, 1) for x in res.get('loadavg_before', [])]}  moved "
                             f"{res.get(run.prefix + 'walk_moved_m')} m, max {wc.get('max_from_start_m')} m from start, "
                             f"stalled chunks {stalls}, harness chunks {wc.get('chunk')}, corrupt "
                             f"{(res.get('picture') or {}).get('corrupt')}"))
    if not need(run, ev, "sync.txt"):
        return
    ev = [e for e in ev if e[1] in ("flush", "finish", "hostwait", "gpuwait", "frontwait")]
    ts = [e[0] for e in ev]
    st = stutter_on_uptime(run)
    for ph in (run.phase_names() if a.phase == "all" else [a.phase]):
        e, d = window(run, ph)
        n = len(d)
        s = sorted(d)
        cls, exc, rows = Counter(), Counter(), []
        big_gw = sum(1 for t, tag, where, x, y in ev[bisect.bisect_left(ts, e[0]):bisect.bisect_left(ts, e[-1])]
                     if tag == "gpuwait" and y >= 8e6)
        for k in range(n):
            if d[k] < a.slow_ms:
                continue
            s0, s1 = e[k], e[k + 1]
            w, fl, g, gi = frame_flush_view(ev, ts, s0, s1)
            hw = sum(x for t, tag, where, x, y in w if tag == "hostwait" and where == "reader") / 1e6
            gw = max([y / 1e6 for t, tag, where, x, y in w if tag == "gpuwait"] or [0])
            c = [x for x in st if s0 < x[0] <= s1 + 3000 and abs(x[1] - d[k]) <= 3]
            jit, blocks = (c[0][2], c[0][3]) if c else (0.0, 0)
            first = (fl[1] - s0) / 1e3 if len(fl) > 2 else d[k]
            kind = "JIT" if jit >= 5 else "read wait" if hw >= 5 else "late start" if first >= 8 else \
                "mid gap" if g[gi] >= 8 else "other"
            cls[kind] += 1
            exc[kind] += d[k] - q(s, .5)
            rows.append((k, round(d[k], 1), kind, round(jit, 1), blocks, round(hw, 1), round(gw, 1), round(first, 1),
                         round(g[gi], 1), round((fl[gi] - s0) / 1e3, 1)))
        print(f"  {ph:6s} n={n} p50 {q(s, .5):.1f} p95 {q(s, .95):.1f} p99 {q(s, .99):.1f} max {s[-1]:.1f} | frames "
              f">={a.slow_ms:g} ms: {sum(x >= a.slow_ms for x in d)} | GPU waits >=8 ms: {big_gw} | "
              + ", ".join(f"{k} {v} ({exc[k]:.0f} ms)" for k, v in cls.most_common()))
        if a.verbose:
            for r in rows:
                print("     frame %d %.1f ms %-10s jit %.1f (%d blocks) readwait %.1f maxgpuwait %.1f first-flush %.1f "
                      "longest-gap %.1f at +%.1f" % r)


# ---- slow (each slow frame in detail) ------------------------------------------------------------------------
def view_slow(run, a):
    edges, d = window(run, a.phase)
    ev = load_sync(run, edges[0], edges[-1])
    print(rundir.header(run, f"  {a.phase} frames >= {a.slow_ms:g} ms"))
    if not need(run, ev, "sync.txt"):
        return
    ts = [e[0] for e in ev]
    cbs = load_profile(run)
    busy = merged((c["gs"], c["ge"]) for c in cbs if c["ge"] > c["gs"]) if cbs else None
    bstart = [b[0] for b in busy] if busy else []
    st = stutter_on_uptime(run)
    print(f"  {'frame':>5s} {'ms':>6s} {'no-flush':>8s} {'at +ms':>6s} {'GPU idle':>8s} {'at +ms':>6s} "
          f"{'frontwait':>9s} {'(site)':14s} {'gpuwait':>7s} {'reader hostwait':>15s} {'JIT':>5s}")
    for k in range(len(d)):
        if d[k] < a.slow_ms:
            continue
        s0, s1 = edges[k], edges[k + 1]
        w, fl, g, gi = frame_flush_view(ev, ts, s0, s1)
        fw = max([(y / 1e6, x) for t, tag, where, x, y in w if tag == "frontwait"] or [(0.0, -1)])
        gw = max([y / 1e6 for t, tag, where, x, y in w if tag == "gpuwait"] or [0.0])
        hws = [x / 1e6 for t, tag, where, x, y in w if tag == "hostwait" and where == "reader"]
        c = [x for x in st if s0 < x[0] <= s1 + 3000 and abs(x[1] - d[k]) <= 3]
        jit = f"{c[0][2]:5.1f}" if c else "    -"
        if busy is not None:
            j = max(0, bisect.bisect_right(bstart, s0) - 1)
            iv = []
            while j < len(busy) and busy[j][0] < s1:
                lo, hi = max(busy[j][0], s0), min(busy[j][1], s1)
                if hi > lo:
                    iv.append((lo, hi))
                j += 1
            pts = [s0] + [x for lo_hi in iv for x in lo_hi] + [s1]
            gaps = [(pts[i + 1] - pts[i], pts[i]) for i in range(0, len(pts) - 1, 2)]
            gap, gat = max(gaps) if gaps else (s1 - s0, s0)
            idle = f"{gap / 1e3:8.1f} {(gat - s0) / 1e3:6.1f}"
        else:
            idle = f"{'-':>8s} {'-':>6s}"
        print(f"  {k:5d} {d[k]:6.1f} {g[gi]:8.1f} {(fl[gi] - s0) / 1e3:6.1f} {idle} {fw[0]:9.1f} "
              f"{('(' + site_name(fw[1]) + ')') if fw[1] >= 0 else '':14s} {gw:7.1f} "
              f"{sum(hws):8.1f} in {len(hws):3d} {jit}")


# ---- stalls (long command buffers) ---------------------------------------------------------------------------
def view_stalls(run, a):
    edges, d = window(run, a.phase)
    cbs = load_profile(run)
    print(rundir.header(run, f"  command buffers >= {a.stall_ms:g} ms on the GPU in {a.phase}"))
    if not need(run, cbs, "frameprof.txt"):
        return
    long_ = [c for c in cbs if edges[0] <= c["gs"] < edges[-1] and c["ge"] - c["gs"] >= a.stall_ms * 1e3]
    slow = {i for i in range(len(d)) if d[i] >= a.slow_ms}
    followed = 0
    print(f"  {'frame':>5s} {'GPU ms':>7s} {'passes ms':>9s} {'enc':>5s} {'slow':>4s}  top signatures (ms)")
    for c in sorted(long_, key=lambda c: c["gs"]):
        i = bisect.bisect_right(edges, c["ge"]) - 1
        hit = any(j in slow for j in (i, i + 1))
        followed += hit
        span = sum(x[2] for x in c["sigs"]) / 1e6
        agg = defaultdict(float)
        for sig, cnt, sp in c["sigs"]:
            agg[sig] += sp / 1e6
        top = ", ".join(f"{s} {v:.1f}" for s, v in sorted(agg.items(), key=lambda kv: -kv[1])[:3])
        print(f"  {bisect.bisect_right(edges, c['gs']) - 1:5d} {(c['ge'] - c['gs']) / 1e3:7.1f} {span:9.1f} "
              f"{c['n']:5d} {'yes' if hit else 'no':>4s}  {top}")
    pre = sum(1 for i in slow if any(bisect.bisect_right(edges, c["ge"]) - 1 in (i, i - 1) for c in long_))
    print(f"  {len(long_)} long command buffers; {followed} followed by a frame >= {a.slow_ms:g} ms within two presents; "
          f"{pre} of {len(slow)} such frames have one")


# ---- the standing-phase gap analyses (ported from the path-to-60fps scripts) ---------------------------------
def gap_setup(run, a):
    """Command buffers wholly inside the phase, sorted, and the phase's window and frame count."""
    edges, d = window(run, a.phase)
    cbs = load_profile(run)
    if cbs is None:
        return None
    w0, w1 = edges[0], edges[-1]
    inside = sorted((c for c in cbs if c["gs"] >= w0 and c["ge"] <= w1), key=lambda c: c["gs"])
    return edges, len(d), w0, w1, inside


def view_gaps(run, a):
    print(rundir.header(run, f"  {a.phase}: created-after GPU idle gaps split into hops"))
    g = gap_setup(run, a)
    ev = load_sync(run)
    if not need(run, g, "frameprof.txt") or not need(run, ev, "sync.txt"):
        return
    edges, nfr, w0, w1, cbs = g
    ft = sorted(t for t, tag, *_ in ev if tag in ("flush", "finish"))
    A, B, C, D, G, NE = [], [], [], [], [], []
    busy_end = None
    tot = 0
    for c in cbs:
        gs, ge, ks, cr, n = c["gs"], c["ge"], c["ks"], c["cr"], c["n"]
        if busy_end is not None and gs - busy_end >= 100 and cr >= busy_end:
            j = bisect.bisect_right(ft, cr) - 1
            f2 = ft[j] if j >= 0 else cr
            A.append(max(f2 - busy_end, 0.0)); B.append(cr - max(f2, busy_end)); C.append(ks - cr)
            D.append(gs - ks); G.append(gs - busy_end); NE.append(n); tot += gs - busy_end
        if busy_end is None or ge > busy_end:
            busy_end = ge
    k = len(G)
    if not k:
        print("  no gaps")
        return
    m = statistics.median
    print(f"{k / nfr:.1f} gaps/frame, {tot / nfr / 1e3:.2f} ms/frame; per gap: median {m(G):.0f} us, mean {sum(G) / k:.0f} us")
    for name, x in (("A  GPU idle -> next flush (CPU produces the next commands)", A), ("B  flush -> encoding starts", B),
                    ("C  encoding -> commit", C), ("D  commit -> GPU start", D)):
        print(f"  {name:58} median {m(x):5.0f} us  mean {sum(x) / k:5.0f} us  = {sum(x) / nfr / 1e3:.2f} ms/frame")
    print(f"  encoders in the command buffer after a gap: median {m(NE):.0f}; gaps where the next flush came before "
          f"the GPU went idle: {sum(1 for x in A if x == 0) / k:.0%}")


def view_gapwaits(run, a):
    print(rundir.header(run, f"  {a.phase}: GPU idle gaps against the sync trace"))
    g = gap_setup(run, a)
    if not need(run, g, "frameprof.txt"):
        return
    edges, nfr, w0, w1, cbs = g
    ev = load_sync(run, w0, w1)
    if not need(run, ev, "sync.txt"):
        return
    flushes, waits = [], []
    for ts, tag, where, x, y in ev:
        if tag in ("flush", "finish"):
            flushes.append((ts, f"{tag} {Path(where).name}:{x}"))
        elif tag == "gpuwait":
            waits.append((ts - y / 1e3, ts, "wait for host GPU tick (Scheduler::Wait)"))
        elif tag == "frontwait":
            waits.append((ts - y / 1e3, ts, "front waits for back: " + site_name(x)))
        elif tag == "hostwait":
            waits.append((ts - x / 1e3, ts, f"read download waits for host GPU ({where})"))
    flushes.sort()
    ft = [f[0] for f in flushes]
    wbe = sorted(waits, key=lambda w: w[1])
    wends = [w[1] for w in wbe]
    by_flush, by_wait, cnt_flush, allwait = Counter(), Counter(), Counter(), Counter()
    for s, e, k in waits:
        allwait[k] += e - s
    total = 0.0
    n = 0
    busy_end = None
    for c in cbs:
        gs, ge, cr = c["gs"], c["ge"], c["cr"]
        if busy_end is not None and gs - busy_end >= 100 and cr >= busy_end:
            gap = gs - busy_end
            total += gap
            n += 1
            j2 = bisect.bisect_right(ft, busy_end) - 1
            prev = flushes[j2][1] if j2 >= 0 else "?"
            by_flush[prev] += gap
            cnt_flush[prev] += 1
            ov = Counter()
            j0 = bisect.bisect_left(wends, busy_end)
            for ws, we, k in wbe[j0:j0 + 4000]:
                if ws >= gs and we - ws < 1e5 and we > gs + 2e5:
                    break
                o = min(we, gs) - max(ws, busy_end)
                if o > 0:
                    ov[k] += o
            if ov:
                by_wait[ov.most_common(1)[0][0]] += gap
            else:
                by_wait["no traced wait overlaps the gap"] += gap
        if busy_end is None or ge > busy_end:
            busy_end = ge
    print(f"{a.phase}: {nfr} frames; created-after gaps of 100 us or more: {n / nfr:.1f} per frame, "
          f"{total / nfr / 1e3:.2f} ms per frame")
    print("\ngap time by the last flush before the GPU went idle (ms/frame, gaps/frame):")
    for k, v in by_flush.most_common(12):
        print(f"  {v / nfr / 1e3:5.2f}  {cnt_flush[k] / nfr:5.2f}  {k}")
    print("\ngap time by the traced wait that overlaps the gap most (ms/frame):")
    for k, v in by_wait.most_common(12):
        print(f"  {v / nfr / 1e3:5.2f}  {k}")
    print("\nall traced waits in the phase, whether or not the GPU was idle (ms/frame):")
    for k, v in allwait.most_common(12):
        print(f"  {v / nfr / 1e3:5.2f}  {k}")
    print("\nflushes per frame by site:")
    fc = Counter(w for ts, w in flushes if w0 <= ts <= w1)
    for k, v in fc.most_common(14):
        print(f"  {v / nfr:6.1f}  {k}")


def view_gapctx(run, a):
    print(rundir.header(run, f"  {a.phase}: GPU idle gaps in the frames dumped encoder by encoder"))
    g = gap_setup(run, a)
    if not need(run, g, "frameprof.txt"):
        return
    edges, nfr, w0, w1, cbs = g
    short = lambda s: re.sub(r"0000000000000000:0", "mvk", s)
    tally = Counter()
    shown = ngap = 0
    tot = 0.0
    busy_end = prev = None
    for c in cbs:
        if busy_end is not None and c["gs"] > busy_end and c["gs"] - busy_end >= 100:
            gap = c["gs"] - busy_end
            kind = "created-after" if c["cr"] >= busy_end else "committed-late" if c["ks"] >= busy_end else "scheduled-late"
            if prev["enc"] and c["enc"]:
                ngap += 1
                tot += gap
                tally[(kind, short(prev["enc"][-1]), short(c["enc"][0]))] += gap
                if shown < 14:
                    shown += 1
                    print(f"gap {gap:6.0f} us {kind:14} prev CB {prev['n']:3} enc, GPU {prev['ge'] - prev['gs']:6.0f} us, "
                          f"ends: {' | '.join(short(e) for e in prev['enc'][-3:])}")
                    print(f"{'':28} next CB {c['n']:3} enc, created {c['cr'] - busy_end:+6.0f} us after idle, commit "
                          f"{c['ks'] - busy_end:+6.0f}; starts: {' | '.join(short(e) for e in c['enc'][:3])}")
        if busy_end is None or c["ge"] > busy_end:
            busy_end, prev = c["ge"], c
    print(f"\nsampled gaps: {ngap}, {tot / 1e3:.1f} ms total. By (kind, last encoder before, first encoder after), "
          f"share of sampled gap time:")
    for (k, x, y), v in tally.most_common(25):
        print(f"  {100 * v / tot:5.1f}%  {k:14} {x:44} -> {y}")


def view_perframe(run, a):
    print(rundir.header(run, f"  {a.phase}: per frame ms/busy/cbs/encoders"))
    cbs = load_profile(run)
    if not need(run, cbs, "frameprof.txt"):
        return
    fr, _ = window(run, a.phase)
    rows = [[fr[i + 1] - fr[i], 0.0, 0, 0] for i in range(len(fr) - 1)]
    for c in cbs:
        i = bisect.bisect_right(fr, c["ge"]) - 1
        if 0 <= i < len(rows):
            rows[i][1] += c["ge"] - c["gs"]
            rows[i][2] += 1
            rows[i][3] += c["n"]
    print(" ".join(f"{r[0] / 1e3:.0f}ms/{r[1] / 1e3:.0f}busy/{r[2]}cb/{r[3]}enc" for r in rows[a.start:a.start + a.count]))
    for lo, hi in ((0, 24), (24, 34), (34, 50), (50, 70), (70, 1e9)):
        w = [r for r in rows if lo <= r[0] / 1e3 < hi]
        if w:
            print(f"frames {lo}-{hi if hi < 1e8 else 'inf'} ms: {len(w):4}  GPU work in them: median "
                  f"{statistics.median(r[1] for r in w) / 1e3:5.1f} ms, CBs {statistics.median(r[2] for r in w):.0f}, "
                  f"encoders {statistics.median(r[3] for r in w):.0f}")


def sig_load(run, phase, r0, r1):
    fr, _ = window(run, phase)
    w0, w1 = fr[r0], fr[r1]
    acc = defaultdict(lambda: [0, 0.0])
    ncb = 0
    for c in load_profile(run) or []:
        if w0 <= c["ge"] < w1:
            ncb += 1
            for sig, cnt, span in c["sigs"]:
                acc[sig][0] += cnt
                acc[sig][1] += span / 1e6
    n = r1 - r0
    return {k: (v[0] / n, v[1] / n) for k, v in acc.items()}, ncb / n


def view_sigdiff(run, a, run2):
    if len(a.ranges) != 4:
        raise SystemExit("sigdiff needs A0 A1 B0 B1 (frame offsets into the phase)")
    a0, a1, b0, b1 = a.ranges
    print(rundir.header(run, f"  {a.phase}: signatures, frames {a0}-{a1} against {b0}-{b1}"
                             + (f" of {run2.label}" if run2 is not run else "")))
    if not need(run, load_profile(run), "frameprof.txt"):
        return
    A = sig_load(run, a.phase, a0, a1)
    B = sig_load(run2, a.phase, b0, b1)
    print(f"command buffers/frame {A[1]:.1f} vs {B[1]:.1f}; encoders/frame {sum(v[0] for v in A[0].values()):.0f} vs "
          f"{sum(v[0] for v in B[0].values()):.0f}; encoder GPU ms/frame {sum(v[1] for v in A[0].values()):.2f} vs "
          f"{sum(v[1] for v in B[0].values()):.2f}")
    keys = sorted(set(A[0]) | set(B[0]), key=lambda k: -abs(B[0].get(k, (0, 0))[1] - A[0].get(k, (0, 0))[1]))
    for k in keys[:a.top]:
        x, y = A[0].get(k, (0, 0)), B[0].get(k, (0, 0))
        print(f"  {x[0]:7.2f} {x[1]:7.3f} ms -> {y[0]:7.2f} {y[1]:7.3f} ms  ({y[1] - x[1]:+.3f})  {k}")


def main():
    view, rest = rundir.view_and_rest(sys.argv[1:], VIEWS, "frames")
    ap = rundir.add_common(argparse.ArgumentParser(description=__doc__.split("\n")[0]), phase_default=PHASE_DEFAULT[view])
    ap.add_argument("--slow-ms", type=float, default=30.0, help="slow frame threshold (default %(default)s)")
    ap.add_argument("--stall-ms", type=float, default=6.0, help="long command buffer threshold (stalls)")
    ap.add_argument("--frames", type=int, default=0, help="frames: only the phase's first N frames")
    ap.add_argument("--start", type=int, default=400, help="perframe: first frame shown")
    ap.add_argument("--count", type=int, default=24, help="perframe: frames shown")
    ap.add_argument("--run2", help="sigdiff: take range B from this run folder")
    ap.add_argument("--top", type=int, default=16, help="sigdiff: signatures shown")
    ap.add_argument("-v", "--verbose", action="store_true", help="sync: every slow frame")
    if view == "sigdiff":
        # the four frame offsets come after the run folder: gpu.py sigdiff RUN A0 A1 B0 B1
        nums, keep = [], []
        for i, x in enumerate(rest):
            is_value = i > 0 and rest[i - 1].startswith("-") and "=" not in rest[i - 1]
            (nums if re.fullmatch(r"\d+", x) and not is_value else keep).append(x)
        rest = keep
    a = ap.parse_args(rest)
    runs = rundir.runs_from(a)
    if view == "sigdiff":
        a.ranges = [int(x) for x in nums]
        run2 = rundir.load_runs([a.run2])[0] if a.run2 else None
        for r in runs:
            view_sigdiff(r, a, run2 or r)
        return
    fn = {"frames": view_frames, "sync": view_sync, "slow": view_slow, "stalls": view_stalls, "gaps": view_gaps,
          "gapwaits": view_gapwaits, "gapctx": view_gapctx, "perframe": view_perframe}[view]
    for r in runs:
        fn(r, a)


if __name__ == "__main__":
    main()
