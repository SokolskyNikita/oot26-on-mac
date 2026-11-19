#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "pillow"]
# ///
"""Verify a rendering change in Lichii: frame times, Metal/MoltenVK errors, and the picture against a reference run.

    ./verify.py run APP LABEL [ENV=VALUE ...] [--out DIR] [--lock-wait SECONDS]
    ./verify.py compare REF_RUN CAND_RUN [--tile T] [--frac F]
    ./verify.py analyze RUN                         # redo result.json from a run's files
    ./verify.py with-lock [--lock-wait S] -- CMD... # run any command (e.g. measure.sh) holding the emulator lock
    ./verify.py lock-status
    ./verify.py build-hook                          # build the frame hook (also done by run, and by the harness)

APP is a .app bundle (e.g. /Applications/lichii.app or build/app/lichii.app). See README.md.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import signal
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
LOG = Path.home() / ".local/share/lichii/log/eden_log.txt"
CONFIG = Path.home() / ".config/lichii/qt-config.ini"
CACHE = Path.home() / ".cache/lichii/shader"
LOCK = Path.home() / ".local/share/lichii/verify.lock"
PAD = ("127.0.0.1", 26761)                    # dsu_server.py control socket
PAD_SERVER = REPO / "tools/pad/dsu_server.py"  # the virtual controller Lichii's player 1 is bound to
HOOK_PORT = 26799
LOAD_WARN = 8.0                                # 1-minute load average above which a run warns (14 cores here)
HOOK_SRC, HOOK_LIB = HERE / "hook.m", HERE / "build/libverifyhook.dylib"

def find_game(repo):
    """Your own dump of the game: $OOT26_DUMP (a .nup file), else *0400486024DEC000*.nup in <repo>/dump or in dump/
    beside the repository (where it sits when this repository is nested in the glitch-research one)."""
    if os.environ.get("OOT26_DUMP"):
        return Path(os.environ["OOT26_DUMP"])
    for d in (repo / "dump", repo.parent / "dump"):
        hit = sorted(d.glob("*0400486024DEC000*.nup"))
        if hit:
            return hit[0]
    return None


GAME = find_game(REPO)

# ---------------------------------------------------------------------------------------------------------------
# The route, in game frames (the hook counts presented frames; the game steps a fixed 1/60 s per frame).
# Same shape as measure.sh's walk, with its seconds turned into frames at ~30 fps (its pace on these builds), and
# still moments (sticks centred, 15 frames to settle) where the screenshots are taken.
STAND_FRAMES = 1050                            # measure.sh stands 35 s
SPAWN_SHOTS = [("spawn-a", 90), ("spawn-b", 990)]  # frames into the standing phase
WALK = [
    ("ls", 0, 1, 120), ("ls", 1, 0, 90), ("rs", 1, 0, 45), ("shot", "r1"),
    ("ls", 0, 1, 120), ("ls", -1, 0, 90), ("rs", -1, 0, 45), ("shot", "r2"),
    ("ls", 0, -1, 120), ("ls", 1, 1, 90), ("rs", 1, 0, 60), ("shot", "r3"),
    ("ls", -1, -1, 90), ("wait", 30),
]
SETTLE = 15
SPAWN_SETTLE = 120                             # frames from the spawn panel appearing to the standing phase

# Picture check. The game area is the 16:9 band under the title bar (28 pt on build 228, 32 on the nx2 builds),
# found by game_top(); a status bar sits below it.
WATCH_BOX = (0, 495, 300, 720)                 # sloperinaGZ "watches" panel, game-area px (x0, y0, x1, y1)
WATCH_VALUES = (150, 540, 270, 610)            # its x / y / z numbers
SPAWN_TEMPLATE = HERE / "spawn-watch.png"      # WATCH_VALUES at the top save's spawn (x -17.30, y 109.95, z -1.84)
SPAWN_MATCH = 4.0                              # mean diff; spawn vs spawn 0.0, menus 18.4, another spot 12.2
TILE_PX = 40                                   # 40x40 game px tiles: a 32x18 grid on 1280x720
TILE_THRESHOLD = 20.0                          # tile mean colour moved by more than this (0-255) = changed
FRAC_THRESHOLD = 0.10                          # fail a shot when more than this share of tiles changed


# --------------------------------------------------------------------------------------------------------- lock
def pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def lichii_pids():
    """Every running Lichii (any copy). Matches the process name, so shells mentioning lichii don't count."""
    out = subprocess.run(["pgrep", "-x", "lichii"], capture_output=True, text=True).stdout.split()
    return [int(p) for p in out]


def lock_owner():
    try:
        return json.loads((LOCK / "owner.json").read_text())
    except (OSError, ValueError):
        return None


def take_lock(label, app, wait_s):
    """mkdir is atomic: whoever creates LOCK owns the emulator. Waits up to wait_s for the lock and for any Lichii
    this tool did not start to go away; never kills one."""
    deadline = time.time() + wait_s
    said = None
    while True:
        try:
            LOCK.mkdir()
        except FileExistsError:
            owner = lock_owner()
            if owner is None:
                # Created but owner not written yet, or a crash between the two: stale after 60 s.
                age = time.time() - LOCK.stat().st_mtime if LOCK.exists() else 0
                if age > 60:
                    print(f"lock: removing stale lock with no owner ({age:.0f} s old)")
                    shutil.rmtree(LOCK, ignore_errors=True)
                    continue
                why = "lock being taken by someone"
            elif not pid_alive(owner["pid"]):
                print(f"lock: removing stale lock of dead pid {owner['pid']} ({owner.get('label')})")
                shutil.rmtree(LOCK, ignore_errors=True)
                continue
            else:
                why = f"lock held by pid {owner['pid']} ({owner.get('label')}, since {owner.get('started')})"
        else:
            (LOCK / "owner.json").write_text(json.dumps({
                "pid": os.getpid(), "label": label, "app": str(app),
                "started": dt.datetime.now().isoformat(timespec="seconds"), "lichii_pid": None}))
            foreign = lichii_pids()
            if not foreign:
                return
            release_lock()
            why = f"a Lichii this tool did not start is running (pid {', '.join(map(str, foreign))})"
        if time.time() > deadline:
            raise SystemExit(f"lock: gave up after {wait_s} s: {why}")
        if why != said:
            print(f"lock: waiting ({why})", flush=True)
            said = why
        time.sleep(10)


def release_lock():
    owner = lock_owner()
    if owner is None or owner["pid"] == os.getpid():
        shutil.rmtree(LOCK, ignore_errors=True)


def set_lock_lichii(pid):
    owner = lock_owner()
    owner["lichii_pid"] = pid
    (LOCK / "owner.json").write_text(json.dumps(owner))


# ---------------------------------------------------------------------------------------------------- controls
class Udp:
    def __init__(self, addr, timeout=2.0):
        self.addr = addr
        self.s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.s.settimeout(timeout)

    def ask(self, text, timeout=None):
        if timeout:
            self.s.settimeout(timeout)
        self.s.sendto(text.encode(), self.addr)
        return self.s.recvfrom(4096)[0].decode()


class Driver:
    """Frame-scheduled inputs: each step starts when the hook's frame count reaches its target frame."""

    def __init__(self, run_dir):
        self.pad, self.hook = Udp(PAD), Udp(("127.0.0.1", HOOK_PORT))
        self.run_dir = run_dir
        self.target = None
        self.marks, self.shots = [], {}
        self.dark = False

    def count(self):
        return int(self.hook.ask("count"))

    def press(self, text):
        if self.pad.ask(text) != "ok":
            raise RuntimeError(f"pad refused {text!r}")

    def sync(self):
        self.target = self.count()

    def until(self, frames):
        """Advance the schedule by `frames` and sleep until the game has presented that many."""
        self.target += frames
        while (n := self.count()) < self.target:
            time.sleep(0.002 if self.target - n < 3 else 0.01)

    def mark(self, name):
        self.marks.append({"name": name, "frame": self.target if self.target is not None else self.count(),
                           "uptime_ns": time.clock_gettime_ns(time.CLOCK_UPTIME_RAW),
                           "log_time": last_log_time()})
        print(f"mark {name} frame {self.marks[-1]['frame']} log {self.marks[-1]['log_time']}", flush=True)

    def shot(self, name):
        (self.run_dir / "shots").mkdir(exist_ok=True)
        path = self.run_dir / "shots" / f"{name}.png"
        reply = self.hook.ask(f"shot {path}", timeout=10)
        self.hook.s.settimeout(2.0)
        self.shots[name] = {"wanted_frame": self.target, "reply": reply}
        print(f"shot {name}: {reply}", flush=True)

    def tap(self, button, frames=4):
        """Hold a button for whole game frames (a 120 ms wall-clock tap is lost when a frame takes longer)."""
        self.press(f"press {button}")
        self.wait_frames(frames)
        self.press(f"release {button}")
        self.wait_frames(frames)

    def wait_frames(self, n, limit_s=10):
        start, t0 = self.count(), time.time()
        while self.count() < start + n and time.time() - t0 < limit_s:
            time.sleep(0.005)

    def at_spawn(self):
        """True when the watches panel shows the spawn position (see SPAWN_TEMPLATE)."""
        path = self.run_dir / "shots" / "_poll.png"
        (self.run_dir / "shots").mkdir(exist_ok=True)
        if not self.hook.ask(f"shot {path}", timeout=10).startswith("ok"):
            return None
        x0, y0, x1, y1 = WATCH_VALUES
        area = game_area(path)
        self.dark = float(area[:400].mean()) < 8      # loading screen: black above the panel
        tpl = np.asarray(Image.open(SPAWN_TEMPLATE).convert("RGB"), dtype=np.float32)
        return float(np.abs(area[y0:y1, x0:x1] - tpl).max(axis=2).mean())

    def walk(self, tag):
        for step in WALK:
            if step[0] in ("ls", "rs"):
                kind, x, y, frames = step
                self.press(f"stick {kind} {x} {y}")
                self.until(frames)
                self.press(f"stick {kind} 0 0")
            elif step[0] == "wait":
                self.until(step[1])
            elif step[0] == "shot":
                self.until(SETTLE)
                self.shot(f"{tag}-{step[1]}")


def last_log_time():
    try:
        with open(LOG, "rb") as f:
            f.seek(max(0, os.path.getsize(LOG) - 4096))
            lines = f.read().decode(errors="replace").splitlines()
        for line in reversed(lines):
            m = re.match(r"^\[\s*([0-9.]+)\]", line)
            if m:
                return float(m.group(1))
    except OSError:
        pass
    return None


def load_top_save(d, alive):
    """measure.sh's menu presses (title, menu, Load, slot 1), then wait for Link at the spawn point, pressing A
    again if a press was lost. Returns the frame count at which the spawn panel was first seen, or None."""
    time.sleep(14)
    for gap in (3, 3, 2.5, 0):
        d.tap("a")
        time.sleep(gap)
    extra = 0
    t_press = time.time()
    while alive():
        diff = d.at_spawn()
        if diff is not None and diff < SPAWN_MATCH:
            (d.run_dir / "shots" / "_poll.png").unlink(missing_ok=True)
            print(f"at spawn (panel diff {diff:.1f}) after {extra} extra A presses", flush=True)
            return d.count(), extra
        if d.dark and time.time() - t_press < 300:
            time.sleep(0.2)
            continue                              # still loading: an A press would not help
        if time.time() - t_press > 60:
            if extra == 3:
                return None, extra
            extra += 1
            print(f"not at spawn after 60 s (panel diff {diff}); pressing A again", flush=True)
            d.tap("a")
            t_press = time.time()
        time.sleep(0.2)
    return None, extra


def file_state(paths):
    out = {}
    for p in paths:
        if p.is_file():
            h = hashlib.sha1()
            with open(p, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 22), b""):
                    h.update(chunk)
            out[str(p)] = {"size": p.stat().st_size, "mtime": p.stat().st_mtime, "sha1": h.hexdigest()}
    return out


def cache_files():
    return sorted(p for p in CACHE.rglob("*") if p.is_file()) if CACHE.exists() else []


def pad_answers():
    try:
        Udp(PAD, 1.0).ask("state")
        return True
    except OSError:
        return False


def start_pad():
    """The virtual controller (../pad/dsu_server.py). One already answering on the control port is used as it is
    and left running; otherwise one is started here and returned, to be stopped when the run ends."""
    if pad_answers():
        return None
    proc = subprocess.Popen([sys.executable, str(PAD_SERVER)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            start_new_session=True)
    for _ in range(50):
        if pad_answers():
            print(f"started the virtual pad ({PAD_SERVER.name}, pid {proc.pid})", flush=True)
            return proc
        if proc.poll() is not None:
            break
        time.sleep(0.1)
    proc.kill()
    raise SystemExit(f"could not start the virtual pad {PAD_SERVER} (is 127.0.0.1:26760 or :26761 taken?)")


def build_hook():
    if not HOOK_LIB.exists() or HOOK_LIB.stat().st_mtime < HOOK_SRC.stat().st_mtime:
        HOOK_LIB.parent.mkdir(exist_ok=True)
        subprocess.run(["clang", "-dynamiclib", "-fobjc-arc", "-O2", "-arch", "arm64", "-framework", "Cocoa",
                        "-framework", "QuartzCore", "-framework", "ImageIO", "-framework",
                        "UniformTypeIdentifiers", str(HOOK_SRC), "-o", str(HOOK_LIB)], check=True)


# --------------------------------------------------------------------------------------------------------- run
def cmd_run(a):
    app = Path(a.app).resolve()
    exe = app / "Contents/MacOS/lichii"
    if not exe.exists():
        raise SystemExit(f"no {exe}")
    env_pairs = [e for e in a.env if "=" in e]
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = Path(a.out).resolve() if a.out else HERE / "runs" / f"{a.label}-{stamp}"
    run_dir.mkdir(parents=True, exist_ok=False)
    build_hook()

    load1 = os.getloadavg()[0]
    if a.max_load and load1 > a.max_load:
        raise SystemExit(f"load average {load1:.1f} > --max-load {a.max_load}: frame times would be spoiled")
    if load1 > LOAD_WARN:
        print(f"WARNING: load average {load1:.1f} (> {LOAD_WARN}): frame times will be noisy", flush=True)
    take_lock(a.label, app, a.lock_wait)
    proc = pad_proc = None
    meta = {"label": a.label, "app": str(app), "env": env_pairs, "started": stamp, "run_dir": str(run_dir)}

    def cleanup(*_):
        if proc and proc.poll() is None:
            os.kill(proc.pid, signal.SIGKILL)       # only the Lichii we started
            proc.wait()
        try:
            Udp(PAD, 1.0).ask("reset")
        except OSError:
            pass
        if pad_proc and pad_proc.poll() is None:  # only a server this run started
            pad_proc.kill()
            pad_proc.wait()
        release_lock()

    signal.signal(signal.SIGTERM, lambda *_: (cleanup(), sys.exit(143)))
    signal.signal(signal.SIGINT, lambda *_: (cleanup(), sys.exit(130)))
    try:
        meta["loadavg_before"] = os.getloadavg()
        meta["config_before"] = file_state([CONFIG])
        meta["app_files"] = file_state([exe, *sorted((app / "Contents/Frameworks").glob("libMoltenVK*"))])
        meta["cache_before"] = file_state(cache_files())
        pad_proc = start_pad()
        Udp(PAD).ask("reset")
        old = LOG.stat() if LOG.exists() else None
        env = dict(os.environ)
        env.update(dict(e.split("=", 1) for e in env_pairs))
        env.update({"MVK_CONFIG_LOG_LEVEL": env.get("MVK_CONFIG_LOG_LEVEL", "2"), "VERIFY_DIR": str(run_dir),
                    "VERIFY_PORT": str(HOOK_PORT), "DYLD_INSERT_LIBRARIES": str(HOOK_LIB)})
        meta["launch_uptime_ns"] = time.clock_gettime_ns(time.CLOCK_UPTIME_RAW)
        with open(run_dir / "stderr.log", "wb") as err:
            proc = subprocess.Popen([str(exe), str(GAME)], env=env, stdout=err, stderr=subprocess.STDOUT,
                                    start_new_session=True)
        set_lock_lichii(proc.pid)
        meta["lichii_pid"] = proc.pid
        print(f"launched {app.name} pid {proc.pid} -> {run_dir}", flush=True)
        meta["outcome"] = drive(proc, run_dir, old, meta)
    finally:
        time.sleep(1)
        cleanup()
        if LOG.exists():
            shutil.copy(LOG, run_dir / "eden_log.txt")
        meta["loadavg_after"] = os.getloadavg()
        meta["config_after"] = file_state([CONFIG])
        meta["cache_after"] = file_state(cache_files())
        (run_dir / "meta.json").write_text(json.dumps(meta, indent=1))
    result = analyze(run_dir)
    print_result(result)
    return 0 if meta.get("outcome") == "completed" else 1


def drive(proc, run_dir, old_log, meta):
    alive = lambda: proc.poll() is None
    # The new log: Lichii moves the old one to eden_log.txt.old.txt at start.
    t0 = time.time()
    while time.time() - t0 < 60:
        st = LOG.stat() if LOG.exists() else None
        if st and (old_log is None or st.st_ino != old_log.st_ino or st.st_size < old_log.st_size):
            break
        time.sleep(1)
    time.sleep(12)
    if not alive():
        return "exited during boot"
    t0 = time.time()
    while time.time() - t0 < 400 and alive():
        text = LOG.read_text(errors="replace") if LOG.exists() else ""
        if "boot load:" in text or "Background prebuild done" in text:
            break
        time.sleep(2)
    for line in LOG.read_text(errors="replace").splitlines():
        if "boot load:" in line or "Background prebuild done" in line:
            print(line[:200], flush=True)
    if not alive():
        return "exited during boot"
    d = Driver(run_dir)
    print("loading the top save", flush=True)
    seen, extra = load_top_save(d, alive)
    meta["extra_a_presses"] = extra
    if not alive():
        return "exited while loading"
    if seen is None:
        return "save did not load (spawn panel never seen)"
    d.target = seen
    d.mark("spawn-seen")
    d.until(SPAWN_SETTLE)
    d.mark("loaded-standing")
    done = 0
    for name, at in SPAWN_SHOTS:
        d.until(at - done)
        done = at
        d.shot(name)
    d.until(STAND_FRAMES - done)
    for tag in ("walk1", "walk2"):
        d.mark(tag)
        d.walk(tag)
        if not alive():
            return f"exited during {tag}"
    d.mark("end")
    meta["marks"], meta["shots"] = d.marks, d.shots
    time.sleep(11)                            # let the last 600-present window land in the log, as measure.sh
    return "completed" if alive() else "exited after the route"


# ----------------------------------------------------------------------------------------------------- analyze
ERROR_RULES = [
    # (category, regex on one error event)
    ("threadgroup_memory", r"Threadgroup memory size \(\d+\) exceeds the maximum threadgroup memory"),
    ("stage_resource_limit", r"wants to bind (buffer|sampler|texture) \d+ which goes above the limit"),
    ("sampler_array_limit", r"Texture arrays exceed descriptor limits"),   # Lichii refuses the pipeline (228)
    ("compute_buffer_index", r"'buffer' attribute parameter is out of bounds"),
    ("device_lost_or_crash", r"DEVICE_LOST|Cannot execute instruction|FastmemCallback|Failed to present"),
    ("draw_skipped", r"Draw skipped"),
    ("pipeline_failed", r"pipeline build failed|could not be compiled into pipeline|Shader library compile failed"
                        r"|pipeline compilation failed|Graphics pipeline [0-9a-f]{16}:|failed to compile"
                        r"|VK_ERROR_INITIALIZATION_FAILED"),
]
HASH = re.compile(r"\b((?:vs|ps|shader|pipeline)=0x[0-9a-f]+)|\b(?:0x)?([0-9a-f]{16})\b")


def error_events(run_dir):
    """MoltenVK errors from stderr (an event is an [mvk-error] line plus its continuation lines) and Lichii's
    <Error>/<Critical> lines plus the warnings the rules know about from eden_log.txt."""
    events = []
    err = run_dir / "stderr.log"
    if err.exists():
        cur = None
        for line in err.read_text(errors="replace").splitlines():
            if line.startswith("[mvk-error]"):
                cur = {"source": "mvk", "text": line}
                events.append(cur)
            elif cur is not None and not line.startswith("["):
                cur["text"] += "\n" + line
            else:
                cur = None
    log = run_dir / "eden_log.txt"
    if log.exists():
        for line in log.read_text(errors="replace").splitlines():
            body = re.sub(r"^\[\s*[0-9.]+\]\s*", "", line)
            if "<Error>" in body or "<Critical>" in body or any(re.search(r, body) for _, r in ERROR_RULES):
                events.append({"source": "lichii", "text": body})
    return events


def classify(events):
    cats = {c: {"count": 0, "hashes": {}, "example": None} for c, _ in ERROR_RULES}
    unknown = {}
    for ev in events:
        for cat, rx in ERROR_RULES:
            if re.search(rx, ev["text"]):
                c = cats[cat]
                c["count"] += 1
                c["example"] = c["example"] or ev["text"].splitlines()[0][:240]
                for h in ("".join(g) for g in HASH.findall(ev["text"])):
                    c["hashes"][h] = c["hashes"].get(h, 0) + 1
                break
        else:
            key = normalise(ev["text"].splitlines()[0])
            unknown[key] = unknown.get(key, 0) + 1
    for c in cats.values():
        c["hashes"] = dict(sorted(c["hashes"].items(), key=lambda kv: -kv[1])[:20])
    return cats, unknown


def normalise(line):
    """One key per kind of line: numbers and hex replaced, so the same message with other values merges."""
    line = re.sub(r"0x[0-9a-fA-F]+|\b[0-9a-f]{8,}\b", "#", line)
    return re.sub(r"\d+(\.\d+)?", "N", line)[:200]


def frame_times(run_dir, meta):
    raw = (run_dir / "frames.bin").read_bytes() if (run_dir / "frames.bin").exists() else b""
    t = np.frombuffer(raw[: len(raw) // 8 * 8], dtype=np.uint64).astype(np.int64)
    marks = {m["name"]: m["frame"] for m in meta.get("marks", [])}
    phases = {}
    order = ["loaded-standing", "walk1", "walk2", "end"]
    for a_, b_ in zip(order, order[1:]):
        if a_ in marks and b_ in marks and marks[b_] <= len(t):
            dts = np.diff(t[marks[a_]: marks[b_]]) / 1e6
            if len(dts):
                phases[a_.replace("loaded-", "")] = stats(dts)
    if "walk1" in marks and "end" in marks and marks["end"] <= len(t):
        phases["walks"] = stats(np.diff(t[marks["walk1"]: marks["end"]]) / 1e6)
    return {"frames_recorded": int(len(t)), "phases": phases}


def stats(ms):
    return {"frames": int(len(ms)), "mean_ms": round(float(ms.mean()), 2),
            "median_ms": round(float(np.median(ms)), 2), "p95_ms": round(float(np.percentile(ms, 95)), 2),
            "p99_ms": round(float(np.percentile(ms, 99)), 2), "max_ms": round(float(ms.max()), 1),
            "over_100ms": int((ms > 100).sum()), "seconds": round(float(ms.sum()) / 1000, 1)}


def lichii_windows(run_dir, meta):
    """Lichii's own 'last 600 presents' lines (what measure.sh prints), each tagged with the phase it ended in."""
    out = []
    log = run_dir / "eden_log.txt"
    if not log.exists():
        return out
    marks = [(m["name"], m["log_time"]) for m in meta.get("marks", []) if m.get("log_time") is not None]
    for line in log.read_text(errors="replace").splitlines():
        m = re.match(r"^\[\s*([0-9.]+)\].*last 600 presents: frame (\d+) us \(max (\d+), (\d+) over 100 ms", line)
        if m:
            t = float(m.group(1))
            phase = "boot/menus"
            for name, mt in marks:
                if t >= mt:
                    phase = name
            out.append({"log_time": t, "phase": phase, "frame_ms": int(m.group(2)) / 1000,
                        "max_ms": int(m.group(3)) / 1000, "over_100ms": int(m.group(4))})
    return out


def analyze(run_dir):
    run_dir = Path(run_dir)
    meta = json.loads((run_dir / "meta.json").read_text())
    cats, unknown = classify(error_events(run_dir))
    cache_changed = sorted(set(meta.get("cache_before", {})) ^ set(meta.get("cache_after", {}))) + sorted(
        p for p in meta.get("cache_before", {}) if p in meta.get("cache_after", {})
        and meta["cache_before"][p]["sha1"] != meta["cache_after"][p]["sha1"])
    result = {
        "label": meta["label"], "app": meta["app"], "env": meta["env"], "outcome": meta.get("outcome"),
        "frames": frame_times(run_dir, meta),
        "lichii_600_present_windows": lichii_windows(run_dir, meta),
        "errors": cats,
        "unrecognised_errors": dict(sorted(unknown.items(), key=lambda kv: -kv[1])),
        "shots": {k: v for k, v in meta.get("shots", {}).items()},
        "config_changed": [p for p, v in meta.get("config_before", {}).items()
                           if meta.get("config_after", {}).get(p, {}).get("sha1") != v["sha1"]],
        "load_average": [meta.get("loadavg_before"), meta.get("loadavg_after")],
        "shader_cache_changed": cache_changed,
        "boot": [l[:200] for l in (run_dir / "eden_log.txt").read_text(errors="replace").splitlines()
                 if "boot load:" in l] if (run_dir / "eden_log.txt").exists() else [],
    }
    (run_dir / "result.json").write_text(json.dumps(result, indent=1))
    return result


def print_result(r):
    print(f"\n== {r['label']}: {r['outcome']}  ({r['frames']['frames_recorded']} frames recorded)")
    print(f"{'phase':10} {'frames':>6} {'mean':>7} {'median':>7} {'p95':>7} {'p99':>7} {'max':>7} {'>100ms':>6}")
    for name, s in r["frames"]["phases"].items():
        print(f"{name:10} {s['frames']:6} {s['mean_ms']:7.2f} {s['median_ms']:7.2f} {s['p95_ms']:7.2f} "
              f"{s['p99_ms']:7.2f} {s['max_ms']:7.1f} {s['over_100ms']:6}")
    print("Lichii 600-present windows:")
    for w in r["lichii_600_present_windows"]:
        print(f"  {w['log_time']:8.1f} s  {w['phase']:16} frame {w['frame_ms']:6.2f} ms  max {w['max_ms']:7.1f}"
              f"  over100 {w['over_100ms']}")
    print("errors: " + ", ".join(f"{k} {v['count']}" for k, v in r["errors"].items()))
    for k, v in r["errors"].items():
        if v["hashes"]:
            print(f"  {k} hashes: {', '.join(v['hashes'])}")
    if r["unrecognised_errors"]:
        print("unrecognised error lines:")
        for k, n in list(r["unrecognised_errors"].items())[:15]:
            print(f"  {n:5} x {k[:160]}")
    print(f"config content changed: {bool(r['config_changed'])}; shader cache files changed: "
          f"{len(r['shader_cache_changed'])}; load average before/after: {r['load_average']}")


# ----------------------------------------------------------------------------------------------------- compare
def game_top(img):
    """Row where the 16:9 game area starts: the pair of strongest horizontal edges one game-height apart."""
    h = img.shape[1] * 9 // 16
    best = (-1.0, 28)
    for t in range(16, min(60, img.shape[0] - h)):
        e = np.abs(img[t] - img[t - 1]).mean() + np.abs(img[t + h] - img[t + h - 1]).mean()
        best = max(best, (e, t))
    return best[1]


def game_area(path):
    img = np.asarray(Image.open(path).convert("RGB"), dtype=np.float32)
    top = game_top(img)
    return img[top: top + img.shape[1] * 9 // 16]


def tile_means(area):
    gh, gw = area.shape[0] // TILE_PX, area.shape[1] // TILE_PX
    return area[: gh * TILE_PX, : gw * TILE_PX].reshape(gh, TILE_PX, gw, TILE_PX, 3).mean(axis=(1, 3))


def picture_diff(ref_png, cand_png, tile_t, frac_t, heat_png=None):
    """Tile mean colours: a tile is 'changed' when its average colour moved by more than tile_t (0-255, largest
    channel). Averages shrug off sub-pixel camera differences and moving leaves; a missing canopy, missing grass or
    a hole in the sky moves them a lot. Tiles under the watches panel are left out."""
    a, b = game_area(ref_png), game_area(cand_png)
    if a.shape != b.shape:
        return {"verdict": "FAIL", "why": f"size {a.shape} vs {b.shape}"}
    ta, tb = tile_means(a), tile_means(b)
    scores = np.abs(ta - tb).max(axis=2)
    keep = np.ones(scores.shape, bool)
    x0, y0, x1, y1 = WATCH_BOX
    keep[y0 // TILE_PX: -(-y1 // TILE_PX), x0 // TILE_PX: -(-x1 // TILE_PX)] = False
    bad = (scores > tile_t) & keep
    frac = float(bad.sum() / keep.sum())
    vx0, vy0, vx1, vy1 = WATCH_VALUES
    # The x / y / z numbers of the watches panel: ~0 when Link stands on the same spot in both shots.
    pos = float(np.abs(a[vy0:vy1, vx0:vx1] - b[vy0:vy1, vx0:vx1]).max(axis=2).mean())
    if heat_png:
        img = Image.fromarray(np.concatenate([a, b], axis=1).astype(np.uint8))
        px = np.asarray(img).copy()
        for i, j in zip(*np.nonzero(bad)):
            for off in (0, a.shape[1]):
                y, x = i * TILE_PX, j * TILE_PX + off
                px[y:y + TILE_PX, x:x + 2] = px[y:y + TILE_PX, x + TILE_PX - 2:x + TILE_PX] = (255, 0, 0)
                px[y:y + 2, x:x + TILE_PX] = px[y + TILE_PX - 2:y + TILE_PX, x:x + TILE_PX] = (255, 0, 0)
        Image.fromarray(px).resize((1280, 360), Image.BILINEAR).save(heat_png)
    return {"verdict": "FAIL" if frac > frac_t else "ok", "changed_tiles": f"{int(bad.sum())}/{int(keep.sum())}",
            "changed_frac": round(frac, 3), "worst_tile": round(float(scores[keep].max()), 1),
            "mean_tile_diff": round(float(scores[keep].mean()), 2), "position_panel_diff": round(pos, 2)}


def cmd_compare(a):
    ref, cand = Path(a.ref), Path(a.cand)
    rr = json.loads((ref / "result.json").read_text())
    cr = json.loads((cand / "result.json").read_text())
    worse = []
    print(f"reference {rr['label']} ({rr['outcome']})  vs  candidate {cr['label']} ({cr['outcome']})")
    for name, r in (("reference", rr), ("candidate", cr)):
        loads = [l[0] for l in r.get("load_average", []) if l]
        if loads and max(loads) > LOAD_WARN:
            print(f"WARNING: {name} ran at load average {max(loads):.1f}: frame-time differences are unreliable")
    if cr["outcome"] != "completed":
        worse.append(f"candidate {cr['outcome']}")
    print(f"\n{'ms a frame':12} {'ref med':>8} {'cand med':>8} {'ref p95':>8} {'cand p95':>8} {'ref p99':>8} "
          f"{'cand p99':>8} {'>100 r/c':>9}")
    for ph in ("standing", "walk1", "walk2", "walks"):
        r, c = rr["frames"]["phases"].get(ph), cr["frames"]["phases"].get(ph)
        if not r or not c:
            print(f"{ph:12} missing")
            continue
        print(f"{ph:12} {r['median_ms']:8.2f} {c['median_ms']:8.2f} {r['p95_ms']:8.2f} {c['p95_ms']:8.2f} "
              f"{r['p99_ms']:8.2f} {c['p99_ms']:8.2f} {r['over_100ms']:4}/{c['over_100ms']:<4}")
        if c["median_ms"] > r["median_ms"] * (1 + a.slower):
            worse.append(f"{ph} median {c['median_ms']} ms vs {r['median_ms']} ms (> +{a.slower:.0%})")
    print(f"\n{'errors':24} {'ref':>5} {'cand':>5}")
    for cat in rr["errors"]:
        r, c = rr["errors"][cat]["count"], cr["errors"][cat]["count"]
        new_hashes = sorted(set(cr["errors"][cat]["hashes"]) - set(rr["errors"][cat]["hashes"]))
        print(f"{cat:24} {r:5} {c:5}" + (f"   new hashes: {', '.join(new_hashes[:6])}" if new_hashes else ""))
        # draw_skipped counts draws made while an async pipeline was still compiling: it swings with timing.
        if (c > r * 1.5 + 10) if cat == "draw_skipped" else (c > r):
            worse.append(f"{cat} {r} -> {c}")
    new_unknown = {k: n for k, n in cr["unrecognised_errors"].items() if k not in rr["unrecognised_errors"]}
    print(f"{'unrecognised (kinds)':24} {len(rr['unrecognised_errors']):5} {len(cr['unrecognised_errors']):5}")
    for k, n in list(new_unknown.items())[:10]:
        print(f"   new: {n} x {k[:150]}")
    review = [f"{len(new_unknown)} kinds of unrecognised error line not in the reference"] if new_unknown else []
    print(f"\npicture (tile > {a.tile}, fail when > {a.frac:.0%} of tiles changed; heatmaps in {cand}/diff/)")
    print(f"{'shot':14} {'verdict':7} {'changed':>9} {'frac':>6} {'worst':>6} {'mean':>6} {'pos':>6}")
    (cand / "diff").mkdir(exist_ok=True)
    pictures = {}
    for png in sorted((ref / "shots").glob("*.png")):
        other = cand / "shots" / png.name
        if not other.exists():
            print(f"{png.stem:14} missing in candidate")
            worse.append(f"shot {png.stem} missing")
            continue
        d = picture_diff(png, other, a.tile, a.frac, cand / "diff" / f"{png.stem}-vs-{ref.name}.png")
        pictures[png.stem] = d
        print(f"{png.stem:14} {d['verdict']:7} {d.get('changed_tiles', ''):>9} {d.get('changed_frac', 0):6.3f} "
              f"{d.get('worst_tile', 0):6.1f} {d.get('mean_tile_diff', 0):6.2f} {d.get('position_panel_diff', 0):6.2f}")
        if d["verdict"] != "ok":
            worse.append(f"picture {png.stem}")
    (cand / f"compare-vs-{ref.name}.json").write_text(
        json.dumps({"worse": worse, "review": review, "pictures": pictures}, indent=1))
    print("\nverdict: " + ("WORSE: " + "; ".join(worse) if worse else "not worse")
          + ("\nreview: " + "; ".join(review) if review else ""))
    return 1 if worse else (2 if review else 0)


# ---------------------------------------------------------------------------------------------------- with-lock
def cmd_with_lock(a):
    cmd = a.cmd[1:] if a.cmd and a.cmd[0] == "--" else a.cmd
    if not cmd:
        raise SystemExit("with-lock: no command")
    take_lock("with-lock: " + " ".join(cmd)[:80], "", a.lock_wait)
    try:
        return subprocess.call(cmd)
    finally:
        release_lock()


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd_name", required=True)
    r = sub.add_parser("run")
    r.add_argument("app")
    r.add_argument("label")
    r.add_argument("env", nargs="*", help="ENV=VALUE pairs for Lichii")
    r.add_argument("--out")
    r.add_argument("--lock-wait", type=int, default=1800)
    r.add_argument("--max-load", type=float, default=0, help="refuse to start above this 1-min load average")
    c = sub.add_parser("compare")
    c.add_argument("ref")
    c.add_argument("cand")
    c.add_argument("--tile", type=float, default=TILE_THRESHOLD)
    c.add_argument("--frac", type=float, default=FRAC_THRESHOLD)
    c.add_argument("--slower", type=float, default=0.10, help="median slowdown counted as worse (0.10 = 10%%)")
    an = sub.add_parser("analyze")
    an.add_argument("run")
    w = sub.add_parser("with-lock")
    w.add_argument("--lock-wait", type=int, default=1800)
    w.add_argument("cmd", nargs=argparse.REMAINDER)
    sub.add_parser("lock-status")
    sub.add_parser("build-hook")
    a = p.parse_args()
    if a.cmd_name == "run":
        return cmd_run(a)
    if a.cmd_name == "compare":
        return cmd_compare(a)
    if a.cmd_name == "analyze":
        r = analyze(a.run)
        print_result(r)
        return 0
    if a.cmd_name == "with-lock":
        return cmd_with_lock(a)
    if a.cmd_name == "build-hook":
        build_hook()
        print(HOOK_LIB)
        return 0
    owner = lock_owner()
    print(f"lock {LOCK}: " + (json.dumps(owner) if owner else ("held, no owner file" if LOCK.exists() else "free"))
          + f"; running Lichii pids: {lichii_pids() or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
