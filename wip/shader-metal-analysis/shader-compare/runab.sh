#!/bin/sh
# runab.sh OUT REPS DIR...: interleaved argument-buffer vs direct runs, both orders, REPS times per DIR.
cd "$(dirname "$0")"; out=$1; reps=$2; shift 2; : > "$out"
for r in $(seq 1 $reps); do for d in "$@"; do
  echo "=== rep $r dir $d" >> "$out"
  ./fsxd "$d" asgen:safe:8:blend asgen_d:safe:8:blend all:safe:8:blend all_d:safe:8:blend asgen_d:safe:8:blend asgen:safe:8:blend all_d:safe:8:blend all:safe:8:blend >> "$out" 2>&1
done; done
