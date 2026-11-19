# Metal's on-disk shader cache

What Metal keeps between launches, how big it can get, and how to see whether a compile was answered from it.
Everything was found on an M4 Pro, macOS 27.0 / 27.0.1, on 2026-11-17, with standalone probes
(`scripts/metal-probes/`) and the prebuild runs (`wip/shader-prebuild/local/emulator-prebuild/runs/`). Each claim is marked
**measured**, **read** (disassembly or source), **reported** (a named public source) or **inferred**.

## Summary

- The cache is two files per bundle id, one for MSL→AIR libraries and one for AIR→GPU code. Both are keyed per
  function, not per pipeline.
- **Each file holds at most 1 GiB.** `MTL_SHADER_CACHE_SIZE` and `FS_CACHE_SIZE` can lower that but never raise
  it. The value is 32 bits, so 4 GiB and its multiples switch the cache off.
- Eviction drops the oldest entries first. A preparation that writes more than the cap keeps only its last part.
- Every launch re-reads the size. A launch with a smaller value cuts an existing cache down at once.
- `MTL_LOG_COMPILE_STATS=2` logs, per pipeline and stage, whether the function came from the cache.
- Ways past 1 GiB: binary archives that the emulator owns ([binary-archives.md](binary-archives.md)). Short of
  that, the file has to be small enough to fit.

## Where it lives and what it holds

`$(getconf DARWIN_USER_CACHE_DIR)<bundle id>/com.apple.metal/` (**measured**: a test program with an embedded
`Info.plist` created exactly one new folder, named after its bundle id):

```
com.apple.metal/32024/libraries.data           MSL -> AIR
com.apple.metal/32024/libraries.list
com.apple.metal/16777235_467/functions.data    AIR -> GPU code
com.apple.metal/16777235_467/functions.list
```

- A cache miss also writes `$(getconf DARWIN_USER_CACHE_DIR)com.apple.gpuarchiver/`. `MTLSetShaderCachePath` does
  not move that folder. **Measured** (timestamps, and `pathtest.swift`).
- **The GPU-code cache works per function.** A pipeline whose fragment function was cached and whose vertex
  function was new sent one compile request, for the vertex function only. **Measured** (`mcdiag`, seeds 31–33
  against 1–3).
- **The two halves of a pipeline cost very different amounts.** Changing the blend state or colour format costs
  about 200 ms (fragment half). Changing the vertex stride or vertex function costs about 10 ms (vertex half). A
  depth format change costs 0 ms. **Measured** (`build/old-trees/compile-time/mtlx --pipe2`, one shader pair,
  5 repetitions).
- **Cold against warm.** In the prebuild app, 5,114 pipelines took 198.3 s cold and 3.5 s when prepared again
  (`t2`, `t3-warm-force`). The test program took 1,351 ms for its pipeline cold and 0.84 ms warm. **Measured.**
- **File format** (**measured** with `xxd` on a probe cache; layout also **reported** by `Lakr233/vphone-cli`):
  - A `.list` starts with a magic number `45 36 27 18`, a 32-byte stamp and an entry count, then 56 bytes per
    entry.
  - A `.data` entry is the body's SHA-256, then its key, then the body, padded in 64 KiB heaps.
  - The header count is not reliable: it stayed the same while the data grew, and read 0 in one run. Count entries
    by parsing the list.
  - A `.list` also holds an edit log and shrinks when Metal rewrites it, so judge fill by the `.data` sizes.

## The size limit

**Read** in `MTLCompilerFSCache::MTLCompilerFSCache` (Metal.framework, macOS 27):

```
size = MTLGetEnvDefault("MTL_SHADER_CACHE_SIZE", 0x40000000)   ; kept in 32 bits
size = MTLGetEnvDefault("FS_CACHE_SIZE", size)                 ; overrides the first
if (size >= 0x40000001) size = 0x40000000                      ; clamped to 1 GiB
else if (size == 0)     disabled = 1
```

There is no other branch, internal-build check or preference lookup in that routine. A public Hex-Rays dump of
iOS 26.1 (`EthanArbuckle/iPhone18-3_26.1_23B85_Restore`, `Metal.framework/Metal/Metal_04.mm`, lines 3613–3656)
shows the same code, so two separate readings agree. No public dump of another version shows the constructor.

What the probe (`cache_size_probe.m`, in its own app bundle, about 7 KB of `functions.data` per kernel) showed,
**measured**:

| Value | Result |
| --- | --- |
| 1 MiB on a new cache | both files capped near 1.1 MiB |
| 4 MiB on that cache | it grew to about 4 MiB: **the size is read at every launch**, not fixed when the files are made |
| 4 MiB, 600 kernels | 418 of 600 hit afterwards: the oldest were evicted |
| default, then 1 MiB on that cache | the 1 MiB launch **cut the cache back at once** to about 1.1 MiB |
| 2³² + 1 MiB | behaves as 1 MiB: only the low 32 bits count |
| 0, or 16 GiB | no files, nothing hits: cache off |
| `FS_CACHE_SIZE=1048576` alone | capped at 1 MiB: a second name for the same limit |

What the full prebuild passes showed (311,091 records, bundle id `io.github.zortos293.lichii.prebuild`),
**measured**:

| Run | Value | What happened |
| --- | --- | --- |
| `t5-full-resume` | default | Both files stopped growing at about 1.2 GB, 16 minutes into an 80-minute pass |
| `t6-warm-sample` | default | A repeat of the pass ran at the cold rate from its first record: the early entries were gone |
| `t7-warm-again` | default | Records compiled a minute earlier were answered at once |
| `t8-capsize-50MB` | 52428800, new bundle id | Both files stayed at about 50 MB (103 MB in total, against 314 MB uncapped for the same input) |
| `t9-full-16G` | 17179869184 | Nothing was written (2³⁴ is 0 in 32 bits) |
| `t10-full-4G` | 4294967295 | Files stayed at the default plateau, 1,244,053,504 and 1,220,706,304 bytes |
| `t11`, `t13` | 2147483647 | Files grew to about 1.27 and 1.28 GB, then stopped |
| `t14-warm-profile` | 2147483647 | A replay ran at about 45 records a second from the start, the cold rate (`runs/t14-sizes.txt` follows `runs/t6-sizes.txt` almost point for point) |

All of these fit the clamp. The plateaus of 1.16–1.19 GiB are 1 GiB plus slack from the 64 KiB heaps.

Public claims about raising the limit are wrong. `sharpemu/sharpemu-mac` (`MetalNative.cs`) sets 3 GiB, and its own
test only shows that a shader still hits, which the default also does. `nizwar/avo` sets 512 MiB, which is a lower
value and so is honoured. **Reported**, then explained by the reading above.

### How many entries fit

**Inferred** from the default plateau (`t7`) and a fresh cache filled by the canyon file (`.pred2`):

- About 19–25 KB per function (GPU code plus its reflection entry) and 35–45 KB per library.
- So one bundle id holds about **50,000–65,000 functions and 28,000–35,000 libraries**.
- The full 311,091-record file needs about 207,000 distinct functions and 50,000–70,000 libraries, which is 3.9–5.2
  GB of functions and 1.8–3.2 GB of libraries. That is an estimate from the file's structure; it was not recounted.

The file is prepared most-likely-first and eviction is oldest-first. A file that overflows therefore keeps its
*least* likely tail. A file meant for Metal's cache has to be trimmed to fit, or prepared in reverse order.

## Seeing hits and misses

**`MTL_LOG_COMPILE_STATS=2`** is the useful switch (**measured**):

- Every pipeline build, hits included, logs `Done compiling Metal pipeline, compile statistics: {…}`. The payload
  has `"Function was cached" = 0|1` and the function name for each stage.
- Each library that misses logs `Done compiling Metal library …` with `"Library was cached" = 0`. A library hit
  logs nothing.
- Mode 1 logs backend compiles (misses only). Mode 3 shows nothing. A path or `YES` counts as off.
- **The payload is `<private>` in the unified log.** Read it in-process with `oslogtap.dylib`, built from
  `scripts/metal-probes/oslogtap.c` (`DYLD_INSERT_LIBRARIES` works because Lichii is ad-hoc signed without hardened runtime). The other way is to
  turn on private data in the system log, which is a system setting and was not done.
- **Side effect:** any nonzero mode changes the *library* cache key, so the first run with stats on recompiles
  each library once (the cheap MSL→AIR step). The GPU-code entries are unaffected.

How to use it in Lichii (not tried yet): launch with
`DYLD_INSERT_LIBRARIES=<path>/oslogtap.dylib MTL_LOG_COMPILE_STATS=2`, then count lines in `stderr.log`:
`grep -c '"Function was cached" = 1'` against `grep -c '"Function was cached"'`. Open questions: whether
MoltenVK's asynchronous, mesh and compute pipeline paths log the same message, and whether the lines stay intact
when seven compiles run at once.

**Counting misses without injection.** Every miss sends a request to `MTLCompilerService`, which logs it publicly.
A hit sends nothing (**measured**):

```
/usr/bin/log stream --style compact --predicate 'process == "MTLCompilerService" AND eventMessage CONTAINS "ParentProcessName=lichii_"'
```

- `Compilation BEGIN … MTLBuildFunctions` counts function misses.
- `MTLBuildLibraryFromSourceToArchive` counts library misses.
- In zsh, `log` is a builtin, so use `/usr/bin/log`.
- For the test program the process name was `mcdiag_<pid>`; for Lichii, `lichii_<pid>` is expected but not checked.

### Variables that do not help

| Variable | Result |
| --- | --- |
| `MTL_DEBUG_LOG_CACHE_KEYS`, `MTL_DEBUG_LOG_FUNCTIONID_KEYS` | Do nothing on a retail OS. Their readers call `_MTLIsInternalBuild()` first and never call `getenv` (**read**; an interposed `getenv` confirmed it) |
| `MTL_WRITE_COMPILE_STATS_TO_JSON_FILE` | No file written; its reader is never called |
| `MTL_DUMP_PIPELINES_TO_JSON_FILE` | **Aborts the process** ("Dumping pipelines is not supported!"). Never set it |
| `AGX_LOG_SHADER_COMPILER_REQUEST=1` | **Breaks compilation** (`makeLibrary` fails). Never set it |
| `MTL_LOG_TO_STDERR`, `OS_ACTIVITY_DT_MODE` | No compile output; they belong to shader logging |
| `MTLPipelineOption.failOnBinaryArchiveMiss` | Applies to binary archives only, not to this cache |

Not tried: `FS_CACHE_RESET`, `FS_CACHE_REUSE_ON_REBOOT`, `MTL_DEBUG_IGNORE_PRECOMPILED_BINARIES`,
`MTL_DEBUG_IGNORE_PSO_FAIL_ON_MISS`, `MTL_DEBUG_PRINT_BINARY_ARCHIVE_URL_LOAD_ERRORS`, the debug-layer variables,
and Instruments' Metal signposts. The full list of `MTL_` names came from scanning Metal's strings
(`mtlstrings.swift`, `scan_metal_strings.py`).

## Rules for any approach that relies on this cache

1. **Never launch the bundle with a size below the default.** It cuts the cache down at once.
2. **Fit the file to the cap**, or prepare it least-likely-first. Otherwise the overflow evicts the most likely
   records.
3. **Reboots may clear it** (not tested). Metal and `libCoreFSCache` both read `FS_CACHE_REUSE_ON_REBOOT`, and
   vphone-cli found that an iOS guest's cache resets when the boot session changes. This Mac had not rebooted
   since 4 November, so no run has crossed a reboot. If a reboot loses it, set `FS_CACHE_REUSE_ON_REBOOT=1` and
   test again.
4. **`MTLSetShaderCachePath` gives a folder per build, not more room.** A process uses one folder at a time.
   - Call it before anything touches Metal (Qt included). A later call is ignored ("Ignoring call
     MTLSetShaderCachePath…").
   - It is private API, called through `dlsym`. WebKit, DXMT and Avo use it.
   - In Lichii it would go in `main()` before `StartupChecks`, next to the Linux NVIDIA cache setup
     (`SetUpNvidiaShaderDiskCache`).
   - It would end the need for a new bundle id per test app.
5. Whether macOS purges large caches under disk pressure was not checked.

## Not known

- Why `t10` stopped writing `libraries.*` after 13:17. Its plateau itself fits the clamp.
- The cause of the 9 `XPC_ERROR_CONNECTION_INTERRUPTED` compiles in `t10` and `t11` (none in `t13`).
- Behaviour on other macOS versions. The clamp is confirmed for macOS 27 and iOS 26.1 only.
