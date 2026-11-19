# Why the Hypervisor backend renders wrong: offline checks

Lichii's Hypervisor CPU backend (`cpu_backend = Hvf`) draws broken frames in motion (a dark band, a missing HUD).
These checks were done on 2026-11-17 without running the emulator, from the source in
`build/old-trees/path-60/lichii` and the logs of earlier runs.

**Status (2026-11-18 00:45): not finished.** The dark band and missing HUD are explained and fixed (section 2 to
4). With the speed patches Hypervisor is faster than the JIT and has no walk hitch (section 5). But about one
Hypervisor boot in twelve still comes up with a corrupted picture, blown out or covered in rainbow shards; a likely
cause is found and a fix is written but **not run** (section 6). Do not make Hypervisor the default before
section 6 is settled.

## 1. The store interpreter is correct

When the game writes to a page the GPU caches, the backend does not let the write through. It runs the one
instruction in software (`InterpretAccess` in `src/core/arm/hvf/arm_hvf.cpp`), so the GPU's caches hear about it.
About 380,000 stores a second go this way. A wrong byte or a wrong length here would corrupt buffers constantly.

**Test:** `wip/hypervisor/scripts/hvf-interp-test/` runs each instruction twice from the same random registers and memory: once
on the Mac's own CPU, once through the interpreter. Registers and memory must match afterwards.

- The general loads and stores run through the emulator's own built object (`interpreter_visitor.cpp.o`).
- `DC ZVA` and the single-element `ST1`/`LD1` sit inside `arm_hvf.cpp` between Hypervisor.framework calls. The test
  runs a copy of that code, so it must be kept in step with the source.

**Result:** no mismatch in 8 million random instructions (seeds 3 and 4). Most random encodings are not loads or
stores the interpreter takes, or point outside the test memory, so the number actually compared is smaller:

| Kind | Compared against the CPU | Mismatches |
| --- | --- | --- |
| General loads and stores (pairs, immediate, register offset, SIMD) | 890,463 | 0 |
| `ST1`/`LD1` of one vector element | 110,419 | 0 |
| `DC ZVA` | 262,577 | 0 |

Thin coverage: the acquire/release forms (`STLR`, `LDAR`) were compared only about 50 times, and loads from a
literal not at all.

Two kinds of instruction are run by the interpreter but fault on a real CPU. Neither matters for rendering, since
compiled game code does not contain them:

- A load or store that writes back into its own base register (unpredictable; Apple's CPUs raise an undefined
  instruction).
- An acquire/release load or store at a misaligned address (a real CPU raises an alignment fault).

To run it again:

```bash
LICHII=build/old-trees/path-60/lichii wip/hypervisor/scripts/hvf-interp-test/run.sh 4000000 1
```

The arguments are the number of instructions and the random seed.

## 2. Likely cause: a fault that lands while a region is being cached

### How a page becomes cached

The GPU thread calls `RasterizerMarkRegionCached(cached = true)` in `src/core/memory.cpp`. It does two things, in
this order:

1. **Protects** the region (`HostProtect`): the guest's pages become read-only, and every vCPU is kicked out of the
   guest to flush its TLB.
2. **Marks** each page's type as `RasterizerCachedMemory` in the emulator's page table, one page at a time.

The GPU side holds its own range lock (`counter_guard`) for this. The CPU fault handler does not take that lock.

### What the fault handler does in between

`ArmHvf::HandleDataAbort` has a branch for a page that is protected but **not** marked as cached
(`arm_hvf.cpp:612`). It assumes the protection is a leftover, gives the page the kernel's permissions back
(read and write) and retries the instruction. The leftover case is real: a read trap disarmed just after its page
left the cache.

A write fault between steps 1 and 2 takes the same branch:

| Step | GPU thread | vCPU |
| --- | --- | --- |
| 1 | Protects the region; kicks the vCPU out to flush its TLB | In the middle of a `memset` or `memcpy` over that region |
| 2 | Still waiting for the other vCPUs to flush | Re-enters, the next store faults |
| 3 | | Handler: page is protected, type is still plain memory, so it makes the page writable again |
| 4 | Marks the page as cached | Keeps writing, with no faults |

After step 4 the page is cached and writable. The GPU's caches never hear of any later write to it, until the
page leaves the cache and is cached again. A buffer the game rewrites every frame would keep its old contents on
the GPU side. That fits a HUD that goes missing and a band that stays dark.

The window is not narrow. Step 1 itself throws every vCPU out of the guest, and the vCPU that was writing the
region is the one most likely to fault on it straight after.

### Why the JIT does not have this

With the JIT, a fault in the same window goes to the slow write path, which writes the bytes and leaves the host
protection alone. The next write faults again, finds the page marked, and the caches are told. At most the writes
inside the window go untracked.

### What the earlier logs say

Run `tools/harness/runs/ab-20261117-160732/hvf-stats` (in the main checkout) printed the exit counters every
10 s. In each period a few write faults were neither interpreted nor turned into an invalidation:

| Period | Write faults / s | Interpreted / s | Difference / s |
| --- | --- | --- | --- |
| 3 | 375,629 | 375,627 | 2 |
| 4 | 386,005 | 386,003 | 2 |
| 5 | 382,260 | 382,257 | 3 |
| 6 | 383,442 | 383,441 | 1 |
| 7 | 393,943 | 393,942 | 1 |

The rates are whole numbers per second over 10 s, so a difference of 1 to 3 means roughly 10 to 35 faults per
period. A write fault that is counted as neither took this branch or was an access to unmapped memory, and the
log has no error or warning from the backend, which an unmapped access would print. So the branch fires a few
times a second. The counters cannot tell the leftover case from the race. That is what patch 1 is for.

## 3. The two patches (run on 2026-11-17, results below)

Both apply cleanly to the current source and compile. `wip/hypervisor/scripts/build-apps.sh` builds three apps from
them without changing the shared source or its build tree: it compiles copies of the two patched files, puts them
into a copy of `libcore.a` and links again. The apps are `path-60/app-hvfrace-base` (unpatched reference),
`app-hvfrace-diag` (patch 1) and `app-hvfrace-fix` (both). The runs below are in `wip/hypervisor/specs/hvfrace.json`,
queued behind the emulator lock on 2026-11-17.

- **`01-count-dropped-protection.patch`** (diagnostic). After the branch makes a page writable, it reads the page
  type again and logs a warning when the page is cached. Any such line in the log is the race happening.
- **`02-mark-before-protect.patch`** (fix to try). When a region becomes cached, mark the pages first and protect
  them second. A fault on a protected page then always finds it marked. It changes shared code in `memory.cpp`, so
  the JIT must be re-checked with it too.

A narrower race remains with patch 2: the handler reads the type of a page with a real leftover protection just
before the GPU thread caches that same page. Patch 1 would log it if it happens.

### Results (2026-11-17, `tools/harness/runs/ab-20261117-203916` in the main checkout)

Both Hypervisor runs ran while other builds were compiling (load average 50 to 85), so their frame times mean
nothing. All apps carried the PR 2901 MoltenVK (`app-mvkp2901`), because the practice library booted cold.

| Run | Race warnings | Protection given back in total | Write faults not interpreted |
| --- | --- | --- | --- |
| `hvfrace-diag` (patch 1) | 25 (22 writes, 3 reads) | 104 | 1 to 5 a second |
| `hvfrace-fix` (patches 1 and 2) | 0 | not logged without a warning | 0 to 1 a second |

- **The race is real.** In about two and a half minutes the handler gave write access back on a page that was
  GPU-cached 25 times. The stores came from four places: `0x873ffdec` (9), `0x81d36f98` (6), `0x873fff00` (3) and
  `0x81d36ec4` (3), with `main` at `0x80a66000`.
- **Marking before protecting removes it** in this run: no warning, and every write fault was interpreted.
- **Picture:** the owner watched both. One run still had visual bugs, fewer than before (the watches panel at the
  bottom left jumped about); the other had no obvious errors. Which run was which is to be confirmed.

### Frame rate with the fix and the speed patches (`tools/harness/runs/ab-20261117-204540`)

`app-hvfrace-fast` is the render fix plus the speed experiments of 2026-11-17
(`patches/experiments/hvf-experiments-2026-11-17.patch`). Frame times in ms, Kokiri Forest spawn, one run
each, after the other session's builds had ended (one-minute load average 9 to 16, still falling).

| Run | Backend and switches | Walk p50 / p95 / max | Stand p50 / p95 / max | Spawn after |
| --- | --- | --- | --- | --- |
| `hvffast-jit` | JIT, unpatched | 22.4 / 43.1 / 650 | 18.4 / 24.8 / 50.1 | 42.9 s |
| `hvffast-jit-fix` | JIT, render fix | 21.6 / 34.4 / 124 | 18.0 / 22.6 / 43.1 | 78.3 s |
| `hvffast-plain` | Hypervisor, render fix | 25.7 / 28.8 / 32.2 | 24.2 / 28.9 / 40.2 | 18.8 s |
| `hvffast-loop` | Hypervisor, render fix, `EDEN_NX2_HVF_LOOP=256`, `EDEN_NX2_HVF_DIRTY_ONLY=1` | 17.5 / 19.4 / 21.7 | 16.7 / 18.1 / 20.0 | 19.8 s |
| `hvffast-burst` | Hypervisor, render fix, `EDEN_NX2_HVF_BURST=32`, `EDEN_NX2_HVF_DIRTY_ONLY=1` | 18.6 / 20.7 / 22.4 | 16.9 / 20.0 / 26.5 | 18.8 s |

- **The loop runner is the fastest setting**, ahead of the JIT in both phases: the 60 fps cap standing, 57 fps
  walking against 45.
- **No walk hitch.** The JIT's 650 ms frame is its code-cache flush; Hypervisor's worst walk frame was 21.7 ms.
- **The render fix costs the JIT nothing** in frame time. Its run booted slowly (52.8 s against 16.5 s); the cause
  was not looked at.
- All three Hypervisor runs logged no race warning and no backend error. The owner watched the JIT reference, the
  plain run and the burst run and called each fine.
- The values 256 and 32 are first picks, not tuned.

### Emulator runs that would settle it

| # | Build | Run | Expected if the theory holds |
| --- | --- | --- | --- |
| 1 | Patch 1 only | Plain Hypervisor, Kokiri spawn, walk | Warnings in the log, and the usual broken frames |
| 2 | Patches 1 and 2 | Same | No warnings (or very few) and a correct picture |
| 3 | Patch 2 only | Default JIT, same spot | Frame times and picture unchanged |

## 4. Other things read and found sound

- **TLB shootdown** (`hvf_vm.cpp`, `RunThread`): a page that loses access is flushed on every vCPU before
  `Protect` returns. The generation counter and the `in_guest` flag cover the case of a vCPU entering the guest
  while the flush is requested.
- **Same notification path as the JIT:** interpreted stores reach `WriteToRasterizer` through `WriteBlock` and
  `ZeroBlock`, the same function the JIT's slow path reaches through `Write<T>`.

Not checked: whether macOS keeps a vCPU's TLB entries when its thread moves to another physical core. The flush
stub uses `TLBI VMALLE1`, which acts on the current core only.

## 5. The finished patch and what it measures (2026-11-17 night)

`03-hvf-final.patch` is one patch against the pristine path-60 Lichii source (three files). It is generated by
`wip/hypervisor/scripts/make-final.py` from the speed experiments of 2026-11-17
(`patches/experiments/hvf-experiments-2026-11-17.patch`) and patches 1 and 2 above, plus:

- **The remaining race closed.** A region's pages are marked before they are protected
  (`Memory::Impl::ProtectForCaching`), and after the fault handler gives a page its kernel permissions back it calls
  `Memory::ReprotectIfCached`. Every order of the two threads then ends with a cached page protected. The log line
  "became GPU-cached while its protection was being lifted" counts the cases; it did not fire in 40 boots.
- **Speed switches on by default** under the Hypervisor backend: loop runner 256 (`EDEN_NX2_HVF_LOOP`), dirty-only
  write-back (`EDEN_NX2_HVF_DIRTY_ONLY`). The loop runner keeps interpreting a fill or copy loop after a trapped
  store, up to that many instructions, instead of one trap per store.
- **Opt-in, not verified:** `EDEN_NX2_HVF_INTERPRET_READS=1` (section 6).

`wip/hypervisor/scripts/build-final.sh BUILD NAME` builds an app from it without touching the shared source: it compiles
the two patched `.cpp` files with that build tree's flags, puts them into a copy of its `libcore.a` and links again.
`path-60/app-hvf-final` (from `build/release`) is the one app left on disk; the ThinLTO variant
(`build/release-lto`, a 4.6-minute link) and the earlier test apps were deleted and can be rebuilt.

**A bug I made and fixed on the way:** the first version of `ProtectForCaching` was called after a loop that had
advanced the region's address, so it protected the memory after the region. The boot hung with "Invalid write of
0xe401". The start address is now kept in a constant.

### Tuning batch (`tools/harness/runs/ab-20261118-000958`, Kokiri spawn, 300-frame walk, two runs each)

All apps carried the MoltenVK with PR 2901 and the mesh cull-mode fix (sha1 `17f76f69f2`). Load average 7 to 11
throughout, so the numbers are comparable with each other, not absolute. Frame times in ms.

| Configuration | Walk p50 | Stand p50 | Worst walk frame | Spawn after |
| --- | --- | --- | --- | --- |
| JIT (unpatched `build/release`) | 22.9 / 21.8 | 18.9 / 18.2 | 653 / 452 | 44.2 s |
| Hypervisor, defaults | 17.5 / 18.0 | 16.7 / 16.7 | 34 / 27 | 20.0 s |
| Loop runner off | 23.4 / 23.9 | 21.6 / 22.4 | 29 / 44 | 19.1 s |
| Loop runner 64 / 1024 / 4096 | 17.4–17.8 | 16.6–16.7 | 20–35 | 20.0 s |
| Burst 32, loop runner off | 17.8 / 17.3 | 16.6 / 16.5 | 24 / 34 | 20.0 s |
| Dirty-only off | 17.5 / 17.4 | 16.6 / 16.6 | 29 / 21 | 20.0 s |

- The loop runner is worth about 6 ms a frame; its limit makes no difference between 64 and 4096; burst 32 does as
  well. Dirty-only write-back makes no measurable difference.
- With the loop runner, write traps are about 120,000 a second, all interpreted. System calls (about 160,000 a
  second) are now the largest source of exits.
- No Hypervisor run logged a backend error, an invalid access or a store the interpreter could not handle.
- The first boot of an app after a MoltenVK change recompiles shaders once (57 to 71 s).

Not done: the ThinLTO Hypervisor app against the best JIT app; a 5-minute walk in Kokiri Forest and Gerudo Valley
(spec `wip/hypervisor/specs/walk5.json`, with the new `leash_m` walk option, never run); any map change.

## 6. Open: a corrupted picture in about one Hypervisor boot in twelve

**Seen:** `fin-default-r2` (`tools/harness/runs/ab-20261118-000958`): rainbow-coloured shards over the foliage.
`shards-hvf-r9` (`tools/harness/runs/ab-20261118-002819`): the whole scene blown out to white and pink. Both were wrong for the
whole run; the boots before and after were fine; their logs are identical to clean runs'.

**Counts** (every Kokiri run picture of 2026-11-17 and -18, scored by `wip/hypervisor/scripts/persist.py`
`picture_metrics`): Hypervisor after the MoltenVK swap 2 of 26; JIT after the swap 0 of 15; Hypervisor before the
swap 0 of 9, which at this rate is close to a coin flip and clears nothing.

**The same picture is documented for one other case:** the JIT with reactive flushing off
(`EDEN_NX2_NO_REACTIVE=1`, `research/emulator-options/README.md`: "blown out (white bloom, rainbow colours)").
Reactive flushing is what makes a CPU read of GPU-written memory fetch the GPU's data first.

**Suspected cause, from the code, not confirmed by a run:** with reactive flushing on (the default) a GPU-cached
page has no read permission, and read traps, which re-arm when the GPU writes, are off
(`Memory::Impl::ReadTrapsEnabled`). The JIT sends every such read through its slow path for good. The Hypervisor
fault handler (`ArmHvf::HandleDataAbort`, the `!write` branch) does one slow-path read and then calls
`GrantCachedPageRead`, which makes the page readable. Nothing takes that permission away again while the page stays
cached, so later reads of it see the guest copy without asking the GPU: reactive flushing stops working for that
page after its first read. A stale read-back (exposure, culling results) would give exactly these pictures, and
whether a boot is hit depends on timing.

**The fix that is written but not run:** with `EDEN_NX2_HVF_INTERPRET_READS=1` the handler interprets each load
from a GPU-cached page through the emulator's memory (as it already does for stores) instead of opening the page.
The exit statistics then also print how many read faults were interpreted.

**How to settle it, in this order:**

1. Count the dangerous event instead of waiting for a bad picture: a diagnostic that logs when the GPU writes into
   a page that `GrantCachedPageRead` opened. Zero in every boot means this explanation is wrong.
2. Force it: Hypervisor with the old behaviour, the JIT with `EDEN_NX2_NO_REACTIVE=1` (known bad) and Hypervisor
   with `EDEN_NX2_HVF_INTERPRET_READS=1`, same spot, pictures compared.
3. Measure the cost of interpreting every read (`wip/hypervisor/specs/read-path.json`), since each one becomes a trap.
4. Only then repetition: thirty boots of the fixed build (`wip/hypervisor/specs/shards-rate.json`), every picture scored.

**Catching the next one:** every harness run now writes `picture` (clipped and vivid shares, `corrupt`) into
`result.json`, and a spec's `on_corrupt` steps run only on a corrupted boot while the game is still up (a GPU trace
with `trace_record`, a `capture_frame` with buffers). No corrupted boot has been captured that way yet.

**Not excluded:** the shared MoltenVK (the corruption has only been seen after the swap to PR 2901 plus the cull
fix, and concurrent-compile libraries are known to produce the same picture on the JIT), and the loop runner
(its instruction emulation was read line by line and looks right, but only loads and stores were tested against
the CPU in `wip/hypervisor/scripts/hvf-interp-test`, not its add, compare and branch handling).
