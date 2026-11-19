#!/bin/bash
# q.sh NAME < lines "CFG APP LABEL [ENV=VAL...]": run verify standing runs one after another (sc-update/run.sh).
# A line starting with "full " uses aio-profile/run_full.sh (whole route). {L} in an env value expands to the label.
REPO=$(git -C "$(dirname "$0")" rev-parse --show-toplevel)
MV=$REPO/build/old-trees
cd "$MV/sc-update" || exit 1
while read -r line; do
  [ -z "$line" ] && continue
  S=./run.sh
  case "$line" in full\ *) S=../aio-profile/run_full.sh; line=${line#full };; esac
  set -- $line
  CFG=$1; APP=$2; LABEL=$3; shift 3
  ARGS=()
  for a in "$@"; do ARGS+=("${a//\{L\}/$LABEL}"); done
  echo "== $LABEL cfg=$CFG $(date +%H:%M:%S) load $(sysctl -n vm.loadavg)"
  CFG=$CFG $S "$APP" "$LABEL" "${ARGS[@]}" 2>&1 | grep -v '^Installed'
done
