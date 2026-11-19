#!/bin/bash
# seedq.sh SEED_CFG QUEUE_FILE: copy the caches of SEED_CFG to every CFG the queue names that has none yet (same
# shader translator only), then run the queue with q.sh.
REPO=$(git -C "$(dirname "$0")" rev-parse --show-toplevel)
MV=$REPO/build/old-trees
SEED=$1; Q=$2
for cfg in $(sed 's/^full //' "$Q" | awk 'NF {print $1}' | sort -u); do
  [ -e "$MV/sc-update/pcache/$cfg" ] || { cp -Rc "$MV/sc-update/pcache/$SEED" "$MV/sc-update/pcache/$cfg" && echo "seeded $cfg from $SEED"; }
done
"$MV/path-60/q.sh" < "$Q"
