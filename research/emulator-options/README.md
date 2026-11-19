# Lichii options, settings and tools, tested (2026-11-17)

What Lichii offers for reading the game's state, measuring speed and finding visual bugs, and what each setting,
switch and tool did when tried on the pinned build's predecessors. The list of settings and switches comes from
Lichii's source (`settings.h`, `settings_enums.h`, `docs/nx2/*.md`); this page keeps what was measured. Tools:
[`tools/harness`](../../tools/harness/README.md).

Measured on an Apple M4 Pro (Mac16,8, 14 cores, 48 GB) under macOS 27.0.1, with a 120 Hz display, on 2026-11-17 and
2026-11-18, at 1x, handheld, post-processing off, GPU accuracy Low unless a row says otherwise. The base build is the
pinned build as it stood that day: the all-in-one build (the first combined build of 2026-11-16, Lichii and MoltenVK
patches 0001–0005) plus the path-to-60fps fixes ([path-to-60fps](../path-to-60fps/README.md)); keep-encoder on by
default from batch 4; MoltenVK PR #2901 and the mesh cull-mode fix from the evening of 2026-11-17; the shared JIT
cache from 2026-11-18. Run folders named `ab-<date>-<time>` are local run data and are not tracked.

All frame times are the median (p50) frame interval in ms, from the verify hook's per-present clock, in three
phases: standing at the Kokiri Forest spawn ("stand"), a fixed scripted walk ("walk"), and standing at the walk's end
("stand2"), written stand / walk / stand2. Run-to-run noise is about ±0.5–1 ms, so smaller differences are not
results.

## The harness (`tools/harness/ab.py`)

From `tools/harness`: `../verify/verify.py with-lock -- uv run -q --with pillow --with numpy python ab.py SPEC.json`,
or several spec files back to back with `./queue.sh A.json B.json …` (log in `runs/queue.log`). A spec is a list of
runs: `label`, `desc` (shown in the window title), `cfg` (qt-config keys), `env`, `app`, `repeat`, `phase_frames`
(default 300), `variants` (live switches in one boot), `server_calls`, `jsdbg` (`attach`/`arm`).

- **Drives the game through Lichii's built-in debug server** (`EDEN_NX2_DEBUG_SERVER`, client `dbg.py`): input,
  memory reads, screenshots, log tail, captures. No pad server, no lldb, no screen access.
- **Decides state from memory, never from the picture:** the game's UI manager tells title / Load list / a save's
  dialog / loading / in game apart (slots 35+36 list, 38 dialog, 55 loading, HUD slot 0), the Load list cursor is
  read directly, and Link must stand at the configured spawn after the load. `main` moves every boot (ASLR): its
  address is read from each boot's log.
- **Save chosen by name** in `config.json` (`"save": "KokiriForest_Child"`: the newest save whose caption holds that
  map; an error if none) or by `"save_index"`.
- **Waits for calm, not for time:** measuring starts after 10 s without a pipeline build in the log; builds are
  counted per phase.
- **Catches stuck states:** no frame for 20 s while Lichii *and Apple's Metal compiler service* are nearly idle (a cold
  boot compiles shaders in `MTLCompilerService`, with Lichii itself at ~2%), menus not done in 150 s, a walk that moves
  Link under 0.5 m, a wrong save, a guest crash. Each leaves a stack sample or a screenshot, the debug server's status
  and the log tail; hangs, crashes and external kills are retried once. Runs without the debug server are refused
  (they could only be driven blind).
- **Unlimited speed until Link is in the game** (`speed_limit` through the debug server, from ~1 s after launch):
  menus and the load run at 120 fps (the display's vsync cap) instead of 60. Back on before anything is measured.
- **Debugger runs** (`"jsdbg"`): with `use_gdbstub` the guest is held at boot until a debugger continues it; the
  harness attaches the lldb driver `jsdbg.py` (from the separate glitch-research repository this one grew out of)
  only once the new log says the guest is held (a continue sent 0.07 s too early is lost and the guest waits
  forever).
- **Other spec options:** `args` (Lichii launch flags, e.g. `-f`), `server_calls` (debug-server tools after settling,
  e.g. `capture_bundle`, `trace_record`, `jit_clear`; the harness settles again before measuring), `settle_s`.
- **Window title** (main window only): `Lichii | <build> ‖ <session> · <run> · <attempt> · <step> ‖ <description>`,
  where `<session>` is the name set in `config.json`.
- Menus take ~2 s; launch to measuring ~40 s.
- Queue several spec files in **one** `queue.sh` call: separate waiters that wait for "no queue.sh running" match
  their own command lines and wait forever.
- Runs wait for builds of the project's trees (`wait_for_builds` in `ab.py`): builds first, measurements after.

## Results

### Debugging and measuring: free, except an attached debugger

| Run | stand / walk / stand2 | Verdict |
| --- | --- | --- |
| Default (several runs) | 20.2–21.3 / 20.1–21.0 / 18.5–19.5 | reference |
| Debug server polled 27×/s (memory reads) | 20.8 / 20.6 / 19.3 | no cost |
| `cpu_accuracy` Accurate (needed for lldb work) | 20.6 / 20.2 / 18.5 | no cost |
| GDB stub on + lldb attached through jsdbg, no breakpoints (run ab-20261117-192110) | 20.7 / 25.0 / 20.9 | **walk ~4 ms slower**, stand2 ~2 ms, load +2–5 s (46.2 s) |
| The same with jsdbg's per-frame breakpoints armed | 21.0 / 24.3 / 20.9 | same as attached: armed breakpoints add nothing on top |

### Docked vs handheld

| Mode | stand / walk / stand2 |
| --- | --- |
| Handheld (default) | ~20.5 / ~20.3 / ~19.0 |
| Docked | 26.1 / 25.1 / 23.4: about 5 ms (25%) slower |

### The Hypervisor CPU backend (`cpu_backend = Hvf`)

Lichii PR #1970's backend runs the game's ARM code directly in a virtual machine (Hypervisor.framework) instead of
recompiling it. It is compiled into the pinned build and not used. The work on it is unfinished; the fixes and speed
patches below are not in the pinned build.

**As shipped in #1970** (measured, run ab-20261117-160732), against the JIT with private caches:

- **Loads twice as fast** (spawn in ~22–25 s against ~42–47 s) and **no first-use hitches** (the ~0.8 s walk hitch of
  the JIT is absent: that hitch is the JIT recompiling after a cache flush).
- **3–5 ms slower per frame** (23.7–25.0 / 25.2–25.3 / 23.2–23.3, three runs). The GPU does the same work (same busy
  time, same command buffers) but idles 5.4–6.7 ms a frame against 2.2–2.8 ms with the JIT: the CPU side reaches its
  submits later.
- **Why:** ~385,000 VM exits a second from stores to GPU-cached pages (each interpreted one at a time, copying all 63
  registers through Hypervisor.framework), plus ~110,000 system calls a second. The hottest stores are the SDK's
  `memset` (`sdk+0x78f3c0`, ~80,000/s) and `memcpy` (`sdk+0x7bcf00`). Timer reads are only ~18,000/s.
- **The SDK hard-codes the 31.25 MHz tick rate** (`sdk+0x1663a0` returns it; conversions at `sdk+0x167a2c`/`0x167a64`;
  a check at `sdk+0x2b02e0`) and never reads `CNTFRQ_EL0`; its 45 `MRS CNTPCT_EL0` sites are all in `sdk`. Untrapped
  counters (the upper bound of a timer patch) froze the game, and timer exits cost only ~0.5 ms, so a timer patch is
  not worth it.
- **It renders wrong.** Plain Hypervisor on the unmodified app showed broken frames in motion (a dark band, a missing
  HUD) and once crashed at boot.
- An early experimental build that interpreted a run of following loads and stores per exit (burst), or whole fill
  and copy loops (loop runner), reached the 60 fps cap at the spot where unpatched Hypervisor ran 19.4–20.6 ms. That
  build was not checked for picture faults and is not the pinned build (patch:
  `patches/experiments/hvf-experiments-2026-11-17.patch`).

**The rendering fault** (measured):

- The store interpreter is not the cause: 1.26 million comparable instructions run against the Mac CPU gave no
  mismatch.
- A race: a write fault while a region is being cached takes the "leftover protection" branch at `arm_hvf.cpp:612`
  and leaves a GPU-cached page writable, so the GPU keeps stale data. Marking a page as GPU-cached before protecting
  it took the hits from 25 in about 2.5 minutes to 0 (run ab-20261117-203916).
- Lichii issues #1380 and #1381 as the cause: all write faults were interpreted and none fell back to invalidation,
  so #1380's race is not it; 1,500–10,000 read faults a second reopen cached pages, which points at #1381's
  read-trap window. Not settled.

**The fixed backend** with the race fix and the loop runner, burst and dirty-only speed patches, against the JIT with
private caches (two runs each, load average 7–11; run ab-20261118-000958):

| | Hypervisor, fixed | JIT, private caches |
| --- | --- | --- |
| Walk | 17.5 / 18.0 ms | 22.9 / 21.8 ms |
| Standing | 16.7 / 16.7 ms | 18.9 / 18.2 ms |
| Worst frame | 34 / 27 ms | 653 / 452 ms |
| Spawn | 20 s | 44 s |

About 120,000 exits a second. Loop runner off: walk 23.4 / 23.9 ms; loop limit 64–4096: 17.4–17.8 ms; burst 32:
17.8 / 17.3 ms; dirty-only off: 17.5 / 17.4 ms.

**Picture check of the fixed backend** (run ab-20261118-002819): 2 of 26 Kokiri Forest pictures corrupt (rainbow
shards; 30% clipped white), silent in the logs; the JIT 0 of 15. That is why it is not adopted. It was never
compared with the shared JIT cache. The open steps are in [TRACKER.md](../../TRACKER.md), "Open".

### Render switches (batch 2b): the defaults are the fastest

| Switch | stand / walk / stand2 | Against default (~20.5–21.3 / 21–22 / 19–19.5) |
| --- | --- | --- |
| Switch 2 draws: Wait (default Bounded) | 20.6 / 22.9 / 19.8 | none |
| Mesh shaders: Compute | 23.5 / 23.2 / 21.2 | ~2 ms slower; first boot 40 s (builds the compute versions) |
| Mesh shaders: Native | 20.3 / 21.3 / 19.1 | none (Automatic is native already) |
| No mesh draws (`EDEN_NX2_NO_MESH`, diagnostic) | 19.9 / 21.1 / 18.9 | ~0.5–1 ms: mesh foliage costs little now |
| GPU accuracy High | 24.4 / 24.7 / 22.7 | ~3–4 ms slower |
| Native compute write mark Full | 24.9 / 23.7 / 21.0 | ~2–4 ms slower |
| Top mip only (`EDEN_NX2_FORCE_LOD0`, diagnostic) | 21.2 / 22.6 / 19.8 | none |

### Present, clocks and shader maths (batch 3)

| Switch | stand / walk / stand2 | Verdict |
| --- | --- | --- |
| Default (batch 3 reference) | 20.5 / 22.1 / 20.0 | |
| vsync Immediate (default Fifo) | 20.8 / 21.7 / 19.5 | none: the game is GPU-bound below 60 fps |
| `EDEN_NX2_FRAMES_AHEAD=0` | 20.7 / 21.5 / 19.7 | none (the switches file's "30.9 against 38.9 fps" does not reproduce) |
| GPU clock Normal (default Boost) | 24.6 / 24.3 / 21.1 | ~2–4 ms slower: the game picks more work when it thinks its GPU is slow |
| GPU clock Overclock | 21.0 / 22.3 / 19.5 | same as Boost |
| CPU clock Boost (default Normal) | 21.2 / 21.9 / 20.0 | none: not CPU-bound |
| Keep-encoder (`MVK_P60_KEEP_ENCODER`) | 18.1 / 21.3 / 17.7 | **~2–2.5 ms faster**: the default (below) |
| Fast math never (`MVK_CONFIG_FAST_MATH_ENABLED=0`) | 40.6 / 44.9 / 39.9 | **about 2× slower**, no pipeline builds during it: the default on-demand fast math is worth a lot |
| Fast math always (run ab-20261117-192758) | 18.6 / 21.6 / 18.1 | **no gain** over the default (same range as the plain runs that day); its first boot recompiles every shader (177 s, ~8 min fully cold), so not worth switching |

### Properties-dialog settings (batch 4, keep-encoder on)

Reference: 18.2 / 22.0 / 18.3. Runs marked * overlapped a variant build (load average ~10), so their numbers are
not results; they need a run on a quiet machine. Later reruns of the starred runs matched the reference
([TRACKER.md](../../TRACKER.md), "Tried and not adopted").

| Setting | stand / walk / stand2 | Verdict |
| --- | --- | --- |
| Switch 2 draws: Skip | 18.0 / 21.1 / 18.0 | none |
| Pipeline wait per frame 2 / 16 ms | 18.3 / 20.5 / 18.0 · 17.8 / 21.6 / 18.4 | none (cache is warm) |
| Frame pacing 60 | 17.9 / 21.8 / 18.1 | none |
| GPU fence Immediate | 17.9 / 21.9 / 18.3 | none (it is what Default does) |
| GPU fence Balanced | 22.0 / 22.7 / 20.7 | ~2–4 ms slower |
| GPU fence Accurate | 56.3 / 53.8 / 46.3 | **2.5–3× slower**: the CPU waits for every GPU fence |
| DMA accuracy Unsafe / Safe | 18.6 / 22.6 / 18.1 · 17.8 / 21.7 / 17.9 | none |
| Sync memory operations | 18.4 / 21.3 / 18.1 | none |
| Precache shaders: Always | 17.8 / 21.4 / 18.0, p99 158 ms | **don't use**: hitches while it precaches in the background, and it once crashed Lichii 72 s in (stack overflow in SPIRV-Cross on a `VkShaderDriver` thread, deep `emit_block_chain` recursion; reported as MoltenVK issue #2907) |
| Reactive flushing off | 17.7 / 22.0 / 17.9 | within noise, and **likely renders wrong**: the Switch-2-only variant (`EDEN_NX2_NO_REACTIVE=1`, batch 5) washed the fog out to near-white with faded colours (watched) |
| Barrier feedback loops off | 18.0 / 21.2 / 18.1 | none |
| ASTC decoded on the CPU | 17.5 / 21.0 / 17.7 | maybe 0.6–1 ms faster; one run, unconfirmed |
| Anisotropic 16x | 19.0 / 21.0 / 18.2 | ~0.8 ms slower standing |
| VRAM usage Aggressive | 18.0 / 22.0 / 20.4 | none (stand2 disturbed by a build) |
| Async presentation off * | 18.3 / 26.8 / 23.9 | unsettled |
| Async shaders off * | 18.7 / 22.0 / 18.4 | unsettled |
| Vertex input dynamic state off * | 24.0 / 27.1 / 22.2 | unsettled |
| CPU accuracy Unsafe * | 22.7 / 24.9 / 21.3 | unsettled |

Not run, and why: Force maximum clocks (only on AMD, NVIDIA and Intel Windows drivers), ASTC recompression
Uncompressed (only for GPUs without ASTC), buffer history (a Burnout bloom fix), frame pacing 30 (a cap).

### Tooling checks

| Tool | Result |
| --- | --- |
| Bug-report bundle (`capture_bundle`) | works: 24 MB zip in 6.6 s (logs, settings, screenshot, frame times, frame capture with shaders) |
| GPU trace (`trace_record`, 120 presents) | works: the call returns at once and records in the background; 120 presents, a 2.3 GB `.lxtrace` (3,981 MiB before compression). Offline replay (`eden-cli --replay`) works too ([`tools/speckcheck`](../../tools/speckcheck/README.md)) |
| `record_frame_times` | writes nothing under `kill -9` (flushed on a clean exit only); the harness's own frame clock replaces it |

### Keep-encoder: on by default

`MVK_P60_KEEP_ENCODER` (MoltenVK patch 0007) lets a blit or plain compute encoder stay open across a pipeline
barrier instead of closing and reopening it (~1,070 encoders a frame). Measured 18.1 / 21.3 / 17.7 against
20.5 / 22.1 / 20.0: **about 2–2.5 ms a frame faster standing**. Review of the code (`MVKCommandBuffer.mm`,
`MVKCmdPipeline.mm`): kept compute encoders are serial (`MTLDispatchTypeSerial`; only occlusion-query accumulation
is concurrent and it is never kept), the game's memory sits in hazard-tracked heaps so Metal orders blits within an
encoder, cross-stage barriers become fence waits on the open encoder (which over-synchronises, never under), and the
deferred own-stage fence update is applied on every encoder end. A watched run showed no wrong or flickering
picture.

Since 2026-11-17 it is **on by default** (MoltenVK patch 0008); `MVK_P60_NO_KEEP_ENCODER=1` turns it off. Runs from
batch 4 on are measured with it on.

### The walk hitch is a full flush of the JIT code cache

Lichii's stutter trace (`EDEN_NX2_STUTTER_TRACE=1`, `EDEN_NX2_STUTTER_DETAIL_MS=200`) reports, per long frame, the
time the dynamic JIT spent compiling. The ~0.75 s hitch on the walk is `jit=ms:734.6 … clears:1, full:1`: the code
cache filled up and was flushed whole, and 6,581 blocks were compiled again on the spot. On ARM hosts each core's
cache is fixed at 128 MiB (`arm_dynarmic_64.cpp:402`; 512 MiB on x86), most likely because ARM64 direct branches
reach ±128 MiB. A bigger cache needs dynarmic's ARM64 backend to branch further first; the shared JIT cache does that
with veneers and removes the hitch ([shared-jit-cache](../shared-jit-cache/README.md)). The load itself compiles
100,000+ blocks (0.5–2.7 s of JIT time per long frame).

**It does not happen in every run.** The same configuration hitches in one run and not the next (four
configurations, two runs each: 534 ms then 50 ms; 558 then 52; 648 then 52; 67 then 765), and only 2 of 11 runs
with 600-frame phases hitched. Whether the cache fills during the walk depends on how much was compiled before it.
So walk p99 / max / mean in single runs are a coin flip; compare walk medians, or count hitches over several runs.

Over 5 runs of the default build on the Kokiri walk with turns (run ab-20261117-224835), each slow frame's cause
from the stutter trace (`tools/diag/stutter.py RUN…`):

| Run | Worst walk frame | Slow frames | JIT time in them | Pipeline builds | JIT full flushes |
| --- | --- | --- | --- | --- | --- |
| r1 | 389 ms | 37 | 1,995 ms | 0 | yes |
| r2 | 66 ms | 12 | 247 ms | 0 | no |
| r3 | 457 ms | 44 | 2,363 ms | 0 | yes |
| r4 | 363 ms | 30 | 1,619 ms | 0 | yes |
| r5 | 370 ms | 42 | 2,034 ms | 0 | yes |

The hitch is the JIT code cache filling, being flushed and recompiling: every hitched walk logged a full flush and
1.6–2.4 s of JIT time in its slow frames, the clean walk none; no run built a pipeline. 4 of 5 hitched on this route.
GPU-side time in the slow frames (unattributed, buffer, texture, fences) is 0.5–0.7 s and present in the clean run too.

### Windowed against fullscreen: two pairs

Standing after the walk, p50 / p90 / p95 ms: pair 1 windowed 18.4 / 21.2 / 22.0, fullscreen 17.8 / 20.5 / 21.4; pair 2
windowed 18.7 / 22.2 / 23.9, fullscreen 17.9 / 20.0 / 21.3. Fullscreen (`-f`) is ~0.6–0.8 ms faster at the median and
more at the tail in both pairs: small, probably real. It is a launch choice, not built in.

Pair 1 (run ab-20261117-190501), all phases:

| Run | Stand (median) | Walk (median / p99) | Stand after |
| --- | --- | --- | --- |
| windowed | 18.9 ms | 22.2 / 142.7 ms | 18.4 ms |
| fullscreen (`-f`) | 17.4 ms | 21.4 / 193.2 ms | 17.8 ms |

Both walks have the usual JIT hitch. For scale, the two standing phases of one control run differed by 2 ms.

### Where the GPU's idle time goes

The back GPU thread (the one that feeds Metal) is idle 12–14 ms of every frame (`EDEN_NX2_BACK_IDLE_TRACE=1`).
By what the front thread was doing meanwhile: waiting on a GPU semaphore 6.4–7.5 ms, finding no work submitted yet
3.3–3.8 ms, parsing 1.4 ms, copying command lists 1.1–1.2 ms. In 10 s the front waited 34,206 times on semaphore
acquires (487 ms) and 17,446 times on list writers (749 ms): the game's GPU channels wait on semaphores that other
channels' work releases, so the pipeline drains each time. This is the main structural lead for the GPU idle gap;
no change has tested it yet, so the cause is not settled (see [mac-performance](../mac-performance/README.md),
cause 5).

### The RNG seed (`rng_seed_enabled`, `rng_seed`)

**What it controls** (read from the source): the process's random entropy (`k_process.cpp:123`, what games usually
seed their own random generators from, through `svcGetInfo`), the `spl` service's random bytes
(`spl_module.cpp:23`), and the ASLR offset at which `main` and the other modules load
(`deconstructed_rom_directory.cpp:499`).

**Measured** (two seeded runs with seed 12345, two unseeded, same scripted input):

| | Seeded | Unseeded |
| --- | --- | --- |
| `main` load address | `0x80059000` both runs | `0x80875000`, `0x802e7000` |
| Link's final position | identical (0.0000 m apart) | identical (0.0000 m apart) |
| Stand-1 screenshots | mean grey diff 6.0, 1.4% of pixels >40 | mean grey diff 7.8, 2.2% of pixels >40 |

- **Fixed addresses across boots.** With a seed, every address in the game (symbol maps, debugger breakpoints,
  memory watchers) is the same each boot, instead of moving with ASLR. Useful for any memory or debugger tooling.
- **Link's movement is repeatable without a seed**: the harness's frame-exact input and the game's fixed 1/60 s step
  already give the same position to the millimetre.
- **The picture is not pixel-identical either way**: leaves, fireflies, particles and Navi differ between runs, seeded
  or not, so the game's visual randomness has another source (likely host timing).
- **Not tested yet: gameplay randomness** (item drops, enemy behaviour, quest outcomes that the game decides at
  random). If the game seeds those from the process entropy, a fixed seed makes them repeatable, which matters for
  routes and setups that depend on a random outcome. Test: the same scripted action twice per seed (for example cut
  the same grass or pots and read the drop from memory or from the sloperinaGZ practice mod's flag log), seeded
  against unseeded.

### A JIT flush after loads (not adopted)

About 90% of the 128 MiB code cache is dead when it fills: before the mid-walk flush, at least 1,021,000 blocks had
been compiled and 127,693 invalidated (39 MiB of game code), while recompiling the live set afterwards took ~78,000
blocks. So the flush is right but badly timed. `patches/experiments/lichii-jit-flush-2026-11-17.patch`:
`EDEN_NX2_JIT_FLUSH_ON_STALL=<ms>` flushes every core's JIT once the guest presents nothing for that long (a load),
at most once per 30 s (detected in `Core::RecordGuestPresent`, done by each core in `ArmDynarmic64::RunThread`), and
the debug server gains `jit_clear`.

**Not adopted**, with the other small JIT tweaks: the per-compile log below shows the bigger lever is sharing
compiled code between cores. The switch is in the pinned build (Lichii patch 0007), off unless set.

A/B runs with the stutter trace, on an older MoltenVK and on the current one (`tools/diag/stutter.py` reads
the stutter trace per phase; walk max frame and frames over 50 ms):

| Run | Old MoltenVK (run ab-20261117-183738) | Current MoltenVK (run ab-20261117-190501) |
| --- | --- | --- |
| jit-control | 57 ms, 3 | 66 ms, 6 |
| jit-stall-flush | 77 ms, 4 | 70 ms, 4 |
| jit-manual-flush | 126 ms, 11 | 99 ms, 11 |

- **The control never hitched,** so these runs can't say whether a flush prevents the hitch: none of the six had a full
  cache flush during the walk.
- **The stall trigger fired at the wrong time:** once per run, during boot (10 s, 32 s), never after the map load.
- **A manual flush before the walk makes the walk worse:** the walk recompiles what it needs (1.2–1.4 s of JIT time in
  slow frames against ~0.4 s), twice as many frames over 50 ms, worst frames ~100–126 ms. Still far better than a
  full-flush hitch (500–950 ms).

### Where the JIT's compile time goes (per-compile log)

A test build with `patches/experiments/dynarmic-jit-log-2026-11-17.patch` (switch `EDEN_NX2_JIT_LOG=<file>`) logs
every block dynarmic compiles: core, guest address, time in each phase. One boot from the title through the load and
the stand/walk/stand phases (run ab-20261117-190501, summary made by `tools/diag/jit.py log`):

- **2.63 million blocks in 71 s, 32.3 s of compile time** summed over the 6 cores (4.5–7.8 s per core; core 0 most).
- **78% of it is repeats.** Only 642,000 distinct blocks: 252,500 of them were compiled on all six cores, and each core
  also recompiled some after invalidations and the one full flush. A code cache shared by all cores (the design of
  Lichii PR #2101, x86 backend only) would have saved about 25 s of the 32 s.
- **Emitting Mac code is 70%** of a compile (22.5 s); decoding the guest code 9%, IR optimisation 8%, linking and
  icache 13%. Blocks are small: median 10 IR ops, ~12 µs each.
- **96% of the blocks are in `main`** (the game), 4% in `sdk`; the costliest 4 KiB page took 81 ms.

By harness step (lined up through `frames.bin` and the menu trace; later runs record both clocks in `result.json`):

| Step | Wall | Blocks | Compile, summed over cores | Busiest core compiling |
| --- | --- | --- | --- | --- |
| Game start → title (boot) | 12.0 s | 734,000 | 8.4 s | 2.5 s (20%) |
| Title → loading screen (menus) | 3.4 s | 166,000 | 1.6 s | 0.3 s (9%) |
| **Map load** (loading screen → in game) | **19.8 s** | **1,394,000** | **18.2 s** | **3.3 s (16%)** |
| In game → stand (settle) | 15.1 s | 71,000 | 0.9 s | 0.2 s (1%) |
| Stand | 5.8 s | 1,300 | 0.03 s | 0% |
| Walk (the full-flush hitch) | 9.3 s | 262,000 | 3.1 s | 1.9 s (20%) |

So during the map load no core spends more than ~3.3 s of the 19.8 s compiling: even a free JIT would shorten the load
by at most about that much (16%), and a shared cache (which removes the repeats, not the first compiles) by less. The
rest of the load is the game itself running and the GPU side. The run booted cold (the Metal cache missed; 470 s),
which delays the JIT's start but doesn't change what it compiles. The 19.8 s is measured from the loading screen to
Link in game in this one run; the harness's "load − boot" figure in [shared-jit-cache](../shared-jit-cache/README.md)
(26.1–26.6 s without the shared cache) spans more of the menus and is a different measure. Note: Lichii's
`steady_clock` (the JIT log's clock) is `CLOCK_MONOTONIC_RAW`, which counts sleep; `frames.bin` uses
`CLOCK_UPTIME_RAW` (24,255 s apart on the test Mac).

### Compiler builds: no clear winner (2026-11-17/18)

All on the same MoltenVK (#2901 + cull fix, `17f76f69f2`), so only how Lichii is compiled differs; Kokiri walk with
turns; load average 11–16 throughout (other work on the machine). p50 / p90 / p95 ms; ⚡ = walk hitched (JIT flush).

| Build | Stand, run 1 | Stand, run 2 | Walk, run 1 | Walk, run 2 |
| --- | --- | --- | --- | --- |
| Default (Apple clang 21, `-O3`, no LTO) | 19.1 / 22.4 / 24.5 | 18.9 / 22.1 / 24.1 | 23.0 / 32.0 / 37.0 | 23.4 / 33.2 / 40.8 |
| Apple clang + ThinLTO + apple-m4 | 19.1 / 22.3 / 23.9 | 18.9 / 22.0 / 24.2 | ⚡ | 22.7 / 31.9 / 36.2 |
| Upstream LLVM 23 + ThinLTO (lld) | 20.2 / 25.3 / 27.7 | 18.0 / 21.3 / 22.9 | ⚡ | 21.9 / 29.1 / 34.0 |

Apple PGO (spec `pgo-compare`, before the cull fix): default 18.2 / 19.6 / 20.4 and 17.2 / 18.3 / 18.9 standing,
PGO 16.4 / 20.4 / 21.2 and 17.4 / 19.2 / 20.5: the pairs disagree and every difference is within ~1 ms.

**Verdict:** no compiler build is clearly better than the default build; the differences flip between runs and stay
within about 1 ms, on a busy machine. Apple PGO was dropped (by the rule "only if clearly better") and LLVM PGO
never built. The pinned build keeps the default compiler setup. Settling the last millisecond would need a quieter
machine.

### Compiler builds: how they are built

Built with `tools/harness/build-variants/prebuild-variants.sh` into separate apps: Apple clang with ThinLTO and
`-mcpu=apple-m4`; Homebrew LLVM 23.1.5 (needs `-include cstdlib` because newer libc++ no longer brings in
`std::abort` for sirit); Homebrew LLVM with LTO; and a PGO pair, one instrumented and one optimised with a profile
trained on one long standard route (`build-variants/pgo-pipeline.sh`).

Build details: PGO-use builds pass `-Wno-backend-plugin` (a stale profile for a few standard-library functions failed
SPIRV-Tools' `-Werror`); upstream-LLVM LTO links Lichii with lld (Apple's ld64 can't read upstream bitcode) and turns
off clang's Objective-C selector stubs, which lld can't link yet; MoltenVK in those variants is built without LTO (its
External libraries are Apple bitcode). A failed variant fails the script, so a pipeline can't go on to measure a build
that doesn't exist. Every new libMoltenVK makes its first boot cold, so boot and load are compared on each build's
second run.

### Other findings

- With the emulation speed limit off, menus and the load run at 120 fps (the display's vsync cap) instead of 60.
- Lichii hung at boot twice with everything idle (once after the intro video's decoder started, once while loading
  pipelines); stack samples were kept with those runs.
- A run was killed from outside once (a `pkill` from another script); the harness retries such runs.

### Parallel shader compiles at boot (tested 2026-11-17)

A cold Metal cache makes boot slow because MoltenVK's `MVKPipelineCache::readData` (`MVKPipeline.mm`) compiles every
library in Lichii's saved pipeline file (~4,700 records, 403 MB) one at a time with `compileLibrary`: one
`MTLCompilerService` at 100% and the other cores idle. It happens after any macOS / Metal / MoltenVK update, a new
compile option (fast math), or a different MoltenVK build. Variants tried: a parallel load written for this test
(`readData` reads all entries, compiles the libraries with `dispatch_apply` capped at the core count, then inserts
them in order; `patches/experiments/moltenvk-pown-vs-path60-2026-11-17.patch`),
`MVK_CONFIG_SHOULD_MAXIMIZE_CONCURRENT_COMPILATION=1` (env only; off by default, Lichii does not set it), and the
upstream MoltenVK PRs [#2901](https://github.com/KhronosGroup/MoltenVK/pull/2901) (open, 2026-11-10: keeps each
library's MSL and compiles it on first use, so `vkCreatePipelineCache` returns at once) and
[#2905](https://github.com/KhronosGroup/MoltenVK/pull/2905) (open, 2026-11-17: stops a shared pipeline cache's lock
from serialising compiles across threads). Metal binary archives are no help for the boot: they skip pipeline builds
(4.4–5.2 s → 1.6 ms for a big render pipeline) but not the source → library step the boot waits on.

Cold boot = an empty Metal cache (the real one held aside and restored); first boot = the variant's first boot on the
real cache (a new libMoltenVK starts partly cold, see below). Frame times p50 / p90 / p95 in ms; ⚡ = the walk hit the
JIT flush; "load" = another `-j 10` build was running (load average 10–14).

| MoltenVK | Cold boot | First boot on the real cache | Stand | Walk |
| --- | --- | --- | --- | --- |
| Current (one at a time) | 455–483 s | 206 s | 18.5 / 20.3 / 21.3 | 22.8 / 35.2 / 47.7 ⚡ |
| Parallel load | 89.5 s | 71.5 s | 18.3 / 19.4 / 19.7 | 21.1 / 28.7 / 33.0 |
| Parallel load + `MVK_CONFIG_SHOULD_MAXIMIZE_CONCURRENT_COMPILATION` | 88.7 s | — | 18.5 / 19.7 / 20.1 | 21.7 / 34.0 / 47.6 ⚡ |
| #2901, compile on first use | 78.8 s | **15.4 s** | 17.8 / 19.2 / 20.2 | 21.2 / 28.9 / 33.0 |
| #2905 only | — (doesn't change the load) | 14.4 s | 25.0 / 36.0 / 38.3 (load) | 34.2 / 46.2 / 57.8 (load) |
| #2901 + #2905 | **76.7 s** | 20.8 s (load) | 17.8 / 18.8 / 19.3 | 21.2 / 29.6 / 34.4 |

- Every parallel variant cuts a fully cold boot ~5–6×. #2901 is best because it compiles only the shaders the boot
  uses (Lichii builds its cached pipelines at boot), and it also makes a new MoltenVK's first boot near-normal.
- The concurrent-compilation switch adds nothing; #2905 adds ~2 s on top of #2901.
- No variant changes frame pacing in these runs (the #2905 run was measured under the other build's load). None of the
  walks built a pipeline.
- Moving (Gerudo Valley, stutter trace): warm, #2901 walks like the base build (p90 19.5 / p95 23.5 ms against
  21.9 / 27.1). A first cold-cache reading gave #2901's walk 58 slow frames against 11 for the parallel load, but
  those walks pushed Link into a cliff. Redone with turns (run ab-20261117-224835): from a cold cache #2901 walks no
  worse than the parallel load (p90 24.4 against 26.3 ms, 20 against 28 slow frames, no pipeline builds), and warm
  like the base build (p95 26.2 against 27.4 ms).
- **Any rebuilt libMoltenVK makes the next boot cold**, even with identical shader code (seen with a rebuild that
  added a progress log): the Metal cache depends on the MoltenVK binary. Compare boot and load on a build's second
  boot. MoltenVK also stamps its pipeline-cache identity with the git commit it was built from, so a library built
  from a different commit invalidates Lichii's stored pipeline file as well (334 s boot measured on 2026-11-19);
  `build.sh` produces the same commit ids on every rebuild.

**Safety: the concurrent variants corrupt the picture now and then.** Of 186 run screenshots on 2026-11-17, three are
blown out (white bloom, rainbow colours): a cold boot of the parallel load (21% clipped white), a warm boot of
#2901 + #2905 (44%), and the known run with reactive flushing off. So the two builds whose shader compiles run
concurrently broke 2 of ~9 runs, silently (no compile or Metal error in the logs); no other build did in 150+. Likely
a race in the concurrent compile path (unconfirmed). #2901 alone (compiles still serialised under the pipeline
cache's lock) was clean in 14 of 14: 8 runs plus 6 safety boots (spec `p2901-safety`, not kept; `tools/harness/specs/cold-boot.json` repeats its cold and warm boot on the pinned build: 3
cold, 3 warm, every screenshot scored by the harness's `clipped_pct`, worst 2.95%). Cold boots 99.7–100.7 s; a warm
boot right after another 17.5 s.

**In the pinned build:** MoltenVK with #2901 and the mesh cull-mode fix (library `17f76f69f2`; patches
`patches/moltenvk/0009-Merge-MoltenVK-PR-2901-frankea-Compile-pipeline-cach.patch` and
`patches/moltenvk/0010-mesh-apply-the-pipeline-s-cull-mode-to-mesh-draws.patch`; #2901 adopted 2026-11-17 23:25, the
cull fix 23:55), keeping keep-encoder and the mesh fixes. It has no pipeline-cache progress log (nothing to report:
the load no longer compiles). The cull-mode fix removes the white specks at the cave wall: in the run that found the
fault, 0 of 30 frames speckled with the fix and 28 of 30 without; in an independent check with a separate build of
the same patch, the unfixed reference had 27 of 30 and the fixed build 0 of 30 twice, same spot; standing
17.1 / 20.0 / 21.5 ms p50 / p90 / p95 on the warm run, no visible frame cost
([mesh-white-specks](../mesh-white-specks/README.md)). The 78.8 s cold boot of the #2901 test build and the
97.4–100.7 s of the pinned build come from different apps and runs; the difference was not looked into. The parallel
load and #2905 are not used until the race is found.

**Warm boots across many MoltenVK builds aren't comparable:** each build keeps its own copy of every shader in the Metal
cache, which grew to 2.4 GB (`libraries.data` ~1.1 GB, rewritten on the fly), and older entries get evicted, so a build
that booted warm before can come back partly cold (30–65 s). Boot two runs of the same build back to back to compare.

### A JIT code cache shared by all cores (in the pinned build since 2026-11-18)

Ported to dynarmic's arm64 backend and validated against the build without it: walk hitches 3/3 → 0/3, walk p95
46–51 → 28–30 ms, map load ~3 s faster, memory ~3–4 GB lower, standing frames unchanged. On through
`EDEN_NX2_SHARED_JIT_CACHE=512` in the app's `nx2_switches.txt`. Full write-up:
[shared-jit-cache](../shared-jit-cache/README.md); tools in [`tools/jit-cache`](../../tools/jit-cache/README.md) and [`tools/diag`](../../tools/diag/README.md).

## Open

- Not started: resetting Link's position from memory, sloperinaGZ checks, Lichii-side pipeline sharding (save the
  pipeline cache as N files, load each into its own `VkPipelineCache` on its own thread, `vkMergePipelineCaches`; first
  check that MoltenVK loads caches safely in parallel), and finding the race in the concurrent shader compiles (the
  parallel load, PR #2905). The GPU trace replay works (`tools/speckcheck/replay.sh`).
- The Hypervisor backend: see above and [TRACKER.md](../../TRACKER.md), "Open".
