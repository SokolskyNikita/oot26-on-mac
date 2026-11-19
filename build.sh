#!/bin/bash
# build.sh [STEP...]: build the pinned emulator from public source and the patches in this repository.
#
#   fetch     clone Lichii and MoltenVK at the commits in versions.lock and apply patches/<name>/*.patch
#   verify    check that the patched source is exactly the pinned source (git tree ids in versions.lock)
#   mvk       build MoltenVK
#   lichii    build Lichii
#   app       assemble <build dir>/app/lichii.app: Lichii + this MoltenVK + the switches in config/
#   install   copy the app to /Applications/lichii.app (the app there is kept as lichii.app.before-<time>)
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
    git -C "$d" -c user.name="${GIT_AUTHOR_NAME:-oot26-on-mac build}" -c user.email="${GIT_AUTHOR_EMAIL:-build@localhost}" \
      am --quiet --keep-cr "$HERE/patches/$name"/*.patch || die "$name: a patch did not apply (git -C $d am --show-current-patch)"
  fi
}

verify_one() { # name tree
  local d=$SRC/$1 got
  [ -z "$(git -C "$d" status --porcelain --untracked-files=no)" ] || die "$1: the source tree has uncommitted changes"
  got=$(git -C "$d" rev-parse 'HEAD^{tree}')
  [ "$got" = "$2" ] || die "$1: source tree is $got, versions.lock pins $2"
  say "$1: source matches versions.lock (tree ${2:0:10})"
}

step_fetch() {
  mkdir -p "$SRC"
  fetch_one lichii "$LICHII_URL" "$LICHII_BASE"
  fetch_one moltenvk "$MOLTENVK_URL" "$MOLTENVK_BASE"
}

step_verify() {
  verify_one lichii "$LICHII_TREE"
  verify_one moltenvk "$MOLTENVK_TREE"
}

step_mvk() {
  mkdir -p "$LOG"; cd "$SRC/moltenvk"
  [ -e build/build.ninja ] || cmake -G Ninja -S . -B build -DCMAKE_BUILD_TYPE=Release > "$LOG/moltenvk-configure.log" 2>&1 \
    || die "MoltenVK configure failed: $LOG/moltenvk-configure.log"
  say "building MoltenVK (log: $LOG/moltenvk-build.log)"
  cmake --build build > "$LOG/moltenvk-build.log" 2>&1 || { grep -n 'error:' "$LOG/moltenvk-build.log" | head -8; die "MoltenVK build failed"; }
  [ -e "build/MoltenVK/$MOLTENVK_DYLIB" ] || die "no build/MoltenVK/$MOLTENVK_DYLIB"
  say "MoltenVK built: $(shasum "build/MoltenVK/$MOLTENVK_DYLIB" | cut -c1-12)"
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
    fetch|verify|mvk|lichii|app|install|versions) "step_$step" ;;
    *) die "unknown step '$step' (fetch verify mvk lichii app install versions all)" ;;
  esac
done
