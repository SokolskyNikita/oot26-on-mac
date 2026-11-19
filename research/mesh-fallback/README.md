# Per-shader mesh fallback by real threadgroup memory



The remake draws foliage and props with mesh shaders. MoltenVK with the pending mesh-shader work
(KhronosGroup/MoltenVK#2842) runs most of them natively in Metal, but a few need more than Metal's 32,768 bytes of
threadgroup memory, and their pipelines fail. This write-up covers a Lichii change that sends only those few to
Lichii's mesh emulation, how to build and run it, and what it does in Kokiri Forest.

- **Date:** 2026-11-16, on an Apple M4 Pro (Mac16,8) under macOS 27.0.1. Lichii#1970's head `1f76c9ff5` plus the
  change (local commit `9537add83`; in the pinned build as
  `patches/lichii/0002-vulkan-demote-a-mesh-program-only-when-its-native-MS.patch`), MoltenVK main `5189f8d` + #2842 +
  #2843, SPIRV-Cross `e99dc7a` (the merge of SPIRV-Cross#2686), `maxPushDescriptors` set back to 16.
- **Run labels** (`fb-dump`, `fb-allemu`, `fb-nativeonly`) name local run folders, which are not tracked.
- **Background:** [../mac-performance/README.md](../mac-performance/README.md).

## Result in short

| What | Result |
| --- | --- |
| Size rule | Works. The prediction matches the MSL to the byte for all 49 native mesh shaders, and gives Metal's own numbers for the 4 it demotes. |
| Counts (Kokiri Forest, top save) | 53 mesh programs: 49 native, 4 emulated. No threadgroup-memory errors, no failed pipelines. |
| Picture | **Wrong in this build.** Foliage and canopy are drawn, but as white or multicoloured shards. The cause is the native mesh path itself, not mixing native with emulated draws (see [The picture](#the-picture)); both faults behind it were fixed later and the pinned build's picture matches stock. |
| Speed | Not established here. Every run was made with the load average at 10–18 from other builds on the machine, and the picture was wrong anyway. A later reading is in [emulator-options](../emulator-options/README.md). |

## 1. The rule

Lichii#1970 demotes a mesh program when it exceeds MoltenVK's reported `maxMeshSharedMemorySize` /
`maxMeshOutputMemorySize` (12,284 bytes each). Those are a fixed share of the real limit, so 36 of the 43 mesh
shaders the cache had reached at the time were demoted although they fit.

The real limit is Metal's `maxThreadgroupMemoryLength`: 32,768 bytes, which Lichii already has as
`device.GetMaxComputeSharedMemorySize()`. Metal counts every `threadgroup` variable the MSL entry point declares.
Lichii decides at pipeline creation, before any SPIR-V or MSL exists, so the branch adds up what those variables will
be from the program's mesh info (`NativeMeshThreadgroupMemorySize` in
`src/video_core/renderer_vulkan/mesh_fallback_limits.h`):

| Part | Source | Bytes |
| --- | --- | --- |
| `isbe_attributes` | Lichii `DefineMesh`: 32-word lines for each group of 32 vertices and 32 primitives | 4 × (⌈V/32⌉·vertex_lines·32 + ⌈P/32⌉·primitive_lines·32), at least 4 |
| `isbe_map` | Lichii `DefineMesh` | 4 × (4 + k·P) with k = 1, 2 or 3 indices per primitive |
| `isbe_primitive_count` | Lichii `DefineMesh` | 4 |
| Staged outputs | SPIRV-Cross declares every mesh `Output` array as a `threadgroup` array | 16·V per vertex generic index, 16·V for Position, 4·V for PointSize (points or when written); 16·P per per-primitive generic, 4·P per PrimitiveId / Layer / ViewportIndex |
| Index array | SPIRV-Cross (`gl_Primitive*IndicesEXT`) | P × 4 / 8 / 16 (points / lines / triangles: `uint3` is 16 bytes) |
| Shared memory | Lichii `DefineSharedMemory` (never explicit layout in a mesh program) | ⌈size/4⌉·4, plus a 4-byte lock with 64-bit shared exchange |
| `spvMeshSizes` | SPIRV-Cross | 8 |

V and P are the program's max vertices and primitives. The task payload is `object_data` in MSL, not threadgroup
memory, so it is not counted. A generic counts once however many of its four components are written: every output
is a `float4`.

The vertex data is held twice (once in `isbe_attributes`, once in the staged outputs). That is why programs with
128 vertices and 23–25 lines go over.

A mesh program is demoted when the total exceeds the limit, or when its vertex or primitive count exceeds MoltenVK's
`maxMeshOutputVertices` / `maxMeshOutputPrimitives`. A task program is demoted when its shared memory (plus lock)
exceeds the limit or its payload exceeds `maxTaskPayloadSize`. Demoting either one emulates the whole pipeline's mesh
stage, as in #1970.

Every mesh pipeline logs its decision:

```text
Mesh fallback: pipeline 491d1ead583121c9 mesh program d395e5a0ccbe218f: 34076 B threadgroup memory
  (isbe 12564 + outputs 21504 + shared 0 + 8; 128 vertices, 64 primitives, 23+0 lines), limit 32768 B: emulating
```

When a native mesh program's SPIR-V is emitted, it also logs MoltenVK's hash of that SPIR-V (`mvkHash`, the name of
MoltenVK's dump files and the id the other write-ups use). The Lichii id in these lines is most likely the pipeline-level one
(`unique_hash` XOR `MeshStateHash()` for mesh and task stages, `shader_cache.cpp:291`, read; the logging code of
that build is gone, so not confirmed), which is why it differs from the
per-program `unique_hash` that [shader-extraction](../shader-extraction/README.md) lists:

```text
Mesh fallback: native mesh program d395e5a0ccbe218f is MoltenVK shader aad4571246c8d55c, predicted 34076 B threadgroup memory
```

`EDEN_NX2_MESH_TG_LIMIT=<bytes>` overrides the limit for testing. The PR's own switches are kept:
`EDEN_NX2_MESH_NATIVE_ALWAYS=1` (all native, no demotion) and `EDEN_NX2_FORCE_MESH_FALLBACK=1` (all emulated).

### Why a prediction, not catching the failure

Catching the failed native pipeline would need a second pipeline build after the first one fails, inside the
asynchronous build path. The prediction is cheap, made once per pipeline, and turned out to be exact (next section),
so the catch is not needed. It remains a useful safety net for shapes this game hasn't shown.

## 2. Checking the prediction

Run `fb-dump` (below) was made with `MVK_CONFIG_SHADER_DUMP_DIR` set, so MoltenVK wrote the MSL of
every shader it converted. A local script, `check_prediction.py <eden_log> <dump dir>`, pairs each "is
MoltenVK shader" line with that hash's `.metal` file and compares the prediction with `tg_audit.py`'s sum:

- **49 of 49** native mesh shaders: predicted = actual, to the byte (5,604 to 28,700 bytes).
- The 4 demoted programs have no MSL in that run, because they were never built natively. Run `fb-nativeonly`
  builds them natively, and Metal's errors there give exactly the predicted sizes:

| Guest program | MoltenVK shader | Predicted | Metal's error |
| --- | --- | --- | --- |
| `d395e5a0ccbe218f` | `aad4571246c8d55c` | 34,076 | 34,076 |
| `0cec5d2541c9d72e` | `efdc2d865aa74afe` | 35,100 | 35,100 |
| `e735bfea4ba8927c` | `0c69b95fb5fc198e` | 35,100 | 35,100 |
| `1c766c30164ac236` | `f745a892263a512e` | 42,012 | 42,012 |

In these runs the cache holds 53 mesh programs.

## 3. Building it

How the test build was made on 2026-11-16. The pinned build is made by `./build.sh` from `patches/` instead.

MoltenVK (under a minute):

1. Clone KhronosGroup/MoltenVK and check out `5189f8d`.
2. Merge `pull/2842/head`, then `pull/2843/head`. One conflict, in `MVKPipeline.mm`:
   - `getShaderOutputs` takes #2842's `meshDesc ? spv::ExecutionModelMeshEXT : spv::ExecutionModelVertex` and #2843's
     extra specialization-values argument.
   - The cereal size checks take #2843's numbers.
3. Set `supportedProps14.maxPushDescriptors = 16` in `MVKDevice.mm`.
4. Put `e99dc7a38daa790eff5425cee18129d9d5b26176` in `ExternalRevisions/SPIRV-Cross_repo_revision`.
5. Build: `cmake -G Ninja -S . -B build -DCMAKE_BUILD_TYPE=Release && cmake --build build`. This produces
   `build/MoltenVK/libMoltenVK.dylib`.

Lichii:

1. `git fetch origin pull/1970/head`, then branch from it (`1f76c9ff5`). Commit `9537add83` holds the change, in
   `mesh_fallback_limits.h` and `vk_pipeline_cache.cpp`.
2. Configure with the macOS flags from Lichii's `release-binaries.yml` (Homebrew `qt@6`, `zlib`, `openssl@3`;
   `ENABLE_UPDATE_CHECKER=OFF`), then build: `cmake --build build/release --target lichii`. A full build is about
   1,870 steps. Use `-j2` while measurements are running.
3. The result is `build/release/bin/lichii.app`. It links Homebrew's Qt and other libraries.

App:

1. `ditto` the built app into a separate folder.
2. Replace `Contents/Frameworks/libMoltenVK.dylib` with the MoltenVK build.
3. Re-sign: `codesign --force --sign - --preserve-metadata=entitlements <app>`. This keeps the
   PR's `com.apple.security.hypervisor` entitlement. `codesign -v` reports "code has no resources" on this bundle,
   exactly as on the untouched build output, and the app runs.



## 4. Running it

Use the shared harness, which holds the one emulator lock and never kills a Lichii it didn't start:

```bash
tools/verify/verify.py run <app> LABEL --out <run folder> --lock-wait 1800 [ENV=VALUE ...]
```

It boots, loads the top save, stands 35 s, walks the `measure.sh` route twice, and takes screenshots at the spawn
point (`spawn-a`, `spawn-b`) and on the walk. It writes frame times, error counts, load average and config/cache
state to `meta.json` and `result.json`, and screenshots to `shots/`. `verify.py compare REF CAND` diffs two runs.

## 5. Results

All runs: Kokiri Forest, top save, 1x, the emulator settings of the time (unchanged by these runs), the same app
and the same cache.

| Run | Switches | Mesh programs | Metal errors | Spawn picture | Standing median, ms | Load avg at start |
| --- | --- | --- | --- | --- | --- | --- |
| `fb-dump` | `MVK_CONFIG_SHADER_DUMP_DIR=…/runs/dump1` (default rule) | 49 native, 4 emulated (8 pipelines) | none | glitched | 41.0 (dump on) | 10.1 |
| `fb-allemu` | `EDEN_NX2_FORCE_MESH_FALLBACK=1` | all emulated | none | **correct** | 51.5 | 17.9 |
| `fb-nativeonly` | `EDEN_NX2_MESH_NATIVE_ALWAYS=1` | all native; the 4 oversized fail | 8 threadgroup errors (34,076 ×2, 35,100 ×4, 42,012 ×2), 16 failed pipelines | glitched, worse | 45.0 | 15.6 |
| `stock228-ref` (the verify harness's reference run) | stock build 228 | all emulated | 152 sampler-array errors | correct (reference) | 42.5 | 53.9 |

- In `fb-dump`, the 8 emulated pipelines built and drew on every frame ("Mesh emulation draws: 8000 (0 with no
  groups)").
- All three runs log "Draw skipped (no pipeline)" for some vertex/pixel pipelines (51 / 31 / 9). The stock reference run
  and a run of Lichii `7c7f723` on MoltenVK main have them too (55 / 36). They are not mesh pipelines.

### The picture

The `spawn-b` shot of `fb-dump` against the same shot of the stock reference run:

- Trees, rocks, Link, the path and the HUD are correct.
- The canopy, and the leaves anywhere in view, are drawn as flat white or randomly coloured shards in roughly the
  right places. The upper half of the screen is blown out.
- The grass and ferns at ground level are missing.
- On the walk (`walk1-r2.png`) the leaves around the Deku-tree house are white flakes.
- `verify.py compare` flags 18–54% of tiles changed in every shot.

Which side causes it:

- **All emulated (`fb-allemu`) is correct**: canopy, leaves and grass match stock 228. So this MoltenVK build (with
  push descriptors at 16), the emulation, and the rest of the frame are fine.
- **All native with nothing emulated (`fb-nativeonly`) is glitched, worse than the mixed run**: most of the screen
  is white haze and leaf shards. No pipeline mixes native and emulated draws here, so the glitch is not caused by
  mixing.
- So it comes from the native mesh path: Lichii's native mesh SPIR-V, SPIRV-Cross's MSL for it, or MoltenVK #2842's
  handling.
- The PR author's glitched experiment (`MVK_MESH_THREAD_OUTPUTS=1` with `EDEN_NX2_MESH_NATIVE_ALWAYS=1`) is the same
  symptom, so `MVK_MESH_THREAD_OUTPUTS` is not needed to cause it.

The cause is traced in [mesh-native-colours](../mesh-native-colours/README.md): MoltenVK reports no subgroup support
for the mesh and task stages, so Lichii lowers the game's warp operations to single-thread code in native mesh
shaders. Fixing that turns the canopy green. The remaining shards, the upside-down foliage and the missing ground grass were
then traced to the mesh position output (SPIRV-Cross issue #2717: no Y flip and no depth fixup) and fixed; both
fixes are in the pinned build ([mac-performance](../mac-performance/README.md), cause 4). The shader dump of
`fb-dump` (2,842 files, local) holds this build's SPIR-V and MSL for every shader converted, with the default rule
(49 native mesh shaders).

### Speed

Not measured cleanly. Other builds on the machine kept the load average between 10 and 18 during every run (54 for the
stock reference), and the reference numbers (28.6 ms native with the 3 dropped, 34.3 ms all emulated) were taken on
a quiet machine. The ordering in these runs matches expectations: native-heavy is faster than all emulated
(45 and 41 ms against 51.5). But the dump slowed `fb-dump`, and a frame-time comparison is only worth making once the
native picture is right, back to back with low load.

### Shader cache and config

- Before the first run, `~/.config/lichii/qt-config.ini` and `~/.cache/lichii/shader` were backed up, with
  SHA-1s.
- No run changed the config.
- Every run grew both cache files, `lichii-cache.v2.bin` and `vulkan_pipelines.fork-v54.bin`: Lichii appends the
  new pipelines (the 53 mesh programs, including the emulated variants). Other runs used the cache in between,
  so it was not restored.

## Not done yet

- A clean frame-time comparison of this rule against all emulated, back to back, at low load. The nearest reading is
  on the later pinned build: all emulated 23.5 / 23.2 / 21.2 ms against 20.3 / 21.3 / 19.1 ms with this rule
  ([emulator-options](../emulator-options/README.md)).
- Catching a failed native mesh pipeline and retrying it emulated, as a safety net behind the prediction.
- Task programs: none was demoted in these runs, and the 8 emulated pipelines have none ("task false"); the task half
  of the rule only logs when it demotes, so whether native pipelines here use task programs was not checked.
