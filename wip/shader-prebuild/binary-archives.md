# Binary archives in MoltenVK: the route past Metal's 1 GiB cache

Metal's own cache holds at most 1 GiB per file ([metal-shader-cache.md](metal-shader-cache.md)), and the full
precompiled file needs several times that. An `MTLBinaryArchive` is a file the emulator owns, with no size cap and
no eviction. This note covers what the standalone probe showed and the plan for MoltenVK. Nothing has been built
in MoltenVK yet. Each claim is **measured** (probe, M4 Pro, macOS 27.0.1, `MTL_SHADER_CACHE_SIZE=0`), **read**
(source or headers), **reported** (a named third party) or **inferred**.

## Result

- **Archives alone, used the obvious way, cover only half.** Setting `binaryArchives` on pipeline descriptors
  keeps the AIR→GPU-code step. Every process still compiles the library from MSL, because a lookup needs the
  descriptor's `MTLFunction` objects. **Measured:** library 318–618 ms every process, then the pipeline from the
  archive in 1.6 ms, against 4,330–5,165 ms without it.
- **The same archive file also works as a library.** A serialised `MTLBinaryArchive` opens with
  `newLibraryWithURL:` or `newLibraryWithData:`. It lists every function that went into it through a pipeline:
  0.4–12.5 ms to load, against 318–618 ms to compile the MSL. Pipelines from those functions are then found in
  the archive (strict lookup, 0.2–0.8 ms). **Measured.**
  - That this works is not documented in `MTLBinaryArchive.h`, so a future macOS could change it. **Read.**
  - If it changes, the fallback is the normal compile, so the risk is speed, not correctness.
- **So archives can replace both cache files.** That needs pipelines looked up in the archives *and* libraries
  loaded from the archive files instead of compiled from MSL.
- **Estimate: about 7 working days** plus about 3 hours of machine time. **Inferred.**

## Probe measurements

`scripts/archive-probe/batest.swift`, each mode in its own process. The shaders are synthetic: a vertex function, a
fragment function of 600 unrolled `sin`/`cos`/sample statements (150 or 20 in some modes), a trivial kernel, and a
mesh + fragment pair. The 4–5 s compile comes from that shader. The game's figures are about 200 ms (fragment GPU
code) and 260 ms (fragment library). **Measured:**

| Step | Time |
| --- | ---: |
| Library from MSL (every process) | 318–618 ms |
| Render pipeline, cold | 4,408 / 4,966 / 5,165 ms |
| `addRenderPipelineFunctions` *after* that create | 4,725 ms: it compiles again |
| Add first, then create from the in-memory archive | add 517–555 ms (150-statement shader); create 1.6 ms |
| Compute / mesh compile; add | 6–7 / 18–24 ms; 6 / 15 ms. Mesh works |
| Serialise 3 pipelines (839,344 bytes) | 20 ms |
| Load the archive file | 0.75 ms |
| Render / compute / mesh from archive, strict, new process | 1.6 / 0.1 / 9.7 ms |
| Strict lookup with another label, or a depth format added | hit (0.4, 0.2 ms) |
| Strict lookup with vertex stride 48, or blending on | miss in 0.1 ms ("Unable to find function fmain … in binary archives") |
| Library from source with one comment added, then strict lookup | library 317 ms, pipeline hit 0.3 ms (the key is the AIR function hash) |
| Library from the archive file / from its bytes | 0.8–12.5 ms / 0.4 ms |
| Pipeline from that library, no archive, new process | 4,935 / 4,330 ms: the library holds AIR, not GPU code |
| Pipeline from that library, with the archive | 0.2–0.8 ms |
| Two libraries with the same entry names in one archive | come back as `fmain`, `vmain`, `__fmain_1`, `__vmain_1`; both pipelines hit |

Other facts from the probe and the SDK:

- **A library reaches an archive only through a pipeline.** `addFunctionWithDescriptor:library:` with a vertex
  or fragment function returns success, but the archive then says "Nothing to serialize". **Measured.**
- **Serialising works only to a file URL.** A missing file gives "Invalid URL", so check that the file exists
  before loading. **Measured.** This was the blocker in MoltenVK#1765 for `vkGetPipelineCacheData`. It does not
  apply here, because the archive is our own file.
- **No offline compiler is installed.** `xcrun -f metal` fails, and only Command Line Tools are present, so
  `.metallib` files cannot be precompiled without Xcode. **Measured.**
- `MTLDynamicLibrary` only serves compute (`preloadedLibraries`), so it is not a way to keep vertex or fragment
  functions. **Read.**
- Metal 4 (`MTL4Archive`, `MTL4PipelineDataSetSerializer`, macOS 26+) would need MoltenVK to move to
  `MTL4Compiler`, a much larger change. **Read**, headers only.

### Sizing, inferred

Both cache files stopped at about 1.2 GB after about 117,000 of 311,091 records. That suggests about 10 KB of
GPU code and 10 KB of library per record, so **about 5–7 GB of archives** for the full file. The error is easily
±50%. Scale step 1 replaces this with a measurement.

- **Collection memory.** An in-memory archive keeps everything until it is serialised, and `serializeToURL:`
  rewrites the whole file. So use segments that are written once and never appended. At about 50 MB per segment
  and 7 threads, expect about 1–1.5 GB on top of the 7.2 GB preparation peak.
- **Load.** A 0.8 MB file loads in 0.75 ms. Multi-GB files are not measured; memory-mapped loading is assumed.
- **Staleness.** The archive key includes hashes of the "air-nt plugin" and the "metal framework" (**measured**,
  from Metal's miss message). So an OS update makes every pipeline miss and the collection has to run again. A
  change to the MoltenVK, SPIRV-Cross or Lichii translation changes the MSL, so the library keys miss too.

## Where it goes in MoltenVK

**Read** in the MoltenVK tree of that time (`8fc3c2af` plus local changes; today `build/src/moltenvk`, branch `gold`). The tree has no
`binaryArchive` code. Every Metal pipeline goes through three functions:

- `MVKRenderPipelineCompiler::newMTLRenderPipelineState(MTLRenderPipelineDescriptor*)` (`MVKPipeline.mm:3133`),
  for render and the tessellation stages.
- The `MTLMeshRenderPipelineDescriptor*` overload (`:3150`).
- `MVKComputePipelineCompiler::newMTLComputePipelineState` (`:3185`).

The callers are `MVKGraphicsPipeline::getOrCompilePipeline` (`:1018`, `:1030`) and `MVKComputePipeline` (`:2500`).
Only the watermark and the internal command shaders call Metal's pipeline APIs elsewhere.

Libraries are compiled eagerly in `MVKShaderLibrary::compileLibrary` (`MVKShaderModule.mm:277`), through
`newMTLLibrary` (`:656`, `newLibraryWithSource` at `:681`). That happens before any pipeline call. MoltenVK already
loads compiled libraries with `newLibraryWithData:` (`:352`), and the library hook can reuse that call.

MoltenVK holds `@synchronized (mtlDev)` around every library and pipeline creation (`MVKPipeline.mm:3137`, `:3155`,
`:3190`; `MVKShaderModule.mm:662`). Synchronous archive adds and serialisation must stay outside that lock, or they
serialise preparation.

Lichii passes `pSpecializationInfo = nullptr` everywhere, so the macro-variant and function-constant recompiles
(`MVKShaderModule.mm:154`, `MVKFunctionSpecializer`), which archives do not cover, should not run for this game.
**Read** (grep).

## Plan

Times are working time. Steps 7 and 8 need the emulator.

1. **Scale probe, standalone (0.5 d).** Extend `batest.swift` to 2,000–5,000 real shaders
   (`extract_msl.py`/`extract_spv.py` pull them out of the caches), written in segments of 500, 2,000 and 10,000
   entries. Measure:
   - bytes per entry, serialise time per segment, and memory while collecting;
   - load time and memory of a large segment, opened as an archive and as a library;
   - lookup time with 1, 8 and 64 archives in `binaryArchives`;
   - whether concurrent `add…Functions` calls on one archive are safe.

   This decides the segment size and whether each worker thread needs its own archive. It was started on
   2026-11-17 and stopped before it produced results.
2. **Design (0.5 d).**
   - Directory `<dir>/<identity>/`, where the identity is the macOS build, GPU name, MoltenVK revision and a hash
     of the compile options.
   - Segments `seg-NNNNN.metalarchive`, each written once to a temp file and renamed.
   - `index.bin` maps a library key (hash of the MSL and options) to its segment and function name.
   - Unique entry-point names (`f<key>`): SPIRV-Cross names nearly every entry point `main0` (**assumed**), and
     duplicate names come back renamed.
   - Switches `MVK_BINARY_ARCHIVE_DIR`, `MVK_BINARY_ARCHIVE_MODE=collect|use|off`, and `MVK_BINARY_ARCHIVE_STRICT=1`
     for tests.
3. **Archive manager on `MVKDevice` (1.5 d).**
   - Load the index at device creation, and open segments lazily.
   - In collect mode, give each worker thread one collecting archive. Rotate it at the segment size and serialise
     it off the creating thread.
   - Flush at `vkDestroyDevice`.
4. **Pipeline hooks (1 d), in the three functions above.**
   - Use mode: set `binaryArchives` from the index and call the existing asynchronous create, with
     fail-on-miss in strict mode only.
   - Collect mode: call `add…Functions` *first*, then create with that in-memory archive in `binaryArchives`.
     Adding after a normal create compiles twice.
   - Count hits and misses per stage and log them at device destruction.
5. **Library hook (1 d).** In `compileLibrary`, look up the key before `newMTLLibrary`. On a hit, use the
   segment's library (opened once) as `_mtlLibrary`. Rename entry points in the SPIR-V→MSL step. Whether that is
   safe for MoltenVK's reflection was not read.
6. **Switch (0.25 d).** Lichii itself needs no change: its preparation already builds every record and drops it,
   which is what collect mode needs. The environment variables go in the launch script or `LSEnvironment`.
7. **Small end-to-end test (1 d, emulator).** Build MoltenVK with `path-60/build.sh mvk` and collect the 5,114-record
   `t2` subset (`scripts/prebuild/subset.py`). Then use it with `MTL_SHADER_CACHE_SIZE=0` and a fresh bundle id.
   - Expect close to `t3`'s 3.5 s, not `t2`'s 198 s, with zero strict misses.
   - Compare screenshots against `runs/exp-base/shots/_poll.png`.
8. **Full collection and first-visit test (0.5 d of work, about 3 h of machine time, emulator).** Collect all
   records. Compare the time against 105 minutes, the disk use, and peak memory against 7.2 GB. Then repeat the
   `exp-pred2` first-visit run twice with Metal's cache off.
9. **Failure handling (0.5 d).**
   - Drop a segment that Metal refuses.
   - Keep a checksum per segment.
   - Ignore a directory whose identity has changed, and offer to delete it.
   - After a crash mid-collection, the next pass collects the lost entries again.
10. **Write-up and upstream (0.25 d).** Offer the patch on KhronosGroup/MoltenVK#1765.

### Risks, worst first

1. **Scale is unmeasured.** Nothing has gone past 3 pipelines per archive. Step 1 exists to find out before any
   MoltenVK work.
2. **Reading an archive as a library is undocumented** (see above).
3. **Silent misses.** A key or index mistake, or a descriptor difference that matters (blend, stride), falls back
   to a full compile with no error. Strict mode and the counters guard against it.
4. **macOS updates** force a full re-collection. Whether the AIR in an archive still loads after an update is
   assumed, not tested.
5. **Disk**: about 5–7 GB, separate from Metal's own cache, which play still fills.
6. **Concurrency**: 7 parallel compiles may need one archive per thread.
7. **Divergence**: a large local patch on a MoltenVK that already carries several.

## Prior work

- KhronosGroup/MoltenVK#1765 (open since 2022-11-10) has no linked PR. Upstream PRs #1847 and #1968 only mention the
  topic.
- `TarbleFR/RewindBox`, `build-utils/melonx/metal-archive/moltenvk-v1.4.2-binary-archives.patch` (710 lines):
  - hooks the same three functions, collects on a serial queue, and uses segments with identity directories and
    checksums;
  - covers pipelines only, and was not integrated because library creation was 81–84% of the time in their iPhone
    logs;
  - has no mesh support.
- `braedonsaunders/caboose`, `moltenvk-pipeline-binary-archive.patch` (223 lines): render and compute only, one
  archive.
- `dttdrv/mullion` issue 171: the maintainer's fix for re-compiles on the second launch keeps pipelines in an
  archive beside their own cache.

None of these loads libraries from the archive. Their figures are from other hardware and were not reproduced
here. **Reported.**

## Not known

- Anything at scale, and anything through MoltenVK or Lichii.
- Whether SPIRV-Cross really names nearly every entry point `main0`, and whether renaming is safe.
- Whether AIR in an archive loads after a macOS update.
- Whether concurrent `add…Functions` calls are thread-safe.
- Whether pipelines served from an archive also enter Metal's own cache. A third party says they do not.
