# Shared JIT code cache on the Mac backend (2026-11-17/18, in the pinned build)

Lichii's shared JIT code cache ([zortos293/Lichii#2101](https://github.com/zortos293/Lichii/pull/2101), x86-64 only)
ported to dynarmic's arm64 backend, which Lichii uses on Apple silicon. The six guest cores compile each block once
into one cache instead of once each into six private 128 MiB caches, and that cache can be larger than 128 MiB.

**State:** in the pinned build since 2026-11-18, switched on with `EDEN_NX2_SHARED_JIT_CACHE=512` in the app's
`Contents/MacOS/nx2_switches.txt` (from [`config/nx2_switches.append.txt`](../../config/README.md)). Deleting that
line returns to private caches without a rebuild. Measured on an Apple M4 Pro (Mac16,8) under macOS 27.0.1, Kokiri
Forest, 1x, handheld. Run folders named `ab-<date>-<time>` are local run data and are not tracked.

| Where | What |
| --- | --- |
| `patches/lichii/0008-dynarmic-arm64-one-A64-code-cache-shared-by-a-proces.patch` | The port as it is in the pinned build, with the review fixes |
| `patches/lichii/0007-core-JIT-invalidation-entry-points-for-the-debug-too.patch` | The System-level JIT invalidation calls the port needs, and the debug server's `jit_clear` |
| `patches/upstream/dynarmic-pr2101-tree-shared-jit-cache-with-tests.patch` | The same work against the PR #2101 tree (`72ff982a3`), with the tests and the JIT replay test |
| [`tools/jit-cache/`](../../tools/jit-cache/README.md) | Tools and run specs |

## Why the Mac needs more than the PR

The PR makes the x86-64 emitter stop baking per-core values into code and puts a lock around one shared block map.
The arm64 backend needs that and three more things:

1. **A cache over 128 MiB.** An arm64 direct branch reaches ±128 MiB, so the backend asserted the cache was no larger.
   One shared 128 MiB cache would fill sooner than six private ones, so sharing only helps with a larger cache.
2. **Links that can change while another core runs them.** The backend patched a two-instruction `ADRL` for
   return-stack pointers, which another core could run half-written.
3. **A lock-free block lookup.** The arm64 backend has no fast dispatch table; every unpredicted indirect branch calls
   the C++ lookup, which with one shared map would take the cache's lock on every core.

## How it works

- **Per-core values from the JIT state.** `A64JitState` holds the callbacks, config, address space and `TPIDR_EL0` /
  `TPIDRRO_EL0` pointers; the prelude's trampolines, the dispatcher and the TPIDR instructions load them through the
  state register (`X28`), so the same code serves any core.
- **One cache, one lock.** `SharedCodeCache` (`a64_interface.cpp`): lookups take the `shared_mutex` shared; emitting,
  invalidating and the fastmem fault handler take it exclusively. A block is translated without the lock and again if
  an invalidation arrived meanwhile. Range invalidations are queued and applied by each core on its next JIT entry. A
  full clear with more than one core attached halts all cores and waits until none runs JIT code (per-core flags).
- **Lock-free lookups.** Each core has a private 8,192-entry table checked before the lock, and the block map itself is
  readable without the lock (`block_table.h`). Each slot carries a drop count, so a dropped block is looked up again.
- **Fastmem faults don't halt everyone.** A fault re-marks its access and drops only the affected block; real code
  invalidations still halt all cores. A first version with a "drop only if still current" check skipped re-marking
  later faulting accesses and caused a storm of stale faults (745 k private and 594 k shared faults in already
  replaced code); the current handling fixes that.
- **Single-store links.** A block link is one instruction (`B target` or `NOP`) written with one aligned 32-bit store
  (allowed while another core executes it, Arm ARM B2.2.5), then its icache line invalidated. The return stack's code
  pointer is an 8-byte literal after the block. A new block's icache is invalidated before anything links to it.
  `MAP_JIT` write permission is per thread, so one core can write while others execute.
- **Regions and veneers.** The cache is a row of 128 MiB regions, each with its own prelude copy. A link further than
  128 MiB goes through a per-region veneer (`LDR X16, literal; BR X16`); with no room left the link stays unlinked
  (counted in `far_link_veneers` / `unlinked_far_links`). Sizes are rounded down to whole regions (a 129–255 MiB
  setting crashed before that fix, see the review).
- **Lichii side.** `KProcess` creates the shared cache; `ArmDynarmic64::MakeJit` uses it when
  `EDEN_NX2_SHARED_JIT_CACHE=<MiB>` is set (128–2048), not with Paranoid accuracy or a debugger attached. Without the
  variable, each core gets a private cache through the same code path.
- **Diagnostics.** Whole-load counters (lock waits by kind, discarded translations, concurrent compiles, lookup hits,
  fault-handler time; `tools/jit-cache/jit_totals.py`), every-frame stutter trace (`EDEN_NX2_STUTTER_ALL_FRAMES=1`,
  `frame_split.py`), and an operation recorder (`DYNARMIC_JIT_TRACE=<file>`) whose traces replay offline
  (`DYNARMIC_JIT_REPLAY=<trace> ./dynarmic_tests "[jit_replay]"`, test source `tests/A64/jit_cache_replay.cpp` in the
  PR #2101 tree).

## Tests (in the PR #2101 tree, build folders `build/jit` and `build/tsan`)

- `dynarmic_tests`: 146 cases pass (2 new), also with 2 and 4 MiB test regions (`DYNARMIC_ARM64_REGION_SIZE`).
- `jit_shared_cache_tests` (the PR's test, now on arm64) plus new cases: cores on one cache with an invalidating,
  clearing writer; veneers across regions; fastmem faults in each other's blocks (≥12,000 recompiles); hidden
  `[jit_large_cache]` (384 MiB, 322 MiB of code over three regions, 16 veneers). All pass; ThreadSanitizer: 0 reports
  (it sees the C++ side only, not emitted code). The tests caught one real race (a block visible before fully linked),
  fixed. The game build's dynarmic files equal the tested ones except two test-only debug hooks.

How to build and run them: [`tools/jit-cache`](../../tools/jit-cache/README.md).

## Measurements

### Development batches

Specs in `tools/jit-cache/specs/`, Kokiri walk; control = switch off:

| Batch | Result |
| --- | --- |
| `sharedjit` | Blocks per load 2.15–2.38 M → 0.60–0.64 M; compile 28–32 s → 11 s; cache use 211–231 MiB, 2,000–3,000 veneers, 0 unlinked far links; control had a 625 ms full-clear hitch |
| `sharedjit3`–`5` | Walk p95 37–39 → 25–28 ms, max 444–468 → 55–64 ms, frames over 50 ms 13–19 → 1–2; lock waits per load: lookup 7.0–7.3 s, emit 2.8–3.5 s, fault handler 5.0–5.5 s (summed over cores) |
| `sharedjit6` (lock-free lookups) | Lookup wait 7 s → 0, emit wait → 4.6–4.8 s; net waiting ~15.5 → ~10 s per load; save load 17.2 → 16.7 s (noise); walk p95 35.5–36.9 → 25.4–26.1 ms |

"Save load" in these batches and the harness's "load − boot" below measure different spans, so their seconds are
not comparable.

Per frame while walking (`sharedjit6`, core time summed over six cores): a median frame is ~99 % non-JIT work with the
shared cache (guest code and callbacks ~64 ms, GPU back/front/worker threads 9–13 ms each); compiling is 3.0 → 0.5 ms
at p50 and 84.5 → 11.6 ms at p99. Slow frames are compile frames.

### Validation before adoption

Spec `tools/harness/specs/merge-sharedjit.json`, run ab-20261118-014956, per-run results in
[`tools/harness/merge-sharedjit.log`](../../tools/harness/merge-sharedjit.log). A candidate with only the JIT change
(16 files of the port; speck diagnostics left out), same MoltenVK library in every app, harness walk with turns,
three runs each:

| | Installed build, without the port | Candidate, switch off | Candidate, shared 512 MiB |
| --- | --- | --- | --- |
| Kokiri walk hitches | 3 of 3 | 1 of 3 | **0 of 3** |
| Walk p95 | 46.1–51.4 ms | 34.6–47.4 ms | **28.1–30.1 ms** |
| Worst walk frame | 312–645 ms | 61–467 ms | **51–60 ms** |
| Map load (load − boot) | 26.1–26.6 s | 23.8–24.9 s | **21.8–23.6 s** |
| Memory footprint | 23.5 GB | 23.5–25.6 GB | **20.5 GB** |
| Standing p50 | 18.7–20.7 ms | 18.6–18.8 ms | 18.5–18.9 ms |

Gerudo Valley, one run each: walk p90 23.8 → 19.7 ms, memory 24.6 → 20.5 GB. Cold Metal cache boot 97.4 s (as with
#2901 alone). Long run (3,600-frame phases): 202 m walked, 12 turns, no full flush, worst frame 52 ms. No blown-out
frames anywhere.

**Code review** (independent reviewer, read-only): no race found in the locking, lock-free lookups, clear handshake,
code publishing / link patching, fastmem handler lock order, stale-translation retry, A32 path, or the switch-off
path. Findings:

1. Sizes 129–255 MiB crashed once code passed 128 MiB (a region larger than a branch's reach): **fixed** (round down
   to multiples of 128).
2. A core waiting for a full clear spun with `yield()` and ignored pause/shutdown halts. **Fixed:** it returns to
   Lichii when asked to halt for any other reason and sleeps in 0.1 ms steps; a test holds one core in a slow callback
   with a clear pending and requires the other to answer a halt within 3 s.
3. Each guest invalidation was queued once per core (6×), halting all cores 6×. **Fixed:** a repeat of a request still
   queued, or of the last one with nothing compiled since, no longer queues or halts. Every request still makes
   in-flight translations retry (dropping that would let code patched twice in a row leave a stale block).

Both fixes are in the pinned build (installed 2026-11-18 02:31). Validation: spec
`tools/jit-cache/specs/jit-review-fixes.json`, run ab-20261118-023158: no regression against the build without the
fixes, full clears still work with a 128 MiB cache; the fixes themselves are proven by the offline tests (146
dynarmic and 6 shared-cache tests, ThreadSanitizer clean on three runs).

## Open work

- Emit contention: ~10 s of emit and fault-handler waiting per load. Idea: per-core emit regions.
- Persisting faulting accesses across boots: ~310 k recompiles per load, a third of compiles; needs module-relative
  offsets because of ASLR; stability across boots unknown.
- Untested in the real kernel: thread migration, the debugger path, process teardown.
- Far-link counters are not in the stutter line; `jit_cache_mib` reports the shared cache once per core (6× too high).
- The default size, removing the switch, and offering the port upstream on top of PR #2101 (Lichii issue #2180 has
  a reply asking for a draft diff) are open.
