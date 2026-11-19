#!/usr/bin/env python3
"""jit.py [VIEW] RUN…: the guest CPU JIT's own recordings in a harness run folder. Standard library only.

Views:
  log (default)  {rd}/jit.bin from EDEN_NX2_JIT_LOG=<file>, which only a build with
                 patches/experiments/dynarmic-jit-log-2026-11-17.patch has. One 40-byte record per compiled block:
                 t_ns (steady_clock, so CLOCK_MONOTONIC_RAW), location (PC in the low 56 bits), IR op count, host
                 bytes, translate / optimise / emit ns, core, full-clear flag, link microseconds. Prints the split
                 by compile phase, per-core totals, how much was compiled more than once (on another core or again
                 after a flush), a per-second timeline, the split by harness step and where the guest code lives
                 (module and 4 KiB page, from the log's "Module … loaded at" lines)
  trace          {rd}/jit-trace.bin from DYNARMIC_JIT_TRACE=<file> (Lichii patch 0007, in the pinned build): what the
                 program asked of the arm64 code cache. 32-byte records (u8 type, u8 jit, u16 flags, u32 count,
                 u64 time_ns, u64 a, u64 b; a Compile is followed by count pairs of u64 guest address and instruction
                 word): lookups that missed a Jit's own table, compiles, fastmem faults, invalidations, clears. Its
                 clock starts at the first record, so it is placed on the harness clock by the log's "JIT totals
                 core=N blocks=B" lines (the B-th compile of that Jit; needs the stutter trace or guest thread
                 stats). Prints counts by type, per Jit, and by harness phase. The records also replay offline:
                 DYNARMIC_JIT_REPLAY=<file> with dynarmic_tests "[jit_replay]" in the PR #2101 tree with
                 patches/upstream/dynarmic-pr2101-tree-shared-jit-cache-with-tests.patch
"""
import re
import statistics
import struct
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rundir  # noqa: E402

VIEWS = ("log", "trace")
PC_MASK = (1 << 56) - 1
REC = struct.Struct("<QQIIIIIBBH")          # 40 bytes: t, loc, ir, host, tr, opt, emit, core, clear, link_us


def modules(log_text):
    return [(int(m[2], 16), int(m[2], 16) + int(m[3], 16), m[1])
            for m in re.finditer(r"Module (\S+) loaded at 0x([0-9a-f]+) \(size 0x([0-9a-f]+)\)", log_text)]


def view_log(rd):
    raw = (rd / "jit.bin").read_bytes() if (rd / "jit.bin").exists() else b""
    n = len(raw) // REC.size
    if n == 0:
        print(f"== {rd.name}: no records in jit.bin (EDEN_NX2_JIT_LOG, experiment patch only)")
        return
    t, loc, ir, host, tr, opt, emit, core, clear, link_us = (list(c) for c in zip(*REC.iter_unpack(raw[:n * REC.size])))
    t0 = min(t)
    sec = [(x - t0) / 1e9 for x in t]
    pc = [x & PC_MASK for x in loc]
    link = [x * 1e3 for x in link_us]
    phases = {"translate (guest -> IR)": tr, "optimise (IR passes)": opt, "emit (IR -> Mac code)": emit,
              "link + icache": link}
    total = sum(sum(v) for v in phases.values())
    print(f"{n:,} blocks over {max(sec):.1f} s, {total / 1e9:.2f} s of compile time (sum over cores)")
    for k, v in phases.items():
        print(f"  {k:24s} {sum(v) / 1e9:7.2f} s  {100 * sum(v) / total:5.1f}%  median {statistics.median(v) / 1e3:6.1f} us")
    print(f"  IR ops/block median {int(statistics.median(ir))}, host bytes total {sum(host) / 2**20:.0f} MiB, "
          f"full flushes {sum(clear)}")

    per_blk = [a + b + c + d for a, b, c, d in zip(tr, opt, emit, link)]
    cores = sorted(set(core))
    print("\nper core: blocks, compile s, unique PCs")
    for c in cores:
        idx = [i for i in range(n) if core[i] == c]
        print(f"  core {c:3d}: {len(idx):8,}  {sum(per_blk[i] for i in idx) / 1e9:6.2f} s  "
              f"{len({pc[i] for i in idx}):8,}")

    # Repeats: the first compile of a location anywhere is "needed"; every later one (another core, or again after a
    # flush on the same core) is a repeat a shared or persistent cache would have saved.
    seen = set()
    first = [False] * n
    for i in sorted(range(n), key=lambda i: t[i]):
        if loc[i] not in seen:
            seen.add(loc[i])
            first[i] = True
    rep = sum(per_blk[i] for i in range(n) if not first[i])
    tot = sum(per_blk)
    print(f"\nunique locations {len(seen):,}; repeats {first.count(False):,} blocks = {rep / 1e9:.2f} s of "
          f"{tot / 1e9:.2f} s ({100 * rep / tot:.0f}%)")
    per_loc = defaultdict(set)
    for l, c in zip(loc, core):
        per_loc[l].add(c)
    ncores = Counter(len(v) for v in per_loc.values())
    print("  locations compiled on N cores: " + ", ".join(f"{k}: {c:,}" for k, c in sorted(ncores.items())))

    print("\nper second: blocks / compile ms, by core")
    print("   s  " + "".join(f"{'core ' + str(c):>16s}" for c in cores) + "     new-locations")
    cnt = defaultdict(int)
    ms = defaultdict(float)
    new = defaultdict(int)
    for i in range(n):
        s = int(sec[i])
        cnt[(s, core[i])] += 1
        ms[(s, core[i])] += per_blk[i]
        new[s] += first[i]
    secs = sorted({int(x) for x in sec})
    for s in secs:
        cells = "".join(f"{cnt[(s, c)]:7d} /{ms[(s, c)] / 1e6:6.0f}ms" for c in cores)
        print(f"{s:4d}  {cells}   {new[s]:7d}")

    steps_report(rd, t, core, per_blk, first)

    log = rd / "eden_log.txt"
    mods = modules(log.read_text(errors="replace")) if log.exists() else []
    if mods:
        where = defaultdict(lambda: [0, 0.0])
        pages = defaultdict(float)
        for p, cost in zip(pc, per_blk):
            hit = next(((lo, name) for lo, hi, name in mods if lo <= p < hi), (0, "other"))
            where[hit[1]][0] += 1
            where[hit[1]][1] += cost
            pages[(hit[1], (p - hit[0]) & ~0xFFF)] += cost
        print("\nby module: blocks, compile s")
        for name, (c, cost) in sorted(where.items(), key=lambda kv: -kv[1][1]):
            print(f"  {name:10s} {c:8,}  {cost / 1e9:6.2f} s")
        print("\ntop 15 code pages (module + offset) by compile time")
        for (name, off), cost in sorted(pages.items(), key=lambda kv: -kv[1])[:15]:
            print(f"  {name}+0x{off:x}  {cost / 1e6:7.1f} ms")


def step_times(rd):
    """The harness's steps on CLOCK_MONOTONIC_RAW (the JIT log's clock: libc++'s steady_clock): result.json's
    t_monotonic, or for runs made before it existed, rebuilt from frames.bin (CLOCK_UPTIME_RAW; the boot ends at
    present 300, phases at their marked presents) and the menu trace (seconds after the boot ended), shifted by
    today's difference between the two clocks (right unless the Mac slept since the run)."""
    run = rundir.load_run(rd)[0]
    if run.res.get("t_monotonic"):
        return dict(run.res["t_monotonic"]), "recorded"
    fr = run.frames
    if len(fr) < 300:
        return {}, "none"
    t = {"boot_done": int(fr[299])}
    for when, what in run.res.get("menu_trace", []):
        key = {"loading": "loading", "in game": "in_game"}.get(what)
        if key and key not in t:
            t[key] = int(fr[299] + when * 1e9)
    for name, i in run.res.get("marks", {}).items():
        if i < len(fr):
            t[name] = int(fr[i])
    off = time.clock_gettime_ns(time.CLOCK_MONOTONIC_RAW) - time.clock_gettime_ns(time.CLOCK_UPTIME_RAW)
    return {k: v + off for k, v in t.items()}, "rebuilt from frames.bin and the menu trace (about +-0.5 s)"


def steps_report(rd, t, core, per_blk, first):
    try:
        steps, how = step_times(rd)
    except (OSError, ValueError):
        return
    if not steps:
        return
    edges = [("(JIT starts)", min(t))] + sorted(steps.items(), key=lambda kv: kv[1]) + [("(log ends)", max(t) + 1)]
    cores = sorted(set(core))
    print(f"\nby harness step ({how}): wall s, blocks, compile s summed, busiest core's compile s and share of the "
          f"wall time, new locations")
    order = sorted(range(len(t)), key=lambda i: t[i])
    ts = [t[i] for i in order]
    import bisect
    for (a, ta), (b, tb) in zip(edges, edges[1:]):
        if tb <= ta:
            continue
        sel = order[bisect.bisect_left(ts, ta):bisect.bisect_left(ts, tb)]
        wall = (tb - ta) / 1e9
        per_core = defaultdict(float)
        for i in sel:
            per_core[core[i]] += per_blk[i] / 1e9
        busiest = max([per_core[c] for c in cores] or [0.0])
        print(f"  {a:>13s} -> {b:<13s} {wall:6.1f} s  {len(sel):9,}  {sum(per_blk[i] for i in sel) / 1e9:6.2f} s  "
              f"{busiest:5.2f} s ({100 * busiest / wall:3.0f}%)  {sum(first[i] for i in sel):8,}")


TREC = struct.Struct("<BBHIQQQ")
TYPES = {0: "header", 1: "lookup", 2: "compile", 3: "fault", 4: "invalidate", 5: "clear"}
LOOKUP_FLAGS = {0: "found in the cache", 1: "compiled here", 2: "translated here but found emitted"}
FAULT_FLAGS = {0: "current code", 1: "stale code", 2: "dropped a block", 3: "stale code, dropped a block"}


def view_trace(run):
    f = run.file("jit-trace.bin")
    print(rundir.header(run, "  DYNARMIC_JIT_TRACE"))
    if not f.exists():
        print("  no jit-trace.bin (DYNARMIC_JIT_TRACE={rd}/jit-trace.bin)")
        return
    data = f.read_bytes()
    n, off = len(data), 0
    by = Counter()
    per_jit = defaultdict(Counter)
    compiles = defaultdict(list)          # jit -> compile times (ns from the first record)
    events = []                           # (time_ns, type, flags)
    header = None
    instrs = 0
    while off + 32 <= n:
        typ, jit, flags, count, tn, a, b = TREC.unpack_from(data, off)
        off += 32
        if typ == 2:
            off += 16 * count
            instrs += count
            compiles[jit].append(tn)
        if typ == 0:
            header = (a, flags)
        by[(typ, flags)] += 1
        per_jit[jit][typ] += 1
        if typ != 1:
            events.append((tn, typ, flags))
    if header:
        print(f"  code cache {header[0] >> 20} MiB, {'shared by the Jits' if header[1] & 1 else 'one per Jit'}; "
              f"{f.stat().st_size / 1e6:.0f} MB, {sum(by.values()):,} records")
    for (typ, flags), c in sorted(by.items()):
        what = LOOKUP_FLAGS.get(flags) if typ == 1 else FAULT_FLAGS.get(flags) if typ == 3 else \
            ("the cache was full" if flags else "") if typ == 5 else ""
        print(f"  {TYPES.get(typ, typ):10s} {what:34s} {c:12,}")
    print(f"  compiled blocks hold {instrs:,} guest instructions")
    print("  per Jit (one per guest core): " + "; ".join(
        f"{j}: {per_jit[j][2]:,} compiles, {per_jit[j][1]:,} lookups" for j in sorted(per_jit)) +
          " (faults, invalidations and clears are all recorded under Jit 0)")
    # Place the trace's clock: "JIT totals core=C blocks=B" is written after that core's B-th compile.
    offs = []
    for m in re.finditer(r"\[\s*([\d.]+)\].*JIT totals core=(\d+) blocks=(\d+)", run.log_text()):
        c, b = int(m[2]), int(m[3])
        if 0 < b <= len(compiles.get(c, [])):
            offs.append(float(m[1]) - compiles[c][b - 1] / 1e9)
    if not offs:
        print("  no JIT totals lines in the log to place the trace on the harness clock: no phase split")
        return
    lo = sorted(offs)[len(offs) // 10] if len(offs) >= 10 else min(offs)
    off_s = statistics.median(offs)
    print(f"  trace time 0 = log time {off_s:.2f} s (median of {len(offs)} JIT totals lines, 10th percentile {lo:.2f})")
    print(f"  {'phase':8s} {'s':>6s} {'compiles':>9s} {'per s':>7s} {'faults':>8s} {'invalidations':>13s} {'clears':>6s}")
    windows = [("load", run.step_log_time("start") or 0.0, run.step_log_time("load_done"))] + \
              [(p, *run.phase_log_window(p)) for p in run.phase_names() if run.phase_log_window(p)]
    allc = sorted(x for v in compiles.values() for x in v)
    import bisect
    for name, a, b in windows:
        if b is None:
            continue
        ta, tb = (a - off_s) * 1e9, (b - off_s) * 1e9
        nc = bisect.bisect_left(allc, tb) - bisect.bisect_left(allc, ta)
        ev = Counter(typ for tn, typ, fl in events if ta <= tn < tb)
        print(f"  {name:8s} {b - a:6.1f} {nc:9,} {nc / max(b - a, 1e-9):7.0f} {ev[3]:8,} {ev[4]:13,} {ev[5]:6,}")


def main():
    view, rest = rundir.view_and_rest(sys.argv[1:], VIEWS, "log")
    if not rest or rest[0] in ("-h", "--help"):
        print(__doc__)
        return
    for a in rest:
        p = Path(a)
        if view == "log":
            for r in rundir.load_runs([p]):
                view_log(r.path)
        else:
            for r in rundir.load_runs([p]):
                view_trace(r)


if __name__ == "__main__":
    main()
