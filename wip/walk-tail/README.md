# Walk tail: why walking frames at p95 and p99 are slow

Unfinished. Question: what makes the slow frames of a walk in the pinned build, and which of them the emulator can
remove. State on 2026-11-19: the p95 frames are ordinary frames with more work in them; the p99 frames have three
causes, two of which are mostly this Mac's other programs and not the emulator. The root cause of the third and the
part of the second that remains on a quiet machine are open.

Measured on the pinned build (Lichii `a1ee50a6ef`, MoltenVK `dc964d4011`) and on a test app made from it, Apple M4
Pro, macOS 27.0.1, 1,800-frame walks kept within 9 m of the Kokiri Forest spawn (`"leash_m": 9`), 1x, handheld.
Run folders named `ab-…` are local run data and are not tracked. Readers: [`tools/diag`](../../tools/diag/README.md).

## What is known

| Frames | Cause | Evidence |
| --- | --- | --- |
| p95 (22-26 ms) | Frames with more commands in them, not hitches: 46 command buffers against 40, about 10 % more encoders. 62-69 % of their excess over a normal frame is GPU idle between hand-offs, the rest more GPU work. JIT compile time is 0.3 ms in them, as in a median frame | `gpu.py frames` on run ab-20261119-090328 (walkcap-gpu-r1/r2); `stutter.py split` on run ab-20261119-090845 |
| p99, cause 1 | JIT first-touch compiles: 340-2,008 blocks and 7-39 ms of compile time in the frame. They fall on the same frame numbers of a repeated route (3, 17 or 20, 184, 447, 464), and a new movement brings new ones | `gpu.py sync` on runs ab-20261119-093044, -095225 |
| p99, cause 2 | A GPU command buffer that occupies the GPU for 8-21 ms with 0.1-3 ms of pass work in it. The time is one gap between two consecutive encoders: 14 of 26 after one compute pass and before the 16384x16384 pass (8.5-9.5 ms each), the rest after a blit and before the next render pass. Up to five guest threads then wait 6-10 ms each for a read download | per-encoder records of the test app, run ab-20261119-094316 (probe-encoders-r1) |
| p99, cause 3 | The next frame's commands arrive 9-23 ms late with the GPU idle. In those frames the game runs no more code than usual, and several of its worker threads, each pinned to one core, are ready without a core for about 10 ms or about 20 ms at the same time while the cores are mostly idle | `gpu.py slow`; per-frame thread reports of the test app, run ab-20261119-094316 (probe-threads-r1) |

Per walk, with other programs open (7 walks) against closed (5 walks, run ab-20261119-095225; Claude's own app
still running):

| | Open | Closed |
| --- | --- | --- |
| GPU waits of 8 ms or more | 21-58 | 4, 7, 19, 9, 9 |
| Read-wait frames (cause 2) | 5-14 | 1, 0, 4, 3, 2 |
| Silent-gap frames (cause 3) | 9-17 | 8, 4, 4, 2, 7 |
| JIT compile frames (cause 1) | 5-13 | 14, 7, 10, 8, 7 |
| p99 | 29.4-33.0 ms | 28.8, 26.9, 28.3, 27.3, 28.0 ms |

The median does not move (19.3-19.7 ms closed). The first closed walk began seconds after the programs were closed.

Ruled out, each by a run: the frame profiler as the cause of the stalls (they occur with the sync trace alone); the
harness's debug-server calls (17 silent-gap frames with a call every 120 frames against 9 and 15 with one every 30);
texture cache churn (events are five times sparser around a stalled command buffer); guest file reads (none over
1 ms); late timers and slow core wake-ups (p99 under 0.1 ms and 20 us).

## What is not known

- What holds the GPU between two passes of a stalled command buffer. macOS's always-on Metal record
  (`metalperftrace collect`) is per second and per program and cannot show it; Instruments' Metal System Trace would,
  and Xcode is not installed on this machine.
- What stops the emulator's core threads together for about 10 or 20 ms (cause 3). A macOS scheduler time slice is
  10 ms; nothing here shows that it is the cause.
- How much of causes 2 and 3 is left with no other program at all using the GPU.
- Whether any of this holds outside Kokiri Forest.

## Files

| File | What |
| --- | --- |
| `build-test-app.sh` | Links a test app from the pinned build trees without touching them (`build/p99probe/app/lichii.app`, its own bundle id): the pinned app with the two experiment patches `patches/experiments/moltenvk-frameprof-dump-long-buffers-2026-11-19.patch` and `patches/experiments/lichii-thread-stats-slow-frames-2026-11-19.patch` |
| `specs/test-app.json`, `specs/test-app-quiet.json` | The test app's runs in a private data root (`python3 tools/harness/ab.py --make-home build/p99probe/home --with-shader-cache`): per-encoder timing of long command buffers, and the per-frame thread report |
| `specs/follow-ups.json` | The runs that ruled causes out: the sync trace alone, harness calls every 120 frames, the profiler with the texture cache trace, the file-read trace |
| `specs/shard-hunt.json` | Twenty watched boots looking for the canopy shards of KNOWN-ISSUES KI-29 (run beside `tools/speckcheck/shotwatch.py --on-bad`). Its run of 2026-11-19 found none: 20 boots clean (run ab-20261119-100116) |

## Next

1. Record a Metal System Trace of one walk (needs Xcode), or sample GPU use per program with `powermetrics` (needs
   `sudo`), to see what runs on the GPU in the gaps.
2. Repeat the closed-programs walks after a restart with nothing else open, for the floor of causes 2 and 3.
3. For cause 1, measure what compiling ahead of first use would remove: the block addresses of the route's compile
   frames are in a `DYNARMIC_JIT_TRACE` recording (run ab-20261119-090845, walkcap-jitrec; `tools/diag/jit.py trace`).
