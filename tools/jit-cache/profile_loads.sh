#!/bin/bash
# profile_loads.sh OUTDIR N: sample the next N launches of local/app-sharedjit (macOS `sample`, 1 ms interval) for
# 40 s each, starting 18 s after the process appears, which covers the boot's end, the menus and the save load of
# the A/B harness. Run it beside a batch whose timings are not used: sampling slows the process.
OUT=$1; N=${2:-1}; mkdir -p "$OUT"; done_pids=" "
for i in $(seq 1 "$N"); do
  pid=""
  for t in $(seq 1 3600); do
    pid=$(pgrep -f '[a]pp-sharedjit/lichii.app/Contents/MacOS/lichii' | head -1)
    case "$done_pids" in *" $pid "*) pid="";; esac
    [ -n "$pid" ] && break
    sleep 1
  done
  [ -n "$pid" ] || { echo "no launch seen"; exit 1; }
  done_pids="$done_pids$pid "
  sleep 18
  sample "$pid" 40 1 -file "$OUT/sample-$i-pid$pid.txt" > /dev/null 2>&1
  echo "sampled launch $i (pid $pid) -> $OUT/sample-$i-pid$pid.txt"
done
