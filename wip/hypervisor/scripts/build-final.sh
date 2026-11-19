#!/bin/bash
# build-final.sh BUILD NAME: an app with the finished Hypervisor change (make-final.py) linked from an existing
# Lichii build tree, without touching the shared source or that tree.
#   ./build-final.sh build/release      hvf-final       -> path-60/app-hvf-final
#   ./build-final.sh build/release-lto  hvf-final-lto   -> path-60/app-hvf-final-lto (ThinLTO, -mcpu=apple-m4)
# The two patched .cpp files are compiled with that tree's own flags (patched memory.h first on the include path),
# put into a copy of its libcore.a, and the emulator is linked again. MVK_FROM picks whose libMoltenVK the app
# carries (default app-mvkp2901, see build-apps.sh).
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
P60=${P60:-OLD_REPO/emulator/mvk-mesh/path-60}
REL=$1; NAME=$2
SRC=$P60/lichii; BLD=$SRC/$REL
FIN=${FIN:-$P60/hvfrace-final}; WORK=$FIN/build-$NAME
MVK_FROM=${MVK_FROM:-app-mvkp2901}
log() { echo "[$(date +%H:%M:%S)] $*"; }
[ -f "$FIN/b/src/core/memory.cpp" ] || python3 "$HERE/make-final.py" "$FIN"
rm -rf "$WORK"; mkdir -p "$WORK"
for rel in src/core/arm/hvf/arm_hvf.cpp src/core/memory.cpp; do
  python3 - "$BLD/compile_commands.json" "$SRC/$rel" "$FIN/b/$rel" "$WORK/$(basename $rel).o" "$FIN/b/src" > "$WORK/cc.sh" <<'PY'
import json, shlex, sys, os
db, orig, patched, out, inc = sys.argv[1:]
entry = next(e for e in json.load(open(db)) if e["file"] == orig)
args = [a for a in shlex.split(entry["command"]) if a != "ccache"]
args[args.index("-o") + 1] = out
args[args.index(orig)] = patched
args[1:1] = ["-I", inc, "-iquote", os.path.dirname(orig)]
print("cd", shlex.quote(entry["directory"]), "&&", shlex.join(args))
PY
  nice -n 19 sh "$WORK/cc.sh" 2>&1 | grep -v -e 'Wno-error-all' -e 'warning generated' || true
  [ -s "$WORK/$(basename $rel).o" ] || { log "compile of $rel failed"; exit 1; }
  log "compiled $rel"
done
cp "$BLD/src/core/libcore.a" "$WORK/libcore.a"
(cd "$WORK" && ar r libcore.a ./*.o 2> ar.log && ranlib libcore.a 2>> ar.log)
(cd "$BLD" && ninja -t commands lichii | tail -1) > "$WORK/link.cmd"
python3 - "$WORK/link.cmd" "$WORK/libcore.a" "$WORK/lichii" > "$WORK/link.sh" <<'PY'
import sys
cmd, lib, out = sys.argv[1:]
s = open(cmd).read(); s = s[s.index("/usr/bin/c++"):]; s = s[:s.index(" && ")]
assert s.count(" src/core/libcore.a ") == 1 and s.count(" -o bin/lichii.app/Contents/MacOS/lichii ") == 1
print(s.replace(" src/core/libcore.a ", f" {lib} ").replace(" -o bin/lichii.app/Contents/MacOS/lichii ", f" -o {out} "))
PY
(cd "$BLD" && nice -n 19 sh "$WORK/link.sh" 2>&1 | grep -v 'ld: warning' || true)
[ -s "$WORK/lichii" ] || { log "link failed"; exit 1; }
log "linked ($(stat -f %z "$WORK/lichii") bytes)"
app=$P60/app-$NAME/lichii.app
mkdir -p "$P60/app-$NAME"; rm -rf "$app"
ditto "$BLD/bin/lichii.app" "$app"
cp "$WORK/lichii" "$WORK/signed"
codesign --force --sign - --entitlements "$SRC/dist/eglantine.entitlements" "$WORK/signed" 2> /dev/null
cp "$WORK/signed" "$app/Contents/MacOS/lichii"
mkdir -p "$app/Contents/Frameworks"
cp -p "$P60/$MVK_FROM/lichii.app/Contents/Frameworks/libMoltenVK.dylib" "$app/Contents/Frameworks/libMoltenVK.dylib"
cp "$P60/app-practice/lichii.app/Contents/MacOS/nx2_switches.txt" "$app/Contents/MacOS/"
log "assembled $app (hypervisor entitlement: $(codesign -d --entitlements - "$app/Contents/MacOS/lichii" 2>&1 | grep -c hypervisor), carries the new log text: $(strings -a "$app/Contents/MacOS/lichii" | grep -c 'became GPU-cached while its protection was being lifted'))"
