#!/bin/bash
# exp.sh NAME PREPFILE|none: first-visit experiment. A copy of the app with its own bundle id (so a fresh Metal
# cache), a shader folder holding only PREPFILE; prepares it (prep.sh), then drops what Lichii itself recorded and
# runs the verify route. The user's shader folder is moved aside and put back at the end.
set -u
REPO=$(git -C "$(dirname "$0")" rev-parse --show-toplevel)
P=$REPO/wip/shader-prebuild/local/emulator-prebuild
NAME=$1; FILE=$2
D=$HOME/.cache/lichii/shader/0400486024dec000; C=$HOME/.config/lichii/qt-config.ini
APP=$P/app-$NAME/lichii.app
if pgrep -f '[l]ichii.app/Contents/MacOS' >/dev/null; then echo "a Lichii is running"; exit 1; fi
[ -e "$P/hold/$NAME" ] && { echo "name used"; exit 1; }
rm -rf "$P/app-$NAME"; mkdir -p "$P/app-$NAME" "$P/hold"
ditto "$P/app/lichii.app" "$APP" && /usr/libexec/PlistBuddy -c "Set :CFBundleIdentifier io.github.zortos293.lichii.prebuild.$NAME" "$APP/Contents/Info.plist" && codesign --force --sign - --preserve-metadata=entitlements "$APP" >/dev/null 2>&1
MC="$(getconf DARWIN_USER_CACHE_DIR)io.github.zortos293.lichii.prebuild.$NAME"; [ -e "$MC" ] && { echo "Metal cache for this name exists"; exit 1; }
mv "$D" "$P/hold/$NAME" || exit 1
cp -p "$C" "$P/hold/$NAME.qt-config.ini"
restore() { rm -rf "$P/hold/$NAME.exp-folder"; mv "$D" "$P/hold/$NAME.exp-folder" 2>/dev/null; mv "$P/hold/$NAME" "$D"; cp -p "$P/hold/$NAME.qt-config.ini" "$C"; echo "shader folder and config restored"; }
trap restore EXIT
mkdir -p "$D"
MODE=2
if [ "$FILE" != none ]; then
  cp -c "$FILE" "$D/precompiled.fork-v54.nx2prep"
  APP=$APP "$P/prep.sh" "exp-$NAME-prep" 3600 | grep -E 'elapsed|prepared,|timeout|exited' | cut -c1-260
  rm -f "$D"/lichii-cache.v2.bin* "$D"/vulkan_pipelines* ; ls "$D" | tr '\n' ' '; echo
  MODE=0
fi
grep -q '^precompiled_prepare=' "$C" || sed -i 's|^build_all_cached_shaders=\(.*\)$|build_all_cached_shaders=\1\nprecompiled_prepare\\default=false\nprecompiled_prepare='"$MODE"'|' "$C"
sed -i 's|^precompiled_prepare=.*|precompiled_prepare='"$MODE"'|; s|^precompiled_prepare\\default=.*|precompiled_prepare\\default=false|' "$C"
echo "Metal cache before the route: $(du -sh "$MC" 2>/dev/null | cut -f1)"
cd "$REPO/tools/verify" && ./verify.py run "$APP" "exp-$NAME" --out "$P/runs/exp-$NAME" --max-load 100 MVK_P60_NO_APPNAP=1 EDEN_NX2_DLSS_REPLACEMENT=fsr P60_OOT_BILINEAR=1 2>&1 | tail -6 | cut -c1-200
echo "Metal cache after the route: $(du -sh "$MC" 2>/dev/null | cut -f1)"
