# Tracker

This file answers three questions about the pinned build in this repository: what is in it and why, what was tried
and not adopted, and what is worth doing next. The pinned build is Lichii `8c0558a3d3` with the series in
`patches/lichii/`, and MoltenVK `5189f8de86ec` with the series in `patches/moltenvk/`, running the 2026 Switch 2
remake of Ocarina of Time (title `0400486024DEC000`, version 1.1.1) through Vulkan, MoltenVK and Metal. The guest
CPU runs on the dynarmic JIT (an arm64-to-arm64 recompiler) with one code cache shared by the six guest cores. The
pinned build does not hold 60 fps: walking medians are 18.7–23 ms across the recorded runs.

Last full review: 2026-11-19. The most recent runs of the pinned build as `build.sh` makes it (2026-11-19, three
runs, 600-frame phases): walking 19.5 / 18.9 / 19.6 ms, standing after the walk 16.6 / 16.5 / 16.5 ms, boot to
in-game 39.4 / 38.0 / 39.3 s, pictures clean. Hardware: Apple M4 Pro (Mac16,8), macOS 27.0.1. Test spot, unless a row says
otherwise: standing at the Kokiri Forest spawn point, 1x resolution, handheld mode, GPU accuracy Low, asynchronous
shaders on, post-processing off.

How to read the numbers:

- Frame times are medians in ms. Numbers from before 2026-11-17 come from an earlier harness that took the median of
  1,050 standing frames. Later numbers come from `tools/harness/`, which reports one median per phase as three
  values: standing / scripted walk / standing again at the end of the walk. Percentiles (p90, p95, p99) are named
  where used. Run-to-run noise in `tools/harness/` is about ±0.5–1 ms.
- "Stock" is Lichii release build 228 (2026-11-15) as downloaded, with its bundled MoltenVK 1.4.1 fork and mesh
  shaders emulated.
- "All-in-one" is the first combined build of 2026-11-16: Lichii patches 0001–0005 and MoltenVK patches 0001–0005.
- "path-60" in patch names is the frame-time work aimed at 60 fps; `P60_*` and `MVK_P60_*` are its environment
  switches.
- "Speckled frames" counts frames with white specks in a 30-frame burst taken at the Kokiri Forest cave wall.
- "Map load" is from the loading screen to Link in game; the harness's own "load" figure also includes boot.
- "Run ab-… (local)" names a run folder kept outside the repository.

## In the pinned build

In the order the changes went in. Patch names are under `patches/lichii/` and `patches/moltenvk/`.

| # | Change | Where it lives | Whose it is | Effect | Evidence |
| --- | --- | --- | --- | --- | --- |
| 1 | Mac support with native mesh shaders and a per-shader fallback to emulated mesh shading | `lichii/0001-Merge-Lichii-PR-1970-HyperCed-Better-MacOS-Support-w.patch` | Lichii PR #1970, HyperCed, open; squash of head `1f76c9ff56` (the PR head is now `b697762630`) | Lets Lichii use MoltenVK's native mesh shaders. Its own demotion rule trusts MoltenVK's advertised 12,284 bytes of threadgroup memory and demotes 256 of the game's 440 mesh shaders (an earlier count said 36 of 43); row 2 replaces the rule. Also brings the Hypervisor CPU backend, compiled in and not used (see Tried, Hypervisor backend). | `research/mesh-fallback/`, `research/mac-performance/` |
| 2 | Demote a mesh program only when its native threadgroup memory exceeds the device limit | `lichii/0002-vulkan-demote-a-mesh-program-only-when-its-native-MS.patch` | ours | Predicts Metal's threadgroup bytes exactly for the 49 native and 4 demoted programs seen in play (4 demoted at 34,076–42,012 bytes against 32,768); 0 threadgroup errors, 0 failed pipelines. Of the 440 mesh shaders in the game, 10 are predicted over the limit, all in `Shader/Foliage.Product.110`. `EDEN_NX2_MESH_TG_LIMIT=<bytes>` overrides the limit. | `research/mesh-fallback/`, `research/mesh-threadgroup-memory/` (`mesh-shader-sizes.csv`) |
| 3 | Skip failed mesh pipelines when seeding vertex-input lenders | `lichii/0003-Merge-Lichii-PR-2022-RomainROCH-vulkan-skip-failed-m.patch` | Lichii PR #2022, RomainROCH, merged 2026-11-17; squash of `f1f0dcc13a` | Not measured on its own. | `research/mac-performance/` |
| 4 | Skip uniform bank re-uploads whose bytes did not change | `lichii/0004-Merge-Lichii-PR-1902-Terobyte-buffer_cache-skip-nati.patch` | Lichii PR #1902, Terobyte, open; squash of `c7e22dabc9` | Not measured on its own. | `research/mac-performance/` |
| 5 | NaN guard for unwritten vertices on the native mesh path | `lichii/0005-native-mesh-NaN-guard-for-unwritten-vertices.patch` | ours | Blanks every vertex position first, as the emulated path does. No visible change at the spawn; kept as a guard. | `research/mesh-native-colours/` |
| 6 | `VK_EXT_mesh_shader` in MoltenVK | `moltenvk/0001-Merge-MoltenVK-PR-2842-dttdrv-Add-VK_EXT_mesh_shader.patch` | MoltenVK PR #2842, dttdrv, open; squash of `c516eb42` (head on 2026-11-16) | Native Metal mesh shaders. Speed is not settled: on 2026-11-16, with a correct picture, native measured 43.5–43.7 ms against ~41.4 ms for stock (different builds); on 2026-11-17, forcing emulated mesh shaders (Mesh shaders = Compute) gave 23.5 / 23.2 / 21.2 ms against 20.3 / 21.3 / 19.1 ms native. All mesh foliage costs ~0.5–1 ms (`EDEN_NX2_NO_MESH`). | `research/mac-performance/`, `research/emulator-options/` |
| 7 | Specialization-constant array sizes; `maxPushDescriptors` reported as 16 | `moltenvk/0002-Merge-MoltenVK-PR-2843-dttdrv-specialization-constan.patch` | MoltenVK PR #2843, dttdrv, open (squash of `cae05219`); the limit is ours (Lichii's bundled MoltenVK fork, HyperCed/Ryujinx.MoltenVK, has the same cap) | #2843 not measured on its own. The limit: upstream MoltenVK reports 287, so Lichii sends push-descriptor sets of 37 buffers to Metal's 31 slots. With 16, MoltenVK main of 2026-10-13 on Lichii `nx2` `7c7f723`: compute pipelines 130 → 135 of 135, "could not be compiled into pipeline" 5 → 0, tree canopy bare → leafy; frame time unchanged (49 / 48 / 44 ms vs 47 / 49 / 61 ms standing / walk / second walk). | `research/compute-buffer-bounds/` |
| 8 | SPIRV-Cross pinned at the PR #2686 merge commit | `moltenvk/0003-SPIRV-Cross-at-the-2686-merge-commit.patch` | SPIRV-Cross PR #2686, dttdrv, merged 2026-10-28 | Mesh and task shader fixes in the Metal backend that #2842 needs. Row 10 moves the pin further. | `research/mac-performance/` |
| 9 | Subgroup support for mesh and task stages; diagnostic hooks | `moltenvk/0004-mesh-subgroup-stages-for-mesh-and-task-shaders-diagn.patch` | ours | MoltenVK listed subgroup support only for fragment, compute and tessellation-control stages, so Lichii emitted a no-subgroup form of every mesh shader (all 32 threads on one element). With mesh (Apple7) and task (Apple9) added, foliage drawn as white and multicoloured shards draws as foliage. The hooks (`MVK_DIAG_INVARIANT`, `MVK_DIAG_OVERRIDE_DIR`) are off unless set. | `research/mesh-native-colours/` |
| 10 | Batched indirect-count draws; SPIRV-Cross `98cbb7c0`; mesh position fixup | `moltenvk/0005-Merge-MoltenVK-PR-2897-paulpan05-batch-indirect-coun.patch` | MoltenVK PR #2897, paulpan05, open (squash of `f2594b14`; the conflict with #2842 resolved by hand, mesh draws keep their old path). The pin carries SPIRV-Cross PR #2721, tksuoran, merged 2026-10-28. The position fixup is ours (SPIRV-Cross issue #2717, open) | #2897 not measured on its own. The new SPIRV-Cross drops `[[clang::optnone]]` from the float helpers: stock with only this MoltenVK swapped in, 32.7–34.7 ms vs 39.4–39.6 ms (one of four runs crashed ~10 s after spawn and did not repeat in 2 reruns); Lichii `nx2` of 2026-11-16, 32.3–34.2 ms vs 46.4 ms with the old library. Position fixup: SPIRV-Cross skips the Y flip and depth fixup for a standalone mesh position output; a text rewrite of the generated Metal source adds both (`MVK_ALLINONE_NO_MESH_FLIP` turns it off). Without it ground grass draws upside down where the canopy should be; with it the picture matches stock, checked by eye at the spawn. | `research/mac-performance/` (`native-mesh-no-position-fix.png`, `native-mesh-with-position-fix.png`) |
| – | Rows 1–10 together (the all-in-one) | – | – | 28.6 and 29.2 ms, 0 slow frames; from empty shader caches 27.9 and 29.1 ms; stock 39.5 ms. Picture right by eye at the spawn. How much each piece gives beyond the SPIRV-Cross update was not separated. | `research/mac-performance/` (`stock-228.png`, `all-in-one.png`) |
| 11 | MoltenVK frame profiler | `moltenvk/0006-Frame-profiler-MVKFrameProf-per-pass-GPU-time-encode.patch` | ours | Per-pass GPU time, encoder and command-buffer counts, written when `MVK_FRAMEPROF=<path>` is set. Instrumented 30.6 ms vs 30.7 ms without, on the all-in-one. It mapped the all-in-one frame: GPU busy 26.7 ms, idle 3.9 ms; the game's upscaling network is one 7.9 ms compute pass (1440×810 → 1920×1080, 105 tensor multiplies emulated with SIMD shuffles); ~1,070 Metal encoders per frame. | `research/allinone-frame-breakdown/` |
| 12 | Frame-time fixes in Lichii | `lichii/0006-path-60-frame-time-fixes-and-their-switches.patch` | ours | Three fixes, each on by default with a `=0` off switch. Shuffle-free tensor multiply for the upscaling network (`P60_HMMA_MEM`): 7.8 → 2.4–2.6 ms offline, 30.0 → 24.2–24.3 ms in game, output bit-identical over 3.1 million lane results and the 2,073,600 pixels of a captured frame. CPU widening of 8-bit indices (`P60_UINT8_HOST`): removes MoltenVK's per-draw conversion dispatches (82 a frame), 1.3 ms alone. List-indirect draws on MoltenVK (`P60_LIST_INDIRECT`; MoltenVK reports 2^30 where Lichii asked for 2^31−1): GPU idle 3.9 → 1.5 ms, 1.2 ms alone. Off unless set: a bilinear stand-in for the upscaling network (`P60_OOT_BILINEAR=1` with `EDEN_NX2_DLSS_REPLACEMENT=fsr`), `P60_RUN_AHEAD`, the frame trace `P60_SYNC_TRACE`. With row 13 on: 18.6–19.1 ms standing, GPU work 16.4 ms. | `research/path-to-60fps/`, `research/allinone-frame-breakdown/`, `tools/perf/` |
| 13 | Keep Metal encoders open across pipeline barriers; App Nap opt-out | `moltenvk/0007-path-60-keep-the-render-encoder-across-barriers-and-.patch` | ours | Under `MVK_P60_KEEP_ENCODER`: encoders 1,073 → 701 a frame, 2.5 ms alone (27.5 ms at the time). `MVK_P60_NO_APPNAP=1` keeps macOS from moving a hidden window to the efficiency cores; off unless set. | `research/path-to-60fps/` |
| 14 | Keep-encoder on by default | `moltenvk/0008-path-60-keep-encoder-on-by-default-MVK_P60_NO_KEEP_E.patch` | ours | 20.5 / 22.1 / 20.0 → 18.1 / 21.3 / 17.7 ms. `MVK_P60_NO_KEEP_ENCODER=1` turns it off. Picture watched at the test spot only. | `research/emulator-options/` |
| 15 | Compile pipeline-cache shader libraries when first used | `moltenvk/0009-Merge-MoltenVK-PR-2901-frankea-Compile-pipeline-cach.patch` | MoltenVK PR #2901, frankea, open; applied from a diff of the PR against this tree, 2026-11-17 | Without it MoltenVK compiles every library in Lichii's pipeline file one at a time at boot (~4,700 libraries). Boot from an empty Metal cache 455–483 s → 78.8 s (test build) and 97.4–100.7 s (pinned build); first boot of a new MoltenVK on a filled cache 206 s → 15.4 s. 14 of 14 boots scored clean (2.83–2.95% clipped white in the six safety boots). No extra stutter on a cold Gerudo Valley walk (an earlier reading said 58 vs 11 slow frames; Link was stuck at a cliff). | `research/emulator-options/`, run ab-20261117-224835 (local) |
| 16 | Apply the pipeline's cull mode to mesh draws | `moltenvk/0010-mesh-apply-the-pipeline-s-cull-mode-to-mesh-draws.patch` | ours | #2842's code treats a mesh pipeline as a point list, so its cull mode is never set on the encoder and mesh draws inherit the previous draw's. Speckled frames 27 of 30 → 0 of 30, twice; offline replay of a recorded GPU trace 20 of 20 → 0 of 20; draw-by-draw state check 263 of 653 mesh draws wrong → 0. Warm standing 17.1 / 20.0 / 21.5 ms (p50 / p90 / p95) in the check runs. | `research/mesh-white-specks/`, `tools/statecheck/`, `tools/speckcheck/`, run ab-20261118-000338 (local) |
| 17 | JIT invalidation entry points for the debug tools | `lichii/0007-core-JIT-invalidation-entry-points-for-the-debug-too.patch` | ours | The System-level calls the shared code cache needs, and the debug-server `jit_clear` command. Also carries `EDEN_NX2_JIT_FLUSH_ON_STALL=<ms>`, off unless set (see Tried, CPU and JIT). | `research/shared-jit-cache/`, `tools/harness/` |
| 18 | One A64 code cache shared by the six guest cores | `lichii/0008-dynarmic-arm64-one-A64-code-cache-shared-by-a-proces.patch` | ours: port of Lichii PR #2101 (zortos293, x86-64 only, open) to dynarmic's arm64 backend; offered in Lichii issue #2180 | Without it each core's private 128 MiB cache fills during play and is flushed whole: one frame of 312–960 ms in about half the walks. The port adds 128 MiB regions joined by veneers, lock-free block lookups, fault handling that re-marks only the faulting access without halting all cores, and two review fixes (a core waiting for a full clear honours pause and quit; repeated invalidations no longer halt six cores). Against the same build without it, same MoltenVK, 3 runs each, Kokiri Forest walk with turns: hitched walks 3 of 3 → 0 of 3; walk p95 46.1–51.4 → 28.1–30.1 ms; worst walk frame 312–645 → 51–60 ms; map load 26.1–26.6 → 21.8–23.6 s; memory 23,552 → 20,480 MB; Gerudo Valley walk p90 23.8 → 19.7 ms; standing unchanged. Blocks compiled per load 2.15–2.38 M → 0.60–0.64 M, compile time over six cores 28.4–32.2 → 10.7–11.5 s. 146 dynarmic tests pass; ThreadSanitizer clean. | `research/shared-jit-cache/`, `tools/jit-cache/`, run ab-20261118-014956 (local), run ab-20261118-023158 (local) |
| 19 | Switches line `EDEN_NX2_SHARED_JIT_CACHE=512` | `config/nx2_switches.append.txt` | ours | Turns row 18 on with 512 MiB; a load uses 211–231 MiB. Sizes must be multiples of 128 MiB (129–255 MiB crashed before the rounding fix). Deleting the line goes back to private caches with no rebuild. | `research/shared-jit-cache/` |
| 20 | Launch environment: App Nap opt-out | `config/launch-env.txt` | ours | A normal launch sets `MVK_P60_NO_APPNAP=1`, so macOS does not move a hidden or covered window to the efficiency cores (frame times of 50–60 ms). The upscaler is the game's own network with row 12's multiply. The app had no launch environment before 2026-11-19, although earlier notes said it did. | `config/README.md` |
| 21 | Explicit pipeline cache id | `moltenvk/0011-cmake-MVK_PIPELINE_CACHE_REV-sets-the-pipeline-cache.patch`, `versions.lock` (`MOLTENVK_CACHE_ID`, `MOLTENVK_CACHE_INPUTS`) | ours | MoltenVK stamps `pipelineCacheUUID` with the git commit it was built from, and Lichii discards its stored pipeline file when that changes: the next boot translates and compiles every shader again, 329–334 s (two boots, 2026-11-19) against about 100 s for a cold Metal cache with the file kept. The id now comes from `versions.lock` (`04ac9bef`), and `build.sh` refuses to build when the files that decide generated shader source change without a new id. `build.sh` also applies the series with fixed committer and dates, so the commit ids in `versions.lock` are reproduced exactly. | run ab-20261119-035532, run ab-20261119-041914 (local) |

## Tried and not adopted

### Emulator settings and switches

| What was tried | Result | Verdict | Evidence |
| --- | --- | --- | --- |
| Docked mode | 26.1 / 25.1 / 23.4 ms vs 20.2–21.3 / 20.1–20.6 / 18.9–19.3 ms handheld (about +5 ms) | rejected | `research/emulator-options/` |
| GPU accuracy High | 24.4 / 24.7 / 22.7 ms (3–4 ms slower) | rejected | `research/emulator-options/` |
| Compute write mark Full | 24.9 / 23.7 / 21.0 ms (2–4 ms slower) | rejected | `research/emulator-options/` |
| Mesh shaders Compute (all emulated) | 23.5 / 23.2 / 21.2 ms vs 20.3 / 21.3 / 19.1 ms native; first boot 40 s | rejected | `research/emulator-options/` |
| GPU clock Normal; GPU clock Overclock | Normal 24.6 / 24.3 / 21.1 ms vs 20.5 / 22.1 / 20.0 ms for the default Boost; Overclock 21.0 / 22.3 / 19.5 ms | rejected (Normal); no gain (Overclock) | `research/emulator-options/` |
| GPU fence Balanced; GPU fence Accurate | 22.0 / 22.7 / 20.7 ms and 56.3 / 53.8 / 46.3 ms vs 18.2 / 22.0 / 18.3 ms for Immediate (the default) | rejected | `research/emulator-options/` |
| Fast math never | 40.6 / 44.9 / 39.9 ms (2× slower) | rejected | `research/emulator-options/` |
| Fast math always | 18.6 / 21.6 / 18.1 ms; first boot 177 s while every shader recompiles (an earlier reading said it hangs Apple's compiler) | no gain | `research/emulator-options/` |
| Precache shaders Always | Crashed 72 s in ("Thread stack size exceeded", SPIRV-Cross recursion on a secondary thread); on retry p99 158 ms | rejected; reported as MoltenVK issue #2907 | `research/emulator-options/` |
| Reactive flushing off; `EDEN_NX2_NO_REACTIVE=1` | 17.7 / 22.0 / 17.9 ms and 19.9 / 19.8 / 18.4 ms; fog washed to near-white, colours faded | rejected (renders wrong) | `research/emulator-options/`, not in a write-up; recorded 2026-11-17 |
| GPU thread split `EDEN_NX2_SPLIT=0` and `=1` | 21.6 / 22.3 / 19.9 ms and 22.1 / 22.3 / 20.6 ms vs 18.2 / 21.2 / 18.0 ms for the default mode 2 | rejected | not in a write-up; measured 2026-11-17 |
| No effect, before keep-encoder (bases 20.2–21.3 / 20.1–22.1 / 18.9–20.0 ms): debug-server memory polling 27 times a second, CPU accuracy Accurate, native async draws Wait, Mesh shaders Native (same as Auto), `EDEN_NX2_FORCE_LOD0`, vsync Immediate, `EDEN_NX2_FRAMES_AHEAD=0`, CPU clock Boost | Each within about 1 ms of its batch's base. The "30.9 vs 38.9 fps" note for `EDEN_NX2_FRAMES_AHEAD=0` in `nx2_switches.txt` does not reproduce | no gain | `research/emulator-options/` |
| No effect, after keep-encoder (bases 18.2 / 21.2–22.0 / 18.0–18.3 ms): async draws Skip, pipeline wait 2 ms and 16 ms, frame pacing 60, DMA Unsafe and Safe, sync memory operations, barrier feedback loops off, ASTC on CPU, VRAM Aggressive, async presentation off, async shaders off, vertex input dynamic state off, CPU accuracy Unsafe, `EDEN_NX2_FENCE_BATCH=0`, vsync Mailbox | Standing 17.5–18.6 ms. Five that first read slower had a build running alongside and matched base on rerun; ASTC on CPU first read 0.6–1 ms faster and matched base on rerun | no gain | `research/emulator-options/`, not in a write-up; recorded 2026-11-17 (reruns) |
| `cpuopt_unsafe_*` all off | 18.4 / 23.0 / 18.6 ms; these switches act only at CPU accuracy Debugging, so nothing was applied | inconclusive | not in a write-up; measured 2026-11-17 |
| `EDEN_NX2_MME_JIT=0` | not recorded | inconclusive | not in a write-up; measured 2026-11-17 |
| Not run: force max clocks (Windows driver only), ASTC Uncompressed, buffer history, frame pacing 30, precache Ask (opens a dialog) | – | abandoned | `research/emulator-options/` |
| Resolution 0.75x and 1.25x | 0.75x 17.4 / 21.4 / 18.0 ms warm; 1.25x 19.3 / 22.7 / 19.3 and 19.5 / 22.5 / 18.9 ms; 1x control 20.3 / 20.8 / 18.4 ms. A resolution change rebuilds all 2,739 pipelines (195 s boot) | inconclusive (within noise) | not in a write-up; measured 2026-11-17; run ab-20261117-183738 (local) |
| Resolution 0.25x with post-processing off, on stock | Title screen 60 fps; outdoors still ~28–40 fps. 0.75x on stock: no change | rejected (pixel count is not the limit) | not in a write-up; measured 2026-11-16 |
| Fullscreen instead of windowed | Standing after the walk, p50 / p90 / p95: 17.8 / 20.5 / 21.4 vs 18.4 / 21.2 / 22.0 ms, and 17.9 / 20.0 / 21.3 vs 18.7 / 22.2 / 23.9 ms | inconclusive (0.6–0.8 ms in two pairs); a launch choice, not built in | `research/emulator-options/` |
| GDB stub with lldb attached | Walk 25.0 ms vs ~20–21 ms, standing after the walk 20.9 ms, load +2–5 s; armed breakpoints add nothing more | rejected for timing runs (`use_gdbstub` stays off) | `research/emulator-options/` |
| `EDEN_NX2_FLUSH_DRAWS` 1024 and 4096 (default 128) | Fastest-tenth frame 30.7 and 31.7 ms vs 29.0–30.5 ms at 128 and 31.0 ms control, load average up to 25; the log did not confirm the switch was applied | no gain (unconfirmed) | not in a write-up; measured 2026-11-16 |
| FSR 3.1 in place of the upscaling network (`EDEN_NX2_DLSS_REPLACEMENT=fsr`) | 24.4 ms on the all-in-one (30.6–30.7 ms without); FSR passes cost 2.67 ms | superseded by the shuffle-free multiply (pinned row 12) | `research/allinone-frame-breakdown/` |
| Bilinear stand-in as the default upscaler (`EDEN_NX2_DLSS_REPLACEMENT=fsr` with `P60_OOT_BILINEAR=1`) | 8.0 ms alone on 2026-11-16 (22.0 ms at the time), before the shuffle-free multiply. On the pinned build, three interleaved runs each on 2026-11-19: walking 20.5 / 19.0 / 18.9 ms with it against 19.5 / 19.0 / 19.1 ms without; standing after the walk 16.8 / 16.5 / 16.6 against 16.7 / 16.5 / 16.5 ms; softer picture | no gain; in the build, off (commented out in `config/launch-env.txt`) | `research/path-to-60fps/`; run ab-20261119-043048 (local) |
| `oot_anti_aliasing=1` ("No sharpening") to skip the upscale pass | The pass still runs in handheld mode | no gain | `research/allinone-frame-breakdown/` |
| Fence-flush deferral (500 µs batching) off | 30.4 ms, twice as many command buffers | rejected | `research/path-to-60fps/` |
| Run a frame ahead when the GPU is behind (`P60_RUN_AHEAD`); present outside the command buffer | No change | rejected | `research/path-to-60fps/` |
| Fixed `rng_seed` | Pins `main`'s load address (0x80059000 on both boots); Link's end position identical with or without it; pictures not pixel-identical either way | inconclusive for gameplay randomness; not a default | `research/emulator-options/` |
| `record_frame_times` | Writes nothing when Lichii is stopped with `kill -9` | rejected | `research/emulator-options/` |

### CPU and JIT

| What was tried | Result | Verdict | Evidence |
| --- | --- | --- | --- |
| Flush the JIT cache when no frame is presented for N ms (`EDEN_NX2_JIT_FLUSH_ON_STALL`); manual `jit_clear` | The stall trigger fired once per run, during boot (10.1 s), never after the map load. A manual flush made the walk worse: worst frame 99–126 ms, 11 frames over 50 ms vs 3–6 | superseded by the shared code cache; switch left in, off | `research/emulator-options/` |
| "Light compile": CPU accuracy Debugging with constant propagation, misc IR passes and context elimination off | Boot 17.6 vs 15.5 s, load 47.2 vs 42.2 s, 20.9 / 22.4 / 20.2 vs 20.3 / 20.8 / 18.4 ms against Debugging with them on | rejected | not in a write-up; measured 2026-11-17; run ab-20261117-183738 (local) |
| Faster JIT compiles to shorten map loads | The busiest core compiles for 3.3 s of a 19.8 s map load, so a free JIT saves at most ~3 s (an earlier reading said the JIT was about half of the load) | abandoned | `research/emulator-options/` |
| Shared code cache at 1 GiB | 231 MiB used; load 51.3 s vs 45.7–45.8 s at 512 MiB (one run, before the fault-handling change) | rejected | not in a write-up; measured 2026-11-17 |
| Shared cache with the old fault handling (every fastmem fault halts all six cores) | Save load 23.6–24.2 s vs 18.1–18.9 s with private caches; 386–527 k fault-driven recompiles per load | superseded by the fault handling in pinned row 18 | not in a write-up; measured 2026-11-18 |
| First fault-handling change: drop a block only if its code is still current | 745 k (private) and 594 k (shared) faults in already replaced code, because the other faulting accesses of a block were not re-marked | rejected; superseded by pinned row 18 | `research/shared-jit-cache/` |
| Larger or two-way per-core lookup table | Lookup hit rate already 98.4% (private) and 99.0% (shared) | abandoned | not in a write-up; measured 2026-11-18 |
| Native code execution (NCE) on macOS | Blocked by `__PAGEZERO` at the game's addresses, `MAP_JIT` write-or-execute rules and Mac fault handling | abandoned | not in a write-up; measured 2026-11-17 |

### MoltenVK and shader compilation

| What was tried | Result | Verdict | Evidence |
| --- | --- | --- | --- |
| Parallel pipeline-cache load in MoltenVK (`dispatch_apply`), ours | Cold boot 89.5 s; first boot on a filled cache 71.5 s; one run had 21% of the picture blown out white, silent in the logs | rejected (a race in concurrent compiles is suspected, not found) | `research/emulator-options/`, `tools/harness/` (patch) |
| MoltenVK PR #2905, alone and with the parallel load | With the parallel load: cold boot 76.7 s, first boot 20.8 s, one run 44% blown out white. Alone: first boots 25.0 and 34.2 s, slow because a build ran alongside | rejected | `research/emulator-options/` |
| `MVK_CONFIG_SHOULD_MAXIMIZE_CONCURRENT_COMPILATION` with the parallel load | 88.7 s vs 89.5 s cold boot | no gain | `research/emulator-options/` |
| Boot progress log in MoltenVK's pipeline-cache load | Made the next boot of each app cold (206 s); the percentage stayed at 0% | superseded by PR #2901 (pinned row 15) | `research/emulator-options/` |
| MoltenVK issue #2863's pipeline-cache lock patch (the lock is held across translation and the Metal compile, so the front end is serial) | not recorded | inconclusive | not in a write-up; measured 2026-11-16 |
| Raising Metal's shader cache size (`MTL_SHADER_CACHE_SIZE`, `FS_CACHE_SIZE`) | Metal clamps anything above 1 GiB (default 0x40000000; zero disables); the same code is in a public decompile of iOS 26.1 | rejected (closed option) | `wip/shader-prebuild/` |
| Metal binary archives for cold boots | They skip pipeline builds, not the source-to-library compile; the scale probe was stopped before any result | rejected for boots; probe abandoned | `wip/shader-prebuild/` |
| Compile options on one real shader pair (`MTLCompileOptions` sweep, math modes, concurrency) | Metal is 96.9% of ~559 ms (SPIRV-Cross 2.6%, Lichii's recompiler 0.5%); no option moves the time more than ~8%; 8 pairs compile at once in barely more time than one | no gain | not in a write-up; measured 2026-11-16 |
| `spirv-opt -O` before SPIRV-Cross | Library 275 → 212 ms, pipeline 225 → 140 ms, but `spirv-opt` itself takes ~240 ms as a separate process | inconclusive | not in a write-up; measured 2026-11-16 |
| Pipeline variants as the cause of compile cost | 2,231 pipelines for 330 fragment programs; 1,053 differ only in a provoking-vertex key bit; only blend or colour-format changes cost a second full compile (~200 ms), ~7–9% of programs | rejected | not in a write-up; measured 2026-11-16 |
| Other shader front ends: Metal Shader Converter through DXIL, `dxc`, DXMT | None is a drop-in; bindings and per-pipeline conversion would not line up | abandoned (not tried) | not in a write-up; measured 2026-11-16 |

### Shaders and translation

| What was tried | Result | Verdict | Evidence |
| --- | --- | --- | --- |
| Remove `[[clang::optnone]]` from SPIRV-Cross's float helpers by text rewrite | Warm 31.3 and 32.4 ms vs 43.7 ms; 1 and 22 of 528 picture tiles differ, all moving objects | superseded by SPIRV-Cross PR #2721 (pinned row 10) | `research/mac-performance/` |
| Invariant positions with `preserveInvariance` (`MVK_DIAG_INVARIANT=1`) against broken native foliage | No change | rejected | `research/mac-performance/` |
| Task-to-mesh payload pairing; group count, group index, skipped indirect mesh draws | Metal accepts any payload mismatch and the pairing is consistent; the rest is the same on both paths, the skip warning appears 0 times | rejected as causes | `research/mac-performance/` |
| Marker shaders (grass mesh shader replaced by fixed magenta triangles) | Draws issued, no magenta: an equal-depth colour pass hides fixed triangles | inconclusive by design | not in a write-up; measured 2026-11-16 |
| Metal API and shader validation | ~38,700 messages, none in mesh stages; shader validation found only 3 "INF or NAN detected in interpolant"; frames 4–6× slower (~250 ms). Full shader validation crashes in `MTLToolsResidencySet` unless `MTL_SHADER_VALIDATION_RESOURCE_USAGE=0`. 328 "texture freed while a command buffer still needed it" messages were never checked against a control run | rejected as an explanation | `research/metal-validation/` |
| White-speck causes other than cull mode: uninitialised threadgroup memory, a shared counter buffer, pacing, buffer write tracking, SIMD operations, group numbering; 14 switches toggled one at a time; Hypervisor, LTO binary, synchronous GPU, buffer downloads, read traps off, GPU accuracy High | 24–30 of 30 frames speckled in every case | rejected | `research/mesh-white-specks/` |
| Translation artefacts in cached fragment shaders, timed offline | Flattening branches is 4–6% slower; `fma` wrappers, precise min/max, xor sign flips and layer round-trips cost nothing measurable; quad emulation 3–8% on one shader, noise on five others; 8 overlapping opaque draws cost the same as 1 | no gain | `wip/shader-metal-analysis/` |
| Fast math per shader, offline | 8–10% faster as generated, 5–27% on five other shaders; up to 5% of pixels change, by at most 0.05% | no gain in game (see fast math always) | `wip/shader-metal-analysis/` |
| Skipping uniform-register copies | 645 copies in 154 of 631 programs; fully skippable in only 10 programs | rejected (too small) | `wip/shader-metal-analysis/` |
| A more accurate `exp2` / `log2` | All Metal variants return identical bits; exp2 100% within 1 ulp, log2 99.95% (worst 3 ulp) | no gain (no better built-in) | `wip/shader-metal-analysis/` |
| Translation mismatches found by static scans: denormal mode, MSAA centroid, round-toward-zero | The game asks for flush-to-zero everywhere, as Apple does; all 2,493 cached pipelines have MSAA off, so the 546 dropped centroid flags do nothing; 15,792 multiplies carry a round-toward-zero mode the SPIR-V backend ignores, no visible effect found | no action | `wip/shader-metal-analysis/` |

### Compilers and build flags

All against the pinned build's compiler setup (Apple clang 21, `-O3`, no LTO), same MoltenVK.

| What was tried | Result | Verdict | Evidence |
| --- | --- | --- | --- |
| Apple clang ThinLTO with `-mcpu=apple-m4` | Final pair: standing 19.1 and 18.9 ms vs 19.1 and 18.9 ms for the default build, load average 11–16 (an earlier reading gave ThinLTO 0.7 ms, 2.7 s of load and 5% of JIT time) | no gain | `research/emulator-options/` |
| Homebrew LLVM 23.1.5 at `-O3`; LLVM with LTO | LLVM alone 17.7 and 18.6 ms vs 18.1 and 18.3 ms; LLVM with LTO 20.2 and 18.0 ms in the final pair | no gain | `research/emulator-options/` |
| Apple ThinLTO with PGO trained on one Kokiri Forest route | Standing 16.4 vs 18.2 ms, then 17.4 vs 17.2 ms (PGO vs default); walk 19.4 vs 18.1 ms, then 17.7 vs 17.8 ms | rejected (pairs point opposite ways) | `research/emulator-options/` |
| Not run: `-mcpu` alone, PGO without LTO, full LTO, context-sensitive PGO, LLVM PGO | – | abandoned | `research/emulator-options/` |

### Hypervisor backend

Lichii PR #1970's backend (`cpu_backend = Hvf`) runs the game's ARM code in a virtual machine instead of the JIT. It
is compiled into the pinned build and not used.

| What was tried | Result | Verdict | Evidence |
| --- | --- | --- | --- |
| Backend as shipped in #1970, against the JIT with private caches | Spawn 21.7 s vs ~42 s; 23.7–25.0 / 25.2–25.3 / 23.2–23.3 ms (+3–5 ms); ~385,000 exits a second on stores to GPU-cached pages; picture wrong | superseded by the fixed build below (an earlier reading closed the backend as slower and broken) | `research/emulator-options/`, run ab-20261117-160732 (local) |
| Patching the game's timer reads | The SDK hard-codes 31.25 MHz at 45 counter-read sites and never reads the frequency register; an untrapped counter froze the game; timer exits cost only ~0.5 ms | rejected | `research/emulator-options/` |
| Differential test of the store interpreter against the Mac CPU | 1.26 M comparable instructions, 0 mismatches (acquire/release loads and stores ~50, literal loads 0) | interpreter cleared | not in a write-up; measured 2026-11-17 |
| Render race fix: mark a page as GPU-cached before protecting it | A protected-but-unmarked page was made writable as leftover protection: 25 hits in ~2.5 min → 0 | not adopted (backend not adopted); see Open | run ab-20261117-203916 (local) |
| Fixed backend with the loop runner, burst and dirty-only speed patches, against the JIT with private caches | Two runs each, load average 7–11: walk 17.5 / 18.0 ms vs 22.9 / 21.8 ms; standing 16.7 / 16.7 ms vs 18.9 / 18.2 ms; worst frame 34 / 27 ms vs 653 / 452 ms; spawn 20 s vs 44 s; ~120,000 exits a second. Loop runner off: walk 23.4 / 23.9 ms; loop limit 64–4096: 17.4–17.8 ms; burst 32: 17.8 / 17.3 ms; dirty-only off: 17.5 / 17.4 ms | inconclusive; not adopted because of the corruption below | not in a write-up; measured 2026-11-18; run ab-20261118-000958 (local) |
| Picture check of the fixed backend | Hypervisor after the MoltenVK swap: 2 of 26 Kokiri Forest pictures corrupt (rainbow shards; 30% clipped white); JIT 0 of 15; Hypervisor before the swap 0 of 9. The JIT half of a 10 + 10 boot check stopped after 1 boot | inconclusive (~1 boot in 12, silent in the logs); see Open | run ab-20261118-002819 (local) |
| Lichii issues #1380 and #1381 as the cause | All write faults were interpreted and none fell back to invalidation, so #1380's race is not it; 1,500–10,000 read faults a second reopen cached pages, which points at #1381's read-trap window | inconclusive; see Open | not in a write-up; measured 2026-11-17 |
| Long walks (3,600 frames) and 5-minute walks, Hypervisor vs JIT | 3 of 4 long walks finished, no table; the 5-minute walks never ran | abandoned | not in a write-up; measured 2026-11-17 |
| One guest CPU core | 11% speed | rejected as a test | not in a write-up; measured 2026-11-17 |

### Other

| What was tried | Result | Verdict | Evidence |
| --- | --- | --- | --- |
| KosmicKrisp (Mesa's Vulkan on Metal) instead of MoltenVK | Vulkan 1.4, macOS 26+, push descriptors, but no `VK_EXT_mesh_shader`; a trial with mesh shaders emulated was never run | abandoned | `research/moltenvk-offramp/` |
| nxnative (runs the game's ARM code natively, NVN to Metal) | Read-only evaluation at `edc7eff9`: needs macOS 26.6 and Xcode 27.2 (~60 GB); its 60 fps is one Kokiri route on an M5 Pro, 48–59 fps on an M4 Pro; cannot load sloperinaGZ, no frame advance, no save states | rejected for now | `research/nxnative/` |
| Techniques from N64 ports (Ship of Harkinian, RT64) | They are ports of the N64 game, not of this remake | rejected (does not apply) | not in a write-up; measured 2026-11-16 |
| GDB stub for live measurements | One client only; per-frame breakpoints drop the game to ~1 fps; with the stub on, 2 of 5 save loads crashed | superseded by memory reads through the debug server (`tools/harness/`) | not in a write-up; measured 2026-11-16 |
| Apple's `metalperftrace listen` for frame profiling | Two runs hung with it attached | abandoned; replaced by the MoltenVK frame profiler (pinned row 11) | not in a write-up; measured 2026-11-16 |
| Several variants in one boot (switch file polled, Link reset with sloperinaGZ between variants) | The position reset failed twice (Link 16.3 m off) | rejected (unreliable) | not in a write-up; measured 2026-11-17 |
| Screenshot-burst metric for a grass "flicker" at the spawn | The fault is a thin wrong fog layer over the grey grass, not flashes; frame differences cannot show it | abandoned | not in a write-up; measured 2026-11-17 |

## Open: worth doing

Ordered by expected value.

| Idea | Why it might help | What exists already | First step |
| --- | --- | --- | --- |
| Re-measure against current Lichii | Every comparison is against stock build 228 (2026-11-15); Lichii is at build 341 as of 2026-11-19. Lichii `nx2` of 2026-11-16 was 7 ms slower than 228 with the same old MoltenVK (46.4 vs 39.5 ms), never explained. PR #2022 has since merged and #1970's head has moved | `tools/harness/` and its default spec; stock 228 for reference | Time stock build 341 at the test spot, then rebase both patch series on its `nx2` commit and time again |
| Hypervisor backend | The fixed backend walked at 17.5–18.0 ms vs 21.8–22.9 ms for the JIT with private caches, worst frame 27–34 vs 452–653 ms, spawn 20 vs 44 s (load average 7–11). The pinned build's shared cache has since narrowed the JIT's walk (p95 28.1–30.1 ms) | The race fix and first patches are in commit `97efae6` of the research repository, which no branch holds (a `git gc` will drop it). The final patch (re-protect after the fault handler restores permissions, speed patches on by default) survives only as a generator script in local editor history. Its binary predates the shared cache and was never booted. A read-path fix, `EDEN_NX2_HVF_INTERPRET_READS=1`, was written and never booted | In order: (0) pin `97efae6` and regenerate the final patch on the current tree; (1) count GPU writes into pages that `GrantCachedPageRead` opened (zero in every boot rules the read-path explanation out); (2) same spot, pictures compared: Hypervisor as before, JIT with `EDEN_NX2_NO_REACTIVE=1` (known bad), Hypervisor with `EDEN_NX2_HVF_INTERPRET_READS=1`; (3) cost of interpreting every read, 6 boots with exit stats; (4) 30 boots of the fixed build, every picture scored; (5) rule out the shared MoltenVK and the loop runner's add/compare/branch emulation (only loads and stores were tested against the CPU), and finish the 10 JIT boots; (6) 5-minute walks in Kokiri Forest and Gerudo Valley against the pinned build; (7) ThinLTO Hypervisor against the pinned build, other maps including a map change; (8) repeat on an idle machine |
| Send the shared JIT cache port upstream | Upstream's shared cache (#2101) is x86-64 only; issue #2180 got a reply asking for a draft diff against #2101's head `72ff982a3` | A patch for that tree with tests (`tools/jit-cache/`); pinned row 18 | Check that the patch for the #2101 tree carries both review fixes, then open a draft PR against #2101's branch |
| Send the mesh cull-mode fix upstream | Every user of #2842's MoltenVK code gets the inherited cull mode | `moltenvk/0010-mesh-apply-the-pipeline-s-cull-mode-to-mesh-draws.patch` (~50 lines); state-check and replay evidence | Post the patch on #2842, or as a PR on dttdrv's branch |
| Per-core emit regions in the shared JIT cache | After lock-free lookups, ~10 s per load still go to waiting: emit 4.6–4.8 s, fault handler 5.3 s. Offline replay at full speed: shared 14.2 s vs private 5.1 s of wall time, 41.1 s waiting to emit | JIT operation recorder and offline replay (`DYNARMIC_JIT_TRACE`, `DYNARMIC_JIT_REPLAY`); boot, load and walk traces kept locally; the paced replay mode (`DYNARMIC_JIT_REPLAY_SPEED`) never run on a real trace | Prototype on the replay and compare emit waiting, then a save-load A/B in the emulator |
| CPU-to-GPU hand-off | GPU work is 15.5–16.4 ms but standing frames are 17–19 ms. Located: a ~2 ms gap after the end-of-frame flush (up to 1.7 ms), downloads of GPU-written buffers that could happen only when needed (up to 1.0 ms), occlusion queries that could accumulate once per command buffer (up to 0.5 ms). The cause of the GPU idle is not settled: one write-up says not found, another says semaphore waits between the game's GPU channels | Frame profiler (pinned row 11), `P60_SYNC_TRACE` | Profile the pinned build with `MVK_FRAMEPROF` and `P60_SYNC_TRACE` to settle the idle cause |
| Prebuilt shaders | First-visit compile work 175.6 → 7.3 s and long-frame time 56.6 → 10.4 s on a held-out save load with a small predicted file. Area loads drop to ~1 fps and first visits show purple slabs while ~260 shaders compile | `wip/shader-prebuild/`: Lichii PR #1366 plus 4 Mac changes (taken into the PR), a builder, a trimmed file of 42,629 records not yet tested, two `-v2` files not checked. The full 311,091-pipeline file overflows Metal's 1 GiB cache. Larger routes: binary archives (~7 days), material decoder (3–5 days), fly-through tour (3–4 days) | Check the two `-v2` files with `nx2-precompile` (needs a ~1 h rebuild), then test the trimmed file |
| Mip-gradient fix in Lichii's shader recompiler | 4,723 of 13,682 automatic-mip samples in 625 of 850 fragment programs sit under a per-pixel condition, where Metal can pick the wrong mip. Offline prototype on a cached shader: 12,384 wrong pixels (~9 levels off) → 0, 0.331 ms vs 0.333 ms | Offline proof; design: an IR pass after `SsaRewritePass` and `ConstantPropagationPass`, before `TexturePass` in `translate_program.cpp`, fragment programs only, taking `DPdxFine`/`DPdyFine` of the coordinates in the nearest always-executed block and sampling with `ImageGradient`. Open points: coordinates computed inside the branch, samples with a bias, texture types | Look for the mip fringe in a running scene that uses one of the 625 programs, before and after frames |
| Remember faulting accesses across boots | ~310 k fastmem recompiles per load | Nothing built; needs module-relative offsets (`main` moves every boot) | Dump the set at the end of a load on 2–3 boots and diff |
| Send `maxPushDescriptors` 16 upstream | One line that fixes canopy and 5 compute pipelines on upstream MoltenVK | Standalone Vulkan repro in `research/compute-buffer-bounds/` | MoltenVK merges nothing since its deprecation notice (needs a Khronos CLA); offer it to the fork Lichii ships, or cap Lichii's own push-descriptor use |
| Send list-indirect and 8-bit index widening upstream | 1.2 ms and 1.3 ms a frame on MoltenVK | Pinned row 12 | Split both out of `lichii/0006-…` as a Lichii PR |
| Send the shuffle-free upscaler multiply upstream | 7.8 → 2.4–2.6 ms for the upscale pass, bit-identical; may help any host without Nvidia tensor units | Pinned row 12, offline bit-exact harness in `tools/perf/` | Clean up (estimated 1–2 days), then a Lichii PR |
| Send keep-encoder upstream | 2–2.5 ms a frame | Pinned rows 13–14; reviewed locally, picture watched at one spot | Check the picture at other areas first |
| Report on #2901 and #2905 | #2901: 14 of 14 clean boots, cold boot 5–6× faster. #2905 corrupted the picture in concurrent compiles | Data in `research/emulator-options/` | Post a test report on #2901 and a warning on #2905 |
| Other areas and docked mode | Only Kokiri Forest (and two Gerudo Valley walks) is measured; docked picture never looked at; open sightings: Hyrule Field white tufts while "Building: 554 shader(s)", Gerudo Valley water streaks, a thin wrong fog layer over the grey grass at the spawn | `tools/statecheck/` (one trace at the cave wall), `tools/harness/` | Record a state-check trace at another save; walk Hyrule Field with the building-shader count logged |
| Direct binding instead of argument buffers | 5–8% faster per shader offline, bit-identical; fits 742 of 944 fragment shaders | Offline measurement in `wip/shader-metal-analysis/` | Prototype in MoltenVK for one pipeline and time it in game |
| Make the 10 oversized mesh shaders native | They run emulated today; native mesh shaders showed no clear speed gain, so the value is low | Hand-edited Metal source builds for the 4 reached programs; after Lichii writes outputs directly (~1 week) the worst would need 30,220 / 58,380 bytes against 32,768 / 61,440 | Build one hand-edited shader in through a hash-keyed replacement and draw it |
| Find the race in concurrent shader compiles | Worth ~2 s of first boot over #2901 | Patches for the parallel load and #2905 (`tools/harness/`) | Replay a cold boot with Metal validation on one compile thread vs many |
| KosmicKrisp trial with mesh shaders emulated | MoltenVK is deprecated (2026-10-13) | Survey in `research/moltenvk-offramp/` | Point Lichii at Homebrew `mesa` 26.3.0's driver and boot |
| Find the cause of a blown-out picture on the JIT build | One run of the previously installed build on 2026-11-19 was white and pink over the whole scene (58.7% clipped pixels against a normal 2.9–3.3%) with normal frame times; the machine was under heavy load from a build. The 20 other runs that day and 58 earlier scored runs of the JIT builds were clean. The same symptom is the open Hypervisor fault and the reason concurrent shader compiles were rejected | the run folder with both pictures: run ab-20261119-035532, `proof-gold-warmup` (local) | Repeat boots under a heavy background build with picture scoring on; if it recurs, record a GPU trace of a bad frame |

## Upstream

States as of 2026-11-19 where checked live that day; others as last seen.

| Number | Author | Title | State on 2026-11-19 | How the pinned build relates |
| --- | --- | --- | --- | --- |
| Lichii PR #1970 | HyperCed | Better MacOS Support with Hypervisor | open (head now `b697762630`) | included at `1f76c9ff56` (`lichii/0001`), with our demotion rule (`lichii/0002`); we commented three times |
| Lichii PR #2022 | RomainROCH | vulkan: skip failed mesh pipelines when seeding vertex-input lenders | merged 2026-11-17 | included at `f1f0dcc13a` (`lichii/0003`) |
| Lichii PR #1902 | Terobyte | buffer_cache: skip native uniform bank re-uploads whose bytes did not change | open | included at `c7e22dabc9` (`lichii/0004`) |
| Lichii PRs #2012, #1868, #1860, #1991, #1953, #1862 | not recorded | not recorded | merged | included through the base `8c0558a3d3` |
| Lichii PR #2101 | zortos293 | dynarmic: one x64 A64 code cache shared by a process's cores (port of Tasa's series) | open | ported to arm64 as `lichii/0008` |
| Lichii issue #2180 | SokolskyNikita | Shared JIT code cache for the arm64 backend (port of #2101): offering a PR | open, 2 bot replies | we opened it |
| Lichii PR #1366 | auz466 | shader: Precompiled pipelines built from the player's own play | open | tested with 4 Mac changes, not in the build; we commented, the changes were taken into the PR |
| Lichii PR #1944 | dzervas | not recorded (a direct NVN renderer, draft) | not checked | surveyed only |
| Lichii PR #1367; issues #1380, #1381 | not recorded | not recorded (#1380: Hypervisor shared page tables; #1381: read-trap window in `memory.cpp`) | open on 2026-11-17, not rechecked | read as Hypervisor leads; nothing reported |
| Lichii issue #237 | not recorded | not recorded (shader-compile stutter) | closed | background only |
| MoltenVK PR #2842 | dttdrv | Add VK_EXT_mesh_shader support | open | included at `c516eb42` (`moltenvk/0001`); we commented twice (test report with the missing subgroup stages, 2026-11-16; the cull-mode fault, 2026-11-18, patch not posted). dttdrv replied that mesh and task now report subgroup support |
| MoltenVK PR #2843 | dttdrv | Use specialization constant values for array sizes in shader interfaces | open | included at `cae05219` (`moltenvk/0002`) |
| MoltenVK PR #2897 | paulpan05 | Batch indirect-count draw conversions into one compute pass | open | included at `f2594b14` (`moltenvk/0005`) |
| MoltenVK PR #2901 | frankea | Compile pipeline cache shader libraries when they are first used | open | included (`moltenvk/0009`); tested, nothing posted |
| MoltenVK PR #2905 | Rai-Aarav | Allow threads sharing a pipeline cache to compile shaders concurrently | open | tested and rejected (picture corruption); nothing posted |
| MoltenVK issue #2907 | SokolskyNikita | Stack overflow in SPIRV-Cross `CFG::walk_from` on a secondary thread on macOS | open | we opened it (Precache shaders Always crash) |
| MoltenVK issue #2863 | not recorded | not recorded (pipeline-cache lock held across shader compiles) | open on 2026-11-16, not rechecked | read; its patch not applied |
| MoltenVK #2874 | not recorded | not recorded (deprecation notice) | merged 2026-10-13 | why MoltenVK items go to comments or forks |
| MoltenVK #2426 | not recorded | not recorded (push-descriptor limit) | closed as intended behaviour | background for `moltenvk/0002`'s limit |
| MoltenVK #1765 | not recorded | not recorded | not checked | we commented (shader prebuild) |
| SPIRV-Cross PR #2721 | tksuoran | MSL: Inline precise arithmetic helpers on MSL 3.2 | merged 2026-10-28 | included through the `98cbb7c0` pin (`moltenvk/0005`) |
| SPIRV-Cross PR #2686 | dttdrv | MSL: Fix several mesh and task shader issues | merged 2026-10-28 | included (`moltenvk/0003`, and in `98cbb7c0`) |
| SPIRV-Cross issue #2717 | nftmago | MSL: flip_vert_y skips mesh positions declared as standalone BuiltIn Position outputs | open | worked around by a text rewrite in `moltenvk/0005`; we commented (repro on this game, plus the missing depth fixup) |
| Mesa #14251; #16316, #16317; MR !44786 | not recorded | not recorded (KosmicKrisp mesh-shader wish list; Metal mesh shaders inside the driver; geometry shaders) | !44786 merged 2026-10-29; others not rechecked | surveyed only |
| llvm-project #210313 | not recorded | not recorded (all Apple CPU targets share one scheduling model) | not checked | why `-mcpu=apple-m4` was expected to give ~0% |

## Measurement rules

- A MoltenVK library built from a different git commit is a different pipeline-cache identity unless
  `MVK_PIPELINE_CACHE_REV` pins it: the next boot of any app that carries it translates every shader again (about
  330 s), and so does the boot after switching back. Compare apps that carry the same library file, and never launch
  an old build "just to check".
- Keep the emulator window visible or set `MVK_P60_NO_APPNAP=1`: with the window hidden macOS can move Lichii to the
  efficiency cores, giving 50–60 ms frames with the same GPU work (5 of 9 runs in one series).
- Do not compare across a change of `libMoltenVK`: any different binary, even the same source with one log line, or
  a changed compile option, makes the next boot recompile every shader; judge a build on its second boot.
- Use one Vulkan pipeline cache per build: MoltenVK stores translated Metal source in it, so a new SPIRV-Cross never
  runs against a warm cache (one early A/B compared old shaders with old shaders).
- Do not let two builds share Lichii's shader cache: it grows duplicates keyed on MoltenVK capability bits and is
  the suspected cause of one-off canopy shards.
- Compare boots back to back on one build: with ~8 MoltenVK variants Metal's cache reached 2.4 GB, evicts at ~1.1 GB
  per file, and "warm" boots came back at 30–65 s.
- Group runs per Lichii binary with a discarded warm-up: alternating binaries forces cold boots (~70 s vs ~17 s).
- Check that nothing else runs: another build adds 3–5 ms a frame, another process's cold Metal compiles doubled
  frame times, and a load average of 59 gave 78–98 ms against ~38 ms. Log the load average and build with
  `nice -n 19 … -j 6`.
- Quote map load (load − boot) or save load, not the harness "load", which counts from launch and includes boot.
- Without the shared JIT cache the walk hitch is a coin flip (about half the runs): compare walk p90, p95, p99, max
  or mean only within hitched or within clean runs.
- Settle nothing under ~1.5 ms with a single run: noise is ±0.5–1 ms and the two standing phases of one run differed
  by 2 ms.
- Look at the pictures: frame times and logs never show a broken picture; three breakages were found only by eye
  and one sat unnoticed for 3.5 hours. Score screenshots (clipped-white share) on every run.
- Judge specks by 30-frame bursts taken with Link stopped within 1 m of the spot, never by one frame; the debug
  server's own screenshot comes out clean 1–6 times in 30, so use window captures, and count only frames with
  "Building: 0 shader(s)".
- Treat a null result as "maybe not applied" until the log shows the switch took effect: `cpuopt_*` act only at
  CPU accuracy Debugging, `force_max_clock` only on a Windows driver.
- Remember what the tools cost: trace switches add 2–3 ms, a recording GPU trace 54 ms, an attached debugger ~4 ms
  walking; `sample` pauses the process and `metalperftrace listen` hung two runs.
- Use per-frame times, not the fps readout, which freezes in background captures.
- Expect a cold first boot after a resolution change: it rebuilds every pipeline (2,739 pipelines, 195 s).
- Read offline shader timings as relative only: they use synthetic inputs, and two sessions sharing the GPU add
  10–25% rep-to-rep noise, so interleave, swap the order and measure A/A noise.
- Keep the saved original of a library: rebuilding untouched MoltenVK source does not give the same bytes.
- Stop Lichii with `kill -9` and never run its binary with `--version` or `--help`: quitting rewrites
  `qt-config.ini`, and starting the binary opens the GUI and rotates the log.
- Do not blame a build for one guest crash ("jump to address 0" or an unmapped address around a load): it appears at
  random on every build.
