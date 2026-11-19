# Metal probes

Small tools for checking whether Metal's on-disk shader cache answered a compile. The write-up is
`wip/shader-prebuild/metal-shader-cache.md`.

Build everything, then run it twice (the first run is cold, the second warm, with per-stage "Function was cached"):

```sh
cd wip/shader-prebuild/scripts/metal-probes && sh build.sh && clang -dynamiclib -O1 oslogtap.c -framework CoreFoundation -o oslogtap.dylib && clang -dynamiclib -O1 getenvlog.c -framework CoreFoundation -o getenvlog.dylib && swiftc -O mtlstrings.swift -o mtlstrings && swiftc -O xref.swift -o xref
DYLD_INSERT_LIBRARIES=./oslogtap.dylib MTL_LOG_COMPILE_STATS=2 ./mcdiag --seed 1
```

- `mcdiag.swift`: compiles one fixed vertex and one fixed fragment MSL library and builds one render pipeline, timing
  each call. `--seed N` changes the source (the fragment source depends only on N % 10), `--reps`, `--sleep SEC`, and
  `--archive` (also adds the pipeline to an in-memory MTLBinaryArchive and rebuilds with failOnBinaryArchiveMiss).
  `build.sh` embeds `Info.plist` (bundle id `local.metal-cache-diag`), so its cache is
  `$(getconf DARWIN_USER_CACHE_DIR)local.metal-cache-diag/`. Delete that folder when you are done.
- `oslogtap.c`: a dylib that interposes `_os_log_impl` and prints Metal's "compil…" messages to stderr, with their
  `<private>` arguments decoded in-process.
- `getenvlog.c`: a dylib that logs each `getenv` (MTL/FS_/AGX/METAL/GPU names) and CFPreferences read, with the image
  that made it.
- `mtlstrings.swift`: loads Metal (plus any frameworks named as arguments) and prints the `__TEXT,__cstring` strings
  of every Metal, GPU or AGX image, one `image<TAB>string` per line.
- `xref.swift`: finds the code in Metal.framework that loads a given string (ADRP+ADD) and names the function. You
  can then disassemble that address with `lldb ./xref -o 'b exit' -o run -o 'disassemble -s ADDR -c 30'`.
- `cache_size_probe.m`: `probe CACHE_DIR FIRST COUNT [UNROLL]` points Metal's cache at `CACHE_DIR`
  (`MTLSetShaderCachePath`), compiles `COUNT` salted compute kernels and reports how many hit. Used for the
  `MTL_SHADER_CACHE_SIZE` steps in `../../metal-shader-cache.md`. Build it as an app with its own bundle id so the
  `com.apple.gpuarchiver` writes (which the cache path does not move) stay out of shared folders:
  `clang -fobjc-arc -O1 cache_size_probe.m -framework Foundation -framework Metal -o probe`, then put `probe` in
  `probe.app/Contents/MacOS/` with `cache_size_probe.Info.plist` as `probe.app/Contents/Info.plist`.
- `scan_metal_strings.py`: loads Metal in Python (no device) and prints the C strings of Metal and
  `libCoreFSCache`; this is where the `FS_CACHE_*` names came from.
