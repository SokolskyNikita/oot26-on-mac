# Extended dynamic state on MoltenVK: plan

Whether turning on extended dynamic state (off by default on Apple in Lichii) would shrink the precompiled file.
Worked out on 2026-11-17 from code reading and offline counts only; the emulator was not launched. Each statement is marked
**verified** (and how) or **assumed**.

## Verdict

- **Worth trying, but the gain is small and its upper bound is already known.** Turning on EDS2 cuts the
  recorded vertex/pixel keys by 17% (2,540 → 2,099) and the "extra" states per shader combination by 31%
  (1,419 → 978). It changes **no** Metal compile: the distinct Metal pipelines (2,082), fragment halves
  (939) and vertex halves (1,189) are the same at every level. **Verified** offline (section E3).
- So it only helps key matching. In this design a key miss whose Metal halves were prepared costs a Lichii
  translation plus MoltenVK's SPIR-V→MSL step and a Metal cache hit, not a compile. The canyon test bounds
  what is left to win: 7.3 s of worker compile time against a 2.7 s floor, and 10.4 s of long frames
  against 8.9 s. EDS can close only part of that gap: at most about 1.5 s of long frames in that test.
  **Inferred** from the README's measurements.
- **Level to try: EDS2.** EDS1 gives nearly all of it (2,104 keys). EDS3 is available on MoltenVK, but in
  Lichii it adds only dynamic depth clamp (17 more keys merge); MoltenVK has no dynamic blend or logic op.
  `VK_EXT_vertex_input_dynamic_state` does not exist in this MoltenVK at all. **Verified** in source.
- **The real risk is the reason for the Apple default.** It dates from Eden PR #372 (2025-09-01): "EDS is
  forced to 0, otherwise games do not show graphics". Nobody has re-tested it on Mac since, as far as the
  repos show. A blank or broken picture is the likely failure, and it is easy to see.
- **Common assumptions, checked:**

  | Claim | Finding |
  | --- | --- |
  | "An hour to test" | **Only for a go/no-go** (does it draw, do keys shrink). A result you can act on (picture, frame time, prediction rebuilt and re-tested) is about **7 to 9 hours**, 4 to 5 of them with the emulator running. |
  | Existing caches stop matching | **True.** Every record has all six flag bits at 0, and `KeyFitsDevice` skips records whose flags differ from the device. **Verified** in code and data. |
  | Need re-recording | **Not necessarily.** An EDS key is the static key with fields cleared, flags set and the topology folded, and the SPIR-V does not change. So recorded and predicted keys can be **converted offline**. One live recording is still worth doing to check the converter. **Verified** in code; the converter itself is untested. |
  | Possible rendering faults | **True.** It is the documented reason for the default. |
  | Helps prediction, not Metal compile count | **True**, verified in code and counts. One nuance: dynamic stride takes the stride out of Metal's vertex descriptor, but in these caches stride never varies apart from the attribute layout, so the count does not change (E3). |

- **Cheaper alternative with no rendering risk:** the cleared fields (depth, cull, stencil) cost nothing in
  Metal. So the builder can raise `--kd` (depth/cull/stencil states per pair, today 1) and get part of the
  same key-match gain without touching the emulator. Held out on cache3: 82 keys are new only because of
  those fields (273 → 191, section E4).

**Total estimate: 7 to 9 hours** (offline work about 3 h, emulator time about 4 to 5 h, more if the
preparation runs cold). **A go/no-go alone (TODO steps 1 to 4): about 1 hour.**

## TODO

Steps 4 to 12 need the emulator.
Times assume the harness in `scripts/prebuild/exp.sh` (moves the shader folder aside, restores it) is reused.

1. **Back up (5 min, offline).** Copy `~/.cache/lichii/shader/0400486024dec000/` (`lichii-cache.v2.bin`
   164 MB and `vulkan_pipelines.fork-v54.bin` 197 MB, sizes as listed today), `~/.config/lichii/qt-config.ini`
   and `custom/0400486024DEC000.ini` to `prebuild/user-state-backup-<date>-eds/`. Even without it nothing is
   lost: records of the other level stay in the file, skipped but kept (section E5).
2. **Config for the test (5 min).** Per game, so other titles keep the default: in
   `custom/0400486024DEC000.ini` set `dyna_state\use_global=false` and `dyna_state=2` (EDS2; the enum is
   Disabled=0, EDS1=1, EDS2=2, EDS3=3, `settings_enums.h:168`). Leave `vertex_input_dynamic_state` alone:
   MoltenVK does not offer it. For the A/B, run the test with an app copy that has its own bundle id (own
   Metal cache) and a moved-aside shader folder, as `exp.sh` does.
3. **Write the key converter (60 to 90 min, offline).** Start from `scripts/eds/eds_keys.py`
   `level_state()`. Set raw1 bits 0 and 1, clear `dynamic_state.raw2` and the cull bits of raw1, clear the
   EDS2 bits (primitive restart, depth bias, rasterize enable), and fold the topology to its class. Then
   recompute each key's hash with `lichii_cache.graphics_key_hash`; `fps_size` already gives 368 bytes. Apply
   it to (a) the three training caches and (b) the builder's output keys. Check with
   `nx2-precompile check` and by matching against step 6's live keys.
4. **Smoke test (10 to 15 min, emulator).** Boot, title screen, load the top save, stand 2 minutes. In the
   log look for `DynamicState setting value: 2`, any MoltenVK `VK_ERROR_FEATURE_NOT_PRESENT` (dynamic
   stride), Metal validation errors, and the loader's count of records skipped for a dynamic-state mismatch
   (it should be about every graphics record). **Go/no-go:** blank or black screen, missing geometry,
   inverted culling (inside-out models), or a device loss means stop and roll back (step 13).
5. **Picture comparison (40 to 50 min, emulator).** The same route on both configs with screenshots at the
   same points: menus and the pause screen (static, so diff them pixel by pixel), Kokiri Forest fog and
   light shafts (blend; Lichii #1293 and #2112 are fog/blend bugs on other GPUs), the canyon, water,
   shadows and decals (stencil), the HUD, one cutscene. Do one extra run with `MTL_DEBUG_LAYER=1` (slow,
   about 15 min): it reports wrong strides (MoltenVK #2041 class) and wrong depth/stencil state.
   Fault signs: z-fighting or missing depth occlusion (dynamic depth test/write), see-through or
   inside-out meshes (cull/front face, MoltenVK #2569), missing stencil shadows or outlines (stencil op;
   MoltenVK #2069 needs a stencil attachment), smeared or exploded vertices (stride).
6. **Recording run (20 min emulator + 10 min offline).** With EDS2, an empty shader folder and the canyon
   route. Compare the live keys with step 3's converted keys for the same pipelines: they should be equal
   byte for byte up to `Size()`. If not, fix the converter before anything else.
7. **Frame-time comparison (75 to 90 min, emulator).** Warm caches on both sides, same route, **3 runs
   each** (the README's runs are n=1, with no spread known), `scripts/prebuild/hitches.py`. EDS adds
   `vkCmdSet*`/encoder state work per draw on the back thread, which is this game's bottleneck (Lichii
   #2116). It also lets more draws stay on the fast path, so the sign is not known.
8. **Builder change (45 to 60 min, offline).** Either post-process `build_precompiled.py --static` output
   with the converter (simplest; duplicates collapse because the `kd`/`kt` variants that differ only in
   cleared fields merge), or teach `state_model_static.py` an EDS2 layout: `STATE_LEN` 368, L without
   strides, D constant except `logic_op`, T with folded topology, and `kd` meaningless. Keep the static
   path for rollback; `--static` and an `--eds 2` mode should coexist.
9. **Rebuild the precompiled file (20 to 30 min, offline CPU).** The current full file, `static-v2`, has 292,535 records
   (1.2 GB, [precompiled-file.md](precompiled-file.md)); the
   EDS file will be somewhat smaller (not measured). Run `nx2-precompile check`.
10. **Prepare it (30 to 105 min, emulator).** The kept translations belong to the precompiled records
    and are made again. Metal: fragment MSL is assumed unchanged and should hit the existing Metal cache;
    vertex halves recompile once because the vertex descriptor now says dynamic stride (about 10 ms each).
    Metal's cache holds at most 1 GiB per file (`metal-shader-cache.md`), so prepare a trimmed
    file; the full one is mostly evicted and runs at the cold rate (105 minutes).
11. **Re-test (45 min, emulator).** The held-out first-visit test (`exp-pred2` style) with the EDS file,
    2 to 3 runs, against `exp-pred2` and `exp-ref`. Success means worker compile time and long-frame time
    move toward the 2.7 s / 8.9 s floor; the most it can gain is about 1.5 s of long frames.
12. **Optional EDS3 (20 min).** Only if step 5 was clean: `dyna_state=3` adds dynamic depth clamp
    (17 of 2,099 keys). Same smoke test and picture check.
13. **Roll back (5 min).** Set `dyna_state\use_global=true` in the per-game file, or restore the backup.
    Records of both levels stay in `lichii-cache.v2.bin`; the static ones are used again at once. One
    catch: MoltenVK keeps the used-pipeline lists of 8 sessions. After more than 8 EDS sessions the static
    used lists expire, and the next static boot builds at most 3,000 cached pipelines up front, the rest
    on demand (`MaxPipelinesWithoutUsedList`, `UsedPipelinesMaxAgeMoltenVK`). Restoring the backup avoids
    that.

| Part | Time | Emulator |
| --- | ---: | :---: |
| 1 to 3 (backup, config, converter) | 1.2 to 1.7 h | no |
| 4 (go/no-go) | 0.2 h | yes |
| 5 and 6 (picture, recording check) | 1.2 to 1.4 h | yes |
| 7 (frame time) | 1.3 to 1.5 h | yes |
| 8 and 9 (builder, rebuild) | 1.1 to 1.5 h | no |
| 10 and 11 (prepare, re-test) | 1.3 to 2.5 h | yes |
| **Total** | **about 7 to 9 h** | 4 to 5.5 h of it |

### Risks, worst first

1. **Blank or broken picture.** This is the reason for the default (Eden #372, 2025, "games do not show
   graphics"). The Lichii code paths for EDS on MoltenVK have not been exercised in this fork's issues or
   PRs. Found in step 4.
2. **Partial state bugs** that only show in some scenes: cull mode not applied (MoltenVK #2569 is open; a
   maintainer thinks the new state tracker, which this build has, fixed it), stencil defaults without a
   stencil attachment (#2069), or Lichii's dynamic-state tracking missing a register written on the native
   Switch 2 paths. The blend comment in `fixed_pipeline_state.cpp` describes that bug class for blending,
   which stays static here. Found in step 5, which needs broad scene coverage.
3. **Back-thread cost.** More per-draw state commands on the thread that limits this game; the change could
   lose more frame time than it saves. Found in step 7.
4. **Small upside.** At most about 1.5 s of long frames in the held-out test. If step 11 shows less than
   the run-to-run spread, the change is not worth keeping.
5. **Converter mistakes** would silently void predictions (as `exp-pred` was voided by a device bit). Found
   in step 6.
6. **Losing the user's cache.** Low: records are kept, and step 1 backs them up.

## Evidence

### E1. What each level takes out of the key

Source: `src/video_core/renderer_vulkan/fixed_pipeline_state.{h,cpp}`, `vk_pipeline_cache.cpp:1154-1186,
1700-1720`, `vk_graphics_pipeline.cpp:1851-1890, 2122-2225` in `prebuild/lichii`. **Verified** by reading.

Layout (offsets computed from the header; they match `lichii_cache.FPS_OFF` and the 432 bytes observed):
raw1 0, raw2 4, colour formats 8, driver 16, alpha ref 24, point size 28, swizzles 32, attribute types or
enabled divisors 64, `dynamic_state` 72 (raw1) and 76 (raw2), attachments 80, attributes 112, binding
divisors 240, vertex strides 368, `xfb_state` 432.

| Level | Flags set | Fields that leave the key | `Size()` |
| --- | --- | --- | ---: |
| Disabled (today) | none | none | 432 |
| EDS1 | raw1 bit 0 | `dynamic_state.raw2` whole (stencil front/back ops and func, stencil enable, depth write/test/bounds enable, depth func, front face); raw1 `cull_face`, `cull_enable`; vertex strides (past `Size()`, and set dynamically with `vkCmdBindVertexBuffers2EXT`) | 368 |
| EDS2 | + bit 1 | + `rasterize_enable`, `primitive_restart_enable`, `depth_bias_enable`; topology folded to its class (`TOPOLOGY_CLASS_REPRESENTATIVE_LUT`: strips, fans, quads and polygons become Triangles; LineLoop and LineStrip stay themselves) | 368 |
| EDS2 logic op | bit 2 | `logic_op`: **not on MoltenVK** (`extendedDynamicState2LogicOp = false`) | |
| EDS3 blend | bit 3 | attachments: **not on MoltenVK** (no ColorBlendEnable, Equation or WriteMask) | |
| EDS3 enables | + bit 4 | on MoltenVK only `depth_clamp_disabled` (`extendedDynamicState3DepthClampEnable = true`); logic-op enable, line stipple, alpha-to-coverage and alpha-to-one stay static | 368 |
| Dynamic vertex input | bit 5 | **not in this MoltenVK** (no such extension in `MVKExtensions.def`) | |

Other effects:
- **SPIR-V does not change.** `MakeRuntimeInfo` (`vk_pipeline_cache.cpp:235-410`) reads ndc, point size
  (only for Points), topology only as an input class (`input_topology`, which the fold keeps), tessellation,
  XFB, alpha test, dual source, colour formats (MoltenVK), early z and y negate. None of the cleared fields.
  **Verified.**
- **Vertex strides:** with EDS1 `Refresh` stops writing `vertex_strides`; the pipeline asks for
  `VK_DYNAMIC_STATE_VERTEX_INPUT_BINDING_STRIDE_EXT`, and buffers are bound with strides
  (`vk_buffer_cache.cpp:862-867, 921-923`). Static vertex repack is off on this Mac: MoltenVK reports a
  stride alignment of 1 on Apple5+ (`MVKDevice.mm:2655`) and `StaticVertexRepackSelected` needs more than 1.
  **Verified.**
- **Topology:** MoltenVK always keeps primitive restart on; Lichii already has MoltenVK cases for the EDS2
  primitive-restart command (`vk_rasterizer.cpp:4769`) and the pipeline (`vk_graphics_pipeline.cpp:1935`).
  **Verified.**
- **Keys from another level** fail `KeyFitsDevice` and are skipped: at cache load (`vk_pipeline_cache.cpp:2035`)
  and in preparation (`:2914`, "Made for a device with other dynamic state"). **Verified.**

### E2. Why Apple defaults to Disabled

`git log -L` over the setting in `prebuild/lichii` (**verified**):
- `6fcfe7f4f3`, 2025-09-01, Eden PR #372 "[macOS, compat] Allow games to boot in MacOS": added
  `__APPLE__ → 0` with "EDS is forced to 0, otherwise games do not show graphics". No root cause is given.
- Kept through `e4cbcec2f1` (#3233, the enum), `ee428deb1e` (#3532: EDS3 broke Sonic on Windows, so the
  Windows default dropped to EDS2) and `1b4a79c7ee` (#3832: Android moved to EDS1; Apple stayed Disabled).
- Lichii (`zortos293/Lichii`) issues and PRs: searches for "dynamic state", "EDS", "extended dynamic" and
  MoltenVK turned up nothing about EDS on Mac. PR #2116 (open) and closed #1216 touch fast draws under
  dynamic strides on PC. **Verified** with `gh search`. It is **assumed** that nobody has re-tested it on
  Mac since 2025.

### E3. MoltenVK support (path-60 tree, main `5189f8de` 2026-10-13 plus PRs)

**Verified** in `MoltenVK/MoltenVK/GPUObjects/MVKDevice.mm:690-735`, `MVKPipeline.mm`,
`Commands/MVKCommandEncoderState.mm`:
- EDS1: full. Depth/stencil goes into one `MTLDepthStencilState` and cull and front face into encoder
  calls, so none of it is part of a compiled Metal pipeline, static or dynamic.
- Dynamic vertex stride: needs macOS 14 and Apple4 or Mac2 (`dynamicVertexStride`, `MVKDevice.mm:2557`).
  It sets `MTLBufferLayoutStrideDynamic` in the vertex descriptor and passes the stride with
  `setVertexBuffer:offset:attributeStride:atIndex:`. Fixes for issue #2041 (PR #2042) and for tessellation
  (#2428, PR #2429) are ancestors of HEAD (`git merge-base --is-ancestor`).
- EDS2: yes, without logic op; patch control points yes. Dynamic rasterizer discard is emulated with an
  empty scissor (`MVKCommandEncoderState.mm:1326-1333`); static discard builds a pipeline with rasterization
  off.
- EDS3: depth clamp, polygon mode, depth clip, sample locations, line rasterization mode, and provoking
  vertex with private API. No blend, colour write mask, logic op enable, alpha-to-coverage or line stipple.
- `VK_EXT_vertex_input_dynamic_state`: not provided.
- Open upstream issues to watch: #2569 (dynamic cull mode ignored after a pipeline change; maintainer: "may
  be fixed now with the new state tracker", which this tree has) and #2069 (stencil test with dynamic state
  falls back to defaults when the render pass has no stencil attachment).
- Data checks on cache3 (**verified**, `stride_checks.py`): no vertex attribute on a stride-0 binding, no
  tessellation, topologies Triangles (2,064), TriangleStrip (241), Points (11). The stride-0 and
  tessellation paths of dynamic stride are therefore not exercised by this game's recorded draws.

### E4. Offline counts

Scripts in `scripts/eds/`: `eds_keys.py` (level rules
and Metal-side parts), `final_counts.py`, `per_pair.py`, `heldout.py`, `residual*.py`, `stride_checks.py`,
`provoking_by_file.py`; outputs `result.json`, `final_counts.json`, `per_pair.json`, `heldout.json`. Input:
`prebuild/eval/out-all/cache1..3.fork-v54.bin`, 9,347 graphics records. All have raw1 flags 0, `Size()` 432
and no XFB (**verified**). Keys are canonicalised as `state_model_static.canonical` does.

**The provoking-vertex bit is cleared before counting.** The provoking-vertex-last bit (raw2 bit 12) differs between the builds
that wrote the caches, not between draws. cache3 never sets it; caches 1 and 2 hold both values, about
65% set. Counted with it, the union looks like 4,014 keys at L0 and the provoking bit alone seems to split
36% of them. Without it the numbers below are the real ones. That is the same trap as the README's void
`exp-pred`, which `--scene-from` handles. **Verified** (`provoking_by_file.py`). The bit follows MoltenVK's
`useMetalPrivateAPI`: the stock app's MoltenVK sets it and the prebuild app's does not
([precompiled-file.md](precompiled-file.md)).

Distinct keys, union of the three caches, provoking bit cleared:

| | Disabled | EDS1 | EDS2 | EDS3 (MVK) | Distinct Metal pipelines |
| --- | ---: | ---: | ---: | ---: | ---: |
| Vertex/pixel keys (1,121 shader combinations) | 2,540 | 2,104 | 2,099 | 2,082 | 2,082 |
| … combinations seen with one state only | 675 | 793 | 796 | 796 | |
| … states beyond the first per combination | 1,419 | 983 | 978 | 961 | |
| Mesh keys (124 combinations) | 499 | 430 | 430 | 427 | 427 |

Metal-side counts, the same at every level (**verified** under the definitions in `eds_keys.metal_parts`):
vertex/pixel 1,189 vertex halves, 939 fragment halves, 2,082 whole pipelines; mesh 357, 93 and 427. "Vertex
half" means the vertex shaders, their SPIR-V inputs and the vertex descriptor (strides included only when
static). "Fragment half" means the pixel shader, MSAA, alpha test, colour formats and blending. "Whole"
adds the depth format. Treating these as exactly what Metal compiles is **assumed**; it rests on the
README's `mtlx --pipe2` measurements. Dynamic stride does not change the vertex-half count, because in
these caches the stride is fixed by the attribute layout of a vertex shader.

Per cache (single build, provoking constant within cache3), vertex/pixel keys at L0/L1/L2/L3: cache1
2,579/2,096/2,093/2,081, cache2 3,030/2,451/2,448/2,432, cache3 2,315/1,923/1,918/1,901.

Held out (train on caches 1 and 2, test cache3, vertex/pixel, provoking cleared; recorded overlap, not the
state model):

| | Test keys | Already recorded | Known shaders, new state | New shaders |
| --- | ---: | ---: | ---: | ---: |
| Disabled | 2,315 | 1,554 | 273 | 488 |
| EDS3 (MVK) | 1,901 | 1,251 | 191 | 459 |

So EDS removes 82 of the 273 "known shaders, new state" cases, the ones a predictor has to guess. The 459
to 488 keys with shaders never seen before are untouched, and they are what the game-file model (PR #1366
tables) covers.

### E5. What happens to existing files

- `lichii-cache.v2.bin`: static records **kept, unused** under EDS. Load skips them (`KeyFitsDevice`), they
  are never tombstoned for that reason, and `Compact()` is called without a size limit
  (`vk_pipeline_cache.cpp:2405`; `CompactLog` keeps every live record when no limit applies,
  `cache_file.cpp:174-218`). EDS records are added beside them with other hashes. **Verified.** The file
  grows by the EDS set (about 0.8× the static set by count); this is **assumed** because record sizes were
  not measured.
- The first EDS session starts **cold** for graphics: none of the recorded pipelines fit, and neither does
  any record of the current precompiled file (they are static keys, skipped without a warning like
  `exp-pred`). Compute records are unaffected. **Verified** in code.
- `static.nx2prep` and its builder: `state_model_static.py` hard-codes `STATE_LEN = 432` and parts that
  include strides (L) and `dynamic_state` (D); `build_precompiled.py --static` uses it. It needs the
  conversion or EDS mode in TODO step 8. `lichii_cache.fps_size`/`graphics_key_hash` already handle 368.
  **Verified** by reading.
- Kept translations (914 MB): made per precompiled record during preparation, so a rebuilt file is
  prepared again (TODO step 10). **Assumed** from `vk_pipeline_cache.cpp:3298` and the README.
- Metal's on-disk cache (per bundle id): fragment halves assumed reusable (same MSL), vertex halves
  recompile once (different vertex descriptor). **Assumed.**
- **Side by side:** the per-game `custom/0400486024DEC000.ini` holds the level (today
  `dyna_state\use_global=true`, `vertex_input_dynamic_state\use_global=true`); the global file has
  `dyna_state\default=true` (so Disabled on Apple). One shader folder can hold both levels' records, but for
  clean A/B runs use `exp.sh`'s pattern (folder moved aside and restored, one app copy and bundle id per
  arm). **Verified** by listing and reading the files, nothing edited.

## Could not check

- Whether games still draw nothing with EDS on this build and MoltenVK (needs the emulator).
- Whether the converted keys equal what a live EDS session records (TODO step 6).
- Back-thread cost of per-draw dynamic state on MoltenVK, and the fast-draw path under EDS without dynamic
  vertex input (#2116 targets PC with both features).
- Whether Metal's fragment compile cache really carries over (same MSL) once the pipeline has dynamic
  states, and how long preparation of a converted file takes.
- The exact size of an EDS precompiled file. It was not measured; reading the 1.3 GB `.nx2prep` was left
  out to keep CPU light.
- Lichii's Discord or other non-GitHub reports of EDS on Mac.
