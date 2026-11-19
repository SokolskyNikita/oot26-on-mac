#!/usr/bin/env python3
"""jitlog.py RUN_DIR: summarise a JIT compile log written by app-jitlog (EDEN_NX2_JIT_LOG=<file>).

Each record (40 bytes, patches/experiments/dynarmic-jit-log-2026-11-17.patch) is one compiled block:
t_ns, location (PC in the low 56 bits), IR op count, host bytes, translate/optimize/emit ns, core, full-clear flag,
link microseconds. Prints the per-phase split, per-core totals, how much was compiled more than once (on other cores
or again after a flush), a per-second timeline, and where the guest code lives (module and 4 KiB page).
"""
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

REC = np.dtype([("t", "<u8"), ("loc", "<u8"), ("ir", "<u4"), ("host", "<u4"), ("tr", "<u4"), ("opt", "<u4"),
                ("emit", "<u4"), ("core", "u1"), ("clear", "u1"), ("link_us", "<u2")])
PC_MASK = (1 << 56) - 1


def modules(log: Path):
    mods = []
    for m in re.finditer(r"Module (\S+) loaded at 0x([0-9a-f]+) \(size 0x([0-9a-f]+)\)", log.read_text(errors="replace")):
        mods.append((int(m[2], 16), int(m[2], 16) + int(m[3], 16), m[1]))
    return mods


def main():
    rd = Path(sys.argv[1])
    raw = (rd / "jit.bin").read_bytes()
    r = np.frombuffer(raw[: len(raw) // REC.itemsize * REC.itemsize], dtype=REC)
    if len(r) == 0:
        sys.exit("no records")
    t0 = int(r["t"].min())
    sec = (r["t"] - t0) / 1e9
    pc = r["loc"] & PC_MASK
    link = r["link_us"].astype(np.float64) * 1e3
    phases = {"translate (guest -> IR)": r["tr"], "optimise (IR passes)": r["opt"], "emit (IR -> Mac code)": r["emit"],
              "link + icache": link}
    total = sum(float(v.sum()) for v in phases.values())
    print(f"{len(r):,} blocks over {sec.max():.1f} s, {total / 1e9:.2f} s of compile time (sum over cores)")
    for k, v in phases.items():
        print(f"  {k:24s} {float(v.sum()) / 1e9:7.2f} s  {100 * float(v.sum()) / total:5.1f}%  "
              f"median {np.median(v) / 1e3:6.1f} us")
    print(f"  IR ops/block median {int(np.median(r['ir']))}, host bytes total {int(r['host'].sum()) / 2**20:.0f} MiB, "
          f"full flushes {int(r['clear'].sum())}")

    per_blk = r["tr"].astype(np.float64) + r["opt"] + r["emit"] + link
    print("\nper core: blocks, compile s, unique PCs")
    for c in sorted(set(r["core"].tolist())):
        m = r["core"] == c
        print(f"  core {c:3d}: {int(m.sum()):8,}  {per_blk[m].sum() / 1e9:6.2f} s  {len(np.unique(pc[m])):8,}")

    # Repeats: the first compile of a location anywhere is "needed"; every later one (another core, or again after a
    # flush on the same core) is a repeat that a shared or persistent cache would have saved.
    seen = set()
    first = np.zeros(len(r), bool)
    for i in np.argsort(r["t"], kind="stable"):
        key = int(r["loc"][i])
        if key not in seen:
            seen.add(key)
            first[i] = True
    print(f"\nunique locations {len(seen):,}; repeats {int((~first).sum()):,} blocks = "
          f"{per_blk[~first].sum() / 1e9:.2f} s of {per_blk.sum() / 1e9:.2f} s "
          f"({100 * per_blk[~first].sum() / per_blk.sum():.0f}%)")
    ncores = Counter(len(v) for v in _cores_per_loc(r).values())
    print("  locations compiled on N cores: " + ", ".join(f"{n}: {c:,}" for n, c in sorted(ncores.items())))

    print("\nper second: blocks / compile ms, by core")
    cores = sorted(set(r["core"].tolist()))
    print("   s  " + "".join(f"{'core ' + str(c):>16s}" for c in cores) + "     new-locations")
    b = sec.astype(int)
    for s in range(int(b.max()) + 1):
        m = b == s
        if not m.any():
            continue
        cells = "".join(f"{int((m & (r['core'] == c)).sum()):7d} /{per_blk[m & (r['core'] == c)].sum() / 1e6:6.0f}ms"
                        for c in cores)
        print(f"{s:4d}  {cells}   {int((m & first).sum()):7d}")

    phases_report(rd, r, per_blk, first)

    log = rd / "eden_log.txt"
    mods = modules(log) if log.exists() else []
    if mods:
        where = defaultdict(lambda: [0, 0.0])
        pages = defaultdict(float)
        for p, cost in zip(pc.tolist(), per_blk.tolist()):
            name = next((f"{n}" for lo, hi, n in mods if lo <= p < hi), "other")
            base = next((lo for lo, hi, n in mods if lo <= p < hi), 0)
            where[name][0] += 1
            where[name][1] += cost
            pages[(name, (p - base) & ~0xFFF)] += cost
        print("\nby module: blocks, compile s")
        for n, (cnt, cost) in sorted(where.items(), key=lambda kv: -kv[1][1]):
            print(f"  {n:10s} {cnt:8,}  {cost / 1e9:6.2f} s")
        print("\ntop 15 code pages (module + offset) by compile time")
        for (n, off), cost in sorted(pages.items(), key=lambda kv: -kv[1])[:15]:
            print(f"  {n}+0x{off:x}  {cost / 1e6:7.1f} ms")


def step_times(rd):
    """The harness's steps on CLOCK_MONOTONIC_RAW (the JIT log's clock: libc++'s steady_clock): from result.json's
    t_monotonic, or for runs before it existed, rebuilt from frames.bin (CLOCK_UPTIME_RAW; boot ends at present 300,
    phases at their marked presents) and the menu trace (seconds after the boot ended), shifted by today's
    difference between the two clocks (right unless the Mac slept since the run)."""
    import json
    import time
    res = json.loads((rd / "result.json").read_text())
    if res.get("t_monotonic"):
        return dict(res["t_monotonic"]), "recorded"
    t, how = _rebuilt_uptime(rd, res)
    off = time.clock_gettime_ns(time.CLOCK_MONOTONIC_RAW) - time.clock_gettime_ns(time.CLOCK_UPTIME_RAW)
    return {k: v + off for k, v in t.items()}, how


def _rebuilt_uptime(rd, res):
    fr = np.fromfile(rd / "frames.bin", dtype="<u8")
    if len(fr) < 300:
        return {}, "none"
    t = {"boot_done": int(fr[299])}
    for when, what in res.get("menu_trace", []):
        key = {"loading": "loading", "in game": "in_game"}.get(what)
        if key and key not in t:
            t[key] = int(fr[299] + when * 1e9)
    for name, idx in res.get("marks", {}).items():
        if idx < len(fr):
            t[name] = int(fr[idx])
    return t, "rebuilt from frames.bin and the menu trace (about +-0.5 s)"


def phases_report(rd, r, per_blk, first):
    try:
        t, how = step_times(rd)
    except (OSError, ValueError):
        return
    if not t:
        return
    steps = sorted(t.items(), key=lambda kv: kv[1])
    edges = [("(JIT starts)", int(r["t"].min()))] + steps + [("(log ends)", int(r["t"].max()) + 1)]
    cores = sorted(set(r["core"].tolist()))
    print(f"\nby harness step ({how}): wall s, blocks, compile s summed, busiest core's compile s and share of the "
          f"wall time, new locations")
    for (a, ta), (b, tb) in zip(edges, edges[1:]):
        if tb <= ta:
            continue
        m = (r["t"] >= ta) & (r["t"] < tb)
        wall = (tb - ta) / 1e9
        per_core = [per_blk[m & (r["core"] == c)].sum() / 1e9 for c in cores]
        busiest = max(per_core) if per_core else 0.0
        print(f"  {a:>13s} -> {b:<13s} {wall:6.1f} s  {int(m.sum()):9,}  {per_blk[m].sum() / 1e9:6.2f} s  "
              f"{busiest:5.2f} s ({100 * busiest / wall:3.0f}%)  {int((m & first).sum()):8,}")


def _cores_per_loc(r):
    d = defaultdict(set)
    for loc, c in zip(r["loc"].tolist(), r["core"].tolist()):
        d[loc].add(c)
    return d


if __name__ == "__main__":
    main()
