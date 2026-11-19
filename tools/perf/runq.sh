#!/bin/bash
# runq.sh QUEUE_FILE: q.sh one line at a time, waiting for the emulator to be gone before each.
REPO=$(git -C "$(dirname "$0")" rev-parse --show-toplevel)
cd "$REPO/build/old-trees/path-60" || exit 1
while read -r line; do
  [ -z "$line" ] && continue
  timeout 900 sh -c "while pgrep -f '[l]ichii.app/Contents/MacOS' >/dev/null; do sleep 3; done"; sleep 6
  echo "$line" | bash ./q.sh
done < "$1"
