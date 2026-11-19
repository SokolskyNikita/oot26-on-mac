# build: swiftc -O mcdiag.swift -o mcdiag -Xlinker -sectcreate -Xlinker __TEXT -Xlinker __info_plist -Xlinker Info.plist
# run:   ./mcdiag --seed 1      (run twice: first cold, second warm; cache in $(getconf DARWIN_USER_CACHE_DIR)local.metal-cache-diag/com.apple.metal/)
cd "$(dirname "$0")" && swiftc -O mcdiag.swift -o mcdiag -Xlinker -sectcreate -Xlinker __TEXT -Xlinker __info_plist -Xlinker Info.plist
