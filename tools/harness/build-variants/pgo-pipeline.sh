#!/bin/sh
# PGO: instrumented build -> one training run (standard route, 1800-frame phases) -> merge -> PGO+ThinLTO build -> compare
REPO=$(git -C "$(dirname "$0")" rev-parse --show-toplevel)
H=${VARIANT_TREE:?set VARIANT_TREE to a folder that holds the lichii/ and moltenvk/ source trees to build variants in}
D=$REPO/tools/harness
cd $H || exit 1
echo "[$(date +%H:%M:%S)] pgo: building instrumented app"
./prebuild-variants.sh pgogen || exit 1
[ -d app-pgogen/lichii.app ] || { echo "pgo: no app-pgogen"; exit 1; }
rm -f pgo-profiles/*.profraw
(cd $D && ./queue.sh pgo-train.json)
n=$(ls pgo-profiles/*.profraw 2>/dev/null | wc -l); s=$(du -sk pgo-profiles 2>/dev/null | cut -f1)
echo "[$(date +%H:%M:%S)] pgo: $n profraw files, $s KiB"
[ "$n" -gt 0 ] && [ "$s" -gt 100 ] || { echo "pgo: no usable profiles (continuous mode under kill -9 failed?)"; exit 1; }
xcrun llvm-profdata merge -o pgo-profiles/merged.profdata pgo-profiles/*.profraw || exit 1
echo "[$(date +%H:%M:%S)] pgo: merged $(du -h pgo-profiles/merged.profdata | cut -f1)"
./prebuild-variants.sh pgouse || exit 1
(cd $D && ./queue.sh pgo-compare.json)
echo "[$(date +%H:%M:%S)] pgo: done"
