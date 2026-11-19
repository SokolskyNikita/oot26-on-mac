#!/bin/bash
# replay.sh LABEL [ENV=VALUE ...]: replay the recorded GPU trace offline (no game, no emulator lock) and count the
# speckled frames. Uses the eden-cli built in local/lichii-emu (override with CLI=path), a private data folder
# (local/replay/user, found because the replay runs from local/replay), and app-mvkp2901's MoltenVK (MVK=path).
# TRACE=path picks another trace, FRAMES=n the number of presents (default 20).
set -u
REPO=$(git -C "$(dirname "$0")" rev-parse --show-toplevel)
HERE=$(cd "$(dirname "$0")" && pwd); S=${SPECKS_LOCAL:-$REPO/build/old-trees/path-60/jit-cache-local}; W=$S/replay
LABEL=$1; shift
TRACE=${TRACE:-$REPO/tools/harness/runs/ab-20261117-221356/specks-gpu-trace/dumps/trace-1794982438-001.lxtrace}
CLI=${CLI:-$S/lichii-emu/build/release/bin/eden-cli}
MVK=${MVK:-$REPO/build/old-trees/path-60/app-mvkp2901/lichii.app/Contents/Frameworks/libMoltenVK.dylib}
OUT=$W/out-$LABEL; rm -rf "$OUT"; mkdir -p "$W/user" "$OUT"
cd "$W" || exit 1
env LIBVULKAN_PATH="$MVK" MVK_P60_NO_APPNAP=1 "$@" "$CLI" --replay "$TRACE" --out "$OUT" --frames "${FRAMES:-20}" > "$OUT/replay.log" 2>&1
echo "$LABEL: replay exit $? ($*)"
cp "$W/user/log/eden_log.txt" "$OUT/eden_log.txt" 2>/dev/null
uv run -q --with pillow --with numpy python "$HERE/whitecount.py" "$OUT" | tail -1 | sed "s|$W/||"
