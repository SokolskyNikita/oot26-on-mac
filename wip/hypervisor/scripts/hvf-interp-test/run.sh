#!/bin/sh
# Builds and runs the interpreter differential test. Needs no emulator: it links the interpreter
# object of an existing Lichii build.
#   ./run.sh [iterations] [seed]
#   LICHII=/path/to/lichii BUILD=build/release ./run.sh   (default: build/src/lichii of this repository)
set -eu
here=$(cd "$(dirname "$0")" && pwd)
# default: the pinned Lichii source and its build tree (./build.sh)
LICHII=${LICHII:-$(git -C "$here" rev-parse --show-toplevel)/build/src/lichii}
BUILD=${BUILD:-build/release}
obj=$LICHII/$BUILD/src/core/CMakeFiles/core.dir/arm/nce/interpreter_visitor.cpp.o
src=$LICHII/src/core/arm/nce/interpreter_visitor.cpp
[ -f "$obj" ] || { echo "no interpreter object at $obj" >&2; exit 2; }
if [ "$src" -nt "$obj" ]; then
    echo "warning: $src is newer than the built object; the test runs the older code" >&2
fi
out=${TMPDIR:-/tmp}/hvf-interp-test.$$
trap 'rm -f "$out"' EXIT
c++ -std=gnu++20 -O1 -arch arm64 -o "$out" "$here/harness.cpp" "$here/tramp.S" "$obj"
"$out" "$@"
