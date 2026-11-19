#!/bin/bash
# p99probe-build.sh: a test app for the walk p99 work, linked from the pinned build trees without touching the pinned
# source or those trees. Two changes:
#   MoltenVK frame profiler: MVK_FRAMEPROF_DUMP_MS=<ms> also writes the per-encoder E records of every command
#     buffer whose GPU interval is at least that long (the pinned profiler writes them for every 150th frame only).
#   Lichii guest thread statistics: EDEN_NX2_GUEST_THREAD_STATS_SLOW_MS=<ms> makes each report window one
#     present-to-present interval and logs only windows at least that long.
# Output: build/p99probe/app/lichii.app with its own bundle id. Work files: build/p99probe/work/.
set -eu
REPO=$(git -C "$(dirname "$0")" rev-parse --show-toplevel)
LSRC=$REPO/build/src/lichii; LBLD=$LSRC/build/release
MSRC=$REPO/build/src/moltenvk; MBLD=$MSRC/build
PINNED=$REPO/build/app/lichii.app
OUT=$REPO/build/p99probe; WORK=$OUT/work
log() { echo "[$(date +%H:%M:%S)] $*"; }
rm -rf "$WORK"; mkdir -p "$WORK/src"

python3 - "$LSRC" "$MSRC" "$WORK/src" <<'PY'
import sys
from pathlib import Path
lsrc, msrc, out = map(Path, sys.argv[1:])

def patch(src, dst, edits):
    s = src.read_text()
    for old, new in edits:
        assert s.count(old) == 1, (src.name, old[:60], s.count(old))
        s = s.replace(old, new)
    dst.write_text(s)

patch(msrc / "MoltenVK/MoltenVK/Utility/MVKFrameProf.mm", out / "MVKFrameProf.mm", [
    ("\tbool dump = (r->frame % 150) == 0;\n",
     "\tstatic const double dumpSec = [] { const char* v = getenv(\"MVK_FRAMEPROF_DUMP_MS\"); return v ? atof(v) / 1e3 : 0.0; }();\n"
     "\tbool dump = (r->frame % 150) == 0 || (dumpSec > 0 && gpuEnd - gpuStart >= dumpSec);\n"),
])
patch(lsrc / "src/core/hle/kernel/nx2_thread_stats.cpp", out / "nx2_thread_stats.cpp", [
    ("constexpr u64 ReportSeconds = 10;\n",
     "constexpr u64 ReportSeconds = 10;\n"
     "// Test build: EDEN_NX2_GUEST_THREAD_STATS_SLOW_MS=<ms> makes each window one present-to-present interval\n"
     "// and logs only windows at least that long.\n"
     "const double g_slow_ms = [] {\n"
     "    const char* value = std::getenv(\"EDEN_NX2_GUEST_THREAD_STATS_SLOW_MS\");\n"
     "    return value ? std::strtod(value, nullptr) : 0.0;\n"
     "}();\n"),
    ("    LOG_INFO(Kernel, \"Guest threads over {:.1f} s, {} presents, {} threads ran; ms per frame:\",\n"
     "             seconds, presents, rows.size());\n",
     "    const bool quiet = g_slow_ms > 0 && seconds * 1e3 < g_slow_ms;\n"
     "    if (!quiet) {\n"
     "        LOG_INFO(Kernel, \"Guest threads over {:.4f} s, {} presents, {} threads ran; ms per frame:\",\n"
     "                 seconds, presents, rows.size());\n"
     "    }\n"),
    ("        const auto& d = rows[i].delta;\n        if (i >= ReportThreads && d[Presents] == 0) {\n",
     "        if (quiet) {\n            break;\n        }\n"
     "        const auto& d = rows[i].delta;\n        if (i >= ReportThreads && d[Presents] == 0) {\n"),
    ("        if (exits == 0) {\n            continue;\n        }\n",
     "        if (exits == 0 || quiet) {\n            continue;\n        }\n"),
    ("    g_next_report.store(now + ReportSeconds * Common::g_wall_clock.GetGuestCNTFRQ(),\n"
     "                        std::memory_order_relaxed);\n",
     "    g_next_report.store(g_slow_ms > 0 ? ~u64{0}\n"
     "                                      : now + ReportSeconds * Common::g_wall_clock.GetGuestCNTFRQ(),\n"
     "                        std::memory_order_relaxed);\n"),
    ("    g_presents.fetch_add(1, std::memory_order_relaxed);\n    if (Counters* c = Get(client)) {\n",
     "    g_presents.fetch_add(1, std::memory_order_relaxed);\n"
     "    if (g_slow_ms > 0) {\n        g_next_report.store(1, std::memory_order_relaxed);\n    }\n"
     "    if (Counters* c = Get(client)) {\n"),
])
PY
log "patched copies written to $WORK/src"

# --- MoltenVK: compile the one file, relink the library elsewhere
MORIG=$MSRC/MoltenVK/MoltenVK/Utility/MVKFrameProf.mm
(cd "$MBLD" && ninja -t commands) > "$WORK/mvk.cmds"
python3 - "$WORK/mvk.cmds" "$MORIG" "$WORK/src/MVKFrameProf.mm" "$WORK/MVKFrameProf.mm.o" "$WORK/libMoltenVK.dylib" > "$WORK/mvk.sh" <<'PY'
import sys, shlex, os
cmds, orig, patched, obj, lib = sys.argv[1:]
lines = open(cmds).read().splitlines()
cc = [l for l in lines if l.rstrip().endswith("-c " + orig)]
assert len(cc) == 1, len(cc)
a = shlex.split(cc[0])
a[a.index("-o") + 1] = obj
a[a.index(orig)] = patched
a[1:1] = ["-iquote", os.path.dirname(orig)]
print(shlex.join(a))
ld = [l for l in lines if "-dynamiclib" in l and "libMoltenVK" in l]
assert len(ld) == 1, len(ld)
s = ld[0]; s = s[s.index("/usr/bin/c++"):]; s = s[:s.rindex(" && :")]
old = "MoltenVK/CMakeFiles/MoltenVK.dir/MoltenVK/Utility/MVKFrameProf.mm.o"
assert s.count(" " + old + " ") == 1 and s.count(" -o MoltenVK/libMoltenVK.1.4.3.dylib ") == 1
print(s.replace(" " + old + " ", f" {obj} ").replace(" -o MoltenVK/libMoltenVK.1.4.3.dylib ", f" -o {lib} "))
PY
(cd "$MBLD" && nice -n 19 sh -e "$WORK/mvk.sh" 2>&1 | grep -v 'ld: warning' || true)
[ -s "$WORK/libMoltenVK.dylib" ] || { log "MoltenVK link failed"; exit 1; }
log "MoltenVK linked ($(stat -f %z "$WORK/libMoltenVK.dylib") bytes; pinned $(stat -f %z "$PINNED/Contents/Frameworks/libMoltenVK.dylib")); carries the switch: $(strings -a "$WORK/libMoltenVK.dylib" | grep -c MVK_FRAMEPROF_DUMP_MS)"

# --- Lichii: compile the one file into a copy of libcore.a, relink the emulator elsewhere
LORIG=$LSRC/src/core/hle/kernel/nx2_thread_stats.cpp
python3 - "$LBLD/compile_commands.json" "$LORIG" "$WORK/src/nx2_thread_stats.cpp" "$WORK/nx2_thread_stats.cpp.o" > "$WORK/cc.sh" <<'PY'
import json, shlex, sys, os
db, orig, patched, out = sys.argv[1:]
entry = next(e for e in json.load(open(db)) if e["file"] == orig)
args = [a for a in shlex.split(entry["command"]) if a != "ccache"]
args[args.index("-o") + 1] = out
args[args.index(orig)] = patched
args[1:1] = ["-iquote", os.path.dirname(orig)]
print("cd", shlex.quote(entry["directory"]), "&&", shlex.join(args))
PY
nice -n 19 sh "$WORK/cc.sh" 2>&1 | grep -v -e 'Wno-error-all' -e 'warning generated' || true
[ -s "$WORK/nx2_thread_stats.cpp.o" ] || { log "compile of nx2_thread_stats.cpp failed"; exit 1; }
cp "$LBLD/src/core/libcore.a" "$WORK/libcore.a"
ar t "$WORK/libcore.a" | grep -c '^nx2_thread_stats.cpp.o$' | grep -q '^1$' || { log "libcore.a does not hold exactly one nx2_thread_stats.cpp.o"; exit 1; }
(cd "$WORK" && ar r libcore.a nx2_thread_stats.cpp.o 2> ar.log && ranlib libcore.a 2>> ar.log)
(cd "$LBLD" && ninja -t commands lichii | tail -1) > "$WORK/link.cmd"
python3 - "$WORK/link.cmd" "$WORK/libcore.a" "$WORK/lichii" > "$WORK/link.sh" <<'PY'
import sys
cmd, lib, out = sys.argv[1:]
s = open(cmd).read(); s = s[s.index("/usr/bin/c++"):]; s = s[:s.index(" && ")]
assert s.count(" src/core/libcore.a ") == 1 and s.count(" -o bin/lichii.app/Contents/MacOS/lichii ") == 1
print(s.replace(" src/core/libcore.a ", f" {lib} ").replace(" -o bin/lichii.app/Contents/MacOS/lichii ", f" -o {out} "))
PY
(cd "$LBLD" && nice -n 19 sh "$WORK/link.sh" 2>&1 | grep -v 'ld: warning' || true)
[ -s "$WORK/lichii" ] || { log "Lichii link failed"; exit 1; }
log "Lichii linked ($(stat -f %z "$WORK/lichii") bytes; pinned $(stat -f %z "$PINNED/Contents/MacOS/lichii")); carries the switch: $(strings -a "$WORK/lichii" | grep -c GUEST_THREAD_STATS_SLOW_MS)"

# --- the app: a copy of the pinned app with this binary, this library and its own bundle id
app=$OUT/app/lichii.app
rm -rf "$OUT/app"; mkdir -p "$OUT/app"
ditto "$PINNED" "$app"
cp "$WORK/lichii" "$WORK/signed"
codesign --force --sign - --entitlements "$LSRC/dist/eglantine.entitlements" "$WORK/signed" 2> "$WORK/codesign.log" || { cat "$WORK/codesign.log"; exit 1; }
cp "$WORK/signed" "$app/Contents/MacOS/lichii"
cp "$WORK/libMoltenVK.dylib" "$app/Contents/Frameworks/libMoltenVK.dylib"
codesign --force --sign - "$app/Contents/Frameworks/libMoltenVK.dylib" 2>> "$WORK/codesign.log"
/usr/libexec/PlistBuddy -c 'Set :CFBundleIdentifier io.github.zortos293.lichii.p99probe' "$app/Contents/Info.plist"
log "assembled $app"
log "  bundle id   $(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$app/Contents/Info.plist")"
log "  lichii      $(shasum "$app/Contents/MacOS/lichii" | cut -c1-12) (pinned $(shasum "$PINNED/Contents/MacOS/lichii" | cut -c1-12))"
log "  libMoltenVK $(shasum "$app/Contents/Frameworks/libMoltenVK.dylib" | cut -c1-12) (pinned $(shasum "$PINNED/Contents/Frameworks/libMoltenVK.dylib" | cut -c1-12))"
log "  pipeline cache id in the library: $(strings -a "$app/Contents/Frameworks/libMoltenVK.dylib" | grep -c "$(sed -n 's/^MOLTENVK_CACHE_ID=//p' "$REPO/versions.lock" | tr -d '"')")"
