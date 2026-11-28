#!/usr/bin/env python3
"""Test apps: copies of the pinned app with their own bundle id, for runs of anything that is not the pinned build.

    python3 test_app.py make NAME [--lichii BINARY] [--moltenvk DYLIB] [--home] [--force]
    python3 test_app.py list
    python3 test_app.py clean NAME

make   copies build/app/lichii.app to build/test-apps/NAME/lichii.app, puts the given Lichii binary and MoltenVK
       library in (each optional), sets the bundle id to io.github.zortos293.lichii.NAME and signs a binary it was
       given with the pinned binary's entitlements. macOS keeps one Metal shader cache per bundle id, so the test
       app has its own and cannot evict the pinned app's shaders. It starts empty, so the app's first boot is cold
       (about 100 s for the pinned pipeline file); copying the pinned app's cache in does not help, Metal compiles
       everything again (measured: 2,719 compiles with the copy, 2,724 without). --home also makes the private
       data root build/test-apps/NAME/home (ab.py --make-home --with-shader-cache). Name both in a spec: "app"
       and "home".
list   every Lichii bundle id that has a Metal cache on this Mac: size, last written, stale or not, and its app.
clean  removes build/test-apps/NAME and the Metal cache of its bundle id. An id whose app is gone is cleaned the
       same way (the names `list` prints).

The pipeline file in a data root is valid only for a MoltenVK with the pinned cache id (MOLTENVK_CACHE_ID in
versions.lock): make says so when the library given does not carry it, and the first boot is then cold.
"""
import argparse
import json
import plistlib
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
import metalcache  # noqa: E402

PINNED = REPO / "build/app/lichii.app"
APPS = REPO / "build/test-apps"
NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,30}")
INFO = "test-app.json"


def bundle(name):
    return f"{metalcache.LICHII_ID}.{name}"


def check_name(name):
    if not NAME.fullmatch(name):
        raise SystemExit(f"{name!r}: a name is lower-case letters, digits and '-' (it becomes part of the bundle id)")
    return name


def pinned_cache_id(repo=REPO):
    """MOLTENVK_CACHE_ID of versions.lock: the id Lichii's pipeline file is keyed on."""
    m = re.search(r"^MOLTENVK_CACHE_ID=(\S+)", (Path(repo) / "versions.lock").read_text(), re.M)
    return m.group(1) if m else None


def carries(dylib, cache_id):
    """Whether a MoltenVK library was built with this pipeline cache id (the id is a string in the library)."""
    return bool(cache_id) and cache_id.encode() in Path(dylib).read_bytes()


def running(app):
    out = subprocess.run(["pgrep", "-fl", "[l]ichii.app/Contents/MacOS"], capture_output=True, text=True).stdout
    return str(Path(app)) in out


def sign_binary(binary, pinned):
    """Ad-hoc sign a Lichii binary that replaces the pinned one, with the pinned binary's entitlements (Hypervisor).
    It is signed as a file on its own, outside the app: the app as a whole is not signed again (the harness starts
    the binary directly, and the pinned app's switches file beside it is not a signed resource)."""
    binary = Path(binary)
    ent = binary.with_name(binary.name + ".entitlements.plist")
    xml = subprocess.run(["codesign", "-d", "--entitlements", "-", "--xml", str(Path(pinned) / "Contents/MacOS/lichii")],
                         capture_output=True).stdout
    ent.write_bytes(xml)
    cmd = ["codesign", "--force", "--sign", "-"] + (["--entitlements", str(ent)] if xml.strip() else []) + [str(binary)]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    finally:
        ent.unlink(missing_ok=True)


def make(name, pinned=PINNED, apps=APPS, user_cache=None, lichii=None, moltenvk=None, force=False, do_sign=True,
         cache_id=None):
    """Make the test app; returns what was made (also written beside the app as test-app.json)."""
    check_name(name)
    pinned, folder = Path(pinned), Path(apps) / name
    app = folder / "lichii.app"
    if not (pinned / "Contents/Info.plist").exists():
        raise SystemExit(f"no pinned app at {pinned}: run ./build.sh")
    if app.exists():
        if not force:
            raise SystemExit(f"{app} exists: --force replaces it (its Metal cache and data root are kept)")
        if running(app):
            raise SystemExit(f"{app} is running: stop it first")
        shutil.rmtree(app)
    folder.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ditto", str(pinned), str(app)], check=True)
    if lichii:                                        # signed outside the app, then put in
        staged = folder / "lichii.staged"
        shutil.copy2(lichii, staged)
        if do_sign:
            sign_binary(staged, pinned)
        staged.replace(app / "Contents/MacOS/lichii")
    if moltenvk:
        lib = app / "Contents/Frameworks/libMoltenVK.dylib"
        shutil.copy2(moltenvk, lib)
        if do_sign:
            subprocess.run(["codesign", "--force", "--sign", "-", str(lib)], check=True, capture_output=True)
    plist = app / "Contents/Info.plist"
    with open(plist, "rb") as f:
        info = plistlib.load(f)
    info["CFBundleIdentifier"] = bundle(name)
    with open(plist, "wb") as f:
        plistlib.dump(info, f)
    cache = metalcache.cache_dir(app, user_cache)
    cache_id = cache_id if cache_id is not None else pinned_cache_id()
    lib = app / "Contents/Frameworks/libMoltenVK.dylib"
    made = {"name": name, "bundle_id": bundle(name), "app": str(app), "made": time.strftime("%Y-%m-%d %H:%M:%S"),
            "lichii": str(lichii) if lichii else "pinned", "moltenvk": str(moltenvk) if moltenvk else "pinned",
            "metal_cache": str(cache),
            "pipeline_cache_id_matches": carries(lib, cache_id) if lib.exists() else None}
    (folder / INFO).write_text(json.dumps(made, indent=1))
    return made


def listing(apps=APPS, user_cache=None):
    """One row per Lichii bundle id with a Metal cache, plus test apps that have none yet."""
    uc = Path(user_cache or metalcache.user_cache_dir())
    known = {}
    for f in sorted(Path(apps).glob(f"*/{INFO}")):
        try:
            d = json.loads(f.read_text()); known[d["bundle_id"]] = d
        except (ValueError, KeyError):
            pass
    ids = {p.name for p in uc.glob(f"{metalcache.LICHII_ID}*") if (p / "com.apple.metal").is_dir()} | set(known)
    rows = []
    for bid in sorted(ids):
        cache = uc / bid / "com.apple.metal"
        lists = [f.stat().st_mtime for f in cache.glob("*/*.list")]
        d = known.get(bid)
        rows.append({"name": "(pinned)" if bid == metalcache.LICHII_ID else bid[len(metalcache.LICHII_ID) + 1:],
                     "bundle_id": bid, "cache_mib": metalcache.data_size(cache) >> 20,
                     "written": time.strftime("%Y-%m-%d %H:%M", time.localtime(max(lists))) if lists else None,
                     "stale": metalcache.stale(cache),
                     "app": d["app"] if d and Path(d["app"]).exists() else None})
    return rows


def clean(name, apps=APPS, user_cache=None):
    """Remove the test app's folder and its bundle id's Metal cache; returns what was removed."""
    check_name(name)                                  # never the pinned id: that has no name
    uc = Path(user_cache or metalcache.user_cache_dir())
    folder, cache_home = Path(apps) / name, uc / bundle(name)
    if folder.exists() and running(folder / "lichii.app"):
        raise SystemExit(f"{folder / 'lichii.app'} is running: stop it first")
    removed = []
    for p in (folder, cache_home):
        if p.exists():
            shutil.rmtree(p); removed.append(str(p))
    return removed


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__.split("\n\n", 2)[2])
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("make"); m.add_argument("name")
    m.add_argument("--lichii", type=Path); m.add_argument("--moltenvk", type=Path)
    m.add_argument("--home", action="store_true")
    m.add_argument("--force", action="store_true")
    sub.add_parser("list")
    c = sub.add_parser("clean"); c.add_argument("name")
    a = ap.parse_args()
    if a.cmd == "make":
        made = make(a.name, lichii=a.lichii, moltenvk=a.moltenvk, force=a.force)
        print(json.dumps(made, indent=1))
        if made["pipeline_cache_id_matches"] is False:
            print(f"NOTE: this MoltenVK does not carry the pinned pipeline cache id {pinned_cache_id()}: the pipeline "
                  "file of a data root is not valid for it, and the first boot will be cold")
        home = APPS / a.name / "home"
        if a.home and not home.exists():
            subprocess.run([sys.executable, str(HERE / "ab.py"), "--make-home", str(home), "--with-shader-cache"], check=True)
        print(f'in a spec: "app": "{made["app"]}"' + (f', "home": "{home}"' if home.exists() else
              f'  (no data root yet: --home makes {home})'))
    elif a.cmd == "list":
        rows = listing()
        print(f"{'name':16} {'Metal cache':>11}  {'written':16}  {'stale':5}  app")
        for r in rows:
            print(f"{r['name']:16} {r['cache_mib']:>7} MiB  {r['written'] or '-':16}  {'yes' if r['stale'] else 'no':5}  "
                  f"{r['app'] or ('build/app/lichii.app' if r['name'] == '(pinned)' else '(no app made by test_app.py)')}")
    else:
        removed = clean(a.name)
        print("\n".join(f"removed {p}" for p in removed) or f"nothing to remove for {a.name}")


if __name__ == "__main__":
    main()
