#!/bin/bash
# Builds the test apps for the Hypervisor cache-window race without touching the pinned Lichii
# source (build/src/lichii) or its build tree (build/release): the patched files are compiled from
# copies, put into a copy of libcore.a, and the emulator is linked again from build/release's other
# objects. Apps go to build/hvf/app-hvfrace-NAME/lichii.app, work files to build/hvf/work/race.
#
#   app-hvfrace-base   build/release as it is (the reference for the ones below)
#   app-hvfrace-diag   + 01-count-dropped-protection.patch (logs the race)
#   app-hvfrace-fix    + both patches (logs, and marks pages before protecting them)
#   app-hvfrace-fast   + both patches and the Hypervisor speed experiments of 2026-11-17 (burst, loop
#                      runner, dirty-only write-back; each off unless its EDEN_NX2_HVF_* switch is set)
#
# Every app is a copy of the pinned app build/app/lichii.app with its own binary, so it carries the
# pinned libMoltenVK.dylib: the Metal cache depends on the MoltenVK binary, and a different one makes
# the next boot compile every shader again.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(git -C "$HERE" rev-parse --show-toplevel)
PATCHES=$HERE/../patches
SPEED=${SPEED:-$REPO/patches/experiments/hvf-experiments-2026-11-17.patch}
SRC=${LICHII_SRC:-$REPO/build/src/lichii}
BLD=$SRC/build/release
PINNED=$REPO/build/app/lichii.app
OUT=$REPO/build/hvf
WORK=${WORK:-$OUT/work/race}
log() { echo "[$(date +%H:%M:%S)] $*"; }
[ -f "$BLD/compile_commands.json" ] || { log "no $BLD/compile_commands.json: build Lichii first (./build.sh)"; exit 1; }
[ -x "$PINNED/Contents/MacOS/lichii" ] || { log "no pinned app $PINNED: run ./build.sh"; exit 1; }

rm -rf "$WORK"; mkdir -p "$WORK/diag/src/core/arm/hvf" "$WORK/fix/src/core/arm/hvf" "$WORK/fix/src/core"
cp "$SRC/src/core/arm/hvf/arm_hvf.cpp" "$WORK/diag/src/core/arm/hvf/"
cp "$SRC/src/core/arm/hvf/arm_hvf.cpp" "$SRC/src/core/memory.cpp" "$WORK/fix/src/core/" 2>/dev/null
mv "$WORK/fix/src/core/arm_hvf.cpp" "$WORK/fix/src/core/arm/hvf/"
(cd "$WORK/diag" && patch -s -p1 < "$PATCHES/01-count-dropped-protection.patch")
(cd "$WORK/fix" && patch -s -p1 < "$PATCHES/01-count-dropped-protection.patch" &&
                   patch -s -p1 < "$PATCHES/02-mark-before-protect.patch")

mkdir -p "$WORK/fast/src/core/arm/hvf"
cp "$SRC/src/core/arm/hvf/arm_hvf.cpp" "$WORK/fast/src/core/arm/hvf/"
cp "$SRC/src/core/memory.cpp" "$WORK/fast/src/core/"
(cd "$WORK/fast" && patch -s -p1 < "$SPEED" && patch -s -p1 < "$PATCHES/01-count-dropped-protection.patch" &&
                    patch -s -p1 < "$PATCHES/02-mark-before-protect.patch")

# compile FILE(relative to the source root) TREE -> $WORK/TREE/<name>.o, with the build's own flags
compile() {
  local rel=$1 tree=$2 out
  out=$WORK/$tree/$(basename "$rel").o
  python3 - "$BLD/compile_commands.json" "$SRC/$rel" "$WORK/$tree/$rel" "$out" > "$WORK/$tree/cc.sh" <<'EOF'
import json, shlex, sys, os
db, orig, patched, out = sys.argv[1:]
entry = next(e for e in json.load(open(db)) if e["file"] == orig)
args = shlex.split(entry["command"])
args = [a for a in args if a != "ccache"]
i = args.index("-o"); args[i + 1] = out
args[args.index(orig)] = patched
args[1:1] = ["-iquote", os.path.dirname(orig)]
print("cd", shlex.quote(entry["directory"]), "&&", shlex.join(args))
EOF
  nice -n 19 sh "$WORK/$tree/cc.sh"
  log "compiled $tree/$rel"
}
compile src/core/arm/hvf/arm_hvf.cpp diag
compile src/core/arm/hvf/arm_hvf.cpp fix
compile src/core/memory.cpp fix
compile src/core/arm/hvf/arm_hvf.cpp fast
compile src/core/memory.cpp fast

# The link command of build/release, with another libcore.a and another output.
(cd "$BLD" && ninja -t commands lichii | tail -1) > "$WORK/link.cmd"
link() {  # TREE
  local tree=$1
  cp "$BLD/src/core/libcore.a" "$WORK/$tree/libcore.a"
  (cd "$WORK/$tree" && ar r libcore.a ./*.o 2> ar.log && ranlib libcore.a 2>> ar.log)
  python3 - "$WORK/link.cmd" "$WORK/$tree/libcore.a" "$WORK/$tree/lichii" > "$WORK/$tree/link.sh" <<'EOF'
import sys
cmd, lib, out = sys.argv[1:]
s = open(cmd).read()
s = s[s.index("/usr/bin/c++"):]          # drop the leading ": &&"
s = s[:s.index(" && ")]                   # drop the post-link copies and signing
assert s.count(" src/core/libcore.a ") == 1 and s.count(" -o bin/lichii.app/Contents/MacOS/lichii ") == 1
s = s.replace(" src/core/libcore.a ", f" {lib} ").replace(
    " -o bin/lichii.app/Contents/MacOS/lichii ", f" -o {out} ")
print(s)
EOF
  (cd "$BLD" && nice -n 19 sh "$WORK/$tree/link.sh")
  log "linked $tree ($(stat -f %z "$WORK/$tree/lichii") bytes)"
}
link diag
link fix
link fast

assemble() {  # NAME BINARY
  local app=$OUT/app-hvfrace-$1/lichii.app
  mkdir -p "$OUT/app-hvfrace-$1"; rm -rf "$app"
  ditto "$PINNED" "$app"
  # Signed outside the bundle and copied in, as the build does: the bundle holds an unsigned
  # text file, which makes signing in place fail.
  cp "${2:-$BLD/bin/lichii.app/Contents/MacOS/lichii}" "$WORK/signed-$1"
  codesign --force --sign - --entitlements "$SRC/dist/eglantine.entitlements" "$WORK/signed-$1" 2> /dev/null
  cp "$WORK/signed-$1" "$app/Contents/MacOS/lichii"
  log "assembled $app (hypervisor entitlement: $(codesign -d --entitlements - "$app/Contents/MacOS/lichii" 2>&1 | grep -c hypervisor), MoltenVK same as the pinned app: $(cmp -s "$app/Contents/Frameworks/libMoltenVK.dylib" "$PINNED/Contents/Frameworks/libMoltenVK.dylib" && echo yes || echo NO))"
}
assemble base ""
assemble diag "$WORK/diag/lichii"
assemble fix "$WORK/fix/lichii"
assemble fast "$WORK/fast/lichii"
strings -a "$OUT/app-hvfrace-diag/lichii.app/Contents/MacOS/lichii" | grep -c 'Protection dropped on a page that is GPU-cached' | sed 's/^/diag binary carries the warning text: /'
log "done"
