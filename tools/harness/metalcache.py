#!/usr/bin/env python3
"""macOS's Metal shader cache of a Lichii app, and whether a boot from it is cold.

    python3 metalcache.py [APP ...]      # each app's cache: size, stamps, stale or not (default: the pinned app)

macOS keeps one Metal cache per bundle id: $(getconf DARWIN_USER_CACHE_DIR)<bundle id>/com.apple.metal/, with
<n>/functions.{list,data} and <n>/libraries.{list,data}. Bytes 4-36 of each .list file are a stamp of the system
that wrote it. A macOS update changes the stamp, and Metal then drops every entry written under the old one: the
next boot of each app compiles all its shaders again, with nothing in Lichii's log to say so.

A boot is called cold when the spec asked for an empty cache, the cache is empty, its stamp is stale (another
Lichii app's cache, written later, carries a different one) or changed during the run, or Metal's compiler was
asked for more than COLD_REQUESTS builds during the boot and load. Every function here takes its paths as
arguments and launches nothing, so tests/test_metalcache.py checks them without the emulator.
"""
import json
import plistlib
import re
import subprocess
import sys
import time
from pathlib import Path

LICHII_ID = "io.github.zortos293.lichii"   # the pinned app's bundle id; test apps append ".name"
COLD_REQUESTS = 500   # compiler requests during boot and load above which a boot is cold (pinned build: 1 warm, 2,724 cold)


def user_cache_dir():
    return Path(subprocess.run(["getconf", "DARWIN_USER_CACHE_DIR"], capture_output=True, text=True).stdout.strip())


def bundle_id(app):
    """The app's bundle id, from its Info.plist."""
    with open(Path(app) / "Contents/Info.plist", "rb") as f:
        return plistlib.load(f)["CFBundleIdentifier"]


def cache_dir(app, user_cache=None):
    """The Metal cache macOS keeps for this app."""
    return Path(user_cache or user_cache_dir()) / bundle_id(app) / "com.apple.metal"


def data_size(cache):
    """Bytes of compiled shaders in the cache; 0 when there is none."""
    try:
        return sum(f.stat().st_size for f in Path(cache).glob("*/*.data"))
    except OSError:
        return 0


def stamps(cache):
    """{"functions": hex, "libraries": hex}: the system stamp of each .list file (bytes 4-36)."""
    out = {}
    for f in sorted(Path(cache).glob("*/*.list")):
        try:
            with open(f, "rb") as fh:
                head = fh.read(36)
        except OSError:
            continue
        if len(head) == 36:
            out[f.stem] = head[4:36].hex()
    return out


def _written(cache):
    """When the cache's .list files were last written; 0 when it has none."""
    return max((f.stat().st_mtime for f in Path(cache).glob("*/*.list")), default=0)


def stale(cache):
    """True when another Lichii app's Metal cache, written later than this one, carries a different stamp: the
    system changed in between, and Metal will drop this cache's entries at the next boot."""
    cache = Path(cache)
    own, own_t = stamps(cache), _written(cache)
    if not own:
        return False
    for other in cache.parent.parent.glob(f"{LICHII_ID}*/com.apple.metal"):
        if other == cache or _written(other) <= own_t:
            continue
        theirs = stamps(other)
        if any(k in theirs and theirs[k] != v for k, v in own.items()):
            return True
    return False


def macos_build():
    return subprocess.run(["sw_vers", "-buildVersion"], capture_output=True, text=True).stdout.strip()


def snapshot(app, user_cache=None):
    """The state of the app's cache now, for result.json."""
    cache = cache_dir(app, user_cache)
    return {"bundle_id": bundle_id(app), "dir": str(cache), "data_mib": data_size(cache) >> 20,
            "stamps": stamps(cache), "stale": stale(cache)}


def expect_cold(before, spec_cold=False):
    """Why this boot will be cold, known before it starts; None when nothing says so."""
    if spec_cold:
        return "empty Metal cache (cold_metal_cache)"
    if not before["stamps"] or before["data_mib"] < 1:
        return "empty Metal cache"
    if before["stale"]:
        return "Metal cache reset (macOS update)"
    return None


def count_requests(lines, parent):
    """Compiler requests made for one process, in `log show --style ndjson` lines of MTLCompilerService:
    "Compilation BEGIN (ParentProcessName=lichii_1234) Build request: ...". parent is "lichii_1234"."""
    needle = f"(ParentProcessName={parent})"
    n = 0
    for line in lines:
        if needle not in line:
            continue
        try:
            msg = json.loads(line).get("eventMessage", "")
        except ValueError:
            continue
        if msg.startswith("Compilation BEGIN") and needle in msg:
            n += 1
    return n


def compile_requests(pid, t_start, t_end, name="lichii"):
    """How many builds Metal's compiler service did for process `name` (pid) between two time.time() values:
    every one is a shader the Metal cache did not have. None when the system log cannot be read."""
    fmt = lambda t: time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t))
    try:
        out = subprocess.run(
            ["/usr/bin/log", "show", "--start", fmt(t_start - 1), "--end", fmt(t_end + 1), "--style", "ndjson",
             "--predicate", 'process == "MTLCompilerService" AND eventMessage CONTAINS "Compilation BEGIN"'],
            capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    return count_requests(out.stdout.splitlines(), f"{name}_{pid}")


def verdict(before, after, requests_boot, spec_cold=False):
    """{"cold": bool, "reasons": [...]} for a finished run. before / after: snapshot()s; requests_boot: compiler
    requests during boot and load (None when unknown)."""
    reasons = []
    pre = expect_cold(before, spec_cold)
    if pre:
        reasons.append(pre)
    changed = [k for k, v in before["stamps"].items() if after["stamps"].get(k) not in (None, v)]
    if changed and "Metal cache reset (macOS update)" not in reasons:
        reasons.append("Metal cache reset (macOS update)")
    if requests_boot is not None and requests_boot > COLD_REQUESTS:
        reasons.append(f"{requests_boot:,} shaders compiled during boot and load")
    return {"cold": bool(reasons), "reasons": reasons}


def progress_text(stderr_tail):
    """Shader progress in the tail of Lichii's stderr during a boot: mesh shaders made and the pipeline file's
    load, as title parts."""
    parts = []
    m = re.findall(r"\((\d+) mesh shaders so far\)", stderr_tail)
    if m:
        parts.append(f"{m[-1]} mesh")
    m = re.findall(r"pipeline cache load (\d+) libraries, (\d+)%", stderr_tail)
    if m:
        parts.append(f"pipeline cache {m[-1][1]}% ({int(m[-1][0]):,} libraries)")
    return parts


def main():
    apps = [Path(a) for a in sys.argv[1:]] or [Path(__file__).resolve().parents[2] / "build/app/lichii.app"]
    print("macOS build", macos_build())
    for app in apps:
        s = snapshot(app)
        print(json.dumps(dict(s, app=str(app), expect_cold=expect_cold(s)), indent=1))


if __name__ == "__main__":
    main()
