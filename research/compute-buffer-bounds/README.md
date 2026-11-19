# Five compute shaders that fail on MoltenVK main

With Lichii `7c7f723` and unmodified MoltenVK main (`5189f8d`), assembled as a local test app (the "mainline app"
below), 5 compute pipelines fail on every boot with the Metal error "'buffer' attribute parameter is out of bounds:
must be between 0 and 30". This file explains why. It is a diagnosis; the pinned build avoids the fault by capping
`maxPushDescriptors` at 16 in MoltenVK (part of `patches/moltenvk/0002-…`), as the fork stock Lichii ships does.
Measured on an Apple M4 Pro (Mac16,8) under macOS 27.0.1.

**Short answer.** Each of the 5 shaders needs 37 buffers in one descriptor set (6 uniform buffers and 31 storage
buffers), plus Lichii's push constants. Metal gives a stage 31 buffer slots. That fits only through a Metal argument
buffer. MoltenVK never uses argument buffers for push descriptor sets. Lichii uses a push descriptor set whenever the
set has no more entries than `maxPushDescriptors`. Upstream MoltenVK (1.4.1 and main alike) reports 287 on the M4 Pro,
so Lichii pushes these sets, they bind one slot per buffer, and indices 31 to 37 fall off the end. The MoltenVK that
ships with stock Lichii (build 228) is **not upstream 1.4.1** but a fork that sets `maxPushDescriptors` to 16, so Lichii
uses ordinary descriptor sets for these shaders and they build. Nothing regressed inside MoltenVK between 1.4.1 and
main: the fork's one-line patch is the whole difference.

The 16 patch makes all 135 compute pipelines build and brings the tree canopy back (measured, run `push16`). A side
effect explains the 5 compile errors that remain with the patch. Each failed shader also poisons MoltenVK's saved
pipeline cache, so on every unpatched boot the driver rejects the whole cache file and Lichii starts from an empty one
(section 4a).

Sources: a baseline run of the mainline app with the unmodified library (logs `base-5189f8d.stderr.log` and
`base-5189f8d.eden_log.txt`; local run data, not tracked), Lichii source at `7c7f723`, MoltenVK source at `v1.4.1`
and `5189f8d`, and a standalone Vulkan reproduction in [repro/](repro/). No emulator was started for the analysis
itself.

## 1. The five shaders

Lichii names them when the driver rejects them (`vk_compute_pipeline.cpp:324` at `7c7f723`), measured in
`base-5189f8d.eden_log.txt`:

```
[2.755474] ... Driver rejected compute shader 331E607152CE78D5: VK_ERROR_INITIALIZATION_FAILED
[2.881320] ... Driver rejected compute shader F12162B84E9CC190: VK_ERROR_INITIALIZATION_FAILED
[2.981119] ... Driver rejected compute shader CE9F15D1FE2E4101: VK_ERROR_INITIALIZATION_FAILED
[3.477140] ... Driver rejected compute shader 74AB167D83C54073: VK_ERROR_INITIALIZATION_FAILED
[3.723238] ... Driver rejected compute shader 541BA22D44898196: VK_ERROR_INITIALIZATION_FAILED
[8.097837] ... Shader cache v2 boot load: 7.2 s, 130 of 135 compute and 1538 of 1538 graphics pipelines built
```

They are the game's own compute shaders (Kepler compute dispatches recompiled by Lichii), not Lichii's internal
helpers. What they do:

- `331e607152ce78d5` is, in Lichii's own words, "Ocarina of Time's foliage culling compute": a test in
  `src/tests/video_core/storage_buffer_pointer_tracking.cpp` (around line 516 at `7c7f723`) says it reads 8
  per-type instance tables through pointers. Read from the code.
- The other four are not named anywhere in Lichii's source or in these notes. Their shape is the same as the foliage
  culler (same 6 + 31 buffer layout), which suggests sibling culling or instancing passes, but that is a guess.
- The stock app (build 228) builds and dispatches `331e607152ce78d5`, `74ab167d83c54073` and `ce9f15d1fe2e4101`
  during normal play (`research/logs/log-run1-addons-on.txt`: "Compute pipeline built on the GPU thread in 10.2 ms ...
  s6:331e607152ce78d5"). Measured.

When a pipeline fails, Lichii keeps the `ComputePipeline` object with no `VkPipeline`; every later dispatch of it
returns early at `if (!pipeline->IsBound()) return;` (`vk_rasterizer.cpp`, `DispatchCompute`, three call sites).
The dispatch is skipped silently: no error per frame, and whatever the shader should have written is stale or empty.
Read from the code.

What visibly breaks: the baseline screenshot (`base-5189f8d.standing.jpg`, Kokiri Forest, top save) shows the forest
trees with bare branches. That fits a foliage culler that never runs, and
[mac-performance](../mac-performance/README.md) lists "tree canopy missing" for MoltenVK main. In that run nothing else
failed (`build failed: 0`, `sampler-limit: 0`, all 1538 graphics pipelines built), so these 5 dispatches are the only
pipelines missing. With the 16 patch (run `push16`, same spot) all 135 compute pipelines build and the canopy is back in
`push16.standing.jpg`. Measured; the screenshot and logs were checked. The link is strong but not isolated: see the last
section.

## 2. What the generated MSL binds

The error lines carry the whole kernel signature. Three distinct signatures appear across 10 failed compiles. Each
shader is compiled twice per boot: once when the driver's pipeline cache file is loaded (5 "Shader library compile
failed" without a pipeline message), then once when the pipeline is built (5 more, each followed by "Compute shader
function could not be compiled into pipeline"). Section 4 explains the first set. Abbreviated, the first
signature is:

```
kernel void main0(
  constant void* spvBufferAliasSet0Binding0 [[buffer(1)]],
  constant cs_cbuf_block_5u_2& c1           [[buffer(2)]],
  constant void* spvBufferAliasSet0Binding2 [[buffer(3)]],
  constant cs_cbuf_block_5u_3& c4           [[buffer(4)]],
  constant void* spvBufferAliasSet0Binding4 [[buffer(5)]],
  constant void* spvBufferAliasSet0Binding5 [[buffer(6)]],
  device void* spvBufferAliasSet0Binding6   [[buffer(7)]],
  ...                                        (one per binding, no gaps)
  device void* spvBufferAliasSet0Binding29  [[buffer(30)]],
  device void* spvBufferAliasSet0Binding30  [[buffer(31)]],   <- first error, column 1752
  ...
  device void* spvBufferAliasSet0Binding36  [[buffer(37)]],   <- seventh error, column 2094
  texture2d<float> cs_tex0_90 [[texture(0)]], texture2d<float> cs_tex0_98 [[texture(1)]],
  sampler cs_tex0_90Smplr [[sampler(0)]], sampler cs_tex0_98Smplr [[sampler(1)]],
  uint3 gl_WorkGroupID [[threadgroup_position_in_grid]], ...)
```

| Signature | Buffers | Textures | Compiles | Probable hash (by log order) |
| --- | --- | --- | --- | --- |
| `cs_tex0_90`, `cs_tex0_98` | set 0 bindings 0–36 at `buffer(1..37)` | 2 combined image samplers | 2 | `331e607152ce78d5` |
| no textures | same | none | 6 | `f12162b84e9cc190`, `ce9f15d1fe2e4101`, `74ab167d83c54073` |
| `cs_tex0_a0`, `cs_tex0_a8` | same | 2 combined image samplers | 2 | `541ba22d44898196` |

The hash-to-signature column is inferred from the order of the stderr blocks matching the order of Lichii's log
lines; the MoltenVK messages carry no hash.

What occupies each index (read from the MSL and from `MVKPipelineLayout::Create` in `MVKPipeline.mm` at
`5189f8d`):

- `buffer(0)`: Lichii's push constants. Lichii's compute pipeline layout always has one push constant range
  (`pipeline_helper.h`, `CreatePipelineLayout`), and MoltenVK reserves a slot for it before the descriptor sets
  whether or not the shader reads it. The three texture-less shaders also start at `buffer(1)`.
- `buffer(1)`–`buffer(6)`: bindings 0–5, uniform buffers (guest constant buffers; `constant` address space).
- `buffer(7)`–`buffer(37)`: bindings 6–36, 31 storage buffers (guest global memory; `device` address space).
- No implicit MoltenVK buffer (swizzle, buffer size, dynamic offset, dispatch base) appears in any signature. The
  indices that overflow, 31 to 37, are all guest storage buffers: bindings 30 to 36.

MoltenVK main also logs the overflow at bind time, 5 times each:

```
[mvk-error] Pipeline wants to bind buffer 31 which goes above the limit 31, skipping...
...
[mvk-error] Pipeline wants to bind buffer 37 which goes above the limit 31, skipping...
```

So the shader really needs 37 guest buffers + 1 push constant buffer = 38 slots when bound one slot per
descriptor. No index assignment can fit that into 31. It fits only through an argument buffer, where the whole set
takes one slot.

## 3. Whose bug, and is it a regression

**It is not a regression in MoltenVK.** Three things, each checked:

1. The `maxPushDescriptors` line is the same in upstream `v1.4.1` and `5189f8d`
   (`MVKDevice.mm`: `supportedProps14.maxPushDescriptors = _properties.limits.maxPerStageResources;`), and
   `maxPerStageResources` = 31 buffers + 256 textures in both. Read from the code.
2. Querying the dylibs directly ([repro/query_push_limit.c](repro/query_push_limit.c)), Apple M4 Pro, measured:

   | Library | `maxPushDescriptors` |
   | --- | --- |
   | Stock Lichii build 228's bundled library (reports itself as "1.4.1") | **16** |
   | MoltenVK main `5189f8d`, unmodified | 287 |
   | Homebrew `molten-vk` 1.4.2 | 287 |

3. Lichii does not use Homebrew's MoltenVK for its release. `cpmfile.json` pins `"moltenvk"` to
   `HyperCed/Ryujinx.MoltenVK` release `v1.4.1-ryujinx-sparse` (branch `lichii-sparse`, a fork of
   `V380-Ori/Ryujinx.MoltenVK`). That fork carries commit `438a62b3` (V380-Ori, 2025-09-05), "Limit
   maxPushDescriptors property to 16. Prevents vertex explosions when push descriptors are used.", a one-line change
   from `maxPerStageResources` to `16`. No upstream tag ever had 16.

So a value of 16 for "MoltenVK 1.4.1" is right about the library stock Lichii ships but not about upstream 1.4.1:
the 16 comes from the fork.

The binding behaviour is also the same in both: `pickArgumentBufferMode` in `MVKDescriptorSet.mm` returns `Off`
for any layout created with `VK_DESCRIPTOR_SET_LAYOUT_CREATE_PUSH_DESCRIPTOR_BIT` ("Push descriptors are always
binding-based"), at `v1.4.1` line 191 and at `5189f8d`. Read from the code.

Lichii's side: `DescriptorLayoutBuilder::CanUsePushDescriptor()` (`pipeline_helper.h`) allows a push set when
`num_descriptors <= device->MaxPushDescriptors()`. These sets have 37 or 39 descriptors: above 16 (ordinary set,
argument buffer, builds) and below 287 (push set, discrete, fails).

The reproduction ([repro/push_set_pipeline.c](repro/push_set_pipeline.c) with [repro/t.comp](repro/t.comp)) builds
the same shape outside the emulator: one set of 6 uniform + 31 storage buffers, all used, plus a push constant
range. Measured, `vkCreateComputePipelines` result:

| Library | Argument buffers | Push set | Ordinary set |
| --- | --- | --- | --- |
| fork 1.4.1 (stock app) | on (default) | -3, `buffer(31..37)` errors | 0 (builds) |
| fork 1.4.1 | off (`MVK_CONFIG_USE_METAL_ARGUMENT_BUFFERS=0`) | -3 | -3 |
| main `5189f8d` | on (default) | -3, the same 7 errors | 0 (builds) |
| main `5189f8d` | off | -3 | -3 |

To rerun: `glslangValidator -V repro/t.comp -o t.spv`, `clang -I/opt/homebrew/include repro/push_set_pipeline.c -o t`,
then `./t <path to libMoltenVK.dylib> <1 for a push set, 0 for an ordinary set>` from the folder holding `t.spv`.
`query_push_limit.c` builds the same way and takes only the dylib path.

Both libraries print the same seven "out of bounds" errors and the same seven "Pipeline wants to bind buffer 31..37"
lines for the failing cases. The bug is therefore a mismatch between the two sides:

- **MoltenVK** advertises a `maxPushDescriptors` (287) that its own discrete binding cannot honour for
  buffer-heavy sets, and does not refuse the layout or pipeline up front. This is a known upstream problem:
  KhronosGroup/MoltenVK#2426, "Max push descriptors is too large when MoltenVK needs reserved bindings" (opened
  2025-01-23 by squidbus, closed by its author on 2026-10-16 with no linked fix; MoltenVK was deprecated three days
  earlier).
- **Lichii** trusts that single number. Vulkan has no per-type push limit, so a portable app can't do better
  without knowing the driver; Lichii already special-cases MoltenVK elsewhere (`IsMoltenVK()`).

The shader itself is legal and fits Metal when bound through an argument buffer. Lichii does not need fewer
buffers.

## 4. The 16 patch and argument buffers

- **`maxPushDescriptors` = 16:** with it Lichii's `CanUsePushDescriptor()` returns false for these 37/39-entry sets,
  so they become ordinary sets, which use argument buffers, which build (row "ordinary set, argument buffers on"
  above, on both libraries). That is exactly the stock app's configuration. In the emulator (run `push16`,
  measured): "135 of 135 compute and 1538 of 1538 graphics pipelines built",
  no "Compute shader function could not be compiled into pipeline" lines, and no "bind buffer ... above the limit
  31" lines. The unpatched baseline had 130 of 135, 5 pipeline failures and 35 limit lines (7 per shader).
- **`MVK_CONFIG_USE_METAL_ARGUMENT_BUFFERS`:** does not help. Its default is already 1 in both versions
  (`MVKEnvironment.h`), and push sets ignore it. Setting it to 0 makes things worse: then even ordinary sets bind one
  slot per buffer and these shaders fail with the 16 patch too (reproduction rows with argument buffers off).

## 4a. Why 5 compile failures remain with the patch

The `push16` run still shows 5 "Shader library compile failed" errors, with the same `buffer(31..37)` signatures,
and then builds all 5 pipelines anyway. Those errors aren't a retry. They come from loading MoltenVK's pipeline
cache:

1. Lichii saves the driver's pipeline cache to
   `~/.cache/lichii/shader/0400486024dec000/vulkan_pipelines.fork-v54.bin` and loads it at boot.
2. When an earlier unpatched run built these 5 shaders, MoltenVK stored the converted MSL in that cache even though
   it failed to compile. `addShaderLibrary` keeps the library either way.
3. On load, `MVKPipelineCache::readData` → `MVKShaderLibraryCache::addShaderLibrary` → the `MVKShaderLibrary`
   constructor compiles every stored library at once (`compileLibrary`). The stale MSL fails again. The compiler's
   `handleError` (`MVKSync.mm`) sets `VK_ERROR_INITIALIZATION_FAILED` on its owner, which is the pipeline cache, so
   **`vkCreatePipelineCache` fails and the whole cache is rejected**, not just those 5 entries.
4. Lichii logs this on every boot of all three runs (`base`, `base2`, `push16`), about 0.5 s after loading:
   `Driver rejected the Vulkan pipeline cache file (VK_ERROR_INITIALIZATION_FAILED), starting with an empty cache and
   deleting it`.
5. With the patch, the pipeline's set 0 is an argument buffer, so its conversion config no longer matches the stale
   entry. MoltenVK converts the SPIR-V again and the new MSL builds. Without the patch the fresh MSL is the same
   bad MSL, fails again, and is saved again. That's why the cache is poisoned on every unpatched boot.

[repro/pipeline_cache_reload.c](repro/pipeline_cache_reload.c) shows each step on main `5189f8d` (measured):

| Step | Result |
| --- | --- |
| Push set, empty cache, save the cache | pipeline fails (-3), 9,745-byte cache saved |
| Load that cache | one "Shader library compile failed" during `vkCreatePipelineCache`, which returns -3 |
| Ordinary set (what the patch gives) with no cache | builds (0) |
| Ordinary set, empty cache, save, then reload | cache loads (0), pipeline builds |

The eager compile and the owner-wide error are the same at `v1.4.1` (`MVKShaderModule.mm:225`, `MVKSync.mm:470`).
This isn't a regression either; the stock app just never stored a failing library. Consequences:

- On unpatched main, Lichii throws away its whole MoltenVK pipeline cache every boot and converts every shader to
  MSL again. All three runs here hit this, so their boot times (7.1–7.2 s for the cache v2 load) all include that
  cost.
- With the patch, the second boot should find a clean cache (the `push16` run wrote one without the stale entries):
  no first-attempt errors and no rejection. Not measured.
- More generally, one MSL compile failure stored in the cache throws away the whole cache on the next boot. A
  MoltenVK-side fix would be to skip a stored library that fails to compile instead of failing the cache, or to not
  store libraries that failed. That's a few lines in `MVKShaderModule.mm`, but upstream is deprecated. Lichii
  already recovers by starting empty.

## 5. The better fix, in Lichii

**In Lichii, about 10–15 lines, in `DescriptorLayoutBuilder::CanUsePushDescriptor()`
(`src/video_core/renderer_vulkan/pipeline_helper.h`).** On MoltenVK, refuse a push set when it would not fit
Metal's buffer table bound one slot per descriptor: count the bindings of type uniform buffer and storage buffer
(texel buffers are Metal textures and don't count), add 1 for Lichii's always-present push constant range, and
require the total to stay under 31 with some headroom for MoltenVK's implicit buffers (buffer-size, dispatch-base,
and for graphics stages the vertex buffers, which take slots from the same table). The simplest safe form is what
the fork already does, clamping the limit to 16 on MoltenVK
(`std::min(MaxPushDescriptors(), 16u)` when `IsMoltenVK()`); the buffer count is the more exact form and keeps
small push sets fast. Either way it is local to Lichii, works with any MoltenVK (upstream main, Homebrew, or the
fork), and doesn't depend on an upstream that is deprecated.

The MoltenVK-side alternatives are worse: the fork's one-line `= 16` patch fixes it only for builds that carry the
patch, and a proper fix (count only buffers against the Metal limit, or fall back to an argument buffer for large
push sets) is a larger change in `MVKDescriptorSet.mm` and `MVKPipeline.mm` that was discussed but not done in
#2426.

## What remains unproven

- That the bare trees in the main baseline come from these 5 skipped dispatches. The canopy comes back with the
  16 patch, and these 5 are the only pipelines that differ in build success. But the patch also moves every other
  set above 16 entries from push to ordinary binding, so this is strong evidence, not isolation. Only the foliage
  culler is named.
- The mapping from the 3 MSL signatures to the 5 hashes is inferred from log order.
- What the other four shaders do.
- The full MSL of the real shaders: no `MVK_CONFIG_SHADER_DUMP_DIR` dump of them exists; the evidence here is the
  kernel signature printed in each compile error, which lists every resource.
- That a second patched boot loads the driver pipeline cache cleanly (section 4a predicts it). That would also show
  how much boot time the rejected cache costs on unpatched main.
