#!/bin/bash
# record.sh LABEL REAL_MOLTENVK [ENV=VALUE ...]: replay a recorded GPU trace offline (no game, no emulator lock)
# through both recorders and leave in runs/:
#   LABEL.vk.log      what Vulkan was asked for at each draw (vkspy; line formats in vkspy/vkspy.c)
#   LABEL.state.log   what the Metal encoder held at each draw (mtlspy MTLSPY_STATE_OUT; format in mtlspy/mtlspy.m)
#   LABEL.mtl.log     mtlspy's ordinary log
#   LABEL.replay.log  the replay's own output
#   out-LABEL/        the frames the replay rendered
# Then compare the two logs: statecheck.py runs/LABEL
#
#   TRACE=path     the .lxtrace to replay (default: the Kokiri cave wall trace of 2026-11-17)
#   EDEN_CLI=path  a Lichii eden-cli that has --replay (default: the one `build.sh cli` makes)
#   FRAMES=n       presents to replay (default 20)
#
# The replay runs from runs/ so that it uses runs/user as its data folder and leaves ~/.local/share/lichii alone.
# Never run eden-cli from anywhere else, not even for --help: it rotates the real emulator's log.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd); RUNS=$HERE/runs
[ $# -ge 2 ] || { sed -n '2,16p' "$0"; exit 2; }
LABEL=$1; REAL=$2; shift 2
case "$LABEL" in ""|*/*|.*) echo "bad label: $LABEL" >&2; exit 2;; esac
TRACE=${TRACE:-$HERE/../harness/runs/ab-20261117-221356/specks-gpu-trace/dumps/trace-1794982438-001.lxtrace}
EDEN_CLI=${EDEN_CLI:-$HERE/../../build/src/lichii/build/release/bin/eden-cli}
for f in "$REAL" "$TRACE" "$EDEN_CLI" "$HERE/vkspy/libvkspy.dylib" "$HERE/mtlspy/libmtlspy.dylib"; do
    [ -e "$f" ] || { echo "missing: $f" >&2; exit 1; }
done
REAL=$(cd "$(dirname "$REAL")" && pwd)/$(basename "$REAL")
OUT=$RUNS/out-$LABEL
mkdir -p "$RUNS/user"
if [ -d "$OUT" ]; then rm -r "$OUT"; fi
mkdir "$OUT"
cd "$RUNS"
status=0
env LIBVULKAN_PATH="$HERE/vkspy/libvkspy.dylib" VKSPY_REAL="$REAL" VKSPY_OUT="$RUNS/$LABEL.vk.log" \
    DYLD_INSERT_LIBRARIES="$HERE/mtlspy/libmtlspy.dylib" MTLSPY_OUT="$RUNS/$LABEL.mtl.log" MTLSPY_STATE_OUT="$RUNS/$LABEL.state.log" \
    MVK_P60_NO_APPNAP=1 "$@" "$EDEN_CLI" --replay "$TRACE" --out "$OUT" --frames "${FRAMES:-20}" > "$RUNS/$LABEL.replay.log" 2>&1 || status=$?
echo "$LABEL: replay exit $status, $(grep -c '^D ' "$RUNS/$LABEL.vk.log") Vulkan draws, $(grep -c '^M ' "$RUNS/$LABEL.state.log") Metal draws, $(ls "$OUT" | grep -c 'png$') frames"
exit $status
