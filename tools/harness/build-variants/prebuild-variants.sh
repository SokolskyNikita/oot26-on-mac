#!/bin/bash
# prebuild-variants.sh [lto|pgogen|llvm|pgouse ...]: build compile-time variants of Lichii + MoltenVK in their own build
# folders and assemble path-60/app-<variant>/lichii.app. The practice app and build/release are never touched.
#   lto     Apple clang, ThinLTO (Lichii ENABLE_LTO=ON, MoltenVK -flto=thin), -mcpu=apple-m4
#   pgogen  Apple clang, -fprofile-generate=$PROF (instrumented, for a training run)
#   llvm    Homebrew LLVM clang (upstream), plain Release
#   pgouse  Apple clang, ThinLTO + -mcpu=apple-m4 + -fprofile-use=$PROF/merged.profdata (after training)
# Runs niced with 6 jobs so measurements running at the same time are disturbed as little as possible.
set -u
REPO=$(git -C "$(dirname "$0")" rev-parse --show-toplevel)
HERE=$REPO/build/old-trees/path-60
PROF=$HERE/pgo-profiles
JOBS=6
SDK=$(xcrun --show-sdk-path)
LLVM=/opt/homebrew/opt/llvm/bin
log() { echo "[$(date +%H:%M:%S)] $*"; }

lichii_common=(-DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF -DLICHII_TESTS=OFF -DLICHII_CMD=ON -DLICHII_ROOM=OFF
  -DLICHII_ROOM_STANDALONE=OFF -DLICHII_USE_BUNDLED_QT=OFF -DENABLE_QT_TRANSLATION=ON
  "-DCMAKE_PREFIX_PATH=$(brew --prefix qt@6);$(brew --prefix zlib)" "-DOPENSSL_ROOT_DIR=$(brew --prefix openssl@3)"
  -DVulkanHeaders_FORCE_BUNDLED=ON -DVulkanUtilityLibraries_FORCE_BUNDLED=ON -DENABLE_UPDATE_CHECKER=OFF
  -DLICHII_BUILD_PLATFORM=macos-arm64 -DUSE_DISCORD_PRESENCE=OFF -DENABLE_WERROR=OFF
  -DCMAKE_C_COMPILER_LAUNCHER=ccache -DCMAKE_CXX_COMPILER_LAUNCHER=ccache)

flags_args() {  # $1 = compile flags, $2 = link flags -> FA: cmake -D arguments for C, C++, Objective-C(++), linkers
  # CXX_EXTRA: C++-only additions (upstream LLVM's libc++ needs <cstdlib> forced in for sirit's std::abort)
  # OBJC_EXTRA: Objective-C(++)-only additions (lld can't link upstream clang's objc_msgSend selector stubs)
  FA=("-DCMAKE_C_FLAGS=$1" "-DCMAKE_CXX_FLAGS=$1 ${CXX_EXTRA:-}" "-DCMAKE_OBJC_FLAGS=$1 ${OBJC_EXTRA:-}" "-DCMAKE_OBJCXX_FLAGS=$1 ${CXX_EXTRA:-} ${OBJC_EXTRA:-}"
      "-DCMAKE_EXE_LINKER_FLAGS=$2" "-DCMAKE_SHARED_LINKER_FLAGS=$2" "-DCMAKE_MODULE_LINKER_FLAGS=$2")
}

build_variant() {
  local v=$1 cflags="" lflags="" lto=OFF compilers=() OBJC_EXTRA=""
  case $v in
    lto)    cflags="-mcpu=apple-m4"; lto=ON; mvk_cflags="-flto=thin -mcpu=apple-m4"; mvk_lflags="-flto=thin" ;;
    pgogen) cflags="-fprofile-generate=$PROF -fprofile-update=atomic"; lflags="$cflags"; mvk_cflags="$cflags"; mvk_lflags="$cflags" ;;
    llvm)   compilers=(-DCMAKE_C_COMPILER=$LLVM/clang -DCMAKE_CXX_COMPILER=$LLVM/clang++ -DCMAKE_OBJC_COMPILER=$LLVM/clang
                       -DCMAKE_OBJCXX_COMPILER=$LLVM/clang++ -DCMAKE_OSX_SYSROOT=$SDK); mvk_cflags=""; mvk_lflags=""
            CXX_EXTRA="-include cstdlib" ;;
    pgouse) [ -e "$PROF/merged.profdata" ] || { log "pgouse: no $PROF/merged.profdata yet"; return 1; }
            cflags="-mcpu=apple-m4 -fprofile-use=$PROF/merged.profdata -Wno-profile-instr-unprofiled -Wno-profile-instr-out-of-date -Wno-backend-plugin"
            lto=ON; mvk_cflags="-flto=thin $cflags"; mvk_lflags="-flto=thin" ;;
    llvm-lto) compilers=(-DCMAKE_C_COMPILER=$LLVM/clang -DCMAKE_CXX_COMPILER=$LLVM/clang++ -DCMAKE_OBJC_COMPILER=$LLVM/clang
                       -DCMAKE_OBJCXX_COMPILER=$LLVM/clang++ -DCMAKE_OSX_SYSROOT=$SDK)
            CXX_EXTRA="-include cstdlib"
            # Apple's ld64 reads LTO bitcode through Apple's libLTO, which can't read upstream LLVM's: link with lld
            OBJC_EXTRA="-fno-objc-msgsend-selector-stubs -fno-objc-msgsend-class-selector-stubs"
            # MoltenVK without LTO: its External static libraries are prebuilt as Apple bitcode, which lld can't read
            cflags="-mcpu=apple-m4"; lflags="-fuse-ld=lld"; lto=ON; mvk_cflags="-mcpu=apple-m4"; mvk_lflags="" ;;
    llvm-pgogen) compilers=(-DCMAKE_C_COMPILER=$LLVM/clang -DCMAKE_CXX_COMPILER=$LLVM/clang++ -DCMAKE_OBJC_COMPILER=$LLVM/clang
                       -DCMAKE_OBJCXX_COMPILER=$LLVM/clang++ -DCMAKE_OSX_SYSROOT=$SDK)
            CXX_EXTRA="-include cstdlib"
            cflags="-fprofile-generate=$PROF-llvm -fprofile-update=atomic"; lflags="$cflags"; mvk_cflags="$cflags"; mvk_lflags="$cflags" ;;
    llvm-pgouse) [ -e "$PROF-llvm/merged.profdata" ] || { log "llvm-pgouse: no $PROF-llvm/merged.profdata yet"; return 1; }
            compilers=(-DCMAKE_C_COMPILER=$LLVM/clang -DCMAKE_CXX_COMPILER=$LLVM/clang++ -DCMAKE_OBJC_COMPILER=$LLVM/clang
                       -DCMAKE_OBJCXX_COMPILER=$LLVM/clang++ -DCMAKE_OSX_SYSROOT=$SDK)
            CXX_EXTRA="-include cstdlib"
            cflags="-mcpu=apple-m4 -fprofile-use=$PROF-llvm/merged.profdata -Wno-profile-instr-unprofiled -Wno-profile-instr-out-of-date -Wno-backend-plugin"
            OBJC_EXTRA="-fno-objc-msgsend-selector-stubs -fno-objc-msgsend-class-selector-stubs"
            lflags="-fuse-ld=lld"; lto=ON; mvk_cflags="$cflags"; mvk_lflags="" ;;   # MoltenVK: no LTO, Apple ld (see llvm-lto)
    *) log "unknown variant $v"; return 1 ;;
  esac
  flags_args "$mvk_cflags" "$mvk_lflags"
  log "== $v: MoltenVK"
  (cd "$HERE/moltenvk" && nice -n 19 cmake -G Ninja -S . -B build-$v -DCMAKE_BUILD_TYPE=Release ${compilers[@]+"${compilers[@]}"} \
      "${FA[@]}" > build-$v-configure.log 2>&1 &&
   nice -n 19 cmake --build build-$v -j $JOBS > build-$v.log 2>&1) || { log "$v: MoltenVK failed"; grep -n 'error' "$HERE/moltenvk/build-$v.log" "$HERE/moltenvk/build-$v-configure.log" 2>/dev/null | head -8; return 1; }
  flags_args "$cflags" "$lflags"
  log "== $v: Lichii"
  (cd "$HERE/lichii" && nice -n 19 cmake -S . -B build/release-$v -G Ninja "${lichii_common[@]}" ${compilers[@]+"${compilers[@]}"} \
      -DLICHII_BUILD_TAG=path60-$v -DENABLE_LTO=$lto "${FA[@]}" > "$HERE/lichii-$v-configure.log" 2>&1 &&
   nice -n 19 cmake --build build/release-$v --target lichii -j $JOBS > "$HERE/lichii-$v-build.log" 2>&1) ||
    { log "$v: Lichii failed"; grep -n 'error' "$HERE/lichii-$v-build.log" "$HERE/lichii-$v-configure.log" 2>/dev/null | head -12; return 1; }
  local app=$HERE/app-$v/lichii.app
  mkdir -p "$HERE/app-$v"; rm -rf "$app"
  ditto "$HERE/lichii/build/release-$v/bin/lichii.app" "$app" &&
  cp -p "$HERE/moltenvk/build-$v/MoltenVK/libMoltenVK.1.4.3.dylib" "$app/Contents/Frameworks/libMoltenVK.dylib" &&
  cp "$HERE/app-practice/lichii.app/Contents/MacOS/nx2_switches.txt" "$app/Contents/MacOS/" &&
  codesign --force --sign - --preserve-metadata=entitlements "$app" > /dev/null 2>&1
  log "$v: assembled $app (hypervisor entitlement: $(codesign -d --entitlements - "$app" 2>&1 | grep -c hypervisor))"
}

mkdir -p "$PROF" "$PROF-llvm"
failed=0
for v in "${@:-lto pgogen llvm}"; do
  for one in $v; do build_variant "$one" || failed=1; done
done
log "done (failed: $failed)"
exit $failed
