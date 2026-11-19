#!/bin/bash
# build-test-app.sh: a test app for the walk-tail work, linked from the pinned build trees (./build.sh) with the
# experiment patches below, without touching the pinned source or those trees. Every change is behind a switch
# that is off unless set, so the same app runs the control and the experiment.
#
#   switch                                       patch (patches/experiments/)
#   MVK_FRAMEPROF_DUMP_MS=<ms>                   moltenvk-frameprof-dump-long-buffers-2026-11-19
#   EDEN_NX2_GUEST_THREAD_STATS_SLOW_MS=<ms>     lichii-thread-stats-slow-frames-2026-11-19
#   DYNARMIC_FASTMEM_PATCH=1                     dynarmic-fastmem-patch-to-stub-2026-11-19
#   EDEN_NX2_FASTMEM_NO_RECOMPILE=1              lichii-fastmem-no-recompile-2026-11-19
#   EDEN_NX2_GPU_THREAD_PRIO=1                   lichii-gpu-thread-priority-2026-11-19
#   EDEN_NX2_GPUWAIT_SPIN_US=<us>                lichii-gpuwait-spin-2026-11-19
#   EDEN_NX2_SYNC_PAYLOAD_RELEASE=1              lichii-sync-payload-release-2026-11-19
#   (none: the sync trace's gpuwait event)       lichii-gpuwait-caller-stamp-2026-11-19
# Not built, because they change the same lines as the one above: lichii-query-wait-own-reports-2026-11-19
# (EDEN_NX2_QUERY_WAIT_REPORTS) and lichii-fence-lazy-submit-2026-11-19 (EDEN_NX2_FENCE_LAZY_US), which goes with it.
#
# Output: build/p99probe/app/lichii.app with its own bundle id (its Metal shader cache is its own; the pipeline
# cache id is the pinned one). Work files: build/p99probe/work/. Run it in a private data root:
#   python3 tools/harness/ab.py --make-home build/p99probe/home --with-shader-cache
# and name both in a spec ("app", "home"), as wip/walk-tail/specs/test-app.json does.
set -eu
REPO=$(git -C "$(dirname "$0")" rev-parse --show-toplevel)
EXP=$REPO/patches/experiments
# Physical paths: the build trees' compile commands name their files that way, and build/ may be a link.
LSRC=$(cd "$REPO/build/src/lichii" && pwd -P); LBLD=$LSRC/build/release
MSRC=$(cd "$REPO/build/src/moltenvk" && pwd -P); MBLD=$MSRC/build
PINNED=$REPO/build/app/lichii.app
OUT=$REPO/build/p99probe; WORK=$OUT/work
LICHII_PATCHES="lichii-thread-stats-slow-frames-2026-11-19 dynarmic-fastmem-patch-to-stub-2026-11-19 lichii-fastmem-no-recompile-2026-11-19 lichii-gpu-thread-priority-2026-11-19 lichii-gpuwait-spin-2026-11-19 lichii-gpuwait-caller-stamp-2026-11-19 lichii-sync-payload-release-2026-11-19"
MVK_PATCHES="moltenvk-frameprof-dump-long-buffers-2026-11-19"
# A patched header is only seen by the files that are compiled again: these are the callers of Scheduler::Wait and the file that instantiates the query cache.
HEADER_USERS="src/video_core/renderer_vulkan/vk_query_cache.cpp src/video_core/renderer_vulkan/nx2_list_slots.cpp src/video_core/renderer_vulkan/vk_blit_screen.cpp src/video_core/renderer_vulkan/vk_buffer_cache.cpp src/video_core/renderer_vulkan/vk_descriptor_buffer.cpp src/video_core/renderer_vulkan/vk_fence_manager.cpp src/video_core/renderer_vulkan/vk_scheduler.cpp src/video_core/renderer_vulkan/vk_staging_buffer_pool.cpp src/video_core/renderer_vulkan/vk_swapchain.cpp"
log() { echo "[$(date +%H:%M:%S)] $*"; }
[ -f "$LBLD/compile_commands.json" ] || { log "no $LBLD/compile_commands.json: run ./build.sh first"; exit 1; }
[ -x "$PINNED/Contents/MacOS/lichii" ] || { log "no pinned app $PINNED: run ./build.sh"; exit 1; }
pgrep -f "[p]99probe/app/lichii.app" > /dev/null && { log "the test app is running: stop it first"; exit 1; }
rm -rf "$WORK"; mkdir -p "$WORK/lichii" "$WORK/moltenvk" "$WORK/obj" "$WORK/mobj"

# --- overlays: the files each patch touches, copied from the pinned tree and patched there
overlay() { # tree overlay patch...
  local tree=$1 over=$2 p rel; shift 2
  for p in "$@"; do
    for rel in $(sed -n 's#^--- a/##p' "$EXP/$p.patch"); do
      [ -e "$over/$rel" ] || { mkdir -p "$over/$(dirname "$rel")"; cp "$tree/$rel" "$over/$rel"; }
    done
    patch -s -p1 -d "$over" < "$EXP/$p.patch" || { log "$p.patch did not apply"; exit 1; }
  done
}
overlay "$LSRC" "$WORK/lichii" $LICHII_PATCHES
overlay "$MSRC" "$WORK/moltenvk" $MVK_PATCHES
log "patched copies in $WORK/lichii and $WORK/moltenvk"

# --- Lichii: compile every patched .cpp and every user of a patched header, with the overlay first on the include path
python3 - "$LBLD/compile_commands.json" "$LSRC" "$WORK" $HEADER_USERS > "$WORK/cc.list" <<'PY'
import json, os, shlex, sys
db, lsrc, work = sys.argv[1:4]; users = sys.argv[4:]
db = json.load(open(db)); over = work + "/lichii"
rels = [os.path.relpath(os.path.join(d, f), over) for d, _, fs in os.walk(over) for f in fs if f.endswith(".cpp")]
for rel in sorted(set(rels) | set(users)):
    orig = f"{lsrc}/{rel}"
    e = next(x for x in db if x["file"] == orig)
    a = [x for x in shlex.split(e["command"]) if x != "ccache"]
    src = f"{over}/{rel}" if os.path.exists(f"{over}/{rel}") else orig
    # where the build tree keeps this object says which library it belongs to (two libraries can hold the same name)
    print(os.path.basename(rel) + ".o", a[a.index("-o") + 1], file=open(f"{work}/obj.map", "a"))
    a[a.index("-o") + 1] = f"{work}/obj/{os.path.basename(rel)}.o"
    a[a.index(orig)] = src
    a[1:1] = ["-I", over + "/src", "-iquote", os.path.dirname(orig)]
    print("cd " + shlex.quote(e["directory"]) + " && " + shlex.join(a))
PY
n=0; while IFS= read -r line; do n=$((n + 1)); ( nice -n 19 sh -c "$line" > "$WORK/obj/job$n.log" 2>&1 || echo "$n" >> "$WORK/cc.failed" ) & done < "$WORK/cc.list"; wait
[ ! -e "$WORK/cc.failed" ] || { log "compile failed:"; grep -h 'error' "$WORK"/obj/job*.log | head -12; exit 1; }
log "compiled $(ls "$WORK"/obj/*.o | wc -l | tr -d ' ') Lichii files"

# --- each object replaces its namesake in a copy of the library that holds it; the emulator is linked from the copies
(cd "$LBLD" && ninja -t commands lichii | tail -1) > "$WORK/link.cmd"
python3 - "$WORK/link.cmd" "$WORK" "$LBLD" > "$WORK/link.sh" <<'PY'
import os, re, subprocess, sys
cmd, work, bld = sys.argv[1:]
s = open(cmd).read(); s = s[s.index("/usr/bin/c++"):]; s = s[:s.index(" && ")]
libs = [x for x in re.findall(r" (\S+\.a)(?= )", s) if not x.startswith("/")]
members = {lib: set(subprocess.run(["ar", "t", f"{bld}/{lib}"], capture_output=True, text=True).stdout.split()) for lib in libs}
used = {}
built_at = dict(l.split() for l in open(work + "/obj.map"))
for o in sorted(f for f in os.listdir(work + "/obj") if f.endswith(".o")):
    homes = [lib for lib in libs if o in members[lib] and built_at[o].startswith(os.path.dirname(lib) + "/")]
    if len(homes) > 1:   # nested library folders: the deepest one holds it
        homes = [max(homes, key=lambda lib: len(os.path.dirname(lib)))]
    assert len(homes) == 1, (o, homes)
    used.setdefault(homes[0], []).append(o)
for lib, objs in used.items():
    copy = f"{work}/{os.path.basename(lib)}"
    subprocess.run(["cp", f"{bld}/{lib}", copy], check=True)
    subprocess.run(["ar", "r", copy] + [f"{work}/obj/{o}" for o in objs], check=True, capture_output=True)
    subprocess.run(["ranlib", copy], check=True, capture_output=True)
    assert s.count(f" {lib} ") == 1, lib
    s = s.replace(f" {lib} ", f" {copy} ")
    print(f"# {lib}: {' '.join(objs)}", file=sys.stderr)
out = " -o bin/lichii.app/Contents/MacOS/lichii "
assert s.count(out) == 1
print(s.replace(out, f" -o {work}/lichii.bin "))
PY
(cd "$LBLD" && nice -n 19 sh "$WORK/link.sh" 2>&1 | grep -v 'ld: warning' || true)
[ -f "$WORK/lichii.bin" ] && [ -s "$WORK/lichii.bin" ] || { log "Lichii link failed"; exit 1; }
log "Lichii linked ($(stat -f %z "$WORK/lichii.bin") bytes; pinned $(stat -f %z "$PINNED/Contents/MacOS/lichii"))"

# --- MoltenVK: the same for its patched files
(cd "$MBLD" && ninja -t commands) > "$WORK/mvk.cmds"
python3 - "$WORK/mvk.cmds" "$MSRC" "$WORK" > "$WORK/mvk.sh" <<'PY'
import os, shlex, sys
cmds, msrc, work = sys.argv[1:]
lines = open(cmds).read().splitlines(); over = work + "/moltenvk"
ld = [l for l in lines if "-dynamiclib" in l and "libMoltenVK" in l]
assert len(ld) == 1
s = ld[0]; s = s[s.index("/usr/bin/c++"):]; s = s[:s.rindex(" && :")]
for d, _, fs in os.walk(over):
    for f in fs:
        if not f.endswith((".mm", ".cpp", ".m")):
            continue
        rel = os.path.relpath(os.path.join(d, f), over); orig = f"{msrc}/{rel}"
        cc = [l for l in lines if l.rstrip().endswith("-c " + orig)]
        assert len(cc) == 1, rel
        a = shlex.split(cc[0]); obj = a[a.index("-o") + 1]; new = f"{work}/mobj/{f}.o"
        a[a.index("-o") + 1] = new; a[a.index(orig)] = f"{over}/{rel}"; a[1:1] = ["-iquote", os.path.dirname(orig)]
        print(shlex.join(a))
        assert s.count(" " + obj + " ") == 1, obj
        s = s.replace(" " + obj + " ", f" {new} ")
out = [x for x in shlex.split(s) if x.endswith(".dylib") and "MoltenVK/libMoltenVK" in x][0]
print(s.replace(f" -o {out} ", f" -o {work}/libMoltenVK.dylib "))
PY
(cd "$MBLD" && nice -n 19 sh -e "$WORK/mvk.sh" 2>&1 | grep -v 'ld: warning' || true)
[ -s "$WORK/libMoltenVK.dylib" ] || { log "MoltenVK link failed"; exit 1; }
log "MoltenVK linked ($(stat -f %z "$WORK/libMoltenVK.dylib") bytes; pinned $(stat -f %z "$PINNED/Contents/Frameworks/libMoltenVK.dylib"))"

# --- the app: a copy of the pinned app with this binary, this library and its own bundle id
app=$OUT/app/lichii.app
rm -rf "$OUT/app"; mkdir -p "$OUT/app"
ditto "$PINNED" "$app"
cp "$WORK/lichii.bin" "$WORK/signed"
codesign --force --sign - --entitlements "$LSRC/dist/eglantine.entitlements" "$WORK/signed" 2> "$WORK/codesign.log" || { cat "$WORK/codesign.log"; exit 1; }
cp "$WORK/signed" "$app/Contents/MacOS/lichii"
cp "$WORK/libMoltenVK.dylib" "$app/Contents/Frameworks/libMoltenVK.dylib"
codesign --force --sign - "$app/Contents/Frameworks/libMoltenVK.dylib" 2>> "$WORK/codesign.log"
/usr/libexec/PlistBuddy -c 'Set :CFBundleIdentifier io.github.zortos293.lichii.p99probe' "$app/Contents/Info.plist"
found=0
SWITCHES=0
for sw in MVK_FRAMEPROF_DUMP_MS EDEN_NX2_GUEST_THREAD_STATS_SLOW_MS DYNARMIC_FASTMEM_PATCH EDEN_NX2_FASTMEM_NO_RECOMPILE EDEN_NX2_GPU_THREAD_PRIO EDEN_NX2_GPUWAIT_SPIN_US EDEN_NX2_SYNC_PAYLOAD_RELEASE; do
  if strings -a "$app/Contents/MacOS/lichii" "$app/Contents/Frameworks/libMoltenVK.dylib" | grep -qx "$sw"; then found=$((found + 1)); fi; SWITCHES=$((SWITCHES + 1)); if ! strings -a "$app/Contents/MacOS/lichii" "$app/Contents/Frameworks/libMoltenVK.dylib" | grep -qx "$sw"; then log "switch $sw is not in the app"; fi
done
log "assembled $app: $found of $SWITCHES switches present"
log "  lichii      $(shasum "$app/Contents/MacOS/lichii" | cut -c1-12) (pinned $(shasum "$PINNED/Contents/MacOS/lichii" | cut -c1-12))"
log "  libMoltenVK $(shasum "$app/Contents/Frameworks/libMoltenVK.dylib" | cut -c1-12) (pinned $(shasum "$PINNED/Contents/Frameworks/libMoltenVK.dylib" | cut -c1-12))"
[ "$found" = "$SWITCHES" ]
