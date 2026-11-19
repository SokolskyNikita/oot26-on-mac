#!/bin/bash
# build-mvk-par.sh: build the parallel-shader-compile MoltenVK variants (our parallel readData patch "pown", upstream PRs 2901 / 2905 / both, applied in
# APFS clones moltenvk-pown, -p2901, -p2905, -pboth) and assemble app-mvk<variant> = app-practice with that libMoltenVK.
set -u
REPO=$(git -C "$(dirname "$0")" rev-parse --show-toplevel)
HERE=${VARIANT_TREE:?set VARIANT_TREE to a folder that holds the lichii/ and moltenvk/ source trees to build variants in}
for v in pown p2901 p2905 pboth; do
  echo "[$(date +%H:%M:%S)] == $v"
  (cd "$HERE/moltenvk-$v" && rm -rf build-par && nice -n 19 cmake -G Ninja -S . -B build-par -DCMAKE_BUILD_TYPE=Release > build-par-configure.log 2>&1 &&
   nice -n 19 cmake --build build-par -j 6 > build-par.log 2>&1) || { echo "$v: build failed"; grep -n 'error' "$HERE/moltenvk-$v/build-par.log" | head -8; continue; }
  app=$HERE/app-mvk$v/lichii.app; mkdir -p "$HERE/app-mvk$v"; rm -rf "$app"
  ditto "$HERE/app-practice/lichii.app" "$app" &&
  cp -p "$HERE/moltenvk-$v/build-par/MoltenVK/libMoltenVK.1.4.3.dylib" "$app/Contents/Frameworks/libMoltenVK.dylib" &&
  codesign --force --sign - --preserve-metadata=entitlements "$app" > /dev/null 2>&1
  echo "[$(date +%H:%M:%S)] $v: $app (hypervisor entitlement: $(codesign -d --entitlements - "$app" 2>&1 | grep -c hypervisor))"
done
