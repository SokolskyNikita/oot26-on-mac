#!/bin/bash
# build.sh: build the two recorders.
#   vkspy/libvkspy.dylib    the requested side (a Vulkan library in front of MoltenVK)
#   mtlspy/libmtlspy.dylib  the Metal side (inserted with DYLD_INSERT_LIBRARIES)
# VKINC=dir picks the Vulkan headers (default: Homebrew's).
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
VKINC=${VKINC:-/opt/homebrew/include}
[ -e "$VKINC/vulkan/vulkan.h" ] || { echo "no vulkan/vulkan.h under $VKINC (set VKINC)" >&2; exit 1; }
clang -O2 -Wall -Wextra -Wno-unused-parameter -dynamiclib -fvisibility=hidden -I"$VKINC" -o "$HERE/vkspy/libvkspy.dylib" "$HERE/vkspy/vkspy.c"
clang -O2 -Wall -Wno-unused-variable -Wno-deprecated-declarations -dynamiclib -fno-objc-arc -framework Foundation -framework Metal -o "$HERE/mtlspy/libmtlspy.dylib" "$HERE/mtlspy/mtlspy.m"
echo "built vkspy/libvkspy.dylib and mtlspy/libmtlspy.dylib"
