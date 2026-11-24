#!/usr/bin/env python3
"""A/B runs of Lichii settings, driven through the built-in debug server.

    ./queue.sh SPEC.json             (under the emulator lock; or ../verify/verify.py with-lock -- python3 ab.py ...)
    python3 ab.py SPEC.json [--only LABEL ...]
    python3 ab.py --make-master [--home DIR] [--force]  # the master config, from qt-config.ini, checked first
    python3 ab.py --make-home DIR [--with-shader-cache]  # a private Lichii data root, copied from the real one
    python3 ab.py --print-paths [--home DIR] [SPEC.json] # what a run would read and write (launches nothing)
    python3 ab.py --add-save NAME SLOT_DIR [--spawn X,Y,Z] [--note TEXT] [--force]  # a save into the library
    python3 ab.py --list-saves                           # the library's saves

SPEC.json is a list of runs: {"label", "cfg": {key: value}, "env": {NAME: VALUE}, "server": true,
"app": path, "poll_hz": 0, "repeat": 1}. Each run:

1. restores ~/.config/lichii/qt-config.ini from the master (qt-config.ini.harness-master beside it), then sets
   `cfg` (key=value plus key\\default=false); with "home" (or $OOT26_LICHII_HOME), the private data root's copies;
2. launches the app with the verify frame hook (frames.bin, one timestamp per presented frame), the debug server
   (unless "server": false) and MVK_P60_NO_APPNAP=1;
3. loads the save named in config.json (a spec's "save" overrides it): a save of the library ("save_library"),
   which replaces every slot of the game's save folder and is left there after the run; else a map name from the saves' captions, the newest save with it, or an error when there is none. Each menu screen, the list's cursor, the loading
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
DEFAULT_APP = REPO / "build/app/lichii.app"          # the pinned build, made by ./build.sh
MASTER_NAME = "qt-config.ini.harness-master"
HOOK = REPO / "tools/verify/build/libverifyhook.dylib"
# The lldb logger (jsdbg.py) lives in the glitch-research repository, not here; only "jsdbg" runs need it, never a
# measurement. $OOT26_JSDBG_DIR, else emulator/debug beside this repository (where it sits when nested in that one).
JSDBG = Path(os.environ.get("OOT26_JSDBG_DIR", REPO.parent / "emulator/debug"))
HOOK_PORT = 26799
sys.path.insert(0, str(HERE))
sys.path.insert(1, str(REPO / "tools/speckcheck"))   # speckhunt, whitecount: at_end, walk_shots, on_corrupt
sys.path.insert(2, str(REPO / "tools/verify"))       # emulock: the emulator lock and its lease
import emulock  # noqa: E402


class Home:
    """Where Lichii keeps its state for a run. Without a root: the real folders. With one: a private data root,
    passed to Lichii as XDG_DATA_HOME / XDG_CACHE_HOME / XDG_CONFIG_HOME = ROOT/share, ROOT/cache, ROOT/config.
    Lichii (src/common/fs/path_util.cpp, GetDataDirectory and Reinitialize) takes each variable when it is an
    absolute path, else $HOME/.local/share, $HOME/.cache, $HOME/.config, and appends "lichii" (EDEN_DIR in
    fs_paths.h) to each; a "user" folder in its working directory would override all three (portable mode)."""
    REAL = {"config": Path.home() / ".config/lichii", "data": Path.home() / ".local/share/lichii",
            "cache": Path.home() / ".cache/lichii"}

    def __init__(self, root=None):
        self.root = Path(root).expanduser().absolute() if root else None
        if self.root:
            self.dirs = {"config": self.root / "config/lichii", "data": self.root / "share/lichii",
                         "cache": self.root / "cache/lichii"}
        else:
            self.dirs = dict(self.REAL)
        self.cfg = self.dirs["config"] / "qt-config.ini"
        self.master = self.dirs["config"] / MASTER_NAME
        self.log = self.dirs["data"] / "log/eden_log.txt"

    def env(self):
        if not self.root:
            return {}
        return {"XDG_DATA_HOME": str(self.root / "share"), "XDG_CACHE_HOME": str(self.root / "cache"),
                "XDG_CONFIG_HOME": str(self.root / "config")}

    def relocate(self, path):
        """A path under one of the real folders, moved to the same place under this root (others unchanged)."""
        path = Path(os.path.expanduser(str(path)))
        for k, real in self.REAL.items():
            if path == real or real in path.parents:
                return self.dirs[k] / path.relative_to(real)
        return path

    def save_dir(self):
        return self.relocate(CONFIG["save_dir"])

    def real_paths_in(self, f):
        """Lines of file f that name one of the real folders (a private root's config must not)."""
        if not f.exists():
            return []
        needles = [str(r) for r in self.REAL.values()]
        return [l for l in f.read_text(errors="replace").splitlines() if any(n in l for n in needles)]

    def check(self, launching=True):
        """Refuse what would make a run read or write outside its root."""
        if not self.master.exists():
            what = f" --home {self.root}" if self.root else ""
            raise SystemExit(f"no master config {self.master}: the harness restores Lichii's config from it before and "
                             f"after every run. Create it (Lichii closed, settings as in config/settings.txt) with: "
                             f"python3 {HERE / 'ab.py'} --make-master{what}")
        if not self.root:
            return
        for f in (self.cfg, self.master):
            bad = self.real_paths_in(f)
            if bad:
                raise SystemExit(f"{f} still names the real Lichii folders, so a run would use them: {bad[:4]}. "
                                 f"Rewrite them (python3 ab.py --make-home does this) and try again")
        if launching and (Path.cwd() / "user").is_dir():
            raise SystemExit(f"{Path.cwd() / 'user'} exists: Lichii would use it (portable mode) instead of {self.root}")


def run_home(spec):
    """The data root of a run: its "home", else $OOT26_LICHII_HOME, else the real folders."""
    root = spec.get("home") or os.environ.get("OOT26_LICHII_HOME")
    return Home(root)


HOME = Home()
CFG, MASTER, LOG = HOME.cfg, HOME.master, HOME.log


def use_home(h):
    """Point the module's paths (the config the harness rewrites, its master, the log it reads) at h."""
    global HOME, CFG, MASTER, LOG
    HOME, CFG, MASTER, LOG = h, h.cfg, h.master, h.log
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

# The practice tool (sloperinaGZ) reads its settings at boot. Binds of its commands that collide with buttons the
# harness presses are switched off for a harness run and put back afterwards. R3: the tool's "ragdoll" command since
# 0.0.9 (it knocks Link over); the harness clicks the right stick to put the camera behind Link when it turns him.
TOOL_BINDS_OFF = {"bind_ragdoll": "unbound"}


def tool_settings(home):
    return home.dirs["data"] / "sdmc/sloperinaGZ/settings.ini"


def tool_binds_set(home):
    """Write the harness's binds into the practice tool's settings, keeping the owner's file beside it. A copy that
    is already there is from a run that was killed before it could put the file back: that copy is the owner's."""
    f = tool_settings(home)
    if not f.exists():
        return
    saved = f.with_name(f.name + ".harness-saved")
    if saved.exists():
        f.write_text(saved.read_text())
    else:
        saved.write_text(f.read_text())
    lines = [l for l in f.read_text().splitlines() if l.split("=", 1)[0] not in TOOL_BINDS_OFF]
    f.write_text("\n".join(lines + [f"{k}={v}" for k, v in TOOL_BINDS_OFF.items()]) + "\n")


def tool_binds_restore(home):
    f = tool_settings(home)
    saved = f.with_name(f.name + ".harness-saved")
    if saved.exists():
        f.write_text(saved.read_text())
        saved.unlink()


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


CUBE_MAX = 50.0   # a clean lighting cube face stays under about 1.2; the bad boots of 2026-11-19 held 4,672-57,856


def cube_check(call, n):
    """Capture n frames in a row and return the largest value in any 128x128 format-21 render target. The capture
    folders are listed under "dirs" so a passing run can delete them (prune_cube_captures)."""
    worst = {"max": 0.0, "captures": 0, "targets": 0, "dirs": []}
    for _ in range(n):
        try:
            r = call("capture_frame", timeout=120, sampled=False)
            worst["dirs"].append(r["directory"])
            rows = [json.loads(l) for l in (Path(r["directory"]) / "manifest.jsonl").read_text().splitlines() if l]
        except Exception as e:   # a failed capture must not fail the run
            worst["error"] = str(e); break
        worst["captures"] += 1
        for row in rows:
            if (row.get("kind") == "pass" and row.get("width") == 128 and row.get("height") == 128
                    and str(row.get("format")) == "21" and row.get("max")):
                worst["targets"] += 1
                m = max(row["max"][:3])
                if m > worst["max"]:
                    worst.update(max=m, name=row.get("name"), directory=r["directory"])
    return worst


def prune_cube_captures(check, rd):
    """Delete the cube check's capture folders (about 1 GB a run) once the run has scored clean; only folders inside
    the run folder are touched. The verdict and the largest value stay in result.json."""
    freed = 0
    for d in check.pop("dirs", []):
        p = Path(d).resolve()
        if p.is_dir() and rd.resolve() in p.parents:
            freed += sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
            shutil.rmtree(p)
    check["captures_deleted_mib"] = freed >> 20


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
GUEST_CRASH_LINES = ("Unhandled guest exception", "Cannot execute instruction at unmapped address")


SAVE_FILES = ("caption.sav", "progress.sav")   # one save: what the Load list shows, and the save itself
LOAD_SLOT = "slot_01"   # where a library save is put; slot_00 is left empty because leaving an area autosaves there


def caption_maps(cap):
    """The Area/Map names in a caption.sav file."""
    return sorted(set(m.decode() for m in re.findall(rb"[A-Za-z]+/[A-Za-z_]+", Path(cap).read_bytes()[:4096])))


def save_library():
    """The folder of named saves (config.json "save_library"), one folder per save. Not in this repository: saves
    are game data."""
    return Path(os.path.expanduser(CONFIG.get("save_library", "~/.local/share/oot26-saves")))


def library_save(name):
    """(folder, save.json) of the library save called `name`, or None when there is none (`name` is then a map)."""
    if not name or "/" in name:
        return None
    d = save_library() / name
    if not all((d / f).is_file() for f in SAVE_FILES):
        return None
    meta = d / "save.json"
    return d, (json.loads(meta.read_text()) if meta.is_file() else {})


def stage_save(h, src):
    """Make library save `src` the only save in h's save folder, in LOAD_SLOT: every slot_NN is deleted first (the
    library keeps the saves that matter), so the Load list has one entry and where the game sorts an imported save
    does not matter. account.sav and option.sav stay the root's own (option.sav differs between game versions)."""
    d = h.save_dir()
    if not d.is_dir():
        raise SystemExit(f"no saves of the game in {d} (config.json save_dir, under Lichii's data folder): boot the "
                         "game once and make a save")
    for sl in d.glob("slot_*"):
        if sl.is_dir():
            shutil.rmtree(sl)
    (d / LOAD_SLOT).mkdir()
    for f in SAVE_FILES:
        shutil.copy2(src / f, d / LOAD_SLOT / f)


def add_save(name, slot, spawn=None, note=None, force=False):
    """Copy the save in folder `slot` (a slot_NN of the game's save folder, or a downloaded save with the same two
    files) into the library as `name`."""
    src = Path(slot).expanduser()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name):
        raise SystemExit(f"{name!r}: a library save's name is letters, digits, '.', '_' and '-'")
    missing = [f for f in SAVE_FILES if not (src / f).is_file()]
    if missing:
        raise SystemExit(f"{src} has no {', '.join(missing)}")
    d = save_library() / name
    if d.exists() and not force:
        raise SystemExit(f"{d} exists; add --force to replace it")
    d.mkdir(parents=True, exist_ok=True)
    for f in SAVE_FILES:
        shutil.copy2(src / f, d / f)
    meta = {"maps": caption_maps(d / "caption.sav"), "expect_spawn": spawn, "source": str(src.absolute()),
            "added": time.strftime("%Y-%m-%d %H:%M"), "note": note}
    (d / "save.json").write_text(json.dumps(meta, indent=1) + "\n")
    print(f"added {d}: {json.dumps(meta)}")


def list_saves():
    lib = save_library()
    rows = sorted(p for p in lib.glob("*/") if library_save(p.name)) if lib.is_dir() else []
    print(f"{lib}: {len(rows)} saves")
    for p in rows:
        m = library_save(p.name)[1]
        print(f"  {p.name:24} {', '.join(m.get('maps') or caption_maps(p / 'caption.sav'))}  spawn {m.get('expect_spawn')}"
              + (f"  ({m['note']})" if m.get("note") else ""))


def is_default_save(spec):
    """A run of config.json's save: its picture checks (end_white_max, cube_check, on_corrupt) apply."""
    return spec.get("save", CONFIG["save"]) == CONFIG["save"]


def resolve_save(name):
    """List position of the newest save whose caption names map `name` (Area/Map or Map), for a `save` that is not
    in the library. The Load list is newest first, taken here as the order of the slots' file times; an imported
    save keeps the date it was made inside its caption, so this order can be wrong for one (use the library).
    Errors out when no save has that map."""
    d = HOME.save_dir()
    if not d.is_dir():
        raise SystemExit(f"no saves of the game in {d} (config.json save_dir, under Lichii's data folder): boot the "
                         "game once and save in the area the spec needs (tools/harness/README.md, \"The save\")")
    slots = sorted((x for x in d.glob("slot_*") if (x / "caption.sav").exists()),
                   key=lambda x: (x / "caption.sav").stat().st_mtime, reverse=True)
    for i, sl in enumerate(slots):
        maps = caption_maps(sl / "caption.sav")
        if any(m == name or m.split("/")[1] == name for m in maps):
            return i, sl.name, maps
    raise SystemExit(f"no library save {name!r} in {save_library()} and no save with map {name!r} in {d}. The "
        "saves there, newest first (the Load list's order): " + (", ".join(
        f"{sl.name}={caption_maps(sl / 'caption.sav')}" for sl in slots) or "none") + ". Add a save to the library "
        f"(python3 {HERE / 'ab.py'} --add-save NAME SLOT_DIR, --list-saves lists them), or set \"save\" (a library "
        "name or a map above), \"expect_spawn\" (where Link stands after loading it, or null) and/or \"save_index\" "
        "(a Load-list position, 0 = newest) in config.json or in the spec")


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
                raise RuntimeError(f"wrong save loaded: Link at {p}, expected {spawn} (expect_spawn; null skips the check)")
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
    emulator lock and put back afterwards, also on errors). Waits first for this project's builds to finish, unless
    the spec says "build_wait": false (for runs judged by picture or log, not by frame times)."""
    if spec.get("build_wait", True):
        w = wait_for_builds(spec["label"])
    else:
        w = 0
        if my_builds():
            print(f"{spec['label']}: builds {my_builds()} are running; not waiting (build_wait false), "
                  "frame times will be skewed", flush=True)
    if w > 0:
        print(f"{spec['label']}: waited {w} s for builds", flush=True)
    # A library save: it becomes the game's only save (and stays so after the run; what the run saved is lost
    # with the next run).
    lib = library_save(spec.get("save", CONFIG["save"]))
    if lib:
        stage_save(run_home(spec), lib[0])
    return _cold_or_warm(spec, out, attempt)


def _cold_or_warm(spec, out, attempt):
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
    h = run_home(spec); use_home(h); h.check()
    set_cfg(spec.get("cfg", {}))
    tool_binds_set(h)
    env = dict(os.environ)
    env.update(h.env())                               # a private data root, when the run has one
    env.update({"MVK_P60_NO_APPNAP": "1", "VERIFY_DIR": str(rd), "VERIFY_PORT": str(HOOK_PORT),
                "DYLD_INSERT_LIBRARIES": str(HOOK)})
    if server:
        env.update({"EDEN_NX2_DEBUG_SERVER": "127.0.0.1:6545", "EDEN_NX2_DEBUG_DIR": str(rd / "dumps")})
    env.update({k: str(v).replace("{rd}", str(rd)) for k, v in spec.get("env", {}).items()})
    if spec.get("variants"):
        env["EDEN_NX2_HVF_CTL"] = str(rd / "hvf_ctl.txt")
    app = Path(spec.get("app", DEFAULT_APP))
    res = {"label": spec["label"], "spec": spec, "loadavg_before": os.getloadavg(), "marks": {}}
    if h.root:
        res["home"] = str(h.root)
    old_log_ino = LOG.stat().st_ino if LOG.exists() else None
    with open(rd / "stderr.log", "wb") as err:
        proc = subprocess.Popen([str(app / "Contents/MacOS/lichii"), *spec.get("args", []), str(GAME)], env=env, stdout=err,
                                stderr=subprocess.STDOUT, start_new_session=True)
    emulock.set_lock_lichii(proc.pid)   # so that whoever takes the lock over can stop this Lichii
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
        # Lichii with use_gdbstub waits at boot for a debugger: attach JSDBG/jsdbg.py (lldb), which then
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
    # Every step reported is a sign of progress: it renews the lock's lease (30 minutes, or the spec's "lock_minutes",
    # 5 to 90), so a run that hangs gives the emulator up after that long instead of holding it for ever.
    title = lambda step: (emulock.renew_lock(spec.get("lock_minutes")),
                          hook(f"title {session} \u00b7 {spec['label']} \u00b7 {attempt} \u00b7 {step} \u2016 {desc}"))
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
            lib = library_save(save)
            if lib:                                   # staged by one_run: the only entry in the Load list
                idx = 0; spawn = spec.get("expect_spawn", lib[1].get("expect_spawn"))
                res["save"] = {"name": save, "library": str(lib[0]), "slot": LOAD_SLOT, "list_index": 0,
                               "maps": lib[1].get("maps")}
            elif fixed is not None:                   # fallback: a fixed Load-list position (0 = newest)
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
            if spec.get("resave"):
                # Save again at once, with Link still at the spawn point: the Load list is newest first, so this
                # puts the save back on top. Plus opens the pause menu (Items tab), R moves to System where Save
                # is the first entry, A opens the Save dialog with Cancel selected, Up selects Save, A confirms
                # (it overwrites the slot that was loaded), B closes the menu. Checked through the slot's file.
                cap = HOME.save_dir() / res["save"].get("slot", "") / "caption.sav"
                before = cap.stat().st_mtime if cap.is_file() else None
                step = lambda b, wait: call("input_sequence", steps=[{"buttons": [b], "frames": 4}, {"frames": wait}])
                title("saving again")
                for b, wait in (("Plus", 60), ("R", 40), ("A", 60), ("Up", 30), ("A", 150), ("B", 60)):
                    step(b, wait)
                res["resave"] = {"slot": res["save"].get("slot"), "file_changed": bool(cap.is_file() and cap.stat().st_mtime != before),
                                 "pos_after": pos(actor)}
                if not res["resave"]["file_changed"]:
                    raise RuntimeError(f"resave: {cap} did not change")
            if spec.get("hold_file"):
                # Right after the load, before Link moves: keep the game running for manual debug-server calls while
                # this file exists (at most hold_max_s
                # seconds): prints main's address and Link's object, which dbg.py needs.
                # The file also names this Lichii and the attempt ("2/3 retry" after a crash), so a client can tell
                # that the game it drives was restarted; if Lichii dies while held, HOLD.died says so at once.
                hf = Path(spec["hold_file"]); died = hf.with_name(hf.name + ".died"); died.unlink(missing_ok=True)
                hf.write_text(json.dumps({"main": hex(dbg.MAIN), "actor": hex(actor), "run": str(rd),
                                          "lichii_pid": proc.pid, "attempt": attempt}))
                title("held for manual calls"); print(f"{spec['label']}: held, main {dbg.MAIN:#x}, rm {hf} to go on", flush=True)
                t_hold = time.time()
                while hf.exists() and alive() and time.time() - t_hold < float(spec.get("hold_max_s", 900)):
                    time.sleep(1)
                if not alive() and not killed_by_us:
                    reports = sorted(Path.home().glob("Library/Logs/DiagnosticReports/lichii*.ips"),
                                     key=lambda f: f.stat().st_mtime)
                    report = next((str(f) for f in reversed(reports) if f.stat().st_mtime >= t0 - 5), None)
                    died.write_text(json.dumps({"lichii_pid": proc.pid, "attempt": attempt, "held_s":
                                                round(time.time() - t_hold, 1), "crash_report": report}))
                    print(f"{spec['label']}: Lichii {proc.pid} died while held; crash report {report}", flush=True)
                elif spec.get("after_hold") == "stop":
                    # a manual session: nothing after the hold is wanted (the walk would use a Link that may be gone)
                    raise HoldDone()
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
                path = [[round(v, 2) for v in start]]; turns = []; leash_turns = []; leash_last = 0.0
                while done_f < P:
                    n = min(chunk, P - done_f)
                    call("input_sequence", steps=[{"left_stick": [0, 1], "frames": n}], timeout_s=120)
                    done_f += n; here = pos(actor); path.append([round(v, 2) for v in here])
                    if spec.get("walk_shots"):      # one screenshot per chunk: the walk as a film strip
                        wd = rd / f"{prefix.strip('/') or 'run'}-walk"; wd.mkdir(exist_ok=True)
                        hook(f"shot {wd}/f{len(path) - 2:03d}.png")     # from the window: what is on screen
                    step = sum((x - y) ** 2 for x, y in zip(here, last)) ** 0.5; last = here
                    # "leash_m": also turn round when Link is that far from where the walk began and still moving
                    # away, so a long walk stays in the area instead of leaving the map (which loads another one
                    # and autosaves).
                    away = sum((x - y) ** 2 for x, y in zip(here, start)) ** 0.5
                    leashed = bool(spec.get("leash_m")) and away > float(spec["leash_m"]) and away > leash_last
                    leash_last = away
                    if (step < float(spec.get("bounce_min_m", 0.3)) or leashed) and done_f < P:
                        call("input_sequence", steps=turn, timeout_s=60); turns.append(done_f)
                        if leashed:
                            leash_turns.append(done_f); leash_last = float("inf")   # no second turn until he is nearer
                    if away < float(spec.get("leash_m") or 0) * 0.8:
                        leash_last = 0.0
                res[ph("walk_call")] = {"mode": "bounce", "chunk": chunk, "turns_at_frame": turns, "path": path,
                                        "leash_turns_at_frame": leash_turns,
                                        "max_from_start_m": round(max(sum((x - y) ** 2 for x, y in zip(pt, path[0])) ** 0.5
                                                                      for pt in path), 1)}
                # A walk that stands still measures nothing (Link in an NPC dialog, or stuck where a turn does
                # not free him): three chunks in a row without movement mark the run, and it says so.
                still = [sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5 < float(spec.get("bounce_min_m", 0.3))
                         for a, b in zip(path, path[1:])]
                run = best = at = 0
                for i, st in enumerate(still):
                    run = run + 1 if st else 0
                    if run > best:
                        best, at = run, i - run + 1
                if best >= 3:
                    res[ph("walk_stalled")] = {"chunks": best, "from_frame": at * chunk, "at": path[at]}
                    print(f"{spec['label']}: WALK STALLED for {best} chunks from walk frame {at * chunk} at {path[at]}: "
                          f"its frame times from there are not a walk", flush=True)
                if spec.get("walk_shots"):
                    import speckhunt, whitecount
                    wd = rd / f"{prefix.strip('/') or 'run'}-walk"; time.sleep(0.5); shots = sorted(wd.glob("f*.png"))
                    if shots:
                        speckhunt.record(wd, shots)             # sheet.png and burst.gif of the walk
                        res[ph("walk_white_pct")] = [round(float(whitecount.share(f)) * 100, 3) for f in shots]
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
                wait_frames(int(spec.get("stand_frames", P)), alive)    # a long walk needs no stand as long
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
        if spec.get("at_end"):
            # steps run once Link has stopped where the walk ended (speckhunt.py): window bursts with the
            # white-pixel share, a sheet and a GIF; debug-server calls; shader-reject groups. "flicker" and
            # "capture" run at the spawn instead.
            import speckhunt
            speckhunt.at_end(spec["at_end"], rd, res, call, lambda n: wait_frames(n, alive), title,
                             pos=lambda: pos(actor))
        # Every run: score its end picture for corruption (persist.picture_metrics). "on_corrupt": steps (the same
        # kinds as at_end) run only when it is corrupted, while the game is still up: a GPU trace, a frame capture,
        # whatever can be studied offline afterwards. A fault that shows in one boot in ten is caught this way.
        try:
            import persist
            shot = rd / "run-stand2.png"
            if shot.is_file():
                res["picture"] = persist.picture_metrics(shot)
                # "end_white_max" (a spec key, or config.json's for runs of the default save): a lower limit on
                # clipped-white pixels than picture_metrics' 15 %, for scenes known to have none (the canopy
                # shards of KNOWN-ISSUES KI-29 score 2.6-2.8 % where a clean Kokiri Forest scene scores 0.0).
                limit = spec.get("end_white_max", CONFIG.get("end_white_max") if is_default_save(spec) else None)
                if limit is not None and res["picture"]["clipped_pct"] > float(limit):
                    res["picture"].update(corrupt=True, over_end_white_max=float(limit))
                # "cube_check" (a spec key, or config.json's for runs of the default save): N frame captures in a
                # row, read for the 128x128 lighting cube the game redraws one face a frame. In a boot with the
                # canopy shards of KNOWN-ISSUES KI-29 a face holds values in the thousands where a clean boot stays
                # near 1, whichever way Link faces, so the end picture's view does not matter.
                n_cube = spec.get("cube_check", CONFIG.get("cube_check") if is_default_save(spec) else 0)
                if n_cube:
                    title("cube check")
                    res["cube_check"] = cube_check(call, int(n_cube))
                    if res["cube_check"].get("max", 0) > CUBE_MAX:
                        res["picture"].update(corrupt=True, cube_max=res["cube_check"]["max"])
                # A clean run keeps the cube check's verdict, not its captures ("keep_cube_captures": true keeps them).
                if n_cube and not res["picture"]["corrupt"] and not spec.get("keep_cube_captures"):
                    prune_cube_captures(res["cube_check"], rd)
                if res["picture"]["corrupt"]:
                    print(f"{spec['label']}: CORRUPT PICTURE {res['picture']}", flush=True)
                    steps = spec.get("on_corrupt", CONFIG.get("on_corrupt") if is_default_save(spec) else None)
                    if steps:
                        import speckhunt
                        speckhunt.at_end(steps, rd, res, call, lambda n: wait_frames(n, alive), title)
        except Exception as e:  # scoring must never fail a run
            res["picture_error"] = str(e)
        title("done"); res["outcome"] = "completed"
    except HoldDone:
        title("done"); res["outcome"] = "completed (held, then stopped)"
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
        tool_binds_restore(h)
    fb = rd / "frames.bin"
    ts = list(struct.unpack(f"<{fb.stat().st_size // 8}Q", fb.read_bytes())) if fb.exists() else []
    m = res["marks"]
    for a, b in res.get("phases") or [("stand1", "walk"), ("walk", "stand2"), ("stand2", "end")]:
        if m.get(a, -1) >= 0 and m.get(b, -1) > m[a]:
            res[a] = stats(ts[m[a]:m[b] + 1])
    log_path = rd / "eden_log.txt"
    # The guest's own crash: the Hypervisor backend logs "Unhandled guest exception", the dynarmic JIT
    # "Cannot execute instruction at unmapped address" (a jump into nothing, KNOWN-ISSUES KI-2).
    if res["outcome"] != "completed" and log_path.exists() and \
            any(t in log_path.read_text(errors="replace") for t in GUEST_CRASH_LINES):
        res["outcome"] = "error: guest crashed (" + res["outcome"][7:80] + ")"
    res["loadavg_after"] = os.getloadavg()
    (rd / "result.json").write_text(json.dumps(res, indent=1))
    return res


class HoldDone(Exception):
    """A held run with "after_hold": "stop" ends when the hold does."""


def lichii_running():
    return subprocess.run(["pgrep", "-f", "[l]ichii.app/Contents/MacOS"], capture_output=True, text=True).stdout.split()


def make_master(h, force=False):
    """The harness's master config: a copy of h's qt-config.ini, once it matches config/settings.txt."""
    if lichii_running():
        raise SystemExit("Lichii is running: it rewrites qt-config.ini when it quits; close it first")
    if not h.cfg.exists():
        raise SystemExit(f"no {h.cfg}: start Lichii once (and close it) so it writes its config")
    if h.master.exists() and not force:
        raise SystemExit(f"{h.master} exists; add --force to replace it")
    chk = subprocess.run([sys.executable, str(REPO / "config/apply-settings.py"), "--check", str(h.cfg)],
                         capture_output=True, text=True)
    print(chk.stdout.strip())
    if chk.returncode != 0:
        raise SystemExit(f"{h.cfg} differs from config/settings.txt (above). With Lichii closed, apply them with "
                         f"python3 {REPO / 'config/apply-settings.py'} {h.cfg}, or set them in Lichii, then try again")
    text = h.cfg.read_text()
    if not re.search(r"^player_0_connected=true$", text, re.M):
        print("WARNING: player 1 is not connected (player_0_connected): the debug server's input goes to player 1 or "
              "the handheld controller and fails when neither is connected", flush=True)
    if h.root and h.real_paths_in(h.cfg):
        raise SystemExit(f"{h.cfg} names the real Lichii folders: {h.real_paths_in(h.cfg)[:4]}")
    shutil.copy2(h.cfg, h.master)
    print(f"wrote {h.master}")


def rewrite_real_paths(h, f):
    """Point every setting in f whose value lies under a real Lichii folder at the same place in h's root."""
    lines = f.read_text(errors="surrogateescape").splitlines(keepends=True); done = []
    for i, l in enumerate(lines):
        if "=" not in l:
            continue
        new = l
        for k, real in Home.REAL.items():
            new = re.sub(re.escape(str(real)) + r"(?=/|\"|,|\s|$)", lambda m, k=k: str(h.dirs[k]), new)
        if new != l:
            lines[i] = new; done.append((l.rstrip("\n"), new.rstrip("\n")))
    f.write_text("".join(lines), errors="surrogateescape")
    return done


def make_home(root, with_shader_cache=False):
    """A private Lichii data root at root, from the real folders: the config (qt-config.ini, custom/), the saves and
    the system files (nand/), the practice tool and its data (load/0400486024DEC000/, sdmc/), keys/ if present, and
    the harness master. The shader caches stay empty unless with_shader_cache (APFS clones of the game's folder).
    The real folders are only read."""
    h = Home(root)
    if h.root == Path.home() or any(h.root == r or r in h.root.parents or h.root in r.parents for r in Home.REAL.values()):
        raise SystemExit(f"{h.root} overlaps the real Lichii folders")
    for d in h.dirs.values():
        if d.exists() and any(d.iterdir()):
            raise SystemExit(f"{d} is not empty: make-home only fills a new root")
    if lichii_running():
        raise SystemExit("Lichii is running: close it first (it rewrites its config and caches while it runs)")
    R = Home.REAL
    if not (R["config"] / "qt-config.ini").exists():
        raise SystemExit(f"no {R['config'] / 'qt-config.ini'} to copy")
    for d in h.dirs.values():
        d.mkdir(parents=True, exist_ok=True)
    copied = []

    def copy(src, dst, clone=False):
        if not src.exists():
            return
        dst.parent.mkdir(parents=True, exist_ok=True)
        if clone:                                     # APFS clones: no extra space until one side changes
            subprocess.run(["cp", "-Rc", str(src), str(dst)], check=True)
        elif src.is_dir():
            shutil.copytree(src, dst, symlinks=True)
        else:
            shutil.copy2(src, dst)
        copied.append(dst)

    copy(R["config"] / "qt-config.ini", h.dirs["config"] / "qt-config.ini")
    copy(R["config"] / "custom", h.dirs["config"] / "custom")
    for name in ("nand", "sdmc", "keys", "load/0400486024DEC000"):
        copy(R["data"] / name, h.dirs["data"] / name)
    if with_shader_cache:
        copy(R["cache"] / "shader/0400486024dec000", h.dirs["cache"] / "shader/0400486024dec000", clone=True)
    # The master: the real harness master when there is one (what every real run starts from), else the config
    real_master = R["config"] / MASTER_NAME
    if real_master.exists():
        shutil.copy2(real_master, h.master); copied.append(h.master)
    ini = [h.dirs["config"] / "qt-config.ini", *sorted((h.dirs["config"] / "custom").glob("*.ini"))]
    for f in ini + ([h.master] if h.master.exists() else []):
        for old, new in rewrite_real_paths(h, f):
            print(f"rewrote in {f.name}: {old}\n                    -> {new}")
    if not h.master.exists():
        make_master(h)
    else:
        chk = subprocess.run([sys.executable, str(REPO / "config/apply-settings.py"), "--check", str(h.master)],
                             capture_output=True, text=True)
        print(chk.stdout.strip())
        if chk.returncode != 0:
            raise SystemExit(f"{h.master} differs from config/settings.txt (above)")
    for f in ini + [h.master]:
        bad = h.real_paths_in(f)
        if bad:
            raise SystemExit(f"{f} still names the real folders: {bad[:4]}")
    for c in copied:
        du = subprocess.run(["du", "-sh", str(c)], capture_output=True, text=True).stdout.split("\t")[0]
        print(f"  {du:>6}  {c}")
    print(f"private Lichii data root ready: {h.root} (cache: {'the game' + chr(39) + 's shader folder, cloned' if with_shader_cache else 'empty'})")
    print(f"use it with \"home\": \"{h.root}\" in a spec, or OOT26_LICHII_HOME={h.root}")


def print_paths(h, spec=None):
    """What a run with data root h would read and write; launches nothing."""
    out = {"home": str(h.root) if h.root else None, "env": h.env(), "config": str(h.cfg), "master": str(h.master),
           "master_exists": h.master.exists(), "log": str(h.log), "save_dir": str(h.save_dir()),
           "save_library (shared by every root)": str(save_library()),
           "metal_cache (macOS's, shared by every root)": str(METAL_CACHE), "hook": str(HOOK), "game": str(GAME),
           "app_default": str(DEFAULT_APP)}
    if h.root:
        inside = [str(v) for k, v in out.items() if k in ("config", "master", "log", "save_dir")] + list(h.env().values())
        out["all_inside_root"] = all(Path(x) == h.root or h.root in Path(x).parents for x in inside)
        out["real_paths_in_config"] = h.real_paths_in(h.cfg) + h.real_paths_in(h.master)
    if spec:
        out["runs"] = {s["label"]: {"home": str(run_home(s).root) if run_home(s).root else None,
                                    "app": str(s.get("app", DEFAULT_APP)), "save": s.get("save", CONFIG["save"]),
                                    "library_save": bool(library_save(s.get("save", CONFIG["save"])))} for s in spec}
    print(json.dumps(out, indent=1))


def preflight(spec):
    """Everything a batch needs, checked before the first boot."""
    if GAME is None:
        raise SystemExit("no dump of the game: set OOT26_DUMP to your .nup file, or put *0400486024DEC000*.nup in "
                         "dump/ in this repository or beside it")
    if not HOOK.exists() or HOOK.stat().st_mtime < (REPO / "tools/verify/hook.m").stat().st_mtime:
        subprocess.run([sys.executable, str(REPO / "tools/verify/verify.py"), "build-hook"], check=True)
    for s in spec:
        app = Path(s.get("app", DEFAULT_APP))
        if not (app / "Contents/MacOS/lichii").exists():
            raise SystemExit(f"{s['label']}: no app at {app}" + (" (build it with ./build.sh)" if app == DEFAULT_APP else ""))
        run_home(s).check(launching=False)
        if library_save(s.get("save", CONFIG["save"])) and s.get("resave"):
            raise SystemExit(f"{s['label']}: \"resave\" with library save {s.get('save', CONFIG['save'])!r}: the next "
                             "run replaces the save folder, so keep a save with --add-save instead")
        if s.get("jsdbg") and not (JSDBG / "jsdbg.py").exists():
            raise SystemExit(f"{s['label']}: \"jsdbg\" needs the lldb logger jsdbg.py, which is in the glitch-research "
                             f"repository, not here; set OOT26_JSDBG_DIR to its folder (looked in {JSDBG}). "
                             "Measurement runs do not need it")


def main():
    # Asked to stop (the lock tool passes SIGTERM on, also when the lock is taken over): leave through the `finally`
    # blocks, which kill this run's Lichii and put the config back.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    argv = sys.argv[1:]
    opt = lambda name: argv[argv.index(name) + 1] if name in argv else None
    if "--make-master" in argv:
        return make_master(Home(opt("--home") or os.environ.get("OOT26_LICHII_HOME")), force="--force" in argv)
    if "--make-home" in argv:
        return make_home(opt("--make-home"), with_shader_cache="--with-shader-cache" in argv)
    if "--add-save" in argv:
        i = argv.index("--add-save")
        if len(argv) < i + 3:
            raise SystemExit("usage: ab.py --add-save NAME SLOT_DIR [--spawn X,Y,Z] [--note TEXT] [--force]")
        sp = opt("--spawn")
        return add_save(argv[i + 1], argv[i + 2], [float(v) for v in sp.split(",")] if sp else None, opt("--note"),
                        "--force" in argv)
    if "--list-saves" in argv:
        return list_saves()
    # "${REPO}" in a spec stands for the repository folder, so specs carry no machine-specific paths
    load = lambda f: json.loads(Path(f).read_text().replace("${REPO}", str(REPO)))
    if "--print-paths" in argv:
        files = [a for a in argv if a.endswith(".json")]
        return print_paths(Home(opt("--home") or os.environ.get("OOT26_LICHII_HOME")), load(files[0]) if files else None)
    spec = load(argv[0])
    only = sys.argv[sys.argv.index("--only") + 1:] if "--only" in sys.argv else None
    preflight([s for s in spec if not only or s["label"] in only])
    out = HERE / "runs" / time.strftime("ab-%Y%m%d-%H%M%S"); out.mkdir(parents=True)
    print("out", out, flush=True)
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
            if any(k.endswith("walk_stalled") for k in r):
                row["walk_stalled"] = True
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
