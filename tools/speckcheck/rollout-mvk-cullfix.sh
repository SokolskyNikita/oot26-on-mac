#!/bin/bash
# rollout-mvk-cullfix.sh: put the MoltenVK with the mesh cull-mode fix into every path-60 app that still carries the
# library it was built from (moltenvk-p2901 build-par, sha1 253a564090...). Run it under the emulator lock so no
# batch is using the apps. Each old library is kept in mvk-backups; the swap is a rename, so a running process is
# not disturbed. Fails closed: an app is skipped unless its library is exactly the expected old one.
set -u
REPO=$(git -C "$(dirname "$0")" rev-parse --show-toplevel)
P=$REPO/build/old-trees/path-60
NEW=$P/app-mvkp2901cull/lichii.app/Contents/Frameworks/libMoltenVK.dylib
OLD_SHA=253a564090; NEW_SHA=17f76f69f2
[ "$(shasum "$NEW" | cut -c1-10)" = "$NEW_SHA" ] || { echo "fixed library is not the verified one"; exit 1; }
changed=0
for a in app-practice app-mvkp2901 app-hvf-final app-hvf-final-lto app-hvfrace-base app-hvfrace-diag app-hvfrace-fast app-hvfrace-fix app-hvfrace-ltojit; do
  app=$P/$a/lichii.app; f=$app/Contents/Frameworks/libMoltenVK.dylib
  [ -f "$f" ] || { echo "$a: no library, skipped"; continue; }
  have=$(shasum "$f" | cut -c1-10)
  if [ "$have" = "$NEW_SHA" ]; then echo "$a: already fixed"; continue; fi
  if [ "$have" != "$OLD_SHA" ]; then echo "$a: carries $have, not the expected library, skipped"; continue; fi
  cp -p "$f" "$P/mvk-backups/$a.libMoltenVK.before-cullfix-2026-11-17.dylib" || { echo "$a: backup failed, skipped"; continue; }
  cp -p "$NEW" "$f.new" && mv "$f.new" "$f" || { echo "$a: swap failed"; continue; }
  codesign --force --sign - --preserve-metadata=entitlements "$app" > /dev/null 2>&1
  echo "$a: fixed library in place (sha $(shasum "$f" | cut -c1-10), hypervisor entitlement: $(codesign -d --entitlements - "$app" 2>&1 | grep -c hypervisor))"
  changed=$((changed + 1))
done
echo "apps changed: $changed"
