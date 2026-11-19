# Walk tail: why walking frames at p95 and p99 are slow

Unfinished. Question: what makes the slow frames of a walk in the pinned build, and which of them the emulator can
remove. State on 2026-11-19: the p95 frames are ordinary frames with more work in them; the p99 frames have three
causes. Two of them fall by half or more when the Mac's other programs are closed; what is left of them, and the
base cost that keeps the Kokiri Forest median at 19.5 ms, are open. No change tried here has lowered p95 or p99.

Measured on the pinned build (Lichii `a1ee50a6ef`, MoltenVK `dc964d4011`) and on a test app made from it, Apple M4
Pro (10 performance cores), macOS 27.0.1, 1,800-frame walks kept within 9 m of the Kokiri Forest spawn
(`"leash_m": 9`), 1x, handheld. Run folders named `ab-…` are local run data and are not tracked. Readers:
[`tools/diag`](../../tools/diag/README.md).

Two rules for every figure here: other programs are closed before a tail figure is quoted, and p99 is compared only
between walks of the same length on the same route.

## The slow frames

| Frames | Cause | Evidence |
| --- | --- | --- |
| p95 (22-26 ms) | Frames with more commands in them, not hitches: 46 command buffers against 40, about 10 % more encoders. 62-69 % of their excess over a normal frame is GPU idle between hand-offs, the rest more GPU work. JIT compile time is 0.3 ms in them, as in a median frame | `gpu.py frames` on run ab-20261119-090328 (walkcap-gpu-r1/r2); `stutter.py split` on run ab-20261119-090845 |
| p99, cause 1 | JIT first-touch compiles: 340-2,008 blocks and 7-39 ms of compile time in the frame. They fall on the same frame numbers of a repeated route (3, 17 or 20, 184, 447, 464), and a new movement brings new ones | `gpu.py sync` on runs ab-20261119-093044, -095225 |
| p99, cause 2 | A GPU command buffer that occupies the GPU for 8-21 ms with 0.1-3 ms of pass work in it. The time is one gap between two consecutive encoders, and the gap has two sizes: 7-11 ms or about 20 ms, nothing between 2 and 7 ms. 14 of 26 fall after one compute pass and before the 16384x16384 pass, the rest after a blit and before the next render pass. Up to five guest threads then wait 6-10 ms each in `FinishReadDownloads` | per-encoder records of the test app, runs ab-20261119-094316 (probe-encoders-r1), -104210 (gaps-1ms) |
| p99, cause 3 | The next frame's commands arrive 9-23 ms late with the GPU idle. In those frames the game runs no more code than usual, and several of its worker threads, each pinned to one core, are ready without a core for about 10 ms or about 20 ms at the same time | `gpu.py slow`; per-frame thread reports of the test app, run ab-20261119-094316 (probe-threads-r1) |

Per walk, with other programs open (7 walks) against closed (5 walks, run ab-20261119-095225; Claude's own app
still running):

| | Open | Closed |
| --- | --- | --- |
| GPU waits of 8 ms or more | 21-58 | 4, 7, 19, 9, 9 |
| Read-wait frames (cause 2) | 5-14 | 1, 0, 4, 3, 2 |
| Silent-gap frames (cause 3) | 9-17 | 8, 4, 4, 2, 7 |
| JIT compile frames (cause 1) | 5-13 | 14, 7, 10, 8, 7 |
| p99 | 29.4-33.0 ms | 28.8, 26.9, 28.3, 27.3, 28.0 ms |

The median does not move (19.3-19.7 ms closed). The emulator itself uses 7.3 of the 10 performance cores while
walking (`tools/diag/threadcpu.py`, run ab-20261119-104210 cpu-threads): the six guest core threads 4.29, the GPU
back thread 0.82, the GPU front thread 0.74, the Vulkan worker 0.50, unnamed threads 0.56. That leaves under three
cores for everything else on the machine, which fits causes 2 and 3 growing with other programs open; both gap sizes
of causes 2 and 3 are multiples of about 10 ms, the length of a macOS scheduler time slice, and nothing here shows
directly that a time slice is the mechanism.

Ruled out, each by a run: the frame profiler as the cause of the stalls (they occur with the sync trace alone); the
harness's debug-server calls (17 silent-gap frames with a call every 120 frames against 9 and 15 with one every 30);
texture cache churn (events are five times sparser around a stalled command buffer); guest file reads (none over
1 ms); late timers and slow core wake-ups (p99 under 0.1 ms and 20 us); memory faults as a direct cost (about 1.7 us
each).

## The base cost: GPU idle between hand-offs

A walking frame has about 5.4 gaps in which the GPU has nothing to do, 3.5-3.9 ms a frame in all, and the GPU is busy
for about 15 of a median frame's 18.9 ms. Over a whole run the emulator submits to the GPU 28-29 times a frame (the
sync trace's `flush` event names the line that asked): 13-14 deferred submissions pushed out at once
(`vk_scheduler.cpp` `FlushDeferred`: a report fence is deferred and then submitted by the next line of
`SignalFence`), 8 from the 128-draw budget, 2-3 from fences and 2 from buffer reads. The fence hold-back window
(`EDEN_NX2_FENCE_FLUSH_US`) only moves submissions from one of those lines to another: 29.3 a frame at 500 us, 26.8
at 2,000 us (run ab-20261119-120851). Almost all of the
emulator's waits for the host GPU are one call, `InnerFence::Wait` (`vk_fence_manager.cpp:51`, shown by the caller
stamp of `patches/experiments/lichii-gpuwait-caller-stamp-2026-11-19.patch`, run ab-20261119-110937 callers-1/2):
8.6 waits a frame, 8.5-9.0 ms of waiting a frame, of which about 1.05 ms overlaps GPU idle.

One round trip of such a wait: the GPU finishes, the waiter wakes 96 us later (median), and the next flush reaches the
GPU 249 us after that. MoltenVK adds a fixed 0.3-0.4 ms per command buffer whatever is in it (42 command buffers a
frame). Per second the emulator signals about 11,300 fences, skips about 8,500, and makes 2,400-2,800, of which
2,200-2,500 carry a query report the game waits for. A comment in the source says that answering those reports early
gave white flashes.

Gerudo Valley holds a 16.6 ms median with a tail that is almost all JIT compiles (run ab-20261119-104210 gerudo), so
the base cost above is a property of the Kokiri Forest scene, not of every area.

## The JIT compiles

A walk compiles 34,269 blocks (`DYNARMIC_JIT_TRACE` recording, run ab-20261119-090845 walkcap-jitrec;
`tools/diag/jit.py trace`):

| What | Figure |
| --- | --- |
| First compiles / recompiles after a memory fault | 73 % / 27 % |
| Blocks that are the fixed successor of a block compiled before | 69.8 %; 84 % of those became known less than 1 ms before they were needed |
| Guest instructions that an earlier block already covers | 44 % |
| Median block | 4 guest instructions |
| Cost of a compile | 1.6 us fixed plus 0.62 us per IR operation; emitting is 70 % of it |
| Frame delay per ms of compile time | about 1.1 ms |
| Where compile time goes (offline profile of replayed compiles) | register allocator 34.6 % (`UpdateAllUses` 15 %, `ValueLocation` 8 %), IR bookkeeping 20.3 %, `malloc` 10.4 %, instruction encoding 3.2 % |

What follows from it: compiling ahead of first use has nothing to work with (the targets are known under 1 ms early);
one emit region per core would save at most the lock wait, 0.26 ms of about 12 ms in a compile frame; the recompiles
after a fault are the removable quarter.

## Changes tried

Each is a switch of the test app (`build-test-app.sh`), off unless set, and none is in the pinned build.

| Change | Switch | Result |
| --- | --- | --- |
| No recompile after a memory fault: the access keeps taking the fault | `EDEN_NX2_FASTMEM_NO_RECOMPILE` | The game does not get past loading in 6 minutes (run ab-20261119-105846). Dropped |
| A faulting access is patched in place to call the slow memory callback | `DYNARMIC_FASTMEM_PATCH` (first form, no longer built) | Median 37.6 ms: the patch ran 1.19 million times in a walk and the callback is the cost (run ab-20261119-110937 jit3-patch-1/2). Dropped |
| Fast stub: every direct access carries an out-of-line page-table lookup, and a faulting access is patched to branch to it; the block is kept | `DYNARMIC_FASTMEM_PATCH` | 33 % fewer compiles, 43 % less compile time, half the compile time in the slowest 2 % of frames, code cache 2 % larger, pictures clean; the median rises 0.3-0.5 ms. p99 unchanged: 28.9, 30.2, 30.3 ms against the controls' 31.8, 28.5, 29.0, 30.2 ms (runs ab-20261119-112513, -115601). Dropped |
| GPU hand-off threads at the guest core threads' priority | `EDEN_NX2_GPU_THREAD_PRIO` | No change (run ab-20261119-113229). Dropped. That the priority took effect was not checked separately |
| A thread waiting for the host GPU polls 300 us before it sleeps | `EDEN_NX2_GPUWAIT_SPIN_US` | No change, alone or with the priority (run ab-20261119-113229). Dropped |
| MoltenVK encodes command buffers early (prefill style 1 and 2) | `MVK_CONFIG_PREFILL_METAL_COMMAND_BUFFERS` | No change (run ab-20261119-114059). Style 1 is the setting of one of the two boots with the canopy shards of KNOWN-ISSUES KI-29. Dropped |
| Fence flushes held back 0, 100, 1000 or 2000 us (pinned: 500 us) | `EDEN_NX2_FENCE_FLUSH_US` | No change. 1000 and 2000 us: 19.4 / 22.9 / 28.0 and 19.4 / 23.4 / 29.1 ms against the control's 20.0 / 23.7 / 28.9 ms (run ab-20261119-120851). 0 and 100 us: walk p50 / p95 / p99 20.0 / 23.6 / 28.9 and 19.9 / 23.4 / 31.0 ms against 19.6-19.9 / 22.9-23.1 / 28.2-29.0 ms (run ab-20261119-114059). Dropped |
| MoltenVK submits from its own queue thread | `MVK_CONFIG_SYNCHRONOUS_QUEUE_SUBMITS=0` | No gain at p50 or p95 (19.7 / 25.1 ms) in one walk, which was also a boot with the KI-29 corruption (run ab-20261119-120851). Dropped |
| The register allocator scans only the spill slots a block has used, slot helpers inline | `patches/experiments/dynarmic-arm64-regalloc-used-spills-2026-11-19.patch` | 8.6 % less compile time in the offline replay of the walk's 839,000 recorded compiles (50.2, 51.2 s against 46.7, 46.1 s; Release, asserts off). Too little to move p99; not run in the game |
| A macro read of report memory waits only for its own query reports (after Lichii PR 559) | `EDEN_NX2_QUERY_WAIT_REPORTS` | No change: 19.6 / 24.4 / 29.3 ms against the control's 20.3 / 24.8 / 29.2 ms. The wait it shortens happens fewer than 10 times a second here (its timer never reached 1,024 waits in a run). Dropped |
| A submission every 512 or 4,096 draws, not every 128 (the MoltenVK budget) | `EDEN_NX2_FLUSH_DRAWS` | Slower: 21.3 / 26.0 / 29.6 and 21.9 / 27.5 / 31.3 ms, with 19.6 and 18.8 submissions a frame against 27.6. Fewer submissions is not faster: an early submission lets the GPU work while the CPU records the rest. Dropped |
| Report fences not submitted at once; the fence thread gives the back 500 or 2,000 us before it asks | `EDEN_NX2_FENCE_LAZY_US` (with the query-wait switch) | No gain at 500 us (19.9 / 24.7 / 30.7 ms), slower at 2,000 us (21.9 / 26.9 / 31.1 ms). The 500 us boot was a KI-29 boot; two boots at 2,000 us were clean. Dropped |
| Full screen, which turns macOS Game Mode on | spec `"args": ["-f"]` | No difference on a quiet machine, three walks each way (run ab-20261119-104840). A full-screen run has no end picture |

Experiments are screened one walk each against one control; walk p99 varies by about 3 ms between identical runs,
so only a p99 under about 26 ms is repeated.

## What is not known

- What holds the GPU between two passes of a stalled command buffer, and what stops the emulator's core threads
  together (causes 2 and 3). macOS's always-on Metal record (`metalperftrace collect`) is per second and per program
  and cannot show it; `powermetrics --show-process-gpu` reads 0.00 for every program on macOS 27; Instruments' Metal
  System Trace would, and Xcode is not installed on this machine.
- How much of causes 2 and 3 is left after a restart with nothing else open.
- Which of the query reports behind the fence waits the game needs in the same frame.
- How the tail behaves on a busy machine with Game Mode on or the other programs demoted (`taskpolicy -b`).

## Files

| File | What |
| --- | --- |
| `build-test-app.sh` | Links a test app from the pinned build trees without touching them (`build/p99probe/app/lichii.app`, its own bundle id): the pinned app with the experiment patches named in the script, from `patches/experiments/` |
| `specs/test-app.json`, `specs/test-app-quiet.json` | The test app's runs in a private data root (`python3 tools/harness/ab.py --make-home build/p99probe/home --with-shader-cache`): per-encoder timing of long command buffers, and the per-frame thread report |
| `specs/follow-ups.json` | The runs that ruled causes out: the sync trace alone, harness calls every 120 frames, the profiler with the texture cache trace, the file-read trace |
| (screens 1 and 2) | Runs ab-20261119-120851 and ab-20261119-133259; their specs were not kept. The per-frame trace files of the dropped experiments' runs were deleted on 2026-11-19; results, frame times, logs and pictures remain |
| `specs/shard-hunt.json` | Twenty watched boots looking for the canopy shards of KNOWN-ISSUES KI-29 (run beside `tools/speckcheck/shotwatch.py --on-bad`) |

## Next

1. Screen `EDEN_NX2_SYNC_PAYLOAD_RELEASE` (after Lichii PR 1099, `patches/experiments/lichii-sync-payload-release-2026-11-19.patch`,
   in the test app): fence-flagged payload releases are not delayed at low accuracy. The walk makes about 740 of
   them a second (run ab-20261119-120851 query-reports: 74,154 of type 0 with the fence flag), each a fence that is
   never skipped. Look at the pictures: the delay it removes was added upstream against white flashes.
2. Record a Metal System Trace of one walk (needs Xcode) to see what runs on the GPU in the gaps.
4. Removing the compiles altogether needs a code cache kept across boots or the Hypervisor backend; a faster
   compiler does not reach p99 (the two JIT rows above).
3. Repeat the closed-programs walks after a restart with nothing else open, for the floor of causes 2 and 3.
