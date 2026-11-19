#!/usr/bin/env python3
"""A/B runs of Lichii settings, driven through the built-in debug server.

    ../verify/verify.py with-lock -- python3 ab.py SPEC.json [--only LABEL ...]

SPEC.json is a list of runs: {"label", "cfg": {key: value}, "env": {NAME: VALUE}, "server": true,
"app": path, "poll_hz": 0, "repeat": 1}. Each run:

1. restores ~/.config/lichii/qt-config.ini from the master backup, then sets `cfg` (key=value plus key\\default=false);
2. launches the app with the verify frame hook (frames.bin, one timestamp per presented frame), the debug server
   (unless "server": false) and MVK_P60_NO_APPNAP=1;
3. loads the save named in config.json ("save": a map name from the saves' captions; the newest save with it,
   or an error when there is none; a spec's "save" overrides it). Each menu screen, the list's cursor, the loading
   screen and the arrival in the game are read from the game's UI manager in memory, and Link must stand at
   "expect_spawn" (else: wrong save, stop). Nothing is decided from the picture. Then it waits until the log shows
   3 s without a pipeline build;
4. after the load settles (pipeline builds quiet for 3 s, `settle_s`), walks 600 frames (walk: Link runs in 30-frame chunks and, when a chunk moves him < 0.3 m, turns him round (two quarter turns: left stick right, then a right-stick click to put the camera behind him) and runs on, back the way he came; `"walk": "route"` = the old fixed route), then stands 600 frames (stand2), with screenshots; `"stand_first": true` adds the old stand1 before the walk;
   with poll_hz > 0 it reads Link's position at that rate during stand2;
5. kills its Lichii, restores the config and writes result.json. A Lichii that dies without being told to is
   reported as "killed externally" and the run is retried once.
"""
import json
import shutil, os, re, signal, socket, statistics, struct, subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
CFG = Path.home() / ".config/lichii/qt-config.ini"
MASTER = Path.home() / ".config/lichii/qt-config.ini.before-debugsrv-2026-11-17"
LOG = Path.home() / ".local/share/lichii/log/eden_log.txt"
HOOK = REPO / "tools/verify/build/libverifyhook.dylib"
# The lldb logger (jsdbg.py) lives in the glitch-research repository; only "debugger" runs need it
JSDBG = Path(os.environ.get("OOT26_JSDBG_DIR", REPO.parent / "emulator/debug"))
HOOK_PORT = 26799
PAD = ("127.0.0.1", 26761)
sys.path.insert(0, str(HERE))
import dbg  # noqa: E402
from dbg import call, kab  # noqa: E402

ROUTE = [{"left_stick": [0, 1], "frames": 240}, {"left_stick": [1, 0], "frames": 120},
         {"left_stick": [0, 1], "frames": 180}, {"frames": 60}]



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

def set_cfg(over):
    lines = MASTER.read_text().splitlines()
    for key, val in over.items():
        sval = str(val).lower() if isinstance(val, bool) else str(val)
        hit = False
        for i, l in enumerate(lines):
            if l.startswith(key + "="):
                lines[i] = f"{key}={sval}"; hit = True
            elif l.startswith(key + "\\default="):
                lines[i] = f"{key}\\default=false"
        if not hit:
            raise SystemExit(f"config key {key} not found")
    CFG.write_text("\n".join(lines) + "\n")


def hook(cmd):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.settimeout(3)
    s.sendto(cmd.encode(), ("127.0.0.1", HOOK_PORT))
    try:
        return s.recvfrom(4096)[0].decode()
    except socket.timeout:
        return ""


def count():
    r = hook("count")
    return int(r) if r.strip().isdigit() else -1


def pad(text):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.settimeout(1)
    s.sendto(text.encode(), PAD); s.recvfrom(256)


def pad_tap(btn, hold=0.15):
    pad(f"press {btn}"); time.sleep(hold); pad(f"release {btn}"); time.sleep(0.15)


def wait_frames(n, alive):
    """Wait until the hook has counted n more presented frames."""
    start = count(); t0 = time.time()
    while count() < start + n:
        if not alive():
            raise RuntimeError("lichii died")
        if time.time() - t0 > n / 3 + 60:
            raise RuntimeError(f"hung: frames stalled at {count()} waiting for {start + n}")
        time.sleep(0.05)


METAL_CACHE = Path(subprocess.run(["getconf", "DARWIN_USER_CACHE_DIR"], capture_output=True, text=True).stdout.strip()) \
    / "io.github.zortos293.lichii" / "com.apple.metal"
_boot_cache0 = {}


def boot_progress(t0, rd):
    """Title text while no frame has arrived: shader compile progress. A cold Metal cache grows as MoltenVK
    recompiles the pipeline file one library at a time; warm boots barely touch it."""
    try:
        size = sum(f.stat().st_size for f in METAL_CACHE.glob("*/*.data"))
    except OSError:
        size = 0
    base = _boot_cache0.setdefault(str(rd), size)
    parts = [f"booting {time.time() - t0:.0f} s"]
    if size - base > 1 << 20:
        parts.append(f"compiling shaders: Metal cache +{(size - base) >> 20} MB")
    try:
        err = (rd / "stderr.log").read_bytes()[-4096:].decode(errors="replace")
        m = re.findall(r"\((\d+) mesh shaders so far\)", err)
        if m:
            parts.append(f"{m[-1]} mesh")
        m = re.findall(r"pipeline cache load (\d+) libraries, (\d+)%", err)
        if m:
            parts.append(f"pipeline cache {m[-1][1]}% ({int(m[-1][0]):,} libraries)")
    except OSError:
        pass
    return " \u00b7 ".join(parts)


def clipped_pct(path):
    """Share of near-white pixels (luma >= 245) in a screenshot, in %: blown-out frames (NaN/Inf through the HDR
    bloom) score 10-45 %, normal Kokiri and Gerudo frames 0-5 %."""
    try:
        from PIL import Image
        import numpy as np
        a = np.asarray(Image.open(path).convert("L").resize((320, 180)), dtype=np.float32)
        return round(float((a >= 245).mean()) * 100, 2)
    except Exception:
        return None


def tmark(res, name):
    """Record when a step happened, on CLOCK_UPTIME_RAW (frames.bin's clock) and CLOCK_MONOTONIC_RAW (libc++'s
    steady_clock in Lichii, so the JIT log's; it also counts time asleep), to line logs up with the harness's steps.
    First occurrence wins."""
    if name not in res.setdefault("t_uptime", {}):
        res["t_uptime"][name] = time.clock_gettime_ns(time.CLOCK_UPTIME_RAW)
        res.setdefault("t_monotonic", {})[name] = time.clock_gettime_ns(time.CLOCK_MONOTONIC_RAW)


def find_link():
    """Link's physics actor, through the player vtable (refs/kabosune/structures.md)."""
    pat = struct.pack("<Q", kab(0x84b6c460)).hex(); start = None
    while True:
        p = dict(pattern=pat, regions="all", max_hits=256, budget_ms=10000)
        if start:
            p["start"] = start
        r = call("search_memory", **p)
        for h in r["hits"]:
            a = int(h, 16)
            try:
                res = int(call("read_memory", address=hex(a + 0x10), size=8, **{"as": "u64"})["u64"][0], 16)
                name = bytes.fromhex(call("read_memory", address=hex(res + 0x58), size=8)["hex"]).split(b"\0")[0]
                if name == b"Player":
                    return int(call("read_memory", address=hex(a + 0x1d68), size=8, **{"as": "u64"})["u64"][0], 16)
            except Exception:
                pass
        if r.get("complete", True):
            return None
        start = r["next"]


def pos(actor):
    return [round(float(v), 3) for v in call("read_memory", address=hex(actor + 0x31c), size=12, **{"as": "f32"})["f32"]]


def stats(ts):
    d = [(b - a) / 1e6 for a, b in zip(ts, ts[1:])]
    if not d:
        return {}
    d.sort()
    q = lambda f: d[min(len(d) - 1, int(f * len(d)))]
    return {"frames": len(d), "mean": round(statistics.fmean(d), 2), "p50": round(q(0.5), 2), "p90": round(q(0.9), 2), "p95": round(q(0.95), 2),
            "p99": round(q(0.99), 2), "max": round(d[-1], 2), "over50": sum(x > 50 for x in d)}


# Screens compared on a part only: the Load dialogs sit on an animated scene, so only the save card counts.
def snap(rd, name, height=540):
    src = call("screenshot", height=height, save=True)["path"]
    dst = rd / f"{name}.png"; dst.write_bytes(Path(src).read_bytes())
    return dst


def failure_dump(rd, res):
    """What the screen and the log showed when a run went wrong."""
    try:
        snap(rd, "fail")
    except Exception as e:
        res["fail_shot"] = str(e)
    try:
        res["fail_status"] = call("status", timeout=10)
        res["fail_log"] = call("log_tail", limit=40, timeout=10).get("lines")
    except Exception as e:
        res["fail_server"] = str(e)


BUILD_RE = re.compile(r"Runtime pipelines in the last|Bounded pipeline wait|Background prebuild|pipeline build failed")


class LogCursor:
    """Reads new eden_log lines through the debug server and counts pipeline builds in them."""
    def __init__(self):
        self.next = call("log_tail", limit=1)["next"]

    def builds(self):
        n = 0
        while True:
            r = call("log_tail", after=self.next, limit=5000)
            self.next = r["next"]; n += sum(bool(BUILD_RE.search(l)) for l in r["lines"])
            if not r.get("more"):
                return n


def settle(res, cur, quiet_s=10, max_s=90):
    """Wait until quiet_s seconds pass with no pipeline-build line in the log (the game is loaded by now)."""
    t0 = last = time.time(); total = 0
    while time.time() - last < quiet_s:
        if time.time() - t0 > max_s:
            res["settle_timeout"] = True
            break
        time.sleep(1)
        n = cur.builds()
        if n:
            total += n; last = time.time()
    res["settle_s"] = round(time.time() - t0, 1); res["settle_builds"] = total


FLICKER_ROI = (0.0, 0.55, 0.38, 1.0)   # x0, y0, x1, y1 as fractions: the grass left of Link at spawn


def flicker_burst(rd, n=40, thrs=(15, 40)):
    """n screenshots in a row while Link stands still; all are kept in flicker/. A pixel 'flickers' in frame i when
    it differs from both neighbours by more than thr grey levels while the neighbours agree with each other (within
    thr / 2): a one-frame flash, not smooth motion. Counted inside FLICKER_ROI, for each threshold."""
    from PIL import Image
    import numpy as np
    fdir = rd / "flicker"; fdir.mkdir(exist_ok=True)
    paths = []
    for i in range(n):
        src = Path(call("screenshot", height=540, save=True)["path"]); dst = fdir / f"f{i:02d}.png"
        dst.write_bytes(src.read_bytes()); paths.append(dst)
    fr = [np.asarray(Image.open(x).convert("L"), dtype=np.int16) for x in paths]
    h, w = fr[0].shape; x0, y0, x1, y1 = FLICKER_ROI
    roi = (slice(int(y0 * h), int(y1 * h)), slice(int(x0 * w), int(x1 * w)))
    out = {"frames": n, "roi": FLICKER_ROI}
    for thr in thrs:
        counts = []
        for i in range(1, n - 1):
            a, b, c = fr[i - 1][roi], fr[i][roi], fr[i + 1][roi]
            m = (np.abs(b - a) > thr) & (np.abs(b - c) > thr) & (np.abs(a - c) < thr // 2)
            counts.append(int(m.sum()))
        out[f"thr{thr}"] = {"per_frame": counts, "total": sum(counts), "max": max(counts), "p50": sorted(counts)[len(counts) // 2]}
    return out


# The game's UI manager (sloperinaGZ's slot, refs/kabosune/sloperina-findings.md): a list of open UI screens. Which
# slots are set tells the screens apart (mapped live 2026-11-17, debugsrv/uisig.py):
#   title: 31 34 40 47 53 54 59 61   Load list: + 35 36   a save's Load dialog: + 38
#   loading: 55 (35/36/38 gone)      in game: the HUD screens (slot 0 among them) and no 55
# The Load list's cursor (0 = top entry) is an int at +0x1520 of screen 36.
UI_SLOT, LIST, DIALOG, LOADING, HUD, CURSOR_OFF = 0x84c9e098, 36, 38, 55, 0, 0x1520
CONFIG = json.loads((HERE / "config.json").read_text())


def resolve_save(name):
    """List position of the newest save whose caption names map `name` (Area/Map or Map). The Load list is newest
    first, which is the order of the slots' file times. Errors out when no save has that map."""
    d = Path(os.path.expanduser(CONFIG["save_dir"]))
    slots = sorted((x for x in d.glob("slot_*") if (x / "caption.sav").exists()),
                   key=lambda x: (x / "caption.sav").stat().st_mtime, reverse=True)
    for i, sl in enumerate(slots):
        cap = (sl / "caption.sav").read_bytes()[:4096]
        maps = set(re.findall(rb"[A-Za-z]+/[A-Za-z_]+", cap))
        if any(m.decode() == name or m.decode().split("/")[1] == name for m in maps):
            return i, sl.name, sorted(m.decode() for m in maps)
    raise SystemExit(f"no save with map {name!r} in {d}: " + ", ".join(
        f"{sl.name}={sorted(set(re.findall(rb'[A-Za-z]+/[A-Za-z_]+', (sl / 'caption.sav').read_bytes()[:4096])))}" for sl in slots))


def ui_screens():
    """{slot: object} of the open UI screens."""
    q = lambda a, n=1: [int(x, 16) for x in call("read_memory", address=hex(a), size=8 * n, **{"as": "u64"})["u64"]]
    ui = q(q(kab(UI_SLOT))[0])[0]; cnt, arr = q(ui + 8, 2)
    return {i: e for i, e in enumerate(q(arr, cnt)) if e}


def list_cursor(scr):
    return struct.unpack("<i", bytes.fromhex(call("read_memory", address=hex(scr[LIST] + CURSOR_OFF), size=4)["hex"]))[0]


def navigate_menus(rd, res, save_index, spawn, limit_s=150):
    """Title -> Load list -> entry save_index -> in game at spawn, decided from the game's own UI state in memory
    and Link's object, never from the picture."""
    press = lambda b: call("input_sequence", steps=[{"buttons": [b], "frames": 4}, {"frames": 8}])
    t0 = time.time(); trace = []; confirmed = False
    note = lambda st: trace.append((round(time.time() - t0, 1), st)) if not trace or trace[-1][1] != st else None
    while time.time() - t0 < limit_s:
        try:
            scr = ui_screens()
        except Exception as e:
            note(f"ui unreadable: {e}"); time.sleep(0.5); continue
        if HUD in scr and LOADING not in scr:
            note("in game"); tmark(res, "in_game")
            actor = find_link()
            if not actor:
                raise RuntimeError("stuck: in game but Link's object not found")
            p = pos(actor); res["spawn_pos"] = p
            if spawn and (abs(p[0] - spawn[0]) > 0.5 or abs(p[2] - spawn[2]) > 0.5):
                raise RuntimeError(f"wrong save loaded: Link at {p}, expected {spawn}")
            res["menu_trace"] = trace; res["menu_s"] = round(time.time() - t0, 1)
            return actor
        if LOADING in scr:
            note("loading"); tmark(res, "loading")
        elif DIALOG in scr:
            note("dialog"); press("A"); confirmed = True
        elif LIST in scr:
            c = list_cursor(scr); note(f"load list, cursor {c}")
            press("Down" if c < save_index else "Up" if c > save_index else "A")
        elif not confirmed:
            note("title"); press("A")
        time.sleep(0.2)
    res["menu_trace"] = trace
    raise RuntimeError(f"stuck: not in game after {limit_s}s; last states {trace[-4:]}")


def one_run(spec, out, attempt="1/1"):
    """One run; with "cold_metal_cache": true, from an empty Metal shader cache (the real one held aside under the
    emulator lock and put back afterwards, also on errors). Waits first for this project's builds to finish."""
    w = wait_for_builds(spec["label"])
    if w > 0:
        print(f"{spec['label']}: waited {w} s for builds", flush=True)
    if not spec.get("cold_metal_cache"):
        return _one_run(spec, out, attempt)
    hold = METAL_CACHE.with_name("com.apple.metal.real-hold")
    if hold.exists():
        raise SystemExit(f"{hold} exists: a previous cold run did not put the real cache back; restore it first")
    METAL_CACHE.rename(hold)
    try:
        return _one_run(spec, out, attempt)
    finally:
        if METAL_CACHE.exists():
            shutil.rmtree(METAL_CACHE)
        hold.rename(METAL_CACHE)


def my_builds():
    """This project's variant builds (path-60's prebuild-variants.sh / build.sh: "ninja -j 6 lichii")."""
    out = subprocess.run(["pgrep", "-f", "[n]inja -j 6 lichii"], capture_output=True, text=True).stdout.split()
    return [p for p in out if p.isdigit()]


def wait_for_builds(label):
    """Builds go first: no run starts while one of this project's variant builds is compiling (it would load every core
    and skew the numbers). Other sessions' builds don't count."""
    waited = time.time(); said = False
    while my_builds():
        if not said:
            print(f"{label}: waiting for builds {my_builds()}", flush=True); said = True
        time.sleep(10)
    return round(time.time() - waited, 1)


def _one_run(spec, out, attempt="1/1"):
    rd = out / spec["label"]; rd.mkdir(parents=True, exist_ok=True)
    for f in rd.glob("frames.bin"):
        f.unlink()
    server = spec.get("server", True)
    if not server:
        raise SystemExit("server-off runs are not supported: without the debug server the menus can only be driven "
                         "blind, which is not reliable (2026-11-17)")
    set_cfg(spec.get("cfg", {}))
    env = dict(os.environ)
    env.update({"MVK_P60_NO_APPNAP": "1", "VERIFY_DIR": str(rd), "VERIFY_PORT": str(HOOK_PORT),
                "DYLD_INSERT_LIBRARIES": str(HOOK)})
    if server:
        env.update({"EDEN_NX2_DEBUG_SERVER": "127.0.0.1:6545", "EDEN_NX2_DEBUG_DIR": str(rd / "dumps")})
    env.update({k: str(v).replace("{rd}", str(rd)) for k, v in spec.get("env", {}).items()})
    if spec.get("variants"):
        env["EDEN_NX2_HVF_CTL"] = str(rd / "hvf_ctl.txt")
    app = Path(spec.get("app", "/Applications/lichii.app"))
    res = {"label": spec["label"], "spec": spec, "loadavg_before": os.getloadavg(), "marks": {}}
    old_log_ino = LOG.stat().st_ino if LOG.exists() else None
    with open(rd / "stderr.log", "wb") as err:
        proc = subprocess.Popen([str(app / "Contents/MacOS/lichii"), *spec.get("args", []), str(GAME)], env=env, stdout=err,
                                stderr=subprocess.STDOUT, start_new_session=True)
    jsdbg = None
    if spec.get("jsdbg"):
        # Attach only once the guest is held for the debugger: a continue sent before that is lost and the guest
        # then waits forever (seen 2026-11-17: attach at 2.87 s, process held at 2.94 s).
        t_wait = time.time()
        while time.time() - t_wait < 120 and proc.poll() is None:
            if LOG.exists() and LOG.stat().st_ino != old_log_ino and \
                    "suspending guest process until a debugger" in LOG.read_text(errors="replace"):
                break
            time.sleep(0.2)
        # Lichii with use_gdbstub waits at boot for a debugger: attach emulator/debug/jsdbg.py (lldb), which then
        # continues it. "arm" also sets its per-frame breakpoints once the game has settled.
        dbgdir = JSDBG
        lldb_py = subprocess.run(["lldb", "-P"], capture_output=True, text=True).stdout.strip()
        (dbgdir / "jsdbg.cmd").unlink(missing_ok=True)
        jsdbg = subprocess.Popen(["/usr/bin/python3", str(dbgdir / "jsdbg.py"), str(rd / "jsdbg.log")], cwd=dbgdir,
                                 env=dict(os.environ, PYTHONPATH=lldb_py), stdout=open(rd / "jsdbg.out", "wb"),
                                 stderr=subprocess.STDOUT, start_new_session=True)
    killed_by_us = False
    alive = lambda: proc.poll() is None
    session = CONFIG.get("session_name", "emu-options")
    desc = (spec.get("desc") or f"Check frame time at the spawn with {spec['label']}")[:120]
    title = lambda step: hook(f"title {session} \u00b7 {spec['label']} \u00b7 {attempt} \u00b7 {step} \u2016 {desc}")
    mark = lambda name: (res["marks"].__setitem__(name, count()), title(name), tmark(res, name))
    try:
        t0 = time.time(); tmark(res, "start")
        # title screen: wait for ~900 presents
        last_n, last_t = -1, time.time()
        busy = []                                     # (time, process CPU %) while no frame arrives
        last_size, last_grow_t = -1, time.time()      # log + stderr size: progress while no frame arrives
        while count() < 300:
            if not alive():
                raise RuntimeError("lichii died during boot")
            title(boot_progress(t0, rd))              # from the start: a cold boot shows no frames for minutes
            if server and "speed_limit_off" not in res:
                try:                                  # unlimited from the first moment the server answers (~1 s)
                    res["speed_limit_off"] = call("speed_limit", on=False, timeout=2)
                except Exception:
                    pass
            n = count()
            # Lichii's own CPU plus Apple's Metal compiler service: a cold boot compiles shaders there, while
            # Lichii itself idles at ~2% waiting for it.
            out = subprocess.run(["ps", "-axo", "pid=,%cpu=,comm="], capture_output=True, text=True).stdout
            cpu = sum(float(l.split()[1]) for l in out.splitlines()
                      if len(l.split()) >= 3 and (l.split()[0] == str(proc.pid) or "MTLCompilerService" in l))
            if n != last_n:
                last_n, last_t, busy = n, time.time(), []
            else:
                busy.append(cpu)
            stalled = time.time() - last_t
            # Progress without frames: a cold boot's shader compiles keep Lichii's log and stderr growing.
            grown = sum(f.stat().st_size for f in (LOG, rd / "stderr.log") if f.exists())
            try:                                      # a cold compile can be silent for minutes; the cache grows
                grown += sum(f.stat().st_size for f in METAL_CACHE.glob("*/*.data"))
            except OSError:
                pass
            if grown != last_size:
                last_size, last_grow_t = grown, time.time()
            quiet = time.time() - max(last_t, last_grow_t)
            # Hung: no frame for 20 s with Lichii and the Metal compiler nearly idle (seen in the intro video and
            # loading pipelines); or no frame and no log output for 180 s however busy the compiler is; or an hour in
            # all. A cold Metal cache makes MoltenVK recompile the whole Vulkan pipeline cache one library at a
            # time at boot (one MTLCompilerService at 100%, tens of minutes), with stderr still growing.
            if (stalled > 20 and sum(busy[-20:]) / max(1, len(busy[-20:])) < 20) or quiet > 180 or stalled > 3600:
                subprocess.run(["sample", str(proc.pid), "3", "-file", str(rd / "hang-sample.txt")],
                               capture_output=True, timeout=60)
                raise RuntimeError(f"hung: no frame for {stalled:.0f} s (no log output for {quiet:.0f} s) during "
                                   f"boot at frame {n}, CPU {sum(busy[-20:]) / max(1, len(busy[-20:])):.0f}%")
            time.sleep(1)
        res["boot_s"] = round(time.time() - t0, 1); title("menus"); tmark(res, "boot_done")
        m = re.search(r"Module main loaded at (0x[0-9a-f]+)", LOG.read_text(errors="replace"))
        if not m:
            raise RuntimeError("main's load address is not in the log")
        dbg.MAIN = int(m.group(1), 16); res["main_base"] = m.group(1)   # ASLR: differs every boot
        if server:
            save = spec.get("save", CONFIG["save"]); spawn = spec.get("expect_spawn", CONFIG.get("expect_spawn"))
            fixed = spec.get("save_index", CONFIG.get("save_index"))
            if fixed is not None:                     # fallback: a fixed Load-list position (0 = newest)
                idx = int(fixed); res["save"] = {"list_index": idx, "by": "save_index"}
            else:
                idx, slot, maps = resolve_save(save); res["save"] = {"name": save, "slot": slot, "list_index": idx}
            # Unlimited speed through menus and the load: 120 fps (the display's vsync cap) instead of 60, a few
            # seconds less per run. Restored before anything is measured.
            if "speed_limit_off" not in res:
                res["speed_limit_off"] = call("speed_limit", on=False)
            actor = navigate_menus(rd, res, idx, spawn)
            call("speed_limit", on=True)
            res["spawn_pos"] = pos(actor)
        else:
            pad("reset")
            for b in ("a", "a", "b"):
                pad_tap(b); time.sleep(3)
            for b in ("down", "down", "a"):
                pad_tap(b); time.sleep(0.6)
            time.sleep(2); pad_tap("a"); time.sleep(45)
        res["load_s"] = round(time.time() - t0, 1); tmark(res, "load_done")
        cur = None
        if server:
            title("settling"); cur = LogCursor(); settle(res, cur, quiet_s=spec.get("settle_s", 3)); tmark(res, "settled")
            if spec.get("jsdbg") == "arm":
                (JSDBG / "jsdbg.cmd").write_text("arm\n"); res["jsdbg_armed"] = True
                wait_frames(60, alive)
            for k, sc in enumerate(spec.get("server_calls", [])):
                # debug-server tools after settle (capture_bundle, trace_record, ...): results kept in result.json
                title(f"server call {sc['method']}")
                t1 = time.time()
                try:
                    out = call(sc["method"], timeout=sc.get("timeout", 400), **sc.get("params", {}))
                except Exception as e:
                    out = {"error": str(e)}
                res.setdefault("server_calls", []).append({"method": sc["method"], "s": round(time.time() - t1, 1),
                                                           "result": out})
                cur.builds()
            if spec.get("server_calls"):
                # anything they set off (a JIT flush recompiles, a capture stalls) settles before measuring
                title("settling again"); r2 = {}; settle(r2, cur, quiet_s=spec.get("settle_s", 3))
                res["resettle_s"] = r2.get("settle_s")
                wait_frames(120, alive)
            if spec.get("capture"):
                # Lichii's frame dump of the next frame at spawn: every pass with its shaders, targets, sampled
                # textures and bound buffers (docs/nx2/debug-mcp.md, capture_frame)
                title("frame capture")
                res["capture"] = call("capture_frame", sampled=True, buffers=True, timeout_s=300, timeout=360)
                cur.builds()
            if spec.get("flicker"):
                # at spawn, before the timed phases; sloperinaGZ's watch box covers the grass, so hide it (R + D-right)
                title("flicker burst")
                chord = [{"buttons": ["R", "Right"], "frames": 6}, {"frames": 20}]
                call("input_sequence", steps=chord)
                res["flicker"] = flicker_burst(rd, n=spec["flicker"])
                call("input_sequence", steps=chord)
                cur.builds()
        else:
            wait_frames(120, alive)
        res["builds"] = {}; res["phases"] = []
        P = int(spec.get("phase_frames", 300))
        route = [dict(st, frames=max(1, round(st["frames"] * P / 600))) for st in ROUTE]

        def measure(prefix=""):
            """stand P frames, walk the route (P frames), stand P frames; marks and builds under prefix."""
            ph = lambda name: f"{prefix}{name}"
            # Default since 2026-11-17 evening: walk as soon as the load has settled (builds quiet for 3 s), then
            # stand; "stand_first": true restores the old stand / walk / stand order.
            stand_first = spec.get("stand_first", False)
            if stand_first:
                mark(ph("stand1")); wait_frames(P // 2, alive); hook(f"shot {rd}/{prefix.strip('/') or 'run'}-stand1.png")
                wait_frames(P - P // 2, alive)
                res["builds"][ph("stand1")] = cur.builds()
            mark(ph("walk"))
            start = pos(actor)
            if spec.get("walk", "bounce") == "bounce":
                # Run forward in short chunks and read Link's position after each: when a chunk barely moves him
                # (a cliff, a wall), turn him round and keep pushing forward, so he runs back the way he came. Pulling
                # the left stick back doesn't rotate him (he backs away facing the wall), so the turn is two quarter
                # turns: left stick right (he turns to his right and runs that way), then a right-stick click
                # (StickR: the camera recentres behind him), twice. Keeps him moving for the whole phase.
                chunk = int(spec.get("bounce_chunk", 30)); done_f = 0; last = start
                tf = int(spec.get("turn_frames", 15))
                quarter = [{"left_stick": [1, 0], "frames": tf},
                           {"left_stick": [1, 0], "buttons": ["StickR"], "frames": 4}, {"frames": 6}]
                turn = quarter + quarter
                path = [[round(v, 2) for v in start]]; turns = []
                while done_f < P:
                    n = min(chunk, P - done_f)
                    call("input_sequence", steps=[{"left_stick": [0, 1], "frames": n}], timeout_s=120)
                    done_f += n; here = pos(actor); path.append([round(v, 2) for v in here])
                    step = sum((x - y) ** 2 for x, y in zip(here, last)) ** 0.5; last = here
                    if step < float(spec.get("bounce_min_m", 0.3)) and done_f < P:
                        call("input_sequence", steps=turn, timeout_s=60); turns.append(done_f)
                res[ph("walk_call")] = {"mode": "bounce", "chunk": chunk, "turns_at_frame": turns, "path": path}
            else:
                res[ph("walk_call")] = call("input_sequence", steps=route, timeout_s=600)
            mark(ph("stand2")); res["builds"][ph("walk")] = cur.builds()
            hook(f"shot {rd}/{prefix.strip('/') or 'run'}-walkend.png")
            moved = sum((x - y) ** 2 for x, y in zip(pos(actor), start)) ** 0.5
            wc = res[ph("walk_call")]
            if isinstance(wc, dict) and wc.get("mode") == "bounce":      # it may end where it began: use the path
                moved = sum(sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5 for a, b in zip(wc["path"], wc["path"][1:]))
            res[ph("walk_moved_m")] = round(moved, 2)
            if moved < 0.5:
                raise RuntimeError(f"stuck: the walk moved Link only {moved:.2f} m")
            polls = []; hz = spec.get("poll_hz", 0)
            if hz:
                end = count() + P
                while count() < end:
                    polls.append(time.time()); pos(actor); time.sleep(max(0, 1 / hz - 0.0003))
                res[ph("poll_rate")] = round(len(polls) / (polls[-1] - polls[0]), 1)
            else:
                wait_frames(P, alive)
            mark(ph("end")); res["builds"][ph("stand2")] = cur.builds()
            try:                                      # resident memory and its footprint (what Activity Monitor shows)
                rss = subprocess.run(["ps", "-o", "rss=", "-p", str(proc.pid)], capture_output=True, text=True).stdout.strip()
                res[ph("rss_mb")] = round(int(rss) / 1024) if rss else None
                fp = subprocess.run(["footprint", "-p", str(proc.pid)], capture_output=True, text=True, timeout=30).stdout
                m = re.search(r"Footprint:\s+([\d.]+)\s*([KMG]B)", fp)
                if m:
                    res[ph("footprint_mb")] = round(float(m[1]) * {"KB": 1 / 1024, "MB": 1, "GB": 1024}[m[2]])
            except Exception:
                pass
            res[ph("end_pos")] = pos(actor)
            res["phases"] += [(ph(x), ph(y)) for x, y in ((("stand1", "walk"),) if stand_first else ()) + (("walk", "stand2"), ("stand2", "end"))]
            if not stand_first:
                hook(f"shot {rd}/{prefix.strip('/') or 'run'}-stand2.png")
            shots = {f.name: clipped_pct(f) for f in sorted(rd.glob(f"{prefix.strip('/') or 'run'}-*.png"))}
            res[ph("clipped_pct")] = shots
            vals = [v for v in shots.values() if v is not None]
            if vals and max(vals) > 8:
                res[ph("blowout")] = True

        variants = spec.get("variants")
        if not variants:
            measure()
        else:
            ctl = rd / "hvf_ctl.txt"
            # save Link's place at spawn (sloperinaGZ: R + D-up); each variant starts there (R + D-down)
            # sloperinaGZ wants R held before the D-pad (as pad.py's chords do)
            chord = lambda d: call("input_sequence", steps=[{"buttons": ["R"], "frames": 4},
                                                            {"buttons": ["R", d], "frames": 6}, {"frames": 20}])
            chord("Up"); home = pos(actor)
            for i, v in enumerate(variants):
                ctl.write_text(v["ctl"] + "\n")
                spec_label = v["label"]; title(f"variant {spec_label}")
                if i:
                    chord("Down"); wait_frames(10, alive)
                    off = sum((a - b) ** 2 for a, b in zip(pos(actor), home)) ** 0.5
                    res[f"{spec_label}/reset_off_m"] = round(off, 2)
                    if off > 1.0:
                        raise RuntimeError(f"position reset failed before {spec_label}: {off:.1f} m from the start")
                wait_frames(60, alive)          # the watcher re-reads the file every 100 ms
                measure(prefix=f"{spec_label}/")
        title("done")
        res["outcome"] = "completed"
    except Exception as e:
        res["outcome"] = "killed externally" if not alive() and not killed_by_us else f"error: {e}"
        if server and alive():
            failure_dump(rd, res)
    finally:
        if alive():
            killed_by_us = True
            os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()
        if jsdbg and jsdbg.poll() is None:
            jsdbg.kill()
        time.sleep(1)
        if LOG.exists():
            (rd / "eden_log.txt").write_bytes(LOG.read_bytes())
        CFG.write_text(MASTER.read_text())
    fb = rd / "frames.bin"
    ts = list(struct.unpack(f"<{fb.stat().st_size // 8}Q", fb.read_bytes())) if fb.exists() else []
    m = res["marks"]
    for a, b in res.get("phases") or [("stand1", "walk"), ("walk", "stand2"), ("stand2", "end")]:
        if m.get(a, -1) >= 0 and m.get(b, -1) > m[a]:
            res[a] = stats(ts[m[a]:m[b] + 1])
    log_path = rd / "eden_log.txt"
    if res["outcome"] != "completed" and log_path.exists() and \
            "Unhandled guest exception" in log_path.read_text(errors="replace"):
        res["outcome"] = "error: guest crashed (" + res["outcome"][7:80] + ")"
    res["loadavg_after"] = os.getloadavg()
    (rd / "result.json").write_text(json.dumps(res, indent=1))
    return res


def main():
    # "${REPO}" in a spec stands for the repository folder, so specs carry no machine-specific paths
    spec = json.loads(Path(sys.argv[1]).read_text().replace("${REPO}", str(REPO)))
    only = sys.argv[sys.argv.index("--only") + 1:] if "--only" in sys.argv else None
    out = HERE / "runs" / time.strftime("ab-%Y%m%d-%H%M%S"); out.mkdir(parents=True)
    print("out", out, flush=True)
    if GAME is None:
        raise SystemExit("no dump of the game: set OOT26_DUMP or put *0400486024DEC000*.nup in dump/")
    if not MASTER.exists():
        raise SystemExit("master config backup missing")
    # The window title counts the batch's runs: "3/9" is the third of nine (repeats included), "3/9 retry" its retry.
    total = sum(s.get("repeat", 1) for s in spec if not only or s["label"] in only)
    number = 0
    for s in spec:
        if only and s["label"] not in only:
            continue
        for rep in range(s.get("repeat", 1)):
            s2 = dict(s, label=s["label"] + (f"-r{rep + 1}" if s.get("repeat", 1) > 1 else ""))
            number += 1
            att = f"{number}/{total}"
            r = one_run(s2, out, att)
            if r["outcome"] == "killed externally" or r["outcome"].startswith(("error: hung", "error: guest crashed")):
                print(f"{s2['label']}: {r['outcome']}, retrying", flush=True)
                r = one_run(s2, out, att + " retry")
            row = {k: r.get(k) for k in ("outcome", "boot_s", "load_s")}
            if r.get("footprint_mb") or r.get("rss_mb"):
                row["mem_mb"] = r.get("footprint_mb") or r.get("rss_mb")
            cp = [v for v in (r.get("clipped_pct") or {}).values() if v is not None]
            if cp:
                row["clipped_max"] = max(cp)
            if r.get("blowout"):
                row["BLOWOUT"] = True
            for a, _ in r.get("phases") or []:
                if r.get(a):
                    row[a] = f"{r[a]['p50']}/{r[a]['p90']}/{r[a].get('p95', '-')}/{r[a]['p99']}/{r[a]['max']}"
            if r.get("flicker"):
                row["flicker"] = {k: f"{v['total']}/{v['max']}" for k, v in r["flicker"].items() if k.startswith("thr")}
            print(s2["label"], json.dumps(row), "load", [round(x, 1) for x in r["loadavg_before"]], flush=True)


if __name__ == "__main__":
    main()
