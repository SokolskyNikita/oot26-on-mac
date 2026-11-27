# jit-cache: tools for the shared JIT code cache (dynarmic arm64)

Write-up and results: [../../research/shared-jit-cache/README.md](../../research/shared-jit-cache/README.md).
The cache is in the pinned build, switched on by `EDEN_NX2_SHARED_JIT_CACHE=512` in the app's
`Contents/MacOS/nx2_switches.txt`.

| File | What |
| --- | --- |
| `patches/lichii/0007-dynarmic-arm64-one-A64-code-cache-shared-by-a-proces.patch` | The port as it is in the pinned build, with the review fixes |
| `patches/upstream/dynarmic-pr2101-tree-shared-jit-cache-with-tests.patch` | The same port in the PR-2101 tree (`zortos293/Lichii` `f27f16c247`), with all tests (`jit_shared_cache_tests`, the dynarmic block-table and replay tests) |
| `specs/shared-cache-128.json` | The pinned build at 512 MiB against 128 MiB, where the cache fills and is cleared during a load: the test for the full-clear path (run with `tools/harness/queue.sh`). The specs of the development rounds are not kept; their runs' `result.json` files hold them |

Switches (in the emulator): `EDEN_NX2_SHARED_JIT_CACHE=<MiB>` (multiples of 128, 128–2048; unset = private caches),
`DYNARMIC_JIT_TRACE=<file>` (record JIT operations for offline replay). Test settings:
`DYNARMIC_ARM64_REGION_SIZE=<bytes>` (smaller regions, so veneers happen in a small cache), `DYNARMIC_JIT_REPLAY=<trace>` with `dynarmic_tests "[jit_replay]"`.

The cache's diagnostics are read with [`tools/diag`](../diag/README.md): `stutter.py totals RUN…` gives the
whole-load JIT counters from a run's log (blocks, compile time, lock waits by kind, faults, discarded translations,
lookup hits), `stutter.py split RUN…` the per-frame core-time split (JIT run, compiling, lock wait, faults, guest
code) from an every-frame stutter trace (`EDEN_NX2_STUTTER_ALL_FRAMES=1`), and `jit.py trace RUN` a
`DYNARMIC_JIT_TRACE` recording. macOS's `sample` on a load is in its catalogue, level 6.

## Building and running the tests

Apply `patches/upstream/dynarmic-pr2101-tree-shared-jit-cache-with-tests.patch` to a checkout of the PR #2101 tree
(`zortos293/Lichii` at `f27f16c247`), then, in that checkout:

```bash
cmake -S . -B build/jit -G Ninja -DCMAKE_BUILD_TYPE=RelWithDebInfo -DBUILD_TESTING=ON -DLICHII_TESTS=ON -DDYNARMIC_TESTS=ON -DDYNARMIC_IGNORE_ASSERTS=OFF -DENABLE_QT=OFF -DLICHII_CMD=OFF -DLICHII_ROOM=OFF -DLICHII_ROOM_STANDALONE=OFF -DENABLE_WEB_SERVICE=OFF -DENABLE_UPDATE_CHECKER=OFF -DUSE_DISCORD_PRESENCE=OFF -DENABLE_WERROR=OFF -DVulkanHeaders_FORCE_BUNDLED=ON -DVulkanUtilityLibraries_FORCE_BUNDLED=ON "-DCMAKE_PREFIX_PATH=$(brew --prefix zlib)" "-DOPENSSL_ROOT_DIR=$(brew --prefix openssl@3)" -DLICHII_BUILD_PLATFORM=macos-arm64
```

```bash
cmake --build build/jit --target dynarmic_tests jit_shared_cache_tests
```

ThreadSanitizer: the same configure into `build/tsan` plus `-DCMAKE_C_FLAGS=-fsanitize=thread
-DCMAKE_CXX_FLAGS=-fsanitize=thread`. A test name with a comma needs a wildcard (`"Jits on one code cache run while
others compile*"`). Build with `nice -n 19 … -j 6` while emulator runs are going, or the harness won't wait for it.
