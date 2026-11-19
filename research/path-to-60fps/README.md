# Path to 60 fps: Ocarina of Time (1.1.1) in Lichii on the M4 Pro

**Answer.** 60 fps (16.7 ms) is not reached. On 2026-11-16 the fastest build measured ran the Kokiri Forest spawn
at **18.6–19.1 ms standing (about 53 fps)** with the game's own upscaling network, using a shuffle-free tensor
multiply in place of the emulated one, against 28.7–30.9 ms for the all-in-one build and 39.5 ms for stock release
228. A variant with a bilinear stand-in for the upscale pass measured **19.2–19.4 ms standing and 20.0–20.8 ms
walking**, with a softer picture that is not the game's. In that build the GPU works **15.5 ms** per frame, which is
under the 16.7 ms budget; the frame is longer because the GPU waits **3.9 ms** per frame for the CPU side to hand it
commands. That hand-off is the blocker, not GPU throughput. Two attempts to shorten it changed nothing; what is left
to try is in the to-do list.

The pinned build in this repository carries the shuffle-free multiply, 8-bit index widening, list-indirect and
keep-encoder, all on by default; the bilinear stand-in is in the build and off unless `P60_OOT_BILINEAR=1` and
`EDEN_NX2_DLSS_REPLACEMENT=fsr` are set. Later changes and the pinned build's own numbers are in
[mac-performance](../mac-performance/README.md).

Measured on an Apple M4 Pro (Mac16,8) under macOS 27.0.1, on 2026-11-16, at the Kokiri Forest spawn, 1x, handheld,
with the verify harness ([`tools/verify`](../../tools/verify/README.md)). "All-in-one" is the first combined build
(Lichii patches 0001–0005, MoltenVK patches 0001–0005 under [`patches/`](../../patches/)). Run labels such as
`p60-a1` or `f-bil-0` name local run folders, which are not tracked. Each number is marked **measured** (with its
run label) or **inferred**. The code is `patches/lichii/0005-…` and `patches/moltenvk/0007-…` (see "The patches");
the scripts are in [`tools/perf`](../../tools/perf/README.md). `P60_*` and `MVK_P60_*` are the environment switches
these patches add.

## Waterfall

Standing-phase median frame time, 1,050 frames per run, from the verify hook's frame clock. "Alone" rows change one
thing against the all-in-one. Savings do not add up: once the GPU is no longer the limit, GPU savings stop turning
into frame time.

| Step | Frame (ms) | Saving | Runs | Picture | Where |
| --- | ---: | ---: | --- | --- | --- |
| Stock release 228 | 39.5 | | the stock runs in [mac-performance](../mac-performance/README.md), not re-measured here | game's | |
| All-in-one build | 28.7–30.9 | about 10 | `p60-a1/a2` 30.9, 28.7; the all-in-one rebuilt with this page's switches, all off: `p60-b1` 28.9, `r6-base-1/2` 30.0, 30.2, `f-base-1/2` 28.7, 29.8 | game's | existing build |
| FSR 3.1 replacement (alone) | 24.6–24.8 | 5.2 | `p60-f1/f2` | temporal upscale, not the game's | setting `EDEN_NX2_DLSS_REPLACEMENT=fsr` |
| **Bilinear stand-in (alone)** | **22.0** | **8.0** | `r3-bil-1` | game's scene scaled bilinearly: softer, no network smoothing or sharpening | Lichii (`P60_OOT_BILINEAR`) |
| Keep Metal encoders open across barriers (alone) | 27.5 | 2.5 | `r6-ke-1` (without the App Nap opt-out, `r3-ke-1`: 28.0) | identical (same commands, same order) | MoltenVK (`MVK_P60_KEEP_ENCODER`) |
| Widen 8-bit indices on the CPU (alone) | 28.7 | 1.3 | `r6-u8-1` | identical | Lichii (`P60_UINT8_HOST`) |
| Enable list-indirect on MoltenVK (alone) | 28.8 | 1.2 | `r6-li-1` | identical in the spawn screenshots | Lichii (`P60_LIST_INDIRECT`) |
| Fence flushes not held back 500 µs (alone) | 30.4 | 0 | `r6-ff0-1` | | setting `EDEN_NX2_FENCE_FLUSH_US=0`; not used |
| **Bilinear + the three overhead fixes** | **19.2–19.4** | 2.7 on top of bilinear | `r6-nbil-1` 19.3, `r7-nbil-tr` 19.4, `f-bil-0` 19.2, `f-bil-1` 19.4 | as bilinear | all of the above |
| …plus run a frame ahead when the GPU is behind | 19.1 | 0.2 (noise) | `r8-ahead-1` | | Lichii (`P60_RUN_AHEAD`); not used |
| …plus present outside the command buffer | 19.2 | 0.1 (noise) | `r8-pwcb0-1` | | setting `MVK_CONFIG_PRESENT_WITH_COMMAND_BUFFER=0`; not used |
| Shuffle-free tensor multiply (alone), game's image | 24.2–24.3 | 5.7 | `r5-hm-4`, `r6-hm-1` | bit-identical to the game's (see below) | Lichii recompiler (`P60_HMMA_MEM`) |
| Shuffle-free multiply + the three overhead fixes | 18.6–19.1 | | `r6-allhm-1` 18.6 (with the flush setting), `f-hm-0` 19.1 | game's | in the pinned build |

Whole route (measured, medians):

| Build | Standing | Walk 1 | Walk 2 | Runs |
| --- | ---: | ---: | ---: | --- |
| All-in-one (rebuilt, switches off) | 28.7, 29.8 | 29.2, 30.0 | 30.0 | `f-base-1`, `f-base-2` (stopped during walk 1) |
| Bilinear + overhead fixes | 19.2, 19.4 | 20.8, 20.6 | 20.4, 20.0 | `f-bil-0`, `f-bil-1` |
| Shuffle-free multiply + overhead fixes | 19.1 | 19.7 | 20.0 | `f-hm-0` |

Two full-route runs of the bilinear build and two of the base were made, plus the standing runs above, rather than
the usual four per build. The run-to-run spread of the runs with the App Nap opt-out is about ±0.2 ms for the
bilinear build and ±0.8 ms for the base. Walk 1 has 4–9 frames over 70 ms in every build (first use of pipelines on
the route).

## The patches and what each saves

| Patch | Switch | What it does | Saving alone | Status |
| --- | --- | --- | ---: | --- |
| Bilinear stand-in for the handheld 3/4 upscale pass | `EDEN_NX2_DLSS_REPLACEMENT=fsr` + `P60_OOT_BILINEAR=1` | Reuses Lichii's upscale-replacement hook, but writes a bilinear scale of the game's tonemapped image: no jitter, no history, no FSR passes, no actor mesh read | 8.0 ms (FSR: 5.2) | works; changes the image; in the pinned build, off unless set |
| Keep encoder across barriers | `MVK_P60_KEEP_ENCODER=1` | MoltenVK ended the current Metal encoder at every `vkCmdPipelineBarrier` outside a render pass. Blit and plain compute encoders now stay open; the encoder waits on the other stages' fences and its own stage's barrier is set when it ends | 2.5 ms; encoders 1,073 → 701 per frame | fence logic reviewed; on by default in the pinned build since 2026-11-17 (`MVK_P60_NO_KEEP_ENCODER=1` turns it off; [emulator-options](../emulator-options/README.md)); not upstream |
| CPU widening of 8-bit indices | `P60_UINT8_HOST=1` | Lichii's existing path, also used when MoltenVK accepts 8-bit indices. Removes 82 conversion dispatches and 82 render-pass splits per frame | 1.3 ms; render encoders 232 → 149 | on by default in the pinned build (`=0` turns it off) |
| List-indirect on MoltenVK | `P60_LIST_INDIRECT=1` | Lichii's Ocarina feature was off because MoltenVK reports 2^30 for `maxComputeWorkGroupCount` and Lichii asks for 2^31−1. 10.9 GPU-written dispatch sizes per frame are then taken without waiting | 1.2 ms; GPU idle 3.9 → 1.5 ms | on by default in the pinned build (`=0` turns it off); a one-line fix on either side |
| Shuffle-free HMMA | `P60_HMMA_MEM=1` | Software tensor multiply exchanges its fragments through workgroup memory with subgroup barriers instead of 48 `simd_shuffle`s per multiply | 5.7 ms; the pass 7.8 → about 2.3 ms | on by default in the pinned build (`=0` turns it off) |
| Run a frame ahead | `P60_RUN_AHEAD=1` | Skips the extra wait for the current frame's fence at present | 0.2 ms (noise) | no gain; off |
| App Nap opt-out | `MVK_P60_NO_APPNAP=1` | Measurement only, see "Measurement hazards" | | needed for clean runs with a hidden window; off unless set |
| Sync trace | `P60_SYNC_TRACE=<file>` | Diagnostics only | | off unless set |

Files: `patches/lichii/0005-path-60-frame-time-fixes-and-their-switches.patch` (15 files),
`patches/moltenvk/0007-path-60-keep-the-render-encoder-across-barriers-and-.patch`, and
`patches/moltenvk/0008-path-60-keep-encoder-on-by-default-MVK_P60_NO_KEEP_E.patch`.

## What remains between 19.3 ms and 16.7 ms

Bilinear build, run `f-bil-1` (measured; categories are named from target size and format, so the game/emulation
labels are **inferred**):

| Part | ms/frame | Kind |
| --- | ---: | --- |
| **GPU idle, waiting for commands** | **3.9** | emulation |
| Main geometry, 1,511 draws at 1440x810 in 42 Metal passes | 5.3 | game |
| Game compute, 143 dispatches | 3.7 | game; 1.5 ms of it is in 17 shaders that use warp shuffles (not probed) |
| Half-res effects, env/LUT targets, shadows, post, bloom, HUD | about 3.9 | game |
| Buffer copies, 141 encoders | 1.0 | emulation |
| Occlusion-query accumulation, 138 dispatches | 0.5 | emulation (MoltenVK) |
| Presentation, image copies, query copies | about 0.6 | emulation |
| **Total** | **19.4** (GPU busy 15.5) | game about 12.9, emulation about 6.0 |

Evidence for the split: the per-pass table of run `f-bil-1` (MoltenVK frame profiler output, grouped by the
frame-breakdown scripts), and the before/after of each removed item in the waterfall. The game's own GPU work, about
13 ms, fits in 16.7 ms. The 2.6 ms still to remove must come out of the 6.0 ms of emulation overhead, and 3.9 ms of
that is idle time.

**The idle time** (run `r7-nbil-tr`, `gapsplit.py` and `gaptrace.py` from `tools/perf` on the MoltenVK profile and
Lichii's sync trace):

- 2.8 gaps per frame where the GPU has run dry and the next command buffer has not been started, 3.1 ms per frame.
- One of them, 0.8 times per frame and about 2.1 ms long, follows the end-of-frame flush
  (`RasterizerVulkan::FlushCommands`). It carries 1.7 ms of the 3.1 ms. The GPU finishes the frame and the next
  frame's first commands are not there yet.
- The others are sync points inside the frame (fence queue, list-page copies, host-read submits), about 0.6 ms each.
- Per gap: 0.69 ms mean until Lichii flushes the next commands, 0.25 ms of MoltenVK encoding, 0.11 ms until Metal
  starts it. In the base build the first part splits into about 0.1 ms until the waiting Lichii thread resumes and
  0.3 ms of producing commands (run `r5-tr-1`).
- Not the cause (measured): the 500 µs fence-flush batching, the "GPU is behind, wait for this frame too" rule at
  present, and presenting through the command buffer.
- Not found: why the next frame's first commands arrive about 2 ms after the GPU finishes the previous frame. The
  guest's main thread and Lichii's front and back GPU threads were not traced at that point with this build. A later
  trace on the keep-encoder build points at semaphore waits between the game's GPU channels
  ([emulator-options](../emulator-options/README.md), "Where the GPU's idle time goes"); that reading is not tested.

## Findings by area

1. **Network upscale.** The bilinear stand-in is the fastest option measured: 22.0 ms against 24.7 ms for FSR
   (measured, one run each plus the combined runs). The shuffle-free multiply keeps the game's image and is the one
   in the pinned build:
   - The multiply's result is bit-identical: 3,145,728 random lane results in six value classes match the original
     helper (`hmtime unit`).
   - On a captured game frame the offline harness reproduces the game's own output on all 2,073,600 pixels, and the
     variant's output is byte-identical to it (`hmtime time --real`).
   - A frame dumped from the game running the patched recompiler equals what the original shader produces from the
     same input (run `r7-hm-fd`).
   - Offline timings: original 7.6–8.1 ms; vector layout 2.4–2.6 ms; scalar layout 2.8–3.2; float storage 4.3;
     native fp16 rounding 3.5; gathers shared between multiplies 3.8–3.9 (slower: register pressure).
   - MPSGraph, Core ML and `simdgroup_matrix` were not tried.
2. **GPU idle.** See above. List-indirect removes the dispatch-size waits; the rest is hand-off latency.
3. **Emulation overhead.**
   - Built: encoder splitting at barriers, 8-bit index conversion.
   - Buffer copies were attributed (run `r5-tr-1`): 254 read-download copies per frame carrying 976 KiB
     (`BufferCache::RecordReadDownload`), 32 list-page copies, and uploads that already go to a separate upload
     command buffer (81 mapped uploads of 920 KiB, 355 inline uploads). The guest reads GPU-written memory less than
     once per frame, so almost all downloads are speculative.
   - Not built: download-on-demand, occlusion-query accumulation.
4. **Game work inflated by translation.**
   - The other compute is spread thin: largest shader 0.25 ms, 101 dispatches under 20 µs each.
   - 133 of 357 dumped fragment shaders discard, 3 force early tests; main-pass fragment time is 2.6 ms in all.
   - No per-shader offline timing and no fragment-cost probe were made; a whole-game fast-math run was spoiled by the
     App Nap hazard and not repeated here (a later one is in [emulator-options](../emulator-options/README.md)).
5. **Outside the per-pass view.**
   - Pacing: menus and the title run at a 16.67 ms median, so nothing caps the game at 30. The limit is
     `nx2_frame_rate_limit=60`. The Dynamic FPS and FPS Unlock add-ons are disabled in this configuration; the game
     steps 1/60 s per frame and runs in slow motion below 60.
   - Release 228 against current `nx2`: not bisected. Tag `build-228` and `nx2` `8c0558a3d` are 142 commits apart on
     the `nx2` side (about 7 builds and 14 runs).
   - KosmicKrisp: not run (no Vulkan SDK or Mesa was installed). The survey in
     [moltenvk-offramp](../moltenvk-offramp/README.md) found it lacks `VK_EXT_mesh_shader`.
   - Internal resolution and docked mode: not measured here (see [emulator-options](../emulator-options/README.md)).

## Measurement hazards

While Lichii's window is hidden during a verify run, macOS can move the process to the efficiency cores. Frame time
then jumps to 50–60 ms from some frame on, with identical GPU work per frame. Apple's trace shows it: the
performance-core share of CPU user time is 93–97% in normal runs and 51–66% in slow ones (run `mpt-1`). It hit 5 of
9 runs between 16:27 and 16:47 and looked like regressions of three different switches. All runs from `r6-*` on use
`MVK_P60_NO_APPNAP=1`; none of them was hit. Runs marked "without the App Nap opt-out" above were checked by their
thirds.

Two more hazards. Running `/Applications/lichii.app/Contents/MacOS/lichii --version` opens the GUI (for about a
minute): it spoiled run `r3-base-1` and rewrote `qt-config.ini` (only `update_remind_at` and shortcut defaults
changed, checked by diff). And the status bar's "60 FPS / 16.67 ms" in two screenshots is not a measurement; the
hook's clock is.

## To do, ranked

| # | Item | Expected | Effort |
| --- | --- | --- | --- |
| 1 | Find why the next frame's first commands arrive about 2 ms after the GPU finishes the frame (trace the guest main thread, front and back at the frame boundary) | up to 1.7 ms | 1–2 days to find; fix unknown |
| 2 | Download GPU-written buffers on demand, or batch read-download copies at flush | up to 1.0 ms GPU, fewer encoders | several days in Lichii's buffer cache |
| 3 | Occlusion-query accumulation once per command buffer instead of at every render-pass end | up to 0.5 ms | 1–2 days in MoltenVK |
| 4 | Cheaper MoltenVK encoding of small command buffers after a sync point (0.25 ms per gap) | up to 0.5 ms | unknown |
| 5 | Upstream-quality versions of the three overhead fixes (fix the limit check for list-indirect) | keeps 2.7 ms | 2–3 days |
| 6 | Upstream-quality version of the shuffle-free multiply (on by default in the pinned build, about 2.3 ms for the pass) | the game's image at about the stand-in's frame time, for every user | 1–2 days to clean up |
| 7 | Probe the 17 shuffle-using compute shaders (1.5 ms) | unknown | 1 day |

Items 1–4 together are worth more than the 2.6 ms still missing, but none is built and item 1 has no known fix.

## Not measured

- Stock 228 was not re-run; docked mode, lower internal resolution, other locations.
- Four full-route runs per build (two were made); image equality of the overhead fixes beyond the spawn screenshots;
  the stand-in while walking beyond frame times.
- Per-draw GPU cost, overdraw, and offline timing of compute shaders other than the upscaler.
- KosmicKrisp, and the release-228 gap.
- Whether these limits hold on faster hardware.

## Summary

1. Best measured on 2026-11-16: 18.6–19.1 ms standing with the game's image (shuffle-free multiply), 19.2–19.4 ms
   standing and 20.0–20.8 ms walking (about 50 fps) with the bilinear stand-in.
2. GPU work is down to 15.5 ms per frame, under budget; 3.9 ms of GPU idle is what keeps the frame above 16.7 ms.
3. Savings alone: stand-in 8.0 ms, keep-encoder 2.5, CPU index widening 1.3, list-indirect 1.2; shuffle-free
   multiply 5.7.
4. The largest idle gap, about 2 ms once per frame at the frame boundary, is located but not explained.
5. The shuffle-free multiply is bit-exact and is what the pinned build uses; the stand-in is off by default.
