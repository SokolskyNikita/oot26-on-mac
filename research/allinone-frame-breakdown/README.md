# All-in-one build: where a 29–31 ms frame goes (Kokiri Forest spawn, 1x, handheld)

The build is the all-in-one: the first combined Lichii + MoltenVK build of 2026-11-16 (Lichii patches 0001–0005 and
MoltenVK patches 0001–0005 under [`patches/`](../../patches/)). It runs on an Apple M4 Pro (Mac16,8) under macOS
27.0.1, standing at the Kokiri Forest spawn point with the verify harness's save, at 1x and in **handheld mode**
(`use_docked_mode=0`). The game renders the scene at 1440x810 and scales it to 1920x1080. Lichii presents that to a
2560x1440 window. The goal is 16.7 ms (60 fps).

Each claim below is marked **measured** (with the run it comes from) or **inference**. Run labels (`aiop-b5`,
`aiop-p3`, …) name local run folders, which are not tracked. The frame profiler is MoltenVK patch
`patches/moltenvk/0006-Frame-profiler-MVKFrameProf-per-pass-GPU-time-encode.patch`; the analysis scripts named
below were local and are not in this repository.

## Summary

1. **One compute dispatch costs 7.9 ms of the frame: the game's own 810p→1080p neural-network upscale.** (measured)
   It is a single dispatch of 1,020 groups of 128 threads, the last big piece of GPU work in each frame. Each thread
   runs 105 tensor-core matrix multiplies (NVIDIA HMMA, half precision). Lichii's recompiler emulates them with
   warp shuffles. Timed alone in an offline harness it takes 7.6 ms. With the emulated multiply stubbed out it takes
   0.13 ms, and with two thirds of the shuffles removed it takes 0.75 ms. Math mode, the fp16 rounding code and the
   SPIRV-Cross float helpers make no difference. So the cost is the shuffle-based emulation. Lichii can already
   replace this pass with FSR 3.1 (`EDEN_NX2_DLSS_REPLACEMENT=fsr`): the frame then drops to **24.4 ms** (measured),
   because FSR's own passes cost 2.7 ms instead of 7.9 ms.
2. **The frame is GPU-bound: the GPU is busy 25–27 ms of the 29–31 ms, and idle about 3.9 ms.** (measured)
   Neither the guest CPU nor the GPU threads are saturated. The idle time comes in about 5 gaps per frame of about
   0.6 ms each. In each gap the CPU had not started the next command buffer when the GPU ran dry. The gaps stay at
   3.9 ms when FSR takes 5 ms of GPU work away (measured). They look like CPU↔GPU round trips at the game's sync
   points (inference: which sync points was not identified).
3. **About 3.5 ms a frame is overhead from the emulation layer, not the game.** (measured costs; fixes are
   inference) Most of it is encoder fragmentation: 1,070 Metal encoders and 45 command buffers per frame for about
   2,100 draws and 140 dispatches.
   - 394 tiny copy-buffer blit encoders (1.8 ms).
   - 82 MoltenVK uint8-index conversion dispatches (0.56 ms).
   - 131 occlusion-query accumulation dispatches (0.44 ms).
   - The main scene pass split into about 39 Metal render passes.

**Verdict.** 60 fps here is not reachable by fixing one thing. FSR alone gives about 41 fps (24.4 ms, measured).
Replacing the network with a plain bilinear scale instead of FSR, and removing the encoder overhead, gives an
estimated 19–21 ms (about 50 fps). Getting to 16.7 ms would also need most of the 3.9 ms of sync bubbles gone, and
that is the least certain item. The GPU work the game itself asks for, without the network and without the
emulation overhead, is about 14 ms on the M4 Pro (inference from the per-pass table), so a ceiling of about
15–17 ms exists only if everything else goes to zero.

The estimates on this page are for this build. The bilinear bypass, a shuffle-free multiply and three overhead fixes
were then built and measured in [path-to-60fps](../path-to-60fps/README.md): 19.2–19.4 ms with the bilinear stand-in,
18.6–19.1 ms with the game's own image.

## The frame budget

Standing, 1,050 frames. All numbers are medians per frame unless marked mean.

| Part | ms/frame | Run and how |
| --- | ---: | --- |
| **Frame time** (uninstrumented) | **30.7** | `aiop-b5`, hook frame clock. Same day: 33.5 (`aiop-b1`, load 8.3). Earlier runs that day: 27.9–29.2 ([mac-performance](../mac-performance/README.md)). Run-to-run spread that day was about ±2 ms. |
| Frame time (instrumented, same pair) | 30.6 | `aiop-p5`. Other instrumented runs: 30.9 (`p1`), 29.1 (`p3`). |
| **GPU executing** | **26.7** | `aiop-p5`: union of `MTLCommandBuffer` GPU start/end per frame interval. Apple's always-on trace gives On-GPU 26.86 (mean) for the same run and **26.79 for the uninstrumented `aiop-b5`**. |
| — of which the network upscale dispatch | 7.9 | one dispatch (see the per-pass table) |
| — of which everything else | 18.8 | |
| **GPU idle (waiting for work)** | **3.9** | same, frame time minus busy. 3.9 in `p1`, `p3`, `p5` and in the FSR run. |
| — CPU had not started the next command buffer | 2.8–3.1 | `gaps.py`: about 4.7 gaps per frame, mean 0.59–0.64 ms. The next command buffer's first encoder was created after the GPU went idle. |
| — next command buffer was being encoded, committed late | 0.8–1.1 | about 4.5 gaps per frame, mean 0.19–0.29 ms |
| — small gaps between command buffers | 0.15 | about 31 per frame, about 5 µs each |
| Present / drawable wait | 0.02 | Apple trace, "Next Drawable Wait", mean |

Work that overlaps the GPU and does not add to the frame on its own (measured):

| CPU side | Load | Source |
| --- | --- | --- |
| Guest CPU (6 emulated cores) | each core runs game code (JIT) 10.8–13.0 ms per 31 ms frame, about 35–40%. The busiest guest thread is on a core 6.4 ms/frame and waits 24–25 ms/frame. The game's main thread (t88) waits on sync objects 10.8–11.1 ms/frame in 3 waits. | `aiop-gp1`, `EDEN_NX2_GUEST_THREAD_STATS=1` (10 s windows at 73 s and 83 s) |
| GPU front thread (command processing, macros) | busy about 24% (macro 232 ms/s). Asleep waiting for the guest 49%, front waiting for back 17%. | `aiop-gp1`, `EDEN_NX2_GPU_PROFILE=1` |
| GPU back thread (Vulkan recording) | busy about 46% (bind stage buffers 63 ms/s, methods 127 ms/s, …), waiting for the front 54% | same |
| MoltenVK encoding (`vkQueueSubmit` on VulkanWorker) | about 2.8% of samples, about 0.8 ms/frame | `aiop-p3`, `sample` (coarse, see "not measured") |

**Which side is the bottleneck: the GPU.** (measured) In every run the GPU is busy 87% of wall time, and the frame
time follows GPU time. FSR removed 5.2 ms of GPU time (busy 25.2 → 20.6 ms) and the frame fell by the same amount
(29.1/30.6 → 24.4 ms). No CPU thread is near 100%. The remaining 3.9 ms is serialization: the GPU waits for the CPU,
which waits for the GPU. That is latency, not CPU throughput.

## GPU breakdown by pass

`aiop-p3`, standing, 1,050 frames. Per-frame GPU span of each Metal encoder from stage-boundary timestamps (render:
vertex start to fragment end). The sum is 24.6 ms against 25.2 ms busy. Category names are **inference** from target
size, formats and draw counts: the profiler sees Metal encoders, not the game's intent.

| Category | GPU ms | Share | Encoders/frame | Draws or dispatches/frame | Target |
| --- | ---: | ---: | ---: | ---: | --- |
| **Network upscale (game compute, emulated tensor ops)** | **7.92** | 32% | 1 | 1 (1,020 groups × 128) | reads 1440x810, writes 1920x1080 |
| **Main geometry** | **4.77** | 19% | 38.6 | 1,502 | 1440x810 RG11B10F + D32F. Vertex 2.0 ms, fragment 2.4 ms (summed stage spans). |
| **Other game compute** | **3.56** | 14% | 142 | 142 (84 shaders; largest 0.24 ms) | — |
| **vkCmdCopyBuffer blits** | **1.82** | 7% | 394 | — | — |
| Half/quarter-res effects | 1.43 | 6% | 58 | 92 | 720x405 (2× RGBA16F + depth, 0.62 ms), 360x202 and below |
| Square targets 128–256 (env/cube/LUT, inferred) | 0.85 | 3% | 14 | 134 | 256x256 RGBA16F, 128x128 RG11B10F + depth |
| MoltenVK uint8 → uint16 index conversion | 0.56 | 2% | 82 | — | added by MoltenVK: Metal has no 8-bit indices |
| Shadow maps (depth only) | 0.46 | 2% | 12 | 106 | 1000x1000 Depth16 and others |
| MoltenVK occlusion-query accumulation | 0.44 | 2% | 131 | — | added by MoltenVK at every render pass end with an active query |
| 2560x1440 presentation | 0.34 | 1% | 5 | 87 | Lichii's present and window filters |
| Mip/luminance chain 1..64 (inferred) | 0.33 | 1% | 32 | 16 | — |
| Downsample/blur chain 960x540..30x16 (bloom, inferred) | 0.33 | 1% | 36 | 31 | RG11B10F |
| Attachment-less render passes | 0.33 | 1% | 0.7 | 1 | — |
| Full-screen 1440x810 passes, no depth (tonemap and post) | 0.27 | 1% | 4 | 2 | — |
| vkCmdCopyImage / BlitImage / CopyQueryPoolResults | 0.50 | 2% | 76 | — | — |
| 1440x810 RGBA8 + depth, depth-only | 0.33 | 1% | 19 | 17 | — |
| Output 1920x1080 (HUD and post after the upscale) | 0.14 | 1% | 3 | 51 | — |
| Other small passes | 0.24 | 1% | 21 | 44 | — |

Totals per frame: 231 render encoders (2,083 draws, 9.8 ms), 367 compute encoders (12.5 ms), 470 blit encoders
(2.3 ms), 45.5 command buffers. One command buffer per frame (23–43 encoders) holds the network dispatch and the
final upscale and presentation passes; it runs 8.5–8.8 ms on the GPU.

**Top passes by time:** the network upscale (7.9 ms), the main geometry pass (4.8 ms), the other game compute
(3.6 ms in 142 dispatches), the copy-buffer blits (1.8 ms), and the half-res effects (1.4 ms).

## Why the top costs cost what they do

### 1. The network upscale: tensor-core multiplies emulated with shuffles (7.9 ms) — fixable in Lichii

- **What it is** (measured): MoltenVK's shader `11e78e3deaec1d65` (SPIR-V hash), from the MoltenVK shader dump of
  run `aiop-p2`.
  - It gathers the 1440x810 tonemapped image in 48x24 tiles (30 × 34 = 1,020 groups) and writes a 64x32 output tile
    per group (16 writes per thread = 1920x1080).
  - Its helper `_97` is an HMMA.16816 (16x8x16, fp16 accumulate) done in software: per call, 2 × 4 steps of 6
    `simd_shuffle`s, 32 FMAs and a manual fp16 rounding of the four accumulators. Each thread calls it 105 times.
  - Running with Lichii's FSR replacement removes exactly this dispatch (`aiop-fsr1`). That makes it the end-of-frame
    "3/4 upscale" pass Lichii's Ocarina upscaler targets (`FindOcarinaUpscalePass`, `ThreeQuarter`).
    `docs/nx2/oot-network-bypass.md` describes the game's network on the anti-aliasing path (docked, 1:1 output).
    This handheld pass is the scaling variant.
- **Why it is slow** (measured with `cstime`, an offline harness). The harness compiles the dumped MSL, dispatches it alone
  with the game's grid and random inputs, and takes the median of 15 runs:

  | Variant | GPU ms |
  | --- | ---: |
  | as MoltenVK compiles it (MTLMathModeSafe, precise functions) | 7.6–7.7 |
  | same with MTLMathModeFast | 7.6–7.8 |
  | `spvFMul`/`spvFAdd` helpers turned into plain `*`/`+` | 7.5–7.6 |
  | fp16 accumulator rounding removed (probe, wrong results) | 7.5–7.6 |
  | `_97` forced inline / its 2-trip loop unrolled | 7.5–7.6 |
  | 16 of the 24 shuffles in the helper's loop body replaced by the lane's own value (probe, wrong results) | **0.75** |
  | `_97` stubbed out (probe, wrong results) | **0.13** |

  The harness reproduces the in-game 7.9 ms. Almost all of the time is the shuffles with per-lane lane indices
  (`_131 + k`, `_130 + k`): about 5,000 per thread. The FP math, the safe-math pragmas and the rounding cost nothing
  measurable. The ALU work is about 0.9 G multiply-adds, roughly 0.2 ms of FP32 throughput on this GPU (inference).
- On the Switch 2 these multiplies run on tensor cores (inference: that is what HMMA is). This cost exists only in
  emulation.
- **Fixes:**
  - (a) **FSR 3.1 replacement, already in Lichii**: `ocarina_fsr` setting or `EDEN_NX2_DLSS_REPLACEMENT=fsr`.
    Measured: frame 24.4 ms, GPU busy 20.6 ms. FSR's 14 dispatches cost 2.7 ms. The picture is correct (spawn
    screenshots of `aiop-fsr1`), but it is a temporal upscale with host jitter, not the game's image.
  - (b) **A bilinear bypass of the handheld 3/4 pass** (Lichii change, not built). The config already asks for "No
    sharpening" (`oot_anti_aliasing=1`), but no bypass happens: the log has no `anti-aliasing network bypassed`
    line. The bypass handles only same-size output programs (`OutputProgramKey`, `BaseOutputPrograms`), not this
    810p→1080p pass. A bilinear 1440x810→1920x1080 copy would cost about 0.1–0.2 ms (inference), saving about
    7.7 ms. The image loses the network's smoothing and sharpening.
  - (c) **Lower HMMA to Metal `simdgroup_matrix` or a shuffle-free layout** in Lichii's recompiler (keeps the
    game's image). It is not prototyped. From the probes, the floor is 0.1–0.75 ms plus whatever layout conversion
    `simdgroup_matrix` needs. A realistic estimate is 1–3 ms, saving 5–7 ms (inference, low confidence).

### 2. GPU idle at sync points (3.9 ms) — partly fixable in Lichii, cause not pinned down

- **Measured:**
  - The idle time is the same, 3.9–4.0 ms/frame, in all instrumented runs and with FSR. It does not scale with GPU
    load.
  - About 4.7 gaps per frame are "created-after": the next command buffer's first encoder was created about 0.6 ms
    after the GPU finished the previous one. The command buffers right before gaps are mostly small (4 or 8
    encoders).
  - The gaps recur at the same points in each frame (frame timeline in `aiop-p1`). One comes right before the
    command buffer that holds the network dispatch.
  - The game's main thread waits on sync objects about 11 ms/frame in 3 waits. Lichii's front thread sleeps 49% of
    the time waiting for the guest. Its back thread waits 54% for the front.
  - Lichii logs about 14,500 split drains per second (front waiting for back, about 1.7 s per 10 s). These are
    CPU-to-CPU waits; they cost CPU-thread time, not GPU time.
- **Inference:** at these points the game waits for a GPU result: a fence, a query, or a GPU-written read. Its next
  commands then go through guest → front → back → Vulkan worker → MoltenVK before the GPU sees work again. That
  takes about 0.6 ms each time. On the console the same round trip takes far less.
- **Where to look:**
  - the latency from the GPU completing to the guest waking: `GPUFencingThread` in `vkWaitSemaphores`, MoltenVK's
    `MTLSharedEvent` notification;
  - whether Lichii can submit the work after a fence earlier;
  - which guest waits these are, using `EDEN_NX2_SEM_WATCH` or `EDEN_NX2_RENDER_TRACE`.
- **Estimated saving:** 1–2.5 ms, low confidence.

### 3. Encoder fragmentation and MoltenVK-added work (about 3.5 ms) — fixable in Lichii and MoltenVK

- **vkCmdCopyBuffer**: 394 separate blit encoders per frame, 1.82 ms (measured). The copies come between draws and
  dispatches, so MoltenVK can't merge them (inference).
  - Lichii could write uniform and vertex uploads straight into host-visible device memory, since the memory is
    unified on Apple silicon. Or it could batch copies at the start of a command buffer.
  - Estimated saving 1–1.5 ms (inference, medium confidence). Which Lichii paths issue these copies was not
    traced.
- **uint8 index conversion**: 82 compute encoders per frame, 0.56 ms (measured). In the sampled frames, 5 of the
  main-pass splits per frame are this conversion (measured, `E` records of 7 frames).
  - Fix: Lichii converts uint8 index buffers once per buffer and caches the result, or MoltenVK caches its
    conversion.
  - Estimated saving 0.6–0.7 ms, splits included (inference, medium-high confidence).
- **Occlusion-query accumulation**: 131 compute encoders per frame, 0.44 ms (measured). MoltenVK runs one at the end
  of every render pass that has a query active.
  - Fix: in MoltenVK, accumulate once per command buffer, or give each query its own visibility-buffer offset.
  - Estimated saving 0.3–0.4 ms (inference, medium confidence).
- **The main scene pass is cut into about 39 Metal passes** (33 begin + 5 restarts per frame, measured).
  - What separates consecutive main-pass encoders inside one command buffer: uint8 conversion (5/frame), query
    accumulation (about 5.7/frame), a game dispatch, or `vkCmdCopyImage`. The other splits fall at command-buffer
    boundaries (Lichii flushes about 45 times a frame).
  - Each pass loads and stores 1440x810 colour + depth. An empty one costs about 14 µs and one with 1–2 draws about
    30 µs (measured, 99 sampled encoders), so about 0.5–1 ms in all (inference).
- **Between encoders**: the gap between summed encoder spans and command-buffer busy time is about 0.6 ms/frame
  (measured, 24.6 vs 25.2 ms). Encoder transitions cost that; the fixes above shrink it.

### 4. The game's own work (about 14 ms) — not fixable outside the game

- Main geometry: 4.8 ms for 1,500 draws at 1440x810, with vertex and fragment about equal.
- Other game compute: 3.6 ms in 142 dispatches.
- Half-res effects: 1.4 ms.
- Shadows, environment and post: about 2.5 ms.
- About 2 ms of small passes.

Nothing here stands out as wrong for the M4 Pro (inference). The overdraw and discard lead from earlier work
would sit in the 2.4 ms of main-pass fragment time, so it is worth at most a fraction of that (inference; not
measured: there are no per-draw timings without Xcode).

## Ranked fixes

Savings are per frame at this spot, against the current about 29–31 ms. They are not fully additive: GPU savings turn
into frame time only while the GPU stays the bottleneck.

| # | Fix | Where | Saving | Confidence |
| --- | --- | --- | ---: | --- |
| 1 | Use the FSR 3.1 replacement for Ocarina (`ocarina_fsr`, or `EDEN_NX2_DLSS_REPLACEMENT=fsr`) | setting, no code | **5.2 GPU → frame 24.4 ms** | high: measured (`aiop-fsr1`, picture correct) |
| 1b | …or a bilinear bypass of the handheld 3/4 pass (extend No sharpening to it) | Lichii | about 7.7 (2.5 more than FSR) | medium: the 7.9 ms is measured, the bypass is not built; changes the image |
| 1c | …or lower HMMA to `simdgroup_matrix` or a shuffle-free layout (keeps the game's image) | Lichii recompiler | 5–7 | low: offline probes only |
| 2 | Shorten the CPU↔GPU round trips at the game's sync points | Lichii (fence signalling, submit), maybe MoltenVK event latency | 1–2.5 | low: gaps measured, cause inferred |
| 3 | Stop issuing hundreds of separate `vkCmdCopyBuffer` blits: write uploads directly (unified memory) or batch them | Lichii | 1–1.5 | medium |
| 4 | Convert uint8 index buffers once and cache them (Lichii), or cache the conversion in MoltenVK | Lichii or MoltenVK | 0.6–0.7 | medium-high |
| 5 | Accumulate occlusion-query results once per command buffer, not at every pass end | MoltenVK | 0.3–0.4 | medium |
| 6 | Fewer main-pass splits once 3–5 are done (fewer flushes, no work between draws) | Lichii and MoltenVK | 0.5–1 (overlaps 3–5) | low-medium |

**Is 60 fps reachable on the M4 Pro?** Not with any one fix. The realistic ceiling at this spot is about 19–21 ms
(48–52 fps): fixes 1b, 3, 4 and 5 with some of 2. With FSR instead of the bypass it is about 2.5 ms slower. 16.7 ms
needs all of that plus most of the sync bubbles gone. The game's own GPU work leaves no headroom for anything else:
about 14 ms + presentation, inferred from the table above.

## Walking (second measurement point)

`aiop-p3`, the same instrumented build through the verify route (two walks of 944 frames each):

| Phase | Frame (median) | GPU busy | GPU idle | Draws/frame | Network upscale |
| --- | ---: | ---: | ---: | ---: | ---: |
| Standing | 29.1 | 25.2 | 3.9 | 2,083 | 7.92 |
| Walk 1 | 30.8 | 24.3 | 5.2 | 1,341 | 7.75 |
| Walk 2 | 28.9 | 24.3 | 3.9 | — | — |

Walk 2's busy and idle are measured from the start of walk 2 to the end of the recording. The breakdown is the
same while walking: network 7.75 ms, main geometry 4.6 ms, other compute 3.4 ms, copy blits
1.75 ms (walk 1, `aiop-p3.walk1.json`). Walk 1 has more idle time and hitches (mean 36.6 ms, 4 frames over 70 ms)
from new pipelines: the main shader cache grew from 49 to 73 MB during the route. The pipeline cache of that
configuration only held standing's pipelines.

## How it was measured

Every run used the run script (copy in [mac-performance/patches/run.sh.txt](../mac-performance/patches/run.sh.txt))
or its full-route variant. Each configuration has its own shader and pipeline caches. The verify harness's hook
([`tools/verify`](../../tools/verify/README.md)) writes the frame clock. The run screenshots were checked for `b1`,
`p1` and `fsr1`: same position, correct picture.

| Run | What | Standing median | Load (1-min) |
| --- | --- | ---: | --- |
| `aiop-b1` | unmodified all-in-one (CFG `allinone-cold`) + Apple trace | 33.5 | 4.8 → 8.3 |
| `aiop-p1` | instrumented, per-encoder timestamps (CFG `aio-prof`) | 30.9 | 8.1 → 9.9 |
| `aiop-p2` | instrumented + shader ids + MoltenVK shader dump, cold MoltenVK cache (CFG `aio-prof-dump`); used only to name shaders, last third slowed down | 33.0 | 8.3 → 9.2 |
| `aiop-p3` | instrumented, full route; `sample` for 8 s at 10 s into standing (inflates those frames: means are skewed, medians used) | 29.1 | 7.5 at end |
| `aiop-fsr1` | instrumented + `EDEN_NX2_DLSS_REPLACEMENT=fsr` (CFG `aio-prof-fsr`) | 24.4 | 4.1 → 7.1 |
| `aiop-gp1` | instrumented + `EDEN_NX2_GPU_PROFILE=1` `EDEN_NX2_GUEST_THREAD_STATS=1` | 31.5 | 5.4 → 8.4 |
| `aiop-b5`, `aiop-p5` | back-to-back pair: unmodified, then instrumented, + Apple trace for both | 30.7, 30.6 | 8.0 → 8.6 |

Tools (local, not in this repository, except the profiler itself):

- **Instrumented MoltenVK**: the all-in-one MoltenVK plus the frame profiler (MoltenVK patch 0006). It is off
  unless `MVK_FRAMEPROF=<file>` is set.
  - Every Metal render, compute and blit encoder gets `MTLCounterSampleBuffer` stage-boundary timestamps.
  - Every command buffer records GPU start/end, kernel (scheduling) start/end, and the host time its first encoder
    was made.
  - Compute encoders are tagged with the SPIR-V hash of their shader and their threadgroup count.
  - Each command buffer's encoders are summed by signature: kind, command use, size, formats, load action, shader.
    Every 150th frame is dumped encoder by encoder.
- **Instrumentation overhead**: under 0.2 ms, within noise (measured, `aiop-b5` and `aiop-p5` back to back). Frame
  30.7 vs 30.6 ms. Apple's On-GPU time 26.79 vs 26.86 ms. The profiler's own GPU-busy union, 26.77 ms, matches
  Apple's figure for the same run within 0.1 ms. No correction was needed.
- `prof_report.py PROF RUN`: frame time, per-frame GPU busy and idle, command buffer and encoder counts, signatures
  ranked by GPU time. `categorize.py` groups them into the per-pass table. `gaps.py` classifies GPU idle gaps.
- `mpt_report.py`: per-phase numbers from Apple's always-on Metal trace (`metalperftrace collect`, then
  `overview --json --json-include-timeline`). It is passive: nothing is attached to Lichii. The window is behind
  other windows during a verify run, so the trace counts all frames as "skipped" (never on glass). Their On-GPU and
  drawable-wait numbers are still recorded.
- `cstime.swift` / `cstime`: the offline harness for the network upscale kernel. Its variants are listed above.
  Inputs are made up, so the numbers are instruction cost, not the game's data.
- `pair.sh`: the overhead pair. `sidecar.sh`: runs a command (here a `sample` wrapper) a fixed time into standing.
- Lichii's own counters: `EDEN_NX2_GPU_PROFILE` (front and back thread time per second, drains) and
  `EDEN_NX2_GUEST_THREAD_STATS` (guest threads and cores, ms per frame).

## What was not measured

- **Per-draw and per-shader GPU cost inside a render pass**, occupancy, ALU vs bandwidth, and overdraw. No Xcode was
  installed, so no Metal System Trace, GPU counters or frame capture. Only encoder-level timestamps. The
  discard/early-depth overdraw lead from earlier work is still untested. It can be worth at most part of the 2.4 ms of
  main-pass fragment time.
- **The fixes themselves**, except FSR, in this build. Their savings here are estimates from the measured cost of
  what they remove. Which were built later, and what they measured, is in [path-to-60fps](../path-to-60fps/README.md).
- **Which guest sync points cause the GPU idle gaps.** The pattern is measured; the cause (fence or query waits and
  the latency of each hop) is inferred.
- **CPU time per thread in detail.** `sample` suspends the 100-thread process for each sample (about 4 ms between
  samples here). Its busy percentages for the GPU threads (about 4%) disagree with Lichii's own timers (front about
  24%, back about 46%). The write-up uses Lichii's timers for the GPU threads and the guest. The `sample` numbers are
  used only for MoltenVK's share of VulkanWorker.
- **Image equivalence of FSR** beyond the two spawn screenshots, and FSR while walking.
- **Docked mode**, where the scene is 1080p and the network 1080p→1440p, so presumably larger. Also other locations,
  and anything over 2 walks.
- **Stage-boundary sampling distortion of encoder overlap.** Per-encoder spans are summed. That they add up (24.6 vs
  25.2 ms busy) and that busy matches Apple's trace suggests little overlap was lost. It is not proven per encoder.
- Why the run-to-run frame time varied by about ±2 ms that day (29.1–33.5 ms for the same build). Load average stayed at
  7–9 throughout, with WindowServer at about 60% CPU. Each comparison above is between runs made back to back.

## Files

The runs (frames, logs, screenshots, profiler output, Apple traces, `cstime` output, sample reports), the 106 MB
shader dump of `aiop-p2` and the per-configuration caches were local and are not tracked. One caching hazard from
them: the full-route run once left a truncated 12-byte pipeline cache, which had to be replaced from another
configuration's cache; the full-route script keeps the previous cache when that happens.
