#!/bin/bash
# build.sh [STEP...]: build the pinned emulator from public source and the patches in this repository.
#
#   fetch     clone Lichii and MoltenVK at the commits in versions.lock and apply patches/<name>/*.patch
#   verify    check that the patched source is exactly the pinned source (commit and tree ids in versions.lock)
#   mvk       build MoltenVK
#   lichii    build Lichii
#   cli       build eden-cli, the command-line Lichii that replays recorded GPU traces (tools/statecheck needs it)
#   app       assemble <build dir>/app/lichii.app: Lichii + this MoltenVK + the switches in config/
#   install   copy the app to /Applications/lichii.app (the app there is kept as lichii.app.before-<time>), then
#             boot it once under the emulator lock so its shader caches are built (OOT26_NO_WARM=1 skips the boot)
#   versions  print the tool versions on this machine next to the ones the pinned build was made with
#   all       fetch verify mvk lichii app (the default; never installs)
#
# BUILD_DIR chooses where everything goes (default: build/ beside this script, git-ignored).
# Needs: Apple silicon Mac, Command Line Tools, Homebrew packages listed in README.md.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/versions.lock"
B=${BUILD_DIR:-$HERE/build}
case $B in /*) ;; *) B=$PWD/$B ;; esac
SRC=$B/src
LOG=$B/logs

say() { printf '== %s\n' "$*"; }
die() { printf 'build.sh: %s\n' "$*" >&2; exit 1; }

fetch_one() { # name url base
  local name=$1 url=$2 base=$3 d=$SRC/$1
  if [ ! -d "$d/.git" ]; then
    say "cloning $name"
    git clone --quiet "$url" "$d"
  fi
  git -C "$d" cat-file -e "$base^{commit}" 2>/dev/null || git -C "$d" fetch --quiet origin "$base"
  if git -C "$d" rev-parse --verify --quiet refs/heads/gold >/dev/null; then
    say "$name: branch gold exists, left as it is"
  else
    git -C "$d" checkout --quiet -b gold "$base"
    say "$name: applying $(ls "$HERE/patches/$name"/*.patch | wc -l | tr -d ' ') patches on ${base:0:10}"
    # Each commit gets its patch's author as committer and the author date as commit date, so the same series
    # always gives the same commit ids. MoltenVK stamps its shader cache with the commit it is built from: a
    # different id would throw away Lichii's pipeline file and make the next boot translate every shader again.
    local p from
    for p in "$HERE/patches/$name"/*.patch; do
      from=$(sed -n 's/^From: //p' "$p" | head -1)
      GIT_COMMITTER_NAME=${from%% <*} GIT_COMMITTER_EMAIL=$(printf '%s' "$from" | sed 's/.*<\(.*\)>.*/\1/') \
        git -C "$d" am --quiet --keep-cr --committer-date-is-author-date "$p" \
        || die "$name: $(basename "$p") did not apply (git -C $d am --show-current-patch)"
    done
  fi
}

verify_one() { # name tree commit
  local d=$SRC/$1 got
  [ -z "$(git -C "$d" status --porcelain --untracked-files=no)" ] || die "$1: the source tree has uncommitted changes"
  got=$(git -C "$d" rev-parse 'HEAD^{tree}')
  [ "$got" = "$2" ] || die "$1: source tree is $got, versions.lock pins $2"
  got=$(git -C "$d" rev-parse HEAD)
  [ "$got" = "$3" ] || die "$1: commit is $got, versions.lock pins $3 (same source, but a different shader cache identity)"
  say "$1: source matches versions.lock (commit ${3:0:10}, tree ${2:0:10})"
}

step_fetch() {
  mkdir -p "$SRC"
  fetch_one lichii "$LICHII_URL" "$LICHII_BASE"
  fetch_one moltenvk "$MOLTENVK_URL" "$MOLTENVK_BASE"
}

cache_inputs() { # hash of the MoltenVK files that decide generated shader source
  git -C "$SRC/moltenvk" ls-tree -r HEAD -- ExternalRevisions MoltenVKShaderConverter \
    MoltenVK/MoltenVK/GPUObjects/MVKShaderModule.h MoltenVK/MoltenVK/GPUObjects/MVKShaderModule.mm \
    MoltenVK/MoltenVK/GPUObjects/MVKPipeline.h MoltenVK/MoltenVK/GPUObjects/MVKPipeline.mm | shasum | cut -c1-16
}

step_verify() {
  verify_one lichii "$LICHII_TREE" "$LICHII_COMMIT"
  verify_one moltenvk "$MOLTENVK_TREE" "$MOLTENVK_COMMIT"
  local got; got=$(cache_inputs)
  [ "$got" = "$MOLTENVK_CACHE_INPUTS" ] || die "MoltenVK's shader translation inputs changed (hash $got, versions.lock has $MOLTENVK_CACHE_INPUTS): the stored shader caches may no longer be valid. Set a new MOLTENVK_CACHE_ID and MOLTENVK_CACHE_INPUTS=$got in versions.lock"
  say "moltenvk: pipeline cache id $MOLTENVK_CACHE_ID (translation inputs ${got})"
}

step_mvk() {
  mkdir -p "$LOG"; cd "$SRC/moltenvk"
  [ "$(cache_inputs)" = "$MOLTENVK_CACHE_INPUTS" ] || die "MoltenVK's shader translation inputs changed; run: build.sh verify"
  cmake -G Ninja -S . -B build -DCMAKE_BUILD_TYPE=Release "-DMVK_PIPELINE_CACHE_REV=$MOLTENVK_CACHE_ID" \
    > "$LOG/moltenvk-configure.log" 2>&1 || die "MoltenVK configure failed: $LOG/moltenvk-configure.log"
  say "building MoltenVK (log: $LOG/moltenvk-build.log)"
  cmake --build build > "$LOG/moltenvk-build.log" 2>&1 || { grep -n 'error:' "$LOG/moltenvk-build.log" | head -8; die "MoltenVK build failed"; }
  [ -e "build/MoltenVK/$MOLTENVK_DYLIB" ] || die "no build/MoltenVK/$MOLTENVK_DYLIB"
  grep -q "\"$MOLTENVK_CACHE_ID\"" build/MoltenVK/mvkGitRevDerived.h || die "the built library does not carry pipeline cache id $MOLTENVK_CACHE_ID"
  say "MoltenVK built: $(shasum "build/MoltenVK/$MOLTENVK_DYLIB" | cut -c1-12), pipeline cache id $MOLTENVK_CACHE_ID"
}

step_lichii() {
  mkdir -p "$LOG"; cd "$SRC/lichii"
  [ -e build/release/build.ninja ] || cmake -S . -B build/release -G Ninja \
    -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF -DLICHII_TESTS=OFF -DLICHII_CMD=ON -DLICHII_ROOM=OFF \
    -DLICHII_ROOM_STANDALONE=OFF -DLICHII_USE_BUNDLED_QT=OFF -DENABLE_QT_TRANSLATION=ON \
    "-DCMAKE_PREFIX_PATH=$(brew --prefix qt@6);$(brew --prefix zlib)" "-DOPENSSL_ROOT_DIR=$(brew --prefix openssl@3)" \
    -DVulkanHeaders_FORCE_BUNDLED=ON -DVulkanUtilityLibraries_FORCE_BUNDLED=ON -DENABLE_UPDATE_CHECKER=OFF \
    -DLICHII_BUILD_TAG=path60 -DLICHII_BUILD_PLATFORM=macos-arm64 -DUSE_DISCORD_PRESENCE=OFF -DENABLE_WERROR=OFF \
    -DCMAKE_C_COMPILER_LAUNCHER=ccache -DCMAKE_CXX_COMPILER_LAUNCHER=ccache \
    > "$LOG/lichii-configure.log" 2>&1 || die "Lichii configure failed: $LOG/lichii-configure.log"
  say "building Lichii (log: $LOG/lichii-build.log)"
  cmake --build build/release --target lichii > "$LOG/lichii-build.log" 2>&1 || { grep -n 'error:' "$LOG/lichii-build.log" | head -12; die "Lichii build failed"; }
  [ -d build/release/bin/lichii.app ] || die "no build/release/bin/lichii.app"
  say "Lichii built: $(shasum build/release/bin/lichii.app/Contents/MacOS/lichii | cut -c1-12)"
}

step_cli() {
  mkdir -p "$LOG"; cd "$SRC/lichii"
  [ -e build/release/build.ninja ] || die "Lichii is not configured; run: build.sh lichii"
  say "building eden-cli (log: $LOG/lichii-cli-build.log)"
  cmake --build build/release --target eden-cli > "$LOG/lichii-cli-build.log" 2>&1 || { grep -n 'error:' "$LOG/lichii-cli-build.log" | head -12; die "eden-cli build failed"; }
  say "eden-cli built: $SRC/lichii/build/release/bin/eden-cli"
}

step_app() {
  local app=$B/app/lichii.app built=$SRC/lichii/build/release/bin/lichii.app lib=$SRC/moltenvk/build/MoltenVK/$MOLTENVK_DYLIB
  [ -d "$built" ] || die "Lichii is not built"
  [ -e "$lib" ] || die "MoltenVK is not built"
  mkdir -p "$B/app"
  [ -e "$app" ] && mv "$app" "$app.old.$(date +%Y%m%d-%H%M%S)"
  ditto "$built" "$app"
  cp -p "$lib" "$app/Contents/Frameworks/libMoltenVK.dylib"
  # Switches: the file Lichii ships, then the lines this build adds
  { cat "$SRC/lichii/dist/nx2_switches.txt"; printf '\n'; cat "$HERE/config/nx2_switches.append.txt"; } > "$app/Contents/MacOS/nx2_switches.txt"
  # Launch environment: only for launches through Finder, Dock or `open` (a binary started directly ignores it)
  local env=$HERE/config/launch-env.txt line
  if grep -q '^[A-Za-z_]' "$env" 2>/dev/null; then
    /usr/libexec/PlistBuddy -c 'Add :LSEnvironment dict' "$app/Contents/Info.plist"
    while IFS= read -r line; do
      case $line in ''|'#'*) continue ;; esac
      /usr/libexec/PlistBuddy -c "Add :LSEnvironment:${line%%=*} string ${line#*=}" "$app/Contents/Info.plist"
    done < "$env"
  fi
  codesign --force --sign - --preserve-metadata=entitlements "$app" 2>&1 | tail -1
  say "assembled $app"
  say "  lichii        $(shasum "$app/Contents/MacOS/lichii" | cut -c1-40)"
  say "  libMoltenVK   $(shasum "$app/Contents/Frameworks/libMoltenVK.dylib" | cut -c1-40)"
}

step_install() {
  local app=$B/app/lichii.app dest=/Applications/lichii.app
  [ -d "$app" ] || die "no assembled app; run: build.sh app"
  if pgrep -f '[l]ichii.app/Contents/MacOS' >/dev/null; then die "Lichii is running; stop it first"; fi
  [ -e "$dest" ] && mv "$dest" "$dest.before-$(date +%Y%m%d-%H%M%S)"
  ditto "$app" "$dest"
  say "installed $dest"
  # A new build's first boot can be cold (minutes of shader compiles): have it now, not in a measurement.
  local warm="python3 $HERE/tools/harness/ab.py --warm"
  if [ "${OOT26_NO_WARM:-}" = 1 ]; then
    say "no warm-up boot (OOT26_NO_WARM=1); before measuring, run: $warm"
  else
    say "warm-up boot, under the emulator lock (it waits for a run in progress)"
    $warm --app "$app" || say "the warm-up boot did not finish; before measuring, run: $warm"
  fi
}

step_versions() {
  printf '%-14s %-34s %s\n' tool "this machine" "pinned build made with"
  row() { printf '%-14s %-34s %s\n' "$1" "$2" "$3"; }
  row macOS "$(sw_vers -productVersion) ($(sw_vers -buildVersion))" "$TOOL_MACOS"
  row clang "$(cc --version | head -1 | sed 's/.*version //')" "$TOOL_CLANG"
  row cmake "$(cmake --version | head -1 | sed 's/.*version //')" "$TOOL_CMAKE"
  row ninja "$(ninja --version)" "$TOOL_NINJA"
  row ccache "$(ccache --version | head -1 | sed 's/.*version //')" "$TOOL_CCACHE"
  local p v
  for p in $TOOL_BREW; do
    v=$(brew list --versions "${p%%=*}" 2>/dev/null | awk '{print $2}')
    row "${p%%=*}" "${v:-missing}" "${p#*=}"
  done
}

[ $# -gt 0 ] || set -- all
for step in "$@"; do
  case $step in
    all) step_fetch; step_verify; step_mvk; step_lichii; step_app ;;
    fetch|verify|mvk|lichii|cli|app|install|versions) "step_$step" ;;
    *) die "unknown step '$step' (fetch verify mvk lichii cli app install versions all)" ;;
  esac
done
