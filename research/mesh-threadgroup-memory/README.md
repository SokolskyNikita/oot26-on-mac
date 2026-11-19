# Fitting the oversized mesh shaders into Metal's threadgroup memory

**Where this stands.** The pinned build uses neither approach below: it emulates the oversized shaders, using the
size rule of [mesh-fallback](../mesh-fallback/README.md) (`patches/lichii/0002-…`). This page is the study of what it
would take to run them natively.

Study made on 2026-11-16 on an Apple M4 Pro (Mac16,8) under macOS 27.0.1. Some mesh shaders fail to build in Metal with
"Threadgroup memory size (N) exceeds the maximum threadgroup memory allowed (32768)". The setup is Lichii `nx2`
`7c7f723` with MoltenVK main + KhronosGroup/MoltenVK#2842 + #2843 + KhronosGroup/SPIRV-Cross#2686 and
`maxPushDescriptors` set to 16. This study asks which changes would make those shaders fit, how much work each one is,
and how each compares with emulating just those shaders (the route of [mesh-fallback](../mesh-fallback/README.md)).

**Measured** means Metal or a script gave the number on the M4 Pro. **Inferred** means a reading of code, or
arithmetic not run on the GPU. **No experiment here shows that the picture is right.** A pipeline that builds
shows that the memory budget works, nothing more.

The scratch code and raw output (`tg-approaches/`) were local and are not tracked; the scripts are listed in
section 8.

## Summary

- **Metal has three limits, not one** (measured): threadgroup memory ≤ 32,768 bytes, mesh output ≤ 32,768 bytes, and
  **threadgroup + mesh output ≤ 61,440 bytes**. The mesh output object is not free: it draws on the same 60 KiB.
- **Four shaders reached in Kokiri Forest are over.** A fresh dump has 53 mesh shaders, and 4 of them are over:
  `f745a892263a512e`, `0c69b95fb5fc198e`, `efdc2d865aa74afe` and `aad4571246c8d55c`. Across all 440 mesh programs the
  game loads, 10 are over (the byte model of [shader-extraction](../shader-extraction/README.md), which matches all 53
  dumped shaders). The worst is 48,412 bytes, a flower shader that is not in the cache yet. All 10 are foliage.
- **Every oversized shader is about two-thirds duplicated vertex data.** The worst one reached, `f745a892263a512e`,
  holds 42,012 bytes. 15,360 of them are Lichii's `isbe_attributes`, 23,040 are SPIRV-Cross's staged outputs, and
  1,552 are Lichii's index map (`isbe_map`), which spends 4 bytes on every 1-byte index.
- **Two changes fix all 440 shaders, each on its own** (budget measured on the 4 cached shaders, inferred for the
  other 436 from the byte model):
  - **A. Lichii writes the mesh outputs directly**, with no `isbe_*` arrays. The worst shader drops to 30,220 + 28,160
    = 58,380 bytes. That fits, but only 3,060 bytes under the 61,440 total.
  - **B. SPIRV-Cross keeps the staged outputs in each thread** instead of in threadgroup memory. The worst shader drops
    to 18,204 + 28,160 = 46,364 bytes, with plenty of room.

  Hand edits of the dumped MSL along both lines build in Metal for all 4 cached oversized shaders. The unedited files
  fail with Metal's exact numbers.
- **Narrowing types (C) is not enough by itself**: one of the 440 shaders stays over. Lowering max vertices or
  primitives, splitting meshlets, the object payload, and a larger limit are not options (section 5).
- **Recommendation: A in Lichii, with a fallback to emulation for anything still over.** About 1 week to a picture that
  has been checked on screen. B is the more robust fix but is more work and needs a SPIRV-Cross patch; it is a good
  second step. B takes 1 to 2 weeks of SPIRV-Cross work; the smallest fix is in Lichii. Section 7 has the estimates and
  the comparison with emulation.

---

## 1. Where the bytes go

### 1.1 Getting a fresh dump

One boot of a test app: Lichii `7c7f723` with MoltenVK `8df5d45` (main + #2842 + #2843 + SPIRV-Cross #2686,
`maxPushDescriptors` 16), run under the emulator lock with `MVK_CONFIG_SHADER_DUMP_DIR` set and no input; "build all
cached shaders" compiles every cached pipeline at boot (`dump_run.sh`). Lichii exited by itself during the prebuild,
after converting 1,101 shaders. The log has the failures: `Threadgroup memory size (42012 / 35100 / 34076) exceeds the
maximum threadgroup memory allowed (32768)`.

The dump holds 53 mesh shaders, and 4 are over. `0c69b95fb5fc198e` is the same size
as `efdc2d865aa74afe` and is drawn with the same fragment shader.

### 1.2 By variable (measured from the MSL with `tg_audit2.py`)

All four have a 32-thread workgroup (`gl_WorkGroupSize = uint3(32, 1, 1)`), draw triangles, and declare no guest
shared memory.

| Shader | V / P | Lines | Outputs (incl. Position) | `isbe_attributes` | `isbe_map` | count + `spvMeshSizes` | staged indices (`uint3`) | staged outputs (`float4`) | **Threadgroup** | Mesh object | Threadgroup + mesh |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `f745a892263a512e` | 160 / 128 | 24 | 9 | 15,360 | 1,552 | 12 | 2,048 | 23,040 | **42,012** | 23,040 | 65,052 |
| `0c69b95fb5fc198e` | 128 / 64 | 25 | 10 | 12,800 | 784 | 12 | 1,024 | 20,480 | **35,100** | 20,480 | 55,580 |
| `efdc2d865aa74afe` | 128 / 64 | 25 | 10 | 12,800 | 784 | 12 | 1,024 | 20,480 | **35,100** | 20,480 | 55,580 |
| `aad4571246c8d55c` | 128 / 64 | 23 | 10 | 11,776 | 784 | 12 | 1,024 | 20,480 | **34,076** | 20,480 | 54,556 |

"Lines" means scalar output components: one 32-word line per component per group of 32 vertices. The outputs are
mostly `.x` or `.xyz` of a `float4`. For example, `f745a892263a512e` writes Position.xyzw, two outputs as `.x` only and
six as `.xyz`: 24 of the 36 components it stores.

`f745a892263a512e` is 9,244 bytes over the limit. Removing one piece at a time leaves:

| Removed from `f745a892263a512e` | Threadgroup left | Fits 32,768? | Threadgroup + mesh (≤ 61,440) |
| --- | ---: | --- | ---: |
| nothing | 42,012 | no (+9,244) | 65,052 (over) |
| `isbe_attributes` | 26,652 | yes | 49,692 |
| `isbe_attributes` + `isbe_map` | 25,100 | yes | 48,140 |
| staged outputs | 18,972 | yes | 42,012 |
| staged outputs + staged indices | 16,924 | yes | 39,964 |
| `isbe_map` only | 40,460 | no | — |
| staged indices only | 39,964 | no | — |

The three 128-vertex shaders are 1,308 to 2,332 bytes over, so either big piece alone fixes them by a wide margin.

### 1.3 Metal's limits (measured)

`mtlcheck` (a small `swiftc` program, section 8) builds an `MTLMeshRenderPipelineDescriptor` pipeline from an MSL file
and prints Metal's own verdict. It was probed with synthetic mesh shaders. On the M4 Pro,
`maxThreadgroupMemoryLength` is 32,768. Metal's messages:

```
Threadgroup memory size (33600) exceeds the maximum threadgroup memory allowed (32768)
Total mesh size (36864) exceeds the maximum mesh size allowed (32768)
Threadgroup memory size and mesh size (28800 + 32768) exceed the maximum limit allowed (61440)
Mesh unique scalar count of 128 exceeds limit of 124
```

From the probes:

- **Mesh size** = max vertices × sizeof(vertex struct) + max primitives × sizeof(primitive struct). Indices are not
  counted: 64 or 512 primitives with no per-primitive data give the same size.
- **Narrower members shrink it.** 256 vertices with Position plus 15 attributes measure 65,536 bytes as `float4`,
  34,816 as `float2` or `half4`, 52,224 as `float3`, and fit as `float`. Unlike threadgroup arrays, a `float3` mesh
  member is not padded to 16 bytes.
- The 61,440 total is a real constraint here. Today `f745a892263a512e` would fail it too (65,052) even if the
  threadgroup check passed. So "move one copy into the mesh object" has to fit the total, not only the 32 KiB.

**Caution for anyone repeating this:** pair the mesh function with the pipeline's real fragment shader. With a trivial
fragment function, Metal strips the outputs nothing reads, along with the threadgroup arrays that feed them, and the
unedited shaders build. The fragment shaders that go with these 4 read every location the mesh shader writes
(`f745a892263a512e` → `5e878fd478991ad2`, `aad4571246c8d55c` → `327e4a4c2b9e8b6f`, the other two →
`8f5528664359d1a1`), so dropping unread outputs gains nothing.

### 1.4 The whole game (inferred from a byte model)

[shader-extraction](../shader-extraction/README.md) extracted every mesh program from the game files (its mesh
table is kept in the separate glitch-research repository). It found this rule, which reproduces all 53 dumped sizes:

    threadgroup = 128·ceil(V/32)·lines + 16·V·vec4_outputs + 28·P + 28,   mesh object = 16·V·vec4_outputs

`approaches.py` applies each approach below to all 440 programs in the set the game loads (`approaches.txt`). Today,
10 are over the threadgroup limit and 2 of those are also over the 61,440 total. The worst is `7289a62f246f6b3c`
(flower, V 160, P 128, 26 lines, 11 outputs): 48,412 + 28,160. It has not reached the cache, so no MSL exists for
it.

## 2. Why there are two copies

### 2.1 Lichii: `isbe_attributes` (read in the fallback build's Lichii source, same emission as `7c7f723`)

NVN mesh programs on the Switch 2 do not write mesh outputs. They write the hardware's stage buffer (ISBE) with
`ISBEWR` stores to linear byte addresses. The attribute region holds the vertices in groups of 32, with one 32-word
line per output component. The map region holds the primitive count and one byte per vertex index. Lichii translates
each store literally:

- `TranslatorVisitor::ISBE_nx2` (`frontend/maxwell/translate/impl/internal_stage_buffer_entry_read.cpp`) turns each
  store into `IsbeWriteAttribute(address, value)`, `IsbeWriteMapU8` or `IsbeWriteMapU32`. The address is a register
  plus an immediate, so it is only known at run time.
- `EmitContext::DefineMesh` (`backend/spirv/spirv_emit_context.cpp:2176`) declares `isbe_attributes` (u32
  `ceil(V/32)·lines·32` + primitive lines), `isbe_map` (one **u32 per byte**, `4 + 3P` of them) and
  `isbe_primitive_count` as Workgroup variables. It also declares the real Output arrays: one `vec4[V]` per generic
  location, plus Position.
- `EmitIsbeWriteAttribute` / `EmitIsbeWriteMapU8` (`backend/spirv/emit_spirv_mesh.cpp`) store into those arrays.
  `MeshEpilogue` then runs a barrier, calls `OpSetMeshOutputsEXT(max_vertices, count)`, and loops
  `vertex = invocation + k·threads` copying each line into its Output component (`CopyLines`, `ConvertDepth`). After
  that it copies the indices from the map.

The intermediate exists for three reasons. Addresses are dynamic. A component can be written by any thread, in any
order, and more than once. And `VK_EXT_mesh_shader` forbids writing outputs before `SetMeshOutputsEXT`, while the
primitive count is only known at the end. The program never reads the attribute region back: `EmitIsbeRead` reads only
the task payload. So nothing about the guest program forces the copy; it is a translation choice.

### 2.2 SPIRV-Cross: the staged outputs (read at `e99dc7a3`, the #2686 merge)

Metal's mesh API takes a whole vertex struct per `set_vertex(i, v)`, and SPIR-V writes outputs component by
component. So `CompilerMSL` declares every mesh Output variable as a `threadgroup` array
(`localize_global_variables`), and `emit_mesh_outputs()` flushes them after a barrier. The flush is
`for (spvVI = gl_LocalInvocationIndex; spvVI < spvMeshSizes.x; spvVI += spvThreadCount)` into an `spvPerVertex`
struct, then `set_vertex`, then the same pattern for the indices. The index array is staged as `uint3` (16 bytes per
triangle).

The design was discussed upstream when it was written. In [SPIRV-Cross#2074](https://github.com/KhronosGroup/SPIRV-Cross/pull/2074)
(the first MSL mesh work) the author wrote that outputs "are represented as shared memory arrays", that "if shader
writes only with `[gl_LocalInvocationIndex]` array can be removed", and later that a thread-local variant was valid
for their own shaders. #2686 and MoltenVK#2842 say nothing about the threadgroup limit. MoltenVK#2842 has no comments.
SPIRV-Cross#2740 (open) packs `vec3` in workgroup structs for the same 32 KiB error in compute shaders. It does not
touch mesh outputs.

### 2.3 MoltenVK#2842 and `MVK_MESH_THREAD_OUTPUTS`

#2842 only maps the stages and reports limits. In `MVKDevice.mm` it sets `maxMeshSharedMemorySize` and
`maxMeshOutputMemorySize` to `(32768 − 8 − 512·16) / 2` = 12,284 bytes each, because "SPIRV-Cross stages mesh outputs …
in threadgroup memory next to shared variables". It has no switch that changes code generation.

`MVK_MESH_THREAD_OUTPUTS` is not in #2842, in MoltenVK main, in the Lichii branch, or anywhere GitHub code search
reaches. It was the Lichii#1970 author's private experiment, and its code is not available. Inferred: by its name it
moved the staged outputs into thread memory, which is approach B below. That would explain why every shader built.
Whether the glitch came from it or from `EDEN_NX2_MESH_NATIVE_ALWAYS=1` is still unknown. One plausible cause, a
guess: a thread-output scheme that assumes vertex index == thread index loses every vertex past the 32nd in these
128- and 160-vertex shaders. The edit in section 4 instead keeps ceil(V/32) vertices per thread.

## 3. The approaches

Byte counts are for `f745a892263a512e` / `0c69b95fb5fc198e` (= `efdc2d865aa74afe`) / `aad4571246c8d55c`, as
threadgroup + mesh object, from the byte tables. "Game" counts how many of the 440 loaded programs would still fail
any of Metal's three limits (`approaches.py`). Cells marked "built" were also checked in Metal (section 4).

| # | Approach | Lives in | Threadgroup (f745 / 0c69 / aad4) | Game: still failing | Worst in game (tg + mesh) |
| --- | --- | --- | --- | ---: | --- |
| — | today | — | 42,012 / 35,100 / 34,076 | 10 | 48,412 + 28,160 |
| A | Lichii writes Output arrays directly; no `isbe_attributes`, no `isbe_map` | Lichii | 25,100 / 21,516 / 21,516, **built** | 0 | 30,220 + 28,160 = 58,380 |
| A1 | A for attributes only, keep `isbe_map` | Lichii | 26,652 / 22,300 / 22,300, **built** | 0 | 31,772 + 28,160 = 59,932 |
| B | Staged outputs and indices thread-local (ceil(V/threads) per thread) | SPIRV-Cross | 16,924 / 13,596 / 12,572, **built** | 0 | 18,204 + 28,160 = 46,364 |
| C | Narrow staging: written components only (`float`, `packed_float3`), `uchar4` indices, u8 map | SPIRV-Cross + Lichii | 31,632 / 26,064 / 24,016, **built** | 1 | 34,192 + 28,160 |
| C1 | Only `uchar4` indices + u8 map | SPIRV-Cross + Lichii | 39,312 / 33,744 / 32,720 | 8 | 45,712 + 28,160 |
| G | `isbe_*` in a device scratch buffer | Lichii | = A | 0 | = A |
| H | `isbe_*` in the object payload | — | not possible | — | — |
| D | Lower V / P, split a meshlet, smaller local size | — | not possible | — | — |
| E | Drop outputs the fragment never reads | — | nothing to drop | — | — |
| F | Larger Metal limit | — | fixed | — | — |

The mesh object stays at 23,040 / 20,480 / 20,480 under all of these, because no approach changes the struct Metal
receives. On the older game version's shader set (`v100`, not loaded by game version 1.1.1), A leaves 1 failing (32,780 +
30,720), B 0 and C 2.

### A. Lichii writes the mesh outputs directly

**Change.** In `emit_spirv_mesh.cpp`, `EmitIsbeWriteAttribute` decodes the word address at run time into group, line
and slot, so `vertex = group·32 + slot`. It then does an `OpSwitch` on the line, whose cases are known at compile time
from `mesh_info.vertex_lines` / `primitive_lines`. Each case stores into `Output[vertex].component`.
`EmitIsbeWriteMapU8` stores into `PrimitiveTriangleIndicesEXT[(byte − 4) / 3][(byte − 4) % 3]`. `MeshEpilogue` loses
both copy loops; `ConvertDepth` reads z and w back from the Output array, which SPIR-V allows for mesh outputs. Gate it
behind a profile flag (for example "small mesh threadgroup memory") so RADV and NVIDIA keep today's path.

**Correctness risks.**
- `SetMeshOutputsEXT` must come before any output write in Vulkan. The count is only known at the end, so call
  `SetMeshOutputsEXT(max_vertices, max_primitives)` in the prologue, and in the epilogue make primitives ≥ count
  degenerate (indices 0,0,0) or set `CullPrimitiveEXT`. SPIRV-Cross's flush already handles `CullPrimitiveEXT`.
  Inferred cost: the GPU walks max_primitives instead of the real count.
- Stores from several threads to different components of one vertex stay correct, because the staged arrays are still
  shared threadgroup memory.
- Stores past the declared lines used to land in the clamped last word; with A they are dropped. A stray store that a
  later store overwrote would behave the same either way.
- Unwritten vertices were never initialised in the native path, so nothing changes there.

**Size.** About 150–250 lines in Lichii's SPIR-V backend, and `NativeMeshThreadgroupMemorySize` in
`mesh_fallback_limits.h` must learn the new layout. 2–4 days to a build, plus 1–2 days checking pictures with the
verify harness. No upstream dependency for a local build. For everyone, Lichii must accept it, and MoltenVK must stop
reporting 12,284 or Lichii#1970 must stop trusting it (see 6).

**Margin.** The worst game shader is 3,060 bytes under the 61,440 total, and a `v100` shader is over. A covers this
game version, but a slightly larger meshlet would not fit, so keep the emulation fallback for anything still over.

### B. SPIRV-Cross keeps mesh outputs per thread

**Change.** In `CompilerMSL`, first check every access chain into a mesh Output variable, and the index array. Each
index must be `LocalInvocationIndex` (or `LocalInvocationID.x` with workgroup size `(T,1,1)`) plus a constant multiple
of T. When all of them are, declare the variable as a thread array of ceil(N/T) elements indexed `[i / T]`, and use
`[spvVI / T]` in `emit_mesh_outputs`. Otherwise keep today's threadgroup array. Lichii's epilogue always has this form:
`vertex = invocation + first` with `first` stepping by `threads` and unrolled to constants. So every Lichii shader
qualifies, and the check is sound for any other application. An opt-in "outputs are thread-owned" option without the
check would take 1–2 days, but it is unsafe for general use.

**Correctness risks.**
- A shader in which another thread writes or reads a vertex must keep the threadgroup path. The check above
  guarantees that.
- Register pressure (inferred, not measured): `f745a892263a512e` keeps 9 × 5 `float4` + 4 `uint3` per thread (about
  780 bytes), more than fits in registers, so it likely spills to thread stack in device memory. Whether that is
  slower than threadgroup memory has to be measured.
- The flush loop's stride must stay equal to the workgroup size, which it is.

**Size.** About 200–400 lines plus reference tests in SPIRV-Cross's `shaders-msl`. 4–6 days, then a MoltenVK rebuild
(under a minute) and checking pictures. For a local build it is a local SPIRV-Cross patch. Upstream SPIRV-Cross is active
(it merged #2686), but acceptance is up to its maintainers. MoltenVK merges nothing since its deprecation, so
MoltenVK-side changes would stay local.

### C. Narrower types

Narrower staged arrays (`float` for `.x`-only outputs, `packed_float3` for `.xyz`), `uchar4` instead of `uint3` for
indices (safe, because Metal caps vertices at 256), and a byte-sized `isbe_map` (Lichii; needs 8-bit Workgroup
storage). These bring the cached four down to 31,632 / 26,064 / 24,016, which builds, but `f745a892263a512e` keeps only
1,136 bytes of room and one game shader stays over (34,192). On its own C is not a fix. The index and map parts
(C1: 2,700 bytes on `f745a892263a512e`) are cheap and safe. With A the map is gone anyway, and the `uchar4` indices still
add 1,536 bytes of room on the 128-primitive shaders. "Every output is a `float4`"
is a Lichii choice (`TypeArray(F32[4], …)` in `DefineMesh`), not something the guest requires. Narrowing the mesh
*object* would also need fragment inputs of the same type, and the mesh object is not the binding limit here.

### G. `isbe_*` in a device buffer

Lichii could keep the ISBE regions in a per-workgroup slice of a scratch storage buffer, as its compute emulation
already does with `mesh_emulation_output`. That gives the same threadgroup budget as A, but it needs a buffer sized
by the grid (≈16 KiB per workgroup for `f745a892263a512e`). Every vertex then goes through device memory twice. A is
simpler and cheaper.

### H. The object payload

In Metal the mesh stage sees the payload as `const object_data`, so it can only read it. The payload is also already
used: 800 words here. It cannot hold mesh-written data.

### D. Smaller declarations

V and P come from the guest's NVN control words (`SET_MESH_SHADER_A`), and the program writes up to those counts, so
lowering them drops vertices. Splitting a meshlet in two would mean re-partitioning the guest program's work: rewriting
its control flow, not its declarations. The local size (32) does not enter the threadgroup sum at all. Not viable.

### E. Unread outputs

The paired fragment shaders read every location these shaders write (section 1.3). Dropping only unread *components*
is C.

### F. A larger limit

Measured: `maxThreadgroupMemoryLength` is 32,768 on the M4 Pro, with mesh ≤ 32,768 and a 61,440 total. Inferred:
Apple documents 32 KiB of threadgroup memory for all its GPU families, and there is no API to raise it. It is fixed.

## 4. Experiments: hand-edited MSL in Metal (measured)

`hand_edit.py` rewrites the dumped MSL of each oversized shader along each line:

- `direct` (A): every `isbe_attributes[...] = v` becomes a run-time-decoded switch into the staged Output component,
  every `isbe_map` byte store goes into `gl_PrimitiveTriangleIndicesEXT`, the epilogue copies are deleted, and both
  arrays are no longer declared. That is 216 attribute stores, 120 copies and 18 map stores in `f745a892263a512e`.
- `direct-attr` (A1): the same, but keeping `isbe_map`.
- `thread` (B): the 9 or 10 staged output arrays and the index array become `thread` arrays of ceil(N/32), indexed
  `[i / 32u]`. The script asserts that every index is `gl_LocalInvocationID.x + 32k`. `thread-full` keeps full-size
  thread arrays.
- `narrow` (C).

`mtlcheck` built each one with the pipeline's real fragment shader (`edits/mtlcheck.txt`):

```
f745a892263a512e.base.metal  + shader-fs-5e878fd478991ad2.metal: PIPELINE ERROR: Threadgroup memory size (42012) exceeds the maximum threadgroup memory allowed (32768)
f745a892263a512e.direct      : BUILDS     .direct-attr: BUILDS     .thread: BUILDS     .thread-full: BUILDS     .narrow: BUILDS
0c69b95fb5fc198e.base.metal  + shader-fs-8f5528664359d1a1.metal: PIPELINE ERROR: Threadgroup memory size (35100) exceeds the maximum threadgroup memory allowed (32768)
0c69b95fb5fc198e  direct / direct-attr / thread / thread-full / narrow: BUILDS
efdc2d865aa74afe.base.metal  + shader-fs-8f5528664359d1a1.metal: PIPELINE ERROR: Threadgroup memory size (35100) exceeds the maximum threadgroup memory allowed (32768)
efdc2d865aa74afe  direct / direct-attr / thread / thread-full / narrow: BUILDS
aad4571246c8d55c.base.metal  + shader-fs-327e4a4c2b9e8b6f.metal: PIPELINE ERROR: Threadgroup memory size (34076) exceeds the maximum threadgroup memory allowed (32768)
aad4571246c8d55c  direct / direct-attr / thread / thread-full / narrow: BUILDS
```

To make sure an edit builds because it really uses less memory, and not because Metal stripped something,
`probe.py` adds a live 32,768-byte threadgroup array. Metal's error then reports the shader's real usage plus 32,768
(`edits/mtlcheck-probe.txt`). Shader alone, after subtracting 32,768:

| Edit | `f745a892263a512e` | `0c69` / `efdc` | `aad4571246c8d55c` |
| --- | ---: | ---: | ---: |
| direct (A) | 25,108 | 21,524 | 21,524 |
| direct-attr (A1) | 26,660 | 22,308 | 22,308 |
| thread (B), thread-full | 16,932 | 13,604 | 12,580 |
| narrow (C) | 31,640 | 26,072 | 24,024 |

Each is the byte-table prediction plus 8 bytes of alignment for the probe, so Metal counts exactly what the tables
say. With the probe, the unedited files crash Metal's compiler service ("XPC_ERROR_CONNECTION_INTERRUPTED") instead of
reporting a size. Their sizes come from the unprobed run above.

**What this does not show.** The edits were not run on the GPU, and the picture was not checked. They show that the
memory budget works for A, A1, B and C. The `direct` edit also shows that the run-time decode switch compiles at that
size (216 dynamic stores). Next steps, in order:
- a GPU differential test of `direct` vs `thread` on synthetic buffers (they share the guest code, so a mismatch would
  be a transformation bug);
- then the real change in the emulator, checked with the verify harness on the foliage scenes.

## 5. Ruled out, and why

- **Packing `vec3`s in the staged arrays alone** (as SPIRV-Cross#2740 does for compute): this is part of C, and not
  enough by itself.
- **Raising MoltenVK's reported 12,284 shared and output limits**: this changes only what Lichii#1970 decides, not
  what Metal accepts. It is still needed alongside A or B, or Lichii#1970 will keep demoting shaders that now fit.
- **The payload, smaller declarations, a bigger limit**: see H, D and F.

## 6. What goes with any fix

- Lichii#1970's check (`mesh_fallback_limits.h`, `NativeMeshThreadgroupMemorySize`) adds the parts up to decide
  native vs emulated. It must model the new layout, and it should also check `mesh ≤ 32,768` and
  `threadgroup + mesh ≤ 61,440`, which it does not do today (inferred from the code read).
- MoltenVK's 12,284-byte mesh shared and output limits make Lichii#1970 demote 36 of 43 shaders. With A or B, those
  numbers no longer describe the real budget. For local builds, change MoltenVK or the Lichii check; upstream, MoltenVK
  is not merging anything.
- Keep the emulation fallback for whatever is still over: none of the 440 programs today, but a later game update
  could add one (see the `v100` margin under A).

## 7. Recommendation

| Rank | Route | Where | Fixes (game) | Effort to a picture checked on screen | Upstream dependency for a local build |
| --- | --- | --- | --- | --- | --- |
| 1 | **A + C1 (Lichii direct writes, byte-sized indices), with the emulation fallback for anything still over** | Lichii | all 440, worst 3 KB under the 61,440 total (`uchar4` indices add 1.5 KB) | **~1 week** (3–5 days code, 1–2 days checking) | none (Lichii fork build) |
| 2 | B (SPIRV-Cross thread-local outputs, with the safety check) | SPIRV-Cross | all 440, worst 15 KB under | ~1.5 weeks (4–6 days code + tests, 2 days checking), plus an unmeasured performance risk from spilling | local SPIRV-Cross patch; upstream acceptance optional |
| 3 | Emulate only the oversized shaders ([mesh-fallback](../mesh-fallback/README.md)) | Lichii | all, by construction | done: in the pinned build | none |
| — | C alone, G, D, H, F | | | not recommended | |

**Against emulating those shaders.** Emulation is the safe baseline and is what the pinned build does; keep it either
way as the fallback. What it costs depends on how much frame time those shaders take, and they are not marginal ones. All 10
oversized programs are the main foliage: flower, leaf, leaf_near, forest, stalk. A measured spread bounds the
stakes: native with the 3 oversized shaders *dropped* ran ~28.6 ms a frame, and everything emulated ran
~34.3 ms. Emulating only the oversized ones lands somewhere between. On the later pinned build, emulating only the
oversized shaders (the default) measured 20.3 / 21.3 / 19.1 ms against 23.5 / 23.2 / 21.2 ms with every mesh shader
emulated, and turning off all mesh draws saved only 0.5–1 ms ([emulator-options](../emulator-options/README.md)).
Inferred: A or B would buy little frame time and is mainly a cleaner design.

**Effort.** B, the SPIRV-Cross route, takes 1 to 2 weeks if it includes the safety check, tests and checking
pictures. The cheapest real fix is in Lichii, not SPIRV-Cross: about 1 week to a picture that has been
checked on screen, with no upstream dependency. A quick opt-in hack along B (no safety check, local only) would build
in 1–2 days, but it is the kind of change that likely produced the glitched picture in Lichii#1970's experiment, so it
needs the same checking time.

## 8. Files (`tg-approaches/`, local, not tracked)

- `tg_audit2.py`: an extended copy of an earlier audit script, `tg_audit.py`. It gives per-variable threadgroup bytes,
  the Metal mesh-object size, V, P, topology and local size. `audit.json` is its output on the dump.
- `mtlcheck.swift` / `mtlcheck`: builds a mesh pipeline from `MESH.metal[:FRAG.metal]` and prints Metal's verdict.
- `synth/`: the synthetic probes behind section 1.3.
- `hand_edit.py`, `probe.py`, `edits/`: the experiments of section 4 and their raw output.
- `approaches.py`, `approaches.txt`: the per-approach counts over every extracted mesh program.
- `dump_run.sh`, `dump-111335/`, `dump-run.*`: the one emulator boot and its MSL/SPIR-V dump (1,101 shaders).
- `spirv-cross/`: SPIRV-Cross at `e99dc7a3` with the CLI built (`build/spirv-cross`), ready for an approach-B
  prototype.


Also in this folder: `mesh-shader-sizes.csv`, the modelled sizes of all 440 mesh programs in the `.110` archives.
It has max vertices and primitives, threadgroup and mesh-output bytes, flags for each Metal limit and for the
fallback rule at Lichii `1f76c9f`, and whether the cache reaches the shader. It is posted on Lichii PR #1970; see
[wip/shader-prebuild/upstream.md](../../wip/shader-prebuild/upstream.md).
