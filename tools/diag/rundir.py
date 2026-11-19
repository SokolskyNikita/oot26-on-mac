#!/usr/bin/env python3
"""Shared loader for the readers in tools/diag: harness run folders (tools/harness/runs/ab-…/LABEL), standard
library only. `python3 rundir.py RUN…` prints each run's phases, clock and frame statistics.

A run folder holds result.json (ab.py), frames.bin (the verify hook: one little-endian u64 of CLOCK_UPTIME_RAW ns
per presented frame), eden_log.txt, and what the run's switches wrote under fixed names ({rd}/frameprof.txt,
{rd}/sync.txt, {rd}/jit-trace.bin, {rd}/jit.bin). A batch folder (ab-…/) stands for all its run folders. A run with
"variants" becomes one Run per variant, labelled LABEL/VARIANT.

Clocks (README.md, "Clocks"):
  log time    eden_log.txt's "[   s.us]": steady_clock seconds since Lichii's logger started
  monotonic   CLOCK_MONOTONIC_RAW (libc++'s steady_clock on macOS): result.json t_monotonic, Nx2Boot mono_s
  uptime      CLOCK_UPTIME_RAW (mach_absolute_time): frames.bin, P60_SYNC_TRACE, MVK_FRAMEPROF, result.json t_uptime
The two kernel clocks differ by the time the Mac has slept since it booted, so they are never compared directly:
result.json records every harness step on both, and their difference converts one to the other. Log time maps to
monotonic through the stutter trace's Nx2Boot line (log time and mono_s of one instant). Without that line it falls
back to t_monotonic["start"] = log time 0, about 0.25 s off (Lichii starts its logger after the harness's mark);
Run.clock_note says which was used and readers print it.
"""
import json
import re
import statistics
import struct
import sys
from pathlib import Path

DEFAULT_BANDS = (20.0, 22.0, 26.0, 33.0)     # band edges in ms: <20, 20-22, 22-26, 26-33, >=33
PHASE_ORDER = ("stand1", "walk", "stand2", "end")
BOOT_LINE = re.compile(r"\[\s*([\d.]+)\].*Nx2Boot event=\w+ mono_s=([\d.]+)")
STALL_STEP_M = 0.3          # a chunk that moved Link less than this did not move him
STALL_CHUNKS = 2            # more such chunks in a row than this: he stood still


class NotAHarnessRun(SystemExit):
    pass


def quantile(sorted_values, f):
    """The harness's percentile (ab.py stats): the value at index int(f * n) of the sorted list."""
    if not sorted_values:
        return float("nan")
    return sorted_values[min(len(sorted_values) - 1, int(f * len(sorted_values)))]


def stats(ms):
    """frames / mean / p50 / p90 / p95 / p99 / max of frame times in ms, as ab.py computes them."""
    s = sorted(ms)
    if not s:
        return {}
    return {"frames": len(s), "mean": statistics.fmean(s), "p50": quantile(s, .5), "p90": quantile(s, .9),
            "p95": quantile(s, .95), "p99": quantile(s, .99), "max": s[-1]}


def parse_bands(text):
    """'20,22,26,33' -> (20.0, 22.0, 26.0, 33.0)."""
    edges = tuple(float(x) for x in str(text).split(",") if x.strip())
    if list(edges) != sorted(edges):
        raise SystemExit(f"--bands {text}: edges must be increasing")
    return edges


def band_ranges(edges=DEFAULT_BANDS):
    """[(lo, hi)]: the first from 0, the last open (hi = inf)."""
    return list(zip((0.0,) + tuple(edges), tuple(edges) + (float("inf"),)))


def band_name(lo, hi):
    if lo == 0:
        return f"<{hi:g}"
    if hi == float("inf"):
        return f">={lo:g}"
    return f"{lo:g}-{hi:g}"


def base_label(label):
    """A repeat's label without its -rN (ab.py appends it when "repeat" > 1)."""
    return re.sub(r"-r\d+$", "", label)


class Run:
    """One measured pass of a harness run folder: the whole run, or one of its variants (prefix "VARIANT/")."""

    def __init__(self, path, res, prefix="", log_clock="auto"):
        self.path = Path(path)
        self.res = res
        self.prefix = prefix
        name = res.get("label", self.path.name)
        tail = f"/{prefix.rstrip('/')}" if prefix else ""
        self.label = name + tail
        self.base = base_label(name) + tail
        self.spec = res.get("spec") or {}
        self.env = {k: str(v) for k, v in (self.spec.get("env") or {}).items()}

        def own(d):          # this pass's keys, prefix removed
            d = d or {}
            if prefix:
                return {k[len(prefix):]: v for k, v in d.items() if k.startswith(prefix)}
            return {k: v for k, v in d.items() if "/" not in k}

        def common(d):       # steps before the measuring (start, boot_done, load_done, settled): no prefix
            return {k: v for k, v in (d or {}).items() if "/" not in k}

        self.marks = own(res.get("marks"))
        self.t_uptime = dict(common(res.get("t_uptime")), **own(res.get("t_uptime")))
        self.t_monotonic = dict(common(res.get("t_monotonic")), **own(res.get("t_monotonic")))
        self.walk_call = res.get(prefix + "walk_call") or {}
        self.log_clock = log_clock
        self._frames = None
        self._log = None
        self._clock = None

    # ---- files -----------------------------------------------------------------------------------------------
    def file(self, name):
        return self.path / name

    @property
    def frames(self):
        """frames.bin: CLOCK_UPTIME_RAW ns of every presented frame (a list of int)."""
        if self._frames is None:
            f = self.file("frames.bin")
            raw = f.read_bytes() if f.exists() else b""
            n = len(raw) // 8
            self._frames = list(struct.unpack(f"<{n}Q", raw[:n * 8]))
        return self._frames

    def log_text(self):
        if self._log is None:
            f = self.file("eden_log.txt")
            self._log = f.read_text(errors="replace") if f.exists() else ""
        return self._log

    def log_lines(self):
        return self.log_text().splitlines()

    # ---- phases ----------------------------------------------------------------------------------------------
    def phases(self):
        """[(name, start mark, end mark)] of the measured phases in order: result.json "phases" (ab.py writes it),
        else the marks present in PHASE_ORDER."""
        out = []
        listed = self.res.get("phases")
        if listed:
            for a, b in listed:
                if self.prefix:
                    if not a.startswith(self.prefix):
                        continue
                    a, b = a[len(self.prefix):], b[len(self.prefix):]
                elif "/" in a:
                    continue
                if a in self.marks and b in self.marks:
                    out.append((a, a, b))
        else:
            names = [n for n in PHASE_ORDER if n in self.marks]
            out = [(a, a, b) for a, b in zip(names, names[1:])]
        return out

    def phase_names(self):
        return [p for p, _, _ in self.phases()]

    def phase_bounds(self, phase):
        """(first, last) indices into frames.bin: the phase's frames are the intervals frames[first..last] (ab.py's
        ts[m[a]:m[b] + 1]), last clamped to what frames.bin holds."""
        for p, a, b in self.phases():
            if p == phase:
                n = len(self.frames)
                if n == 0:
                    return None
                return min(self.marks[a], n - 1), min(self.marks[b], n - 1)
        return None

    def phase_ms(self, phase):
        """Frame times (ms) of the phase: the intervals between its consecutive presents."""
        b = self.phase_bounds(phase)
        if not b:
            return []
        fr = self.frames
        return [(fr[i + 1] - fr[i]) / 1e6 for i in range(b[0], b[1])]

    def phase_present_ns(self, phase):
        """Uptime ns of the presents that bound the phase's frames (one more than phase_ms)."""
        b = self.phase_bounds(phase)
        return self.frames[b[0]:b[1] + 1] if b else []

    def require_phase(self, phase):
        if phase not in self.phase_names():
            raise SystemExit(f"{self.label}: no phase {phase!r} (phases: {', '.join(self.phase_names()) or 'none'})")

    # ---- clocks ----------------------------------------------------------------------------------------------
    def _clocks(self):
        if self._clock is None:
            mono_minus_up = None
            both = [k for k in self.t_uptime if k in self.t_monotonic]
            if both:
                diffs = sorted(self.t_monotonic[k] - self.t_uptime[k] for k in both)
                mono_minus_up = diffs[len(diffs) // 2] / 1e9
            boot = BOOT_LINE.search(self.log_text()) if self.log_clock == "auto" else None
            if boot:
                log_to_mono = float(boot[2]) - float(boot[1])
                note = "log time placed by the Nx2Boot line"
            elif "start" in self.t_monotonic:
                log_to_mono = self.t_monotonic["start"] / 1e9
                why = "--log-clock start" if self.log_clock == "start" else "no Nx2Boot line (stutter trace off)"
                note = f"log time placed by t_monotonic['start'] = log time 0 ({why}): about 0.25 s off"
            else:
                log_to_mono = None
                note = "no t_monotonic in result.json: log lines cannot be placed in phases"
            self._clock = (log_to_mono, mono_minus_up, note)
        return self._clock

    @property
    def clock_note(self):
        return self._clocks()[2]

    def log_to_mono(self, t_log):
        off = self._clocks()[0]
        return None if off is None else t_log + off

    def mono_to_log(self, t_mono_s):
        off = self._clocks()[0]
        return None if off is None else t_mono_s - off

    def log_to_uptime(self, t_log):
        """Log seconds -> CLOCK_UPTIME_RAW seconds (frames.bin's clock)."""
        lm, mu, _ = self._clocks()
        if lm is None or mu is None:
            return None
        return t_log + lm - mu

    def uptime_to_log(self, t_up_s):
        lm, mu, _ = self._clocks()
        if lm is None or mu is None:
            return None
        return t_up_s + mu - lm

    def step_log_time(self, step):
        """A harness step (start, boot_done, load_done, settled, walk, stand2, end, …) in log seconds."""
        if step not in self.t_monotonic:
            return None
        return self.mono_to_log(self.t_monotonic[step] / 1e9)

    def phase_log_window(self, phase):
        """(start, end) of the phase in log seconds, from t_monotonic."""
        for p, a, b in self.phases():
            if p == phase:
                s, e = self.step_log_time(a), self.step_log_time(b)
                if s is not None and e is not None:
                    return s, e
        return None

    def phase_of_log_time(self, t_log, names=None):
        """The phase a log time falls in (by t_monotonic), or None."""
        for p in names or self.phase_names():
            w = self.phase_log_window(p)
            if w and w[0] <= t_log < w[1]:
                return p
        return None

    # ---- checks ----------------------------------------------------------------------------------------------
    def walk_stalls(self):
        """(suspect, text). A bounce walk stood still when more than STALL_CHUNKS points of walk_call.path in a row
        are under STALL_STEP_M apart. A walk that gets 14 m from the Kokiri spawn can walk Link into an NPC dialog
        near (-6.6, 110.2, -11.5); he then stands for the rest of the walk and its frame times measure nothing."""
        path = self.walk_call.get("path") or []
        if len(path) < 2:
            return False, "no walk path in result.json"
        run = best = best_at = 0
        for i, (a, b) in enumerate(zip(path, path[1:])):
            if sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5 < STALL_STEP_M:
                run += 1
                if run > best:
                    best, best_at = run, i - run + 1
            else:
                run = 0
        if best > STALL_CHUNKS:
            chunk = int(self.walk_call.get("chunk", 30))
            at = path[best_at]
            return True, (f"WARNING: the walk stood still for {best} chunks in a row from walk frame {best_at * chunk} "
                          f"(Link at {at[0]:.1f}, {at[1]:.1f}, {at[2]:.1f}): its frame times from there are not a walk")
        return False, "the walk moved"

    def warn_lines(self):
        """What a reader prints under the run's header: a walk that stood still, a log clock that is approximate."""
        out = []
        suspect, text = self.walk_stalls()
        if suspect:
            out.append(text)
        if "0.25 s off" in self.clock_note or "cannot" in self.clock_note:
            out.append("note: " + self.clock_note)
        return out


def _is_verify_run(path, res):
    return (path / "meta.json").exists() or ("lichii_600_present_windows" in res and "marks" not in res)


def load_run(path, log_clock="auto"):
    """The Runs of one harness run folder (one per variant)."""
    path = Path(path)
    res = json.loads((path / "result.json").read_text())
    if _is_verify_run(path, res):
        raise NotAHarnessRun(f"{path} is a tools/verify run folder (verify.py run: meta.json, marks loaded-standing, "
                             f"walk1, walk2), whose result.json has another schema. The readers in tools/diag take "
                             f"harness run folders (tools/harness/runs/ab-…/LABEL)")
    variants = (res.get("spec") or {}).get("variants")
    if variants:
        return [Run(path, res, prefix=v["label"] + "/", log_clock=log_clock) for v in variants
                if f"{v['label']}/walk" in (res.get("marks") or {})]
    return [Run(path, res, log_clock=log_clock)]


def load_runs(args, log_clock="auto", skip_warmup=True):
    """Runs from run folders and batch folders (a folder without result.json whose subfolders have one; its warm-up
    runs are left out unless skip_warmup is false). Order: as given, a batch's members by name."""
    runs = []
    for a in args:
        p = Path(a)
        if (p / "result.json").exists():
            runs += load_run(p, log_clock)
        elif p.is_dir():
            members = sorted(d for d in p.iterdir() if (d / "result.json").exists())
            if not members:
                raise SystemExit(f"{p}: no result.json in it or in its subfolders")
            runs += [r for d in members if not (skip_warmup and "warmup" in d.name) for r in load_run(d, log_clock)]
        else:
            raise SystemExit(f"{p}: not a run folder")
    return runs


def group_by_label(runs):
    """{label without -rN: [runs]} in first-seen order: the repeats of one spec entry pooled."""
    out = {}
    for r in runs:
        out.setdefault(r.base, []).append(r)
    return out


def view_and_rest(argv, views, default):
    """Split `READER.py [VIEW] ARGS…`: the first argument is a view when it names one."""
    if argv and argv[0] in views:
        return argv[0], argv[1:]
    return default, argv


def add_common(parser, phase_default=None):
    """Options every reader takes."""
    parser.add_argument("runs", nargs="+", help="harness run folders (runs/ab-…/LABEL) or batch folders (runs/ab-…)")
    parser.add_argument("--bands", default=",".join(f"{x:g}" for x in DEFAULT_BANDS),
                        help="frame-time band edges in ms (default %(default)s)")
    parser.add_argument("--log-clock", choices=("auto", "start"), default="auto",
                        help="auto: the Nx2Boot line when there is one; start: t_monotonic['start'] = log time 0")
    parser.add_argument("--with-warmup", action="store_true", help="keep the warm-up runs of a batch folder")
    if phase_default is not None:
        parser.add_argument("--phase", default=phase_default, help="harness phase (default %(default)s)")
    return parser


def runs_from(args):
    return load_runs(args.runs, log_clock=args.log_clock, skip_warmup=not args.with_warmup)


def header(run, extra=""):
    """A run's first line, then its warnings."""
    return "\n".join([f"== {run.label}{extra}"] + ["  " + w for w in run.warn_lines()])


if __name__ == "__main__":
    for r in load_runs(sys.argv[1:]):
        print(header(r))
        print(f"  phases {[p for p, _, _ in r.phases()]}, {len(r.frames)} presents; {r.clock_note}")
        for p in r.phase_names():
            s = stats(r.phase_ms(p))
            print(f"  {p:7s} " + "  ".join(f"{k} {v:.1f}" if isinstance(v, float) else f"{k} {v}" for k, v in s.items()))
