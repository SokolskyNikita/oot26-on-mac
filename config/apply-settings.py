#!/usr/bin/env python3
"""apply-settings.py [--check] [INI]: set Lichii's qt-config.ini to the values in settings.txt.

Run with Lichii closed (it rewrites the file when it quits). --check only prints the differences and exits 1 if
there are any. INI defaults to ~/.config/lichii/qt-config.ini; a copy is kept beside it before any change.
Not covered, set them in Lichii's window: the three built-in add-ons to switch off for this game (Max Resolution,
FPS Unlock, Dynamic FPS) and the controller bindings."""
import datetime, os, re, shutil, sys

args = [a for a in sys.argv[1:] if a != "--check"]
ini = args[0] if args else os.path.expanduser("~/.config/lichii/qt-config.ini")
here = os.path.dirname(os.path.abspath(__file__))
want = dict(l.strip().split("=", 1) for l in open(os.path.join(here, "settings.txt")) if l.strip() and not l.startswith("#"))
s = open(ini).read()
changes, missing = [], []
for k, v in want.items():
    m = re.search(rf"^{re.escape(k)}=(.*)$", s, re.M)
    if not m:
        missing.append(k)
    elif m.group(1) != v:
        changes.append((k, m.group(1), v))
for k, old, new in changes:
    print(f"{k}: {old} -> {new}")
if missing:
    print("not in the ini (left alone):", ", ".join(missing))
if not changes:
    print(f"{ini}: all {len(want) - len(missing)} settings match")
    sys.exit(0)
if "--check" in sys.argv:
    sys.exit(1)
backup = f"{ini}.before-apply-settings-{datetime.datetime.now():%Y%m%d-%H%M%S}"
shutil.copy2(ini, backup)
for k, old, new in changes:
    s = re.sub(rf"^{re.escape(k)}=.*$", f"{k}={new}", s, flags=re.M)
    s = re.sub(rf"^{re.escape(k)}\\default=.*$", lambda m, k=k: k + "\\default=false", s, flags=re.M)
open(ini, "w").write(s)
print("written; previous file kept as", backup)
