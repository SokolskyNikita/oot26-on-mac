#!/bin/sh
# Run spec files back to back, each under the emulator lock: ./queue.sh SPEC.json ... (log: runs/queue.log)
cd "$(dirname "$0")" || exit 1
for f in "$@"; do
  # touch PAUSE: let other sessions have the emulator; this queue waits (outside the lock) until it is removed
  [ -e PAUSE ] && { echo "=== paused before $f $(date +%H:%M:%S) (rm $(pwd)/PAUSE to go on)"; while [ -e PAUSE ]; do sleep 20; done; }
  echo "=== $f $(date +%H:%M:%S)"
  ../verify/verify.py with-lock --lock-wait 7200 -- uv run -q --with pillow --with numpy python ab.py "$f"
done
echo "=== queue done $(date +%H:%M:%S)"
