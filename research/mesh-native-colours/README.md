# Why natively drawn foliage comes out white or in shards

**Where this stands.** Both faults found here are fixed in the pinned build: the subgroup stages in
`patches/moltenvk/0004-mesh-subgroup-stages-for-mesh-and-task-shaders-diagn.patch` and the NaN guard in
`patches/lichii/0004-native-mesh-NaN-guard-for-unwritten-vertices.patch`. What this page leaves open (white shards,
missing ground grass) was found later to be the mesh position output: SPIRV-Cross skips the Y flip and the depth
fixup for a standalone mesh position (issue #2717), fixed by a text rewrite in
`patches/moltenvk/0005-Merge-MoltenVK-PR-2897-paulpan05-batch-indirect-coun.patch`
([mac-performance](../mac-performance/README.md), cause 4). The scratch folders named below (`shader-diff/`,
`fallback/`, `tg-approaches/`), and the dumps and runs in them, were local and are not tracked.

Done 2026-11-16 on an Apple M4 Pro (Mac16,8) under macOS 27.0.1. The setup is Lichii#1970 with the per-shader mesh
fallback of [mesh-fallback](../mesh-fallback/README.md): mesh shaders that fit Metal's threadgroup limit run natively
through MoltenVK `8df5d45` (main + KhronosGroup/MoltenVK#2842 + #2843, SPIRV-Cross at the #2686 merge `e99dc7a3`,
`maxPushDescriptors` 16), and the oversized ones are emulated. With it, the native foliage is drawn as flat white or
multicoloured shards, and the ground grass is missing. All emulated (`EDEN_NX2_FORCE_MESH_FALLBACK=1`) is correct.

**Measured** means a dump, a Metal run or a screenshot on the M4 Pro showed it. **Inferred** means it is a reading
of code.

## Verdict

The main fault is on the Lichii side of the native mesh path, triggered by what MoltenVK reports. It is not
SPIRV-Cross, not the mesh-to-fragment interface, and not mixing native and emulated draws. Lichii's native mesh SPIR-V
differs from its own emulation of the same guest program in exactly two ways, and both are wrong:

1. **No subgroup operations in native mesh shaders.** MoltenVK reports subgroup support only for the fragment,
   compute and tessellation-control stages (`MVKDevice.mm:1533`). MoltenVK#2842 adds mesh and task shaders but does
   not add them to that mask. Lichii therefore takes its "no subgroups in this stage" path for native mesh programs
   (`emit_spirv_warp.cpp`): the lane id becomes `0`, a ballot becomes `pred ? 1 : 0`, the lane masks become constants,
   and every shuffle returns the thread's own value. The game's mesh programs are written for a 32-lane warp: each
   thread picks its element as `workgroup·32 + lane`, compacts with ballots and prefix sums, and broadcasts with
   shuffles. Natively, all 32 threads of a workgroup work on one element. The emulated path runs as a compute shader,
   which has subgroups, so it is correct.
2. **No guard against unwritten vertices in native mesh shaders.** Lichii's mesh prologue sets every vertex position
   in the stage buffer to NaN first ("Workgroup memory keeps whatever the previous workgroup left. A primitive that
   uses a vertex the program never wrote would draw a stray triangle", `emit_spirv_mesh.cpp:458`). That block sits
   inside `if (as_compute)`, so the native path has no guard and can draw stray triangles from stale memory.

Fixing (1) alone, in MoltenVK, changes the picture a lot (measured): the canopy becomes dense green leaves in the right
shapes. White shards remain, and the ground grass is still missing. Adding the NaN guard to the native path as well
(Lichii, in a local clone) changes nothing visible at the spawn point (measured). With both changes, the native MSL of all 49
programs matches the emulated MSL of the same programs except for how the task payload arrives (measured, section 5).
So the rest of the glitch is outside the mesh programs' own code: in the native task stage, in resource binding for
the mesh stage, or in pipeline state. It turned out to be the position output (see the top of this page).

The old build does not help here. The shaders Lichii and MoltenVK produced before Lichii#1970 are byte-identical to the
current ones (section 2), so native foliage was most likely never right on this MoltenVK (inferred: same shaders,
same MoltenVK; the old picture itself was not kept).

## 1. Test shaders

From the shader dump `dump1` of the `fb-dump` run ([mesh-fallback](../mesh-fallback/README.md)), matched to
shading models through the mesh table of [shader-extraction](../shader-extraction/README.md) by vertex count,
primitive count and output lines. All run natively in the fallback build and are Foliage programs; the fragment
shader is the one MoltenVK pairs them with in `pipeline-*.txt`.

| Model | Lichii mesh program | MoltenVK mesh shader | V / P / lines | Fragment shader |
| --- | --- | --- | --- | --- |
| turf4 (ground grass) | `717b82304a8d8db5` | `3e4e74d89ecf136b` | 96 / 64 / 21 | `30be8ecc20d951e3` |
| impostor (ornament / low tree) | `4bcce0ad3a25fab8` | `e7152702540f354a` | 96 / 64 / 26 | `f28d8b8b3f98bab1` |
| moss or turf1 | `3e64dc9496175ce8` | `99a044ff8e9150e8` | 96 / 32 / 21 | `8c1760d10558983a` |
| stalk or leaf_near | `7ce70774d14b16cf` | `3ef8aa1f88f187e8` | 128 / 64 / 10 | `f31ec48ac518c71a` |
| leaf or stalk | `1e8bf02b3ed9a3f3` | `cfb1e18769027146` | 128 / 64 / 7 | `223c8b037c077455` |
| flower | `d68fffbcec430183` | `4f561cda19f163db` | 160 / 128 / 8 | `07de0fd60e53cf7a` |

Which of them are drawn at the spawn point was not established per shader: the boot compiles every cached pipeline
whether it is drawn or not. Grass, leaves, canopy and impostor trees are all in the spawn shot.

## 2. The dumps, and old against new

- `fallback/runs/dump1/` is a native-mesh dump of the fallback build as it stood: the `fb-dump` verify run of
  the fallback build's app (binary built 10:59, with the native-size predictor later committed as `9537add`) with
  `MVK_CONFIG_SHADER_DUMP_DIR`. Its log maps each Lichii mesh program to its MoltenVK shader name
  ("Mesh fallback: native mesh program … is MoltenVK shader …"). 49 mesh programs are native, 4 emulated.
- **Old build.** `960f215` is not a commit of Lichii#1970's branch: it is the `nx2` commit for #1963 (buffer-cache
  retry), one after `0eb76dde`, which the PR branch merged in at `443307e5`. It is not an ancestor of the PR head
  `1f76c9ff5`. `nx2` `7c7f723` descends from it with no change under `src/shader_recompiler` and none in
  `src/video_core` that touches shader emission. A dump of `7c7f723` with the same MoltenVK `8df5d45` already existed
  (`tg-approaches/dump-111335/`, the one used in [mesh-threadgroup-memory](../mesh-threadgroup-memory/README.md); 53
  native mesh shaders, the 4 oversized included). `960f215` was rebuilt but not booted: the 7c7f723 dump already
  settles the comparison.
- **MoltenVK then and now.** The PR heads have not moved since 2026-09-25 (#2842 `c516eb42`, #2843 `cae05219`),
  MoltenVK main stopped at `5189f8d` on 2026-10-13, and SPIRV-Cross #2686 merged as `e99dc7a3`. So `8df5d45` is the
  old combination's source. The one open point is whether the 960f215 run had the `maxPushDescriptors` 16 line; that
  changes resource binding, not the code paths below.

**Measured: the old and new shaders are identical.** Every one of the 2,180 shader files the two dumps share
(SPIR-V and MSL, all stages) is byte-identical. MoltenVK names files by a hash of the SPIR-V, so all 49 native mesh
shaders of `dump1` are present under the same names in the 7c7f723 dump. Lichii#1970 changed which shaders run
natively, not what a native shader is. So "the old build was correct" does not hold for the shaders that ran
natively in both.

## 3. What is not wrong (measured)

The non-position attributes were followed from the stage buffer to the fragment shader.

- **Line-to-output mapping.** Lichii's native epilogue (`MeshEpilogue` → `CopyLines`) and its emulation pass-through
  (`EmitMeshEmulationVertex`) both map stage-buffer line `l` to `mesh.vertex_lines[l]`, from the same `AddMeshLines`.
  In turf4's MSL the guest stores at byte offsets 512–2560 (lines 4–20), and the epilogue copies line 4 → `locn0.x`,
  5 → `locn1.x`, 6–8 → `locn3.xyz`, … 18–20 → `locn11.xyz`, with a 672-word group stride (21 lines × 32).
- **Mesh outputs against fragment inputs.** A script over all 54 native mesh/fragment pairs in `dump1` checked every
  `[[user(locnN)]]` the fragment shader declares and every component it reads. Each is one the mesh shader declares
  and writes. (The one per-primitive shader, `7f15d8c4e2d5d54b`, was not parsed.) The unwritten components
  (`.w`, and `.yzw` of 1-component outputs) are never read.
- **Metal's handling of this code shape.** `shader-diff/probe/interp.swift` draws one triangle through a vertex
  pipeline and through a mesh pipeline shaped like SPIRV-Cross's output for Lichii: 32 threads, threadgroup `float4`
  staging with only `.xyz` written, a barrier, a `set_vertex` loop. It reads back `[[position]]`, a smooth, a
  `[[flat]]` and a `[[center_no_perspective]]` input. All four match to 4 decimals, also with the triangle at
  vertices 64–66. So the missing interpolation qualifiers on the mesh vertex struct, and the staging, are fine.
- **Fragment shaders in mesh pipelines.** Lichii decorates no-perspective inputs as `NoPerspective` when the
  previous stage is a mesh shader (`scaled_noperspective_inputs` is false), which is correct.
- **Sizes.** No threadgroup or pipeline errors in any run. The predictor of [mesh-fallback](../mesh-fallback/README.md)
  matches the MSL.

## 4. The decisive diff: one guest program, emulated and native

The oversized leaf programs exist both ways: emulated as compute in `dump1`, native in the 7c7f723 dump. Pairing
them by body (fewest differing lines) gives `cs-e96cd2231d858e5f` ↔ `efdc2d865aa74afe`,
`cs-a3d740198ff80ed4` ↔ `0c69b95fb5fc198e` and `cs-50b8144cb32d23ab` ↔ `aad4571246c8d55c`. After normalising
SSA names and descriptor access, the whole guest-program body of `cs-e96cd2231d858e5f` and `efdc2d865aa74afe`
differs only here (measured):

```
emulated  dump1/shader-cs-e96cd2231d858e5f.metal:398
    uint _2109 = (((0u == 0u) ? gl_WorkGroupID.x : task_payload[min((0u >> 2u), 799u)]) << 5u) + gl_SubgroupInvocationID;
native    tg-approaches/dump-111335/shader-efdc2d865aa74afe.metal:327
    uint _1887 = (((0u == 0u) ? gl_WorkGroupID.x : task_payload[min((0u >> 2u), 799u)]) << 5u) + 0u;

emulated  bool b = gl_SubgroupInvocationID != 0u;   uint4 v = spvSubgroupBallot(...);   popcount(x & gl_SubgroupLtMask.x)
native    bool b = 0u != 0u;                        uint  v = uint(...);                popcount(x & 0u)
```

Plus the prologue (emulated only): 16 stores of `2143289344u` (`0x7FC00000`, NaN) into the position lines of all
128 vertices, and the task payload zeroed. Everything else is the expected epilogue difference (copy to
`mesh_emulation_output` vs to the staged outputs).

The test shaders show the same thing natively (measured, `dump1`):

- turf4 `3e4e74d89ecf136b`, line 328–329: `uint _2068 = 0u >> 1u;` then
  `uint _2070 = (WG.x << 4u) + _2068;`. Element = 16 per workgroup + lane / 2, and the lane is 0, so all 32 threads
  build the same grass element. Line 739: a warp-aggregated atomic counter gets `uint _2562 = uint(true);` as its
  ballot.
- moss/turf1 `99a044ff8e9150e8:362`, stalk/leaf_near `3ef8aa1f88f187e8:184`, leaf `cfb1e18769027146:172`:
  `(WG.x << 5u) + 0u`.
- The emulated flower program (`cs-01b7bca62a6d8e50`, 160/128) builds warp prefix sums from 36 `spvSubgroupShuffle`
  and 35 `spvSubgroupBroadcast` calls. Natively each shuffle returns the thread's own value.
- **None of the 49 native mesh shaders in `dump1`, and none of the 53 in the 7c7f723 dump, contains a single SIMD
  operation**, while all 4 emulated mesh programs use `simd_ballot` and `gl_SubgroupInvocationID`. Lichii's SPIR-V
  for the test shaders (`spirv-dis`, `shader-diff/dis/`) has no `OpGroupNonUniform*` and no subgroup built-ins; the
  lowering happens in Lichii, not in SPIRV-Cross.

Why (inferred from source, Lichii `1f76c9ff5` and MoltenVK `8df5d45`):

- `vk_pipeline_cache.cpp:603-618` builds `profile.supported_subgroup_stages` from
  `VkPhysicalDeviceSubgroupProperties::supportedStages`, including `VK_SHADER_STAGE_MESH_BIT_EXT` → `Stage::Mesh`.
- `EmitContext::SupportsSubgroups()` (`spirv_emit_context.h:205`) asks for `Stage::Compute` when
  `mesh_as_compute`, else for the real stage. So emulation gets subgroups and native mesh does not.
- MoltenVK `populateSubgroupProperties` (`MVKDevice.mm:1531`) sets `FRAGMENT | COMPUTE`, plus `TESSELLATION_CONTROL`.
  #2842 did not touch it.

## 5. Confirmation

**Can SPIRV-Cross and Metal do subgroups in a mesh shader?** (measured) A GLSL mesh shader with
`gl_SubgroupInvocationID`, `subgroupBallot`, `subgroupShuffle` and `subgroupShuffleUp`, compiled with
`glslangValidator` and converted with SPIRV-Cross `e99dc7a3`, gives a `[[mesh]]` function with
`[[thread_index_in_simdgroup]]` and `simd_ballot` / `simd_shuffle` / `simd_shuffle_up`, and Metal builds the mesh
pipeline (`shader-diff/probe/sg/`). It was not run on the GPU.

**Fix 1 on screen** (measured). `shader-diff/moltenvk/` is `8df5d45` plus one change in `populateSubgroupProperties`:

```objc
if (_gpuCapabilities.supportsApple7) { pVk11Props->subgroupSupportedStages |= VK_SHADER_STAGE_MESH_BIT_EXT; }
if (_gpuCapabilities.supportsApple9) { pVk11Props->subgroupSupportedStages |= VK_SHADER_STAGE_TASK_BIT_EXT; }
```

(the same feature gates #2842 uses for `meshShader` and `taskShader`). `fix-app` is the fallback build's Lichii
(unchanged) with that library. One verify run, stopped after the spawn shots (run `fix-run`, shader dump
`fix-dump`):

- All 49 native mesh shaders now contain SIMD operations (0 before). turf4 (now `4b8115033abd19df`; the Lichii
  program ids are unchanged) has `uint _N = gl_SubgroupInvocationID >> 1u;` where it had `0u >> 1u`, and real
  `spvSubgroupBallot` calls.
- No MoltenVK errors, no threadgroup or pipeline failures.
- The picture (`runs/fix-run/shots/spawn-b.png` against `fallback/runs/fb-dump/shots/spawn-b.png`): the canopy is
  now dense green foliage in the right shapes instead of white blobs. The upper screen is still hazy, white shards
  remain across the canopy and the middle ground, and the ground grass is still missing.

**Fix 2 on screen** (measured). A Lichii build of `9537add` (the fallback build's head) with the NaN block of
`EmitMeshPrologue` moved out of `if (as_compute)`. `fix2-app` = that build plus the subgroup MoltenVK. One verify run,
stopped after the spawn shots (`runs/fix2-run/`, dump `runs/fix2-dump/`): all 49 native mesh shaders now start with the
NaN stores, 47 use SIMD operations (the other 2 have no warp ops). The picture is the same as fix 1: green canopy, white
shards, hazy top, no ground grass. One large stray leaf card appeared next to the rock on the left.

**All 49 programs, native against emulated, same build** (measured). One more no-input boot of `fix2-app` with
`EDEN_NX2_FORCE_MESH_FALLBACK=1` (`runs/fix2-emu/`, `dump_boot.sh`) dumped the emulated compute form of every mesh
program. `shader-diff/pairdiff.py runs/fix2-dump runs/fix2-emu/dump` pairs each native shader with its emulated
form by the closest normalised body and lists what differs before the epilogue (`runs/pairdiff-fix2.txt`):

- 19 pairs differ in 3 or 5 lines: the payload clamp (`min(…, 63u)` against `799u`), nothing else.
- 28 pairs differ in 26 or 83 lines, and 2 in 139 and 141. Each is the emulation's task-payload lookup (a binary
  search over `mesh_emulation_task_offsets`, then a copy from `mesh_emulation_task_payload`) and its payload
  zeroing. Natively the payload comes from Metal's object stage.
- Nothing else differs. In particular, no lane, ballot or shuffle differences remain.

The native task shaders were broken the same way before fix 1: `dump1/shader-c7841cbd9bd516d9.metal` computes the
mesh workgroup count from `popcount(uint(true))`, so each task launches 1 mesh workgroup instead of one per active
lane. Fix 1 covers the task stage too (`VK_SHADER_STAGE_TASK_BIT_EXT`). The new dumps have no task-shader files: no
pipeline in them was converted with a task stage, so the task side after fix 1 was not inspected.

Metal's API and shader validation on the fix-1 build ([metal-validation](../metal-validation/README.md)) flag nothing
in any mesh or object function. The undersized constant buffers it reports in vertex and fragment functions appear
equally in the all-emulated control.

## 6. What would fix it, and where

1. **MoltenVK (KhronosGroup/MoltenVK#2842): report subgroup support for the mesh and task stages.** In
   `MVKPhysicalDevice::populateSubgroupProperties` (`MVKDevice.mm:1531`), add `VK_SHADER_STAGE_MESH_BIT_EXT` when mesh
   shaders are offered (Apple7) and `VK_SHADER_STAGE_TASK_BIT_EXT` when task shaders are (Apple9), as in section 5.
   SPIRV-Cross already emits SIMD-group operations for mesh functions. This is the one change with a visible effect.
   MoltenVK is deprecated and merges nothing, so it is a local patch on top of #2842 (in the pinned build). The PR's
   author has since replied that mesh and task now report subgroup support.
2. **Lichii (Lichii#1970): never run a warp-cooperative mesh or task program natively without subgroups.** The
   scalar fallback in `emit_spirv_warp.cpp` is only valid if the guest warp has one thread, and a 32-thread mesh
   workgroup is one 32-lane guest warp. In `vk_pipeline_cache.cpp`, where the fallback decides native against
   emulated, emulate a mesh or task program when `!profile.SupportsSubgroupStage(Stage::Mesh / Task)` and the
   program uses warp operations (lane id, votes, ballots, shuffles, lane masks: already tracked in `Shader::Info`).
   Then a driver like today's MoltenVK gets a correct picture by emulation instead of a broken native one.
3. **Lichii: the NaN-position guard for native mesh shaders too.** In `EmitMeshPrologue` (`emit_spirv_mesh.cpp`),
   move the "every vertex position starts as NaN" block out of `if (as_compute)`, as in
   fix 2 above (now `patches/lichii/0004-…`). It costs 4 stores per vertex. It showed no visible effect
   here, but it removes a real difference from the emulated path, which Lichii added for stray triangles.
4. **Found later:** what remained (white shards, haze, missing ground grass) is not in the mesh programs' code after 1
   and 3. It is the mesh position output (see the top of this page). The leads this page listed were: the native task
   stage after fix 1 (its MSL was not dumped), resource binding of the mesh stage (`prepareDraw<true>` binds the vertex
   stage's resources to `MVKMetalGraphicsStage::Mesh`; Metal's API validation rejected no mesh draw, see
   [metal-validation](../metal-validation/README.md)), and the per-primitive outputs of the one shader that has them
   (`7f15d8c4e2d5d54b`).

Changes 1 and 3 are in the pinned build (see the top of this page); change 2 is not.

## 7. Runs and what was not done

- Three emulator boots: two verify runs stopped after the spawn shots (`fix-run`, `fix2-run`) and one no-input dump
  boot with `EDEN_NX2_FORCE_MESH_FALLBACK=1` (`fix2-emu`). The emulator config was unchanged (SHA-1 checked); the
  shared shader cache grew, as on every run.
- Not done: a dump boot of the rebuilt `960f215` (not needed once the 7c7f723 dump proved the shaders identical);
  a GPU run of the subgroup probe; per-shader confirmation of which foliage programs are drawn at the spawn point.
