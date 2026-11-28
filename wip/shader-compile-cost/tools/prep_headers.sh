#!/bin/sh
# prep_headers.sh: preprocess Apple's texture class headers for Metal language 4.0 into ../local/pp/, where slim.py
# reads the method bodies. The headers are Apple's and are not kept in this repository.
set -e
cd "$(dirname "$0")"
I=$(ls -d /System/Library/PrivateFrameworks/GPUCompiler.framework/Versions/[0-9]*/Libraries/lib/clang/*/include/metal | head -1)
mkdir -p ../local/pp
for t in texture2d texture3d texture2d_array texturecube depth2d depth2d_array depthcube; do
    clang -E -P -x c++ -nostdinc -D__METAL_VERSION__=400 -D__METAL_MACOS__ -include "$I/metal_config" "$I/__bits/metal_$t" 2>/dev/null > ../local/pp/$t.h
done
wc -l ../local/pp/*.h
