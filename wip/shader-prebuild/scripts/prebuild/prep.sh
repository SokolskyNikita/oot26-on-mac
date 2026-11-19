#!/bin/bash
# prep.sh LABEL TIMEOUT_S [ENV=VALUE ...]: boot prebuild/app with "Prepare precompiled shaders" = Before the game
# starts, wait for the preparation to end (or TIMEOUT_S), kill the emulator, restore the config. The shader folder
# (~/.cache/lichii/shader/<title>) is used as it is: put the .nx2prep there first. Holds the verify lock.
set -u
REPO=$(git -C "$(dirname "$0")" rev-parse --show-toplevel)
P=$REPO/wip/shader-prebuild/local/emulator-prebuild
LABEL=$1; TMO=$2; shift 2
APP=${APP:-$P/app/lichii.app}
MODE=${MODE:-1}   # precompiled_prepare: 0 while playing, 1 before start, 2 never
C=$HOME/.config/lichii/qt-config.ini; LOG=$HOME/.local/share/lichii/log/eden_log.txt
GAME=$(ls "$REPO"/dump/*0400486024DEC000*.nup | head -1)
OUT=$P/runs/$LABEL; [ -e "$OUT" ] && { echo "label used"; exit 1; }; mkdir -p "$OUT"
if pgrep -f '[l]ichii.app/Contents/MacOS' >/dev/null; then echo "a Lichii is running"; exit 1; fi
mkdir "$HOME/.local/share/lichii/verify.lock" 2>/dev/null || { echo "verify lock held"; exit 1; }
echo "{\"pid\": $$, \"label\": \"prep-$LABEL\"}" > "$HOME/.local/share/lichii/verify.lock/owner.json"
cp -p "$C" "$OUT/qt-config.before.ini"
finish() { [ -n "${LP:-}" ] && kill -9 "$LP" 2>/dev/null; cp -p "$OUT/qt-config.before.ini" "$C"; rm -rf "$HOME/.local/share/lichii/verify.lock"; }
trap finish EXIT
grep -q '^precompiled_prepare=' "$C" || sed -i 's|^build_all_cached_shaders=\(.*\)$|build_all_cached_shaders=\1\nprecompiled_prepare\\default=false\nprecompiled_prepare='"$MODE"'|' "$C"
sed -i 's|^precompiled_prepare=.*|precompiled_prepare='"$MODE"'|; s|^precompiled_prepare\\default=.*|precompiled_prepare\\default=false|' "$C"
grep -n '^precompiled_prepare' "$C" | tr '\n' ' '; echo
env MVK_P60_NO_APPNAP=1 EDEN_NX2_DLSS_REPLACEMENT=fsr P60_OOT_BILINEAR=1 MVK_CONFIG_LOG_LEVEL=1 "$@" "$APP/Contents/MacOS/lichii" "$GAME" > "$OUT/stderr.log" 2>&1 &
LP=$!; echo "launched pid $LP $(date +%H:%M:%S)"
T0=$(date +%s)
while kill -0 $LP 2>/dev/null; do
  sleep 5
  grep -q -E 'Precompiled pipelines: [0-9]+ prepared, |Precompiled pipelines already prepared|Precompiled pipelines skipped' "$LOG" 2>/dev/null && { echo "prep ended"; break; }
  [ $(( $(date +%s) - T0 )) -ge "$TMO" ] && { echo "timeout"; break; }
done
kill -0 $LP 2>/dev/null || echo "emulator exited by itself"
echo "elapsed $(( $(date +%s) - T0 )) s"; sleep 2
ps -o rss= -p $LP 2>/dev/null | awk '{print "rss MiB", $1/1024}'
cp -p "$LOG" "$OUT/eden_log.txt"
grep -E 'Precompiled|Preparing|precompiled' "$OUT/eden_log.txt" | cut -c1-260 | tail -25
