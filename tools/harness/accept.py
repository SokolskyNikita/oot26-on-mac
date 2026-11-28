#!/usr/bin/env python3
"""The frame-time acceptance rule for a change to the pinned build, applied to paired harness runs.

    python3 accept.py RUNS_DIR CONTROL_PREFIX CHANGE_PREFIX [--phase walk]

Runs are paired by the suffix after the prefix (route-off-1 with route-on-1). For p50, p95 and p99 of the phase, a
pair's ratio is (60 - fps of the control) / (60 - fps of the change): how much of the shortfall from 60 fps the
change closes; 1.1 means a tenth of it. The rule: the change is accepted when the one-sided 90 % lower confidence
bound of the ratio (Student t on the log ratios of the pairs) is above 1.1 for at least one of the three, the mean
ratio of none of the three is below 1.0, and the pictures are clean. A percentile whose control is within 2 fps of
60 is at the target and is not scored."""
import json, math, statistics, sys
from pathlib import Path

T90 = {1: 3.078, 2: 1.886, 3: 1.638, 4: 1.533, 5: 1.476, 6: 1.440, 7: 1.415, 8: 1.397, 9: 1.383, 10: 1.372,
       11: 1.363, 12: 1.356, 13: 1.350, 14: 1.345, 15: 1.341, 19: 1.328, 24: 1.318, 29: 1.311}


def t90(df):
    return T90[max(k for k in T90 if k <= df)] if df >= 1 else float("inf")


def main(argv):
    phase = argv[argv.index("--phase") + 1] if "--phase" in argv else "walk"
    runs, off, on = Path(argv[0]), argv[1], argv[2]
    res = {p.parent.name: json.loads(p.read_text()) for p in runs.glob("*/result.json")}
    pairs = sorted((n[len(off):], n, on + n[len(off):]) for n in res if n.startswith(off) and on + n[len(off):] in res)
    if not pairs:
        sys.exit(f"no pairs {off}* / {on}* in {runs}")
    corrupt = [n for _, a, b in pairs for n in (a, b) if (res[n].get("picture") or {}).get("corrupt")]
    verdicts = {}
    print(f"{len(pairs)} pairs, phase {phase!r}; shortfall = 60 - 1000 / frame time")
    for q in ("p50", "p95", "p99"):
        a = [res[x][phase][q] for _, x, _ in pairs]; b = [res[y][phase][q] for _, _, y in pairs]
        short = lambda ms: 60 - 1000 / ms
        line = f"{q}: control {' '.join(f'{v:.2f}' for v in a)} ms | change {' '.join(f'{v:.2f}' for v in b)} ms"
        if statistics.mean(short(v) for v in a) < 2 or min(short(v) for v in a + b) <= 0:
            print(line + " | at the 60 fps target, not scored"); verdicts[q] = None; continue
        logs = [math.log(short(x) / short(y)) for x, y in zip(a, b)]
        mean = statistics.mean(logs); n = len(logs)
        se = statistics.stdev(logs) / math.sqrt(n) if n > 1 else float("inf")
        low = math.exp(mean - t90(n - 1) * se)
        verdicts[q] = (math.exp(mean), low)
        print(line + f" | ratio {math.exp(mean):.3f}, 90 % lower bound {low:.3f}")
    scored = {q: v for q, v in verdicts.items() if v}
    passed = [q for q, (m, low) in scored.items() if low > 1.1]
    worse = [q for q, (m, low) in scored.items() if m < 1.0]
    ok = bool(passed) and not worse and not corrupt
    print(f"clears 1.1: {passed or 'none'}; mean below 1.0: {worse or 'none'}; corrupt pictures: {corrupt or 'none'}")
    print("ACCEPTED" if ok else "NOT ACCEPTED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
