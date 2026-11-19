#!/bin/bash
# build.sh [TARGETS...]: configure (once) and build the prebuild worktree of Lichii. Default targets: lichii nx2-precompile
set -u
REPO=$(git -C "$(dirname "$0")" rev-parse --show-toplevel)
HERE=$REPO/wip/shader-prebuild/local/emulator-prebuild
cd "$HERE/lichii" || exit 1
[ -e build/release/build.ninja ] || cmake -S . -B build/release -G Ninja \
  -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF -DLICHII_TESTS=OFF -DLICHII_CMD=ON -DLICHII_ROOM=OFF \
  -DLICHII_ROOM_STANDALONE=OFF -DLICHII_USE_BUNDLED_QT=OFF -DENABLE_QT_TRANSLATION=ON \
  "-DCMAKE_PREFIX_PATH=$(brew --prefix qt@6);$(brew --prefix zlib)" "-DOPENSSL_ROOT_DIR=$(brew --prefix openssl@3)" \
  -DVulkanHeaders_FORCE_BUNDLED=ON -DVulkanUtilityLibraries_FORCE_BUNDLED=ON -DENABLE_UPDATE_CHECKER=OFF \
  -DLICHII_BUILD_TAG=prebuild -DLICHII_BUILD_PLATFORM=macos-arm64 -DUSE_DISCORD_PRESENCE=OFF -DENABLE_WERROR=OFF \
  -DENABLE_DEBUG_TOOLS=ON \
  -DCMAKE_C_COMPILER_LAUNCHER=ccache -DCMAKE_CXX_COMPILER_LAUNCHER=ccache \
  > "$HERE/configure.log" 2>&1
echo "configure exit $?"; tail -2 "$HERE/configure.log" | cut -c1-200
[ $# -gt 0 ] || set -- lichii nx2-precompile
cmake --build build/release --target "$@" > "$HERE/build.log" 2>&1
echo "build exit $?"; tail -2 "$HERE/build.log" | cut -c1-200; grep -n "error:" "$HERE/build.log" | head -12 | cut -c1-260
