#!/bin/bash
# cfgrun.sh "key=value key2=value2" < queue lines: run q.sh lines with global settings changed in
# ~/.config/lichii/qt-config.ini (each key gets \default=false), then put the saved config back, whatever happens.
REPO=$(git -C "$(dirname "$0")" rev-parse --show-toplevel)
MV=$REPO/build/old-trees
C=$HOME/.config/lichii/qt-config.ini
B=$MV/path-60/runs/qt-config.ini.saved-$(date +%H%M%S)
cp -p "$C" "$B" || exit 1
trap 'cp -p "$B" "$C"; echo "config restored from $B ($(shasum "$C" | cut -c1-12))"' EXIT
echo "config before: $(shasum "$C" | cut -c1-12)"
for kv in $1; do
  k=${kv%%=*}; v=${kv#*=}
  grep -q "^$k=" "$C" || { echo "no key $k"; exit 1; }
  sed -i "s|^$k=.*|$k=$v|; s|^$k\\\\default=.*|$k\\\\default=false|" "$C"
  echo "set: $(grep -n "^$k" "$C" | tr '\n' ' ')"
done
"$MV/path-60/q.sh"
