# Metal runtime validation on the native mesh path

Done 2026-11-16 on an Apple M4 Pro (Mac16,8) under macOS 27, Command Line Tools only. The question: with Metal's
API debug layer and shader validation switched on, does Metal flag anything that explains what is still wrong with
natively drawn foliage after the subgroup fix (the `fix-app` build of
[mesh-native-colours](../mesh-native-colours/README.md)): white shards across the canopy and middle ground, and the
ground grass (turf4, Lichii mesh program `717b82304a8d8db5`) missing. Both symptoms were later traced to the mesh
position output (no Y flip, no depth fixup) and fixed in the pinned build
([mac-performance](../mac-performance/README.md), cause 4). Wrong positions are in-bounds data, which fits the result
below (inferred).

**Measured** means a run or probe on the M4 Pro showed it. **Inferred** means a reading. The scratch files, runs and
helper scripts named below were local and are not tracked.

## Verdict

Metal validation reports nothing that explains either symptom. In about 1,100 frames standing at the spawn point,
shader validation found no out-of-bounds buffer read, no out-of-bounds threadgroup access and no unbound texture in
any mesh, object or fragment function. That includes turf4. The API debug layer rejected no mesh draw. Every error
it reported also appears, at nearly the same count, in the all-emulated control run, whose picture is correct. Under
validation the picture is unchanged: shards present, grass missing.

This neither confirms nor rules out the missing NaN prologue. A mesh shader that emits a vertex it never wrote
reads threadgroup memory that is in bounds, only stale, and a probe shows Metal does not flag that (section 1). What
the result does exclude is a second, independent fault of a kind validation sees: a read past the end of a bound
buffer or a threadgroup array, or a null texture, in the native mesh pipelines.

The NaN-prologue build (`fix2-app`, Lichii `9537add839` with the NaN guard) gave the same 3
messages under shader validation, and its spawn shot still shows white shards and no ground grass (section 5).

## 1. The variables, and what they cover

From `man MetalValidation`. All must be set before the Metal device is created, so they go in Lichii's
environment.

| Variable | Used | Meaning |
| --- | --- | --- |
| `MTL_DEBUG_LAYER` | `1` | API validation (CPU-side use of the API: bindings, buffer sizes at draw time, object lifetime) |
| `MTL_DEBUG_LAYER_ERROR_MODE` | `nslog` | log errors instead of the default `assert` (abort); `ignore` is the third option |
| `MTL_DEBUG_LAYER_WARNING_MODE` | `nslog` | log warnings too (default `ignore`) |
| `MTL_SHADER_VALIDATION` | `1` | GPU validation: instruments every shader |
| `MTL_SHADER_VALIDATION_REPORT_TO_STDERR` | `1` | reports to stderr instead of only the unified log |
| `MTL_SHADER_VALIDATION_RESOURCE_USAGE` | `0` | turns off the residency check; needed here, see section 2 |
| `MTL_SHADER_VALIDATION_FAIL_MODE` | default `zerofill` | invalid reads return 0, invalid writes are dropped (`allow` lets them through) |
| `MTL_SHADER_VALIDATION_ABORT_ON_FAULT` | default `0` | shader-validation errors are only logged, not fatal |
| `MTL_SHADER_VALIDATION_DEFAULT_STATE` + `_ENABLE_PIPELINES` / `_DISABLE_PIPELINES` | not used | `none` plus a comma-separated list of pipeline labels or UIDs limits instrumentation to chosen pipelines; UIDs come from `MTL_SHADER_VALIDATION_DUMP_PIPELINES=1` (unified log, "Shader Validation UID") |

Other checks are on by default: `_GLOBAL_MEMORY`, `_THREADGROUP_MEMORY`, `_TEXTURE_USAGE` (nil texture, wrong
type), `_NAN_INF` (NaN or Inf written into a vertex-stage interpolant other than position), `_STACK_OVERFLOW`.

**Are mesh and object functions covered?** The man page does not say. A probe answers it (measured,
a probe program `coverage.swift`, built with `swiftc`, 14 pipelines each making one deliberate fault chosen
at run time):

| Fault | vertex | fragment | mesh | object |
| --- | --- | --- | --- | --- |
| device-buffer read past the end | reported | reported | reported | reported |
| threadgroup array index past the end | – | – | reported | reported |
| read from an unbound (nil) texture | reported | reported | reported | not tried |
| NaN into a user interpolant | not reported | – | not reported | – |
| mesh vertex emitted but never written (`set_index` to it, no `set_vertex`) | – | – | not reported | – |
| index past the declared vertex count | – | – | not reported | – |

Reports name the stage ("executing mesh function"), the pipeline UID and `program_source:LINE:COL`. So mesh and
object stages are covered for memory bounds and textures, but not for unwritten or stale data, and not for bad
indices. The NaN check did fire in the emulator (section 3), so it works on real vertex shaders; why it stayed quiet
in the probe was not followed up.

## 2. How to repeat the runs

Every run went through the emulator lock with a wrapper, `run_to_spawn.sh`. It calls `verify.py run`
([`tools/verify`](../../tools/verify/README.md)) on a copy of the app (`fix-app` or `fix2-app`, SHA-1-identical to the
originals), writes to `runs/LABEL/`, and sends SIGTERM to its own verify process once the second spawn shot is taken
(verify kills its Lichii with SIGKILL and frees the lock).

```bash
./run_to_spawn.sh fix-debuglayer MTL_DEBUG_LAYER=1 MTL_DEBUG_LAYER_ERROR_MODE=nslog MTL_DEBUG_LAYER_WARNING_MODE=nslog
```

```bash
./run_to_spawn.sh fix-shaderval MTL_SHADER_VALIDATION=1 MTL_SHADER_VALIDATION_REPORT_TO_STDERR=1 MTL_SHADER_VALIDATION_RESOURCE_USAGE=0
```

Add `EDEN_NX2_FORCE_MESH_FALLBACK=1` for the control, and `APP=<fix2-app>` for the NaN-prologue build.
The messages were grouped with `dl_parse.py runs/X/stderr.log` (debug layer) and
`sv_parse.py runs/X/stderr.log <fix-dump>` (shader validation).

**Shader validation with the residency check crashes Lichii** (measured, run `fix-shaderval-crash1`, with its crash
report). With all checks on, the boot completed and Link reached the spawn point, then Lichii died with
SIGSEGV 7 frames later on its `VulkanWorker` thread: `-[MTLToolsResidencySet allCommittedAllocations]` ←
`-[MTLGPUDebugCommandBuffer preCommit]` ← `MVKQueueCommandBufferSubmission::commitActiveMTLCommandBuffer` ←
`vkQueueSubmit2`. MoltenVK keeps an `MTLResidencySet` when it uses argument buffers (`MVKDevice.mm:5549`). Whether
the cause is a race between the validator walking that set and MoltenVK changing it, or an allocation freed while
still in it, was not established (inferred: the debug layer's "destroyed while still required" messages, section 4,
point to the second). `MTL_SHADER_VALIDATION_RESOURCE_USAGE=0` avoided it; MoltenVK's argument buffers were left on, since
turning them off would change the path under test.

Cost, from Lichii's "Shader cache v2 boot load" line and frame times while standing at spawn. Boot times depend on
what Metal has cached already (the first instrumented boot pays for compiling instrumented variants), so they are
rough:

| Run | App | Boot | Standing frame time | Outcome |
| --- | --- | --- | --- | --- |
| reference (`fix-run` of [mesh-native-colours](../mesh-native-colours/README.md)) | fix-app | 153 s | ~42–65 ms | – |
| `fix-debuglayer` | fix-app | 175 s | ~70 ms | spawn shots |
| `fix-shaderval-crash1` (all checks) | fix-app | 299 s | – | SIGSEGV 7 frames after spawn |
| `fix-shaderval-noresusage` | fix-app | 99 s | ~254 ms | spawn shots |
| `ctl-debuglayer` (forced fallback) | fix-app | 4 s | ~100 ms | spawn shots |
| `ctl-shaderval` (forced fallback) | fix-app | 30 s | ~259 ms | spawn shots |
| `fix2-shaderval` | fix2-app | 163 s | ~254 ms | spawn shots (one extra A press) |

Shader validation makes each frame about 4–6× slower. The debug layer costs little. Neither hung.

## 3. Shader validation: every message

Three messages per run, the same three in all three completed runs (measured, each run's `sv.json`):

| Count | Stage | Message | Location | Pipeline UID | Shader |
| --- | --- | --- | --- | --- | --- |
| 2 | vertex | INF or NAN detected in interpolant `out_attr10` | `program_source:369:1` | `5616153726F7…` | `66cc568843a9518e` (pipeline `970c4223c6dfd4b4`, FS `d75b65b37e0c57fa`) |
| 1 | vertex | INF or NAN detected in interpolant `out_attr13` | `program_source:0:0` (`air.vertexFetchFunction`) | `4480B37EDF32…` | not identifiable (Metal's own vertex-fetch stage, an indexed draw) |

| Run | Reports | Mesh / object | Fragment |
| --- | --- | --- | --- |
| `fix-shaderval-noresusage` (native mesh) | 3 | 0 | 0 |
| `ctl-shaderval` (all emulated, correct picture) | 3, same UIDs and locations | 0 | 0 |
| `fix2-shaderval` (NaN prologue) | 3, same UIDs and locations | 0 | 0 |
| `fix-shaderval-crash1` (until the crash) | 4, the same two kinds | 0 | 0 |

How shaders were matched: every MoltenVK function is called `main0` and pipelines have no labels, so a report
carries only stage, line:column and a Metal pipeline UID. `sv_parse.py` keeps the dumped MSL files of that stage
(from the `fix-dump` shader dump, the same Lichii and MoltenVK binaries as `fix-app`) whose line LINE is long
enough. For line 369 that leaves 144 vertex shaders; requiring line 369 to be the end of `main0` and the shader to
declare `out_attr10` leaves one, `66cc568843a9518e`. It is an ordinary instanced vertex shader (tangent frame from
storage buffers), not part of the mesh path. Since the control has the same message, it is pre-existing and has
nothing to do with the native mesh path.

## 4. API debug layer: grouped messages

Measured, `dl_parse.py` on runs `fix-debuglayer` and `ctl-debuglayer`. Counts cover boot, menus,
loading and ~1,100 frames at spawn, so small differences are timing.

| Kind | fix-app (native) | control (emulated) | Reading |
| --- | --- | --- | --- |
| Draw Errors: vertex function constant buffer `cN[0]` declared 65,536 bytes, bound 16–512 bytes | 4,092 | 4,246 | Lichii declares each guest constant buffer as 64 KiB and binds only what it uses. Shader validation saw no read past the bound part, so these are size-declaration noise |
| Draw Errors: the same for fragment functions | 192 | 190 | same |
| object destroyed while a command buffer still needs it (2D-array textures: RGBA16Uint 16×16, R8Unorm 64×64, RGB10A2Unorm 512×512, RG11B10Float 16×8) | 328 | 328 | a texture-view lifetime bug in Lichii or MoltenVK; identical in the control, so not the foliage bug |
| unused binding warnings (fragment/vertex/compute buffers and samplers) | 38,697 | 39,435 | harmless |
| unused **mesh** binding at a sampler index | 1,158 | 0 | MoltenVK binds samplers to the mesh stage that the mesh function does not use; there are no native mesh draws in the control. Harmless |
| redundant `setDepthBias` | 68 | 0 | harmless |

No "Draw Errors" message names a mesh or object function in either run, and no draw was rejected. The debug layer
does look at mesh draws (it reports their unused bindings). Whether it also checks mesh-stage buffer sizes the way
it does for vertex and fragment was not tested.

## 5. What this means for the two symptoms

**White shards.** Measured: no validation error in any mesh or fragment function at the spawn point, and the shards
are on screen in that same run. Shader validation's default fail mode replaces an invalid read by 0, so a bounds
fault in a drawn mesh shader would both be reported and change the picture; neither happened. Inferred: whatever
puts the shards there reads memory that is in bounds. Stale threadgroup memory behind vertices that the program
never wrote fits this; Metal cannot see it (section 1). So the result is consistent with the NaN-prologue
explanation, but does not support it any more than it supports other in-bounds causes, such as wrong data from the
mesh shader's own logic.

**Missing ground grass.** Measured: turf4 (`717b82304a8d8db5`, MoltenVK shader `4b8115033abd19df` in the fix
build) produced no validation report, and no draw was rejected or reported as a pipeline error. Not measured:
whether turf4 is drawn at all at the spawn point. A pipeline that is never drawn would also produce no report, so
this result says nothing about "drawn but empty" against "never drawn".

**The NaN-prologue build.** Measured: `fix2-app` gives the same three pre-existing messages, nothing new from mesh
pipelines, and its spawn shot (`spawn-b` of run `fix2-shaderval`) still shows white shards and no ground
grass, under validation. The NaN check covers interpolants other than position, so the prologue's NaN positions
are not expected to trigger it, and did not. The conclusion on that build without validation is in
[mesh-native-colours](../mesh-native-colours/README.md).

## 6. Not covered

- The route after the spawn point (spawn shots only) and other areas of the game.
- Shader validation with the residency check on, past the spawn point (it crashes, section 2). Missing
  `useResource` or residency of a buffer was therefore not checked.
- `MTL_SHADER_VALIDATION_FAIL_MODE=allow` (would show the picture with invalid accesses let through; nothing was
  reported, so it should not matter).
- Restricting validation to the mesh pipelines (`DEFAULT_STATE=none`): not needed, since the full runs completed.
- Which foliage pipelines are actually drawn at the spawn point, and with how many workgroups. A Metal frame capture
  (`MTL_CAPTURE_ENABLED=1` and an in-process capture), or a per-draw counter in MoltenVK, would answer that, and with
  it whether turf4 is drawn at all.
- The cause of the 328 "destroyed while still required" textures and of the residency-set crash.

## 7. Runs

- Six emulator boots, all through `verify.py` under the emulator lock, each stopped after the spawn shots, except
  `fix-shaderval-crash1`, where Lichii crashed and verify exited on its own.
- The emulator config was unchanged (SHA-1 checked before and after every run). The shared shader cache changed, as
  on every run, and other runs used it in between. No app was modified; the runs used copies.
