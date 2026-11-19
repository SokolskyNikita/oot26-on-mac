#!/bin/bash
# build-final.sh [BUILD [NAME]]: a test app with the finished Hypervisor change (make-final.py, the same change as
# ../patches/03-hvf-final.patch) linked from an existing Lichii build tree, without touching the source or that tree.
#   ./build-final.sh                                  build/release, hvf-final -> build/hvf/app-hvf-final/lichii.app
#   ./build-final.sh build/release-lto hvf-final-lto  a ThinLTO tree (-mcpu=apple-m4), if one has been configured
# BUILD is relative to the pinned Lichii source, build/src/lichii (made by ./build.sh; $LICHII_SRC for another).
# The two patched .cpp files are compiled with that tree's own flags (patched memory.h first on the include path),
# put into a copy of its libcore.a, and the emulator is linked again. The app is a copy of the pinned app
# build/app/lichii.app with this binary: the same libMoltenVK.dylib (so the shader caches stay valid), the same
# nx2_switches.txt and Info.plist. Work files go to build/hvf/work/.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(git -C "$HERE" rev-parse --show-toplevel)
REL=${1:-build/release}; NAME=${2:-hvf-final}
SRC=${LICHII_SRC:-$REPO/build/src/lichii}; BLD=$SRC/$REL
PINNED=$REPO/build/app/lichii.app
FIN=${FIN:-$REPO/build/hvf/work/final}; WORK=$REPO/build/hvf/work/build-$NAME
log() { echo "[$(date +%H:%M:%S)] $*"; }
[ -f "$BLD/compile_commands.json" ] || { log "no $BLD/compile_commands.json: build Lichii first (./build.sh)"; exit 1; }
[ -x "$PINNED/Contents/MacOS/lichii" ] || { log "no pinned app $PINNED: run ./build.sh"; exit 1; }
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
app=$REPO/build/hvf/app-$NAME/lichii.app
mkdir -p "$REPO/build/hvf/app-$NAME"; rm -rf "$app"
ditto "$PINNED" "$app"
# Signed outside the bundle and copied in: the bundle holds an unsigned text file (nx2_switches.txt), which makes
# signing in place fail.
cp "$WORK/lichii" "$WORK/signed"
codesign --force --sign - --entitlements "$SRC/dist/eglantine.entitlements" "$WORK/signed" 2> /dev/null
cp "$WORK/signed" "$app/Contents/MacOS/lichii"
log "assembled $app (hypervisor entitlement: $(codesign -d --entitlements - "$app/Contents/MacOS/lichii" 2>&1 | grep -c hypervisor), carries the new log text: $(strings -a "$app/Contents/MacOS/lichii" | grep -c 'became GPU-cached while its protection was being lifted'), MoltenVK same as the pinned app: $(cmp -s "$app/Contents/Frameworks/libMoltenVK.dylib" "$PINNED/Contents/Frameworks/libMoltenVK.dylib" && echo yes || echo NO))"
