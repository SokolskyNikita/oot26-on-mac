#!/bin/sh
# One interactive Lichii session with the built-in debug server on, held under the emulator lock.
# Run it as:  ../verify/verify.py with-lock -- ./session.sh [APP]
# Stop it with:  touch STOP  (in this folder). It kills its own Lichii, then reports config changes.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
APP=${1:-/Applications/lichii.app}
# your own dump of the game: $OOT26_DUMP, else dump/ in this repository or beside it
GAME=${OOT26_DUMP:-$(ls "$HERE"/../../dump/*0400486024DEC000*.nup "$HERE"/../../../dump/*0400486024DEC000*.nup 2>/dev/null | head -1)}
CFG="$HOME/.config/lichii/qt-config.ini"
STAMP=$(date +%Y%m%d-%H%M%S)
RUN="$HERE/runs/$STAMP"
mkdir -p "$RUN/dumps"
rm -f "$HERE/STOP"
cp "$CFG" "$RUN/qt-config.before.ini"

EDEN_NX2_DEBUG_SERVER=127.0.0.1:6545 EDEN_NX2_DEBUG_DIR="$RUN/dumps" MVK_P60_NO_APPNAP=1 \
  "$APP/Contents/MacOS/lichii" "$GAME" >"$RUN/stderr.log" 2>&1 &
PID=$!
echo "$PID" >"$RUN/lichii.pid"
echo "launched $APP pid $PID -> $RUN"

while kill -0 "$PID" 2>/dev/null && [ ! -e "$HERE/STOP" ]; do sleep 2; done
if kill -0 "$PID" 2>/dev/null; then kill -9 "$PID"; echo "stopped by STOP file"; else echo "lichii exited by itself"; fi
sleep 1
cp "$HOME/.local/share/lichii/log/eden_log.txt" "$RUN/eden_log.txt" 2>/dev/null
if cmp -s "$CFG" "$RUN/qt-config.before.ini"; then echo "config unchanged"; else echo "config CHANGED:"; diff "$RUN/qt-config.before.ini" "$CFG"; fi
